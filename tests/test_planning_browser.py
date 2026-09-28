"""Real browser against an isolated database and temporary PDF archive."""
import os
import socket
import subprocess
import time
from pathlib import Path
import urllib.request
import sqlite3
import json
import pytest
from tests.test_planning_needs import canonical, registry, postgres16

@pytest.mark.skipif(os.environ.get('RUN_PLANNING_BROWSER')!='1',reason='Browser opt-in')
def test_common_editor_browser(canonical,tmp_path):
    root=Path(__file__).resolve().parents[1]
    import psycopg
    from psycopg.types.json import Jsonb
    with psycopg.connect(canonical) as conn:
        header=[None]*18;header[17]='Perfil U'
        conn.execute("UPDATE raw_mtg.other_sheet_rows SET row_data=%s WHERE sheet_name='AreaSecaoCorte' AND excel_row=1",(Jsonb({'values':header}),))
        conn.execute("UPDATE raw_mtg.other_sheet_rows SET row_data=%s WHERE sheet_name='AreaSecaoCorte' AND excel_row=2",(Jsonb({'values':[None]*17+['UPN50x25']}),))
        conn.execute("INSERT INTO raw_mtg.other_sheet_rows VALUES ('s1','AreaSecaoCorte',4,%s)",(Jsonb({'values':['Perfil U']+[None]*16+['UPN50x38']}),))
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    env={**os.environ,'MES_PG_DSN':os.environ['MES_PG_DSN'],'MES_DATA_DIR':str(tmp_path),'MES_DOSSIER_WORKER_DISABLED':'1','MES_PLANNING_NEEDS_ENABLED':'1'}
    from app.dossiers.store import SCHEMA
    from tests.test_planning_needs import vals
    archive=tmp_path/'dossiers';archive.mkdir()
    with sqlite3.connect(archive/'dossiers.db') as conn:
        conn.executescript(SCHEMA)
        conn.execute("INSERT INTO documents(id,sha256,filename,page_count,status,production_order,created_at,updated_at) VALUES ('browser-doc','browser-hash','Dossier de ensaio.pdf',1,'ready','OF4200','2026-09-21','2026-09-21')")
        values=vals();values['component_ref']='BROWSER-NEW';values['angle_deg']=0;values['abocardar']='X'
        conn.execute("INSERT INTO pieces(id,document_id,source_key,machine_group,index_page,index_ref,drawing_pages_json,raw_json,values_json,state) VALUES ('browser-piece','browser-doc','p1','Serrote',1,'BROWSER-NEW','[1]',?,?,'ready')",(json.dumps(values),json.dumps(values)))
        values['component_ref']='SECOND-PIECE'
        conn.execute("INSERT INTO pieces(id,document_id,source_key,machine_group,index_page,index_ref,drawing_pages_json,raw_json,values_json,state) VALUES ('second-piece','browser-doc','p2','Serrote',1,'SECOND-PIECE','[1]',?,?,'ready')",(json.dumps(values),json.dumps(values)))
    log=(tmp_path/'server.log').open('w+')
    process=subprocess.Popen([str(root/'.venv/bin/python'),'-m','uvicorn','app.web.planning_app:app','--host','127.0.0.1','--port',str(port)],cwd=root,env=env,stdout=log,stderr=log)
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(f'http://127.0.0.1:{port}/planeamento',timeout=.5);break
            except Exception:time.sleep(.1)
        run=subprocess.run(['node',str(root/'tests/planning_browser.cjs')],env={**env,'PLANNING_CHECK_BASE':f'http://127.0.0.1:{port}'},capture_output=True,text=True,timeout=150)
        log.flush();log.seek(0)
        assert run.returncode==0,run.stdout+run.stderr+'\n'+log.read()
    finally:process.terminate();process.wait(timeout=10);log.close()
