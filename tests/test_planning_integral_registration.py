import uuid
from pathlib import Path

import psycopg
import pytest

from app import planning, planning_needs as needs, planning_catalogs as catalogs
from app.raw import projection, query, edits, contracts
from tests.test_raw_workspace import workspace, database, canonical, registry, postgres16
from tests.test_planning_needs import vals


@pytest.fixture()
def local_workspace(workspace):
    with psycopg.connect(workspace) as conn:
        conn.execute((Path(__file__).parents[1]/'sql/027_planning_local_orders.sql').read_text())
        conn.execute('TRUNCATE planning_mtg.local_orders CASCADE')
    return workspace


def test_new_of_ov_atomic_persistent_partial_edits_and_zero_initial(local_workspace):
    p={'request_id':str(uuid.uuid4()),'area':'perfis','production_order_no':'OF998877',
       'catalog_version':'s1','record_status':'draft','values':{**vals(),'abocardar':False},
       'local_order':{'expected_revision':0,'values':{'ov':'OV-NEW','customer':'Cliente local','designation':'Obra nova','delivery_date':'2026-10-15'}}}
    created=edits.prepare(p)
    assert edits.prepare(p)==created
    d=needs.detail(created['need_id'])
    assert d['local_order']['values_json']['ov']=='OV-NEW'
    projection.rebuild('perfis')
    row=query.listing({'area':'perfis','q':'OF998877'})['rows'][0]
    assert row['values']['customer']=='Cliente local'
    assert row['values']['cut']==0 and row['values']['remaining']==100
    assert row['values']['quantity_to_plan']==100 and row['values']['bars']==17
    assert row['calculation']['production_sources'][0]['origin']=='Condição inicial local'
    edited=edits.prepare({**p,'request_id':str(uuid.uuid4()),'need_id':created['need_id'],'expected_revision':created['revision'],
                          'values':{'quantity_required':120,'operation':'corte'},
                          'local_order':{'expected_revision':1,'values':{'designation':'Obra revista'}}})
    d=needs.detail(edited['need_id'])
    assert d['local_order']['values_json']['ov']=='OV-NEW'
    assert d['local_order']['values_json']['designation']=='Obra revista'
    assert d['need']['specification']['length_mm']==1000
    before=d['need']['revision']
    with pytest.raises(planning.PlanningError,match='dados desta OF mudaram'):
        edits.prepare({**p,'request_id':str(uuid.uuid4()),'need_id':edited['need_id'],'expected_revision':before,
                       'local_order':{'expected_revision':1,'values':{'designation':'Conflito'}}})
    assert needs.detail(edited['need_id'])['need']['revision']==before
    with planning.connect(readonly=True) as c:
        assert c.execute("SELECT count(*) n FROM planning_mtg.local_order_history WHERE production_order_no='OF998877'").fetchone()['n']==2
        assert c.execute("SELECT count(*) n FROM mes_kanban.production_records WHERE production_order='OF998877'").fetchone()['n']==0


@pytest.mark.parametrize('area',['perfis','cantoneiras'])
def test_editable_raw_contract_has_form_controls(local_workspace,area):
    visible={f['id'] for f in catalogs.catalog(area)['fields'] if f['editor_visible']}
    editable={f['id'] for f in contracts.fields(area) if f['editable']}
    assert editable-visible==set()
