"""Deterministic earliest-due feasible schedule and CP-SAT fallback."""
from __future__ import annotations

from .calendar import first_fit, windows
from .contracts import minute
from .provenance import apply as annotate_provisional
from .validation import validate


def build(snapshot):
    jobs = {job['key']: job for job in snapshot['operations']}
    states = {key: job['state'] if job['state'] != 'ready' else 'overflow' for key, job in jobs.items()}
    bars = {}
    unplaced = {}
    occupied = {resource: [] for resource in snapshot['resources']}
    remaining = {key for key, job in jobs.items() if job['state'] == 'ready'}
    # Reserve fixed work and its unfinished predecessors before free work can
    # consume their slots. A fixed successor cannot run until its chain ends.
    pin_chain = {}
    def reserve_chain(key, fixed_minute):
        if key not in remaining or pin_chain.get(key, fixed_minute + 1) <= fixed_minute:
            return
        pin_chain[key] = fixed_minute
        predecessor = jobs[key].get('predecessor_key')
        if predecessor in remaining:
            reserve_chain(predecessor, fixed_minute)
    for key, pin in snapshot.get('pins', {}).items():
        if key in remaining:
            reserve_chain(key, minute(pin['start'], snapshot['started_at']))
    def order(key):
        job = jobs[key]
        due = minute(job['deadline'], snapshot['started_at']) if job.get('deadline') else snapshot['horizon_minutes']
        if key in pin_chain:
            return (0, pin_chain[key], key in snapshot.get('pins', {}), job['of'], key)
        return (1, job['priority_group'], due, job['of'], key)
    while remaining:
        progressed = False
        protected = remaining.intersection(pin_chain)
        for key in sorted(protected if protected else remaining, key=order):
            job = jobs[key]
            prior = job.get('predecessor_key')
            if prior and prior in remaining:
                continue
            earliest = bars[prior]['end_minute'] if prior in bars else 0
            if prior and jobs[prior]['state'] != 'complete' and prior not in bars:
                remaining.remove(key); states[key] = 'overflow'
                unplaced[key] = 'Dependência anterior sem colocação no horizonte.'
                progressed = True; continue
            pin = snapshot.get('pins', {}).get(key)
            candidates = []
            for option in job['options']:
                resource = option['resource_id']
                if pin and pin['resource_id'] != resource:
                    continue
                fixed = minute(pin['start'], snapshot['started_at']) if pin else None
                found = first_fit(windows(snapshot, resource), max(earliest, option.get('earliest_minute') or 0),
                                  option['duration_minutes'], occupied[resource], fixed)
                if found and option.get('latest_minute') is not None and found['end'] > option['latest_minute']:
                    found = None
                if found:
                    candidates.append((found['end'], resource, found['start'],
                                       str(option.get('option_id') or option['duration_minutes']), found, option))
            if candidates:
                _, resource, _, _, found, option = min(candidates, key=lambda x: x[:4])
                bars[key] = {'resource_id': resource, 'start_minute': found['start'],
                             'end_minute': found['end'], 'segments': found['segments'],
                             'duration_minutes': option['duration_minutes'],
                             'option_id':option.get('option_id'),
                             'provisional':bool(job.get('balance_provisional') or option.get('provisional'))}
                occupied[resource].extend(found['segments'])
                occupied[resource].sort()
                states[key] = 'scheduled'
            else:
                unplaced[key] = 'Sem encaixe válido no calendário, vigência ou fixação.'
            remaining.remove(key)
            progressed = True
        if not progressed:
            for key in remaining:
                states[key] = 'overflow'
                unplaced[key] = 'Ciclo ou dependência sem colocação.'
            break
    proposal = {'bars': bars, 'states': states, 'unplaced_reasons': unplaced,
                'origin': 'sequência inicial'}
    annotate_provisional(jobs, bars)
    check = validate(snapshot, proposal)
    if not check['valid']:
        raise ValueError('Proposta inicial inválida: ' + '; '.join(check['errors']))
    proposal['score'] = check['score']
    proposal['coverage'] = check['coverage']
    return proposal
