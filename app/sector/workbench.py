"""Painel «Máquinas»: carga por máquina, sugestões de máquina e propostas de equilíbrio (1/10/2026).

Tudo aqui é leitura e proposta. Nada é gravado sem o planeador carregar em aplicar, e aplicar usa as
ações normais de máquina por grupo (com histórico, idempotência e desfazer).

Propostas de equilíbrio: nenhum trabalho é retirado, só muda a máquina de um lote (OF × operação × perfil,
que partilha preparação). Regras:
- só máquinas com capacidade semanal conhecida (confirmada, observada ou declarada) entram na conta;
- o lote inteiro tem de ter a máquina de destino como alternativa não excluída em todas as ocorrências;
- trabalho iniciado e escolhas explícitas gravadas na aplicação nunca são propostos para mudar;
- um movimento só é proposto se reduzir o pior dos dois tempos (origem e destino), em semanas de carga;
- nunca propõe destinos com condições de terceiros (mercado nacional, 112 → 119) nem máquinas onde o
  lote demora mais de 1,5 vezes: isso acrescentaria trabalho em vez de o aliviar;
- prefere destinos do mesmo processo (punção/broca), com menos condições e onde o lote é mais rápido;
- trabalho em atraso é movido primeiro, porque é o que mais ganha em sair da fila mais longa.
"""
from __future__ import annotations

from collections import defaultdict

from .. import planning, planning_needs as needs
from . import capacity, estimates, occurrences, throughput

MAX_PROPOSALS = 150
MIN_WEEKS = 2.0          # below this a machine is not considered overloaded
MAX_SLOWDOWN = 1.5       # a move may not make the lot take more than 1.5× its current hours
LABELS = {"admissible": "admissível", "conditional": "condicional", "excluded": "excluída"}


def _lanes(cap_view):
    lanes = {}
    for area, unit in cap_view["units"].items():
        for lane in unit["resources"]:
            lanes[(area, lane["resource_id"])] = {**lane, "area": area, "unit": unit["label"]}
    return lanes


def suggestion_groups(area, facts):
    """Facts with a suggested machine, grouped by set-up lot, most urgent first."""
    groups = defaultdict(list)
    for f in facts:
        if f.get("machine_basis") == "sugerida":
            groups[estimates.group_key(f)].append(f)
    result = []
    for key, items in groups.items():
        s = items[0]["suggestion"]
        hours = [f["load_hours"] for f in items if f.get("load_hours") is not None]
        result.append({
            "area": area, "of": key[0], "operation": items[0]["operation_label"], "profile": items[0]["profile"],
            "customer": items[0]["customer"], "sku_family": items[0]["sku_family"],
            "occurrences": len(items), "references": len({f["reference"] for f in items}),
            "keys": [f["key"] for f in items], "hours": round(sum(hours), 2), "unknown_hours": len(items) - len(hours),
            "late": sum(f["late"] for f in items), "max_late_days": max(f["late_days"] for f in items),
            "first_day": min((f["priority_day"] for f in items if f["priority_day"]), default=None),
            "machine": s["machine"], "resource_id": s["resource_id"], "reason": s["reason"],
            "process": s.get("process"), "conditions": sorted({c for f in items for c in (f["suggestion"].get("conditions") or [])}),
            "alternatives": s.get("alternatives", 1),
            "mixed": len({f["suggestion"]["resource_id"] for f in items}) > 1,
        })
    result.sort(key=lambda g: (-g["max_late_days"], g["first_day"] or "9999", -g["hours"], g["of"]))
    return result


def rebalance(c, area, data, lanes, *, study, by_id, limit=MAX_PROPOSALS):
    """Greedy, explained moves of whole set-up lots from the longest queues to machines with room."""
    from . import assignments
    evidence = assignments._evidence(c, data)
    if not evidence:
        return []
    names = throughput.aliases_to_names(by_id)
    from ..gantt import research
    rates = estimates.area_rates(research.load(c)["metadata"]) if research.enabled() else {}
    extra = data.get("_estimate_inputs") or {}  # tabela de velocidades e margem do setor, as mesmas da Carteira
    cap = {rid: lane["weekly_capacity_hours"] for (a, rid), lane in lanes.items()
           if a == area and lane["weekly_capacity_hours"] and lane["role"] in ("maquina", "posto_composto")}
    load = {rid: lanes[(area, rid)]["load_hours"] for rid in cap}
    weeks = lambda rid, extra=0.0: (load[rid] + extra) / cap[rid]
    processes = estimates.group_processes(data["facts"])
    groups = defaultdict(list)
    for f in data["facts"]:
        rid = f.get("planning_resource_id")
        if rid in cap and f.get("load_hours") is not None:
            groups[(rid, estimates.group_key(f))].append(f)
    candidates_cache, common_cache, hours_cache = {}, {}, {}

    def options(fact):
        if fact["key"] not in candidates_cache:
            row = data["_rows"].get(fact["key"])
            found = {}
            for o in (evidence["index"].candidates(row, evidence["codes"]) if row else []):
                if o.get("resource_id") and o["eligibility"] != "excluded":
                    found.setdefault(o["resource_id"], o)
            candidates_cache[fact["key"]] = found
        return candidates_cache[fact["key"]]

    def movable(items):
        return not any(f["started"] or (f.get("decision") or {}).get("mode") in ("assign", "stale") for f in items)

    proposals, moved = [], set()
    for _ in range(limit):
        ranked = sorted((rid for rid in cap if weeks(rid) > MIN_WEEKS), key=lambda r: -weeks(r))
        best = None
        for src in ranked:
            pool = [(k, items) for (rid, k), items in groups.items() if rid == src and (src, k) not in moved and movable(items)]
            pool.sort(key=lambda x: (-sum(f["late"] for f in x[1]), -sum(f["load_hours"] for f in x[1])))
            for key, items in pool[:400]:
                if key not in common_cache:
                    common = None
                    for f in items:
                        ids = set(options(f))
                        common = ids if common is None else common & ids
                    common_cache[key] = common or set()
                hours_from = sum(f["load_hours"] for f in items)
                for dst in common_cache[key] - {src}:
                    if dst not in cap:
                        continue
                    if (key, dst) not in hours_cache:
                        total = 0.0
                        for f in items:
                            h, _ = estimates.estimate(f, by_id.get(dst), names.get(dst, set()), study, rates,
                                                      table=extra.get("table"), timing=extra.get("timing"),
                                                      published=extra.get("published")) if study else (None, None)
                            total += h if h is not None else f["load_hours"]
                        hours_cache[(key, dst)] = total
                    hours_to = hours_cache[(key, dst)]
                    sample = options(items[0])[dst]
                    if estimates.PENALISED.intersection(sample.get("conditions", [])):
                        continue  # national market / 112→119 need a decision outside planning
                    if hours_from and hours_to > MAX_SLOWDOWN * hours_from:
                        continue  # a much slower machine adds work instead of relieving it
                    before = max(weeks(src), weeks(dst))
                    after = max(weeks(src, -hours_from), weeks(dst, hours_to))
                    if after >= before - 0.05:
                        continue
                    preferred = processes.get(key)
                    rank = (bool(preferred) and sample.get("process") != preferred, len(sample.get("conditions", [])),
                            round(hours_to / hours_from, 1) if hours_from else 1, after, -hours_from, dst)
                    if best is None or rank < best[0]:
                        best = (rank, src, dst, key, items, hours_from, hours_to, before, after, sample)
            if best:
                break
        if not best:
            break
        _, src, dst, key, items, hours_from, hours_to, before, after, sample = best
        proposals.append({
            "area": area, "of": key[0], "operation": items[0]["operation_label"], "profile": items[0]["profile"],
            "customer": items[0]["customer"], "occurrences": len(items), "keys": [f["key"] for f in items],
            "late": sum(f["late"] for f in items),
            "from_id": src, "from": by_id[src]["name"], "to_id": dst, "to": by_id[dst]["name"],
            "hours_from": round(hours_from, 2), "hours_to": round(hours_to, 2),
            "from_weeks": [round(weeks(src), 1), round(weeks(src, -hours_from), 1)],
            "to_weeks": [round(weeks(dst), 1), round(weeks(dst, hours_to), 1)],
            "gain_weeks": round(before - after, 1),
            "origin": "sugerida" if all(f.get("machine_basis") == "sugerida" for f in items) else "atribuída no Excel ou na aplicação",
            "process": sample.get("process"), "conditions": sorted(set(sample.get("conditions", []))),
            "eligibility": LABELS.get(sample.get("eligibility"), sample.get("eligibility")),
        })
        load[src] -= hours_from
        load[dst] += hours_to
        moved.add((src, key))
        groups[(dst, key)] = items
        moved.add((dst, key))  # never bounce the same lot back
    return proposals


_cache: dict = {}


def overview(areas=None, scenario="mediana", today=None):
    """Cached per data/decision stamps and scenario; the rebalance search is the costly part."""
    areas = [planning.check_area(a) for a in (areas or list(planning.AREAS))]
    if scenario not in capacity.SCENARIOS:
        raise planning.PlanningError("Cenário de capacidade inválido.")
    today = today or occurrences.lisbon_today()  # o dia de Lisboa das chaves das ocorrências (08/10)
    cap_view = capacity.view(areas, horizon_weeks=12, scenario=scenario, today=today)
    key = (tuple(areas), scenario, today, tuple(sorted((a, v["stamp"], v["stale"]) for a, v in cap_view["stamps"].items())))
    if _cache.get("key") == key:
        return _cache["value"]
    value = _overview(areas, scenario, today, cap_view)
    _cache.update(key=key, value=value)
    return value


def _overview(areas, scenario, today, cap_view):
    lanes = _lanes(cap_view)
    result = {"scenario": scenario, "scenarios": capacity.SCENARIOS, "today": today.isoformat(),
              "machines": [], "suggestions": [], "rebalance": [], "stamps": {}, "notes": [],
              "stale": any(v["stale"] for v in cap_view["stamps"].values())}
    with planning.connect(readonly=True) as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        _, by_id, _, _, package = occurrences.resources_context(c)
        study = throughput.load(c) if package else None
        for area in areas:
            data = occurrences.load(area, conn=c, today=today, allow_stale=True)
            result["stamps"][area] = data["stamp"]
            if data.get("stale"):
                result["notes"].append(f"{cap_view['units'][area]['label']}: a atualizar; números da versão anterior.")
            result["suggestions"] += suggestion_groups(area, data["facts"])
            result["rebalance"] += rebalance(c, area, data, lanes, study=study, by_id=by_id) if package else []
    for (area, rid), lane in lanes.items():
        if lane["role"] not in ("maquina", "posto_composto") and not lane["load_hours"]:
            continue
        result["machines"].append({
            "area": area, "unit": lane["unit"], "resource_id": rid, "name": lane["name"], "role": lane["role"],
            "load_hours": lane["load_hours"], "estimated_hours": lane["estimated_hours"],
            "suggested_occurrences": lane["suggested_occurrences"], "unknown_occurrences": lane["unknown_occurrences"],
            "late_hours": lane["late_need_hours"], "weekly_capacity_hours": lane["weekly_capacity_hours"],
            "capacity_status": lane["weekly_capacity_status"], "weeks": lane["weeks_to_clear"],
            "capacity_source": next((p["capacity_source"] for p in lane["periods"] if p.get("capacity_source")), None),
            "families": lane["families"][:4],
            "after_rebalance_weeks": None,
        })
    # Effect of applying every proposal, per machine.
    delta = defaultdict(float)
    for p in result["rebalance"]:
        delta[(p["area"], p["from_id"])] -= p["hours_from"]
        delta[(p["area"], p["to_id"])] += p["hours_to"]
    for m in result["machines"]:
        if m["weekly_capacity_hours"] and (m["area"], m["resource_id"]) in delta:
            m["after_rebalance_weeks"] = round((m["load_hours"] + delta[(m["area"], m["resource_id"])]) / m["weekly_capacity_hours"], 1)
    result["machines"].sort(key=lambda m: (-(m["weeks"] or -1), m["name"]))
    result["summary"] = {area: {"suggested_groups": sum(g["area"] == area for g in result["suggestions"]),
                                "suggested_occurrences": sum(g["occurrences"] for g in result["suggestions"] if g["area"] == area),
                                "moves": sum(p["area"] == area for p in result["rebalance"])} for area in areas}
    return needs.serial(result)
