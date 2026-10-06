"""Recuperação de atraso numa janela curta (plano de 01/10/2026, secção 10).

Mede uma proposta contra a mesma entrada congelada:
- horas de referência = duração da opção da máquina de origem quando existe, senão a menor opção
  admissível; ficam fixas para comparar planos (uma máquina mais lenta não «reduz» mais atraso);
- trabalho omitido, bloqueado ou fora do horizonte nunca conta como concluído;
- um marco de OF só conta quando todas as operações dessa OF no setor terminam na janela.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from .contracts import minute, utc

WINDOW_DAYS = 14


def reference_hours(op):
    options = [o for o in op.get('options', []) if o.get('eligibility', 'admissible') == 'admissible']
    source = [o for o in options if o['resource_id'] == op.get('source_resource_id')]
    chosen = min(source or options, key=lambda o: o['duration_minutes'], default=None)
    return chosen['duration_minutes'] / 60 if chosen else None


def evaluate(snapshot, proposal, *, days=WINDOW_DAYS):
    start = snapshot['started_at']
    window = min(days * 1440, snapshot['horizon_minutes'])
    end = utc(start) + timedelta(minutes=window)
    bars = (proposal or {}).get('bars') or {}
    result = {'window_days': days, 'late_reference_hours': 0.0, 'late_completed_hours': 0.0,
              'due_reference_hours': 0.0, 'due_completed_hours': 0.0, 'unknown_reference_hours': 0,
              'not_ready': 0, 'orders_due': 0, 'orders_completed': 0}
    orders = defaultdict(lambda: {'keys': [], 'done': 0})
    for op in snapshot['operations']:
        if op['state'] == 'complete' or not op.get('deadline'):
            continue
        due = minute(op['deadline'], start)
        late, due_in_window = due <= 0, 0 < due <= window
        if not (late or due_in_window):
            continue
        hours = reference_hours(op)
        bar = bars.get(op['key'])
        finished = bool(bar) and bar['end_minute'] <= window
        if op['state'] != 'ready':
            result['not_ready'] += 1
        if hours is None:
            result['unknown_reference_hours'] += 1
        else:
            kind = 'late' if late else 'due'
            result[f'{kind}_reference_hours'] += hours
            if finished:
                result[f'{kind}_completed_hours'] += hours
        group = orders[(op.get('area'), op['of'])]
        group['keys'].append(op['key'])
        group['done'] += finished
    for group in orders.values():
        result['orders_due'] += 1
        result['orders_completed'] += group['done'] == len(group['keys'])
    for key in ('late_reference_hours', 'late_completed_hours', 'due_reference_hours', 'due_completed_hours'):
        result[key] = round(result[key], 2)
    result['until'] = end.isoformat()
    return result


def compare(snapshot, reference, proposal, *, days=WINDOW_DAYS):
    before, after = evaluate(snapshot, reference, days=days), evaluate(snapshot, proposal, days=days)
    return {'reference': before, 'proposal': after,
            'gain_late_hours': round(after['late_completed_hours'] - before['late_completed_hours'], 2),
            'gain_orders': after['orders_completed'] - before['orders_completed'],
            'semantics': 'Mesma entrada, mesmas horas de referência e mesma janela; trabalho não colocado não conta.'}
