"""Dates used by planning. Forecasts, downstream need and CPIS milestones stay distinct."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .dossiers.models import order_number


def normalized_of(value):
    if isinstance(value, (int, float)) and float(value).is_integer():
        value = str(int(value))
    return order_number(value)


def positive_week(value):
    try:
        number = float(str(value).replace(',', '.'))
        return int(number) if number.is_integer() and 1 <= number <= 53 else None
    except (TypeError, ValueError):
        return None


def _integer(value):
    try:
        number = float(str(value).replace(',', '.'))
        return int(number) if number.is_integer() else None
    except (TypeError, ValueError):
        return None


def picking_index(rows):
    """Return unambiguous OF weeks and all source cells, including conflicts."""
    evidence = {}
    for row in rows:
        values = (row.get('row_data') or {}).get('values') or []
        if len(values) < 3:
            continue
        of = normalized_of(values[1])
        week = positive_week(values[2])
        if of and week:
            evidence.setdefault(of, []).append({'week': week, 'row': row.get('excel_row'), 'sheet': 'Picking'})
    weeks = {}
    for of, sources in evidence.items():
        unique = {source['week'] for source in sources}
        weeks[of] = next(iter(unique)) if len(unique) == 1 else None
    return weeks, evidence


def resolve_picking(of, line_week, indexed_weeks, evidence, *, manual_week=None, has_manual=False):
    of = normalized_of(of)
    source_week = indexed_weeks.get(of)
    cell_week = positive_week(line_week)
    manual = positive_week(manual_week) if has_manual else None
    conflict = bool(source_week and cell_week and source_week != cell_week)
    if indexed_weeks.get(of, False) is None and evidence.get(of):
        conflict = True
    if has_manual:
        return {'week': manual, 'origin': 'Decisão manual', 'conflict': False,
                'evidence': evidence.get(of, []), 'line_week': cell_week}
    if conflict:
        return {'week': None, 'origin': 'Conflito Picking', 'conflict': True,
                'evidence': evidence.get(of, []), 'line_week': cell_week}
    return {'week': source_week or cell_week, 'origin': 'Picking · folha' if source_week else 'Picking · linha' if cell_week else None,
            'conflict': False, 'evidence': evidence.get(of, []), 'line_week': cell_week}


def period(values, *, area, operation='corte', cantoneiras_week=None):
    """Resolve an operation period without borrowing the date of another operation."""
    expected = values.get('expected_date')
    explicit_year, explicit_week = values.get('planned_year'), values.get('planned_week')
    forecast = expected or (values.get('cut_date') if area == 'perfis' and operation == 'corte' else None)
    from_date = None
    if forecast:
        try:
            from_date = date.fromisoformat(str(forecast)[:10]).isocalendar()[:2]
        except ValueError:
            return None, None, 'Data prevista inválida.'
    if explicit_year not in (None, '') or explicit_week not in (None, ''):
        try:
            year, week = _integer(explicit_year), positive_week(explicit_week)
            date.fromisocalendar(year, week, 1)
        except (TypeError, ValueError):
            return None, None, 'Ano/semana explícitos inválidos.'
        if expected and from_date != (year, week):
            return None, None, 'Data prevista e semana escolhida não coincidem.'
        return year, week, 'Decisão local'
    if from_date:
        return *from_date, 'Data prevista' if expected else 'Data Corte'
    if area == 'cantoneiras' and cantoneiras_week:
        return None, cantoneiras_week, 'Semana W importada — ano por confirmar'
    return None, None, 'Por calendarizar'


def operation_period_inputs(values, operation_values, *, area, operation):
    """Keep line-level cut decisions separate from operation-level decisions."""
    source = values if area == 'perfis' and operation == 'corte' else {}
    local = operation_values or {}
    result = {field: source.get(field) for field in ('expected_date', 'planned_year', 'planned_week')}
    if local.get('expected_date') not in (None, ''):
        result['expected_date'] = local['expected_date']
    if any(local.get(field) not in (None, '') for field in ('planned_year', 'planned_week')):
        result.update({field: local.get(field) for field in ('planned_year', 'planned_week')})
    result['cut_date'] = values.get('cut_date') if area == 'perfis' and operation == 'corte' else None
    return result


def period_deadline(year, week, *, timezone='Europe/Lisbon'):
    """Exclusive end of a chosen ISO week; it is not a machine start time."""
    next_monday = date.fromisocalendar(year, week, 1) + timedelta(days=7)
    return datetime.combine(next_monday, time.min, ZoneInfo(timezone)).isoformat()


def picking_deadline(week, year=None, *, assumed_year=2026, timezone='Europe/Lisbon'):
    week = positive_week(week)
    if week is None:
        return None
    explicit = year not in (None, '')
    try:
        chosen = _integer(year) if explicit else assumed_year
        day = date.fromisocalendar(chosen, week, 1)
    except (ValueError, TypeError):
        return None
    return {'at': datetime.combine(day, time(8), ZoneInfo(timezone)).isoformat(),
            'year': chosen, 'week': week, 'provisional': not explicit,
            'origin': 'Picking · ano assumido' if not explicit else 'Picking · ano explícito'}


def picking_values(of, line_week, indexed_weeks, evidence, *, record=None, override=None):
    """Effective Picking, with imported suggestions separate from explicit decisions.

    Older manual forms saved blank fields as `write` even when untouched. Such
    blanks are not an instruction to erase Picking. An explicit `clear` is.
    """
    record = record or {}
    state = (record.get('provenance_json') or {}).get(str(record.get('operation_id')) + ':picking_week') or {}
    decision = state.get('human_decision')
    manual_week = (record.get('values_json') or {}).get('picking_week')
    has_manual = decision == 'clear' or bool(decision and positive_week(manual_week))
    if override is not None:
        manual_week, decision = override
        has_manual = decision == 'clear' or bool(positive_week(manual_week))
    selected = resolve_picking(of, line_week, indexed_weeks, evidence,
                               manual_week=manual_week, has_manual=has_manual)
    return {'picking_week': selected['week'], 'picking_origin': selected['origin'],
            'picking_evidence': selected['evidence'], 'picking_conflict': selected['conflict']}
