"""Auditoria reproduzível do fluxo de dados do planeamento (Etapa 0, 08/10/2026). Só leitura.

Recalcula a partir da origem (Excel importado, folhas OCR validadas do MES, decisões da Carteira, Definições)
o que cada página devia mostrar e compara com o que as páginas mostram (Tabela, Carteira, KPIs, Carga, Gantt).
As regras estão em `auditoria_fluxo_regras.py` (funções puras, com testes).

Uso (na raiz do projeto ou numa worktree; numa worktree o .env vem de --env):
    .venv/bin/python scripts/auditoria_fluxo.py --tag antes --prever
    .venv/bin/python scripts/auditoria_fluxo.py --tag teste --limite 20 --sem-gantt
    .venv/bin/python scripts/auditoria_fluxo.py --tag depois \\
        --comparar docs/auditoria-fluxo-2026-10-08/evidencia/antes-20261008T0900.json \\
        --efeitos docs/auditoria-fluxo-2026-10-08/efeitos-etapa1.json

Garantias:
- base: transação READ ONLY com tempo limite (scripts/audit_readonly.py); só SELECT; só linhas ativas e só os
  campos necessários;
- páginas: só GET, um de cada vez, 0,2 s entre pedidos, 60 s de limite, no máximo 800 pedidos, pára à 3.ª
  resposta 5xx; resposta «stale» → espera até 3 × 10 s;
- não corre enquanto a limpeza da base (planning-retention-20261007) estiver ativa;
- nunca imprime segredos do .env.
Saída: docs/auditoria-fluxo-2026-10-08/evidencia/<tag>-<AAAAMMDDThhmm>.json (comprimido em .json.gz acima de
5 MB) e docs/auditoria-fluxo-2026-10-08/RELATORIO-<tag>.md.
"""
from __future__ import annotations

import argparse
import gzip
import re
import json
import os
import subprocess
import sys
import time as relogio
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import auditoria_fluxo_regras as R  # noqa: E402

PRODUCAO = Path("/home/luis/projects/planeamento")
SETORES = ("cantoneiras", "perfis")
APP_MES = {"perfis": "kanban-mes-mtg2", "cantoneiras": "kanban-mes"}
DATASET = {"perfis": "ds-met2-perfis", "cantoneiras": "ds-2638099daddc474e"}
LIMPEZA = "planning-retention-20261007.service"
SAIDA = ROOT / "docs" / "auditoria-fluxo-2026-10-08"
MAX_JSON = 5 * 1024 * 1024
CAMPOS_EXCEL = {
    "cantoneiras": ["QTD", "Comp.", "Maq.", "Qtd falta", "Máquina Corte", "Data Corte", "W", "Fechado", "Mt\\h",
                    "1ª Oper.", "2ª Oper.", "Tipo de perfil", "Data Galvanização", "h teor. Falta", "Peso un. Kg"],
    "perfis": ["QTD [un,]", "QTD", "Ser.", "Qtd em Falta", "Máquina Corte", "Data Corte", "Picking", "Data Galvanização",
               "Fechado", "Aborc.", "Aboc.", "Ø Externo [mm]", "Largura (w) [mm]", "Altura (h) [mm]",
               "Espessura (t) [mm]", "Qual."],
}
OBRIGATORIAS = {"cantoneiras": ["QTD", "Maq.", "Qtd falta", "Máquina Corte", "Data Corte", "Mt\\h", "1ª Oper."],
                "perfis": ["QTD [un,]", "Ser.", "Qtd em Falta", "Máquina Corte", "Data Corte"]}
VALORES_APP = ("remaining", "planning_remaining", "planning_balance_origin", "theoretical_hours", "rate_source",
               "applied_rate_value", "machine", "weight_unit", "section_unit", "quantity_required", "ocr_quantity",
               "sku_family", "length_mm", "of")
MARCAS_RARAS = {"repetida", "OCR>QTD", "OCR<Excel"}


# ---------------------------------------------------------------- ambiente e segurança

def carregar_env(caminho: Path) -> str:
    """Variáveis do .env (sem as imprimir). Numa worktree não há .env: usa-se o da produção (--env)."""
    proprio = ROOT / ".env"
    fonte = proprio if proprio.is_file() else caminho
    if not fonte.is_file():
        raise SystemExit(f"Sem ficheiro .env em {proprio} nem em {caminho}: indica --env.")
    for linha in fonte.read_text().splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            k, v = linha.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return str(fonte)


def limpeza_ativa() -> bool:
    try:
        r = subprocess.run(["systemctl", "--user", "is-active", LIMPEZA], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.stdout.strip() in ("active", "activating")


def commit(pasta: Path) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(pasta), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def hoje_lisboa() -> date:
    return datetime.now(R.LISBOA).date()


# ---------------------------------------------------------------- páginas (só GET)

class Paginas:
    """GET sequenciais e limitados à app em produção."""

    def __init__(self, base: str, *, intervalo=0.2, limite_s=60, maximo=800):
        self.base, self.intervalo, self.limite_s, self.maximo = base.rstrip("/"), intervalo, limite_s, maximo
        self.pedidos, self.falhas_5xx, self.ultimo, self.registo = 0, 0, 0.0, []

    def disponivel(self) -> bool:
        return self.pedidos < self.maximo and self.falhas_5xx < 3

    def get(self, caminho: str, params: dict | list | None = None):
        """(dados, erro). Resposta «stale» → espera 10 s e repete, até 3 vezes (fica marcada se continuar)."""
        for tentativa in range(4):
            dados, erro = self._get(caminho, params)
            if erro or not isinstance(dados, dict) or not dados.get("stale") or tentativa == 3:
                if isinstance(dados, dict) and dados.get("stale"):
                    dados["_stale_depois_de_esperar"] = True
                return dados, erro
            relogio.sleep(10)
        return None, "stale"

    def _get(self, caminho, params):
        if self.falhas_5xx >= 3:
            return None, "parado: 3 respostas 5xx"
        if self.pedidos >= self.maximo:
            return None, "limite de pedidos atingido"
        espera = self.intervalo - (relogio.monotonic() - self.ultimo)
        if espera > 0:
            relogio.sleep(espera)
        url = self.base + caminho + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
        pedido = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
        inicio = relogio.monotonic()
        self.pedidos += 1
        estado, erro, dados = None, None, None
        try:
            with urllib.request.urlopen(pedido, timeout=self.limite_s) as resposta:
                estado = resposta.status
                dados = json.loads(resposta.read().decode())
        except urllib.error.HTTPError as exc:
            estado = exc.code
            try:
                corpo = json.loads(exc.read().decode())
                detalhe = corpo.get("detail") or corpo.get("error") or corpo
            except Exception:
                detalhe = ""
            erro = f"HTTP {exc.code}: {str(detalhe)[:200]}"
            if exc.code >= 500:
                self.falhas_5xx += 1
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            erro = f"{type(exc).__name__}: {exc}"[:200]
        self.ultimo = relogio.monotonic()
        self.registo.append({"caminho": caminho, "params": params if isinstance(params, dict) else dict(params or []),
                             "estado": estado, "ms": round((self.ultimo - inicio) * 1000), "erro": erro})
        return dados, erro


# ---------------------------------------------------------------- origem (SQL só de leitura)

def _existe(c, tabela: str) -> bool:
    from scripts.audit_readonly import query
    return bool(query(c, "SELECT to_regclass(%s) AS t", (tabela,))[0]["t"])


def ler_comum(c) -> dict:
    """Snapshots, decisões de recursos/taxas, Definições, Drive e registos manuais (para os dois setores)."""
    from scripts.audit_readonly import query
    snaps = query(c, "SELECT DISTINCT ON (dataset_id) dataset_id, snapshot_id, source_filename, source_sha256, loaded_at "
                     "FROM audit_mtg.snapshots WHERE dataset_id = ANY(%s) ORDER BY dataset_id, loaded_at DESC, snapshot_id DESC",
                  (list(DATASET.values()),))
    objetos = query(c, "SELECT id::text, kind, name, area, definition FROM planning_mtg.raw_objects "
                       "WHERE kind = ANY(%s) AND NOT archived", (["resource", "rate"],))
    definicoes = {r["area"]: r["definition"] for r in query(c, "SELECT area, definition FROM planning_mtg.sector_settings")}
    drive = query(c, "SELECT area, checked_at, remote_sha256, remote_modified_at, remote_filename, error "
                     "FROM planning_mtg.raw_drive_observations")
    manuais = []
    if _existe(c, "planning_mtg.field_state"):
        manuais = query(c, "SELECT need_id::text, scope, field, value, human_decision, decided_at, requires_review "
                           "FROM planning_mtg.field_state WHERE human_decision IS NOT NULL ORDER BY decided_at")
    politicas, substituicoes = {}, {}
    if _existe(c, "planning_mtg.sector_priority_policies"):
        politicas = {r["area"]: r["definition"] for r in query(c, "SELECT area, definition FROM planning_mtg.sector_priority_policies")}
    if _existe(c, "planning_mtg.sector_priority_overrides"):
        for r in query(c, "SELECT * FROM planning_mtg.sector_priority_overrides"):
            substituicoes[(r["area"], r["production_order_no"], r["reference"])] = r.get("definition") or r
    return {"snapshots": {r["dataset_id"]: r for r in snaps}, "objetos": objetos, "definicoes": definicoes,
            "drive": drive, "manuais": manuais, "politicas": politicas, "substituicoes": substituicoes}


def ler_setor(c, setor: str, comum: dict) -> dict:
    """Tudo o que a auditoria lê da origem para um setor."""
    from scripts.audit_readonly import query
    g = query(c, "SELECT id, created_at, metadata->'snapshot' AS snapshot FROM planning_mtg.raw_generations "
                 "WHERE dataset = %s ORDER BY id DESC LIMIT 1", (f"planning:{setor}",))
    if not g:
        raise SystemExit(f"Sem geração planning:{setor}.")
    g = g[0]
    snap = (g["snapshot"] or {}).get("snapshot_id")
    linhas = query(c, """SELECT source_line_id, excel_row, production_order_no, component_ref, profile_type, material_type,
                                length_mm, quantity_planned, closed_x, cut_date, cutting_machine,
                                coalesce((SELECT jsonb_object_agg(k, row_data->k) FROM unnest(%s::text[]) k
                                          WHERE row_data ? k), '{}'::jsonb) AS r,
                                (SELECT array_agg(k) FROM unnest(%s::text[]) k WHERE row_data ? k) AS presentes
                           FROM raw_mtg.plan_production_rows WHERE snapshot_id = %s AND closed_x IS NOT TRUE""",
                   (CAMPOS_EXCEL[setor], OBRIGATORIAS[setor], snap))
    presentes = Counter(k for l in linhas for k in (l["presentes"] or []))
    faltam = [k for k in OBRIGATORIAS[setor] if linhas and presentes[k] == 0]
    if faltam:
        raise SystemExit(f"{setor}: colunas do Excel em falta no snapshot {snap}: {', '.join(faltam)}. Rever a auditoria.")
    outras = {d: s["snapshot_id"] for d, s in comum["snapshots"].items()}
    mtg3, mtg2 = outras.get(DATASET["cantoneiras"]), outras.get(DATASET["perfis"])
    folhas = defaultdict(list)
    for snapshot, nomes in ((mtg3, ["Tabela pesos"]), (snap if setor == "perfis" else mtg2, ["AreaSecaoCorte", "CapacidadeMáquinas", "Picking"])):
        if snapshot:
            for r in query(c, "SELECT sheet_name, excel_row, row_data FROM raw_mtg.other_sheet_rows "
                              "WHERE snapshot_id = %s AND sheet_name = ANY(%s) ORDER BY sheet_name, excel_row", (snapshot, nomes)):
                folhas[r["sheet_name"]].append(r)
    velocidades = {}
    if setor == "cantoneiras":
        vel = query(c, "SELECT row_data->>'Máquina Corte' AS m, row_data->>%s AS s, row_data->>'Data Corte' AS d "
                       "FROM raw_mtg.plan_production_rows WHERE snapshot_id = %s", ("Mt\\h", snap))
        carregado = (g["snapshot"] or {}).get("loaded_at")
        ate = R.dia(carregado) or hoje_lisboa()
        velocidades = R.velocidades_recentes([{"Máquina Corte": r["m"], "Mt\\h": r["s"], "Data Corte": r["d"]} for r in vel], ate)
    cpis = query(c, """SELECT c.production_order_no, c.status, c.record_date, c.delivery_date, c.planned_finish_date,
                              s.loaded_at FROM raw_mtg.cpis_rows c JOIN audit_mtg.snapshots s ON s.snapshot_id = c.snapshot_id
                        WHERE c.snapshot_id = ANY(%s)""", ([x for x in (mtg3, mtg2) if x],))
    app = query(c, """SELECT m.row_key, coalesce(m.planning_active, (v.values_json->>'planning_active')::boolean) AS ativa,
                             m.planning_order, """ + ", ".join(f"v.values_json->'{k}' AS \"{k}\"" for k in VALORES_APP) + """
                        FROM planning_mtg.raw_members m JOIN planning_mtg.raw_contents v ON v.hash = m.content_hash
                       WHERE m.dataset = %s AND m.first_generation <= %s AND (m.last_generation IS NULL OR m.last_generation > %s)
                         AND m.planning_active IS NOT FALSE""", (f"planning:{setor}", g["id"], g["id"]))
    membros = query(c, "SELECT member_key, production_order_no, reference, decision, revision FROM planning_mtg.sector_member_selection "
                       "WHERE area = %s", (setor,)) if _existe(c, "planning_mtg.sector_member_selection") else []
    antigas = query(c, "SELECT production_order_no, reference, decision FROM planning_mtg.sector_selection WHERE area = %s",
                    (setor,)) if _existe(c, "planning_mtg.sector_selection") else []
    escolhas = query(c, "SELECT member_key, production_order_no, reference, resource_id, machine_name, seen "
                        "FROM planning_mtg.sector_member_machine WHERE area = %s", (setor,)) \
        if _existe(c, "planning_mtg.sector_member_machine") else []
    conjuntos = query(c, "SELECT name, families, resource_id, machine_name FROM planning_mtg.sector_family_sets "
                         "WHERE area = %s AND NOT archived", (setor,)) if _existe(c, "planning_mtg.sector_family_sets") else []
    # Aliases (chaves de importações anteriores) só das OF com decisões gravadas por chave antiga.
    atuais = {r["row_key"] for r in app}
    antigas_chaves = sorted({r["member_key"] for r in [*membros, *escolhas]} - atuais)
    aliases = {}
    if antigas_chaves:
        ofs = sorted({r["production_order_no"] for r in [*membros, *escolhas] if r["member_key"] in antigas_chaves})
        for r in query(c, """SELECT m.row_key, CASE WHEN v.detail_source_hash IS NULL THEN v.detail->'selection_aliases'
                                                    ELSE s.detail->'selection_aliases' END AS aliases
                               FROM planning_mtg.raw_members m JOIN planning_mtg.raw_contents v ON v.hash = m.content_hash
                               LEFT JOIN planning_mtg.raw_contents s ON s.hash = v.detail_source_hash
                              WHERE m.dataset = %s AND m.first_generation <= %s AND (m.last_generation IS NULL OR m.last_generation > %s)
                                AND m.planning_order = ANY(%s)""", (f"planning:{setor}", g["id"], g["id"], ofs)):
            aliases[r["row_key"]] = list(r["aliases"] or [])
    registos = query(c, """SELECT p.id, p.sheet_uid, p.row_index, p.sheet_date, p.machine, p.production_order, p.model_ref,
                                  p.matched_plan_key, p.quantity, p.length_mm, p.profile_type, p.full_profile, p.validated_at,
                                  p.extra->'plan_identity' AS plan_identity,
                                  coalesce(p.extra->>'operation_code', p.extra->>'operacao') AS operacao,
                                  v.image_sha256, v.source_filename, v.source_page
                             FROM mes_kanban.production_records p JOIN mes_kanban.validated_sheets v USING (sheet_uid)
                            WHERE v.source_app = %s ORDER BY p.id""", (APP_MES[setor],))
    refs = defaultdict(list)
    if registos:
        for r in query(c, "SELECT production_record_id, plan_key, component_ref, length_mm, profile_type, assumed_quantity "
                          "FROM mes_kanban.production_record_plan_refs WHERE production_record_id = ANY(%s) ORDER BY plan_key",
                       ([r["id"] for r in registos],)):
            refs[r["production_record_id"]].append(r)
    chaves_hist = sorted({r["matched_plan_key"] for r in registos if r["matched_plan_key"] and not r["plan_identity"]})
    historico = defaultdict(list)
    if chaves_hist:
        for r in query(c, "SELECT plan_key, production_order_no, component_ref, profile_type, length_mm "
                          "FROM analytics_mtg.kanban_plan_lines WHERE plan_key = ANY(%s)", (chaves_hist,)):
            historico[r["plan_key"]].append(r)
    # A associação MES da app compara com todas as linhas do retrato (também as fechadas) das OF com registos:
    # uma linha fechada com a mesma referência, comprimento e perfil torna a associação ambígua.
    ofs_mes = sorted({x for r in registos for x in (R.of_normalizada(r["production_order"]),) if x})
    todas = query(c, """SELECT source_line_id, production_order_no, component_ref, profile_type,
                               coalesce(length_mm::text, row_data->>'Comp.') AS comp
                          FROM raw_mtg.plan_production_rows
                         WHERE snapshot_id = %s AND ('OF' || regexp_replace(trim(production_order_no), '^OF[ ._-]*', '', 'i')) = ANY(%s)""",
                  (snap, ofs_mes)) if ofs_mes else []
    return {"geracao": g, "snapshot": snap, "linhas": linhas, "folhas": dict(folhas), "velocidades": velocidades, "cpis": cpis,
            "app": {r["row_key"]: r for r in app}, "membros": membros, "antigas": antigas, "escolhas": escolhas,
            "conjuntos": conjuntos, "aliases": aliases, "registos": registos, "refs": refs, "historico": historico,
            "todas": todas}


def ler_v2() -> dict:
    """Fontes selecionadas da camada v2 (base de pesquisa) e as identidades das linhas desses retratos."""
    out = {"fontes": None, "erro": None, "snapshots": []}
    try:
        from scripts.audit_readonly import research_db, query
        with research_db(timeout_ms=60_000) as c:
            fontes = query(c, "SELECT * FROM consulta_v2.fontes_selecionadas")
        out["fontes"] = json.loads(json.dumps(fontes, default=str))
        out["snapshots"] = sorted({v for f in out["fontes"] for v in f.values()
                                   if isinstance(v, str) and re.fullmatch(r"mtg2?_[0-9a-f]{16}", v)})
    except Exception as exc:  # a base de pesquisa pode não estar acessível: fica dito no relatório
        out["erro"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    return out


def identidades_v2(c, snapshots) -> set:
    from scripts.audit_readonly import query
    if not snapshots:
        return set()
    rows = query(c, "SELECT snapshot_id, production_order_no, component_ref, profile_type, length_mm, quantity_planned, "
                    "row_data->>'Comp.' AS comp, row_data->>'QTD [un,]' AS qtd2 FROM raw_mtg.plan_production_rows WHERE snapshot_id = ANY(%s)",
                 (list(snapshots),))
    out = set()
    for r in rows:
        setor = "perfis" if r["snapshot_id"].startswith("mtg2_") else "cantoneiras"
        comp = r["length_mm"] if r["length_mm"] is not None else R.numero(r["comp"])
        qtd = R.numero(r["qtd2"]) if setor == "perfis" and r["qtd2"] is not None else r["quantity_planned"]
        out.add(R.identidade(setor, r["production_order_no"], r["component_ref"], r["profile_type"], comp, qtd, 0)[:-2])
    return out


# ---------------------------------------------------------------- casos: o esperado a partir da origem

def recursos_por_nome(objetos, setor) -> dict:
    """{nome em minúsculas: {id, nome, nomes}} dos recursos do catálogo (nome e aliases da área)."""
    out = {}
    for o in objetos:
        if o["kind"] != "resource":
            continue
        d = o["definition"] or {}
        nomes = [o["name"]] + [a.get("name") for a in d.get("aliases") or [] if a.get("area") == setor and a.get("name")]
        info = {"id": o["id"], "nome": o["name"], "nomes": list(dict.fromkeys(nomes))}
        for n in nomes:
            out.setdefault(str(n).strip().casefold(), info)
    return out


def taxa_confirmada(objetos, resource_id, setor, operacao):
    """Taxa «Confirmada» da tabela de velocidades para o recurso e a operação (sem intervalos de dimensão)."""
    for o in objetos:
        d = o["definition"] or {}
        if o["kind"] != "rate" or not d.get("confirmed") or str(d.get("resource_id")) != str(resource_id):
            continue
        if d.get("area") not in (None, setor):
            continue
        op = str(d.get("operation") or "").removeprefix("CPIS:")
        if op in (str(operacao), "corte" if setor == "perfis" else op):
            if not any(k in d for k in ("min_value", "max_value", "min_thickness_mm", "max_thickness_mm")):
                return {"method": d.get("method"), "value": d.get("value")}
    return None


def eficiencia(definicoes, setor, recurso) -> float:
    """Eficiência da máquina (%), defeito 100 (pressuposto). Lê `efficiency`/`eficiencia` das Definições do setor
    quando existir (por id do recurso ou nome); hoje não existe nenhuma."""
    d = (definicoes or {}).get(setor) or {}
    tabela = d.get("efficiency") or d.get("eficiencia") or {}
    for k in ((recurso or {}).get("id"), (recurso or {}).get("nome")):
        if k and R.positivo(tabela.get(k)):
            return R.positivo(tabela[k])
    return 100.0


def construir_casos(setor, o, comum, hoje, v2_ids) -> tuple[list, dict]:
    """Um caso por linha ativa do Excel (pela regra de população), com o esperado e os estratos."""
    # CPIS: a cópia carregada mais tarde manda, campo a campo (cpis_copies.latest_first).
    copias = defaultdict(list)
    for r in o["cpis"]:
        copias[R.of_normalizada(r["production_order_no"])].append(r)
    piso = datetime.min.replace(tzinfo=timezone.utc)

    def momento(v):
        if v is None:
            return piso
        if not isinstance(v, datetime):
            v = datetime(v.year, v.month, v.day)
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)

    estado_cpis = {}
    for of, rs in copias.items():
        rs = sorted(rs, key=lambda r: (momento(r["loaded_at"]), momento(r["record_date"])), reverse=True)
        campo = lambda k: next((r[k] for r in rs if r[k] not in (None, "")), None)  # noqa: E731
        estado_cpis[of] = {"status": campo("status"), "entrega": campo("delivery_date"), "fim": campo("planned_finish_date")}
    pesos = R.indice_pesos(o["folhas"].get("Tabela pesos", []))
    areas = R.indice_areas(o["folhas"].get("AreaSecaoCorte", []))
    taxas = R.taxas_capacidade(o["folhas"].get("CapacidadeMáquinas", []))
    picking = R.indice_picking(o["folhas"].get("Picking", [])) if setor == "perfis" else {}
    recursos = recursos_por_nome(comum["objetos"], setor)
    membros = {r["member_key"]: r for r in o["membros"]}
    antigas = {(r["production_order_no"], r["reference"]): r for r in o["antigas"]}
    escolhas = {r["member_key"]: r for r in o["escolhas"]}
    conjuntos = {f: s for s in o["conjuntos"] for f in s["families"] or []}
    alias_de = defaultdict(list)  # chave atual → chaves antigas
    for chave, lista in o["aliases"].items():
        alias_de[chave] = lista
    ano_assumido = (comum["politicas"].get(setor) or {}).get("assume_picking_year")
    # Linhas ativas pela regra da população e a associação MES refeita.
    linhas = []
    for l in o["linhas"]:
        raw = l["r"] or {}
        of = R.of_normalizada(l["production_order_no"]) or str(l["production_order_no"] or "")
        cp = estado_cpis.get(of) or {}
        if not R.ativa(cp.get("status"), raw.get("Fechado"), l["closed_x"]):
            continue
        comp = R.numero(l["length_mm"]) if l["length_mm"] is not None else R.numero(raw.get("Comp."))
        qtd = R.numero(raw["QTD [un,]"]) if setor == "perfis" and "QTD [un,]" in raw else R.numero(l["quantity_planned"])
        perfil = (l["profile_type"] or raw.get("Tipo de perfil") or "").strip()
        if setor == "cantoneiras":
            codigos = [str(raw.get(k) or "").strip().removesuffix(".0") for k in ("1ª Oper.", "2ª Oper.")]
            operacoes = list(dict.fromkeys(x for x in codigos if x.isdigit() and x != "0"))
            principal = operacoes[0] if operacoes else str(raw.get("1ª Oper.") or "").strip().removesuffix(".0")
        else:
            marca = str(raw.get("Aborc.") or "").strip().upper().lstrip("'")
            operacoes = ["corte"] + (["abocardar"] if marca not in ("", "-", "NÃO", "NAO") else [])
            principal = "corte"
        linhas.append({"l": l, "raw": raw, "of": of, "cp": cp, "comp": comp, "qtd": qtd, "perfil": perfil,
                       "ref": (l["component_ref"] or "").strip(), "operacoes": operacoes, "principal": principal,
                       "plan_key": l["source_line_id"], "chave": "macro:" + l["source_line_id"]})
    registos = {}
    for r in o["registos"]:
        frozen = r["plan_identity"] or {}
        if not frozen and len(o["historico"].get(r["matched_plan_key"], [])) == 1:
            frozen = o["historico"][r["matched_plan_key"]][0]
        registos[r["id"]] = {
            "id": r["id"], "of": R.of_normalizada(r["production_order"]) or R.of_normalizada(frozen.get("production_order_no")),
            "quantidade": r["quantity"], "plan_key": r["matched_plan_key"], "full_profile": r["full_profile"],
            "ref": frozen.get("component_ref", r["model_ref"]), "comprimento": frozen.get("length_mm", r["length_mm"]),
            "perfil": frozen.get("profile_type", r["profile_type"]), "maquina": r["machine"], "operacao": r["operacao"],
            "plan_refs": [{"plan_key": x["plan_key"], "component_ref": x["component_ref"], "length_mm": x["length_mm"],
                           "profile_type": x["profile_type"], "assumed_quantity": x["assumed_quantity"]} for x in o["refs"].get(r["id"], [])],
            "dia": str(r["sheet_date"]) if r["sheet_date"] else None, "imagem": r["image_sha256"],
            "pdf": r["source_filename"], "pagina_pdf": r["source_page"], "folha": r["sheet_uid"]}
    planos = {x["plan_key"]: {"plan_key": x["plan_key"], "of": x["of"], "ref": x["ref"], "comprimento": x["comp"],
                              "perfil": x["perfil"]} for x in linhas}
    for r in o.get("todas") or []:  # linhas fechadas das mesmas OF: contam para a ambiguidade, como na app
        planos.setdefault(r["source_line_id"], {"plan_key": r["source_line_id"], "of": R.of_normalizada(r["production_order_no"]),
                                                "ref": (r["component_ref"] or "").strip(), "comprimento": R.numero(r["comp"]),
                                                "perfil": (r["profile_type"] or "").strip()})
    assoc = R.associar_registos(list(registos.values()), list(planos.values()))
    por_linha = R.indice_por_linha(assoc)
    # Repetidas: mesma OF, referência, perfil, comprimento e QTD (a ordem segue a linha do Excel).
    for x in linhas:
        x["base_id"] = R.identidade(setor, x["of"], x["ref"], x["perfil"], x["comp"], x["qtd"], 0)[:-2]
        x["linha_excel"] = x["l"]["excel_row"]
    R.numerar_repetidas(linhas)
    casos = []
    for x in linhas:
        raw, l = x["raw"], x["l"]
        app = o["app"].get(x["chave"]) or {}
        contador, motivo_contador = R.contador_excel(raw, "Ser." if setor == "perfis" else "Maq.", R.quantidade(x["qtd"]))
        ocr = R.ocr_da_operacao(setor, por_linha, registos, x["plan_key"], x["operacoes"], x["principal"])
        s = R.saldo(x["qtd"], contador, ocr["ocr"], ocr_bloqueado=ocr["bloqueado"])
        m = R.metros(s["saldo"], x["comp"])
        if setor == "cantoneiras":
            p = R.peso_cantoneira(x["perfil"], x["comp"], pesos)
            p_tabela = R.peso_cantoneira(x["perfil"], x["comp"], pesos, geometria=False)
            area = None
        else:
            area, _ = R.area_seccao(l["material_type"], d=raw.get("Ø Externo [mm]"), w=raw.get("Largura (w) [mm]"),
                                    h=raw.get("Altura (h) [mm]"), t=raw.get("Espessura (t) [mm]"), perfil=x["perfil"], catalogo=areas)
            # Linha do Excel: aço 7850 kg/m³ seja qual for a Qual. (raw.calculations.recalculate, como o Excel DB/DC).
            kg_peca = R.peso_perfil(area, x["comp"], R.DENSIDADE_ACO)
            p = {"kg_m": None, "kg_peca": kg_peca, "origem": "área × L × 7850" if kg_peca else None}
            p_tabela = p
        chaves = [x["chave"], *alias_de.get(x["chave"], [])]
        maq_tabela = raw.get("Máquina Corte") or l["cutting_machine"]
        familia = app.get("sku_family") if isinstance(app.get("sku_family"), str) else None
        efetiva = R.maquina_efetiva(chaves, escolhas, maq_tabela, familia, conjuntos)
        dec = R.decisao(chaves, membros, antigas, x["of"], x["ref"])
        est = R.estado(dec, efetiva["maquina"])
        subst = comum["substituicoes"].get((setor, x["of"], x["ref"])) or comum["substituicoes"].get((setor, x["of"], "*"))
        pk = R.picking_da_linha(x["of"], raw.get("Picking"), picking) if setor == "perfis" else {"semana": None, "conflito": False}
        pz = R.prazo(setor, data_corte=raw.get("Data Corte") or l["cut_date"], picking_semana=pk["semana"],
                     picking_conflito=pk["conflito"], galvanizacao=raw.get("Data Galvanização"), coluna_w=raw.get("W"),
                     hoje=hoje, ano_assumido=ano_assumido, substituicao=subst,
                     fim_previsto=x["cp"].get("fim"), entrega=x["cp"].get("entrega"))
        sc = R.semana_carga(pz["dia"], hoje)
        recurso = recursos.get(str(efetiva["maquina"] or "").strip().casefold())
        if efetiva.get("resource_id") and not recurso:
            recurso = next((r for r in recursos.values() if r["id"] == str(efetiva["resource_id"])), None)
        nomes = (recurso or {}).get("nomes") or ([efetiva["maquina"]] if efetiva["maquina"] else [])
        h = R.horas_decididas(setor, s["saldo"], comprimento_mm=x["comp"], area_mm2=area, qtd=x["qtd"], nomes_maquina=nomes,
                              velocidades=o["velocidades"], taxas=taxas,
                              confirmada=taxa_confirmada(comum["objetos"], (recurso or {}).get("id"), setor, x["principal"]),
                              eficiencia_pct=eficiencia(comum["definicoes"], setor, recurso))
        rec_tabela = recursos.get(R.maquina_normalizada(maq_tabela).casefold())
        h_tabela = R.horas_decididas(setor, s["saldo"], comprimento_mm=x["comp"], area_mm2=area, qtd=x["qtd"],
                                     nomes_maquina=(rec_tabela or {}).get("nomes") or ([maq_tabela] if R.maquina_normalizada(maq_tabela) else []),
                                     velocidades=o["velocidades"], taxas=taxas)
        marcas = []
        if x["repetidas"] > 1:
            marcas.append("repetida")
        if setor == "cantoneiras" and str(raw.get("2ª Oper.") or "").strip().removesuffix(".0") not in ("", "0"):
            marcas.append("2.ª operação")  # também os códigos compostos («111-1034»)
        if setor == "perfis" and "abocardar" in x["operacoes"]:
            marcas.append("abocardar")
        if ocr["ocr"] is not None and s["qtd"] is not None and ocr["ocr"] > s["qtd"]:
            marcas.append("OCR>QTD")
        if s["ocr_menor_excel"]:
            marcas.append("OCR<Excel")
        if setor == "cantoneiras" and p_tabela["kg_peca"] is None:
            marcas.append("sem peso na tabela" if p["kg_peca"] is not None else "sem peso nem geometria")
        identidade_app = "v2" if x["base_id"] in v2_ids else "app"
        origem_maq = ("sugerida" if efetiva["sugerida"] else
                      "Carteira≠Tabela" if efetiva["origem"] == "carteira" and str(efetiva["maquina"]).casefold() != R.maquina_normalizada(maq_tabela).casefold()
                      else "Carteira=Tabela" if efetiva["origem"] == "carteira" else
                      "Tabela" if efetiva["origem"] == "tabela" else "conjunto" if efetiva["origem"] == "conjunto" else "nenhuma")
        caso = {
            "id": R.identidade(setor, x["of"], x["ref"], x["perfil"], x["comp"], x["qtd"], x["ordem"]),
            "setor": setor, "chave": x["chave"], "linha_excel": l["excel_row"], "of": x["of"], "referencia": x["ref"],
            "perfil": x["perfil"], "comprimento_mm": x["comp"], "qtd": x["qtd"], "repetidas": x["repetidas"],
            "origem": {
                "contador": contador, "contador_motivo": motivo_contador, "coluna_falta": raw.get(R.COLUNA_SALDO_EXCEL["Ser." if setor == "perfis" else "Maq."]),
                "ocr": ocr["ocr"], "ocr_registos": ocr["registos"], "ocr_bloqueado": ocr["motivo"],
                "maquina_tabela": maq_tabela, "maquina_carteira": (escolhas.get(next((k for k in chaves if k in escolhas), "")) or {}).get("machine_name"),
                "decisao": dec, "data_corte": str(raw.get("Data Corte") or l["cut_date"] or "") or None,
                "picking": pk.get("semana"), "picking_conflito": pk.get("conflito"), "galvanizacao": raw.get("Data Galvanização"),
                "W": raw.get("W"), "mt_h": raw.get("Mt\\h"), "area_mm2": area, "kg_m": p.get("kg_m"),
                "operacoes": x["operacoes"], "estado_cpis": x["cp"].get("status"),
            },
            "esperado": {
                "saldo": s["saldo"], "fonte_saldo": s["fonte"], "excesso": s["excesso"], "metros": m,
                "kg_peca": p["kg_peca"], "kg": R.kg(s["saldo"], p["kg_peca"]), "kg_origem": p["origem"],
                "kg_tabela": R.kg(s["saldo"], p_tabela["kg_peca"]),
                "maquina": efetiva["maquina"], "maquina_origem": efetiva["origem"], "recurso": (recurso or {}).get("id"),
                "estado": est, "tipo_carga": R.TIPO_CARGA.get(est), "prazo_dia": pz["dia"], "prazo_fonte": pz["fonte"],
                "estacionada": pz["estacionada"], "semana_carga": sc, "horas": h["horas"], "horas_detalhe": h,
                "horas_maquina_tabela": h_tabela["horas"], "nomes_maquina": nomes,
            },
            "estratos": {"setor": setor, "fonte_saldo": s["fonte"], "origem_maquina": origem_maq, "estado": est,
                         "prazo": pz["fonte"], "atraso": "atrasada" if sc["atrasada"] else "sem prazo" if pz["dia"] is None else "em dia",
                         "identidade": identidade_app},
            "marcas": marcas, "app_sql": {k: app.get(k) for k in VALORES_APP if k in app},
            "app_ativa": x["chave"] in o["app"],
            "_aberta": s["saldo"] is None or s["saldo"] > 0,
        }
        casos.append(caso)
    extra = {"associacoes": assoc, "registos": registos, "taxas": taxas, "pesos_perfis": len(pesos),
             "velocidades": o["velocidades"], "picking": len(picking)}
    return casos, extra


# ---------------------------------------------------------------- páginas por caso

def ler_paginas(paginas: Paginas, setor: str, casos: list, mapa_recursos: dict, hoje: date) -> dict:
    """Tabela e Carteira por OF; Carga (operações) por OF × máquina × semana. Junta os valores a cada caso."""
    por_of = defaultdict(list)
    for c in casos:
        por_of[c["of"]].append(c)
    falhas = []
    for of, lista in sorted(por_of.items()):
        if not paginas.disponivel():
            falhas.append({"of": of, "erro": "sem pedidos disponíveis"})
            continue
        tabela, pagina = {}, 1
        while True:
            dados, erro = paginas.get("/planeamento/api/raw/linhas", {"area": setor, "q": of, "page_size": 500, "page": pagina})
            if erro or not dados:
                falhas.append({"of": of, "pagina": "tabela", "erro": erro})
                break
            for r in dados.get("rows") or []:
                v = r.get("values") or {}
                if R.of_normalizada(v.get("of")) != of:
                    continue
                ops = r.get("operations") or []
                principal = next((op for op in ops if str(op.get("operation")) == str(v.get("operation") if setor == "cantoneiras" else "corte")), ops[0] if ops else {})
                tabela[r["key"]] = {"remaining": v.get("remaining"), "planning_remaining": v.get("planning_remaining"),
                                    "balance_origin": v.get("planning_balance_origin"), "remaining_m": v.get("remaining_m"),
                                    "weight_unit": v.get("weight_unit"), "weight": v.get("weight"), "machine": v.get("machine"),
                                    "theoretical_hours": v.get("theoretical_hours"), "rate_source": v.get("rate_source"),
                                    "applied_rate_value": v.get("applied_rate_value"), "section_unit": v.get("section_unit"),
                                    "made": v.get("made") if setor == "cantoneiras" else v.get("cut"),
                                    "production_excess": v.get("production_excess"),
                                    "ocr_registos": sorted({e.get("record_id") for e in principal.get("ocr_records") or [] if e.get("record_id") is not None}),
                                    "aliases": r.get("selection_aliases") or []}
            if pagina * 500 >= int(dados.get("total") or 0) or not paginas.disponivel():
                break
            pagina += 1
        membros, erro = paginas.get("/planeamento/api/carteira/membros", {"setor": setor, "vista": "of_perfil", "caminho": of, "limite": 1000})
        carteira = {}
        if erro:
            falhas.append({"of": of, "pagina": "carteira", "erro": erro})
        for item in (membros or {}).get("items") or []:
            carteira[item["key"]] = item
        for c in lista:
            c["paginas"] = {"tabela": tabela.get(c["chave"]), "carteira": carteira.get(c["chave"]),
                            "carteira_erro": erro if erro else None, "carga": None, "carga_pedidos": []}
    # Carga: as operações de cada OF na célula esperada (máquina e semana pela origem) e, se for outra, na que a
    # Carteira indica (máquina mostrada ou sugerida e semana do prazo mostrado): assim uma diferença fica medida.
    pedidos = defaultdict(list)
    for c in casos:
        p = c.get("paginas") or {}
        item = p.get("carteira") or {}
        app_rid = mapa_recursos.get(str(item.get("machine") or "").casefold())
        if not item.get("machine") and isinstance(item.get("suggested"), dict):
            app_rid = item["suggested"].get("resource_id")
        recursos = [r for r in dict.fromkeys((c["esperado"]["recurso"], app_rid)) if r]
        c["paginas"]["carga_recurso"] = recursos[0] if recursos else None
        celulas = []
        esperada = c["esperado"]["semana_carga"]["celula"]
        if isinstance(esperada, tuple):
            celulas.append(esperada)
        app_dia = item.get("priority_day")
        app_celula = R.semana_carga(app_dia, hoje)["celula"] if app_dia else None
        if isinstance(app_celula, tuple) and app_celula not in celulas:
            celulas.append(app_celula)
        for rid in recursos:
            for cel in celulas:
                pedidos[(rid, cel, c["of"])].append(c)
    resultados = {}
    for (rid, cel, of), lista in sorted(pedidos.items(), key=lambda kv: (kv[0][2], str(kv[0][0]), kv[0][1])):
        dados, erro = paginas.get("/planeamento/api/setor/carga/operacoes",
                                  {"setor": setor, "maquina": rid, "ano": cel[0], "semana": cel[1], "of": of})
        resultados[(rid, cel, of)] = (dados, erro)
        for c in lista:
            c["paginas"]["carga_pedidos"].append({"recurso": rid, "celula": list(cel), "erro": erro})
    # Emparelhar operações com casos: referência, comprimento e perfil; entre repetidas, a ordem do Excel.
    for (rid, cel, of), (dados, erro) in resultados.items():
        if erro or not dados:
            continue
        principais = [op for op in dados.get("operations") or [] if op.get("phase", "principal") == "principal"]
        candidatos = sorted(pedidos[(rid, cel, of)], key=lambda c: c["linha_excel"] or 0)
        usadas = set()
        for c in candidatos:
            if (c["paginas"].get("carga") or {}).get("_celula"):
                continue
            for i, op in enumerate(principais):
                if i in usadas:
                    continue
                if (R.chave_tecnica(op.get("reference")) == R.chave_tecnica(c["referencia"] or "Sem referência")
                        and R.chave_perfil(op.get("profile")) == R.chave_perfil(c["perfil"] or "Sem perfil")
                        and R.numero(op.get("length_mm")) == R.numero(c["comprimento_mm"])):
                    usadas.add(i)
                    c["paginas"]["carga"] = {**{k: op.get(k) for k in ("remaining", "length_mm", "load_hours", "kind", "late",
                                                                    "priority_day", "weight_kg", "excel_hours", "load_basis",
                                                                    "load_origin", "hours_origin", "priority_source")},
                                             "taxa": (op.get("estimate") or {}).get("rate"), "_celula": list(cel), "_recurso": rid}
                    break
    return {"falhas": falhas}


def horas_na_sugerida(setor, casos, extra, objetos, definicoes) -> None:
    """Linhas sem máquina: a Carga usa a máquina sugerida. A regra decidida aplica-se também aí (decisão 3 de
    08/10): calcula as horas esperadas nessa máquina (`esperado.horas_sugerida`)."""
    por_id = {info["id"]: info for info in recursos_por_nome(objetos, setor).values()}
    for c in casos:
        e, g = c["esperado"], (c.get("paginas") or {}).get("carga") or {}
        if e["maquina"] or not g.get("_recurso"):
            continue
        recurso = por_id.get(str(g["_recurso"]))
        h = R.horas_decididas(setor, e["saldo"], comprimento_mm=c["comprimento_mm"], area_mm2=c["origem"].get("area_mm2"),
                              qtd=c["qtd"], nomes_maquina=(recurso or {}).get("nomes") or [], velocidades=extra["velocidades"],
                              taxas=extra["taxas"], eficiencia_pct=eficiencia(definicoes, setor, recurso))
        e["horas_sugerida"], e["horas_sugerida_detalhe"] = h["horas"], h


# ---------------------------------------------------------------- verificações por caso

def _v(codigo, campo, pagina, esperado, valor, tolerancia=0.0, defeito=None, nota=None):
    d = R.diferenca(esperado, valor, tolerancia)
    return {"codigo": codigo, "campo": campo, "pagina": pagina, "esperado": esperado, "valor": valor, "diferenca": d,
            "defeito": (defeito or R.INEXPLICADO) if d is not None else None, "nota": nota if d is not None else None}


def _r(x, casas=6):
    return round(x, casas) if isinstance(x, float) else x


def verificar_caso(c: dict, agora: datetime) -> list:
    e, o, p = c["esperado"], c["origem"], c.get("paginas") or {}
    t, k, g = p.get("tabela"), p.get("carteira"), p.get("carga")
    out = []
    # C01: presença nas páginas (saldo > 0 ou desconhecido → a Carteira mostra; excluída também aparece).
    out.append(_v("C01", "presente", "tabela", True, t is not None, nota="Linha ativa sem linha na Tabela."))
    # Saldo 0 com operação seguinte (2.ª operação, abocardar) pode continuar na Carteira: o saldo dessa operação não
    # está na origem lida aqui, por isso a presença não se confere.
    seguinte = bool({"2.ª operação", "abocardar"} & set(c["marcas"]))
    if not p.get("carteira_erro") and (c["_aberta"] or not seguinte):
        out.append(_v("C01", "presente", "carteira", c["_aberta"], k is not None))
    # C14: associação dos registos OCR à linha (mesma regra refeita) — explica as diferenças de saldo.
    assoc_dif = t is not None and sorted(t.get("ocr_registos") or []) != sorted(o["ocr_registos"] or [])
    if t is not None:
        out.append(_v("C14", "registos_ocr", "tabela", o["ocr_registos"], t.get("ocr_registos"), defeito="F07",
                      nota="Registos MES associados a esta linha diferentes da associação refeita."))
    if "OCR>QTD" in c["marcas"]:
        out.append(_v("C14", "producao_acima_qtd", "origem", 0.0, e["excesso"], defeito="F07",
                      nota="Produção OCR acima da QTD: a linha some da Carteira com saldo 0."))

    def saldo_defeito(valor):
        if t and t.get("planning_remaining") is not None and valor == t.get("planning_remaining") != t.get("remaining"):
            return "F05"
        if assoc_dif:
            return "F07"
        return R.INEXPLICADO

    # C02: saldo pela regra decidida (OCR substitui o Excel) em cada página.
    if t is not None:
        out.append(_v("C02", "saldo", "tabela", e["saldo"], t.get("remaining"), defeito="F07" if assoc_dif else None))
        out.append(_v("C02", "saldo_a_planear", "tabela", t.get("remaining"), t.get("planning_remaining"), defeito="F05",
                      nota="A camada v2 (29/09) substitui o saldo principal."))
    if k is not None:
        out.append(_v("C02", "saldo", "carteira", e["saldo"], k.get("pieces"), defeito=saldo_defeito(k.get("pieces"))))
    if g is not None:
        out.append(_v("C02", "saldo", "carga", e["saldo"], g.get("remaining"), defeito=saldo_defeito(g.get("remaining"))))
    if "OCR<Excel" in c["marcas"]:
        out.append(_v("C02", "ocr_menor_excel", "origem", o["contador"], o["ocr"], defeito="F03",
                      nota="Decisão 2 de 08/10: o OCR manda; conferir a folha no MES."))
    # C03: metros.
    if t is not None:
        out.append(_v("C03", "metros", "tabela", _r(e["metros"]), _r(t.get("remaining_m")), R.TOLERANCIA_METROS,
                      defeito="F07" if assoc_dif else None))
    if k is not None:
        dif_saldo = R.diferenca(e["saldo"], k.get("pieces")) is not None
        out.append(_v("C03", "metros", "carteira", _r(e["metros"], 2), k.get("metres"), R.TOLERANCIA_METROS,
                      defeito=saldo_defeito(k.get("pieces")) if dif_saldo else "F09" if e["metros"] is None else None))
    if g is not None and g.get("remaining") is not None and g.get("length_mm"):
        out.append(_v("C03", "metros", "carga", _r(e["metros"]), _r(g["remaining"] * g["length_mm"] / 1000), R.TOLERANCIA_METROS,
                      defeito=saldo_defeito(g.get("remaining"))))
    # C04: peso; o desconhecido nunca vira 0.
    geometria = e["kg_origem"] == "geometria"
    if k is not None:
        esperado_kg = _r(e["kg"], 1) if e["kg"] is not None else None
        defeito = "F08" if geometria and k.get("kg") is None else "F09" if e["kg"] is None and k.get("kg") == 0 else \
            saldo_defeito(k.get("pieces")) if R.diferenca(e["saldo"], k.get("pieces")) is not None else None
        out.append(_v("C04", "kg", "carteira", esperado_kg, k.get("kg"), R.TOLERANCIA_KG + 0.05, defeito=defeito))
    if g is not None:
        defeito = saldo_defeito(g.get("remaining")) if R.diferenca(e["saldo"], g.get("remaining")) is not None else \
            "F08" if geometria and not g.get("weight_kg") else "F09" if e["kg"] is None and g.get("weight_kg") == 0 else \
            "F21" if k is not None and R.diferenca(k.get("kg"), g.get("weight_kg"), 0.5) is not None else None
        out.append(_v("C04", "kg", "carga", _r(e["kg"], 1) if e["kg"] is not None else None, _r(g.get("weight_kg"), 1),
                      R.TOLERANCIA_KG + 0.05, defeito=defeito))
    # C05: máquina efetiva (Carteira → Tabela → conjunto).
    esperada = (e["maquina"] or "").casefold() or None
    if k is not None:
        out.append(_v("C05", "maquina", "carteira", esperada, (k.get("machine") or "").casefold() or None))
    if t is not None:
        out.append(_v("C05", "maquina_tabela", "tabela", R.maquina_normalizada(o["maquina_tabela"]).casefold() or None,
                      R.maquina_normalizada(t.get("machine")).casefold() or None, nota="Máquina da Tabela diferente do Excel (edição manual?)."))
    if g is not None and e["recurso"]:
        out.append(_v("C05", "recurso", "carga", e["recurso"], g.get("_recurso")))
    # C06: horas pela regra decidida (Excel da máquina efetiva ÷ eficiência; ×3 Thomas; E/F na MTG2).
    if g is not None:
        defeito = None
        horas = e["horas"] if e["maquina"] else e.get("horas_sugerida")
        if R.diferenca(horas, g.get("load_hours"), R.TOLERANCIA_HORAS) is not None:
            tabela_dif = R.maquina_normalizada(o["maquina_tabela"]).casefold() != (e["maquina"] or "").casefold()
            origem_horas = str(g.get("hours_origin") or g.get("load_origin") or "")
            if R.diferenca(e["saldo"], g.get("remaining")) is not None:
                defeito = saldo_defeito(g.get("remaining"))  # horas de outro saldo
            elif g.get("load_basis") == "documental" and (tabela_dif or not e["maquina"]):
                defeito = "F01"  # horas da linha da Tabela levadas para a máquina efetiva ou sugerida
            elif "Histórico" in origem_horas or (t or {}).get("rate_source") == "Histórico":
                defeito = "F02"  # taxa histórica em vez da velocidade do Excel
            elif c["setor"] == "perfis":
                defeito = "F02"  # coluna C da CapacidadeMáquinas em vez da E/F, ou ×3 da Thomas em falta
        out.append(_v("C06", "horas", "carga", _r(horas, 4), _r(g.get("load_hours"), 4), R.TOLERANCIA_HORAS,
                      defeito=defeito, nota=f"Carga: {g.get('load_basis')} · {g.get('hours_origin') or g.get('load_origin')}"))
    # C07: prazo e semana da carga.
    dia_esperado = e["prazo_dia"].isoformat() if e["prazo_dia"] else None
    picking = e["prazo_fonte"] == "Picking"
    junto_meia_noite = agora.astimezone(R.LISBOA).hour == 23
    if k is not None:
        pd = str(k.get("priority_day"))[:10] if k.get("priority_day") else None
        out.append(_v("C07", "prazo", "carteira", dia_esperado, pd, defeito="F24" if junto_meia_noite else None))
    if g is not None:
        pd = str(g.get("priority_day"))[:10] if g.get("priority_day") else None
        out.append(_v("C07", "prazo", "carga", dia_esperado, pd, defeito="F24" if junto_meia_noite else None))
        cel = e["semana_carga"]["celula"]
        out.append(_v("C07", "celula", "carga", list(cel) if isinstance(cel, tuple) else cel, g.get("_celula"),
                      defeito="F24" if junto_meia_noite else None))
    if picking:
        out.append({"codigo": "C07", "campo": "picking_semana", "pagina": "carga", "esperado": e["semana_carga"].get("semana_iso"),
                    "valor": e["semana_carga"].get("semana_iso"), "diferenca": None, "defeito": None,
                    "nota": "F11: Picking (segunda 08:00) conta na própria semana; Q6 (semana anterior) por decidir."})
    # C08: estado da Carteira = tipo da Carga.
    if k is not None:
        estado_pag = next((s for s, v in (k.get("status") or {}).items() if v), "excluida")
        out.append(_v("C08", "estado", "carteira", e["estado"], estado_pag))
    if g is not None:
        out.append(_v("C08", "tipo", "carga", e["tipo_carga"], g.get("kind")))
    # C09: repetidas contam a dobrar sem aviso.
    if "repetida" in c["marcas"] and k is not None:
        out.append({"codigo": "C09", "campo": "repetida", "pagina": "carteira", "esperado": f"aviso «repetida {c['repetidas']}×»",
                    "valor": k.get("repeated"), "diferenca": None if k.get("repeated") else True,
                    "defeito": None if k.get("repeated") else "F06", "nota": "Linha repetida contada sem aviso."})
    # C13: Planear não é produzir — o saldo da linha planeada é o da produção registada.
    if e["estado"] == "planeado" and k is not None:
        out.append(_v("C13", "saldo_planeado", "carteira", e["saldo"], k.get("pieces"), defeito=saldo_defeito(k.get("pieces"))))
    return out


# ---------------------------------------------------------------- verificações globais

def fechos(globais, casos_amostra, origem_casos) -> dict:
    """C11: Carteira = Carga (peças, m, t, sem peso); KPI por estado = Carteira; KPI Planeado = Σ «no plano»;
    quadro (Gantt) = Carga por OF × máquina das linhas planeadas."""
    out = {}
    cart = (globais.get("carteira") or {}).get("list_totals") or {}
    carga = globais.get("carga") or {}
    kpis = globais.get("kpis") or {}
    nomes = {m["id"]: m.get("name") for m in [*(carga.get("machines") or []), *(carga.get("totals") or [])] if m.get("id")}
    if cart and carga:
        tot = Counter()
        for m in carga.get("totals") or []:
            for campo in ("pieces", "metres", "weight_kg", "weight_unknown", "operations", "load"):
                tot[campo] += m.get(campo) or 0
        excluidas = sum(1 for c in origem_casos if c["esperado"]["estado"] == "excluida" and c["_aberta"])
        fora = (carga.get("elsewhere") or {}).get("operations", 0)
        out["carteira_vs_carga"] = {
            "carteira": {"linhas": cart.get("lines"), "pecas": cart.get("pieces"), "metros": cart.get("metres"),
                         "toneladas": cart.get("tonnes"), "sem_peso": cart.get("weight_unknown")},
            "carga": {"pecas": round(tot["pieces"]), "metros": round(tot["metres"], 1), "toneladas": round(tot["weight_kg"] / 1000, 2),
                      "sem_peso": tot["weight_unknown"]},
            "diferenca": {"pecas": round(tot["pieces"] - (cart.get("pieces") or 0)),
                          "metros": round(tot["metres"] - (cart.get("metres") or 0), 1),
                          "toneladas": round(tot["weight_kg"] / 1000 - (cart.get("tonnes") or 0), 2),
                          "sem_peso": tot["weight_unknown"] - (cart.get("weight_unknown") or 0)},
            "explicacao": f"Linhas excluídas na Carteira (fora da Carga): {excluidas}; operações noutro setor (fora dos totais "
                          f"da Carga, F14): {fora}; «sem peso» contado de fontes diferentes (F21)."}
    if kpis and cart:
        resumo = {s["code"]: s for s in kpis.get("summary") or []}
        estados = cart.get("status") or {}
        out["kpi_vs_carteira"] = {code: {"kpi": {k: resumo.get(code, {}).get(k) for k in ("lines", "metres", "tonnes", "weight_unknown")},
                                         "carteira": {k: (estados.get(code) or {}).get(k) for k in ("lines", "metres", "tonnes", "weight_unknown")}}
                                  for code in ("planeado", "nesting", "sem_maquina")}
    # KPI Planeado (horas por máquina) vs Σ «no plano» da Carga (células) e vs operações das linhas planeadas.
    if kpis and carga:
        kpi_h = {}
        for painel in kpis.get("panels") or []:
            for m in painel.get("machines") or []:
                if (m.get("base") or {}).get("hours"):
                    kpi_h[m["id"]] = m["base"]["hours"]
        for m in kpis.get("other_machines") or []:
            if (m.get("base") or {}).get("hours"):
                kpi_h[m["id"]] = m["base"]["hours"]
        plano_celulas = {m["id"]: round(sum(w.get("plan") or 0 for w in m.get("weeks") or []), 1) for m in carga.get("machines") or []}
        plano_ops = defaultdict(float)
        for c in casos_amostra:
            g = (c.get("paginas") or {}).get("carga") or {}
            if g.get("kind") == "no plano" and g.get("load_hours") is not None:
                plano_ops[g["_recurso"]] += g["load_hours"]
        out["kpi_planeado_vs_carga"] = [{"recurso": rid, "maquina": nomes.get(rid, rid), "kpi_h": kpi_h.get(rid),
                                         "carga_celulas_no_plano_h": plano_celulas.get(rid),
                                         "carga_operacoes_no_plano_h": round(plano_ops.get(rid, 0.0), 2),
                                         "defeito": "F12" if kpi_h.get(rid) and abs((plano_celulas.get(rid) or 0) - kpi_h[rid]) > 0.1 else None}
                                        for rid in sorted(set(kpi_h) | {r for r, v in plano_celulas.items() if v})]
    quadro = globais.get("quadro")
    if quadro:
        caixas = defaultdict(float)
        for m in quadro.get("machines") or []:
            for b in m.get("boxes") or []:
                caixas[(b.get("of"), m["id"])] += b.get("hours") or 0
        carga_plano, operacoes, outra_maquina = defaultdict(float), Counter(), set()
        for c in casos_amostra:
            g = (c.get("paginas") or {}).get("carga") or {}
            if g.get("kind") == "no plano" and g.get("load_hours") is not None:
                carga_plano[(c["of"], g["_recurso"])] += g["load_hours"]
                operacoes[(c["of"], g["_recurso"])] += 1
                if c["estratos"]["origem_maquina"] == "Carteira≠Tabela":
                    outra_maquina.add((c["of"], g["_recurso"]))
        linhas = []
        for chave in sorted(set(caixas) | set(carga_plano), key=str):
            d = round(caixas.get(chave, 0.0) - carga_plano.get(chave, 0.0), 2)
            tolerancia = max(0.05, operacoes[chave] / 60)  # o Gantt arredonda cada operação ao minuto
            defeito = None if abs(d) <= tolerancia else "F01" if chave in outra_maquina else R.INEXPLICADO
            linhas.append({"of": chave[0], "recurso": chave[1], "maquina": nomes.get(chave[1], chave[1]),
                           "gantt_h": round(caixas.get(chave, 0.0), 2), "carga_no_plano_h": round(carga_plano.get(chave, 0.0), 2),
                           "diferenca_h": d, "operacoes": operacoes[chave], "defeito": defeito})
        out["gantt_vs_carga"] = {"fonte": (quadro.get("source") or {}).get("kind"), "linhas": linhas,
                                 "em_falta": len((quadro.get("source") or {}).get("missing") or [])}
    return out


def frescura(comum, origens, v2, agora) -> dict:
    """C10: idade de cada fonte e ficheiros mais recentes no Drive por importar (F16)."""
    out = {"snapshots": {}, "drive": [], "v2": None}
    for setor, o in origens.items():
        snap = (o["geracao"]["snapshot"] or {})
        carregado = snap.get("loaded_at")
        idade = (agora - datetime.fromisoformat(str(carregado))).total_seconds() / 86400 if carregado else None
        out["snapshots"][setor] = {"geracao": o["geracao"]["id"], "geracao_criada": str(o["geracao"]["created_at"]),
                                   "snapshot": snap.get("snapshot_id"), "ficheiro": snap.get("source_filename"),
                                   "carregado": carregado, "idade_dias": round(idade, 1) if idade is not None else None}
    for d in comum["drive"]:
        setor = d["area"]
        snap = out["snapshots"].get(setor) or {}
        remoto = d.get("remote_modified_at")
        mais_novo = bool(remoto and snap.get("carregado") and remoto > datetime.fromisoformat(str(snap["carregado"])))
        out["drive"].append({"setor": setor, "ficheiro_remoto": d.get("remote_filename"), "modificado": str(remoto),
                             "sha": (d.get("remote_sha256") or "")[:16], "verificado": str(d.get("checked_at")),
                             "importado": (snap.get("snapshot") or "").split("_")[-1] == (d.get("remote_sha256") or "")[:16],
                             "mais_recente_por_importar": mais_novo, "defeito": "F16" if mais_novo else None})
    out["v2"] = {"fontes": v2.get("fontes"), "snapshots": v2.get("snapshots"), "erro": v2.get("erro"), "defeito": "F05"}
    return out


def associacoes_globais(extra, casos) -> dict:
    """C14: registos não associados, ambíguos, folhas repetidas e k × QTD no mesmo dia e máquina."""
    estados = Counter(a["estado"] for a in extra["associacoes"].values())
    regs = extra["registos"]
    imagens = defaultdict(list)
    for r in regs.values():
        if r.get("imagem"):
            imagens[r["imagem"]].append(r["id"])
    repetidas = {k: v for k, v in imagens.items() if len({regs[i]["folha"] for i in v}) > 1}
    por_linha = defaultdict(list)
    for rid, a in extra["associacoes"].items():
        for chave, _ in a["linhas"]:
            por_linha[chave].append(regs[rid])
    multiplos = []
    qtd = {c["chave"].removeprefix("macro:"): c["qtd"] for c in casos}
    for chave, lista in por_linha.items():
        q = qtd.get(chave)
        grupos = defaultdict(list)
        for r in lista:
            grupos[(r.get("dia"), str(r.get("maquina") or "").casefold())].append(r)
        for (d, m), rs in grupos.items():
            soma = sum(R.numero(r["quantidade"]) or 0 for r in rs)
            if q and len(rs) > 1 and soma >= 2 * q and soma % q == 0:
                multiplos.append({"linha": chave, "dia": d, "maquina": m, "registos": [r["id"] for r in rs], "soma": soma, "qtd": q})
    acima = [{"chave": c["chave"], "of": c["of"], "referencia": c["referencia"], "qtd": c["qtd"], "ocr": c["origem"]["ocr"]}
             for c in casos if "OCR>QTD" in c["marcas"]]
    return {"registos": len(regs), "estados": dict(estados), "producao_acima_qtd": {"linhas": len(acima),
            "pecas": sum((x["ocr"] or 0) - (x["qtd"] or 0) for x in acima), "exemplos": acima[:20]},
            "k_vezes_qtd_mesmo_dia": multiplos[:40], "k_vezes_qtd_total": len(multiplos),
            "imagens_em_varias_folhas": len(repetidas), "defeito": "F07"}


def prever(setor, casos) -> dict:
    """--prever: impacto, a partir da origem, das regras decididas a 08/10 sobre toda a população aberta.

    Horas por máquina efetiva, comparadas só nas linhas em que as duas são conhecidas e a máquina efetiva é a da
    Tabela (as horas de hoje são as da Tabela); as linhas com máquina da Carteira diferente ficam à parte (F01) e as
    sem máquina não entram (as horas delas são as da sugerida, na Carga)."""
    por_maquina = defaultdict(lambda: {"linhas": 0, "comparaveis": 0, "horas_atuais": 0.0, "horas_decididas_comparaveis": 0.0,
                                       "horas_decididas": 0.0, "sem_horas_decididas": 0, "fontes_atuais": Counter()})
    f01 = {"linhas": 0, "horas_maquina_tabela": 0.0, "horas_maquina_efetiva": 0.0}
    sem_maquina = 0
    for c in casos:
        if not c["_aberta"] or c["esperado"]["estado"] == "excluida":
            continue
        e, app = c["esperado"], c["app_sql"]
        if not e["maquina"]:
            sem_maquina += 1
            continue
        m = por_maquina[e["maquina"]]
        m["linhas"] += 1
        m["fontes_atuais"][str(app.get("rate_source"))] += 1
        if e["horas"] is None:
            m["sem_horas_decididas"] += 1
        else:
            m["horas_decididas"] += e["horas"]
        atual = R.numero(app.get("theoretical_hours"))
        mesma = R.maquina_normalizada(c["origem"]["maquina_tabela"]).casefold() == e["maquina"].casefold()
        if mesma and atual is not None and e["horas"] is not None:
            m["comparaveis"] += 1
            m["horas_atuais"] += atual
            m["horas_decididas_comparaveis"] += e["horas"]
        if not mesma and c["origem"]["maquina_tabela"]:
            f01["linhas"] += 1
            f01["horas_maquina_tabela"] += atual or 0
            f01["horas_maquina_efetiva"] += e["horas"] or 0
    maquinas = []
    for nome, m in sorted(por_maquina.items(), key=lambda kv: -kv[1]["horas_decididas"]):
        razao = m["horas_decididas_comparaveis"] / m["horas_atuais"] if m["horas_atuais"] else None
        maquinas.append({"maquina": nome, "linhas": m["linhas"], "comparaveis": m["comparaveis"],
                         "horas_atuais_tabela": round(m["horas_atuais"], 1),
                         "horas_regra_decidida_comparaveis": round(m["horas_decididas_comparaveis"], 1),
                         "razao": round(razao, 2) if razao else None, "horas_regra_decidida_total": round(m["horas_decididas"], 1),
                         "sem_horas_decididas": m["sem_horas_decididas"], "fontes_atuais": dict(m["fontes_atuais"])})
    out = {"horas_por_maquina": maquinas, "linhas_sem_maquina": sem_maquina,
           "f01_maquina_carteira_diferente": {k: round(v, 1) if isinstance(v, float) else v for k, v in f01.items()}}
    if setor == "cantoneiras":
        sem = [c for c in casos if c["_aberta"] and ("sem peso na tabela" in c["marcas"] or "sem peso nem geometria" in c["marcas"])]
        out["peso_geometria"] = {"linhas_sem_peso_na_tabela": len(sem),
                                 "calculaveis_pela_geometria": sum(1 for c in sem if c["esperado"]["kg"] is not None),
                                 "toneladas_acrescentadas": round(sum(c["esperado"]["kg"] or 0 for c in sem) / 1000, 1),
                                 "continuam_sem_peso": sum(1 for c in sem if c["esperado"]["kg"] is None)}
    menor = [c for c in casos if "OCR<Excel" in c["marcas"]]
    out["ocr_menor_excel"] = {"linhas": len(menor), "pecas_a_mais_face_ao_excel": sum((c["origem"]["contador"] or 0) - (c["origem"]["ocr"] or 0) for c in menor),
                              "metros": round(sum(((c["origem"]["contador"] or 0) - (c["origem"]["ocr"] or 0)) * (c["comprimento_mm"] or 0) / 1000 for c in menor), 1),
                              "exemplos": [{"of": c["of"], "referencia": c["referencia"], "qtd": c["qtd"], "excel": c["origem"]["contador"],
                                            "ocr": c["origem"]["ocr"]} for c in menor[:10]],
                              "nota": "Decisão 2 de 08/10: o OCR continua a mandar; estas linhas vão para conferir no MES."}
    return out


def prever_mtg2_colunas(casos, taxas) -> list:
    """MTG2: horas com a coluna C (em uso) e com a E/F (decidida), mesma área e mesmo ×3 da Thomas."""
    por = defaultdict(lambda: {"area": 0.0, "c": 0.0, "ef": 0.0, "linhas": 0})
    for c in casos:
        if c["setor"] != "perfis" or not c["_aberta"] or c["esperado"]["estado"] == "excluida":
            continue
        area, s = c["origem"]["area_mm2"], c["esperado"]["saldo"]
        nomes = c["esperado"]["horas_detalhe"]
        maquina = c["esperado"]["maquina"] or "Sem máquina"
        if not area or s is None:
            continue
        taxa = next((taxas[n] for n in [maquina, *(c["esperado"].get("nomes_maquina") or [])] if n in taxas), None)
        p = por[maquina]
        p["linhas"] += 1
        p["area"] += s * area
        if taxa:
            thomas = R.e_thomas([maquina])
            p["c"] += R.horas_regra_atual_mtg2(s, area, taxa["C"], thomas=thomas, qtd=c["qtd"]) or 0
        if nomes.get("horas") is not None:
            p["ef"] += nomes["horas"]
    return [{"maquina": m, "linhas": v["linhas"], "area_mm2": round(v["area"]), "horas_coluna_C": round(v["c"], 1),
             "horas_coluna_EF": round(v["ef"], 1)} for m, v in sorted(por.items(), key=lambda kv: -kv[1]["area"])]


# ---------------------------------------------------------------- relatório

def _n(x, casas=1):
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:,.{casas}f}".replace(",", " ").replace(".", ",")
    return f"{x:,}".replace(",", " ") if isinstance(x, int) else str(x)


def relatorio(ev: dict) -> str:
    m = ev["manifesto"]
    linhas = [f"# Auditoria do fluxo de dados — {m['tag']} ({m['quando_lisboa']})", "",
              "Gerado por `scripts/auditoria_fluxo.py`. Só leitura (SELECT em transação READ ONLY e GET às páginas).",
              f"Código da auditoria: `{(m.get('commit_auditoria') or '?')[:12]}`; código da app lido: `{(m.get('commit_app') or '?')[:12]}`.", ""]
    linhas += ["## Fontes", "", "| Setor | Geração | Excel importado | Idade (dias) |", "|---|---|---|---|"]
    for setor, s in ev["frescura"]["snapshots"].items():
        linhas.append(f"| {setor} | {s['geracao']} | {s['snapshot']} ({str(s['carregado'])[:16]}) | {_n(s['idade_dias'])} |")
    for d in ev["frescura"]["drive"]:
        aviso = " — **mais recente no Drive por importar (F16)**" if d["mais_recente_por_importar"] else ""
        linhas.append(f"- Drive {d['setor']}: `{d['ficheiro_remoto']}` modificado {d['modificado'][:16]}{aviso}")
    v2 = ev["frescura"]["v2"]
    linhas.append(f"- Camada v2: retratos {', '.join(v2.get('snapshots') or []) or '?'}" + (f" (erro: {v2['erro']})" if v2.get("erro") else ""))
    linhas += ["", "## Amostra", "",
               f"{ev['amostra']['casos']} linhas de {ev['amostra']['populacao']} abertas ({ev['amostra']['obrigatorias']} obrigatórias: "
               "todas as linhas das OF com Planeado e as marcadas como repetida, OCR>QTD ou OCR<Excel).", "",
               "| Dimensão | Valor | Na amostra | Na população |", "|---|---|---|---|"]
    for dim, valores in ev["amostra"]["cobertura"].items():
        for valor, (a, p) in valores.items():
            linhas.append(f"| {dim} | {valor} | {a} | {p} |")
    linhas += ["", "## Verificações por caso", "", "Diferença = valor da página ≠ esperado pela regra. Cada diferença leva o defeito "
               "que a explica (F01…F26 do desenho «dados») ou «inexplicado».", "",
               "| Verificação | Campo | Página | Casos | Batem | Diferentes | Por defeito |", "|---|---|---|---|---|---|---|"]
    for chave, r in sorted(ev["contagens"].items()):
        codigo, campo, pagina = chave.split("·")
        defeitos = ", ".join(f"{k} {v}" for k, v in sorted(r["defeitos"].items()))
        linhas.append(f"| {codigo} | {campo} | {pagina} | {r['casos']} | {r['batem']} | {r['diferentes']} | {defeitos or '—'} |")
    linhas += ["", f"**Inexplicadas: {ev['resumo']['inexplicadas']}** de {ev['resumo']['diferencas']} diferenças.", ""]
    linhas += ["## Três exemplos seguidos da origem ao ecrã", ""]
    for ex in ev["exemplos"]:
        linhas += [f"### {ex['titulo']}", "", "```", *ex["texto"], "```", ""]
    linhas += ["## Fechos globais (C11)", ""]
    for setor, f in ev["fechos"].items():
        linhas.append(f"### {setor}")
        cv = f.get("carteira_vs_carga")
        if cv:
            linhas += ["", "| | Peças | Metros | Toneladas | Sem peso |", "|---|---|---|---|---|",
                       f"| Carteira | {_n(cv['carteira']['pecas'])} | {_n(cv['carteira']['metros'])} | {_n(cv['carteira']['toneladas'], 2)} | {_n(cv['carteira']['sem_peso'])} |",
                       f"| Carga | {_n(cv['carga']['pecas'])} | {_n(cv['carga']['metros'])} | {_n(cv['carga']['toneladas'], 2)} | {_n(cv['carga']['sem_peso'])} |",
                       f"| Diferença | {_n(cv['diferenca']['pecas'])} | {_n(cv['diferenca']['metros'])} | {_n(cv['diferenca']['toneladas'], 2)} | {_n(cv['diferenca']['sem_peso'])} |",
                       "", cv["explicacao"], ""]
        kv = f.get("kpi_vs_carteira")
        if kv:
            linhas += ["| Estado | KPI linhas | Carteira linhas | KPI m | Carteira m | KPI t | Carteira t |", "|---|---|---|---|---|---|---|"]
            for code, x in kv.items():
                linhas.append(f"| {code} | {_n(x['kpi']['lines'])} | {_n(x['carteira']['lines'])} | {_n(x['kpi']['metres'])} | "
                              f"{_n(x['carteira']['metres'])} | {_n(x['kpi']['tonnes'], 2)} | {_n(x['carteira']['tonnes'], 2)} |")
            linhas.append("")
        kp = f.get("kpi_planeado_vs_carga")
        if kp:
            linhas += ["Horas «Planeado» (KPI) contra «no plano» da Carga (células das 13 semanas; operações das linhas planeadas, "
                       "incluindo as atrasadas que a grelha não mostra como «no plano»):", "",
                       "| Máquina | KPI h | Carga células h | Carga operações h | Defeito |", "|---|---|---|---|---|"]
            for x in kp:
                linhas.append(f"| {x.get('maquina') or x['recurso']} | {_n(x['kpi_h'])} | {_n(x['carga_celulas_no_plano_h'])} | "
                              f"{_n(x['carga_operacoes_no_plano_h'], 2)} | {x['defeito'] or '—'} |")
            linhas.append("")
        gv = f.get("gantt_vs_carga")
        if gv:
            linhas += [f"Gantt simples (fonte: {gv['fonte']}; operações em falta: {gv['em_falta']}) contra a Carga, por OF × máquina "
                       "(tolerância: 1 minuto por operação):", "",
                       "| OF | Máquina | Operações | Gantt h | Carga no plano h | Diferença h | Defeito |", "|---|---|---|---|---|---|---|"]
            for x in gv["linhas"]:
                linhas.append(f"| {x['of']} | {x.get('maquina') or x['recurso']} | {x.get('operacoes', '—')} | {_n(x['gantt_h'], 2)} | "
                              f"{_n(x['carga_no_plano_h'], 2)} | {_n(x['diferenca_h'], 2)} | {x['defeito'] or '—'} |")
            linhas.append("")
    linhas += ["## Associações MES (C14)", ""]
    for setor, a in ev["associacoes"].items():
        linhas.append(f"- {setor}: {a['registos']} registos; estados {a['estados']}; produção acima da QTD em "
                      f"{a['producao_acima_qtd']['linhas']} linhas (+{_n(a['producao_acima_qtd']['pecas'])} peças); "
                      f"{a['k_vezes_qtd_total']} grupos k × QTD no mesmo dia e máquina; {a['imagens_em_varias_folhas']} imagens em várias folhas.")
    linhas += ["", "## População (C01)", ""]
    for setor, p in ev["populacao"].items():
        linhas.append(f"- {setor}: origem {p['origem_ativas']} linhas ativas, app {p['app_ativas']}; só na origem {p['so_origem']}, "
                      f"só na app {p['so_app']} (peças do registo manual: {p['manuais_app']}).")
    if ev.get("manuais"):
        linhas += ["", "## Correções manuais (C12)", ""]
        for x in ev["manuais"]:
            linhas.append(f"- {x['need_id']} · {x['field']} = {json.dumps(x['value'], ensure_ascii=False)[:60]} ({x['human_decision']}, {str(x['decided_at'])[:16]})")
    if ev.get("prever"):
        linhas += ["", "## Previsão das regras decididas a 08/10 (--prever)", ""]
        for setor, p in ev["prever"].items():
            linhas += [f"### {setor}", "", "Razão = horas pela regra decidida ÷ horas de hoje, nas mesmas linhas (máquina efetiva = Tabela, "
                       "horas conhecidas nas duas). < 1: as horas descem; > 1: sobem.", "",
                       "| Máquina efetiva | Linhas | Comparáveis | Horas hoje (Tabela) | Horas regra decidida | Razão | "
                       "Total regra decidida | Sem horas | Fontes de hoje |", "|---|---|---|---|---|---|---|---|---|"]
            for x in p["horas_por_maquina"][:20]:
                linhas.append(f"| {x['maquina']} | {x['linhas']} | {x['comparaveis']} | {_n(x['horas_atuais_tabela'])} | "
                              f"{_n(x['horas_regra_decidida_comparaveis'])} | {_n(x['razao'], 2)} | {_n(x['horas_regra_decidida_total'])} | "
                              f"{x['sem_horas_decididas']} | {', '.join(f'{k} {v}' for k, v in x['fontes_atuais'].items())} |")
            linhas.append(f"\nLinhas sem máquina (horas na máquina sugerida, ver C06 na Carga): {p.get('linhas_sem_maquina')}.")
            f = p["f01_maquina_carteira_diferente"]
            linhas += ["", f"F01: {f['linhas']} linhas com máquina da Carteira diferente da Tabela: {_n(f['horas_maquina_tabela'])} h "
                       f"na máquina da Tabela contra {_n(f['horas_maquina_efetiva'])} h na máquina efetiva (regra decidida)."]
            if p.get("peso_geometria"):
                g = p["peso_geometria"]
                linhas.append(f"F08: {g['linhas_sem_peso_na_tabela']} linhas sem peso na Tabela de pesos; {g['calculaveis_pela_geometria']} "
                              f"calculáveis pela geometria (+{_n(g['toneladas_acrescentadas'])} t); {g['continuam_sem_peso']} continuam sem peso.")
            o = p["ocr_menor_excel"]
            linhas.append(f"OCR abaixo do Excel: {o['linhas']} linhas, {_n(o['pecas_a_mais_face_ao_excel'])} peças e {_n(o['metros'])} m a mais "
                          f"de saldo face ao Excel. {o['nota']}")
            if p.get("colunas_mtg2"):
                linhas += ["", "| Máquina | Linhas | Área mm² | Horas coluna C | Horas coluna E/F |", "|---|---|---|---|---|"]
                for x in p["colunas_mtg2"]:
                    linhas.append(f"| {x['maquina']} | {x['linhas']} | {_n(x['area_mm2'])} | {_n(x['horas_coluna_C'])} | {_n(x['horas_coluna_EF'])} |")
            linhas.append("")
    linhas += ["## C15 — Preenchimento automático: campo → fonte → regra → onde se usa", "",
               "| Campo | Fonte(s) | Regra quando as fontes se contradizem | Onde se usa | No código |", "|---|---|---|---|---|"]
    for x in ev["c15"]:
        provas = "; ".join(f"{p['ficheiro']}:{','.join(map(str, p['linhas'])) or '?'}" for p in x["confirmacao"])
        linhas.append(f"| {x['campo']} | {x['fontes']} | {x['regra']} | {x['onde']} | {x['estado']}: {provas} |")
    if ev.get("comparacao"):
        cmp_ = ev["comparacao"]
        linhas += ["", f"## Comparação com `{cmp_['anterior']}`", "", f"Resumo: {cmp_['resumo']}", "",
                   "| Caso | Verificação | Campo | Página | Antes | Depois | Esperado | Estado |", "|---|---|---|---|---|---|---|---|"]
        for d in [x for x in cmp_["diferencas"] if x.get("estado") == "inexplicada"][:60]:
            linhas.append(f"| {d['id']} | {d.get('codigo')} | {d.get('campo')} | {d.get('pagina')} | {d.get('antes')} | {d.get('depois')} | {d.get('esperado')} | {d['estado']} |")
    linhas += ["", "## Pedidos às páginas", "", f"{ev['pedidos']['total']} GET; erros: {ev['pedidos']['erros']}; "
               f"5xx: {ev['pedidos']['5xx']}; tempo médio {ev['pedidos']['ms_medio']} ms."]
    return "\n".join(linhas) + "\n"


def exemplo(c: dict) -> dict:
    e, o, p = c["esperado"], c["origem"], c.get("paginas") or {}
    t, k, g = p.get("tabela") or {}, p.get("carteira") or {}, p.get("carga") or {}
    texto = [f"Origem   : {c['of']} · {c['referencia']} · {c['perfil']} · {_n(c['comprimento_mm'], 0)} mm · QTD {_n(c['qtd'], 0)} (linha {c['linha_excel']} do Excel)",
             f"           contador {o.get('contador')} ({o.get('contador_motivo') or 'célula preenchida'}); OCR {o.get('ocr')} "
             f"(registos {o.get('ocr_registos')})",
             f"           máquina Tabela {o.get('maquina_tabela')!r}; Carteira {o.get('maquina_carteira')!r}; decisão {o.get('decisao')}; "
             f"Data Corte {o.get('data_corte')}",
             f"Esperado : saldo {e.get('saldo')} ({e.get('fonte_saldo')}); {_n(e.get('metros'), 2)} m; {_n(e.get('kg'), 1)} kg "
             f"({e.get('kg_origem')}); máquina {e.get('maquina') or '—'} ({e.get('maquina_origem')}); {e.get('estado')}; "
             f"prazo {e.get('prazo_dia')} ({e.get('prazo_fonte')}); célula {(e.get('semana_carga') or {}).get('celula')}; "
             f"{_n(e.get('horas'), 3)} h ({(e.get('horas_detalhe') or {}).get('origem')}, fator {(e.get('horas_detalhe') or {}).get('fator')})",
             f"Tabela   : saldo {t.get('remaining')} / a planear {t.get('planning_remaining')} ({t.get('balance_origin')}); {t.get('remaining_m')} m; "
             f"{t.get('theoretical_hours')} h ({t.get('rate_source')} {t.get('applied_rate_value')})",
             f"Carteira : {k.get('pieces')} peças; {k.get('metres')} m; {k.get('kg')} kg; máquina {k.get('machine')} ({k.get('machine_source')}); "
             f"prazo {k.get('priority_day')}; estado {next((s for s, v in (k.get('status') or {}).items() if v), '—')}",
             f"Carga    : {g.get('remaining')} peças; {g.get('load_hours')} h ({g.get('load_basis')}, {g.get('hours_origin') or g.get('load_origin')}); "
             f"{g.get('weight_kg')} kg; {g.get('kind')}; célula {g.get('_celula')}"]
    difs = [v for v in c.get("verificacoes", []) if v["diferenca"] is not None]
    texto.append("Diferenças: " + ("; ".join(f"{v['codigo']} {v['campo']}@{v['pagina']} {v['esperado']}→{v['valor']} ({v['defeito']})" for v in difs) or "nenhuma"))
    return {"titulo": f"{c['setor']} · {c['of']} · {c['referencia']} ({c['estratos']['estado']}, {c['estratos']['fonte_saldo']})", "texto": texto}


# ---------------------------------------------------------------- principal

def _serial(x):
    if isinstance(x, (date, datetime)):
        return x.isoformat()
    if isinstance(x, tuple):
        return list(x)
    if isinstance(x, (set, frozenset)):
        return sorted(x)
    try:
        from decimal import Decimal
        if isinstance(x, Decimal):
            return float(x)
    except ImportError:
        pass
    return str(x)


def carregar_json(caminho: Path) -> dict:
    dados = caminho.read_bytes()
    if caminho.suffix == ".gz":
        dados = gzip.decompress(dados)
    return json.loads(dados)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Auditoria reproduzível do fluxo de dados (só leitura).")
    ap.add_argument("--tag", default="antes", help="etiqueta da corrida (antes, depois, teste…)")
    ap.add_argument("--base", default="http://127.0.0.1:8113", help="endereço da app (só GET)")
    ap.add_argument("--env", default=str(PRODUCAO / ".env"), help="ficheiro .env quando a pasta não tem um")
    ap.add_argument("--setores", default=",".join(SETORES))
    ap.add_argument("--amostra", type=int, default=400, help="tamanho alvo da amostra estratificada")
    ap.add_argument("--minimo", type=int, default=5, help="casos mínimos por valor de cada dimensão")
    ap.add_argument("--limite", type=int, default=None, help="corrida pequena: no máximo N casos por setor, sem obrigatórios")
    ap.add_argument("--max-pedidos", type=int, default=800)
    ap.add_argument("--intervalo", type=float, default=0.2)
    ap.add_argument("--sem-gantt", action="store_true", help="não pede o quadro (Gantt simples)")
    ap.add_argument("--sem-paginas", action="store_true", help="só a origem (sem GET)")
    ap.add_argument("--prever", action="store_true", help="impacto das regras decididas, a partir da origem")
    ap.add_argument("--comparar", help="evidência anterior (.json ou .json.gz)")
    ap.add_argument("--efeitos", help="ficheiro JSON com os efeitos esperados das correções")
    ap.add_argument("--saida", default=str(SAIDA))
    ap.add_argument("--codigo", default=str(ROOT), help="pasta do código onde se confirmam as regras do C15")
    ap.add_argument("--ignorar-limpeza", action="store_true", help="corre mesmo com a limpeza da base ativa (não usar)")
    a = ap.parse_args(argv)
    if limpeza_ativa() and not a.ignorar_limpeza:
        print(f"A limpeza da base ({LIMPEZA}) está a correr: tenta depois de acabar.", file=sys.stderr)
        return 3
    fonte_env = carregar_env(Path(a.env))
    from scripts.audit_readonly import planning_db  # depois do .env
    agora = datetime.now(timezone.utc)
    hoje = hoje_lisboa()
    setores = [s for s in a.setores.split(",") if s in SETORES]
    print(f"Auditoria {a.tag}: setores {setores}; .env de {fonte_env}; hoje {hoje}.", flush=True)
    v2 = ler_v2()
    with planning_db() as c:
        c.commit()  # os SET da ligação abriram uma transação: o retrato coerente começa aqui
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        c.execute("SET LOCAL jit = off")
        comum = ler_comum(c)
        origens = {s: ler_setor(c, s, comum) for s in setores}
        v2_ids = identidades_v2(c, v2.get("snapshots") or [])
    print("Origem lida: " + ", ".join(f"{s} {len(o['linhas'])} linhas (não fechadas), {len(o['registos'])} registos MES" for s, o in origens.items()), flush=True)
    casos_setor, extras = {}, {}
    for s in setores:
        casos_setor[s], extras[s] = construir_casos(s, origens[s], comum, hoje, v2_ids)
    paginas = Paginas(a.base, intervalo=a.intervalo, maximo=a.max_pedidos)
    globais, amostras, universos, populacao, obrig_total = {}, {}, {}, {}, 0
    for s in setores:
        # Universo: linhas com saldo (ou saldo desconhecido) e as marcadas (repetida, OCR>QTD, OCR<Excel), mesmo
        # com saldo 0 — essas confirmam que a Carteira as esconde e que a Tabela mostra o excesso.
        abertas = [c for c in casos_setor[s] if c["_aberta"] or MARCAS_RARAS.intersection(c["marcas"])]
        if a.limite:
            amostra = R.escolher_amostra(abertas, alvo=a.limite, minimo=1)[:a.limite]
        else:
            planeadas = {c["of"] for c in abertas if c["esperado"]["estado"] == "planeado"}
            obrig = [c["id"] for c in abertas if c["of"] in planeadas or MARCAS_RARAS.intersection(c["marcas"])]
            obrig_total += len(obrig)
            # ~400 linhas estratificadas (metade por setor) além das obrigatórias; o enchimento junta OF inteiras.
            amostra = R.escolher_amostra(abertas, alvo=len(obrig) + a.amostra // len(setores), minimo=a.minimo,
                                         obrigatorios=obrig, grupo=lambda c: c["of"], por_grupo=8)
        amostras[s], universos[s] = amostra, abertas
        app_ativas = {k for k, r in origens[s]["app"].items() if r.get("ativa")}
        origem_ativas = {c["chave"] for c in casos_setor[s]}
        populacao[s] = {"origem_ativas": len(origem_ativas), "app_ativas": len(app_ativas),
                        "so_origem": len(origem_ativas - app_ativas), "so_app": len({k for k in app_ativas - origem_ativas if k.startswith("macro:")}),
                        "manuais_app": len({k for k in app_ativas if not k.startswith("macro:")}),
                        "exemplos_so_origem": sorted(origem_ativas - app_ativas)[:20],
                        "exemplos_so_app": sorted(k for k in app_ativas - origem_ativas if k.startswith("macro:"))[:20],
                        "defeito": R.INEXPLICADO if (origem_ativas ^ {k for k in app_ativas if k.startswith('macro:')}) else None}
    mapa_recursos = {}
    for s in setores:
        for nome, info in recursos_por_nome(comum["objetos"], s).items():
            mapa_recursos.setdefault(nome, info["id"])
    if not a.sem_paginas:
        for s in setores:
            g = {}
            g["carteira"], _ = paginas.get("/planeamento/api/carteira", {"setor": s, "vista": "of"})
            g["kpis"], _ = paginas.get("/planeamento/api/carteira/kpis", {"setor": s})
            g["carga"], _ = paginas.get("/planeamento/api/setor/carga", {"setor": s})
            if not a.sem_gantt:
                g["quadro"], _ = paginas.get("/planeamento/api/setor/quadro", {"setor": s})
            for m in (g.get("carga") or {}).get("machines") or []:
                mapa_recursos.setdefault(str(m["name"]).casefold(), m["id"])
            globais[s] = g
        for s in setores:
            print(f"{s}: {len(amostras[s])} casos; a ler páginas ({paginas.pedidos} pedidos até agora)…", flush=True)
            globais[s]["falhas"] = ler_paginas(paginas, s, amostras[s], mapa_recursos, hoje)["falhas"]
            horas_na_sugerida(s, amostras[s], extras[s], comum["objetos"], comum["definicoes"])
    contagens = defaultdict(lambda: {"casos": 0, "batem": 0, "diferentes": 0, "defeitos": Counter()})
    for s in setores:
        for c in amostras[s]:
            c.setdefault("paginas", {})
            c["verificacoes"] = verificar_caso(c, agora) if not a.sem_paginas else []
            for v in c["verificacoes"]:
                r = contagens["·".join((v["codigo"], v["campo"], v["pagina"]))]
                r["casos"] += 1
                if v["diferenca"] is None:
                    r["batem"] += 1
                else:
                    r["diferentes"] += 1
                    r["defeitos"][v["defeito"]] += 1
    textos = {}
    base_codigo = Path(a.codigo)
    for entrada in R.PREENCHIMENTO:
        for f, _ in entrada["codigo"]:
            caminho = base_codigo / f
            if caminho.is_file():
                textos[f] = caminho.read_text()
    todos = [c for s in setores for c in amostras[s]]
    resumo = {"diferencas": sum(r["diferentes"] for r in contagens.values()),
              "inexplicadas": sum(r["defeitos"].get(R.INEXPLICADO, 0) for r in contagens.values())}
    exemplos, usadas = [], set()  # três OF diferentes: MTG3 com a máquina da Tabela, MTG2, uma linha Planeado
    for filtro in (lambda c: c["setor"] == "cantoneiras" and c["esperado"]["maquina_origem"] == "tabela",
                   lambda c: c["setor"] == "perfis",
                   lambda c: c["esperado"]["estado"] == "planeado"):
        found = next((c for c in sorted(todos, key=lambda c: R.sha(c["id"]))
                      if filtro(c) and c["of"] not in usadas and (c.get("paginas") or {}).get("carga")), None)
        if found:
            usadas.add(found["of"])
            exemplos.append(exemplo(found))
    ev = {
        "manifesto": {"tag": a.tag, "quando": agora.isoformat(), "quando_lisboa": agora.astimezone(R.LISBOA).strftime("%d/%m/%Y %H:%M"),
                      "commit_auditoria": commit(ROOT), "commit_app": commit(PRODUCAO), "base": a.base, "hoje": hoje,
                      "argumentos": {k: v for k, v in vars(a).items() if k != "env"},
                      "geracoes": {s: o["geracao"]["id"] for s, o in origens.items()},
                      "snapshots": {s: o["snapshot"] for s, o in origens.items()}, "drive": comum["drive"], "v2": v2,
                      "velocidades_excel_mtg3": extras.get("cantoneiras", {}).get("velocidades"),
                      "taxas_capacidade_mtg2": extras.get("perfis", {}).get("taxas")},
        "frescura": frescura(comum, origens, v2, agora),
        "populacao": populacao,
        "amostra": {"casos": len(todos), "populacao": sum(len(universos[s]) for s in setores), "obrigatorias": obrig_total,
                    "cobertura": R.cobertura(todos, [c for s in setores for c in universos[s]])},
        "contagens": {k: {**v, "defeitos": dict(v["defeitos"])} for k, v in contagens.items()},
        "resumo": resumo, "exemplos": exemplos,
        "fechos": {s: fechos(globais.get(s, {}), amostras[s], casos_setor[s]) for s in setores} if not a.sem_paginas else {},
        "associacoes": {s: associacoes_globais(extras[s], casos_setor[s]) for s in setores},
        "manuais": comum["manuais"],
        "c15": R.verificar_codigo(textos),
        "casos": [{k: v for k, v in c.items() if not k.startswith("_") or k == "_aberta"} for c in todos],
        "falhas_paginas": {s: globais.get(s, {}).get("falhas") for s in setores},
        "pedidos": {"total": paginas.pedidos, "erros": sum(1 for r in paginas.registo if r["erro"]),
                    "5xx": paginas.falhas_5xx, "ms_medio": round(sum(r["ms"] for r in paginas.registo) / len(paginas.registo)) if paginas.registo else 0,
                    "lista": paginas.registo},
        "defeitos": R.DEFEITOS,
    }
    if a.prever:
        ev["prever"] = {s: prever(s, casos_setor[s]) for s in setores}
        if "perfis" in setores:
            ev["prever"]["perfis"]["colunas_mtg2"] = prever_mtg2_colunas(casos_setor["perfis"], extras["perfis"]["taxas"])
    if a.comparar:
        anterior = carregar_json(Path(a.comparar))
        efeitos = json.loads(Path(a.efeitos).read_text()).get("efeitos", []) if a.efeitos else []
        atual = json.loads(json.dumps({"casos": ev["casos"]}, default=_serial))
        ev["comparacao"] = {"anterior": a.comparar, **R.comparar(anterior, atual, efeitos)}
    saida = Path(a.saida)
    (saida / "evidencia").mkdir(parents=True, exist_ok=True)
    carimbo = agora.astimezone(R.LISBOA).strftime("%Y%m%dT%H%M")
    texto = json.dumps(ev, ensure_ascii=False, default=_serial, separators=(",", ":"))
    caminho = saida / "evidencia" / f"{a.tag}-{carimbo}.json"
    if len(texto.encode()) > MAX_JSON:
        caminho = caminho.with_suffix(".json.gz")
        caminho.write_bytes(gzip.compress(texto.encode(), compresslevel=9))
    else:
        caminho.write_text(texto)
    ev_relatorio = json.loads(texto)
    (saida / f"RELATORIO-{a.tag}.md").write_text(relatorio(ev_relatorio))
    print(f"Evidência: {caminho} ({caminho.stat().st_size // 1024} KB); relatório: {saida / f'RELATORIO-{a.tag}.md'}")
    print(f"Diferenças: {resumo['diferencas']}; inexplicadas: {resumo['inexplicadas']}; pedidos: {paginas.pedidos}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
