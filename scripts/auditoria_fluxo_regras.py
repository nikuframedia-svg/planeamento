"""Regras da auditoria do fluxo de dados (08/10/2026): funções puras, sem base de dados nem rede.

Recalculam a partir da origem (Excel importado, folhas OCR validadas do MES, decisões da Carteira e Definições)
o que cada página devia mostrar, pelas regras em vigor e pelas decididas pelo Luís a 08/10:
- saldo: o OCR validado substitui o contador do Excel («Ser.» MTG2, «Maq.» MTG3) mesmo quando é menor; contador
  vazio conta 0 quando «Qtd falta» = QTD; a «Qtd em falta» escrita no registo manual manda;
- metros = saldo × comprimento ÷ 1000; peso MTG3 = kg/m da Tabela de pesos (valor único) ou, quando falta, a
  geometria da cantoneira t(a+b−t)·7850/10⁶; peso MTG2 = área × comprimento × 7850;
- horas (decisão 3 de 08/10) = volume ÷ velocidade do Excel da máquina efetiva ÷ eficiência da máquina; uma
  taxa «Confirmada» das Definições substitui o Excel; ×3 da Thomas quando QTD > 50; MTG2 pela coluna E/F
  (29/11/2024) da folha CapacidadeMáquinas (F quando preenchida, senão E);
- prazo: MTG3 Data Corte; MTG2 Picking (segunda às 08:00) → semana escolhida → Galvanização → Data Corte;
  «2026/53» na coluna W = estacionada (sem prazo). Semana de carga = semana ISO do prazo; antes da semana atual
  vai para a coluna Atrasado.
O script `auditoria_fluxo.py` lê a origem e as páginas e usa estas funções; os testes estão em
tests/test_auditoria_fluxo.py.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

LISBOA = ZoneInfo("Europe/Lisbon")
DENSIDADE_ACO = 7850  # kg/m³
ESTACIONADA = {"2026/53"}  # coluna W da Tabela MTG3: linha estacionada (S53-1)
SEMANAS_CARGA = 13
SEMANAS_VELOCIDADE = 8  # janela da velocidade «mais recente» do Excel (productivity.RECENT_WEEKS)
THOMAS_QTD = 50
COLUNA_SALDO_EXCEL = {"Ser.": "Qtd em Falta", "Maq.": "Qtd falta"}
CPIS_FECHADO = ("fechada", "fechado")
MACRO_FECHADO = ("x", "true", "1")
# Textos da coluna Máquina que querem dizer «sem máquina física» (machine_choice.PLACEHOLDERS).
SEM_MAQUINA = {"", "por definir", "sem máquina", "sem maquina", "mtg3", "subcontrato", "abocardar",
               "serrote mtg2", "serrote mtg3"}
TOLERANCIA_HORAS = 1 / 60  # 1 minuto por operação
TOLERANCIA_METROS = 0.01
TOLERANCIA_KG = 0.1

# Defeitos do desenho «dados» (07/10/2026) que podem explicar uma diferença.
DEFEITOS = {
    "F01": "Horas calculadas para a máquina da Tabela e não para a máquina efetiva.",
    "F02": "Política de taxas diferente (Histórico em vez do Excel, ×3 da Thomas, coluna C em vez da E/F).",
    "F03": "OCR abaixo do contador do Excel (decisão 2 de 08/10: o OCR continua a mandar; só conferir no MES).",
    "F04": "Camada v2 regrava o saldo de linhas fechadas ou sem coluna de falta.",
    "F05": "Camada v2 parada a 29/09 sobrepõe-se ao saldo principal.",
    "F06": "Linhas repetidas contam a dobrar, sem aviso.",
    "F07": "Associação MES errada ou em falta (produção acima da QTD, folha repetida).",
    "F08": "Linha MTG3 sem peso na Tabela de pesos (calculável pela geometria).",
    "F09": "Desconhecido mostrado como 0 (kg, metros, peças).",
    "F10": "Ordem por urgência com grupos de 0 m depois dos sem data.",
    "F11": "Picking (segunda 08:00) cai na própria semana na Carga.",
    "F12": "Trabalho Planeado atrasado não aparece como «no plano» na Carga.",
    "F13": "Cor da célula contradiz a recomendação.",
    "F14": "Nota «noutro setor» escondida (operações em máquinas de outro setor).",
    "F15": "`unplanned.planned_orders` mal nomeado.",
    "F16": "Excel mais recente no Drive por importar (SAIDA/).",
    "F17": "Grupo de operadores sem calendário bloqueia os serrotes do pav.1 no Gantt técnico.",
    "F18": "Capacidade do posto Fita pav.1 somada com as suas máquinas.",
    "F19": "Parsers de números diferentes.",
    "F20": "Edição na Tabela congela campos que deviam seguir o Excel.",
    "F21": "Peso da Carga e da Carteira de fontes diferentes; contagem de «sem peso» diferente.",
    "F22": "Problema na origem (OF com gralha, sem Data Corte, OCR mal lido).",
    "F24": "Dia de Berlim em vez do de Lisboa entre as 23:00 e as 24:00.",
    "F25": "Sugestões calculadas com linhas excluídas.",
    "F26": "Rótulos diferentes para «sem família».",
}
INEXPLICADO = "inexplicado"


# ---------------------------------------------------------------- números e textos

_MILHARES = re.compile(r"[+-]?\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?")


def numero(valor):
    """Um só leitor de números: 12, 12.5, «12,5», «1 200» (grupos de três completos). Inválido → None."""
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return float(valor) if math.isfinite(valor) else None
    texto = str(valor).strip()
    if _MILHARES.fullmatch(texto):
        texto = re.sub(r"[   ]", "", texto)
    try:
        n = float(texto.replace(",", "."))
    except ValueError:
        return None
    return n if math.isfinite(n) else None


def quantidade(valor):
    """Inteiro não negativo, ou None."""
    n = numero(valor)
    return n if n is not None and n >= 0 and n.is_integer() else None


def positivo(valor):
    n = numero(valor)
    return n if n is not None and n > 0 else None


def chave_texto(valor) -> str:
    """Chave de catálogo (planning_catalogs.key): espaços normalizados, minúsculas, «rectangular» → «retangular»."""
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    texto = re.sub(r"\s+", " ", str(valor).replace("_x000D_", " ")).strip()
    if texto.startswith(("#", "=")) or texto in ("-", "—"):
        return ""
    return texto.casefold().replace("rectangular", "retangular")


def chave_tecnica(valor) -> str:
    return re.sub(r"\s+", " ", str(valor or "").strip().upper())


def chave_perfil(valor) -> str:
    return re.sub(r"\s", "", str(valor or "")).upper()


def of_normalizada(valor) -> str | None:
    if isinstance(valor, (int, float)) and not isinstance(valor, bool) and float(valor).is_integer():
        valor = str(int(valor))
    found = re.fullmatch(r"\s*(?:OF[\s._-]*)?(\d{4,10})\s*", str(valor or ""), re.I)
    return "OF" + found[1] if found else None


def maquina_normalizada(nome) -> str:
    texto = str(nome or "").strip()
    return "" if texto.casefold() in SEM_MAQUINA else texto


def dia(valor) -> date | None:
    if valor in (None, ""):
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        return None


def semana_positiva(valor):
    n = numero(valor)
    return int(n) if n is not None and n.is_integer() and 1 <= n <= 53 else None


# ---------------------------------------------------------------- população e saldo

def ativa(estado_cpis, fechado_excel, closed_x=False) -> bool:
    """Linha ativa: o CPIS (cópia mais recente) não diz «Fechada» e o Excel não tem Fechado = X."""
    if str(estado_cpis or "").strip().lower() in CPIS_FECHADO:
        return False
    if closed_x is True:
        return False
    return str(fechado_excel if fechado_excel is not None else "").strip().lower() not in MACRO_FECHADO


def contador_excel(raw: dict, coluna: str, qtd):
    """Contador do Excel (planning_calculations.excel_counter): célula vazia = 0 quando a «falta» da folha = QTD.

    Devolve (valor | None, motivo). Coluna ausente ou texto inválido → desconhecido."""
    raw = raw or {}
    if coluna not in raw:
        return None, f"Coluna «{coluna}» ausente."
    valor = raw.get(coluna)
    if valor is None or str(valor).strip() == "":
        falta = quantidade(raw.get(COLUNA_SALDO_EXCEL[coluna]))
        if qtd is not None and falta is not None and falta == qtd:
            return 0.0, f"«{coluna}» vazio e «{COLUNA_SALDO_EXCEL[coluna]}» = QTD: conta 0."
        return None, f"«{coluna}» vazio e «{COLUNA_SALDO_EXCEL[coluna]}» diferente da QTD."
    n = quantidade(valor)
    return (n, None) if n is not None else (None, f"«{coluna}» inválido ({valor!r}).")


def saldo(qtd, contador=None, ocr=None, *, declarada=None, ocr_bloqueado=False) -> dict:
    """Saldo da operação principal pela regra da app (decisão 2 de 08/10: o OCR substitui o Excel, sem máximo).

    `ocr`: soma das quantidades OCR validadas associadas à operação (None = nenhuma); `ocr_bloqueado`: há
    registos mas por confirmar (operação, sobreposição) → o OCR não serve e vale o Excel. `declarada`: «Qtd em
    falta» escrita no registo manual (prevalece; o desconto da produção posterior não é reproduzido aqui)."""
    q = quantidade(qtd)
    usa_ocr = ocr is not None and not ocr_bloqueado
    if usa_ocr:
        produzido, fonte = float(ocr), "OCR"
    elif contador is not None:
        produzido, fonte = float(contador), "Excel"
    else:
        produzido, fonte = None, "indisponível"
    resultado = {"qtd": q, "produzido": produzido, "fonte": fonte, "ocr": ocr, "excel": contador,
                 "ocr_menor_excel": bool(usa_ocr and contador is not None and ocr < contador),
                 "diferenca_ocr_excel": (ocr - contador) if ocr is not None and contador is not None else None}
    if declarada is not None and q is not None:
        d = quantidade(declarada)
        if d is not None:
            resultado.update(saldo=min(d, q), fonte="Qtd em falta", excesso=0.0)
            return resultado
    if q is None or produzido is None:
        resultado.update(saldo=None, excesso=None)
    else:
        resultado.update(saldo=max(q - produzido, 0.0), excesso=max(produzido - q, 0.0))
    return resultado


def metros(saldo_pecas, comprimento_mm):
    if saldo_pecas == 0:
        return 0.0
    c = positivo(comprimento_mm)
    if saldo_pecas is None or c is None:
        return None
    return saldo_pecas * c / 1000


# ---------------------------------------------------------------- produção do MES (OCR validado)

def associar_registos(registos, linhas) -> dict:
    """Associação refeita dos registos MES às linhas, por OF (planning_hub._production_associations):
    a chave gravada no registo quando é deste retrato; senão referência + comprimento + perfil únicos na OF.

    `registos`: {id, of, quantidade, plan_key, ref, comprimento, perfil, plan_refs[], full_profile};
    `linhas`: {plan_key, of, ref, comprimento, perfil}. Devolve {id: {estado, linhas: [(plan_key, quantidade)],
    candidatas}}; estado ∈ explicit, technical_unique, ambiguous, unmatched, incomplete."""
    por_of = defaultdict(list)
    for linha in linhas:
        por_of[linha["of"]].append(linha)
    out = {}
    for r in registos:
        planos = por_of.get(r.get("of"), [])
        atuais = {p["plan_key"]: p for p in planos}
        if r.get("full_profile") and not r.get("plan_refs"):
            out[r["id"]] = {"estado": "incomplete", "linhas": [], "candidatas": []}
            continue
        sondas = r.get("plan_refs") or [{"plan_key": r.get("plan_key"), "component_ref": r.get("ref"),
                                         "length_mm": r.get("comprimento"), "profile_type": r.get("perfil"),
                                         "assumed_quantity": r.get("quantidade")}]
        resolvidas, candidatas, explicitas = [], set(), 0
        for s in sondas:
            if s.get("plan_key") in atuais:
                resolvidas.append((s["plan_key"], s.get("assumed_quantity")))
                explicitas += 1
                continue
            ref = chave_tecnica(s.get("component_ref"))
            achadas = [p for p in planos if ref and chave_tecnica(p.get("ref")) == ref]
            c = numero(s.get("length_mm"))
            if c is not None:
                achadas = [p for p in achadas if numero(p.get("comprimento")) is not None and abs(numero(p["comprimento"]) - c) < .001]
            perfil = s.get("profile_type")
            if perfil:
                achadas = [p for p in achadas if chave_perfil(p.get("perfil")) == chave_perfil(perfil)]
            candidatas.update(p["plan_key"] for p in achadas)
            if len(achadas) == 1 and c is not None and perfil:
                resolvidas.append((achadas[0]["plan_key"], s.get("assumed_quantity")))
        unicas = list(dict.fromkeys(k for k, _ in resolvidas))
        if unicas and len(unicas) == len(sondas):
            estado_ = "explicit" if explicitas == len(sondas) else "technical_unique"
            out[r["id"]] = {"estado": estado_, "linhas": resolvidas, "candidatas": sorted(candidatas)}
        elif candidatas:
            out[r["id"]] = {"estado": "ambiguous" if len(candidatas) > 1 else "incomplete", "linhas": [],
                            "candidatas": sorted(candidatas)}
        else:
            out[r["id"]] = {"estado": "unmatched", "linhas": [], "candidatas": []}
    return out


def operacao_registo(setor, registo, operacoes_linha) -> str | None:
    """Operação de um registo MES numa linha (planning_production.operation_for_record): MTG2 pela máquina
    (abocardar / serrotes = corte); MTG3 pelo código escrito ou pela operação única da peça. None = por confirmar."""
    if setor == "perfis":
        maquina = " ".join(str(registo.get("maquina") or "").split()).casefold()
        if maquina in ("abocardar", "maq. abocardar"):
            return "abocardar"
        if any(p in maquina for p in ("serrote", "vanguard", "meba", "doall", "corte", "disco", "fita")):
            return "corte"
        return None
    explicita = str(registo.get("operacao") or "").strip()
    if explicita and explicita in operacoes_linha:
        return explicita
    return operacoes_linha[0] if len(operacoes_linha) == 1 else None


def indice_por_linha(associacoes: dict) -> dict:
    """{plan_key: [(id do registo, quantidade assumida)]} a partir de `associar_registos`."""
    out = defaultdict(list)
    for rid, a in associacoes.items():
        for chave, assumida in a["linhas"]:
            out[chave].append((rid, assumida))
    return dict(out)


def ocr_da_operacao(setor, por_linha: dict, registos: dict, plan_key, operacoes_linha, principal) -> dict:
    """Soma OCR validada da operação principal de uma linha: {ocr, registos, bloqueado, motivo}.

    `por_linha`: `indice_por_linha(associar_registos(...))`. Um registo associado por confirmar (operação
    desconhecida, quantidade inválida) bloqueia o OCR: a app usa então o contador do Excel."""
    soma, ids, bloqueado, motivo = 0.0, [], False, None
    for rid, assumida in por_linha.get(plan_key, ()):
        r = registos[rid]
        op = operacao_registo(setor, r, operacoes_linha)
        if op is None:
            bloqueado, motivo = True, "Registo MES com operação por confirmar."
            continue
        if op != principal:
            continue
        q = quantidade(assumida if assumida is not None else r.get("quantidade"))
        if q is None:
            bloqueado, motivo = True, "Quantidade OCR inválida."
            continue
        soma += q
        ids.append(rid)
    return {"ocr": soma if ids else None, "registos": sorted(ids), "bloqueado": bloqueado, "motivo": motivo}


# ---------------------------------------------------------------- peso e área

_CANTONEIRA = re.compile(r"^\s*[Ll]\s*(\d+(?:[.,]\d+)?)\s*[xX×*]\s*(\d+(?:[.,]\d+)?)\s*[xX×*]\s*(\d+(?:[.,]\d+)?)\s*$")


def dimensoes_cantoneira(perfil):
    """(a, b, t) em mm de «L70X70X7» / «L 100x65x8»; None se não se lê como cantoneira."""
    found = _CANTONEIRA.match(str(perfil or ""))
    if not found:
        return None
    a, b, t = (float(x.replace(",", ".")) for x in found.groups())
    if not (a > 0 and b > 0 and 0 < t < min(a, b)):
        return None
    return a, b, t


def kg_m_geometria(perfil):
    """kg/m de uma cantoneira pela geometria: t(a+b−t) mm² × 7850 kg/m³ ÷ 10⁶ (sem raios: ±2 %)."""
    d = dimensoes_cantoneira(perfil)
    if not d:
        return None
    a, b, t = d
    return t * (a + b - t) * DENSIDADE_ACO / 1e6


def indice_pesos(linhas):
    """{chave do perfil: {kg/m}} da folha «Tabela pesos» (colunas B e C), como raw.calculations.weights."""
    indice = defaultdict(set)
    for linha in linhas:
        valores = (linha.get("row_data") or {}).get("values") or linha.get("values") or []
        if len(valores) < 3 or not valores[1]:
            continue
        kg = positivo(valores[2])
        if kg is not None:
            indice[chave_texto(valores[1])].add(kg)
    return dict(indice)


def peso_cantoneira(perfil, comprimento_mm, pesos: dict, *, geometria: bool = True) -> dict:
    """Peso de uma peça MTG3: Tabela de pesos (kg/m único) → geometria (regra F08 de 08/10) → desconhecido."""
    c = positivo(comprimento_mm)
    valores = pesos.get(chave_texto(perfil)) or set()
    if len(valores) == 1 and c:
        kg_m = next(iter(valores))
        return {"kg_m": kg_m, "kg_peca": kg_m * c / 1000, "origem": "Tabela de pesos"}
    motivo = "Pesos divergentes na Tabela de pesos." if len(valores) > 1 else "Perfil sem peso na Tabela de pesos."
    if geometria and c:
        kg_m = kg_m_geometria(perfil)
        if kg_m:
            return {"kg_m": kg_m, "kg_peca": kg_m * c / 1000, "origem": "geometria", "motivo_tabela": motivo}
    return {"kg_m": None, "kg_peca": None, "origem": None, "motivo_tabela": motivo if c else "Comprimento desconhecido."}


def area_seccao(tipo, *, d=None, w=None, h=None, t=None, perfil=None, catalogo=None):
    """Área de corte (mm²) MTG2 pela FuncAreaPerf do Excel; sem fórmula para o tipo, o catálogo AreaSecaoCorte
    exato (família, perfil) com um só valor. Devolve (área | None, regra)."""
    familia = chave_texto(tipo)
    d, w, h, t = (positivo(x) for x in (d, w, h, t))
    formulas = {
        "varão redondo": lambda: math.pi * d * d / 4 if d else None,
        "varão nervurado": lambda: math.pi * d * d / 4 if d else None,
        "varão quadrado": lambda: w * w if w else None,
        "varão retangular": lambda: w * h if w and h else None,
        "barra": lambda: w * h if w and h else None,
        "tubo redondo": lambda: math.pi * (d * d - (d - 2 * t) ** 2) / 4 if d and t and 2 * t < d else None,
        "tubo quadrado": lambda: w * w - (w - 2 * t) ** 2 if w and t and 2 * t < w else None,
        "tubo retangular": lambda: w * h - (w - 2 * t) * (h - 2 * t) if w and h and t and 2 * t < min(w, h) else None,
        "calha": lambda: h * t + 2 * w * t - 2 * t * t if w and h and t and 2 * t < h and t < w else None,
        "cantoneira": lambda: h * t + w * t - t * t if w and h and t and t < min(w, h) else None,
        "chapa": lambda: w * t if w and t else None,
    }
    if familia in formulas:
        return formulas[familia](), "FuncAreaPerf"
    valores = {positivo(x) for x in (catalogo or {}).get((familia, chave_texto(perfil)), [])} - {None}
    if len(valores) == 1:
        return next(iter(valores)), "AreaSecaoCorte"
    return None, "Catálogo com áreas divergentes." if len(valores) > 1 else "Sem área para a família e o perfil."


def indice_areas(linhas):
    """{(família, perfil): [área]} da folha AreaSecaoCorte (colunas A, B, C)."""
    indice = defaultdict(list)
    for linha in linhas:
        valores = (linha.get("row_data") or {}).get("values") or linha.get("values") or []
        if len(valores) >= 3 and valores[0] and valores[1]:
            indice[(chave_texto(valores[0]), chave_texto(valores[1]))].append(valores[2])
    return dict(indice)


def peso_perfil(area_mm2, comprimento_mm, densidade=DENSIDADE_ACO):
    a, c = positivo(area_mm2), positivo(comprimento_mm)
    return a / 1e6 * c / 1000 * densidade if a and c else None


def kg(saldo_pecas, kg_peca):
    if saldo_pecas is None or kg_peca is None:
        return None
    return saldo_pecas * kg_peca


# ---------------------------------------------------------------- velocidades e horas

def _dia_producao(valor):
    texto = str(valor or "")[:10].strip()
    if not texto or "+" in texto:
        return None
    d = dia(texto)
    return d if d and d.year >= 2000 else None


def velocidades_recentes(linhas, ate: date, semanas: int = SEMANAS_VELOCIDADE) -> dict:
    """Velocidade do Excel (m/h) em vigor por máquina MTG3: a moda de «Mt\\h» nas linhas com Data Corte das
    últimas `semanas` com dados (até `ate`); empate → a da linha mais recente (productivity.recent_excel_speeds)."""
    por_maquina = defaultdict(list)
    for linha in linhas:
        maquina = str(linha.get("Máquina Corte") or "").strip()
        velocidade = numero(linha.get("Mt\\h"))
        d = _dia_producao(linha.get("Data Corte"))
        if maquina and velocidade and velocidade > 0 and d is not None:
            por_maquina[maquina].append((d, velocidade))
    resultado = {}
    for maquina, itens in por_maquina.items():
        passadas = [x for x in itens if x[0] <= ate]
        base = passadas or itens
        ultimo = max(x[0] for x in base) if passadas else min(x[0] for x in base)
        inicio = ultimo - timedelta(weeks=semanas)
        janela = ([x for x in itens if inicio < x[0] <= ultimo] if passadas
                  else [x for x in itens if x[0] < ultimo + timedelta(weeks=semanas)])
        contagem = Counter(v for _, v in janela)
        recente = {v: d for d, v in sorted(janela)}
        valor = max(contagem, key=lambda v: (contagem[v], recente[v]))
        resultado[maquina] = {"valor": valor, "linhas": len(janela), "de": inicio.isoformat(), "ate": ultimo.isoformat()}
    return resultado


def taxas_capacidade(linhas) -> dict:
    """{máquina: {C, E, F, EF}} da folha CapacidadeMáquinas (linhas 2-12; B = máquina). EF = F quando preenchida,
    senão E: é a taxa que a tabela «Carga serrotes total» do próprio Excel usa (decisão 3 de 08/10)."""
    taxas = {}
    for linha in linhas:
        if not 2 <= int(linha.get("excel_row") or 0) <= 12:
            continue
        v = (linha.get("row_data") or {}).get("values") or linha.get("values") or []
        maquina = str(v[1]).strip() if len(v) > 1 and v[1] else ""
        if not maquina:
            continue
        c, e, f = (positivo(v[i]) if len(v) > i else None for i in (2, 4, 5))
        taxas[maquina] = {"C": c, "E": e, "F": f, "EF": f or e, "linha": linha.get("excel_row")}
    return taxas


def e_thomas(nomes) -> bool:
    return any("thomas" in str(n or "").casefold() for n in (nomes or ()))


def fator_thomas(setor, nomes_maquina, qtd) -> int:
    """×3 da Thomas como no Excel: perfis, máquina Thomas e QTD > 50."""
    q = quantidade(qtd)
    return 3 if setor == "perfis" and e_thomas(nomes_maquina) and q is not None and q > THOMAS_QTD else 1


def horas_decididas(setor, saldo_pecas, *, comprimento_mm=None, area_mm2=None, qtd=None, nomes_maquina=(),
                    velocidades=None, taxas=None, confirmada=None, eficiencia_pct=100.0) -> dict:
    """Horas pela regra decidida a 08/10: volume ÷ velocidade ÷ eficiência.

    Velocidade: taxa «Confirmada» da tabela de velocidades (`confirmada` = {'method','value'}) → Excel da máquina
    efetiva (MTG3 «Mt\\h» mais recente; MTG2 coluna E/F da CapacidadeMáquinas, ×3 da Thomas com QTD > 50).
    `nomes_maquina`: o nome da máquina efetiva e os seus aliases (procura-se a velocidade por qualquer deles)."""
    out = {"horas": None, "taxa": None, "unidade": None, "origem": None, "fator": 1, "eficiencia_pct": eficiencia_pct,
           "volume": None, "motivo": None}
    if saldo_pecas is None:
        return {**out, "motivo": "Saldo desconhecido."}
    if saldo_pecas == 0:
        return {**out, "horas": 0.0, "motivo": "Concluída."}
    if not nomes_maquina:
        return {**out, "motivo": "Sem máquina efetiva."}
    efic = positivo(eficiencia_pct) or 100.0
    if setor == "cantoneiras":
        c = positivo(comprimento_mm)
        if not c:
            return {**out, "motivo": "Comprimento desconhecido."}
        volume, unidade, metodo = saldo_pecas * c / 1000, "m/h", "metres_hour"
    else:
        a = positivo(area_mm2)
        if not a:
            return {**out, "motivo": "Área de corte desconhecida."}
        volume, unidade, metodo = saldo_pecas * a, "mm²/h", "area_hour"
    taxa, origem, fator = None, None, 1
    if confirmada and positivo(confirmada.get("value")) and confirmada.get("method", metodo) == metodo:
        taxa, origem = positivo(confirmada["value"]), "Confirmada"
    elif setor == "cantoneiras":
        for nome in nomes_maquina:
            found = (velocidades or {}).get(str(nome or "").strip())
            if found and positivo(found.get("valor")):
                taxa, origem = found["valor"], f"Excel Mt\\h de {nome}"
                break
    else:
        for nome in nomes_maquina:
            found = (taxas or {}).get(str(nome or "").strip())
            if found and found.get("EF"):
                taxa, origem = found["EF"], f"Excel E/F de {nome}"
                break
        fator = fator_thomas(setor, nomes_maquina, qtd)
    if not taxa:
        return {**out, "volume": volume, "unidade": unidade, "motivo": "Velocidade do Excel desconhecida para a máquina."}
    horas = volume / (taxa * fator) / (efic / 100)
    return {**out, "horas": horas, "taxa": taxa, "unidade": unidade, "origem": origem, "fator": fator, "volume": volume,
            "eficiencia_pct": efic}


def horas_regra_atual_mtg2(saldo_pecas, area_mm2, taxa_c, *, thomas=False, qtd=None):
    """Horas MTG2 com a coluna C (regra em uso até 08/10), para o --prever."""
    a = positivo(area_mm2)
    if saldo_pecas is None or not a or not positivo(taxa_c):
        return None
    fator = 3 if thomas and (quantidade(qtd) or 0) > THOMAS_QTD else 1
    return saldo_pecas * a / (taxa_c * fator)


# ---------------------------------------------------------------- prazo e semana de carga

def indice_picking(linhas) -> dict:
    """{OF: semana | None} da folha Picking (B = OF, C = semana); semanas diferentes para a OF → None (conflito)."""
    semanas = defaultdict(set)
    for linha in linhas:
        v = (linha.get("row_data") or {}).get("values") or linha.get("values") or []
        if len(v) < 3:
            continue
        of, semana = of_normalizada(v[1]), semana_positiva(v[2])
        if of and semana:
            semanas[of].add(semana)
    return {of: next(iter(s)) if len(s) == 1 else None for of, s in semanas.items()}


def picking_da_linha(of, semana_linha, indice: dict) -> dict:
    """Semana de Picking (planning_dates.resolve_picking sem decisão manual): folha > coluna da linha; conflito
    entre as duas ou dentro da folha → sem Picking."""
    of = of_normalizada(of)
    folha = indice.get(of)
    linha = semana_positiva(semana_linha)
    conflito = bool(folha and linha and folha != linha) or (of in indice and folha is None)
    if conflito:
        return {"semana": None, "origem": "Conflito Picking", "conflito": True}
    return {"semana": folha or linha, "origem": "folha" if folha else "linha" if linha else None, "conflito": False}


def inferir_ano_iso(semana, ancora: date) -> int | None:
    """Ano ISO em que a semana fica mais perto da âncora (Data Corte; sem ela, hoje)."""
    semana = semana_positiva(semana)
    if semana is None:
        return None
    melhor = None
    for ano in (ancora.year - 1, ancora.year, ancora.year + 1):
        try:
            meio = date.fromisocalendar(ano, semana, 4)
        except ValueError:
            continue
        distancia = abs((meio - ancora).days)
        if melhor is None or distancia < melhor[0]:
            melhor = (distancia, ano)
    return melhor[1] if melhor else None


def _picking(semana, ano, ancora: date, ano_assumido=None):
    semana = semana_positiva(semana)
    if not semana:
        return None
    escolhido = int(ano) if ano not in (None, "") else ano_assumido or inferir_ano_iso(semana, ancora)
    try:
        return date.fromisocalendar(escolhido, semana, 1)
    except (TypeError, ValueError):
        return None


def prazo(setor, *, data_corte=None, picking_semana=None, picking_ano=None, picking_conflito=False,
          semana_escolhida=None, galvanizacao=None, coluna_w=None, hoje: date, ano_assumido=None,
          substituicao: dict | None = None, fim_previsto=None, entrega=None) -> dict:
    """Prazo do setor (priority.DEFAULTS e resolve): {dia, instante, fonte, provisorio, estacionada}.

    `substituicao`: definição de uma substituição por OF/referência (due_date ou field) — prevalece, também
    sobre a linha estacionada."""
    out = {"dia": None, "instante": None, "fonte": None, "provisorio": False, "estacionada": False}
    ancora = dia(data_corte) or hoje
    candidatos = {
        "cut_date": lambda: dia(data_corte),
        "galvanizing": lambda: dia(galvanizacao),
        "planned_finish_date": lambda: dia(fim_previsto),
        "delivery_date": lambda: dia(entrega),
        "picking": lambda: None if picking_conflito else _picking(picking_semana, picking_ano, ancora, ano_assumido),
        "planned_period": lambda: date.fromisocalendar(int(semana_escolhida[0]), int(semana_escolhida[1]), 7)
        if semana_escolhida else None,
    }
    if substituicao:
        if dia(substituicao.get("due_date")):
            return {**out, "dia": dia(substituicao["due_date"]), "fonte": "Substituição manual"}
        campo = substituicao.get("field")
        if campo in candidatos:
            d = candidatos[campo]()
            return {**out, "dia": d, "fonte": f"Substituição manual ({campo})" if d else "sem prazo"}
    if setor == "cantoneiras":
        if str(coluna_w or "").strip() in ESTACIONADA:
            return {**out, "estacionada": True, "fonte": "estacionada"}
        d = dia(data_corte)
        return {**out, "dia": d, "fonte": "Data Corte"} if d else {**out, "fonte": "sem prazo"}
    segunda = candidatos["picking"]()
    if segunda:
        instante = datetime.combine(segunda, time(8), LISBOA)
        return {**out, "dia": segunda, "instante": instante.isoformat(), "fonte": "Picking",
                "provisorio": picking_ano in (None, "")}
    for fonte, campo in (("Semana escolhida", "planned_period"), ("Galvanização", "galvanizing"), ("Data Corte", "cut_date")):
        d = candidatos[campo]()
        if d:
            return {**out, "dia": d, "fonte": fonte}
    return {**out, "fonte": "sem prazo"}


def semanas_horizonte(hoje: date, n: int = SEMANAS_CARGA):
    segunda = hoje - timedelta(days=hoje.weekday())
    return [tuple((segunda + timedelta(weeks=i)).isocalendar()[:2]) for i in range(n)]


def semana_carga(dia_prazo, hoje: date, n: int = SEMANAS_CARGA) -> dict:
    """Onde a Carga põe a linha (load.classify + overview): {celula: (ano, semana) | 'sem_prazo' | 'depois',
    coluna: 'semana' | 'atrasado' | 'sem_prazo' | 'depois', atrasada}.

    Prazo antes da segunda-feira da semana atual → coluna Atrasado (o detalhe da célula da semana atual também o
    mostra); prazo entre segunda e ontem → célula da semana atual, marcada atrasada."""
    semanas = semanas_horizonte(hoje, n)
    atual = semanas[0]
    d = dia(dia_prazo)
    if d is None:
        return {"celula": "sem_prazo", "coluna": "sem_prazo", "atrasada": False, "semana_iso": None}
    semana = tuple(d.isocalendar()[:2])
    iso = f"{semana[0]}-W{semana[1]:02d}"
    atrasada = d < hoje
    if semana < atual:
        return {"celula": atual, "coluna": "atrasado", "atrasada": True, "semana_iso": iso}
    if semana in semanas:
        return {"celula": semana, "coluna": "semana", "atrasada": atrasada, "semana_iso": iso}
    return {"celula": "depois", "coluna": "depois", "atrasada": atrasada, "semana_iso": iso}


# ---------------------------------------------------------------- máquina e estado

def maquina_efetiva(chaves, escolhas: dict, maquina_tabela, familia=None, conjuntos: dict | None = None) -> dict:
    """Carteira (pela chave atual e aliases) → coluna Máquina da Tabela → conjunto de famílias (machine_choice)."""
    for chave in chaves or ():
        found = (escolhas or {}).get(chave)
        if found:
            return {"maquina": found.get("machine_name") or "", "resource_id": found.get("resource_id"),
                    "origem": "carteira", "sugerida": (found.get("seen") or {}).get("origem") == "sugerida"}
    nome = maquina_normalizada(maquina_tabela)
    if nome:
        return {"maquina": nome, "resource_id": None, "origem": "tabela", "sugerida": False}
    found = (conjuntos or {}).get(familia) if familia else None
    if found:
        return {"maquina": found.get("machine_name") or "", "resource_id": found.get("resource_id"), "origem": "conjunto",
                "sugerida": False}
    return {"maquina": "", "resource_id": None, "origem": None, "sugerida": False}


def decisao(chaves, membros: dict, antigas: dict, of, referencia):
    """Planear efetivo (decisions.resolve): membro (chave/aliases) → (OF, referência) → (OF, '*')."""
    for chave in chaves or ():
        found = (membros or {}).get(chave)
        if found:
            return None if found.get("decision") == "cleared" else found.get("decision")
    referencia = str(referencia or "").strip() or "Sem referência"
    for k in ((of, referencia), (of, "*")):
        found = (antigas or {}).get(k)
        if found:
            return found.get("decision")
    return None


def estado(decisao_efetiva, maquina) -> str:
    """planeado / nesting / sem_maquina; «excluida» fora da partição (planning_status.classify)."""
    if decisao_efetiva == "excluded":
        return "excluida"
    if not maquina:
        return "sem_maquina"
    return "planeado" if decisao_efetiva == "selected" else "nesting"


TIPO_CARGA = {"planeado": "no plano", "nesting": "a vencer", "sem_maquina": "a vencer, máquina sugerida"}


# ---------------------------------------------------------------- identidade, estratos e amostra

def identidade(setor, of, referencia, perfil, comprimento_mm, qtd, ordem=1) -> str:
    """Identidade estável entre importações: setor, OF, referência, perfil, comprimento, QTD e ordem entre repetidas."""
    c = numero(comprimento_mm)
    q = numero(qtd)
    return "|".join([setor, of_normalizada(of) or str(of or ""), chave_tecnica(referencia), chave_perfil(perfil),
                     f"{c:g}" if c is not None else "", f"{q:g}" if q is not None else "", str(ordem)])


def numerar_repetidas(linhas, chave=lambda x: x["base_id"], ordem=lambda x: x.get("linha_excel") or 0):
    """Acrescenta `ordem` (1, 2, …) e `repetidas` (n) às linhas com a mesma identidade base, pela linha do Excel."""
    grupos = defaultdict(list)
    for linha in linhas:
        grupos[chave(linha)].append(linha)
    for itens in grupos.values():
        for i, linha in enumerate(sorted(itens, key=ordem), start=1):
            linha["ordem"] = i
            linha["repetidas"] = len(itens)
    return linhas


def sha(texto: str) -> str:
    return hashlib.sha1(texto.encode()).hexdigest()


def etiquetas(caso: dict) -> set:
    """Valores de cada dimensão da amostra que o caso cobre."""
    e = caso.get("estratos") or {}
    out = {(k, v) for k, v in e.items() if v not in (None, "")}
    out |= {("marca", m) for m in caso.get("marcas") or ()}
    return out


def escolher_amostra(casos, *, alvo: int = 400, minimo: int = 5, obrigatorios=(), grupo=None, por_grupo=None) -> list:
    """Amostra estratificada determinística (sha1 da identidade).

    1. os obrigatórios (todas as linhas das OF com Planeado e as linhas com marcas raras);
    2. cada valor de cada dimensão até `minimo` casos, do valor mais raro para o mais comum, pela ordem do sha1;
    3. completa até `alvo` pela ordem do sha1. Se os obrigatórios passarem o alvo, ficam todos.
    Com `grupo` (ex.: a OF), o passo 3 junta grupos pela ordem do sha1 do grupo, até `por_grupo` linhas de cada
    (menos pedidos às páginas por linha auditada sem deixar uma OF grande ocupar a amostra; 08/10)."""
    ordem = sorted(casos, key=lambda c: sha(c["id"]))
    escolhidos, vistos = [], set()

    def junta(c):
        if c["id"] not in vistos:
            vistos.add(c["id"])
            escolhidos.append(c)

    obrigatorios = set(obrigatorios)
    for c in ordem:
        if c["id"] in obrigatorios:
            junta(c)
    contagem = Counter(t for c in ordem for t in etiquetas(c))
    cobertura = Counter(t for c in escolhidos for t in etiquetas(c))
    for etiqueta in sorted(contagem, key=lambda t: (contagem[t], t)):
        if cobertura[etiqueta] >= minimo:
            continue
        for c in ordem:
            if cobertura[etiqueta] >= minimo:
                break
            if c["id"] not in vistos and etiqueta in etiquetas(c):
                junta(c)
                cobertura.update(etiquetas(c))
    if grupo is None:
        for c in ordem:
            if len(escolhidos) >= alvo:
                break
            junta(c)
        return escolhidos
    grupos = defaultdict(list)
    for c in ordem:
        grupos[grupo(c)].append(c)
    for chave in sorted(grupos, key=lambda g: sha(str(g))):
        if len(escolhidos) >= alvo:
            break
        for c in grupos[chave][:por_grupo]:
            if len(escolhidos) >= alvo:
                break
            junta(c)
    return escolhidos


def cobertura(amostra, populacao) -> dict:
    """{dimensão: {valor: [na amostra, na população]}} para o relatório."""
    total = Counter(t for c in populacao for t in etiquetas(c))
    tem = Counter(t for c in amostra for t in etiquetas(c))
    out = defaultdict(dict)
    for (dim, valor), n in sorted(total.items(), key=lambda x: (x[0][0], str(x[0][1]))):
        out[dim][str(valor)] = [tem[(dim, valor)], n]
    return dict(out)


# ---------------------------------------------------------------- comparação entre corridas

def diferenca(esperado, valor, tolerancia=0.0):
    """None quando batem (ou ambos desconhecidos); senão a diferença (número) ou True (valores não numéricos)."""
    if esperado is None and valor is None:
        return None
    if isinstance(esperado, (int, float)) and isinstance(valor, (int, float)) and not isinstance(esperado, bool):
        d = valor - esperado
        return None if abs(d) <= tolerancia else round(d, 6)
    return None if esperado == valor else True


def efeito_aplica(efeito: dict, caso: dict, verificacao: dict, defeito_antes=None) -> bool:
    """Um efeito esperado (ficheiro de efeitos) cobre esta diferença? Filtro por verificação, campo, página,
    setor, máquina (subtexto), marca e defeito que explicava a diferença antes da correção."""
    if efeito.get("verificacao") not in (None, verificacao.get("codigo")):
        return False
    if efeito.get("campo") not in (None, verificacao.get("campo")):
        return False
    if efeito.get("pagina") not in (None, verificacao.get("pagina")):
        return False
    filtro = efeito.get("filtro") or {}
    if filtro.get("setor") and filtro["setor"] != caso.get("setor"):
        return False
    if filtro.get("maquina") and filtro["maquina"].casefold() not in str((caso.get("esperado") or {}).get("maquina") or "").casefold():
        return False
    if filtro.get("marca") and filtro["marca"] not in (caso.get("marcas") or ()):
        return False
    if filtro.get("defeito") and filtro["defeito"] not in (defeito_antes, verificacao.get("defeito")):
        return False
    return True


def comparar(antes: dict, depois: dict, efeitos=()) -> dict:
    """Compara duas evidências pela identidade estável. Cada valor de página que mudou fica:
    - «origem mudou» quando os valores de origem do caso mudaram (importação nova pelo meio);
    - «explicada» quando um efeito esperado declarado o cobre (e, se o efeito pede `fecha`, a diferença para o
      esperado desapareceu);
    - «inexplicada» nos outros casos."""
    a = {c["id"]: c for c in antes.get("casos", [])}
    d = {c["id"]: c for c in depois.get("casos", [])}
    linhas, resumo = [], Counter()
    for ident in sorted(set(a) | set(d)):
        if ident not in a or ident not in d:
            estado_ = "só antes" if ident in a else "só depois"
            resumo[estado_] += 1
            linhas.append({"id": ident, "estado": estado_})
            continue
        ca, cd = a[ident], d[ident]
        origem_mudou = ca.get("origem") != cd.get("origem")
        va = {(v["codigo"], v["campo"], v["pagina"]): v for v in ca.get("verificacoes", [])}
        vd = {(v["codigo"], v["campo"], v["pagina"]): v for v in cd.get("verificacoes", [])}
        for k in sorted(set(va) | set(vd), key=str):
            x, y = va.get(k), vd.get(k)
            if x and y and x.get("valor") == y.get("valor"):
                continue
            if origem_mudou:
                estado_ = "origem mudou"
            else:
                ref = y or x
                efeito = next((e for e in efeitos if efeito_aplica(e, cd, ref, (x or {}).get("defeito"))), None)
                if efeito and efeito.get("fecha") and y and y.get("diferenca") is not None:
                    efeito = None  # o efeito prometia fechar a diferença e ela continua
                estado_ = "explicada" if efeito else "inexplicada"
            resumo[estado_] += 1
            linhas.append({"id": ident, "codigo": k[0], "campo": k[1], "pagina": k[2], "antes": (x or {}).get("valor"),
                           "depois": (y or {}).get("valor"), "esperado": (y or x or {}).get("esperado"), "estado": estado_,
                           "efeito": (efeito or {}).get("descricao") if estado_ == "explicada" else None})
    return {"resumo": dict(resumo), "diferencas": linhas}


# ---------------------------------------------------------------- C15: preenchimento automático

# Mapa «campo preenchido automaticamente → fonte(s) → regra quando as fontes se contradizem → onde se usa»
# (relatório fluxo-dados §4 do mapeamento de 07/10, com as decisões de 08/10). `codigo`: (ficheiro, expressão)
# que o script procura no código para confirmar que a regra citada está lá.
PREENCHIMENTO = [
    {"campo": "OV, Cliente, Descrição da obra, Estado, Entrega, Fim previsto",
     "fontes": "Cópias CPIS nos dois Excel; OF registada à mão (local_orders)",
     "regra": "Cópia carregada mais tarde ganha, campo a campo; campo vazio herda da outra; com registo livre a OF "
              "local sobrepõe-se. O CPIS direto (vazio) substituiria as cópias.",
     "onde": "Carteira, sinais (prioridade/anulada), prazo de reserva",
     "codigo": [("app/cpis_copies.py", r"def latest_first"), ("app/planning_hub.py", r"latest_first")]},
    {"campo": "Família de Produto", "fontes": "cpis_rows do snapshot do próprio setor",
     "regra": "Sem a regra «mais recente»: junta pelo snapshot da geração; código mais baixo quando há vários.",
     "onde": "Filtro e vista da Carteira, Carga",
     "codigo": [("app/sector/occurrences.py", r"ORDER BY production_order_no, work_type_code"),
                ("app/sector/portfolio.py", r"cp\.snapshot_id = g\.snapshot")]},
    {"campo": "Família SKU", "fontes": "Regra CSV em sku_family_rules",
     "regra": "Só MTG3; sem regra, «Sem família SKU».", "onde": "Filtros, conjuntos, aprendizagem",
     "codigo": [("app/raw/sku_families.py", r"def annotate")]},
    {"campo": "Referência, Perfil, QTD, Comp., material, dimensões", "fontes": "Excel; PDF (dossiê); registo manual",
     "regra": "Valor escrito à mão > origem; campos não mexidos seguem a origem (OPERATION_FOLLOW só 7 campos — F20).",
     "onde": "Identidade, metros, horas",
     "codigo": [("app/planning_needs.py", r"OPERATION_FOLLOW"), ("app/planning_needs.py", r"def follow")]},
    {"campo": "Produção feita (cut, made)", "fontes": "MES OCR validado; Excel «Ser.»/«Maq.»; 0 local",
     "regra": "OCR validado > Excel > 0 > desconhecido; sem máximo (decisão 2 de 08/10: o OCR substitui mesmo menor).",
     "onde": "Saldo",
     "codigo": [("app/planning_calculations.py", r"if usable: value, origin = ocr, 'OCR validado'"),
                ("app/planning_calculations.py", r"def excel_counter")]},
    {"campo": "Saldo (remaining, planning_remaining)", "fontes": "Cálculo acima; «Qtd em falta» manual; camada v2",
     "regra": "Qtd em falta > OCR > v2 (sem OCR e contadores iguais) > Excel. A v2 sobrepõe-se ao saldo principal (F04/F05).",
     "onde": "Carteira (peças, metros, kg), Carga, Gantt",
     "codigo": [("app/gantt/research.py", r"def overlay_rows"), ("app/gantt/research.py", r"def excel_counters_changed"),
                ("app/planning_estimates.py", r"def select_balance")]},
    {"campo": "Peso", "fontes": "MTG3: Tabela de pesos (kg/m exato e único); MTG2: área × L × 7850",
     "regra": "Pesos divergentes → desconhecido. Decisão F08 (08/10): sem perfil na tabela, geometria t(a+b−t)·7850/10⁶.",
     "onde": "kg na Carteira e na Carga",
     "codigo": [("app/planning_calculations.py", r"Pesos divergentes para a designação exata"),
                ("app/planning_calculations.py", r"density=7850")]},
    {"campo": "Área de corte (MTG2)", "fontes": "Fórmula geométrica (FuncAreaPerf) ou AreaSecaoCorte exata",
     "regra": "Fórmula > catálogo exato.", "onde": "Horas e peso MTG2",
     "codigo": [("app/planning_calculations.py", r"def section")]},
    {"campo": "Máquina (Tabela)", "fontes": "Registo manual; Excel «Máquina Corte»",
     "regra": "Manual > Excel; segue a origem se ninguém a escreveu.", "onde": "Máquina efetiva",
     "codigo": [("app/planning.py", r"\"machine\": _text\(d.get\(\"Máquina Corte\"\)")]},
    {"campo": "Máquina efetiva", "fontes": "Carteira (sector_member_machine) > Tabela > conjunto de famílias",
     "regra": "Uma sugestão nunca é máquina efetiva; «Por definir», «Subcontrato», «MTG3»… = sem máquina.",
     "onde": "Estado, Carga, Gantt",
     "codigo": [("app/sector/machine_choice.py", r"def effective"), ("app/sector/machine_choice.py", r"PLACEHOLDERS")]},
    {"campo": "Máquina sugerida", "fontes": "Aprendizagem (Carteira 5, Tabela 1, histórico 1) > previsão (estimates.apply)",
     "regra": "Ao Planear grava-se em sector_member_machine com origem «sugerida» (não alimenta a aprendizagem).",
     "onde": "Lupa, Planear, coluna «sugerida» da Carga",
     "codigo": [("app/sector/selection.py", r"def suggested_machines"), ("app/sector/selection.py", r"\"origem\": \"sugerida\"")]},
    {"campo": "1.ª/2.ª Oper. (MTG3)", "fontes": "Excel; valores por defeito 119/0",
     "regra": "Excel > defeito.", "onde": "Saldo, horas, operações seguintes",
     "codigo": [("app/raw/registration.py", r"119")]},
    {"campo": "Data Corte", "fontes": "Excel; manual", "regra": "Manual > Excel (segue a origem).",
     "onde": "Prazo MTG3; prazo de reserva MTG2",
     "codigo": [("app/sector/priority.py", r"\"principal\": \[\"cut_date\"\]")]},
    {"campo": "Picking (MTG2)", "fontes": "Folha Picking; coluna da linha; manual",
     "regra": "Manual > folha (semana única) > linha; conflito → nenhum; ano deduzido pela Data Corte.", "onde": "Prazo MTG2",
     "codigo": [("app/planning_dates.py", r"def resolve_picking"), ("app/planning_dates.py", r"def infer_iso_year")]},
    {"campo": "Prazo do setor", "fontes": "Data Corte; Picking; semana escolhida; Galvanização; coluna W",
     "regra": "MTG3 Data Corte; MTG2 Picking → semana escolhida → Galvanização → Data Corte; W 2026/53 = estacionada.",
     "onde": "Carteira (janela, semana), Carga (semana da carga), Gantt",
     "codigo": [("app/sector/priority.py", r"\"perfis\": \{"), ("app/sector/priority.py", r"PARKED_WEEKS = \{\"2026/53\"\}")]},
    {"campo": "Horas", "fontes": "Taxa confirmada; Histórico; tabela de velocidades; Excel (Mt\\h / CapacidadeMáquinas)",
     "regra": "Hoje: Manual > Histórico (¼–4× Excel) > tabela Excel > Excel (coluna C na MTG2, ×3 Thomas só no motor). "
              "Decidido a 08/10: Confirmada > Excel × eficiência, ×3 da Thomas em todo o lado, coluna E/F na MTG2.",
     "onde": "Carteira (KPI), Carga, Gantt",
     "codigo": [("app/raw/productivity.py", r"def select_rate"), ("app/raw/capacity_revision.py", r"rate=number\(cell\(row,'C'\)\)"),
                ("app/sector/estimates.py", r"sem o fator ×3")]},
    {"campo": "Operação dos registos MES MTG3", "fontes": "extra.operation_code → operação única aplicável da peça",
     "regra": "Nunca deduzida da máquina.", "onde": "Atribuição de produção à operação",
     "codigo": [("app/planning_production.py", r"def operation_for_record")]},
]


def verificar_codigo(textos: dict) -> list:
    """Confirma no código cada regra do mapa. `textos`: {ficheiro relativo: conteúdo}. Devolve as entradas com
    `confirmacao`: [{ficheiro, expressao, linhas}] e `estado` («confirmada» / «por rever»)."""
    out = []
    for entrada in PREENCHIMENTO:
        provas = []
        for ficheiro, expressao in entrada["codigo"]:
            conteudo = textos.get(ficheiro)
            linhas = [] if conteudo is None else [i for i, linha in enumerate(conteudo.splitlines(), start=1)
                                                   if re.search(expressao, linha)]
            provas.append({"ficheiro": ficheiro, "expressao": expressao, "linhas": linhas[:5],
                           "existe": conteudo is not None})
        estado_ = "confirmada" if provas and all(p["linhas"] for p in provas) else "por rever"
        out.append({**{k: v for k, v in entrada.items() if k != "codigo"}, "confirmacao": provas, "estado": estado_})
    return out
