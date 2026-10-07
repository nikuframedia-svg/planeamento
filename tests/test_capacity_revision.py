"""Behavioural checks for the revised workbook/capacity contract; disposable PostgreSQL only."""
import uuid
from pathlib import Path
import pytest
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from tests.test_raw_workspace import workspace,database,canonical,registry,postgres16
from datetime import date
from app import planning,planning_needs as needs,planning_dates
from app.raw import capacity,capacity_revision as calc,capacity_views as views,projection,query,objects,contracts,workbooks


def command(**kw):return {'request_id':str(uuid.uuid4()),**kw}


def test_estimates_negative_zero_varied_rates_and_thomas_boundary():
    values={'quantity_to_plan':10,'length_mm':1000,'section_unit':20}
    assert capacity.estimate({**values,'quantity_to_plan':-5},{'method':'metres_hour','value':5},'119')[0] is None
    assert capacity.estimate({**values,'quantity_to_plan':0},{'method':'metres_hour','value':5},'119')[0]==0
    a=calc.reference_estimate({'length_mm':1000,'speed_m_h':5},'cantoneiras',10,None)[0]
    b=calc.reference_estimate({'length_mm':1000,'speed_m_h':10},'cantoneiras',10,None)[0]
    assert a+b==3 and a+b!=20/7.5
    for quantity,factor in [(50,1),(51,3)]:
        v={**values,'machine':'Serrote Fita Thomas IS639 Pav.1','quantity_required':quantity}
        hours,_,used=calc.reference_estimate(v,'perfis',10,{'value':100})
        assert used==factor and hours==pytest.approx(2/factor)
        assert capacity.estimate(v,{'method':'area_hour','value':100},'corte')[0]==2


def test_period_mtg3_uses_cut_date_and_deduces_the_week_year_without_it():
    # Decisão do Luís (01/10/2026, plano das vistas por família): prazo MTG3 = Data Corte. Antes (22/09) a
    # capacidade MTG3 usava só a semana W importada, com o ano confirmado à mão por versão da macro; a
    # carga ficava sem ano e a ocupação das máquinas MTG3 aparecia a 0 % (auditoria 06/10, C1-1/A9-2).
    # Desde 07/10/2026 o ano da semana W é deduzido (o mais perto de hoje); as confirmações por versão não contam.
    periods=[{'area':'cantoneiras','definition':{'snapshot':'s','week':39,'year':2025}}]
    today=date(2026,10,7)
    assert calc.period({'imported_week':39,'cut_date':'2025-03-14'},'cantoneiras','s',periods,today=today)==(2025,11,'Data Corte')
    assert calc.period({'imported_week':41,'cut_date':'2026-10-07','operation':'119'},'cantoneiras','new-version',[],today=today)==(2026,41,'Data Corte')
    # Operações seguintes não herdam o prazo do corte; sem Data Corte vale a semana W com o ano deduzido.
    assert calc.period({'imported_week':39,'cut_date':'2026-10-07'},'cantoneiras','s',periods,primary=False,today=today)[:2]==(2026,39)
    assert calc.period({'imported_week':39},'cantoneiras','s',periods,today=today)==(2026,39,'Semana W importada — ano deduzido')
    assert calc.period({'imported_week':39},'cantoneiras','new-version',periods,today=today)[:2]==(2026,39)
    # Uma semana escolhida localmente continua a mandar sobre a Data Corte.
    assert calc.period({'cut_date':'2026-10-07','planned_year':2026,'planned_week':44},'cantoneiras','s',[])[:2]==(2026,44)
    assert calc.period({'cut_date':'2026-09-22','operation':'corte'},'perfis','s',[])[:2]==(2026,39)
    assert calc.period({'cut_date':'2026-09-22','operation':'abocardar'},'perfis','s',[])[:2]==(None,None)
    assert calc.period({'expected_date':'2027-01-01'},'perfis','s',[])[:2]==(2026,53)
    assert calc.period({'expected_date':'2026-09-22','planned_week':40,'planned_year':2026},'perfis','s',[])[:2]==(None,None)


def test_mtg3_table_week_and_capacity_occupancy_follow_cut_date():
    from app import planning_dates
    assert planning_dates.period({'cut_date':'2026-10-07','imported_week':41},area='cantoneiras',operation='119',cantoneiras_week=41)==(2026,41,'Data Corte')
    assert planning_dates.period({'cut_date':None,'imported_week':41},area='cantoneiras',operation='0',cantoneiras_week=41)==(None,41,'Semana W importada — ano por confirmar')
    # Com ano e semana, o balde da máquina recebe a carga e a ocupação deixa de ser 0 %.
    confirmed={'local':True,'confirmed':True,'hours':60,'shifts':8,'hours_per_shift':7.5}
    y,w,_=calc.period({'cut_date':'2026-10-07','imported_week':41},'cantoneiras','s',[])
    out=calc.summary([item(h=30)],[confirmed],None,y,w,[])
    assert out['values']['occupancy']==50 and 'Ano por confirmar' not in out['warnings']


def test_workbook_evidence_keeps_excel_dates_readable(tmp_path):
    from datetime import datetime
    from openpyxl import Workbook
    book=Workbook();sheet=book.active;sheet.title='Plan_semanal'
    sheet['G6']=datetime(2026,7,28);sheet['G6'].number_format='dd/mm/yyyy'
    sheet['H6']=46231;sheet['I6']=1.5;sheet['I6'].number_format='0.00'
    path=tmp_path/'Met3.xlsx';book.save(path)
    cells=workbooks.extract(path,'cantoneiras')['Plan_semanal'][0]['cells']
    # O valor guardado fica igual ao do Excel (número de série); a data legível segue ao lado.
    assert cells['G']['value']==46231 and cells['G']['date']=='2026-07-28'
    assert 'date' not in cells['H'] and 'date' not in cells['I']


def item(q=2,h=1,primary=True):
    return {'values':{'draft':False,'primary_operation':primary,'quantity':q,'planned_hours':h,'reference_hours':h,'pending_quantity':q,'pending_metres':q,'pending_area':q*10,'weight':q,'area_load':q*10,'metres':q}}


def test_duplicate_calendar_coverage_and_fractional_shifts():
    imp=[{'hours':80,'shifts':10,'hours_per_shift':8},{'hours':32,'shifts':2,'hours_per_shift':16}]
    out=calc.summary([item(h=.5)],imp,None,2026,39,[])
    assert out['calendar_conflict'] and out['values']['available_hours'] is None and out['values']['reference_available_hours'] is None
    confirmed={'local':True,'confirmed':True,'hours':1,'shifts':1,'hours_per_shift':8}
    out=calc.summary([item(h=.5),item(h=2,primary=False)],imp+[confirmed],None,2026,39,[])
    assert out['values']['free_hours']==-1.5 and out['values']['occupancy']==250
    assert out['values']['equivalent_shifts']==2.5/8
    assert out['values']['weight']==2  # one physical piece; additional operation cannot double its weight
    out=calc.summary([item(h=None)],imp,None,2026,39,[])
    assert out['values']['planned_hours'] is None
    assert out['coverage']['planned_hours']['known']==0


def test_cantoneiras_layout_description_and_operation_zero(workspace):
    with psycopg.connect(workspace,row_factory=dict_row) as c:
        c.execute("UPDATE raw_mtg.plan_production_rows SET material_type='Cantoneira',row_data=row_data||%s WHERE snapshot_id='c1'",(Jsonb({'Des. Material':'L45X45X4 S355J0 EN10025','1ª Oper.':119,'2ª Oper.':0,'W':39,'Mt\\h':100}),))
    projection.rebuild('cantoneiras')
    r=query.listing({'area':'cantoneiras'})['rows'][0]
    cols=contracts.columns('cantoneiras')
    assert cols['default_columns']==contracts.CANT_DEFAULT
    assert not {'remaining','macro_closed'}.intersection(cols['default_columns'])
    assert r['values']['material_description']=='L45X45X4 S355J0 EN10025'
    assert r['values']['imported_week']==39 and r['values']['operation_detail']=='0'
    for a in planning.AREAS:projection.rebuild(a)
    capacity.rebuild()
    assert query.listing({'dataset':'capacity_items','area':'cantoneiras'})['total']==1
    with psycopg.connect(workspace,row_factory=dict_row) as c:
        # O ano da semana W já não se confirma (07/10/2026): é deduzido, sem registo por versão.
        with pytest.raises(planning.PlanningError,match='deduzido'):
            objects.save(command(area='cantoneiras',name='W39 de 2026',definition={'snapshot':'c1','week':39,'year':2026,'reason':'Confirmado para o ensaio.'}),'period',c)
    year=planning_dates.infer_iso_year(39)
    row=views.overview({'area':'cantoneiras','year':year,'week':39})['rows'][0]
    assert row['values']['year']==year


def setup_week(workspace):
    with psycopg.connect(workspace,row_factory=dict_row) as c:
        c.execute("UPDATE raw_mtg.plan_production_rows SET row_data=row_data||%s WHERE snapshot_id='s1'",(Jsonb({'Data prevista':'2026-09-22','Quantidade Prevista':36,'Área de Seção de Corte Unit. [mm2]':20}),))
    for a in planning.AREAS:projection.rebuild(a)
    capacity.rebuild()
    version=views.overview({'area':'perfis','year':2026,'week':39})['version']
    return {'area':'perfis','year':2026,'week':39,'version':version}


def test_week_reference_atomic_replay_compatible_production_and_revision(workspace):
    p=setup_week(workspace);preview=views.reference_preview(p)
    assert preview['count']==2 and preview['known']==2
    payload=command(**p,name='Plano conferido',token=preview['token'],confirmed=True)
    ref=views.save_reference(payload);assert views.save_reference(payload)==ref
    with pytest.raises(planning.PlanningError):views.save_reference({**payload,'name':'Conteúdo diferente'})
    d=objects.get(ref['id'])['definition'];first=d['rows'][0]
    # Frozen plan identifies a piece+operation, not merely its reference.
    event={'key':'evt','planning_keys':[first['planning_key']],'values':{'machine':'MEBA','operation':'corte','quantity':12,'production_date':'2026-09-23','association_status':'technical_unique','of':'OF4200'},'record_id':1}
    with psycopg.connect(workspace,row_factory=dict_row) as c:projection.publish(c,'production:perfis','capacity-test-events',[event],{})
    actual=views.compliance({'id':ref['id']})
    assert actual['coverage']['known']==1 and actual['coverage']['planned']==36
    assert actual['coverage']['percent']==pytest.approx(100/3)
    assert actual['rows'][1]['produced'] is None # missing OCR stays unknown
    # Source observations do not mutate the frozen plan, and stale proposals fail.
    changed=query.listing({'area':'perfis'})['rows']
    next(r for r in changed if r['key']==first['planning_key'])['values']['length_mm']=9999
    with psycopg.connect(workspace,row_factory=dict_row) as c:projection.publish(c,'planning:perfis','technical-change-fixture',changed,{})
    assert objects.get(ref['id'])['definition']==d
    assert views.compliance({'id':ref['id']})['coverage']['known']==0
    with pytest.raises(planning.PlanningError):views.save_reference(command(**p,name='Obsoleto',token=preview['token'],confirmed=True))


def test_week_reference_accepts_current_worked_hours_and_rejects_pending_revision(workspace):
    from tests.test_planning_worked_hours import save
    p=setup_week(workspace)
    resource=objects.save(command(name='MEBA hours',definition={
        'aliases':[{'area':'perfis','name':'MEBA'}],'operations':['corte'],'confirmed':True}),'resource')
    definition={'resource_id':resource['id'],'mode':'period','start_date':'2026-09-22',
        'end_date':'2026-09-22','hours':4,'source':'Apontamento conferido','confirmed':True,'replace_ocr':True}
    saved,_=save(definition)
    for a in planning.AREAS:projection.rebuild(a)
    capacity.rebuild();p['version']=views.overview({k:v for k,v in p.items() if k!='version'})['version']
    preview=views.reference_preview(p)
    reference=views.save_reference(command(**p,token=preview['token'],confirmed=True,name='Com horas reais'))
    frozen=objects.get(reference['id'])['definition']
    save({**definition,'hours':6},id=saved['id'],expected_revision=saved['revision'])
    with pytest.raises(planning.PlanningError,match='configuração mudou'):
        views.reference_preview(p)
    for a in planning.AREAS:projection.rebuild(a)
    capacity.rebuild();p['version']=views.overview({k:v for k,v in p.items() if k!='version'})['version']
    assert views.reference_preview(p)['count']==preview['count']
    assert objects.get(reference['id'])['definition']==frozen


def test_workbook_formula_and_duplicate_rows_preserved(workspace):
    # Genuine workbook extracts are stored independently from the XLSM snapshot contract.
    evidence={'PlanDisponibilidadeSemanal':[{'row':101,'cells':{'B':{'value':39},'C':{'value':2026},'D':{'value':'Vanguard'},'F':{'value':10},'G':{'value':8},'H':{'value':80,'formula':'F101*G101'}}},{'row':103,'cells':{'B':{'value':39},'C':{'value':2026},'D':{'value':'Vanguard'},'F':{'value':2},'G':{'value':16}}}]}
    with psycopg.connect(workspace,row_factory=dict_row) as c:c.execute("INSERT INTO planning_mtg.raw_workbook_evidence(snapshot_id,source_sha256,source_filename,sheets) VALUES('s1','fixture','fixture.xlsm',%s)",(Jsonb(evidence),))
    p=setup_week(workspace)
    row=next(r for r in views.overview(p)['rows'] if r['values']['machine']=='Vanguard')
    assert row['calendar_conflict']
    assert [r['hours'] for r in row['calendars']]==[80,32]
    cells=views.evidence({'area':'perfis','version':p['version']})['sheets']['PlanDisponibilidadeSemanal'][0]['cells']
    assert cells['H']['formula']=='F101*G101'


def test_invalidated_local_quantity_cannot_reappear_in_capacity(workspace):
    row={'key':'local-invalid','values':{'of':'OF4200','component_ref':'local','machine':'MEBA','operation':'corte','status':'Em Aberto','expected_date':'2026-09-22','quantity_to_plan':None,'section_unit':20,'length_mm':1000},'preparations':[{'values_json':{'operation':'corte','quantity_to_plan':99},'operation_id':'corte','record_status':'ready','capacity_compatible':False}]}
    with planning.connect() as c:
        projection.publish(c,'planning:perfis','invalid-conference',[row],{'core_source_fingerprint':projection.fingerprint(c,'perfis')})
        projection.publish(c,'planning:cantoneiras','invalid-conference',[],{'core_source_fingerprint':projection.fingerprint(c,'cantoneiras')})
    capacity.rebuild();r=query.listing({'dataset':'capacity_items'})['rows'][0]
    assert r['values']['quantity'] is None and r['values']['planned_hours'] is None
    assert 'revisão' in r['reason']


def _drive_file(path,when,sha):
    return {'Path':path,'Name':path.rpartition('/')[2],'ModTime':when,'Hashes':{'sha256':sha}}


def test_drive_choice_sees_a_newer_plan_in_a_subfolder():
    # Auditoria 06/10 (A1-F1/A1-F2): o plano gravado só em "Kanban's MTG3/" passava despercebido.
    name='Met2_Plan_Perfis.xlsm'
    root=_drive_file(name,'2026-09-29T07:00:00Z','old')
    sub=_drive_file("Kanban's MTG3/"+name,'2026-09-30T06:58:51.241123456Z','new')
    stale=_drive_file('SAIDA/'+name,'2026-09-21T12:54:32Z','older')
    assert workbooks.drive_choice([root,sub,stale],name) is sub
    assert workbooks.drive_choice([root,stale],name) is root
    assert workbooks.drive_choice([root,{**sub,'Hashes':{'sha256':'old'}}],name) is root
    assert workbooks.drive_choice([sub],name) is sub


def test_drive_observation_reports_newer_plan_in_subfolder(workspace,monkeypatch):
    import json,subprocess
    imported={}
    with planning.connect() as c:
        for a in planning.AREAS:
            snap=planning.snapshot(c,a)
            imported[a]=c.execute('SELECT source_sha256 FROM audit_mtg.snapshots WHERE snapshot_id=%s',(snap['snapshot_id'],)).fetchone()['source_sha256']
    files=[_drive_file('Met2_Plan_Perfis.xlsm','2026-09-29T07:00:00Z',imported['perfis']),
           _drive_file("Kanban's MTG3/Met2_Plan_Perfis.xlsm",'2026-09-30T06:58:51Z','subfolder-hash'),
           _drive_file('Met3_Plan_Cantoneiras.xlsm','2026-09-29T07:00:00Z',imported['cantoneiras'])]
    calls=[]
    def run(command,**kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command,0,json.dumps(files),'')
    monkeypatch.setenv('MES_RAW_DRIVE_CHECK','1')
    monkeypatch.setattr(workbooks.subprocess,'run',run)
    workbooks.observe_drive(force=True)
    assert '--recursive' in calls[0] and '- crm-backups/**' in calls[0]
    by_area={x['area']:x for x in workbooks.status()['sources']}
    assert by_area['perfis']['newer_available'] and by_area['perfis']['newer_folder']=="Kanban's MTG3"
    assert by_area['perfis']['drive']['remote_filename']=="Kanban's MTG3/Met2_Plan_Perfis.xlsm"
    assert not by_area['cantoneiras']['newer_available'] and by_area['cantoneiras']['newer_folder'] is None


def test_drive_failure_preserves_observation_and_does_not_import(workspace,monkeypatch):
    import subprocess
    with planning.connect() as c:
        for a in planning.AREAS:c.execute("INSERT INTO planning_mtg.raw_drive_observations(area,checked_at,remote_sha256,remote_filename) VALUES(%s,now(),'known-hash','known-file')",(a,))
    before=workbooks.status()
    monkeypatch.setenv('MES_RAW_DRIVE_CHECK','1')
    def fail(*args,**kwargs):raise subprocess.TimeoutExpired('rclone',40)
    monkeypatch.setattr(workbooks.subprocess,'run',fail)
    workbooks.observe_drive(force=True)
    after=workbooks.status()
    for x,y in zip(before['sources'],after['sources']):
        assert x['snapshot']==y['snapshot']
        assert x['drive']['checked_at']==y['drive']['checked_at']
        assert y['drive']['remote_sha256']=='known-hash' and y['drive']['error']


def test_rate_proposals_skip_cantoneiras_rows_without_machine(monkeypatch):
    # Auditoria 06/10 (A4-07): linhas com Mt\h mas sem máquina davam propostas de ritmo com machine=None.
    from contextlib import contextmanager

    class Conn:
        def execute(self, sql, args=None):
            class R:
                def fetchall(self):
                    return [{'machine': None, 'operation': '119', 'material_type': 'L', 'profile_type': 'L60', 'speed': '80', 'n': 3},
                            {'machine': '', 'operation': '119', 'material_type': 'L', 'profile_type': 'L60', 'speed': '80', 'n': 1},
                            {'machine': 'Peddi 8', 'operation': '119', 'material_type': 'L', 'profile_type': 'L60', 'speed': '80', 'n': 2}]
            return R()

    @contextmanager
    def connect(readonly=False):
        yield Conn()
    monkeypatch.setattr(planning, 'connect', connect)
    monkeypatch.setattr(workbooks, 'source', lambda c, a: {})
    monkeypatch.setattr(calc, 'workbook_index', lambda sources: ({}, {}, None))
    monkeypatch.setattr(planning, 'snapshot', lambda c, a: {'snapshot_id': 'mtg_x'})
    rates = [p for p in views.proposals()['proposals'] if p['kind'] == 'rate']
    assert [p['machine'] for p in rates] == ['Peddi 8']
