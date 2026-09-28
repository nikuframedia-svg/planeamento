"""Capacity HTTP services, frozen weekly plans and evidence-based compliance."""
from datetime import date, datetime
from zoneinfo import ZoneInfo
import uuid
from .. import planning, planning_needs as needs
from . import query, objects, workbooks, projection, capacity_revision as calc


def overview(p):
    area=planning.check_area(p.get('area','perfis'))
    mode=p.get('mode','weekly')
    if mode not in ('weekly','machines'):raise planning.PlanningError('Vista de capacidade inválida.')
    today=datetime.now(ZoneInfo(planning.settings.display_timezone)).date()
    y,w,_=today.isocalendar()
    filters=list(p.get('filters') or [])
    if mode=='weekly' and not p.get('all_periods'):
        try:y=int(p.get('year',y));w=int(p.get('week',w));date.fromisocalendar(y,w,1)
        except (ValueError,TypeError):raise planning.PlanningError('Semana/ano inválidos.')
        if p.get('unscheduled'):filters.append({'field':'year','op':'empty'})
        else:filters += [{'field':'year','op':'eq','value':y},{'field':'week','op':'eq','value':w}]
    result=query.listing({**p,'area':area,'dataset':'capacity' if mode=='weekly' else 'capacity_machines','filters':filters})
    with planning.connect(readonly=True) as c:
        aggregate=query.generation(c,area,result['version'],'capacity' if mode=='weekly' else 'capacity_machines')
        gen=c.execute("SELECT * FROM planning_mtg.raw_generations WHERE dataset=%s AND metadata->>'source_fingerprint'=%s ORDER BY id DESC LIMIT 1",('capacity_items:'+area,aggregate['metadata']['source_fingerprint'])).fetchone()
        base,args=query.source(gen)
        fields,expressions=query.field_expressions(c,area,'capacity_items')
        where,params=query.predicates({'q':p.get('q'),'filters':[f for f in filters if f.get('field') in fields]},fields,expressions)
        scoped=base+' AND '+where
        stats=c.execute("SELECT count(*) FILTER(WHERE c.values_json->>'primary_operation'='true') primary_operations,count(*) FILTER(WHERE c.values_json->>'primary_operation'='false') additional_operations,count(*) FILTER(WHERE c.values_json->>'primary_operation'='true' AND c.values_json->>'reference_hours' IS NOT NULL) reference_known,sum((c.values_json->>'reference_hours')::numeric) FILTER(WHERE c.values_json->>'primary_operation'='true') reference_hours"+scoped,args+params).fetchone()
        unscheduled=c.execute("SELECT count(*) n"+base+" AND c.values_json->>'year' IS NULL",args).fetchone()['n']
    result.update(totals=needs.serial(stats),unscheduled_operations=unscheduled)
    result.update(year=y,week=w,mode=mode,timezone=planning.settings.display_timezone)
    return result


def pieces(p):
    filters=[]
    if p.get('bucket_key'):filters.append({'field':'bucket_key','op':'eq','value':p['bucket_key']})
    elif p.get('machine_key'):filters.append({'field':'machine_key','op':'eq','value':p['machine_key']})
    else:raise planning.PlanningError('Seleciona uma máquina ou período.')
    if p.get('primary_only'):filters.append({'field':'primary_operation','op':'eq','value':True})
    with planning.connect(readonly=True) as c:
        # The item generation is pinned to the aggregate generation shown to the user.
        aggregate=query.generation(c,p.get('area','perfis'),p.get('version'),p.get('dataset','capacity'))
        item=c.execute("SELECT id FROM planning_mtg.raw_generations WHERE dataset=%s AND metadata->>'source_fingerprint'=%s ORDER BY id DESC LIMIT 1",('capacity_items:'+p.get('area','perfis'),aggregate['metadata']['source_fingerprint'])).fetchone()
        if not item:raise planning.PlanningError('Esta versão de suporte expirou. Atualiza a página.',409)
        return query.listing({**p,'dataset':'capacity_items','version':str(item['id']),'filters':filters,'order':[{'field':'of','direction':'asc'},{'field':'component_ref','direction':'asc'}]},c)


def evidence(p):
    area=planning.check_area(p.get('area','perfis'))
    with planning.connect(readonly=True) as c:
        src=workbooks.source(c,area)
        gen=query.generation(c,area,p.get('version'),p.get('dataset','capacity'))
        if src['snapshot_id']!=gen['metadata'].get('snapshots',{}).get(area):
            # Locate the retained exact workbook of this generation, not today's file.
            frozen=c.execute('SELECT * FROM planning_mtg.raw_workbook_evidence WHERE snapshot_id=%s',(gen['metadata'].get('snapshots',{}).get(area),)).fetchone()
            if not frozen:raise planning.PlanningError('Evidência desta versão indisponível. Atualiza a página.',409)
            src=needs.serial(frozen)
        selected=p.get('sheet');allowed=workbooks.SHEETS[area]
        if selected and selected not in allowed:raise planning.PlanningError('Folha desconhecida.')
        return {**src,'sheets':{k:v for k,v in src['sheets'].items() if not selected or k==selected},'notice':'Valores guardados e fórmulas originais. Sem execução de VBA. Células manuais não são capacidades confirmadas.'}


def proposals():
    output=[]
    with planning.connect(readonly=True) as c:
        sources={a:workbooks.source(c,a) for a in planning.AREAS}
        calendars,rates,_=calc.workbook_index(sources)
        for (a,m,y,w),items in calendars.items():
            for row in items:
                output.append({'kind':'calendar','area':a,'machine':m,'conflict':len(items)>1,'provenance':row,'definition':{'year':y,'week':w,'shifts':row['shifts'],'hours_per_shift':row['hours_per_shift'],'exception_hours':0,'confirmed':False,'source':f"{row['source']['snapshot']} · PlanDisponibilidadeSemanal!{row['source']['row']}"}})
        for (a,m),rate in rates.items():
            if not rate['value']:continue
            output.append({'kind':'rate','area':a,'machine':m,'provenance':rate,'definition':{'area':a,'operation':'corte','method':'area_hour','value':rate['value'],'valid_from':None,'setup_minutes':0,'confirmed':False,'source':f"{rate['source']['snapshot']} · CapacidadeMáquinas!{rate['source']['cell']}"}})
        snap=planning.snapshot(c,'cantoneiras')
        for r in c.execute("""SELECT cutting_machine machine,row_data->>'1ª Oper.' operation,material_type,profile_type,
          row_data->>'Mt\\h' speed,count(*) n FROM raw_mtg.plan_production_rows WHERE snapshot_id=%s
          GROUP BY 1,2,3,4,5""",(snap['snapshot_id'],)).fetchall():
            rate=calc.number(r['speed'])
            if rate is None or rate<=0:continue
            output.append({'kind':'rate','area':'cantoneiras','machine':r['machine'],'provenance':{'snapshot':snap['snapshot_id'],'rows':r['n'],'speed':rate},'definition':{'area':'cantoneiras','operation':r['operation'],'material_type':r['material_type'],'profile':r['profile_type'],'method':'metres_hour','value':rate,'valid_from':None,'setup_minutes':0,'confirmed':False,'source':snap['snapshot_id']+' · velocidade das linhas ('+str(r['n'])+')'}})
    return needs.serial({'proposals':output,'notice':'Escolhe uma sugestão e confirma recurso, âmbito, unidades e vigência. Alternativas E/F e auxiliares XP/Rapid não são aplicadas automaticamente.'})


def reference_definition(c,p):
    area=planning.check_area(p.get('area','perfis'))
    try:y=int(p['year']);w=int(p['week']);date.fromisocalendar(y,w,1)
    except (KeyError,ValueError,TypeError):raise planning.PlanningError('Escolhe semana e ano válidos.')
    gen=query.generation(c,area,p.get('version'),'capacity')
    if gen['id']!=query.generation(c,area,dataset='capacity')['id']:raise planning.PlanningError('A disponibilidade mudou. Atualiza antes de guardar a referência.',409)
    configurations=c.execute("SELECT * FROM planning_mtg.raw_objects WHERE kind IN ('resource','calendar','rate','period','worked_hours') AND NOT archived ORDER BY id").fetchall()
    if gen['metadata'].get('configuration_digest')!=needs.digest(needs.serial(configurations)):raise planning.PlanningError('A configuração mudou. Aguarda o recálculo e atualiza a página.',409)
    for a in planning.AREAS:
        planned=query.generation(c,a)
        if str(planned['metadata'].get('core_generation',planned['id']))!=gen['metadata']['planning_versions'].get(a) or planned['metadata'].get('core_source_fingerprint',planned['metadata'].get('source_fingerprint'))!=projection.fingerprint(c,a):raise planning.PlanningError('As peças mudaram. Aguarda o recálculo e atualiza a página.',409)
    item_gen=c.execute("SELECT * FROM planning_mtg.raw_generations WHERE dataset=%s AND metadata->>'source_fingerprint'=%s ORDER BY id DESC LIMIT 1",('capacity_items:'+area,gen['metadata']['source_fingerprint'])).fetchone()
    if not item_gen:raise planning.PlanningError('Peças da versão indisponíveis.',409)
    base,args=query.source(item_gen)
    base+=" AND c.values_json->>'year'=%s AND c.values_json->>'week'=%s AND c.values_json->>'area'=%s";args += [str(y),str(w),area]
    if p.get('machine_key'):base+=" AND c.values_json->>'machine_key'=%s";args.append(p['machine_key'])
    rows=c.execute('SELECT c.detail,c.values_json'+base+' ORDER BY m.row_key',args).fetchall()
    if not rows:raise planning.PlanningError('Não existem operações neste período para guardar como referência.')
    frozen=[{**r['detail'],'values':r['values_json']} for r in rows]
    return needs.serial({'area':area,'year':y,'week':w,'machine_key':p.get('machine_key'),'capacity_generation':str(gen['id']),'sources':gen['metadata'],'rows':frozen,'quantity_unit':'un.','notice':'Referência do plano neste momento; não comprova que era o plano vigente antes da gravação.'})


def reference_preview(p):
    with planning.connect(readonly=True) as c:d=reference_definition(c,p)
    known=[r['values']['quantity'] for r in d['rows'] if r['values']['quantity'] is not None]
    return {'token':needs.digest(d),'count':len(d['rows']),'known':len(known),'quantity':sum(known),'examples':d['rows'][:20],'notice':d['notice']}


def save_reference(p):
    with planning.connect() as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        _,_,prior=needs.command(c,p)
        if prior:return prior
        if p.get('confirmed') is not True:raise planning.PlanningError('Confirma as peças e quantidades da referência semanal.')
        d=reference_definition(c,p)
        if p.get('token')!=needs.digest(d):raise planning.PlanningError('A referência mudou. Repete a comparação.',409)
        d['recorded_at']=datetime.now(ZoneInfo('UTC')).isoformat()
        result=objects.save({'request_id':str(uuid.uuid5(needs.uid(p['request_id']),'reference')),'id':p.get('id'),'expected_revision':p.get('expected_revision',0),'area':d['area'],'name':p.get('name') or f"Plano W{d['week']:02}/{d['year']}",'definition':d},'week_reference',c)
        return needs.finish(c,p,{'id':result['id'],'revision':result['revision'],'count':len(d['rows'])})


def references(area):
    with planning.connect(readonly=True) as c:
        return needs.serial({'items':c.execute("SELECT id,name,area,revision,created_at,definition->>'year' year,definition->>'week' week,definition->>'machine_key' machine_key,jsonb_array_length(definition->'rows') lines FROM planning_mtg.raw_objects WHERE kind='week_reference' AND area=%s AND NOT archived ORDER BY updated_at DESC",(planning.check_area(area),)).fetchall()})


def compliance(p):
    with planning.connect(readonly=True) as c:
        ref=objects.get(p['id'],c)
        if ref['kind']!='week_reference':raise planning.PlanningError('Referência semanal desconhecida.')
        rev=int(p.get('revision') or ref['revision'])
        old=c.execute('SELECT definition FROM planning_mtg.raw_object_versions WHERE object_id=%s AND revision=%s',(ref['id'],rev)).fetchone()
        if not old:raise planning.PlanningError('Revisão não encontrada.',404)
        d=old['definition'];area=d['area'];start=date.fromisocalendar(d['year'],d['week'],1)
        gen=query.generation(c,area,dataset='production');base,args=query.source(gen)
        base+=" AND (c.values_json->>'production_date')::date >= %s AND (c.values_json->>'production_date')::date < %s::date + 7";args += [start,start]
        events=[{**r['detail'],'values':r['values_json']} for r in c.execute('SELECT c.detail,c.values_json'+base,args).fetchall()]
        current=query.generation(c,area);base,args=query.source(current)
        search_keys=list({str(k) for r in d['rows'] for k in [r['planning_key'],r.get('need_id'),*(r.get('aliases') or [])] if k})
        base+=" AND (m.row_key=ANY(%s) OR coalesce(c.detail->'selection_aliases','[]') ?| %s)";args += [search_keys,search_keys]
        current_rows=[{'key':r['row_key'],'values':r['values_json'],'selection_aliases':r['aliases']} for r in c.execute("SELECT m.row_key,c.values_json,c.detail->'selection_aliases' aliases"+base,args).fetchall()]
    by_key={}
    for r in current_rows:
        for k in [r['key'],*(r.get('selection_aliases') or [])]:by_key.setdefault(k,[]).append(r)
    rows=[];index={}
    for item in d['rows']:
        keys=list(dict.fromkeys([item['planning_key'],item.get('need_id'),*(item.get('aliases') or [])]));keys=[k for k in keys if k]
        current_matches={r['key']:r for k in keys for r in by_key.get(k,[])}
        valid=len(current_matches)==1 and needs.signature(next(iter(current_matches.values()))['values'])==item['technical_signature']
        result={'key':item['key'],'of':item['values']['of'],'reference':item['values']['component_ref'],'operation':item['values']['operation'],'planned':item['values']['quantity'],'produced':None,'fulfilled':None,'evidence':[],'compatibility':valid}
        rows.append(result)
        if valid:
            keys += list(current_matches)
            for k in set(keys):index.setdefault((k,result['operation']),[]).append(result)
    outside=[];unmatched=[]
    for e in events:
        v=e['values'];candidates={r['key']:r for k in e.get('planning_keys',[]) for r in index.get((k,v.get('operation')),[])}
        if len(candidates)==1 and v.get('association_status') in ('associated','explicit','technical_unique'):
            r=next(iter(candidates.values()));r['evidence'].append(e)
        elif not candidates and e.get('planning_keys') and not set(e['planning_keys']).intersection(search_keys):outside.append(e)
        else:unmatched.append(e)
    known_plan=known_fulfilled=0;covered=0
    for r in rows:
        if not r['evidence']:continue
        quantities=[e['values'].get('quantity') for e in r['evidence']]
        if all(q is not None and q>=0 for q in quantities):r['produced']=sum(quantities)
        if r['planned'] is not None and r['produced'] is not None:
            r['fulfilled']=min(r['planned'],r['produced']);known_plan+=r['planned'];known_fulfilled+=r['fulfilled'];covered+=1
    page=max(1,int(p.get('page',1)));size=100
    return needs.serial({'reference':{k:ref[k] for k in ('id','name','created_at')},'revision':rev,'year':d['year'],'week':d['week'],'rows':rows[(page-1)*size:page*size],'total':len(rows),'page':page,
        'production_generation':str(gen['id']),'coverage':{'known':covered,'total':len(rows),'planned':known_plan,'fulfilled':known_fulfilled,'percent':100*known_fulfilled/known_plan if known_plan>0 else None},'outside_plan':{'records':len(outside),'quantity_known':sum(e['values']['quantity'] for e in outside if e['values'].get('quantity') is not None),'quantity_unknown':sum(e['values'].get('quantity') is None for e in outside)},'unmatched_records':len(unmatched),'outside_evidence':outside[:100],'unmatched_evidence':unmatched[:100],'notice':d['notice']+' Ausência de OCR não significa zero. O avanço apresentado abrange apenas identidades e quantidades compatíveis.'})
