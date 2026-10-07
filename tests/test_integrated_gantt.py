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


def test_version_ignores_reading_day_but_not_content():
    # Auditoria 06/10 (A14-F2): a mudança de dia sozinha não cria versão nova.
    a=package();a['metadata']['as_of']='2026-09-30'
    b=copy.deepcopy(a);b['metadata']['as_of']='2026-10-06'
    assert research.version_digest(a)==research.version_digest(b)
    b['metadata']['events']=[{'id':1,'quantidade_reportada':5,'data_producao':'2026-10-05'}]
    assert research.version_digest(a)!=research.version_digest(b)


def test_new_reading_day_keeps_the_published_version(integrated_db):
    with planning.connect() as c:
        p=package();p['metadata']['as_of']='2026-10-05'
        first=research.publish(c,p)
        p['metadata']['as_of']='2026-10-06'
        again=research.publish(c,p)
        assert again['version']==first['version'] and not again['changed']


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
    # Desde 07/10/2026 a rota do Excel com a máquina do Excel (PEDDI6) conta como validada: fica como aviso;
    # bloqueia o que falta mesmo (duração e calendário).
    assert 'Operação ou aplicabilidade da rota por confirmar.' in op['warnings']
    assert 'Operação ou aplicabilidade da rota por confirmar.' not in op['blocking_reasons']
    assert 'Duração admissível por confirmar.' in op['blocking_reasons']


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
    # A pesquisa (retrato de 29/09) diz saldo 10; o Excel atual diz 7. Desde 08/10 (F05) vale o da app nas duas páginas.
    values={'of':'OF100','component_ref':'PART','profile':'L80X80X8','grade':'','quantity_required':10,
        'length_mm':1000,'operation':'112','status':'Em Aberto','planning_active':True,'machine':'PEDDI6',
        'planning_remaining':7,'planning_balance_origin':'Excel provisório'}
    detail={'key':'macro:reimported-line','values':values,'area':'cantoneiras','selection_aliases':['macro:line'],
        'calculation':{'production_sources':[{'operation':'112','remaining':7,'value':3,'origin':'Excel provisório','records':[]}]}}
    with planning.connect() as c:
        projection.publish(c,'planning:cantoneiras','alias-balance', [detail],{})
    portfolio._cache.clear()
    line=portfolio.load('cantoneiras')['lines'][0]
    op=service.operations()['operations'][0]
    assert line['pieces']==op['planning_remaining']==7
    assert line['balance_origin']==op['balance_origin']=='Excel provisório'
    values.update(planning_remaining=None,planning_balance_origin='MES parcial')
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


def test_old_technical_review_requests_are_still_accepted_without_reason_checkbox_or_same_sources(integrated_db):
    # A regra técnica saiu do ecrã a 07/10/2026; o pedido antigo continua aceite sem motivo, caixa nem fontes iguais,
    # mas uma caixa explicitamente por marcar (confirmed: false) nunca é gravada como confirmada.
    from app.sector.decisions import NO_REASON
    detail=service.options(service.operations()['operations'][0]['key'])
    candidate=next(c for c in detail['operation']['candidates'] if c['resource_code']=='XPT6')
    with planning.connect(readonly=True) as c:
        revision=c.execute('SELECT revision FROM planning_mtg.raw_objects WHERE id=%s',(candidate['resource_id'],)).fetchone()['revision']
    base={'key':detail['operation']['key'],'resource_id':candidate['resource_id'],'expected_revision':revision,
          'source_references':{'antigas':True},'resolved_conditions':candidate['conditions']}
    with pytest.raises(planning.PlanningError,match='Confirma') as refused:
        service.confirm_rule({**base,'request_id':str(uuid.uuid4()),'confirmed':False})
    assert refused.value.status==422
    result=service.confirm_rule({**base,'request_id':str(uuid.uuid4())})
    assert result['revision']==revision+1
    with planning.connect(readonly=True) as c:
        rules=c.execute('SELECT definition FROM planning_mtg.raw_objects WHERE id=%s',(candidate['resource_id'],)).fetchone()['definition']['technical_rules']
    assert rules[-1]['reason']==NO_REASON and rules[-1]['confirmed'] is True


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
    # Com a máquina do Excel (PEDDI6) a rota do Excel conta como validada (07/10/2026): a diferença fica como aviso.
    op=service.operations()['operations'][0]
    assert 'Rota CPIS atual difere da informação de planeamento.' in op['warnings']
    assert 'Rota CPIS atual difere da informação de planeamento.' not in op['blocking_reasons']
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


def _ready_machine(c, code, operation):
    """Máquina confirmada, com taxa e calendário da semana do ensaio (para só sobrarem as razões em estudo)."""
    from app.raw import objects
    from tests.test_planning_gantt import calendar
    rid = research.resource_id(code)
    resource = objects.get(rid, c)
    objects.save({'request_id': str(uuid.uuid4()), 'id': rid, 'expected_revision': resource['revision'], 'name': resource['name'],
                  'area': 'cantoneiras', 'definition': {**resource['definition'], 'confirmed': True}}, 'resource', conn=c)
    objects.save({'request_id': str(uuid.uuid4()), 'name': f'Taxa {code}', 'area': 'cantoneiras', 'definition':
        {'resource_id': rid, 'area': 'cantoneiras', 'operation': operation, 'method': 'metres_hour', 'value': 10,
         'setup_minutes': 0, 'valid_from': '2026-09-01', 'confirmed': True}}, 'rate', conn=c)
    objects.save({'request_id': str(uuid.uuid4()), 'name': f'{code} · 2026-W39', 'area': 'cantoneiras',
                  'definition': {**calendar(), 'resource_id': rid}}, 'calendar', conn=c)
    return rid


def test_excel_machine_and_route_count_as_validated_route_compatibility_and_sequence(integrated_db):
    """Plano de 07/10/2026: com a máquina do planeador/Excel, rota, compatibilidade e sequência não bloqueiam."""
    from app.raw import projection
    p = package()
    p['metadata']['resources'].append({'codigo': 'SACA', 'designacao': 'SACA', 'setor': 'MTG3', 'tipo': 'equipamento',
                                       'quantidade_operadores': None})
    p['rows'].append(row(operacao_id='op2', ocorrencia=2, fase='complementar', operacao_codigo='CPIS:111', codigo_original='111',
                         recurso_atual='SACA', maquina_original='SACA'))
    p['metadata']['dependencies'] = [{'predecessora': 'op', 'sucessora': 'op2', 'validada': False}]
    with planning.connect() as c:
        research.publish(c, p)
        projection.publish(c, 'planning:cantoneiras', 'validated-route', [{'key': 'macro:line', 'values':
            {'of': 'OF100', 'component_ref': 'PART', 'profile': 'L80X80X8', 'quantity_required': 10, 'length_mm': 1000,
             'status': 'Em Aberto', 'operation': '112', 'planning_active': True, 'machine': 'XPT6'}, 'area': 'cantoneiras'}], {})
        main, following = _ready_machine(c, 'XPT6', '112'), _ready_machine(c, 'SACA', '111')
    with planning.connect(readonly=True) as c:
        snapshot = integrated.capture(c, {'areas': ['cantoneiras']}, MONDAY.isoformat())
    ops = {op['operation']: op for op in snapshot['operations']}
    first, second = ops['CPIS:112'], ops['CPIS:111']
    assert first['assignment']['resource_id'] == main and first['assignment']['eligibility'] == 'conditional'
    assert first['state'] == 'ready', first['blocking_reasons']
    # A 2.ª operação fica na máquina do Excel (fora da ficha) e a sequência não validada deixa de bloquear.
    assert second['assignment']['resource_id'] == following and second['assignment']['basis'] == 'escolha_do_planeador'
    assert second['state'] == 'ready', second['blocking_reasons']
    assert 'Sequência operacional por validar.' in second['warnings']
    assert baseline.build(snapshot)['bars'][second['key']]['resource_id'] == following


def test_automatic_machine_still_waits_for_compatibility_and_sequence():
    """Sem máquina escolhida por uma pessoa, a escolha automática condicional continua por confirmar."""
    candidates = [{'resource_id': 'a', 'eligibility': 'conditional', 'conditions': ['revisao_tecnica_por_validar']}]
    selected, _ = machines.choose(candidates, None)
    assert selected['resource_id'] == 'a' and selected['eligibility'] == 'conditional'
    assert integrated.chosen_by_planner(selected, None, None, None) is False
    assert integrated.chosen_by_planner(selected, 'a', None, None) is True  # Carteira, Tabela/Excel ou conjunto
    assert integrated.chosen_by_planner(selected, None, 'a', None) is True  # escolha manual no Gantt
    assert integrated.chosen_by_planner(selected, 'b', None, {'mode': 'prefer', 'resource_id': 'a'}) is True
    assert integrated.chosen_by_planner(selected, 'a', 'b', None) is False  # a escolha manual ganhou a outra máquina


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


def _research_row(**changes):
    # Linha da pesquisa (retrato de 29/09), como a OF256804 ZG-4001 da auditoria de 06/10.
    return {'setor':'MTG2','fase':'principal','operacao_id':'op1','item_id':'i1','linha_origem':'snapA:plan:748',
            'ordem_codigo':'OF256804','referencia_original':'ZG-4001','perfil':'TUBO 40','comprimento_mm':1000,
            'quantidade_base':8,'saldo_documental':8,'saldo_confirmado':None,'estado_quantidade':'coerente',
            'operacao_codigo':'LOCAL:PRINCIPAL','codigo_original':'corte','ocorrencia':1,'snapshot_id':'snapA',
            'raw':{'Ser.':None,'Qtd em Falta':8},**changes}


def _raw_row(remaining, raw):
    values={'of':'OF256804','component_ref':'ZG-4001','profile':'TUBO 40','length_mm':1000,'quantity_required':8,
            'remaining':remaining,'planning_remaining':remaining,'stock_length_mm':6000,'section_unit':100,'weight_unit':2}
    return {'key':'macro:snapB:plan:748','selection_aliases':['macro:snapA:plan:748'],'values':values,'raw':raw,
            'calculation':{'production_sources':[{'operation':'corte','remaining':remaining,'value':None if remaining is None else 8-remaining,
                                                  'origin':'Excel provisório' if remaining is not None else 'Indisponível','records':[]}]}}


def test_newer_excel_counter_keeps_the_raw_balance_over_the_research_snapshot(monkeypatch):
    # A6-1/A4-04: o Excel de 02/10 tem Ser.=7 (falta 1); a pesquisa de 29/09 ainda dizia falta 8.
    monkeypatch.setattr(research,'enabled',lambda:True)
    monkeypatch.setattr(research,'load',lambda c:{'rows':[_research_row()],'head':{'version_id':'v'}})
    row=_raw_row(1,{'Ser.':7,'Qtd em Falta':1})
    research.overlay_rows(None,'perfis',[row])
    assert row['values']['remaining']==1 and row['values']['planning_remaining']==1
    assert not any(s.get('v2_evidence') for s in row['calculation']['production_sources'])


def test_research_never_gives_the_main_balance_but_keeps_the_following_operations(monkeypatch):
    # F05 (08/10): a v2 está parada a 29/09; a operação principal fica com o saldo da app, mesmo desconhecido
    # e com os contadores iguais (antes a pesquisa enchia-o, A5-F1). A operação seguinte continua a vir da v2.
    following=_research_row(fase='complementar',operacao_id='op2',ocorrencia=2,operacao_codigo='LOCAL:ABOCARDAR',
                            codigo_original='abocardar',saldo_documental=5)
    monkeypatch.setattr(research,'enabled',lambda:True)
    monkeypatch.setattr(research,'load',lambda c:{'rows':[_research_row(),following],'head':{'version_id':'v'}})
    row=_raw_row(None,{'Ser.':None,'Qtd em Falta':8})
    before=copy.deepcopy(row['values'])
    research.overlay_rows(None,'perfis',[row])
    assert row['values']==before and row['values']['remaining'] is None
    assert not any(s.get('v2_evidence') for s in row['calculation']['production_sources'])
    assert row['calculation']['integrated_operations']==[
        {'operation':'LOCAL:ABOCARDAR','occurrence':2,'remaining':5,'origin':'Excel provisório'}]


def test_research_does_not_touch_closed_lines(monkeypatch):
    # F04 (08/10): 307 linhas fechadas MTG3 ficavam com saldo 0 e saldo a planear = QTD, e mudavam a cada recálculo.
    monkeypatch.setattr(research,'enabled',lambda:True)
    monkeypatch.setattr(research,'load',lambda c:pytest.fail('linhas fechadas não precisam da pesquisa'))
    row=_raw_row(0,{'Ser.':8,'Qtd em Falta':0,'Fechado':'X'})
    row['values']['planning_active']=False
    before=copy.deepcopy(row)
    research.overlay_rows(None,'perfis',[row])
    assert row==before
    # Sem a marca gravada vale a regra de fecho (Fechado = X na macro).
    del row['values']['planning_active']
    research.overlay_rows(None,'perfis',[row])
    assert 'integrated_operations' not in row['calculation']


def test_excel_counters_without_the_remaining_column_are_unknown():
    # F04 (08/10): a vista raw_capacity_contents não guarda «Maq.» nem «Qtd falta»; antes isto dava False.
    assert research.excel_counters_changed('cantoneiras',{'Maq.':0,'Qtd falta':10},{'Maq.':10}) is None
    assert research.excel_counters_changed('cantoneiras',{'Qtd falta':10},{'Maq.':0,'Qtd falta':10}) is None
    assert research.excel_counters_changed('cantoneiras',{'Maq.':0,'Qtd falta':10},{'Maq.':'0','Qtd falta':'10'}) is False
    assert research.excel_counters_changed('perfis',{'Ser.':None,'Qtd em Falta':8},{'Ser.':7,'Qtd em Falta':1}) is True


def test_gantt_and_load_use_the_application_main_balance(monkeypatch):
    from app.raw import query
    monkeypatch.setattr(query,'generation',lambda c,area:{})
    monkeypatch.setattr(query,'source',lambda g:('',[]))
    raw=_raw_row(1,{'Ser.':7,'Qtd em Falta':1})
    record={'area':'perfis','row_key':raw['key'],'values_json':raw['values'],
            'detail':{'selection_aliases':raw['selection_aliases'],'raw':raw['raw'],'calculation':raw['calculation']}}
    r={**_research_row(),'matched_application_key':raw['key']}
    balances=research.application_balances(None,[r],records=[record])
    b=integrated.balance({**r,**balances['op1']})
    assert b['planning_remaining']==1 and b['balance_origin']=='Excel provisório' and b['balance_provisional']
    # F05 (08/10): sem produção posterior no Excel, o saldo continua a ser o da app (antes voltava o da v2).
    record['detail']['raw']={'Ser.':None,'Qtd em Falta':8}
    assert integrated.balance({**r,**research.application_balances(None,[r],records=[record])['op1']})['planning_remaining']==1
    # Saldo da app desconhecido fica desconhecido, como na Carteira; a coerência da v2 já não o anula.
    unknown=_raw_row(None,{'Ser.':None,'Qtd em Falta':8})
    record.update(values_json=unknown['values'],detail={**record['detail'],'calculation':unknown['calculation']})
    assert integrated.balance({**r,**research.application_balances(None,[r],records=[record])['op1']})['planning_remaining'] is None
    record.update(values_json=raw['values'],detail={**record['detail'],'calculation':raw['calculation']})
    assert integrated.balance({**r,'estado_quantidade':'divergente',**research.application_balances(None,[r],records=[record])['op1']})['planning_remaining']==1
    # Linha sem cálculo publicado (sem saldo da app): fica a pesquisa.
    bare={**record,'values_json':{k:v for k,v in raw['values'].items() if k not in ('remaining','planning_remaining')},
          'detail':{**record['detail'],'calculation':{}}}
    assert research.application_balances(None,[r],records=[bare])=={}


def test_application_only_line_keeps_the_portfolio_provisional_balance():
    # A8-1/A7-5: o detalhe reduzido das ocorrências não traz 'original'; o saldo vem da projeção.
    from app.sector import scope
    record={'area':'perfis','row_key':'macro:snapB:plan:9','values_json':{'of':'OF1','component_ref':'R','quantity_required':10,
            'remaining':None,'planning_remaining':10,'planning_balance_origin':'Saldo da macro provisório · Qtd em Falta','abocardar':'-'},
            'detail':{'calculation':{'production_sources':[{'operation':'corte','remaining':None,'records':[]}]}}}
    rows,_=scope.local_rows([record],{})
    b=integrated.balance(rows[0])
    assert b['planning_remaining']==10 and b['balance_origin']=='Saldo da macro provisório · Qtd em Falta'


def test_gantt_uses_the_current_picking_sheet_on_research_matched_perfis_lines(integrated_db):
    # Auditoria 06/10 (A9-1): a pesquisa de 29/09 não tem semana; a folha Picking atual diz W39.
    # O Gantt deve dar o mesmo prazo da Carteira (Picking, 21/09) e não a Data Corte (09/10).
    mtg2=row(setor='MTG2',ordem_codigo='OF200',referencia_original='CA1',item_id='item2',operacao_id='op2',
        linha_origem='pline',operacao_codigo='LOCAL:PRINCIPAL',codigo_original='corte',perfil='HEA200',
        semana_picking=None,ano_picking=None,data_corte_prevista='2026-10-09')
    pkg=package(); pkg['rows'].append(mtg2)
    values={'of':'OF200','component_ref':'CA1','profile':'HEA200','quantity_required':10,'length_mm':1000,
        'status':'Em Aberto','planning_active':True,'machine':'PEDDI6','cut_date':'2026-10-09',
        'picking_week':39,'picking_year':None,'abocardar':'-'}
    with planning.connect() as c:
        research.publish(c,pkg)
        from app.raw import projection
        projection.publish(c,'planning:perfis','picking-sheet',[{'key':'macro:pline','values':values,'area':'perfis'}],{})
        c.execute("INSERT INTO planning_mtg.sector_selection(area,production_order_no,reference,decision,actor) VALUES('perfis','OF200','*','selected','test')")
    research._cache.clear()
    op=next(o for o in service.operations()['operations'] if o['of']=='OF200')
    assert op['priority']['priority_field']=='picking'
    assert op['priority']['priority_day']=='2026-09-21'


def test_gantt_uses_the_application_section_or_derives_it_from_the_total():
    # Auditoria 06/10 (GT-01, A7-4): a pesquisa de 29/09 não tem a área unitária; a Carga usa a da aplicação.
    mtg2=row(setor='MTG2',operacao_codigo='LOCAL:PRINCIPAL',raw={'Área de Seção de Corte [mm2]':261380.5},quantidade_base=52)
    assert integrated.section_unit({**mtg2,'section_unit':5026.55})==5026.55
    assert integrated.section_unit(mtg2)==pytest.approx(5026.55,abs=0.01)
    assert integrated.section_unit({**mtg2,'raw':{'Área de Seção de Corte Unit. [mm2]':400}})==400
    # Linha só da aplicação sem área (peça alterada): continua por confirmar.
    assert integrated.section_unit({**mtg2,'application_row_key':'macro:x','section_unit':None}) is None
    rates={('VANGUARD','LOCAL:PRINCIPAL'):[{'method':'area_hour','value':10000,'setup_minutes':0}]}
    option={'resource_code':'VANGUARD','proposed_code':'LOCAL:PRINCIPAL','eligibility':'admissible'}
    found=integrated._duration(mtg2,option,{'id':'vg','confirmed':False},[],rates,MONDAY.isoformat())
    assert found and found['duration_hours']==pytest.approx(10*5026.55/10000,abs=0.01)


def test_application_inputs_bring_the_published_section_and_estimate_of_the_line():
    record={'row_key':'macro:a','values_json':{'section_unit':520.2},'detail':{'calculation':{'operation_estimates':[
        {'operation':'corte','machine':'Serrote Fita Thomas IS639 Pav.1','source':'Excel provisório','factor':3,
         'rate':{'method':'area_hour','value':55434}},{'operation':'abocardar','machine':None,'source':None}]}}}
    r=integrated._application_inputs(row(setor='MTG2',operacao_codigo='LOCAL:PRINCIPAL',matched_application_key='macro:a'),
        record,{('perfis','Serrote Fita Thomas IS639 Pav.1'):'THOMAS'})
    assert r['section_unit']==520.2 and r['documentary_rate']['operation']=='corte'
    assert r['documentary_rate_resource']=='THOMAS'


def test_gantt_uses_the_published_excel_rate_only_on_the_machine_of_that_estimate():
    # Auditoria 06/10 (GT-05): a mesma taxa do Excel da Carga, sem o ×3 da Thomas e nunca noutra máquina.
    estimate={'operation':'112','machine':'Peddi 6','source':'Excel provisório','factor':1,'rate':{'method':'metres_hour','value':120,'setup_minutes':0}}
    r=row(recurso_atual='PEDDI6',documentary_rate=estimate,documentary_rate_resource='PEDDI6',perfil='L250X250X24')
    templates={('XPT6','CPIS:112'):[{'method':'metres_hour','value':70,'setup_minutes':0,'profile':None}]}
    own=integrated._duration(r,{'resource_code':'PEDDI6','proposed_code':'CPIS:112','eligibility':'admissible'},
        {'id':'p6','confirmed':False},[],templates,MONDAY.isoformat())
    assert own['duration_hours']==pytest.approx(10*1/120,abs=0.01)
    other=integrated._duration(r,{'resource_code':'XPT6','proposed_code':'CPIS:112','eligibility':'admissible'},
        {'id':'xp','confirmed':False},[],templates,MONDAY.isoformat())
    assert other['duration_hours']==pytest.approx(10*1/70,abs=0.01)
    # Fator ×3 da Thomas fica fora do Gantt (decisão de 01/10).
    thomas={**estimate,'factor':3,'rate':{'method':'metres_hour','value':360,'setup_minutes':0}}
    assert integrated._documentary({**r,'documentary_rate':thomas},{'resource_code':'PEDDI6','proposed_code':'CPIS:112'},{})[0][0]['value']==120


class _History:
    aliases={('cantoneiras','Peddi 8'):{}}

    def __init__(self, value):
        self.value=value; self.calls=[]

    def rate(self, values, area, operation, when, *, excel=None, as_of=None):
        from app.raw.productivity import select_rate
        self.calls.append({'excel':excel,'as_of':as_of})
        history={'source':'Histórico','method':'metres_hour','unit':'m/h','value':self.value,'window':{}}
        chosen=select_rate(values,area=area,operation=operation,resource_id='p8',manual=[],historical_rate=history,excel=excel,when=when)
        return {**chosen,'history_hash':'h','history':history,'excluded_cohorts':0}


def test_gantt_history_follows_the_same_plausibility_and_window_as_the_load():
    # Auditoria 06/10 (GT-04, C3-F6): o Gantt passa a taxa do Excel à regra H10 e a janela acaba hoje.
    estimate={'operation':'112','machine':'Peddi 8','source':'Excel provisório','factor':1,'rate':{'method':'metres_hour','value':120,'setup_minutes':0}}
    r=row(recurso_atual='PEDDI8',documentary_rate=estimate,documentary_rate_resource='PEDDI8')
    option={'resource_code':'PEDDI8','proposed_code':'CPIS:112','eligibility':'admissible'}
    resource={'id':'p8','confirmed':True,'aliases':[{'area':'cantoneiras','name':'Peddi 8'}]}
    far=_History(20)  # 1/6 do Excel: implausível, fica o Excel
    found=integrated._duration(r,dict(option),resource,[],{},MONDAY.isoformat(),far,rate_day='2026-10-20')
    assert far.calls[0]['excel']['value']==120 and str(far.calls[0]['as_of'])==MONDAY.isoformat()[:10]
    assert found['duration_origin']!='Histórico' and found['duration_hours']==pytest.approx(10/120,abs=0.01)
    assert any('fora do intervalo plausível' in a for a in found['assumptions'])
    near=_History(100)
    assert integrated._duration(r,dict(option),resource,[],{},MONDAY.isoformat(),near)['duration_hours']==pytest.approx(10/100,abs=0.01)


def test_insights_keep_the_machine_and_operation_of_each_historical_evidence():
    # Auditoria 06/10 (GT-08): a evidência guarda a máquina e a operação da taxa.
    snap={'operations':[],'historical_evidence':{'h1':{'unit':'m/h','window':{'end':'2026-10-06','days':90},'cohorts':[],'excluded':[],
        'scope_resource_id':'p8','scope_machine':'Peddi 8','scope_operation':'112'}}}
    observed=insights.build(snap)['observed_productivity'][0]
    assert (observed['resource_id'],observed['machine'],observed['operation'])==('p8','Peddi 8','112')


def test_runtime_manifest_covers_the_modules_that_change_durations():
    # Auditoria 06/10 (GT-07): mudar as horas trabalhadas ou a regra de horas torna o plano obsoleto.
    names={str(p).split('/app/')[-1] for p in service.runtime_paths()}
    assert {'raw/worked_hours.py','raw/capacity.py','raw/productivity.py','sector/priority.py','sector/estimates.py',
            'sector/assignments.py','planning_calculations.py'} <= names
    # Revisão de 07/10: todos os módulos do setor de que o retrato do Gantt depende (máquinas do setor incluídas).
    assert {'sector/members.py','sector/scope.py','sector/decisions.py','sector/machine_choice.py','sector/portfolio.py',
            'sector/occurrences.py'} <= names


def test_local_cantoneiras_line_with_composite_second_operation_gives_one_occurrence_per_operation():
    # Auditoria 06/10 (ORF-2): «111-1034» na 2.ª Oper. são duas operações, como na pesquisa.
    from app.sector import scope
    record={'area':'cantoneiras','row_key':'macro:s:plan:7','values_json':{'of':'OF1','component_ref':'ZG-1','operation':'119',
            'quantity_required':3,'profile':'L60X60X4'},
            'detail':{'calculation':{'production_sources':[{'operation':'111-1034','remaining':2,'records':[{'source':'excel'}],'origin':'Excel'},
                                                           {'operation':'119','remaining':3,'records':[],'origin':'Excel provisório'}]}}}
    rows,deps=scope.local_rows([record],{})
    assert [(r['ocorrencia'],r['operacao_codigo'],r['fase']) for r in rows]==[(1,'CPIS:119','principal'),(2,'CPIS:111','complementar'),(3,'CPIS:1034','complementar')]
    # O saldo é o da operação composta, a única fonte.
    assert [r['saldo_documental'] for r in rows[1:]]==[2,2]
    assert len(deps)==2
    # Na MTG2 não se divide nada.
    record['area']='perfis'
    assert 'CPIS:111-1034' in [r['operacao_codigo'] for r in scope.local_rows([record],{})[0]]


@pytest.mark.parametrize('mark,operations', [(None, ['LOCAL:PRINCIPAL']), ('', ['LOCAL:PRINCIPAL']), ('?', ['LOCAL:PRINCIPAL']),
                                             ('-', ['LOCAL:PRINCIPAL']), ('X', ['LOCAL:PRINCIPAL', 'LOCAL:ABOCARDAR'])])
def test_unknown_abocardar_is_no_abocardar_without_route_review(mark, operations):
    # Plano de 07/10/2026: abocardar desconhecido = «-» (também nos registos antigos); só «X»/«sim» cria a operação.
    from app.planning_calculations import calculate
    from app.sector import scope
    values={'of':'OF1','component_ref':'R','quantity_required':4,'length_mm':1000,'abocardar':mark}
    # O cálculo real (production_sources) ainda traz «abocardar» quando a marca é desconhecida.
    sources=calculate(values,area='perfis')['operations']
    record={'area':'perfis','row_key':'k1','values_json':values,'detail':{'calculation':{'production_sources':sources}}}
    rows,deps=scope.local_rows([record],{})
    assert [r['operacao_codigo'] for r in rows]==operations
    assert not any(r['route_review_required'] for r in rows) and all(d['validada'] for d in deps)
