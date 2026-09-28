from datetime import date
import copy
import uuid
import pytest

from app import planning
from app.raw import productivity as p, projection, query, objects, capacity, capacity_revision
from tests.test_raw_workspace import workspace, database, canonical, registry, postgres16


def event(key, sheet, q, **kw):
    return {'key':key,'sheet_key':sheet,'area':'cantoneiras','operation':'112',
            'date':'2026-09-22','quantity':q,'length_mm':1000,'section_unit':20,
            'material_type':'Cantoneira','profile':'L40','grade':'S235',
            'identity_valid':True,**kw}


def cohort(key,h,**kw):
    return {'key':key,'sheets':[key],'hours':h,'start_date':'2026-09-22','end_date':'2026-09-22','origin':'OCR',**kw}


def historic(events,cohorts,**kw):
    return p.historical(events,cohorts,area='cantoneiras',operation='112',method='metres_hour',
        values={'material_type':'Cantoneira','profile':'L40','grade':'S235'},as_of=date(2026,9,23),**kw)


def test_weighted_matching_cohorts_exclude_both_unknown_numerator_and_denominator():
    result=historic([event('a','a',10),event('b','b',90),event('c','c',1000),event('d','d',None)],
                    [cohort('a',2),cohort('b',8),cohort('c',None),cohort('d',100)])
    assert result['value']==10  # (10+90)/(2+8), not mean(5,11.25), not 1100/10.
    assert result['volume']==100 and result['hours']==10
    assert result['sheet_count']==2 and result['event_count']==2
    assert len(result['excluded'])==2


@pytest.mark.parametrize('change',[
    {'operation':'113'},{'area':'perfis'},{'identity_valid':False},
    {'length_mm':None},{'quantity':-1},{'quantity':1.5},
    {'date':'2026-09-21'},
])
def test_incomplete_or_mixed_sheet_never_uses_partial_volume_with_whole_time(change):
    result=historic([event('good','a',10),event('bad','a',20,**change)], [cohort('a',2)])
    assert result['value'] is None and result['hours']==0 and result['volume']==0
    assert result['excluded'][0]['reasons']


def test_duplicate_events_time_overlaps_and_window():
    e=event('a','a',10)
    assert historic([e,e],[cohort('a',2),cohort('a',2)])['value']==5
    assert historic([e,{**e,'quantity':11}],[cohort('a',2)])['value'] is None
    assert historic([e],[cohort('a',2),cohort('b',3,sheets=['a'])])['value'] is None
    assert historic([e],[cohort('a',2),cohort('a',3)])['value'] is None
    assert historic([e],[cohort('a',2)],days=1)['value'] is None
    assert historic([e],[cohort('a',0)])['value'] is None


def test_history_evidence_is_independent_of_database_event_and_cohort_order():
    import random
    events=[event('z','valid',10),event('a','valid',20),
            event('unknown','incomplete',None),event('wrong','incomplete',10,operation='113'),
            event('duplicate','conflict',4),event('duplicate','conflict',5)]
    cohorts=[cohort('valid',3),cohort('incomplete',2),cohort('conflict',1),
             cohort('conflict',2),cohort('empty',None)]
    expected=historic(events,cohorts)
    assert expected['value']==10 and expected['event_count']==2
    assert len(expected['excluded'])==3
    rng=random.Random(54)
    for _ in range(20):
        rng.shuffle(events);rng.shuffle(cohorts)
        actual=historic(events,cohorts)
        assert actual==expected
        assert p.needs.digest(actual)==p.needs.digest(expected)


def test_mixed_dimensions_use_all_normalized_volume_with_the_corresponding_time():
    result=historic([event('a','s',10),event('b','s',20,profile='L50',length_mm=2000)],[cohort('s',5)])
    assert result['volume']==50 and result['value']==10
    # Counting raw units needs comparable pieces; it cannot reuse mixed geometry.
    result=p.historical([event('a','s',10),event('b','s',20,profile='L50',length_mm=2000)],[cohort('s',5)],
        area='cantoneiras',operation='112',method='units_hour',values=event('target','s',1),as_of=date(2026,9,23))
    assert result['value'] is None


def test_mixed_operations_require_a_complete_explicit_time_allocation():
    events=[event('cut','s',20),event('drill','s',40,operation='113')]
    time=cohort('s',6,origin='Manual',revision=2)
    assert historic(events,[time])['value'] is None
    allocation=[{'area':'cantoneiras','operation':'112','hours':2},
                {'area':'cantoneiras','operation':'113','hours':4}]
    time['definition']={'operation_hours':allocation}
    result=historic(events,[time])
    assert result['value']==10 and result['hours']==2 and result['volume']==20
    assert result['cohorts'][0]['hours_revision']==2
    assert result['cohorts'][0]['allocation']==allocation[0]
    assert historic(events+[event('unknown-op','s',1,operation='114')],[time])['value'] is None


def test_priority_expiry_conflict_and_thomas_factor_only_excel():
    v={'machine':'Serrote Fita Thomas IS639 Pav.1','quantity_required':51}
    manual=[{'id':'m','definition':{'resource_id':'r','area':'perfis','operation':'corte',
        'method':'area_hour','value':20,'confirmed':True,'valid_from':'2026-01-01','valid_until':'2026-09-22'}}]
    args=dict(area='perfis',operation='corte',resource_id='r',manual=manual,
              historical_rate={'value':10,'method':'area_hour'},excel={'value':5,'method':'area_hour'})
    result=p.select_rate(v,when='2026-09-22',**args)
    assert result['source']=='Manual' and result['rate']['value']==20 and result['factor']==1
    result=p.select_rate(v,when='2026-09-23',**args)
    assert result['source']=='Histórico' and result['rate']['value']==10 and result['factor']==1
    result=p.select_rate(v,when='2026-09-23',**{**args,'historical_rate':{'value':None}})
    assert result['source']=='Excel provisório' and result['rate']['value']==15 and result['factor']==3
    assert p.select_rate({**v,'quantity_required':50},when='2026-09-23',**{**args,'historical_rate':{'value':None}})['rate']['value']==5
    result=p.select_rate(v,when='2026-09-22',**{**args,'manual':manual+[{**manual[0],'id':'other'}]})
    assert result['rate'] is None and 'conflito' in result['reason']


def command(**kw):return {'request_id':str(uuid.uuid4()),**kw}


def publish_planning_fixture(conn,area,revision,rows):
    # Capacity publication requires a coherent cut of both areas, even when
    # this arithmetic fixture deliberately has no pieces in the other area.
    for other in planning.AREAS:
        if other!=area and not conn.execute('SELECT 1 FROM planning_mtg.raw_generations WHERE dataset=%s',('planning:'+other,)).fetchone():
            projection.publish(conn,'planning:'+other,'empty-fixture',[],{'core_source_fingerprint':projection.fingerprint(conn,other)})
    return projection.publish(conn,'planning:'+area,revision,rows,{'core_source_fingerprint':projection.fingerprint(conn,area)})


@pytest.mark.parametrize('area,op,method,unit_volume',[('perfis','corte','area_hour',20),('cantoneiras','112','metres_hour',1)])
def test_closed_history_supplies_active_draft_then_manual_overrides_and_expires(workspace,area,op,method,unit_volume):
    import psycopg
    from psycopg.types.json import Jsonb
    from app.raw import worked_hours
    # Independent Excel fallback: 20 mm²/h in Perfis; Cantoneiras has 5 m/h
    # on each source row below. These are reference inputs, not engine output.
    if area=='perfis':
        with psycopg.connect(workspace) as c:
            c.execute("INSERT INTO raw_mtg.other_sheet_rows VALUES ('s1','CapacidadeMáquinas',2,%s)",
                (Jsonb({'values':[None,'MEBA',20]}),))
    machine='MEBA' if area=='perfis' else 'Ficep'
    resource=objects.save(command(name='Historic machine',area=area,definition={'aliases':[{'area':area,'name':machine}],
        'operations':[op],'history_window_days':90,'confirmed':True}), 'resource')
    objects.save(command(name='Availability stays separate',area=area,definition={'resource_id':resource['id'],
        'year':2026,'week':39,'shifts':2,'hours_per_shift':7.5,'exception_hours':1,'confirmed':True}),'calendar')
    technical={'material_type':'Cantoneira','profile':'L40','grade':'S235','length_mm':1000,'section_unit':20}
    rows=[{'key':key,'values':{**technical,'of':'OF4200','component_ref':key,'machine':machine,'operation':op,
        'quantity_required':100,'remaining':100,'quantity_to_plan':100,'planning_active':active,'expected_date':'2026-09-23'},
        'raw':{'Mt\\h':5},'calculation':{'compatible':True,'rules':{},'production_sources':[{'operation':op,'remaining':100,'origin':'Condição inicial local'}]},
        'population':{'active':active},'preparations':[]} for key,active in [('closed-a',False),('closed-b',False),('new',True)]]
    events=[{'key':key,'sheet_uid':sheet,'planning_keys':[key], 'values':{'machine':machine,'operation':op,
        'quantity':q,'production_date':'2026-09-22','association_status':'explicit'}}
        for key,sheet,q in [('closed-a','a',10),('closed-b','b',90)]]
    with planning.connect() as c:
        publish_planning_fixture(c,area,'historical-fixture',rows)
        projection.publish(c,'production:'+area,'historical-fixture',events,{})
        projection.publish(c,'production_hours:'+area,'historical-fixture',[
            {'key':s,'sheet_uid':s,'values':{'machine':machine,'production_date':'2026-09-22','hours_worked':h}}
            for s,h in [('a',2),('b',8)]],{})
    with planning.connect() as c:
        configs=c.execute('SELECT * FROM planning_mtg.raw_objects WHERE NOT archived').fetchall()
        p.apply_rows(c,area,rows,configs)
        assert rows[-1]['values']['theoretical_hours']==10
        assert rows[-1]['values']['rate_source']=='Histórico'
        if area=='cantoneiras':assert rows[-1]['values']['speed_m_h']==10
        publish_planning_fixture(c,area,'historical-calculated',rows)
    capacity.rebuild()
    result=query.listing({'area':area,'dataset':'capacity_items'})['rows']
    assert len(result)==1 and result[0]['planning_key']=='new'
    row=result[0]
    assert row['values']['planned_hours']==10
    assert row['values']['rate_source']=='Histórico'
    assert row['values']['applied_rate_value']==10*unit_volume
    evidence=p.evidence(row['applied_rate']['history_hash'])
    assert evidence['hours']==10 and evidence['event_count']==2
    frozen=query.listing({'area':area,'population':'all'})['version']
    manual=objects.save(command(name='Manual faster',area=area,definition={'resource_id':resource['id'],'area':area,
        'operation':op,'method':method,'value':20*unit_volume,'valid_from':'2026-09-01','valid_until':'2026-09-30','confirmed':True}), 'rate')
    capacity.rebuild()
    row=query.listing({'area':area,'dataset':'capacity_items'})['rows'][0]
    assert row['values']['planned_hours']==5 and row['values']['rate_source']=='Manual'
    closed=query.listing({'area':area,'population':'history'})['rows']
    assert len(closed)==2
    assert all(r['values']['theoretical_hours']==5 and r['values']['rate_source']=='Manual' for r in closed)
    assert all(r['values']['hours_pct'] is None for r in closed)
    objects.save(command(id=manual['id'],expected_revision=1,name='Expired',area=area,
        definition={**manual['definition'],'valid_until':'2026-09-22'}),'rate')
    capacity.rebuild()
    assert query.listing({'area':area,'dataset':'capacity_items'})['rows'][0]['values']['rate_source']=='Histórico'
    assert all(r['values']['theoretical_hours']==10 and r['values']['rate_source']=='Histórico'
        for r in query.listing({'area':area,'population':'history'})['rows'])
    def check(source,hours,rate,actual_hours):
        current=query.listing({'area':area,'population':'all'})['rows']
        assert len(current)==3
        for r in current:
            assert r['values']['rate_source']==source
            assert r['values']['theoretical_hours']==pytest.approx(hours)
            assert r['values']['applied_rate_value']==pytest.approx(rate)
            if not r['population']['active']:
                assert r['values']['hours_pct'] is None
                assert 'fechada' in r['calculation']['rules']['hours_pct']['reason']
        items=query.listing({'area':area,'dataset':'capacity_items'})['rows']
        assert len(items)==1 and items[0]['planning_key']=='new'
        weekly=next(r for r in query.listing({'area':area,'dataset':'capacity'})['rows'] if r['key']==resource['id']+'|2026|39')
        assert weekly['values']['planned_hours']==pytest.approx(hours)
        assert weekly['values']['actual_hours']==actual_hours
        assert weekly['values']['available_hours']==14
    definition={'resource_id':resource['id'],'mode':'sheet','sheet_key':area+':a','hours':12,
        'operation':op,'source':'Reviewed manual test declaration','confirmed':True,'replace_ocr':True}
    reviewed=worked_hours.preview({'definition':definition})
    hours=objects.save(command(name='Actual hours',area=area,definition={**definition,'basis_hash':reviewed['basis_hash']}),'worked_hours')
    capacity.rebuild();check('Histórico',20,5*unit_volume,20)  # 100 units / (12+8 hours)
    hours=objects.save(command(id=hours['id'],expected_revision=hours['revision'],name='Revised actual hours',area=area,
        definition={**hours['definition'],'hours':2}),'worked_hours')
    capacity.rebuild();check('Histórico',10,10*unit_volume,10)
    resource=objects.save(command(id=resource['id'],expected_revision=resource['revision'],name='One day window',area=area,
        definition={**resource['definition'],'history_window_days':1}),'resource')
    capacity.rebuild();check('Excel provisório',100 if area=='perfis' else 20,20 if area=='perfis' else 5,10)
    resource=objects.save(command(id=resource['id'],expected_revision=resource['revision'],name='Restored window',area=area,
        definition={**resource['definition'],'history_window_days':90}),'resource')
    capacity.rebuild();check('Histórico',10,10*unit_volume,10)
    revised=copy.deepcopy(events[0]);revised['values']['quantity']=20
    with planning.connect() as c:projection.publish_delta(c,'production:'+area,'revised-closed-production',[revised],{})
    capacity.rebuild();check('Histórico',100/11,11*unit_volume,10)
    assert all(r['values']['theoretical_hours']==10 for r in query.listing({'area':area,'population':'all','version':frozen})['rows'])
    def contents():
        result={}
        for dataset in ('planning','capacity','capacity_items','capacity_machines'):
            result[dataset]=query.listing({'area':area,'dataset':dataset,'population':'all'})['rows']
            for row in result[dataset]:
                for rule in row.get('calculation',{}).get('rules',{}).values():rule.pop('capacity_fingerprint',None)
        return result
    incremental=contents();capacity_revision.rebuild(force=True)
    assert contents()==incremental


@pytest.mark.parametrize('quantities,shifts,hours_per_shift,exception,expected_hours,occupancy',[
    ((10,40),1,8,4,[1,4],125),
    ((20,80),2,7.5,1,[2,8],1000/14),
])
def test_occupancy_repeated_on_each_piece_and_delta_retains_frozen_versions(workspace,quantities,shifts,hours_per_shift,exception,expected_hours,occupancy):
    resource=objects.save(command(name='Physical machine',definition={'aliases':[{'area':'perfis','name':'MEBA'}],
        'operations':['corte'],'confirmed':True}), 'resource')
    objects.save(command(name='Availability',definition={'resource_id':resource['id'],'year':2026,'week':39,
        'shifts':shifts,'hours_per_shift':hours_per_shift,'exception_hours':exception,'confirmed':True}), 'calendar')
    objects.save(command(name='Rate',definition={'resource_id':resource['id'],'area':'perfis','operation':'corte',
        'method':'units_hour','value':10,'valid_from':'2026-01-01','confirmed':True}), 'rate')
    rows=[{'key':str(i),'values':{'of':'OF4200','component_ref':str(i),'machine':'MEBA','operation':'corte',
        'quantity_required':q,'quantity_to_plan':q,'expected_date':'2026-09-23'},
        'calculation':{'production_sources':[{'operation':'corte','remaining':q,'origin':'Local'}]}}
        for i,q in enumerate(quantities)]
    with planning.connect() as c:first=publish_planning_fixture(c,'perfis','occupancy',rows)
    capacity.rebuild()
    calculated=query.listing({})
    assert [r['values']['hours_pct'] for r in calculated['rows']]==pytest.approx([occupancy,occupancy])  # Same weekly aggregate, never individual contributions.
    assert [r['values']['theoretical_hours'] for r in calculated['rows']]==expected_hours
    assert all('hours_pct' not in r['values'] for r in query.listing({'version':str(first['id'])})['rows'])
    again=calculated['version'];capacity.rebuild()
    assert query.listing({})['version']==again  # No feedback loop from derived generations.
    with planning.connect() as c:
        gen=projection.publish_delta(c,'planning:perfis','delta-fixture',[
            {'key':'2','values':{'of':'OF4300','component_ref':'2'}}],{},remove=['0'])
    assert query.listing({})['total']==2
    assert {r['key'] for r in query.listing({})['rows']}=={'1','2'}
    assert {r['key'] for r in query.listing({'version':again})['rows']}=={'0','1'}
    with pytest.raises(planning.PlanningError,match='população mudou'):
        with planning.connect() as c:projection.publish_delta(c,'planning:perfis','stale-delta',rows,{},expected_generation=again)
    assert query.listing({})['version']==str(gen['id'])
    with planning.connect(readonly=True) as c:
        assert c.execute("SELECT count(*) n FROM planning_mtg.raw_members WHERE dataset='planning:perfis' AND row_key='1'").fetchone()['n']==2


def test_stale_repeatable_read_delta_cannot_publish_over_a_new_generation(workspace):
    import psycopg
    with planning.connect() as c:projection.publish(c,'planning:perfis','before',[{'key':'a','values':{'of':'OF4200'}}],{})
    with pytest.raises(psycopg.errors.SerializationFailure):
        with planning.connect() as stale:
            stale.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            first=query.generation(stale)
            with planning.connect() as fresh:
                latest=projection.publish_delta(fresh,'planning:perfis','concurrent',[{'key':'b','values':{'of':'OF4300'}}],{})
            projection.publish_delta(stale,'planning:perfis','obsolete',[],{},expected_generation=first['id'])
    result=query.listing({})
    assert result['version']==str(latest['id']) and result['total']==2


def test_shared_quantity_survives_other_operation_edits_and_keeps_validated_production(workspace):
    from app import planning_needs as needs, planning_associations as assoc
    from tests.test_planning_needs import request, vals, save
    from psycopg.types.json import Jsonb
    initial={**vals(),'quantity_required':50,'abocardar':'X','expected_date':'2026-09-23'}
    n=needs.resolve(request(area='perfis',production_order_no='4200',values=initial))
    n=save(n,initial)
    with planning.connect() as c:
        # A persisted secondary preparation retains the common values at its revision.
        boc=c.execute("SELECT id FROM planning_mtg.need_operations WHERE need_id=%s AND code='abocardar'",(n['need_id'],)).fetchone()['id']
        c.execute('''INSERT INTO planning_mtg.records(id,area,production_order_no,component_ref,
            source_payload,values_json,actor,source_kind,need_id,operation_id,record_status)
            SELECT %s,area,production_order_no,component_ref,source_payload,
                values_json || '{"operation":"abocardar"}'::jsonb,actor,source_kind,need_id,%s,'draft'
            FROM planning_mtg.records WHERE operation_id=%s''',(uuid.uuid4(),boc,n['operation_id']))
        c.execute("INSERT INTO mes_kanban.validated_sheets(sheet_uid,sheet_date,template_name,family,operator_name,image_sha256,raw_extraction,sheet_data,validated_by,source_app) VALUES ('shared-q','2026-09-22','t','perfis','Teste','hash','{}','{}','Teste','kanban-mes-mtg2')")
        rid=c.execute("INSERT INTO mes_kanban.production_records(sheet_uid,row_index,sheet_date,family,operator_name,production_order,quantity,validated_at) VALUES ('shared-q',0,'2026-09-22','perfis','Teste','4200',4,now()) RETURNING id").fetchone()['id']
        fact=assoc.fact(c,rid)
    assoc.save(request(production_record_id=rid,expected_revision=0,evidence_hash=needs.digest(fact),reason='Folha conferida',
        allocations=[{'need_id':n['need_id'],'operation_id':n['operation_id'],'expected_need_revision':n['revision'],'quantity':4}]))
    before=needs.detail(n['need_id'])
    changed=save(n,{'operation':'abocardar','quantity_required':51})
    current=needs.detail(n['need_id'])
    assert current['need']['technical_revision']==before['need']['technical_revision']
    assert next(r for r in current['records'] if str(r['operation_id'])==str(n['operation_id']))['values_json']['quantity_required']==50
    assert assoc.get_evidence(n['need_id'],n['operation_id'])['evidence']['ocr_quantity']==4
    resource=objects.save(command(name='Shared piece test',definition={'aliases':[{'area':'perfis','name':'MEBA'}],
        'operations':['corte','abocardar'],'confirmed':True}),'resource')
    for op in ('corte','abocardar'):
        objects.save(command(name=op,definition={'resource_id':resource['id'],'area':'perfis','operation':op,
            'method':'units_hour','value':10,'valid_from':'2026-01-01','confirmed':True}),'rate')
    for area in planning.AREAS:projection.rebuild(area)
    capacity.rebuild()
    row=query.listing({'selected':[n['need_id']]})['rows'][0]
    assert row['values']['quantity_required']==51 and row['values']['cut']==4
    assert row['values']['remaining']==47 and row['values']['theoretical_hours']==4.7
    items=[r for r in query.listing({'dataset':'capacity_items'})['rows'] if r['planning_key']==n['need_id']]
    assert len(items)==2 and {r['values']['quantity_required'] for r in items}=={51}
    assert {r['values']['operation']:r['values']['planned_hours'] for r in items}=={'corte':4.7,'abocardar':5.1}
    # Reopening/saving only a note in the older cut preparation cannot restore50.
    last=save(changed,{'operation':'corte','notes':'Nota sem alterar a quantidade comum'})
    assert needs.detail(last['need_id'])['need']['quantity_required']==51
    assert assoc.get_evidence(last['need_id'],last['operation_id'])['evidence']['ocr_quantity']==4
