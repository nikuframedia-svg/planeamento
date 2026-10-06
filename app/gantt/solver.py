"""CP-SAT flexible job shop over machine-specific working-minute axes."""
from __future__ import annotations

import time
from collections import defaultdict

from ortools.sat.python import cp_model

from .calendar import option_windows, working_offset
from .contracts import SOLVER_SECONDS, minute, predecessors
from .validation import validate, order_scoped, milestone_orders
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
    shared_intervals = defaultdict(list)
    shared_demands = defaultdict(list)
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
            if option.get('eligibility', 'admissible') != 'admissible':
                continue
            resource = option['resource_id']
            available = option_windows(snapshot, option)
            total = sum(high-low for low, high in available)
            duration = option['duration_minutes']
            if not available or duration > total:
                continue
            chosen = model.NewBoolVar(f'use:{key}:{index}')
            start_work = model.NewIntVar(0, total-duration, f'ws:{key}:{index}')
            end_work = model.NewIntVar(duration, total, f'we:{key}:{index}')
            model.Add(end_work == start_work + duration).OnlyEnforceIf(chosen)
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
                # Clip execution to each actual working window. Shared pools and
                # machines use these absolute segments, including calendar pauses.
                seg_start = model.NewIntVar(0, horizon, f'ss:{key}:{index}:{window_index}')
                seg_stop = model.NewIntVar(0, horizon, f'se:{key}:{index}:{window_index}')
                delta = model.NewIntVar(-horizon, horizon, f'sd:{key}:{index}:{window_index}')
                seg_size = model.NewIntVar(0, size, f'sz:{key}:{index}:{window_index}')
                seg_end = model.NewIntVar(0, horizon + size, f'send:{key}:{index}:{window_index}')
                present = model.NewBoolVar(f'sp:{key}:{index}:{window_index}')
                model.AddMaxEquality(seg_start, [starts[key], low])
                model.AddMinEquality(seg_stop, [ends[key], high])
                model.Add(delta == seg_stop - seg_start)
                model.AddMaxEquality(seg_size, [delta, 0])
                model.Add(seg_end == seg_start + seg_size)
                model.AddImplication(present, chosen)
                model.Add(seg_size >= 1).OnlyEnforceIf(present)
                model.Add(seg_size == 0).OnlyEnforceIf([chosen, present.Not()])
                interval = model.NewOptionalIntervalVar(seg_start, seg_size, seg_end,
                                                         present, f'wall:{key}:{index}:{window_index}')
                machine_intervals[resource].append(interval)
                for pool, demand in option.get('shared_demands', {}).items():
                    shared_intervals[pool].append(interval)
                    shared_demands[pool].append(demand)
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
        if job.get('deadline') and not order_scoped(job):
            due = minute(job['deadline'], snapshot['started_at'])
            late = model.NewIntVar(0, max(horizon, horizon-due), 'late:' + key)
            model.Add(late >= ends[key] - due).OnlyEnforceIf(placed)
            model.Add(late == 0).OnlyEnforceIf(placed.Not())
            lateness[key] = late
    for resource, intervals in machine_intervals.items():
        model.AddNoOverlap(intervals)
    for pool, intervals in shared_intervals.items():
        model.AddCumulative(intervals, shared_demands[pool], snapshot['resources'][pool].get('capacity', 1))
    for job in ready:
        for prior in predecessors(job):
            if prior in placements:
                model.Add(placements[job['key']][0] <= placements[prior][0])
                model.Add(starts[job['key']] >= ends[prior]).OnlyEnforceIf(placements[job['key']][0])
            elif jobs.get(prior, {}).get('state') != 'complete':
                model.Add(placements[job['key']][0] == 0)

    # Order-scoped milestones (Picking): the whole OF of that sector must be ready.
    # Operation-scoped ones (Data Corte) already have their own lateness above.
    milestone_lateness = []
    for area, of, keys, required in milestone_orders(snapshot, jobs, [key for key in by_group[1] if order_scoped(jobs[key])]):
        if not all(key in placements for key in required):
            continue
        label = f'{area}:{of}'
        all_placed = model.NewBoolVar('of-ready:' + label)
        model.Add(sum(placements[key][0] for key in required) == len(required)).OnlyEnforceIf(all_placed)
        model.Add(sum(placements[key][0] for key in required) <= len(required)-1).OnlyEnforceIf(all_placed.Not())
        finished = model.NewIntVar(0, horizon, 'of-end:' + label)
        model.AddMaxEquality(finished, [ends[key] for key in required])
        due = min(minute(jobs[key]['deadline'], snapshot['started_at']) for key in keys)
        late = model.NewIntVar(0, max(horizon,horizon-due), 'of-late:' + label)
        model.Add(late >= finished - due).OnlyEnforceIf(all_placed)
        model.Add(late == 0).OnlyEnforceIf(all_placed.Not())
        milestone_lateness.append(late)

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
    for key,(_,choices) in placements.items():
        current=jobs[key].get('source_resource_id')
        if key not in (snapshot.get('accepted_bars') or {}) and current and any(resource==current for _,resource,*_ in choices):
            moves.extend(480*chosen for chosen,resource,*_ in choices if resource!=current)
    model.AddMaxEquality(makespan, list(ends.values()))
    objectives = []
    for group in range(3):
        objectives.append(sum(1-placements[key][0] for key in by_group[group]))
        objectives.append((sum(milestone_lateness) if group == 1 else 0) + sum(lateness[key] for key in by_group[group] if key in lateness))
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
            selected = bool(bar and resource == bar['resource_id'] and
                            (bar.get('option_id') == option.get('option_id') if bar.get('option_id')
                             else bar.get('duration_minutes') == option['duration_minutes']))
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
                    for low, high in option_windows(snapshot, option):
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
