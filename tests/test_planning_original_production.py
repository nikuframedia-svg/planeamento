"""Original-source pipeline against disposable SQLite and PostgreSQL only."""
import json,sqlite3,uuid
from pathlib import Path
import psycopg
import pytest
from app import planning,original_ocr,planning_hub
from app.raw import projection,query
from tests.test_raw_workspace import workspace,database,canonical,registry,postgres16
from tests.test_original_ocr import local
from tests.test_planning_ocr_incremental import source


@pytest.fixture()
def original_source(workspace,local):
    with psycopg.connect(workspace) as c:
        c.execute((Path(__file__).parents[1]/'sql/021_original_ocr_import.sql').read_text())
        c.execute('TRUNCATE ocr_original.instances CASCADE')
        c.execute('TRUNCATE mes_kanban.validated_sheets CASCADE')
    return workspace,local,str(uuid.uuid4())


def publish(f):
    dsn,path,instance=f
    return original_ocr.publish(original_ocr.read_snapshot(path,instance),dsn)


def configure(f,area):
    dsn,path,instance=f
    with psycopg.connect(dsn) as c:
        if area=='cantoneiras':c.execute("UPDATE raw_mtg.plan_production_rows SET row_data=row_data||'{\"1ª Oper.\":\"112\"}'::jsonb WHERE snapshot_id='c1'")
    with planning.connect(readonly=True) as c:
        snap=planning.snapshot(c,area)
        row=c.execute('SELECT * FROM raw_mtg.plan_production_rows WHERE snapshot_id=%s ORDER BY excel_row LIMIT 1',(snap['snapshot_id'],)).fetchone()
    code='corte' if area=='perfis' else str(row['row_data']['1ª Oper.'])
    with sqlite3.connect(path) as c:
        c.execute('ALTER TABLE production_rows ADD COLUMN profile_type TEXT')
        c.execute('ALTER TABLE production_rows ADD COLUMN operation TEXT')
        c.execute('ALTER TABLE production_rows ADD COLUMN modelo TEXT')
        c.execute('ALTER TABLE production_rows ADD COLUMN comp_mm REAL')
        c.execute('UPDATE production_rows SET qtd=7,of=?,modelo=?,comp_mm=?,profile_type=?,operation=? WHERE sheet_id=1',
          (row['production_order_no'],row['component_ref'],float(row['length_mm']),row['profile_type'],code))
        payload={'template_name':'fixture','header':{'area':area,'setor_maquina':'Unknown fixture machine'}}
        c.execute('UPDATE sheets SET sheet_data=? WHERE id=1',(json.dumps(payload),))
    return row,code


def piece(area,key):return query.listing({'area':area,'population':'all','selected':[key]})['rows'][0]


@pytest.mark.parametrize('area',['perfis','cantoneiras'])
def test_original_revision_replay_and_removal_feed_shared_balances(original_source,area):
    raw,op=configure(original_source,area);publish(original_source)
    gen=projection.rebuild(area);key='macro:'+raw['source_line_id'];row=piece(area,key)
    selected=next(s for s in row['calculation']['production_sources'] if s['operation']==op)
    assert selected['origin']=='OCR validado' and selected['value']==7
    assert row['values']['remaining']==max(row['values']['quantity_required']-7,0)
    assert selected['records'][0]['source']=='ocr_original'
    assert selected['records'][0]['instance_id']==original_source[2]
    assert publish(original_source)['unchanged']
    assert projection.rebuild(area)['id']==gen['id']
    with sqlite3.connect(original_source[1]) as c:
        c.execute('UPDATE sheets SET revision=2 WHERE id=1');c.execute('UPDATE production_rows SET qtd=9 WHERE sheet_id=1')
    publish(original_source);revised=projection.rebuild(area)
    assert revised['metadata']['calculation_scope']=='ocr_orders'
    assert piece(area,key)['values']['cut' if area=='perfis' else 'made']==9
    old=query.listing({'area':area,'version':str(gen['id']),'population':'all','selected':[key]})['rows'][0]
    assert old['values']['cut' if area=='perfis' else 'made']==7
    with sqlite3.connect(original_source[1]) as c:
        c.execute('UPDATE sheets SET revision=3 WHERE id=1');c.execute('DELETE FROM production_rows WHERE sheet_id=1')
    publish(original_source);projection.rebuild(area)
    current=piece(area,key)
    assert next(s for s in current['calculation']['production_sources'] if s['operation']==op)['origin']!='OCR validado'


def test_original_and_mes_are_not_summed_and_incomplete_original_stays_visible(original_source):
    raw,op=configure(original_source,'perfis')
    with psycopg.connect(original_source[0]) as c:
        source(c,of=raw['production_order_no'],key=raw['source_line_id'],profile=raw['profile_type'],length=raw['length_mm'])
    publish(original_source);projection.rebuild('perfis');key='macro:'+raw['source_line_id']
    selected=piece('perfis',key)['calculation']['production_sources'][0]
    assert selected['origin']=='Excel provisório'
    assert any('Sobreposição' in s for s in selected['coverage_reasons'])
    details=planning_hub.order_detail(raw['production_order_no'])
    operation=next(o for line in details['plan_lines'] if line['plan_key']==raw['source_line_id'] for o in line['operations'] if o['operation']=='corte')
    assert operation['ocr_quantity'] is None
    with planning.connect(readonly=True) as c:
        gen=query.generation(c,'perfis',dataset='production');base,args=query.source(gen)
        events=c.execute('SELECT c.values_json,c.detail'+base,args).fetchall()
    linked=[e for e in events if key in e['detail']['planning_keys']]
    assert len(linked)==2 and all(e['values_json']['association_status']=='source_overlap' for e in linked)
    with sqlite3.connect(original_source[1]) as c:
        c.execute('UPDATE sheets SET revision=2 WHERE id=1');c.execute('UPDATE production_rows SET profile_type=NULL WHERE sheet_id=1')
    publish(original_source);projection.rebuild('perfis')
    selected=piece('perfis',key)['calculation']['production_sources'][0]
    assert selected['origin']=='Excel provisório' and selected['coverage_reasons']
    detail=planning_hub.order_detail(raw['production_order_no'])
    original=[r for r in detail['production'] if r.get('source')=='ocr_original']
    assert original and all(r['association_status'] in ('incomplete','ambiguous','unmatched') and not r['resolved_plan_keys'] for r in original)


def test_original_status_tracks_applied_snapshot_and_row_diagnostics(original_source):
    raw,op=configure(original_source,'perfis');publish(original_source)
    assert original_ocr.status()['included_in_planning_balances'] is False
    for area in planning.AREAS:projection.rebuild(area)
    status=original_ocr.status();assert status['included_in_planning_balances'] is True
    result=original_ocr.query(of=raw['production_order_no'])
    assert result['total']==1
    applied=next(r for r in result['records'][0]['planning'] if r['area']=='perfis')
    assert applied['operation']=='corte' and applied['planning_keys']==['macro:'+raw['source_line_id']]
    with sqlite3.connect(original_source[1]) as c:
        c.execute('UPDATE sheets SET revision=2 WHERE id=1');c.execute('UPDATE production_rows SET qtd=8 WHERE sheet_id=1')
    publish(original_source)
    assert original_ocr.status()['included_in_planning_balances'] is False
    assert all(r['state']=='pending_publication' for r in original_ocr.query()['records'][0]['planning'])
    for area in planning.AREAS:projection.rebuild(area)
    assert original_ocr.status()['included_in_planning_balances'] is True


def test_real_original_schema_without_geometry_never_invents_an_association(original_source):
    publish(original_source)
    projection.rebuild('perfis');projection.rebuild('cantoneiras')
    data=original_ocr.query()
    assert data['records'][0]['data']['qtd']==4
    for item in data['records'][0]['planning']:
        assert not item.get('planning_keys')
        assert item['state'] in ('incomplete','ambiguous','unmatched')
        assert item['reason']


def test_original_browser_shows_applied_revision_and_individual_reasons(original_source,tmp_path):
    import os,socket,subprocess,time,urllib.request
    raw,_=configure(original_source,'perfis')
    with sqlite3.connect(original_source[1]) as c:
        c.execute("INSERT INTO production_rows(id,sheet_id,row_index,qtd,of,sheet_iso_date,modelo) VALUES (44,1,1,NULL,'9999','2026-09-17','SEM-IDENTIDADE')")
    publish(original_source)
    for area in planning.AREAS:projection.rebuild(area)
    projection.rebuild_original()
    original=query.listing({'area':'perfis','dataset':'original','population':'all'})
    assert original['total']==2
    assert any(r['values']['association_status']=='Identidade técnica única' for r in original['rows'])
    root=Path(__file__).parents[1]
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    env={**os.environ,'MES_DATA_DIR':str(tmp_path),'MES_DOSSIER_WORKER_DISABLED':'1','MES_PLANNING_NEEDS_ENABLED':'1','MES_PLANNING_RAW_ENABLED':'1','MES_RAW_WORKSPACE_ENABLED':'1','PLANNING_TEST_ISOLATED':'1','PLANNING_CHECK_BASE':f'http://127.0.0.1:{port}'}
    with (tmp_path/'server.log').open('w+') as log:
        process=subprocess.Popen([str(root/'.venv/bin/python'),'-m','uvicorn','app.web.planning_app:app','--host','127.0.0.1','--port',str(port)],cwd=root,env=env,stdout=log,stderr=log)
        try:
            for _ in range(100):
                try:urllib.request.urlopen(env['PLANNING_CHECK_BASE']+'/planeamento',timeout=.5);break
                except Exception:time.sleep(.1)
            run=subprocess.run(['node',str(root/'tests/planning_original_source_browser.cjs')],env=env,capture_output=True,text=True,timeout=60)
            log.flush();log.seek(0)
            assert run.returncode==0,run.stdout+run.stderr+'\n'+log.read()
        finally:process.terminate();process.wait(timeout=10)


def test_original_production_survives_linking_the_macro_to_a_local_need(original_source):
    from app.raw import edits
    from app import planning_associations as assoc
    raw,op=configure(original_source,'perfis');publish(original_source)
    projection.rebuild('perfis')
    saved=edits.prepare({'request_id':str(uuid.uuid4()),'area':'perfis','catalog_version':'s1',
        'source':{'kind':'plan_line','id':raw['source_line_id'],'version':'s1'},
        'values':{'operation':'corte','notes':'Original source association fixture'}})
    evidence=assoc.get_evidence(saved['need_id'],saved['operation_id'])['evidence']
    assert evidence['ocr_quantity']==7
    assert evidence['ocr_records'][0]['source']=='ocr_original'
    assert piece('perfis',saved['need_id'])['values']['cut']==7
    with psycopg.connect(original_source[0]) as c:
        source(c,of=raw['production_order_no'],key=raw['source_line_id'],profile=raw['profile_type'],length=raw['length_mm'])
    projection.rebuild('perfis')
    evidence=assoc.get_evidence(saved['need_id'],saved['operation_id'])['evidence']
    assert evidence['ocr_quantity'] is None and any('Sobreposição' in w for w in evidence['warnings'])
    assert piece('perfis',saved['need_id'])['calculation']['production_sources'][0]['origin']=='Excel provisório'
