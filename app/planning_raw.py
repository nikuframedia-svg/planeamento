"""RAW projection. Immutable sources plus audited common preparation decisions."""
from __future__ import annotations
import math
import threading
import time
import uuid
from collections import OrderedDict, defaultdict
from datetime import date
from . import planning, planning_needs as needs, planning_catalogs as catalogs, planning_hub as hub
from .dossiers.models import order_number
from . import planning_population as population, planning_order_population
# O leitor de números é o de toda a app, com milhares por espaço («1 200»; 08/10, F19).
from .planning_calculations import number

# The attachment's A:AP order is a public presentation contract.
SPECS=[
 ('id','ID','identity',None),('customer','Cliente','identity',None),('designation','Descrição da obra','identity',None),('ov','OV','identity',None),('of','OF','identity',None),
 ('cut_date','Data de corte','identity','date'),('delivery_date','Data de entrega','identity',None),('picking_week','Semana de picking','identity','number'),('team','Equipa','identity','select'),('pavilion','Pavilhão','identity','text'),('component_ref','Referência','identity','text'),('description','Descrição do perfil','identity',None),('notes','Observações locais','identity','text'),('abocardar','Abocardar','identity','checkbox'),
 ('quantity_required','Quantidade total necessária','quantity','number'),('cut','Cortada · macro','quantity',None),('boc','Abocardada · macro','quantity',None),('cut_pct','% cortada','quantity',None),('boc_pct','% abocardada','quantity',None),('final_pct','% operação final','quantity',None),('remaining','Por cortar','quantity',None),('boc_remaining','Por abocardar','quantity',None),
 ('material_type','Tipo de perfil nível 1','technical','select'),('profile','Tipo de perfil nível 2','technical','select'),('outer_diameter_mm','Diâmetro (mm)','technical','number'),('width_mm','Largura (mm)','technical','number'),('height_mm','Altura (mm)','technical','number'),('thickness_mm','Espessura (mm)','technical','number'),('length_mm','Comprimento (mm)','technical','number'),('angle_deg','Ângulo (°)','technical','number'),('grade','Qualidade','technical','text'),('section_total','Área total das secções (mm²)','technical',None),
 ('machine','Máquina de corte','work','select'),('expected_date','Data prevista de execução','work','date'),('quantity_to_plan','Quantidade prevista','work',None),('hours_pct','% horas consumidas','work',None),('expected_week','Semana prevista','work',None),('weight','Peso a produzir (kg)','work',None),
 ('material_requested','Requisitado?','material','tristate'),('total_length','Comprimento total necessário (mm)','material',None),('stock_length_mm','Comprimento unitário considerado (mm)','material','number'),('bars','Estimativa de perfis inteiros','material',None)]
EDITABLE={x[0] for x in SPECS if x[3]}|{'picking_year','custom_profile','special_profile','geometry','identity_discriminator'}
_cache=OrderedDict();_lock=threading.Lock()


def columns():
    cat=catalogs.catalog('perfis')
    units={f['id']:f.get('unit') for f in cat['fields']}
    units.update({k:'un.' for k in ('cut','boc','remaining','boc_remaining','bars')})
    units.update({k:'%' for k in ('cut_pct','boc_pct','final_pct','hours_pct')})
    units.update(section_total='mm²',weight='kg',total_length='mm')
    return {'columns':[dict(id=k,label=l,group=g,type=t or 'readonly',editable=bool(t),unit=units.get(k)) for k,l,g,t in SPECS], 'catalog':cat}


def calculated(v,raw,compatible=True):
    """Never interpret absence as zero; imported facts remain independently visible."""
    v=dict(v);q=number(v.get('quantity_required'));length=number(v.get('length_mm'))
    if q is not None and (q<0 or not q.is_integer()):q=None;v['quantity_required']=None
    cut=number(raw.get('Ser.'));boc=number(raw.get('Aboc.'))
    if cut is not None and (cut<0 or not cut.is_integer()):cut=None
    if boc is not None and (boc<0 or not boc.is_integer()):boc=None
    mark=v.get('abocardar');yes=mark in ('X','Sim',True);no=mark in ('-',False)
    v.update(cut=cut,boc=boc)
    v['cut_pct']=100*cut/q if compatible and q and q>0 and cut is not None else None
    v['boc_pct']=100*boc/q if compatible and yes and q and q>0 and boc is not None else None
    v['final_pct']=v['boc_pct'] if yes else v['cut_pct'] if no else None
    v['boc_remaining']=max(q-boc,0) if compatible and yes and q is not None and boc is not None else None
    v['total_length']=q*length if q is not None and length is not None else None
    v['section_unit']=number(raw.get('Área de Seção de Corte Unit. [mm2]')) if compatible else None
    v['section_total']=number(raw.get('Área de Seção de Corte [mm2]')) if compatible else None
    if v['section_unit'] is not None and v['section_unit']<=0:v['section_unit']=None
    if v['section_total'] is not None and (v['section_total']<0 or (q and v['section_total']==0)):v['section_total']=None
    if v['section_unit'] is None:
        family=catalogs.key(v.get('material_type'));diam=number(v.get('outer_diameter_mm'));w=number(v.get('width_mm'));h=number(v.get('height_mm'));t=number(v.get('thickness_mm'))
        if family=='varão redondo' and diam and diam>0:v['section_unit']=math.pi*diam*diam/4
        elif family=='varão quadrado' and w and w>0:v['section_unit']=w*w
        elif family=='varão retangular' and w and h and min(w,h)>0:v['section_unit']=w*h
        elif family=='tubo redondo' and diam and t and 0<2*t<diam:v['section_unit']=math.pi*(diam*diam-(diam-2*t)**2)/4
    if v['section_unit'] is not None and q is not None:v['section_total']=v['section_unit']*q
    v['weight']=number(raw.get('Peso Previsto [kg]')) if compatible else None
    hp=number(raw.get('Percentual de Horas Consumidas'));v['hours_pct']=hp*100 if hp is not None and compatible else None
    try:
        year,week,_=date.fromisoformat(str(v.get('expected_date'))[:10]).isocalendar();v['expected_week']=f'{year}-W{week:02}'
    except ValueError:v['expected_week']=None
    stock=number(v.get('stock_length_mm'));balance=number(v.get('remaining'))
    pieces=math.floor(stock/length) if stock and length and length>0 else 0
    v['bars']=math.ceil(balance/pieces) if pieces>0 and balance is not None and balance>=0 else None
    v['description']=' · '.join(str(v[k]) for k in ('material_type','profile','grade') if v.get(k))
    for key,label,unit in [('outer_diameter_mm','Ø','mm'),('width_mm','L','mm'),('height_mm','A','mm'),('thickness_mm','e','mm'),('length_mm','Comp.','mm'),('angle_deg','Âng.','°')]:
        if v.get(key) is not None:v['description']+=f' · {label} {v[key]} {unit}'
    return v


def dataset(version=None, force=False):
    with _lock:
        if version:
            if version not in _cache:raise planning.PlanningError('Esta versão expirou. Atualiza a lista após guardar as alterações.',409)
            return _cache[version][1]
        if not force and _cache:
            stamp,data=next(reversed(_cache.values()))
            if time.monotonic()-stamp<20:return data
    with planning.connect(readonly=True) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        snap=planning.snapshot(conn,'perfis');direct=hub._direct_version(conn)
        cpis=defaultdict(list)
        for r in hub._order_rows(conn,direct,'',None):cpis[order_number(r['production_order_no'])].append(r)
        contexts={k:hub._order_summary(v) for k,v in cpis.items()}
        lines=conn.execute('''SELECT r.*,p.remaining_quantity canonical_remaining,p.remaining_valid,
            NULL::text cpis_status,NULL::date cpis_delivery_date,NULL::date cpis_planned_finish_date
            FROM raw_mtg.plan_production_rows r LEFT JOIN analytics_mtg.kanban_plan_lines p
            ON p.snapshot_id=r.snapshot_id AND p.plan_key=r.source_line_id
            WHERE r.snapshot_id=%s ORDER BY r.excel_row''',(snap['snapshot_id'],)).fetchall()
        ns={str(n['id']):n for n in conn.execute('SELECT * FROM planning_mtg.needs').fetchall()}
        links=defaultdict(list)
        for s in conn.execute('SELECT * FROM planning_mtg.need_sources').fetchall():
            links[str(s['need_id'])].append(s)
        members,_=planning_order_population.read(conn,{'ds-met2-perfis':snap})
        by_plan={source_key:m['need_id'] for m in members
                 if m['area']=='perfis' and m['need_id']
                 for source_key in m['source_keys']}
        records=defaultdict(list)
        for r in conn.execute("SELECT * FROM planning_mtg.records WHERE area='perfis' AND need_id IS NOT NULL").fetchall():records[str(r['need_id'])].append(r)
        grouped=defaultdict(list)
        for line in lines:grouped[by_plan.get(line['source_line_id']) or 'macro:'+line['source_line_id']].append(line)
        for nid in records:grouped.setdefault(nid,[])
        output=[]
        for key,origins in grouped.items():
            need=ns.get(key);line=origins[0] if len(origins)==1 else None
            raw=line['row_data'] if line else {}
            values=planning.line_data(line,'perfis',{})['values'] if line else {}
            original=dict(values);warn=[]
            values['picking_week']=number(raw.get('Picking'))
            if values['picking_week'] is not None and not 1<=values['picking_week']<=53:values['picking_week']=None
            values['stock_length_mm']=number(raw.get('comp.per. utilizar (mm)'))
            values['quantity_to_plan']=number(raw.get('Quantidade Prevista'))
            values['material_requested']=None
            operation=None
            if need:
                values.update(need['specification'])
                corte=[r for r in records[key] if r['values_json'].get('operation')=='corte']
                if len(corte)==1:values.update(corte[0]['values_json']);values.update(need['specification']);operation=corte[0]['operation_id']
                if values.get('quantity_to_plan') is None:values['quantity_to_plan']=number(raw.get('Quantidade Prevista'))
            compatible=not need or bool(line and needs.signature(original)==needs.signature(need['specification']) and original.get('quantity_required')==need['quantity_required'])
            values['remaining']=number(line['canonical_remaining']) if line and line['remaining_valid'] and compatible else None
            if need and operation:
                from . import planning_associations as associations
                proof=associations.evidence(conn,need,{'id':operation,'area':'perfis','code':'corte'})
                conference=associations.current_conference(conn,need,{'id':operation},proof)
                if conference:values['remaining']=conference['accepted_remaining']
            if not compatible:
                values['quantity_to_plan']=None
                warn.append('Conferir compatibilidade com a macro.')
            if len(origins)>1:warn.append('Várias linhas de origem: valores não agregados automaticamente.')
            if any(isinstance(v,str) and v.startswith('#') for v in raw.values()):warn.append('A origem contém erros Excel; consulta os valores originais.')
            of=need['production_order_no'] if need else order_number(line['production_order_no'])
            context=contexts.get(of,{})
            if context.get('conflicts'):warn.append('Existem diferenças entre as cópias CPIS.')
            values.update(id=line.get('external_row_number') if line else 'Local '+key[:8],of=of,ov=', '.join(context.get('ovs',[])),customer=context.get('customer_name'),designation=context.get('observations'),delivery_date=context.get('delivery_date'))
            values=calculated(values,raw,compatible)
            if any(values.get(k) is not None and values[k]>100 for k in ('cut_pct','boc_pct')):warn.append('Produção superior à quantidade necessária.')
            if values.get('boc') is not None and values.get('cut') is not None and values['boc']>values['cut']:warn.append('Abocardado superior ao cortado.')
            output.append(dict(key=key,need_id=key if need else None,revision=need['revision'] if need else 0,values=values,original=original,raw=raw,warnings=warn,status=context.get('cpis_status'),status_values=context.get('status_values',[]),origin='local' if need else 'macro',sources=links.get(key,[]),plan_key=line['source_line_id'] if line else None,operation_id=operation,macro_closure_values=[value for origin in origins for value in (origin.get('closed_x'),(origin.get('row_data') or {}).get('Fechado'))]))
            population.annotate(output[-1])
        enrich_ocr(conn,output,snap['snapshot_id'])
        data=needs.serial({'rows':output,'snapshot':snap,'cpis_version':str(direct['id']) if direct else hub._fallback_token(hub._latest_snapshots(conn)),'cpis_mode':('CPIS direto · confirmado' if hub._fresh(direct['last_confirmed_at']) else 'CPIS direto · confirmação atrasada') if direct else 'CPIS importado da macro — sem confirmação direta','cpis_checked_at':direct['last_confirmed_at'] if direct else None,'display_timezone':planning.settings.display_timezone})
    data['version']=needs.digest(data)
    with _lock:
        _cache[data['version']]=(time.monotonic(),data)
        while len(_cache)>6:_cache.popitem(last=False)
    return data


def filtered(data,params):
    rows=[r for r in data['rows'] if population.includes(r,params.get('population'))];q=str(params.get('q','')).casefold()
    if q:rows=[r for r in rows if q in ' '.join(str(r['values'].get(k) or '') for k in ('of','ov','customer','designation','component_ref')).casefold()]
    state=params.get('state')
    if state and state!='all':rows=[r for r in rows if any(s in hub.OPEN_STATES for s in r.get('status_values',[r['status']]))] if state=='open' else [r for r in rows if r['status']==state]
    for field in ('machine','material_type'):
        if params.get(field):rows=[r for r in rows if r['values'].get(field)==params[field]]
    if params.get('origin'):rows=[r for r in rows if r['origin']==params['origin']]
    if params.get('pending'):rows=[r for r in rows if r['warnings'] or any(r['values'].get(k) in (None,'') for k in ('machine','remaining','length_mm'))]
    sort=params.get('sort','of')
    if sort not in {s[0] for s in SPECS}:raise planning.PlanningError('Coluna de ordenação inválida.')
    def sortable(r):
        v=r['values'].get(sort)
        return (v is None,0 if isinstance(v,(int,float)) else 1,v if isinstance(v,(int,float)) else str(v or ''),r['key'])
    return sorted(rows,key=sortable,reverse=params.get('direction')=='desc')


def listing(params):
    data=dataset(params.get('version'),force=params.get('refresh')=='1');rows=filtered(data,params)
    try:page=max(1,int(params.get('page',1)))
    except ValueError:raise planning.PlanningError('Página inválida.')
    return {**{k:v for k,v in data.items() if k!='rows'},'rows':rows[(page-1)*100:page*100],'total':len(rows),'page':page}


def update(key,payload):
    changes=payload.get('values') or {}
    if not isinstance(changes,dict) or not changes or set(changes)-EDITABLE:raise planning.PlanningError('Só podes alterar os campos locais de preparação.')
    with planning.connect() as conn:
        _,_,old=needs.command(conn,payload)
        if old:return old
        olddata=dataset(payload.get('version'));current=dataset(force=True)
        if olddata['version']!=current['version']:raise planning.PlanningError('As fontes mudaram. Atualiza a lista antes de guardar.',409)
        row=next((r for r in current['rows'] if r['key']==key),None)
        if not row:raise planning.PlanningError('Linha não encontrada.',404)
        if payload.get('expected_revision')!=row['revision']:raise planning.PlanningError('A linha mudou. Reabre a ficha.',409)
        if not row['need_id']:
            resolved=needs.resolve({'request_id':str(uuid.uuid5(needs.uid(payload['request_id']),'resolve')),'area':'perfis','source':{'kind':'plan_line','id':row['plan_key'],'version':current['snapshot']['snapshot_id']}},conn=conn)
            if resolved.get('needs_decision'):raise planning.PlanningError('Há peças semelhantes. Abre o formulário para escolher a associação.',409)
        else:resolved={'need_id':row['need_id'],'revision':row['revision']}
        cat=catalogs.catalog('perfis',conn)
        vals={k:v for k,v in row['values'].items() if k in {f['id'] for f in cat['fields']}}
        defaults=dict(vals);vals=dict(changes);vals['operation']='corte'
        result=needs.save({'request_id':str(uuid.uuid5(needs.uid(payload['request_id']),'save')),'area':'perfis','need_id':resolved['need_id'],'expected_revision':resolved['revision'],'catalog_version':cat['version'],'values':vals,'record_status':'draft'},conn=conn,source_defaults=defaults)
        return needs.finish(conn,payload,result)


def enrich_ocr(conn,rows,snapshot_id):
    """Batch-load validated facts; reuse the historical identity and operation rules."""
    from . import planning_production, planning_associations as assoc
    produced=conn.execute("""SELECT p.id,p.sheet_uid,v.source_app,p.row_index,p.sheet_date,
        p.validated_at,p.machine,p.model_ref,p.quantity,p.length_mm,p.profile_type,
        p.matched_plan_key,p.plan_snapshot_id,p.extra,p.full_profile,v.cross_check,p.production_order
        FROM mes_kanban.production_records p JOIN mes_kanban.validated_sheets v USING(sheet_uid)
        WHERE v.source_app='kanban-mes-mtg2' ORDER BY p.id""").fetchall()
    refs=defaultdict(list)
    if produced:
        for r in conn.execute('SELECT * FROM mes_kanban.production_record_plan_refs WHERE production_record_id=ANY(%s)',([r['id'] for r in produced],)).fetchall():refs[r['production_record_id']].append(r)
    decided={r['production_record_id'] for r in conn.execute('SELECT DISTINCT production_record_id FROM planning_mtg.association_decisions').fetchall()}
    by_of=defaultdict(list);history=defaultdict(list)
    keys=list({r['matched_plan_key'] for r in produced if r.get('matched_plan_key')})
    if keys:
        for r in conn.execute('SELECT plan_key,source_app,production_order_no,component_ref,profile_type,length_mm FROM analytics_mtg.kanban_plan_lines WHERE plan_key=ANY(%s)',(keys,)).fetchall():history[r['plan_key']].append(r)
    for r in produced:
        check=next((c for c in (r.pop('cross_check') or {}).get('rows',[]) if c.get('row_index')==r['row_index']),{})
        r['frozen_identity']=check.get('plan_identity') or {}
        r['plan_refs']=refs[r['id']] or check.get('plan_refs') or []
        if not r['frozen_identity'] and not (r.get('extra') or {}).get('plan_identity'):
            old=history[r.get('matched_plan_key')]
            if len(old)==1 and old[0]['source_app']==r['source_app']:r['frozen_identity']=old[0]
        if r['id'] not in decided:by_of[order_number(r['production_order'])].append(r)
    plans=defaultdict(list);indexed={}
    for row in rows:
        row['values']['ocr_cut']=None;row['values']['ocr_boc']=None;row['ocr_evidence']={}
        if not row['plan_key']:continue
        v=row['values'];original=row['original']
        p=dict(source_app='kanban-mes-mtg2',plan_key=row['plan_key'],component_ref=original.get('component_ref'),profile_type=original.get('profile'),length_mm=original.get('length_mm'),quantity_planned=original.get('quantity_required'),operation_inputs=row['raw'],remaining_quantity=v.get('remaining'),remaining_valid=v.get('remaining') is not None)
        plans[v['of']].append(p);indexed[row['plan_key']]=p
    for of,items in plans.items():
        facts=by_of.get(of,[]);hub._production_associations(facts,items);planning_production.attach_operation_evidence(items,facts)
    for row in rows:
        if not row['need_id']:
            for op in indexed.get(row['plan_key'],{}).get('operations',[]):
                target={'corte':'ocr_cut','abocardar':'ocr_boc'}.get(op['operation'])
                if target:row['values'][target]=op['ocr_quantity'];row['ocr_evidence'][target]=op['ocr_records']
            continue
        need=needs.load(conn,row['need_id'])
        for op in conn.execute("SELECT * FROM planning_mtg.need_operations WHERE need_id=%s AND area='perfis'",(need['id'],)).fetchall():
            target={'corte':'ocr_cut','abocardar':'ocr_boc'}.get(op['code'])
            if not target:continue
            proof=assoc.evidence(conn,need,op)
            row['values'][target]=proof['ocr_quantity'];row['ocr_evidence'][target]=proof['ocr_records']
            row['warnings'].extend(proof['warnings'])
