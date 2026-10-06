import uuid
from pathlib import Path
import pytest
import psycopg
from tests.test_planning_raw import database,canonical,registry,postgres16
from app import planning,planning_needs as needs
from app.raw import projection,query,expressions,contracts

@pytest.fixture()
def workspace(database,monkeypatch,tmp_path):
    monkeypatch.setenv("MES_RAW_WORKBOOK_ROOT",str(tmp_path))
    with psycopg.connect(database) as c:
        c.execute((Path(__file__).parents[1]/'sql/024_raw_workspace.sql').read_text())
        c.execute('TRUNCATE planning_mtg.raw_objects CASCADE')
        c.execute((Path(__file__).parents[1]/'sql/026_capacity_revision.sql').read_text())
        c.execute((Path(__file__).parents[1]/'sql/028_planning_worked_hours.sql').read_text())
        c.execute((Path(__file__).parents[1]/'sql/029_planning_content_compression.sql').read_text())
        c.execute((Path(__file__).parents[1]/'sql/030_planning_member_epochs.sql').read_text())
        c.execute((Path(__file__).parents[1]/'sql/031_planning_member_dependencies.sql').read_text())
        c.execute((Path(__file__).parents[1]/'sql/032_planning_estimate_storage.sql').read_text())
        c.execute((Path(__file__).parents[1]/'sql/036_planning_order_members.sql').read_text())
        c.execute((Path(__file__).parents[1]/'sql/038_planning_balance_evidence.sql').read_text())
        c.execute('TRUNCATE planning_mtg.raw_workbook_evidence,planning_mtg.raw_drive_observations')
        c.execute('TRUNCATE planning_mtg.raw_objects,planning_mtg.raw_generations,planning_mtg.raw_members,planning_mtg.raw_contents,planning_mtg.raw_signals CASCADE')
    return database


def test_generation_query_and_typed_filter(workspace):
    gen=projection.rebuild('perfis')
    result=query.listing({'area':'perfis','page_size':25})
    assert result['total']>0 and len(result['rows'])<=25
    assert query.listing({'version':result['version']})['total']==result['total']
    assert projection.rebuild('perfis')['id']==gen['id']
    known=query.listing({'filters':[{'field':'length_mm','op':'gt','value':'1,0'}]})
    assert all(r['values']['length_mm']>1 for r in known['rows'])
    assert query.options({'field':'of'})['total']>0
    with pytest.raises(planning.PlanningError):query.listing({'filters':[{'field':'cut;DROP TABLE x','op':'known'}]})
    with pytest.raises(planning.PlanningError):query.listing({'version':'999999'})


def test_structured_quantity_drives_raw_and_manual_source_without_rewriting_macro(workspace):
    from psycopg.types.json import Jsonb
    from app.dossiers.cpis import _plan_values
    with psycopg.connect(workspace,row_factory=psycopg.rows.dict_row) as c:
        source=c.execute('SELECT * FROM raw_mtg.plan_production_rows ORDER BY excel_row LIMIT 1').fetchone()
        raw={**source['row_data'],'QTD':62,'QTD [un,]':130,'Ser.':62,'Aborc.':'-'}
        c.execute('UPDATE raw_mtg.plan_production_rows SET quantity_planned=62,row_data=%s WHERE snapshot_id=%s AND source_line_id=%s',
                  (Jsonb(raw),source['snapshot_id'],source['source_line_id']))
    projection.rebuild('perfis')
    row=query.listing({'area':'perfis','population':'all','selected':['macro:'+source['source_line_id']]})['rows'][0]
    assert row['values']['quantity_required']==130
    assert row['values']['remaining']==68
    assert row['values']['cut_pct']==pytest.approx(6200/130)
    assert row['raw']['QTD']==62 and row['raw']['QTD [un,]']==130
    with planning.connect(readonly=True) as c:
        manual=needs.source_data({'kind':'plan_line','id':source['source_line_id']},'perfis',c)
        original=c.execute('SELECT * FROM raw_mtg.plan_production_rows WHERE snapshot_id=%s AND source_line_id=%s',
                           (source['snapshot_id'],source['source_line_id'])).fetchone()
    assert manual['values']['quantity_required']==_plan_values(original)['quantity_required']==130
    assert original['quantity_planned']==62 and original['row_data']==raw


def test_expression_types_and_unknowns():
    fields=contracts.mapping()
    ast=expressions.parse('[Quantidade por cortar] * 2',fields) if 'Quantidade por cortar' in [f['label'] for f in fields.values()] else expressions.parse('[Por cortar] * 2',fields)
    expr=expressions.compile_ast(ast,fields)
    assert expr.unit=='un.' and expr.args==[2]
    with pytest.raises(planning.PlanningError):expressions.compile_ast(expressions.parse('[Por cortar] + [Comprimento (mm)]',fields),fields)
    with pytest.raises(planning.PlanningError):expressions.parse('__import__("os")',fields)
    div=expressions.compile_ast(expressions.parse('[Por cortar] / 0',fields),fields)
    assert 'NULLIF' in div.sql

def test_atomic_batch_revision_and_analysis(workspace):
    from app.raw import edits,analysis,objects,capacity
    projection.rebuild('perfis');r=query.listing({});row=r['rows'][0]
    p={'request_id':str(uuid.uuid4()),'area':'perfis','version':r['version'],'edits':[{'key':row['key'],'expected_revision':row['revision'],'values':{'notes':'RAW v2'}}]}
    saved=edits.update_batch(p);assert edits.update_batch(p)==saved
    projection.rebuild('perfis');updated=query.listing({})
    assert any(x['values'].get('notes')=='RAW v2' for x in updated['rows'])
    definition={'area':'perfis','dataset':'planning','group_by':['[machine]'],'metrics':[{'name':'Saldo','expression':'sum([remaining])'}],'visual':'bar'}
    preview=analysis.preview({'definition':definition})
    assert preview['preview']['rows']==r['total']
    conf=analysis.confirm({'request_id':str(uuid.uuid4()),'definition':preview['definition'],'evidence_hash':preview['evidence_hash']})
    with planning.connect(readonly=True) as c:job=c.execute('SELECT * FROM planning_mtg.raw_jobs WHERE id=%s',(conf['job_id'],)).fetchone()
    analysis.run_job(job)
    assert analysis.get_job(job['id'])['status']=='done'
    assert analysis.evidence(job['id'])['total']==r['total']
    formula=objects.save({'request_id':str(uuid.uuid4()),'name':'Metros de saldo','area':'perfis','confirmed':True,'definition':{'expression':'[remaining] * [length_mm] / 1000','unit':'m'}},'formula')
    assert 'calc_'+formula['id'].replace('-','') in query.listing({})['rows'][0]['values']
    resource=objects.save({'request_id':str(uuid.uuid4()),'area':'perfis','name':'MEBA físico','definition':{'aliases':[{'area':'perfis','name':'MEBA'}],'operations':['corte'],'confirmed':True}},'resource')
    objects.save({'request_id':str(uuid.uuid4()),'area':'perfis','name':'Semana','definition':{'resource_id':resource['id'],'year':2026,'week':53,'shifts':10,'hours_per_shift':8,'exception_hours':0,'confirmed':True}},'calendar')
    projection.rebuild('cantoneiras')
    capacity.rebuild();matrix=query.listing({'dataset':'capacity'})
    assert any(x['values']['available_hours']==80 for x in matrix['rows'])


def test_atomic_manual_failure_does_not_create(workspace,monkeypatch):
    from app.raw.edits import prepare
    from tests.test_planning_needs import vals
    payload={'request_id':str(uuid.uuid4()),'area':'perfis','production_order_no':'OF4200','catalog_version':'s1','values':{**vals(),'machine':'Invalid machine'},'record_status':'draft'}
    # Uma máquina fora do catálogo já não impede de gravar (07/10/2026); uma falha a meio desfaz tudo.
    def fail(*args,**kwargs):raise planning.PlanningError('Falha simulada ao gravar.')
    with monkeypatch.context() as patched:
        patched.setattr(needs,'save',fail)
        with pytest.raises(planning.PlanningError):prepare(payload)
    with planning.connect(readonly=True) as c:assert c.execute('SELECT count(*) n FROM planning_mtg.needs').fetchone()['n']==0
    saved=prepare({**payload,'request_id':str(uuid.uuid4())})
    assert needs.detail(saved['need_id'])['records'][0]['values_json']['machine']=='Invalid machine'

def test_workspace_browser(workspace,tmp_path):
    import os,socket,subprocess,time,urllib.request
    projection.rebuild('perfis')
    root=Path(__file__).parents[1];(root/'docs/raw-completa').mkdir(exist_ok=True)
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    env={**os.environ,'MES_PG_DSN':os.environ['MES_PG_DSN'],'MES_DATA_DIR':str(tmp_path),'MES_DOSSIER_WORKER_DISABLED':'1','MES_PLANNING_NEEDS_ENABLED':'1','MES_PLANNING_RAW_ENABLED':'1','MES_RAW_WORKSPACE_ENABLED':'1'}
    with (tmp_path/'web.log').open('w+') as log:
        proc=subprocess.Popen([str(root/'.venv/bin/python'),'-m','uvicorn','app.web.planning_app:app','--host','127.0.0.1','--port',str(port)],env=env,stdout=log,stderr=log)
        try:
            for _ in range(80):
                try:urllib.request.urlopen(f'http://127.0.0.1:{port}/planeamento/raw');break
                except Exception:time.sleep(.2)
            run=subprocess.run(['node','tests/raw_workspace_browser.cjs'],env={**env,'PLANNING_CHECK_BASE':f'http://127.0.0.1:{port}'},capture_output=True,text=True,timeout=120)
            log.flush();log.seek(0);assert run.returncode==0,run.stdout+run.stderr+'\n'+log.read()
        finally:proc.terminate();proc.wait(timeout=10)

@pytest.mark.parametrize('area',['perfis','cantoneiras'])
@pytest.mark.parametrize('pdf_first',[False,True])
def test_atomic_pdf_manual_both_directions(workspace,monkeypatch,area,pdf_first):
    import copy
    from psycopg.types.json import Jsonb
    from app.raw.edits import prepare
    from app.dossiers import store
    from tests.test_planning_needs import vals
    v=vals();version='s1'
    if area=='cantoneiras':
        version='c1';v={**v,'component_ref':'CANT-NEW','material_type':'Cantoneira','profile':'L80x80x6','machine':'Ficep','operation':'112','outer_diameter_mm':None,'width_mm':80,'height_mm':80,'thickness_mm':6}
        with psycopg.connect(workspace) as c:
            c.execute("INSERT INTO raw_mtg.other_sheet_rows VALUES('c1','Dados',3,%s)",(Jsonb({'values':[None,'Ficep',None,None,'Cantoneira',None,None,112,'Corte',None,'Equipa']}),))
    document={'id':'raw-doc','revision':1,'production_order':'OF4200','status':'ready','pieces':[{'id':'piece','revision':1,'state':'ready','values':v}]}
    monkeypatch.setattr(store,'get_document',lambda ident:copy.deepcopy(document))
    def payload(pdf):return {'request_id':str(uuid.uuid4()),'area':area,'production_order_no':'OF4200','source':{'kind':'pdf','id':'raw-doc/piece'} if pdf else None,'values':v,'catalog_version':version,'record_status':'draft'}
    first=prepare(payload(pdf_first));second=prepare(payload(not pdf_first))
    assert first['need_id']==second['need_id']
    projection.rebuild(area)
    result=query.listing({'area':area,'q':v['component_ref']})
    assert result['total']==1 and result['rows'][0]['values']['quantity_required']==100
    with planning.connect(readonly=True) as c:assert c.execute('SELECT count(*) n FROM planning_mtg.order_registration').fetchone()['n']==1


def test_new_macro_generation_preserves_identity(workspace):
    from app.raw.edits import prepare
    from app import planning_catalogs as cat
    with planning.connect(readonly=True) as c:source=needs.source_data({'kind':'plan_line','id':'s1:10'},'perfis',c)
    p={'request_id':str(uuid.uuid4()),'area':'perfis','production_order_no':'OF4200','catalog_version':'s1','values':{**source['values'],'operation':'corte'},'record_status':'draft'}
    saved=prepare(p)
    with psycopg.connect(workspace) as c:
        c.execute("INSERT INTO audit_mtg.snapshots SELECT 's2',dataset_id,source_filename,source_path,source_sha256,now()+interval '1 second' FROM audit_mtg.snapshots WHERE snapshot_id='s1'")
        for table in ('raw_mtg.plan_production_rows','analytics_mtg.kanban_plan_lines','core_mtg.production_orders','raw_mtg.cpis_rows','raw_mtg.other_sheet_rows','raw_mtg.machine_rows'):
            # All fixture tables keep snapshot_id as the first column.
            columns=[r[0] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position",tuple(table.split('.'))).fetchall()]
            selected=["'s2'" if k=='snapshot_id' else "replace("+k+",'s1:','s2:')" if k in ('source_line_id','plan_key') else k for k in columns]
            c.execute('INSERT INTO '+table+' SELECT '+','.join(selected)+" FROM "+table+" WHERE snapshot_id='s1'")
    projection.rebuild('perfis');r=query.listing({'selected':[saved['need_id']]})
    assert r['total']==1 and r['rows'][0]['plan_key']=='s2:10'
    assert query.listing({'q':'REF-A'})['total']==2  # two different profiles, not a duplicate of the local piece


def test_live_definition_updates_without_llm_and_keeps_history(workspace):
    from app.raw import analysis,objects,worker,exports
    projection.rebuild('perfis');definition={'area':'perfis','dataset':'planning','group_by':[],'metrics':[{'name':'Saldo','expression':'sum([remaining])'}],'visual':'line','title':'Saldo'}
    preview=analysis.preview({'definition':definition});confirmed=analysis.confirm({'request_id':str(uuid.uuid4()),'definition':preview['definition'],'evidence_hash':preview['evidence_hash']})
    jobs=worker.tick('test',2);assert len(jobs)==1;analysis.run_job(jobs[0]);old=analysis.get_job(jobs[0]['id'])
    with planning.connect() as c:
        gen=query.generation(c);base,args=query.source(gen);data=c.execute('SELECT detail,values_json'+base,args).fetchall();rows=[{**r['detail'],'values':r['values_json']} for r in data];rows[0]['values']['remaining']=1
        projection.publish(c,'planning:perfis','changed-source',rows,{'source_fingerprint':'changed-source'})
    next_jobs=worker.tick('test',2);assert len(next_jobs)==1;analysis.run_job(next_jobs[0]);new=analysis.get_job(next_jobs[0]['id'])
    assert new['result']['definition']==old['result']['definition']
    assert new['result']['groups']!=old['result']['groups']
    assert analysis.get_job(old['id'])['result']==old['result']
    assert 'RawCharts.render' in exports.report(old['id'],'html')[0]
    import json
    report=json.loads(exports.report(old['id'],'json')[0])
    assert report['result']==old['result']
    assert 'remaining' in report['support_fields']
    assert all('raw' not in r['detail'] and 'original' not in r['detail'] for r in report['support'])
    assert sum(r['values_json']['remaining'] for r in report['support'] if r['values_json'].get('remaining') is not None)==old['result']['groups'][0]['m0']
    assert analysis.evidence(old['id'])['total']==old['result']['rows']


def test_capacity_methods_unknown_zero_and_overload(workspace):
    from app.raw import capacity,objects
    values={'quantity_to_plan':10,'section_unit':20,'length_mm':1000}
    assert capacity.estimate(values,{'method':'area_hour','value':100,'setup_minutes':0},'corte')[0]==2
    assert capacity.estimate(values,{'method':'metres_hour','value':5,'setup_minutes':0},'112')[0]==2
    assert capacity.estimate({**values,'quantity_to_plan':None},{'method':'area_hour','value':100},'corte')[0] is None
    assert capacity.estimate({**values,'quantity_to_plan':0},{'method':'area_hour','value':100},'corte')[0]==0
    resource=objects.save({'request_id':str(uuid.uuid4()),'name':'Partilhada','area':'perfis','definition':{'aliases':[{'area':'perfis','name':'MEBA'},{'area':'cantoneiras','name':'Ficep'}],'operations':['corte','112'],'confirmed':True}},'resource')
    with pytest.raises(planning.PlanningError):objects.save({'request_id':str(uuid.uuid4()),'name':'Duplicada','area':'perfis','definition':{'aliases':[{'area':'perfis','name':'MEBA'}],'operations':['corte'],'confirmed':True}},'resource')
    with pytest.raises(planning.PlanningError):objects.save({'request_id':str(uuid.uuid4()),'name':'Semana inválida','area':'perfis','definition':{'resource_id':resource['id'],'year':2025,'week':53,'shifts':0,'hours_per_shift':8,'confirmed':True}},'calendar')


def test_formula_cycles_units_and_frozen_exports(workspace):
    from app.raw import objects,exports
    projection.rebuild('perfis')
    first=objects.save({'request_id':str(uuid.uuid4()),'name':'A','area':'perfis','confirmed':True,'definition':{'expression':'[remaining] * 2'}},'formula');key='calc_'+first['id'].replace('-','')
    second=objects.save({'request_id':str(uuid.uuid4()),'name':'B','area':'perfis','confirmed':True,'definition':{'expression':'['+key+'] * 2'}},'formula')
    with pytest.raises(planning.PlanningError):objects.save({'request_id':str(uuid.uuid4()),'id':first['id'],'expected_revision':first['revision'],'name':'A','area':'perfis','confirmed':True,'definition':{'expression':'[calc_'+second['id'].replace('-','')+']'}},'formula')
    with pytest.raises(planning.PlanningError):objects.save({'request_id':str(uuid.uuid4()),'name':'Peso falso','area':'perfis','confirmed':True,'definition':{'expression':'[length_mm]','unit':'kg'}},'formula')
    condition=objects.save({'request_id':str(uuid.uuid4()),'name':'Saldo pendente','area':'perfis','confirmed':True,'definition':{'expression':'[remaining] > 0','style':'warning'}},'format')
    result=query.listing({});assert result['rows'][0]['formats'][0]['id']==condition['id']
    csv,mime=exports.table({'area':'perfis','columns':['of','cut_date','remaining']},'csv');assert 'OF4200' in csv


def test_formula_preview_sql_nulls_and_portuguese_export(workspace):
    from app.raw import objects,exports
    projection.rebuild('perfis')
    p=objects.preview_formula({'area':'perfis','expression':'round([remaining] / 3, 2)'})
    assert p['coverage']['total']>0
    whole=objects.preview_formula({'area':'perfis','expression':'round([remaining])'})
    assert whole['coverage']['total']==p['coverage']['total']
    unknown=objects.preview_formula({'area':'perfis','expression':'[remaining] / 0'})
    assert unknown['coverage']['known']==0
    condition=objects.preview_formula({'area':'perfis','expression':'if([remaining] > 0, [remaining], 0)'})
    assert condition['data_type']=='number'
    data,_=exports.table({'columns':['length_mm']},'csv')
    assert '.' not in data.splitlines()[1]


def test_stable_selection_and_selected_production_scope(workspace):
    from app.raw import analysis
    projection.rebuild('perfis')
    before=query.listing({})['rows'][0];key=before['key']
    with planning.connect() as c:
        rows=[dict(before,key='macro:replacement',selection_aliases=[key])]
        projection.publish(c,'planning:perfis','new-alias',rows,{'source_fingerprint':'new-alias'})
        projection.publish(c,'production:perfis','new-events',[{'key':'event-a','planning_keys':['macro:replacement'],'values':{'quantity':3,'machine':'MEBA'}},{'key':'event-b','planning_keys':['other'],'values':{'quantity':100,'machine':'MEBA'}}],{})
    assert query.listing({'selected':[key]})['total']==1
    result=analysis.preview({'definition':{'area':'perfis','dataset':'production','planning_selection':[key],'group_by':[],'metrics':[{'name':'Quantidade','expression':'sum([quantity])'}]}})
    assert result['preview']['groups'][0]['m0']==3
    assert result['preview']['rows']==1


def test_view_legacy_and_worker_lease_recovery(workspace):
    from app.raw import objects,analysis,worker
    d=objects.normalize_view({'hidden':['technical'],'filters':{'state':'open','machine':'MEBA','q':'OF4200','sort':'remaining','direction':'desc'}},'perfis')
    assert d['order']==[{'field':'remaining','direction':'desc'}]
    assert all(contracts.mapping()[k]['group']!='technical' for k in d['columns'])
    assert len(d['filters'])==2
    projection.rebuild('perfis');p=analysis.preview({'definition':{'area':'perfis','dataset':'planning','group_by':[],'metrics':[{'name':'N','expression':'count([of])'}]}})
    saved=analysis.confirm({'request_id':str(uuid.uuid4()),'definition':p['definition'],'evidence_hash':p['evidence_hash']})
    worker.tick('interrupted',2)
    with planning.connect() as c:c.execute("UPDATE planning_mtg.raw_jobs SET heartbeat_at=now()-interval '10 minutes' WHERE id=%s",(saved['job_id'],))
    recovered=worker.tick('new-worker',2)
    assert len(recovered)==1 and str(recovered[0]['id'])==saved['job_id']


def test_atomic_paste_does_not_leave_first_edit(workspace):
    from app.raw import edits
    projection.rebuild('perfis');data=query.listing({});first,second=data['rows'][:2]
    with pytest.raises(planning.PlanningError):edits.update_batch({'request_id':str(uuid.uuid4()),'area':'perfis','version':data['version'],'edits':[{'key':first['key'],'expected_revision':0,'values':{'notes':'Must roll back'}},{'key':second['key'],'expected_revision':0,'values':{'machine':'Invalid machine'}}]})
    with planning.connect(readonly=True) as c:
        assert c.execute('SELECT count(*) n FROM planning_mtg.needs').fetchone()['n']==0
        assert c.execute('SELECT count(*) n FROM planning_mtg.order_registration').fetchone()['n']==0


def test_shared_capacity_aggregates_each_operation_once(workspace):
    from app.raw import capacity,objects
    resource=objects.save({'request_id':str(uuid.uuid4()),'name':'Recurso de ensaio','area':'perfis','definition':{'aliases':[{'area':'perfis','name':'MEBA'},{'area':'cantoneiras','name':'Ficep'}],'operations':['corte','112'],'confirmed':True}},'resource')
    objects.save({'request_id':str(uuid.uuid4()),'name':'3 horas','area':'perfis','definition':{'resource_id':resource['id'],'year':2026,'week':39,'shifts':1,'hours_per_shift':3,'exception_hours':0,'confirmed':True}},'calendar')
    fixtures=[]
    for area,operation,method,value,machine in [('perfis','corte','area_hour',100,'MEBA'),('cantoneiras','112','metres_hour',5,'Ficep')]:
        objects.save({'request_id':str(uuid.uuid4()),'name':'Taxa '+area,'area':area,'definition':{'resource_id':resource['id'],'area':area,'operation':operation,'method':method,'value':value,'valid_from':'2026-01-01','confirmed':True}},'rate')
        row={'key':area,'values':{'of':'OF4200','component_ref':area,'machine':machine,'operation':operation,'status':'Em Aberto','expected_date':'2026-09-22','quantity_to_plan':10,'section_unit':20,'length_mm':1000},'preparations':[{'values_json':{'operation':operation,'quantity_to_plan':10},'operation_id':operation,'record_status':'ready'}]}
        fixtures.append((area,row))
    with planning.connect() as c:
        for area,row in fixtures:
            projection.publish(c,'planning:'+area,'capacity-fixture:'+area,[row],
                               {'core_source_fingerprint':projection.fingerprint(c,area)})
    capacity.rebuild();rows=query.listing({'dataset':'capacity'})['rows']
    rows=[r for r in rows if r['values']['week']==39]
    assert len(rows)==1
    assert rows[0]['values']['planned_hours']==4
    assert rows[0]['values']['free_hours']==-1
    assert rows[0]['values']['lines_total']==2
    assert rows[0]['values']['actual_hours'] is None


def test_order_summary_unknowns_and_worker_source_state(workspace):
    from app.raw import worker
    rows=[{'key':'one','values':{'of':'OF4200','remaining':1,'quantity_required':2}},{'key':'two','values':{'of':'OF4200','remaining':None,'quantity_required':2}}]
    with planning.connect() as c:projection.publish_orders(c,'perfis',rows,{},'partial')
    r=query.listing({'dataset':'orders'})['rows'][0]['values']
    assert r['remaining'] is None and r['known_remaining_total']==1
    assert r['remaining_known_lines']==1 and r['lines_total']==2
    worker.source_status('perfis',begin=True);worker.source_status('perfis',available=True)
    with planning.connect(readonly=True) as c:before=c.execute("SELECT * FROM planning_mtg.raw_worker_state WHERE source='perfis'").fetchone()
    worker.source_status('perfis',available=False,error='TimeoutError')
    with planning.connect(readonly=True) as c:after=c.execute("SELECT * FROM planning_mtg.raw_worker_state WHERE source='perfis'").fetchone()
    assert after['confirmed_at']==before['confirmed_at'] and not after['available']


def test_historical_reference_punctuation_does_not_authorize_association():
    from app import planning_hub as hub
    record={'id':1,'source_app':'kanban-mes-mtg2','model_ref':'REFA','profile_type':'UPN50x25','length_mm':1000,'quantity':1}
    plans=[{'source_app':'kanban-mes-mtg2','plan_key':'current','component_ref':'REF-A','profile_type':'UPN50x25','length_mm':1000}]
    hub._production_associations([record],plans)
    assert record['association_status']=='unmatched'


def test_cantoneiras_manual_pdf_browser(workspace,tmp_path,monkeypatch):
    import os,sqlite3,json,socket,subprocess,time,urllib.request,dataclasses
    from psycopg.types.json import Jsonb
    from app.dossiers import store
    with psycopg.connect(workspace) as c:c.execute("INSERT INTO raw_mtg.other_sheet_rows VALUES('c1','Dados',3,%s)",(Jsonb({'values':[None,'Ficep',None,None,'Cantoneira',None,None,112,'Corte',None,'Equipa']}),))
    archive=tmp_path/'dossiers';archive.mkdir()
    values={'component_ref':'CANT-BROWSER','material_type':'Cantoneira','profile':'L80x80x6','length_mm':1000,'quantity_required':100,'operation':'112','machine':'Ficep'}
    with sqlite3.connect(archive/'dossiers.db') as c:
        c.executescript(store.SCHEMA)
        c.execute("INSERT INTO documents(id,sha256,filename,page_count,status,production_order,created_at,updated_at) VALUES('cant-doc','cant-hash','Cantoneiras de ensaio.pdf',1,'ready','OF4200','2026-09-22','2026-09-22')")
        c.execute("INSERT INTO pieces(id,document_id,source_key,machine_group,index_page,index_ref,drawing_pages_json,raw_json,values_json,state) VALUES('cant-piece','cant-doc','one','Por definir',1,'CANT-BROWSER','[1]',?,?,'ready')",(json.dumps(values),json.dumps(values)))
    monkeypatch.setattr(store,'settings',dataclasses.replace(store.settings,data_dir=tmp_path))
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    env={**os.environ,'MES_DATA_DIR':str(tmp_path),'MES_DOSSIER_WORKER_DISABLED':'1','MES_PLANNING_NEEDS_ENABLED':'1','MES_PLANNING_RAW_ENABLED':'1','MES_RAW_WORKSPACE_ENABLED':'1'}
    root=Path(__file__).parents[1]
    with (tmp_path/'web.log').open('w+') as log:
        proc=subprocess.Popen([str(root/'.venv/bin/python'),'-m','uvicorn','app.web.planning_app:app','--host','127.0.0.1','--port',str(port)],env=env,stdout=log,stderr=log)
        try:
            for _ in range(80):
                try:urllib.request.urlopen(f'http://127.0.0.1:{port}/planeamento');break
                except Exception:time.sleep(.2)
            result=subprocess.run(['node','tests/raw_cantoneiras_browser.cjs'],env={**env,'PLANNING_CHECK_BASE':f'http://127.0.0.1:{port}'},capture_output=True,text=True,timeout=100)
            assert result.returncode==0,result.stdout+result.stderr
            projection.rebuild('cantoneiras')
            assert query.listing({'area':'cantoneiras','q':'CANT-BROWSER'})['total']==1
        finally:proc.terminate();proc.wait(timeout=10)


def test_browser_json_numeric_literals_keep_preview_token(workspace):
    from app.raw import analysis
    projection.rebuild('perfis')
    d={'area':'perfis','dataset':'planning','group_by':[],'metrics':[{'name':'Cobertura','expression':'round(count([remaining]) / count([of]) * 100, 2)'}]}
    p=analysis.preview({'definition':d})
    browser=analysis.canonical_definition(p['definition'])
    assert analysis.confirm({'request_id':str(uuid.uuid4()),'definition':browser,'evidence_hash':p['evidence_hash']})['job_id']
