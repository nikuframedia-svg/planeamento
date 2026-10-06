"""Leitura da vista de necessidades: árvore, facetas, detalhe e explicação das famílias sem trabalho ativo.

Separada da simulação (Gantt) e da gravação de decisões. Cada resposta indica as versões usadas
(`stamps`) para que uma gravação posterior possa conferir que nada mudou entretanto.
"""
from __future__ import annotations

from collections import Counter
from datetime import date

from .. import planning, planning_needs as needs, planning_population
from . import occurrences, tree, sets as reference_sets


def _areas(value) -> list[str]:
    values = value if isinstance(value, list) else [value] if value else list(planning.AREAS)
    return [planning.check_area(v) for v in dict.fromkeys(values)]


def _load(c, areas, today):
    facts, stamps, memberships, names, meta = [], {}, {}, {}, {}
    for area in areas:
        data = occurrences.load(area, conn=c, today=today, allow_stale=True)
        facts += data["facts"]
        stamps[area] = data["stamp"]
        found, labels = reference_sets.memberships(c, area, data["facts"])
        memberships.update(found)
        names.update(labels)
        meta[area] = {"generation": data["generation"], "snapshot": data["snapshot"], "imported_at": data["imported_at"],
                      "research_version": data["research_version"], "stale": data.get("stale", False)}
    return facts, stamps, memberships, names, meta


def view(params: dict, today: date | None = None) -> dict:
    today = today or date.today()
    areas = _areas(params.get("areas"))
    dims = tree.dims_for(params.get("preset") or ("familias" if not params.get("dims") else None), params.get("dims"))
    filters = tree.clean_filters(params.get("filters"))
    try:
        horizon = int(params.get("horizon_weeks") or 12)
        offset, limit = int(params.get("offset") or 0), int(params.get("limit") or 100)
    except (TypeError, ValueError):
        raise planning.PlanningError("Horizonte ou paginação inválidos.") from None
    with planning.connect(readonly=True) as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        facts, stamps, memberships, names, meta = _load(c, areas, today)
        family_notes = history_of_families(c, areas, filters.get("sku_family") or [], facts) if filters.get("sku_family") else {}
    result = tree.build(facts, dims, params.get("path") or [], filters, today=today, horizon_weeks=horizon,
                        granularity=params.get("granularity") or "auto", sort=params.get("sort") or "urgencia",
                        offset=offset, limit=limit, sets=memberships, set_names=names)
    result.update(areas=areas, stamps=stamps, sources=meta, filters=filters, family_notes=family_notes,
                  scope="needs", scope_note="Carteira e necessidades: inclui trabalho não escolhido e bloqueado; não é ocupação reservada.")
    return needs.serial(result)


def facet_view(params: dict, today: date | None = None) -> dict:
    today = today or date.today()
    areas = _areas(params.get("areas"))
    with planning.connect(readonly=True) as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        facts, stamps, memberships, names, _ = _load(c, areas, today)
    return needs.serial({"facets": tree.facets(facts, memberships, names), "stamps": stamps,
                         "dimensions": tree.DIMENSIONS, "presets": {k: {"label": v[0], "dims": v[1]} for k, v in tree.PRESETS.items()},
                         "flags": tree.FLAGS, "windows": tree.WINDOWS})


def occurrence(area: str, key: str, today: date | None = None) -> dict:
    """Sources, route position, machine, alternatives, duration, quantity and decisions of one occurrence."""
    from . import assignments
    area = planning.check_area(area)
    with planning.connect(readonly=True) as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        data = occurrences.load(area, conn=c, today=today, allow_stale=True)
        fact = next((f for f in data["facts"] if f["key"] == key), None)
        if not fact:
            raise planning.PlanningError("Ocorrência indisponível nesta versão. Atualiza a vista.", 404)
        row = data["_rows"].get(key) or {}
        options = assignments.alternatives(c, data, fact)
        history = []
        if c.execute("SELECT to_regclass('planning_mtg.sector_machine_decision_history') t").fetchone()["t"]:
            history = c.execute("""SELECT h.at,h.before,h.after,a.mode,a.actor,a.reason,a.id action_id
                FROM planning_mtg.sector_machine_decision_history h JOIN planning_mtg.sector_machine_actions a ON a.id=h.action_id
                WHERE h.area=%s AND h.occurrence_key=%s ORDER BY h.id DESC LIMIT 20""", (area, fact["occurrence_key"])).fetchall()
        route = [{"operation": occurrences.operation_label(r["operacao_codigo"]), "occurrence": r["ocorrencia"]}
                 for r in data["_rows"].values() if r.get("item_id") == fact["item"]]
        memberships, names = reference_sets.memberships(c, area, [fact])
    return needs.serial({
        "occurrence": tree.leaf(fact), "alternatives": options, "decision_history": history,
        "route": sorted(route, key=lambda r: r["occurrence"]),
        "sets": [names.get(s, s) for s in memberships.get(key, [])],
        "sources": {"snapshot": row.get("snapshot_id"), "excel_row": row.get("excel_linha"),
                    "operation_id": row.get("operacao_id"), "line_key": fact["line_key"],
                    "identity": fact["identity_source"], "balance_origin": fact["balance_origin"],
                    "provisional": fact["balance_provisional"]},
        "stamp": data["stamp"],
    })


def history_of_families(c, areas, families, active_facts) -> dict:
    """A family with no active work explains why (e.g. M1 closed by the workbook macro)."""
    from ..raw import query
    result = {}
    active = Counter(f["sku_family"] for f in active_facts)
    for area in areas:
        wanted = [f for f in families if not active.get(f)]
        if not wanted:
            continue
        g = query.generation(c, area)
        base, args = query.source(g)
        rows = c.execute("SELECT c.values_json->>'sku_family' family, c.values_json->>'status' status, "
                         "c.values_json->>'closure_reason' closure, " + planning_population.active_sql() + " active" + base +
                         " AND c.values_json->>'sku_family' = ANY(%s)", args + [wanted]).fetchall()
        for family in wanted:
            found = [r for r in rows if r["family"] == family]
            if not found:
                continue
            result[family] = {
                "area": area, "history_lines": len(found), "active_lines": sum(bool(r["active"]) for r in found),
                "closure_reasons": dict(Counter(r["closure"] or "sem motivo registado" for r in found)),
                "cpis_states": dict(Counter(r["status"] or "Sem estado CPIS" for r in found)),
                "note": (f"{len(found)} linhas no histórico; 0 ativas pela regra atual de fecho. "
                         "O histórico fica consultável e não cria trabalho em atraso."),
            }
    return result
