"""Run the F12 browser simulation between read-only snapshots of the full clone."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
from datetime import datetime, timezone

folder=Path('docs/validacao-planeamento-integral/20260923-execucao')
os.environ['MES_PG_DSN']=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
from app import planning
from app.raw import query


def snapshot():
    result={}
    with planning.connect(readonly=True) as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        assert c.execute('SELECT current_database() name').fetchone()['name']=='planning_integral'
        for table in ['needs','records','record_versions','need_events','need_commands','audit_outbox',
                      'raw_objects','raw_object_versions','raw_signals','raw_jobs']:
            rows=c.execute('SELECT to_jsonb(t) v FROM planning_mtg.'+table+' t ORDER BY to_jsonb(t)::text').fetchall()
            result[table]={'count':len(rows),'sha256':hashlib.sha256(json.dumps(rows,sort_keys=True,default=str).encode()).hexdigest()}
        for table in ['raw_contents','raw_members','raw_generations']:
            result[table]=c.execute('SELECT count(*) count FROM planning_mtg.'+table).fetchone()
        result['current_generations']={area:{dataset:query.generation(c,area,dataset=dataset)['id']
            for dataset in ['planning','production','production_hours','orders','capacity','capacity_items','capacity_machines']}
            for area in planning.AREAS}
    return result


report={'at':datetime.now(timezone.utc).isoformat(),'environment':'isolated full copy localhost44164/18113','before':snapshot()}
env={**os.environ,'PLANNING_CHECK_BASE':'http://127.0.0.1:18113','PLANNING_TEST_ISOLATED':'1'}
# Browser receives no database credential.
env.pop('MES_PG_DSN',None)
completed=subprocess.run(['node','tests/planning_capacity_preview_browser.cjs'],env=env)
report['browser_exit_code']=completed.returncode
report['after']=snapshot()
report['unchanged']=report['before']==report['after']
report['result']='passed' if report['unchanged'] and completed.returncode==0 else 'failed'
(folder/'c05-f12-readonly-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n')
assert report['result']=='passed',report['result']
print('Browser simulations left all checked revisions, records, commands, evidence and generations unchanged.',flush=True)
