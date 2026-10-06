"""Whole-lot weekly simulation, retaining units and conditional dependencies."""
from collections import defaultdict
from datetime import date, timedelta
from zoneinfo import ZoneInfo
from datetime import datetime, time
from .contracts import utc, predecessors


def plan_charge(unit, hours, quantity, length):
    """Charge of the whole lot in the budget's own unit; None when the units are incompatible."""
    if unit == 'hours':
        return hours
    if unit in ('metros', 'metres') and length:
        return quantity * length / 1000
    return None


def _reserve(budgets, rid, earliest, hours, quantity, length, demands):
    """Consecutive weeks of one resource and unit that together hold the lot.

    The earliest week is tried first, whatever the budget unit. A gap week without budget, or a
    shared pool without room, breaks the chain: the lot is not split across non-consecutive weeks
    (dividing a lot is a different, explicit decision).
    """
    by_unit = {}
    for (resource, week, unit), available in budgets.items():
        if resource == rid and week + timedelta(days=7) > earliest:
            by_unit.setdefault(unit, {})[week] = available
    for first, unit in sorted((week, unit) for unit, weeks in by_unit.items() for week in weeks):
        charge = plan_charge(unit, hours, quantity, length)
        if charge is None or charge <= 0:
            continue
        weeks, portions, left, week = by_unit[unit], [], charge, first
        while left > 1e-9 and week in weeks:
            room = weeks[week]
            if hours is not None:
                for p, demand in demands.items():
                    pool = budgets.get((p, week, 'hours'))
                    if p != rid and pool is not None and hours * demand > 0:
                        # The pool limits the share of this lot that can run this week.
                        room = min(room, pool / (hours * demand) * charge)
            take = min(room, left)
            if take <= 1e-9:
                break
            portions.append((week, take))
            left -= take
            week += timedelta(days=7)
        if left <= 1e-9:
            return unit, portions
    return None


def build(snapshot):
    start = utc(snapshot['started_at']).astimezone(ZoneInfo('Europe/Lisbon')).date()
    end = start + timedelta(minutes=snapshot['horizon_minutes'])
    budgets = {}; allocations = []; pending = []; finished = {}
    for b in snapshot.get('weekly_availability', []):
        if b.get('status') != 'confirmed':
            continue
        week = date.fromisocalendar(b['year'], b['week'], 1)
        # Whole-week documentary budgets cannot supply remaining hours in a
        # partially elapsed week. A confirmed hourly calendar can.
        resource = snapshot['resources'].get(b['resource_id'], {})
        amount = b.get('hours') if b.get('hours') is not None else b.get('capacity')
        unit = 'hours' if b.get('hours') is not None else b.get('unit')
        if amount is None or week >= end or week + timedelta(days=7) <= start:
            continue
        if week < start and not resource.get('windows'):
            continue
        if resource.get('windows') and unit == 'hours':
            lo = max(utc(snapshot['started_at']), utc(datetime.combine(week,time.min,ZoneInfo('Europe/Lisbon')).isoformat()))
            hi = utc(datetime.combine(week+timedelta(days=7),time.min,ZoneInfo('Europe/Lisbon')).isoformat())
            amount = sum(max(0, (min(utc(w['end']), hi) - max(utc(w['start']), lo)).total_seconds()) / 3600 for w in resource['windows'])
        budgets[(b['resource_id'], week, unit)] = max(0, amount) * resource.get('capacity',1)
    jobs = {o['key']: o for o in snapshot['operations']}
    remaining = {k for k, o in jobs.items() if o['state'] != 'complete'}
    for _ in range(len(remaining) + 1):
        progressed = False
        for key in sorted(remaining, key=lambda k: (jobs[k]['priority_group'], jobs[k].get('deadline') or '9999', k)):
            op = jobs[key]; before = predecessors(op)
            if any(p in remaining for p in before):
                continue
            remaining.remove(key); progressed = True
            if any(reason in ('Trabalho excluído da seleção.', 'Operação fora da seleção do cenário.', 'Escolha manual contradiz trabalho iniciado.') for reason in op.get('blocking_reasons', [])):
                pending.append({'key':key,'reason':'Operação excluída ou escolha incompatível.'}); continue
            q = op.get('planning_remaining'); assignment = op.get('assignment') or {}
            rid = assignment.get('resource_id'); hours = op.get('source_duration', {}).get('hours')
            length = op.get('technical', {}).get('length_mm')
            if q is None or not rid:
                pending.append({'key': key, 'reason': 'Saldo ou máquina por confirmar.'}); continue
            if any(jobs.get(p, {}).get('state') != 'complete' and p not in finished for p in before):
                pending.append({'key': key, 'reason': 'Operação anterior sem previsão semanal.'}); continue
            earliest = max([start] + [finished[p] for p in before if p in finished])
            demands = snapshot['resources'].get(rid, {}).get('shared_demands', {})
            plan = _reserve(budgets, rid, earliest, hours, q, length, demands)
            if not plan:
                pending.append({'key': key, 'reason': 'Sem orçamento compatível ou lote sem encaixe no horizonte.'}); continue
            unit, portions = plan
            pool_keys = {(p, week, 'hours') for p in demands if p != rid for week, _ in portions}
            for week, portion in portions:
                budgets[(rid, week, unit)] -= portion
                if hours is not None:
                    share = portion / plan_charge(unit, hours, q, length)
                    for p in demands:
                        if p != rid and (p, week, 'hours') in budgets:
                            budgets[(p, week, 'hours')] -= hours * share * demands[p]
            # One lot keeps its identity across weeks; it is finished only after the last one.
            finished[key] = portions[-1][0] + timedelta(days=7)
            for index, (week, portion) in enumerate(portions):
                allocations.append({'key': key, 'resource_id': rid, 'start_date': week.isoformat(),
                                    'end_date_exclusive': (week + timedelta(days=7)).isoformat(),
                                    'charge': portion, 'unit': unit, 'quantity': q,
                                    'segment': index + 1, 'segments': len(portions),
                                    'lot_charge': plan_charge(unit, hours, q, length),
                                    'provisional': True, 'conditions': list(assignment.get('conditions', [])) +
                                      (['Orçamento dos recursos partilhados por confirmar.'] if any(p not in budgets for p in pool_keys) else []) +
                                      (['Sequência dentro da semana e operadores por validar.'] if before or snapshot['resources'][rid].get('shared_demands') else []) +
                                      (['Lote inteiro em semanas consecutivas; conclusão só na última.'] if len(portions) > 1 else [])})
        if not progressed:
            break
    pending += [{'key': k, 'reason': 'Ciclo ou dependência desconhecida.'} for k in sorted(remaining)]
    return {'allocations': allocations, 'pending': pending,
            'semantics': 'Simulação semanal por lotes inteiros e unidades explícitas; não define hora de execução.'}
