"""Vistas da Carga por setor, perfil, família de produto e família SKU (P10, plano de 08/10/2026).

A mesma população e a mesma semana da grelha das Máquinas; nada se reclassifica aqui:
- ocorrências de load._context (as linhas excluídas na Carteira já saíram) e semana por load.classify sobre
  load.week_list: a semana do prazo, como na Carteira;
- só entram as ocorrências que caem numa linha de máquina da Carga (load.overview). As sem máquina e as de máquinas
  de outro setor ficam fora, como na grelha (contadas à parte); a 2.ª operação das cantoneiras também
  (second_operation.operation), como na Carga;
- colunas: Atrasado (prazo antes desta semana), as 13 semanas, Sem prazo e Mais tarde;
- horas desconhecidas nunca contam como 0: contam-se à parte («*» no ecrã);
- metros e peças só da operação principal e só dentro de um setor (nunca se somam entre setores); kg = o peso da
  Carteira (load.fact_weight);
- capacidade só na vista Setores: a da grelha das Máquinas (semana inteira), somada com capacity.counted(); um posto
  com calendário (Serrote Fita pav.1) substitui as máquinas que o compõem (Doall, Thomas): conta uma vez.
Por isso cada vista soma, semana a semana, o mesmo que as máquinas da Carga.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from .. import planning, planning_needs as needs
from . import cache, load
from .portfolio import SECTORS

try:  # 2.ª operação das cantoneiras (P3): fora da Carga; sem o módulo, nada sai (como antes)
    from . import second_operation as _second
except ImportError:  # pragma: no cover - só enquanto a parte da 2.ª operação não estiver junta
    _second = None

BY = {"setor": "Setores", "perfil": "Perfis", "familia": "Famílias de produto", "familia_sku": "Famílias SKU"}
UNITS = {"setor": ("h", "kg"), "perfil": ("h", "m", "pecas"), "familia": ("h", "m", "pecas"), "familia_sku": ("h", "m", "pecas")}
LATE, NO_DATE, AFTER = "atrasado", "sem_prazo", "mais_tarde"
TEXT = {"h": "Horas", "m": "Metros", "pecas": "Peças", "kg": "Peso (kg)"}
FAMILY_NOTE = "Família de Produto = tipo de obra do CPIS, por OF. Família SKU = grupo de referências, por peça; só MTG3."
NO_SKU = "A MTG2 ainda não tem famílias SKU."
_FIELD = {"h": "hours", "m": "metres", "pecas": "pieces", "kg": "kg"}

# Uma entrada por (setor, vista): no máximo 4 por setor. A chave é o carimbo das ocorrências e as decisões.
_cache = cache.Cache("Vistas da Carga")


KEYS = {  # a chave de cada vista, por ocorrência (os campos que as ocorrências já trazem)
    "setor": lambda sector, f: sector,
    "perfil": lambda sector, f: f.get("profile_group") or "Sem perfil",
    "familia": lambda sector, f: f.get("cpis_family") or "Sem família",
    "familia_sku": lambda sector, f: f.get("sku_family") or "Sem família SKU",
}


def _empty() -> dict:
    return {"hours": 0.0, "hours_unknown": 0, "operations": 0, "metres": 0.0, "metres_unknown": 0,
            "pieces": 0.0, "pieces_unknown": 0, "kg": 0.0, "kg_unknown": 0, "plan": 0.0, "due": 0.0, "suggested": 0.0}


def _add(acc: dict, fact: dict, kind: str, weight: float | None) -> None:
    """Uma ocorrência numa célula: horas (desconhecidas à parte) e, só na principal, metros, peças e kg."""
    extra = bool(fact.get("_extra"))  # resto de uma operação planeada em parte (load.split_facts): conta uma vez
    acc["operations"] += not extra
    hours = fact.get("load_hours")
    if hours is None:
        acc["hours_unknown"] += not extra
    else:
        acc["hours"] += hours
        acc[kind] += hours
    if fact.get("phase", "principal") != "principal":
        return
    for field, value in (("metres", fact.get("metres")), ("pieces", fact.get("pieces")), ("kg", weight)):
        if value is None:
            acc[field + "_unknown"] += not extra
        else:
            acc[field] += value


def _merge(into: dict, acc: dict) -> None:
    for k, v in acc.items():
        into[k] += v


def second_operation(sector: str, fact: dict) -> bool:
    """A Carga tira a 2.ª operação das cantoneiras (P3); estas vistas também."""
    return bool(_second and _second.operation(sector, fact))


def slot_of(fact: dict, planned: set, current: tuple[int, int], horizon: set, today: date) -> tuple[str, object] | None:
    """(tipo, coluna) de uma ocorrência na grelha da Carga: a semana de load.classify; o prazo antes desta semana vai
    para Atrasado (load._before_week), como a coluna Atrasado das Máquinas. None = sem máquina."""
    found = load.classify(fact, planned, current, horizon, today)
    if not found:
        return None
    kind, week, _ = found
    if week == "depois":
        return kind, AFTER
    if week == "sem_data":
        return kind, NO_DATE
    if week == current and load._before_week(fact, date.fromisocalendar(*current, 1)):
        return kind, LATE
    return kind, week


def _population(sector: str, own: set, today: date, context=None):
    """(ocorrência, tipo, coluna) das ocorrências da grelha das Máquinas, e quantas ficaram fora (sem máquina ou em
    máquina de outro setor). A 2.ª operação das cantoneiras sai sem contar (tem a sua linha na Carga)."""
    data, planned, occ = context or load._context(sector, today)
    weeks = load.week_list(today)
    horizon, current = set(weeks), weeks[0]
    out, outside = [], 0
    for f in load.split_facts(occ["facts"], planned, data["lines"]):
        if second_operation(sector, f):
            continue
        found = slot_of(f, planned, current, horizon, today)
        if found is None or f.get("planning_resource_id") not in own:
            outside += not f.get("_extra")
            continue
        out.append((f, *found))
    return out, outside, load.weights_of(data["lines"])


def _context_key(context, today: date) -> tuple:
    data, planned, occ = context
    return (occ.get("stamp"), len(occ["facts"]), len(data["lines"]), hash(frozenset(planned.items() if isinstance(planned, dict) else planned)), today)


def _aggregate(sector: str, por: str, today: date, now: datetime, context=None) -> dict:
    """Células de uma vista num setor (todas as unidades), guardadas pelo carimbo das ocorrências e das decisões."""
    context = context or load._context(sector, today)

    def build():
        overview = load.overview(sector, today=today, now=now)
        machines = {m["id"]: m["name"] for m in overview["machines"]}
        rows, outside, weights = _population(sector, set(machines), today, context)
        groups = {}
        for f, kind, slot in rows:
            key = KEYS[por](sector, f)
            g = groups.setdefault(key, {"cells": {}, "profiles": {}, "sections": {}})
            _add(g["cells"].setdefault(slot, _empty()), f, kind, load.fact_weight(f, weights))
            if por == "perfil":
                g["profiles"][f.get("profile")] = f.get("material_type")
                if f.get("section_unit"):
                    g["sections"][f["section_unit"]] = g["sections"].get(f["section_unit"], 0) + 1
        return {"groups": groups, "outside": outside, "machines": machines,
                "stale": bool(context[2].get("stale") or context[0].get("stale"))}
    return _cache.get((sector, por), (por, *_context_key(context, today)), build)


def dimension(sector: str, group: dict) -> dict | None:
    """Coluna Dimensão dos Perfis: MTG3 aba e espessura (gantt.machines.dimensions); MTG2 tipo e área de corte mm²."""
    profile, material = next(iter(group["profiles"].items()), (None, None))
    if sector == "cantoneiras":
        from ..gantt.machines import dimensions
        found = dimensions(profile)
        return {"aba": found[0], "aba2": found[1], "esp": found[2]} if found else None
    area = max(group["sections"].items(), key=lambda kv: (kv[1], kv[0]))[0] if group["sections"] else None
    return {"tipo": material, "area_mm2": round(area, 1) if area is not None else None} if material or area else None


def _cell(acc: dict, unit: str) -> dict:
    field = _FIELD[unit]
    return {"value": round(acc[field], 1), "unknown": acc[field + "_unknown"], "operations": acc["operations"]}


def _row(cells: dict, weeks: list, unit: str) -> dict:
    total = _empty()
    for acc in cells.values():
        _merge(total, acc)
    return {"late_before": _cell(cells.get(LATE) or _empty(), unit),
            "weeks": [_cell(cells.get(w) or _empty(), unit) for w in weeks],
            "no_date": _cell(cells.get(NO_DATE) or _empty(), unit), "after": _cell(cells.get(AFTER) or _empty(), unit),
            "total": _cell(total, unit)}


def sector_capacity(rows: list[dict], posts: dict) -> tuple[list[float | None], list[str]]:
    """Capacidade do setor por semana, sem contar a dobrar (capacity.counted, F18): a da grelha das Máquinas (semana
    inteira) das máquinas com calendário; um posto com calendário substitui as máquinas que o compõem.
    Devolve também os postos que substituíram máquinas da grelha (para a nota «conta uma vez»)."""
    from .capacity import counted
    members = {post: list(ms) for post, ms in (posts or {}).items()}
    resources = {rid: {"id": rid} for rid in {r["id"] for r in rows} | set(members) | {m for ms in members.values() for m in ms}}
    shape = {"roles": {rid: "maquina" for rid in resources if rid not in members}, "members": members}
    shown = {r["id"] for r in rows}
    out, merged = [], set()
    for i in range(max((len(r["weeks"]) for r in rows), default=0)):
        caps = {r["id"]: r["weeks"][i]["full_capacity"] for r in rows
                if r.get("has_calendar", True) and r["weeks"][i].get("status") != "sem_calendario"}
        chosen = counted(resources, caps, shape=shape)
        merged |= {post for post in chosen if post in members and set(members[post]) & shown}
        known = [caps[rid] for rid in chosen if caps.get(rid) is not None]
        out.append(round(sum(known), 1) if known else None)
    return out, sorted(merged)


def _setor_capacity(sector: str, today: date, now: datetime) -> tuple[list, str | None]:
    from . import load_sources
    overview = load.overview(sector, today=today, now=now)
    with planning.connect(readonly=True) as c:
        src = load_sources.context(c, sector)
    capacity, merged = sector_capacity(overview["machines"], src.get("posts") or {})
    names = {**{m["id"]: m["name"] for m in overview["machines"]}, **(src.get("names") or {})}
    notes = [f"{names.get(p, p)} é um posto com {' e '.join(names.get(m, m) for m in (src.get('posts') or {})[p])}: conta uma vez."
             for p in merged]
    return capacity, " ".join(notes) or None


def view(sector: str, por: str, unit: str = "h", *, today: date | None = None, now: datetime | None = None) -> dict:
    """GET /api/setor/carga/vista: uma linha por grupo, colunas Atrasado · 13 semanas · Sem prazo · Mais tarde."""
    planning.check_area(sector)
    if por not in BY:
        raise planning.PlanningError("Vista inválida.")
    if unit not in _FIELD:
        raise planning.PlanningError("Unidade inválida.")
    unit = unit if unit in UNITS[por] else UNITS[por][0]  # Setores fica em horas ou kg: nunca metros nem peças
    today = today or load._today()
    now = now or datetime.now(timezone.utc)
    weeks = load.week_list(today)
    base = {"sector": sector, "por": por, "label": BY[por], "unit": unit, "units": list(UNITS[por]),
            "text": f"{TEXT[unit]} do trabalho aberto na semana do prazo (como na Carteira).",
            "note": FAMILY_NOTE if por in ("familia", "familia_sku") else None,
            "weeks": [{"year": y, "week": w, "monday": date.fromisocalendar(y, w, 1)} for y, w in weeks]}
    if por == "familia_sku" and sector == "perfis":
        return needs.serial({**base, "note": None, "rows": [], "total": None, "outside": 0, "stale": False, "empty": NO_SKU})
    sectors = ["perfis", "cantoneiras"] if por == "setor" else [sector]
    rows, outside, stale, notes = [], 0, False, []
    total = {}
    for s in sectors:
        agg = _aggregate(s, por, today, now)
        outside += agg["outside"]
        stale = stale or agg["stale"]
        capacity = None
        if por == "setor":
            capacity, note = _setor_capacity(s, today, now)
            if note:
                notes.append(note)
        groups = agg["groups"] or ({s: {"cells": {}}} if por == "setor" else {})  # Setores: sempre as duas linhas
        for key, g in groups.items():
            for slot, acc in g["cells"].items():
                _merge(total.setdefault(slot, _empty()), acc)
            row = {"key": key, "label": SECTORS[key] if por == "setor" else key, **_row(g["cells"], weeks, unit)}
            if por == "perfil":
                row["dimension"] = dimension(s, g)
            if capacity is not None and unit == "h":
                for cell, cap in zip(row["weeks"], capacity):
                    cell["capacity"] = cap
                    cell["pct"] = round(100 * cell["value"] / cap) if cap else None
            rows.append(row)
    rows.sort(key=lambda r: (-r["total"]["value"], -r["total"]["operations"], str(r["label"])))
    return needs.serial({**base, "note": " ".join(dict.fromkeys(notes)) or base["note"], "rows": rows,
                         "total": {"key": None, "label": "Total", **_row(total, weeks, unit)} if rows else None,
                         "outside": outside, "stale": stale, "empty": None})


def _slot_param(year, week, weeks: list) -> object:
    if str(week) in (LATE, NO_DATE, AFTER):
        return str(week)
    try:
        target = (int(year), int(week))
    except (TypeError, ValueError):
        raise planning.PlanningError("Semana inválida.") from None
    if target not in weeks:
        raise planning.PlanningError("Semana fora das 13 semanas da Carga.")
    return target


def cell(sector: str, por: str, key: str, year, week, *, today: date | None = None, now: datetime | None = None) -> dict:
    """GET /api/setor/carga/vista/celula: o que está atrás de uma célula de uma vista — horas por máquina e as OF
    (horas, peças, metros, kg, prazo, tipo). Na vista Setores a chave é o setor."""
    planning.check_area(sector)
    if por not in BY:
        raise planning.PlanningError("Vista inválida.")
    today = today or load._today()
    now = now or datetime.now(timezone.utc)
    weeks = load.week_list(today)
    slot = _slot_param(year, week, weeks)
    if por == "setor":
        sector = planning.check_area(key)
    context = load._context(sector, today)
    agg = _aggregate(sector, por, today, now, context)
    rows, _, weights = _population(sector, set(agg["machines"]), today, context)
    machines, orders, total = {}, {}, _empty()
    for f, kind, found in rows:
        if found != slot or KEYS[por](sector, f) != key:
            continue
        weight = load.fact_weight(f, weights)
        _add(total, f, kind, weight)
        rid = f["planning_resource_id"]
        _add(machines.setdefault(rid, {"id": rid, "name": agg["machines"].get(rid) or f.get("planning_machine") or rid, **_empty()}),
             f, kind, weight)
        o = orders.setdefault(f["of"], {"of": f["of"], "customer": f.get("customer"), **_empty(), "kinds": set(),
                                        "priority_day": None, "late_days": 0})
        _add(o, f, kind, weight)
        o["kinds"].add(kind)
        day = f.get("priority_day")
        if day and (o["priority_day"] is None or str(day) < str(o["priority_day"])):
            o["priority_day"] = day
        o["late_days"] = max(o["late_days"], f.get("late_days") or 0)
    rounded = lambda d: {k: round(v, 2) if isinstance(v, float) else v for k, v in d.items()}
    machine_rows = sorted((rounded(m) for m in machines.values()), key=lambda m: (-m["hours"], str(m["name"])))
    order_rows = sorted((rounded({**o, "kinds": sorted(o["kinds"])}) for o in orders.values()),
                        key=lambda o: (-o["late_days"], str(o["priority_day"] or "9999"), o["of"]))
    return needs.serial({"sector": sector, "por": por, "key": key, "label": SECTORS[key] if por == "setor" else key,
                         "slot": slot if isinstance(slot, str) else "semana",
                         "year": slot[0] if isinstance(slot, tuple) else None, "week": slot[1] if isinstance(slot, tuple) else None,
                         "machines": machine_rows, "orders": order_rows, **rounded(total), "stale": agg["stale"]})
