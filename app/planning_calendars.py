"""Confirmed machine windows, with an exact UTC expansion for scheduling."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def _minutes(value, *, end=False):
    if end and value == '24:00':
        return 1440
    if not isinstance(value, str) or len(value) != 5 or value[2] != ':':
        raise ValueError('Indica horas no formato HH:MM.')
    hour, minute = int(value[:2]), int(value[3:])
    if not 0 <= hour < 24 or not 0 <= minute < 60:
        raise ValueError('Hora inválida.')
    return hour * 60 + minute


def _at(day, minutes, zone):
    local = datetime.combine(day + timedelta(days=minutes // 1440), time.min, zone) + timedelta(minutes=minutes % 1440)
    if local.replace(fold=1).utcoffset() != local.replace(fold=0).utcoffset():
        raise ValueError('Hora local ambígua numa mudança de fuso; divide o intervalo.')
    return local.astimezone(timezone.utc)


def validate(definition):
    """Normalize an hourly week; a missing weekly_windows key is legacy-only."""
    if 'weekly_windows' not in definition:
        return definition
    year, week = int(definition['year']), int(definition['week'])
    date.fromisocalendar(year, week, 1)
    zone_name = definition.get('timezone') or 'Europe/Lisbon'
    ZoneInfo(zone_name)
    weekly = definition['weekly_windows']
    overrides = definition.get('date_overrides') or {}
    if not isinstance(weekly, dict) or not isinstance(overrides, dict):
        raise ValueError('Indica intervalos por dia e exceções por data.')
    if any(str(day) not in {str(i) for i in range(1, 8)} for day in weekly):
        raise ValueError('Dia semanal inválido.')
    for day in overrides:
        if date.fromisoformat(day).isocalendar()[:2] != (year, week):
            raise ValueError('A exceção pertence a outra semana.')
    normalized = dict(definition)
    normalized['timezone'] = zone_name
    normalized['weekly_windows'] = {str(day): _normalize(windows) for day, windows in weekly.items()}
    normalized['date_overrides'] = {day: _normalize(windows) for day, windows in overrides.items()}
    reservations = definition.get('reserved_windows') or []
    if not isinstance(reservations, list):
        raise ValueError('As reservas horárias devem formar uma lista.')
    first = date.fromisocalendar(year, week, 1)
    zone = ZoneInfo(zone_name)
    week_start = datetime.combine(first, time.min, zone).astimezone(timezone.utc)
    week_end = datetime.combine(first + timedelta(days=7), time.min, zone).astimezone(timezone.utc)
    normalized_reservations = []
    for item in reservations:
        if not isinstance(item, dict):
            raise ValueError('Reserva horária inválida.')
        try:
            start, end = datetime.fromisoformat(item['start']), datetime.fromisoformat(item['end'])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError('Indica início e fim ISO da reserva horária.') from exc
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError('As reservas horárias exigem fuso horário explícito.')
        start, end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
        if not week_start <= start < end <= week_end:
            raise ValueError('A reserva horária deve estar dentro da semana.')
        normalized_reservations.append({'start':start.isoformat(),'end':end.isoformat(),
                                        'area':str(item.get('area') or '').strip()})
    normalized_reservations.sort(key=lambda item:item['start'])
    if any(left['end'] > right['start'] for left,right in zip(normalized_reservations,normalized_reservations[1:])):
        raise ValueError('Existem reservas horárias sobrepostas.')
    normalized['reserved_windows'] = normalized_reservations
    # Also detect UTC overlaps across a local clock change.
    expand(normalized)
    return normalized


def _normalize(windows):
    if not isinstance(windows, list):
        raise ValueError('Os intervalos do dia devem formar uma lista.')
    result = []
    for window in windows:
        if not isinstance(window, dict):
            raise ValueError('Intervalo inválido.')
        start, end = _minutes(window.get('start')), _minutes(window.get('end'), end=True)
        if end <= start:
            raise ValueError('Divide os turnos que atravessam a meia-noite entre dois dias.')
        result.append({'start': f'{start//60:02}:{start%60:02}',
                       'end': '24:00' if end == 1440 else f'{end//60:02}:{end%60:02}'})
    result.sort(key=lambda item: item['start'])
    for left, right in zip(result, result[1:]):
        if left['end'] > right['start']:
            raise ValueError('Existem intervalos sobrepostos no mesmo dia.')
    return result


def expand(definition):
    if 'weekly_windows' not in definition:
        return None
    year, week = int(definition['year']), int(definition['week'])
    zone = ZoneInfo(definition.get('timezone') or 'Europe/Lisbon')
    first = date.fromisocalendar(year, week, 1)
    result = []
    for offset in range(7):
        day = first + timedelta(days=offset)
        windows = (definition.get('date_overrides') or {}).get(day.isoformat(),
                   (definition.get('weekly_windows') or {}).get(str(offset + 1), []))
        for window in windows:
            start = _at(day, _minutes(window['start']), zone)
            end = _at(day, _minutes(window['end'], end=True), zone)
            if end <= start:
                raise ValueError('Intervalo sem minutos úteis.')
            result.append({'start': start.isoformat(), 'end': end.isoformat()})
    result.sort(key=lambda item: item['start'])
    for left, right in zip(result, result[1:]):
        if left['end'] > right['start']:
            raise ValueError('Os intervalos da máquina sobrepõem-se.')
    reservations = definition.get('reserved_windows') or []
    if not reservations:
        return result
    available = []
    for window in result:
        cursor = datetime.fromisoformat(window['start'])
        limit = datetime.fromisoformat(window['end'])
        for reservation in reservations:
            blocked_start = datetime.fromisoformat(reservation['start'])
            blocked_end = datetime.fromisoformat(reservation['end'])
            if blocked_end <= cursor or blocked_start >= limit:
                continue
            if blocked_start > cursor:
                available.append({'start':cursor.isoformat(),'end':blocked_start.isoformat()})
            cursor = max(cursor, min(blocked_end, limit))
            if cursor >= limit:
                break
        if cursor < limit:
            available.append({'start':cursor.isoformat(),'end':limit.isoformat()})
    return available


def available_hours(definition):
    intervals = expand(definition)
    if intervals is None:
        return definition['shifts'] * definition['hours_per_shift'] - definition.get('exception_hours', 0)
    return sum((datetime.fromisoformat(r['end']) - datetime.fromisoformat(r['start'])).total_seconds() / 3600 for r in intervals)
