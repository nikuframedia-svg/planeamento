"""Acceptance examples use a frozen clock and synthetic confirmed test calendars."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import uuid

import psycopg
import pytest

from app import planning, planning_calendars, planning_dates, planning_estimates
from app.gantt import baseline, solver, validation
from app.gantt.calendar import first_fit, windows
from tests.test_raw_workspace import workspace
from tests.test_planning_raw import database, canonical, registry, postgres16


MONDAY = datetime(2026, 9, 21, 7, tzinfo=timezone.utc)  # 08:00 Lisbon


def calendar(year=2026, week=39):
    return planning_calendars.validate({'year': year, 'week': week,
        'timezone': 'Europe/Lisbon',
        'weekly_windows': {str(day): ([{'start':'08:00','end':'12:00'},
                                       {'start':'13:00','end':'17:00'}] if day <= 5 else []) for day in range(1,8)},
        'date_overrides': {}, 'confirmed': True})


def synthetic(operations, resources=('meba',), weeks=1, pins=None):
    rows = planning_calendars.expand(calendar())
    return {'started_at': MONDAY.isoformat(), 'horizon_minutes': weeks*7*1440,
            'resources': {rid: {'name':rid,'windows':rows,'operations':['corte','abocardar']} for rid in resources},
            'operations': operations, 'orders': {'OF1':[op['key'] for op in operations]},
            'pins': pins or {}, 'accepted_bars': {}}


def operation(key, duration, *, machine='meba', predecessor=None, balance=10, priority=2):
    return {'key':key,'of':'OF1','operation':'abocardar' if predecessor else 'corte',
            'state':'complete' if balance==0 else 'ready', 'planning_remaining':balance,
            'reconciled_remaining':balance, 'provisional':False,'priority_group':priority,
            'deadline':None,'predecessor_key':predecessor,
            'options':[] if balance==0 else [{'resource_id':machine,'duration_minutes':duration,
                                               'duration_hours':duration/60,'quantity':balance,
                                               'earliest_minute':0,'latest_minute':None}],
            'blocking_reasons':[]}


def test_picking_and_cut_dates_are_distinct():
    rows=[{'row_data':{'values':['', 'OF265270',34]},'excel_row':4}]
    indexed,evidence=planning_dates.picking_index(rows)
    found=planning_dates.resolve_picking('OF265270',None,indexed,evidence)
    assert found['week']==34 and found['origin']=='Picking · folha'
    rows.append({'row_data':{'values':['','OF265270',35]},'excel_row':5})
    indexed,evidence=planning_dates.picking_index(rows)
    assert planning_dates.resolve_picking('OF265270',None,indexed,evidence)['conflict']
    due=planning_dates.picking_deadline(39)
    assert due['at']=='2026-09-21T08:00:00+01:00' and due['provisional']
    assert planning_dates.period({'cut_date':'2026-09-22'},area='perfis',operation='corte')[:2]==(2026,39)
    assert planning_dates.period({'cut_date':'2026-09-22'},area='perfis',operation='abocardar')[:2]==(None,None)
    assert planning_dates.period({'cut_date':'2027-01-01'},area='perfis',operation='corte')[:2]==(2026,53)


def test_provisional_balance_preserves_unknown_production():
    row={'area':'perfis','values':{'quantity_required':100},'original':{'quantity_required':100},
         'raw':{'Qtd em Falta':40},
         'calculation':{'production_sources':[{'operation':'corte','remaining':None,'origin':'Indisponível'}]},
         'compatible':True}
    balance=planning_estimates.select_balance(row,'corte')
    assert balance['reconciled_remaining'] is None
    assert balance['planning_remaining']==40 and balance['provisional']
    assert planning_estimates.select_balance(row,'abocardar')['planning_remaining'] is None


def test_macro_balance_is_invalidated_by_required_quantity_or_identity_change():
    row={'area':'perfis','values':{'component_ref':'A','quantity_required':100},
         'original':{'component_ref':'A','quantity_required':100},
         'raw':{'Qtd em Falta':40},'calculation':{'compatible':True}}
    assert planning_estimates.select_balance(row,'corte')['planning_remaining']==40
    for changed in (1, 200):
        altered={**row,'values':{**row['values'],'quantity_required':changed}}
        result=planning_estimates.select_balance(altered,'corte')
        assert result['planning_remaining'] is None
        assert 'Quantidade necessária alterada' in result['reasons'][0]
    changed={**row,'values':{**row['values'],'component_ref':'B'}}
    assert planning_estimates.select_balance(changed,'corte')['planning_remaining'] is None


def test_gantt_uses_manual_period_and_blocks_conflicting_manual_date(monkeypatch):
    from app.gantt import inputs
    resource_id='11111111-1111-4111-8111-111111111111'
    configs=[{'id':resource_id,'kind':'resource','name':'M',
              'definition':{'confirmed':True,'operations':['corte'],
                            'aliases':[{'area':'perfis','name':'M'}]}},
             {'id':'calendar-test','kind':'calendar','definition':{**calendar(),'resource_id':resource_id}},
             {'kind':'rate','definition':{'confirmed':True,'resource_id':resource_id,
                                        'area':'perfis','operation':'corte','method':'units_hour',
                                        'value':10,'valid_from':'2026-01-01'}}]
    class Cursor:
        def __init__(self,rows):self.rows=rows
        def fetchall(self):return self.rows
    class Source:
        def __init__(self,values):self.values=values
        def execute(self,sql,args=None):
            if 'raw_objects' in sql:return Cursor(configs)
            return Cursor([{'row_key':'line1','values_json':self.values,
                'detail':{'area':'perfis','calculation':{'compatible':True,
                'operation_estimates':[{'operation':'corte','machine':'Por definir','hours':1,'quantity':10,'source':'Macro'}],
                'production_sources':[{'operation':'corte','remaining':10,'origin':'OCR validado'}]}}}])
    monkeypatch.setattr(inputs,'references',lambda conn:{'planning_generation':1,'sources_pending':False})
    monkeypatch.setattr(inputs.query,'generation',lambda *args,**kwargs:{})
    monkeypatch.setattr(inputs.query,'source',lambda generation:(' FROM dummy WHERE true',[]))
    basic={'of':'OF1','component_ref':'R','machine':'M','quantity_required':10,'abocardar':'-'}
    selected=inputs.capture(Source({**basic,'cut_date':'2026-09-22',
                                   'planned_year':2026,'planned_week':43}),{},MONDAY)['operations'][0]
    assert selected['state']=='ready'
    assert selected['milestones']['period_origin']=='Decisão local'
    assert selected['milestones']['period_week']==43
    assert selected['milestones']['cut_date']=='2026-09-22'
    assert selected['deadline']=='2026-10-26T00:00:00+00:00'
    conflict=inputs.capture(Source({**basic,'expected_date':'2026-09-22',
                                   'planned_year':2026,'planned_week':40}),{},MONDAY)['operations'][0]
    assert conflict['state']=='blocked'
    assert 'Data prevista e semana escolhida não coincidem.' in conflict['blocking_reasons']
    configs.clear()
    imported=inputs.capture(Source(basic),{},MONDAY)['operations'][0]
    assert imported['source_machine']=='M'
    assert imported['blocking_reasons']==['Calendário horário por confirmar.']
    assert imported['options'][0]['duration_minutes']==60
    absent=inputs.capture(Source({**basic,'machine':None}),{},MONDAY)['operations'][0]
    assert absent['blocking_reasons']==['Máquina da operação por indicar.']


def test_working_minutes_lunch_weekend_zero_and_dst():
    snap=synthetic([operation('cut',180)])
    monday11=180
    found=first_fit(windows(snap,'meba'),monday11,180,fixed=monday11)
    assert found=={'start':180,'end':420,'segments':[(180,240),(300,420)]}
    friday16=4*1440+480
    found=first_fit(windows(snap,'meba'),friday16,120,fixed=friday16)
    assert found is None  # the next Monday lies outside this one-week horizon
    next_week=planning_calendars.validate({**calendar(), 'week':40})
    snap['resources']['meba']['windows']+=planning_calendars.expand(next_week)
    snap['horizon_minutes']=2*7*1440
    found=first_fit(windows(snap,'meba'),friday16,120,fixed=friday16)
    assert found['end']==7*1440+60
    dst=planning_calendars.validate({'year':2026,'week':43,'timezone':'Europe/Lisbon',
        'weekly_windows':{'7':[{'start':'00:00','end':'04:00'}]},'date_overrides':{},'confirmed':True})
    assert planning_calendars.available_hours(dst)==5


def test_confirmed_hourly_reservations_reduce_one_physical_calendar():
    original=calendar()
    reserved=planning_calendars.validate({**original,'reserved_windows':[
        {'start':'2026-09-21T09:00:00+01:00','end':'2026-09-21T10:00:00+01:00',
         'area':'cantoneiras'}]})
    assert planning_calendars.available_hours(reserved)==39
    snap=synthetic([operation('cut',120)])
    snap['resources']['meba']['windows']=planning_calendars.expand(reserved)
    first=baseline.build(snap)
    assert first['bars']['cut']['start_minute']==0
    assert first['bars']['cut']['end_minute']==180
    assert first['bars']['cut']['segments']==[(0,60),(120,180)]
    assert validation.validate(snap,first)['valid']
    with pytest.raises(ValueError,match='sobrepostas'):
        planning_calendars.validate({**original,'reserved_windows':[
            {'start':'2026-09-21T09:00:00+01:00','end':'2026-09-21T10:00:00+01:00'},
            {'start':'2026-09-21T09:30:00+01:00','end':'2026-09-21T10:30:00+01:00'}]})
    with pytest.raises(ValueError,match='semana'):
        planning_calendars.validate({**original,'reserved_windows':[
            {'start':'2026-09-28T09:00:00+01:00','end':'2026-09-28T10:00:00+01:00'}]})


def test_baseline_dependency_overlap_and_independent_rejection():
    snap=synthetic([operation('cut',120),operation('boc',60,machine='boc-machine',predecessor='cut')],
                   resources=('meba','boc-machine'))
    result=baseline.build(snap)
    assert result['bars']['cut']['end_minute']==120
    assert result['bars']['boc']['start_minute']>=120
    assert validation.validate(snap,result)['valid']
    corrupted={**result,'bars':{**result['bars'],'boc':{**result['bars']['boc'],'start_minute':0}}}
    assert not validation.validate(snap,corrupted)['valid']
    wrong_quantity=synthetic([operation('cut',120)])
    wrong_quantity['operations'][0]['options'][0]['quantity']=11
    invalid={'bars':{'cut':result['bars']['cut']},'states':{'cut':'scheduled'}}
    assert any('quantidade' in error for error in validation.validate(wrong_quantity,invalid)['errors'])
    pinned=synthetic([operation('a',120),operation('b',120)],pins={
        'a':{'resource_id':'meba','start':MONDAY.isoformat()},
        'b':{'resource_id':'meba','start':MONDAY.isoformat()}})
    with pytest.raises(ValueError,match='fixação'):
        baseline.build(pinned)


def test_feasible_pin_reserves_capacity_before_free_work():
    pinned=synthetic([operation('a',120),operation('b',60)],pins={
        'b':{'resource_id':'meba','start':MONDAY.isoformat()}})
    first=baseline.build(pinned)
    assert first['bars']['b']['start_minute']==0
    assert first['bars']['a']['start_minute']==60
    assert validation.validate(pinned,first)['valid']


def test_picking_due_uses_all_operations_even_if_successor_is_urgent():
    cut=operation('cut',60,priority=1)
    boc=operation('boc',60,machine='boc',predecessor='cut',priority=0)
    cut['deadline']=boc['deadline']=(MONDAY+timedelta(minutes=60)).isoformat()
    snapshot=synthetic([cut,boc],resources=('meba','boc'))
    first=baseline.build(snapshot)
    assert first['score'][3]==60
    assert validation.validate(snapshot,first)['score'][3]==60
    optimized,technical=solver.optimize(snapshot,first,seconds=3)
    assert validation.validate(snapshot,optimized)['valid']
    assert optimized['score'][3]==60


def test_provisional_cut_propagates_to_abocardar_and_validator_checks_origin():
    cut=operation('cut',60);cut['balance_provisional']=cut['provisional']=True
    boc=operation('boc',60,machine='boc',predecessor='cut')
    snapshot=synthetic([cut,boc],resources=('meba','boc'))
    first=baseline.build(snapshot)
    assert first['bars']['boc']['provisional']
    assert first['bars']['boc']['provisional_reasons']==['Saldo provisório da operação cut']
    corrupted={**first,'bars':{**first['bars'],'boc':{**first['bars']['boc'],
                                            'provisional':False,'provisional_reasons':[]}}}
    assert not validation.validate(snapshot,corrupted)['valid']
    optimized,technical=solver.optimize(snapshot,first,seconds=3)
    assert validation.validate(snapshot,optimized)['valid']
    assert optimized['bars']['boc']['provisional']


def test_validator_rejects_duplicate_operation_keys():
    snapshot=synthetic([operation('same',60),operation('same',60)])
    proposal={'bars':{},'states':{'same':'overflow'}}
    assert any('repetidas' in error for error in validation.validate(snapshot,proposal)['errors'])


def test_predecessor_outside_horizon_leaves_successor_visible():
    snap=synthetic([operation('cut',10000),operation('boc',60,machine='boc-machine',predecessor='cut')],
                   resources=('meba','boc-machine'))
    result=baseline.build(snap)
    assert result['states']=={'cut':'overflow','boc':'overflow'}
    assert not result['bars']
    assert validation.validate(snap,result)['valid']


def test_pin_transfer_requires_unique_technical_match():
    from app.gantt.inputs import reconcile_pins
    signature={'profile':'P','length_mm':1000}
    binding={'of':'OF1','operation':'corte','planning_key':'old',
             'selection_aliases':[],'technical_signature':signature}
    candidate={'key':'new:corte','planning_key':'new','selection_aliases':['old'],
               'of':'OF1','operation':'corte','technical_signature':signature,'state':'ready'}
    pin={'resource_id':'meba','start':MONDAY.isoformat()}
    assert reconcile_pins([candidate],{'old:corte':pin},{'old:corte':binding})==(
        {'new:corte':pin},{'old:corte':'new:corte'},[])
    duplicate={**candidate,'key':'another:corte','planning_key':'another','selection_aliases':['old']}
    assert reconcile_pins([candidate,duplicate],{'old:corte':pin},{'old:corte':binding})[2]==['old:corte']
    changed={**candidate,'technical_signature':{'profile':'P','length_mm':1200}}
    assert reconcile_pins([changed],{'old:corte':pin},{'old:corte':binding})[2]==['old:corte']


def test_small_flexible_job_shop_matches_independent_enumeration():
    from itertools import product
    jobs=[operation('a',120,machine='a'),operation('b',120,machine='a'),
          operation('c',60,machine='a')]
    choices=[(120,180),(120,180),(60,60)]
    for job,(_,alternative) in zip(jobs,choices):
        job['options'].append({'resource_id':'b','duration_minutes':alternative,
                               'duration_hours':alternative/60,'quantity':job['planning_remaining'],
                               'earliest_minute':0,'latest_minute':None})
    snapshot=synthetic(jobs,resources=('a','b'))
    first=baseline.build(snapshot)
    final,technical=solver.optimize(snapshot,first,seconds=5)
    independent=min(max(sum(choices[i][selected[i]] for i in range(3) if selected[i]==machine)
                        for machine in (0,1)) for selected in product((0,1),repeat=3))
    assert independent==180
    assert validation.validate(snapshot,final)['valid']
    assert final['score'][-1]==independent
    assert technical['optimal']


def test_solver_never_worsens_baseline_and_rejects_unlisted_machine():
    snap=synthetic([operation('a',120),operation('b',60),operation('c',45)])
    snap['resources']['fast']={'name':'fast','windows':snap['resources']['meba']['windows'],'operations':['corte']}
    initial=baseline.build(snap)
    better,status=solver.optimize(snap,initial,seconds=3)
    assert validation.validate(snap,better)['valid']
    assert better['score']<=initial['score']
    assert all(bar['resource_id']=='meba' for bar in better['bars'].values())
    assert status['status'] in ('OPTIMAL','FEASIBLE','sem tempo para otimizar')
    snap['operations'][0]['deadline']='2025-01-01T00:00:00+00:00'
    initial=baseline.build(snap)
    still_valid,status=solver.optimize(snap,initial,seconds=3)
    assert validation.validate(snap,still_valid)['valid']
    assert still_valid['score']<=initial['score']


def test_inputs_include_more_than_a_listing_page(workspace):
    from app.raw import projection, query
    from app.gantt import inputs
    rows=[]
    for index in range(620):
        rows.append({'key':f'test-line:{index:04}',
                     'values':{'of':f'OF{100000+index}','component_ref':f'R{index}',
                               'quantity_required':10,'status':'Em Aberto','machine':'M',
                               'abocardar':'-','planning_active':True},
                     'raw':{'Qtd em Falta':10},'calculation':{'production_sources':[
                         {'operation':'corte','remaining':None,'origin':'Indisponível'}]}})
    with planning.connect() as conn:
        projection.publish(conn,'planning:perfis','gantt-620-test',rows,{})
    with planning.connect(readonly=True) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        snapshot=inputs.capture(conn,{},MONDAY)
    assert len(snapshot['operations'])==620
    assert snapshot['operations'][0]['key']=='test-line:0000:corte'
    assert snapshot['operations'][-1]['key']=='test-line:0619:corte'


def test_rate_changes_create_same_machine_options_with_distinct_validity(workspace):
    from app.raw import projection, objects
    from app.gantt import inputs
    resource=objects.save({'request_id':str(uuid.uuid4()),'name':'Máquina de taxas','area':'perfis',
        'definition':{'aliases':[{'area':'perfis','name':'M'}],
                      'operations':['corte'],'confirmed':True}},'resource')
    objects.save({'request_id':str(uuid.uuid4()),'name':'Semana de taxas','area':'perfis',
                  'definition':{**calendar(),'resource_id':resource['id']}},'calendar')
    for from_day,until,speed in [('2026-09-21','2026-09-21',10),('2026-09-22',None,20)]:
        objects.save({'request_id':str(uuid.uuid4()),'name':f'Taxa {speed}','area':'perfis',
            'definition':{'resource_id':resource['id'],'area':'perfis','operation':'corte',
                          'method':'units_hour','value':speed,'valid_from':from_day,
                          'valid_until':until,'confirmed':True}},'rate')
    row={'key':'test-rate','area':'perfis','values':{'of':'OF1','component_ref':'R1',
        'machine':'M','quantity_required':20,'status':'Em Aberto','planning_active':True,
        'abocardar':'-'},'raw':{},'calculation':{'production_sources':[
            {'operation':'corte','remaining':20,'origin':'OCR validado'}]}}
    with planning.connect() as conn:
        projection.publish(conn,'planning:perfis','rate-horizon-test',[row],{})
    tuesday=datetime(2026,9,22,7,tzinfo=timezone.utc).isoformat()
    with planning.connect(readonly=True) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        snapshot=inputs.capture(conn,{'horizon_weeks':1,
            'pins':{'test-rate:corte':{'resource_id':resource['id'],'start':tuesday}}},MONDAY)
    op=snapshot['operations'][0]
    assert op['state']=='ready'
    assert {option['duration_minutes'] for option in op['options']}=={60,120}
    planned=baseline.build(snapshot)
    assert planned['bars']['test-rate:corte']['duration_minutes']==60
    assert planned['bars']['test-rate:corte']['start_minute']==1440
    assert validation.validate(snapshot,planned)['valid']
    optimized,technical=solver.optimize(snapshot,planned,seconds=3)
    assert validation.validate(snapshot,optimized)['valid']
    assert optimized['bars']['test-rate:corte']['duration_minutes']==60
    assert optimized['score']<=planned['score']


def test_gantt_scenario_revision_and_idempotency_on_disposable_database(workspace,monkeypatch):
    from app.raw import projection, worker, objects, capacity, query
    from app.gantt import service
    monkeypatch.setenv('MES_PLANNING_GANTT_ENABLED','1')
    with psycopg.connect(workspace) as c:
        c.execute((Path(__file__).parents[1]/'sql/037_planning_gantt.sql').read_text())
    projection.rebuild('perfis')
    projection.rebuild('cantoneiras')
    capacity.rebuild()
    request={'request_id':str(uuid.uuid4()),'name':'Teste Gantt','area':'perfis',
             'definition':{'horizon_weeks':1},'expected_revision':0}
    saved=service.save(request)
    assert service.save(request)==saved
    assert len(service.scenarios()['scenarios'])==1
    with pytest.raises(planning.PlanningError) as stale:
        service.save({**request,'request_id':str(uuid.uuid4()),'id':saved['id'],
                      'expected_revision':0})
    assert stale.value.status==409
    with pytest.raises(planning.PlanningError):
        service.save({**request,'request_id':str(uuid.uuid4()),'definition':{'accepted':{'job_id':'fake'}}})
    queued=service.solve({'request_id':str(uuid.uuid4()),'id':saved['id'],'expected_revision':saved['revision']})
    assert queued['status']=='queued'
    claimed=worker.tick('gantt-test')
    assert len(claimed)==1 and claimed[0]['kind']=='gantt'
    service.run_job(claimed[0])
    finished=service.job(queued['job_id'])
    assert finished['status']=='done' and finished['result']['phase']=='done'
    assert finished['input']['runtime_manifest']['code_sha256']==service.runtime_manifest()['code_sha256']
    assert finished['input']['runtime_manifest']['python_dependencies']['ortools']
    assert service.scenarios()['scenarios'][0]['latest_job_id']==queued['job_id']
    assert finished['input']['snapshot']['operations']
    assert finished['result']['validation']['valid']
    assert set(finished['result']['proposal']['states'])=={
        op['key'] for op in finished['input']['snapshot']['operations']}
    accepted=service.accept({'request_id':str(uuid.uuid4()),'job_id':queued['job_id'],
                             'expected_revision':saved['revision']})
    assert accepted['revision']==saved['revision']+1
    assert not service.scenarios()['scenarios'][0]['stale']
    with monkeypatch.context() as patch:
        patch.setattr(service,'runtime_manifest',lambda:{'code_sha256':'changed'})
        assert service.job(queued['job_id'])['stale']
        assert service.scenarios()['scenarios'][0]['stale']
    with planning.connect() as conn:
        generation=query.generation(conn,'perfis');base,args=query.source(generation)
        source=conn.execute('SELECT m.row_key,c.detail,c.values_json'+base+' ORDER BY m.row_key LIMIT 1',args).fetchone()
        unchanged={**source['detail'],'key':source['row_key'],
                   'values':{**source['values_json'],'stock_length_mm':9876}}
        projection.publish_delta(conn,'planning:perfis','stock-only-test',[unchanged],
                                 generation['metadata'],expected_generation=generation['id'])
    assert not service.job(queued['job_id'])['stale']
    assert not service.scenarios()['scenarios'][0]['stale']
    resource=objects.save({'request_id':str(uuid.uuid4()),'name':'Máquina nova','area':'perfis',
                  'definition':{'aliases':[{'area':'perfis','name':'Máquina nova'}],
                                'operations':['corte'],'confirmed':True}},'resource')
    assert service.job(queued['job_id'])['stale']
    assert service.scenarios()['scenarios'][0]['stale']
    hourly=objects.save({'request_id':str(uuid.uuid4()),'name':'Horário de ensaio','area':'perfis',
        'definition':{**calendar(),'resource_id':resource['id'],
                      'date_overrides':{'2026-09-24':[]},
                      'reserved_windows':[{'start':'2026-09-21T09:00:00+01:00',
                                           'end':'2026-09-21T10:00:00+01:00',
                                           'area':'cantoneiras'}]}},'calendar')
    assert planning_calendars.available_hours(hourly['definition'])==31
    copy={'request_id':str(uuid.uuid4()),'source_id':hourly['id'],
          'expected_revision':hourly['revision'],'start_year':2026,'start_week':40,
          'end_year':2026,'end_week':40}
    preview=capacity.copy_calendar(copy)
    copied=capacity.copy_calendar({**copy,'confirm':True,'evidence_hash':preview['evidence_hash']})
    assert len(copied['items'])==1
    definition=copied['items'][0]['definition']
    assert definition['date_overrides']=={}
    assert definition['reserved_windows']==[]
    assert planning_calendars.available_hours(definition)==40


def test_gantt_browser_generate_accept_and_reopen(workspace,monkeypatch,tmp_path):
    import os, socket, subprocess, threading, time, urllib.request
    from app.raw import projection, capacity, worker, objects, query
    from app.gantt import service
    with psycopg.connect(workspace) as c:
        c.execute((Path(__file__).parents[1]/'sql/037_planning_gantt.sql').read_text())
    projection.rebuild('perfis');projection.rebuild('cantoneiras')
    example=next(row for row in query.listing({'area':'perfis','page_size':25})['rows'] if row['values'].get('machine'))
    machine=example['values']['machine']
    physical=objects.save({'request_id':str(uuid.uuid4()),'name':'Máquina Gantt de ensaio','area':'perfis',
        'definition':{'aliases':[{'area':'perfis','name':machine}], 'operations':['corte'], 'confirmed':True}},'resource')
    objects.save({'request_id':str(uuid.uuid4()),'name':'Horário Gantt de ensaio','area':'perfis',
        'definition':{**calendar(),'resource_id':physical['id']}},'calendar')
    objects.save({'request_id':str(uuid.uuid4()),'name':'Taxa Gantt de ensaio','area':'perfis',
        'definition':{'resource_id':physical['id'],'area':'perfis','operation':'corte',
                      'method':'units_hour','value':20,'setup_minutes':15,
                      'valid_from':'2026-01-01','confirmed':True}},'rate')
    projection.rebuild('perfis');projection.rebuild('cantoneiras');capacity.rebuild()
    evidence=Path(__file__).parents[1]/'docs/gantt-2026-09-24';evidence.mkdir(parents=True,exist_ok=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    env={**os.environ,'MES_PG_DSN':os.environ['MES_PG_DSN'],
         'MES_DATA_DIR':str(tmp_path),'MES_DOSSIER_WORKER_DISABLED':'1',
         'MES_PLANNING_NEEDS_ENABLED':'1','MES_PLANNING_RAW_ENABLED':'1',
         'MES_RAW_WORKSPACE_ENABLED':'1','MES_PLANNING_GANTT_ENABLED':'1',
         'PLANNING_CHECK_BASE':f'http://127.0.0.1:{port}',
         'GANTT_EVIDENCE':str(evidence)}
    done=threading.Event()
    def jobs():
        while not done.is_set():
            for queued in worker.tick('browser-gantt'):
                if queued['kind']=='gantt':service.run_job(queued)
            done.wait(.15)
    thread=threading.Thread(target=jobs,daemon=True)
    with (tmp_path/'gantt-server.log').open('w+') as log:
        proc=subprocess.Popen([str(Path(__file__).parents[1]/'.venv/bin/python'),'-m','uvicorn',
                               'app.web.planning_app:app','--host','127.0.0.1','--port',str(port)],
                              cwd=Path(__file__).parents[1],env=env,stdout=log,stderr=log)
        try:
            for _ in range(100):
                try:
                    urllib.request.urlopen(env['PLANNING_CHECK_BASE']+'/planeamento/gantt',timeout=.3)
                    break
                except Exception:time.sleep(.1)
            else:pytest.fail('O servidor Gantt não iniciou.')
            thread.start()
            run=subprocess.run(['node','tests/planning_gantt_browser.cjs'],env=env,
                               capture_output=True,text=True,timeout=90,cwd=Path(__file__).parents[1])
            log.flush();log.seek(0)
            assert run.returncode==0,run.stdout+run.stderr+'\n'+log.read()
        finally:
            done.set();thread.join(timeout=5) if thread.is_alive() else None
            proc.terminate();proc.wait(timeout=10)
