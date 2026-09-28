"""Original sheet time is counted once and paired with complete production."""
from datetime import date
import json,math,sqlite3,uuid
import pytest
from app import planning,planning_associations as assoc
from app.raw import projection,productivity,worked_hours,objects
from tests.test_planning_original_associations import decision_source,make_need,proposal
from tests.test_planning_original_production import original_source,publish
from tests.test_original_ocr import local
from tests.test_raw_workspace import workspace,database,canonical,registry,postgres16


def setup_source(f,area,hours=2):
    with sqlite3.connect(f[1]) as c:
        c.execute('ALTER TABLE production_rows ADD COLUMN sheet_hours REAL')
        c.execute('UPDATE production_rows SET sheet_hours=? WHERE sheet_id=1',(hours,))
        c.execute('UPDATE sheets SET sheet_data=? WHERE id=1',(json.dumps({'header':{'area':area,'setor_maquina':'MEBA' if area=='perfis' else 'Ficep'}}),))
    publish(f)
    n,values=make_need(area)
    for a in planning.AREAS:projection.rebuild(a)
    assoc.save(proposal(area,n))
    return n,values


def history(area,values):
    with planning.connect(readonly=True) as c:
        configs=c.execute('SELECT * FROM planning_mtg.raw_objects WHERE NOT archived').fetchall()
        context=productivity.Context(c,configs)
        return context.rate(values,area,'corte' if area=='perfis' else '112','2026-09-24',as_of=date(2026,9,24))


@pytest.mark.parametrize('area',['perfis','cantoneiras'])
def test_original_hours_feed_history_once_and_revisions_refresh_rate(decision_source,area):
    _,values=setup_source(decision_source,area)
    result=history(area,values)
    volume=4*math.pi*(88.9**2-82.9**2)/4 if area=='perfis' else 4
    assert result['source']=='Histórico'
    assert result['rate']['value']==pytest.approx(volume/2)
    assert result['history']['hours']==2 and result['history']['sheet_count']==1
    with sqlite3.connect(decision_source[1]) as c:
        c.execute('UPDATE production_rows SET sheet_hours=4 WHERE sheet_id=1')
        c.execute('UPDATE sheets SET revision=2 WHERE id=1')
    publish(decision_source)
    for a in planning.AREAS:projection.rebuild(a)
    result=history(area,values)
    assert result['rate']['value']==pytest.approx(volume/4)
    assert result['history']['hours']==4
    assert assoc.pending('4200',area,source='original')['records']==[]
    with sqlite3.connect(decision_source[1]) as c:c.execute("UPDATE sheets SET status='draft',revision=3 WHERE id=1")
    # A completely empty publication is deliberately rejected by the importer;
    # retain a second validated sheet with no usable hours to exercise retirement.
    with sqlite3.connect(decision_source[1]) as c:c.execute("UPDATE sheets SET status='validated',revision=1 WHERE id=2")
    publish(decision_source)
    for a in planning.AREAS:projection.rebuild(a)
    assert history(area,values)['source'] is None


def test_original_shared_area_view_does_not_duplicate_physical_time(decision_source):
    from app.raw import capacity,query
    with sqlite3.connect(decision_source[1]) as c:
        c.execute('ALTER TABLE production_rows ADD COLUMN sheet_hours REAL')
        c.execute('UPDATE production_rows SET sheet_hours=3 WHERE sheet_id=1')
    publish(decision_source)
    for a in planning.AREAS:projection.rebuild(a)
    with planning.connect(readonly=True) as c:
        rows=worked_hours.observations(c)
    original=[r for r in rows if r['origin']=='OCR original']
    assert len(original)==1 and original[0]['hours']==3
    assert set(original[0]['areas'])==set(planning.AREAS)
    capacity.rebuild()
    with planning.connect(readonly=True) as c:
        assert worked_hours.observations(c)==rows
        for area in planning.AREAS:
            g=query.generation(c,area,dataset='capacity');base,args=query.source(g)
            assert not any(original[0]['key'] in e.get('sheets',[]) for r in c.execute('SELECT c.detail'+base,args)
                for e in r['detail'].get('actual_evidence',[]))


def test_original_unknown_area_cannot_duplicate_time_across_same_named_resources():
    declaration={'key':'original:instance:1','sheet_uid':'original:instance:1','area':None,
        'areas':['perfis','cantoneiras'],'machine':'SHARED NAME','machines':['SHARED NAME'],
        'hours':3,'date':'2026-09-23','origin':'OCR original','instance_id':'instance','revision':1}
    aliases=[{'area':area,'name':'SHARED NAME'} for area in planning.AREAS]
    for alias in aliases:
        separate={'id':alias['area'],'definition':{'aliases':[alias]}}
        resolved=worked_hours.resolve(separate,[],[declaration])
        assert len(resolved)==1 and resolved[0]['hours'] is None
        assert 'recursos físicos distintos' in resolved[0]['reason']
    shared={'id':'one-confirmed-physical-resource','definition':{'aliases':aliases}}
    resolved=worked_hours.resolve(shared,[],[declaration])
    assert len(resolved)==1 and resolved[0]['hours']==3


def test_sheet_replacement_cannot_hide_new_original_overlap():
    resource={'id':'machine','definition':{'aliases':[{'area':'perfis','name':'M'}]}}
    mes={'key':'perfis:mes-1','sheet_uid':'mes-1','area':'perfis','machine':'M','machines':['M'],
         'date':'2026-09-23','hours':2,'origin':'OCR'}
    original={**mes,'key':'original:x:1','sheet_uid':'original:x:1','origin':'OCR original','instance_id':'x'}
    d={'confirmed':True,'resource_id':'machine','mode':'sheet','sheet_key':mes['key'],
       'start_date':mes['date'],'end_date':mes['date'],'hours':2,'replace_ocr':True,'basis_hash':worked_hours.basis([mes])}
    manual={'id':'human','revision':1,'definition':d}
    assert worked_hours.resolve(resource,[manual],[mes])[0]['hours']==2
    resolved=worked_hours.resolve(resource,[manual],[mes,original])
    assert len(resolved)==1 and resolved[0]['hours'] is None
    assert 'Sobreposição' in resolved[0]['reason'] and set(resolved[0]['sheets'])=={mes['key'],original['key']}
    period={**manual,'definition':{**d,'mode':'period','basis_hash':worked_hours.basis([mes,original])}}
    resolved=worked_hours.resolve(resource,[period],[mes,original])
    assert len(resolved)==1 and resolved[0]['hours']==2
    assert worked_hours.resolve(resource,[period],[mes,{**original,'hours':3}])[0]['hours'] is None
    assert worked_hours.resolve(resource,[period],[mes])[0]['hours'] is None


def test_sheet_overlap_is_visible_in_preview_and_rejected_by_save(workspace):
    resource=objects.save({'request_id':str(uuid.uuid4()),'name':'M','area':'perfis',
        'definition':{'aliases':[{'area':'perfis','name':'M'}],'operations':['corte'],'confirmed':True}},'resource')
    with planning.connect() as c:
        projection.publish(c,'production_hours:perfis','overlap-fixture',[
            {'key':'mes-1','sheet_uid':'mes-1','values':{'machine':'M','production_date':'2026-09-23','hours_worked':2}},
            {'key':'original:x:1','sheet_uid':'original:x:1','areas':['perfis'],'instance_id':'x','source_revision':1,
             'values':{'machine':'M','production_date':'2026-09-23','hours_worked':2,'source':'ocr_original'}}],{})
    d={'resource_id':resource['id'],'mode':'sheet','sheet_key':'perfis:mes-1','hours':2,'source':'Relógio conferido','confirmed':True,'replace_ocr':True}
    preview=worked_hours.preview({'definition':d})
    assert preview['scope_conflict'] and len(preview['observations'])==2
    p={'request_id':str(uuid.uuid4()),'name':'Tentativa parcial','area':'perfis','definition':{**d,'basis_hash':preview['basis_hash']}}
    with pytest.raises(planning.PlanningError,match='declaração por período'):objects.save(p,'worked_hours')
    d={**d,'mode':'period','start_date':'2026-09-23','end_date':'2026-09-23'}
    preview=worked_hours.preview({'definition':d});assert preview['scope_conflict'] is None
    objects.save({**p,'request_id':str(uuid.uuid4()),'definition':{**d,'basis_hash':preview['basis_hash']}},'worked_hours')
    with planning.connect(readonly=True) as c:
        from app import planning_needs
        declarations=planning_needs.serial(c.execute("SELECT * FROM planning_mtg.raw_objects WHERE kind='worked_hours'").fetchall())
        resolved=worked_hours.resolve(resource,declarations,worked_hours.observations(c))
        assert len(resolved)==1 and resolved[0]['hours']==2


def test_unconfigured_machine_does_not_sum_original_and_mes_overlap(workspace):
    from app.raw import capacity,query
    with planning.connect() as c:
        for area in planning.AREAS:
            projection.publish(c,'planning:'+area,'overlap',[],{'core_source_fingerprint':projection.fingerprint(c,area)})
        projection.publish(c,'production_hours:perfis','overlap',[
            {'key':'mes','sheet_uid':'mes','values':{'machine':'M','production_date':'2026-09-23','hours_worked':2}},
            {'key':'original:x:1','sheet_uid':'original:x:1','areas':['perfis'],'instance_id':'x','source_revision':1,
             'values':{'source':'ocr_original','machine':'M','production_date':'2026-09-23','hours_worked':2}}],{})
    capacity.rebuild()
    row=next(r for r in query.listing({'area':'perfis','dataset':'capacity'})['rows'] if r['values']['machine']=='M')
    assert row['values']['actual_hours'] is None
    assert row['actual_coverage']['known']==0 and row['actual_coverage']['total']==2
    assert {e['origin'] for e in row['actual_evidence']}=={'OCR','OCR original'}
    assert all('Sobreposição' in e['reason'] for e in row['actual_evidence'])


def test_original_incomplete_sheet_excludes_volume_and_hours_together(decision_source):
    _,values=setup_source(decision_source,'cantoneiras')
    with sqlite3.connect(decision_source[1]) as c:
        c.execute("INSERT INTO production_rows(id,sheet_id,row_index,qtd,of,sheet_iso_date,sheet_hours) VALUES(55,1,1,NULL,'4200','2026-09-17',2)")
        c.execute('UPDATE sheets SET revision=2 WHERE id=1')
    publish(decision_source)
    for a in planning.AREAS:projection.rebuild(a)
    result=history('cantoneiras',values)
    assert result['source'] is None and result['history']['hours']==0 and result['history']['volume']==0
    assert result['excluded_cohorts']>0


def test_empty_original_sheet_does_not_recalculate_unassigned_resources(decision_source):
    from app.raw import capacity,query
    setup_source(decision_source,'cantoneiras')
    capacity.rebuild()
    before={a:query.listing({'area':a,'population':'all'})['rows'] for a in planning.AREAS}
    with sqlite3.connect(decision_source[1]) as c:
        c.execute("INSERT INTO sheets VALUES(99,'validated',?,'2026-09-23 12:00:00',1)",(json.dumps({'header':{'area':'cantoneiras'}}),))
    publish(decision_source)
    for a in planning.AREAS:projection.rebuild(a)
    capacity.rebuild()
    with planning.connect(readonly=True) as c:
        assert query.generation(c,'perfis',dataset='capacity')['metadata']['affected_resources']==[]
    for a in planning.AREAS:
        after=query.listing({'area':a,'population':'all'})['rows']
        assert {r['key']:r['values'] for r in after}=={r['key']:r['values'] for r in before[a]}


def test_original_mes_time_overlap_requires_audited_replacement(decision_source):
    _,values=setup_source(decision_source,'perfis')
    resource=objects.save({'request_id':str(uuid.uuid4()),'name':'MEBA','area':'perfis',
        'definition':{'aliases':[{'area':'perfis','name':'MEBA'}],'operations':['corte'],'confirmed':True}},'resource')
    with planning.connect() as c:
        rows=worked_hours.observations(c)
        original=next(r for r in rows if r['origin']=='OCR original')
        synthetic={**original,'key':'perfis:mes-other','sheet_uid':'mes-other','origin':'OCR'}
        for field in ('areas','revision','source_content_hash','instance_id'):synthetic.pop(field,None)
        cohorts=worked_hours.resolve({'id':resource['id'],'definition':{'aliases':[{'area':'perfis','name':'MEBA'}]}},[],[original,synthetic])
    assert len(cohorts)==2 and all(r['hours'] is None and 'Sobreposição' in r['reason'] for r in cohorts)
    d={'resource_id':resource['id'],'mode':'period','start_date':'2026-09-17','end_date':'2026-09-17',
       'hours':2,'source':'Conferência de folha original','confirmed':True,'replace_ocr':True}
    preview=worked_hours.preview({'definition':d})
    objects.save({'request_id':str(uuid.uuid4()),'area':'perfis','name':'Horas conferidas','definition':{**d,'basis_hash':preview['basis_hash']}},'worked_hours')
    assert history('perfis',values)['history']['hours']==2
    with sqlite3.connect(decision_source[1]) as c:
        c.execute('UPDATE production_rows SET sheet_hours=3 WHERE sheet_id=1')
        c.execute('UPDATE sheets SET revision=2 WHERE id=1')
    publish(decision_source)
    for a in planning.AREAS:projection.rebuild(a)
    assert history('perfis',values)['source'] is None
