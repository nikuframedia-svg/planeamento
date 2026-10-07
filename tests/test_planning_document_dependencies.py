"""Real SQLite document revisions wake planning; untouched fields follow, human values stay (07/10/2026)."""
import json
from dataclasses import replace
from app import planning,planning_needs as needs
from app.dossiers import store
from app.raw import document_dependencies,projection,query
from tests.test_raw_workspace import workspace,database,canonical,registry,postgres16
from tests.test_planning_needs import request,vals


def test_document_revision_exclusion_and_recovery_are_idempotent(workspace,tmp_path,monkeypatch):
    monkeypatch.setattr(store,'settings',replace(store.settings,data_dir=tmp_path))
    with store.connect() as c:
        c.execute("INSERT INTO documents(id,sha256,filename,page_count,status,production_order,created_at,updated_at) VALUES('doc','hash','test.pdf',1,'review','OF4200','2026-09-24','2026-09-24')")
        c.execute("INSERT INTO pieces(id,document_id,source_key,machine_group,index_page,index_ref,drawing_pages_json,raw_json,values_json) VALUES('piece','doc','piece','perfis',1,'P1','[1]','{}',?)",(json.dumps(vals()),))
    n=needs.resolve(request(area='perfis',source={'kind':'pdf','id':'doc/piece'}))
    n=needs.save(request(area='perfis',need_id=n['need_id'],expected_revision=n['revision'],catalog_version='s1',values={**vals(),'thickness_mm':4},
                         decisions={'length_mm':'accept','thickness_mm':'write'}))
    assert document_dependencies.refresh()['changed']==[]
    first=projection.rebuild('perfis')
    with store.connect() as c:c.execute('UPDATE pieces SET revision=revision+1,values_json=? WHERE id=?',(json.dumps({**vals(),'length_mm':900,'thickness_mm':5}),'piece'))
    assert document_dependencies.refresh()['changed']==[n['need_id']]
    assert document_dependencies.refresh()['changed']==[]
    new=projection.rebuild('perfis')
    assert new['metadata']['calculation_scope']=='source_orders'
    # O worker segue a revisão do PDF (07/10/2026): a sugestão aceite segue, o valor escrito fica com nota.
    visible=query.listing({'area':'perfis','selected':[n['need_id']],'population':'all'})['rows'][0]
    assert visible['values']['length_mm']==900 and visible['values']['thickness_mm']==4
    assert visible['sources'][0]['payload']['values']['length_mm']==900
    with planning.connect(readonly=True) as c:
        field=c.execute("SELECT * FROM planning_mtg.field_state WHERE need_id=%s AND field='length_mm'",(n['need_id'],)).fetchone()
        assert field['value']==900 and field['suggestion']==900 and not field['requires_review'] and field['human_decision']=='accept'
        written=c.execute("SELECT * FROM planning_mtg.field_state WHERE need_id=%s AND field='thickness_mm'",(n['need_id'],)).fetchone()
        assert written['value']==4 and written['suggestion']==5 and written['requires_review'] and written['human_decision']=='write'
        assert c.execute('SELECT count(*) n FROM planning_mtg.audit_outbox WHERE delivered_at IS NULL').fetchone()['n']>0
    with store.connect() as c:c.execute("UPDATE pieces SET state='excluded',revision=revision+1 WHERE id='piece'")
    assert document_dependencies.refresh()['changed']==[n['need_id']]
    projection.rebuild('perfis')
    row=query.listing({'area':'perfis','selected':[n['need_id']],'population':'all'})['rows'][0]
    assert any('documental' in w for w in row['warnings']) and row['values']['length_mm']==900
    assert query.listing({'area':'perfis','version':str(first['id']),'selected':[n['need_id']],'population':'all'})['rows'][0]['values']['length_mm']==1000
    with store.connect() as c:c.execute("UPDATE pieces SET state='review',revision=revision+1 WHERE id='piece'")
    document_dependencies.refresh();projection.rebuild('perfis')
    delivered=needs.deliver_outbox();assert delivered['delivered']>0
    assert needs.deliver_outbox()['delivered']==0
    with store.connect() as c:
        receipts=c.execute('SELECT count(*) FROM planning_event_receipts').fetchone()[0]
        events=c.execute("SELECT count(*) FROM events WHERE action LIKE 'planning:%'").fetchone()[0]
        assert events==receipts==delivered['delivered']
