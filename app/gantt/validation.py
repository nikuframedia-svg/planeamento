"""Check a proposed schedule independently from the construction algorithm."""
from __future__ import annotations

from collections import defaultdict
import math

from .contracts import minute, operation_by_key
from .calendar import windows


def score(snapshot, proposal):
    jobs = operation_by_key(snapshot)
    bars = proposal.get('bars') or {}
    counts = [0, 0, 0]
    delays = [0, 0, 0]
    picking_orders = defaultdict(list)
    for key, op in jobs.items():
        if op['state'] != 'ready':
            continue
        group = op['priority_group']
        bar = bars.get(key)
        if not bar:
            counts[group] += 1
        elif group != 1 and op.get('deadline'):
            delays[group] += max(0, bar['end_minute'] - minute(op['deadline'], snapshot['started_at']))
        if group == 1:
            picking_orders[op['of']].append(key)
    for of, keys in picking_orders.items():
        required = [key for key in snapshot.get('orders', {}).get(of, keys)
                    if jobs[key]['state'] != 'complete']
        if required and all(key in bars for key in required):
            due = min(minute(jobs[key]['deadline'], snapshot['started_at']) for key in keys if jobs[key].get('deadline'))
            delays[1] += max(0, max(bars[key]['end_minute'] for key in required) - due)
    previous = snapshot.get('accepted_bars') or {}
    moves = sum(abs(bar['start_minute'] - previous[key]['start_minute']) +
                (480 if bar['resource_id'] != previous[key]['resource_id'] else 0)
                for key, bar in bars.items() if key in previous)
    end = max((bar['end_minute'] for bar in bars.values()), default=0)
    return [counts[0], delays[0], counts[1], delays[1], counts[2], delays[2], moves, end]


def validate(snapshot, proposal):
    input_keys = [job['key'] for job in snapshot['operations']]
    jobs = operation_by_key(snapshot)
    bars = proposal.get('bars') or {}
    states = proposal.get('states') or {}
    errors = []
    if len(input_keys) != len(set(input_keys)):
        errors.append('A entrada contém chaves de operação repetidas.')
    if set(states) != set(jobs):
        errors.append('A proposta não cobre todas as operações.')
    if set(bars) - set(jobs):
        errors.append('A proposta contém operações desconhecidas.')
    occupancy = defaultdict(list)
    def expected_provisional(key, visited=frozenset()):
        if key in visited or key not in bars:
            return []
        job, bar = jobs[key], bars[key]
        matching = next((candidate for candidate in job['options']
                         if candidate['resource_id'] == bar.get('resource_id')
                         and (candidate.get('option_id') == bar.get('option_id')
                              if bar.get('option_id') else
                              candidate['duration_minutes'] == bar.get('duration_minutes'))), None)
        reasons = []
        if job.get('balance_provisional'):
            reasons.append(f'Saldo provisório da operação {key}')
        if matching and matching.get('provisional'):
            reasons.append(f'Duração provisória da operação {key}')
        predecessor = job.get('predecessor_key')
        if predecessor in bars:
            reasons.extend(expected_provisional(predecessor, visited | {key}))
        return sorted(set(reasons))
    for key, job in jobs.items():
        bar = bars.get(key)
        state = states.get(key)
        if job['state'] != 'ready':
            if bar or state != job['state']:
                errors.append(f'{key}: estado ou capacidade futura indevidos.')
            continue
        if not bar:
            if state != 'overflow':
                errors.append(f'{key}: falta o estado por calendarizar.')
            if key in snapshot.get('pins', {}):
                errors.append(f'{key}: fixação sem colocação válida.')
            continue
        if state != 'scheduled':
            errors.append(f'{key}: barra sem estado calendarizado.')
        resource = bar.get('resource_id')
        option = next((x for x in job['options'] if x['resource_id'] == resource
                       and (bar.get('option_id') == x.get('option_id') if bar.get('option_id')
                            else bar.get('duration_minutes') == x['duration_minutes'])), None)
        if not option:
            errors.append(f'{key}: máquina incompatível.'); continue
        if option.get('quantity') != job.get('planning_remaining'):
            errors.append(f'{key}: quantidade diferente do saldo de planeamento.')
        provisional_reasons = expected_provisional(key)
        if bar.get('provisional_reasons', []) != provisional_reasons:
            errors.append(f'{key}: origem da provisoriedade ou dependência incorreta.')
        if bar.get('provisional') != bool(provisional_reasons):
            errors.append(f'{key}: identificação de estimativa provisória incorreta.')
        hours = option.get('duration_hours')
        if not isinstance(hours,(int,float)) or not math.isfinite(hours) or math.ceil(hours*60) != option['duration_minutes']:
            errors.append(f'{key}: duração e horas de origem divergentes.')
        if bar.get('duration_minutes') != option['duration_minutes']:
            errors.append(f'{key}: duração diferente da estimativa escolhida.')
        start, end = bar.get('start_minute'), bar.get('end_minute')
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= snapshot['horizon_minutes']:
            errors.append(f'{key}: intervalo inválido.'); continue
        if start < (option.get('earliest_minute') or 0) or option.get('latest_minute') is not None and end > option['latest_minute']:
            errors.append(f'{key}: taxa fora da vigência.')
        segments = bar.get('segments') or []
        if not segments or segments[0][0] != start or segments[-1][1] != end:
            errors.append(f'{key}: segmentos incompletos.'); continue
        if sum(right-left for left, right in segments) != option['duration_minutes']:
            errors.append(f'{key}: minutos úteis incorretos.')
        available = windows(snapshot, resource)
        if any(not any(low <= left < right <= high for low, high in available) for left, right in segments):
            errors.append(f'{key}: trabalho fora do horário.')
        if any(left[1] > right[0] for left, right in zip(segments, segments[1:])):
            errors.append(f'{key}: segmentos sobrepostos ou sem pausa.')
        if any(any(max(gap_start, low) < min(gap_end, high) for low, high in available)
               for (_, gap_start), (gap_end, _) in zip(segments, segments[1:])):
            errors.append(f'{key}: execução interrompida durante horário disponível.')
        for left, right in segments:
            occupancy[resource].append((left, right, key))
        pin = snapshot.get('pins', {}).get(key)
        if pin and (resource != pin['resource_id'] or start != minute(pin['start'], snapshot['started_at'])):
            errors.append(f'{key}: fixação não respeitada.')
        predecessor = job.get('predecessor_key')
        if predecessor and jobs.get(predecessor, {}).get('state') != 'complete':
            prior = bars.get(predecessor)
            if not prior or prior['end_minute'] > start:
                errors.append(f'{key}: dependência não respeitada.')
    for resource, used in occupancy.items():
        used.sort()
        for left, right in zip(used, used[1:]):
            if left[1] > right[0]:
                errors.append(f'{resource}: {left[2]} e {right[2]} sobrepõem-se.')
    for of, keys in snapshot.get('orders', {}).items():
        complete = all(states.get(key) in ('complete', 'scheduled') for key in keys)
        if (proposal.get('ready_orders') or {}).get(of) and not complete:
            errors.append(f'{of}: a OF aparece pronta sem todas as operações.')
    expected = score(snapshot, proposal)
    if proposal.get('score') is not None and proposal['score'] != expected:
        errors.append('Métricas diferentes das barras verificadas.')
    return {'valid': not errors, 'errors': errors, 'score': expected,
            'coverage': 'complete' if not any(states.get(j['key']) in ('blocked','overflow') for j in jobs.values()) else 'partial'}
