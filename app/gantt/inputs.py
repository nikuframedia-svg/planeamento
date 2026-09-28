"""Build a complete immutable Perfis scheduling input from published generations."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
import math

from .. import planning, planning_needs as needs, planning_population, planning_estimates, planning_dates, planning_calendars
from ..planning_calculations import abocardar, quantity
from ..raw import query
from .contracts import HORIZON_WEEKS, utc, minute
from . import source_plan


CONFIG_KINDS = ('resource', 'calendar', 'rate')


def effective_digest(snapshot):
    """Scheduling inputs only; stock, workbook epoch and display keys are excluded."""
    fields = ('of','operation','technical_signature','quantity_required',
              'reconciled_remaining','planning_remaining','balance_origin','provisional',
              'observations','options','state','blocking_reasons','priority_group',
              'deadline','milestones','source_machine','source_duration','source_resource_id')
    jobs = [{field:op.get(field) for field in fields} |
            {'has_predecessor':bool(op.get('predecessor_key'))}
            for op in snapshot['operations']]
    jobs.sort(key=needs.digest)
    physical = {rid:{'windows':resource['windows'],'operations':resource['operations']}
                for rid,resource in snapshot['resources'].items()}
    return needs.digest({'jobs':jobs,'physical':physical,
                         'horizon_minutes':snapshot['horizon_minutes'],
                         'started_at':snapshot['started_at'],
                         'weekly_availability':snapshot.get('weekly_availability',[])})


def reconcile_pins(operations, incoming_pins, bindings):
    """Transfer only unique same-OF, same-operation, same-geometry decisions."""
    by_key = {item['key']:item for item in operations}
    pins = {}
    transfers = {}
    orphaned = []
    for old_key,pin in incoming_pins.items():
        binding = bindings.get(old_key)
        direct = by_key.get(old_key)
        if direct and (not binding or direct['technical_signature']==binding.get('technical_signature')):
            target = direct
        elif binding:
            candidates = [candidate for candidate in operations
                if candidate['of']==binding['of'] and candidate['operation']==binding['operation']
                and candidate['technical_signature']==binding['technical_signature']]
            aliases = set(binding.get('selection_aliases') or []) | {binding.get('planning_key')}
            aliased = [candidate for candidate in candidates if candidate['planning_key'] in aliases
                       or aliases.intersection(candidate.get('selection_aliases') or [])]
            target = aliased[0] if len(aliased)==1 else candidates[0] if not aliased and len(candidates)==1 else None
        else:
            target = None
        if not target or target['state']!='ready' or target['key'] in pins:
            orphaned.append(old_key)
            continue
        pins[target['key']] = pin
        if target['key']!=old_key:
            transfers[old_key]=target['key']
    return pins,transfers,sorted(orphaned)


def references(conn):
    planning_gen = query.generation(conn, 'perfis')
    try:
        capacity_gen = query.generation(conn, 'perfis', dataset='capacity')
    except planning.PlanningError as exc:
        if exc.status != 503:
            raise
        capacity_gen = None
    configs = conn.execute("SELECT id,kind,revision,definition,name,area FROM planning_mtg.raw_objects WHERE kind=ANY(%s) AND NOT archived ORDER BY id",(list(CONFIG_KINDS),)).fetchall()
    return {'planning_generation': planning_gen['id'],
            'capacity_generation': capacity_gen['id'] if capacity_gen else None,
            'configuration_digest': needs.digest(needs.serial(configs)),
            'sources_pending': bool(planning_gen['metadata'].get('aggregates_pending') or planning_gen['metadata'].get('source_refresh_pending'))}


def _forecast_deadline(raw):
    if not raw:
        return None
    try:
        day = date.fromisoformat(str(raw)[:10]) + timedelta(days=1)
    except ValueError:
        return None
    return datetime.combine(day, time.min, ZoneInfo('Europe/Lisbon')).astimezone(timezone.utc).isoformat()


def _rate_bounds(applied):
    rate = (applied or {}).get('rate') or {}
    def bound(value, after=False):
        if not value:
            return None
        day = date.fromisoformat(str(value)[:10]) + (timedelta(days=1) if after else timedelta())
        return datetime.combine(day, time.min, ZoneInfo('Europe/Lisbon')).astimezone(timezone.utc).isoformat()
    return bound(rate.get('valid_from')), bound(rate.get('valid_until'), True)


def _option(resource_id, estimate, origin, started_at):
    hours = estimate.get('hours') if estimate else None
    if not isinstance(hours, (int, float)) or not math.isfinite(hours) or hours <= 0:
        return None
    earliest, latest = _rate_bounds(estimate)
    if earliest and utc(earliest) >= utc(started_at):
        earliest_minute = math.ceil((utc(earliest)-utc(started_at)).total_seconds()/60)
    else:
        earliest_minute = 0
    latest_minute = math.floor((utc(latest)-utc(started_at)).total_seconds()/60) if latest else None
    duration=max(1, math.ceil(hours * 60))
    return {'option_id':needs.digest([resource_id,origin,estimate.get('rate'),duration,
                                      earliest,latest]),
            'resource_id': resource_id, 'duration_minutes': duration,
            'duration_hours': hours, 'duration_origin': origin,
            'quantity': estimate.get('quantity'),
            'rate_source': estimate.get('source'), 'rate': estimate.get('rate'),
            'provisional': estimate.get('source') != 'Manual',
            'valid_from': earliest, 'valid_until': latest,
            'earliest_minute': earliest_minute, 'latest_minute': latest_minute}


def capture(conn, definition, started_at, *, expected_references=None):
    refs = references(conn)
    if expected_references and refs != expected_references:
        raise planning.PlanningError('As fontes mudaram antes do cálculo. Volta a gerar a proposta.',409)
    if refs['sources_pending']:
        raise planning.PlanningError('Aguarda a atualização dos cálculos publicados.',409)
    start = utc(started_at).replace(second=0,microsecond=0)
    weeks = int(definition.get('horizon_weeks', HORIZON_WEEKS))
    horizon_minutes = weeks * 7 * 24 * 60
    end = start + timedelta(minutes=horizon_minutes)
    configs = conn.execute("SELECT * FROM planning_mtg.raw_objects WHERE kind=ANY(%s) AND NOT archived ORDER BY id",(list(CONFIG_KINDS),)).fetchall()
    resources = {}
    aliases = {}
    for resource in configs:
        if resource['kind'] != 'resource' or not resource['definition'].get('confirmed'):
            continue
        rid = str(resource['id'])
        resources[rid] = {'name': resource['name'], 'operations': resource['definition']['operations'],
                          'windows': [], 'calendar_status': 'unknown',
                          'aliases': resource['definition'].get('aliases') or []}
        for alias in resources[rid]['aliases']:
            if alias.get('area') == 'perfis':
                aliases[alias['name']] = rid
    # An unambiguous configured resource name also identifies its imported machine.
    for rid, resource in resources.items():
        name = resource['name']
        if sum(r['name'] == name for r in resources.values()) == 1:
            aliases.setdefault(name, rid)
    for row in configs:
        if row['kind'] != 'calendar' or not row['definition'].get('confirmed'):
            continue
        d = row['definition'];rid = str(d['resource_id'])
        if rid in resources and 'weekly_windows' in d:
            resources[rid]['windows'].extend(planning_calendars.expand(d))
            resources[rid]['calendar_status'] = 'closed'
    for resource in resources.values():
        resource['windows'] = sorted({(x['start'],x['end']) for x in resource['windows']
                                     if utc(x['end']) > start and utc(x['start']) < end})
        resource['windows'] = [{'start': low, 'end': high} for low, high in resource['windows']]
        if resource['windows']:
            resource['calendar_status'] = 'available'
    gen = query.generation(conn, 'perfis', refs['planning_generation'])
    base,args = query.source(gen)
    rows = conn.execute('SELECT m.row_key,c.detail,c.values_json'+base+' AND '+planning_population.active_sql()+' ORDER BY m.row_key',args).fetchall()
    operations = []
    orders = defaultdict(list)
    manual_years = definition.get('picking_year_by_of') or {}
    manual_deadlines = definition.get('picking_deadline_by_of') or {}
    urgencies = set(definition.get('urgent') or [])
    alternatives = definition.get('alternatives') or {}
    for record in rows:
        row = {**record['detail'],'key':record['row_key'],'values':record['values_json']}
        row.setdefault('area','perfis')
        v = row['values'];of = v.get('of') or 'Sem OF:' + str(row['key'])
        mark = abocardar(v.get('abocardar'))
        op_names = ['corte'] + (['abocardar'] if mark is not False else [])
        estimators = {e['operation']: e for e in row.get('calculation',{}).get('operation_estimates') or []}
        preparations = {p.get('values_json',{}).get('operation'):p.get('values_json',{}) for p in row.get('preparations') or []}
        picking = (planning_dates.picking_deadline(v.get('picking_week'),manual_years.get(of) or v.get('picking_year'))
                   if not v.get('picking_conflict') else None)
        picking_at = manual_deadlines.get(of) or (picking['at'] if picking else None)
        if picking_at:
            picking_at = utc(picking_at).isoformat()
        for op in op_names:
            key = str(row['key']) + ':' + op
            balance = planning_estimates.select_balance(row,op)
            remaining = balance['planning_remaining']
            estimate = estimators.get(op)
            operation_values = preparations.get(op) or {}
            machine = operation_values.get('machine') if op == 'abocardar' else operation_values.get('machine') or v.get('machine')
            if not machine and estimate:
                machine = estimate.get('machine')
            if str(machine or '').strip().casefold() in ('por definir','sem máquina','sem maquina'):
                machine = None
            machine = str(machine).strip() if machine else None
            resource_id = aliases.get(machine)
            if machine and resource_id is None:
                resource_id = source_plan.imported_resource_id(machine)
                resources.setdefault(resource_id, {'name':machine, 'operations':[],
                    'windows':[], 'calendar_status':'unknown', 'origin':'Planeamento',
                    'aliases':[{'area':'perfis','name':machine}]})
                if op not in resources[resource_id]['operations']:
                    resources[resource_id]['operations'].append(op)
                aliases[machine] = resource_id
            if resource_id and resources[resource_id].get('origin') == 'Planeamento':
                if op not in resources[resource_id]['operations']:
                    resources[resource_id]['operations'].append(op)
            reasons = list(balance['reasons']) if remaining is None else []
            period_values = planning_dates.operation_period_inputs(v, operation_values,
                                                                    area='perfis', operation=op)
            period_year, period_week, period_origin = planning_dates.period(
                period_values, area='perfis', operation=op)
            period_error = period_origin in ('Data prevista inválida.', 'Ano/semana explícitos inválidos.',
                                             'Data prevista e semana escolhida não coincidem.')
            if period_error:
                reasons.append(period_origin)
            target = period_values.get('expected_date') or period_values.get('cut_date')
            period_end = (planning_dates.period_deadline(period_year, period_week)
                          if period_year is not None and period_week is not None else None)
            if v.get('picking_conflict') and of not in manual_deadlines:
                reasons.append('Semanas de Picking contraditórias; confirmar prazo.')
            if v.get('picking_week') and not picking_at and not v.get('picking_conflict'):
                reasons.append('Ano/semana de Picking inválidos; confirmar prazo.')
            if op == 'abocardar' and mark is None:
                reasons.append('Necessidade de abocardar por confirmar.')
            if remaining is None:
                reasons.append('Saldo por confirmar.')
            options = []
            if remaining and not reasons:
                from ..raw.capacity import estimate as calculate_hours
                effective={**v,**{field:value for field,value in operation_values.items()
                                 if field not in needs.PIECE_FIELDS},'quantity_to_plan':remaining}
                primary=_option(resource_id,estimate,(estimate or {}).get('source'),start) if resource_id else None
                if primary and estimate.get('quantity')!=remaining:
                    primary=None
                candidates=[str(rid) for rid in alternatives.get(key,[])]
                if resource_id:
                    candidates.insert(0,resource_id)
                for rid in dict.fromkeys(candidates):
                    if rid not in resources or op not in resources[rid]['operations']:
                        continue
                    rates=[r['definition'] for r in configs if r['kind']=='rate' and r['definition'].get('confirmed')
                           and str(r['definition'].get('resource_id'))==rid
                           and r['definition'].get('area')=='perfis' and r['definition'].get('operation')==op
                           and all(not r['definition'].get(field) or r['definition'][field]==v.get(field)
                                   for field in ('material_type','profile'))]
                    spans=[]
                    for rate in rates:
                        low,high=_rate_bounds({'rate':rate})
                        left=max(0,math.ceil((utc(low)-start).total_seconds()/60)) if low else 0
                        right=min(horizon_minutes,math.floor((utc(high)-start).total_seconds()/60)) if high else horizon_minutes
                        if right<=left:
                            continue
                        spans.append((left,right))
                        hours,why=calculate_hours(effective,rate,op)
                        if why is None:
                            option=_option(rid,{'hours':hours,'quantity':remaining,'source':'Manual','rate':rate},'Manual',start)
                            if option:
                                options.append(option)
                    if rid==resource_id and primary:
                        if primary['rate_source']=='Manual' or not spans:
                            options.append(primary)
                        else:
                            # Lower-priority historical/Excel rates apply only where
                            # no confirmed manual rate is in force.
                            covered=sorted(spans);cursor=0
                            for left,right in [*covered,(horizon_minutes,horizon_minutes)]:
                                if left>cursor:
                                    fallback={**primary,'earliest_minute':cursor,'latest_minute':left}
                                    fallback['option_id']=needs.digest([primary['option_id'],cursor,left])
                                    options.append(fallback)
                                cursor=max(cursor,right)
                options=list({option['option_id']:option for option in options}.values())
                usable=[option for option in options if resources[option['resource_id']]['windows']
                        and (option['latest_minute'] is None or option['latest_minute']-option['earliest_minute']>=option['duration_minutes'])
                        and option['earliest_minute']<horizon_minutes]
                if not usable:
                    if not options:
                        reasons.append((f'{machine}: máquina indicada no planeamento; ligação ao Gantt por configurar.'
                                        if machine else 'Máquina da operação por indicar.') if not resource_id and not candidates else
                                       'Operação não autorizada nesta máquina.' if resource_id and op not in resources[resource_id]['operations'] else
                                       (estimate or {}).get('reason') or 'Duração por confirmar.')
                    elif all(not resources[option['resource_id']]['windows'] for option in options):
                        closed=any(resources[option['resource_id']]['calendar_status']=='closed' for option in options)
                        reasons.append('Calendário explicitamente encerrado.' if closed else 'Calendário horário por confirmar.')
                    else:
                        reasons.append('Taxa fora da vigência ou sem encaixe no horizonte.')
            deadline = (picking_at or (period_end if period_origin == 'Decisão local'
                                       else _forecast_deadline(target))) if not period_error else None
            priority = 0 if key in urgencies or of in urgencies else 1 if picking_at else 2
            source = next((s for s in row.get('calculation',{}).get('production_sources') or [] if s.get('operation')==op),{})
            state = 'complete' if remaining == 0 else 'blocked' if reasons else 'ready'
            operation = {'key':key,'planning_key':str(row['key']),'operation_id':op,'of':of,
                         'reference':v.get('component_ref'),'line':v.get('id'),
                         'source_machine':machine, 'source_resource_id':resource_id,
                         'source_duration':{'hours':(estimate or {}).get('hours'),
                                            'quantity':(estimate or {}).get('quantity'),
                                            'origin':(estimate or {}).get('source')},
                         'selection_aliases':row.get('selection_aliases') or [],
                         'technical_signature':needs.signature(v),'operation':op,
                         'quantity_required':quantity(v.get('quantity_required')),
                         'reconciled_remaining':balance['reconciled_remaining'],
                         'planning_remaining':remaining,'balance_origin':balance['balance_origin'],
                         'balance_provisional':balance['provisional'],
                         'provisional':balance['provisional'] or any(x['provisional'] for x in options),
                         'evidence':balance['evidence'],'observations':source.get('records') or [],
                         'options':options,'state':state,'blocking_reasons':list(dict.fromkeys(reasons)),
                         'predecessor_key':str(row['key'])+':corte' if op=='abocardar' else None,
                         'priority_group':priority,'deadline':deadline,
                         'milestones':{'operation_forecast':target,'cut_date':v.get('cut_date'),
                                       'period_year':period_year,'period_week':period_week,
                                       'period_origin':period_origin,
                                       'period_deadline':period_end if period_origin == 'Decisão local' else None,
                                       'picking':picking_at,'picking_provisional':bool(picking and picking['provisional'] and not manual_deadlines.get(of)),
                                       'planned_start_date':v.get('planned_start_date'),
                                       'planned_finish_date':v.get('planned_finish_date'),
                                       'delivery_date':v.get('delivery_date')}}
            operations.append(operation)
            orders[of].append(key)
    pins,transfers,orphaned = reconcile_pins(operations, definition.get('pins') or {},
                                             definition.get('pin_bindings') or {})
    return needs.serial({'area':'perfis','started_at':start.isoformat(),'horizon_minutes':horizon_minutes,
                         'source_references':refs,'resources':resources,'operations':operations,
                         'weekly_availability':source_plan.availability(conn,gen,configs,aliases),
                         'orders':dict(orders),'pins':pins,'pin_transfers':transfers,
                         'orphaned_pins':sorted(orphaned),
                         'accepted_bars':definition.get('accepted_bars') or {}})
