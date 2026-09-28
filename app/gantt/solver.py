"""CP-SAT flexible job shop over machine-specific working-minute axes."""
from __future__ import annotations

import time
from collections import defaultdict

from ortools.sat.python import cp_model

from .calendar import windows, working_offset
from .contracts import SOLVER_SECONDS, minute
from .validation import validate
from .provenance import apply as annotate_provisional


def optimize(snapshot, baseline, *, seconds=SOLVER_SECONDS):
    started = time.monotonic()
    jobs = {job['key']: job for job in snapshot['operations']}
    ready = [job for job in jobs.values() if job['state'] == 'ready']
    if not ready:
        return baseline, {'status': 'sem operações elegíveis', 'optimal': False, 'seconds': 0}
    model = cp_model.CpModel()
    horizon = snapshot['horizon_minutes']
    machine_intervals = defaultdict(list)
    placements = {}
    starts = {}
    ends = {}
    lateness = {}
    by_group = defaultdict(list)
    for job in ready:
        if time.monotonic()-started >= seconds:
            return baseline, {'status':'orçamento esgotado ao construir o modelo',
                              'optimal':False,'seconds':round(time.monotonic()-started,3)}
        key = job['key']
        placed = model.NewBoolVar('placed:' + key)
        starts[key] = model.NewIntVar(0, horizon, 'start:' + key)
        ends[key] = model.NewIntVar(0, horizon, 'end:' + key)
        choices = []
        for index, option in enumerate(job['options']):
            resource = option['resource_id']
            available = windows(snapshot, resource)
            total = sum(high-low for low, high in available)
            duration = option['duration_minutes']
            if not available or duration > total:
                continue
            chosen = model.NewBoolVar(f'use:{key}:{index}')
            start_work = model.NewIntVar(0, total-duration, f'ws:{key}:{index}')
            end_work = model.NewIntVar(duration, total, f'we:{key}:{index}')
            model.Add(end_work == start_work + duration).OnlyEnforceIf(chosen)
            machine_intervals[resource].append(model.NewOptionalIntervalVar(
                start_work, duration, end_work, chosen, f'interval:{key}:{index}'))
            first, last = [], []
            accumulated = 0
            for window_index, (low, high) in enumerate(available):
                if time.monotonic()-started >= seconds:
                    return baseline, {'status':'orçamento esgotado ao expandir calendários',
                                      'optimal':False,'seconds':round(time.monotonic()-started,3)}
                size = high-low
                begin = model.NewBoolVar(f'begin:{key}:{index}:{window_index}')
                finish = model.NewBoolVar(f'finish:{key}:{index}:{window_index}')
                model.Add(start_work >= accumulated).OnlyEnforceIf(begin)
                model.Add(start_work <= accumulated + size - 1).OnlyEnforceIf(begin)
                model.Add(starts[key] == low + start_work - accumulated).OnlyEnforceIf(begin)
                model.Add(end_work >= accumulated + 1).OnlyEnforceIf(finish)
                model.Add(end_work <= accumulated + size).OnlyEnforceIf(finish)
                model.Add(ends[key] == low + end_work - accumulated).OnlyEnforceIf(finish)
                model.AddImplication(begin, chosen)
                model.AddImplication(finish, chosen)
                first.append(begin)
                last.append(finish)
                accumulated += size
            model.Add(sum(first) == chosen)
            model.Add(sum(last) == chosen)
            if option.get('earliest_minute') is not None:
                model.Add(starts[key] >= option['earliest_minute']).OnlyEnforceIf(chosen)
            if option.get('latest_minute') is not None:
                model.Add(ends[key] <= option['latest_minute']).OnlyEnforceIf(chosen)
            pin = snapshot.get('pins', {}).get(key)
            if pin and pin['resource_id'] == resource:
                model.Add(starts[key] == minute(pin['start'], snapshot['started_at'])).OnlyEnforceIf(chosen)
            elif pin:
                model.Add(chosen == 0)
            choices.append((chosen, resource, option, start_work, end_work, first, last, available))
        model.Add(sum(choice[0] for choice in choices) == placed)
        if key in snapshot.get('pins', {}):
            model.Add(placed == 1)
        previous = (snapshot.get('accepted_bars') or {}).get(key)
        model.Add(starts[key] == (previous['start_minute'] if previous else 0)).OnlyEnforceIf(placed.Not())
        model.Add(ends[key] == 0).OnlyEnforceIf(placed.Not())
        placements[key] = (placed, choices)
        by_group[job['priority_group']].append(key)
        if job.get('deadline') and job['priority_group'] != 1:
            due = minute(job['deadline'], snapshot['started_at'])
            late = model.NewIntVar(0, max(horizon, horizon-due), 'late:' + key)
            model.Add(late >= ends[key] - due).OnlyEnforceIf(placed)
            model.Add(late == 0).OnlyEnforceIf(placed.Not())
            lateness[key] = late
    for resource, intervals in machine_intervals.items():
        model.AddNoOverlap(intervals)
    for job in ready:
        prior = job.get('predecessor_key')
        if prior in placements:
            model.Add(placements[job['key']][0] <= placements[prior][0])
            model.Add(starts[job['key']] >= ends[prior]).OnlyEnforceIf(placements[job['key']][0])
        elif prior and jobs.get(prior, {}).get('state') != 'complete':
            model.Add(placements[job['key']][0] == 0)

    picking_lateness = []
    for of in sorted({jobs[key]['of'] for key in by_group[1]}):
        keys = [key for key in by_group[1] if jobs[key]['of'] == of]
        required = [key for key in snapshot.get('orders', {}).get(of, keys)
                    if jobs[key]['state'] != 'complete']
        if not all(key in placements for key in required):
            continue
        all_placed = model.NewBoolVar('of-ready:' + of)
        model.Add(sum(placements[key][0] for key in required) == len(required)).OnlyEnforceIf(all_placed)
        model.Add(sum(placements[key][0] for key in required) <= len(required)-1).OnlyEnforceIf(all_placed.Not())
        finished = model.NewIntVar(0, horizon, 'of-end:' + of)
        model.AddMaxEquality(finished, [ends[key] for key in required])
        due = min(minute(jobs[key]['deadline'], snapshot['started_at']) for key in keys)
        late = model.NewIntVar(0, max(horizon,horizon-due), 'of-late:' + of)
        model.Add(late >= finished - due).OnlyEnforceIf(all_placed)
        model.Add(late == 0).OnlyEnforceIf(all_placed.Not())
        picking_lateness.append(late)

    moves = []
    for key, prior in (snapshot.get('accepted_bars') or {}).items():
        if key not in placements:
            continue
        delta = model.NewIntVar(0, horizon+abs(prior['start_minute']), 'move:' + key)
        model.AddAbsEquality(delta, starts[key] - prior['start_minute'])
        moves.append(delta)
        for chosen, resource, *_ in placements[key][1]:
            if resource != prior['resource_id']:
                moves.append(480 * chosen)
    makespan = model.NewIntVar(0, horizon, 'makespan')
    model.AddMaxEquality(makespan, list(ends.values()))
    objectives = []
    for group in range(3):
        objectives.append(sum(1-placements[key][0] for key in by_group[group]))
        objectives.append(sum(picking_lateness) if group == 1 else sum(lateness[key] for key in by_group[group] if key in lateness))
    objectives.extend([sum(moves), makespan])

    # Give the solver the independently validated deterministic proposal.
    for key, (placed, choices) in placements.items():
        if time.monotonic()-started >= seconds:
            return baseline, {'status':'orçamento esgotado ao preparar as sugestões',
                              'optimal':False,'seconds':round(time.monotonic()-started,3)}
        bar = baseline['bars'].get(key)
        model.AddHint(placed, int(bar is not None))
        if bar:
            model.AddHint(starts[key], bar['start_minute'])
            model.AddHint(ends[key], bar['end_minute'])
        for chosen, resource, option, ws, we, first, last, available in choices:
            selected = bool(bar and resource == bar['resource_id'])
            model.AddHint(chosen, int(selected))
            if selected:
                start_work = working_offset(available, bar['start_minute'])
                end_work = working_offset(available, bar['end_minute'], end=True)
                if start_work is not None and end_work is not None:
                    model.AddHint(ws, start_work)
                    model.AddHint(we, end_work)

    best = baseline
    statuses = []
    for stage, expression in enumerate(objectives):
        remaining = seconds - (time.monotonic() - started)
        if remaining <= 0:
            break
        model.Minimize(expression)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = min(remaining, max(1, remaining / (len(objectives)-stage)))
        solver.parameters.num_search_workers = 2
        result = solver.Solve(model)
        statuses.append(solver.StatusName(result))
        if result not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            break
        bars = {}
        states = dict(baseline['states'])
        for key, (placed, choices) in placements.items():
            if not solver.Value(placed):
                states[key] = 'overflow'
                continue
            for chosen, resource, option, *_ in choices:
                if solver.Value(chosen):
                    start, end = solver.Value(starts[key]), solver.Value(ends[key])
                    used = []
                    for low, high in windows(snapshot, resource):
                        left, right = max(low, start), min(high, end)
                        if right > left:
                            used.append((left, right))
                    bars[key] = {'resource_id': resource, 'start_minute': start,
                                 'end_minute': end, 'segments': used,
                                 'duration_minutes': option['duration_minutes'],
                                 'option_id':option.get('option_id'),
                                 'provisional':bool(jobs[key].get('balance_provisional') or option.get('provisional'))}
                    states[key] = 'scheduled'
                    break
        proposed = {'bars': bars, 'states': states, 'origin': 'CP-SAT'}
        annotate_provisional(jobs, bars)
        checked = validate(snapshot, proposed)
        if not checked['valid']:
            return best, {'status': 'resultado rejeitado pelo validador',
                          'errors': checked['errors'], 'stages': statuses,
                          'seconds': round(time.monotonic()-started, 3)}
        proposed['score'] = checked['score']
        proposed['coverage'] = checked['coverage']
        if proposed['score'] <= best['score']:
            best = proposed
        model.Add(expression == solver.Value(expression))
    return best, {'status': statuses[-1] if statuses else 'sem tempo para otimizar',
                  'stages': statuses, 'optimal': best.get('coverage') == 'complete'
                  and len(statuses) == len(objectives) and all(s == 'OPTIMAL' for s in statuses),
                  'seconds': round(time.monotonic()-started, 3)}
