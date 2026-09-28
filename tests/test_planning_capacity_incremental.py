"""Incremental capacity must equal a fresh calculation across areas and periods."""
import copy
import uuid
import pytest
from app import planning
from app.raw import projection,query,objects,capacity_revision as capacity
from tests.test_raw_workspace import workspace,database,canonical,registry,postgres16


def command(**kw):return {'request_id':str(uuid.uuid4()),**kw}


def piece(key,area,machine,q,when='2026-09-23'):
    op='corte' if area=='perfis' else '112'
    return {'key':key,'area':area,'values':{'of':'OF'+key,'component_ref':key,'machine':machine,
        'operation':op,'quantity_required':q,'quantity_to_plan':q,'remaining':q,'length_mm':1000,
        'expected_date':when,'planning_active':True},'raw':{},
        'calculation':{'compatible':True,'production_sources':[{'operation':op,'remaining':q,'origin':'Local'}]}}


def resource(name,aliases):
    r=objects.save(command(name=name,definition={'aliases':aliases,'operations':['corte','112','abocardar'],'confirmed':True}),'resource')
    for alias in aliases:
        objects.save(command(name=name+' rate '+alias['area'],definition={'resource_id':r['id'],
            'area':alias['area'],'operation':'corte' if alias['area']=='perfis' else '112',
            'method':'units_hour','value':10 if alias['area']=='perfis' else 20,'valid_from':'2026-01-01','confirmed':True}),'rate')
    for week in [39,40]:
        objects.save(command(name=name+' week '+str(week),definition={'resource_id':r['id'],'year':2026,
            'week':week,'shifts':2,'hours_per_shift':7.5,'exception_hours':1,'confirmed':True}),'calendar')
    return r


def read_all():
    data={}
    with planning.connect(readonly=True) as c:
        for area in planning.AREAS:
            for dataset in ['planning','capacity','capacity_items','capacity_machines']:
                g=query.generation(c,area,dataset=dataset);base,args=query.source(g)
                rows={r['row_key']:{**r['detail'],'values':r['values_json']} for r in c.execute('SELECT m.row_key,c.detail,c.values_json'+base,args)}
                # Only the immutable provenance epoch differs between rebuilds.
                for row in rows.values():
                    for rule in row.get('calculation',{}).get('rules',{}).values():rule.pop('capacity_fingerprint',None)
                data[(area,dataset)]=rows
    return data


def assert_matches_full():
    actual=read_all();capacity.rebuild(force=True)
    fresh=read_all()
    def first_difference(left,right,path='root'):
        if type(left)!=type(right):return path,left,right
        if isinstance(left,dict):
            for key in sorted(set(left)|set(right),key=str):
                if key not in left or key not in right:return path+'.'+str(key),left.get(key),right.get(key)
                found=first_difference(left[key],right[key],path+'.'+str(key))
                if found:return found
            return None
        if isinstance(left,list):
            if len(left)!=len(right):return path+'.length',len(left),len(right)
            for index,(a,b) in enumerate(zip(left,right)):
                found=first_difference(a,b,path+f'[{index}]')
                if found:return found
            return None
        return (path,left,right) if left!=right else None
    assert fresh==actual,first_difference(fresh,actual)


def test_macro_balance_survives_capacity_storage_and_origin_changes_invalidate(workspace):
    """Capacity's compact SQL reader must retain evidence used by planning balances."""
    from app.planning_estimates import select_balance
    resource('MEBA',[{'area':'perfis','name':'MEBA'}])
    row=piece('macro-balance','perfis','MEBA',100)
    row['original']=dict(row['values'])
    row['raw']={'Qtd em Falta':40}
    row['values']['remaining']=None
    row['calculation']['production_sources'][0].update(remaining=None,origin='Indisponível')
    expected=select_balance(row,'corte')
    assert expected['planning_remaining']==40
    with planning.connect() as c:
        projection.publish(c,'planning:perfis','macro-balance-start',[row],
                           {'core_source_fingerprint':projection.fingerprint(c,'perfis')})
        projection.publish(c,'planning:cantoneiras','macro-balance-empty',[],
                           {'core_source_fingerprint':projection.fingerprint(c,'cantoneiras')})
    capacity.rebuild()
    actual=read_all()[('perfis','planning')][row['key']]
    estimate=actual['calculation']['operation_estimates'][0]
    assert estimate['balance']==expected
    assert estimate['quantity']==40 and estimate['hours']==4
    assert actual['values']['remaining'] is None
    assert actual['values']['planning_remaining']==40
    assert_matches_full()

    changed=copy.deepcopy(row)
    changed['original']['quantity_required']=120
    with planning.connect() as c:
        projection.publish_delta(c,'planning:perfis','macro-origin-changed',[changed],
                                 {'core_source_fingerprint':projection.fingerprint(c,'perfis')})
    capacity.rebuild()
    actual=read_all()[('perfis','planning')][row['key']]
    assert actual['values']['planning_remaining'] is None
    assert actual['calculation']['operation_estimates'][0]['hours'] is None
    assert_matches_full()


@pytest.fixture()
def populations(workspace):
    shared=resource('Shared',[{'area':'perfis','name':'MEBA'},{'area':'cantoneiras','name':'Ficep'}])
    other=resource('Other',[{'area':'perfis','name':'OTHER'}])
    untouched=resource('Untouched',[{'area':'perfis','name':'UNCHANGED'}])
    rows=[piece('1','perfis','MEBA',20),piece('2','perfis','MEBA',80),
          piece('3','perfis','OTHER',50),piece('4','perfis','UNCHANGED',30)]
    with planning.connect() as c:
        projection.publish(c,'planning:perfis','initial-p',rows,{'core_source_fingerprint':projection.fingerprint(c,'perfis')})
        projection.publish(c,'planning:cantoneiras','initial-c',[piece('5','cantoneiras','Ficep',100)],{'core_source_fingerprint':projection.fingerprint(c,'cantoneiras')})
    capacity.rebuild()
    return shared,other,untouched


def test_move_quantity_machine_and_week_updates_old_new_and_shared_area(populations):
    shared,other,untouched=populations
    original=read_all();moved=piece('1','perfis','OTHER',40,'2026-09-30')
    with planning.connect() as c:
        before=query.generation(c,'perfis',dataset='capacity_items');base,args=query.source(before)
        hashes={r['row_key']:r['content_hash'] for r in c.execute('SELECT m.row_key,m.content_hash'+base,args)}
        projection.publish_delta(c,'planning:perfis','move',[moved],{'core_source_fingerprint':projection.fingerprint(c,'perfis')})
    capacity.rebuild();actual=read_all()
    shared_week=actual[('perfis','capacity')][shared['id']+'|2026|39']['values']
    assert shared_week['planned_hours']==13 and shared_week['occupancy']==pytest.approx(1300/14)
    for area,key in [('perfis','2'),('cantoneiras','5')]:assert actual[(area,'planning')][key]['values']['hours_pct']==pytest.approx(1300/14)
    new_week=actual[('perfis','capacity')][other['id']+'|2026|40']['values']
    assert new_week['planned_hours']==4 and new_week['occupancy']==pytest.approx(400/14)
    assert actual[('perfis','capacity_items')]['1:corte']['values']['bucket_key']==other['id']+'|2026|40'
    assert actual[('perfis','planning')]['4']==original[('perfis','planning')]['4']
    with planning.connect(readonly=True) as c:
        g=query.generation(c,'perfis',dataset='capacity');assert g['metadata']['calculation_scope']=='resources'
        assert untouched['id'] not in g['metadata']['affected_resources']
        g=query.generation(c,'perfis',dataset='capacity_items');base,args=query.source(g)
        current={r['row_key']:r['content_hash'] for r in c.execute('SELECT m.row_key,m.content_hash'+base,args)}
        assert current['4:corte']==hashes['4:corte']
    assert_matches_full()


def test_rate_calendar_archive_and_piece_removal_equal_complete_rebuild(populations):
    shared,_,_=populations
    with planning.connect(readonly=True) as c:
        conf=c.execute("SELECT * FROM planning_mtg.raw_objects WHERE kind='rate' AND definition->>'resource_id'=%s AND definition->>'area'='perfis'",(shared['id'],)).fetchone()
    saved=objects.save(command(id=str(conf['id']),expected_revision=conf['revision'],name=conf['name'],definition={**conf['definition'],'value':20}),'rate')
    capacity.rebuild();r=read_all()
    assert r[('perfis','capacity')][shared['id']+'|2026|39']['values']['planned_hours']==10  # 1+4+5, both areas.
    assert_matches_full()
    objects.save(command(id=saved['id'],expected_revision=saved['revision'],name=conf['name'],definition=saved['definition'],archived=True),'rate')
    capacity.rebuild();assert_matches_full()
    with planning.connect() as c:projection.publish_delta(c,'planning:perfis','remove',[],{'core_source_fingerprint':projection.fingerprint(c,'perfis')},remove=['1','2'])
    capacity.rebuild();r=read_all()
    assert not {'1:corte','2:corte'}&set(r[('perfis','capacity_items')])
    assert r[('perfis','capacity')][shared['id']+'|2026|39']['values']['planned_hours']==5
    assert_matches_full()


def test_secondary_resource_update_preserves_primary_and_both_operation_estimates(populations):
    shared,other,_=populations
    rate=objects.save(command(name='Secondary rate',definition={'resource_id':other['id'],'area':'perfis',
        'operation':'abocardar','method':'units_hour','value':20,'valid_from':'2026-01-01','confirmed':True}),'rate')
    row=piece('2','perfis','MEBA',80);row['values']['abocardar']='X'
    row['preparations']=[{'operation_id':'boc','capacity_compatible':True,'record_status':'draft',
        'values_json':{'operation':'abocardar','machine':'OTHER','expected_date':'2026-09-30','quantity_to_plan':60}}]
    row['calculation']['production_sources'].append({'operation':'abocardar','remaining':60,'origin':'Local'})
    with planning.connect() as c:projection.publish_delta(c,'planning:perfis','secondary',[row],{'core_source_fingerprint':projection.fingerprint(c,'perfis')})
    capacity.rebuild();before=read_all()
    with planning.connect(readonly=True) as c:
        assert 'perfis:Por definir' not in query.generation(c,'perfis',dataset='capacity')['metadata']['affected_resources']
    primary=before[('perfis','planning')]['2']['values']['hours_pct']
    objects.save(command(id=rate['id'],expected_revision=rate['revision'],name='Secondary faster',
        definition={**rate['definition'],'value':30}),'rate')
    capacity.rebuild();after=read_all();piece_row=after[('perfis','planning')]['2']
    assert piece_row['values']['hours_pct']==primary
    assert {e['operation']:e['hours'] for e in piece_row['calculation']['operation_estimates']}=={'corte':8,'abocardar':2}
    assert after[('perfis','capacity_items')]['2:boc']['values']['planned_hours']==2
    assert_matches_full()


def test_refreshing_unchanged_peer_does_not_rebuild_its_machine_or_lose_occupancy(populations):
    shared,other,untouched=populations
    before=read_all();moved=piece('1','perfis','OTHER',40,'2026-09-30')
    # As in an OF refresh, core rows omit capacity-derived fields even when
    # this peer's own inputs are unchanged.
    peer=piece('4','perfis','UNCHANGED',30)
    peer['values'].update(last_activity='2026-09-22',unassigned_records=7,execution_status='Consultar produção por operação')
    with planning.connect() as c:projection.publish_delta(c,'planning:perfis','peer-refresh',[moved,peer],{'core_source_fingerprint':projection.fingerprint(c,'perfis')})
    capacity.rebuild();after=read_all()
    assert after[('perfis','planning')]['4']['values']['hours_pct']==before[('perfis','planning')]['4']['values']['hours_pct']
    with planning.connect(readonly=True) as c:
        meta=query.generation(c,'perfis',dataset='capacity')['metadata']
        assert untouched['id'] not in meta['affected_resources']
    assert_matches_full()


def test_macro_rebinding_preserves_history_but_production_revision_invalidates_it(populations,monkeypatch):
    from app.raw import historical_estimates
    closed=piece('closed-history','perfis','MEBA',20)
    closed['values'].update(planning_active=False,status='Fechada')
    event={'key':'fact','planning_keys':['1'],'sheet_uid':'sheet','values':{
        'machine':'MEBA','production_date':'2026-09-23','quantity':10,
        'operation':'corte','association_status':'explicit','source':'kanban-mes-mtg2'}}
    with planning.connect() as c:
        projection.publish_delta(c,'planning:perfis','with-closed',[closed],{'core_source_fingerprint':projection.fingerprint(c,'perfis')})
        projection.publish(c,'production:perfis','before-rebind',[event],{})
    capacity.rebuild()
    visited=[];original=historical_estimates.recalculate
    def observe(conn,area,rows,*args,**kwargs):
        visited.extend(r['key'] for r in rows)
        return original(conn,area,rows,*args,**kwargs)
    monkeypatch.setattr(historical_estimates,'recalculate',observe)
    rebound=copy.deepcopy(read_all()[('perfis','planning')]['1']);rebound['key']='new-import:1'
    event['planning_keys']=[rebound['key']]
    with planning.connect() as c:
        projection.publish_delta(c,'planning:perfis','rebind',[rebound],{'core_source_fingerprint':projection.fingerprint(c,'perfis')},remove=['1'])
        projection.publish_delta(c,'production:perfis','after-rebind',[event],{})
    capacity.rebuild()
    with planning.connect(readonly=True) as c:assert query.generation(c,'perfis',dataset='capacity')['metadata']['history_inputs_unchanged']
    assert 'closed-history' not in visited
    assert_matches_full()
    visited.clear();event['values']['quantity']=11
    with planning.connect() as c:projection.publish_delta(c,'production:perfis','corrected-fact',[event],{})
    capacity.rebuild()
    with planning.connect(readonly=True) as c:assert not query.generation(c,'perfis',dataset='capacity')['metadata']['history_inputs_unchanged']
    assert 'closed-history' in visited
    assert_matches_full()


def test_peer_refresh_keeps_current_diagnostics_for_unresolved_extra_operation(populations):
    from datetime import date
    from app.raw import productivity
    row=piece('5','cantoneiras','Ficep',100,when=None)
    row['values']['operation_detail']='111-1410'
    row['calculation']['production_sources'].append({'operation':'111-1410','remaining':None,'origin':'Indisponível'})
    def publish_core(day,token):
        current=copy.deepcopy(row)
        with planning.connect() as c:
            configs=c.execute("SELECT * FROM planning_mtg.raw_objects WHERE NOT archived ORDER BY id").fetchall()
            productivity.apply_rows(c,'cantoneiras',[current],configs,today=day)
            projection.publish_delta(c,'planning:cantoneiras',token,[current],{'core_source_fingerprint':projection.fingerprint(c,'cantoneiras')})
        capacity.rebuild()
    publish_core(date(2026,9,23),'peer-old-diagnostics')
    before=read_all()[('cantoneiras','planning')]['5']
    publish_core(date(2026,9,24),'peer-current-diagnostics')
    after=read_all()[('cantoneiras','planning')]['5']
    extra=next(e for e in after['calculation']['operation_estimates'] if e['operation']=='111-1410')
    assert extra['history']['window']['end']=='2026-09-24'
    assert extra['rate'] is None and extra['hours'] is None
    assert after['values']['hours_pct']==before['values']['hours_pct']
    assert '5:111-1410' not in read_all()[('cantoneiras','capacity_items')]
    assert_matches_full()


def test_imported_rate_is_original_and_only_belongs_to_primary_operation(populations):
    row=piece('5','cantoneiras','Ficep',100)
    row['values'].update(operation_detail='302',speed_m_h=50)
    row['raw']['Mt\\h']=50
    with planning.connect() as c:projection.publish_delta(c,'planning:cantoneiras','secondary-reference',[row],{'core_source_fingerprint':projection.fingerprint(c,'cantoneiras')})
    capacity.rebuild();data=read_all();items=data[('cantoneiras','capacity_items')]
    assert items['5:112']['reference_rate']['value']==50
    assert items['5:112']['values']['planned_hours']==5
    assert items['5:112']['values']['reference_hours']==2
    assert items['5:302']['reference_rate'] is None
    assert data[('cantoneiras','planning')]['5']['values']['speed_m_h'] is None  # Applied rate is in units/h.
    assert_matches_full()


def test_core_refresh_of_closed_piece_does_not_restore_an_older_estimate(populations):
    from app import planning_population
    row=piece('closed','perfis','MEBA',20);row['values'].update(status='Fechada',theoretical_hours=2,rate_source='Excel provisório')
    planning_population.annotate(row)
    with planning.connect() as c:projection.publish_delta(c,'planning:perfis','closed-first',[row],{'core_source_fingerprint':projection.fingerprint(c,'perfis')})
    capacity.rebuild()
    # Make the newer core estimate true in the shared rate configuration too.
    with planning.connect(readonly=True) as c:
        rate=c.execute("SELECT * FROM planning_mtg.raw_objects WHERE kind='rate' AND definition->>'resource_id'=%s AND definition->>'area'='perfis'",(populations[0]['id'],)).fetchone()
    objects.save(command(id=str(rate['id']),expected_revision=rate['revision'],name=rate['name'],
        definition={**rate['definition'],'value':20}),'rate')
    row['values'].update(theoretical_hours=1,rate_source='Manual')
    with planning.connect() as c:projection.publish_delta(c,'planning:perfis','closed-refreshed',[row],{'core_source_fingerprint':projection.fingerprint(c,'perfis')})
    capacity.rebuild();data=read_all()
    assert data[('perfis','planning')]['closed']['values']['theoretical_hours']==1
    assert data[('perfis','planning')]['closed']['values']['rate_source']=='Manual'
    assert not any(item['planning_key']=='closed' for item in data[('perfis','capacity_items')].values())
    assert_matches_full()


@pytest.mark.parametrize('legacy_index',[False,True])
def test_closed_estimate_patch_preserves_sources_frozen_versions_and_search(populations,legacy_index):
    from app import planning_population,planning_needs as needs
    from app.raw import historical_estimates
    row=piece('closed-source','perfis','MEBA',20)
    row['values']['customer']='Straße'
    row['values']['status']='Fechada';planning_population.annotate(row)
    row['raw']={'Fechado':'X','unrelated_cells':[{'formula':'A1+B2','cached':17}]}
    row['sources']=[{'kind':'macro','payload':{'source_id':'unchanged','cells':[1,2,None]}}]
    row['original']={'quantity_required':20,'source_note':'Original unchanged'}
    row['calculation']['rules']={'unrelated':{'formula':'A1+B2','source':'Original workbook'}}
    with planning.connect() as c:projection.publish_delta(c,'planning:perfis','closed-source',[row],{'core_source_fingerprint':projection.fingerprint(c,'perfis')})
    capacity.rebuild()
    if legacy_index:
        with planning.connect() as c:
            c.execute("UPDATE planning_mtg.raw_members SET planning_active=NULL,planning_machine=NULL WHERE dataset='planning:perfis' AND row_key='closed-source' AND last_generation IS NULL")
    with planning.connect(readonly=True) as c:
        before=query.generation(c,'perfis');base,args=query.source(before)
        prior=c.execute('SELECT m.content_hash,c.values_json,c.detail'+base+" AND m.row_key='closed-source'",args).fetchone()
        rate=c.execute("SELECT * FROM planning_mtg.raw_objects WHERE kind='rate' AND definition->>'resource_id'=%s AND definition->>'area'='perfis'",(populations[0]['id'],)).fetchone()
    saved=objects.save(command(id=str(rate['id']),expected_revision=rate['revision'],name=rate['name'],definition={**rate['definition'],'value':20}),'rate')
    capacity.rebuild()
    current=query.listing({'population':'history','selected':['closed-source']})['rows'][0]
    assert current['values']['theoretical_hours']==1
    for key in ('raw','sources','original','population'):assert current[key]==prior['detail'][key]
    assert current['calculation']['rules']['unrelated']==prior['detail']['calculation']['rules']['unrelated']
    with planning.connect(readonly=True) as c:
        gen=query.generation(c,'perfis');base,args=query.source(gen)
        digest=c.execute('SELECT m.content_hash'+base+" AND m.row_key='closed-source'",args).fetchone()['content_hash']
        stored=c.execute('SELECT detail,detail_source_hash FROM planning_mtg.raw_contents WHERE hash=%s',(digest,)).fetchone()
        assert stored['detail']=={} and stored['detail_source_hash']
        source_hash=stored['detail_source_hash']
        source=c.execute('SELECT detail,detail_source_hash FROM planning_mtg.raw_contents WHERE hash=%s',(source_hash,)).fetchone()
        assert source['detail_source_hash'] is None and source['detail']['raw']==row['raw']
    assert digest==needs.digest(['planning-estimate-patch-v1',prior['content_hash'],historical_estimates.patch(current)])
    frozen=query.listing({'population':'history','selected':['closed-source'],'version':str(before['id'])})['rows'][0]
    assert frozen['values']==prior['values_json'] and frozen['values']['theoretical_hours']==2
    assert query.listing({'population':'history','selected':['closed-source'],'q':'Manual'})['total']==1
    assert query.listing({'population':'history','selected':['closed-source'],'q':'STRASSE'})['total']==1
    objects.save(command(id=saved['id'],expected_revision=saved['revision'],name=rate['name'],definition=saved['definition'],archived=True),'rate')
    capacity.rebuild()
    assert query.listing({'population':'history','selected':['closed-source'],'q':'Manual'})['total']==0
    with planning.connect(readonly=True) as c:
        gen=query.generation(c,'perfis');base,args=query.source(gen)
        newest=c.execute('SELECT m.content_hash'+base+" AND m.row_key='closed-source'",args).fetchone()['content_hash']
        stored=c.execute('SELECT detail_source_hash FROM planning_mtg.raw_contents WHERE hash=%s',(newest,)).fetchone()
        assert stored['detail_source_hash']==source_hash  # Direct source, no unbounded chain of joins.
    assert_matches_full()


def test_closed_secondary_resource_uses_revisioned_preparation_index(populations):
    from app import planning_population
    shared,other,_=populations
    rate=objects.save(command(name='Closed secondary rate',definition={'resource_id':other['id'],
        'area':'perfis','operation':'abocardar','method':'units_hour','value':10,
        'valid_from':'2026-01-01','confirmed':True}),'rate')
    row=piece('closed-preparation','perfis','MEBA',20)
    row['values'].update(status='Fechada',abocardar='X')
    planning_population.annotate(row)
    row['calculation']['production_sources'].append({'operation':'abocardar','remaining':20,'origin':'Local'})
    row['preparations']=[{'operation_id':'secondary','values_json':{'operation':'abocardar','machine':'OTHER'}}]
    with planning.connect() as c:projection.publish_delta(c,'planning:perfis','closed-prepared',[row],{'core_source_fingerprint':projection.fingerprint(c,'perfis')})
    capacity.rebuild()
    with planning.connect(readonly=True) as c:
        before=query.generation(c,'perfis')
        assert 'closed-preparation' in before['metadata']['preparation_keys']
    objects.save(command(id=rate['id'],expected_revision=rate['revision'],name='Closed secondary rate',
        definition={**rate['definition'],'value':20}),'rate')
    capacity.rebuild()
    current=query.listing({'population':'history','selected':['closed-preparation']})['rows'][0]
    estimates={e['operation']:e for e in current['calculation']['operation_estimates']}
    assert estimates['corte']['hours']==2 and estimates['abocardar']['hours']==1
    assert current['values']['hours_pct'] is None
    assert not any(i['planning_key']=='closed-preparation' for i in read_all()[('perfis','capacity_items')].values())
    assert_matches_full()
    row['preparations']=[]
    with planning.connect() as c:
        projection.publish_delta(c,'planning:perfis','preparation-removed',[row],{'core_source_fingerprint':projection.fingerprint(c,'perfis')})
        assert 'closed-preparation' not in query.generation(c,'perfis')['metadata']['preparation_keys']
        frozen=query.generation(c,'perfis',str(before['id']))
        assert 'closed-preparation' in frozen['metadata']['preparation_keys']


def test_analysis_and_export_keep_frozen_estimates_with_shared_source_detail(populations):
    import json
    from app import planning_population
    from app.raw import analysis,exports
    row=piece('closed-report','perfis','MEBA',20)
    row['values']['status']='Fechada';planning_population.annotate(row)
    row['sources']=[{'kind':'macro','source_id':'retained-source','payload':{'original_quantity':20}}]
    with planning.connect() as c:projection.publish_delta(c,'planning:perfis','closed-report',[row],{'core_source_fingerprint':projection.fingerprint(c,'perfis')})
    capacity.rebuild()
    preview=analysis.preview({'definition':{'area':'perfis','dataset':'planning','population':'history',
        'selected':['closed-report'],'group_by':[],'metrics':[{'name':'Horas','expression':'sum([theoretical_hours])'}]}})
    saved=analysis.confirm(command(definition=preview['definition'],evidence_hash=preview['evidence_hash']))
    with planning.connect(readonly=True) as c:
        job=c.execute('SELECT * FROM planning_mtg.raw_jobs WHERE id=%s',(saved['job_id'],)).fetchone()
        rate=c.execute("SELECT * FROM planning_mtg.raw_objects WHERE kind='rate' AND definition->>'resource_id'=%s AND definition->>'area'='perfis'",(populations[0]['id'],)).fetchone()
    analysis.run_job(job)
    evidence=analysis.evidence(job['id'])
    assert evidence['total']==1 and evidence['rows'][0]['values']['theoretical_hours']==2
    assert evidence['rows'][0]['sources']==row['sources']
    frozen=json.loads(exports.report(job['id'],'json')[0])
    assert frozen['support'][0]['values_json']['theoretical_hours']==2
    assert frozen['support'][0]['sources']==[{'kind':'macro','source_id':'retained-source'}]
    objects.save(command(id=str(rate['id']),expected_revision=rate['revision'],name=rate['name'],
        definition={**rate['definition'],'value':20}),'rate')
    capacity.rebuild()
    assert query.listing({'population':'history','selected':['closed-report']})['rows'][0]['values']['theoretical_hours']==1
    assert analysis.evidence(job['id'])==evidence
    assert json.loads(exports.report(job['id'],'json')[0])==frozen
    before=read_all()
    # Roll back only the storage representation; retain hashes, membership
    # epochs and every frozen export before restarting an older application.
    with planning.connect() as c:
        materialized=c.execute('''UPDATE planning_mtg.raw_contents stored
            SET detail=resolved.detail,detail_source_hash=NULL,detail_patch=NULL
            FROM planning_mtg.raw_resolved_contents resolved
            WHERE stored.hash=resolved.hash AND stored.detail_source_hash IS NOT NULL''').rowcount
        assert materialized>0
    assert read_all()==before
    assert analysis.evidence(job['id'])==evidence
    assert json.loads(exports.report(job['id'],'json')[0])==frozen
