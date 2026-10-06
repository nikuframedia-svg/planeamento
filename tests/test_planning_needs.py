"""Canonical needs on disposable PostgreSQL; no operational writes."""
import copy
import uuid
from pathlib import Path
import pytest
import psycopg
from psycopg.types.json import Jsonb
from app import planning, planning_needs as needs, planning_catalogs as catalogs, planning_associations as assoc
from tests.test_planning_registry import registry, postgres16

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture()
def canonical(registry):
    with psycopg.connect(registry,autocommit=True) as conn:
        conn.execute((ROOT/'sql/020_planning_needs.sql').read_text())
        conn.execute((ROOT/'sql/022_planning_order_registration.sql').read_text())
        conn.execute('TRUNCATE planning_mtg.order_registration')
        conn.execute('TRUNCATE planning_mtg.needs,planning_mtg.need_operations,planning_mtg.need_sources,planning_mtg.need_commands,planning_mtg.need_events,planning_mtg.field_state,planning_mtg.association_decisions,planning_mtg.need_conferences,planning_mtg.audit_outbox CASCADE')
        if conn.execute("SELECT to_regclass('planning_mtg.original_association_decisions')").fetchone()[0]:
            conn.execute('TRUNCATE planning_mtg.original_association_decisions')
        conn.execute("INSERT INTO raw_mtg.other_sheet_rows VALUES ('s1','Dados',3,%s),('s1','AreaSecaoCorte',1,%s),('s1','AreaSecaoCorte',2,%s),('s1','AreaSecaoCorte',3,%s)",
          (Jsonb({'values':[None,'MEBA',None,None,'Tubo redondo',None,'Equipa 1']}),Jsonb({'values':[None]*22+['Tubo redondo']}),Jsonb({'values':[None]*22+['88.9x3']}),Jsonb({'values':['Tubo redondo']})))
    return registry


def vals():
    return {'component_ref':'NEW-A','material_type':'Tubo redondo','profile':'88.9x3','length_mm':1000,'outer_diameter_mm':88.9,'thickness_mm':3,'quantity_required':100,'quantity_to_plan':100,'operation':'corte','machine':'MEBA'}


def request(**kw):return {'request_id':str(uuid.uuid4()),'actor':'Teste',**kw}


def create():return needs.resolve(request(area='perfis',production_order_no='4200',values=vals()))


def save(n,values=None,**kw):
    return needs.save(request(need_id=n['need_id'],expected_revision=n['revision'],area='perfis',catalog_version='s1',values=values or vals(),**kw))


def test_identity_idempotency_history_and_revision(canonical):
    p=request(area='perfis',production_order_no='4200',values=vals())
    n=needs.resolve(p)
    assert needs.resolve(p)==n
    assert needs.resolve(request(area='perfis',production_order_no='OF4200',values=vals()))['need_id']==n['need_id']
    record=save(n)
    changed=vals();changed['notes']='Só uma observação';record2=save(record,changed)
    assert needs.detail(n['need_id'])['need']['technical_revision']==2  # first normalization is a technical revision
    assert len(needs.history(n['need_id'])['events'])>=3
    with pytest.raises(planning.PlanningError) as exc:save(n)
    assert exc.value.status==409
    assert record2['record_revision']==2


def test_quantities_not_summed_and_geometry_not_merged(canonical):
    n=create(); other=vals();other['quantity_required']=60
    result=needs.resolve(request(area='perfis',production_order_no='OF4200',values=other))
    assert result['needs_decision'] and result['candidates'][0]['quantity_required']==100
    other['length_mm']=2000
    assert needs.resolve(request(area='perfis',production_order_no='4200',values=other))['needs_decision']
    with pytest.raises(planning.PlanningError):needs.resolve(request(area='perfis',production_order_no='OF4200/33',values=vals()))


def test_conference_without_plan_and_notes_do_not_invalidate(canonical):
    n=save(create()); proof=assoc.get_evidence(n['need_id'],n['operation_id'])
    assert proof['evidence']['macro_remaining'] is None and proof['evidence']['ocr_quantity'] is None
    p=request(need_id=n['need_id'],operation_id=n['operation_id'],expected_revision=n['revision'],evidence_hash=proof['evidence']['evidence_hash'],accepted_required=100,accepted_remaining=70,reason='Conferência física')
    assert assoc.confer(p)==assoc.confer(p)
    changed=vals();changed['notes']='Observação';n=save(n,changed)
    assert assoc.get_evidence(n['need_id'],n['operation_id'])['conferences'][0]['valid']
    changed['length_mm']=900;n=save(n,changed)
    assert not assoc.get_evidence(n['need_id'],n['operation_id'])['conferences'][0]['valid']


def test_catalog_columns_and_operation_blocks(canonical):
    with psycopg.connect(canonical) as conn:
        for i,row in enumerate([
            [None,'Ficep',None,None,'Cantoneira',None,None,112,'CORTE',None,'Equipa'],
            [None,None,None,None,None,None,None,'2ª Operação',None,None,'Equipa 9'],
            [None,None,None,None,None,None,None,209,'ALARGAR',None,'Equipa 10'],
            [None,None,None,None,None,None,None,'B','NÃO GALVANIZA']],3):
            conn.execute("INSERT INTO raw_mtg.other_sheet_rows VALUES ('c1','Dados',%s,%s)",(i,Jsonb({'values':row})))
    cat=catalogs.catalog('cantoneiras')
    assert cat['material_types']==['Cantoneira']
    assert cat['teams']==['Equipa 10','Equipa 9']
    assert [x['value'] for x in cat['operations']]==['112']
    none=next(x for x in cat['additional_operations'] if x['value']=='0')
    assert none['countable'] is False and none['source']['kind']=='planning_rule'
    assert cat['additional_operations'][-1]['countable'] is False
    bad=vals();bad['operation']='corte';bad['material_type']='Cantoneira';bad['profile']='';bad['machine']='Ficep'
    with pytest.raises(planning.PlanningError) as exc:catalogs.validate(bad,cat)
    assert 'operation' in exc.value.fields


def test_zero_additional_operation_is_persisted_without_creating_an_operation(canonical):
    with psycopg.connect(canonical) as conn:
        for index,row in enumerate([
            [None,'Ficep',None,None,'Cantoneira',None,None,112,'CORTE'],
            [None,None,None,None,None,None,None,'2ª Operação'],
            [None,None,None,None,None,None,None,0,'SEM OPERAÇÃO']],3):
            conn.execute("INSERT INTO raw_mtg.other_sheet_rows VALUES ('c1','Dados',%s,%s)",(index,Jsonb({'values':row})))
    cat=catalogs.catalog('cantoneiras')
    zeros=[x for x in cat['additional_operations'] if x['value']=='0']
    assert len(zeros)==1 and zeros[0]['countable'] is False
    values={**vals(),'material_type':'Cantoneira','profile':'L50X50X5','machine':'Ficep',
            'operation':'112','operation_detail':'0'}
    created=needs.resolve(request(area='cantoneiras',production_order_no='OF909090',values=values))
    saved=needs.save(request(area='cantoneiras',need_id=created['need_id'],expected_revision=created['revision'],
                             catalog_version='c1',record_status='draft',values=values))
    result=needs.detail(saved['need_id'])
    assert [op['code'] for op in result['operations']]==['112']
    assert result['records'][0]['values_json']['operation_detail']=='0'
    with pytest.raises(planning.PlanningError) as exc:
        catalogs.validate({**values,'operation':'0'},cat)
    assert 'operation' in exc.value.fields


def test_invalid_profile_geometry_and_week(canonical):
    cat=catalogs.catalog('perfis'); v=vals();v['profile']='UPN50x38'
    with pytest.raises(planning.PlanningError):catalogs.validate(v,cat)
    v=vals();v['picking_week']=53;v['picking_year']=2025
    with pytest.raises(planning.PlanningError):catalogs.validate(v,cat)
    v=vals();v['outer_diameter_mm']='88,9'
    assert catalogs.validate(v,cat,ready=True)['outer_diameter_mm']==88.9
    v['thickness_mm']=None
    with pytest.raises(planning.PlanningError):catalogs.validate(v,cat,ready=True)


def test_pdf_and_manual_share_need_without_quantity_addition(canonical,monkeypatch):
    from app.dossiers import store
    raw=vals();document={'id':'doc','revision':1,'production_order':'OF4200','status':'ready','pieces':[{'id':'piece','revision':1,'state':'ready','values':raw}]}
    monkeypatch.setattr(store,'get_document',lambda ident:copy.deepcopy(document))
    manual=create()
    pdf=needs.resolve(request(area='perfis',source={'kind':'pdf','id':'doc/piece'}))
    assert pdf['need_id']==manual['need_id']
    saved=save(pdf);document['revision']=2;document['pieces'][0]['revision']=2;document['pieces'][0]['values']['length_mm']=900
    refreshed=needs.detail(pdf['need_id'])
    assert refreshed['need']['specification']['length_mm']==1000
    state=next(f for f in refreshed['fields'] if f['field']=='length_mm')
    assert state['suggestion']==900 and state['value']==1000 and state['human_decision'] is None
    # Explicit confirmation of an unchanged suggested value must count as a human choice.
    assert refreshed['need']['revision']>saved['revision']


def test_human_association_conserves_quantity(canonical):
    n=save(create())
    with psycopg.connect(canonical) as conn:
        conn.execute("INSERT INTO mes_kanban.validated_sheets(sheet_uid,sheet_date,template_name,family,operator_name,image_sha256,raw_extraction,sheet_data,validated_by,source_app) VALUES ('assoc-test','2026-09-17','tpl999','perfis','Teste','hash','{}','{}','Teste','kanban-mes-mtg2')")
        rid=conn.execute("INSERT INTO mes_kanban.production_records(sheet_uid,row_index,sheet_date,family,operator_name,production_order,quantity,validated_at) VALUES ('assoc-test',0,'2026-09-17','perfis','Teste','4200',4,now()) RETURNING id").fetchone()[0]
    with planning.connect(readonly=True) as conn:record=assoc.fact(conn,rid)
    p=request(production_record_id=rid,expected_revision=0,evidence_hash=needs.digest(record),reason='Folha conferida',allocations=[{'need_id':n['need_id'],'operation_id':n['operation_id'],'expected_need_revision':n['revision'],'quantity':4}])
    result=assoc.save(p);assert assoc.save(p)==result
    assert assoc.get_evidence(n['need_id'],n['operation_id'])['evidence']['ocr_quantity']==4
    bad=copy.deepcopy(p);bad.update(request_id=str(uuid.uuid4()),expected_revision=1);bad['allocations'][0]['quantity']=5
    with pytest.raises(planning.PlanningError):assoc.save(bad)
    pending=request(production_record_id=rid,expected_revision=1,evidence_hash=needs.digest(record),reason='Reabrir',status='pending')
    assoc.save(pending)
    assert assoc.get_evidence(n['need_id'],n['operation_id'])['evidence']['ocr_quantity'] is None


def test_concurrent_creation_and_request_conflict(canonical):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:create(),range(2)))
    assert results[0]['need_id']==results[1]['need_id']
    p=request(area='perfis',production_order_no='4200',values=vals());needs.resolve(p)
    p['values']['quantity_required']=99
    with pytest.raises(planning.PlanningError) as exc:needs.resolve(p)
    assert exc.value.status==409


def test_accept_unchanged_suggestion_preserves_human_choice(canonical,monkeypatch):
    from app.dossiers import store
    document={'id':'doc','revision':1,'production_order':'OF4200','status':'ready','pieces':[{'id':'piece','revision':1,'state':'ready','values':vals()}]}
    monkeypatch.setattr(store,'get_document',lambda ident:copy.deepcopy(document))
    n=needs.resolve(request(area='perfis',source={'kind':'pdf','id':'doc/piece'}))
    n=save(n,decisions={'length_mm':'accept'})
    document['pieces'][0]['revision']=2;document['pieces'][0]['values']['length_mm']=900
    state=next(f for f in needs.detail(n['need_id'])['fields'] if f['field']=='length_mm')
    assert state['value']==1000 and state['suggestion']==900 and state['human_decision']=='accept' and state['requires_review']


def test_migration_preserves_legacy_record_and_revision(canonical):
    from tests.test_planning_registry import payload
    old=planning.save_record(payload())
    result=needs.migrate_legacy_records()
    assert result['bound']==1
    data=planning.get_record(old['id'])
    assert data['record']['revision']==1 and data['record']['need_id']
    assert len(data['versions'])==1
    assert any(f['source']['kind']=='historical' for f in needs.history(data['record']['need_id'])['fields'])
    assert needs.migrate_legacy_records()['bound']==0


def test_common_output_deduplicates_pdf_and_record(canonical,tmp_path,monkeypatch):
    import hashlib
    import io
    from datetime import datetime, timezone
    from openpyxl import load_workbook
    from app import cpis_sync, planning_output
    from app.dossiers import store
    from tests.test_planning_registry import direct_row
    from tests.test_dossier_macro import workbook_source
    source=workbook_source();path=tmp_path/'Met2_Plan_Perfis.xlsm';path.write_bytes(source)
    cpis_sync.publish([direct_row('OF4200')],datetime.now(timezone.utc),central_dsn=canonical)
    with psycopg.connect(canonical) as conn:
        conn.execute("UPDATE audit_mtg.snapshots SET source_path=%s,source_sha256=%s WHERE snapshot_id='s1'",(str(path),hashlib.sha256(source).hexdigest()))
        conn.execute("DELETE FROM raw_mtg.plan_production_rows WHERE source_line_id='s1:11'")
        conn.execute("UPDATE raw_mtg.plan_production_rows SET excel_row=7 WHERE snapshot_id='s1'")
    n=save(create());proof=assoc.get_evidence(n['need_id'],n['operation_id'])
    assoc.confer(request(need_id=n['need_id'],operation_id=n['operation_id'],expected_revision=n['revision'],evidence_hash=proof['evidence']['evidence_hash'],accepted_required=100,accepted_remaining=100,reason='Saldo conferido'))
    doc={'id':'output-doc','revision':1,'production_order':'OF4200','status':'ready','pieces':[{'id':'output-piece','revision':1,'state':'ready','values':vals()}]}
    monkeypatch.setattr(store,'get_document',lambda ident:copy.deepcopy(doc))
    linked=needs.resolve(request(area='perfis',source={'kind':'pdf','id':'output-doc/output-piece'}))
    # Adding supporting evidence changes the dependencies of a previous balance decision.
    proof=assoc.get_evidence(n['need_id'],n['operation_id'])
    assoc.confer(request(need_id=n['need_id'],operation_id=n['operation_id'],expected_revision=proof['need_revision'],evidence_hash=proof['evidence']['evidence_hash'],accepted_required=100,accepted_remaining=100,reason='PDF conferido'))
    prepared=vals();prepared['quantity_to_plan']=80
    n=save(linked,prepared,record_status='ready')
    p=planning_output.create_proposal(request(record_ids=[n['record_id']],pdf_refs=[{'id':'output-doc/output-piece','version':'1:1'}]))
    assert p['added']==1
    assert any(c['field']=='quantity_required' and c['after']==100 for c in p['cells'])
    output=planning_output.generate(p['id'],p['proposal_fingerprint'])
    sheet=load_workbook(io.BytesIO(output),data_only=False)['Planeamento']
    assert sheet['L8'].value=='NEW-A'
    assert path.read_bytes()==source
    doc['pieces'][0]['revision']=2
    with pytest.raises(planning.PlanningError,match='origem PDF'):planning_output.generate(p['id'],p['proposal_fingerprint'])


def test_legacy_endpoint_adapter_retry_is_atomic(canonical):
    p=request(area='perfis',production_order_no='OF4200',values=vals(),record_status='draft')
    first=needs.save_legacy_payload(p);again=needs.save_legacy_payload(p)
    assert first['id']==again['id'] and again['replayed']
    p['values']['quantity_required']=101
    with pytest.raises(planning.PlanningError) as exc:needs.save_legacy_payload(p)
    assert exc.value.status==409


def test_pending_feed_filters_unknown_orders_without_fabricating_identity(canonical):
    with psycopg.connect(canonical) as conn:
        conn.execute("INSERT INTO mes_kanban.validated_sheets(sheet_uid,sheet_date,template_name,family,operator_name,image_sha256,raw_extraction,sheet_data,validated_by,source_app) VALUES ('unknown-of-test','2026-09-17','tpl999','perfis','Teste','hash','{}','{}','Teste','kanban-mes-mtg2')")
        rid=conn.execute("INSERT INTO mes_kanban.production_records(sheet_uid,row_index,sheet_date,family,operator_name,production_order,quantity,validated_at) VALUES ('unknown-of-test',0,'2026-09-17','perfis','Teste','OF4200/33',0,now()) RETURNING id").fetchone()[0]
    assert rid not in [r['id'] for r in assoc.pending('OF4200','perfis')['records']]
    found=next(r for r in assoc.pending('OF4200','perfis',include_unknown=True)['records'] if r['id']==rid)
    assert found['production_order']=='OF4200/33' and found['quantity']==0
    assert found['reason_code']=='piece'
    assert rid in [r['id'] for r in assoc.pending('OF4200','perfis',reason='piece',include_unknown=True)['records']]


def test_editor_presentation_contract_is_shared(canonical):
    cat=catalogs.catalog('perfis')
    fields={f['id']:f for f in cat['fields']}
    assert fields['quantity_required']['label']=='Quantidade'
    assert fields['quantity_to_plan']['label']=='Quantidade a preparar agora'
    assert fields['quantity_required']['group']=='piece'
    assert not fields['quantity_to_plan']['editor_visible']
    assert fields['grade']['group']=='piece' and fields['picking_week']['group']=='piece'
    assert fields['length_mm']['visibility']=='always'
    assert fields['quantity_to_plan']['help']
    assert needs.need_for_pdf('not-linked','piece')=={'need_id':None}


def test_removed_production_preserves_human_decision_and_returns_unavailable_evidence(canonical):
    n=save(create())
    with psycopg.connect(canonical) as conn:
        conn.execute("INSERT INTO mes_kanban.validated_sheets(sheet_uid,sheet_date,template_name,family,operator_name,image_sha256,raw_extraction,sheet_data,validated_by,source_app) VALUES ('removed-assoc','2026-09-17','tpl999','perfis','Teste','hash','{}','{}','Teste','kanban-mes-mtg2')")
        rid=conn.execute("INSERT INTO mes_kanban.production_records(sheet_uid,row_index,sheet_date,family,operator_name,production_order,quantity,validated_at) VALUES ('removed-assoc',0,'2026-09-17','perfis','Teste','4200',4,now()) RETURNING id").fetchone()[0]
    with planning.connect(readonly=True) as conn:record=assoc.fact(conn,rid)
    decision=assoc.save(request(production_record_id=rid,expected_revision=0,evidence_hash=needs.digest(record),reason='Folha conferida',allocations=[{'need_id':n['need_id'],'operation_id':n['operation_id'],'expected_need_revision':n['revision'],'quantity':4}]))
    with psycopg.connect(canonical) as conn:
        conn.execute('DELETE FROM mes_kanban.production_records WHERE id=%s',(rid,))
    evidence=assoc.get_evidence(n['need_id'],n['operation_id'])['evidence']
    assert evidence['ocr_quantity'] is None
    assert evidence['ocr_records']==[]
    assert any(str(rid) in warning and 'produção validada' in warning for warning in evidence['warnings'])
    with planning.connect(readonly=True) as conn:
        retained=assoc.latest(conn,rid)
    assert str(retained['id'])==decision['id'] and retained['status']=='associated'
