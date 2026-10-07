import uuid
from pathlib import Path
import pytest
import psycopg
from app import planning, planning_raw as raw, planning_raw_analysis as analysis, planning_needs as needs
from tests.test_planning_needs import canonical, registry, postgres16, create, save, vals

@pytest.fixture()
def database(canonical,monkeypatch):
    with psycopg.connect(canonical) as c:c.execute((Path(__file__).parents[1]/'sql/023_planning_raw.sql').read_text())
    raw._cache.clear();monkeypatch.setenv('MES_PLANNING_RAW_ENABLED','1')
    return canonical


def test_layout_and_unknowns():
    assert len(raw.SPECS)==42
    v=raw.calculated({'quantity_required':10,'length_mm':1000,'stock_length_mm':6000,'remaining':None,'abocardar':'X'},{})
    assert all(v[k] is None for k in ('cut','boc','cut_pct','boc_pct','bars'))
    assert v['total_length']==10000
    v=raw.calculated({'quantity_required':320,'length_mm':1000,'stock_length_mm':6000,'remaining':0,'abocardar':'X'},{'Ser.':315,'Aboc.':298,'Área de Seção de Corte Unit. [mm2]':20})
    assert v['cut']==315 and v['boc']==298 and v['boc_remaining']==22 and v['bars']==0
    assert v['section_total']==6400 and v['final_pct']==298/320*100


def test_totals_coverage_and_reject_code():
    q=analysis.Query(group_by='machine',measure='remaining',aggregate='sum',filter_field=None,filter_value=None)
    result=analysis.aggregate([{'machine':'A','remaining':4},{'machine':'A','remaining':None}],q)
    assert result['groups'][0]==dict(group='A',value=4,known=1,unknown=1,rows=2)
    q.measure='SELECT * FROM production'
    with pytest.raises(planning.PlanningError):analysis.aggregate([],q)


def test_source_projection_and_atomic_edit(database):
    ds=raw.dataset(force=True);assert ds['rows']
    row=ds['rows'][0]
    p={'request_id':str(uuid.uuid4()),'version':ds['version'],'expected_revision':row['revision'],'values':{'notes':'Teste RAW','material_requested':False,'stock_length_mm':'6000,5'}}
    result=raw.update(row['key'],p)
    assert raw.update(row['key'],p)==result
    detail=needs.detail(result['need_id']);record=detail['records'][0]
    assert record['values_json']['material_requested'] is False
    assert record['values_json']['stock_length_mm']==6000.5
    machine=next(f for f in detail['fields'] if f['field']=='machine')
    assert machine['human_decision'] is None and machine['source']['kind']=='plan_line'
    after=raw.dataset(force=True)
    assert len(after['rows'])==len(ds['rows'])
    assert any(r['need_id']==result['need_id'] for r in after['rows'])
    with pytest.raises(planning.PlanningError):raw.update(row['key'],{**p,'request_id':str(uuid.uuid4()),'values':{'cut':999}})


def test_rollback_does_not_create_need(database,monkeypatch):
    ds=raw.dataset(force=True);row=ds['rows'][0]
    # Gravar já não recusa valores fora do catálogo (07/10/2026); uma falha a meio continua a desfazer a peça.
    def fail(*args,**kwargs):raise planning.PlanningError('Falha simulada ao gravar.')
    monkeypatch.setattr(needs,'save',fail)
    with pytest.raises(planning.PlanningError):raw.update(row['key'],{'request_id':str(uuid.uuid4()),'version':ds['version'],'expected_revision':0,'values':{'machine':'inexistente'}})
    with planning.connect(readonly=True) as c:assert c.execute('SELECT count(*) n FROM planning_mtg.needs').fetchone()['n']==0


def test_local_row_and_version_pagination(database):
    n=save(create());ds=raw.dataset(force=True)
    assert any(r['need_id']==n['need_id'] for r in ds['rows'])
    result=raw.listing({'version':ds['version'],'q':'NEW-A'})
    assert result['total']==1 and result['rows'][0]['values']['remaining'] is None
    with pytest.raises(planning.PlanningError):raw.dataset('expired')


def test_render_escapes_and_coverage():
    report={'status':'done','model':'test','result':{'visual':{'title':'<script>x</script>','kind':'bar','explanation':'dados','limitations':[]},'result':{'rows':2,'groups':[{'group':'<x>','value':5,'known':1,'unknown':1}]},'sources':{'snapshot':{'loaded_at':'UTC'},'cpis_mode':'importado'},'limitations':[]}}
    rendered=analysis.render(report)
    assert '<script>' not in rendered and '&lt;script&gt;' in rendered
    assert 'Por confirmar' in rendered


def test_raw_browser(database,tmp_path):
    import os,socket,subprocess,time,urllib.request
    root=Path(__file__).parents[1]
    (root/'docs/raw-2026-09-22').mkdir(exist_ok=True)
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    env={**os.environ,'MES_PG_DSN':os.environ['MES_PG_DSN'],'MES_DATA_DIR':str(tmp_path),'MES_DOSSIER_WORKER_DISABLED':'1','MES_PLANNING_NEEDS_ENABLED':'1','MES_PLANNING_RAW_ENABLED':'1'}
    with (tmp_path/'server.log').open('w+') as log:
        process=subprocess.Popen([str(root/'.venv/bin/python'),'-m','uvicorn','app.web.planning_app:app','--host','127.0.0.1','--port',str(port)],cwd=root,env=env,stdout=log,stderr=log)
        try:
            for _ in range(100):
                try:urllib.request.urlopen(f'http://127.0.0.1:{port}/planeamento/raw',timeout=.5);break
                except Exception:time.sleep(.1)
            run=subprocess.run(['node',str(root/'tests/raw_browser.cjs')],env={**env,'PLANNING_CHECK_BASE':f'http://127.0.0.1:{port}'},capture_output=True,text=True,timeout=120)
            log.flush();log.seek(0)
            assert run.returncode==0,run.stdout+run.stderr+'\n'+log.read()
        finally:process.terminate();process.wait(timeout=10)


def test_saved_analysis_frozen_and_idempotent(database,monkeypatch):
    monkeypatch.setattr(analysis._pool,'submit',lambda *args:None)
    ds=raw.dataset(force=True)
    p={'request_id':str(uuid.uuid4()),'version':ds['version'],'question':'Soma os saldos por máquina','filters':{}}
    report=analysis.create(p);assert analysis.create(p)['id']==report['id']
    with pytest.raises(planning.PlanningError):analysis.create({**p,'question':'Outro pedido'})
    class Provider:
        config={'model':'fixture'}
        def request(self,prompt,schema,**kw):
            assert 'transcrever' not in kw['system']
            if schema is analysis.Query:return {'group_by':'machine','measure':'remaining','aggregate':'sum','filter_field':None,'filter_value':None}
            return {'title':'Saldo conhecido','kind':'bar','explanation':'Valores calculados pelo servidor.','limitations':['Há valores desconhecidos.']}
    analysis.execute(report['id'],Provider());done=analysis.get(report['id'])
    assert done['status']=='done'
    frozen=done['result']
    p={'request_id':str(uuid.uuid4()),'id':report['id'],'title':'Análise guardada'}
    assert analysis.save(p)==analysis.save(p)
    with psycopg.connect(database) as c:c.execute("UPDATE raw_mtg.plan_production_rows SET quantity_planned=999")
    assert analysis.get(report['id'])['result']==frozen


def test_invalid_local_options_stay_out_of_calculations_without_blocking(database):
    # 07/10/2026: o registo grava sempre; um valor inválido fica fora do cálculo em vez de recusar.
    from app import planning_catalogs as c
    from app.raw import registration as free
    cat=c.catalog('perfis')
    for changes,field in (({'material_requested':'Sim'},'material_requested'),({'stock_length_mm':0},'stock_length_mm'),
                          ({'stock_length_mm':'nan'},'stock_length_mm'),({'picking_week':54},'picking_week')):
        assert free.normalize({**vals(),**changes},cat)[0][field] is None
    value=free.normalize({**vals(),'picking_week':53,'picking_year':2026,'material_requested':None},cat)[0]
    assert value['picking_week']==53 and value['material_requested'] is None


def test_geometric_area_and_incompatible_bars():
    import math
    v=raw.calculated({'material_type':'Varão redondo','outer_diameter_mm':20,'quantity_required':48,'length_mm':13000,'stock_length_mm':12000,'remaining':48},{})
    assert v['section_unit']==pytest.approx(math.pi*100)
    assert v['section_total']==pytest.approx(15079.644737231007)
    assert v['bars'] is None
    v=raw.calculated({'quantity_required':10,'abocardar':'X'},{'Ser.':-1,'Aboc.':1.2})
    assert v['cut'] is None and v['boc'] is None


def test_false_zero_and_unknown_are_different_groups():
    query=analysis.Query(group_by='material_requested',measure='id',aggregate='count',filter_field=None,filter_value=None)
    result=analysis.aggregate([{'material_requested':True},{'material_requested':False},{'material_requested':None}],query)
    assert {g['group'] for g in result['groups']}=={'Sim','Não','Por confirmar'}
    query.filter_field='material_requested';query.filter_value='false'
    assert analysis.aggregate([{'material_requested':True},{'material_requested':False}],query)['rows']==1
