"""Read-only PDF-context checks against immutable RAW and real source files."""
import os,json,hashlib
from pathlib import Path
from datetime import datetime,timezone
from collections import defaultdict

folder=Path('docs/validacao-planeamento-integral/20260923-execucao')
os.environ['MES_PG_DSN']=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
from app import planning
from app.raw import query
from app.dossiers import cpis
from scripts.audit_planning_selected_ocr import source_fingerprints

report={'at':datetime.now(timezone.utc).isoformat(),'environment':'planning_integral clone, read only',
 'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
 'method':'One real OF for each observed CPIS-state/closure-source/local-or-macro combination; compare every member of each selected OF to the previously published RAW generation. Synthetic transitions tested separately.',
 'samples':[],'failures':[]}
with planning.connect(readonly=True) as c:
 c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
 assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
 report['sources_before']=source_fingerprints(c)
 gen=query.generation(c,'perfis');base,args=query.source(gen)
 rows=c.execute("SELECT m.row_key,c.values_json->>'of' of,(c.values_json->>'planning_active')::boolean active,c.detail->'status_values' statuses,c.detail->'population' population,c.detail->>'need_id' need_id"+base,args).fetchall()
 report['generation']=gen['id'];report['population_rows']=len(rows)
 expected=defaultdict(dict);selected={}
 for row in rows:
  expected[row['of']][row['row_key']]=row['active']
  kind=(tuple(sorted(row['statuses'] or [])),tuple((row['population'] or {}).get('closed_sources',[])),bool(row['need_id']))
  if row['of'] is not None:selected.setdefault(kind,row['of'])
for of in sorted(set(selected.values())):
 ctx=cpis.read_context(of)
 actual={m['key']:m['population']['active'] for m in ctx['planning_members']}
 if actual!=expected[of]:report['failures'].append({'of':of,'expected':expected[of],'actual':actual})
 cp_closed=any(str(s).strip().lower() in ('fechada','fechado') for s in ctx['status_values'])
 if ctx['population']['active']==cp_closed:report['failures'].append({'of':of,'order_classification':ctx['population']})
 if ('of_closed' in {i['code'] for i in ctx['issues']})!=cp_closed:report['failures'].append({'of':of,'issue_classification':ctx['issues']})
 assert all(r['planning_key'] in actual and r['population']['active']==actual[r['planning_key']] for r in ctx['plan_rows'])
 report['samples'].append({'of':of,'cpis_version':ctx['cpis_version'],'status_values':ctx['status_values'],
  'members':len(actual),'active':sum(actual.values()),'history':sum(not v for v in actual.values()),
  'source_rows':len(ctx['plan_rows']),'issue_codes':[i['code'] for i in ctx['issues']],
  'source_freshness':ctx['source_freshness'],'source_sha256':ctx['source']['source_sha256']})
with planning.connect(readonly=True) as c:report['sources_after']=source_fingerprints(c)
assert report['sources_before']==report['sources_after']
report['combinations']=len(selected);report['members_compared']=sum(r['members'] for r in report['samples'])
report['result']='passed_in_stated_scope' if not report['failures'] else 'failed'
(folder/'c06-dossiers-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n')
print(json.dumps({k:report[k] for k in ['result','generation','population_rows','combinations','members_compared']})+' OFs='+str(len(report['samples'])))
assert not report['failures'], report['failures'][:2]
