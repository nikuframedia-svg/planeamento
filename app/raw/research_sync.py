"""Durable one-way mirror to the new research database, independent of UI saves.

Read a consistent application snapshot and switch all destination heads in one
transaction. Versions and identical content are reused. Source records retain
their own keys; CPIS, Excel and OCR are never unioned into additive demand.
"""
import argparse
import json
import logging
import os
from pathlib import Path
import time

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .. import planning, planning_needs as needs
from . import query

APPLICATION_TABLES = ('needs','need_operations','need_sources','records','record_versions',
    'need_events','field_state','local_orders','local_order_history','association_decisions',
    'original_association_decisions','need_conferences','order_registration',
    'sku_family_rules','sku_family_heads','sku_family_mappings','sku_family_history',
    # Planning decisions (plano de 01/10/2026): selection, priorities, sets, machines, quotas.
    'sector_selection','sector_decision_events','sector_priority_policies','sector_priority_overrides',
    'sector_reference_sets','sector_reference_set_members','sector_machine_actions',
    'sector_machine_decisions','sector_machine_decision_history','sector_machine_preferences',
    'sector_capacity_quotas','sector_config_events',
    # Seleção por membro (plano de 02/10/2026); os rascunhos da Carteira ficam no browser.
    'sector_member_selection','sector_selection_requests',
    # Máquina escolhida na Carteira e conjuntos de famílias (05/10/2026).
    'sector_member_machine','sector_family_sets',
    # Definições do setor: horário dos turnos, dias de trabalho e feriados (06/10/2026).
    'sector_settings')
# Configuration that explains a plan; conversations and transient caches stay out.
CONFIGURATION_KINDS = ('resource','calendar','rate','gantt')


def planning_configuration(c):
    if not c.execute("SELECT to_regclass('planning_mtg.raw_object_versions') t").fetchone()['t']:
        return None
    objects = c.execute('SELECT * FROM planning_mtg.raw_objects WHERE kind=ANY(%s)',(list(CONFIGURATION_KINDS),)).fetchall()
    versions = c.execute('''SELECT v.* FROM planning_mtg.raw_object_versions v JOIN planning_mtg.raw_objects o ON o.id=v.object_id
        WHERE o.kind=ANY(%s)''',(list(CONFIGURATION_KINDS),)).fetchall()
    rows = [('object:'+str(r['id']),needs.serial(r)) for r in objects]
    rows += [('version:'+str(r['object_id'])+':'+str(r['revision']),needs.serial(r)) for r in versions]
    return rows


def accepted_plans(c):
    """The accepted plan of each scenario and its segments: planned, never produced."""
    if not c.execute("SELECT to_regclass('planning_mtg.raw_jobs') t").fetchone()['t']:
        return None
    rows = []
    scenarios = c.execute("SELECT id,name,revision,definition FROM planning_mtg.raw_objects WHERE kind='gantt'").fetchall()
    for scenario in scenarios:
        accepted = scenario['definition'].get('accepted') or {}
        if not accepted.get('job_id'):
            continue
        job = c.execute("SELECT id,input,result,object_revision,finished_at FROM planning_mtg.raw_jobs WHERE id=%s AND kind='gantt'",
                        (accepted['job_id'],)).fetchone()
        if not job or not (job['result'] or {}).get('proposal'):
            continue
        snapshot = job['input'].get('snapshot') or {}
        ops = {o['key']:o for o in snapshot.get('operations',[])}
        header = {'scenario_id':str(scenario['id']),'scenario':scenario['name'],'scenario_revision':scenario['revision'],
                  'job_id':str(job['id']),'accepted_at':accepted.get('accepted_at'),'score':accepted.get('score'),
                  'started_at':job['input'].get('started_at'),'source_references':job['input'].get('source_references'),
                  'semantics':'Plano aceite: compromisso planeado, não produção observada.'}
        rows.append(('plan:'+str(scenario['id']),{**header,'kind':'header'}))
        for key,bar in job['result']['proposal'].get('bars',{}).items():
            op = ops.get(key,{})
            rows.append(('bar:'+str(scenario['id'])+':'+key,{**{k:header[k] for k in ('scenario_id','job_id','started_at')},
                'kind':'segment','operation_key':key,'area':op.get('area'),'of':op.get('of'),'reference':op.get('reference'),
                'operation':op.get('operation'),'occurrence':op.get('occurrence'),'resource_id':bar['resource_id'],
                'start_minute':bar['start_minute'],'end_minute':bar['end_minute'],'segments':bar.get('segments'),
                'provisional':bar.get('provisional'),'priority':op.get('priority')}))
    return rows


def target():
    access = os.environ['MES_RESEARCH_SYNC_ACCESS_FILE']
    c = psycopg.connect(**json.loads(Path(access).read_text()), row_factory=dict_row,
                        connect_timeout=10, application_name='planning_research_sync')
    expected = os.environ.get('MES_RESEARCH_SYNC_DATABASE','dataresearchmtg_planeamento_20260930')
    if c.execute('SELECT current_database() db').fetchone()['db'] != expected:
        c.close();raise ValueError('wrong_research_database')
    return c


def table(c, schema, name, where='', args=()):
    qualified = schema+'.'+name
    if not c.execute('SELECT to_regclass(%s) t',(qualified,)).fetchone()['t']:return None
    keys = c.execute('''SELECT a.attname FROM pg_index i
        CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY k(attnum,n)
        JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum
        WHERE i.indrelid=%s::regclass AND i.indisprimary ORDER BY k.n''', (qualified,)).fetchall()
    if not keys and schema=='raw_mtg' and name in ('plan_production_rows','cpis_rows'):
        keys=[{'attname':'snapshot_id'},{'attname':'source_line_id'}]
    if not keys:raise ValueError('missing_source_primary_key:'+qualified)
    rows = c.execute(sql.SQL('SELECT * FROM {}.{} ').format(sql.Identifier(schema),sql.Identifier(name))+sql.SQL(where),args).fetchall()
    result = []
    for row in rows:
        row = needs.serial(row)
        key = json.dumps([row[k['attname']] for k in keys],ensure_ascii=False,separators=(',',':'))
        result.append((key,row))
    return result


def packages(c, known=None):
    known = known or {}
    database = c.execute('SELECT current_database() db').fetchone()['db']
    meta = {'database':database,'contract':'planning-live-v1'}
    for name in APPLICATION_TABLES:
        rows = table(c,'planning_mtg',name)
        if rows is not None:yield 'application:'+name,rows,meta
    for name,builder in (('application:planning_configuration',planning_configuration),('application:accepted_plans',accepted_plans)):
        rows = builder(c)
        if rows is not None:yield name,rows,meta
    for name in ('validated_sheets','production_records'):
        yield 'mes:'+name,table(c,'mes_kanban',name),meta
    direct=c.execute('SELECT id FROM cpis_mtg.versions ORDER BY last_confirmed_at DESC LIMIT 1').fetchone()
    yield 'cpis_direct:orders',table(c,'cpis_mtg','orders','WHERE version_id=%s',(direct['id'],)) if direct else [],{**meta,'version':str(direct['id']) if direct else None}
    for area in planning.AREAS:
        snap = planning.snapshot(c,area)
        source_meta = {**meta,'snapshot':needs.serial(snap)}
        for name,prefix in (('plan_production_rows','excel'),('cpis_rows','cpis_excel')):
            if known.get(prefix+':'+area)==source_meta:continue
            yield prefix+':'+area,table(c,'raw_mtg',name,'WHERE snapshot_id=%s',(snap['snapshot_id'],)),source_meta
        gen = query.generation(c,area)
        generation_meta = {**meta,'generation':gen['id'],'published_at':str(gen['created_at']),
            'snapshot':needs.serial(gen['metadata'].get('snapshot')),
            'source_refresh_pending':gen['metadata'].get('source_refresh_pending',False)}
        if known.get('planning:'+area)==generation_meta:continue
        base,args = query.source(gen)
        # Carry source identity, manual input and warnings, not UI-only caches.
        records = c.execute('''SELECT m.row_key,c.values_json,
            jsonb_build_object('need_id',c.detail->'need_id','plan_key',c.detail->'plan_key',
              'revision',c.detail->'revision','origin',c.detail->'origin',
              'input_values',c.detail->'input_values','identity_pending',c.detail->'identity_pending',
              'identity_candidates',c.detail->'identity_candidates',
              'registration_warnings',c.detail->'registration_warnings',
              'warnings',c.detail->'warnings') detail'''+base,args).fetchall()
        rows = [(r['row_key'], {**r['detail'],'values':r['values_json']}) for r in records]
        yield 'planning:'+area,rows,generation_meta
    # Native and HTTP representations are alternatives, never additive events.
    native = c.execute('SELECT * FROM ocr_original.instances WHERE current_snapshot IS NOT NULL').fetchall()
    if native:
        rows = c.execute('''SELECT s.* FROM ocr_original.instances i
            JOIN ocr_original.snapshot_sheets x ON x.snapshot_id=i.current_snapshot
            JOIN ocr_original.sheets s USING(instance_id,sheet_id,content_hash)''').fetchall()
        yield 'ocr:native_sheets',[(str(r['instance_id'])+':'+str(r['sheet_id']),needs.serial(r)) for r in rows],meta
        yield 'ocr:validated_export',[],{**meta,'superseded_by':'ocr:native_sheets'}
    else:
        from . import ocr_export
        state = ocr_export.status(c)
        if state:
            rows = c.execute('SELECT row_key,payload FROM ocr_original.export_rows WHERE version_id=%s',(state['export']['current_version'],)).fetchall()
            yield 'ocr:validated_export',[(r['row_key'],r['payload']) for r in rows],{**meta,'version':state['export']['current_version'],'note':state['note']}
        yield 'ocr:native_sheets',[],meta


def publish(c, name, rows, metadata):
    if rows is None:raise ValueError('missing_required_dataset:'+name)
    members = sorted((key,needs.digest(data)) for key,data in rows)
    if len({key for key,_ in members}) != len(members):raise ValueError('duplicate_source_key:'+name)
    version = needs.digest([name,members,metadata])
    exists = c.execute('SELECT id FROM origem_v2.aplicacao_versoes WHERE id=%s',(version,)).fetchone()
    if not exists:
        c.execute('INSERT INTO origem_v2.aplicacao_versoes(id,conjunto,linhas,metadata) VALUES(%s,%s,%s,%s)',(version,name,len(rows),Jsonb(metadata)))
        c.execute('CREATE TEMP TABLE IF NOT EXISTS sync_content(hash text PRIMARY KEY,dados jsonb) ON COMMIT DROP')
        c.execute('TRUNCATE sync_content')
        contents = {needs.digest(data):data for _,data in rows}
        with c.cursor().copy('COPY sync_content(hash,dados) FROM STDIN') as copy:
            for key,data in contents.items():copy.write_row((key,Jsonb(data)))
        c.execute('INSERT INTO origem_v2.aplicacao_conteudos SELECT * FROM sync_content ON CONFLICT DO NOTHING')
        with c.cursor().copy('COPY origem_v2.aplicacao_membros(versao,chave,conteudo) FROM STDIN') as copy:
            for key,content in members:copy.write_row((version,key,content))
    c.execute('''INSERT INTO origem_v2.aplicacao_fontes(conjunto,versao) VALUES(%s,%s)
        ON CONFLICT(conjunto) DO UPDATE SET versao=excluded.versao,confirmada_em=now()''',(name,version))
    return {'dataset':name,'rows':len(rows),'unchanged':bool(exists)}


def refresh():
    try:
        with target() as destination, planning.connect(readonly=True) as source:
            if not destination.execute("SELECT pg_try_advisory_xact_lock(hashtext('planning-research-sync')) locked").fetchone()['locked']:
                return {'skipped':'already_running'}
            source.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            source.execute("SET LOCAL statement_timeout='120s'")
            known = {r['conjunto']:r['metadata'] for r in destination.execute('''SELECT f.conjunto,v.metadata
                FROM origem_v2.aplicacao_fontes f JOIN origem_v2.aplicacao_versoes v ON v.id=f.versao''').fetchall()}
            result = [publish(destination,*package) for package in packages(source,known)]
            destination.execute('UPDATE origem_v2.aplicacao_fontes SET confirmada_em=now()')
            destination.execute('''INSERT INTO origem_v2.aplicacao_sincronizacao(id,ultimo_sucesso)
                VALUES(true,now()) ON CONFLICT(id) DO UPDATE SET ultima_tentativa=now(),ultimo_sucesso=now(),erro=NULL''')
        return result
    except Exception as exc:
        try:
            with target() as c:
                c.execute('''INSERT INTO origem_v2.aplicacao_sincronizacao(id,erro) VALUES(true,%s)
                    ON CONFLICT(id) DO UPDATE SET ultima_tentativa=now(),erro=excluded.erro''',(type(exc).__name__,))
        except Exception:pass
        raise


def main():
    from dotenv import load_dotenv
    load_dotenv('.env')
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--watch',action='store_true');args=parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            result = refresh()
            print(json.dumps(result),flush=True)
        except Exception as exc:
            # Do not log credentials, SQL parameters, or business data.
            logging.error('Research synchronization failed: %s',type(exc).__name__)
            if not args.watch:raise SystemExit(1) from None
        if not args.watch:break
        time.sleep(60)


if __name__=='__main__':main()
