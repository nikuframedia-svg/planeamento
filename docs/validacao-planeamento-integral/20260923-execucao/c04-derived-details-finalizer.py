from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,urllib.request
folder=Path('docs/validacao-planeamento-integral/20260923-execucao')
read=lambda n:json.loads((folder/n).read_text())
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
m=read('execution-manifest.json');previous=read('c04-hours-detail-final-state.json')
assert m['code_digest']==previous['revision']
changed=['app/planning_calculations.py','app/web/static/raw_workspace.js','scripts/audit_planning_semantic_results.py','tests/planning_semantic_detail_browser.cjs']
added=['tests/test_planning_calculation_details.py','scripts/audit_planning_calculation_details.py','tests/planning_calculation_details_browser.cjs']
assert set(k for k,v in m['changes_this_execution'].items() if sha(k)!=v['after'])==set(changed)
assert not set(added)&set(m['changes_this_execution'])
audit=read('c04-derived-details-population.json');arithmetic=read('c04-derived-details-arithmetic.json');semantic=read('c04-derived-details-semantic.json')
raw=read('c04-derived-details-browser-final.json');semantic_browser=read('c04-derived-details-semantic-browser.json');rebuild=read('c04-derived-details-rebuild.json')
assert all(x['result']=='passed' for x in (audit,semantic,raw,semantic_browser,rebuild))
assert arithmetic['result']=='passed_in_stated_scope'
assert audit['script_sha256']==sha(added[1]) and raw['script_sha256']==sha(added[2])
assert semantic['script_sha256']==sha(changed[2]) and semantic_browser['script_sha256']==sha(changed[3])
assert audit['checks']==8147719 and not audit['failures']
assert not arithmetic['failures'] and not semantic['failures']
assert sum(x['checks'] for x in arithmetic['areas'].values())==966629
assert sum(x['checks'] for x in semantic['areas'].values())==1701766
assert len(raw['cases'])==len(semantic_browser['cases'])==2 and not raw['errors'] and not semantic_browser['errors']
assert not rebuild['value_changes'] and not rebuild['unexpected_changes']
for a in (arithmetic,semantic):assert sha(folder/a['ledger']['file'])==a['ledger']['sha256']
assert '142 passed' in (folder/'c04-derived-details-regression.log').read_text()
assert '10 failed' in (folder/'c04-derived-details-before.log').read_text()
for archive,path in [('c04-derived-semantic-auditor-before.py',changed[2]),('c04-derived-semantic-browser-before.cjs',changed[3])]:
 assert sha(folder/archive)==m['changes_this_execution'][path]['after']
assert all(r['missing_inputs']==0 for a in read('c04-derived-details-input-gaps.json')['areas'].values() for r in a['numeric_rules'])
preserved=read('preexisting-tracked-preservation.json');assert len(preserved)==27 and all(sha(r['path'])==r['baseline_sha256'] for r in preserved)
for b in previous['source_workbooks']:assert sha(b['file'])==b['sha256']
command=lambda pid:Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0',b' ').decode().strip()
for pid,cmd in previous['operational_processes'].items():assert command(pid)==cmd
server=read('c04-derived-details-server.json');assert server['previous_pid']==previous['isolated_server_pid']
assert 'app.web.planning_app:app' in command(server['pid']) and '--port 18113' in command(server['pid'])
config=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())
env=dict(e.decode().split('=',1) for e in Path(f"/proc/{server['pid']}/environ").read_bytes().split(b'\0') if b'=' in e)
assert env['MES_PG_DSN']==config['dsn'] and env['MES_DATA_DIR']=='/tmp/planning-integral-data'
assert env['MES_DOSSIER_WORKER_DISABLED']=='1'
os.environ['MES_PG_DSN']=config['dsn']
from app import planning
from app.raw import query
from scripts.audit_planning_selected_ocr import source_fingerprints
with planning.connect(readonly=True) as c:
 c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
 assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
 sources=source_fingerprints(c);versions={a:{dataset:query.generation(c,a,dataset=dataset)['id'] for dataset in ('planning','capacity_items','capacity','capacity_machines')} for a in planning.AREAS}
 configs={str(r['id']):dict(r) for r in c.execute("SELECT * FROM planning_mtg.raw_objects WHERE NOT archived AND kind IN ('resource','calendar','rate')")}
 config_hash=hashlib.sha256(json.dumps(configs,sort_keys=True,default=str).encode()).hexdigest()
 assert config_hash==previous['configuration_sha256']
 assert hashlib.sha256(json.dumps({k:v for k,v in configs.items() if v['kind'] in ('resource','rate')},sort_keys=True,default=str).encode()).hexdigest()==read('c04-hours-detail-population.json')['configuration_sha256']
assert sources==previous['source_fingerprints']==audit['sources_before']==audit['sources_after']==rebuild['sources_after']==semantic['sources_after']
assert {a:v['planning'] for a,v in versions.items()}==rebuild['after']
assert all(audit['areas'][a]['generation']==arithmetic['areas'][a]['version']==semantic['areas'][a]['generation']==rebuild['after'][a] for a in planning.AREAS)
assert all(int(case['version'])==rebuild['after'][case['area']] for proof in (raw,semantic_browser) for case in proof['cases'])
assert all(info['generation']==rebuild['after'][area] for area,info in read('c04-derived-details-input-gaps.json')['areas'].items())
static={name:{str(port):hashlib.sha256(urllib.request.urlopen(f'http://127.0.0.1:{port}/static/{name}',timeout=10).read()).hexdigest() for port in (8113,18113)} for name in ('raw_workspace.js','capacity.js')}
for name,ports in static.items():assert all(v==sha('app/web/static/'+name) for v in ports.values())
for path in changed+added:m['changes_this_execution'][path]={'before':read('baseline.json')['files'].get(path),'after':sha(path)}
assert all(sha(k)==v['after'] for k,v in m['changes_this_execution'].items())
m['code_digest']=hashlib.sha256(json.dumps({k:v['after'] for k,v in sorted(m['changes_this_execution'].items())},sort_keys=True).encode()).hexdigest()
m['at']=datetime.now(timezone.utc).isoformat();m['validation_status']='Explicações de produção/saldos/geometria/comprimentos/pesos/semana: 8147719 verificações, zero diferenças, nenhum resultado numérico conhecido com entradas vazias. Aritmética e semântica atuais passaram; 142 testes e quatro percursos browser. C04 integral e restantes checkpoints continuam incompletos.'
state={k:previous[k] for k in ('source_workbooks','operational_processes','hours_contract','capacity_contract','rules_without_full_population_arithmetic_or_semantic_audit')}
state.update(at=m['at'],revision=m['code_digest'],execution_files_verified=len(m['changes_this_execution']),
 previous_stage='c04-hours-detail-final-state.json',preexisting_tracked_preserved=27,source_fingerprints=sources,
 generations=rebuild['after'],capacity_versions=versions,configuration_sha256=config_hash,
 isolated_server_pid=server['pid'],isolated_command=command(server['pid']),served_static_sha256=static,
 operational_processes_not_restarted=True,isolated_server_restarted=True,static_assets_shared_with_operational_planning=True,
 contract='planning-integral-20260923-v4',detail_checks=8147719,arithmetic_checks=966629,semantic_checks=1701766,
 regression_tests=142,browser_cases=4,browser_errors=0,numerical_and_other_values_unchanged=True,value_changes=0,
 this_stage_database_writes='Only disposable tests and isolated projection rebuild; original inputs/configurations unchanged',
 this_stage_process_restarts='Only isolated server 18113',whole_delivery='incomplete')
for name,data in [('execution-manifest.json',m),('execution-manifest-c04-derived-details-validated.json',m),('c04-derived-details-final-state.json',state)]:
 (folder/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'revision':m['code_digest'],'files':len(m['changes_this_execution']),'versions':versions,'preserved':27}))
