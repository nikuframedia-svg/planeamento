from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,urllib.request,re
folder=Path('docs/validacao-planeamento-integral/20260923-execucao')
read=lambda n:json.loads((folder/n).read_text())
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
previous=read('c10-time-cohorts-final-state.json');m=read('execution-manifest.json')
assert m['code_digest']==previous['revision']
changed=['app/planning_calculations.py','app/web/static/need_editor.js','scripts/audit_planning_semantic_results.py','tests/planning_semantic_detail_browser.cjs','scripts/audit_planning_calculation_details.py','tests/planning_calculation_details_browser.cjs','app/planning_associations.py','tests/test_planning_needs.py']
added=['scripts/audit_planning_production_sources.py','tests/test_planning_production_source_policy.py','tests/planning_production_source_preview_browser.cjs','tests/planning_production_sources_browser.cjs','tests/planning_direct_form_browser.cjs','tests/planning_typography_browser.cjs','tests/planning_browser.cjs']
assert {k for k,v in m['changes_this_execution'].items() if sha(k)!=v['after']}==set(changed)
assert not set(added)&set(m['changes_this_execution'])
proofs={name:read(name) for name in ['c02-source-policy-population.json','c02-source-policy-central.json','c02-source-policy-details-final.json','c02-source-policy-semantic.json','c02-source-policy-preview-browser.json','c02-source-policy-states-browser.json','c05-direct-form-browser.json']}
for name,p in proofs.items():
 assert p['result'] in ('passed','passed_in_stated_scope'),name
 assert not p.get('failures') and not p.get('errors'),name
producers={'c02-source-policy-population.json':added[0],'c02-source-policy-central.json':'scripts/audit_planning_selected_ocr.py','c02-source-policy-details-final.json':changed[4],'c02-source-policy-semantic.json':changed[2],'c02-source-policy-preview-browser.json':added[2],'c02-source-policy-states-browser.json':added[3],'c05-direct-form-browser.json':added[4]}
for name,path in producers.items():assert proofs[name]['script_sha256']==sha(path),(name,path)
for name in ['c02-source-policy-population.json','c02-source-policy-semantic.json']:
 ledger=proofs[name]['ledger'];assert sha(folder/ledger['file'])==ledger['sha256']
assert proofs['c02-source-policy-population.json']['checks']==1778925
assert proofs['c02-source-policy-details-final.json']['checks']==8147719
assert len(proofs['c02-source-policy-preview-browser.json']['steps'])==3
assert len(proofs['c02-source-policy-states-browser.json']['cases'])==8
assert len(proofs['c05-direct-form-browser.json']['cases'])==2
assert '140 passed' in (folder/'c02-source-policy-regression.log').read_text()
assert '1 passed' in (folder/'c11-common-editor-browser.log').read_text()
assert '39 passed' in (folder/'c02-removed-evidence-regression.log').read_text()
assert '1 passed' in (folder/'c02-removed-evidence-final.log').read_text()
typography=read('c08-pages-browser.json');assert typography['result']=='passed_typography_and_reflow' and len(typography['cases'])==14 and not typography['errors']
assert typography['script_sha256']==sha('tests/planning_typography_browser.cjs')
regression=(folder/'c11-current-regression.log').read_text()
assert 'failed' not in regression and 'passed' in regression
counts=re.search(r'(\d+) passed, (\d+) skipped',regression);assert counts and int(counts[2])==1
preserved=read('preexisting-tracked-preservation.json');assert len(preserved)==27 and all(sha(r['path'])==r['baseline_sha256'] for r in preserved)
for book in previous['source_workbooks']:assert sha(book['file'])==book['sha256']
command=lambda pid:Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0',b' ').decode().strip()
for pid,cmd in previous['operational_processes'].items():assert command(pid)==cmd
initial_server=read('c02-source-policy-server.json');assert initial_server['previous_pid']==previous['isolated_server_pid']
server=read('c02-removed-evidence-server.json');assert server['previous_pid']==initial_server['pid']
assert 'app.web.planning_app:app' in command(server['pid']) and '--port 18113' in command(server['pid'])
config=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text());os.environ['MES_PG_DSN']=config['dsn']
from app import planning
from app.raw import query
from scripts.audit_planning_selected_ocr import source_fingerprints
with planning.connect(readonly=True) as c:
 c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
 assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
 sources=source_fingerprints(c)
 versions={a:{dataset:query.generation(c,a,dataset=dataset)['id'] for dataset in ('planning','capacity_items','capacity','capacity_machines','production','production_hours')} for a in planning.AREAS}
 configs={str(r['id']):dict(r) for r in c.execute("SELECT * FROM planning_mtg.raw_objects WHERE NOT archived AND kind IN ('resource','calendar','rate')")}
 assert hashlib.sha256(json.dumps(configs,sort_keys=True,default=str).encode()).hexdigest()==previous['configuration_sha256']
assert sources==previous['source_fingerprints']
rebuild=read('c02-source-policy-rebuild.json');assert rebuild['result']=='passed' and not rebuild['value_changes'] and not rebuild['unexpected_changes']
assert sources==rebuild['sources_before']==rebuild['sources_after']
for name in ['c02-source-policy-population.json','c02-source-policy-details-final.json','c02-source-policy-semantic.json']:
 p=proofs[name];assert sources==p['sources_before']==p['sources_after']
 for area in planning.AREAS:assert p['areas'][area]['generation']==versions[area]['planning']==rebuild['after'][area]
for name in ['c02-source-policy-states-browser.json','c05-direct-form-browser.json']:
 for case in proofs[name]['cases']:assert int(case['version'])==versions[case['area']]['planning']
static={str(port):hashlib.sha256(urllib.request.urlopen(f'http://127.0.0.1:{port}/static/need_editor.js',timeout=10).read()).hexdigest() for port in (8113,18113)}
assert all(v==sha('app/web/static/need_editor.js') for v in static.values())
for path in changed+added:m['changes_this_execution'][path]={'before':read('baseline.json')['files'].get(path),'after':sha(path)}
assert all(sha(k)==v['after'] for k,v in m['changes_this_execution'].items())
m['code_digest']=hashlib.sha256(json.dumps({k:v['after'] for k,v in sorted(m['changes_this_execution'].items())},sort_keys=True).encode()).hexdigest()
m['at']=datetime.now(timezone.utc).isoformat();m['validation_status']='Seleção por peça/operação auditada; troca de operação não transfere acumulado Excel; abertura RAW/formulário corrigida. Regressão conjunta e browser manual/PDF passaram. Restantes gates do plano continuam pendentes.'
state={k:previous[k] for k in ('source_workbooks','operational_processes','configuration_sha256','hours_contract','capacity_contract')}
state.update(at=m['at'],revision=m['code_digest'],previous_stage='c10-time-cohorts-final-state.json',execution_files_verified=len(m['changes_this_execution']),preexisting_tracked_preserved=27,source_fingerprints=sources,generations=rebuild['after'],capacity_versions=versions,contract='planning-integral-20260923-v5',isolated_server_pid=server['pid'],isolated_command=command(server['pid']),served_need_editor_sha256=static,regression_tests=int(counts[1]),separately_executed_opt_in_browser=1,source_selection_checks=1778925,detail_checks=8147719,selection_browser_states=8,operation_preview_steps=3,direct_form_areas=2,rules_without_full_population_arithmetic_or_semantic_audit=[],numerical_and_other_values_unchanged=True,this_stage_database_writes='Disposable test databases and isolated projection rebuild only',this_stage_process_restarts='Only isolated server 18113',static_assets_shared_with_operational_planning=True,whole_delivery='incomplete')
for name,data in [('execution-manifest.json',m),('execution-manifest-c02-sources-c05-forms.json',m),('c02-sources-c05-forms-final-state.json',state)]:
 (folder/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'revision':m['code_digest'],'files':len(m['changes_this_execution']),'tests':int(counts[1]),'versions':versions}))
