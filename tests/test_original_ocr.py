import copy
import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
import psycopg
import pytest
from app import original_ocr as ocr
from tests.test_planning_needs import canonical, registry, postgres16

@pytest.fixture()
def local(tmp_path):
    path=tmp_path/'original.db'
    with sqlite3.connect(path) as c:
        c.executescript('CREATE TABLE sheets(id integer primary key,status text,sheet_data text,validated_at text,revision integer); CREATE TABLE production_rows(id integer primary key,sheet_id integer,row_index integer,qtd integer,of text,sheet_iso_date text);')
        c.execute('INSERT INTO sheets VALUES (1,\'validated\',?,\'2026-09-17 12:00:00\',1)',(json.dumps({'template_name':'kanban','header':{'setor_maquina':'Teste'},'rows':[{'qtd':4}]}),))
        c.execute("INSERT INTO sheets VALUES (2,'draft','{}',NULL,0)")
        c.execute("INSERT INTO production_rows VALUES (12,1,0,4,'4200','2026-09-17')")
        c.execute("INSERT INTO production_rows VALUES (13,2,0,500,'4200','2026-09-17')")
    return path


def test_readonly_validated_only_and_stable_identity(local):
    instance=str(uuid.uuid4());before=hashlib.sha256(local.read_bytes()).hexdigest()
    first=ocr.read_snapshot(local,instance)
    assert first['sheet_count']==1 and first['production_count']==1
    assert hashlib.sha256(local.read_bytes()).hexdigest()==before
    with sqlite3.connect(local) as conn:conn.execute('UPDATE production_rows SET id=99 WHERE sheet_id=1')
    second=ocr.read_snapshot(local,instance)
    assert first['content_hash']==second['content_hash']
    assert 'id' not in first['sheets'][0]['payload']['production'][0]


def test_atomic_idempotent_revisions_and_regression(canonical,local):
    with psycopg.connect(canonical,autocommit=True) as conn:conn.execute((Path(__file__).resolve().parents[1]/'sql/021_original_ocr_import.sql').read_text())
    instance=str(uuid.uuid4());snap=ocr.read_snapshot(local,instance)
    a=ocr.publish(snap,canonical);b=ocr.publish(snap,canonical)
    assert a['snapshot_id']==b['snapshot_id'] and b['unchanged']
    with sqlite3.connect(local) as conn:
        conn.execute('UPDATE sheets SET revision=2 WHERE id=1');conn.execute("UPDATE production_rows SET sheet_iso_date='2026-09-18' WHERE sheet_id=1")
    revised=ocr.read_snapshot(local,instance);new=ocr.publish(revised,canonical)
    assert new['snapshot_id']!=a['snapshot_id']
    with pytest.raises(ValueError,match='regressed'):ocr.publish(snap,canonical)
    broken=copy.deepcopy(revised);broken['production_count']=900
    with pytest.raises(ValueError,match='count_mismatch'):ocr.publish(broken,canonical)
    with psycopg.connect(canonical) as conn:
        assert conn.execute('SELECT current_snapshot::text FROM ocr_original.instances WHERE id=%s',(instance,)).fetchone()[0]==new['snapshot_id']
        assert conn.execute('SELECT count(*) FROM ocr_original.snapshots WHERE instance_id=%s',(instance,)).fetchone()[0]==2


def test_missing_path_never_creates_source(tmp_path):
    path=tmp_path/'absent.db'
    with pytest.raises(FileNotFoundError):ocr.read_snapshot(path,str(uuid.uuid4()))
    assert not path.exists()


def test_publication_failure_after_insert_keeps_previous(canonical,local):
    with psycopg.connect(canonical,autocommit=True) as conn:conn.execute((Path(__file__).resolve().parents[1]/'sql/021_original_ocr_import.sql').read_text())
    instance=str(uuid.uuid4());first=ocr.publish(ocr.read_snapshot(local,instance),canonical)
    with sqlite3.connect(local) as conn:
        conn.execute("UPDATE sheets SET revision=2 WHERE id=1");conn.execute('UPDATE production_rows SET qtd=3 WHERE sheet_id=1')
    with psycopg.connect(canonical,autocommit=True) as conn:
        conn.execute("CREATE OR REPLACE FUNCTION ocr_original.fail_test_insert() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'test publication failure'; END $$")
        conn.execute('CREATE TRIGGER fail_test BEFORE INSERT ON ocr_original.snapshot_sheets FOR EACH ROW EXECUTE FUNCTION ocr_original.fail_test_insert()')
    try:
        with pytest.raises(psycopg.Error):ocr.publish(ocr.read_snapshot(local,instance),canonical)
        with psycopg.connect(canonical) as conn:
            assert conn.execute('SELECT current_snapshot::text FROM ocr_original.instances WHERE id=%s',(instance,)).fetchone()[0]==first['snapshot_id']
            assert conn.execute('SELECT count(*) FROM ocr_original.snapshots WHERE instance_id=%s',(instance,)).fetchone()[0]==1
    finally:
        with psycopg.connect(canonical,autocommit=True) as conn:conn.execute('DROP TRIGGER fail_test ON ocr_original.snapshot_sheets')


def test_source_retirement_and_future_dates_preserved(canonical,local):
    with psycopg.connect(canonical,autocommit=True) as conn:conn.execute((Path(__file__).resolve().parents[1]/'sql/021_original_ocr_import.sql').read_text())
    with sqlite3.connect(local) as conn:
        conn.execute("UPDATE sheets SET status='validated',revision=1 WHERE id=2")
        conn.execute("UPDATE production_rows SET sheet_iso_date='2099-01-01' WHERE sheet_id=2")
    instance=str(uuid.uuid4());snapshot=ocr.read_snapshot(local,instance)
    assert snapshot['sheets'][1]['payload']['quality_flags'][0]['code']=='future_production_date'
    ocr.publish(snapshot,canonical)
    with sqlite3.connect(local) as conn:conn.execute("UPDATE sheets SET status='draft' WHERE id=2")
    second=ocr.publish(ocr.read_snapshot(local,instance),canonical)
    with psycopg.connect(canonical) as conn:
        assert conn.execute('SELECT count(*) FROM ocr_original.snapshot_sheets WHERE snapshot_id=%s',(second['snapshot_id'],)).fetchone()[0]==1
        assert conn.execute('SELECT count(*) FROM ocr_original.sheets WHERE instance_id=%s',(instance,)).fetchone()[0]==2
    assert ocr.query(of='4200')['total']>=1
