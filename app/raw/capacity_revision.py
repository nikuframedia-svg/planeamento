"""Capacity with complete populations, workbook evidence and explicit weekly identity."""
from __future__ import annotations
from collections import defaultdict
from datetime import date, datetime
from zoneinfo import ZoneInfo
import re
from psycopg.types.json import Jsonb, set_json_loads, set_json_dumps
from pydantic_core import from_json, to_json
from .. import planning, planning_needs as needs, planning_raw as raw, planning_catalogs as catalogs, planning_dates, planning_calendars
from . import query, projection, objects, workbooks

CONTRACT = 'capacity-20260925-integral-v28'
NON_PHYSICAL = {'', 'sem máquina', 'mtg3', 'subcontrato', 'abocardar', 'serrote mtg2', 'serrote mtg3'}


def number(v):
    return raw.number(v)


def valid_quantity(v):
    v=number(v)
    return v if v is not None and v >= 0 and v.is_integer() else None


def cell(row, col):
    return row.get('cells', {}).get(col, {}).get('value')


def validate_period(c, area, id, d):
    try:
        year=int(d['year']); week=int(d['week']); date.fromisocalendar(year,week,1)
    except (ValueError,TypeError,KeyError): raise planning.PlanningError('Indica semana e ano ISO válidos.')
    snap=planning.snapshot(c,area)
    if d.get('snapshot')!=snap['snapshot_id']: raise planning.PlanningError('A macro mudou. Confirma o ano na versão atual.',409)
    if not str(d.get('reason') or '').strip(): raise planning.PlanningError('Indica o motivo da associação ao ano.')
    for x in c.execute("SELECT id,definition FROM planning_mtg.raw_objects WHERE kind='period' AND area=%s AND NOT archived AND id<>%s",(area,id)).fetchall():
        if x['definition'].get('snapshot')==d['snapshot'] and x['definition'].get('week')==week:
            raise planning.PlanningError('Já existe uma confirmação para esta semana e versão. Edita-a.',409)
    return {**d,'year':year,'week':week,'confirmed':True}


def period(v, area, snapshot, periods):
    y,w,origin=planning_dates.period(v,area=area,operation=v.get('operation') or ('corte' if area=='perfis' else ''),cantoneiras_week=number(v.get('imported_week')))
    if y is not None or (area=='perfis' and origin!='Por calendarizar'):
        return y,w,origin
    if area=='cantoneiras':
        w=number(v.get('imported_week'))
        if w is not None and w.is_integer() and 1<=w<=53:
            found=[r for r in periods if r['area']==area and r['definition'].get('snapshot')==snapshot and r['definition'].get('week')==w]
            if len(found)==1:return found[0]['definition']['year'],int(w),'Ano confirmado para W desta versão'
            return None,int(w),'Semana W importada — ano por confirmar'
    return y,w,origin


def workbook_index(sources):
    calendars=defaultdict(list); rates={}; summaries=defaultdict(dict)
    for area,src in sources.items():
        sheets=src['sheets'];snapshot=src['snapshot_id']
        for row in sheets.get('PlanDisponibilidadeSemanal',[]):
            if row['row']==1:continue
            y,w=number(cell(row,'C')),number(cell(row,'B'));machine=cell(row,'D')
            if not machine or y is None or w is None:continue
            try:date.fromisocalendar(int(y),int(w),1)
            except ValueError:continue
            turns,per=number(cell(row,'F')),number(cell(row,'G'))
            hours=turns*per if turns is not None and per is not None and turns>=0 and per>=0 else None
            calendars[(area,str(machine),int(y),int(w))].append({'hours':hours,'shifts':turns,'hours_per_shift':per,'source':{'snapshot':snapshot,'file':src.get('source_filename'),'sheet':'PlanDisponibilidadeSemanal','row':row['row']},'cells':row['cells']})
        for row in sheets.get('CapacidadeMáquinas',[]):
            if row['row']>12 or row['row']<2:continue
            machine=cell(row,'B')
            if not machine:continue
            rate=number(cell(row,'C'))
            rates[(area,machine)]={'value':rate if rate is not None and rate>0 else None,'unit':'mm²/h','source':{'snapshot':snapshot,'file':src.get('source_filename'),'sheet':'CapacidadeMáquinas','cell':'C'+str(row['row'])},'alternatives':{k:row['cells'].get(k) for k in ('E','F')},'cells':row['cells']}
            summaries[(area,machine)]={k:row['cells'].get(col) for k,col in [('area','J'),('hours','K'),('shifts','L'),('weight_t','M')]}
            formula=(row['cells'].get('L') or {}).get('formula') or ''
            divisor=re.search(r'/\s*(\d+(?:\.\d+)?)',formula)
            rates[(area,machine)]['shift_hours']=float(divisor[1]) if divisor and float(divisor[1])>0 else None
    return calendars,rates,summaries


def reference_estimate(v, area, q, rate):
    if q is None:return None,'Quantidade negativa, inválida ou por confirmar',1
    if q==0:return 0,None,1
    if area=='cantoneiras':
        length=number(v.get('length_mm'));speed=number(v.get('speed_m_h'))
        if length is None or length<=0 or speed is None or speed<=0:return None,'Comprimento ou velocidade por confirmar',1
        return q*length/1000/speed,None,1
    unit=number(v.get('section_unit'));speed=(rate or {}).get('value')
    if unit is None or unit<=0 or not speed:return None,'Área unitária ou taxa importada por confirmar',1
    factor=3 if v.get('machine')=='Serrote Fita Thomas IS639 Pav.1' and (number(v.get('quantity_required')) or 0)>50 else 1
    return q*unit/(speed*factor),None,factor


def summary(items, calendars, resource, year, week, rates, imported_summary=None):
    live=list(items);v={}
    def total(field):
        included=[r for r in live if r['values']['primary_operation']] if field in ('weight','pending_quantity','pending_metres','pending_area') else live
        vals=[r['values'].get(field) for r in included];known=[x for x in vals if x is not None]
        v[field]=sum(known) if len(known)==len(vals) else None
        return {'known':len(known),'total':len(vals),'sum_known':sum(known),'population':'peças' if field in ('weight','pending_quantity','pending_metres','pending_area') else 'operações'}
    cov={k:total(k) for k in ('planned_hours','reference_hours','weight','area_load','metres','quantity','pending_quantity','pending_metres','pending_area')}
    v['unknown_load']=len(live)-cov['planned_hours']['known'];v['lines_total']=len(live)
    v['draft_hours']=sum(r['values']['planned_hours'] or 0 for r in items if r['values']['draft'])
    v['draft_unknown']=sum(r['values']['planned_hours'] is None for r in items if r['values']['draft'])
    v['macro_hours']=sum(r['values'].get('macro_hours') or 0 for r in live) if live and all(r['values'].get('macro_hours') is not None for r in live) else None
    d=resource['definition'] if resource else {}; available=None; per=None;source_calendar=None
    confirmed=[x for x in calendars if x.get('local') and x.get('confirmed')]
    imported=[x for x in calendars if not x.get('local')]
    if len(confirmed)==1:
        cal=confirmed[0];available=cal['hours'];per=cal['hours_per_shift'];source_calendar=cal
    v.update(available_hours=available,free_hours=None,occupancy=None,reference_available_hours=imported[0]['hours'] if len(imported)==1 else None,
             reference_shifts=imported[0]['shifts'] if len(imported)==1 else None,reference_hours_per_shift=imported[0]['hours_per_shift'] if len(imported)==1 else None,
             equivalent_shifts=v['planned_hours']/per if per and v['planned_hours'] is not None else None,
             actual_hours=None,capacity_total=None,capacity_free=None)
    if available is not None and v['planned_hours'] is not None:
        v['free_hours']=available-v['planned_hours'];v['occupancy']=v['planned_hours']/available*100 if available>0 else None
    from .capacity import hourly_rate
    physical_rates=rates
    if live and any('applied_rate' in item for item in live):
        physical_rates=[{'definition':{**item['applied_rate']['rate'],'operation':item['values']['operation'],'confirmed':True}}
                        for item in live if (item.get('applied_rate') or {}).get('rate')]
        if len(physical_rates)!=len(live):physical_rates=[]
    normalized=[(r['definition'].get('operation'),hourly_rate(r['definition'])) for r in physical_rates if r['definition'].get('confirmed')]
    positive_rates={(op,physical[0],physical[1]) for op,physical in normalized if physical}
    unit=None
    if len(positive_rates)==1 and physical_rates and len(normalized)==len(physical_rates) and all(physical for _,physical in normalized):
        operation,unit,rate=next(iter(positive_rates))
        v['capacity_total']=available*rate if available is not None else None
        v['capacity_free']=v['free_hours']*rate if v['free_hours'] is not None else None
    reasons=[]
    if len(imported)>1 and not confirmed:reasons.append('Calendário duplicado: escolher uma origem ou registar a disponibilidade correta.')
    if not confirmed:reasons.append('Disponibilidade por confirmar.')
    if v['unknown_load']:reasons.append('Carga incompleta: faltam parâmetros ou existem divergências.')
    if v['free_hours'] is not None and v['free_hours']<0:reasons.append('Sobrecarga')
    if year is None:reasons.append('Ano por confirmar' if week else 'Por calendarizar')
    return {'values':v,'coverage':cov,'calendars':calendars,'calendar_conflict':len(imported)>1 and not confirmed,'source_calendar':source_calendar,
            'resource':resource,'rates':rates,'warnings':reasons,'capacity_unit':unit,'macro_summary':imported_summary or {},
            'actual_coverage':{'known':0,'total':0},'lines':[],'draft_lines':[]}


def resource_index(configs):
    resources={str(r['id']):needs.serial(r) for r in configs if r['kind']=='resource'}
    aliases={(alias['area'],alias['name']):ident for ident,r in resources.items()
             if r['definition'].get('confirmed') for alias in r['definition'].get('aliases',[])}
    return resources,aliases


def calculate(c,configs,sources,gens,*,today,scope=None,rows_override=None,persist=True,rate_context=None):
    """One capacity engine for published revisions and read-only what-if previews."""
    imported_cal,imported_rates,imported_totals=workbook_index(sources)
    from . import productivity
    from .. import planning_estimates
    rate_context=rate_context or productivity.Context(c,configs,rows_override=rows_override)
    resources,aliases=resource_index(configs)
    periods=[r for r in configs if r['kind']=='period'];rates=[needs.serial(r) for r in configs if r['kind']=='rate']
    def machine_key(area,name):return aliases.get((area,name)) or area+':'+str(name or 'Por definir')
    all_items=[];buckets={};machines={};historical_updates={}
    def ensure(area,name,y,w):
        mk=machine_key(area,name);key=f'{mk}|{y}|{w}'
        if key not in buckets:buckets[key]={'items':[],'calendar':[],'areas':set(),'mk':mk,'name':resources[mk]['name'] if mk in resources else name or 'Por definir','year':y,'week':w,'aliases':set()}
        buckets[key]['areas'].add(area);buckets[key]['aliases'].add((area,name));return key,buckets[key]
    for (area,name,y,w),rows in imported_cal.items():ensure(area,name,y,w)[1]['calendar'].extend(rows)
    for cal in configs:
        if cal['kind']!='calendar':continue
        d=cal['definition'];res=resources.get(d['resource_id'])
        if not res:continue
        for alias in res['definition'].get('aliases',[]):
            key,b=ensure(alias['area'],alias['name'],d['year'],d['week'])
            if not any(x.get('id')==str(cal['id']) for x in b['calendar']):b['calendar'].append({'id':str(cal['id']),'revision':cal['revision'],'local':True,'confirmed':bool(d.get('confirmed') and res['definition'].get('confirmed')),'hours':planning_calendars.available_hours(d),'hours_per_shift':d.get('hours_per_shift') or res['definition'].get('shift_hours'),'shifts':d.get('shifts'),'definition':d})
    if scope is not None:
        for area,ids in scope.get('reuse',{}).items():
            if not ids:continue
            prior=query.generation(c,area,dataset='capacity_items');base,args=query.source(prior)
            # Totals consume only the selected rate, not its full historical
            # evidence. Load that evidence later only for pieces whose derived
            # fields actually change. What-if previews retain the full detail.
            rate_sql="jsonb_build_object('rate',c.detail->'applied_rate'->'rate')" if persist else "c.detail->'applied_rate'"
            for row in c.execute("SELECT m.row_key,c.values_json,"+rate_sql+" applied_rate,c.detail->>'planning_key' planning_key,c.detail->>'raw_machine' raw_machine"+base+" AND m.row_key=ANY(%s)",args+[sorted(ids)]):
                v=row['values_json'];item={'key':row['row_key'],'values':v,'applied_rate':row['applied_rate'],
                    'planning_key':row['planning_key'],'raw_machine':row['raw_machine'],'_retained':True,'_rate_deferred':persist}
                # Shared resources expose the same item in both area datasets.
                if v['area']!=area:continue
                _,bucket=ensure(area,row['raw_machine'],v['year'],v['week'])
                bucket['items'].append(item);all_items.append(item)
    for area,gen in gens.items():
        base,args=query.source(gen,capacity_inputs=True)
        # Detoast each source once before extracting several fields. Keeping
        # compressed JSON in repeated expressions multiplies disk reads/decodes.
        rows=c.execute("SELECT c.values_json,c.detail"+base+
            (" AND m.row_key=ANY(%s)" if scope is not None else ""),
            args+([sorted(scope['keys'][area])] if scope is not None else [])).fetchall()
        for row in rows:row['raw']=row['detail'].pop('raw',{})
        if rows_override and area in rows_override:
            selected={row['detail']['key']:row for row in rows}
            for row in rows_override[area]:
                selected[row['key']]={'values_json':row['values'],'detail':{k:v for k,v in row.items() if k not in ('values','raw')},'raw':row.get('raw',{})}
            rows=list(selected.values())
        from .. import planning_population
        closed_rows=[]
        for row in rows:
            if not planning_population.includes({**row['detail'],'values':row['values_json'],'raw':row['raw']}):
                closed_rows.append({**row['detail'],'values':row['values_json'],'raw':row['raw']})
                continue
            v=row['values_json'];detail=row['detail'];original=row['raw'];closed=str(original.get('Fechado') or '').upper()=='X'
            preps=detail.get('preparations') or []
            if not preps and closed:continue
            ops=[({**r['values_json'],'_compatible':r.get('capacity_compatible',True)},r.get('record_status')=='draft',str(r.get('operation_id')),True) for r in preps]
            if not ops or (area=='perfis' and not any(x[0].get('operation')=='corte' for x in ops)):
                ops.append((v,False,v.get('operation') or ('corte' if area=='perfis' else 'por_confirmar'),False))
            extra='abocardar' if area=='perfis' and v.get('abocardar')=='X' else v.get('operation_detail') if area=='cantoneiras' else None
            if str(extra or '').isdigit() and str(extra)=='0':extra=None
            if extra and (str(extra).isdigit() or extra=='abocardar') and not any(o[0].get('operation')==extra for o in ops):
                ops.append(({'operation':str(extra),'quantity_to_plan':None,'machine':None,'expected_date':None,'planned_year':None,'planned_week':None},False,str(extra),False))
            seen=set()
            for local,draft,opid,is_local in ops:
                if opid in seen:continue
                seen.add(opid);vals={**v,**{k:x for k,x in local.items() if k not in needs.PIECE_FIELDS}};op=vals.get('operation');primary=op==v.get('operation') or (area=='perfis' and op=='corte')
                calculated_source=next((x for x in detail.get('calculation',{}).get('production_sources',[]) if x['operation']==str(op)),None)
                balance=planning_estimates.select_balance({**detail,'values':v,'raw':original},str(op)) if area=='perfis' and calculated_source is not None else None
                if balance is not None:q=valid_quantity(balance['planning_remaining'])
                elif calculated_source is not None:q=valid_quantity(calculated_source.get('remaining'))
                elif is_local:q=valid_quantity(vals.get('quantity_to_plan')) if local.get('_compatible') else None
                elif not primary:q=None
                elif area=='cantoneiras':q=valid_quantity(v.get('remaining'))
                else:q=valid_quantity(original.get('Quantidade Prevista'))
                if detail.get('calculation',{}).get('compatible') is False:q=None
                if not is_local and closed and primary:continue
                name=vals.get('machine')
                if scope is not None and machine_key(area,name) not in scope['machines']:continue
                y,w,period_source=period(vals,area,sources[area]['snapshot_id'],periods)
                bucket,b=ensure(area,name,y,w);mk=b['mk'];res=resources.get(mk)
                ref,ref_reason,factor=reference_estimate({**vals,'speed_m_h':number(original.get('Mt\\h'))} if area=='cantoneiras' else vals,area,q,imported_rates.get((area,name))) if primary else (None,'Operação adicional: quantidade e parâmetros próprios por confirmar',1)
                when=str(vals.get('expected_date') or '')[:10]
                if not when and y and w:when=str(date.fromisocalendar(y,w,1))
                if not when:when=str(today)
                effective={**vals,'quantity_to_plan':q}
                excel=None
                if primary:
                    imported=imported_rates.get((area,name))
                    excel={**imported,'method':'area_hour'} if area=='perfis' and imported else {'value':number(original.get('Mt\\h')) if 'Mt\\h' in original else number(vals.get('speed_m_h')),'method':'metres_hour','unit':'m/h','source':'Velocidade da macro'} if area=='cantoneiras' else None
                applied=rate_context.estimate(effective,area,str(op),when,excel=excel,as_of=min(today,date.fromisoformat(when)))
                hours,reason=applied['hours'],applied['reason']
                if q==0:hours,reason=0,None
                if is_local and not local.get('_compatible') and calculated_source is None:hours=None;reason='A preparação local exige revisão da quantidade ou da especificação técnica.'
                if res and op not in res['definition']['operations']:hours=None;reason='Operação não confirmada para este recurso.'
                from .capacity import estimate_rule
                applied={**applied,'hours':hours,'reason':reason}
                applied['calculation']=estimate_rule(effective,applied)
                length=number(vals.get('length_mm'));unit=number(vals.get('section_unit'));weight_unit=number(vals.get('weight_unit'))
                weight=weight_unit*q if weight_unit is not None and q is not None else number(vals.get('weight')) if primary else None
                if weight is not None and weight<0:weight=None
                pending=valid_quantity(v.get('remaining')) if primary else None
                item={'key':detail['key']+':'+opid,'values':{'of':v.get('of'),'component_ref':v.get('component_ref'),'machine':b['name'],'machine_key':mk,'bucket_key':bucket,'area':area,'operation':op,'week':w,'year':y,'quantity':q,'quantity_required':vals.get('quantity_required'),'pending_quantity':pending,'pending_metres':pending*length/1000 if pending is not None and length and length>0 else None,'pending_area':pending*unit if pending is not None and unit and unit>0 else None,'planned_hours':hours,'rate_source':applied['source'],'applied_rate_value':applied['rate'].get('value') if applied['rate'] else None,'reference_hours':ref,'macro_hours':number(original.get('Horas Consumidas' if area=='perfis' else 'h teor. Falta')) if primary else None,'weight':weight,'area_load':q*unit if q is not None and unit is not None and unit>0 else None,'metres':q*length/1000 if q is not None and length is not None and length>0 else None,'draft':draft,'primary_operation':primary,'status':v.get('status')},
                      'planning_key':detail['key'],'raw_machine':name,'aliases':detail.get('selection_aliases',[]),'technical_signature':needs.signature(vals),'plan_key':detail.get('plan_key'),'need_id':detail.get('need_id'),'operation_id':opid,'revision':detail.get('revision',0),'macro_closed':closed,'physical_status':'Não é uma máquina física' if str(name or '').casefold() in NON_PHYSICAL else 'Confirmado' if res else 'Máquina por confirmar',
                      'rate':applied.get('configuration'),'applied_rate':applied,'reference_rate':(imported_rates.get((area,name)) if area=='perfis' else {'value':number(original.get('Mt\\h')),'unit':'m/h'}) if primary else None,'reference_factor':factor,'reason':reason,'reference_reason':ref_reason,'period_source':period_source,'rate_date':when,'rate_date_source':'Período previsto' if y and w else 'Taxa vigente na data da consulta; trabalho continua por calendarizar',
                      'inputs':{'quantity':q,'quantity_source':calculated_source.get('origin') if calculated_source else 'Preparação local' if is_local else 'Saldo da macro' if area=='cantoneiras' else 'Quantidade Prevista · macro','length_mm':length,'section_unit':unit,'weight_unit':weight_unit,'snapshot':sources[area]['snapshot_id']}}
                item['planning_balance']=balance
                b['items'].append(item);all_items.append(item)
        from . import historical_estimates
        historical_updates[area]=historical_estimates.recalculate(c,area,closed_rows,configs,rate_context,sources[area],today)
    if persist:rate_context.persist(c)
    # Include physical resources even when no work or calendar exists.
    for mk,r in resources.items():
        for alias in r['definition']['aliases']:ensure(alias['area'],alias['name'],None,None)
    from . import worked_hours
    actual={}
    observed=worked_hours.observations(c)
    declarations=[needs.serial(r) for r in configs if r['kind']=='worked_hours']
    covered_aliases=set()
    for resource_id,resource in resources.items():
        if not resource['definition'].get('confirmed'):continue
        resource_aliases=resource['definition']['aliases']
        covered_aliases.update((a['area'],a['name']) for a in resource_aliases)
        for cohort in worked_hours.resolve(resource,declarations,observed):
            try:y,w,_=date.fromisoformat(cohort['start_date']).isocalendar()
            except (TypeError,ValueError):continue
            key=None
            for alias in resource_aliases:key,_=ensure(alias['area'],alias['name'],y,w)
            actual.setdefault(key,[]).append(cohort)
    unconfigured_times={}
    for o in observed:
        if worked_hours.observation_aliases(o)&covered_aliases:continue
        # A source sheet visible in both areas is one declaration. Without a
        # confirmed physical resource, retain it in production_hours without
        # guessing an area or multiplying its time into two capacity buckets.
        if o['area'] not in planning.AREAS:continue
        try:y,w,_=date.fromisoformat(o['date']).isocalendar()
        except (ValueError,TypeError):continue
        key,b=ensure(o['area'],o['machine'],y,w)
        resolved=o
        if o['machine']:
            alias=(o['area'],o['machine'])
            if alias not in unconfigured_times:
                resource={'id':'unconfigured','definition':{'aliases':[{'area':o['area'],'name':o['machine']}]}}
                unconfigured_times[alias]={r['key']:r for r in worked_hours.resolve(resource,[],observed)}
            resolved=unconfigured_times[alias][o['key']]
        actual.setdefault(key,[]).append({'key':o['key'],'sheets':[o['key']],
            'origin':o['origin'],'hours':resolved['hours'],'sheet_evidence':[o],
            'reason':resolved.get('reason',o.get('hours_reason'))})
    if scope is not None:buckets={key:b for key,b in buckets.items() if b['mk'] in scope['machines']}
    weekly=[]
    for key,b in buckets.items():
        res=resources.get(b['mk']);rs=[r for r in rates if r['definition']['resource_id']==b['mk'] and b['year'] and r['definition']['valid_from']<=str(date.fromisocalendar(b['year'],int(b['week']),1)) and (not r['definition'].get('valid_until') or r['definition']['valid_until']>=str(date.fromisocalendar(b['year'],int(b['week']),1)))]
        r=summary(b['items'],b['calendar'],res,b['year'],b['week'],rs)
        r.update(key=key,areas=sorted(b['areas']),aliases=sorted(b['aliases'],key=str));r['values'].update(machine=b['name'],machine_key=b['mk'],bucket_key=key,week=b['week'],year=b['year'])
        ev=actual.get(key,[]);known=[e['hours'] for e in ev if e['hours'] is not None]
        r['values']['actual_hours']=sum(known) if ev and len(known)==len(ev) else None;r['actual_coverage']={'known':len(known),'total':len(ev),'sum_known':sum(known) if known else None};r['actual_evidence']=ev
        r['warnings'] += [e['reason'] for e in ev if e.get('reason')]
        weekly.append(r)
    for key,b in buckets.items():
        mk=b['mk'];m=machines.setdefault(mk,{'items':[],'areas':set(),'aliases':set(),'name':b['name']})
        m['items'].extend(b['items']);m['areas'].update(b['areas']);m['aliases'].update(b['aliases'])
    machine_rows=[]
    for mk,m in machines.items():
        r=summary(m['items'],[],resources.get(mk),None,None,[r for r in rates if r['definition']['resource_id']==mk])
        r.update(key=mk,areas=sorted(m['areas']),aliases=sorted(m['aliases'],key=str),source_totals=[{'area':a,'machine':n,'values':imported_totals[(a,n)]} for a,n in m['aliases'] if (a,n) in imported_totals])
        r['values'].update(machine=m['name'],machine_key=mk);r['warnings']=[x for x in r['warnings'] if x not in ('Por calendarizar','Disponibilidade por confirmar.')]
        r['physical_status']='Recurso físico confirmado' if resources.get(mk,{}).get('definition',{}).get('confirmed') else 'Grupo / destino; capacidade física por definir' if all(str(n or '').casefold() in NON_PHYSICAL for a,n in m['aliases']) else 'Máquina física por confirmar'
        r['reference_rates']=[imported_rates[(a,n)] for a,n in m['aliases'] if (a,n) in imported_rates]
        shift_values={v['shift_hours'] for v in r['reference_rates'] if v.get('shift_hours')}
        sh=next(iter(shift_values)) if len(shift_values)==1 else None
        r['reference_shift_hours']=sh
        if sh:r['coverage']['reference_equivalent_shifts']={**r['coverage']['reference_hours'],'sum_known':r['coverage']['reference_hours']['sum_known']/sh}
        r['values']['reference_equivalent_shifts']=r['values']['reference_hours']/sh if sh and r['values']['reference_hours'] is not None else None
        confirmed_shift=number((resources.get(mk) or {}).get('definition',{}).get('shift_hours'))
        if confirmed_shift and r['values']['planned_hours'] is not None:r['values']['equivalent_shifts']=r['values']['planned_hours']/confirmed_shift
        machine_rows.append(r)
    return {'items':all_items,'weekly':weekly,'machines':machine_rows,'historical_updates':historical_updates}


def rebuild(*,force=False):
    with planning.connect() as c:
        # Decode the large historical population with the JSON runtime already
        # used by Pydantic. Scope adapters to this connection; content digests
        # keep their existing canonical encoder and all retained identities.
        set_json_loads(from_json,c)
        set_json_dumps(to_json,c)
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        c.execute('SET LOCAL jit=off')
        c.execute("SELECT pg_advisory_xact_lock(hashtextextended('capacity-revision',0))")
        configs=c.execute("SELECT * FROM planning_mtg.raw_objects WHERE kind IN ('resource','calendar','rate','period','worked_hours') AND NOT archived ORDER BY id").fetchall()
        sources={};versions={};gens={}
        for area in planning.AREAS:
            try:
                workbooks.capture(c,area);sources[area]=workbooks.source(c,area)
                gens[area]=query.generation(c,area);versions[area]=str(gens[area]['metadata'].get('core_generation',gens[area]['id']))
                for dataset in ('production','production_hours'):
                    try:versions[dataset+':'+area]=str(query.generation(c,area,dataset=dataset)['id'])
                    except planning.PlanningError:pass
            except planning.PlanningError as exc:
                if exc.status==409:raise
        # A successful area task is insufficient: a source can commit between
        # the two tasks. Compare their complete source revisions in the same
        # database snapshot used by the aggregate calculation.
        if set(gens)!=set(planning.AREAS):
            raise planning.PlanningError('Capacidades pendentes: falta uma área atualizada.',409)
        for area,gen in gens.items():
            meta=gen['metadata']
            if meta.get('source_refresh_pending') or meta.get('core_source_fingerprint',meta.get('source_fingerprint'))!=projection.fingerprint(c,area):
                raise planning.PlanningError('Capacidades pendentes: a origem de '+area+' mudou; aguardar o recálculo da área.',409)
        today=datetime.now(ZoneInfo(planning.settings.display_timezone)).date()
        reference_inputs={a:needs.digest(src['sheets']) for a,src in sources.items()}
        fp=needs.digest([CONTRACT,str(today),versions,needs.serial(configs),{a:s['snapshot_id'] for a,s in sources.items()},reference_inputs])
        prev=c.execute("SELECT * FROM planning_mtg.raw_generations WHERE dataset='capacity:perfis' ORDER BY id DESC LIMIT 1").fetchone()
        if prev and prev['metadata'].get('calculation_fingerprint',prev['metadata'].get('source_fingerprint'))==fp and not force:return
        publication_fp=needs.digest([fp,'forced',prev['id']]) if force and prev else fp
        from . import capacity_scope
        resources,aliases=resource_index(configs)
        def machine_key(area,name):return aliases.get((area,name)) or area+':'+str(name or 'Por definir')
        snapshots={a:src['snapshot_id'] for a,src in sources.items()}
        from . import productivity
        rate_context=productivity.Context(c,configs)
        history_hash=rate_context.history_inputs_hash()
        history_unchanged=bool(prev and prev['metadata'].get('history_inputs_hash')==history_hash)
        scope=None if force else capacity_scope.identify(c,prev,gens,versions,snapshots,configs,CONTRACT,str(today),machine_key,reference_inputs,history_unchanged=history_unchanged)
        result=calculate(c,configs,sources,gens,today=today,scope=scope,rate_context=rate_context)
        all_items,weekly,machine_rows=result['items'],result['weekly'],result['machines']
        published=publish_planning_results(c,gens,all_items,weekly,publication_fp,restored=scope['restored'] if scope else None,
            historical_updates=result['historical_updates'])
        meta={'calculation_fingerprint':fp,'applied_planning_versions':published,'configurations':needs.serial(configs),'day':str(today),
            'calculation_scope':'full' if scope is None else 'resources','affected_resources':None if scope is None else sorted(scope['machines']),
            'historical_estimates_updated':{a:len(rows) for a,rows in result['historical_updates'].items()},
            'configuration_digest':needs.digest(needs.serial(configs)),'snapshots':{a:s['snapshot_id'] for a,s in sources.items()},
            'reference_inputs':reference_inputs,'history_inputs_hash':history_hash,'history_inputs_unchanged':history_unchanged,
            'reference_reuse_policy':'Unchanged workbook cells/formulas retain the cited immutable source evidence.',
            'planning_versions':versions,'source_fingerprint':fp,'contract':CONTRACT,'scope':'Recurso físico; áreas partilhadas identificadas explicitamente','display_timezone':planning.settings.display_timezone}
        for area in planning.AREAS:
            visible_machines={r['key'] for r in machine_rows if area in r['areas']}
            capacity_scope.publish(c,'capacity_items:'+area,publication_fp,[r for r in all_items if r['values']['machine_key'] in visible_machines],meta,scope)
            capacity_scope.publish(c,'capacity:'+area,publication_fp,[r for r in weekly if area in r['areas']],meta,scope)
            capacity_scope.publish(c,'capacity_machines:'+area,publication_fp,[r for r in machine_rows if area in r['areas']],meta,scope)
        return len(weekly)


def apply_planning_results(row,items,weekly,capacity_fingerprint=None):
    """Attach the same aggregate occupancy and per-operation estimates everywhere."""
    buckets={r['key']:r for r in weekly}
    v=row['values'];area=row.get('area') or (items[0]['values']['area'] if items else None)
    estimates={str(e['operation']):e for e in row.get('calculation',{}).get('operation_estimates',[])}
    for item in items:
        iv=item['values'];applied=item['applied_rate']
        from .. import planning_estimates
        balance=item.get('planning_balance')
        if balance is None and area=='perfis':
            balance=planning_estimates.select_balance(row,str(iv['operation']))
        estimates[str(iv['operation'])]={'operation':iv['operation'],'machine':iv['machine'],'quantity':iv['quantity'],
                                         'balance':balance,**applied}
        if not iv['primary_operation']:continue
        bucket=buckets[iv['bucket_key']];bv=bucket['values']
        v['hours_pct']=bv['occupancy'];v['theoretical_hours']=iv['planned_hours']
        if balance:
            v['planning_remaining']=balance['planning_remaining']
            v['planning_balance_origin']=balance['balance_origin']
            v['planning_balance_provisional']=balance['provisional']
        v['rate_source']=applied['source'];v['applied_rate_value']=(applied['rate'] or {}).get('value')
        from .productivity import UNITS
        v['applied_rate_unit']=UNITS.get((applied['rate'] or {}).get('method'))
        if area=='cantoneiras':v['speed_m_h']=v['applied_rate_value'] if (applied['rate'] or {}).get('method')=='metres_hour' else None
        rules=row.setdefault('calculation',{}).setdefault('rules',{})
        rules['hours_pct']={'formula':'100 × soma das horas previstas da máquina/semana / horas disponíveis',
            'unit':'%','inputs':{'planned_hours':bv['planned_hours'],'available_hours':bv['available_hours']},
            'bucket':iv['bucket_key'],'capacity_fingerprint':capacity_fingerprint,
            'reason':None if bv['occupancy'] is not None else 'Disponibilidade positiva ou carga integral desconhecida.'}
        from .capacity import estimate_rule
        rules['theoretical_hours']=applied.get('calculation') or estimate_rule({**v,'quantity_to_plan':iv['quantity']},applied)
    row.setdefault('calculation',{})['operation_estimates']=list(estimates.values())
    return row


def publish_planning_results(conn,gens,items,weekly,capacity_fingerprint,*,restored=None,historical_updates=None):
    """Attach F12 and operation estimates from the same capacity revision."""
    by_piece=defaultdict(list);published={}
    previous={}
    if any(item.get('_retained') for item in items):
        for area in gens:
            g=query.generation(conn,area,dataset='capacity');base,args=query.source(g)
            previous.update({r['row_key']:r['values_json'] for r in conn.execute('SELECT m.row_key,c.values_json'+base,args)})
    current={r['key']:r['values'] for r in weekly}
    for item in items:
        bucket=item['values']['bucket_key'];old=previous.get(bucket,{})
        if item.get('_retained') and all(old.get(k)==current[bucket].get(k) for k in ('planned_hours','available_hours','occupancy')):continue
        by_piece[(item['values']['area'],item['planning_key'])].append(item)
    for area in gens:
        deferred={item['key']:item for (a,_),group in by_piece.items() if a==area for item in group if item.get('_rate_deferred')}
        if deferred:
            gen=query.generation(conn,area,dataset='capacity_items');base,args=query.source(gen)
            for row in conn.execute("SELECT m.row_key,c.detail->'applied_rate' applied_rate"+base+' AND m.row_key=ANY(%s)',args+[list(deferred)]):
                deferred[row['row_key']]['applied_rate']=row['applied_rate']
    for area,gen in gens.items():
        history=(historical_updates or {}).get(area,{})
        keys=[key for a,key in by_piece if a==area]
        base,args=query.source(gen)
        changed=dict((restored or {}).get(area,{}))
        for data in conn.execute('SELECT m.row_key,c.values_json,c.detail'+base+' AND m.row_key=ANY(%s)',args+[keys]).fetchall():
            row=changed.get(data['row_key']) or {**data['detail'],'values':data['values_json']}
            apply_planning_results(row,by_piece[(area,data['row_key'])],weekly,capacity_fingerprint)
            changed[data['row_key']]=row
        core_fp=gen['metadata'].get('core_source_fingerprint',gen['metadata']['source_fingerprint'])
        metadata={**gen['metadata'],'core_source_fingerprint':core_fp,
            'core_generation':gen['metadata'].get('core_generation',str(gen['id'])),
            'capacity_fingerprint':capacity_fingerprint,'aggregates_pending':False}
        new=projection.publish_delta(conn,'planning:'+area,needs.digest([core_fp,capacity_fingerprint]),list(changed.values()),metadata,expected_generation=gen['id'],estimate_patches=history)
        published[area]=str(new['id'])
    return published
