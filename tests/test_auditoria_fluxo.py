"""Funções puras da auditoria do fluxo de dados (08/10/2026): sem base de dados nem rede."""
import random
from datetime import date, datetime, timezone

import pytest

from scripts import auditoria_fluxo as A
from scripts import auditoria_fluxo_regras as R


# ---------------------------------------------------------------- números e saldo

@pytest.mark.parametrize("valor,esperado", [
    (12, 12.0), ("12,5", 12.5), ("1 200", 1200.0), ("1 543,5", 1543.5), (" 7 ", 7.0),
    ("1 20", None), ("abc", None), (float("inf"), None), (True, None), (None, None),
])
def test_um_so_leitor_de_numeros(valor, esperado):
    assert R.numero(valor) == esperado


def test_contador_vazio_conta_zero_so_quando_a_falta_e_a_qtd():
    assert R.contador_excel({"Maq.": None, "Qtd falta": 336}, "Maq.", 336.0)[0] == 0.0
    assert R.contador_excel({"Maq.": "", "Qtd falta": 300}, "Maq.", 336.0)[0] is None
    assert R.contador_excel({"Qtd falta": 336}, "Maq.", 336.0) == (None, "Coluna «Maq.» ausente.")
    assert R.contador_excel({"Ser.": 404, "Qtd em Falta": 490}, "Ser.", 894.0)[0] == 404.0
    assert R.contador_excel({"Ser.": "4,5", "Qtd em Falta": 490}, "Ser.", 894.0)[0] is None


def test_ocr_substitui_o_excel_mesmo_quando_e_menor():
    # OF265528 2C1 30x8 (07/10): QTD 14 690, Ser. 14 550, OCR 8 072 → saldo 6 618 (decisão 2 de 08/10: sem máximo).
    s = R.saldo(14690, 14550.0, 8072.0)
    assert s["saldo"] == 6618.0 and s["fonte"] == "OCR" and s["ocr_menor_excel"]
    assert s["diferenca_ocr_excel"] == 8072.0 - 14550.0


def test_saldo_pelas_outras_fontes():
    assert R.saldo(336, 0.0, None)["saldo"] == 336.0
    assert R.saldo(336, 0.0, 319.0)["saldo"] == 17.0  # OF264157 CWA5
    bloqueado = R.saldo(336, 100.0, 319.0, ocr_bloqueado=True)
    assert bloqueado["fonte"] == "Excel" and bloqueado["saldo"] == 236.0
    assert R.saldo(336, None, None) | {} == R.saldo(336, None, None)
    assert R.saldo(336, None, None)["fonte"] == "indisponível" and R.saldo(336, None, None)["saldo"] is None
    acima = R.saldo(12, None, 24.0)
    assert acima["saldo"] == 0.0 and acima["excesso"] == 12.0
    escrita = R.saldo(100, 10.0, None, declarada=150)
    assert escrita["fonte"] == "Qtd em falta" and escrita["saldo"] == 100.0
    assert R.saldo("x", 1.0, None)["saldo"] is None


def test_metros_e_desconhecidos():
    assert R.metros(17.0, 2168) == pytest.approx(36.856)
    assert R.metros(0.0, None) == 0.0
    assert R.metros(5.0, None) is None and R.metros(None, 1000) is None


# ---------------------------------------------------------------- peso e área

def test_peso_da_cantoneira_pela_tabela_e_pela_geometria():
    assert R.kg_m_geometria("L70X70X7") == pytest.approx(7.30835)
    assert R.kg_m_geometria("L 40 x 40 x 3") == pytest.approx(1.81335)
    assert R.kg_m_geometria("BARRA30X30") is None and R.kg_m_geometria("L10X10X12") is None
    pesos = R.indice_pesos([{"row_data": {"values": [None, "L70X70X7 ", 7.38]}},
                            {"row_data": {"values": [None, "L80X80X8", 9.63]}},
                            {"row_data": {"values": [None, "L80X80X8 ", 9.70]}}])
    tabela = R.peso_cantoneira("L70X70X7", 2168, pesos)
    assert tabela["origem"] == "Tabela de pesos" and tabela["kg_peca"] == pytest.approx(15.99984)
    divergente = R.peso_cantoneira("L80X80X8", 1000, pesos)
    assert divergente["origem"] == "geometria" and "divergentes" in divergente["motivo_tabela"]
    assert R.peso_cantoneira("L80X80X8", 1000, pesos, geometria=False)["kg_peca"] is None
    assert R.peso_cantoneira("PERFIL ESTRANHO", 1000, pesos)["kg_peca"] is None
    assert R.kg(17.0, 15.99984) == pytest.approx(271.99728) and R.kg(None, 1.0) is None


def test_area_e_peso_dos_perfis():
    area, regra = R.area_seccao("Tubo redondo", d=139.7, t=3)
    assert area == pytest.approx(1288.3671472, rel=1e-9) and regra == "FuncAreaPerf"
    assert R.peso_perfil(area, 1725) == pytest.approx(17.4461016, rel=1e-6)  # OF266067 7450V001
    assert R.area_seccao("Tubo redondo", d=10, t=6)[0] is None
    catalogo = R.indice_areas([{"row_data": {"values": ["Perfil I", "IPE80", 764]}}])
    assert R.area_seccao("Perfil I", perfil="IPE80", catalogo=catalogo) == (764.0, "AreaSecaoCorte")
    assert R.area_seccao("Perfil I", perfil="IPE100", catalogo=catalogo)[0] is None


# ---------------------------------------------------------------- velocidades e horas

def test_velocidade_mais_recente_do_excel():
    linhas = ([{"Máquina Corte": "Peddi 8", "Mt\\h": 80, "Data Corte": "2026-03-01"}] * 9
              + [{"Máquina Corte": "Peddi 8", "Mt\\h": 120, "Data Corte": "2026-09-20"}] * 3
              + [{"Máquina Corte": "Peddi 8", "Mt\\h": 100, "Data Corte": "2026-09-01"}] * 3
              + [{"Máquina Corte": "Peddi 8", "Mt\\h": 120, "Data Corte": "20+21/08"}])
    v = R.velocidades_recentes(linhas, date(2026, 10, 2))
    assert v["Peddi 8"]["valor"] == 120 and v["Peddi 8"]["linhas"] == 6  # empate 3–3: ganha a mais recente
    futuro = R.velocidades_recentes([{"Máquina Corte": "XP", "Mt\\h": 45, "Data Corte": "2027-01-04"}], date(2026, 10, 2))
    assert futuro["XP"]["valor"] == 45


CAPACIDADE = [  # folha CapacidadeMáquinas do Excel de 07/10 (B, C, D, E, F)
    {"excel_row": 1, "row_data": {"values": ["ID", "Máquina", "Capa. Específica de Corte 11/11/2024", None, "2024-11-29T00:00:00"]}},
    {"excel_row": 2, "row_data": {"values": [1, "Serrote Disco pav 1", 12824, None, 15409, None]}},
    {"excel_row": 3, "row_data": {"values": [2, "Serrote MEBA IS381 Pav 3", 48024, None, 40323, None]}},
    {"excel_row": 4, "row_data": {"values": [3, "Serrote Fita Thomas IS639 Pav.1", 18478, None, 37692, 18846]}},
    {"excel_row": 6, "row_data": {"values": [5, "Vanguard", 9200, None, 13636, None]}},
    {"excel_row": 10, "row_data": {"values": [9, "Serrote Doall Pav.1", 21863.5, None, None, 18846]}},
    {"excel_row": 21, "row_data": {"values": [None] * 14 + [5, "Vanguard", 12878660, 944]}},
]


def test_taxas_da_coluna_e_f():
    t = R.taxas_capacidade(CAPACIDADE)
    assert {m: x["EF"] for m, x in t.items()} == {"Serrote Disco pav 1": 15409, "Serrote MEBA IS381 Pav 3": 40323,
                                                  "Serrote Fita Thomas IS639 Pav.1": 18846, "Vanguard": 13636,
                                                  "Serrote Doall Pav.1": 18846}
    assert t["Vanguard"]["C"] == 9200
    # A tabela «Carga serrotes total» do Excel: Vanguard 12 878 660 mm² ÷ 13 636 = 944 h.
    assert round(12878660 / t["Vanguard"]["EF"]) == 944


def test_horas_pela_regra_decidida():
    mtg3 = R.horas_decididas("cantoneiras", 17.0, comprimento_mm=2168, nomes_maquina=["Peddi 8"],
                             velocidades={"Peddi 8": {"valor": 120}})
    assert mtg3["horas"] == pytest.approx(36.856 / 120) and mtg3["origem"].startswith("Excel")
    taxas = R.taxas_capacidade(CAPACIDADE)
    mtg2 = R.horas_decididas("perfis", 215.0, area_mm2=1288.3671472, qtd=894, nomes_maquina=["Serrote MEBA IS381 Pav 3"], taxas=taxas)
    assert mtg2["horas"] == pytest.approx(215 * 1288.3671472 / 40323) and mtg2["fator"] == 1
    # Aliases: a máquina efetiva «Serrote Fita pav.1» tem o alias da Thomas; ×3 só com QTD > 50.
    nomes = ["Serrote Fita pav.1", "Serrote Fita Thomas IS639 Pav.1"]
    com = R.horas_decididas("perfis", 10.0, area_mm2=1000, qtd=51, nomes_maquina=nomes, taxas=taxas)
    sem = R.horas_decididas("perfis", 10.0, area_mm2=1000, qtd=50, nomes_maquina=nomes, taxas=taxas)
    assert com["fator"] == 3 and sem["fator"] == 1 and sem["horas"] == pytest.approx(3 * com["horas"])
    lenta = R.horas_decididas("cantoneiras", 17.0, comprimento_mm=2168, nomes_maquina=["Peddi 8"],
                              velocidades={"Peddi 8": {"valor": 120}}, eficiencia_pct=80)
    assert lenta["horas"] == pytest.approx(mtg3["horas"] / 0.8)
    confirmada = R.horas_decididas("cantoneiras", 17.0, comprimento_mm=2168, nomes_maquina=["Peddi 8"],
                                   velocidades={"Peddi 8": {"valor": 120}}, confirmada={"method": "metres_hour", "value": 100})
    assert confirmada["origem"] == "Confirmada" and confirmada["horas"] == pytest.approx(0.36856)
    assert R.horas_decididas("cantoneiras", 0.0, nomes_maquina=["X"])["horas"] == 0.0
    assert R.horas_decididas("cantoneiras", 5.0, comprimento_mm=1000, nomes_maquina=[])["horas"] is None
    assert R.horas_decididas("cantoneiras", 5.0, comprimento_mm=1000, nomes_maquina=["Nova"], velocidades={})["horas"] is None
    assert R.horas_regra_atual_mtg2(215.0, 1288.3671472, 48024) == pytest.approx(5.7679272, rel=1e-6)  # a app hoje (coluna C)


# ---------------------------------------------------------------- prazo e semana da carga

def test_prazo_mtg3_e_estacionada():
    hoje = date(2026, 10, 8)
    assert R.prazo("cantoneiras", data_corte="2026-08-10T00:00:00", hoje=hoje)["dia"] == date(2026, 8, 10)
    parada = R.prazo("cantoneiras", data_corte="2026-03-01", coluna_w="2026/53", hoje=hoje)
    assert parada["estacionada"] and parada["dia"] is None
    assert R.prazo("cantoneiras", hoje=hoje)["fonte"] == "sem prazo"
    manual = R.prazo("cantoneiras", data_corte="2026-03-01", coluna_w="2026/53", hoje=hoje, substituicao={"due_date": "2026-11-02"})
    assert manual["dia"] == date(2026, 11, 2) and manual["fonte"] == "Substituição manual"


def test_prazo_mtg2_pelo_picking_e_depois():
    hoje = date(2026, 10, 8)
    p = R.prazo("perfis", data_corte="2026-10-09", picking_semana=42, galvanizacao="2026-10-20", hoje=hoje)
    assert p["fonte"] == "Picking" and p["dia"] == date(2026, 10, 12) and p["provisorio"]
    assert p["instante"] == "2026-10-12T08:00:00+01:00" or p["instante"].startswith("2026-10-12T08:00:00")
    conflito = R.prazo("perfis", data_corte="2026-10-09", picking_semana=42, picking_conflito=True, galvanizacao="2026-10-20", hoje=hoje)
    assert conflito["fonte"] == "Galvanização" and conflito["dia"] == date(2026, 10, 20)
    assert R.prazo("perfis", data_corte="2026-10-09", hoje=hoje)["fonte"] == "Data Corte"
    escolhida = R.prazo("perfis", semana_escolhida=(2026, 44), data_corte="2026-10-09", hoje=hoje)
    assert escolhida["dia"] == date(2026, 11, 1)
    # Ano do Picking: a semana mais perto da Data Corte (dezembro → semana 1 do ano seguinte).
    assert R.inferir_ano_iso(1, date(2026, 12, 20)) == 2027 and R.inferir_ano_iso(52, date(2027, 1, 5)) == 2026
    assert R.prazo("perfis", picking_semana=1, data_corte="2026-12-20", hoje=hoje)["dia"] == date(2027, 1, 4)


def test_picking_da_folha_e_da_linha():
    indice = R.indice_picking([{"row_data": {"values": [1, 266067, 42]}}, {"row_data": {"values": [2, 265001, 41]}},
                               {"row_data": {"values": [3, 265001, 43]}}, {"row_data": {"values": [4, 253377, 0]}}])
    assert indice == {"OF266067": 42, "OF265001": None}
    assert R.picking_da_linha("OF266067", None, indice) == {"semana": 42, "origem": "folha", "conflito": False}
    assert R.picking_da_linha("OF266067", 43, indice)["conflito"]
    assert R.picking_da_linha("OF265001", None, indice)["conflito"]
    assert R.picking_da_linha("OF999999", "40", indice)["semana"] == 40


def test_semana_da_carga():
    hoje = date(2026, 10, 8)  # quinta-feira da semana 41
    assert R.semana_carga("2026-10-01", hoje) == {"celula": (2026, 41), "coluna": "atrasado", "atrasada": True, "semana_iso": "2026-W40"}
    ontem = R.semana_carga("2026-10-06", hoje)
    assert ontem["celula"] == (2026, 41) and ontem["coluna"] == "semana" and ontem["atrasada"]
    assert R.semana_carga("2026-10-20", hoje)["celula"] == (2026, 43)
    assert R.semana_carga("2027-03-01", hoje)["coluna"] == "depois"
    assert R.semana_carga(None, hoje)["celula"] == "sem_prazo"
    assert len(R.semanas_horizonte(hoje)) == 13 and R.semanas_horizonte(date(2026, 12, 31))[1] == (2027, 1)


# ---------------------------------------------------------------- máquina e estado

def test_maquina_efetiva_e_estado():
    escolhas = {"macro:velho:plan:7": {"machine_name": "Ficep XP T4", "resource_id": "r4", "seen": {}},
                "macro:novo:plan:9": {"machine_name": "Peddi 8", "resource_id": "r8", "seen": {"origem": "sugerida"}}}
    carteira = R.maquina_efetiva(["macro:novo:plan:7", "macro:velho:plan:7"], escolhas, "Peddi 8")
    assert carteira == {"maquina": "Ficep XP T4", "resource_id": "r4", "origem": "carteira", "sugerida": False}
    assert R.maquina_efetiva(["macro:novo:plan:9"], escolhas, None)["sugerida"]
    assert R.maquina_efetiva(["x"], escolhas, " Peddi 8 ")["origem"] == "tabela"
    assert R.maquina_efetiva(["x"], escolhas, "Por definir")["maquina"] == ""
    conjunto = R.maquina_efetiva(["x"], {}, "MTG3", "CWA", {"CWA": {"machine_name": "Peddi 6", "resource_id": "r6"}})
    assert conjunto["origem"] == "conjunto" and conjunto["maquina"] == "Peddi 6"
    membros = {"k1": {"decision": "selected"}, "k2": {"decision": "cleared"}}
    antigas = {("OF1", "A"): {"decision": "excluded"}, ("OF1", "*"): {"decision": "selected"}}
    assert R.decisao(["k1"], membros, antigas, "OF1", "A") == "selected"
    assert R.decisao(["k2"], membros, antigas, "OF1", "A") is None  # desmarcação explícita: não herda a antiga
    assert R.decisao(["k3"], membros, antigas, "OF1", "A") == "excluded"
    assert R.decisao(["k3"], membros, antigas, "OF1", "B") == "selected"
    assert [R.estado(d, m) for d, m in (("selected", "P8"), (None, "P8"), ("selected", ""), ("excluded", "P8"))] == \
        ["planeado", "nesting", "sem_maquina", "excluida"]


# ---------------------------------------------------------------- MES

def test_associacao_refeita_dos_registos():
    linhas = [{"plan_key": "s:plan:1", "of": "OF1", "ref": "CWA5", "comprimento": 2168, "perfil": "L70X70X7"},
              {"plan_key": "s:plan:2", "of": "OF1", "ref": "CWA6", "comprimento": 1000, "perfil": "L70X70X7"},
              {"plan_key": "s:plan:3", "of": "OF1", "ref": "CWA6", "comprimento": 1000, "perfil": "L70X70X7"}]
    registos = [{"id": 1, "of": "OF1", "quantidade": 137, "plan_key": "s:plan:1"},
                {"id": 2, "of": "OF1", "quantidade": 5, "plan_key": "velho:plan:1", "ref": "cwa5", "comprimento": 2168.0, "perfil": "L70X70X7 "},
                {"id": 3, "of": "OF1", "quantidade": 5, "plan_key": None, "ref": "CWA6", "comprimento": 1000, "perfil": "L70X70X7"},
                {"id": 4, "of": "OF1", "quantidade": 5, "plan_key": None, "ref": "OUTRA", "comprimento": 1, "perfil": "X"},
                {"id": 5, "of": "OF1", "quantidade": 5, "full_profile": True}]
    a = R.associar_registos(registos, linhas)
    assert a[1]["estado"] == "explicit" and a[2]["estado"] == "technical_unique"
    assert a[3]["estado"] == "ambiguous" and a[4]["estado"] == "unmatched" and a[5]["estado"] == "incomplete"
    por_id = {r["id"]: r for r in registos}
    indice = R.indice_por_linha(a)
    assert indice == {"s:plan:1": [(1, 137), (2, 5)]}
    assert R.ocr_da_operacao("cantoneiras", indice, por_id, "s:plan:1", ["119"], "119") == \
        {"ocr": 142.0, "registos": [1, 2], "bloqueado": False, "motivo": None}
    assert R.ocr_da_operacao("cantoneiras", indice, por_id, "s:plan:2", ["119"], "119")["ocr"] is None
    # Peça com 2.ª operação e registo sem código: operação por confirmar → o OCR não serve.
    duas = R.ocr_da_operacao("cantoneiras", indice, por_id, "s:plan:1", ["119", "1034"], "119")
    assert duas["bloqueado"] and duas["ocr"] is None
    assert R.operacao_registo("perfis", {"maquina": "MAQ.  Abocardar"}, ["corte", "abocardar"]) == "abocardar"
    assert R.operacao_registo("perfis", {"maquina": "DISCO PAV1"}, ["corte"]) == "corte"
    assert R.operacao_registo("cantoneiras", {"operacao": "1034"}, ["119", "1034"]) == "1034"


# ---------------------------------------------------------------- amostra

def _casos(n=60):
    casos = []
    for i in range(n):
        casos.append({"id": f"cantoneiras|OF{i % 7}|R{i}|L|1000|10|1",
                      "estratos": {"setor": "cantoneiras" if i % 3 else "perfis", "estado": "planeado" if i < 2 else "nesting",
                                   "fonte_saldo": "OCR" if i % 10 == 0 else "Excel"},
                      "marcas": ["repetida"] if i in (5, 6) else []})
    return casos


def test_amostra_estratificada_deterministica_e_com_cobertura():
    casos = _casos()
    a = R.escolher_amostra(casos, alvo=20, minimo=5, obrigatorios=[casos[5]["id"], casos[6]["id"]])
    baralhados = casos[:]
    random.Random(7).shuffle(baralhados)
    b = R.escolher_amostra(baralhados, alvo=20, minimo=5, obrigatorios=[casos[6]["id"], casos[5]["id"]])
    assert [c["id"] for c in a] == [c["id"] for c in b]
    ids = {c["id"] for c in a}
    assert {casos[5]["id"], casos[6]["id"]} <= ids and len(a) == 20
    cobertura = R.cobertura(a, casos)
    assert cobertura["estado"]["planeado"] == [2, 2]  # só há 2: ficam os 2
    assert cobertura["fonte_saldo"]["OCR"][0] >= 5 and cobertura["setor"]["perfis"][0] >= 5
    # Enchimento por OF inteira: menos OF diferentes para o mesmo tamanho.
    por_of = R.escolher_amostra(casos, alvo=40, minimo=1, grupo=lambda c: c["id"].split("|")[1])
    soltas = R.escolher_amostra(casos, alvo=40, minimo=1)
    assert len(por_of) == len(soltas) == 40
    assert len({c["id"].split("|")[1] for c in por_of}) <= len({c["id"].split("|")[1] for c in soltas})
    limitada = R.escolher_amostra(casos, alvo=40, minimo=0, grupo=lambda c: c["id"].split("|")[1], por_grupo=3)
    from collections import Counter
    assert max(Counter(c["id"].split("|")[1] for c in limitada).values()) <= 3 and len(limitada) == 21  # 7 OF × 3


def test_identidade_e_repetidas():
    assert R.identidade("cantoneiras", "264157", " cwa5 ", "L70X70X7 ", 2168.0, 336, 1) == "cantoneiras|OF264157|CWA5|L70X70X7|2168|336|1"
    linhas = [{"base_id": "a", "linha_excel": 9}, {"base_id": "a", "linha_excel": 3}, {"base_id": "b", "linha_excel": 1}]
    R.numerar_repetidas(linhas)
    assert [(x["ordem"], x["repetidas"]) for x in linhas] == [(2, 2), (1, 2), (1, 1)]


# ---------------------------------------------------------------- comparação entre corridas

def _ev(valor, origem=None, diferenca=None):
    return {"casos": [{"id": "x", "setor": "cantoneiras", "marcas": [], "esperado": {"maquina": "Peddi 8"},
                       "origem": origem or {"contador": 1},
                       "verificacoes": [{"codigo": "C06", "campo": "horas", "pagina": "carga", "valor": valor,
                                         "esperado": 0.3, "diferenca": diferenca, "defeito": "F02" if diferenca else None}]}]}


def test_comparar_explica_ou_nao_cada_mudanca():
    efeitos = [{"verificacao": "C06", "campo": "horas", "filtro": {"maquina": "peddi"}, "descricao": "F02: Excel", "fecha": True}]
    assert R.comparar(_ev(0.43, diferenca=0.13), _ev(0.43, diferenca=0.13), efeitos)["diferencas"] == []
    explicada = R.comparar(_ev(0.43, diferenca=0.13), _ev(0.3), efeitos)
    assert explicada["resumo"] == {"explicada": 1} and explicada["diferencas"][0]["efeito"] == "F02: Excel"
    assert R.comparar(_ev(0.43, diferenca=0.13), _ev(0.3), [])["resumo"] == {"inexplicada": 1}
    # O efeito prometia fechar a diferença e ela continua: não explica.
    assert R.comparar(_ev(0.43, diferenca=0.13), _ev(0.5, diferenca=0.2), efeitos)["resumo"] == {"inexplicada": 1}
    assert R.comparar(_ev(0.43), _ev(0.5, origem={"contador": 2}), [])["resumo"] == {"origem mudou": 1}
    assert R.comparar(_ev(0.43), {"casos": []})["resumo"] == {"só antes": 1}


def test_ficheiro_de_efeitos_da_etapa1_explica_pelo_defeito_de_antes():
    import json
    from pathlib import Path
    efeitos = json.loads((Path(A.ROOT) / "docs/auditoria-fluxo-2026-10-08/efeitos-etapa1.json").read_text())["efeitos"]
    assert {e["defeito"] for e in efeitos} >= {"F01", "F02", "F05", "F08", "F09", "F06"}
    antes, depois = _ev(0.43, diferenca=0.13), _ev(0.3)
    antes["casos"][0]["verificacoes"][0]["defeito"] = "F01"
    resultado = R.comparar(antes, depois, efeitos)
    assert resultado["resumo"] == {"explicada": 1} and resultado["diferencas"][0]["efeito"].startswith("F01")


# ---------------------------------------------------------------- C15

def test_mapa_do_preenchimento_automatico_confirma_no_codigo():
    assert len(R.PREENCHIMENTO) >= 15
    assert all({"campo", "fontes", "regra", "onde", "codigo"} <= set(e) for e in R.PREENCHIMENTO)
    textos = {"app/cpis_copies.py": "x\ndef latest_first(rows):\n", "app/planning_hub.py": "latest_first(rows)"}
    out = R.verificar_codigo(textos)
    primeira = out[0]
    assert primeira["estado"] == "confirmada" and primeira["confirmacao"][0]["linhas"] == [2]
    assert out[1]["estado"] == "por rever" and not out[1]["confirmacao"][0]["existe"]


# ---------------------------------------------------------------- verificações por caso e páginas

def _caso(**paginas):
    return {
        "id": "cantoneiras|OF264095|A1|L70X70X7|1000|10|1", "setor": "cantoneiras", "of": "OF264095", "referencia": "A1",
        "perfil": "L70X70X7", "comprimento_mm": 1000.0, "qtd": 10.0, "repetidas": 1, "marcas": [], "linha_excel": 7, "_aberta": True,
        "origem": {"ocr_registos": [], "contador": 0.0, "ocr": None, "maquina_tabela": "Peddi 8"},
        "esperado": {"saldo": 10.0, "metros": 10.0, "kg": 73.1, "kg_origem": "geometria", "maquina": "Ficep XP T4", "recurso": "r4",
                     "horas": 10 / 120, "horas_detalhe": {"fator": 1}, "estado": "planeado", "tipo_carga": "no plano",
                     "prazo_dia": date(2026, 10, 1), "prazo_fonte": "Data Corte", "excesso": 0.0,
                     "semana_carga": {"celula": (2026, 41), "semana_iso": "2026-W40", "atrasada": True}},
        "estratos": {"estado": "planeado", "fonte_saldo": "Excel"},
        "paginas": {"tabela": {"remaining": 10.0, "planning_remaining": 8.0, "remaining_m": 10.0, "machine": "Peddi 8",
                               "rate_source": "Histórico", "ocr_registos": []},
                    "carteira": {"pieces": 8.0, "metres": 8.0, "kg": None, "machine": "Ficep XP T4", "priority_day": "2026-10-01",
                                 "status": {"planeado": True, "nesting": False, "sem_maquina": False}},
                    "carga": {"remaining": 10.0, "length_mm": 1000.0, "load_hours": 0.117, "load_basis": "documental",
                              "kind": "no plano", "priority_day": "2026-10-01", "weight_kg": 0.0, "_celula": [2026, 41], "_recurso": "r4"},
                    **paginas},
    }


def test_verificacoes_ligam_cada_diferenca_a_um_defeito():
    v = {(x["codigo"], x["campo"], x["pagina"]): x for x in A.verificar_caso(_caso(), datetime(2026, 10, 8, 10, tzinfo=timezone.utc))}
    assert v[("C02", "saldo", "tabela")]["diferenca"] is None
    assert v[("C02", "saldo_a_planear", "tabela")]["defeito"] == "F05"
    assert v[("C02", "saldo", "carteira")]["defeito"] == "F05"  # a Carteira mostra o saldo da camada v2
    assert v[("C04", "kg", "carteira")]["defeito"] == "F08"  # sem peso na tabela, calculável pela geometria
    assert v[("C04", "kg", "carga")]["defeito"] == "F08"
    assert v[("C06", "horas", "carga")]["defeito"] == "F01"  # horas da Peddi 8 (Tabela) na XP T4 (Carteira)
    assert v[("C05", "maquina", "carteira")]["diferenca"] is None
    assert v[("C07", "celula", "carga")]["diferenca"] is None and v[("C08", "tipo", "carga")]["diferenca"] is None
    assert v[("C13", "saldo_planeado", "carteira")]["defeito"] == "F05"
    sem_paginas = A.verificar_caso(_caso(tabela=None, carteira=None, carga=None), datetime(2026, 10, 8, tzinfo=timezone.utc))
    assert [(x["codigo"], x["campo"]) for x in sem_paginas] == [("C01", "presente"), ("C01", "presente")]


def test_paginas_so_get_com_espera_quando_stale(monkeypatch):
    p = A.Paginas("http://127.0.0.1:9", intervalo=0, maximo=5)
    respostas = iter([({"stale": True}, None), ({"stale": True}, None), ({"x": 1}, None)])
    monkeypatch.setattr(p, "_get", lambda caminho, params: next(respostas))
    monkeypatch.setattr(A.relogio, "sleep", lambda s: None)
    assert p.get("/a") == ({"x": 1}, None)
    pedidos = []

    class Falha(Exception):
        pass

    def abrir(pedido, timeout):
        pedidos.append(pedido.get_method())
        raise A.urllib.error.HTTPError(pedido.full_url, 503, "x", {}, None)
    monkeypatch.setattr(A.urllib.request, "urlopen", abrir)
    q = A.Paginas("http://127.0.0.1:9", intervalo=0, maximo=10)
    for _ in range(5):
        q.get("/b")
    assert pedidos == ["GET"] * 3 and q.falhas_5xx == 3 and not q.disponivel()
    assert q.get("/b") == (None, "parado: 3 respostas 5xx")


def _origem_sintetica():
    snap = {"snapshot_id": "mtg_aaaaaaaaaaaaaaaa", "loaded_at": "2026-10-02T12:51:22+00:00", "source_filename": "Met3.xlsm"}
    linha = lambda n, ref, qtd, maq, extra=None: {  # noqa: E731
        "source_line_id": f"mtg_aaaaaaaaaaaaaaaa:plan:{n}", "excel_row": n, "production_order_no": "OF264157", "component_ref": ref,
        "profile_type": "L70X70X7", "material_type": "Cantoneira", "length_mm": 2168, "quantity_planned": qtd, "closed_x": False,
        "cut_date": None, "cutting_machine": None, "presentes": [],
        "r": {"QTD": qtd, "Maq.": None, "Qtd falta": qtd, "Máquina Corte": maq, "Data Corte": "2026-08-10T00:00:00", "W": 41,
              "Mt\\h": 120, "1ª Oper.": 119, "2ª Oper.": 0, **(extra or {})}}
    origem = {
        "geracao": {"id": 6804, "created_at": "2026-10-07T12:39:02+00:00", "snapshot": snap}, "snapshot": snap["snapshot_id"],
        "linhas": [linha(1, "CWA5", 336, "Peddi 8"), linha(2, "CWA6", 10, "Por definir"), linha(3, "CWA7", 5, "Peddi 8", {"Fechado": "X"})],
        "folhas": {"Tabela pesos": [{"row_data": {"values": [None, "L70X70X7", 7.38]}}]},
        "velocidades": {"Peddi 8": {"valor": 120}}, "cpis": [], "conjuntos": [], "aliases": {}, "refs": {}, "historico": {},
        "app": {"macro:mtg_aaaaaaaaaaaaaaaa:plan:1": {"ativa": True, "theoretical_hours": 0.431, "rate_source": "Histórico", "machine": "Peddi 8"},
                "macro:mtg_aaaaaaaaaaaaaaaa:plan:2": {"ativa": True}},
        "membros": [{"member_key": "macro:mtg_aaaaaaaaaaaaaaaa:plan:1", "decision": "selected"}], "antigas": [], "escolhas": [],
        "registos": [{"id": 4475, "sheet_uid": "s1", "row_index": 0, "sheet_date": "2026-10-05", "machine": "Peddi 8",
                      "production_order": "264157", "model_ref": "CWA5", "matched_plan_key": "mtg_aaaaaaaaaaaaaaaa:plan:1",
                      "quantity": 319, "length_mm": 2168, "profile_type": "L70X70X7", "full_profile": False, "plan_identity": None,
                      "operacao": None, "image_sha256": "i1", "source_filename": "a.pdf", "source_page": 2}],
    }
    comum = {"snapshots": {}, "objetos": [{"id": "r8", "kind": "resource", "name": "Peddi 8", "area": "cantoneiras",
                                           "definition": {"aliases": [{"area": "cantoneiras", "name": "Peddi 8"}]}}],
             "definicoes": {}, "drive": [{"area": "cantoneiras", "remote_filename": "SAIDA/Met3.xlsm", "remote_sha256": "b" * 64,
                                          "remote_modified_at": datetime(2026, 10, 7, 7, 5, tzinfo=timezone.utc), "checked_at": None}],
             "manuais": [], "politicas": {}, "substituicoes": {}}
    return origem, comum


class _Ligacao:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a, **k):
        return self

    def commit(self):
        pass


def _paginas_falsas(caminho, params=None):
    if caminho.endswith("/raw/linhas"):
        return {"total": 2, "rows": [
            {"key": "macro:mtg_aaaaaaaaaaaaaaaa:plan:1", "values": {"of": "OF264157", "operation": "119", "remaining": 17.0,
             "planning_remaining": 17.0, "remaining_m": 36.856, "machine": "Peddi 8", "rate_source": "Histórico"},
             "operations": [{"operation": "119", "ocr_records": [{"record_id": 4475}]}]},
            {"key": "macro:mtg_aaaaaaaaaaaaaaaa:plan:2", "values": {"of": "OF264157", "operation": "119", "remaining": 10.0,
             "planning_remaining": 10.0, "remaining_m": 21.68, "machine": "Por definir"}, "operations": []}]}, None
    if caminho.endswith("/carteira/membros"):
        return {"items": [
            {"key": "macro:mtg_aaaaaaaaaaaaaaaa:plan:1", "pieces": 17.0, "metres": 36.86, "kg": 272.0, "machine": "Peddi 8",
             "priority_day": "2026-08-10", "status": {"planeado": True, "nesting": False, "sem_maquina": False}},
            {"key": "macro:mtg_aaaaaaaaaaaaaaaa:plan:2", "pieces": 10.0, "metres": 21.68, "kg": 160.0, "machine": "",
             "priority_day": "2026-08-10", "status": {"planeado": False, "nesting": False, "sem_maquina": True},
             "suggested": {"resource_id": "r8"}}]}, None
    if caminho.endswith("/carga/operacoes"):
        return {"operations": [
            {"reference": "CWA5", "profile": "L70X70X7", "length_mm": 2168.0, "phase": "principal", "remaining": 17.0,
             "load_hours": 0.431, "load_basis": "documental", "hours_origin": "Histórico", "kind": "no plano", "weight_kg": 272.0,
             "priority_day": "2026-08-10"},
            {"reference": "CWA6", "profile": "L70X70X7", "length_mm": 2168.0, "phase": "principal", "remaining": 10.0,
             "load_hours": 21.68 / 120, "load_basis": "estimada", "kind": "a vencer, máquina sugerida", "weight_kg": 160.0,
             "priority_day": "2026-08-10"}]}, None
    if caminho.endswith("/setor/carga"):
        return {"machines": [{"id": "r8", "name": "Peddi 8", "weeks": [{"plan": 0.0}]}],
                "totals": [{"id": "r8", "pieces": 27, "metres": 58.5, "weight_kg": 432.0, "weight_unknown": 0}],
                "elsewhere": {"operations": 0}}, None
    if caminho.endswith("/carteira/kpis"):
        return {"summary": [{"code": "planeado", "lines": 1, "metres": 36.9}],
                "panels": [{"machines": [{"id": "r8", "base": {"hours": 0.4}}]}]}, None
    if caminho.endswith("/setor/quadro"):
        return {"source": {"kind": "automatica", "missing": []},
                "machines": [{"id": "r8", "boxes": [{"of": "OF264157", "hours": 0.31}]}]}, None
    if caminho.endswith("/planeamento/api/carteira"):
        return {"list_totals": {"lines": 2, "pieces": 27, "metres": 58.5, "tonnes": 0.43, "weight_unknown": 0, "status": {}}}, None
    return None, "HTTP 404"


def test_corrida_completa_com_origem_e_paginas_falsas(monkeypatch, tmp_path):
    origem, comum = _origem_sintetica()
    import scripts.audit_readonly as ro
    monkeypatch.setattr(A, "limpeza_ativa", lambda: False)
    monkeypatch.setattr(A, "carregar_env", lambda caminho: "falso")
    monkeypatch.setattr(ro, "planning_db", lambda *a, **k: _Ligacao())
    monkeypatch.setattr(A, "ler_comum", lambda c: comum)
    monkeypatch.setattr(A, "ler_setor", lambda c, s, cm: origem)
    monkeypatch.setattr(A, "ler_v2", lambda: {"fontes": [], "snapshots": [], "erro": None})
    monkeypatch.setattr(A, "identidades_v2", lambda c, s: set())
    monkeypatch.setattr(A.Paginas, "get", lambda self, caminho, params=None: (self.__dict__.__setitem__("pedidos", self.pedidos + 1),
                                                                             _paginas_falsas(caminho, params))[1])
    monkeypatch.setattr(A, "hoje_lisboa", lambda: date(2026, 10, 8))
    assert A.main(["--tag", "teste", "--setores", "cantoneiras", "--saida", str(tmp_path), "--prever", "--amostra", "10"]) == 0
    import json
    evidencia = json.loads(next((tmp_path / "evidencia").glob("teste-*.json")).read_text())
    casos = {c["referencia"]: c for c in evidencia["casos"]}
    assert set(casos) == {"CWA5", "CWA6"}  # a linha fechada (Fechado = X) fica fora
    cwa5 = {(v["codigo"], v["campo"], v["pagina"]): v for v in casos["CWA5"]["verificacoes"]}
    assert casos["CWA5"]["esperado"]["saldo"] == 17.0 and cwa5[("C02", "saldo", "carga")]["diferenca"] is None
    assert cwa5[("C06", "horas", "carga")]["defeito"] == "F02"  # Histórico 0,431 h contra Excel 0,307 h
    assert cwa5[("C14", "registos_ocr", "tabela")]["diferenca"] is None
    cwa6 = {(v["codigo"], v["campo"], v["pagina"]): v for v in casos["CWA6"]["verificacoes"]}
    assert cwa6[("C08", "tipo", "carga")]["diferenca"] is None  # sem máquina → sugerida na Carga
    assert cwa6[("C06", "horas", "carga")]["diferenca"] is None  # horas na sugerida pela mesma regra (Excel 120 m/h)
    assert evidencia["frescura"]["drive"][0]["defeito"] == "F16"
    assert evidencia["prever"]["cantoneiras"]["horas_por_maquina"][0]["maquina"] == "Peddi 8"
    assert evidencia["fechos"]["cantoneiras"]["gantt_vs_carga"]["linhas"][0]["diferenca_h"] == pytest.approx(0.31 - 0.431, abs=0.01)
    relatorio = (tmp_path / "RELATORIO-teste.md").read_text()
    assert "Três exemplos" in relatorio and "C15" in relatorio


def test_relatorio_e_exemplo_sem_base():
    caso = _caso()
    caso["verificacoes"] = A.verificar_caso(caso, datetime(2026, 10, 8, tzinfo=timezone.utc))
    ex = A.exemplo(caso)
    assert ex["titulo"].startswith("cantoneiras · OF264095") and any("F05" in t for t in ex["texto"])
    ev = {"manifesto": {"tag": "teste", "quando_lisboa": "08/10/2026 09:00", "commit_auditoria": "abc", "commit_app": "def"},
          "frescura": {"snapshots": {"cantoneiras": {"geracao": 1, "snapshot": "mtg_x", "carregado": "2026-10-02", "idade_dias": 6.0}},
                       "drive": [{"setor": "cantoneiras", "ficheiro_remoto": "SAIDA/x.xlsm", "modificado": "2026-10-07",
                                  "mais_recente_por_importar": True}], "v2": {"snapshots": ["mtg_y"]}},
          "amostra": {"casos": 1, "populacao": 1, "obrigatorias": 1, "cobertura": {"estado": {"planeado": [1, 1]}}},
          "contagens": {"C02·saldo·carteira": {"casos": 1, "batem": 0, "diferentes": 1, "defeitos": {"F05": 1}}},
          "resumo": {"diferencas": 1, "inexplicadas": 0}, "exemplos": [ex], "fechos": {}, "associacoes": {}, "populacao": {},
          "manuais": [], "c15": R.verificar_codigo({}), "pedidos": {"total": 3, "erros": 0, "5xx": 0, "ms_medio": 10}}
    texto = A.relatorio(ev)
    assert "F16" in texto and "| C02 | saldo | carteira | 1 | 0 | 1 | F05 1 |" in texto and "C15" in texto
