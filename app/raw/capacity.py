"""Explicit physical resources, confirmed calendars/rates and transparent load estimates."""
from collections import defaultdict
from datetime import date,timedelta
import uuid
from .. import planning,planning_needs as needs,planning_raw as old
from . import objects,projection,query

METHODS={'area_hour':'mm²/h','metres_hour':'m/h','units_hour':'un./h','minutes_unit':'min/un.','fixed_minutes':'min'}
ESTIMATE_CONTRACT='planning-operation-hours-20260924-v2'  # v2 (06/10): janela histórica até hoje, amostra mínima e plausibilidade


def hourly_rate(rate):
    """A physical rate needs a compatible unit and cannot absorb a setup cost."""
    value=old.number(rate.get('value'))
    if value is None or value<=0 or rate.get('setup_minutes'):return None
    unit={'area_hour':'mm²','metres_hour':'m','units_hour':'un.','minutes_unit':'un.'}.get(rate.get('method'))
    if unit is None:return None
    return unit,60/value if rate['method']=='minutes_unit' else value


def positive(v,zero=False):
    n=old.number(v)
    if n is None or n<0 or not zero and n==0:raise planning.PlanningError('Indica um número '+('não negativo.' if zero else 'positivo.'))
    return n


def validate(c,kind,id,d):
    if kind=='resource':
        from ..gantt.machines import validate_rules
        validate_rules(d.get('technical_rules', []))
        aliases=d.get('aliases',[])
        if not aliases or any(not a.get('name') or a.get('area') not in planning.AREAS for a in aliases):raise planning.PlanningError('Indica pelo menos um nome de máquina e a respetiva área.')
        for r in c.execute("SELECT id,definition FROM planning_mtg.raw_objects WHERE kind='resource' AND NOT archived AND id<>%s",(id,)).fetchall():
            if any(a in r['definition'].get('aliases',[]) for a in aliases):raise planning.PlanningError('Este nome já pertence a outro recurso físico.',409)
        if not d.get('operations') and d.get('resource_type') not in ('grupo_operadores',):raise planning.PlanningError('Indica as operações suportadas.')
        shift=positive(d['shift_hours']) if d.get('shift_hours') not in (None,'') else None
        if shift and shift>24:raise planning.PlanningError('As horas por turno não podem exceder 24.')
        window=positive(d.get('history_window_days',90))
        if not window.is_integer() or not 1<=window<=3660:raise planning.PlanningError('A janela histórica deve ter entre 1 e 3660 dias inteiros.')
        return {**d,'aliases':aliases,'shift_hours':shift,'history_window_days':int(window),'confirmed':bool(d.get('confirmed'))}
    resource=objects.get(d.get('resource_id'),c)
    if resource['kind']!='resource' or resource['archived']:raise planning.PlanningError('Seleciona um recurso físico ativo.')
    if d.get('confirmed') and not resource['definition'].get('confirmed'):raise planning.PlanningError('Confirma primeiro a identidade da máquina física.')
    if kind=='calendar':
        try:year=int(d.get('year'));week=int(d.get('week'));date.fromisocalendar(year,week,1)
        except (TypeError,ValueError):raise planning.PlanningError('Semana e ano ISO inválidos.')
        if 'weekly_windows' in d:
            from .. import planning_calendars
            try:d=planning_calendars.validate({**d,'year':year,'week':week})
            except (ValueError,TypeError,KeyError) as exc:raise planning.PlanningError(str(exc))
            d={**d,'shifts':0,'hours_per_shift':0,'exception_hours':0}
            shifts=hours=exceptions=0
        else:
            shifts=positive(d.get('shifts'),True);hours=positive(d.get('hours_per_shift'),True);exceptions=positive(d.get('exception_hours',0),True)
            if shifts!=int(shifts) or shifts>21 or hours>24:raise planning.PlanningError('Turnos ou horas por turno inválidos.')
            if exceptions>shifts*hours:raise planning.PlanningError('As exceções excedem as horas do calendário.')
        for r in c.execute("SELECT definition FROM planning_mtg.raw_objects WHERE kind='calendar' AND NOT archived AND id<>%s",(id,)).fetchall():
            x=r['definition']
            if x.get('resource_id')==d['resource_id'] and x.get('year')==year and x.get('week')==week:raise planning.PlanningError('Já existe um calendário para esta máquina e semana. Edita-o.',409)
        return {**d,'year':year,'week':week,'shifts':shifts,'hours_per_shift':hours,'exception_hours':exceptions,'confirmed':bool(d.get('confirmed'))}
    if d.get('method') not in METHODS:raise planning.PlanningError('Método de cálculo desconhecido.')
    if d.get('area') not in planning.AREAS or not str(d.get('operation') or '').strip():raise planning.PlanningError('Indica a área e operação da taxa.')
    try:start=date.fromisoformat(d['valid_from']);end=date.fromisoformat(d['valid_until']) if d.get('valid_until') else None
    except (KeyError,ValueError):raise planning.PlanningError('Indica a vigência da taxa.')
    if end and end<start:raise planning.PlanningError('A vigência termina antes de começar.')
    d={**d,'material_type':str(d.get('material_type') or '').strip(),'profile':str(d.get('profile') or '').strip(),'value':positive(d.get('value')),'setup_minutes':positive(d.get('setup_minutes',0),True),'confirmed':bool(d.get('confirmed'))}
    for r in c.execute("SELECT definition FROM planning_mtg.raw_objects WHERE kind='rate' AND NOT archived AND id<>%s",(id,)).fetchall():
        x=r['definition']
        if (x.get('resource_id'),x.get('area'),x.get('operation'))!=(d['resource_id'],d['area'],d['operation']):continue
        scopes_overlap=all(not x.get(k) or not d.get(k) or x[k]==d[k] for k in ('material_type','profile'))
        if scopes_overlap and x.get('confirmed') and d['confirmed'] and (not x.get('valid_until') or x['valid_until']>=str(start)) and (not end or x['valid_from']<=str(end)):raise planning.PlanningError('Existem taxas confirmadas com vigência sobreposta.',409)
    return d


def estimate_inputs(values,rate):
    q=old.number(values.get('quantity_to_plan'));method=(rate or {}).get('method')
    inputs={'quantity':q,'rate':rate,'method':method,'volume':None,
            'volume_unit':{'area_hour':'mm²','metres_hour':'m','units_hour':'un.','minutes_unit':'un.'}.get(method),
            'setup_minutes':0 if q==0 else rate.get('setup_minutes',0) if rate else None}
    if method=='area_hour':inputs['section_unit']=old.number(values.get('section_unit'))
    if method=='metres_hour':inputs['length_mm']=old.number(values.get('length_mm'))
    if q is not None and q>=0 and q.is_integer():
        if method in ('units_hour','minutes_unit'):inputs['volume']=q
        elif method in ('area_hour','metres_hour'):
            dimension=inputs['section_unit' if method=='area_hour' else 'length_mm']
            inputs['volume']=0 if q==0 else q*dimension/(1000 if method=='metres_hour' else 1) if dimension is not None and dimension>0 else None
    return inputs


def operation_code(code):
    """Código simples de uma operação: 'CPIS:119' → '119', 'LOCAL:PRINCIPAL' → 'corte', 'LOCAL:ABOCARDAR' → 'abocardar'."""
    code=str(code or '')
    return {'LOCAL:PRINCIPAL':'corte','LOCAL:ABOCARDAR':'abocardar'}.get(code,code.removeprefix('CPIS:'))


def supports(resource,operation):
    """O recurso confirmado faz esta operação? Aceita os dois formatos (simples e da camada de pesquisa, 06/10/2026).

    As máquinas confirmadas a 05/10 guardam 'CPIS:119'/'LOCAL:PRINCIPAL'; o motor de horas usa '119'/'corte'.
    """
    return operation_code(operation) in {operation_code(x) for x in (resource or {}).get('definition',{}).get('operations') or []}


def estimate_rule(values,applied):
    inputs=estimate_inputs(values,applied.get('rate'));method=inputs['method']
    formulas={'area_hour':'Saldo × área unitária / taxa (mm²/h) + preparação (min) / 60',
              'metres_hour':'Saldo × comprimento (mm) / 1000 / taxa (m/h) + preparação (min) / 60',
              'units_hour':'Saldo / taxa (un./h) + preparação (min) / 60',
              'minutes_unit':'Saldo × taxa (min/un.) / 60 + preparação (min) / 60',
              'fixed_minutes':'Minutos fixos / 60 + preparação (min) / 60'}
    formula='Saldo nulo: 0 h, sem preparação' if inputs['quantity']==0 and applied.get('hours')==0 else formulas.get(method,'Taxa e método por confirmar')
    if applied.get('source')=='Excel provisório':
        inputs['excel_factor']=applied.get('factor',1)
        rate=old.number((applied.get('rate') or {}).get('value'))
        inputs['reference_rate_value']=rate/inputs['excel_factor'] if rate is not None and inputs['excel_factor'] else None
    return {'formula':formula,'unit':'h','inputs':inputs,'source':applied.get('source'),
            'reason':applied.get('reason'),'history_hash':applied.get('history_hash'),'contract':ESTIMATE_CONTRACT}


def estimate(values,rate,operation):
    inputs=estimate_inputs(values,rate);q=inputs['quantity']
    if q is None or q < 0 or not q.is_integer():return None,'Quantidade prevista negativa, inválida ou por confirmar'
    if q==0:return 0,None
    method=rate['method'];v=rate['value'];setup=inputs['setup_minutes']/60
    if method=='area_hour':return (inputs['volume']/v+setup,None) if inputs['volume'] is not None else (None,'Área unitária por confirmar')
    if method=='metres_hour':return (inputs['volume']/v+setup,None) if inputs['volume'] is not None else (None,'Comprimento por confirmar')
    if method=='units_hour':return q/v+setup,None
    if method=='minutes_unit':return q*v/60+setup,None
    if method=='fixed_minutes':return v/60+setup,None
    return None,'Método por confirmar'


def rebuild():
    from .capacity_revision import rebuild as calculate
    return calculate()


def sources():
    """Historical source rows are proposals, never implicit current calendars or confirmed rates."""
    result={}
    with planning.connect(readonly=True) as c:
        for area in planning.AREAS:
            snap=planning.snapshot(c,area)
            rows=c.execute("SELECT sheet_name,excel_row,row_data FROM raw_mtg.other_sheet_rows WHERE snapshot_id=%s AND sheet_name IN ('PlanDisponibilidadeSemanal','CapacidadeMáquinas','Dados') ORDER BY sheet_name,excel_row",(snap['snapshot_id'],)).fetchall()
            result[area]={'snapshot':snap['snapshot_id'],'rows':rows,'warning':'Dados históricos: confirmar unidades, vigência e calendário. O fator Thomas ×3 não está ativo.'}
    return needs.serial(result)


def copy_calendar(p):
    with planning.connect() as c:
        _,_,old_result=needs.command(c,p)
        if old_result:return old_result
        src=objects.get(p['source_id'],c)
        if src['kind']!='calendar' or p.get('expected_revision')!=src['revision']:raise planning.PlanningError('O calendário mudou. Reabre a origem.',409)
        try:start=date.fromisocalendar(int(p['start_year']),int(p['start_week']),1);end=date.fromisocalendar(int(p['end_year']),int(p['end_week']),1)
        except (KeyError,ValueError):raise planning.PlanningError('Intervalo de semanas inválido.')
        if end<start or (end-start).days>730:raise planning.PlanningError('Escolhe um intervalo até dois anos.')
        changes=[]
        while start<=end:
            y,w,_=start.isocalendar();d={**src['definition'],'year':y,'week':w};existing=c.execute("SELECT id,revision,definition FROM planning_mtg.raw_objects WHERE kind='calendar' AND NOT archived AND definition->>'resource_id'=%s AND (definition->>'year')::int=%s AND (definition->>'week')::int=%s",(d['resource_id'],y,w)).fetchone()
            if 'weekly_windows' in d:
                d['date_overrides']={}
                d['reserved_windows']=[]
            changes.append({'definition':d,'existing':needs.serial(existing)});start+=timedelta(days=7)
        token=needs.digest(changes)
        if not p.get('confirm'):return {'changes':changes,'evidence_hash':token}
        if p.get('evidence_hash')!=token:raise planning.PlanningError('O calendário mudou. Revê a comparação.',409)
        results=[]
        for i,ch in enumerate(changes):
            ex=ch['existing'];d=ch['definition'];results.append(objects.save({'request_id':str(uuid.uuid5(needs.uid(p['request_id']),str(i))),'id':ex['id'] if ex else None,'expected_revision':ex['revision'] if ex else 0,'area':src['area'],'name':src['name'].split(' · ')[0]+f" · {d['year']}-W{d['week']:02}",'definition':d},'calendar',conn=c))
        return needs.finish(c,p,{'items':results})


def source_proposals():
    data=sources();result=[]
    for area,source in data.items():
        for row in source['rows']:
            v=row['row_data'].get('values',[]);sheet=row['sheet_name'];line=row['excel_row']
            provenance={'snapshot':source['snapshot'],'sheet':sheet,'row':line}
            if sheet=='PlanDisponibilidadeSemanal' and line>1 and len(v)>=7 and isinstance(v[1],(int,float)) and isinstance(v[2],(int,float)):
                result.append({'kind':'calendar','machine':v[3],'area':area,'definition':{'year':int(v[2]),'week':int(v[1]),'shifts':v[5],'hours_per_shift':v[6],'exception_hours':0,'confirmed':False,'source':f"{source['snapshot']} · {sheet}!{line}"},'provenance':provenance})
            if sheet=='CapacidadeMáquinas' and line>1 and len(v)>=5 and v[1]:
                for col,when in ((2,'2024-11-11'),(4,'2024-11-29')):
                    rate=old.number(v[col])
                    if rate and rate>0:result.append({'kind':'rate','machine':v[1],'area':area,'definition':{'area':area,'operation':'corte','method':'area_hour','value':rate,'setup_minutes':0,'valid_from':when,'confirmed':False,'source':f"{source['snapshot']} · {sheet}!{line} · coluna {col+1}"},'provenance':provenance})
    with planning.connect(readonly=True) as c:
        snap=planning.snapshot(c,'cantoneiras')
        rows=c.execute("""SELECT cutting_machine machine,row_data->>'1ª Oper.' operation,material_type,profile_type,
            row_data->>'Mt\\h' rate,count(*) n FROM raw_mtg.plan_production_rows WHERE snapshot_id=%s
            GROUP BY 1,2,3,4,5 ORDER BY 1,2,3,4""",(snap['snapshot_id'],)).fetchall()
        for r in rows:
            rate=old.number(r['rate'])
            if r['machine'] and rate and rate>0:
                result.append({'kind':'rate','machine':r['machine'],'area':'cantoneiras','definition':{'area':'cantoneiras','operation':r['operation'],'material_type':r['material_type'],'profile':r['profile_type'],'method':'metres_hour','value':rate,'setup_minutes':0,'valid_from':None,'confirmed':False,'source':snap['snapshot_id']+' · '+str(r['n'])+' linhas com estes parâmetros'},'provenance':{'snapshot':snap['snapshot_id'],'rows':r['n']}})
    return needs.serial({'proposals':result,'notice':'Sugestões históricas. Confirmar recurso físico, unidades, operação e vigência antes de utilizar.'})
