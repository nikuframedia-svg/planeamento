"""Persistent, content-addressed query generations. Only the worker reads full macros."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import json,hashlib
from psycopg.types.json import Jsonb
from .. import planning, planning_needs as needs, planning_hub as hub, planning_raw as old, planning_catalogs as catalogs, planning_dates
from ..dossiers.models import order_number
from .. import planning_population as population

RAW_CONTRACT='raw-workspace-20260925-integral-v26'

def serialized_digest(value):
    """Same digest for an already JSON-normalized value, without a round trip."""
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def member_dependencies(dataset,row):
    if not dataset.startswith('planning:'):return None,None,None
    value=row['values'].get('planning_active')
    active=True if value is True or value=='true' else False if value is False or value=='false' else population.classify(row)['active']
    machine=row['values'].get('machine')
    return str(machine) if machine is not None else '',active,row['values'].get('of')


def signal(conn,topic='planning'):
    if conn.execute("SELECT to_regclass('planning_mtg.raw_signals') t").fetchone()['t']:
        conn.execute('INSERT INTO planning_mtg.raw_signals(topic) VALUES(%s) ON CONFLICT(topic) DO UPDATE SET revision=raw_signals.revision+1,changed_at=now()',(topic,))
        conn.execute("SELECT pg_notify('planning_raw_changed',%s)",(topic,))



def mark_aggregates_pending(conn,request_id,*,source_failures=(),only_if_needed=False):
    """Configuration writes invalidate aggregates without rereading macro rows."""
    from . import query
    for area in planning.AREAS:
        try:gen=query.generation(conn,area)
        except planning.PlanningError as exc:
            if exc.status==503:continue
            raise
        meta=gen['metadata']
        failed=area in source_failures or bool(meta.get('source_refresh_pending'))
        if only_if_needed and meta.get('aggregates_pending') and (not area in source_failures or meta.get('source_refresh_pending')):continue
        metadata={**meta,'core_source_fingerprint':meta.get('core_source_fingerprint',meta['source_fingerprint']),
            'core_generation':meta.get('core_generation',str(gen['id'])),'aggregates_pending':True,'source_refresh_pending':failed}
        publish_delta(conn,'planning:'+area,needs.digest(['configuration-pending',request_id,area]),[],metadata,expected_generation=gen['id'])

def fingerprint(conn,area,*,include_ocr=True):
    from ..planning_calculations import CONTRACT as calculation_contract
    from .capacity import ESTIMATE_CONTRACT
    snap=planning.snapshot(conn,area)
    direct=hub._direct_version(conn)
    pieces=conn.execute("SELECT coalesce(md5(string_agg(id::text||':'||revision::text,',' ORDER BY id)),'') f FROM planning_mtg.needs").fetchone()['f']
    decisions={}
    if conn.execute("SELECT to_regclass('planning_mtg.raw_objects') t").fetchone()['t']:
        decisions['periods']=conn.execute("SELECT md5(coalesce(string_agg(t::text,'' ORDER BY t.id),'')) f FROM planning_mtg.raw_objects t WHERE kind='period'").fetchone()['f']
    from .. import planning_associations as assoc
    tables=['association_decisions','need_conferences']
    if assoc.original_decisions_available(conn):tables.append('original_association_decisions')
    for table in tables:
        decisions[table]=conn.execute('SELECT md5(coalesce(string_agg(t::text,\'\' ORDER BY t.id),\'\')) f FROM planning_mtg.'+table+' t').fetchone()['f']
    base={'contract':RAW_CONTRACT,'day':datetime.now(ZoneInfo(planning.settings.display_timezone)).date().isoformat(),'snapshot':snap['snapshot_id'],'cpis':str(direct['id']) if direct else hub._fallback_token(hub._latest_snapshots(conn)),'pieces':pieces,'decisions':decisions}
    from .registration import enabled as free_entry
    base['free_registration']=free_entry()
    from . import sku_families
    base['sku_family_rules']=sku_families.token(conn,area)
    base['calculation_contract']=calculation_contract
    base['operation_hours_contract']=ESTIMATE_CONTRACT
    from ..gantt import research
    if research.enabled():
        base['research_version']=research.head(conn)['version_id']
        base['research_balance_contract']=research.BALANCE_CONTRACT
    if not include_ocr:return needs.digest(base)
    from .. import planning_original_production
    base['original_ocr']=planning_original_production.snapshot_token(conn)
    production=conn.execute("SELECT md5(coalesce(string_agg(t::text,'' ORDER BY t.sheet_uid),'')) f FROM mes_kanban.validated_sheets t WHERE source_app=%s",('kanban-mes-mtg2' if area=='perfis' else 'kanban-mes',)).fetchone()['f']
    decisions['production_records']=conn.execute("SELECT md5(coalesce(string_agg(p::text,'' ORDER BY p.id),'')) f FROM mes_kanban.production_records p JOIN mes_kanban.validated_sheets v USING(sheet_uid) WHERE v.source_app=%s",('kanban-mes-mtg2' if area=='perfis' else 'kanban-mes',)).fetchone()['f']
    decisions['production_refs']=conn.execute("SELECT md5(coalesce(string_agg(r::text,'' ORDER BY r.production_record_id,r.plan_key),'')) f FROM mes_kanban.production_record_plan_refs r").fetchone()['f']
    return needs.digest({**base,'production':production})


def build_rows(conn,area,*,orders=None,facts=None):
    """Build complete OF populations, optionally only the affected orders.

    Keeping all pieces of each selected OF is essential for ambiguity checks.
    A caller must not publish a partial result as a full dataset.
    """
    if orders is not None:
        orders={order_number(of) for of in orders}
        if not orders or None in orders:raise planning.PlanningError('Indica OFs válidas para o recálculo.')
        orders=sorted(orders)
    # Proofs are immutable within this read snapshot. A prepared operation is
    # visited for its balance, its preparation and its production columns.
    proofs={};source_cache={}
    def proof_for(need,op):
        from .. import planning_associations as assoc
        key=(str(need['id']),str(op['id']))
        if key not in proofs:proofs[key]=assoc.evidence(conn,need,op,source_cache=source_cache)
        return proofs[key]
    snap=planning.snapshot(conn,area);direct=hub._direct_version(conn)
    picking_rows=conn.execute("SELECT excel_row,row_data FROM raw_mtg.other_sheet_rows WHERE snapshot_id=%s AND sheet_name='Picking' ORDER BY excel_row",(snap['snapshot_id'],)).fetchall() if area=='perfis' else []
    picking_weeks,picking_evidence=planning_dates.picking_index(picking_rows)
    contexts=defaultdict(list)
    for r in hub._order_rows(conn,direct,'',None,only_ofs=orders):contexts[order_number(r['production_order_no'])].append(r)
    contexts={k:hub._order_summary(v) for k,v in contexts.items()}
    from .. import planning_local_orders
    local_orders={r['production_order_no']:r for r in conn.execute('SELECT * FROM planning_mtg.local_orders').fetchall()} if planning_local_orders.available(conn) else {}
    # Administrative context is joined once by OF; do not fan out source lines for multiple OVs.
    lines=conn.execute('''SELECT r.*,p.remaining_quantity canonical_remaining,p.remaining_valid,
        NULL::text cpis_status,NULL::date cpis_delivery_date,NULL::date cpis_planned_finish_date
        FROM raw_mtg.plan_production_rows r LEFT JOIN analytics_mtg.kanban_plan_lines p
        ON p.snapshot_id=r.snapshot_id AND p.plan_key=r.source_line_id
        WHERE r.snapshot_id=%s''' + (" AND regexp_replace(trim(r.production_order_no),'^OF[ ._-]*','','i')=ANY(%s)" if orders is not None else '') + ' ORDER BY r.excel_row',
        (snap['snapshot_id'],[of[2:] for of in orders]) if orders is not None else (snap['snapshot_id'],)).fetchall()
    ns={str(n['id']):n for n in conn.execute('SELECT * FROM planning_mtg.needs'+(' WHERE production_order_no=ANY(%s)' if orders is not None else ''),(orders,) if orders is not None else ()).fetchall()}
    links=defaultdict(list);plan_links=defaultdict(set);records=defaultdict(list)
    for s in conn.execute('SELECT * FROM planning_mtg.need_sources').fetchall():
        if orders is not None and str(s['need_id']) not in ns:continue
        links[str(s['need_id'])].append(s)
        if s['kind']=='plan_line' and s['payload'].get('area','perfis')==area:
            try:current=needs.source_data({'kind':'plan_line','id':s['source_id']},area,conn)
            except planning.PlanningError:current=None
            if current:
                source_cache[('plan_line',s['source_id'],area)]=current
                plan_links[current['id']].add(str(s['need_id']))
    for r in conn.execute('SELECT * FROM planning_mtg.records WHERE area=%s AND need_id IS NOT NULL',(area,)).fetchall():
        if orders is None or str(r['need_id']) in ns:records[str(r['need_id'])].append(r)
    by_plan={k:next(iter(v)) for k,v in plan_links.items() if len(v)==1}
    conflicted={k for k,v in plan_links.items() if len(v)>1}
    grouped=defaultdict(list)
    for line in lines:grouped[by_plan.get(line['source_line_id']) or 'macro:'+line['source_line_id']].append(line)
    for nid in records:grouped.setdefault(nid,[])
    from . import calculations
    weight_table=calculations.weights(conn,snap['snapshot_id'])
    output=[]
    for key,origins in grouped.items():
        need=ns.get(key);line=origins[0] if len(origins)==1 else None
        raw=line['row_data'] if line else {};v=planning.line_data(line,area,picking_weeks)['values'] if line else {}
        if area=='cantoneiras':
            v.update(operation=catalogs.clean(raw.get('1ª Oper.')),operation_detail=catalogs.clean(raw.get('2ª Oper.')),material_description=planning._text(raw.get('Des. Material')),macro_closed=str(raw.get('Fechado') or '').strip(),imported_week=old.number(raw.get('W')))
        of=need['production_order_no'] if need else order_number(line['production_order_no'])
        if area=='perfis':
            v.update(planning_dates.picking_values(of,raw.get('Picking'),picking_weeks,picking_evidence))
        v['stock_length_mm']=old.number(raw.get('comp.per. utilizar (mm)'))
        v['quantity_to_plan']=old.number(raw.get('Quantidade Prevista'));v['material_requested']=None
        original=old.calculated(dict(v),raw,True)
        if line:original.update(id=line.get('external_row_number'),of=line.get('production_order_no'),ov=line.get('sales_order_no'),customer=line.get('customer_name'),designation=line.get('designation'),remaining=old.number(line['canonical_remaining']) if line['remaining_valid'] else None)
        warn=[];operation=None;status='Sem ficha de preparação';record=None
        if line and line['source_line_id'] in conflicted:warn.append('Linha da macro ligada a várias necessidades: identidade por conferir.')
        if need:
            for source in links.get(key,[]):
                if source['payload'].get('source_state')=='unavailable':warn.append(source['payload'].get('source_error') or 'Origem documental por confirmar.')
            v.update(need['specification'])
            primary=v.get('operation') if area=='cantoneiras' else 'corte'
            if area=='cantoneiras' and not primary:
                codes=[r['code'] for r in conn.execute('SELECT code FROM planning_mtg.need_operations WHERE need_id=%s AND area=%s AND sequence=1',(need['id'],area))]
                primary=codes[0] if len(codes)==1 else None
            main=[r for r in records[key] if r['values_json'].get('operation')==primary]
            from .registration import enabled as free_entry
            if free_entry() and records[key]:main=[max(records[key],key=lambda r:r['updated_at'])]
            if len(main)==1:
                record=main[0];v.update(record['values_json']);v.update(need['specification']);operation=record['operation_id'];status=record['record_status']
            elif len(main)>1:warn.append('Várias preparações de operação: consultar o detalhe antes de alterar.')
        if area=='perfis':
            # Blank saved form fields must not erase an OF-level imported Picking.
            v.update(planning_dates.picking_values(of,raw.get('Picking'),picking_weeks,
                                                   picking_evidence,record=record))
        compatible=not need or not origins or bool(line and needs.signature(original)==needs.signature(need['specification']))
        v['remaining']=old.number(line['canonical_remaining']) if line and line['remaining_valid'] and compatible else None
        if need and operation:
            from .. import planning_associations as assoc
            op={'id':operation,'area':area,'code':v.get('operation')}
            proof=proof_for(need,op);conf=assoc.current_conference(conn,need,op,proof)
            if conf:v['remaining']=conf['accepted_remaining']
            quantity_state=(record.get('provenance_json') or {}).get(str(operation)+':quantity_to_plan',{}) if record else {}
            basis=quantity_state.get('source') or {}
            if basis.get('kind')=='system' and basis.get('evidence_hash')!=proof['evidence_hash']:
                v['quantity_to_plan']=None;warn.append('Quantidade prevista a rever após alteração da evidência.')
        if need:
            from .. import planning_associations as assoc
            for preparation in records[key]:
                local=preparation['values_json'];op_id=str(preparation['operation_id'])
                valid=needs.signature(local)==needs.signature(need['specification']) and old.number(local.get('quantity_required'))==old.number(need['quantity_required'])
                basis=((preparation.get('provenance_json') or {}).get(op_id+':quantity_to_plan',{}).get('source') or {})
                if basis.get('kind')=='system':
                    evidence=proof_for(need,{'id':preparation['operation_id'],'area':area,'code':local.get('operation')})
                    valid=valid and basis.get('evidence_hash')==evidence['evidence_hash']
                preparation['capacity_compatible']=bool(valid)
        if not compatible:warn.append('Conferir compatibilidade técnica com a macro.')
        if len(origins)>1:warn.append('Várias linhas de origem: valores não agregados automaticamente.')
        if any(isinstance(x,str) and x.startswith('#') for x in raw.values()):warn.append('A origem contém erros Excel.')
        of=need['production_order_no'] if need else order_number(line['production_order_no']);ctx=contexts.get(of,{})
        if ctx.get('conflicts'):warn.append('Existem diferenças entre as cópias CPIS.')
        v.update(id=line.get('external_row_number') if line else 'Local '+key[:8],of=of,ov=', '.join(ctx.get('ovs',[])),customer=ctx.get('customer_name'),designation=ctx.get('observations'),planned_start_date=ctx.get('planned_start_date'),planned_finish_date=ctx.get('planned_finish_date'),delivery_date=ctx.get('delivery_date'),status=ctx.get('cpis_status'),preparation_status={'draft':'Rascunho','ready':'Preparada'}.get(status,status))
        if of in local_orders:
            local_context=local_orders[of]['values_json']
            for field in ('ov','customer','designation','delivery_date'):
                from .registration import enabled as free_entry
                if (free_entry() and field in local_context) or not v.get(field):v[field]=local_context.get(field)
            v['administrative_origin']='Manual local' if not ctx else 'CPIS com contexto local preservado'
        v=old.calculated(v,raw,compatible)
        if area=='cantoneiras':
            v['imported_week']=old.number(raw.get('W'))
            v['macro_closed']=str(raw.get('Fechado') or '').strip()
            q=old.number(v.get('quantity_required'));made=old.number(line.get('quantity_made')) if line else None
            if made is not None and (made<0 or not made.is_integer()):made=None
            v.update(made=made,made_pct=100*made/q if compatible and q and q>0 and made is not None else None,speed_m_h=old.number(raw.get('Mt\\h')),theoretical_hours=old.number(raw.get('h teor. Falta')) if compatible else None)
            v['weight']=old.number(raw.get('Peso em falta (kg)')) if compatible else None
        rem=old.number(v.get('remaining'));length=old.number(v.get('length_mm'))
        v['remaining_m']=rem*length/1000 if rem is not None and length is not None and length>0 else None
        if area=='cantoneiras':
            speed=old.number(raw.get('Mt\\h'))
            v['theoretical_hours']=v['remaining_m']/speed if v['remaining_m'] is not None and speed and speed>0 else None
            v['weight_unit']=old.number(raw.get('Peso un. Kg')) if compatible else None
        if any(v.get(k) is not None and v[k]>100 for k in ('cut_pct','boc_pct','made_pct')):warn.append('Produção superior à quantidade necessária.')
        if v.get('boc') is not None and v.get('cut') is not None and v['boc']>v['cut']:warn.append('Abocardado superior ao cortado.')
        rules=calculations.enrich(v,original,raw,weight_table,area)
        output.append(dict(key=key,area=area,need_id=key if need else None,revision=need['revision'] if need else 0,values=v,original=original,raw=raw,warnings=warn,status=ctx.get('cpis_status'),status_values=ctx.get('status_values',[]),origin='local' if record else 'macro',sources=links.get(key,[]),plan_key=line['source_line_id'] if line else None,operation_id=operation,preparations=records.get(key,[]),operations=[],calculation={'contract':'raw-v2','rules':rules,'compatible':compatible,'macro_snapshot':snap['snapshot_id']},cpis_conflicts=ctx.get('conflicts'),macro_closure_values=[value for origin in origins for value in (origin.get('closed_x'), (origin.get('row_data') or {}).get('Fechado'))]))
        output[-1]['local_order_revision']=(local_orders.get(of) or {}).get('revision',0)
        population.annotate(output[-1])
        from . import registration as free
        free.annotate(output[-1],record,need)
        if free.enabled() and of in local_orders:
            output[-1].setdefault('input_values',{}).update(local_orders[of]['values_json'])
            if v.get('delivery_date'):
                from datetime import date
                try:v['delivery_date']=date.fromisoformat(str(v['delivery_date'])).isoformat()
                except ValueError:
                    v['delivery_date']=None
                    output[-1]['warnings'].append('Data de entrega guardada; data por interpretar.')
    for row in output:row['selection_aliases']=[]
    preserve_selection(conn,area,output,orders=orders)
    events=enrich(conn,area,output,snap['snapshot_id'],facts=facts,proofs=proofs)
    section_table=calculations.sections(conn,snap['snapshot_id'])
    for row in output:
        calculations.recalculate(row,section_table,weight_table)
        if row.get('identity_pending'):
            row['values']['remaining']=None
            row['values']['planning_remaining']=None
            row['values']['quantity_to_plan']=None
    from . import sku_families
    sku_families.annotate(conn,area,output)
    return output,events,source_metadata(conn,area)


def source_metadata(conn,area):
    from .. import planning_original_production
    direct=hub._direct_version(conn)
    return needs.serial({'original_ocr_snapshots':planning_original_production.snapshot_token(conn),'area':area,'snapshot':planning.snapshot(conn,area),'cpis_version':str(direct['id']) if direct else hub._fallback_token(hub._latest_snapshots(conn)),'cpis_mode':'CPIS direto' if direct else 'CPIS importado da macro — sem confirmação direta','cpis_checked_at':direct['last_confirmed_at'] if direct else None,'display_timezone':planning.settings.display_timezone})


def source_facts(conn,area):
    """Resolve the same source identity for calculation and change detection."""
    app='kanban-mes-mtg2' if area=='perfis' else 'kanban-mes'
    facts=conn.execute('''SELECT p.*,v.source_app,v.sheet_no,
        jsonb_path_query_first(v.cross_check,'strict $.rows[*] ? (@.row_index == $row)',jsonb_build_object('row',p.row_index),true) cross_check_row
        FROM mes_kanban.production_records p
        JOIN mes_kanban.validated_sheets v USING(sheet_uid) WHERE source_app=%s ORDER BY p.id''',(app,)).fetchall()
    refs=defaultdict(list)
    for r in conn.execute('SELECT * FROM mes_kanban.production_record_plan_refs ORDER BY production_record_id,plan_key').fetchall():refs[r['production_record_id']].append(r)
    history=defaultdict(list)
    for r in facts:
        check=r.pop('cross_check_row') or {}
        r['frozen_identity']=(r.get('extra') or {}).get('plan_identity') or check.get('plan_identity') or {}
        r['plan_refs']=refs[r['id']] or check.get('plan_refs') or []
    keys=list({r['matched_plan_key'] for r in facts if r.get('matched_plan_key') and not r['frozen_identity']})
    if keys:
        for r in conn.execute('SELECT plan_key,source_app,production_order_no,component_ref,profile_type,length_mm FROM analytics_mtg.kanban_plan_lines WHERE plan_key=ANY(%s)',(keys,)).fetchall():history[r['plan_key']].append(r)
    for r in facts:
        if not r['frozen_identity'] and len(history[r.get('matched_plan_key')])==1:r['frozen_identity']=history[r['matched_plan_key']][0]
        r['of']=order_number(r['production_order']) or order_number(r['frozen_identity'].get('production_order_no'))
    from .. import planning_original_production
    return facts+planning_original_production.records(conn,area)


def enrich(conn,area,rows,snapshot,*,facts=None,proofs=None):
    from .. import planning_production as prod, planning_associations as assoc
    app='kanban-mes-mtg2' if area=='perfis' else 'kanban-mes'
    facts=source_facts(conn,area) if facts is None else facts
    decisions={r['production_record_id']:r for r in assoc.latest_all(conn)}
    by_of=defaultdict(list);plans=defaultdict(list);indexed={};row_by_plan={r['plan_key']:r for r in rows if r['plan_key']};pending=defaultdict(int);last={};events=[]
    for r in facts:
        of=r['of'];by_of[of].append(r)
        if r.get('sheet_date') and (of not in last or r['sheet_date']>last[of]):last[of]=r['sheet_date']
    for row in rows:
        v=row['values'];o=row['original'];row['ocr_evidence']={}
        v.update(ocr_cut=None,ocr_boc=None,ocr_quantity=None,last_activity=last.get(v['of']))
        if not row['plan_key']:continue
        p=dict(source_app=app,plan_key=row['plan_key'],component_ref=o.get('component_ref'),profile_type=o.get('profile'),length_mm=o.get('length_mm'),quantity_planned=o.get('quantity_required'),quantity_made=v.get('made'),operation_inputs=row['raw'],remaining_quantity=v.get('remaining'),remaining_valid=v.get('remaining') is not None)
        plans[v['of']].append(p);indexed[row['plan_key']]=p
    for of in dict.fromkeys([*by_of,*plans]):
        items=by_of.get(of,[])
        hub._production_associations(items,plans.get(of,[]))
        prod.attach_operation_evidence(plans.get(of,[]),assoc.automatic_records(conn,items,decisions))
        for r in items:
            decision=decisions.get(r['id']);state=decision['status'] if decision else r.get('association_status')
            if decision and not assoc.decision_valid(conn,assoc.fact(conn,r['id']),decision):state='compatibility_review'
            allocations=[];operation=prod.operation_for_record(r,plans.get(of,[]))
            if decision and state=='associated':
                actual=assoc.fact(conn,r['id'])
                valid=assoc.decision_valid(conn,actual,decision)
                for a in decision['allocations']:
                    n=needs.load(conn,a['need_id'])
                    op=conn.execute('SELECT code FROM planning_mtg.need_operations WHERE id=%s',(a['operation_id'],)).fetchone()
                    if n['technical_revision']!=a['technical_revision'] or not op:valid=False
                    allocations.append({**a,'operation':op['code'] if op else 'operacao_por_confirmar','component_ref':n['component_ref']})
                if not valid:allocations=[];state='compatibility_review'
            # Barra completa: a operação pode estar decidida por filho (ver planning_production).
            by_child=r.get('operation_by_plan_key') or {}
            per_child_done=bool(by_child) and all(k in by_child for k in r.get('resolved_plan_keys',[]))
            unresolved=state not in ('associated','explicit','technical_unique','unrelated') or (not allocations and operation=='operacao_por_confirmar' and not per_child_done and state!='unrelated')
            children=r['plan_refs'] if r.get('full_profile') or r['plan_refs'] else [None]
            if not children:children=[{'plan_key':'incomplete','assumed_quantity':None}]
            for i,child in enumerate(children):
                qty=old.number(child.get('assumed_quantity') if child is not None else r.get('quantity'))
                child_key=child.get('plan_key') if child else None
                assigned=[a for a in allocations if a.get('child_key')==child_key]
                fragments=[{'quantity':a['quantity'],'operation':a['operation'],'component_ref':a['component_ref'],'need_id':a['need_id'],'association_status':'associated'} for a in assigned]
                known_sum=sum(a['quantity'] for a in assigned if a['quantity'] is not None)
                if not assigned or qty is not None and known_sum<qty:
                    if assigned:unresolved=True
                    child_plan=(r.get('resolved_plan_refs') or [])[i]['plan_key'] if i<len(r.get('resolved_plan_refs') or []) else None
                    fragments.append({'quantity':qty-known_sum if qty is not None else None,'operation':by_child.get(child_plan,operation),'component_ref':(child.get('component_ref') or child.get('model_ref')) if child else r.get('model_ref'),'association_status':state if not assigned else 'unallocated'})
                for j,fragment in enumerate(fragments):
                    v=dict(of=of,ov=r.get('sales_order'),machine=r.get('machine'),production_date=r.get('sheet_date'),length_mm=r.get('length_mm'),hours_worked=None,source=r.get('source',app),sheet=r.get('sheet_no'),**fragment)
                    # Resolved refs retain probe order: each expanded child belongs
                    # to its own piece, never to every child of the original bar.
                    resolved_refs=r.get('resolved_plan_refs') or []
                    resolved_key=resolved_refs[i]['plan_key'] if i<len(resolved_refs) else None
                    linked=[row_by_plan[resolved_key]['key']] if state in ('explicit','technical_unique') and resolved_key in row_by_plan else []
                    if fragment.get('need_id'):linked=[fragment['need_id']]
                    events.append({'planning_keys':linked,'key':str(r['id'])+':'+str(i)+':'+str(j),'values':v,'record_id':r['id'],'sheet_uid':r['sheet_uid'],'row_index':r['row_index'],'validated_at':r['validated_at'],'child':child,'decision_id':str(decision['id']) if decision else None,'warnings':['Horas da folha não são repartidas por linha.'] if r.get('hours_worked') else []})
            if unresolved:pending[of]+=1
    for row in rows:
        row['operations']=indexed.get(row['plan_key'],{}).get('operations',[])
        for op in row['operations']:
            target={'corte':'ocr_cut','abocardar':'ocr_boc'}.get(op['operation'])
            if target:row['values'][target]=op.get('ocr_quantity');row['ocr_evidence'][target]=op.get('ocr_records',[])
            if area=='cantoneiras' and op['operation'].isdigit():
                row['values']['ocr_op_'+op['operation']]=op.get('ocr_quantity')
                row['ocr_evidence'][op['operation']]=op.get('ocr_records',[])
                if op['operation']==row['values'].get('operation'):row['values']['ocr_quantity']=op.get('ocr_quantity')
        if row['need_id']:
            n=needs.load(conn,row['need_id'])
            for op in conn.execute('SELECT * FROM planning_mtg.need_operations WHERE need_id=%s AND area=%s',(n['id'],area)).fetchall():
                proof=(proofs or {}).get((str(n['id']),str(op['id'])))
                if proof is None:proof=assoc.evidence(conn,n,op)
                target={'corte':'ocr_cut','abocardar':'ocr_boc'}.get(op['code'],'ocr_quantity')
                row['ocr_evidence'][op['code']]=proof['ocr_records']
                existing=next((item for item in row['operations'] if item['operation']==op['code']),None)
                if existing is None:
                    existing={'operation':op['code']};row['operations'].append(existing)
                existing.update(ocr_records=[{**fact,'operation':op['code']} for fact in proof['ocr_records']],
                    ocr_quantity=proof['ocr_quantity'],ocr_partial=bool(proof['ocr_records']) and proof['ocr_quantity'] is None,
                    coverage_reasons=proof['warnings'])
                if len(proof['macro'])==1:existing['macro_quantity']=proof['macro'][0]['quantity']
                if area=='perfis' or op['code']==row['values'].get('operation'):row['values'][target]=proof['ocr_quantity']
                if area=='cantoneiras' and op['code'].isdigit():row['values']['ocr_op_'+op['code']]=proof['ocr_quantity']
                row['warnings'].extend(proof['warnings'])
        v=row['values'];v['unassigned_records']=pending.get(v['of'],0)
        v['execution_status']='Sem registos OCR associados' if all(v.get(k) is None for k in ('ocr_cut','ocr_boc','ocr_quantity')) else 'Consultar produção por operação'
    # Potentially duplicated original/MES production cannot feed history either.
    blocked=set()
    for row in rows:
        for op in row.get('operations',[]):
            origins={(r.get('source','mes'),r.get('instance_id')) for r in op.get('ocr_records',[])}
            overlap=len(origins)>1 and any(source=='ocr_original' for source,_ in origins)
            incomplete=any('original:' in reason for reason in op.get('coverage_reasons',[]))
            if overlap or incomplete:blocked.add((row['key'],op['operation']))
    for event in events:
        if any((key,event['values']['operation']) in blocked for key in event['planning_keys']):
            event['values']['association_status']='source_overlap'
            event['warnings'].append('Cobertura entre OCR original e MES por reconciliar; excluído do histórico.')
    return events


def publish(conn,dataset,fingerprint,rows,metadata):
    conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('raw:'+dataset,))
    previous=conn.execute('SELECT * FROM planning_mtg.raw_generations WHERE dataset=%s ORDER BY id DESC LIMIT 1',(dataset,)).fetchone()
    if previous and previous['metadata'].get('source_fingerprint')==fingerprint:return previous
    if previous:
        # A no-op write is an epoch barrier under REPEATABLE READ: a publisher
        # using an obsolete snapshot must fail serialization, even if its delta
        # does not touch any of the concurrently changed membership rows.
        conn.execute('UPDATE planning_mtg.raw_generations SET row_count=row_count WHERE id=%s',(previous['id'],))
    # Content may recur after an intermediate source revision: a generation is a navigation epoch.
    token=needs.digest([fingerprint,previous['id'] if previous else None])
    if dataset.startswith('planning:'):
        metadata={**metadata,'preparation_keys':sorted(r['key'] for r in rows if r.get('preparations'))}
    gen=conn.execute('INSERT INTO planning_mtg.raw_generations(dataset,fingerprint,metadata,row_count) VALUES(%s,%s,%s,%s) RETURNING *',(dataset,token,Jsonb({**metadata,'source_fingerprint':fingerprint}),len(rows))).fetchone()
    current={r['row_key']:r['content_hash'] for r in conn.execute('SELECT row_key,content_hash FROM planning_mtg.raw_members WHERE dataset=%s AND last_generation IS NULL',(dataset,)).fetchall()}
    new={};content=[];members=[];changed=[]
    for r in rows:
        r=needs.serial(r);key=r['key'];h=serialized_digest(r);new[key]=h
        if current.get(key)==h:continue
        detail={k:v for k,v in r.items() if k!='values'};values=r['values']
        search=' '.join(str(v) for v in values.values() if v is not None).casefold()
        content.append((h,Jsonb(values),Jsonb(detail),search));members.append((dataset,key,gen['id'],h,*member_dependencies(dataset,r)));changed.append(key)
    removed=list(current.keys()-new.keys());closed=changed+removed
    if closed:conn.execute('UPDATE planning_mtg.raw_members SET last_generation=%s WHERE dataset=%s AND last_generation IS NULL AND row_key=ANY(%s)',(gen['id'],dataset,closed))
    if content:
        with conn.cursor() as cur:
            cur.executemany('INSERT INTO planning_mtg.raw_contents(hash,values_json,detail,search_text) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING',content)
            cur.executemany('INSERT INTO planning_mtg.raw_members(dataset,row_key,first_generation,content_hash,planning_machine,planning_active,planning_order) VALUES(%s,%s,%s,%s,%s,%s,%s)',members)
    count=conn.execute('SELECT count(*) n FROM planning_mtg.raw_members WHERE dataset=%s AND last_generation IS NULL',(dataset,)).fetchone()['n']
    if count!=len(rows):raise planning.PlanningError('A projeção não contém a população integral.',409)
    return gen


def rebuild(area,force=False):
    from . import ocr_scope,source_scope
    with planning.connect() as conn:
        from psycopg.types.json import set_json_loads,set_json_dumps
        from pydantic_core import from_json,to_json
        set_json_loads(from_json,conn);set_json_dumps(to_json,conn)
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        conn.execute('SET LOCAL jit=off')
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('raw-build:'+area,))
        fp=fingerprint(conn,area)
        current=conn.execute('SELECT * FROM planning_mtg.raw_generations WHERE dataset=%s ORDER BY id DESC LIMIT 1',('planning:'+area,)).fetchone()
        if current and current['metadata'].get('core_source_fingerprint',current['metadata'].get('source_fingerprint'))==fp and not current['metadata'].get('source_refresh_pending') and not force:return needs.serial(current)
        facts=source_facts(conn,area)
        manifest=ocr_scope.capture(conn,area,facts=facts)
        scope=ocr_scope.identify(conn,current,manifest) if current and not force else None
        if scope is not None:return needs.serial(ocr_scope.publish(conn,area,current,fp,manifest,scope,facts=facts))
        sources=source_scope.capture(conn,area,force=force)
        scope=source_scope.identify(conn,current,sources,manifest) if current and not force else None
        if scope is not None:return needs.serial(ocr_scope.publish(conn,area,current,fp,manifest,scope,facts=facts,source_manifest=sources))
        rows,events,meta=build_rows(conn,area,facts=facts)
        # Core rows are current, but F12 and shared-resource totals still belong
        # to the next capacity publication. Keep that interval visible.
        meta={**meta,'core_source_fingerprint':fp,'aggregates_pending':True,'source_refresh_pending':False,'ocr_manifest':ocr_scope.store(conn,manifest),'source_manifest':source_scope.store(conn,sources),'calculation_scope':'full'}
        publication_fp=needs.digest(['forced-core',fp,current['id'] if current else None]) if force else fp
        publish(conn,'production:'+area,publication_fp,events,meta)
        publish_hours(conn,area,publication_fp,meta)
        from . import productivity
        configs=conn.execute("SELECT * FROM planning_mtg.raw_objects WHERE kind IN ('resource','calendar','rate','period','worked_hours') AND NOT archived").fetchall()
        productivity.apply_rows(conn,area,rows,configs)
        gen=publish(conn,'planning:'+area,publication_fp,rows,meta)
        publish_orders(conn,area,rows,meta,publication_fp)
        return needs.serial(gen)


def publish_delta(conn,dataset,fingerprint,rows,metadata,remove=(),expected_generation=None,*,estimate_patches=None):
    """Publish changed rows without reserializing the unchanged population."""
    conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('raw:'+dataset,))
    previous=conn.execute('SELECT * FROM planning_mtg.raw_generations WHERE dataset=%s ORDER BY id DESC LIMIT 1',(dataset,)).fetchone()
    if not previous:
        if estimate_patches:raise planning.PlanningError('As estimativas exigem uma população publicada.',409)
        return publish(conn,dataset,fingerprint,rows,metadata)
    if previous['metadata'].get('source_fingerprint')==fingerprint:return previous
    if expected_generation is not None and str(previous['id'])!=str(expected_generation):
        raise planning.PlanningError('A população mudou durante o cálculo. Repete com a versão atual.',409)
    conn.execute('UPDATE planning_mtg.raw_generations SET row_count=row_count WHERE id=%s',(previous['id'],))
    incoming={r['key']:needs.serial(r) for r in rows}
    # Engine patches already contain JSON values from the published source and
    # normalized rate context. Their digest below validates JSON encoding; a
    # second encode/decode of thousands of closed-piece estimates is redundant.
    patches=estimate_patches or {}
    if patches and (not dataset.startswith('planning:') or set(patches)&(set(incoming)|set(remove))):
        raise planning.PlanningError('Estimativas com identidades repetidas ou fora do planeamento.')
    if len(incoming)!=len(rows) or set(incoming)&set(remove):raise planning.PlanningError('Delta com identidades repetidas ou contraditórias.')
    touched=list(set(incoming)|set(remove)|set(patches))
    current_members={r['row_key']:r for r in conn.execute('SELECT row_key,content_hash,planning_machine,planning_active,planning_order FROM planning_mtg.raw_members WHERE dataset=%s AND last_generation IS NULL AND row_key=ANY(%s)',(dataset,touched))}
    current={key:r['content_hash'] for key,r in current_members.items()}
    if set(patches)-set(current):raise planning.PlanningError('A peça deixou de existir durante o cálculo das estimativas.',409)
    if dataset.startswith('planning:'):
        prepared=previous['metadata'].get('preparation_keys')
        if prepared is None:
            # Upgrade old publications once. Keep the index in the new epoch,
            # not by modifying the metadata of a retained generation.
            prepared=[r['row_key'] for r in conn.execute("SELECT m.row_key FROM planning_mtg.raw_members m JOIN planning_mtg.raw_resolved_contents c ON c.hash=m.content_hash WHERE m.dataset=%s AND m.last_generation IS NULL AND jsonb_array_length(coalesce(c.detail->'preparations','[]'))>0",(dataset,))]
        prepared=(set(prepared)-set(remove)-set(incoming))|{key for key,row in incoming.items() if row.get('preparations')}
        metadata={**metadata,'preparation_keys':sorted(prepared)}
    count=previous['row_count']+len(set(incoming)-set(current))-len(set(remove)&set(current))
    gen=conn.execute('INSERT INTO planning_mtg.raw_generations(dataset,fingerprint,metadata,row_count) VALUES(%s,%s,%s,%s) RETURNING *',
        (dataset,needs.digest([fingerprint,previous['id']]),Jsonb({**metadata,'source_fingerprint':fingerprint}),count)).fetchone()
    content=[];members=[];changed=list(set(remove)&set(current));derived=[]
    for key,row in incoming.items():
        digest=serialized_digest(row)
        if current.get(key)==digest:continue
        if key in current:changed.append(key)
        values=row['values'];detail={k:v for k,v in row.items() if k!='values'}
        content.append((digest,Jsonb(values),Jsonb(detail),' '.join(str(v) for v in values.values() if v is not None).casefold()))
        members.append((dataset,key,gen['id'],digest,*member_dependencies(dataset,row)))
    for key,patch in patches.items():
        # Commit to the immutable parent and the exact derived patch. Keep the
        # large source JSON in PostgreSQL instead of reading/encoding it again.
        digest=serialized_digest(['planning-estimate-patch-v1',current[key],patch])
        derived.append({'hash':digest,'patch':patch,'parent':current[key]});changed.append(key)
        previous_member=current_members[key]
        members.append((dataset,key,gen['id'],digest,previous_member['planning_machine'],previous_member['planning_active'],previous_member['planning_order']))
    if changed:conn.execute('UPDATE planning_mtg.raw_members SET last_generation=%s WHERE dataset=%s AND last_generation IS NULL AND row_key=ANY(%s)',(gen['id'],dataset,changed))
    if content or derived:
        with conn.cursor() as cur:
            if content:cur.executemany('INSERT INTO planning_mtg.raw_contents(hash,values_json,detail,search_text) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING',content)
            for offset in range(0,len(derived),1000):cur.execute('''WITH patches AS MATERIALIZED (
                SELECT p.hash,p.patch,c.values_json || (p.patch->'values') values_json,
                    coalesce(c.detail_source_hash,c.hash) source_hash,
                    jsonb_build_object(
                        'original',coalesce(c.detail_patch->'original','{}') || (p.patch->'original'),
                        'rules',coalesce(c.detail_patch->'rules','{}') || (p.patch->'rules'),
                        'operation_estimates',p.patch->'operation_estimates') detail_patch
                FROM jsonb_to_recordset(%s) p(hash text,patch jsonb,parent text)
                JOIN planning_mtg.raw_contents c ON c.hash=p.parent
                ) INSERT INTO planning_mtg.raw_contents(hash,values_json,detail,search_text,detail_source_hash,detail_patch)
                SELECT p.hash,p.values_json,'{}',p.patch->>'search_text',p.source_hash,p.detail_patch
                FROM patches p ON CONFLICT DO NOTHING''',(Jsonb(derived[offset:offset+1000]),))
            # Membership rows are new epochs with no conflict fallback. COPY
            # retains the same constraints and transaction while avoiding one
            # INSERT per historical estimate when a source cohort changes.
            if members:
                with cur.copy('COPY planning_mtg.raw_members(dataset,row_key,first_generation,content_hash,planning_machine,planning_active,planning_order) FROM STDIN') as copied:
                    for member in members:copied.write_row(member)
    return gen


def order_rows(rows):
    grouped=defaultdict(list)
    for row in rows:
        if row.get('identity_pending'):continue
        grouped[(row['values'].get('of'),population.includes(row))].append(row)
    output=[]
    for (of,active),items in grouped.items():
        v=items[0]['values'];known=[r['values'].get('remaining') for r in items if r['values'].get('remaining') is not None];q=[r['values'].get('quantity_required') for r in items if r['values'].get('quantity_required') is not None]
        output.append({'key':(of or 'unknown')+('' if active else ':history'),'population':{'active':active},'values':{k:v.get(k) for k in ('of','ov','customer','status','last_activity','unassigned_records')}|{'planning_active':active,'closure_reason':None if active else 'Consultar fecho das peças','quantity_required':sum(q) if len(q)==len(items) else None,'remaining':sum(known) if len(known)==len(items) else None,'known_remaining_total':sum(known) if known else None,'remaining_known_lines':len(known),'lines_total':len(items)},'coverage':{'rows':len(items),'remaining_known':len(known),'required_known':len(q)},'line_keys':[r['key'] for r in items],'warnings':['Os totais abrangem apenas valores conhecidos.'] if len(known)!=len(items) else []})
    return output


def publish_orders(conn,area,rows,meta,fp):
    publish(conn,'orders:'+area,fp,order_rows(rows),meta)


def rebuild_original():
    from .. import original_ocr,planning_original_production
    with planning.connect() as c:
        if not planning_original_production.available(c):return
        instances=c.execute('SELECT * FROM ocr_original.instances ORDER BY id').fetchall()
        if not instances:
            from . import ocr_export
            return ocr_export.rebuild(c)
        rows=planning_original_production.sheets(c)
        ids=['original:'+str(s['instance_id'])+':'+str(s['sheet_id'])+':'+str(line['row_index']) for s in rows for line in s['payload'].get('production',[])]
        diagnostics=planning_original_production.diagnostics(c,ids)
        source_state=original_ocr.status(c)
        meta={'source':'OCR original — evidência do motor de planeamento','instances':needs.serial(instances),
              'included_in_planning_balances':source_state['included_in_planning_balances'],
              'planning_publications':source_state['planning_publications']}
        for area in planning.AREAS:
            output=[]
            for sheet in rows:
                for record in planning_original_production.normalize(sheet,area):
                    checks=[d for d in diagnostics[record['id']] if d['area']==area]
                    check=checks[0] if len(checks)==1 else {}
                    v={'of':record['of'],'ov':record['sales_order'],'component_ref':record['model_ref'],
                       'machine':record['machine'],'operation':check.get('operation') or record['extra']['operation_code'],
                       'production_date':record['sheet_date'],'quantity':record['quantity'],'length_mm':record['length_mm'],
                       'hours_worked':None,'source':'OCR original','sheet':sheet['sheet_id'],
                       'association_status':check.get('reason') or 'Sem associação comprovada nesta área.'}
                    output.append({'key':record['id'].removeprefix('original:'),'source_event_key':record['id'],
                        'values':v,'original':record['original'],'planning':checks,
                        'source_sheet':{k:sheet[k] for k in ('instance_id','sheet_id','content_hash','source_revision')},
                        'warnings':sheet['payload'].get('quality_flags',[])})
            fp=needs.digest([planning_original_production.snapshot_token(c),area,output])
            publish(c,'original:'+area,fp,output,meta)
        return {'rows':len(ids),'instances':len(instances)}


def publish_hours(conn,area,fp,meta):
    app='kanban-mes-mtg2' if area=='perfis' else 'kanban-mes'
    sheets=conn.execute('''SELECT v.sheet_uid,v.sheet_no,v.sheet_date,v.validated_at,
        array_agg(DISTINCT p.hours_worked) FILTER(WHERE p.hours_worked IS NOT NULL) hours,
        array_agg(DISTINCT p.machine) FILTER(WHERE nullif(p.machine,'') IS NOT NULL) machines
        FROM mes_kanban.validated_sheets v LEFT JOIN mes_kanban.production_records p USING(sheet_uid)
        WHERE v.source_app=%s GROUP BY v.sheet_uid,v.sheet_no,v.sheet_date,v.validated_at''',(app,)).fetchall()
    output=[]
    for s in sheets:
        hours=s['hours'] or [];machines=s['machines'] or [];value=old.number(hours[0]) if len(hours)==1 else None
        output.append({'key':s['sheet_uid'],'values':{'source':app,'sheet':s['sheet_no'],'production_date':s['sheet_date'],'machine':machines[0] if len(machines)==1 else None,'hours_worked':value},'sheet_uid':s['sheet_uid'],'validated_at':s['validated_at'],'original_hours':hours,'original_machines':machines,'warnings':['Horas ou máquina da folha por confirmar.'] if value is None or len(machines)!=1 else []})
    from .. import planning_original_production
    output.extend(planning_original_production.hour_rows(conn,area))
    publish(conn,'production_hours:'+area,fp,output,meta)


def preserve_selection(conn,area,rows,*,orders=None):
    """Retain aliases only for unique, complete physical identities across macro versions."""
    old_rows=conn.execute("SELECT jsonb_build_object('key',m.row_key,'selection_aliases',coalesce(c.detail->'selection_aliases','[]'::jsonb)) detail,c.values_json FROM planning_mtg.raw_members m JOIN planning_mtg.raw_contents c ON c.hash=m.content_hash WHERE m.dataset=%s AND m.last_generation IS NULL"+(" AND m.planning_order=ANY(%s)" if orders is not None else ''),('planning:'+area,orders) if orders is not None else ('planning:'+area,)).fetchall()
    def identity(v):return needs.digest([v.get('of'),needs.signature(v)]) if v.get('of') and needs.complete(v) else None
    before=defaultdict(list);after=defaultdict(list)
    for r in old_rows:
        key=identity(r['values_json'])
        if key:before[key].append({**r['detail'],'external_id':r['values_json'].get('id')})
    for r in rows:
        key=identity(r['values'])
        if key:after[key].append(r)
    for key,current in after.items():
        for r in current:
            candidates=before[key]
            if len(current)!=1 or len(candidates)!=1:
                ident=r['values'].get('id')
                if ident is None or sum(x['values'].get('id')==ident for x in current)!=1:continue
                candidates=[x for x in candidates if x.get('external_id')==ident]
            if len(candidates)!=1:continue
            prior=candidates[0]
            r['selection_aliases']=sorted(set(prior.get('selection_aliases',[])+[prior['key']])-{r['key']})
