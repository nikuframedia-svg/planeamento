"""Compare every legacy RAW membership with the previously published projection."""
import os,json,hashlib
from pathlib import Path
from datetime import datetime,timezone

folder=Path('docs/validacao-planeamento-integral/20260923-execucao')
os.environ['MES_PG_DSN']=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
from app import planning,planning_raw
from app.raw import query
from scripts.audit_planning_selected_ocr import source_fingerprints

report={'at':datetime.now(timezone.utc).isoformat(),'environment':'planning_integral clone, read only',
 'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
 'method':'Complete legacy Perfis RAW identity/OF/active comparison to immutable generation published before the builder fix. No rebuild or source mutation.',
 'scopes':{},'failures':[]}
with planning.connect(readonly=True) as c:
 c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
 assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
 report['sources_before']=source_fingerprints(c)
 gen=query.generation(c,'perfis');base,args=query.source(gen)
 rows=c.execute("SELECT m.row_key,c.values_json->>'of' of,(c.values_json->>'planning_active')::boolean active"+base,args).fetchall()
 report['generation']=gen['id']
expected={r['row_key']:(r['of'],r['active']) for r in rows}
data=planning_raw.dataset(force=True)
actual={r['key']:(r['values']['of'],r['population']['active']) for r in data['rows']}
assert len(actual)==len(data['rows']), 'Duplicate keys in old RAW'
for key in set(expected)|set(actual):
 if expected.get(key)!=actual.get(key):report['failures'].append({'key':key,'expected':expected.get(key),'actual':actual.get(key)})
for scope in ('active','history','all'):
 target={k for k,v in expected.items() if scope=='all' or v[1]==(scope=='active')}
 found={r['key'] for r in planning_raw.filtered(data,{'population':scope})}
 report['scopes'][scope]={'expected':len(target),'observed':len(found),'identities_equal':target==found,
  'identity_sha256':hashlib.sha256(json.dumps(sorted(found)).encode()).hexdigest()}
 if target!=found:report['failures'].append({'scope':scope,'missing':sorted(target-found),'unexpected':sorted(found-target)})
with planning.connect(readonly=True) as c:report['sources_after']=source_fingerprints(c)
assert report['sources_before']==report['sources_after']
report['result']='passed' if not report['failures'] else 'failed'
(folder/'c06-legacy-raw-population-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n')
print(json.dumps({k:report[k] for k in ('result','generation','scopes')}))
assert not report['failures'],report['failures'][:3]
