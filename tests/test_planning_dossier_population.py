"""PDF context and active exports use planning closure, with separate operational gates."""
import os
import uuid
import io
import hashlib
from zipfile import ZipFile
from datetime import datetime,timezone

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app import planning,planning_hub,planning_output,cpis_sync,planning_needs as needs
from app.dossiers import cpis,pipeline,store
from tests.test_planning_needs import canonical,registry,postgres16,request
from tests.test_planning_registry import direct_row,payload
from tests.test_dossier_macro import workbook_source
from tests.test_dossiers import piece_values,plan_row,context,isolated_dossiers,pdf_bytes,FakeVision

pytestmark=[pytest.mark.pg_integration,pytest.mark.skipif(os.environ.get('RUN_PG_INTEGRATION')!='1',reason='Disposable PostgreSQL opt-in')]


def codes(ctx):
    return {i['code'] for i in ctx['issues']}


def test_pdf_uses_all_imported_copies_then_current_direct_cpis(canonical):
    with psycopg.connect(canonical) as conn:
        conn.execute("UPDATE raw_mtg.cpis_rows SET status=' FeChAdA ' WHERE snapshot_id='c1'")
    imported=cpis.read_context('4200')
    assert imported['cpis_mode']=='imported'
    assert imported['population']['active'] is False
    assert set(imported['status_values'])=={'Em Produção',' FeChAdA '}
    assert 'of_closed' in codes(imported)
    assert all(not r['population']['active'] for r in imported['plan_rows'])
    first=cpis_sync.publish([direct_row('OF4200')],datetime.now(timezone.utc),central_dsn=canonical)
    opened=cpis.read_context('OF4200')
    assert opened['cpis_mode']=='direct' and opened['cpis_version']==first['version_id']
    assert opened['population']['active'] is True and 'of_closed' not in codes(opened)
    cpis_sync.publish([{**direct_row('OF4200'),'status':'Fechada'}],datetime.now(timezone.utc),central_dsn=canonical)
    assert cpis.read_context('4200')['population']['active'] is False
    assert planning_hub.order_detail('4200',version=first['version_id'])['context']['cpis_status']=='Em Aberto'
    cpis_sync.publish([direct_row('OF4200')],datetime.now(timezone.utc),central_dsn=canonical)
    assert cpis.read_context('4200')['population']['active'] is True


@pytest.mark.parametrize('status',['Pronta','Estado desconhecido',None,' em aberto '])
def test_non_operational_does_not_mean_closed(canonical,status):
    cpis_sync.publish([{**direct_row('OF4200'),'status':status}],datetime.now(timezone.utc),central_dsn=canonical)
    ctx=cpis.read_context('4200')
    assert ctx['population']['active'] is True
    assert 'of_closed' not in codes(ctx)
    assert 'of_not_operational' in codes(ctx)
    assert ('cpis_state_unknown' in codes(ctx)) is (status=='Estado desconhecido')
    with pytest.raises(planning.PlanningError):planning_hub.require_operational_orders(['OF4200'])


@pytest.mark.parametrize('mark,closed',[(' x ',True),('true',True),(1,True),(False,False),('#VALUE!',False)])
def test_pdf_assessment_uses_textual_closure_without_discarding_history(mark,closed):
    row=plan_row();row['row_data']['Fechado']=mark
    values=piece_values()
    issues,match=cpis.assess({'values':values,'raw':values,'reviewed':{},'machine_group':'Serrote'},context(rows=[row]),2)
    assert ('plan_row_closed' in {i['code'] for i in issues}) is closed
    assert match['population']['active'] is not closed
    assert match['source_plan_key']==row['source_line_id']
    if mark=='#VALUE!':assert any(i['code']=='closure_state_unknown' for i in issues)


def test_pdf_and_manual_output_respect_closure_of_associated_origin(canonical):
    n=needs.resolve(request(area='perfis',source={'kind':'plan_line','id':'s1:10'}))
    with planning.connect() as conn:
        source=needs.source_data({'kind':'plan_line','id':'s1:11'},'perfis',conn)
        conn.execute('INSERT INTO planning_mtg.need_sources(kind,source_id,need_id,version,payload) VALUES(%s,%s,%s,%s,%s)',
            ('plan_line','s1:11',n['need_id'],'s1',Jsonb({**source,'area':'perfis'})))
    with psycopg.connect(canonical) as conn:
        conn.execute("UPDATE raw_mtg.plan_production_rows SET row_data=row_data||%s WHERE source_line_id='s1:11'",(Jsonb({'Fechado':'X'}),))
    ctx=cpis.read_context('4200')
    assert len(ctx['plan_rows'])==2
    assert all(not r['population']['active'] for r in ctx['plan_rows'])
    assert {r['planning_key'] for r in ctx['plan_rows']}=={n['need_id']}
    # A record created before the source was associated may lack source_plan_key.
    record={'id':str(uuid.uuid4()),'need_id':n['need_id'],'production_order_no':'OF4200',
        'component_ref':'REF-A','source_plan_key':None,'values_json':{'operation':'corte','quantity_to_plan':5}}
    with pytest.raises(planning.PlanningError,match='histórico'):
        planning_output._macro_rows([record])


def test_public_manual_proposal_rejects_closed_macro_without_creating_output(canonical):
    published=cpis_sync.publish([direct_row('OF4200')],datetime.now(timezone.utc),central_dsn=canonical)
    data=payload();data.update(record_status='ready',cpis_version=published['version_id'])
    saved=planning.save_record(data)
    with psycopg.connect(canonical) as conn:
        conn.execute("UPDATE raw_mtg.plan_production_rows SET row_data=row_data||%s WHERE source_line_id='s1:10'",(Jsonb({'Fechado':' X '}),))
        before=conn.execute('SELECT count(*) FROM planning_mtg.output_proposals').fetchone()[0]
    with pytest.raises(planning.PlanningError,match='saída ativa'):
        planning_output.create_proposal({'request_id':str(uuid.uuid4()),'actor':'Teste','record_ids':[saved['id']]})
    with psycopg.connect(canonical) as conn:
        assert conn.execute('SELECT count(*) FROM planning_mtg.output_proposals').fetchone()[0]==before
    assert planning.get_record(saved['id'])['record']['id']==saved['id']


def test_download_rechecks_closure_after_an_approved_comparison(canonical,tmp_path):
    content=io.BytesIO()
    with ZipFile(io.BytesIO(workbook_source())) as source,ZipFile(content,'w') as output:
        for entry in source.infolist():
            data=source.read(entry.filename)
            if entry.filename=='xl/worksheets/sheet1.xml':data=data.replace(b'OF265931',b'OF4200')
            output.writestr(entry,data)
    original=content.getvalue();path=tmp_path/'planning.xlsm';path.write_bytes(original)
    with psycopg.connect(canonical) as conn:
        conn.execute("UPDATE audit_mtg.snapshots SET source_path=%s,source_sha256=%s WHERE snapshot_id='s1'",(str(path),hashlib.sha256(original).hexdigest()))
        conn.execute("DELETE FROM raw_mtg.plan_production_rows WHERE source_line_id='s1:11'")
        conn.execute("DELETE FROM analytics_mtg.kanban_plan_lines WHERE plan_key='s1:11'")
        conn.execute("UPDATE raw_mtg.plan_production_rows SET excel_row=7 WHERE source_line_id='s1:10'")
        conn.execute("UPDATE analytics_mtg.kanban_plan_lines SET excel_row=7 WHERE plan_key='s1:10'")
    published=cpis_sync.publish([direct_row('OF4200')],datetime.now(timezone.utc),central_dsn=canonical)
    data=payload();data.update(record_status='ready',cpis_version=published['version_id'])
    saved=planning.save_record(data)
    proposal=planning_output.create_proposal({'request_id':str(uuid.uuid4()),'actor':'Teste','record_ids':[saved['id']]})
    assert proposal['cells']
    with psycopg.connect(canonical) as conn:
        conn.execute("UPDATE raw_mtg.plan_production_rows SET closed_x=true WHERE source_line_id='s1:10'")
    with pytest.raises(planning.PlanningError,match='saída ativa'):
        planning_output.generate(proposal['id'],proposal['proposal_fingerprint'])
    with psycopg.connect(canonical) as conn:
        assert conn.execute('SELECT exported_at FROM planning_mtg.output_proposals WHERE id=%s',(proposal['id'],)).fetchone()[0] is None
    assert path.read_bytes()==original


def test_multiple_sales_orders_keep_all_copies_without_arbitrary_choice(canonical):
    rows=[direct_row('OF4200','OV1111'),{**direct_row('OF4200','OV2222'),'source_row_no':2}]
    cpis_sync.publish(rows,datetime.now(timezone.utc),central_dsn=canonical)
    ctx=cpis.read_context('4200')
    assert ctx['sales_order'] is None and set(ctx['sales_orders'])=={'OV1111','OV2222'}
    assert 'cpis_ambiguous' not in codes(ctx)


def test_pdf_reclassification_preserves_document_piece_and_original_bytes(canonical):
    # Actual SQL context and persisted PDF; the vision response alone is simulated.
    source=pdf_bytes()
    uid=store.ingest(source,'OF265931.pdf')['id']
    rows=[direct_row('OF265931','OV2607672'),{**direct_row('OF265931','OV9999'),'source_row_no':2}]
    cpis_sync.publish(rows,datetime.now(timezone.utc),central_dsn=canonical)
    pipeline.process_document(uid,provider=FakeVision())
    original=store.get_document(uid)
    ids=[p['id'] for p in original['pieces']]
    assert ids and not any(i['code']=='of_closed' for p in original['pieces'] for i in p['issues'])
    assert original['context']['sales_order'] is None
    assert not any(i['code']=='ov_disagreement' for p in original['pieces'] for i in p['issues'])
    for status,closed in [('Fechada',True),('Pronta',False),('Estado novo',False),('Em Aberto',False)]:
        cpis_sync.publish([{**r,'status':status} for r in rows],datetime.now(timezone.utc),central_dsn=canonical)
        pipeline.reconcile(uid)
        current=store.get_document(uid)
        assert current['sha256']==original['sha256']
        assert store.file_path(uid).read_bytes()==source
        assert [p['id'] for p in current['pieces']]==ids
        assert ('of_closed' in {i['code'] for p in current['pieces'] for i in p['issues']}) is closed
        assert current['context']['population']['active'] is not closed
        assert [p['raw'] for p in current['pieces']]==[p['raw'] for p in original['pieces']]
