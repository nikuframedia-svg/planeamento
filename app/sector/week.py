"""Horas por dia (hora de Lisboa) para o Gantt semanal (06/10/2026).

Os segmentos da proposta estão em minutos desde `started_at` (tempo real, em UTC); os calendários
estão em intervalos UTC. Aqui parte-se tudo à meia-noite de Lisboa — as contas fazem-se em UTC, por isso
a mudança da hora (25/10) não estraga nada.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .. import planning_calendars

LISBON = ZoneInfo("Europe/Lisbon")


def split_interval(start: datetime, end: datetime) -> dict[str, float]:
    """{data ISO: horas} de um intervalo [start, end) partido às meias-noites de Lisboa."""
    out = defaultdict(float)
    cursor = start
    while cursor < end:
        local = cursor.astimezone(LISBON)
        midnight = datetime.combine(local.date() + timedelta(days=1), time.min, LISBON).astimezone(timezone.utc)
        stop = min(end, midnight)
        out[local.date().isoformat()] += (stop - cursor).total_seconds() / 3600
        cursor = stop
    return dict(out)


def split_segments(started_at: str, segments) -> dict[str, float]:
    origin = datetime.fromisoformat(started_at)
    if origin.tzinfo is None:
        origin = origin.replace(tzinfo=timezone.utc)
    out = defaultdict(float)
    for a, b in segments:
        for day, hours in split_interval(origin + timedelta(minutes=a), origin + timedelta(minutes=b)).items():
            out[day] += hours
    return dict(out)


def calendar_days(definitions) -> dict[str, float]:
    """Horas de calendário por dia, a partir de várias semanas de calendário de uma máquina."""
    out = defaultdict(float)
    for d in definitions:
        for r in planning_calendars.expand(d) or []:
            for day, hours in split_interval(datetime.fromisoformat(r["start"]), datetime.fromisoformat(r["end"])).items():
                out[day] += hours
    return dict(out)


# Turnos (06/10/2026): em que turno cai cada pedaço de trabalho e de calendário, para o Gantt do dia.
# Os rótulos vêm do horário dos turnos do setor (settings.read(...)["template"]), não das janelas do
# calendário, para que segmentos de um plano aceite e janelas mudadas à mão tenham o rótulo certo.
# O que fica fora de qualquer turno do horário fica sem turno (None): mostram-se as horas, sem inventar.

def _minutes(value: str) -> int:
    return 1440 if value == "24:00" else int(value[:2]) * 60 + int(value[3:])


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """[início, fim) do dia de Lisboa em UTC (23, 24 ou 25 horas)."""
    start = datetime.combine(day, time.min, LISBON).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time.min, LISBON).astimezone(timezone.utc)
    return start, end


def shift_at(local: datetime, template) -> tuple[int, date] | None:
    """(número do turno, dia em que o turno começa) para um instante de Lisboa; None fora dos turnos.

    O turno que passa da meia-noite (ex.: 22:00–05:30) conta para o dia em que começa: 01:00 de quarta é
    o 3.º turno de terça.
    """
    m = local.hour * 60 + local.minute
    for i, (a, b) in enumerate(template):
        a, b = _minutes(a), _minutes(b)
        if b > a:
            if a <= m < b:
                return i + 1, local.date()
        elif m >= a:
            return i + 1, local.date()
        elif m < b:
            return i + 1, local.date() - timedelta(days=1)
    return None


def _cuts(start: datetime, end: datetime, template) -> list[datetime]:
    """Instantes UTC em [start, end) onde algum turno começa ou acaba (hora de Lisboa, 1.ª ocorrência)."""
    marks = sorted({_minutes(x) % 1440 for pair in template for x in pair} | {0})
    out = []
    day = start.astimezone(LISBON).date() - timedelta(days=1)
    last = end.astimezone(LISBON).date() + timedelta(days=1)
    while day <= last:
        for m in marks:
            local = datetime.combine(day, time(m // 60, m % 60), LISBON)
            instant = local.astimezone(timezone.utc)
            if start < instant < end:
                out.append(instant)
        day += timedelta(days=1)
    return sorted(set(out))


def split_by_shift(start: datetime, end: datetime, template) -> list[dict]:
    """Corta [start, end) nos limites dos turnos: [{start, end, from, to, shift, shift_date, hours}] (UTC, horas reais)."""
    out = []
    points = [start, *_cuts(start, end, template), end]
    for a, b in zip(points, points[1:]):
        if b <= a:
            continue
        la, lb = a.astimezone(LISBON), b.astimezone(LISBON)
        found = shift_at(la, template)
        out.append({"start": a, "end": b, "from": la.strftime("%H:%M"), "to": "24:00" if lb.time() == time.min and lb.date() > la.date() else lb.strftime("%H:%M"),
                    "shift": found[0] if found else None, "shift_date": found[1] if found else la.date(),
                    "hours": (b - a).total_seconds() / 3600})
    return out


def labelled_windows(definitions, template, start: datetime, end: datetime) -> list[dict]:
    """Janelas dos calendários dentro de [start, end), cortadas e rotuladas por turno."""
    out = []
    for d in definitions:
        for r in planning_calendars.expand(d) or []:
            a, b = max(datetime.fromisoformat(r["start"]), start), min(datetime.fromisoformat(r["end"]), end)
            if b > a:
                out.extend(split_by_shift(a, b, template))
    return sorted(out, key=lambda w: w["start"])


def bands(day: date, template) -> list[dict]:
    """Faixas dos turnos no eixo do dia, incluindo a madrugada que pertence ao turno do dia anterior."""
    start, end = day_bounds(day)
    out = []
    for i, (a, b) in enumerate(template):
        ma, mb = _minutes(a), _minutes(b)
        pieces = [(day, ma, mb)] if mb > ma else [(day - timedelta(days=1), 0, mb), (day, ma, 1440)]
        for shift_date, x, y in pieces:
            s = datetime.combine(day, time(x // 60, x % 60), LISBON).astimezone(timezone.utc)
            e = end if y == 1440 else datetime.combine(day, time(y // 60, y % 60), LISBON).astimezone(timezone.utc)
            out.append({"start": max(s, start), "end": min(e, end), "shift": i + 1, "shift_date": shift_date, "from": a, "to": b})
    return sorted(out, key=lambda x: x["start"])


def hour_ticks(day: date) -> list[dict]:
    """Uma marca por hora real do dia (25/10 tem duas «01», 29/03 não tem «01»)."""
    start, end = day_bounds(day)
    out, cursor = [], start
    while cursor < end:
        out.append({"at": cursor, "label": cursor.astimezone(LISBON).strftime("%H")})
        cursor += timedelta(hours=1)
    return out
