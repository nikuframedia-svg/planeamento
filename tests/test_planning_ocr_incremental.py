"""OCR revisions: affected OF closure, deletion, durability and full equivalence."""
import uuid
import psycopg
import pytest
from psycopg.types.json import Jsonb
from app import planning,planning_needs as needs,planning_associations as assoc
from app.raw import projection,query,capacity_revision as capacity,edits
from tests.test_raw_workspace import workspace,database,canonical,registry,postgres16
from tests.test_planning_needs import vals,request,save


@pytest.fixture(autouse=True)
def isolated_source_facts(workspace):
    with psycopg.connect(workspace) as c:
        c.execute('TRUNCATE mes_kanban.validated_sheets CASCADE')


def source(conn,area='perfis',of='4200',key=None,profile=None,length=None):
    uid='ocr-delta-'+uuid.uuid4().hex
    app='kanban-mes-mtg2' if area=='perfis' else 'kanban-mes'
    key=key or ('s1:11' if area=='perfis' else 'c1:10')
    profile=profile or ('108x3' if area=='perfis' else 'L80x80x6')
    length=length or (3003 if area=='perfis' else 5291)
    conn.execute("INSERT INTO mes_kanban.validated_sheets(sheet_uid,sheet_date,template_name,family,operator_name,image_sha256,raw_extraction,sheet_data,validated_by,source_app) VALUES (%s,'2026-09-22','t',%s,'Teste','hash','{}','{}','Teste',%s)",(uid,area,app))
    rid=conn.execute("INSERT INTO mes_kanban.production_records(sheet_uid,row_index,sheet_date,family,operator_name,production_order,quantity,machine,model_ref,length_mm,profile_type,matched_plan_key,plan_snapshot_id,validated_at,hours_worked) VALUES (%s,0,'2026-09-22',%s,'Teste',%s,10,%s,'REF-A',%s,%s,%s,%s,now(),2) RETURNING id",
        (uid,area,of,'MEBA' if area=='perfis' else 'Ficep XP T4',length,profile,key,'s1' if area=='perfis' else 'c1')).fetchone()[0]
    return rid,uid


def test_source_fact_uses_first_matching_sheet_row_and_preserves_identity(workspace):
    identity={'production_order_no':'OF4200','component_ref':'REF-A','profile_type':'108x3','length_mm':3003}
    refs=[{'plan_key':'s1:11','quantity':10}]
    with psycopg.connect(workspace) as c:
        rid,uid=source(c)
        c.execute('UPDATE mes_kanban.validated_sheets SET cross_check=%s WHERE sheet_uid=%s',
            (Jsonb({'rows':[{'row_index':1,'plan_identity':{'wrong':1}},
                {'row_index':'0','plan_identity':{'wrong':'string index'}},
                {'row_index':[0],'plan_identity':{'wrong':'array index'}},
                {'row_index':0,'plan_identity':identity,'plan_refs':refs},
                {'row_index':0,'plan_identity':{'wrong':'later duplicate'}}]}),uid))
    with planning.connect(readonly=True) as c:
        fact=next(r for r in projection.source_facts(c,'perfis') if r['id']==rid)
    assert fact['frozen_identity']==identity and fact['plan_refs']==refs
    assert fact['of']=='OF4200' and 'cross_check_row' not in fact and 'cross_check' not in fact


def test_scoped_administrative_context_keeps_conflicting_cpis_copies(workspace):
    from app import planning_hub as hub
    with psycopg.connect(workspace) as c:
        c.execute("UPDATE raw_mtg.cpis_rows SET status='Fechada' WHERE snapshot_id='c1'")
        # Decisão de 06/10/2026: a cópia mais recente (c1) decide o estado da OF.
        c.execute("UPDATE audit_mtg.snapshots SET loaded_at=loaded_at+interval '1 minute' WHERE snapshot_id='c1'")
    with planning.connect() as c:
        direct=hub._direct_version(c)
        copies=hub._order_rows(c,direct,'',None,only_ofs=['OF4200'])
        assert {r['status'] for r in copies}=={'Em Produção','Fechada'}
        assert hub._order_rows(c,direct,'',None,only_ofs=['OF9999'])==[]
        full,_,_=projection.build_rows(c,'perfis')
        scoped,_,_=projection.build_rows(c,'perfis',orders=['OF4200'])
    assert scoped==[r for r in full if r['values']['of']=='OF4200']
    assert scoped and all(not r['population']['active'] for r in scoped)


def contents(area):
    output={}
    with planning.connect(readonly=True) as c:
        for ds in ['planning','production','production_hours','orders','capacity','capacity_items','capacity_machines']:
            gen=query.generation(c,area,dataset=ds);base,args=query.source(gen)
            rows={r['row_key']:{**r['detail'],'values':r['values_json']} for r in c.execute('SELECT m.row_key,c.detail,c.values_json'+base,args)}
            for row in rows.values():
                for rule in row.get('calculation',{}).get('rules',{}).values():rule.pop('capacity_fingerprint',None)
            output[ds]=rows
    return output


def coherent_capacity(**kwargs):
    # Production now requires both current areas, as does the actual worker.
    for area in planning.AREAS:projection.rebuild(area)
    return capacity.rebuild(**kwargs)


def update(area):
    gen=projection.rebuild(area)
    assert gen['metadata']['calculation_scope']=='ocr_orders'
    coherent_capacity()
    before=contents(area)
    full=projection.rebuild(area,force=True)
    assert full['id']!=gen['id']
    coherent_capacity(force=True)
    actual=contents(area)
    def differences(a,b,path=''):
        if isinstance(a,dict) and isinstance(b,dict):
            return [d for k in a.keys()|b.keys() for d in differences(a.get(k),b.get(k),path+'/'+str(k))]
        return [(path,a,b)] if a!=b else []
    assert actual==before,differences(actual,before)[:15]
    return gen,before


@pytest.mark.parametrize('area',['perfis','cantoneiras'])
def test_new_corrected_and_deleted_ocr_equal_full_with_immutable_old_version(workspace,area):
    if area=='cantoneiras':
        with psycopg.connect(workspace) as c:c.execute("UPDATE raw_mtg.plan_production_rows SET row_data=row_data||'{\"1ª Oper.\":112}' WHERE snapshot_id='c1'")
    projection.rebuild(area);coherent_capacity()
    old=query.listing({'area':area,'population':'all'})
    with psycopg.connect(workspace) as c:rid,uid=source(c,area)
    gen,data=update(area)
    assert gen['metadata']['updated_orders']==['OF4200']
    key='macro:s1:11' if area=='perfis' else 'macro:c1:10'
    assert data['planning'][key]['values']['remaining']==90
    with psycopg.connect(workspace) as c:c.execute('UPDATE mes_kanban.production_records SET quantity=25,hours_worked=4 WHERE id=%s',(rid,))
    _,data=update(area)
    assert data['planning'][key]['values']['remaining']==75
    assert data['production_hours'][uid]['values']['hours_worked']==4
    with psycopg.connect(workspace) as c:c.execute('DELETE FROM mes_kanban.production_records WHERE id=%s',(rid,))
    _,data=update(area)
    assert data['planning'][key]['values']['remaining']==36  # Excel provisional restored.
    assert not any(r['record_id']==rid for r in data['production'].values())
    assert query.listing({'area':area,'population':'all','version':old['version']})['rows']==old['rows']


def test_moved_record_refreshes_previous_of_and_new_of_without_touching_third(workspace):
    for of in ['4201','4202']:save(needs.resolve(request(area='perfis',production_order_no=of,values=vals())))
    with psycopg.connect(workspace) as c:rid,uid=source(c)
    projection.rebuild('perfis');coherent_capacity();before=contents('perfis')
    with psycopg.connect(workspace) as c:c.execute("UPDATE mes_kanban.production_records SET production_order='4201' WHERE id=%s",(rid,))
    third=next(k for k,r in before['planning'].items() if r['values']['of']=='OF4202')
    projection.rebuild('perfis')
    assert contents('perfis')['planning'][third]==before['planning'][third]
    gen,data=update('perfis')
    assert gen['metadata']['updated_orders']==['OF4200','OF4201']
    assert data['planning']['macro:s1:11']['values']['remaining']==36
    # Capacity may revise the common machine's historical-rate provenance.
    assert data['planning'][third]['values']['remaining']==before['planning'][third]['values']['remaining']
    assert next(r for r in data['production'].values() if r['record_id']==rid)['values']['of']=='OF4201'


def test_frozen_unknown_order_and_header_only_revision_use_same_identity(workspace):
    with psycopg.connect(workspace) as c:
        rid,uid=source(c,of=None)
        c.execute('UPDATE mes_kanban.validated_sheets SET cross_check=%s WHERE sheet_uid=%s',
            (Jsonb({'rows':[{'row_index':0,'plan_identity':{'production_order_no':'OF4200'}}]}),uid))
    projection.rebuild('perfis');coherent_capacity()
    with psycopg.connect(workspace) as c:
        c.execute('UPDATE mes_kanban.validated_sheets SET sheet_no=54321 WHERE sheet_uid=%s',(uid,))
    gen,data=update('perfis');assert gen['metadata']['updated_orders']==['OF4200']
    assert next(r for r in data['production'].values() if r['record_id']==rid)['values']['sheet']==54321
    # A record with no usable OF remains a diagnostic event; it cannot touch a random piece.
    with psycopg.connect(workspace) as c:
        c.execute("UPDATE mes_kanban.production_records SET matched_plan_key=NULL,extra='{}' WHERE id=%s",(rid,))
        c.execute("UPDATE mes_kanban.validated_sheets SET cross_check='{}' WHERE sheet_uid=%s",(uid,))
    _,data=update('perfis');assert data['planning']['macro:s1:11']['values']['remaining']==36
    with psycopg.connect(workspace) as c:c.execute('UPDATE mes_kanban.production_records SET quantity=33 WHERE id=%s',(rid,))
    gen,data=update('perfis');assert gen['metadata']['updated_orders']==[]
    assert next(r for r in data['production'].values() if r['record_id']==rid)['values']['quantity']==33


def test_expanded_children_revision_and_removal_equal_full(workspace):
    with psycopg.connect(workspace) as c:
        rid,uid=source(c)
        c.execute('UPDATE mes_kanban.production_records SET full_profile=true WHERE id=%s',(rid,))
        c.execute("INSERT INTO mes_kanban.production_record_plan_refs(production_record_id,sheet_uid,row_index,plan_snapshot_id,plan_key,assumed_quantity,remaining_before,remaining_rule) VALUES(%s,%s,0,'s1','s1:11',10,100,'test')",(rid,uid))
    projection.rebuild('perfis');coherent_capacity()
    with psycopg.connect(workspace) as c:c.execute('UPDATE mes_kanban.production_record_plan_refs SET assumed_quantity=27 WHERE production_record_id=%s',(rid,))
    _,data=update('perfis');assert data['planning']['macro:s1:11']['values']['remaining']==73
    with psycopg.connect(workspace) as c:c.execute('DELETE FROM mes_kanban.production_record_plan_refs WHERE production_record_id=%s',(rid,))
    update('perfis')


def test_revision_invalidates_human_allocation_to_another_of(workspace):
    n=save(needs.resolve(request(area='perfis',production_order_no='4201',values=vals())))
    with psycopg.connect(workspace) as c:rid,uid=source(c,of=None)
    with planning.connect(readonly=True) as c:fact=assoc.fact(c,rid)
    assoc.save(request(production_record_id=rid,expected_revision=0,evidence_hash=needs.digest(fact),reason='Conferido',
        allocations=[{'need_id':n['need_id'],'operation_id':n['operation_id'],'expected_need_revision':n['revision'],'quantity':10}]))
    projection.rebuild('perfis');coherent_capacity()
    with psycopg.connect(workspace) as c:c.execute('UPDATE mes_kanban.production_records SET quantity=20 WHERE id=%s',(rid,))
    gen,data=update('perfis');assert gen['metadata']['updated_orders']==['OF4200','OF4201']
    event=next(r for r in data['production'].values() if r['record_id']==rid)
    assert event['values']['association_status']=='compatibility_review' and event['planning_keys']==[]


def test_failure_keeps_old_generations_and_retry_is_idempotent(workspace,monkeypatch):
    projection.rebuild('perfis');coherent_capacity();before=contents('perfis')
    with psycopg.connect(workspace) as c:rid,uid=source(c)
    original=projection.publish_delta
    def fail(conn,dataset,*args,**kw):
        if dataset=='planning:perfis':raise RuntimeError('Injected OCR publication failure')
        return original(conn,dataset,*args,**kw)
    monkeypatch.setattr(projection,'publish_delta',fail)
    with pytest.raises(RuntimeError,match='Injected OCR'):projection.rebuild('perfis')
    assert contents('perfis')==before
    monkeypatch.setattr(projection,'publish_delta',original)
    gen=projection.rebuild('perfis')
    assert projection.rebuild('perfis')['id']==gen['id']
    assert query.listing({'selected':['macro:s1:11']})['rows'][0]['values']['remaining']==90


def test_complete_local_edit_rebases_checkpoint_and_need_revision_uses_source_scope(workspace):
    projection.rebuild('perfis');projection.rebuild('cantoneiras')
    row=query.listing({'selected':['macro:s1:11']})['rows'][0]
    edits.update_batch(request(area='perfis',version=query.listing({})['version'],
        edits=[{'key':row['key'],'expected_revision':0,'values':{'notes':'Confirmed locally'}}]))
    with psycopg.connect(workspace) as c:source(c)
    gen=projection.rebuild('perfis');assert gen['metadata']['calculation_scope']=='ocr_orders'
    # Unpublished local identity revisions must never be disguised as an OCR-only delta.
    with planning.connect() as c:c.execute('UPDATE planning_mtg.needs SET revision=revision+1')
    revised=projection.rebuild('perfis')
    assert revised['metadata']['calculation_scope']=='source_orders'
    assert revised['metadata']['updated_orders']==['OF4200']


def test_removed_human_associated_record_rebuilds_with_unknown_balance(workspace):
    n=save(needs.resolve(request(area='perfis',production_order_no='4201',values=vals())))
    with psycopg.connect(workspace) as c:rid,uid=source(c,of=None)
    with planning.connect(readonly=True) as c:fact=assoc.fact(c,rid)
    assoc.save(request(production_record_id=rid,expected_revision=0,evidence_hash=needs.digest(fact),reason='Conferido',
        allocations=[{'need_id':n['need_id'],'operation_id':n['operation_id'],'expected_need_revision':n['revision'],'quantity':10}]))
    projection.rebuild('perfis');coherent_capacity()
    with psycopg.connect(workspace) as c:
        c.execute('DELETE FROM mes_kanban.production_records WHERE id=%s',(rid,))
    gen,data=update('perfis')
    row=data['planning'][n['need_id']]
    assert row['values']['cut'] is None and row['values']['remaining'] is None
    assert any(str(rid) in warning and 'produção validada' in warning for warning in row['warnings'])
    with planning.connect(readonly=True) as c:assert assoc.latest(c,rid)['status']=='associated'
