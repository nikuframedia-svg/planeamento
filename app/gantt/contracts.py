"""Small, explicit wire contracts used by the scheduler and its verifier."""
from __future__ import annotations

from datetime import datetime, timezone

HORIZON_WEEKS = 12
SOLVER_SECONDS = 30


def utc(value):
    instant = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if instant.tzinfo is None:
        raise ValueError('É necessária uma hora com fuso explícito.')
    return instant.astimezone(timezone.utc)


def minute(value, origin):
    seconds = (utc(value) - utc(origin)).total_seconds()
    if seconds % 60:
        raise ValueError('As horas da proposta devem ter precisão ao minuto.')
    return int(seconds // 60)


def timestamp(value, origin):
    from datetime import timedelta
    return (utc(origin) + timedelta(minutes=int(value))).isoformat()


def operation_by_key(snapshot):
    return {item['key']: item for item in snapshot['operations']}
