"""PostgreSQL round trips, snapshot replacement, and rollback on incomplete sync."""
import io
import uuid
from pathlib import Path

import openpyxl
import psycopg
from psycopg.rows import dict_row
import pytest

from app import planning, planning_needs as needs
from app.raw import edits, query, projection, ocr_export, research_sync
from tests.test_planning_integral_registration import local_workspace, workspace, database, canonical, registry, postgres16
from tests.test_planning_needs import vals

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture()
def free_workspace(local_workspace,postgres16,monkeypatch):
    with psycopg.connect(postgres16[0]) as c:
        for name in ('042_free_registration.sql','021_original_ocr_import.sql','043_original_ocr_export.sql'):
            c.execute((ROOT/'sql'/name).read_text())
        c.execute('TRUNCATE ocr_original.export_sources CASCADE')
        c.execute((ROOT/'sql/integration/research_live.sql').read_text())
        c.execute('TRUNCATE origem_v2.aplicacao_versoes,origem_v2.aplicacao_conteudos CASCADE')
    monkeypatch.setenv('MES_PLANNING_FREE_ENTRY','1')
    return local_workspace


def workbook(rows):
    b=openpyxl.Workbook();s=b.active
    s.append(['Data','OF','Modelo','QTD','Setor / Máquina Desc.','Comprimento (mm)'])
    for row in rows:s.append(row)
    stream=io.BytesIO();b.save(stream);return stream.getvalue()


def test_raw_roundtrip_preserves_arbitrary_input_and_history(free_workspace):
    projection.rebuild('perfis')
    entered={**vals(),'machine':'Máquina fora do catálogo','length_mm':'por medir','quantity_to_plan':25,'cut_date':'a combinar'}
    saved=edits.prepare({'request_id':str(uuid.uuid4()),'area':'perfis','production_order_no':'OF998877',
        'record_status':'ready','values':entered})
    listed=query.listing({'area':'perfis','q':'OF998877'})
    row=listed['rows'][0]
    assert row['values']['length_mm']=='por medir'
    assert row['values']['quantity_to_plan']==25
    assert row['values']['cut_date']=='a combinar'
    changed=edits.update_batch({'request_id':str(uuid.uuid4()),'area':'perfis','version':listed['version'],
        'edits':[{'key':row['key'],'expected_revision':row['revision'],
            'values':{'length_mm':'outro texto','quantity_to_plan':'não sei','customer':'Cliente livre','delivery_date':'2026-99-99','operation':'Operação fora do catálogo'}}]})
    row=query.listing({'area':'perfis','q':'OF998877'})['rows'][0]
    assert row['values']['length_mm']=='outro texto'
    assert row['values']['quantity_to_plan']=='não sei'
    assert row['values']['customer']=='Cliente livre'
    assert row['values']['delivery_date']=='2026-99-99'
    assert row['values']['operation']=='Operação fora do catálogo'
    assert not query.listing({'area':'perfis','q':'OF998877','filters':[{'field':'delivery_date','op':'known'}]})['rows']
    assert any(r['input_values'].get('quantity_to_plan')=='não sei' for r in needs.detail(saved['need_id'])['records'])
    # Rebuilding from sources must not erase manual text.
    projection.rebuild('perfis')
    assert query.listing({'area':'perfis','q':'OF998877'})['rows'][0]['values']['length_mm']=='outro texto'
    with planning.connect(readonly=True) as c:
        assert c.execute('SELECT count(*) n FROM planning_mtg.record_versions v JOIN planning_mtg.records r ON r.id=v.record_id WHERE r.need_id=%s',(saved['need_id'],)).fetchone()['n']==2


def test_export_repetition_revision_duplicates_and_native_ids(free_workspace,postgres16):
    a=['2026-09-29','OF42','X',10,'M1',1000]
    b=['2026-09-28','OF43','Y',5,'M2',2000]
    first=ocr_export.parse(workbook([a,a,b]))
    reordered=ocr_export.parse(workbook([b,a,a]))
    assert first['hash']==reordered['hash']
    assert len({r['key'] for r in first['rows']})==3
    with psycopg.connect(postgres16[0],row_factory=dict_row) as c:
        one=ocr_export.publish(c,first,'http://test/export')
        two=ocr_export.publish(c,reordered,'http://test/export')
        assert two['unchanged'] and one['version']==two['version']
        three=ocr_export.publish(c,ocr_export.parse(workbook([b])),'http://test/export')
        assert three['rows']==1 and not three['unchanged']
        state=ocr_export.status(c)
        assert not state['included_in_planning_balances']
        result=ocr_export.query(c,state)
        assert result['total']==1 and 'sheet_id' not in result['records'][0]
        assert c.execute('SELECT count(*) n FROM ocr_original.export_versions').fetchone()['n']==2
    with pytest.raises(ValueError,match='empty_validated_export'):ocr_export.parse(workbook([]))


def test_research_heads_replace_current_rows_and_keep_history(free_workspace,postgres16):
    with psycopg.connect(postgres16[0],row_factory=dict_row) as c:
        rows=[('A',{'values':{'of':'OF42','quantity_required':10}}),('B',{'values':{'of':'OF43','quantity_required':20}})]
        assert not research_sync.publish(c,'planning:perfis',rows,{})['unchanged']
        assert research_sync.publish(c,'planning:perfis',list(reversed(rows)),{})['unchanged']
        research_sync.publish(c,'planning:perfis',[('A',{'values':{'of':'OF42','quantity_required':15}})],{})
        current=c.execute('SELECT * FROM consulta_v2.planeamento_atual').fetchall()
        assert len(current)==1 and current[0]['valores']['quantity_required']==15
        assert c.execute('SELECT count(*) n FROM origem_v2.aplicacao_versoes').fetchone()['n']==2
        with pytest.raises(ValueError,match='duplicate_source_key'):
            with c.transaction():research_sync.publish(c,'planning:perfis',[rows[0],rows[0]],{})
        assert c.execute('SELECT valores FROM consulta_v2.planeamento_atual').fetchone()['valores']['quantity_required']==15


def test_research_complete_package_includes_new_manual_record(free_workspace,postgres16):
    saved=edits.prepare({'request_id':str(uuid.uuid4()),'area':'perfis','production_order_no':'OF998877','values':vals()})
    for area in planning.AREAS:projection.rebuild(area)
    with planning.connect(readonly=True) as source, psycopg.connect(postgres16[0],row_factory=dict_row) as dest:
        source.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        for package in research_sync.packages(source):research_sync.publish(dest,*package)
        records=dest.execute('SELECT dados FROM consulta_v2.registos_manuais_atuais').fetchall()
        assert any(r['dados']['id']==saved['record_id'] for r in records)
        raw=dest.execute("SELECT valores FROM consulta_v2.planeamento_atual WHERE valores->>'of'='OF998877'").fetchone()
        assert raw['valores']['quantity_required']==100
        known={r['conjunto']:r['metadata'] for r in dest.execute('SELECT f.conjunto,v.metadata FROM origem_v2.aplicacao_fontes f JOIN origem_v2.aplicacao_versoes v ON v.id=f.versao').fetchall()}
        repeated=list(research_sync.packages(source,known))
        assert not any(name.startswith(('excel:','cpis_excel:','planning:')) for name,_,_ in repeated)


def test_browser_free_registration(free_workspace,tmp_path):
    import os, socket, subprocess, time
    from urllib.request import urlopen
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    env={**os.environ,'PLANNING_CHECK_BASE':f'http://127.0.0.1:{port}','PLANNING_TEST_ISOLATED':'1','MES_PLANNING_NEEDS_ENABLED':'1','MES_PLANNING_RAW_ENABLED':'1','MES_DOSSIER_WORKER_DISABLED':'1'}
    with (tmp_path/'server.log').open('w') as log:
        server=subprocess.Popen([str(ROOT/'.venv/bin/python'),'-m','uvicorn','app.web.planning_app:app','--host','127.0.0.1','--port',str(port)],cwd=ROOT,env=env,stdout=log,stderr=log)
        try:
            for _ in range(100):
                try:
                    with urlopen(env['PLANNING_CHECK_BASE']+'/planeamento',timeout=1):break
                except Exception:time.sleep(.1)
            result=subprocess.run(['node',str(ROOT/'tests/planning_free_registration_browser.cjs')],cwd=ROOT,env=env,capture_output=True,text=True,timeout=90)
            assert result.returncode==0,result.stdout+'\n'+result.stderr
        finally:
            server.terminate();server.wait(timeout=15)
