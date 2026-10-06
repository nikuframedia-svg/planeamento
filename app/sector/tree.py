"""Árvore compacta e desdobrável sobre a base de operações (plano de 01/10/2026, secção 5).

Puro: recebe ocorrências (`occurrences.build`) e devolve grupos com totais calculados no servidor.
- Vários valores no mesmo filtro combinam-se por OU; filtros diferentes por E.
- Contagens e pesquisa abrangem toda a população elegível, não a página carregada.
- As OF e referências distintas recalculam-se em cada grupo; nunca se somam as dos filhos.
- Peças e metros contam uma vez por item (operação principal); horas somam-se por ocorrência.
- A procura por período usa o prazo de prioridade: é procura de capacidade, não ocupação reservada.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta

from .. import planning

NO_DATE = "sem_data"
LATE = "atrasado"
AFTER = "depois"

DIMENSIONS = {
    "unit": "Setor",
    "sku_family": "Família SKU",
    "classification": "Estado da família",
    "cpis_family": "Família da encomenda (CPIS)",
    "material_type": "Tipo de material",
    "profile": "Perfil",
    "master": "Referência mestre",
    "reference": "Referência (SKU)",
    "of": "OF",
    "work": "Obra / OV",
    "customer": "Cliente",
    "machine": "Máquina atribuída",
    "machine_planned": "Máquina atribuída ou sugerida",
    "machine_documented": "Máquina indicada no planeamento",
    "operation": "Operação",
    "window": "Prazo",
    "set": "Conjunto de referências",
}
PRESETS = {
    "familias": ("Famílias", ["unit", "sku_family", "profile", "reference", "of"]),
    "perfis": ("Perfis", ["unit", "material_type", "profile", "reference", "of"]),
    "conjuntos": ("Conjuntos", ["set", "reference", "of"]),
    "maquinas": ("Máquinas", ["machine_planned", "sku_family", "of", "reference"]),
    "encomendas": ("Encomendas", ["work", "of", "sku_family", "reference"]),
}
WINDOWS = {
    "atrasado": "Prazo já passado",
    "3_semanas": "Até ao fim da semana ISO +2",
    "mais_tarde": "Mais tarde",
    "sem_data": "Sem prazo",
}
FLAGS = {
    "late": "Atrasado pelo marco do setor",
    "no_machine": "Sem máquina",
    "no_hours": "Sem horas",
    "unknown_balance": "Saldo por esclarecer",
    "started": "Iniciado",
    "no_date": "Sem prazo",
    "suggested": "Máquina sugerida (por decidir)",
    "estimated": "Horas estimadas",
    "no_load": "Sem horas nem estimativa",
}
SELECTION = {"selected": "Marcado para planear", "excluded": "Excluído", "none": "Sem decisão"}
MAX_LEVELS = 7


def value_of(fact: dict, dim: str, sets: dict | None = None):
    """Grouping value; `set` returns every membership (a fact may belong to several)."""
    if dim == "machine":
        return fact["assigned_machine"]
    if dim == "machine_documented":
        return fact["machine"]
    if dim == "machine_planned":
        return fact.get("planning_machine") or fact["assigned_machine"]
    if dim == "operation":
        return fact["operation_label"]
    if dim == "profile":
        return fact["profile_group"]
    if dim == "set":
        return (sets or {}).get(fact["key"]) or ["Fora de conjuntos"]
    return fact.get(dim)


def check_dims(dims) -> list[str]:
    if not isinstance(dims, list) or not 1 <= len(dims) <= MAX_LEVELS or any(d not in DIMENSIONS for d in dims) or len(set(dims)) != len(dims):
        raise planning.PlanningError(f"Escolhe entre 1 e {MAX_LEVELS} níveis diferentes para agrupar.")
    return list(dims)


def dims_for(preset: str | None, dims=None) -> list[str]:
    if dims:
        return check_dims(dims)
    if preset not in PRESETS:
        raise planning.PlanningError("Vista inválida.")
    return list(PRESETS[preset][1])


def _listed(value) -> list[str]:
    if value in (None, "", []):
        return []
    values = value if isinstance(value, list) else [value]
    if len(values) > 500 or any(not isinstance(v, str) or len(v) > 300 for v in values):
        raise planning.PlanningError("Filtro inválido.")
    return [v for v in values if v != ""]


def clean_filters(filters: dict | None) -> dict:
    """Only allowed fields; each value list is OR, fields are AND."""
    filters = dict(filters or {})
    clean = {}
    for name, value in filters.items():
        if name in DIMENSIONS:
            values = _listed(value)
            if values:
                clean[name] = values
        elif name == "flags":
            values = _listed(value)
            if any(v not in FLAGS for v in values):
                raise planning.PlanningError("Filtro de pendência inválido.")
            if values:
                clean["flags"] = values
        elif name == "selection":
            values = _listed(value)
            if any(v not in SELECTION for v in values):
                raise planning.PlanningError("Filtro de seleção inválido.")
            if values:
                clean["selection"] = values
        elif name == "q":
            text = str(value or "").strip()
            if len(text) > 200:
                raise planning.PlanningError("Pesquisa demasiado longa.")
            if text:
                clean["q"] = text.upper()
        elif name in ("from", "to"):
            if value:
                try:
                    clean[name] = date.fromisoformat(str(value)[:10]).isoformat()
                except ValueError:
                    raise planning.PlanningError("Intervalo de datas inválido.") from None
        elif value not in (None, "", []):
            raise planning.PlanningError(f"Filtro desconhecido: {name}.")
    return clean


def _flag(fact: dict, flag: str) -> bool:
    return {"late": fact["late"], "no_machine": fact["assigned_machine"] == "Sem máquina",
            "no_hours": fact["hours"] is None, "unknown_balance": not fact["balance_known"],
            "started": fact["started"], "no_date": not fact["priority_day"],
            "suggested": fact.get("machine_basis") == "sugerida", "estimated": fact.get("load_basis") == "estimada",
            "no_load": fact.get("load_hours") is None}[flag]


def matches(fact: dict, filters: dict, sets: dict | None = None) -> bool:
    for name, values in filters.items():
        if name in DIMENSIONS:
            if not set(values).intersection(values_of(fact, name, sets)):
                return False
        elif name == "flags":
            if not any(_flag(fact, flag) for flag in values):
                return False
        elif name == "selection":
            if (fact["selection"] or "none") not in values:
                return False
        elif name == "q":
            haystack = " ".join(str(fact.get(k) or "") for k in ("of", "ov", "reference", "master", "customer", "designation", "sku_family")).upper()
            if values not in haystack:
                return False
        elif name == "from":
            if not fact["priority_day"] or fact["priority_day"] < values:
                return False
        elif name == "to":
            if not fact["priority_day"] or fact["priority_day"] > values:
                return False
    return True


def values_of(fact: dict, dim: str, sets: dict | None = None) -> list[str]:
    value = value_of(fact, dim, sets)
    return [str(v) for v in value] if isinstance(value, list) else [str(value)]


def select(facts: list[dict], dims: list[str], path: list[str], filters: dict, sets: dict | None = None) -> list[dict]:
    if len(path) > len(dims):
        raise planning.PlanningError("Grupo inválido.")
    chosen = [f for f in facts if matches(f, filters, sets)]
    for dim, key in zip(dims, path):
        chosen = [f for f in chosen if key in values_of(f, dim, sets)]
    return chosen


def periods(today: date, horizon_weeks: int, granularity: str = "auto") -> list[dict]:
    """Daily/weekly near the start, monthly for the far horizon; one consistent time base."""
    if not 1 <= horizon_weeks <= 52:
        raise planning.PlanningError("Escolhe um horizonte entre 1 e 52 semanas.")
    monday = today - timedelta(days=today.weekday())
    end = monday + timedelta(weeks=horizon_weeks)
    result = []
    weekly_until = end if granularity == "week" or (granularity == "auto" and horizon_weeks <= 26) else monday + timedelta(weeks=26)
    day = monday
    while day < min(weekly_until, end):
        year, week, _ = day.isocalendar()
        result.append({"key": f"{year}-W{week:02d}", "start": day.isoformat(),
                       "end": (day + timedelta(days=7)).isoformat(), "label": f"W{week:02d}", "kind": "week"})
        day += timedelta(days=7)
    while day < end:
        month_end = (day.replace(day=1) + timedelta(days=32)).replace(day=1)
        stop = min(month_end, end)
        result.append({"key": f"{day.year}-{day.month:02d}" + ("" if day.day == 1 else f"-{day.day:02d}"),
                       "start": day.isoformat(), "end": stop.isoformat(),
                       "label": day.strftime("%m/%Y"), "kind": "month"})
        day = stop
    return result


def bucket(day_text: str | None, today: date, slots: list[dict]) -> str:
    if not day_text:
        return NO_DATE
    if day_text < today.isoformat():
        return LATE
    for slot in slots:
        if slot["start"] <= day_text < slot["end"]:
            return slot["key"]
    return AFTER


def summary(facts: list[dict], today: date, slots: list[dict]) -> dict:
    """Group totals, every measure at its own level."""
    principal = [f for f in facts if f["phase"] == "principal"]
    hours = [f["hours"] for f in facts if f["hours"] is not None]
    positive = [f for f in facts if f["balance_known"] and (f["remaining"] or 0) > 0]
    with_hours = sum(f["hours"] is not None for f in positive)
    # Machines and demand use the planning machine (assigned, else suggested) and the load hours
    # (documentary, else estimated); the estimated and suggested parts stay counted apart.
    machines = defaultdict(lambda: {"occurrences": 0, "hours": 0.0, "unknown_hours": 0, "suggested": 0, "estimated_hours": 0.0})
    for f in facts:
        m = machines[f.get("planning_machine") or f["assigned_machine"]]
        m["occurrences"] += 1
        m["suggested"] += f.get("machine_basis") == "sugerida"
        load = f.get("load_hours", f["hours"])
        if load is None:
            m["unknown_hours"] += 1
        else:
            m["hours"] += load
            if f.get("load_basis") == "estimada":
                m["estimated_hours"] += load
    demand = defaultdict(float)
    estimated_demand = defaultdict(float)
    unknown_demand = Counter()
    for f in facts:
        slot = bucket(f["priority_day"], today, slots)
        load = f.get("load_hours", f["hours"])
        if load is None:
            unknown_demand[slot] += 1
        else:
            demand[slot] += load
            if f.get("load_basis") == "estimada":
                estimated_demand[slot] += load
    days = sorted(f["priority_day"] for f in facts if f["priority_day"])
    upcoming = [d for d in days if d >= today.isoformat()]
    return {
        "occurrences": len(facts),
        "items": len({f["item"] for f in facts}),
        "ofs": len({(f["area"], f["of"]) for f in facts}),
        "references": len({(f["area"], f["reference"]) for f in facts}),
        "pieces": round(sum(f["pieces"] for f in principal if f["pieces"] is not None), 3),
        "metres": round(sum(f["metres"] for f in principal if f["metres"] is not None), 1),
        "unknown_balances": sum(not f["balance_known"] for f in facts),
        "hours_known": round(sum(hours), 2),
        "hours_coverage": round(with_hours / len(positive), 4) if positive else None,
        "hours_covered": with_hours, "hours_basis": len(positive),
        "late_hours": round(sum(f["hours"] for f in facts if f["late"] and f["hours"] is not None), 2),
        "hours_estimated": round(sum(f["load_hours"] for f in facts if f.get("load_basis") == "estimada"), 2),
        "load_hours": round(sum(f["load_hours"] for f in facts if f.get("load_hours") is not None), 2),
        "late_load_hours": round(sum(f["load_hours"] for f in facts if f["late"] and f.get("load_hours") is not None), 2),
        "suggested": sum(f.get("machine_basis") == "sugerida" for f in facts),
        "no_load": sum(f.get("load_hours") is None for f in facts),
        "late_occurrences": sum(f["late"] for f in facts),
        "max_late_days": max((f["late_days"] for f in facts), default=0),
        "first_priority_day": days[0] if days else None,
        "last_priority_day": days[-1] if days else None,
        "next_priority_day": upcoming[0] if upcoming else None,
        "machines": sorted(({"machine": k, **{x: round(y, 2) if isinstance(y, float) else y for x, y in v.items()}}
                            for k, v in machines.items()), key=lambda m: (-m["occurrences"], m["machine"])),
        "pending": {"no_machine": sum(f["assigned_machine"] == "Sem máquina" for f in facts),
                    "no_hours": sum(f["hours"] is None for f in facts),
                    "unknown_balance": sum(not f["balance_known"] for f in facts),
                    "no_date": sum(not f["priority_day"] for f in facts)},
        "classification": dict(Counter(f["classification"] for f in facts)),
        "selection": dict(Counter(f["selection"] or "none" for f in facts)),
        "demand": {k: round(v, 2) for k, v in demand.items()},
        "estimated_demand": {k: round(v, 2) for k, v in estimated_demand.items()},
        "unknown_demand": dict(unknown_demand),
        "started": sum(f["started"] for f in facts),
    }


def _urgency(group: dict):
    s = group["summary"]
    return (-s["max_late_days"], s["first_priority_day"] or "9999", -s["hours_known"], str(group["key"]))


SORTS = {
    "urgencia": _urgency,
    "horas": lambda g: (-g["summary"]["hours_known"], str(g["key"])),
    "nome": lambda g: str(g["key"]),
    "atraso": lambda g: (-g["summary"]["late_hours"], -g["summary"]["max_late_days"], str(g["key"])),
}
LEAF_SORTS = {
    "urgencia": lambda f: (-f["late_days"], f["priority_day"] or "9999", f["of"], f["reference"], f["occurrence"]),
    "horas": lambda f: (-(f["hours"] or 0), f["of"], f["reference"], f["occurrence"]),
    "nome": lambda f: (f["of"], f["reference"], f["occurrence"]),
    "atraso": lambda f: (-f["late_days"], -(f["hours"] or 0), f["of"], f["occurrence"]),
}


def leaf(fact: dict) -> dict:
    """Public detail of one occurrence (sources, route position, machine, duration, quantity)."""
    return {k: fact.get(k) for k in (
        "key", "area", "unit", "of", "ov", "customer", "reference", "master", "sku_family", "sku_family_state",
        "classification", "cpis_family", "material_type", "profile", "length_mm", "pavilion", "operation",
        "operation_label", "occurrence", "phase", "quantity_required", "remaining", "balance_known",
        "balance_provisional", "balance_origin", "pieces", "metres", "machine", "assigned_machine",
        "assigned_resource_id", "resource_id", "decision", "hours", "hours_origin", "hours_reason", "priority",
        "planning_resource_id", "planning_machine", "machine_basis", "suggestion", "load_hours", "load_basis", "load_origin",
        "priority_day", "late", "late_days", "window", "started", "selection", "status", "designation",
        "identity_source")}


def build(facts: list[dict], dims: list[str], path: list[str], filters: dict, *, today: date, horizon_weeks: int = 12,
          granularity: str = "auto", sort: str = "urgencia", offset: int = 0, limit: int = 100,
          sets: dict | None = None, set_names: dict | None = None) -> dict:
    if sort not in SORTS:
        raise planning.PlanningError("Ordenação inválida.")
    if not 0 <= offset <= 10_000_000 or not 1 <= limit <= 500:
        raise planning.PlanningError("Paginação inválida.")
    path = [str(p) for p in path or []]
    if len(path) > len(dims):
        raise planning.PlanningError("Não há mais níveis nesta vista.")
    slots = periods(today, horizon_weeks, granularity)
    filtered = [f for f in facts if matches(f, filters, sets)]
    chosen = select(filtered, dims, path, {}, sets)
    result = {
        "dims": [{"id": d, "label": DIMENSIONS[d]} for d in dims], "path": path,
        "periods": slots, "today": today.isoformat(),
        "population": summary(facts, today, slots), "filtered": summary(filtered, today, slots),
        "here": summary(chosen, today, slots), "offset": offset, "limit": limit,
    }
    if len(path) == len(dims):
        leaves = sorted(chosen, key=LEAF_SORTS[sort])
        result.update(level={"id": "occurrence", "label": "Ocorrência de operação"}, kind="occurrences",
                      count=len(leaves), rows=[leaf(f) for f in leaves[offset:offset + limit]])
        return result
    dim = dims[len(path)]
    buckets = defaultdict(list)
    for f in chosen:
        for v in values_of(f, dim, sets):
            buckets[v].append(f)
    groups = [{"key": k, "label": (set_names or {}).get(k, k) if dim == "set" else WINDOWS.get(k, k) if dim == "window" else k,
               "summary": summary(v, today, slots)} for k, v in buckets.items()]
    groups.sort(key=SORTS[sort])
    result.update(level={"id": dim, "label": DIMENSIONS[dim]}, kind="groups", count=len(groups),
                  rows=groups[offset:offset + limit], has_children=True)
    return result


def facets(facts: list[dict], sets: dict | None = None, set_names: dict | None = None, limit: int = 400) -> dict:
    """Filter options with counts over the whole eligible population."""
    result = {}
    for dim in ("unit", "sku_family", "classification", "cpis_family", "material_type", "profile", "machine",
                "machine_planned", "machine_documented", "operation", "window", "customer"):
        counts = Counter(str(value_of(f, dim)) for f in facts)
        result[dim] = [{"value": k, "label": WINDOWS.get(k, k) if dim == "window" else k, "count": n}
                       for k, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]
    if sets is not None:
        counts = Counter(s for f in facts for s in (sets.get(f["key"]) or []))
        result["set"] = [{"value": k, "label": (set_names or {}).get(k, k), "count": n} for k, n in counts.most_common(limit)]
    result["flags"] = [{"value": k, "label": v, "count": sum(_flag(f, k) for f in facts)} for k, v in FLAGS.items()]
    result["selection"] = [{"value": k, "label": v, "count": sum((f["selection"] or "none") == k for f in facts)} for k, v in SELECTION.items()]
    return result
