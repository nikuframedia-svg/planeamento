"""Technical decisions, coherent imports and shared real-time capacity."""
import copy
from datetime import date
from pathlib import Path
import uuid

import psycopg
import pytest
from app import planning, planning_needs as needs
from app.gantt import research, integrated, machines, inputs, service, baseline, solver, validation, weekly, insights
from tests.test_planning_gantt import synthetic, operation, MONDAY
from tests.test_raw_workspace import workspace
from tests.test_planning_raw import database, canonical, registry, postgres16


def row(**extra):
    return {'setor':'MTG3','ordem_codigo':'OF100','referencia_original':'PART','item_id':'item',
        'operacao_id':'op','linha_origem':'line','ocorrencia':1,'operacao_codigo':'CPIS:112',
        'codigo_original':'112','snapshot_id':'source','excel_linha':1,'fase':'principal',
        'perfil':'L80X80X8','qualidade':'S355','assinatura':'tech','revisao_desenho':None,
        'identidade_tecnica_confirmada':False,'variante_id':'variant','segunda_operacao_estado':'ausente',
        'quantidade_base':10,'saldo_confirmado':None,'saldo_documental':10,'estado_quantidade':'coerente',
        'estado_documental':'aberta','comprimento_mm':1000,'recurso_atual':None,'contador_excel':None,
        'maquina_original':None,'semana_picking':None,'data_corte_prevista':'2026-09-22',
        'raw':{},**extra}


def package():
    resources=[{'codigo':code,'designacao':code,'setor':'MTG3','tipo':'equipamento','quantidade_operadores':None} for code in ('PEDDI6','XPT6','VANGUARD')]
    capacities=[{'id':code,'recurso_codigo':code,'operacao_codigo':'CPIS:112','processo_fisico':'furacao',
        'perfil_minimo':'L30X30X3','perfil_maximo':'L200X200X20','fonte':'ficha','apenas_cliente_nacional':code=='PEDDI6','numero_diametros':3 if code=='XPT6' else None} for code in ('PEDDI6','XPT6')]
    return {'sources':{},'rows':[row()], 'metadata':{'resources':resources,'aliases':[],
        'capacities':capacities,'relations':[],'rates':[],'availability':[],'budgets':[],
        'rules':[],'dependencies':[],'possible_duplicates':[], 'history':[], 'events':[]}}


@pytest.fixture()
def integrated_db(workspace,monkeypatch):
    with psycopg.connect(workspace) as c:
        c.execute((Path(__file__).parents[1]/'sql/037_planning_gantt.sql').read_text())
        for name in ('040_sector_selection.sql','041_integrated_machine_planning.sql','046_sector_member_selection.sql'):
            table={'040':'sector_selection','041':'gantt_source_heads','046':'sector_member_selection'}[name[:3]]
            if not c.execute("SELECT to_regclass(%s)",('planning_mtg.'+table,)).fetchone()[0]:
                c.execute((Path(__file__).parents[1]/'sql'/name).read_text())
        if c.execute("SELECT 1 FROM information_schema.columns WHERE table_schema='planning_mtg' AND table_name='sector_member_selection' AND column_name='phase'").fetchone():
            c.execute((Path(__file__).parents[1]/'sql/047_member_selection_no_phase.sql').read_text())
        c.execute('TRUNCATE planning_mtg.sector_selection,planning_mtg.sector_decision_events,planning_mtg.sector_member_selection,planning_mtg.sector_selection_requests,planning_mtg.gantt_source_rows,planning_mtg.gantt_source_heads,planning_mtg.gantt_source_versions CASCADE')
    monkeypatch.setenv('MES_PLANNING_V2_ENABLED','1')
    research._cache.clear()
    with planning.connect() as c:
        research.publish(c,package())
        from app.raw import projection
        projection.publish(c,'planning:cantoneiras','selected-fixture',[{'key':'macro:line','values':
            {'of':'OF100','component_ref':'PART','profile':'L80X80X8','quantity_required':10,'length_mm':1000,'status':'Em Aberto','operation':'112','planning_active':True,'machine':'PEDDI6'},'area':'cantoneiras'}],{})
        c.execute("INSERT INTO planning_mtg.sector_selection(area,production_order_no,reference,decision,actor) VALUES('cantoneiras','OF100','*','selected','test')")
    return workspace


def test_conditions_are_not_certified_by_frequent_history():
    p=package();r=row()
    p['metadata']['history']=[{'variante_id':'variant','operacao_codigo':'CPIS:112','recurso_atual':'PEDDI6','route':['CPIS:112'],'segunda_operacao_estado':'ausente','ordem_codigo':of} for of in ('OF100','OF101','OF102')]
    resources={r['codigo']:{'id':research.resource_id(r['codigo'])} for r in p['metadata']['resources']}
    options=machines.EvidenceIndex(p['metadata'],[r]).candidates(r,resources)
    peddi=next(o for o in options if o['resource_code']=='PEDDI6')
    xp=next(o for o in options if o['resource_code']=='XPT6')
    assert peddi['other_orders']==2 and peddi['eligibility']=='conditional'
    assert 'confirmar_cliente_nacional' in peddi['conditions']
    assert 'confirmar_numero_de_diametros_da_peca' in xp['conditions']
    r['perfil']='L300X300X30'
    assert all(o['eligibility']=='excluded' for o in machines.EvidenceIndex(p['metadata'],[r]).candidates(r,resources))


def test_112_to_119_requires_explicit_rule():
    p=package();cap={**p['metadata']['capacities'][1],'operacao_codigo':'CPIS:119'}
    p['metadata']['capacities']=[cap]
    r=row();resource={'id':research.resource_id('XPT6'),'technical_rules':[]}
    index=machines.EvidenceIndex(p['metadata'],[r])
    opt=index.candidates(r,{'XPT6':resource})[0]
    assert opt['code_change'] and 'mudanca_112_para_119_requer_decisao' in opt['conditions']
    resource['technical_rules']=[{'operation_code':'CPIS:112','signature':'tech','reason':'Ficha validada','confirmed':True,'resolved_conditions':opt['conditions']}]
    assert index.candidates(r,{'XPT6':resource})[0]['eligibility']=='admissible'


def test_review_of_unknown_revision_does_not_certify_a_later_drawing_revision():
    resource={'technical_rules':[{'operation_code':'CPIS:112','signature':'tech','confirmed':True,'revision':None}]}
    assert len(machines.matching_rules(row(),resource))==1
    assert not machines.matching_rules(row(revisao_desenho='B'),resource)


def test_ambiguous_repeated_operations_never_inherit_decisions():
    ops=[{'key':str(i),'of':'OF1','operation':'112','technical_signature':'sig','planning_key':'new','selection_aliases':[],'area':'cantoneiras','occurrence':i} for i in (1,2)]
    binding={'of':'OF1','operation':'112','technical_signature':'sig','planning_key':'old'}
    assert inputs.reconcile_decisions(ops,{'old':{'resource_id':'x'}},{'old':binding})[2]==['old']
    binding.update(area='cantoneiras',occurrence=2)
    decisions,transfers,orphans=inputs.reconcile_decisions(ops,{'old':{'resource_id':'x'}},{'old':binding})
    assert transfers=={'old':'2'} and not orphans and decisions['2']['resource_id']=='x'


def test_unknown_balance_and_incompatible_units_stay_unknown():
    assert integrated.balance(row(saldo_documental=None))['planning_remaining'] is None
    assert integrated.balance(row(estado_quantidade='divergente'))['planning_remaining'] is None
    r=row(comprimento_mm=None)
    option={'resource_code':'XPT6','proposed_code':'CPIS:112','eligibility':'conditional'}
    rate={('XPT6','CPIS:112'):[{'method':'metres_hour','value':10,'setup_minutes':0}]}
    assert integrated._duration(r,option,{'id':'xp'},[],rate,MONDAY.isoformat()) is None


def test_same_machine_and_rate_keep_distinct_operation_alternatives():
    r=row(recurso_atual='XPT6')
    rate={('XPT6',code):[{'method':'metres_hour','value':10,'setup_minutes':0}] for code in ('CPIS:112','CPIS:119')}
    durations=[integrated._duration(r,{'resource_code':'XPT6','proposed_code':code,'eligibility':'admissible'},
        {'id':'xp'},[],rate,MONDAY.isoformat()) for code in ('CPIS:112','CPIS:119')]
    assert durations[0]['duration_minutes']==durations[1]['duration_minutes']
    assert durations[0]['option_id']!=durations[1]['option_id']


def test_publication_is_idempotent_and_manual_choice_is_independent_of_time(integrated_db):
    with planning.connect() as c:
        initial=research.head(c)['version_id']
        assert not research.publish(c,package())['changed']
        assert research.head(c)['version_id']==initial
    info=service.operations();op=info['operations'][0]
    rid=research.resource_id('XPT6')
    d={'areas':['perfis','cantoneiras'],'machine_overrides':{op['key']:{'resource_id':rid,'reason':'Ferramentas preparadas'}}}
    saved=service.save({'request_id':str(uuid.uuid4()),'name':'Manual','definition':d})
    updated=service.options(op['key'],saved['id'])['operation']
    assert updated['assignment']['mode']=='manual' and updated['assignment']['resource_id']==rid
    assert updated['assignment']['eligibility']=='conditional' and not saved['definition']['pins']
    assert updated['state']=='blocked'
    auto=service.save({'request_id':str(uuid.uuid4()),'id':saved['id'],'expected_revision':saved['revision'],'name':'Manual','definition':{**d,'machine_overrides':{}}})
    assert service.options(op['key'],auto['id'])['operation']['assignment']['mode']=='automatic'


def test_resource_capability_without_operation_keeps_the_unknown(integrated_db):
    p=package()
    p['metadata']['capacities'].append({**p['metadata']['capacities'][0],'id':'unknown','operacao_codigo':None})
    with planning.connect() as c:
        assert research.publish(c,p)['changed']
        resource=c.execute('SELECT definition FROM planning_mtg.raw_objects WHERE id=%s',(research.resource_id('PEDDI6'),)).fetchone()
        assert None not in resource['definition']['operations']


def test_missing_documentary_operation_stays_visible_and_blocked(integrated_db):
    p=package();p['rows'][0].update(operacao_codigo=None,codigo_original=None)
    from app.raw import projection
    with planning.connect() as c:
        research.publish(c,p)
        projection.publish(c,'planning:cantoneiras','missing-operation',[{'key':'macro:line','values':
            {'of':'OF100','component_ref':'PART','profile':'L80X80X8','quantity_required':10,'length_mm':1000,
             'status':'Em Aberto','operation':None,'planning_active':True,'machine':'PEDDI6'},'area':'cantoneiras'}],{})
    op=service.operations()['operations'][0]
    assert op['operation']=='por_definir' and op['state']=='blocked'
    assert 'Operação ou aplicabilidade da rota por confirmar.' in op['blocking_reasons']


def test_only_chosen_orders_with_current_planning_information_enter_gantt(integrated_db):
    assert len(service.operations()['operations'])==1
    scenario=service.save({'request_id':str(uuid.uuid4()),'name':'Seleção obrigatória','definition':{'areas':['cantoneiras']}})
    with planning.connect() as c:
        c.execute('DELETE FROM planning_mtg.sector_selection')
    assert not service.operations()['operations']
    with pytest.raises(planning.PlanningError,match='Planear') as error:
        service.solve({'request_id':str(uuid.uuid4()),'id':scenario['id'],'expected_revision':scenario['revision']})
    assert error.value.status==422
    with planning.connect() as c:
        c.execute("INSERT INTO planning_mtg.sector_selection(area,production_order_no,reference,decision,actor) VALUES('cantoneiras','OF999','*','selected','test')")
    info=service.operations()
    assert not info['operations'] and info['selection_summary']['pending'][0]['of']=='OF999'
    with planning.connect() as c:
        c.execute("INSERT INTO planning_mtg.sector_selection(area,production_order_no,reference,decision,actor) VALUES('cantoneiras','OF100','*','selected','test'),('cantoneiras','OF100','PART','selected','test')")
        c.execute("UPDATE planning_mtg.sector_selection SET decision='excluded',reason='Exceção explícita' WHERE reference='PART'")
    assert not service.operations()['operations']


def test_current_preparation_preserves_following_machine_and_changed_technical_identity():
    from app.sector import scope
    main=row(recurso_atual='PEDDI6')
    following=row(operacao_id='next',ocorrencia=2,fase='complementar',operacao_codigo='CPIS:111',recurso_atual='SACA_BOCADOS')
    record={'area':'cantoneiras','row_key':'macro:line','values_json':
        {'of':'OF100','component_ref':'PART','profile':'L80X80X8','length_mm':1000,'quantity_required':10,
         'grade':'S355','operation':'112','machine':'XP T6'},'detail':{}}
    rows,unmatched=scope.research_rows([main,following],[record])
    assert not unmatched and len(rows)==2
    assert rows[0]['current_planning']['machine']=='XP T6'
    assert 'machine' not in rows[1]['current_planning']
    record['values_json']['grade']=''
    assert len(scope.research_rows([main,following],[record])[0])==2
    record['values_json']['grade']='S275'
    assert scope.research_rows([main,following],[record])==([],[record])
    record['values_json'].update(grade='S355',operation='119')
    assert scope.research_rows([main,following],[record])==([],[record])


def test_portfolio_and_gantt_share_balances_across_import_aliases(integrated_db):
    from app.raw import projection
    from app.sector import portfolio
    values={'of':'OF100','component_ref':'PART','profile':'L80X80X8','grade':'','quantity_required':10,
        'length_mm':1000,'operation':'112','status':'Em Aberto','planning_active':True,'machine':'PEDDI6','planning_remaining':None}
    detail={'key':'macro:reimported-line','values':values,'area':'cantoneiras','selection_aliases':['macro:line']}
    with planning.connect() as c:
        projection.publish(c,'planning:cantoneiras','alias-balance', [detail],{})
    portfolio._cache.clear()
    line=portfolio.load('cantoneiras')['lines'][0]
    op=service.operations()['operations'][0]
    assert line['pieces']==op['planning_remaining']==10
    assert line['balance_origin']==op['balance_origin']=='Excel provisório'
    detail['calculation']={'production_sources':[{'operation':'112','remaining':None,'origin':'MES parcial',
        'records':[{'id':'event'}],'coverage_reasons':['Cobertura incompleta.']}]}
    with planning.connect() as c:
        projection.publish(c,'planning:cantoneiras','alias-incomplete-evidence',[detail],{})
    portfolio._cache.clear()
    line=portfolio.load('cantoneiras')['lines'][0];op=service.operations()['operations'][0]
    assert line['pieces'] is None and op['planning_remaining'] is None
    assert line['balance_origin']==op['balance_origin']=='MES parcial'


def test_production_core_metadata_does_not_keep_planning_pending_forever(integrated_db):
    from app.raw import projection
    with planning.connect() as c:
        projection.publish(c,'production:cantoneiras','inherited-core-flag',[],{'aggregates_pending':True})
        assert integrated.references(c)['sources_pending'] is False
        projection.publish(c,'planning:cantoneiras','actual-planning-pending',[],{'aggregates_pending':True})
        assert integrated.references(c)['sources_pending'] is True


def test_current_material_scope_applies_its_confirmed_machine_rate(integrated_db):
    from app.raw import objects,projection
    rid=research.resource_id('XPT6')
    with planning.connect() as c:
        resource=objects.get(rid,c)
        objects.save({'request_id':str(uuid.uuid4()),'id':rid,'expected_revision':resource['revision'],
            'name':resource['name'],'area':'cantoneiras','definition':{**resource['definition'],'confirmed':True}},'resource',conn=c)
        objects.save({'request_id':str(uuid.uuid4()),'name':'Taxa confirmada','area':'cantoneiras','definition':
            {'resource_id':rid,'area':'cantoneiras','operation':'112','material_type':'Cantoneira','method':'metres_hour',
             'value':10,'setup_minutes':0,'valid_from':'2026-09-01','confirmed':True}},'rate',conn=c)
        projection.publish(c,'planning:cantoneiras','material-scope',[{'key':'macro:line','values':
            {'of':'OF100','component_ref':'PART','profile':'L80X80X8','quantity_required':10,'length_mm':1000,
             'status':'Em Aberto','operation':'112','planning_active':True,'machine':'PEDDI6','material_type':'Cantoneira'},'area':'cantoneiras'}],{})
    detail=service.options(service.operations()['operations'][0]['key'])['operation']
    candidate=next(c for c in detail['candidates'] if c['resource_id']==rid)
    assert detail['technical']['material_type']=='Cantoneira'
    assert candidate['duration']['duration_origin']=='Manual' and candidate['duration']['duration_minutes']==60


def test_new_app_planning_information_does_not_wait_for_a_factory_copy(integrated_db):
    from app.raw import projection
    with planning.connect() as c:
        projection.publish(c,'planning:cantoneiras','new-registered-line',[{'key':'manual:new','values':
            {'of':'OF100','component_ref':'NEW','profile':'L80X80X8','quantity_required':5,'length_mm':1000,'status':'Em Aberto','operation':'112',
             'planning_remaining':5,'machine':'PEDDI6'},'area':'cantoneiras','calculation':{'production_sources':[{'operation':'112','remaining':5,'origin':'Excel provisório'}]}}],{})
    ops=service.operations()['operations']
    assert len(ops)==1 and ops[0]['reference']=='NEW' and ops[0]['quantity_required']==5
    assert ops[0]['assignment']['eligibility']=='conditional'


def test_technical_review_is_versioned_and_idempotent(integrated_db):
    detail=service.options(service.operations()['operations'][0]['key'])
    candidate=next(c for c in detail['operation']['candidates'] if c['resource_code']=='XPT6')
    with planning.connect(readonly=True) as c:
        revision=c.execute('SELECT revision FROM planning_mtg.raw_objects WHERE id=%s',(candidate['resource_id'],)).fetchone()['revision']
    p={'request_id':str(uuid.uuid4()),'key':detail['operation']['key'],'resource_id':candidate['resource_id'],
       'expected_revision':revision,'source_references':detail['source_references'],'reason':'Desenho e três diâmetros confirmados',
       'resolved_conditions':candidate['conditions'],'confirmed':True}
    result=service.confirm_rule(p)
    assert result['revision']==revision+1 and service.confirm_rule(p)==result
    op=service.options(detail['operation']['key'])['operation']
    assert next(c for c in op['candidates'] if c['resource_id']==candidate['resource_id'])['eligibility']=='admissible'


def test_review_can_explicitly_authorize_the_second_code_of_one_machine(integrated_db):
    p=package();p['metadata']['capacities'].append({**p['metadata']['capacities'][0],'id':'alternative119','operacao_codigo':'CPIS:119'})
    with planning.connect() as c:research.publish(c,p)
    detail=service.options(service.operations()['operations'][0]['key'])
    candidate=next(o for o in detail['operation']['candidates'] if o['resource_code']=='PEDDI6' and o['code_change'])
    with planning.connect(readonly=True) as c:
        rev=c.execute('SELECT revision FROM planning_mtg.raw_objects WHERE id=%s',(candidate['resource_id'],)).fetchone()['revision']
    service.confirm_rule({'request_id':str(uuid.uuid4()),'key':detail['operation']['key'],'resource_id':candidate['resource_id'],
        'expected_revision':rev,'source_references':detail['source_references'],'reason':'Alteração da rota documentada',
        'resolved_conditions':['mudanca_112_para_119_requer_decisao'],'confirmed':True})
    revised=service.options(detail['operation']['key'])['operation']
    assert 'mudanca_112_para_119_requer_decisao' not in next(o for o in revised['candidates'] if o['resource_code']=='PEDDI6' and o['code_change'])['conditions']


def test_last_good_survives_failure_and_sources_changed_during_calculation(integrated_db,monkeypatch):
    refs=service.operations()['source_references']
    def fail():
        raise RuntimeError('source unavailable')
    monkeypatch.setattr(research,'connect',fail)
    with pytest.raises(RuntimeError):research.refresh()
    assert service.operations()['source_status']['last_error']
    p=package();p['rows'][0]['saldo_documental']=8
    with planning.connect() as c:
        research.publish(c,p)
    with planning.connect(readonly=True) as c,pytest.raises(planning.PlanningError,match='mudaram'):
        inputs.capture(c,{},MONDAY.isoformat(),expected_references=refs)


def test_started_work_rejects_a_different_machine(integrated_db):
    p=package();p['rows'][0].update(recurso_atual='PEDDI6',contador_excel=1,maquina_original='Peddi6')
    with planning.connect() as c:research.publish(c,p)
    op=service.operations()['operations'][0]
    assert op['started'] and op['assignment']['resource_id']==research.resource_id('PEDDI6')
    with pytest.raises(planning.PlanningError,match='iniciada'):
        service.save({'request_id':str(uuid.uuid4()),'name':'Invalid','definition':{'areas':['cantoneiras'],'machine_overrides':{op['key']:{'resource_id':research.resource_id('XPT6'),'reason':'Troca'}}}})


def test_shared_operators_and_multiple_predecessors_use_wall_time():
    ops=[operation(str(i),120,machine=str(i)) for i in range(3)]
    last=operation('last',30,machine='last');last['predecessor_keys']=['0','1','2'];ops.append(last)
    snap=synthetic(ops,resources=('0','1','2','last','operators'))
    snap['resources']['operators']['capacity']=2
    for op in ops[:3]:op['options'][0]['shared_demands']={'operators':1}
    first=baseline.build(snap)
    assert max(first['bars'][str(i)]['end_minute'] for i in range(3))==240
    assert first['bars']['last']['start_minute']>=240
    best,_=solver.optimize(snap,first,seconds=2)
    assert validation.validate(snap,best)['valid'] and best['score']<=first['score']
    bad=copy.deepcopy(first)
    for i in range(3):bad['bars'][str(i)].update(start_minute=0,end_minute=120,segments=[(0,120)])
    assert not validation.validate(snap,bad)['valid']


def test_temporal_evaluation_never_trains_on_a_held_out_order():
    cohorts=[{'key':'train','orders':['OF1'],'start_date':'2026-08-01','end_date':'2026-08-02','hours':2,'volume':20},
        {'key':'leak','orders':['OF2'],'start_date':'2026-08-02','end_date':'2026-08-03','hours':1,'volume':100},
        {'key':'test','orders':['OF2'],'start_date':'2026-09-02','end_date':'2026-09-03','hours':4,'volume':20}]
    evaluation=insights.temporal_evaluation(cohorts,'2026-08-31')
    assert evaluation['training_cohorts']==1 and evaluation['evaluated']==1
    assert evaluation['mae_hours']==2


def test_weekly_simulation_keeps_unknowns_and_exclusions():
    op=operation('a',60);op.update(assignment={'resource_id':'meba'},source_duration={'hours':1},technical={})
    snap=synthetic([op]);snap['weekly_availability']=[{'resource_id':'meba','year':2026,'week':39,'hours':40,'status':'confirmed'}]
    assert weekly.build(snap)['allocations'][0]['charge']==1
    op['blocking_reasons']=['Trabalho excluído da seleção.']
    assert not weekly.build(snap)['allocations']


def test_cpis_tables_reimport_and_correction_publish_one_coherent_head(integrated_db):
    from app.gantt import cpis_tables
    tables={table:[] for table in cpis_tables.KEYS}
    tables['cpis_ordensfabrico']=[{'id':1,'ficof':'OF1000'}]
    tables['cpis_ordensfabricolin']=[{'id':2,'idpai':1}]
    tables['cpis_ordensfabricolinexp']=[{'id':3,'idpai':2,'codart':'PART','qtd':10,'qtdper':1}]
    tables['cpis_ordensfabricolinope']=[{'id':4,'idpai':3,'codope':'112','posicao':1}]
    tables['cpis_artigos']=[{'codart':'PART','coduniper':'M'}]
    cpis_tables.validate(tables)
    p={'schema':'dados','orders':['OF100'],'references':['PART'],'tables':tables}
    with planning.connect() as c:
        first=cpis_tables.publish(c,p)
        assert cpis_tables.publish(c,p)['version']==first['version']
        proof=cpis_tables.evidence(cpis_tables.load(c),[row(ordem_codigo='OF1000')])['op']
        assert proof['status']=='correspondencia_documental_unica'
        p=copy.deepcopy(p);p['tables']['cpis_ordensfabricolinope'][0]['codope']='119'
        assert cpis_tables.publish(c,p)['version']!=first['version']
    source=package();source['rows'][0]['ordem_codigo']='OF1000'
    from app.raw import projection
    with planning.connect() as c:
        research.publish(c,source)
        projection.publish(c,'planning:cantoneiras','cpis-route-test',[{'key':'macro:line','values':
            {'of':'OF1000','component_ref':'PART','profile':'L80X80X8','quantity_required':10,'length_mm':1000,'status':'Em Aberto','operation':'112','planning_active':True,'machine':'PEDDI6'},'area':'cantoneiras'}],{})
        c.execute("UPDATE planning_mtg.sector_selection SET production_order_no='OF1000'")
    assert 'Rota CPIS atual difere da informação de planeamento.' in service.operations()['operations'][0]['blocking_reasons']
    tables['cpis_ordensfabricolinexp'][0]['idpai']=999
    with pytest.raises(planning.PlanningError,match='incoerente'):cpis_tables.validate(tables)


def test_browser_selection_manual_automatic(integrated_db,monkeypatch,tmp_path):
    import os,socket,subprocess,time,urllib.request
    root=Path(__file__).parents[1]
    with planning.connect() as c:
        c.execute('DELETE FROM planning_mtg.sector_selection')
        from app.raw import projection  # Planear exige máquina (regra de 02/10/2026): a linha do ensaio tem PEDDI6
        projection.publish(c,'planning:cantoneiras','selected-fixture-machine',[{'key':'macro:line','values':
            {'of':'OF100','component_ref':'PART','profile':'L80X80X8','quantity_required':10,'length_mm':1000,'status':'Em Aberto',
             'operation':'112','planning_active':True,'machine':'PEDDI6'},'area':'cantoneiras'}],{})
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    env={**os.environ,'MES_PG_DSN':os.environ['MES_PG_DSN'],'MES_PLANNING_V2_ENABLED':'1','MES_PLANNING_SELECTION_ENABLED':'1',
        'MES_DATA_DIR':str(tmp_path),'MES_DOSSIER_WORKER_DISABLED':'1','MES_RAW_WORKSPACE_ENABLED':'1','MES_PLANNING_GANTT_ENABLED':'1',
        'PLANNING_CHECK_BASE':f'http://127.0.0.1:{port}','GANTT_EVIDENCE':str(tmp_path)}
    with (tmp_path/'integrated-web.log').open('w+') as log:
        server=subprocess.Popen([str(root/'.venv/bin/python'),'-m','uvicorn','app.web.planning_app:app','--host','127.0.0.1','--port',str(port)],cwd=root,env=env,stdout=log,stderr=log)
        try:
            for _ in range(100):
                try:urllib.request.urlopen(env['PLANNING_CHECK_BASE']+'/planeamento/gantt',timeout=.3);break
                except Exception:time.sleep(.1)
            else:pytest.fail('Servidor de ensaio não iniciou.')
            result=subprocess.run(['node','tests/integrated_gantt_browser.cjs'],cwd=root,env=env,capture_output=True,text=True,timeout=90)
            log.flush();log.seek(0)
            assert result.returncode==0,result.stdout+result.stderr+'\n'+log.read()
        finally:server.terminate();server.wait(timeout=10)


def test_choose_keeps_the_planner_machine_even_out_of_the_capacity_sheet():
    candidates = [{'resource_id': 'a', 'eligibility': 'excluded', 'conditions': []},
                  {'resource_id': 'b', 'eligibility': 'admissible', 'conditions': []}]
    selected, reason = machines.choose(candidates, 'a')
    assert selected['resource_id'] == 'a' and reason.startswith('Mantém')
    assert machines.choose(candidates, None)[0]['resource_id'] == 'b'


def test_planner_machine_out_of_range_is_kept_and_placed_with_calendar_and_rate(integrated_db):
    """L200X200X24 na XPT6 (ficha até L200X200X20): fica na XPT6 e, com calendário e taxa, entra na proposta."""
    from app.raw import objects, projection
    from tests.test_planning_gantt import calendar
    p = package(); p['rows'][0].update(perfil='L200X200X24')
    rid = research.resource_id('XPT6')
    with planning.connect() as c:
        research.publish(c, p)
        projection.publish(c, 'planning:cantoneiras', 'out-of-range', [{'key': 'macro:line', 'values':
            {'of': 'OF100', 'component_ref': 'PART', 'profile': 'L200X200X24', 'quantity_required': 10, 'length_mm': 1000,
             'status': 'Em Aberto', 'operation': '112', 'planning_active': True, 'machine': 'XPT6'}, 'area': 'cantoneiras'}], {})
    op = service.operations()['operations'][0]
    assert op['assignment']['resource_id'] == rid and op['assignment']['basis'] == 'escolha_do_planeador'
    assert 'Compatibilidade técnica por confirmar.' not in op['blocking_reasons']
    with planning.connect() as c:
        resource = objects.get(rid, c)
        objects.save({'request_id': str(uuid.uuid4()), 'id': rid, 'expected_revision': resource['revision'], 'name': resource['name'],
                      'area': 'cantoneiras', 'definition': {**resource['definition'], 'confirmed': True}}, 'resource', conn=c)
        objects.save({'request_id': str(uuid.uuid4()), 'name': 'Taxa XPT6', 'area': 'cantoneiras', 'definition':
            {'resource_id': rid, 'area': 'cantoneiras', 'operation': '112', 'method': 'metres_hour', 'value': 10,
             'setup_minutes': 0, 'valid_from': '2026-09-01', 'confirmed': True}}, 'rate', conn=c)
        objects.save({'request_id': str(uuid.uuid4()), 'name': 'XPT6 · 2026-W39', 'area': 'cantoneiras',
                      'definition': {**calendar(), 'resource_id': rid}}, 'calendar', conn=c)
    with planning.connect(readonly=True) as c:
        snapshot = integrated.capture(c, {'areas': ['cantoneiras']}, MONDAY.isoformat())
    op = snapshot['operations'][0]
    assert op['state'] == 'ready', op['blocking_reasons']
    assert op['options'] and all(o['eligibility'] == 'admissible' and o['eligibility_basis'] == 'escolha_do_planeador' for o in op['options'])
    assert baseline.build(snapshot)['bars'][op['key']]['resource_id'] == rid


def test_member_planned_line_stays_in_the_gantt_after_a_new_import(integrated_db):
    from app.raw import projection
    with planning.connect() as c:
        c.execute('DELETE FROM planning_mtg.sector_selection')
        c.execute("INSERT INTO planning_mtg.sector_member_selection (area, member_key, production_order_no, reference, decision, actor, request_id) "
                  "VALUES ('cantoneiras', 'macro:line', 'OF100', 'PART', 'selected', 'teste', gen_random_uuid())")
        projection.publish(c, 'planning:cantoneiras', 'new-import', [{'key': 'macro:reimported', 'area': 'cantoneiras',
            'selection_aliases': ['macro:line'], 'values': {'of': 'OF100', 'component_ref': 'PART', 'profile': 'L80X80X8',
            'quantity_required': 10, 'length_mm': 1000, 'status': 'Em Aberto', 'operation': '112', 'planning_active': True,
            'machine': 'PEDDI6'}}], {})
    info = service.operations()
    assert len(info['operations']) == 1 and info['selection_summary']['selected_orders'] == 1
    with planning.connect() as c:
        c.execute("DELETE FROM planning_mtg.sector_member_selection")


def test_selected_lines_without_machine_stay_out_of_the_gantt(integrated_db):
    from app.raw import projection
    with planning.connect() as c:
        projection.publish(c, 'planning:cantoneiras', 'no-machine', [{'key': 'macro:line', 'area': 'cantoneiras', 'values':
            {'of': 'OF100', 'component_ref': 'PART', 'profile': 'L80X80X8', 'quantity_required': 10, 'length_mm': 1000,
             'status': 'Em Aberto', 'operation': '112', 'planning_active': True, 'machine': 'Por definir'}}], {})
    info = service.operations()
    assert not info['operations']
    assert any('sem máquina' in p['reason'] for p in info['selection_summary']['pending'])
