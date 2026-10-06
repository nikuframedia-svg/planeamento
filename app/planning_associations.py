"""Local human associations and balances. Never writes production facts."""
from __future__ import annotations
import uuid
from decimal import Decimal, InvalidOperation
from psycopg.types.json import Jsonb
from . import planning, planning_hub, planning_needs as needs
from .dossiers.models import order_number


def integer(value,nullable=False):
    if value in (None,'') and nullable:return None
    try:
        n=Decimal(str(value).replace(',','.'))
        if not n.is_finite() or n<0 or n!=n.to_integral_value():raise ValueError()
        return int(n)
    except (ValueError,InvalidOperation):raise planning.PlanningError('Indica uma quantidade inteira não negativa.') from None


def fact(conn,record_id):
    if str(record_id).startswith('original:'):
        from . import planning_original_production
        return planning_original_production.fact(conn,record_id)
    try:record_id=int(record_id)
    except (ValueError,TypeError):raise planning.PlanningError('Registo de produção inválido.') from None
    row=conn.execute('''SELECT p.*,v.source_app,v.sheet_no,v.cross_check FROM mes_kanban.production_records p
        JOIN mes_kanban.validated_sheets v USING(sheet_uid) WHERE p.id=%s AND v.source_app IN ('kanban-mes-mtg2','kanban-mes')''',(record_id,)).fetchone()
    if not row:raise planning.PlanningError('Registo validado não encontrado.',404)
    children=conn.execute('SELECT * FROM mes_kanban.production_record_plan_refs WHERE production_record_id=%s ORDER BY plan_key',(record_id,)).fetchall()
    check=next((r for r in (row.get('cross_check') or {}).get('rows',[]) if r.get('row_index')==row['row_index']),{})
    row['frozen_identity']=(row.get('extra') or {}).get('plan_identity') or check.get('plan_identity') or {}
    row['children']=children or check.get('plan_refs') or []
    row['area']='perfis' if row['source_app']=='kanban-mes-mtg2' else 'cantoneiras'
    return needs.serial(row)


def original_decisions_available(conn):
    return bool(conn.execute("SELECT to_regclass('planning_mtg.original_association_decisions') t").fetchone()['t'])


def latest_all(conn,*,original_only=False):
    tables=[] if original_only else ['association_decisions']
    if original_decisions_available(conn):tables.append('original_association_decisions')
    return [row for table in tables for row in conn.execute('SELECT DISTINCT ON(production_record_id) * FROM planning_mtg.'+table+' ORDER BY production_record_id,revision DESC')]


def latest(conn,record_id):
    original=str(record_id).startswith('original:')
    if original and not original_decisions_available(conn):return None
    table='original_association_decisions' if original else 'association_decisions'
    return conn.execute('SELECT * FROM planning_mtg.'+table+' WHERE production_record_id=%s ORDER BY revision DESC LIMIT 1',(record_id,)).fetchone()


def evidence_fingerprint(record):
    if record.get('source')!='ocr_original':return needs.digest(record)
    ignored={'source_revision','source_content_hash','validated_at','sheet_date','hours_worked','original'}
    data={k:v for k,v in record.items() if k not in ignored}
    data['original']={k:v for k,v in record.get('original',{}).items() if k not in
        {'validated_at','sheet_hours','sheet_date','sheet_iso_date','captured_at','sheet_total_qty','sheet_status','human_fields'}}
    return needs.digest(data)


def decision_valid(conn,record,decision,*,technical_revisions=None):
    """One validity rule for routing, diagnostics and usable production."""
    if not decision or evidence_fingerprint(record)!=decision['evidence_hash']:return False
    for a in decision['allocations']:
        if technical_revisions is None:
            target=conn.execute('SELECT technical_revision FROM planning_mtg.needs WHERE id=%s',(a['need_id'],)).fetchone()
            revision=target['technical_revision'] if target else None
        else:revision=technical_revisions.get(str(a['need_id']))
        if revision!=a['technical_revision']:return False
    return True


def allocation_gaps(record,decision):
    """Known production left outside a human distribution remains unresolved."""
    if not decision or decision['status']!='associated':return []
    children=record.get('children') or record.get('plan_refs') or []
    quantities={r['plan_key']:integer(r.get('assumed_quantity'),True) for r in children} if children else {None:integer(record.get('quantity'),True)}
    result=[]
    for child,total in quantities.items():
        assigned=[a for a in decision['allocations'] if a.get('child_key')==child]
        allocated=sum(a['quantity'] or 0 for a in assigned)
        if total is not None and allocated<total:
            result.append({'child_key':child,'quantity':total-allocated})
    return result


def automatic_records(conn,records,decisions):
    """Manual decisions replace automatic evidence, keeping unresolved coverage."""
    result=[]
    for record in records:
        decision=decisions.get(record['id'])
        if not decision:result.append(record);continue
        actual=fact(conn,record['id'])
        valid=decision_valid(conn,actual,decision)
        if valid and (decision['status']=='unrelated' or decision['status']=='associated' and not allocation_gaps(actual,decision)):
            continue
        candidates=list(dict.fromkeys(record.get('association_candidates',[])+record.get('resolved_plan_keys',[])))
        result.append({**record,'association_status':'compatibility_review','resolved_plan_keys':[],
            'resolved_plan_refs':[],'association_candidates':candidates})
    return result


def pending(of=None,area=None,page=1,state="pending",reason=None,include_unknown=False,source="mes"):
    if source=="original":return original_pending(of,area,page,state,reason,include_unknown)
    if source!="mes":raise planning.PlanningError("Origem OCR inválida.")
    if area:planning.check_area(area)
    page=max(int(page),1)
    with planning.connect(readonly=True) as conn:
        clauses=["v.source_app IN ('kanban-mes-mtg2','kanban-mes')"];args=[]
        if of:
            normalized=order_number(of)
            if not normalized:raise planning.PlanningError('Indica uma OF válida.')
            predicate="regexp_replace(trim(p.production_order),'^OF[ ._-]*','','i')=%s"
            if include_unknown:predicate="("+predicate+" OR coalesce(p.production_order,'') !~* '^\\s*(OF[ ._-]*)?[0-9]{4,10}\\s*$')"
            clauses.append(predicate);args.append(normalized[2:])
        if area:clauses.append('v.source_app=%s');args.append('kanban-mes-mtg2' if area=='perfis' else 'kanban-mes')
        if state not in ('pending','associated','unrelated','all'):raise planning.PlanningError('Filtro de associação inválido.')
        stale="EXISTS(SELECT 1 FROM jsonb_array_elements(coalesce(d.allocations,'[]'::jsonb)) a JOIN planning_mtg.needs n ON n.id::text=a->>'need_id' WHERE n.technical_revision<>(a->>'technical_revision')::integer)"
        if state=='pending':clauses.append("(coalesce(d.status,'pending')='pending' OR "+stale+")")
        elif state=='associated':clauses.append("d.status='associated' AND NOT "+stale)
        elif state=='unrelated':clauses.append("d.status='unrelated'")
        base=" FROM mes_kanban.production_records p JOIN mes_kanban.validated_sheets v USING(sheet_uid) LEFT JOIN LATERAL (SELECT * FROM planning_mtg.association_decisions WHERE production_record_id=p.id ORDER BY revision DESC LIMIT 1) d ON true WHERE "+' AND '.join(clauses)
        total=conn.execute('SELECT count(*) n'+base,args).fetchone()['n']
        ids=conn.execute('SELECT p.id'+base+' ORDER BY p.id DESC'+('' if reason else ' LIMIT 50 OFFSET %s'),args if reason else (*args,(page-1)*50)).fetchall()
        result=[]
        for r in ids:
            record=fact(conn,r['id']);decision=latest(conn,r['id'])
            effective_of=order_number(record.get('production_order')) or order_number(record['frozen_identity'].get('production_order_no'))
            candidates=conn.execute('SELECT * FROM planning_mtg.needs WHERE production_order_no=%s ORDER BY component_ref',(effective_of or (order_number(of) if include_unknown else None),)).fetchall() if effective_of or (include_unknown and of) else []
            record.update(evidence_hash=needs.digest(record),decision=needs.serial(decision),candidates=needs.serial(candidates))
            frozen=record['frozen_identity']
            identity_ref=record.get('model_ref') or frozen.get('component_ref')
            matching=[n for n in candidates if needs.catalogs.key(n['component_ref'])==needs.catalogs.key(identity_ref)]
            reason_code=('expansion' if record.get('full_profile') and not record['children'] else
                         'piece' if not identity_ref else
                         'geometry' if (record.get('length_mm') or frozen.get('length_mm')) is None else
                         'ambiguous' if len(matching)>1 else 'operation')
            labels={'expansion':'Expansão histórica incompleta','piece':'Peça por identificar','geometry':'Geometria incompleta','ambiguous':'Várias peças possíveis','operation':'Operação / associação por confirmar'}
            record['reason_code']=reason_code
            record['reason']=labels[reason_code]
            if reason and reason_code!=reason:continue
            result.append(record)
        if reason:total=len(result);result=result[(page-1)*50:page*50]
        return {'records':result,'page':page,'total':total}


def save(payload):
    with planning.connect() as conn:
        _,actor,old=needs.command(conn,payload)
        if old:return old
        from .raw import incremental
        before=incremental.baseline(conn)
        record=fact(conn,payload.get('production_record_id'));current=latest(conn,record['id'])
        revision=current['revision'] if current else 0
        if payload.get('expected_revision')!=revision:raise planning.PlanningError('A associação mudou. Atualiza a evidência.',409)
        fingerprint=evidence_fingerprint(record)
        if payload.get('evidence_hash')!=fingerprint:raise planning.PlanningError('A evidência mudou. Reabre a associação.',409)
        reason=str(payload.get('reason') or '').strip()  # opcional desde 07/10/2026; o autor e a hora ficam registados
        status=payload.get('status','associated')
        if status not in ('associated','pending','unrelated'):raise planning.PlanningError('Decisão inválida.')
        allocations=payload.get('allocations') or []
        if status=='associated' and not allocations:raise planning.PlanningError('Seleciona a necessidade e a operação.')
        if status!='associated' and allocations:raise planning.PlanningError('Uma decisão pendente ou sem correspondência não pode atribuir quantidades.')
        expanded=bool(record.get('full_profile') or record['children'])
        children={r['plan_key']:r for r in record['children']}
        totals={};counts={};seen=set();clean=[];allocation_areas=set()
        for a in allocations:
            if type(a.get('expected_need_revision')) is not int:raise planning.PlanningError('Atualiza a revisão da necessidade antes de associar.',409)
            need=needs.load(conn,a.get('need_id'),a['expected_need_revision'])
            op=conn.execute('SELECT * FROM planning_mtg.need_operations WHERE id=%s AND need_id=%s',(needs.uid(a.get('operation_id')),need['id'])).fetchone()
            if not op or record['area'] is not None and op['area']!=record['area']:raise planning.PlanningError('Operação incompatível com a área do registo.')
            allocation_areas.add(op['area'])
            if len(allocation_areas)>1:raise planning.PlanningError('Uma linha de produção deve pertencer a uma única área.')
            of=order_number(record.get('production_order')) or order_number(record['frozen_identity'].get('production_order_no'))
            if of and of!=need['production_order_no']:raise planning.PlanningError('A produção pertence a outra OF.')
            child=a.get('child_key') or None
            if expanded and child not in children:raise planning.PlanningError('Falta a referência filha congelada. A distribuição histórica não pode ser inventada.')
            if not expanded and child:raise planning.PlanningError('Este registo não possui referências filhas.')
            available=integer(children[child].get('assumed_quantity'),True) if child else integer(record.get('quantity'),True)
            qty=integer(a.get('quantity'),True)
            if available is None and qty is not None:raise planning.PlanningError('Quantidade OCR desconhecida. A associação não pode criar uma quantidade.')
            if available is not None and qty is None:raise planning.PlanningError('Indica a quantidade da distribuição.')
            ident=(child,str(op['id']))
            if ident in seen:raise planning.PlanningError('A mesma operação está repetida nesta distribuição.')
            seen.add(ident);totals[child]=totals.get(child,0)+(qty or 0);counts[child]=counts.get(child,0)+1
            if available is not None and totals[child]>available:raise planning.PlanningError('A distribuição ultrapassa a produção validada.')
            if available is None and counts[child]>1:raise planning.PlanningError('Uma quantidade desconhecida não pode ser repartida.')
            clean.append({'need_id':str(need['id']),'operation_id':str(op['id']),'technical_revision':need['technical_revision'],'child_key':child,'quantity':qty,**({'area':op['area']} if record.get('source')=='ocr_original' else {})})
        ident=uuid.uuid4()
        table='original_association_decisions' if record.get('source')=='ocr_original' else 'association_decisions'
        if table=='original_association_decisions' and not original_decisions_available(conn):raise planning.PlanningError('Atualiza o esquema de associações do Planeamento.',503)
        conn.execute('''INSERT INTO planning_mtg.'''+table+'''(id,production_record_id,revision,status,allocations,evidence_hash,evidence,actor,reason)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)''',(ident,record['id'],revision+1,status,Jsonb(clean),fingerprint,Jsonb(record),actor,reason))
        affected={a['need_id'] for a in clean}|{a['need_id'] for a in (current['allocations'] if current else [])}
        for nid in sorted(affected):needs.event(conn,needs.load(conn,nid),'production_association',actor,{'decision_id':str(ident),'record_id':record['id'],'status':status,'allocations':clean,'reason':reason})
        orders={needs.load(conn,nid)['production_order_no'] for nid in affected}
        if order_number(record.get('production_order')):orders.add(order_number(record['production_order']))
        publication=incremental.publish(conn,before,orders,affected,payload['request_id'],refresh_hours=record.get('source')=='ocr_original') if orders else None
        return needs.finish(conn,payload,{'id':ident,'revision':revision+1,'status':status,'publication':publication})


def evidence(conn,need,op,*,source_cache=None):
    sources=needs.linked_sources(conn,need['id']);source_dependencies=[];macros=[];facts=[];warnings=[];seen_macro=set()
    detail=planning_hub.order_detail(need['production_order_no'],conn=conn)
    decisions=latest_all(conn)
    from . import planning_production
    automatic=automatic_records(conn,detail['production'],{d['production_record_id']:d for d in decisions})
    planning_production.attach_operation_evidence(detail['plan_lines'],automatic)
    if not any(src['kind']=='plan_line' for src in sources):
        # Local needs have no macro row on which the automatic matcher can put
        # unresolved coverage. Preserve candidate original facts here as well.
        app='kanban-mes-mtg2' if op['area']=='perfis' else 'kanban-mes'
        for record in automatic:
            if record.get('source')!='ocr_original' or record.get('source_app')!=app:continue
            if record.get('model_ref') and needs.catalogs.key(record['model_ref'])!=needs.catalogs.key(need['component_ref']):continue
            spec=need['specification']
            if record.get('length_mm') is not None and spec.get('length_mm') is not None and float(record['length_mm'])!=float(spec['length_mm']):continue
            if record.get('profile_type') and spec.get('profile') and needs.catalogs.key(record['profile_type'])!=needs.catalogs.key(spec['profile']):continue
            if record.get('operation') not in (op['code'],'operacao_por_confirmar',None):continue
            warnings.append('Registo '+str(record['id'])+': identidade ou operação por confirmar.')
    for src in sources:
        try:
            area=src['payload'].get('area',op['area']);key=(src['kind'],src['source_id'],area)
            current=source_cache.get(key) if source_cache is not None else None
            if current is None:
                current=needs.source_data({'kind':src['kind'],'id':src['source_id']},area,conn)
                if source_cache is not None:source_cache[key]=current
        except planning.PlanningError:
            warnings.append('Origem indisponível ou alterada: '+src['source_id']);source_dependencies.append({'kind':src['kind'],'id':src['source_id'],'unavailable':True});continue
        source_dependencies.append({'kind':src['kind'],'id':src['source_id'],'technical':{k:current['values'].get(k) for k in needs.PIECE_FIELDS}})
        if src['kind']=='plan_line':
            if current['id'] in seen_macro:continue
            seen_macro.add(current['id'])
            line=next((x for x in detail['plan_lines'] if x['plan_key']==current['id']),None)
            if not line:continue
            selected=next((x for x in line['operations'] if x['operation']==op['code']),None)
            original=needs.signature(current['values']);effective=needs.signature(need['specification'])
            compatible=all(value is None or effective.get(k)==value for k,value in original.items())
            # Cantoneiras Maq. is a line aggregate, never copied into each code.
            accumulated=selected['macro_quantity'] if selected else None
            remaining=max(float(need['quantity_required'])-float(accumulated),0) if compatible and accumulated is not None and need['quantity_required'] is not None else None
            macros.append({'plan_key':line['plan_key'],'snapshot_id':line['snapshot_id'],
                'quantity':accumulated,'remaining':remaining,
                'line_remaining':line['remaining_quantity'],'operation':op['code'],'compatible':compatible})
            if selected and compatible:
                warnings.extend(selected.get('coverage_reasons',[]))
                for f in selected['ocr_records']:
                    if latest(conn,f['record_id']) is None:
                        produced=next((r for r in detail['production'] if r['id']==f['record_id']),{})
                        facts.append({**f,'child_key':line['plan_key'] if produced.get('plan_refs') else None,'association':'source_plan'})
    for decision in decisions:
        if decision['status']!='associated':continue
        for a in decision['allocations']:
            if a['need_id']!=str(need['id']) or a['operation_id']!=str(op['id']):continue
            if a['technical_revision']!=need['technical_revision']:
                warnings.append('Rever a compatibilidade da produção '+str(decision['production_record_id']));continue
            try:
                actual=fact(conn,decision['production_record_id'])
            except planning.PlanningError as exc:
                if exc.status!=404:raise
                warnings.append('Registo '+str(decision['production_record_id'])+' já não está disponível como produção validada; decisão anterior preservada.')
                continue
            if not decision_valid(conn,actual,decision):
                warnings.append('A evidência de produção mudou.');continue
            if allocation_gaps(actual,decision):
                warnings.append('Registo '+str(actual['id'])+': distribuição parcial; produção por atribuir.')
            facts.append({'record_id':actual['id'],'child_key':a.get('child_key'),'quantity':a['quantity'],'sheet_uid':actual['sheet_uid'],
                          'association':str(decision['id']),'association_revision':decision['revision'],
                          **({k:actual[k] for k in ('source','instance_id','source_revision','source_content_hash')} if actual.get('source')=='ocr_original' else {})})
    unique={ (f['record_id'],f.get('child_key')):f for f in facts }
    facts=list(unique.values())
    if len({(f.get('source','mes'),f.get('instance_id')) for f in facts})>1:
        warnings.append('Sobreposição entre origens OCR por resolver.')
    ocr=sum(f['quantity'] for f in facts) if facts and not warnings and all(f['quantity'] is not None for f in facts) else None
    macro_remaining=macros[0]['remaining'] if len(macros)==1 and macros[0]['compatible'] else None
    result=needs.serial({'need_id':need['id'],'operation_id':op['id'],'operation':op['code'],'technical_revision':need['technical_revision'],
        'required':need['quantity_required'],'specification':need['specification'],'sources':source_dependencies,
        'macro':macros,'macro_remaining':macro_remaining,'ocr_records':facts,'ocr_quantity':ocr,'warnings':warnings,
        'balance_reason':'A peça ou a quantidade total difere da linha da macro. Confirma a quantidade em falta.' if any(not m['compatible'] for m in macros) else None})
    # Operational validity checks CPIS separately. An unrelated CPIS refresh does not invalidate balance decisions.
    dependencies={**result,'macro':[{k:m.get(k) for k in ('quantity','remaining','line_remaining','operation','compatible')} for m in result['macro']],
        'sources':[{k:v for k,v in s.items() if k!='id' or s.get('kind')!='plan_line'} for s in result['sources']],
        'ocr_records':[{k:v for k,v in f.items() if k!='child_key' or f.get('association')!='source_plan'} for f in result['ocr_records']]}
    result['evidence_hash']=needs.digest(dependencies)
    return result


def current_conference(conn,need,op,proof):
    row=conn.execute('SELECT * FROM planning_mtg.need_conferences WHERE need_id=%s AND operation_id=%s ORDER BY created_at DESC,id DESC LIMIT 1',(need['id'],op['id'])).fetchone()
    return row if row and row['evidence_hash']==proof['evidence_hash'] else None


def get_evidence(need_id,operation_id):
    with planning.connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('planning-needs-writes',0))")
        need=needs.refresh(conn,needs.load(conn,need_id))
        op=conn.execute('SELECT * FROM planning_mtg.need_operations WHERE id=%s AND need_id=%s',(needs.uid(operation_id),need['id'])).fetchone()
        if not op:raise planning.PlanningError('Operação não encontrada.',404)
        proof=evidence(conn,need,op)
        history=conn.execute('SELECT * FROM planning_mtg.need_conferences WHERE need_id=%s AND operation_id=%s ORDER BY created_at DESC',(need['id'],op['id'])).fetchall()
        for row in history:row['valid']=row['evidence_hash']==proof['evidence_hash']
        return needs.serial({'evidence':proof,'conferences':history,'need_revision':need['revision']})


def confer(payload):
    with planning.connect() as conn:
        _,actor,old=needs.command(conn,payload)
        if old:return old
        need=needs.refresh(conn,needs.load(conn,payload.get('need_id')))
        needs.load(conn,need['id'],needs.expected_revision(payload))
        op=conn.execute('SELECT * FROM planning_mtg.need_operations WHERE id=%s AND need_id=%s',(needs.uid(payload.get('operation_id')),need['id'])).fetchone()
        if not op:raise planning.PlanningError('Seleciona uma operação da necessidade.')
        proof=evidence(conn,need,op)
        if payload.get('evidence_hash')!=proof['evidence_hash']:raise planning.PlanningError('A evidência mudou. Reabre a conferência.',409)
        required=integer(payload.get('accepted_required'));remaining=integer(payload.get('accepted_remaining'))
        if remaining>required:raise planning.PlanningError('O saldo aceite não pode ultrapassar a necessidade aceite.')
        if required!=need['quantity_required']:raise planning.PlanningError('Atualiza primeiro a quantidade necessária na ficha para conservar a revisão técnica.',409)
        reason=str(payload.get('reason') or '').strip()
        if not reason:raise planning.PlanningError('Justifica o saldo aceite.')
        ident=uuid.uuid4()
        conn.execute('''INSERT INTO planning_mtg.need_conferences(id,need_id,operation_id,accepted_required,accepted_remaining,evidence_hash,evidence,actor,reason)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)''',(ident,need['id'],op['id'],required,remaining,proof['evidence_hash'],Jsonb(proof),actor,reason))
        needs.event(conn,need,'balance_conference',actor,{'id':str(ident),'operation_id':str(op['id']),'required':required,'remaining':remaining,'evidence':proof,'reason':reason})
        return needs.finish(conn,payload,{'id':ident,'evidence_hash':proof['evidence_hash']})


def original_pending(of=None,area=None,page=1,state='pending',reason=None,include_unknown=False):
    from . import planning_original_production as original
    area=area or 'perfis';planning.check_area(area);page=max(int(page),1)
    normalized=order_number(of) if of else None
    if of and not normalized:raise planning.PlanningError('Indica uma OF válida.')
    if state not in ('pending','associated','unrelated','all'):raise planning.PlanningError('Filtro de associação inválido.')
    labels={'piece':'Peça por identificar','geometry':'Geometria incompleta','ambiguous':'Várias peças possíveis','operation':'Operação / associação por confirmar'}
    with planning.connect(readonly=True) as conn:
        decisions={d['production_record_id']:d for d in latest_all(conn,original_only=True)}
        result=[]
        for raw in original.records(conn,area,None if include_unknown else normalized):
            if normalized and raw['of']!=normalized and not (include_unknown and raw['of'] is None):continue
            record=original.decision_record(raw)
            fingerprint=evidence_fingerprint(record);decision=decisions.get(record['id']);stale=False
            if decision:
                stale=not decision_valid(conn,record,decision)
            gaps=allocation_gaps(record,decision)
            effective='pending' if stale or not decision or gaps else decision['status']
            if state!='all' and effective!=state:continue
            selected_of=record['of'] or (normalized if include_unknown else None)
            candidates=conn.execute('SELECT * FROM planning_mtg.needs WHERE production_order_no=%s ORDER BY component_ref',(selected_of,)).fetchall() if selected_of else []
            matching=[n for n in candidates if needs.catalogs.key(n['component_ref'])==needs.catalogs.key(record['model_ref'])]
            code='piece' if not record['model_ref'] else 'geometry' if record['length_mm'] is None or not record['profile_type'] else 'ambiguous' if len(matching)>1 else 'operation'
            if reason and reason!=code:continue
            result.append({**record,'evidence_hash':fingerprint,'decision':needs.serial(decision),'requires_review':bool(stale),
                'unallocated':gaps,'candidates':needs.serial(candidates),'reason_code':code,
                'reason':'Distribuição parcial; produção por atribuir.' if gaps else
                    'Associação confirmada.' if effective=='associated' else 'Sem correspondência confirmada.' if effective=='unrelated' else labels[code]})
        return {'records':result[(page-1)*50:page*50],'page':page,'total':len(result),'source':'original'}
