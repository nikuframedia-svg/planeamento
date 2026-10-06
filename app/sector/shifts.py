"""Turnos por máquina, semana e dia, guardados nos calendários (pedido do Luís, 06/10/2026).

O calendário semanal (raw_objects kind='calendar') continua a ser a capacidade que todo o planeamento usa.
Aqui só se traduz «quantos turnos» ↔ horários:
- `shift_plan` = turnos por dia da semana ("1"…"7"); `day_shifts` = exceções de um dia ({data: turnos});
- feriados = dia sem turnos; o 3.º turno atravessa a meia-noite e parte-se em dois dias;
- `manual: true` quando a semana foi mudada à mão (não é reescrita quando mudam os turnos padrão).
Gravação em lote numa só transação, com um único sinal de agregados no fim (evita recalcular tudo
a cada calendário).
"""
from __future__ import annotations

import math
import uuid
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone

from .. import planning, planning_needs as needs, planning_calendars

DEFAULT_TEMPLATE = [["06:00", "13:30"], ["14:00", "21:30"], ["22:00", "05:30"]]
DEFAULT_WORKDAYS = [1, 2, 3, 4, 5]
MAX_SHIFTS = 3


def easter(year: int) -> date:
    """Domingo de Páscoa (algoritmo gregoriano anónimo)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    return date(year, month, (h + l - 7 * m + 114) % 31 + 1)


def national_holidays(year: int) -> list[str]:
    """Feriados nacionais de Portugal (fixos + Sexta-feira Santa, Páscoa e Corpo de Deus)."""
    e = easter(year)
    fixed = [(1, 1), (4, 25), (5, 1), (6, 10), (8, 15), (10, 5), (11, 1), (12, 1), (12, 8), (12, 25)]
    days = [date(year, m, d) for m, d in fixed] + [e - timedelta(days=2), e, e + timedelta(days=60)]
    return sorted(d.isoformat() for d in days)


def _minutes(value: str) -> int:
    return 1440 if value == "24:00" else int(value[:2]) * 60 + int(value[3:])


def _clock(minutes: int) -> str:
    return "24:00" if minutes == 1440 else f"{minutes // 60:02}:{minutes % 60:02}"


def shift_hours(template) -> list[float]:
    out = []
    for start, end in template:
        a, b = _minutes(start), _minutes(end)
        out.append(((b - a) if b > a else (1440 - a + b)) / 60)
    return out


def _windows(n: int, previous: int, template) -> list[dict]:
    """Horários de um dia com n turnos, mais o fim do turno da noite do dia anterior."""
    result = []
    for start, end in template[:previous]:  # partes que passam da meia-noite do dia anterior
        if _minutes(end) <= _minutes(start):
            result.append({"start": "00:00", "end": end})
    for start, end in template[:n]:
        a, b = _minutes(start), _minutes(end)
        result.append({"start": start, "end": _clock(b if b > a else 1440)})
    return sorted(result, key=lambda w: w["start"])


def build(base_plan: dict, day_shifts: dict, holidays, template, year: int, week: int) -> tuple[dict, dict]:
    """(weekly_windows, date_overrides) for one ISO week."""
    base = {str(d): int(base_plan.get(str(d), 0)) for d in range(1, 8)}
    weekly = {str(d): _windows(base[str(d)], base[str(d - 1)] if d > 1 else 0, template) for d in range(1, 8)}
    first = date.fromisocalendar(year, week, 1)
    holidays = set(holidays or ())
    effective = {}
    for offset in range(7):
        day = first + timedelta(days=offset)
        iso = day.isoformat()
        n = int(day_shifts[iso]) if iso in day_shifts else (0 if iso in holidays else base[str(offset + 1)])
        effective[offset] = n
    overrides = {}
    for offset in range(7):
        day = first + timedelta(days=offset)
        windows = _windows(effective[offset], effective[offset - 1] if offset else 0, template)
        if windows != weekly[str(offset + 1)]:
            overrides[day.isoformat()] = windows
    return weekly, overrides


def decode(definition: dict, template=DEFAULT_TEMPLATE) -> tuple[dict, dict]:
    """(base_plan, day_shifts) of a calendar; old calendars are read from their windows."""
    if "shift_plan" in definition:
        return {str(k): int(v) for k, v in definition["shift_plan"].items()}, dict(definition.get("day_shifts") or {})
    starts = {s for s, _ in template}
    plan = {}
    for d in range(1, 8):
        windows = (definition.get("weekly_windows") or {}).get(str(d), [])
        plan[str(d)] = sum(1 for w in windows if w["start"] in starts and w["start"] != "00:00")
    return plan, {}


def definition_for(resource_id: str, year: int, week: int, base_plan: dict, day_shifts: dict, settings: dict,
                   *, manual: bool, previous: dict | None = None) -> dict:
    weekly, overrides = build(base_plan, day_shifts, settings["holidays"], settings["template"], year, week)
    d = {k: v for k, v in (previous or {}).items() if k not in ("weekly_windows", "date_overrides", "shift_plan", "day_shifts", "manual")}
    d.update(resource_id=resource_id, year=year, week=week, timezone="Europe/Lisbon", weekly_windows=weekly,
             date_overrides=overrides, shift_plan={str(k): int(v) for k, v in base_plan.items()},
             day_shifts={k: int(v) for k, v in day_shifts.items()}, manual=manual, confirmed=True)
    return planning_calendars.validate(d)


def week_hours(definition: dict, *, after: datetime | None = None) -> float:
    """Horas do calendário; com `after`, só as que faltam a partir desse instante."""
    intervals = planning_calendars.expand(definition) or []
    total = 0.0
    for r in intervals:
        start, end = datetime.fromisoformat(r["start"]), datetime.fromisoformat(r["end"])
        if after:
            start = max(start, after)
        if end > start:
            total += (end - start).total_seconds() / 3600
    return total


def shift_week_hours(settings: dict) -> float:
    """Horas de um turno a mais numa semana normal (um turno × dias de trabalho)."""
    return shift_hours(settings["template"])[0] * len(settings["workdays"])


def advise(load_hours: float, capacity_hours: float, shifts: int, settings: dict, *, workdays_in_week: int | None = None) -> dict:
    """Recomendação de turnos para uma máquina numa semana: {delta, text}."""
    per_shift = shift_hours(settings["template"])[0] * (workdays_in_week if workdays_in_week is not None else len(settings["workdays"]))
    if per_shift <= 0:
        return {"delta": 0, "text": "Sem dias de trabalho nesta semana."}
    missing = load_hours - capacity_hours
    if missing > 0.05:
        needed = math.ceil(missing / per_shift)
        delta = min(needed, MAX_SHIFTS - shifts)
        if delta <= 0:
            return {"delta": 0, "text": f"Faltam {missing:.0f} h e já está no máximo de {MAX_SHIFTS} turnos: mudar trabalho de máquina ou de semana."}
        left = missing - delta * per_shift
        text = f"+{delta} turno{'s' if delta > 1 else ''} · faltam {missing:.0f} h"
        if left > 0.05:
            text += f"; mesmo com {shifts + delta} turnos ficam a faltar {left:.0f} h"
        return {"delta": delta, "text": text, "still_missing": round(max(left, 0), 1)}
    spare = -missing
    if shifts > 1 and spare >= per_shift:
        delta = -min(int(spare // per_shift), shifts - 1)
        return {"delta": delta, "text": f"{delta} turno{'s' if delta < -1 else ''} · sobram {spare:.0f} h"}
    return {"delta": 0, "text": f"Certo · sobram {spare:.0f} h" if spare >= 0.05 else "Certo"}


def calendar_row(c, resource_id: str, year: int, week: int):
    return c.execute("SELECT * FROM planning_mtg.raw_objects WHERE kind='calendar' AND NOT archived AND definition->>'resource_id'=%s "
                     "AND (definition->>'year')::int=%s AND (definition->>'week')::int=%s", (resource_id, year, week)).fetchone()


def write(c, resource: dict, area: str, year: int, week: int, base_plan: dict, day_shifts: dict, settings: dict, *,
          manual: bool, request_id: uuid.UUID, actor_payload: dict) -> bool:
    """Grava (sem sinal de agregados) o calendário de uma semana; devolve True se mudou."""
    from ..raw import objects
    row = calendar_row(c, resource["id"], year, week)
    previous = (row or {}).get("definition") or {}
    d = definition_for(resource["id"], year, week, base_plan, day_shifts, settings, manual=manual, previous=previous)
    if row and all(previous.get(k) == d.get(k) for k in ("weekly_windows", "date_overrides", "shift_plan", "day_shifts", "manual")):
        return False
    objects.save({**actor_payload, "request_id": str(uuid.uuid5(request_id, f"{resource['id']}:{year}:{week}")),
                  "id": str(row["id"]) if row else None, "expected_revision": row["revision"] if row else 0, "area": area,
                  "name": f"{resource['name']} · {year}-W{week:02}", "definition": d}, "calendar", conn=c, signal=False)
    return True


def finish_batch(c, request_id) -> None:
    """Um só sinal e uma só marcação de agregados para o lote todo."""
    from ..raw import projection
    projection.signal(c, "calendar")
    projection.mark_aggregates_pending(c, str(request_id))


def apply(payload: dict, *, conn=None) -> dict:
    """Mudanças de turnos: [{maquina, ano, semana, turnos} | {maquina, dia: 'AAAA-MM-DD', turnos}]."""
    from . import settings as sector_settings
    sector = str(payload.get("setor") or "")
    changes = payload.get("mudancas")
    if not isinstance(changes, list) or not changes or len(changes) > 2000:
        raise planning.PlanningError("Indica as mudanças de turnos.")
    try:
        request_id = uuid.UUID(str(payload.get("request_id")))
    except ValueError:
        raise planning.PlanningError("Pedido sem identificador; recarrega a página.") from None
    with (planning.connect() if conn is None else nullcontext(conn)) as c:
        planning.check_area(sector)
        settings = sector_settings.read(c, sector)
        machines = {m["id"]: m for m in sector_settings.machine_rows(c, sector)}
        weeks = {}
        for item in changes:
            if not isinstance(item, dict) or item.get("maquina") not in machines:
                raise planning.PlanningError("Máquina inválida.")
            try:
                n = int(item.get("turnos"))
            except (TypeError, ValueError):
                raise planning.PlanningError("Número de turnos inválido.") from None
            if not 0 <= n <= MAX_SHIFTS:
                raise planning.PlanningError(f"Os turnos vão de 0 a {MAX_SHIFTS}.")
            if item.get("dia"):
                try:
                    day = date.fromisoformat(str(item["dia"]))
                except ValueError:
                    raise planning.PlanningError("Dia inválido.") from None
                year, week, _ = day.isocalendar()
            else:
                year, week, day = int(item.get("ano")), int(item.get("semana")), None
                date.fromisocalendar(year, week, 1)
            key = (item["maquina"], year, week)
            if key not in weeks:
                row = calendar_row(c, item["maquina"], year, week)
                base, days = decode((row or {}).get("definition") or {}, settings["template"]) if row else (
                    {str(d): (machines[item["maquina"]]["default_shifts"] if d in settings["workdays"] else 0) for d in range(1, 8)}, {})
                weeks[key] = [base, days]
            base, days = weeks[key]
            if day:
                days[day.isoformat()] = n
            else:
                for d in range(1, 8):
                    base[str(d)] = n if d in settings["workdays"] else 0
                for iso in [k for k in days if date.fromisoformat(k).isocalendar()[:2] == (year, week)]:
                    del days[iso]  # a semana inteira manda: as exceções de dias dessa semana saem
        changed = 0
        for (rid, year, week), (base, days) in weeks.items():
            changed += write(c, machines[rid], sector, year, week, base, days, settings, manual=True,
                             request_id=request_id, actor_payload={})
        if changed:
            finish_batch(c, request_id)
    return {"changed": changed, "weeks": len(weeks)}
