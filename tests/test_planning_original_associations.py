"""Human original-OCR decisions, local publication and immutable source facts."""
import copy,json,sqlite3,uuid
from pathlib import Path
import psycopg
import pytest
from psycopg.types.json import Jsonb
from app import planning,planning_needs as needs,planning_associations as assoc,planning_catalogs as catalogs
from app.raw import projection,query
from tests.test_planning_original_production import original_source,publish
from tests.test_original_ocr import local
from tests.test_raw_workspace import workspace,database,canonical,registry,postgres16
from tests.test_planning_needs import vals,request


@pytest.fixture()
def decision_source(original_source):
    with psycopg.connect(original_source[0]) as c:
        c.execute((Path(__file__).parents[1]/'sql/033_original_ocr_associations.sql').read_text())
        for i,row in enumerate([[None,'Ficep',None,None,'Cantoneira',None,None,112,'CORTE'],
                              [None,None,None,None,None,None,None,119,'FURAÇÃO']],20):
            c.execute("INSERT INTO raw_mtg.other_sheet_rows VALUES ('c1','Dados',%s,%s)",(i,Jsonb({'values':row})))
    publish(original_source)
    return original_source


def make_need(area='perfis',of='4200'):
    values=vals() if area=='perfis' else {**vals(),'material_type':'Cantoneira','profile':'L80x80x6','machine':'Ficep','operation':'112','outer_diameter_mm':None,'width_mm':80,'height_mm':80,'thickness_mm':6}
    n=needs.resolve(request(area=area,production_order_no=of,values=values))
    return needs.save(request(area=area,need_id=n['need_id'],expected_revision=n['revision'],catalog_version='s1' if area=='perfis' else 'c1',values=values)),values


def proposal(area,n,quantity=4,of='4200'):
    pending=assoc.pending(of,area,source='original',state='all')['records'][0]
    return request(production_record_id=pending['id'],expected_revision=(pending['decision'] or {}).get('revision',0),evidence_hash=pending['evidence_hash'],reason='Correspondência física conferida no ensaio descartável',
        allocations=[{'need_id':n['need_id'],'operation_id':n['operation_id'],'expected_need_revision':n['revision'],'quantity':quantity}])


def row(area,n):return query.listing({'area':area,'population':'all','selected':[n['need_id']]})['rows'][0]


@pytest.mark.parametrize('area',['perfis','cantoneiras'])
def test_original_human_association_publishes_and_only_identity_invalidates(decision_source,area):
    n,values=make_need(area)
    for a in planning.AREAS:projection.rebuild(a)
    p=proposal(area,n);before=publish(decision_source)
    saved=assoc.save(p);assert assoc.save(p)==saved
    assert saved['publication']['status']=='published'
    field='cut' if area=='perfis' else 'made'
    assert row(area,n)['values'][field]==4
    assert row(area,n)['values']['remaining']==96
    import csv,io
    from openpyxl import load_workbook
    from app.raw import exports
    selection={'area':area,'selected':[n['need_id']],'columns':['quantity_required',field,'remaining']}
    csv_data,_=exports.table(selection,'csv')
    assert [float(v.replace(',','.')) for v in list(csv.reader(io.StringIO(csv_data),delimiter=';'))[1]]==[100,4,96]
    xlsx_data,_=exports.table(selection,'xlsx')
    assert list(load_workbook(io.BytesIO(xlsx_data),data_only=True)['RAW'].values)[1]==(100,4,96)
    assert publish(decision_source)['snapshot_id']==before['snapshot_id']
    details=needs.detail(n['need_id']);technical=details['need']['technical_revision']
    values={**values,'quantity_required':120}
    n=needs.save(request(area=area,need_id=n['need_id'],expected_revision=n['revision'],catalog_version='s1' if area=='perfis' else 'c1',values=values))
    assert needs.detail(n['need_id'])['need']['technical_revision']==technical
    projection.rebuild(area)
    assert row(area,n)['values'][field]==4 and row(area,n)['values']['remaining']==116
    values={**values,'length_mm':1100}
    n=needs.save(request(area=area,need_id=n['need_id'],expected_revision=n['revision'],catalog_version='s1' if area=='perfis' else 'c1',values=values))
    projection.rebuild(area)
    assert row(area,n)['values'][field] is None
    assert assoc.pending('4200',area,source='original')['records'][0]['requires_review']
    assert assoc.save(proposal(area,n))['revision']==2
    assert row(area,n)['values'][field]==4


def test_original_revised_fact_rejects_old_proof_and_retains_history(decision_source):
    n,_=make_need();projection.rebuild('perfis');p=proposal('perfis',n);assoc.save(p)
    stale=proposal('perfis',n)
    with sqlite3.connect(decision_source[1]) as c:
        c.execute('UPDATE sheets SET revision=2 WHERE id=1');c.execute('UPDATE production_rows SET qtd=7 WHERE sheet_id=1')
    publish(decision_source);gen=projection.rebuild('perfis')
    assert gen['metadata']['calculation_scope']=='ocr_orders'
    assert row('perfis',n)['values']['cut'] is None
    with pytest.raises(planning.PlanningError,match='evidência mudou'):assoc.save(stale)
    assert assoc.save(proposal('perfis',n,7))['revision']==2
    assert row('perfis',n)['values']['cut']==7
    with sqlite3.connect(decision_source[1]) as c:
        c.execute('UPDATE sheets SET revision=3 WHERE id=1');c.execute('DELETE FROM production_rows WHERE sheet_id=1')
    publish(decision_source);projection.rebuild('perfis')
    assert row('perfis',n)['values']['cut'] is None
    with planning.connect(readonly=True) as c:
        assert assoc.latest(c,p['production_record_id'])['revision']==2
        history=c.execute('SELECT revision FROM planning_mtg.original_association_decisions WHERE production_record_id=%s ORDER BY revision',(p['production_record_id'],)).fetchall()
        assert [r['revision'] for r in history]==[1,2]


def test_original_quantity_and_area_constraints_are_atomic(decision_source):
    n,_=make_need();p=proposal('perfis',n,5)
    with pytest.raises(planning.PlanningError,match='ultrapassa'):assoc.save(p)
    with sqlite3.connect(decision_source[1]) as c:
        c.execute('UPDATE sheets SET revision=2 WHERE id=1');c.execute('UPDATE production_rows SET qtd=NULL WHERE sheet_id=1')
    publish(decision_source)
    with pytest.raises(planning.PlanningError,match='desconhecida'):assoc.save(proposal('perfis',n,1))
    saved=assoc.save(proposal('perfis',n,None));assert saved['revision']==1
    evidence=assoc.get_evidence(n['need_id'],n['operation_id'])['evidence'];assert evidence['ocr_quantity'] is None
    assert evidence['ocr_records'][0]['quantity'] is None


def test_original_area_correction_reopens_event_and_moves_hours_without_losing_history(decision_source):
    from app.raw import worked_hours
    with sqlite3.connect(decision_source[1]) as c:
        c.execute('ALTER TABLE production_rows ADD COLUMN sheet_hours REAL')
        c.execute('UPDATE production_rows SET sheet_hours=2 WHERE sheet_id=1')
        c.execute('UPDATE sheets SET sheet_data=? WHERE id=1',(json.dumps({'header':{'area':'perfis','setor_maquina':'MEBA'}}),))
    publish(decision_source)
    perf,_=make_need('perfis')
    cant_values={**vals(),'component_ref':'CANT-A','material_type':'Cantoneira','profile':'L80x80x6','machine':'Ficep','operation':'112','outer_diameter_mm':None,'width_mm':80,'height_mm':80,'thickness_mm':6}
    cant=needs.resolve(request(area='cantoneiras',production_order_no='4200',values=cant_values))
    cant=needs.save(request(area='cantoneiras',need_id=cant['need_id'],expected_revision=cant['revision'],catalog_version='c1',values=cant_values))
    for area in planning.AREAS:projection.rebuild(area)
    p=proposal('perfis',perf);assoc.save(p)
    assert assoc.pending('4200','cantoneiras',source='original',state='all')['records']==[]
    with sqlite3.connect(decision_source[1]) as c:
        c.execute('UPDATE sheets SET revision=2,sheet_data=? WHERE id=1',(json.dumps({'header':{'area':'cantoneiras','setor_maquina':'Ficep'}}),))
    publish(decision_source)
    for area in planning.AREAS:projection.rebuild(area)
    pending=assoc.pending('4200','cantoneiras',source='original')['records']
    assert len(pending)==1 and pending[0]['requires_review'] and pending[0]['id']==p['production_record_id']
    assert row('perfis',perf)['values']['cut'] is None
    with planning.connect(readonly=True) as c:
        hours=[r for r in worked_hours.observations(c) if r['origin']=='OCR original' and r['hours']==2]
        assert len(hours)==1 and hours[0]['area']=='cantoneiras'
    assoc.save(proposal('cantoneiras',cant))
    assert row('cantoneiras',cant)['values']['made']==4
    with planning.connect(readonly=True) as c:
        versions=c.execute('SELECT revision,allocations FROM planning_mtg.original_association_decisions WHERE production_record_id=%s ORDER BY revision',(p['production_record_id'],)).fetchall()
        assert [v['revision'] for v in versions]==[1,2]
        assert [v['allocations'][0]['area'] for v in versions]==['perfis','cantoneiras']


def test_invalidated_unknown_area_decision_does_not_hide_other_area(decision_source):
    from app import planning_original_production as original
    perf,values=make_need('perfis')
    for area in planning.AREAS:projection.rebuild(area)
    assoc.save(proposal('perfis',perf))
    with planning.connect(readonly=True) as c:assert original.records(c,'cantoneiras')==[]
    needs.save(request(area='perfis',need_id=perf['need_id'],expected_revision=perf['revision'],catalog_version='s1',values={**values,'length_mm':1100}))
    with planning.connect(readonly=True) as c:
        assert len(original.records(c,'perfis'))==len(original.records(c,'cantoneiras'))==1
    assert assoc.pending('4200','cantoneiras',source='original')['records'][0]['requires_review']


def test_partial_original_distribution_stays_pending_until_fully_allocated(decision_source):
    n,_=make_need();projection.rebuild('perfis')
    assoc.save(proposal('perfis',n,2))
    pending=assoc.pending('4200','perfis',source='original')['records']
    assert pending[0]['unallocated']==[{'child_key':None,'quantity':2}]
    proof=assoc.get_evidence(n['need_id'],n['operation_id'])['evidence']
    assert proof['ocr_quantity'] is None and any('distribuição parcial' in w for w in proof['warnings'])
    assert row('perfis',n)['values']['cut'] is None
    assoc.save(proposal('perfis',n,4))
    assert assoc.pending('4200','perfis',source='original')['records']==[]
    assert row('perfis',n)['values']['cut']==4


@pytest.mark.parametrize('area',['perfis','cantoneiras'])
def test_original_manual_decision_clears_only_its_macro_diagnostic(decision_source,area):
    from tests.test_planning_original_production import configure
    from app.raw import edits
    raw,op=configure(decision_source,area)
    with sqlite3.connect(decision_source[1]) as c:
        c.execute('UPDATE production_rows SET profile_type=NULL,operation=NULL WHERE sheet_id=1')
    publish(decision_source);projection.rebuild(area)
    saved=edits.prepare(request(area=area,catalog_version=raw['snapshot_id'],
        source={'kind':'plan_line','id':raw['source_line_id'],'version':raw['snapshot_id']},values={'operation':op}))
    n={**saved,'revision':needs.detail(saved['need_id'])['need']['revision']}
    before=assoc.get_evidence(n['need_id'],n['operation_id'])['evidence']
    assert before['ocr_quantity'] is None
    assoc.save(proposal(area,n,7,raw['production_order_no']))
    after=assoc.get_evidence(n['need_id'],n['operation_id'])['evidence']
    assert after['ocr_quantity']==7 and not after['warnings']
    assert row(area,n)['values']['cut' if area=='perfis' else 'made']==7
    with sqlite3.connect(decision_source[1]) as c:
        c.execute("INSERT INTO production_rows(id,sheet_id,row_index,qtd,of,sheet_iso_date,modelo,comp_mm) SELECT 55,sheet_id,1,2,of,sheet_iso_date,modelo,comp_mm FROM production_rows WHERE id=12")
        c.execute('UPDATE sheets SET revision=2 WHERE id=1')
    publish(decision_source);projection.rebuild(area)
    proof=assoc.get_evidence(n['need_id'],n['operation_id'])['evidence']
    assert proof['ocr_quantity'] is None and any('por confirmar' in w for w in proof['warnings'])


def test_original_unrelated_sheet_change_preserves_decision_and_stale_write_conflicts(decision_source):
    n,_=make_need();projection.rebuild('perfis')
    initial=proposal('perfis',n);assoc.save(initial)
    with sqlite3.connect(decision_source[1]) as c:
        c.execute('ALTER TABLE production_rows ADD COLUMN sheet_hours REAL')
        c.execute('UPDATE production_rows SET sheet_hours=2 WHERE sheet_id=1')
        c.execute('UPDATE sheets SET revision=2 WHERE id=1')
    publish(decision_source);projection.rebuild('perfis')
    assert row('perfis',n)['values']['cut']==4
    assert assoc.pending('4200','perfis',source='original')['records']==[]
    stale={**initial,'request_id':str(uuid.uuid4())}
    with pytest.raises(planning.PlanningError) as error:assoc.save(stale)
    assert error.value.status==409
    assert row('perfis',n)['values']['cut']==4


def test_original_decision_waits_for_capacity_publication_without_losing_history(decision_source,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor,TimeoutError
    from threading import Event
    from app.raw import capacity_revision,incremental
    n,_=make_need()
    for area in planning.AREAS:projection.rebuild(area)
    payload=proposal('perfis',n)
    calculated=Event();release=Event();saving=Event()
    calculate=capacity_revision.calculate;baseline=incremental.baseline
    def paused_calculation(*args,**kwargs):
        result=calculate(*args,**kwargs)
        calculated.set()
        assert release.wait(15),'Timed out releasing capacity publication'
        return result
    def observed_baseline(conn):
        saving.set()
        return baseline(conn)
    monkeypatch.setattr(capacity_revision,'calculate',paused_calculation)
    monkeypatch.setattr(incremental,'baseline',observed_baseline)
    with ThreadPoolExecutor(max_workers=2) as pool:
        worker=pool.submit(capacity_revision.rebuild)
        try:
            if not calculated.wait(5):worker.result(timeout=1)
            assert calculated.is_set()
            human=pool.submit(assoc.save,payload)
            assert saving.wait(5)
            with pytest.raises(TimeoutError):human.result(timeout=.2)
        finally:release.set()
        worker.result(timeout=15)
        result=human.result(timeout=15)
    assert result['revision']==1 and result['publication']['status']=='published'
    assert assoc.save(payload)==result
    assert row('perfis',n)['values']['cut']==4
    with planning.connect(readonly=True) as c:
        history=c.execute('SELECT revision FROM planning_mtg.original_association_decisions WHERE production_record_id=%s ORDER BY revision',(payload['production_record_id'],)).fetchall()
        assert [r['revision'] for r in history]==[1]


@pytest.mark.parametrize('area',['perfis','cantoneiras'])
def test_original_association_browser(decision_source,tmp_path,area):
    import os,socket,subprocess,time,urllib.request
    n,_=make_need(area)
    for a in planning.AREAS:projection.rebuild(a)
    root=Path(__file__).parents[1]
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    env={**os.environ,'MES_DATA_DIR':str(tmp_path),'MES_DOSSIER_WORKER_DISABLED':'1',
        'MES_PLANNING_NEEDS_ENABLED':'1','MES_PLANNING_RAW_ENABLED':'1','MES_RAW_WORKSPACE_ENABLED':'1',
        'PLANNING_TEST_ISOLATED':'1','PLANNING_CHECK_BASE':f'http://127.0.0.1:{port}',
        'PLANNING_CHECK_AREA':area,'PLANNING_CHECK_NEED':n['need_id']}
    with (tmp_path/'server.log').open('w+') as log:
        process=subprocess.Popen([str(root/'.venv/bin/python'),'-m','uvicorn','app.web.planning_app:app',
            '--host','127.0.0.1','--port',str(port)],cwd=root,env=env,stdout=log,stderr=log)
        try:
            for _ in range(100):
                try:urllib.request.urlopen(env['PLANNING_CHECK_BASE']+'/planeamento',timeout=.5);break
                except Exception:time.sleep(.1)
            run=subprocess.run(['node',str(root/'tests/planning_original_association_browser.cjs')],env=env,capture_output=True,text=True,timeout=60)
            log.flush();log.seek(0)
            assert run.returncode==0,run.stdout+run.stderr+'\n'+log.read()
        finally:process.terminate();process.wait(timeout=10)
