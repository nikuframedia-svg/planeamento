"""Vistas da previsão na Carga: «Capacidade e prazos» e «Calendário» (Etapa 3, pontos 11 e 12, 08/10/2026).

Tudo sai da previsão em cache (forecast.current; com `cenario`, scenarios.compute_for quando existir) e nunca se
mistura com o que foi feito:
- Previsão = o que cada máquina vai fazer, com a capacidade dos turnos (células máquina × dia × turno do motor).
- Realizado = MES (folhas OCR validadas), pela data de produção, como load.production. Só em dias passados e hoje.

Regras mostradas no ecrã:
- risco em 3 estados (atrasa, em risco, sem previsão) e, à parte, «já em atraso» (prazo antes de hoje); os
  contadores são os da previsão (`counts`);
- estado de cada célula: Fechado (capacidade 0), Sem carga, parcial (%), «100 % · completa» (normal, nunca erro);
  o risco é uma marca à parte (OF que acabam nessa célula e atrasam ou ficam em risco);
- capacidade do setor num dia sem contar a dobrar (capacity.counted): um posto com calendário (Fita pav.1)
  substitui as máquinas que o compõem (Doall e Thomas);
- mapa por dia: 15 dias úteis a partir de hoje; por semana: 13 semanas a partir da atual.
"""
from __future__ import annotations

import threading
import time as clock
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .. import planning, planning_needs as needs
from . import forecast

LISBON = ZoneInfo("Europe/Lisbon")
DAY_COLUMNS = 15
WEEK_COLUMNS = 13
MAX_CALENDAR_DAYS = 7 * 14
RISKS_SHOWN = 100
# Motivos de «Previsão com dados em falta» (os outros não são dados em falta: 2.ª operação, estacionada).
MISSING = ("sem_horas", "sem_calendario", "sem_maquina", "saldo_desconhecido", "outro_setor")
TEXT = "Previsão: o que cada máquina vai fazer, com a capacidade dos turnos."

_lock = threading.Lock()
_index_memo: dict[tuple, tuple] = {}
_names_memo: dict[str, tuple] = {}
_realized_memo: dict[tuple, tuple] = {}
NAMES_SECONDS = 300
REALIZED_SECONDS = 60


# ---------------------------------------------------------------- previsão (com ou sem cenário)

def _scenario_compute():
    """scenarios.compute_for (parte dos cenários), se já existir; senão None."""
    try:
        from .scenarios import compute_for
    except ImportError:
        return None
    return compute_for


def forecast_for(sector: str, cenario=None) -> tuple[dict, dict | None]:
    """(previsão, cenário). Sem `cenario`: o plano em uso. Com `cenario` e sem a parte dos cenários instalada: o
    plano em uso, com o cenário marcado «available: False» (o ecrã diz que ainda não há cenários)."""
    planning.check_area(sector)
    cenario = str(cenario).strip() if cenario not in (None, "") else None
    if not cenario:
        return forecast.current(sector, allow_stale=True), None
    compute_for = _scenario_compute()
    if compute_for is None:
        return forecast.current(sector, allow_stale=True), {"id": cenario, "name": None, "available": False}
    f = compute_for(sector, cenario_id=cenario)
    found = f.get("scenario")
    name = found.get("name") if isinstance(found, dict) else found if isinstance(found, str) else None
    return f, {"id": cenario, "name": name, "available": True}


# ---------------------------------------------------------------- funções puras

def end_day(end) -> str | None:
    """Dia de Lisboa em que uma conclusão acaba (uma conclusão à meia-noite ainda é o dia anterior)."""
    if end is None:
        return None
    return (end - timedelta(seconds=1)).astimezone(LISBON).date().isoformat()


def _is_workday(day: date, workdays: set, holidays: set) -> bool:
    return day.isoweekday() in workdays and day.isoformat() not in holidays


def posts_of(f: dict) -> dict:
    """Postos partilhados da previsão: {posto: [máquinas que o compõem]} (slots com mais de uma máquina)."""
    out = {}
    for s in f.get("slots") or []:
        members = sorted((rid for rid, m in (f.get("machines") or {}).items() if m.get("slot") == s["id"] and rid != s["id"]), key=str)
        if members and s.get("pool"):
            out[s["id"]] = members
    return out


def sector_capacity(caps: dict, posts: dict) -> float:
    """Capacidade do setor (segundos ou horas) sem contar a dobrar: capacity.counted() com os postos da previsão.
    `caps` = {máquina: capacidade ou None (sem calendário)}."""
    from .capacity import counted
    members = {p: list(ms) for p, ms in posts.items()}
    resources = {rid: {"id": rid} for rid in set(caps) | set(members) | {m for ms in members.values() for m in ms}}
    shape = {"roles": {rid: "maquina" for rid in resources if rid not in members}, "members": members}
    return sum(caps[rid] for rid in counted(resources, caps, shape=shape) if caps.get(rid) is not None)


def _due_fields(f: dict) -> dict:
    """{linha: campo do prazo} pelas operações da previsão (Data Corte, Picking…)."""
    out = {}
    meta = f.get("meta") or {}
    for key, r in (f.get("operations") or {}).items():
        lk = (meta.get(key) or {}).get("line_key") or key
        if r.get("due_field") and lk not in out:
            out[lk] = r["due_field"]
    return out


def field_label(field) -> str | None:
    from .priority import FIELDS
    return FIELDS.get(field, field) if field else None


def build_index(f: dict) -> dict:
    """Agregados por máquina e dia da previsão (calculados uma vez por previsão)."""
    meta = f.get("meta") or {}
    machines = f.get("machines") or {}
    cap = defaultdict(float)     # (máquina, dia) → s
    load = defaultdict(float)
    shifts = defaultdict(list)   # (máquina, dia) → [{shift, capacity_h, forecast_h}]
    for rid, cells in (f.get("cells") or {}).items():
        for c in cells:
            key = (rid, str(c["date"])[:10])
            cap[key] += (c.get("capacity") or 0) * 3600
            load[key] += (c.get("load") or 0) * 3600
            shifts[key].append({"shift": c.get("shift"), "capacity_h": c.get("capacity"), "forecast_h": c.get("load")})
    work = defaultdict(lambda: defaultdict(lambda: {"seconds": 0.0, "keys": []}))  # (máquina, dia) → (of, âmbito)
    day_ofs = defaultdict(set)
    for key, r in (f.get("operations") or {}).items():
        m = meta.get(key) or {}
        for a, b, day, _shift in r.get("segments") or ():
            d = str(day)[:10] if day else a.astimezone(LISBON).date().isoformat()
            slot = work[(r["resource_id"], d)][(r.get("of"), 0 if m.get("plan") else 1)]
            slot["seconds"] += (b - a).total_seconds()
            if key not in slot["keys"]:
                slot["keys"].append(key)
            day_ofs[d].add(r.get("of"))
    # Marcas de risco: MTG2 pela OF inteira (Picking); MTG3 por linha (Data Corte).
    items = []
    if f.get("sector") == "perfis":
        for o in (f.get("orders") or {}).values():
            items.append((o.get("of"), o.get("resource_id"), o.get("end"), o.get("state"), o.get("already_late")))
    else:
        for line in (f.get("lines") or {}).values():
            if line.get("parked") or not (line.get("ops") or line.get("missing")):
                continue
            items.append((line.get("of"), line.get("resource_id"), line.get("end"), line.get("state"), line.get("already_late")))
    marks = defaultdict(lambda: {"atrasa": set(), "em_risco": set(), "ja_em_atraso": set()})
    for of, rid, end, state, late in items:
        d = end_day(end)
        if d is None or rid is None:
            continue
        if late:
            marks[(rid, d)]["ja_em_atraso"].add(of)
        elif state in (forecast.LATE, forecast.AT_RISK):
            marks[(rid, d)][state].add(of)
    ends = defaultdict(set)
    states = defaultdict(lambda: {"atrasa": set(), "em_risco": set(), "ja_em_atraso": set()})
    for o in (f.get("orders") or {}).values():
        d = end_day(o.get("end")) if not o.get("beyond") else None
        if d is None:
            continue
        ends[d].add(o["of"])
        if o.get("already_late"):
            states[d]["ja_em_atraso"].add(o["of"])
        elif o.get("state") in (forecast.LATE, forecast.AT_RISK):
            states[d][o["state"]].add(o["of"])
    fields = _due_fields(f)
    dues = defaultdict(set)
    for lk, line in (f.get("lines") or {}).items():
        if line.get("parked") or not line.get("due_day"):
            continue
        dues[str(line["due_day"])[:10]].add((line.get("of"), fields.get(lk)))
    return {"cap": cap, "load": load, "shifts": shifts, "work": work, "day_ofs": day_ofs, "marks": marks,
            "ends": ends, "states": states, "dues": dues, "posts": posts_of(f), "fields": fields,
            "machines": sorted(machines.values(), key=lambda m: (str(m.get("name") or ""), str(m.get("id"))))}


def _index(f: dict, slot) -> dict:
    """O índice da previsão `f`, guardado enquanto a previsão em cache for a mesma (um por setor e cenário)."""
    with _lock:
        found = _index_memo.get(slot)
        if found and found[0] is f:
            return found[1]
    index = build_index(f)
    with _lock:
        _index_memo[slot] = (f, index)
    return index


def cell_of(cap_s: float, load_s: float, has_calendar: bool = True) -> dict:
    """Uma célula: capacidade, previsão, % e estado (Fechado / Sem carga / parcial / Completa; sem calendário)."""
    if not has_calendar and cap_s <= 0 and load_s <= 0:
        return {"capacity_h": None, "forecast_h": 0.0, "pct": None, "state": "sem_calendario"}
    state = forecast.cell_state(cap_s, load_s)
    pct = None
    if cap_s > 0:
        pct = 100 if state == "completa" else min(99, int(100 * load_s / cap_s))
    return {"capacity_h": round(cap_s / 3600, 1), "forecast_h": round(load_s / 3600, 1), "pct": pct, "state": state}


def work_days(start: date, count: int, workdays, holidays, has_capacity) -> list[date]:
    """`count` dias úteis a partir de `start` (inclusive): dias de trabalho do setor ou com turnos no calendário."""
    workdays = {int(d) for d in (workdays or (1, 2, 3, 4, 5))}
    holidays = {str(h)[:10] for h in holidays or ()}
    out, day = [], start
    for _ in range(count * 4 + 14):
        if _is_workday(day, workdays, holidays) or has_capacity(day.isoformat()):
            out.append(day)
            if len(out) == count:
                break
        day += timedelta(days=1)
    return out


def counters(f: dict) -> dict:
    counts = f.get("counts") or {}
    return {"atrasam": counts.get(forecast.LATE, 0), "em_risco": counts.get(forecast.AT_RISK, 0),
            "ja_em_atraso": counts.get("ja_em_atraso", 0), "sem_previsao": counts.get(forecast.NO_FORECAST, 0)}


def limiting_of(f: dict) -> list[dict]:
    out = []
    machines = f.get("machines") or {}
    for s in f.get("limiting") or []:
        ends = [m.get("queue_end") for m in machines.values() if m.get("slot") == s["id"] and m.get("queue_end")]
        out.append({"id": s["id"], "machine": s.get("name"), "machines": s.get("machines"), "recovery": s.get("recovery"),
                    "recovers": s.get("recovers"), "peak_gap_weeks": s.get("peak_weeks"), "peak_hours": s.get("peak_hours"),
                    "late_hours": s.get("late_hours"),
                    "suggested_share": round(s["suggested_hours"] / s["hours"], 2) if s.get("hours") else None,
                    "queue_end": max(ends) if ends else None})
    return out


def risks_of(f: dict, index: dict) -> list[dict]:
    """Riscos principais: só as OF que atrasam ou ficam em risco (as já em atraso contam à parte)."""
    names = f.get("names") or {}
    lines_by_of = defaultdict(list)
    for lk, line in (f.get("lines") or {}).items():
        if not line.get("parked"):
            lines_by_of[line.get("of")].append(line)
    out = []
    for o in (f.get("orders") or {}).values():
        if o.get("already_late") or o.get("state") not in (forecast.LATE, forecast.AT_RISK):
            continue
        group = lines_by_of.get(o["of"]) or []
        if f.get("sector") == "perfis":
            machine = names.get(o.get("resource_id")) or o.get("resource_id")
            due_line = next((x for x in group if x.get("due") is not None and x.get("due") == o.get("due")), None)
        else:
            group = [x for x in group if x.get("ops") or x.get("missing")]
            due_line = min(group, key=lambda x: (forecast._rank(x.get("state")), x["margin_days"] if x.get("margin_days") is not None
                                                 else 10 ** 6, str(x.get("line_key")))) if group else None
            machine = (due_line or {}).get("machine")
        field = index["fields"].get(due_line["line_key"]) if due_line else None
        if o.get("beyond"):
            reason = forecast.REASON_TEXT["alem_do_horizonte"]
        elif o.get("reason"):
            reason = forecast.REASON_TEXT.get(o["reason"], o["reason"])
        else:
            reason = f"Fila na {machine}" if machine else "Fila na máquina"
        out.append({"of": o["of"], "customer": o.get("customer"), "machine": machine, "machines": o.get("machines"),
                    "due": o.get("due"), "due_day": o.get("due_day"), "due_field": field, "due_label": field_label(field),
                    "conclusion": None if o.get("beyond") else o.get("end"), "beyond": bool(o.get("beyond")),
                    "margin_days": o.get("margin_days"), "state": o["state"], "reason": reason,
                    "approximate": o.get("approximate") or []})
    out.sort(key=lambda r: (0 if r["state"] == forecast.LATE else 1, str(r["due_day"] or "9999"),
                            r["margin_days"] if r["margin_days"] is not None else 10 ** 6, str(r["of"])))
    return out


def unreliable_of(f: dict) -> dict:
    rel = f.get("reliability") or {}
    counts = rel.get("unschedulable") or {}
    reasons = [{"reason": r, "label": forecast.REASON_TEXT.get(r, r), "count": counts[r]} for r in MISSING if counts.get(r)]
    return {"reasons": reasons, "approximate_lines": rel.get("approximate_lines", 0),
            "approximate": [{"label": k, "count": v} for k, v in (rel.get("reasons") or {}).items()],
            "sources": {"excel_imported_at": rel.get("excel_imported_at"), "v2_at": rel.get("v2_at")}}


def capacity_view(f: dict, index: dict, grao: str, today: date, by_deadline: dict | None = None) -> dict:
    """Capacidade e prazos (puro): contadores, recurso limitante, mapa máquina × dia|semana, riscos e dados em falta."""
    workdays, holidays = f.get("workdays") or [1, 2, 3, 4, 5], f.get("holidays") or []
    cap, load, marks = index["cap"], index["load"], index["marks"]
    if grao == "semana":
        monday = today - timedelta(days=today.weekday())
        periods = []
        for i in range(WEEK_COLUMNS):
            start = monday + timedelta(weeks=i)
            y, w, _ = start.isocalendar()
            periods.append({"key": f"{y}-W{w:02d}", "year": y, "week": w, "start": start,
                            "days": [(start + timedelta(days=d)).isoformat() for d in range(7)]})
    else:
        has = lambda d: any(cap.get((m["id"], d), 0) > 0 for m in index["machines"])
        periods = [{"key": d.isoformat(), "start": d, "days": [d.isoformat()]}
                   for d in work_days(today, DAY_COLUMNS, workdays, holidays, has)]
    machines = []
    for m in index["machines"]:
        rid = m["id"]
        cells = []
        for p in periods:
            c_s = sum(cap.get((rid, d), 0.0) for d in p["days"])
            l_s = sum(load.get((rid, d), 0.0) for d in p["days"])
            cell = cell_of(c_s, l_s, m.get("has_calendar", True))
            risk = {k: len(set().union(*[marks[(rid, d)][k] for d in p["days"] if (rid, d) in marks]))
                    for k in ("atrasa", "em_risco", "ja_em_atraso")}
            cell.update(key=p["key"], risk_marks={k: v for k, v in risk.items() if v})
            if by_deadline is not None and (rid, p.get("year"), p.get("week")) in by_deadline:
                cell["deadline_h"] = by_deadline[(rid, p["year"], p["week"])]
            cells.append(cell)
        machines.append({"id": rid, "name": m.get("name"), "has_calendar": m.get("has_calendar", True),
                         "queue_end": m.get("queue_end"), "late_hours": m.get("late_hours"), "beyond": m.get("beyond", 0),
                         "slot": m.get("slot"), "periods": cells})
    risks = risks_of(f, index)
    return {"grao": "semana" if grao == "semana" else "dia", "text": TEXT, "folga": f.get("folga"),
            "origin": f.get("origin"), "today": today, "horizon_end": f.get("horizon_end"),
            "counters": counters(f), "limiting": limiting_of(f),
            "periods": [{"key": p["key"], "start": p["start"], **({"year": p["year"], "week": p["week"]} if "week" in p else {})}
                        for p in periods],
            "machines": machines, "risks": risks[:RISKS_SHOWN], "risks_total": len(risks),
            "unreliable": unreliable_of(f), "posts": {p: ms for p, ms in index["posts"].items()}}


def _day_capacity(index: dict, day: str) -> tuple[float, float]:
    caps = {}
    total_load = 0.0
    for m in index["machines"]:
        rid = m["id"]
        if m.get("has_calendar", True):
            caps[rid] = index["cap"].get((rid, day), 0.0)
        else:
            caps[rid] = None
        total_load += index["load"].get((rid, day), 0.0)
    return sector_capacity(caps, index["posts"]), total_load


def calendar_view(f: dict, index: dict, de: date, ate: date, today: date, deliveries: dict, realized: dict | None) -> dict:
    """Calendário (puro): um bloco por dia. Dias passados: só o realizado; hoje e depois: a previsão (e, hoje,
    também o realizado, à parte)."""
    days = []
    day = de
    while day <= ate:
        iso = day.isoformat()
        past = day < today
        entry = {"date": iso, "past": past}
        if past:
            entry.update(closed=None, capacity_h=None, forecast_h=None, pct=None, state=None, ofs=0, ends=[], at_risk=0, late=0,
                         already_late=0)
        else:
            c_s, l_s = _day_capacity(index, iso)
            cell = cell_of(c_s, l_s)
            states = index["states"].get(iso) or {}
            entry.update(closed=cell["state"] == "fechado", capacity_h=cell["capacity_h"], forecast_h=cell["forecast_h"],
                         pct=cell["pct"], state=cell["state"], ofs=len(index["day_ofs"].get(iso) or ()),
                         ends=sorted(index["ends"].get(iso) or (), key=str), at_risk=len(states.get("em_risco") or ()),
                         late=len(states.get("atrasa") or ()), already_late=len(states.get("ja_em_atraso") or ()))
        entry["due"] = [{"of": of, "field": field, "label": field_label(field)}
                        for of, field in sorted(index["dues"].get(iso) or (), key=lambda x: (str(x[0]), str(x[1])))]
        entry["deliveries"] = sorted(deliveries.get(iso) or (), key=str)
        entry["realized"] = (realized.get(iso) or {"pieces": 0, "metres": None, "metres_unknown": 0, "sheets": 0, "records": 0}) \
            if realized is not None and day <= today else None
        days.append(entry)
        day += timedelta(days=1)
    return {"text": TEXT, "from": de, "to": ate, "today": today, "origin": f.get("origin"), "days": days,
            "realized_available": realized is not None}


def day_view(f: dict, index: dict, day: date, today: date, realized: list | None, template=None) -> dict:
    """Detalhe de um dia (puro): por máquina os turnos, a previsão e as OF; pessoas (se definidas); e, à parte, o
    realizado por máquina (MES, pela data de produção)."""
    iso = day.isoformat()
    meta = f.get("meta") or {}
    ops = f.get("operations") or {}
    template = template or f.get("template") or []
    machines = []
    if day >= today:
        for m in index["machines"]:
            rid = m["id"]
            c_s, l_s = index["cap"].get((rid, iso), 0.0), index["load"].get((rid, iso), 0.0)
            work = index["work"].get((rid, iso)) or {}
            if c_s <= 0 and l_s <= 0 and not work:
                continue
            rows = []
            for (of, scope), w in work.items():
                keys = w["keys"]
                pieces = [meta[k].get("pieces") for k in keys if k in meta]
                metres = [(meta[k].get("pieces") or 0) * meta[k]["length_mm"] / 1000 for k in keys
                          if k in meta and meta[k].get("pieces") is not None and meta[k].get("length_mm")]
                ends = [ops[k]["end"] for k in keys if ops.get(k, {}).get("end") is not None]
                last = max(ends) if ends and len(ends) == len(keys) else None
                first = meta.get(keys[0]) or {}
                due_day = min((str(meta[k]["due_day"])[:10] for k in keys if meta.get(k, {}).get("due_day")), default=None)
                field = next((index["fields"].get(meta[k].get("line_key")) for k in keys
                              if k in meta and index["fields"].get(meta[k].get("line_key"))), None)
                rows.append({"of": of, "customer": first.get("customer"), "hours": round(w["seconds"] / 3600, 1),
                             "pieces": sum(p for p in pieces if p is not None) if any(p is not None for p in pieces) else None,
                             "metres": round(sum(metres), 1) if metres else None, "kind": "Planeado" if scope == 0 else "Resto",
                             "due_day": due_day, "due_field": field, "due_label": field_label(field),
                             "ends": last if last is not None and end_day(last) == iso else None, "conclusion": last,
                             "operations": len(keys)})
            rows.sort(key=lambda r: (-r["hours"], str(r["of"]), r["kind"]))
            shifts = []
            for s in sorted(index["shifts"].get((rid, iso)) or [], key=lambda x: x["shift"] or 9):
                n = s["shift"]
                hours = template[n - 1] if n and 0 < n <= len(template) else None
                shifts.append({**s, "start": hours[0] if hours else None, "end": hours[1] if hours else None})
            cell = cell_of(c_s, l_s, m.get("has_calendar", True))
            machines.append({"id": rid, "name": m.get("name"), "shifts": [s for s in shifts if (s["capacity_h"] or 0) > 0 or (s["forecast_h"] or 0) > 0],
                             **cell, "ofs": rows})
    people = [p for p in f.get("people") or [] if str(p.get("date"))[:10] == iso]
    defined = any(p.get("available") is not None for p in people)
    total = None
    if day >= today:
        c_s, l_s = _day_capacity(index, iso)
        total = cell_of(c_s, l_s)
    return {"day": iso, "past": day < today, "today": today, "text": TEXT, "total": total, "machines": machines,
            "people": [{k: p.get(k) for k in ("shift", "machines", "need", "available", "deficit")} for p in people] if defined else None,
            "realized": realized, "realized_available": realized is not None}


# ---------------------------------------------------------------- realizado (MES, pela data de produção)

def _number(value):
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _machine_names(sector: str) -> dict:
    """{nome da máquina nas folhas: (id, nome do catálogo)} pelos aliases (como load.production)."""
    with _lock:
        found = _names_memo.get(sector)
        if found and clock.monotonic() - found[0] < NAMES_SECONDS:
            return found[1]
    from .occurrences import resources_context
    with planning.connect(readonly=True) as c:
        codes, by_id, aliases, _, _ = resources_context(c)
    out = {}
    for rid, r in by_id.items():
        if r.get("name"):
            out[r["name"]] = (rid, r["name"])
    for (area, name), code in aliases.items():
        rid = (codes.get(code) or {}).get("id")
        if rid and name and (area == sector or name not in out):
            out[name] = (rid, (by_id.get(rid) or {}).get("name") or name)
    with _lock:
        _names_memo[sector] = (clock.monotonic(), out)
    return out


def realized_rows(sector: str, de: date, ate: date) -> tuple[list, dict]:
    """Linhas de produção validadas (máquina, dia, quantidade, comprimento, folha) e as horas das folhas
    {(dia, máquina): horas}. Sem consulta pronta: PlanningError (quem chama mostra «sem dados»)."""
    slot = (sector, de, ate)
    with _lock:
        found = _realized_memo.get(slot)
        if found and clock.monotonic() - found[0] < REALIZED_SECONDS:
            return found[1]
    from ..raw import query
    with planning.connect(readonly=True) as c:
        gen = query.generation(c, sector, dataset="production")
        base, args = query.source(gen)
        base += " AND (c.values_json->>'production_date')::date BETWEEN %s AND %s"
        rows = c.execute("SELECT c.values_json->>'machine' AS machine, (c.values_json->>'production_date')::date AS day, "
                         "c.values_json->>'quantity' AS quantity, c.values_json->>'length_mm' AS length_mm, "
                         "coalesce(c.detail->>'sheet_uid', c.values_json->>'sheet') AS sheet" + base, args + [de, ate]).fetchall()
        hours = {}
        try:
            hgen = query.generation(c, sector, dataset="production_hours")
            hbase, hargs = query.source(hgen)
            hbase += " AND (c.values_json->>'production_date')::date BETWEEN %s AND %s"
            for r in c.execute("SELECT m.row_key AS sheet, c.values_json->>'machine' AS machine, "
                               "(c.values_json->>'production_date')::date AS day, c.values_json->>'hours_worked' AS hours"
                               + hbase, hargs + [de, ate]).fetchall():
                value = _number(r["hours"])
                if value is not None:
                    key = (r["day"].isoformat(), r["machine"])
                    hours[key] = hours.get(key, 0.0) + value
        except planning.PlanningError:
            hours = {}
    out = ([{"machine": r["machine"], "day": r["day"].isoformat(), "quantity": _number(r["quantity"]),
             "length_mm": _number(r["length_mm"]), "sheet": r["sheet"]} for r in rows], hours)
    with _lock:
        _realized_memo[slot] = (clock.monotonic(), out)
    return out


def _add_row(a: dict, r: dict) -> None:
    """Soma uma linha de produção: peças; metros só com comprimento (as outras contam em `metres_unknown`)."""
    if r.get("quantity") is not None:
        a["pieces"] += r["quantity"]
        if r.get("length_mm"):
            a["metres"] = (a["metres"] or 0.0) + r["quantity"] * r["length_mm"] / 1000
        else:
            a["metres_unknown"] += 1
    if r.get("sheet"):
        a["sheets"].add(r["sheet"])


def _new_acc(**extra) -> dict:
    return {"pieces": 0.0, "metres": None, "metres_unknown": 0, "sheets": set(), **extra}


def _metres(a: dict):
    """Metros conhecidos; desconhecido nunca é 0 (as folhas do MES quase nunca trazem o comprimento)."""
    return round(a["metres"], 1) if a["metres"] is not None else None


def realized_by_day(rows: list) -> dict:
    """{dia: {pieces, metres, metres_unknown, sheets, records}} (puro). Metros só das linhas com comprimento."""
    acc = defaultdict(lambda: _new_acc(records=0))
    for r in rows:
        a = acc[r["day"]]
        a["records"] += 1
        _add_row(a, r)
    return {d: {"pieces": round(a["pieces"]), "metres": _metres(a), "metres_unknown": a["metres_unknown"],
                "sheets": len(a["sheets"]), "records": a["records"]} for d, a in acc.items()}


def realized_by_machine(rows: list, hours: dict, names: dict, day: str) -> list[dict]:
    """Realizado de um dia por máquina (puro): peças, metros, horas das folhas e folhas."""
    acc = {}
    for r in rows:
        if r["day"] != day:
            continue
        rid, name = names.get(r.get("machine")) or (None, r.get("machine") or "Sem máquina")
        a = acc.setdefault(rid or name, _new_acc(id=rid, machine=name, hours=None))
        _add_row(a, r)
    for (d, machine), value in hours.items():
        if d != day:
            continue
        rid, name = names.get(machine) or (None, machine or "Sem máquina")
        a = acc.setdefault(rid or name, _new_acc(id=rid, machine=name, hours=None))
        a["hours"] = round((a["hours"] or 0) + value, 1)
    return sorted(({"id": a["id"], "machine": a["machine"], "pieces": round(a["pieces"]), "metres": _metres(a),
                    "metres_unknown": a["metres_unknown"], "hours": a["hours"], "sheets": len(a["sheets"])}
                   for a in acc.values()), key=lambda x: str(x["machine"]))


def _realized(sector: str, de: date, ate: date):
    try:
        return realized_rows(sector, de, ate)
    except planning.PlanningError:
        return None


# ---------------------------------------------------------------- leituras (rotas)

def _date(value, name: str) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise planning.PlanningError(f"Data inválida em «{name}».") from None


def _today(f: dict) -> date:
    today = f.get("today")
    return today if isinstance(today, date) else date.fromisoformat(str(today)[:10])


def _head(f: dict, scenario) -> dict:
    return {"sector": f.get("sector"), "computed_at": f.get("computed_at"), "stale": bool(f.get("stale")),
            "scenario": scenario, "capabilities": ["previsao", "realizado"]}


def _deadline_hours(sector: str) -> dict | None:
    """Horas pelo prazo de cada máquina e semana (as da grelha da Carga), para o cursor do mapa por semana."""
    try:
        from . import load
        data = load.overview(sector)
    except Exception:  # o cursor é um extra: sem a Carga, o mapa continua certo
        return None
    out = {}
    for m in data.get("machines") or []:
        for w in m.get("weeks") or []:
            out[(m["id"], w.get("year"), w.get("week"))] = round(w.get("load") or 0, 1)
    return out


def capacity_deadlines(sector: str, grao: str = "dia", cenario=None) -> dict:
    if grao not in ("dia", "semana"):
        raise planning.PlanningError("Escolhe «dia» ou «semana».")
    f, scenario = forecast_for(sector, cenario)
    index = _index(f, (sector, scenario["id"] if scenario else None))
    by_deadline = _deadline_hours(sector) if grao == "semana" and not scenario else None
    return needs.serial({**_head(f, scenario), **capacity_view(f, index, grao, _today(f), by_deadline)})


def _deliveries(sector: str) -> dict:
    """{dia: [OF]} pela Data de entrega (CPIS) das linhas da Carteira."""
    try:
        from . import portfolio
        lines = portfolio.current(sector, allow_stale=True)["lines"]
    except Exception:  # sem a Carteira, o calendário mostra o resto
        return {}
    out = defaultdict(set)
    for x in lines:
        d = x.get("delivery_date")
        if d:
            out[str(d)[:10]].add(x.get("of"))
    return out


def calendar(sector: str, de=None, ate=None, cenario=None) -> dict:
    f, scenario = forecast_for(sector, cenario)
    today = _today(f)
    start = _date(de, "de") or (today - timedelta(days=today.weekday() + 7))
    end = _date(ate, "ate") or (start + timedelta(days=6 * 7 - 1))
    if end < start:
        raise planning.PlanningError("A data final é antes da inicial.")
    if (end - start).days + 1 > MAX_CALENDAR_DAYS:
        raise planning.PlanningError(f"No máximo {MAX_CALENDAR_DAYS // 7} semanas de cada vez.")
    index = _index(f, (sector, scenario["id"] if scenario else None))
    realized = None
    if start <= today:
        found = _realized(sector, start, min(end, today))
        realized = realized_by_day(found[0]) if found is not None else None
    return needs.serial({**_head(f, scenario), **calendar_view(f, index, start, end, today, _deliveries(sector), realized)})


def calendar_day(sector: str, dia, cenario=None) -> dict:
    day = _date(dia, "dia")
    if day is None:
        raise planning.PlanningError("Indica o dia.")
    f, scenario = forecast_for(sector, cenario)
    today = _today(f)
    index = _index(f, (sector, scenario["id"] if scenario else None))
    realized = None
    if day <= today:
        found = _realized(sector, day, day)
        if found is not None:
            try:
                names = _machine_names(sector)
            except Exception:
                names = {}
            realized = realized_by_machine(found[0], found[1], names, day.isoformat())
    return needs.serial({**_head(f, scenario), **day_view(f, index, day, today, realized)})


def invalidate() -> None:
    with _lock:
        _index_memo.clear()
        _names_memo.clear()
        _realized_memo.clear()
