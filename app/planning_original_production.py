"""Read-only adapter from published original OCR snapshots to planning evidence.

Source names and IDs remain distinct from MES. Missing geometry or operation is
reported by the shared association engine; it is never inferred from OF/ref alone.
"""
from __future__ import annotations
from datetime import date
from . import planning
from .dossiers.models import order_number

APPS={'perfis':'kanban-mes-mtg2','cantoneiras':'kanban-mes'}


def available(conn):
    return bool(conn.execute("SELECT to_regclass('ocr_original.instances') t").fetchone()['t'])


def snapshot_token(conn):
    if not available(conn):return []
    return [(str(r['id']),str(r['current_snapshot'])) for r in conn.execute('SELECT id,current_snapshot FROM ocr_original.instances ORDER BY id')]


def sheets(conn,of=None):
    if not available(conn):return []
    return conn.execute('''SELECT s.* FROM ocr_original.instances i
        JOIN ocr_original.snapshot_sheets x ON x.snapshot_id=i.current_snapshot
        JOIN ocr_original.sheets s USING(instance_id,sheet_id,content_hash)
        WHERE (%s::text IS NULL OR EXISTS(SELECT 1 FROM jsonb_array_elements(s.payload->'production') p
            WHERE regexp_replace(trim(coalesce(p->>'production_order',p->>'of')),'^OF[ ._-]*','','i')=%s))
        ORDER BY s.instance_id,s.sheet_id''',(of,of[2:] if of else None)).fetchall()


def normalize(sheet,area):
    payload=sheet['payload'];header=(payload.get('data') or {}).get('header') or {}
    declared_area=payload.get('area') or header.get('area')
    if declared_area in APPS and declared_area!=area:return []
    result=[]
    for line in payload.get('production',[]):
        # Canonical import retains the original production_rows schema verbatim.
        of=order_number(line.get('production_order') or line.get('of'))
        machine=line.get('machine') or payload.get('machine')
        sheet_key='original:'+str(sheet['instance_id'])+':'+str(sheet['sheet_id'])
        ident=sheet_key+':'+str(line['row_index'])
        identity=line.get('plan_identity') or {}
        operation=line.get('operation') or line.get('operation_code')
        result.append({'id':ident,'sheet_uid':sheet_key,'sheet_no':sheet['sheet_id'],
            'source':'ocr_original','instance_id':str(sheet['instance_id']),
            'source_revision':sheet['source_revision'],'source_content_hash':sheet['content_hash'],
            # source_app routes the shared area matcher; source retains provenance.
            'source_app':APPS[area],'area':area,'declared_area':declared_area,
            'row_index':line['row_index'],'production_order':of,'of':of,
            'sales_order':line.get('sales_order') or line.get('ov'),
            'model_ref':line.get('model_ref') or line.get('reference') or line.get('modelo'),
            'profile_type':line.get('profile_type') or identity.get('profile_type'),
            'length_mm':planning._number(line.get('length_mm') if line.get('length_mm') is not None else line.get('comp_mm')),
            'quantity':planning._number(line.get('quantity') if line.get('quantity') is not None else line.get('qtd')),
            'sheet_date':date.fromisoformat(planning._date(line.get('sheet_iso_date'))) if planning._date(line.get('sheet_iso_date')) else None,
            'validated_at':line.get('validated_at') or payload.get('sheet',{}).get('validated_at'),
            'machine':machine,'hours_worked':planning._number(line.get('sheet_hours')),
            'matched_plan_key':None,'plan_snapshot_id':None,'plan_refs':[],
            'full_profile':False,'frozen_identity':identity,'extra':{'operation_code':operation},
            'original':line,'source_url':'https://mtg2.nikufra.ai/sheet/'+str(sheet['sheet_id'])})
    return result


def decision_record(record):
    from . import planning_needs as needs
    return needs.serial({**record,'area':record['declared_area'] if record['declared_area'] in APPS else None,
                         'source_app':'ocr_original','children':[]})


def decision_context(conn):
    from . import planning_associations as assoc
    return ({d['production_record_id']:d for d in assoc.latest_all(conn,original_only=True)},
            {str(n['id']):n['technical_revision'] for n in conn.execute('SELECT id,technical_revision FROM planning_mtg.needs')})


def assigned_areas(conn,record,decisions,revisions):
    from . import planning_associations as assoc
    decision=decisions.get(record['id'])
    if not decision or decision['status']!='associated':return set()
    if not assoc.decision_valid(conn,decision_record(record),decision,technical_revisions=revisions):return set()
    return {a['area'] for a in decision['allocations'] if a.get('area') in APPS}


def records(conn,area,of=None):
    planning.check_area(area)
    decisions,revisions=decision_context(conn)
    result=[]
    for sheet in sheets(conn,of):
        for r in normalize(sheet,area):
            if of is not None and r['of']!=of:continue
            areas=assigned_areas(conn,r,decisions,revisions)
            if areas and area not in areas:continue
            result.append(r)
    return result


def hour_rows(conn,area):
    """One physical declaration per original sheet, shared across area views."""
    decisions,revisions=decision_context(conn)
    result=[]
    for sheet in sheets(conn):
        payload=sheet['payload'];header=(payload.get('data') or {}).get('header') or {}
        declared=payload.get('area') or header.get('area')
        rows=normalize(sheet,declared if declared in APPS else 'perfis')
        areas=set();unclassified=False
        for row in rows:
            assigned=assigned_areas(conn,row,decisions,revisions)
            classified=assigned or ({declared} if declared in APPS else set())
            areas.update(classified);unclassified=unclassified or not classified
        if unclassified or not areas:areas.update([declared] if declared in APPS else planning.AREAS)
        if area not in areas:continue
        raw_hours=[r.get('sheet_hours') for r in payload.get('production',[]) if r.get('sheet_hours') is not None]
        if not raw_hours:
            footer=(payload.get('data') or {}).get('footer') or {}
            raw_hours=[footer['horas_trabalhadas']] if footer.get('horas_trabalhadas') not in (None,'') else []
        hours=sorted({planning._number(h) for h in raw_hours if planning._number(h) is not None})
        valid=bool(raw_hours) and len(hours)==1 and all(planning._number(h) is not None for h in raw_hours)
        machines=sorted({r['machine'] for r in rows if r['machine']} or ({payload['machine']} if payload.get('machine') else set()))
        dates=sorted({str(r['sheet_date']) for r in rows if r['sheet_date']})
        key='original:'+str(sheet['instance_id'])+':'+str(sheet['sheet_id'])
        result.append({'key':key,'sheet_uid':key,'areas':sorted(areas),
            'values':{'source':'ocr_original','sheet':sheet['sheet_id'],'production_date':dates[0] if len(dates)==1 else None,
                'machine':machines[0] if len(machines)==1 else None,'hours_worked':hours[0] if valid else None},
            'original_hours':raw_hours,'original_machines':machines,
            'source_revision':sheet['source_revision'],'source_content_hash':sheet['content_hash'],
            'instance_id':str(sheet['instance_id']),
            'warnings':[] if valid and len(machines)==1 and len(dates)==1 else ['Horas, máquina ou período da folha original por confirmar.']})
    return result


def diagnostics(conn,record_ids):
    from .raw import query,projection
    from . import planning_needs as needs
    current=needs.serial(snapshot_token(conn));result={str(key):[] for key in record_ids}
    if not conn.execute("SELECT to_regclass('planning_mtg.raw_generations') t").fetchone()['t']:return result
    labels={'technical_unique':'Identidade técnica única','explicit':'Identidade comprovada',
            'associated':'Associação confirmada','unrelated':'Sem correspondência no Planeamento, por decisão humana',
            'source_overlap':'Sobreposição ou cobertura entre origens por resolver',
            'ambiguous':'Várias peças possíveis','incomplete':'Identidade técnica incompleta',
            'unmatched':'Sem peça compatível identificada'}
    for area in planning.AREAS:
        try:
            gen=query.generation(conn,area,dataset='production')
            if (gen['metadata'].get('original_ocr_snapshots')!=current or gen['metadata'].get('source_refresh_pending')
                    or gen['metadata'].get('core_source_fingerprint',gen['metadata'].get('source_fingerprint'))!=projection.fingerprint(conn,area)):
                for key in result:result[key].append({'area':area,'state':'pending_publication','reason':'Revisão de origem ainda não aplicada ao planeamento.'})
                continue
            base,args=query.source(gen)
            for row in conn.execute("SELECT c.values_json,c.detail"+base+" AND c.detail->>'record_id'=ANY(%s)",args+[list(result)]):
                v,d=row['values_json'],row['detail'];state=v.get('association_status')
                reason=labels.get(state,'Identidade e operação por confirmar')
                if v.get('operation')=='operacao_por_confirmar':reason+='; operação por confirmar'
                result[str(d['record_id'])].append({'area':area,'state':state,'reason':reason,
                    'scope_state':'out_of_scope' if state=='unrelated' else 'applicable' if state in ('associated','explicit','technical_unique') and v.get('operation')!='operacao_por_confirmar' else 'pending',
                    'operation':v.get('operation'),'planning_keys':d.get('planning_keys',[]),'quantity':v.get('quantity'),
                    'generation':gen['id'],'warnings':d.get('warnings',[])})
        except planning.PlanningError as exc:
            if exc.status!=503:raise
            for key in result:result[key].append({'area':area,'state':'not_published','reason':'Planeamento ainda não publicado.'})
    return result


def fact(conn,record_id):
    from . import planning_needs as needs
    import re,uuid
    match=re.fullmatch(r'original:([0-9a-f-]{36}):(\d+):(\d+)',str(record_id))
    if not match:raise planning.PlanningError('Identificador de produção original inválido.')
    try:instance=uuid.UUID(match[1])
    except ValueError:raise planning.PlanningError('Instância OCR inválida.') from None
    sheet=conn.execute("""SELECT s.* FROM ocr_original.instances i
        JOIN ocr_original.snapshot_sheets x ON x.snapshot_id=i.current_snapshot
        JOIN ocr_original.sheets s USING(instance_id,sheet_id,content_hash)
        WHERE s.instance_id=%s AND s.sheet_id=%s""",(instance,int(match[2]))).fetchone() if available(conn) else None
    if not sheet:raise planning.PlanningError('Registo original validado não encontrado.',404)
    header=(sheet['payload'].get('data') or {}).get('header') or {}
    declared=sheet['payload'].get('area') or header.get('area')
    record=next((r for r in normalize(sheet,declared if declared in APPS else 'perfis') if str(r['row_index'])==match[3]),None)
    if not record:raise planning.PlanningError('Registo original validado não encontrado.',404)
    return decision_record(record)
