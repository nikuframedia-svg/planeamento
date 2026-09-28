import uuid
import psycopg
import pytest
from psycopg.types.json import Jsonb

from app import planning, planning_hub as hub, planning_needs as needs, planning_raw
from app.raw import projection, query
from tests.test_raw_workspace import workspace, database, canonical, registry, postgres16
from tests.test_planning_needs import request, vals, save


def assert_raw_counts():
    expected={scope:{} for scope in ('active','history','all')}
    perfis_keys={}
    for area in ('perfis','cantoneiras'):
        projection.rebuild(area)
        for scope in expected:
            rows=query.listing({'area':area,'population':scope,'page_size':500})['rows']
            if area=='perfis':perfis_keys[scope]={r['key'] for r in rows}
            for row in rows:
                of=row['values']['of']
                expected[scope].setdefault(of,{}).setdefault(area,0)
                expected[scope][of][area]+=1
    for scope, counts in expected.items():
        observed=hub._order_population(population=scope)['orders']
        actual={r['of']:r['plan'] for r in observed if r['plan']}
        assert actual==counts
    old=planning_raw.dataset(force=True)
    for scope,keys in perfis_keys.items():
        assert {r['key'] for r in planning_raw.filtered(old,{'population':scope})}==keys


def test_macro_order_without_cpis_is_searchable_and_normalized(workspace):
    with psycopg.connect(workspace) as conn:
        conn.execute('DELETE FROM raw_mtg.cpis_rows')
        conn.execute("UPDATE raw_mtg.plan_production_rows SET production_order_no='4200'")
        conn.execute("UPDATE analytics_mtg.kanban_plan_lines SET production_order_no='4200'")
    found=hub.list_orders(query='REF-A')['orders']
    assert len(found)==1 and found[0]['of']=='OF4200'
    assert found[0]['administrative_origin']=='Macro — sem contexto CPIS'
    assert found[0]['status_values']==[] and found[0]['plan']=={'perfis':2,'cantoneiras':1}
    detail=hub.order_detail('4200')
    assert len(detail['plan_lines'])==3 and detail['context']['cpis_status'] is None
    assert len(planning.order_lines('perfis','4200')['lines'])==2
    assert hub.list_orders(state='open')['total']==0  # no invented CPIS state
    assert_raw_counts()


def test_local_order_and_piece_are_counted_and_found_by_reference(workspace):
    n=needs.resolve(request(area='perfis',production_order_no='OF998877',values=vals()))
    save(n)
    result=hub.list_orders(query='NEW-A')['orders']
    assert len(result)==1 and result[0]['of']=='OF998877'
    assert result[0]['plan']=={'perfis':1}
    assert result[0]['administrative_origin']=='Manual local'
    assert hub.order_detail('998877')['preparations'][0]['component_ref']=='NEW-A'
    assert hub.list_orders(population='history',query='998877')['total']==0
    assert_raw_counts()


def test_invalid_source_order_is_visible_without_inventing_identity(workspace):
    with psycopg.connect(workspace) as conn:
        conn.execute("UPDATE raw_mtg.plan_production_rows SET production_order_no='P' WHERE source_line_id='c1:10'")
        conn.execute("UPDATE analytics_mtg.kanban_plan_lines SET production_order_no='P' WHERE plan_key='c1:10'")
    unknown=next(r for r in hub.list_orders()['orders'] if r['of'] is None)
    assert unknown['unidentified'] and unknown['plan']=={'cantoneiras':1}
    assert unknown['raw_links'][0]['key']=='macro:c1:10'
    assert all(r['of'] for r in planning.search_orders('cantoneiras')['orders'])
    assert_raw_counts()


def test_associated_origins_close_one_identity_without_hiding_local_work(workspace):
    linked=needs.resolve(request(area='perfis',source={'kind':'plan_line','id':'s1:10'}))
    # A second explicit source of the same need; closure is not inferred from its quantities.
    with planning.connect() as conn:
        second=needs.source_data({'kind':'plan_line','id':'s1:11'},'perfis',conn)
        conn.execute('INSERT INTO planning_mtg.need_sources(kind,source_id,need_id,version,payload) VALUES(%s,%s,%s,%s,%s)',
            ('plan_line','s1:11',linked['need_id'],'s1',Jsonb({**second,'area':'perfis'})))
    with psycopg.connect(workspace) as conn:
        conn.execute("UPDATE raw_mtg.plan_production_rows SET closed_x=true WHERE source_line_id='s1:11'")
    local=needs.resolve(request(area='perfis',production_order_no='OF4200',values=vals()))
    save(local)
    active=hub.list_orders()['orders'][0]
    assert active['plan']=={'perfis':1,'cantoneiras':1}
    assert hub.list_orders(population='history')['orders'][0]['plan']=={'perfis':1}
    assert planning.order_lines('perfis','4200')['lines']==[]
    history=planning.order_lines('perfis','4200',population='history')['lines']
    assert {r['plan_key'] for r in history}=={'s1:10','s1:11'}
    assert {r['planning_key'] for r in history}=={linked['need_id']}
    assert {r['id'] for r in needs.list_needs('4200',area='perfis')['needs']}=={local['need_id']}
    assert {r['id'] for r in needs.list_needs('4200',area='perfis',population='history')['needs']}=={linked['need_id']}
    assert {r['id'] for r in needs.list_needs('4200',area='perfis',population='all')['needs']}=={linked['need_id'],local['need_id']}
    assert_raw_counts()
    with psycopg.connect(workspace) as conn:
        # Reopening is a new immutable import, not a mutation under an old hash.
        for previous,current in [('s1','s2'),('c1','c2')]:
            conn.execute("INSERT INTO audit_mtg.snapshots SELECT %s,dataset_id,source_filename,source_path,source_sha256||'-reopened',now()+interval '1 second' FROM audit_mtg.snapshots WHERE snapshot_id=%s",(current,previous))
            for table in ['raw_mtg.plan_production_rows','analytics_mtg.kanban_plan_lines',
                          'core_mtg.production_orders','raw_mtg.cpis_rows',
                          'raw_mtg.other_sheet_rows','raw_mtg.machine_rows','core_mtg.machines']:
                for (data,) in conn.execute('SELECT to_jsonb(t) FROM '+table+' t WHERE snapshot_id=%s',(previous,)).fetchall():
                    data['snapshot_id']=current
                    for key in ['source_line_id','plan_key']:
                        if data.get(key):data[key]=data[key].replace(previous+':',current+':',1)
                    if 'closed_x' in data:data['closed_x']=False
                    conn.execute('INSERT INTO '+table+' SELECT * FROM jsonb_populate_record(NULL::'+table+',%s)',(Jsonb(data),))
        assert conn.execute("SELECT closed_x FROM raw_mtg.plan_production_rows WHERE source_line_id='s1:11'").fetchone()[0] is True
    assert hub.list_orders(population='history')['total']==0
    assert hub.list_orders()['orders'][0]['plan']=={'perfis':2,'cantoneiras':1}
    assert len(needs.list_needs('4200',area='perfis')['needs'])==2
    assert_raw_counts()
