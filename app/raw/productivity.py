"""Weighted, traceable productivity from complete matching time/production cohorts.

A cohort's numerator and denominator are accepted or rejected together. No
allocation of sheet time to a subset of its pieces or operations is inferred.
"""
from collections import defaultdict
from datetime import date, timedelta
from itertools import groupby
from psycopg.types.json import Jsonb

from .. import planning, planning_needs as needs
from ..planning_calculations import number, quantity, positive, key
from . import query, worked_hours

UNITS={'area_hour':'mm²/h','metres_hour':'m/h','units_hour':'un./h','minutes_unit':'min/un.','fixed_minutes':'min'}
SCOPE_FIELDS=('material_type','profile','grade')


def ordered_records(rows):
    """Stable evidence order, including conflicting versions of the same ID."""
    result=[]
    for _,group in groupby(sorted(rows,key=lambda r:r['key']),key=lambda r:r['key']):
        versions=list(group)
        result.extend(sorted(versions,key=needs.digest) if len(versions)>1 else versions)
    return result


def historical(events, cohorts, *, area, operation, method, values, as_of, days=90):
    start=as_of-timedelta(days=days-1)
    by_sheet=defaultdict(list)
    for e in ordered_records(events):by_sheet[e['sheet_key']].append(e)
    expanded=[]
    for c in cohorts:
        allocations=(c.get('definition') or {}).get('operation_hours') or []
        if not allocations:expanded.append(c);continue
        assigned={(a['area'],a['operation']) for a in allocations}
        covered=[e for sheet in c.get('sheets',[]) for e in by_sheet[sheet]]
        complete=all((e.get('area'),str(e.get('operation'))) in assigned for e in covered)
        for a in allocations:
            expanded.append({**c,'key':c['key']+':'+a['area']+':'+a['operation'],
                'parent_key':c['key'],'allocation':a,'operation':a['operation'],
                'hours':a['hours'] if c.get('hours') is not None and complete else None,
                'reason':c.get('reason') or ('Repartição não abrange todas as operações dos eventos.' if not complete else None)})
    cohorts=ordered_records(expanded)
    def records_for(c):
        records=[r for sheet in sorted(c.get('sheets',[])) for r in by_sheet[sheet]]
        allocation=c.get('allocation')
        return [r for r in records if r.get('area')==allocation['area'] and str(r.get('operation'))==allocation['operation']] if allocation else records
    owners=defaultdict(set);versions=defaultdict(set)
    for cohort in cohorts:
        versions[cohort['key']].add(needs.digest(cohort))
        for e in records_for(cohort):owners[e['key']].add(cohort['key'])
    used=[];excluded=[];seen_cohorts=set();seen_events=set()
    for cohort in cohorts:
        ident=cohort['key'];reasons=[]
        if ident in seen_cohorts:continue
        seen_cohorts.add(ident)
        if len(versions[ident])>1:reasons.append('Declaração de horas repetida com conteúdo divergente.')
        try:
            first=date.fromisoformat(cohort['start_date']);last=date.fromisoformat(cohort['end_date'])
        except (ValueError,TypeError,KeyError):
            first=last=None;reasons.append('Data das horas desconhecida.')
        if first is not None and (first<start or last>as_of or first>last):
            reasons.append('Período fora da janela histórica.')
        h=positive(cohort.get('hours'))
        if h is None:reasons.append(cohort.get('reason') or 'Horas positivas desconhecidas; zero horas não define produtividade.')
        records=records_for(cohort)
        if not records:reasons.append('Sem produção correspondente às horas.')
        if cohort.get('operation') and str(cohort['operation'])!=str(operation):reasons.append('Horas de outra operação.')
        distinct={};volume=0
        for e in records:
            prior=distinct.get(e['key'])
            if prior is not None:
                if prior!=e:reasons.append('Evento repetido com conteúdo divergente.')
                continue
            distinct[e['key']]=e
            if len(owners[e['key']])>1:reasons.append('Evento abrangido por mais de uma declaração de horas.')
            if e.get('area')!=area or str(e.get('operation'))!=str(operation):
                reasons.append('Tempo partilhado por operações/áreas sem repartição comprovada.')
            if not e.get('identity_valid'):reasons.append('Associação técnica ou operação do evento por confirmar.')
            try:
                produced_on=date.fromisoformat(e['date'])
                if first is None or not first<=produced_on<=last:reasons.append('Data do evento incompatível com o período de horas.')
            except (ValueError,TypeError,KeyError):reasons.append('Data de produção desconhecida.')
            if method=='units_hour' and any(key(e.get(k))!=key(values.get(k)) for k in SCOPE_FIELDS):
                reasons.append('Família, perfil ou qualidade incompatíveis com esta estimativa.')
            q=quantity(e.get('quantity'))
            if q is None:reasons.append('Quantidade de produção desconhecida ou inválida.');continue
            if method=='units_hour':
                if any(number(e.get(k))!=number(values.get(k)) for k in ('length_mm','outer_diameter_mm','width_mm','height_mm','thickness_mm','angle_deg')):
                    reasons.append('Dimensões incompatíveis para produtividade em unidades/h.')
                volume+=q
            elif method in ('area_hour','metres_hour'):
                unit=positive(e.get('section_unit' if method=='area_hour' else 'length_mm'))
                if unit is None and q:reasons.append('Volume do evento sem dimensão comprovada.')
                else:volume+=q*(unit or 0)/(1000 if method=='metres_hour' else 1)
            else:reasons.append('Método histórico desconhecido.')
        if reasons:
            excluded.append({'key':ident,'sheets':sorted(cohort.get('sheets',[])),'events':sorted(distinct),
                             'reasons':sorted(set(reasons))})
            continue
        used.append({'key':ident,'sheets':sorted(cohort.get('sheets',[])),'events':sorted(distinct),'hours':h,'volume':volume,
                     'start_date':str(first),'end_date':str(last),'hours_origin':cohort.get('origin'),
                     'hours_revision':cohort.get('revision'),'allocation':cohort.get('allocation')})
        seen_events.update(distinct)
    volume=sum(r['volume'] for r in used);hours=sum(r['hours'] for r in used)
    value=volume/hours if hours>0 and volume>0 else None
    return {'source':'Histórico','method':method,'unit':UNITS.get(method),'value':value,
            'window':{'start':str(start),'end':str(as_of),'days':days},'volume':volume,'hours':hours,
            'sheet_count':len({s for r in used for s in r['sheets']}),'event_count':len(seen_events),
            'cohorts':used,'excluded':excluded,'scope':{k:values.get(k) for k in SCOPE_FIELDS} if method=='units_hour' else {'area':area,'operation':operation,'unit':UNITS.get(method),'compatibility':'Volume integral normalizado pela dimensão comprovada de cada peça.'},
            'reason':None if value is not None else 'Sem coorte compatível com volume e horas positivos.'}


def select_rate(values, *, area, operation, resource_id, manual, historical_rate, excel, when):
    """H10 selection, before calculating hours. A conflict cannot fall through."""
    applicable=[r for r in manual if r['definition'].get('confirmed')
        and r['definition'].get('resource_id')==resource_id and r['definition'].get('area')==area
        and str(r['definition'].get('operation'))==str(operation)
        and all(not r['definition'].get(k) or key(r['definition'][k])==key(values.get(k)) for k in ('material_type','profile'))
        and r['definition']['valid_from']<=when and (not r['definition'].get('valid_until') or when<=r['definition']['valid_until'])]
    if len(applicable)>1:return {'source':None,'rate':None,'reason':'Taxas manuais aplicáveis em conflito.','candidates':[r['id'] for r in applicable]}
    if applicable:
        r=applicable[0]
        return {'source':'Manual','rate':r['definition'],'configuration':r,'reason':None,'factor':1}
    if positive(historical_rate.get('value')):
        return {'source':'Histórico','rate':{k:historical_rate[k] for k in ('method','value','unit','window') if k in historical_rate},'reason':None,'factor':1}
    if excel and positive(excel.get('value')):
        factor=3 if area=='perfis' and operation=='corte' and values.get('machine')=='Serrote Fita Thomas IS639 Pav.1' and (quantity(values.get('quantity_required')) or 0)>50 else 1
        return {'source':'Excel provisório','rate':{**excel,'value':excel['value']*factor},'reason':None,'factor':factor}
    return {'source':None,'rate':None,'reason':historical_rate.get('reason') or 'Sem taxa manual, histórica ou Excel válida.','factor':1}


class Context:
    """One database snapshot and memoized rates for a whole planning calculation."""
    def __init__(self, conn, configs, *, rows_override=None, events_override=None):
        self.configs=needs.serial(configs);self.manual=[r for r in self.configs if r['kind']=='rate']
        self.resources={r['id']:r for r in self.configs if r['kind']=='resource' and r['definition'].get('confirmed')}
        self.aliases={(a['area'],a['name']):r for r in self.resources.values() for a in r['definition']['aliases']}
        self.observed=worked_hours.observations(conn);self.events=[];self.cache={};self.time_cache={};self.history_hashes={}
        declarations=[r for r in self.configs if r['kind']=='worked_hours']
        self.declarations=declarations
        for area in planning.AREAS:
            try:
                if events_override and area in events_override:events=events_override[area]
                else:
                    gen=query.generation(conn,area,dataset='production');base,args=query.source(gen)
                    events=[{**r['detail'],'values':r['values_json']} for r in conn.execute('SELECT c.detail,c.values_json'+base,args)]
            except planning.PlanningError as exc:
                if exc.status==503:continue
                raise
            ids=list({k for e in events for k in e.get('planning_keys',[])})
            lines={}
            try:
                gen=query.generation(conn,area);base,args=query.source(gen)
                for r in conn.execute("SELECT m.row_key,c.values_json,jsonb_build_object('compatible',c.detail->'calculation'->'compatible','historical_compatible',c.detail->'calculation'->'historical_compatible') calculation"+base+' AND m.row_key=ANY(%s)',args+[ids]):
                    lines[r['row_key']]={'values':r['values_json'],'calculation':r['calculation'] or {}}
            except planning.PlanningError as exc:
                if exc.status!=503:raise
            for row in (rows_override or {}).get(area,[]):
                for ident in [row['key']]+row.get('selection_aliases',[]):lines[ident]=row
            for e in events:
                v=e['values'];linked=e.get('planning_keys',[]);piece=lines.get(linked[0]) if len(linked)==1 else None
                self.events.append({**(piece['values'] if piece else {}),'key':area+':'+e['key'],
                    'sheet_key':('' if v.get('source')=='ocr_original' else area+':')+str(e.get('sheet_uid') or 'unknown:'+e['key']),'area':area,'operation':v.get('operation'),
                    'machine':v.get('machine'),'date':v.get('production_date'),'quantity':v.get('quantity'),
                    'identity_valid':bool(piece and piece.get('calculation',{}).get('compatible') is not False and piece.get('calculation',{}).get('historical_compatible') is not False
                        and v.get('association_status') in ('associated','explicit','technical_unique'))})

    def history_inputs_hash(self):
        """Inputs consumed by historical(), independent of planning import IDs.

        Closing/reopening an OF or rebinding an unchanged macro row must not
        invalidate the historical rates of every other piece on its machines.
        Production identity, dimensions, coverage and all time evidence remain
        dependencies. Duplicate keys retain their entire conflicting payloads.
        """
        fields=('key','sheet_key','area','operation','machine','date','quantity','identity_valid',
                *SCOPE_FIELDS,'length_mm','section_unit','outer_diameter_mm','width_mm',
                'height_mm','thickness_mm','angle_deg')
        groups=defaultdict(list)
        for event in self.events:groups[event['key']].append(event)
        events=[]
        for ident,rows in sorted(groups.items()):
            events.extend(sorted(rows,key=needs.digest) if len(rows)>1 else [{k:rows[0].get(k) for k in fields}])
        return needs.digest(['historical-inputs-v1',events,sorted(self.observed,key=needs.digest),
                             sorted(self.declarations,key=needs.digest)])

    def cohorts(self, area, machine):
        resource=self.aliases.get((area,machine))
        if resource is None:
            resource={'id':area+':'+str(machine),'definition':{'aliases':[{'area':area,'name':machine}]}}
        if resource['id'] not in self.time_cache:
            self.time_cache[resource['id']]=worked_hours.resolve(resource,self.declarations,self.observed) if machine else []
        return resource,self.time_cache[resource['id']]

    def rate(self, values, area, operation, when, *, excel=None, as_of=None):
        resource,cohorts=self.cohorts(area,values.get('machine'))
        days=resource['definition'].get('history_window_days',90)
        as_of=as_of or date.fromisoformat(when)
        method='area_hour' if area=='perfis' and operation=='corte' else 'metres_hour' if area=='cantoneiras' else 'units_hour'
        scope={k:values.get(k) for k in SCOPE_FIELDS+('length_mm','outer_diameter_mm','width_mm','height_mm','thickness_mm','angle_deg')} if method=='units_hour' else {}
        cache_key=needs.digest([resource['id'],area,operation,method,scope,str(as_of),days])
        if cache_key not in self.cache:
            self.cache[cache_key]=historical(self.events,cohorts,area=area,operation=operation,method=method,values=values,as_of=as_of,days=days)
            self.history_hashes[cache_key]=needs.digest({'productivity':self.cache[cache_key]})
        history=self.cache[cache_key]
        chosen=select_rate(values,area=area,operation=operation,resource_id=resource['id'],manual=self.manual,historical_rate=history,excel=excel,when=when)
        digest=self.history_hashes[cache_key]
        return {**chosen,'history_hash':digest,'history':{k:v for k,v in history.items() if k not in ('cohorts','excluded')},
                'excluded_cohorts':len(history['excluded'])}

    def persist(self, conn):
        # Immutable evidence is shared by content hash, rather than repeated for
        # tens of thousands of pieces with the same productivity scope.
        for cache_key,history in self.cache.items():
            digest=self.history_hashes[cache_key]
            conn.execute("INSERT INTO planning_mtg.raw_contents(hash,values_json,detail,search_text) VALUES(%s,'{}',%s,'') ON CONFLICT DO NOTHING",
                         (digest,Jsonb({'productivity':needs.serial(history)})))

    def estimate(self, values, area, operation, when, *, excel=None, as_of=None):
        from .capacity import estimate,estimate_rule
        applied=self.rate(values,area,operation,when,excel=excel,as_of=as_of)
        resource=self.aliases.get((area,values.get('machine')))
        allowed=operation in ('corte','abocardar') if area=='perfis' else str(operation).isdigit() and str(operation)!='0'
        if not allowed or resource and operation not in resource['definition']['operations']:
            result={**applied,'source':None,'rate':None,'hours':None,'reason':'Operação por confirmar para este recurso.'}
            return {**result,'calculation':estimate_rule(values,result)}
        h,reason=estimate(values,applied['rate'],operation) if applied['rate'] else (None,applied['reason'])
        if quantity(values.get('quantity_to_plan'))==0:h,reason=0,None
        result={**applied,'hours':h,'reason':reason}
        return {**result,'calculation':estimate_rule(values,result)}


def apply_rows(conn, area, rows, configs, *, persist=True, context=None, source=None, today=None):
    if not rows:return
    from zoneinfo import ZoneInfo
    from datetime import datetime
    from . import workbooks, capacity_revision
    from .. import planning_estimates
    context=context or Context(conn,configs,rows_override={area:rows})
    if source is None and persist:workbooks.capture(conn,area)
    src=source or workbooks.source(conn,area)
    _,excel_rates,_=capacity_revision.workbook_index({area:src})
    periods=[r for r in configs if r['kind']=='period']
    today=today or datetime.now(ZoneInfo(planning.settings.display_timezone)).date()
    for row in rows:
        row.setdefault('calculation',{}).setdefault('rules',{})
        v=row['values'];primary='corte' if area=='perfis' else str(v.get('operation') or '')
        if area=='cantoneiras':
            row.setdefault('original',{}).setdefault('speed_m_h',number(row['raw'].get('Mt\\h')))
            row['original'].setdefault('theoretical_hours',number(row['raw'].get('h teor. Falta')))
        preparations={r['values_json'].get('operation'):r['values_json'] for r in row.get('preparations',[])}
        estimates=[]
        for source in row.get('calculation',{}).get('production_sources',[]):
            op=source['operation'];main=op==primary
            balance=planning_estimates.select_balance(row,op) if area=='perfis' else {
                'planning_remaining':source['remaining'],'reconciled_remaining':source['remaining'],
                'balance_origin':source['origin'],'provisional':source['origin']=='Excel provisório',
                'evidence':source.get('records') or [],'reasons':source.get('coverage_reasons') or []}
            operation_values=preparations.get(op) or ({} if main else {'machine':None,'expected_date':None,'planned_week':None,'planned_year':None})
            vals={**v,**{k:x for k,x in operation_values.items() if k not in needs.PIECE_FIELDS}}
            vals['quantity_to_plan']=balance['planning_remaining'];vals['quantity_required']=v.get('quantity_required')
            y,w,_=capacity_revision.period(vals,area,src['snapshot_id'],periods)
            when=str(vals.get('expected_date') or (date.fromisocalendar(y,w,1) if y and w else today))[:10]
            excel=None
            if main:
                imported=excel_rates.get((area,vals.get('machine')))
                excel={**imported,'method':'area_hour'} if area=='perfis' and imported else {'method':'metres_hour','value':number(row['raw'].get('Mt\\h')),'unit':'m/h','source':'Macro · Mt\\h'} if area=='cantoneiras' else None
            result=context.estimate(vals,area,op,when,excel=excel,as_of=min(today,date.fromisoformat(when)))
            estimates.append({'operation':op,'machine':vals.get('machine'),'quantity':balance['planning_remaining'],
                              'balance':balance,**result})
            if main:
                v['planning_remaining']=balance['planning_remaining']
                v['planning_balance_origin']=balance['balance_origin']
                v['planning_balance_provisional']=balance['provisional']
                v['theoretical_hours']=result['hours'];v['rate_source']=result['source']
                v['applied_rate_value']=(result['rate'] or {}).get('value')
                v['speed_m_h']=v['applied_rate_value'] if (result['rate'] or {}).get('method')=='metres_hour' else None
                v['applied_rate_unit']=UNITS.get((result['rate'] or {}).get('method')) or (result['rate'] or {}).get('method')
                row['calculation']['rules']['theoretical_hours']=result['calculation']
        row['calculation']['operation_estimates']=estimates
        # The old Excel percentage is not the recalculated weekly occupancy.
        v['hours_pct']=None
        from .. import planning_population
        row['calculation']['rules']['hours_pct']={'formula':'100 × carga da máquina/semana / disponibilidade',
            'reason':'Ocupação agregada aguarda publicação conjunta com a capacidade.' if planning_population.includes(row)
                else 'Peça fechada: excluída da carga do planeamento ativo.'}
    if persist:context.persist(conn)


def evidence(digest):
    with planning.connect(readonly=True) as conn:
        row=conn.execute("SELECT detail->'productivity' evidence FROM planning_mtg.raw_contents WHERE hash=%s AND detail ? 'productivity'",(digest,)).fetchone()
        if not row:raise planning.PlanningError('Evidência de produtividade não encontrada.',404)
        return {'hash':digest,**row['evidence']}
