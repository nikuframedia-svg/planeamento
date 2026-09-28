"""Read-only before/after audit, including linked documents and audit receipts."""
import argparse,hashlib,json,os,sqlite3
from datetime import datetime,timezone
from pathlib import Path

F=Path('docs/validacao-planeamento-integral/20260923-execucao')
P=Path('/home/luis/.local/state/planning-backups/integral-20260923')


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,default=str,ensure_ascii=False).encode()).hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['before','after']);args=parser.parse_args()
    os.environ['MES_PG_DSN']=json.loads((P/'isolated.json').read_text())['dsn']
    os.environ['MES_DATA_DIR']='/tmp/planning-integral-data'
    from app import planning
    from app.raw import query
    from app.dossiers import store
    from scripts.audit_planning_selected_ocr import source_fingerprints
    report={'at':datetime.now(timezone.utc).isoformat(),'stage':args.stage,'environment':'planning_integral; read-only',
            'populations':{},'tables':{},'document_tables':{},'files':{},'failures':[]}
    with planning.connect(readonly=True) as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
        report['sources']=source_fingerprints(c)
        for area in planning.AREAS:
            for dataset in ['planning','production','production_hours','orders','capacity','capacity_items','capacity_machines']:
                gen=query.generation(c,area,dataset=dataset);base,params=query.source(gen)
                value=c.execute("SELECT count(*) n,md5(string_agg(md5(m.row_key||c.values_json::text||c.detail::text),'' ORDER BY m.row_key)) hash"+base,params).fetchone()
                report['populations'][dataset+':'+area]={'generation':gen['id'],**value}
                if dataset=='planning' and (gen['metadata'].get('aggregates_pending') or gen['metadata'].get('source_refresh_pending')):report['failures'].append(area+':pending')
        for table in ['needs','need_operations','need_sources','need_events','field_state','records','record_versions',
                      'association_decisions','original_association_decisions','need_conferences','need_commands',
                      'local_orders','local_order_history','raw_objects','raw_object_versions','raw_generations','audit_outbox']:
            if c.execute('SELECT to_regclass(%s) t',('planning_mtg.'+table,)).fetchone()['t']:
                report['tables'][table]=c.execute("SELECT count(*) n,md5(string_agg(h,'' ORDER BY h)) hash FROM (SELECT md5(to_jsonb(t)::text) h FROM planning_mtg."+table+' t) x').fetchone()
        report['history_counts']={table:c.execute('SELECT count(*) n FROM planning_mtg.'+table).fetchone()['n'] for table in ['raw_contents','raw_members']}
        outbox=c.execute('SELECT id,document_id,piece_id,delivered_at FROM planning_mtg.audit_outbox ORDER BY id').fetchall()
        report['audit_delivery']={'total':len(outbox),'pending':sum(r['delivered_at'] is None for r in outbox)}
        if report['audit_delivery']['pending']:report['failures'].append('pending_document_audit')
    path=store.root()/'dossiers.db'
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as c:
        c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON');c.execute('BEGIN')
        names=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        for table in names:
            rows=[dict(r) for r in c.execute('SELECT * FROM "'+table.replace('"','""')+'"')]
            report['document_tables'][table]={'n':len(rows),'sha256':digest(sorted(digest(row) for row in rows))}
        receipts={r[0] for r in c.execute('SELECT id FROM planning_event_receipts')}
        for event in outbox:
            if str(event['id']) not in receipts:report['failures'].append('missing_receipt:'+str(event['id']))
        report['audit_delivery']['receipts']=len(receipts)
    for file in sorted(store.root().rglob('*')):
        if file.is_file() and not file.name.startswith('dossiers.db'):
            report['files'][str(file.relative_to(store.root()))]={'size':file.stat().st_size,'sha256':hashlib.sha256(file.read_bytes()).hexdigest()}
    if args.stage=='after':
        before=json.loads((F/'t10-persistence-before.json').read_text())
        for field in ['sources','populations','tables','history_counts','document_tables','audit_delivery','files']:
            if report[field]!=before[field]:report['failures'].append('restart_changed:'+field)
    report['result']='failed' if report['failures'] else 'passed'
    (F/('t10-persistence-'+args.stage+'.json')).write_text(json.dumps(report,indent=2,default=str)+'\n')
    print(report['result'],report['failures'],flush=True)
    assert not report['failures']


if __name__=='__main__':main()
