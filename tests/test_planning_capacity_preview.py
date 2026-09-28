"""F12 is the whole physical resource/week, including both areas, without writes."""
import uuid
import pytest
import psycopg
from psycopg.types.json import Jsonb
from app import planning
from app.raw import preview,projection,capacity_revision as capacity,objects,edits,query
from tests.test_raw_workspace import workspace,database,canonical,registry,postgres16
from tests.test_planning_needs import vals


def cmd(**kw):return {'request_id':str(uuid.uuid4()),**kw}


def payload(area,of,q,reference):
    v={**vals(),'component_ref':reference,'quantity_required':q,'abocardar':False,'expected_date':'2026-09-23'}
    if area=='cantoneiras':v={'component_ref':reference,'quantity_required':q,'length_mm':2000,
        'material_type':'Cantoneira','profile':'L TEST','operation':'112','machine':'Ficep XP T4','expected_date':'2026-09-23'}
    return {'area':area,'production_order_no':of,'catalog_version':'s1' if area=='perfis' else 'c1','values':v}


def resource(name,aliases):
    r=objects.save(cmd(name=name,definition={'aliases':aliases,'operations':['corte','112','abocardar'],'confirmed':True}),'resource')
    for alias in aliases:
        objects.save(cmd(name=name+' '+alias['area'],definition={'resource_id':r['id'],'area':alias['area'],
            'operation':'corte' if alias['area']=='perfis' else '112','method':'units_hour',
            'value':10 if alias['area']=='perfis' else 20,'valid_from':'2026-01-01','confirmed':True}),'rate')
    for week in [39,40]:objects.save(cmd(name=name+' week '+str(week),definition={'resource_id':r['id'],
        'year':2026,'week':week,'shifts':2,'hours_per_shift':7.5,'exception_hours':1,'confirmed':True}),'calendar')
    return r


@pytest.fixture()
def shared(workspace):
    with psycopg.connect(workspace) as c:
        c.execute('TRUNCATE mes_kanban.validated_sheets CASCADE')
        c.execute("INSERT INTO raw_mtg.other_sheet_rows VALUES ('c1','Dados',3,%s),('c1','Tabela pesos',3,%s)",
            (Jsonb({'values':[None,'Ficep XP T4',None,None,'Cantoneira',None,None,112,'CORTE']}),Jsonb({'values':[None,'L TEST',3]})))
        c.execute("INSERT INTO raw_mtg.other_sheet_rows VALUES ('s1','Dados',4,%s)",(Jsonb({'values':[None,'OTHER',None,None,'Tubo redondo']}),))
        # Existing macro pieces must not add unspecified load to this fixture resource.
        c.execute("UPDATE raw_mtg.plan_production_rows SET closed_x=true")
    machine=resource('Shared',[{'area':'perfis','name':'MEBA'},{'area':'cantoneiras','name':'Ficep XP T4'}])
    other=resource('Other',[{'area':'perfis','name':'OTHER'}])
    for area in planning.AREAS:projection.rebuild(area)
    saved=[]
    for area,of,q,ref in [('perfis','9901',20,'ONE'),('perfis','9902',80,'PEER'),('cantoneiras','9903',100,'CROSS')]:
        p=payload(area,of,q,ref);n=edits.prepare(cmd(**p));saved.append((p,n))
    capacity.rebuild()
    return machine,other,saved


def count_writes():
    with planning.connect(readonly=True) as c:
        return {table:c.execute('SELECT count(*) n FROM planning_mtg.'+table).fetchone()['n'] for table in
            ('raw_generations','raw_contents','raw_members','raw_signals','raw_jobs','needs','records','record_versions','need_events','need_commands','audit_outbox')}


def test_geometry_restoration_preview_keeps_normalized_cantoneiras_counter(workspace):
    with psycopg.connect(workspace) as c:
        c.execute("INSERT INTO raw_mtg.other_sheet_rows VALUES('c1','Dados',3,%s)",(Jsonb({'values':[None,'Ficep',None,None,'Cantoneira',None,None,112,'Corte']}),))
        c.execute("UPDATE raw_mtg.plan_production_rows SET quantity_made=3,row_data=row_data||%s WHERE snapshot_id='c1'",(Jsonb({'1ª Oper.':112,'Maq.':None,'Des. Material':'Descrição importada'}),))
        c.execute("UPDATE analytics_mtg.kanban_plan_lines SET quantity_made=3 WHERE snapshot_id='c1'")
    for area in planning.AREAS:projection.rebuild(area)
    capacity.rebuild()
    imported=query.listing({'area':'cantoneiras','population':'all'})['rows'][0]
    saved=edits.prepare(cmd(area='cantoneiras',catalog_version='c1',source={'kind':'plan_line','id':imported['plan_key']},values={'operation':'112'}))
    length=imported['values']['length_mm']
    changed=edits.prepare(cmd(area='cantoneiras',catalog_version='c1',need_id=saved['need_id'],expected_revision=saved['revision'],values={'length_mm':length+1}))
    p={'area':'cantoneiras','catalog_version':'c1','need_id':changed['need_id'],'expected_revision':changed['revision'],'values':{'length_mm':length}}
    result=preview.preview(p)
    assert result['row']['values']['made']==3
    assert result['row']['values']['remaining']==imported['values']['quantity_required']-3
    saved=edits.prepare(cmd(**p))
    current=query.listing({'area':'cantoneiras','population':'all','selected':[saved['need_id']]})['rows'][0]
    for field in ['made','remaining','material_description','original_description']:
        assert current['values'][field]==result['row']['values'][field]


def edit_payload(saved,**changes):
    p,n=saved
    return {**p,'need_id':n['need_id'],'expected_revision':n['revision'],'values':{**p['values'],**changes}}


def verify_save(preview_payload,result):
    saved=edits.prepare(cmd(**preview_payload));capacity.rebuild()
    row=query.listing({'area':preview_payload['area'],'selected':[saved['need_id']]})['rows'][0]
    for name in ['remaining','quantity_to_plan','theoretical_hours','hours_pct','rate_source','applied_rate_value']:
        assert row['values'][name]==pytest.approx(result['row']['values'][name]) if isinstance(row['values'][name],float) else row['values'][name]==result['row']['values'][name]
    return row


@pytest.mark.parametrize('area,index,q,expected_hours,load',[('perfis',0,40,4,17),('cantoneiras',2,60,3,13)])
def test_quantity_preview_matches_save_and_counts_shared_area_once(shared,area,index,q,expected_hours,load):
    machine,other,saved=shared;p=edit_payload(saved[index],quantity_required=q)
    before=count_writes();result=preview.preview(p);assert count_writes()==before
    v=result['row']['values'];assert v['theoretical_hours']==expected_hours
    assert v['hours_pct']==pytest.approx(load/14*100)
    display=next(r for r in result['results'] if r['field']=='hours_pct')
    assert display['value']==v['hours_pct'] and display['unit']=='%'
    period=next(r for r in result['capacity_preview']['weekly'] if r['key']==machine['id']+'|2026|39')
    assert period['values']['lines_total']==3 and period['values']['planned_hours']==load
    assert result['capacity_preview']['saved'] is False
    verify_save(p,result)


def test_move_machine_and_week_removes_old_load_and_uses_new_calendar(shared):
    machine,other,saved=shared;p=edit_payload(saved[0],quantity_required=40,machine='OTHER',expected_date='2026-09-30')
    result=preview.preview(p);periods={r['key']:r for r in result['capacity_preview']['weekly']}
    assert periods[machine['id']+'|2026|39']['values']['planned_hours']==13
    assert periods[other['id']+'|2026|40']['values']['planned_hours']==4
    assert result['row']['values']['hours_pct']==pytest.approx(400/14)
    verify_save(p,result)


def test_preview_uses_new_peer_revision_before_capacity_worker_runs(shared):
    machine,other,saved=shared
    p=edit_payload(saved[1],quantity_required=40)
    edits.prepare(cmd(**p))  # Durable RAW already current; capacity still says peer80.
    result=preview.preview(edit_payload(saved[0],quantity_required=40))
    assert result['row']['values']['hours_pct']==pytest.approx(1300/14)  #4+4+5


def test_new_piece_preview_adds_once_and_is_read_only(shared):
    machine,other,saved=shared;p=payload('perfis','9910',30,'NEW')
    before=count_writes();result=preview.preview(p);assert count_writes()==before
    assert result['row']['values']['hours_pct']==pytest.approx(1800/14)  #2+8+5+3
    verify_save(p,result)


def test_zero_availability_and_unknown_peer_load_remain_unknown(shared):
    machine,other,saved=shared
    with planning.connect(readonly=True) as c:
        calendar=c.execute("SELECT * FROM planning_mtg.raw_objects WHERE kind='calendar' AND definition->>'resource_id'=%s AND definition->>'week'='39'",(machine['id'],)).fetchone()
    objects.save(cmd(id=str(calendar['id']),expected_revision=calendar['revision'],name='Zero',
        definition={**calendar['definition'],'shifts':0,'exception_hours':0}),'calendar')
    result=preview.preview(edit_payload(saved[0],quantity_required=40))
    assert result['row']['values']['hours_pct'] is None
    assert result['row']['calculation']['rules']['hours_pct']['reason']
    # No positive availability must not be displayed as0% occupancy.
    assert result['row']['values']['theoretical_hours']==4


def test_unknown_peer_load_does_not_become_zero_occupancy(shared):
    _,_,saved=shared
    edits.prepare(cmd(**payload('perfis','9911',None,'UNKNOWN-PEER')))
    result=preview.preview(edit_payload(saved[0],quantity_required=40))
    assert result['row']['values']['theoretical_hours']==4
    assert result['row']['values']['hours_pct'] is None
    assert result['row']['calculation']['rules']['hours_pct']['inputs']['available_hours']==14
    assert result['row']['calculation']['rules']['hours_pct']['inputs']['planned_hours'] is None


def test_source_pending_or_closed_of_never_claims_current_occupancy(shared,workspace):
    machine,other,saved=shared
    with psycopg.connect(workspace) as c:
        c.execute("INSERT INTO mes_kanban.validated_sheets(sheet_uid,sheet_date,template_name,family,operator_name,image_sha256,raw_extraction,sheet_data,validated_by,source_app) VALUES ('pending-preview','2026-09-23','t','perfis','test','hash','{}','{}','test','kanban-mes-mtg2')")
    result=preview.preview(edit_payload(saved[0],quantity_required=40))
    assert result['capacity_preview']['available'] is False and 'atualização' in result['capacity_preview']['reason']
    assert result['row']['values']['hours_pct'] is None
    # A new manual piece under an already closed CPIS order is also excluded.
    with psycopg.connect(workspace) as c:c.execute("UPDATE raw_mtg.cpis_rows SET status='Fechada' WHERE production_order_no='OF4200'")
    result=preview.preview(payload('perfis','4200',30,'CLOSED-NEW'))
    assert not result['row']['population']['active'] and result['row']['values']['hours_pct'] is None


def test_secondary_preparation_preserves_primary_and_shared_occupancy(shared,workspace):
    machine,other,saved=shared
    with psycopg.connect(workspace) as c:
        c.execute("INSERT INTO raw_mtg.other_sheet_rows VALUES ('c1','Dados',4,%s),('c1','Dados',5,%s)",
            (Jsonb({'values':[None,None,None,None,None,None,None,'2ª Operação']}),Jsonb({'values':[None,None,None,None,None,None,None,209,'ALARGAR']})))
    objects.save(cmd(id=machine['id'],expected_revision=machine['revision'],name='Shared',
        definition={**machine['definition'],'operations':['corte','112','209']}),'resource')
    objects.save(cmd(name='Secondary rate',definition={'resource_id':machine['id'],'area':'cantoneiras',
        'operation':'209','method':'units_hour','value':40,'valid_from':'2026-01-01','confirmed':True}),'rate')
    p=edit_payload(saved[2],operation_detail='209');first=edits.prepare(cmd(**p))
    second=edits.prepare(cmd(**{**p,'expected_revision':first['revision'],'values':{**p['values'],'operation':'209'}}))
    capacity.rebuild()
    row=query.listing({'area':'cantoneiras','selected':[second['need_id']]})['rows'][0]
    assert row['values']['operation']=='112' and row['values']['theoretical_hours']==5
    assert row['values']['hours_pct']==pytest.approx(1750/14)  #2+8+5+2.5
    proposed={**p,'expected_revision':second['revision'],'values':{**p['values'],'quantity_required':60,'operation':'209'}}
    result=preview.preview(proposed)
    assert result['row']['values']['operation']=='112'
    assert {e['operation']:e['hours'] for e in result['row']['calculation']['operation_estimates']}=={'112':3,'209':1.5}
    assert result['row']['values']['hours_pct']==pytest.approx(1450/14)
    verify_save(proposed,result)
