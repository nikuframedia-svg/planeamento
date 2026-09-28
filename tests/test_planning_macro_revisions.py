"""Real import IDs change with a file hash; identical evidence remains usable."""
import uuid
import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from app import planning,planning_needs as needs
from app.raw import projection,query,capacity_revision as capacity,edits
from tests.test_raw_workspace import workspace,database,canonical,registry,postgres16


def import_copy(dsn,area,target,*,closed=False):
    with psycopg.connect(dsn,row_factory=dict_row) as c:
        previous=planning.snapshot(c,area)['snapshot_id']
        c.execute("INSERT INTO audit_mtg.snapshots SELECT %s,dataset_id,source_filename,source_path,source_sha256,now()+interval '1 second' FROM audit_mtg.snapshots WHERE snapshot_id=%s",(target,previous))
        for table in ('raw_mtg.plan_production_rows','analytics_mtg.kanban_plan_lines','core_mtg.production_orders','raw_mtg.cpis_rows','raw_mtg.other_sheet_rows','raw_mtg.machine_rows'):
            schema,name=table.split('.')
            cols=[r['column_name'] for r in c.execute('SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position',(schema,name))]
            expressions=['%s' if k=='snapshot_id' else '%s||source_line_id' if k=='source_line_id' else '%s||plan_key' if table=='analytics_mtg.kanban_plan_lines' and k=='plan_key' else k for k in cols]
            params=[]
            for k in cols:
                if k=='snapshot_id':params.append(target)
                elif k=='source_line_id' or table=='analytics_mtg.kanban_plan_lines' and k=='plan_key':params.append(target+':')
            c.execute('INSERT INTO '+table+' SELECT '+','.join(expressions)+' FROM '+table+' WHERE snapshot_id=%s',params+[previous])
        if closed:
            c.execute("UPDATE raw_mtg.plan_production_rows SET closed_x=true,row_data=row_data||%s WHERE snapshot_id=%s",(Jsonb({'Fechado':'X'}),target))


@pytest.mark.parametrize('area',['perfis','cantoneiras'])
def test_rekeyed_macro_preserves_unchanged_rows_and_rebinds_edits(workspace,area):
    # An old confirmation belongs to another snapshot and has no effect on
    # either the before or after population. It must not force a full rebuild.
    with planning.connect() as c:
        c.execute("INSERT INTO planning_mtg.raw_objects(id,kind,name,area,definition,actor) VALUES(%s,'period','Inactive historical week',%s,%s,'Macro regression')",
                  (uuid.uuid4(),area,Jsonb({'snapshot':'older-snapshot','week':39,'year':2026,'confirmed':True})))
    for a in planning.AREAS:projection.rebuild(a)
    capacity.rebuild()
    old=query.listing({'area':area,'population':'all'})
    old_keys={r['key'] for r in old['rows']}
    target='new-'+area
    import_copy(workspace,area,target)
    for a in planning.AREAS:projection.rebuild(a)
    capacity.rebuild()
    current=query.listing({'area':area,'population':'all'})
    assert {r['key'] for r in current['rows']}==old_keys
    assert not current['aggregates_pending']
    with planning.connect(readonly=True) as c:
        gen=query.generation(c,area)
        assert gen['metadata']['calculation_scope']=='source_orders'
        assert gen['metadata']['macro_evidence_reuse']['verified_snapshot']==target
        assert query.generation(c,area,dataset='capacity')['metadata']['calculation_scope']=='resources'
        first=old['rows'][0]
        resolved=needs.source_data({'kind':'plan_line','id':first['plan_key'],'version':first['calculation']['macro_snapshot']},area,c)
        assert resolved['version']==target and resolved['id'].startswith(target+':')
    changed=edits.update_batch({'request_id':str(uuid.uuid4()),'area':area,'version':current['version'],
        'edits':[{'key':first['key'],'expected_revision':first['revision'],'values':{'notes':'After a byte-equivalent macro revision'}}]})
    assert changed['publication']['status']=='published'
    assert query.listing({'area':area,'population':'all','selected':[changed['items'][0]['need_id']]})['rows'][0]['values']['notes']=='After a byte-equivalent macro revision'
    assert query.listing({'area':area,'version':old['version'],'population':'all'})['rows']==old['rows']


def test_changed_imported_facts_do_not_pass_as_byte_equivalent(workspace):
    projection.rebuild('perfis');old=query.listing({'area':'perfis','population':'all'})['rows'][0]
    import_copy(workspace,'perfis','changed',closed=True)
    with planning.connect(readonly=True) as c:
        with pytest.raises(planning.PlanningError,match='mudou'):
            needs.source_data({'kind':'plan_line','id':old['plan_key'],'version':old['calculation']['macro_snapshot']},'perfis',c)
    gen=projection.rebuild('perfis')
    assert gen['metadata']['calculation_scope']=='source_orders' and gen['metadata']['updated_orders']==['OF4200']
    history=query.listing({'area':'perfis','population':'history'})
    assert history['total']==2 and all('Macro' in r['population']['closed_sources'] for r in history['rows'])


def test_engine_revision_cannot_reuse_unchanged_source_manifests(workspace,monkeypatch):
    from app.raw import calculations
    before=projection.rebuild('perfis');visited=[];original=calculations.recalculate
    def calculate(row,*args):
        visited.append(row['key']);return original(row,*args)
    monkeypatch.setattr(calculations,'recalculate',calculate)
    monkeypatch.setattr(projection,'RAW_CONTRACT',projection.RAW_CONTRACT+'-new-engine')
    after=projection.rebuild('perfis')
    assert after['id']!=before['id'] and after['metadata']['calculation_scope']=='full'
    assert len(visited)==before['row_count']>0


def test_worker_publishes_linked_macro_revision_before_form_is_opened(workspace):
    from app.raw import worker,document_dependencies
    for area in planning.AREAS:projection.rebuild(area)
    capacity.rebuild()
    initial=query.listing({'area':'perfis','population':'all'})
    first=initial['rows'][0]
    saved=edits.update_batch({'request_id':str(uuid.uuid4()),'area':'perfis','version':initial['version'],
        'edits':[{'key':first['key'],'expected_revision':first['revision'],'values':{'notes':'Preserved human value'}}]})
    need_id=saved['items'][0]['need_id']
    import_copy(workspace,'perfis','linked-new',closed=True)
    assert worker.refresh_sources()
    row=query.listing({'area':'perfis','population':'all','selected':[need_id]})['rows'][0]
    # Opening detail used to discover a later revision after this publication.
    detail=needs.detail(need_id)
    assert detail['need']['revision']==row['revision']
    assert not row['values']['planning_active']
    assert row['values']['notes']=='Preserved human value'
    assert next(s for s in row['sources'] if s['kind']=='plan_line')['version']=='linked-new'
    before=needs.history(need_id)
    assert document_dependencies.refresh()['changed']==[]
    assert needs.history(need_id)==before
