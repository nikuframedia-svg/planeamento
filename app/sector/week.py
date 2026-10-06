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
