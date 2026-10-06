"""Contrato de fichas: origem, persistência, concorrência e CPIS.

As integrações usam PostgreSQL descartável, nunca a base operacional.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import uuid
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from openpyxl import load_workbook

from app import cpis_sync, planning, planning_hub, planning_output
from app.web.planning_app import app
from tests.test_dossier_macro import workbook_source
from tests.test_pg_sheet_numbering_integration import postgres16


def values():
    return {"component_ref":"REF-A", "material_type":"Tubo redondo", "profile":"88.9x3",
            "length_mm":3003, "quantity_required":100, "quantity_to_plan":36,
            "quantity_completed":64, "machine":"MEBA", "operation":"corte",
            "cut_date":"2026-09-15", "picking_week":39}


def test_values_preserve_unknown_completed_and_zero_capacity():
    data=values();data["quantity_completed"]=None;data["weekly_capacity_hours"]=0
    result=planning.validate_values(data,["MEBA"])
    assert result["quantity_completed"] is None
    assert result["weekly_capacity_hours"]==0
    assert result["picking_year"] is None


def test_incomplete_draft_can_keep_a_proposed_quantity_without_required_quantity():
    result = planning.validate_values({'quantity_to_plan':7}, [], record_status='draft')
    assert result['quantity_required'] is None and result['quantity_to_plan']==7


@pytest.mark.parametrize("field,value",[
    ("quantity_required",-1),("quantity_completed",1.5),("weekly_capacity_hours",169),
    ("angle_deg",1404),("length_mm",float('nan')),("picking_week",54),("machine","INVENTADA"),
])
def test_invalid_inputs_are_rejected(field,value):
    data=values();data[field]=value
    with pytest.raises(planning.PlanningError): planning.validate_values(data,["MEBA"])


def test_production_identity_uses_geometry_and_keeps_ambiguity_visible():
    plans=[
        {'plan_key':'p1','source_app':'kanban-mes-mtg2','component_ref':'REF-A','length_mm':1000,'profile_type':'80x3'},
        {'plan_key':'p2','source_app':'kanban-mes-mtg2','component_ref':'REF-A','length_mm':2000,'profile_type':'80x3'},
    ]
    unique={'source_app':'kanban-mes-mtg2','matched_plan_key':'old:1','model_ref':'REF-A',
            'length_mm':2000,'profile_type':'80x3','quantity':4,'plan_refs':[]}
    ambiguous={'source_app':'kanban-mes-mtg2','matched_plan_key':None,'model_ref':'REF-A',
               'length_mm':None,'profile_type':'80x3','quantity':2,'plan_refs':[]}
    planning_hub._production_associations([unique,ambiguous],plans)
    assert unique['association_status']=='technical_unique' and unique['resolved_plan_keys']==['p2']
    assert ambiguous['association_status']=='ambiguous'
    assert ambiguous['association_candidates']==['p1','p2']


def test_html_exposes_required_fields_and_local_assets():
    with TestClient(app) as client:
        response=client.get('/planeamento/manual')
        assert response.status_code==200
        for field in ('component_ref','quantity_required','custom_profile','outer_diameter_mm',
                      'material_request_date','abocardar','finish_week','weekly_capacity_hours'):
            assert f'name="{field}"' in response.text
        assert client.get('/static/planning.js').status_code==200
        assert client.post('/planeamento/api/registos',data={}).status_code==415
        assert client.post('/planeamento/api/registos',json={},headers={'Origin':'https://outro.example'}).status_code==403


@pytest.fixture()
def registry(postgres16,monkeypatch):
    admin,app_dsn=postgres16
    monkeypatch.setenv('MES_PG_DSN',app_dsn)
    with psycopg.connect(admin,autocommit=True) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS audit_mtg.snapshots(snapshot_id text PRIMARY KEY,dataset_id text,
                source_filename text,source_path text,source_sha256 text,loaded_at timestamptz DEFAULT now());
            CREATE TABLE IF NOT EXISTS raw_mtg.plan_production_rows(snapshot_id text,source_line_id text,
                excel_row int,external_row_number bigint,production_order_no text,sales_order_no text,
                customer_name text,designation text,component_ref text,material_type text,material_description text,
                profile_type text,length_mm numeric,quantity_planned numeric,quantity_made numeric,closed_x boolean,
                team text,pavilion text,cutting_machine text,cut_date date,row_data jsonb);
            CREATE TABLE IF NOT EXISTS analytics_mtg.kanban_plan_lines(snapshot_id text,plan_key text,
                remaining_quantity numeric,remaining_valid boolean,source_app text,excel_row int,
                production_order_no text,component_ref text,profile_type text,material_type text,
                material_description text,length_mm numeric,quantity_planned numeric,quantity_made numeric,
                remaining_rule text,closed_x boolean,cutting_machine text,planning_week int,cut_date date);
            CREATE TABLE IF NOT EXISTS core_mtg.production_orders(snapshot_id text,production_order_no text,
                cpis_status text,cpis_delivery_date date,cpis_planned_finish_date date);
            CREATE TABLE IF NOT EXISTS core_mtg.machines(snapshot_id text,display_name text);
            CREATE TABLE IF NOT EXISTS raw_mtg.machine_rows(snapshot_id text,machine_name text,material_type text,row_data jsonb,
                operation_code text,operation_description text);
            CREATE TABLE IF NOT EXISTS raw_mtg.other_sheet_rows(snapshot_id text,sheet_name text,excel_row int,row_data jsonb);
            CREATE TABLE IF NOT EXISTS raw_mtg.cpis_rows(snapshot_id text,source_line_id text,excel_row int,
                production_order_no text,sales_order_no text,customer_name text,responsible_dp text,
                actual_start_date timestamp,planned_finish_date timestamp,actual_finish_date timestamp,
                observations text,work_type_code text,work_type_description text,production_order_weight_kg numeric,
                record_date timestamp,received_dp_date timestamp,status text,delivery_date timestamp,
                received_dl_date timestamp,planned_start_date timestamp,sap_order text,factory_unit text,row_data jsonb);
            CREATE TABLE IF NOT EXISTS mes_kanban.validated_sheets(sheet_uid text,source_app text,sheet_no bigint,
                source_filename text,source_page int,validated_at timestamptz);
            CREATE TABLE IF NOT EXISTS mes_kanban.production_records(id bigint,sheet_uid text,row_index int,
                sheet_date date,validated_at timestamptz,machine text,model_ref text,quantity numeric,
                length_mm numeric,profile_type text,matched_plan_key text,plan_snapshot_id text,
                match_confidence double precision,production_order text,extra jsonb);
            CREATE TABLE IF NOT EXISTS mes_kanban.production_record_plan_refs(production_record_id bigint,
                plan_key text,assumed_quantity numeric);
            GRANT SELECT ON ALL TABLES IN SCHEMA raw_mtg,core_mtg,analytics_mtg,audit_mtg TO mes_kanban_app;
            GRANT SELECT ON ALL TABLES IN SCHEMA mes_kanban TO mes_kanban_app;
        ''')
        conn.execute((Path(__file__).resolve().parents[1]/'sql/018_planning_registry.sql').read_text())
        conn.execute((Path(__file__).resolve().parents[1]/'sql/019_cpis_planning_hub.sql').read_text())
        # The current hub reads canonical technical revisions even when this
        # fixture exercises the older registry API. Match the deployed schema.
        conn.execute((Path(__file__).resolve().parents[1]/'sql/020_planning_needs.sql').read_text())
        conn.execute('TRUNCATE planning_mtg.needs CASCADE')
        conn.execute((Path(__file__).resolve().parents[1]/'sql/022_planning_order_registration.sql').read_text())
        conn.execute('TRUNCATE planning_mtg.order_registration')
        conn.execute('''TRUNCATE planning_mtg.output_proposals,planning_mtg.reconciliations,
            planning_mtg.record_versions,planning_mtg.records,
            raw_mtg.plan_production_rows,analytics_mtg.kanban_plan_lines,core_mtg.production_orders,
            core_mtg.machines,raw_mtg.machine_rows,raw_mtg.other_sheet_rows,raw_mtg.cpis_rows,
            cpis_mtg.sync_attempts,cpis_mtg.orders,cpis_mtg.versions,audit_mtg.snapshots''')
        conn.execute("""INSERT INTO audit_mtg.snapshots(snapshot_id,dataset_id,source_filename,source_path,source_sha256)
            VALUES ('s1','ds-met2-perfis','Met2_Plan_Perfis.xlsm','/tmp/perfis','a'),
                   ('c1','ds-2638099daddc474e','Met3_Plan_Cantoneiras.xlsm','/tmp/cant','b')""")
        conn.execute("INSERT INTO raw_mtg.machine_rows(snapshot_id,machine_name,material_type,row_data) VALUES ('s1','MEBA','Tubo redondo','{}')")
        conn.execute("INSERT INTO core_mtg.machines VALUES ('c1','Ficep XP T4')")
        conn.execute("INSERT INTO raw_mtg.other_sheet_rows VALUES ('s1','Picking',2,%s)",(Jsonb({'values':[1,4200,39]}),))
        for snap,key,profile,length in [('s1','s1:10','88.9x3',3003),('s1','s1:11','108x3',3003),('c1','c1:10','L80x80x6',5291)]:
            conn.execute('''INSERT INTO raw_mtg.plan_production_rows
                (snapshot_id,source_line_id,excel_row,external_row_number,production_order_no,sales_order_no,
                 customer_name,designation,component_ref,material_type,profile_type,length_mm,quantity_planned,
                 quantity_made,closed_x,row_data) VALUES (%s,%s,%s,%s,'OF4200','OV21','Cliente exemplo','Obra exemplo',
                 'REF-A','Tubo redondo',%s,%s,100,64,false,%s)''',
                (snap,key,int(key.split(':')[1]),int(key.split(':')[1]),profile,length,Jsonb({'Ser.':64,'Máquina Corte':'MEBA','Picking':None})))
            conn.execute('''INSERT INTO analytics_mtg.kanban_plan_lines
                (snapshot_id,plan_key,remaining_quantity,remaining_valid,source_app,excel_row,
                 production_order_no,component_ref,profile_type,material_type,length_mm,
                 quantity_planned,quantity_made,remaining_rule,closed_x)
                VALUES (%s,%s,36,true,%s,%s,'OF4200','REF-A',%s,'Tubo redondo',%s,100,64,
                        'source:test',false)''',
                (snap,key,'kanban-mes-mtg2' if snap=='s1' else 'kanban-mes',int(key.split(':')[1]),profile,length))
        conn.execute("INSERT INTO core_mtg.production_orders VALUES ('s1','OF4200','Em Produção','2026-10-30','2026-10-20'),('c1','OF4200','Em Produção','2026-10-30','2026-10-20')")
        conn.execute("""INSERT INTO raw_mtg.cpis_rows(snapshot_id,source_line_id,excel_row,production_order_no,
            sales_order_no,customer_name,planned_finish_date,observations,status,delivery_date,factory_unit,row_data)
            VALUES ('s1','s1:cpis:1',1,'OF4200','OV21','Cliente exemplo','2026-10-20','Obra exemplo','Em Produção','2026-10-30','MTG II','{}'),
                   ('c1','c1:cpis:1',1,'OF4200','OV21','Cliente exemplo','2026-10-20','Obra exemplo','Em Produção','2026-10-30','MTG II','{}')""")
    return admin


def payload():
    return {'area':'perfis','request_id':str(uuid.uuid4()),'actor':'Planeador teste',
            'snapshot_id':'s1','plan_key':'s1:10','values':values()}


@pytest.mark.pg_integration
@pytest.mark.skipif(os.environ.get('RUN_PG_INTEGRATION')!='1', reason='PostgreSQL descartável opt-in')
def test_real_database_save_reopen_revision_and_retries(registry):
    with TestClient(app) as client:
        line_response=client.get('/planeamento/api/linhas',params={'area':'perfis','of':'OF4200'})
        assert line_response.status_code==200,line_response.text
        lines=line_response.json()['lines']
        assert len(lines)==2
        assert {r['values']['profile'] for r in lines}=={'88.9x3','108x3'}
        assert all(r['values']['picking_week']==39 for r in lines)
        request=payload()
        response=client.post('/planeamento/api/registos',json=request)
        assert response.status_code==200,response.text
        saved=response.json()
        repeated=client.post('/planeamento/api/registos',json=request).json()
        assert repeated['id']==saved['id'] and repeated['replayed']
        request['values']['quantity_completed']=69
        assert client.post('/planeamento/api/registos',json=request).status_code==409
        request.update(record_id=saved['id'],revision=1,request_id=str(uuid.uuid4()))
        revision=client.post('/planeamento/api/registos',json=request)
        assert revision.status_code==200,revision.text
        reopened=client.get('/planeamento/api/registos/'+saved['id']).json()
        assert reopened['record']['values_json']['quantity_completed']==69
        assert reopened['record']['source_payload']['source_cut_completed']==64
        assert len(reopened['versions'])==2
        request['request_id']=str(uuid.uuid4())
        assert client.post('/planeamento/api/registos',json=request).status_code==409
        assert len(client.get('/planeamento/api/registos?area=perfis').json())==1
    with psycopg.connect(registry) as conn:
        assert conn.execute("SELECT row_data->>'Ser.' FROM raw_mtg.plan_production_rows WHERE source_line_id='s1:10'").fetchone()[0]=='64'


@pytest.mark.pg_integration
@pytest.mark.skipif(os.environ.get('RUN_PG_INTEGRATION')!='1', reason='PostgreSQL descartável opt-in')
def test_cpis_closure_and_stale_source_block_write(registry):
    request=payload()
    with TestClient(app) as client:
        assert client.get('/planeamento/api/ofs?area=perfis&q=cliente').json()['orders']
        with psycopg.connect(registry,autocommit=True) as conn:
            conn.execute("UPDATE core_mtg.production_orders SET cpis_status='Fechada'")
            conn.execute("UPDATE raw_mtg.cpis_rows SET status='Fechada'")
        assert client.post('/planeamento/api/registos',json=request).status_code==409
        assert not client.get('/planeamento/api/ofs?area=perfis&q=cliente').json()['orders']
        with psycopg.connect(registry,autocommit=True) as conn:
            conn.execute("UPDATE core_mtg.production_orders SET cpis_status='Em Produção'")
            conn.execute("UPDATE raw_mtg.cpis_rows SET status='Em Produção'")
            conn.execute("INSERT INTO audit_mtg.snapshots VALUES ('s2','ds-met2-perfis','Met2_Plan_Perfis.xlsm',now()+interval '1 day')")
        assert client.post('/planeamento/api/registos',json=request).status_code==409
        assert not client.get('/planeamento/api/registos?area=perfis').json()


@pytest.mark.pg_integration
@pytest.mark.skipif(os.environ.get('RUN_PG_INTEGRATION')!='1', reason='PostgreSQL descartável opt-in')
def test_cross_area_and_source_rebinding(registry):
    request=payload()
    with TestClient(app) as client:
        request['area']='cantoneiras'
        assert client.post('/planeamento/api/registos',json=request).status_code==409
        request['area']='perfis'
        saved=client.post('/planeamento/api/registos',json=request).json()
        request.update(record_id=saved['id'],revision=1,request_id=str(uuid.uuid4()),plan_key='s1:11')
        assert client.post('/planeamento/api/registos',json=request).status_code==409
        refreshed=client.get('/planeamento/api/registos/'+saved['id']+'/origem').json()
        assert refreshed['source']['plan_key']=='s1:10'


@pytest.mark.pg_integration
@pytest.mark.skipif(os.environ.get('RUN_PG_INTEGRATION')!='1', reason='PostgreSQL descartável opt-in')
def test_pending_filter_only_excludes_work_with_complete_operation_evidence(registry):
    assert planning_hub.list_orders(pending_only=True)['total']==1
    with psycopg.connect(registry,autocommit=True) as conn:
        conn.execute("UPDATE analytics_mtg.kanban_plan_lines SET remaining_quantity=0,closed_x=true")
    assert planning_hub.list_orders(pending_only=True)['total']==0
    assert planning_hub.list_orders(pending_only=False)['total']==1


@pytest.mark.pg_integration
@pytest.mark.skipif(os.environ.get('RUN_PG_INTEGRATION')!='1', reason='PostgreSQL descartável opt-in')
def test_record_can_follow_same_line_into_a_new_import(registry):
    request=payload()
    saved=planning.save_record(request)
    with psycopg.connect(registry,autocommit=True) as conn:
        conn.execute("INSERT INTO audit_mtg.snapshots VALUES ('s2','ds-met2-perfis','Met2_Plan_Perfis.xlsm',now()+interval '1 day')")
        conn.execute("INSERT INTO raw_mtg.plan_production_rows SELECT * FROM raw_mtg.plan_production_rows WHERE snapshot_id='s1'")
        # Mudar uma das duas cópias por ctid para modelar a importação seguinte.
        conn.execute("""UPDATE raw_mtg.plan_production_rows SET snapshot_id='s2',source_line_id=replace(source_line_id,'s1:','s2:')
            WHERE ctid IN (SELECT max(ctid) FROM raw_mtg.plan_production_rows WHERE snapshot_id='s1' GROUP BY source_line_id)""")
        conn.execute("""INSERT INTO analytics_mtg.kanban_plan_lines
            (snapshot_id,plan_key,remaining_quantity,remaining_valid,source_app,excel_row,
             production_order_no,component_ref,profile_type,material_type,material_description,
             length_mm,quantity_planned,quantity_made,remaining_rule,closed_x,cutting_machine,
             planning_week,cut_date)
            SELECT 's2',replace(plan_key,'s1:','s2:'),remaining_quantity,remaining_valid,source_app,
             excel_row,production_order_no,component_ref,profile_type,material_type,material_description,
             length_mm,quantity_planned,quantity_made,remaining_rule,closed_x,cutting_machine,
             planning_week,cut_date FROM analytics_mtg.kanban_plan_lines WHERE snapshot_id='s1'""")
        conn.execute("INSERT INTO core_mtg.production_orders SELECT 's2',production_order_no,cpis_status,cpis_delivery_date,cpis_planned_finish_date FROM core_mtg.production_orders WHERE snapshot_id='s1'")
        conn.execute("INSERT INTO raw_mtg.machine_rows VALUES ('s2','MEBA','Tubo redondo','{}')")
    refreshed=planning.refresh_source(saved['id'])
    assert refreshed['source']['plan_key']=='s2:10'
    request.update(record_id=saved['id'],revision=1,request_id=str(uuid.uuid4()),snapshot_id='s2',plan_key='s2:10')
    planning.save_record(request)
    assert planning.get_record(saved['id'])['record']['source_snapshot_id']=='s2'


def direct_row(of='OF2000', ov='OV-DIRECTA'):
    return {
        'source_row_no': 1, 'production_order_no': of,
        'production_order_original': of.removeprefix('OF'),
        'sales_order_no': ov, 'customer_name': 'Cliente CPIS',
        'responsible_dp': 'DP', 'actual_start_date': None,
        'planned_finish_date': None, 'actual_finish_date': None,
        'observations': 'Ordem sem linha de plano', 'work_type_code': 'T',
        'work_type_description': 'Estrutura', 'production_order_weight_kg': None,
        'record_date': None, 'received_dp_date': None, 'status': 'Em Aberto',
        'delivery_date': None, 'received_dl_date': None, 'planned_start_date': None,
        'sap_order': None, 'factory_unit': 'MTG II', 'row_data': {'of': of, 'ov': ov},
    }


@pytest.mark.pg_integration
@pytest.mark.skipif(os.environ.get('RUN_PG_INTEGRATION')!='1', reason='PostgreSQL descartável opt-in')
def test_direct_cpis_publish_is_atomic_versioned_and_lists_order_without_plan(registry):
    from datetime import date, datetime, timezone
    row=direct_row();row['row_data']['dataentregadl']=date(2026,10,30)
    # A leitura normaliza tipos nativos da vista antes da publicação JSON.
    row['row_data']=json.loads(json.dumps(row['row_data'],default=cpis_sync._json))
    first=cpis_sync.publish([row],datetime.now(timezone.utc),central_dsn=registry)
    repeated=cpis_sync.publish([row],datetime.now(timezone.utc),central_dsn=registry)
    assert first['changed'] is True and repeated['changed'] is False
    assert first['version_id']==repeated['version_id']
    result=planning_hub.list_orders(query='OV-DIRECTA')
    assert result['mode']=='direct' and result['total']==1
    assert result['orders'][0]['of']=='OF2000'
    assert result['orders'][0]['plan']=={}
    status=planning_hub.source_status()
    assert status['cpis']['fresh'] and status['completion_allowed']
    with psycopg.connect(registry) as conn:
        assert conn.execute('SELECT count(*) FROM cpis_mtg.versions').fetchone()[0]==1
        assert conn.execute('SELECT count(*) FROM cpis_mtg.orders').fetchone()[0]==1
        assert conn.execute('SELECT count(*) FROM cpis_mtg.sync_attempts').fetchone()[0]==2


@pytest.mark.pg_integration
@pytest.mark.skipif(os.environ.get('RUN_PG_INTEGRATION')!='1', reason='PostgreSQL descartável opt-in')
def test_manual_draft_without_plan_and_reconciliation_are_audited(registry):
    from datetime import datetime, timezone
    published=cpis_sync.publish([direct_row(), {**direct_row('OF4200'), 'source_row_no': 2}],datetime.now(timezone.utc),central_dsn=registry)
    request=payload()
    request.pop('plan_key'); request.pop('snapshot_id')
    request.update(production_order_no='OF2000',cpis_version=published['version_id'],
                   source_kind='cpis_manual',record_status='draft')
    request['values']={'component_ref':'NOVA-1','notes':'Medir em obra'}
    saved=planning.save_record(request)
    record=planning.get_record(saved['id'])['record']
    assert record['source_kind']=='cpis_manual' and record['source_plan_key'] is None
    assert record['record_status']=='draft'
    conference={
        'request_id':str(uuid.uuid4()),'of':'OF2000','area':'perfis',
        'component_ref':'NOVA-1','operation':'corte','actor':'Planeador teste',
        'reason':'Saldo confirmado com a equipa','accepted_required':'12',
        'accepted_remaining':'7','cpis_version':published['version_id'],
        'evidence':{'ocr_record_ids':[10,11],'macro_snapshot_id':'s1'},
    }
    # Arbitrary browser evidence is not proof of production on a manual draft.
    with pytest.raises(planning.PlanningError, match='geometria'):
        planning_hub.save_reconciliation(conference)
    detail = planning_hub.order_detail('OF4200')
    selected = next(line for line in detail['plan_lines'] if line['plan_key']=='s1:10')
    cut = selected['operations'][0]
    conference.update(of='OF4200', component_ref='REF-A', plan_key=selected['plan_key'],
                      evidence_fingerprint=cut['evidence_fingerprint'])
    result=planning_hub.save_reconciliation(conference)
    replay=planning_hub.save_reconciliation(conference)
    assert not result['replayed'] and replay['replayed']
    detail=planning_hub.order_detail('OF2000')
    assert detail['preparations'][0]['record_status']=='draft'
    detail=planning_hub.order_detail('OF4200')
    assert float(detail['reconciliations'][0]['accepted_remaining'])==7
    assert detail['reconciliations'][0]['valid']
    assert detail['reconciliations'][0]['evidence_json']['ocr_records']==[]
    with psycopg.connect(registry, autocommit=True) as conn:
        conn.execute("UPDATE analytics_mtg.kanban_plan_lines SET remaining_quantity=35 WHERE plan_key=%s", (conference['plan_key'],))
    assert not planning_hub.order_detail('OF4200')['reconciliations'][0]['valid']
    with pytest.raises(planning.PlanningError, match='evidência mudou'):
        planning_hub.save_reconciliation({**conference, 'request_id':str(uuid.uuid4())})


@pytest.mark.pg_integration
@pytest.mark.skipif(os.environ.get('RUN_PG_INTEGRATION')!='1', reason='PostgreSQL descartável opt-in')
def test_manual_ready_proposal_preserves_macro_and_detects_record_revision(registry,tmp_path):
    from datetime import datetime, timezone
    source=workbook_source();path=tmp_path/'Met2_Plan_Perfis.xlsm';path.write_bytes(source)
    published=cpis_sync.publish([direct_row()],datetime.now(timezone.utc),central_dsn=registry)
    with psycopg.connect(registry,autocommit=True) as conn:
        conn.execute("UPDATE audit_mtg.snapshots SET source_path=%s,source_sha256=%s WHERE snapshot_id='s1'",
                     (str(path),hashlib.sha256(source).hexdigest()))
        conn.execute("DELETE FROM raw_mtg.plan_production_rows WHERE snapshot_id='s1' AND source_line_id='s1:11'")
        conn.execute("UPDATE raw_mtg.plan_production_rows SET excel_row=7 WHERE snapshot_id='s1'")
        conn.execute("""INSERT INTO raw_mtg.cpis_rows(snapshot_id,source_line_id,excel_row,
            production_order_no,sales_order_no,customer_name,observations,status,row_data)
            VALUES ('s1','s1:cpis:2',2,'OF2000','OV-DIRECTA','Cliente CPIS',
                    'Ordem sem linha de plano','Em Aberto','{}')""")
    request={'area':'perfis','request_id':str(uuid.uuid4()),'actor':'Planeador teste',
             'production_order_no':'OF2000','cpis_version':published['version_id'],
             'source_kind':'cpis_manual','record_status':'ready','values':{
                 'component_ref':'NOVA-1','material_type':'Tubo redondo','profile':'88.9x3',
                 'length_mm':1200,'quantity_required':4,'quantity_to_plan':4,
                 'machine':'MEBA','operation':'corte'}}
    saved=planning.save_record(request)
    proposal=planning_output.create_proposal({'request_id':str(uuid.uuid4()),
        'actor':'Planeador teste','record_ids':[saved['id']]})
    assert proposal['added']==1 and proposal['cells']
    output=planning_output.generate(proposal['id'],proposal['proposal_fingerprint'])
    sheet=load_workbook(io.BytesIO(output),data_only=False)['Planeamento']
    assert sheet['E8'].value=='OF2000' and sheet['L8'].value=='NOVA-1'
    assert '[planeamento:' in sheet['AT8'].value
    edit={**request,'record_id':saved['id'],'revision':1,'request_id':str(uuid.uuid4()),
          'record_status':'draft'}
    planning.save_record(edit)
    with pytest.raises(planning.PlanningError,match='fichas selecionadas'):
        planning_output.generate(proposal['id'],proposal['proposal_fingerprint'])


@pytest.mark.pg_integration
@pytest.mark.skipif(os.environ.get('RUN_PG_INTEGRATION')!='1', reason='PostgreSQL descartável opt-in')
def test_list_shows_newest_copy_status_and_does_not_infer_area_from_cpis(registry):
    # Decisão de 06/10/2026 (substitui 20/09): cópias em desacordo → manda a mais recente, sem conflito.
    with psycopg.connect(registry, autocommit=True) as conn:
        conn.execute("UPDATE raw_mtg.cpis_rows SET status='Pronta' WHERE snapshot_id='c1'")
        conn.execute("UPDATE audit_mtg.snapshots SET loaded_at=loaded_at+interval '1 minute' WHERE snapshot_id='c1'")
        conn.execute('DELETE FROM analytics_mtg.kanban_plan_lines')
        conn.execute('DELETE FROM raw_mtg.plan_production_rows')
    item = planning_hub.list_orders()['orders'][0]
    detail = planning_hub.order_detail('4200')
    assert item['status_values'] == ['Pronta'] and item['cpis_status'] == 'Pronta'
    assert item['status_values'] == detail['context']['status_values']
    assert item['conflicts'] == [] and item['area'] == 'por_identificar'
    assert item['sources'] == [] and detail['context']['sources'] == []
    assert not item['execution_complete']
    status = planning_hub.source_status()
    assert status['cpis']['checked_at'] is None and status['cpis']['imported_at']
    assert not status['completion_allowed']


@pytest.mark.pg_integration
@pytest.mark.skipif(os.environ.get('RUN_PG_INTEGRATION')!='1', reason='PostgreSQL descartável opt-in')
def test_cut_complete_with_abocardar_pending_stays_in_pending_list(registry):
    with psycopg.connect(registry, autocommit=True) as conn:
        conn.execute("UPDATE analytics_mtg.kanban_plan_lines SET remaining_quantity=0,closed_x=true")
        conn.execute("UPDATE analytics_mtg.kanban_plan_lines SET closed_x=false WHERE plan_key='s1:10'")
        conn.execute("UPDATE raw_mtg.plan_production_rows SET row_data=%s WHERE source_line_id='s1:10'",
                     (Jsonb({'Ser.':100, 'Aborc.':'X', 'Aboc.':83, 'Máquina Corte':'MEBA'}),))
    item = planning_hub.list_orders(pending_only=True)['orders'][0]
    assert not item['execution_complete']
    line = next(row for row in planning_hub.order_detail('OF4200')['plan_lines'] if row['plan_key']=='s1:10')
    assert line['operations'][0]['macro_remaining'] == 0
    assert line['operations'][1]['macro_remaining'] == 17
    assert all(item['ocr_quantity'] is None for item in line['operations'])


@pytest.mark.pg_integration
@pytest.mark.skipif(os.environ.get('RUN_PG_INTEGRATION')!='1', reason='PostgreSQL descartável opt-in')
def test_latest_cpis_blocks_closed_of_even_when_user_pinned_open_version(registry):
    from datetime import datetime, timezone
    first = cpis_sync.publish([direct_row('OF4200')], datetime.now(timezone.utc), central_dsn=registry)
    assert planning_hub.require_operational_orders(['4200'], expected_version=first['version_id'])
    second = cpis_sync.publish([{**direct_row('OF4200'), 'status':'Fechada'}], datetime.now(timezone.utc), central_dsn=registry)
    # Historical consultation remains possible; completion must use current state.
    assert planning_hub.order_detail('4200', version=first['version_id'])['context']['cpis_status']=='Em Aberto'
    for version in (first['version_id'], second['version_id'], None):
        with pytest.raises(planning.PlanningError) as exc:
            planning_hub.require_operational_orders(['OF4200'], expected_version=version)
        assert exc.value.status == 409
    request = payload()
    request.update(cpis_version=first['version_id'], record_status='ready')
    with pytest.raises(planning.PlanningError, match='CPIS mudou'):
        planning.save_record(request)
    with psycopg.connect(registry, autocommit=True) as conn:
        conn.execute("UPDATE cpis_mtg.versions SET last_confirmed_at=now()-interval '16 minutes'")
    assert not planning_hub.source_status()['completion_allowed']
    with pytest.raises(planning.PlanningError, match='15 minutos'):
        planning_hub.require_operational_orders(['OF4200'])


@pytest.mark.pg_integration
@pytest.mark.skipif(os.environ.get('RUN_PG_INTEGRATION')!='1', reason='PostgreSQL descartável opt-in')
def test_direct_list_reference_search_keeps_all_ovs_and_pagination_stable(registry):
    from datetime import datetime, timezone
    rows = [direct_row(f'OF{number}') for number in range(100, 160)]
    rows += [direct_row('OF4200', 'OV-A'), direct_row('OF4200', 'OV-B')]
    for index, row in enumerate(rows, 1):
        row['source_row_no'] = index
    published = cpis_sync.publish(rows, datetime.now(timezone.utc), central_dsn=registry)
    first = planning_hub.list_orders(page=1)
    second = planning_hub.list_orders(page=2, version=first['version'])
    identities = [row['of'] for row in first['orders'] + second['orders']]
    assert len(identities) == len(set(identities)) == first['total'] == 61
    result = planning_hub.list_orders(query='REF-A')
    assert result['total']==1 and result['orders'][0]['of']=='OF4200'
    assert set(result['orders'][0]['ovs'])=={'OV-A', 'OV-B'}
    assert not result['orders'][0]['conflicts']
    assert result['version']==published['version_id']


@pytest.mark.pg_integration
@pytest.mark.skipif(os.environ.get('RUN_PG_INTEGRATION')!='1', reason='PostgreSQL descartável opt-in')
def test_abocardar_preparation_uses_abocardar_balance_not_cut_balance(registry):
    from datetime import datetime, timezone
    published=cpis_sync.publish([direct_row('OF4200')],datetime.now(timezone.utc),central_dsn=registry)
    with psycopg.connect(registry, autocommit=True) as conn:
        conn.execute("INSERT INTO raw_mtg.machine_rows VALUES ('s1','Abocardar',NULL,'{}')")
        conn.execute("UPDATE analytics_mtg.kanban_plan_lines SET remaining_quantity=0 WHERE plan_key='s1:10'")
        conn.execute("UPDATE raw_mtg.plan_production_rows SET row_data=%s WHERE source_line_id='s1:10'",
                     (Jsonb({'Ser.':100, 'Aborc.':'X', 'Aboc.':83}),))
    request=payload()
    request.update(record_status='ready',cpis_version=published['version_id'])
    request['values'].update(operation='abocardar',machine='Abocardar',quantity_to_plan=17)
    saved = planning.save_record(request)
    assert planning.get_record(saved['id'])['record']['record_status']=='ready'
    request.update(request_id=str(uuid.uuid4()),record_id=saved['id'],revision=1)
    request['values']['quantity_to_plan']=0
    with pytest.raises(planning.PlanningError, match='divergência'):
        planning.save_record(request)

