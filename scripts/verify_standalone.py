"""Read-only before/after proof of the Planning project relocation."""
import argparse,hashlib,json,sqlite3,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/separacao-2026-09-24'


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['before','after']);args=parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(ROOT/'.env')
    from app import planning
    from app.raw import query
    state=json.loads((OUT/'migration.json').read_text())
    report={'at':datetime.now(timezone.utc).isoformat(),'stage':args.stage,'mode':__doc__,
            'tables':{},'populations':{},'document_tables':{},'document_files':{},'services':{},'failures':[]}
    with planning.connect(readonly=True) as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ');c.execute('SET LOCAL jit=off')
        assert c.execute('SELECT current_database() n').fetchone()['n']=='dataresearchmtg'
        for area in planning.AREAS:
            for dataset in ['planning','production','production_hours','orders','capacity','capacity_items','capacity_machines']:
                gen=query.generation(c,area,dataset=dataset);sql,params=query.source(gen)
                values=c.execute('SELECT count(*) n,md5(string_agg(md5(m.row_key||c.values_json::text||c.detail::text),\'\' ORDER BY m.row_key COLLATE "C")) hash'+sql,params).fetchone()
                report['populations'][dataset+':'+area]={'generation':gen['id'],**values}
                # Ancillary datasets retain metadata from the core publication;
                # current aggregate readiness is recorded on planning itself.
                if dataset=='planning' and (gen['metadata'].get('aggregates_pending') or gen['metadata'].get('source_refresh_pending')):
                    report['failures'].append(dataset+':'+area+':pending')
        for table in ['mes_kanban.validated_sheets','mes_kanban.production_records','mes_kanban.production_record_plan_refs']+[
                'planning_mtg.'+t for t in ['needs','need_operations','need_sources','need_events','field_state','records',
                    'record_versions','association_decisions','original_association_decisions','need_conferences',
                    'need_commands','local_orders','local_order_history','raw_objects','raw_object_versions','audit_outbox']]:
            report['tables'][table]=c.execute("SELECT count(*) n,md5(string_agg(h,'' ORDER BY h COLLATE \"C\")) hash FROM (SELECT md5(to_jsonb(t)::text) h FROM "+table+' t) q').fetchone()
        report['worker']=c.execute("SELECT source,attempted_at,confirmed_at,available,error FROM planning_mtg.raw_worker_state WHERE source IN ('perfis','cantoneiras','capacity','documents') ORDER BY source").fetchall()
        if not all(s['available'] and not s['error'] for s in report['worker']):report['failures'].append('worker')
    documents=Path(state['old_root'] if args.stage=='before' else state['new_root'])/'data/dossiers'
    db=documents/'dossiers.db';report['document_db_inode']=db.stat().st_ino
    with sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True) as c:
        c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON');c.execute('BEGIN')
        assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        for row in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall():
            table=row['name'];rows=[dict(r) for r in c.execute('SELECT * FROM "'+table.replace('"','""')+'"')]
            report['document_tables'][table]={'rows':len(rows),'hash':digest(sorted(digest(r) for r in rows))}
    for p in sorted(documents.rglob('*')):
        if p.is_file() and not p.name.startswith('dossiers.db') and p.suffix!='.lock':
            report['document_files'][str(p.relative_to(documents))]={'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    for unit in state['units_before']:
        props=dict(line.split('=',1) for line in subprocess.check_output(['systemctl','--user','show',unit,'-p','MainPID','-p','ActiveState','-p','WorkingDirectory'],text=True).splitlines())
        assert props['ActiveState']=='active',unit
        if unit in ['kanban-mes.service','kanban-mes-mtg2.service']:
            assert props['MainPID']==state['units_before'][unit],unit
        elif args.stage=='after':
            assert props['MainPID']!=state['units_before'][unit],unit
            assert props['WorkingDirectory']==str(ROOT),unit
            assert (Path('/proc')/props['MainPID']/'cwd').resolve()==ROOT,unit
            command=(Path('/proc')/props['MainPID']/'cmdline').read_bytes().decode().replace('\0',' ')
            assert str(ROOT/'.venv/bin/python') in command,command
            props['command']=command
        report['services'][unit]=props
    if args.stage=='after':
        before=json.loads((OUT/'before.json').read_text())
        for field in ['tables','populations','document_tables','document_files','document_db_inode']:
            if report[field]!=before[field]:report['failures'].append('changed:'+field)
        manifest=json.loads((OUT/'runtime-manifest.json').read_text())
        assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==sha for p,sha in manifest['files'].items())
        report['candidate']=manifest['candidate'];report['runtime_files_checked']=len(manifest['files'])
        report['python_prefix']=sys.prefix;assert Path(sys.prefix)==ROOT/'.venv'
        assert not any(p.is_symlink() and str(p.resolve()).startswith(state['old_root']) for p in (ROOT/'app').rglob('*'))
    report['result']='failed' if report['failures'] else 'passed'
    (OUT/(args.stage+'.json')).write_text(json.dumps(report,indent=2,ensure_ascii=False,default=str)+'\n')
    print(report['result'],len(report['populations']),'datasets;',len(report['tables']),'tables;',report['failures'],flush=True)
    assert not report['failures']


if __name__=='__main__':main()
