"""Coverage, actionable gaps and time-separated evaluation from explicit evidence."""
from collections import Counter, defaultdict
from datetime import date, timedelta
import math
import statistics


def quantile(values, p):
    values = sorted(values)
    if not values:
        return None
    at = (len(values) - 1) * p
    lo, hi = math.floor(at), math.ceil(at)
    return values[lo] + (values[hi] - values[lo]) * (at - lo)


def cohort_statistics(cohorts):
    """Accepted complete time/volume cohorts, never arbitrary per-piece sheet hours."""
    valid = [c for c in cohorts if c.get('hours', 0) > 0 and c.get('volume', 0) > 0]
    values = [c['volume'] / c['hours'] for c in valid]
    return {'sample_size': len(valid), 'excluded': len(cohorts) - len(valid),
            'rate': sum(c['volume'] for c in valid) / sum(c['hours'] for c in valid) if valid else None,
            'p25': quantile(values, .25), 'median': quantile(values, .5), 'p75': quantile(values, .75),
            'start': min((c.get('start_date') for c in valid if c.get('start_date')), default=None),
            'end': max((c.get('end_date') for c in valid if c.get('end_date')), default=None)}


def temporal_evaluation(cohorts, cutoff):
    """All records of a held-out OF stay out of training; unknown dates/OFs excluded."""
    cutoff = date.fromisoformat(str(cutoff))
    usable, excluded = [], []
    for c in cohorts:
        try:
            low, high = date.fromisoformat(c['start_date']), date.fromisoformat(c['end_date'])
            if low > high or not c.get('orders') or c.get('hours', 0) <= 0 or c.get('volume', 0) <= 0:
                raise ValueError()
            usable.append((c, low, high))
        except (ValueError, TypeError, KeyError):
            excluded.append(c.get('key'))
    held_out = {of for c, low, _ in usable if low > cutoff for of in c['orders']}
    train = [c for c, _, high in usable if high <= cutoff and not held_out.intersection(c['orders'])]
    test = [c for c, low, _ in usable if low > cutoff]
    # Units and operation scopes must match; a rate cannot cross units or processes.
    groups = defaultdict(list)
    for c in train:
        groups[(c.get('resource_id'), c.get('operation'), c.get('unit'))].append(c)
    errors = []
    for c in test:
        history = groups.get((c.get('resource_id'), c.get('operation'), c.get('unit')), [])
        rate = cohort_statistics(history)['rate']
        if rate:
            errors.append({'key': c.get('key'), 'observed_hours': c['hours'], 'predicted_hours': c['volume'] / rate})
    return {'cutoff': str(cutoff), 'training_cohorts': len(train), 'test_cohorts': len(test),
            'evaluated': len(errors), 'excluded': excluded, 'orders_held_out': sorted(held_out),
            'mae_hours': statistics.mean(abs(e['observed_hours'] - e['predicted_hours']) for e in errors) if errors else None,
            'bias_hours': statistics.mean(e['predicted_hours'] - e['observed_hours'] for e in errors) if errors else None,
            'errors': errors}


def build(snapshot):
    coverage = Counter(); groups = defaultdict(list); gaps = defaultdict(list)
    for op in snapshot['operations']:
        assignment = op.get('assignment') or {}
        coverage[op['state']] += 1
        coverage['with_machine'] += bool(assignment.get('resource_id'))
        coverage['conditional_machine'] += assignment.get('eligibility') == 'conditional'
        coverage['unknown_balance'] += op.get('planning_remaining') is None
        technical = op.get('technical', {})
        groups[(op.get('area', 'perfis'), assignment.get('resource_id'), op['operation'],
                technical.get('profile'), technical.get('grade'))].append(op)
        for reason in op.get('blocking_reasons', []):
            gaps[reason].append(op)
    summaries = []
    for (area, resource, operation, profile, grade), ops in groups.items():
        durations = [o.get('source_duration', {}).get('hours') for o in ops]
        known = [h for h in durations if isinstance(h, (int, float)) and h > 0]
        summaries.append({'area': area, 'resource_id': resource, 'operation': operation,
                          'profile': profile, 'grade': grade, 'operations': len(ops),
                          'known_balances': sum(o['planning_remaining'] is not None for o in ops),
                          'estimated_hours': sum(known), 'unknown_durations': len(ops) - len(known),
                          'duration_p25': quantile(known, .25), 'duration_median': quantile(known, .5),
                          'duration_p75': quantile(known, .75), 'kind': 'estimativas_de_carga'})
    queue = []
    for reason, ops in gaps.items():
        queue.append({'reason': reason, 'operations': len(ops), 'orders': len({o['of'] for o in ops}),
                      'urgent': sum(o['priority_group'] == 0 for o in ops),
                      'known_remaining': sum(o['planning_remaining'] or 0 for o in ops),
                      'unknown_balances': sum(o['planning_remaining'] is None for o in ops),
                      'examples': [o['key'] for o in sorted(ops, key=lambda o: (o['priority_group'], o.get('deadline') or '9999', o['key']))[:10]],
                      'resolution_url': '/planeamento/setor/carga' if 'Calendário' in reason else '/planeamento/setor/definicoes' if 'Duração' in reason or 'Compatibilidade' in reason else '/planeamento/raw'})
    queue.sort(key=lambda g: (-g['urgent'], -g['known_remaining'], -g['operations'], g['reason']))
    observed=[]
    historical = snapshot.get('historical_evidence',{})
    for digest,evidence in historical.items():
        # Máquina e operação guardadas com a evidência (auditoria 06/10, GT-08); nos retratos antigos,
        # inferidas das durações (opções e candidatas) que a usaram.
        scopes={(o['resource_id'],op['operation']) for op in snapshot['operations']
                for o in [*op.get('options',[]),*(d for c in op.get('candidates',[]) for d in c.get('durations') or [])]
                if o.get('history_hash')==digest}
        resource,operation = next(iter(scopes)) if len(scopes)==1 else (None,None)
        if evidence.get('scope_resource_id') or evidence.get('scope_operation'):
            resource,operation = evidence.get('scope_resource_id') or resource, evidence.get('scope_operation') or operation
        cohorts=[{**c,'resource_id':resource,'operation':operation,'unit':evidence.get('unit')} for c in evidence.get('cohorts',[])]
        period = evidence.get('window',{})
        cutoff = (date.fromisoformat(period['end'])-timedelta(days=max(1,period.get('days',90)//3))).isoformat() if period.get('end') else None
        observed.append({'digest':digest,'resource_id':resource,'machine':evidence.get('scope_machine'),'operation':operation,'unit':evidence.get('unit'),
            'kind':'produtividade_observada','scope':evidence.get('scope'),**cohort_statistics(cohorts),
            'excluded_cohorts':len(evidence.get('excluded',[])), 'exclusion_reasons':dict(Counter(reason for c in evidence.get('excluded',[]) for reason in c.get('reasons',[]))),
            'temporal_evaluation':temporal_evaluation(cohorts,cutoff) if cutoff else None})
    return {'coverage': dict(coverage), 'groups': summaries, 'resolution_queue': queue, 'observed_productivity':observed,
            'source_status': snapshot.get('source_status'),
            'possible_duplicates': len(snapshot.get('possible_duplicates', [])),
            'limitations': ['Quantis de duração descrevem estimativas de carga; produtividade observada exige horas e produção correspondentes.',
                            'Pendências sobrepõem-se; os seus totais não se somam como trabalho distinto.']}
