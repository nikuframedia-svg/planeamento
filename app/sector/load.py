"""Carga e turnos por máquina e semana (pedido do Luís, 06/10/2026).

Para cada máquina e semana ISO (a atual e as 12 seguintes):
- capacidade = horas do calendário dessa semana (na semana atual, só as que faltam a partir de agora);
- no plano = horas das linhas «Planeado» (Planear + máquina) na sua máquina, na semana do prazo;
- a vencer = trabalho aberto não planeado com prazo nessa semana: na máquina efetiva («com máquina») ou
  na sugerida (à parte); o que já passou do prazo conta na semana atual (atrasado);
- recomendação de turnos (shifts.advise) sobre no plano + a vencer; tirar turnos só nas 3 primeiras semanas
  (mais à frente a carga ainda está a chegar).
Prazo pela política do setor (MTG3 Data Corte; MTG2 Picking, depois Data Corte). As horas são as mesmas da
Carteira (occurrences + estimates); horas desconhecidas nunca contam como zero — são contadas à parte.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from .. import planning, planning_needs as needs
from . import shifts

WEEKS = 13
REDUCE_WEEKS = 3  # só se propõe tirar turnos na semana atual e nas duas seguintes
PLAN, DUE, SUGGESTED = "plan", "due", "suggested"


def _week_of(day) -> tuple[int, int] | None:
    if not day:
        return None
    d = day if isinstance(day, date) else date.fromisoformat(str(day)[:10])
    y, w, _ = d.isocalendar()
    return y, w


def week_list(today: date | None = None, count: int = WEEKS) -> list[tuple[int, int]]:
    today = today or date.today()
    monday = today - timedelta(days=today.weekday())
    return [(monday + timedelta(weeks=i)).isocalendar()[:2] for i in range(count)]


def classify(fact: dict, planned_keys: set, current: tuple[int, int], horizon: set) -> tuple[str, tuple[int, int] | str, bool] | None:
    """(kind, week | 'sem_data' | 'depois', late) for one occurrence; None when it has no machine at all."""
    rid = fact.get("planning_resource_id")
    if not rid:
        return None
    planned = fact.get("line_key") in planned_keys and fact.get("machine_basis") == "atribuída"
    kind = PLAN if planned else DUE if fact.get("machine_basis") == "atribuída" else SUGGESTED
    week = _week_of(fact.get("priority_day"))
    if week is None:
        return kind, "sem_data", False
    if week < current:
        return kind, current, True
    return (kind, week, False) if week in horizon else (kind, "depois", False)


def _empty_cell():
    return {PLAN: 0.0, DUE: 0.0, SUGGESTED: 0.0, "late": 0.0, "unknown": 0, "operations": 0}


def _context(sector: str, today: date | None = None):
    from . import occurrences, portfolio, selection, settings as sector_settings
    data = portfolio.current(sector)
    decisions = selection.current(sector)
    planned = {x["key"] for x in data["lines"] if portfolio.status_of(x, decisions)["planeado"]}
    occ = occurrences.load(sector, allow_stale=True)
    return data, planned, occ


def overview(sector: str, *, today: date | None = None, now: datetime | None = None) -> dict:
    from . import settings as sector_settings
    planning.check_area(sector)
    today = today or date.today()
    now = now or datetime.now(timezone.utc)
    weeks = week_list(today)
    horizon = set(weeks)
    current = weeks[0]
    data, planned, occ = _context(sector, today)
    with planning.connect(readonly=True) as c:
        settings = sector_settings.read(c, sector)
        machines = sector_settings.machine_rows(c, sector)
        ids = [m["id"] for m in machines]
        calendars = c.execute("SELECT definition FROM planning_mtg.raw_objects WHERE kind='calendar' AND NOT archived "
                              "AND definition->>'resource_id' = ANY(%s)", (ids,)).fetchall()
    cal = {(str(r["definition"]["resource_id"]), int(r["definition"]["year"]), int(r["definition"]["week"])): r["definition"] for r in calendars}
    cells = defaultdict(_empty_cell)
    no_date = defaultdict(_empty_cell)
    for f in occ["facts"]:
        found = classify(f, planned, current, horizon)
        if not found:
            continue
        kind, week, late = found
        if week == "depois":
            continue
        target = no_date[f["planning_resource_id"]] if week == "sem_data" else cells[(f["planning_resource_id"], *week)]
        target["operations"] += 1
        if f.get("load_hours") is None:
            target["unknown"] += 1
            continue
        target[kind] += f["load_hours"]
        if late:
            target["late"] += f["load_hours"]
    rows = []
    for m in machines:
        has_load = any(cells.get((m["id"], y, w)) for y, w in weeks)
        has_calendar = any((m["id"], y, w) in cal for y, w in weeks)
        if not (has_load or has_calendar):
            continue
        out = []
        for index, (y, w) in enumerate(weeks):
            d = cal.get((m["id"], y, w))
            cell = cells.get((m["id"], y, w)) or _empty_cell()
            capacity = shifts.week_hours(d, after=now if (y, w) == current else None) if d else 0.0
            base, days = shifts.decode(d, settings["template"]) if d else ({}, {})
            n = max([base.get(str(x), 0) for x in settings["workdays"]] or [0])
            monday = date.fromisocalendar(y, w, 1)
            workdays = [monday + timedelta(days=x - 1) for x in settings["workdays"]]
            open_days = [x for x in workdays if x.isoformat() not in set(settings["holidays"]) and (x >= today if (y, w) == current else True)]
            load = cell[PLAN] + cell[DUE] + cell[SUGGESTED]
            advice = shifts.advise(load, capacity, n, settings, workdays_in_week=len(open_days)) if d else {"delta": 0, "text": "Sem calendário"}
            if advice["delta"] < 0 and index >= REDUCE_WEEKS:
                # Mais à frente a carga ainda está a chegar: mostrar a folga, sem propor cortar turnos.
                advice = {"delta": 0, "text": f"Sobram {capacity - load:.0f} h (carga ainda por chegar)"}
            balance = capacity - load
            status = "falta" if balance < -0.05 else "apertado" if capacity and balance < 0.15 * capacity else "folga"
            out.append({"year": y, "week": w, "monday": monday, "shifts": n, "manual": bool((d or {}).get("manual")),
                        "day_changes": len(days), "capacity": round(capacity, 1), "plan": round(cell[PLAN], 1),
                        "due": round(cell[DUE], 1), "suggested": round(cell[SUGGESTED], 1), "late": round(cell["late"], 1),
                        "unknown": cell["unknown"], "operations": cell["operations"], "load": round(load, 1),
                        "balance": round(balance, 1), "status": status if d else "sem_calendario", "advice": advice,
                        "days": [{"date": monday + timedelta(days=i), "shifts": _day_shifts(base, days, settings, monday + timedelta(days=i))}
                                 for i in range(7)] if d else []})
        nd = no_date.get(m["id"]) or _empty_cell()
        rows.append({"id": m["id"], "name": m["name"], "code": m["code"], "process": m["process"], "default_shifts": m["default_shifts"],
                     "weeks": out, "no_date": {"hours": round(nd[PLAN] + nd[DUE] + nd[SUGGESTED], 1), "unknown": nd["unknown"],
                                               "operations": nd["operations"]}})
    return needs.serial({"sector": sector, "today": today, "weeks": [{"year": y, "week": w, "monday": date.fromisocalendar(y, w, 1)} for y, w in weeks],
                         "machines": rows, "settings": {k: settings[k] for k in ("template", "workdays", "holidays")},
                         "shift_hours": shifts.shift_hours(settings["template"]), "stale": bool(occ.get("stale")),
                         "rules": __doc__.split("\n\n", 1)[1].strip()})


def _day_shifts(base: dict, days: dict, settings: dict, day: date) -> int:
    iso = day.isoformat()
    if iso in days:
        return int(days[iso])
    if iso in set(settings["holidays"]):
        return 0
    return int(base.get(str(day.isoweekday()), 0))


def cell(sector: str, machine: str, year: int, week: int, *, today: date | None = None) -> dict:
    """O que está atrás de uma célula: uma linha por OF (horas, peças, metros, prazo, planeado ou não)."""
    planning.check_area(sector)
    today = today or date.today()
    weeks = week_list(today)
    horizon, current = set(weeks), weeks[0]
    data, planned, occ = _context(sector, today)
    lines = {x["key"]: x for x in data["lines"]}
    target = (int(year), int(week))
    groups = {}
    for f in occ["facts"]:
        if f.get("planning_resource_id") != machine:
            continue
        found = classify(f, planned, current, horizon)
        if not found or found[1] != target:
            continue
        kind, _, late = found
        g = groups.setdefault(f["of"], {"of": f["of"], "customer": f.get("customer"), "work": f.get("work"), "hours": 0.0, "unknown": 0,
                                        "pieces": 0.0, "metres": 0.0, "operations": 0, "references": set(), "kinds": set(),
                                        "priority_day": None, "late_days": 0})
        g["operations"] += 1
        g["references"].add(f.get("reference"))
        g["kinds"].add(kind)
        if f.get("load_hours") is None:
            g["unknown"] += 1
        else:
            g["hours"] += f["load_hours"]
        line = lines.get(f.get("line_key"))
        if f.get("phase") == "principal" and line:
            g["pieces"] += line["pieces"] or 0
            g["metres"] += line["metres"] or 0
        day = f.get("priority_day")
        if day and (g["priority_day"] is None or str(day) < str(g["priority_day"])):
            g["priority_day"] = day
        g["late_days"] = max(g["late_days"], f.get("late_days") or 0)
    rows = sorted(groups.values(), key=lambda g: (-g["late_days"], str(g["priority_day"] or "9999"), g["of"]))
    for g in rows:
        g["references"] = len(g["references"])
        g["kinds"] = sorted(g["kinds"])
        g["hours"] = round(g["hours"], 2)
        g["metres"] = round(g["metres"], 1)
        g["pieces"] = round(g["pieces"])
    return needs.serial({"sector": sector, "machine": machine, "year": int(year), "week": int(week), "orders": rows,
                         "hours": round(sum(g["hours"] for g in rows), 2), "unknown": sum(g["unknown"] for g in rows)})
