"""Automatic OF Picking must survive manual registration, preview and RAW edits."""
import uuid
from pathlib import Path
import psycopg
from psycopg.types.json import Jsonb

from app import planning, planning_dates, planning_needs as needs
from app.raw import projection, preview, query, edits, contracts, capacity
from tests.test_raw_workspace import workspace, database, canonical, registry, postgres16
from tests.test_planning_needs import vals


def payload(**changes):
    return {'request_id':str(uuid.uuid4()),'area':'perfis','production_order_no':'OF4200',
            'catalog_version':'s1','record_status':'draft','values':{**vals(),'component_ref':'AUTO-PICKING'},**changes}


def preview_of(p):
    return preview.preview({k:v for k,v in p.items() if k not in ('request_id','record_status')})['row']['values']


def published(key):
    return query.listing({'area':'perfis','selected':[key]})['rows'][0]


def test_manual_registration_inherits_picking_without_storing_a_manual_override(workspace):
    projection.rebuild('perfis');projection.rebuild('cantoneiras');capacity.rebuild()
    p=payload()
    before=preview_of(p)
    assert before['picking_week']==39 and before['picking_date']=='2026-09-21'
    assert before['picking_year'] is None and before['picking_deadline_provisional']
    saved=edits.prepare(p);row=published(saved['need_id']);v=row['values']
    assert v['picking_week']==39 and v['picking_origin']=='Picking · folha'
    assert v['picking_date']==before['picking_date']
    record=needs.detail(saved['need_id'])['records'][0]
    assert record['values_json']['picking_week'] is None
    # Editing an unrelated field preserves automatic resolution and refreshes the date.
    with planning.connect(readonly=True) as c:version=query.generation(c,'perfis')['id']
    edited=edits.update_batch({'request_id':str(uuid.uuid4()),'area':'perfis','version':version,
        'edits':[{'key':row['key'],'expected_revision':row['revision'],'values':{'notes':'Apenas nota'}}]})
    assert published(saved['need_id'])['values']['picking_date']=='2026-09-21'
    with psycopg.connect(workspace) as c:
        c.execute("UPDATE raw_mtg.other_sheet_rows SET row_data=%s WHERE snapshot_id='s1' AND sheet_name='Picking'",
                  (Jsonb({'values':[1,'OF4200',40]}),))
    projection.rebuild('perfis',force=True)
    assert published(saved['need_id'])['values']['picking_date']=='2026-09-28'
    assert published(saved['need_id'])['values']['picking_year'] is None
    assert contracts.mapping('perfis')['picking_date']['data_type']=='date'
    assert not contracts.mapping('perfis')['picking_date']['editable']


def test_picking_conflict_manual_override_and_explicit_clear_agree_with_preview(workspace):
    with psycopg.connect(workspace) as c:
        c.execute("INSERT INTO raw_mtg.other_sheet_rows VALUES ('s1','Picking',99,%s)",
                  (Jsonb({'values':[2,4200,40]}),))
    projection.rebuild('perfis');projection.rebuild('cantoneiras');capacity.rebuild()
    p=payload();v=preview_of(p)
    assert v['picking_conflict'] and v['picking_date'] is None
    p['values']['picking_week']=41;p['decisions']={'picking_week':'write'}
    assert preview_of(p)['picking_date']=='2026-10-05'
    saved=edits.prepare(p)
    v=published(saved['need_id'])['values']
    assert v['picking_date']=='2026-10-05' and not v['picking_conflict']
    assert v['picking_origin']=='Decisão manual'
    update=payload(need_id=saved['need_id'],expected_revision=saved['revision'],
                   values={'operation':'corte','picking_week':None},decisions={'picking_week':'clear'})
    assert preview_of(update)['picking_date'] is None
    saved=edits.prepare(update)
    assert published(saved['need_id'])['values']['picking_date'] is None


def test_untouched_blank_record_does_not_clear_picking():
    record={'operation_id':'cut','values_json':{'picking_week':None},
            'provenance_json':{'cut:picking_week':{'human_decision':'write'}}}
    result=planning_dates.picking_values('OF4200',None,{'OF4200':39},{},record=record)
    assert result['picking_week']==39
    record['provenance_json']['cut:picking_week']['human_decision']='clear'
    assert planning_dates.picking_values('OF4200',None,{'OF4200':39},{},record=record)['picking_week'] is None


def test_picking_form_and_raw_browser(workspace,monkeypatch,tmp_path):
    import os,socket,subprocess,time,urllib.request
    projection.rebuild('perfis');projection.rebuild('cantoneiras');capacity.rebuild()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    root=Path(__file__).parents[1];evidence=root/'docs/picking-automatico-2026-09-25';evidence.mkdir(exist_ok=True)
    env={**os.environ,'MES_PG_DSN':workspace,'MES_DATA_DIR':str(tmp_path),
         'MES_DOSSIER_WORKER_DISABLED':'1','MES_PLANNING_NEEDS_ENABLED':'1',
         'MES_PLANNING_RAW_ENABLED':'1','MES_RAW_WORKSPACE_ENABLED':'1',
         'PLANNING_TEST_ISOLATED':'1','PLANNING_CHECK_BASE':f'http://127.0.0.1:{port}',
         'PICKING_EVIDENCE':str(evidence)}
    with (tmp_path/'server.log').open('w+') as log:
        proc=subprocess.Popen([str(root/'.venv/bin/python'),'-m','uvicorn','app.web.planning_app:app',
                              '--host','127.0.0.1','--port',str(port)],cwd=root,env=env,stdout=log,stderr=log)
        try:
            for _ in range(100):
                try:urllib.request.urlopen(env['PLANNING_CHECK_BASE']+'/planeamento/manual',timeout=.3);break
                except Exception:time.sleep(.1)
            else:raise AssertionError('Server not ready')
            run=subprocess.run(['node','tests/planning_picking_automatic_browser.cjs'],cwd=root,env=env,
                               capture_output=True,text=True,timeout=80)
            log.flush();log.seek(0)
            assert run.returncode==0,run.stdout+run.stderr+'\n'+log.read()
        finally:
            proc.terminate();proc.wait(timeout=10)
