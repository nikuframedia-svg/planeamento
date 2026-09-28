from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os
folder=Path('docs/validacao-planeamento-integral/20260923-execucao')
read=lambda n:json.loads((folder/n).read_text())
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
previous=read('c04-derived-details-final-state.json');m=read('execution-manifest.json')
assert m['code_digest']==previous['revision'] and all(sha(k)==v['after'] for k,v in m['changes_this_execution'].items())
added=['scripts/audit_planning_actual_hours.py','scripts/audit_planning_historical_cohorts.py',
       'tests/test_planning_actual_hours_audit.py','tests/test_planning_historical_cohort_audit.py','tests/planning_time_cohorts_browser.cjs']
assert not set(added)&set(m['changes_this_execution'])
h=read('c04-actual-hours-current.json');p=read('c10-historical-cohorts-final.json');b=read('c10-cohorts-browser-final.json');fixture=read('c10-cohorts-browser-fixture.json')
assert all(x['result']=='passed' for x in (h,p,b)) and not h['failures'] and not p['failures'] and not b['errors']
assert h['checks']==1894 and len(h['weeks'])==185 and len(h['observations'])==286
assert p['checks']==107520 and p['unique_histories']==105 and p['contexts']==123
assert sum(a['pieces'] for a in p['areas'].values())==83156 and sum(a['estimates'] for a in p['areas'].values())==105999
assert h['input_sha256']==p['hours_input_sha256']
assert h['script_sha256']==sha(added[0]) and p['script_sha256']==sha(added[1]) and b['script_sha256']==sha(added[-1])
assert sha(folder/p['ledger']['file'])==p['ledger']['sha256']
assert len(b['actual'])==4 and len(b['historical'])==2
assert b['fixture_sha256']==sha(folder/'c10-cohorts-browser-fixture.json')
assert all(sha(folder/n)==v for n,v in fixture['input_proofs'].items())
assert '64 passed' in (folder/'c10-cohorts-regression.log').read_text()
assert '32 passed' in (folder/'c10-cohort-auditor-examples.log').read_text()
preserved=read('preexisting-tracked-preservation.json');assert len(preserved)==27 and all(sha(r['path'])==r['baseline_sha256'] for r in preserved)
for book in previous['source_workbooks']:assert sha(book['file'])==book['sha256']
command=lambda pid:Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0',b' ').decode().strip()
for pid,cmd in previous['operational_processes'].items():assert command(pid)==cmd
assert command(previous['isolated_server_pid'])==previous['isolated_command']
os.environ['MES_PG_DSN']=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
from app import planning
from app.raw import query
from scripts.audit_planning_selected_ocr import source_fingerprints
from scripts.audit_planning_actual_hours import load_inputs,digest
with planning.connect(readonly=True) as c:
 c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
 assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
 sources=source_fingerprints(c)
 versions={a:{dataset:query.generation(c,a,dataset=dataset)['id'] for dataset in ('planning','capacity_items','capacity','capacity_machines','production','production_hours')} for a in planning.AREAS}
 for area in planning.AREAS:
  for dataset,g in previous['capacity_versions'][area].items():assert versions[area][dataset]==g
  for proof in (h,p):
   for dataset,g in proof['versions'][area].items():assert versions[area][dataset]==g
 assert digest(load_inputs(c)[-1])==h['input_sha256']
 configs={str(r['id']):dict(r) for r in c.execute("SELECT * FROM planning_mtg.raw_objects WHERE NOT archived AND kind IN ('resource','calendar','rate')")}
 assert hashlib.sha256(json.dumps(configs,sort_keys=True,default=str).encode()).hexdigest()==previous['configuration_sha256']
assert sources==previous['source_fingerprints']==h['sources_before']==h['sources_after']==p['sources_before']==p['sources_after']
for path in added:m['changes_this_execution'][path]={'before':read('baseline.json')['files'].get(path),'after':sha(path)}
m['code_digest']=hashlib.sha256(json.dumps({k:v['after'] for k,v in sorted(m['changes_this_execution'].items())},sort_keys=True).encode()).hexdigest()
m['at']=datetime.now(timezone.utc).isoformat();m['validation_status']='H03/H09: horas reais e aceitação/exclusão de todos os contextos históricos atuais conferidos independentemente.1894+107520 verificações,64testes,6browser,zero diferenças. Fontes C01/C02, matrizes de atualização e entrega integral continuam incompletas.'
state={k:previous[k] for k in ('source_workbooks','operational_processes','isolated_server_pid','isolated_command','configuration_sha256','hours_contract','capacity_contract','contract')}
state.update(at=m['at'],revision=m['code_digest'],execution_files_verified=len(m['changes_this_execution']),
 previous_stage='c04-derived-details-final-state.json',preexisting_tracked_preserved=27,source_fingerprints=sources,
 generations={a:v['planning'] for a,v in versions.items()},capacity_versions=versions,
 this_stage_application_changes=False,this_stage_database_writes=False,this_stage_process_restarts=False,
 h03={'checks':h['checks'],'sheets':286,'central_records':2351,'weeks':185,'manual_declarations':h['manual_declarations'],'known_weekly_totals':sum(w['expected'] is not None for w in h['weeks'])},
 h09={'checks':p['checks'],'histories':105,'contexts':123,'pieces':83156,'estimates':105999,'events':p['events'],'cohort_checks':p['cohort_checks']},
 hours_input_sha256=h['input_sha256'],regression_tests=64,browser_cases=6,browser_errors=0,
 rules_without_full_population_arithmetic_or_semantic_audit=['F02','F03','G01'],whole_delivery='incomplete')
for name,data in [('execution-manifest.json',m),('execution-manifest-c10-time-cohorts-validated.json',m),('c10-time-cohorts-final-state.json',state)]:
 (folder/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'revision':m['code_digest'],'files':len(m['changes_this_execution']),'versions':versions,'preexisting_preserved':27}))
