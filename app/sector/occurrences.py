"""Base comum de operações para a vista de necessidades (plano de 01/10/2026, secção 4).

Uma linha por ocorrência de operação de todo o trabalho ativo do setor — escolhido ou não com
«Planear» —, com as mesmas identidades do Gantt (`v2:<uuid>`). É a população do âmbito
«Carteira e necessidades»: o filtro de apresentação nunca muda a seleção, a prioridade ou um plano.

Regras de contagem:
- peças e metros contam uma vez por item (só na operação principal);
- horas somam-se por ocorrência e só quando a estimativa corresponde ao saldo atual;
- saldo desconhecido nunca vira zero; horas desconhecidas nunca viram zero.

Só leitura. Resultado guardado em memória por geração publicada, versão da camada v2, regras de
famílias, prioridades, decisões de máquina, seleção e dia.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone
import math

from .. import planning, planning_needs as needs, planning_population
from . import cache
from .references import UNRESOLVED, master_reference
from .week import lisbon_today

UNITS = {"perfis": "MTG2", "cantoneiras": "MTG3"}
NO_FAMILY = "Sem família SKU"
NO_MACHINE = "Sem máquina"
NO_CPIS_FAMILY = "Sem família (OF fora do CPIS)"  # o mesmo rótulo da Carteira (08/10)
STATUS_CODES = {  # label in the projection -> code of the SKU family catalogue
    "Família confirmada pelo utilizador": "confirmada_pelo_utilizador",
    "Inferida — várias OF": "forte_padrao_e_varias_of",
    "Inferida — uma OF": "forte_padrao_e_uma_of",
    "Por confirmar": "candidata_por_confirmar",
    "Prefixo genérico — por confirmar": "prefixo_demasiado_generico",
    "Possível projeto — por confirmar": "codigo_de_projeto_por_confirmar",
    "Sem família identificada": "sem_familia",
}
CLASSIFICATION = {  # grouped states shown in the tree
    "confirmada_pelo_utilizador": "Confirmada",
    "forte_padrao_e_varias_of": "Inferida com evidência",
    "forte_padrao_e_uma_of": "Inferida com evidência",
    "candidata_por_confirmar": "Candidata",
    "prefixo_demasiado_generico": "Candidata",
    "codigo_de_projeto_por_confirmar": "Candidata",
    "sem_familia": "Sem família",
    None: "Sem catálogo",
}

# Os recálculos de fundo das ocorrências começam logo e passam à frente dos outros (cache.URGENT, sem a espera de
# REFRESH_DELAY): depois de cada ação, a página Máquinas desliga os botões até eles acabarem; a Carga, os KPIs e o
# Gantt também as leem.
_cache = cache.Cache("Ocorrências", mark=lambda value: {**value, "stale": True}, priority=cache.URGENT, refresh_delay=0)


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def operation_label(code: str) -> str:
    code = str(code or "")
    if code == "LOCAL:PRINCIPAL":
        return "Corte"
    if code == "LOCAL:ABOCARDAR":
        return "Abocardar"
    return code.removeprefix("CPIS:")


def _estimate_name(code: str, area: str, principal: bool) -> str:
    if area == "perfis" and principal:
        return "corte"
    if code == "LOCAL:ABOCARDAR":
        return "abocardar"
    return str(code).removeprefix("CPIS:")


def _documentary(row, values, detail, area, remaining):
    """(horas, origem, motivo, máquina) documentais do motor de capacidade, quando descrevem o saldo atual.

    A máquina é aquela para que o motor as calculou: a da Tabela na operação principal (values.machine), a da
    estimativa da operação nas seguintes. Só valem nessa máquina (F01, `_hours`).
    """
    principal = row["fase"] == "principal"
    if remaining is None:
        return None, None, "Saldo da operação por confirmar.", None
    if remaining == 0:
        return 0.0, "Concluída", None, None
    if principal:
        hours, basis = _number(values.get("theoretical_hours")), _number(values.get("remaining"))
        if hours is not None and hours >= 0 and basis is not None and basis == remaining:
            return hours, values.get("rate_source") or "Excel provisório", None, values.get("machine")
        if hours is not None and basis is not None and basis != remaining:
            return None, None, "Estimativa calculada para outro saldo; recalcular.", values.get("machine")
    name = _estimate_name(row["operacao_codigo"], area, principal)
    for estimate in (detail.get("calculation") or {}).get("operation_estimates") or []:
        if str(estimate.get("operation")) != name:
            continue
        hours = _number(estimate.get("hours"))
        if hours is not None and hours >= 0 and _number(estimate.get("quantity")) == remaining:
            return hours, estimate.get("source") or "Estimativa", None, estimate.get("machine")
        return None, None, estimate.get("reason") or "Taxa da máquina/operação por confirmar.", estimate.get("machine")
    return None, None, "Taxa da máquina/operação por confirmar.", None


def _hours(row, values, detail, area, remaining, *, effective_id=None, effective_machine=None, resolve=None):
    """Horas documentais só para a máquina efetiva da ocorrência (F01, 08/10).

    O motor de capacidade calcula as horas para a máquina da Tabela; quando a máquina efetiva é outra (escolhida
    na Carteira, conjunto de famílias, decisão do setor) essas horas não valem: ficam None e a estimativa da
    máquina efetiva entra depois (estimates.hours_on). Compara-se o recurso físico (`effective_id`, `resolve(nome)`)
    e, quando nenhum dos dois é do catálogo, o nome. Devolve (horas, origem, motivo, máquina documental, ID do
    recurso documental).
    """
    hours, origin, reason, machine = _documentary(row, values, detail, area, remaining)
    from . import machine_choice
    machine = machine_choice.normalize(machine) or None
    documentary_id = resolve(machine) if machine and resolve else None
    effective = machine_choice.normalize(effective_machine).casefold()
    same = documentary_id == effective_id if documentary_id or effective_id else (machine or "").casefold() == effective
    if hours is not None and remaining and not same:
        return None, None, f"Horas da Tabela calculadas para {machine or 'sem máquina'}; estimadas na máquina da linha.", machine, documentary_id
    return hours, origin, reason, machine, documentary_id


RAW_FIELDS = ("Descrição", "Observações", "Observações Galvanização", "Designação", "Data Galvanização",
              "Des. Material", "Equipa", "Área de Seção de Corte Unit. [mm2]", "Área de Seção de Corte Unit. [mm²]",
              "Ser.", "Qtd em Falta", "Maq.", "Qtd falta",  # contadores: o saldo RAW mais recente ganha à pesquisa
              "W")  # «2026/53» = linha estacionada no Excel (S53-1)
# Only the parts of the stored detail that identity matching, balances and estimates read;
# the full calculation rules and evidence would cost seconds of JSON decoding per rebuild.
_DETAIL = ("jsonb_build_object('area',c.detail->'area','line',c.detail->'line','revision',c.detail->'revision',"
           "'selection_aliases',coalesce(c.detail->'selection_aliases','[]'::jsonb),"
           "'preparations',coalesce(c.detail->'preparations','[]'::jsonb),"
           "'sku_family_mapping',c.detail->'sku_family_mapping',"
           # estados de todas as cópias CPIS: aberto/aberto em conflito não bloqueia a linha (auditoria A8-3)
           "'status_values',coalesce(c.detail->'status_values','[]'::jsonb),"
           "'calculation',jsonb_build_object('compatible',c.detail->'calculation'->'compatible',"
           "'production_sources',coalesce(c.detail->'calculation'->'production_sources','[]'::jsonb),"
           "'operation_estimates',(SELECT jsonb_agg(e - 'history' - 'calculation') FROM jsonb_array_elements("
           "coalesce(c.detail->'calculation'->'operation_estimates','[]'::jsonb)) e)),"
           "'raw',jsonb_build_object(" + ",".join(f"'{k}',c.detail->'raw'->'{k}'" for k in RAW_FIELDS) + ")) detail")


def _records(c, area):
    from ..raw import query
    g = query.generation(c, area)
    base, args = query.source(g)
    rows = c.execute("SELECT m.row_key,c.values_json," + _DETAIL + base + " AND " + planning_population.active_sql(), args).fetchall()
    for r in rows:
        r["detail"]["raw"] = {k: v for k, v in r["detail"]["raw"].items() if v is not None}
        r["detail"]["calculation"]["operation_estimates"] = r["detail"]["calculation"]["operation_estimates"] or []
        if r["detail"]["calculation"]["compatible"] is None:
            del r["detail"]["calculation"]["compatible"]
    return g, [{**r, "area": area} for r in rows]


def _cpis_families(c, snapshot):
    if not snapshot:
        return {}
    rows = c.execute("""SELECT DISTINCT ON (production_order_no) production_order_no, work_type_code, work_type_description
        FROM raw_mtg.cpis_rows WHERE snapshot_id=%s ORDER BY production_order_no, work_type_code NULLS LAST""", (snapshot,)).fetchall()
    return {r["production_order_no"]: r for r in rows}


def stamp(c, area, today):
    """Everything the facts depend on; a change in any of them rebuilds the cache.

    Só o que build() lê (07/10/2026): a seleção e as máquinas escolhidas na Carteira deste setor — um Planear
    ou «Atribuir máquina» no outro setor não refaz estas ocorrências — e nunca as exportações do OCR original
    (original:*), que não são lidas aqui.
    """
    from ..raw import query, sku_families
    from ..gantt import research
    from . import priority, assignments, scope, machine_choice
    g = query.generation(c, area)
    # Os calendários entram no equilíbrio das sugestões dos perfis (PROP-7): uma mudança refaz as ocorrências.
    calendars = tuple(c.execute("SELECT count(*) n, max(updated_at) m FROM planning_mtg.raw_objects WHERE kind='calendar' AND NOT archived"
                                ).fetchone().values()) if area == "perfis" else None
    # Tabela de velocidades (taxas, também as arquivadas), tempo fixo do setor e eficiência das máquinas (08/10) mudam
    # as horas estimadas; a eficiência é um dicionário, por isso entra pelo digest (a chave da cache tem de ser hashable).
    from ..raw.productivity import sector_timing
    rates = tuple(c.execute("SELECT count(*) FILTER (WHERE NOT archived) n, count(*) t, max(updated_at) m "
                            "FROM planning_mtg.raw_objects WHERE kind='rate'").fetchone().values())
    timing = needs.digest(sector_timing(c)[area])
    return (area, g["id"], research.head(c)["version_id"] if research.enabled() else None,
            sku_families.token(c, area), priority.digest(c), assignments.digest(c),
            scope.area_digest(scope.read(c), area), machine_choice.context(area, conn=c)["digest"], calendars, rates, timing, today)


def resources_context(c, start=None):
    """Physical resources (shared identity across sectors) and the name → code aliases."""
    from ..gantt import research, integrated
    start = start or datetime.now(timezone.utc).replace(second=0, microsecond=0)
    configs = c.execute("SELECT * FROM planning_mtg.raw_objects WHERE kind=ANY(%s) AND NOT archived ORDER BY id",
                        (["resource", "calendar", "rate", "worked_hours"],)).fetchall()
    if not research.enabled():
        return {}, {}, {}, configs, None
    package = research.load(c)
    metadata = package["metadata"]
    codes, by_id = integrated._resources(metadata, configs, start, start + timedelta(weeks=52))
    aliases = {(area, a["nome_origem"]): a["recurso_codigo"] for a in metadata["aliases"] for area in planning.AREAS}
    for code, resource in codes.items():
        for alias in resource.get("aliases", []):
            aliases[(alias["area"], alias["name"])] = code
        for area in planning.AREAS:
            aliases.setdefault((area, resource["name"]), code)
    return codes, by_id, aliases, configs, package


def build(c, area: str, today: date | None = None) -> dict:
    from ..gantt import research, integrated
    from . import priority, scope, assignments
    from .portfolio import signals_of
    today = today or lisbon_today()  # dia de Lisboa, como a Carga (08/10)
    g, records = _records(c, area)
    codes, by_id, aliases, configs, package = resources_context(c)
    by_key = {r["row_key"]: r for r in records}
    if package:
        matched, unmatched = scope.research_rows(package["rows"], records)
        balances = research.application_balances(c, matched, records=records)
        rows = [{**r, **balances.get(r["operacao_id"], {})} for r in matched]
    else:
        rows, unmatched = [], records
    local, _ = scope.local_rows(unmatched, aliases)
    rows += local
    snapshot = (g["metadata"].get("snapshot") or {}).get("snapshot_id")
    cpis = _cpis_families(c, snapshot)
    policies = priority.policies(c)
    overrides = priority.overrides(c)
    selection = scope.read(c)
    decisions = assignments.resolver(c, today)  # vigência das preferências no mesmo dia de Lisboa (F24)
    from . import machine_choice
    mctx = machine_choice.context(area, conn=c)
    facts = []
    rows_by_key = {}  # internal: the source row of each fact, for machine alternatives
    for row in rows:
        current = row.get("current_planning") or {}
        if "machine" in current:
            row = {**row, "maquina_original": current["machine"], "recurso_atual": aliases.get((area, current["machine"]))}
        if current.get("cut_date"):
            row = {**row, "data_corte_prevista": current["cut_date"]}
        if current.get("material_type"):
            row = {**row, "material_type": current["material_type"]}
        record = by_key.get(row.get("matched_application_key") or row.get("application_row_key")) or {}
        values, detail = record.get("values_json") or {}, record.get("detail") or {}
        raw = row.get("raw") or detail.get("raw") or {}
        uid, signature = integrated.identity(row)
        b = integrated.balance(row)
        remaining = b["planning_remaining"]
        principal = row["fase"] == "principal"
        if remaining == 0:
            continue  # nothing left of this operation; following operations keep their own rows
        started = bool((row.get("contador_excel") or 0) > 0 or row.get("execution_started"))
        of, reference = row["ordem_codigo"], row["referencia_original"]
        designation = values.get("designation") or raw.get("Designação") or ""
        signals = signals_of(designation, raw.get("Descrição") or values.get("notes") or "",
                             raw.get("Observações") or "", raw.get("Observações Galvanização") or "", values.get("status"),
                             detail.get("status_values"))
        # Mesma origem de prazo da Carteira e do Gantt (Picking atual da linha, Semana escolhida).
        marks = priority.milestones_from_values(priority.engine_values(row, values), raw,
                                                assumed_year=policies[area].get("assume_picking_year"))
        # A coluna W da importação atual (não a da pesquisa) diz se a linha está estacionada (S53-1).
        marks["parked"] = priority.parked_week((detail.get("raw") or raw).get("W"))
        due = priority.resolve(area, "principal" if principal else "following", marks, policy=policies[area],
                               override=priority.override_for(overrides, area, of, reference),
                               urgent=signals["prioridade"] is not None)
        day = date.fromisoformat(due["priority_day"]) if due["priority_day"] else None
        late_days = (today - day).days if day and day < today else 0
        mapping = detail.get("sku_family_mapping") or {}
        state = mapping.get("status") or STATUS_CODES.get(values.get("sku_family_status"))
        family = values.get("sku_family") or mapping.get("family")
        cpis_row = cpis.get(of) or {}
        cpis_code = (cpis_row.get("work_type_code") or "").strip() or None
        if principal and record:
            # Máquina efetiva (Carteira → Tabela → conjunto de famílias): a mesma da Carteira e do Gantt.
            found = machine_choice.effective(mctx, [record["row_key"], *(detail.get("selection_aliases") or [])],
                                             family, row.get("maquina_original"))
            if found["source"] in ("carteira", "conjunto"):
                code = next((k for k, r in codes.items() if r.get("id") == found["resource_id"]), None)
                row = {**row, "maquina_original": found["machine"], "recurso_atual": code}
        resource_code = row.get("recurso_atual")
        resource = codes.get(resource_code) if resource_code else None
        length = _number(row.get("comprimento_mm") if row.get("comprimento_mm") is not None else values.get("length_mm"))
        machine = machine_choice.normalize(row.get("maquina_original"))
        decision = decisions.lookup(area, row, signature, None)
        applied = decision if decision and decision["mode"] in ("assign", "prefer") else None
        assigned = (applied or {}).get("resource_id") or (resource["id"] if resource else None)
        # F01 (08/10): as horas só depois de decidida a máquina efetiva; as da Tabela só valem nessa máquina.
        hours, hours_origin, hours_reason, hours_machine, documentary_id = _hours(
            row, values, detail, area, remaining, effective_id=assigned, effective_machine=machine,
            resolve=lambda name: (codes.get(aliases.get((area, name))) or {}).get("id"))
        material = row.get("material_type") or values.get("material_type") or "Sem tipo"
        profile = (row.get("perfil") or values.get("profile") or "").strip() or "Sem perfil"
        group_name = assignments.profile_group(material, profile)
        rows_by_key["v2:" + uid] = row
        facts.append({
            "key": "v2:" + uid, "area": area, "unit": UNITS[area], "item": row["item_id"],
            "occurrence_key": assignments.occurrence_key(row),
            "line_key": record.get("row_key") or row.get("application_row_key"),
            "of": of, "ov": values.get("ov") or "", "customer": (values.get("customer") or "").strip() or "Sem cliente",
            "work": values.get("ov") or of, "designation": designation,
            "reference": reference or "Sem referência", "master": master_reference(reference) or UNRESOLVED,
            "sku_family": family or NO_FAMILY, "sku_family_state": state,
            "classification": CLASSIFICATION.get(state, "Sem catálogo") if family or state else ("Sem catálogo" if area == "perfis" else "Sem família"),
            "cpis_family_code": cpis_code,
            "cpis_family": f"{cpis_code} {(cpis_row.get('work_type_description') or '').strip()}".strip() if cpis_code else NO_CPIS_FAMILY,
            "material_type": material, "profile": profile, "profile_group": group_name,
            "length_mm": length, "pavilion": str(values.get("pavilion") or "Sem pavilhão"),
            "section_unit": _number(row.get("section_unit") if row.get("section_unit") is not None else values.get("section_unit")),
            "operation": row["operacao_codigo"], "operation_label": operation_label(row["operacao_codigo"]),
            "occurrence": row["ocorrencia"], "phase": "principal" if principal else "seguinte",
            "technical_signature": signature,
            "quantity_required": _number(row.get("quantidade_base")),
            "remaining": remaining, "balance_known": remaining is not None,
            "balance_provisional": b["balance_provisional"], "balance_origin": b["balance_origin"],
            "pieces": remaining if principal else None,
            "metres": remaining * length / 1000 if principal and remaining is not None and length else None,
            "machine": machine or NO_MACHINE, "resource_code": resource_code,
            "resource_id": resource["id"] if resource else None,
            "assigned_resource_id": assigned,
            "decision": decision,
            "hours": hours, "hours_origin": hours_origin, "hours_reason": hours_reason,
            # Máquina para que o motor de capacidade calculou as horas da Tabela (F01): aviso «iniciada na X».
            "hours_machine": hours_machine, "documentary_resource_id": documentary_id,
            "priority": due, "priority_day": due["priority_day"], "late": bool(late_days), "late_days": late_days,
            "window": priority.window(due, today), "started": started,
            "selection": scope.decision(selection, area, of, reference,
                                        [record["row_key"], *(detail.get("selection_aliases") or [])] if record else ()),
            "signals": signals, "status": values.get("status") or "Sem estado CPIS",
            "identity_source": "v2" if package and not row.get("application_row_key") else "aplicação",
        })
    names = {rid: r["name"] for rid, r in by_id.items()}
    for fact in facts:
        rid = fact["assigned_resource_id"]
        fact["assigned_machine"] = names.get(rid) or (fact["machine"] if rid == fact["resource_id"] else None) or NO_MACHINE
    from . import estimates, throughput
    study = throughput.load(c) if package else None
    from . import machine_learning
    learned = machine_learning.model(area, conn=c) if package else None
    # MTG2 sem débito observado: o equilíbrio usa as horas dos calendários do setor (auditoria 06/10, PROP-7).
    calendar = estimates.calendar_capacity(c, list(by_id), today) if package and area == "perfis" else None
    from ..raw.productivity import sector_timing, current_excel_area
    table = [cfg for cfg in configs if cfg["kind"] == "rate"]  # tabela de velocidades: antes do Excel, também nas sugeridas
    timing = sector_timing(c)[area]
    # Velocidade do Excel que o motor publicou por máquina e operação (F01, 08/10): a das horas noutra máquina.
    published = estimates.published_rates(records, lambda a, name: (codes.get(aliases.get((a, name))) or {}).get("id"),
                                          excel_area=current_excel_area(c) if area == "perfis" else None)
    # F25 (08/10): as linhas excluídas na Carteira não pesam nas sugestões (a Carga também as tira, load._context).
    excluded = {f["key"] for f in facts if f["selection"] == "excluded"}
    balance_info = estimates.apply(facts, rows_by_key, codes=codes, by_id=by_id, package=package, study=study, learned=learned,
                                   calendar=calendar, table=table, timing=timing, published=published, excluded=excluded)
    return {"area": area, "unit": UNITS[area], "generation": g["id"], "snapshot": snapshot,
            "imported_at": g["created_at"], "research_version": package["head"]["version_id"] if package else None,
            "today": today, "facts": facts, "resources": {rid: {k: r.get(k) for k in ("id", "code", "name", "type", "capacity")}
                                                          for rid, r in by_id.items()},
            "_rows": rows_by_key, "machine_balance": balance_info,
            "_estimate_inputs": {"table": table, "timing": timing, "published": published}}


def load(area: str, *, today: date | None = None, conn=None, allow_stale: bool = False) -> dict:
    """Current facts. Reads may get the previous result of the same day, marked stale, while a rebuild runs
    (one at a time, in the background); a request for a key already being computed waits for it (cache.py).

    Writes and previews never pass `allow_stale`: they always decide on the current versions.
    """
    planning.check_area(area)
    today = today or lisbon_today()  # dia de Lisboa, como a Carga (08/10)
    with (planning.connect(readonly=True) if conn is None else nullcontext(conn)) as c:
        if conn is None:
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        c.execute("SET LOCAL jit = off")
        key = stamp(c, area, today)

        def compute():
            result = build(c, area, today)
            result["stamp"] = needs.digest(key)
            result["stale"] = False
            return result
        return _cache.get(area, key, compute, allow_stale=allow_stale, stale_if=lambda old: old[-1] == today,
                          refresh=lambda: load(area, today=today))


def invalidate():
    _cache.clear()
