"""Verify the isolated candidate and preserve the independent calculation cut."""
from pathlib import Path
import argparse
import hashlib
import json
import os
from datetime import datetime, timezone

FOLDER=Path('docs/validacao-planeamento-integral/20260923-execucao')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['before','after']);args=parser.parse_args()
    os.environ['MES_PG_DSN']=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
    from app import planning
    from app.raw import query
    from scripts.audit_planning_selected_ocr import source_fingerprints
    reference=json.loads((FOLDER/'t5-association-hours-rebuild.json').read_text())
    report={'at':datetime.now(timezone.utc).isoformat(),'stage':args.stage,'areas':{},'local_tables':{},'history_counts':{},
            'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'failures':[]}
    with planning.connect(readonly=True) as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ');c.execute('SET LOCAL jit=off')
        assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
        report['sources']=source_fingerprints(c)
        if report['sources']!=reference['sources_after']:report['failures'].append('baseline_source_change')
        for area in planning.AREAS:
            old=query.generation(c,area,reference['after'][area]);new=query.generation(c,area)
            old_sql,old_args=query.source(old);new_sql,new_args=query.source(new)
            counts=c.execute('WITH old AS (SELECT m.row_key,c.values_json'+old_sql+'), new AS (SELECT m.row_key,c.values_json'+new_sql+''')
                SELECT count(*) n,count(*) FILTER(WHERE old.row_key IS NULL OR new.row_key IS NULL) identity_changes,
                    count(*) FILTER(WHERE old.values_json IS DISTINCT FROM new.values_json) value_changes
                FROM old FULL JOIN new USING(row_key)''',old_args+new_args).fetchone()
            counts.update(reference_generation=old['id'],generation=new['id'],aggregates_pending=new['metadata'].get('aggregates_pending'))
            report['areas'][area]=counts
            if counts['identity_changes'] or counts['value_changes'] or counts['aggregates_pending']:report['failures'].append(area)
        for table in ['needs','need_operations','need_sources','need_events','field_state','records','record_versions',
                      'association_decisions','original_association_decisions','need_conferences','need_commands',
                      'local_orders','local_order_history','raw_objects','raw_object_versions','raw_generations']:
            exists=c.execute('SELECT to_regclass(%s) t',('planning_mtg.'+table,)).fetchone()['t']
            if exists:
                report['local_tables'][table]=c.execute("SELECT count(*) n,md5(string_agg(h,'' ORDER BY h)) hash FROM (SELECT md5(to_jsonb(t)::text) h FROM planning_mtg."+table+' t) hashes').fetchone()
        for table in ['raw_contents','raw_members']:
            report['history_counts'][table]=c.execute('SELECT count(*) n FROM planning_mtg.'+table).fetchone()['n']
        report['original_instances']=c.execute('SELECT count(*) n FROM ocr_original.instances').fetchone()['n']
    if args.stage=='after':
        before=json.loads((FOLDER/'t7-persistence-before.json').read_text())
        for field in ['areas','sources','local_tables','history_counts','original_instances']:
            if report[field]!=before[field]:report['failures'].append('restart_changed:'+field)
    report['result']='passed' if not report['failures'] else 'failed'
    (FOLDER/('t7-persistence-'+args.stage+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n')
    print(report['result'],report['areas'],report['failures'])
    assert not report['failures']


if __name__=='__main__':main()
