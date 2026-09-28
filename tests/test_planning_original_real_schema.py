"""Original integration with the observed SQLite schema, without invented fields."""
import json,sqlite3,uuid
from pathlib import Path
import pytest
from app import original_ocr,planning,planning_associations as assoc
from app.raw import projection,worked_hours
from tests.test_planning_original_associations import decision_source,make_need,proposal
from tests.test_planning_original_production import original_source,publish
from tests.test_original_ocr import local
from tests.test_raw_workspace import workspace,database,canonical,registry,postgres16
from scripts.audit_planning_actual_hours import load_inputs,resource_cohorts,canonical as cohort


@pytest.mark.parametrize('area',['perfis','cantoneiras'])
def test_real_schema_requires_human_identity_and_independent_hours_agree(decision_source,tmp_path,area):
    path=tmp_path/'observed-schema.db'
    with sqlite3.connect(path) as c:
        c.executescript((Path(__file__).parent/'fixtures/original_ocr_schema.sql').read_text())
        data={'template_name':'manual','header':{'setor_maquina':'MEBA' if area=='perfis' else 'Ficep'},'footer':{'horas_trabalhadas':'2,5'},'rows':[]}
        c.execute("INSERT INTO sheets(id,image_path,status,sheet_data,revision,validated_at) VALUES(1,'fixture.jpg','validated',?,1,'2026-09-23 16:00:00')",(json.dumps(data),))
        c.execute("INSERT INTO production_rows(sheet_id,row_index,of,modelo,qtd,comp_mm,sheet_iso_date,sheet_hours) VALUES(1,0,'4200','NEW-A',4,1000,'2026-09-23',2.5)")
        columns={r[1] for r in c.execute('PRAGMA table_info(production_rows)')}
        assert not columns&{'profile_type','operation','operation_code','plan_identity','area'}
    # A separate persistent identity prevents collisions with the earlier fixture.
    source=(decision_source[0],path,str(uuid.uuid4()))
    original_ocr.publish(original_ocr.read_snapshot(path,source[2]),source[0])
    n,_=make_need(area)
    for a in planning.AREAS:projection.rebuild(a)
    with planning.connect(readonly=True) as c:
        pending=assoc.original_pending('4200',area,state='all')['records']
        record=next(r for r in pending if source[2] in r['id'])
        assert record['profile_type'] is None and record['extra']['operation_code'] is None
    from tests.test_planning_needs import request
    assoc.save(request(production_record_id=record['id'],expected_revision=0,evidence_hash=record['evidence_hash'],reason='Identidade e operação conferidas no ensaio',
        allocations=[{'need_id':n['need_id'],'operation_id':n['operation_id'],'expected_need_revision':n['revision'],'quantity':4}]))
    for a in planning.AREAS:projection.rebuild(a)
    with planning.connect(readonly=True) as c:
        independent,_,_,_,_=load_inputs(c)
        expected=[o for o in independent if o.get('instance_id')==source[2]]
        actual=[o for o in worked_hours.observations(c) if o.get('instance_id')==source[2]]
        assert actual==expected and len(actual)==1 and actual[0]['hours']==2.5
        resource={'id':'physical','definition':{'aliases':[{'area':area,'name':data['header']['setor_maquina']}]}}
        assert [cohort(x) for x in worked_hours.resolve(resource,[],actual)]==[cohort(x) for x in resource_cohorts(resource,[],expected)]
    status=original_ocr.status();instance=next(x for x in status['instances'] if x['id']==source[2])
    assert instance['data_recency']['latest_production_date']=='2026-09-23'
    assert instance['last_consistent_read_at'] and instance['last_successful_publication']['finished_at']
    assert original_ocr.run_once(path,source[2],source[0])['unchanged']
    missing=original_ocr.run_once(tmp_path/'missing.db',source[2],source[0])
    assert missing['error']=='FileNotFoundError'
    current=next(x for x in original_ocr.status()['instances'] if x['id']==source[2])
    assert not current['last_attempt']['success'] and current['current_snapshot']==instance['current_snapshot']
    assert current['last_successful_publication']==instance['last_successful_publication'] or current['last_successful_publication']['snapshot_id']==instance['current_snapshot']
