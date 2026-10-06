"""Existing dated plan and weekly load; never fabricates hourly execution windows."""
from collections import defaultdict
from datetime import date, timedelta
import math
import uuid

from .. import planning_calendars


def imported_resource_id(machine):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'planeamento:perfis:machine:' + machine))


def availability(conn, generation, configs, aliases):
    """Read the workbook belonging to the published generation, in caller's transaction."""
    source = generation.get('metadata', {}).get('snapshot') or {}
    snapshot = source.get('snapshot_id')
    rows = conn.execute("SELECT excel_row,row_data FROM raw_mtg.other_sheet_rows "
        "WHERE snapshot_id=%s AND sheet_name='PlanDisponibilidadeSemanal' ORDER BY excel_row",
        (snapshot,)).fetchall() if snapshot else []
    grouped = defaultdict(list)
    for row in rows:
        values = row['row_data'].get('values') or []
        if len(values) < 7 or not values[3]:
            continue
        try:
            year, week = int(values[2]), int(values[1])
            if year != values[2] or week != values[1]:
                continue
            date.fromisocalendar(year, week, 1)
            shifts, hours = float(values[5]), float(values[6])
            amount = shifts * hours
            if shifts < 0 or hours < 0 or not math.isfinite(amount):
                continue
        except (ValueError, TypeError, OverflowError):
            continue
        machine = str(values[3]).strip()
        rid = aliases.get(machine, imported_resource_id(machine))
        grouped[(rid, year, week)].append({'hours': amount, 'machine': machine,
            'snapshot': snapshot, 'file': source.get('source_filename'),
            'sheet': 'PlanDisponibilidadeSemanal', 'row': row['excel_row']})
    result = {}
    for (rid, year, week), evidence in grouped.items():
        amounts = sorted({r['hours'] for r in evidence})
        result[(rid, year, week)] = {'resource_id': rid, 'year': year, 'week': week,
            'hours': amounts[0] if len(amounts) == 1 else None,
            'status': 'imported' if len(amounts) == 1 else 'conflict',
            'alternatives': amounts, 'evidence': evidence}
    for config in configs:
        d = config['definition']
        if config['kind'] != 'calendar' or not d.get('confirmed'):
            continue
        key = (str(d['resource_id']), d['year'], d['week'])
        previous = result.get(key)
        result[key] = {'resource_id': key[0], 'year': key[1], 'week': key[2],
            'hours': planning_calendars.available_hours(d), 'status': 'confirmed',
            'alternatives': [], 'evidence': [{'object_id': str(config['id']),
                'revision': config.get('revision')}],
            'imported_evidence': previous['evidence'] if previous else []}
    return sorted(result.values(), key=lambda r: (r['resource_id'], r['year'], r['week']))


def build(snapshot):
    entries, pending = [], []
    loads = defaultdict(lambda: {'hours': 0, 'unknown_durations': 0, 'operations': 0,
                                 'provisional_operations': 0})
    complete = 0
    for op in snapshot['operations']:
        if op['state'] == 'complete':
            complete += 1
            continue
        m = op['milestones']
        period = m.get('period_origin') == 'Decisão local'
        reasons = []
        if 'Operação fora da seleção do cenário.' in op['blocking_reasons'] or 'Trabalho excluído da seleção.' in op['blocking_reasons']:
            pending.append({'key':op['key'],'reasons':['Operação fora da seleção.']})
            continue
        if any(reason in op['blocking_reasons'] for reason in (
                'Data prevista inválida.', 'Ano/semana explícitos inválidos.',
                'Data prevista e semana escolhida não coincidem.')):
            reasons.append('Previsão em conflito.')
        start = end = None
        try:
            if period:
                start = date.fromisocalendar(m['period_year'], m['period_week'], 1)
                end = start + timedelta(days=7)
            elif m.get('operation_forecast'):
                start = date.fromisoformat(str(m['operation_forecast'])[:10])
                end = start + timedelta(days=1)
        except (ValueError, TypeError, KeyError):
            reasons.append('Previsão inválida.')
        if not start:
            reasons.append('Previsão da operação por indicar.')
        rid = (op.get('assignment') or {}).get('resource_id') or op.get('source_resource_id')
        if not rid:
            reasons.append('Máquina da operação por indicar.')
        if reasons:
            pending.append({'key': op['key'], 'reasons': reasons})
            continue
        duration = op.get('source_duration') or {}
        hours = duration.get('hours')
        valid = (isinstance(hours, (int, float)) and math.isfinite(hours) and hours > 0
                 and op['planning_remaining'] is not None
                 and duration.get('quantity') == op['planning_remaining'])
        year, week, _ = start.isocalendar()
        entry = {'key': op['key'], 'resource_id': rid, 'start_date': start.isoformat(),
            'end_date_exclusive': end.isoformat(), 'precision': 'week' if period else 'day',
            'year': year, 'week': week, 'hours': hours if valid else None,
            'duration_origin': duration.get('origin'),
            'provisional': bool(op['provisional'] or duration.get('origin') != 'Manual'),
            'forecast_origin': m.get('period_origin'),
            'assignment': op.get('assignment'),
            'hourly_reasons': op['blocking_reasons']}
        entries.append(entry)
        load = loads[(rid, year, week)]
        load['hours'] += hours if valid else 0
        load['unknown_durations'] += not valid
        load['operations'] += 1
        load['provisional_operations'] += entry['provisional']
    capacity = {(r['resource_id'], r['year'], r['week']): r for r in snapshot['weekly_availability']}
    weekly = []
    for key in sorted(loads.keys() | capacity.keys()):
        weekly.append({'resource_id': key[0], 'year': key[1], 'week': key[2],
            **loads[key], 'availability': capacity.get(key)})
    return {'entries': sorted(entries, key=lambda r: (r['start_date'], r['resource_id'], r['key'])),
            'pending': pending, 'completed': complete, 'weekly_load': weekly,
            'semantics': 'Previsões importadas/manuais; largura por dia ou semana, sem hora de execução.'}
