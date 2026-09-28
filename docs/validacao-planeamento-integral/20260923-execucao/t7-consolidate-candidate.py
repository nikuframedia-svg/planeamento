"""Register current proofs and keep incomplete gates explicit; no production writes."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,subprocess,zipfile

F=Path('docs/validacao-planeamento-integral/20260923-execucao')
read=lambda n:json.loads((F/n).read_text())
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
now=datetime.now(timezone.utc).isoformat()
old=read('t3-live-mes-reconciliation-before-drive-sqlite.json');current=read('t3-live-mes-reconciliation.json')
assert old['central_before_sha256']==old['central_after_sha256']
pinned={'at':now,'cut':old['at'],'original_report':'t3-live-mes-reconciliation-before-drive-sqlite.json',
    'original_report_sha256':sha(F/'t3-live-mes-reconciliation-before-drive-sqlite.json'),'areas':{},'corrections':[],
    'boundary':'Certifies the fixed 295-sheet MES cut. Later source arrivals and real original ingestion remain separate pending gates.'}
drive=read('t3-drive-source-analysis.json')
backup=next(r for r in drive['database_archive_files'] if r['Path']=='SAIDA/backups/kanban-mes/app-20260924-063002.db')
assert current['cantoneiras_backup']['sha256']==backup['Hashes']['sha256']
for area,v in old['areas'].items():
    assert v['source_population_stable'] and not v['source_only'] and not v['central_only']
    projection=v['central_projection']
    assert not projection['missing_or_changed'] and not projection['extra_or_changed']
    for r in v['checks']:
        if not r['differences']:continue
        proof=next(x for x in current['areas'][area]['checks'] if x['uid']==r['uid'])
        assert proof['classification']=='display_order_only_proven_by_sqlite'
        assert all(proof[k]==r[k] for k in ('source_sha256','expected_sha256'))
        pinned['corrections'].append({'area':area,'uid':r['uid'],'sheet_no':r['sheet_no'],
            'revision':proof['backup_revision'],'identity_rows_exact':True,'display_order':proof['export_display_order'],
            'source_sha256':r['source_sha256'],'stored_rows_sha256':r['expected_sha256']})
    pinned['areas'][area]={'source_sheets':v['source_sheets'],'central_sheets':v['central_sheets'],
        'source_pages':v['source_pages'],'central_projection':projection}
pinned['source_backup_sha256']=backup['Hashes']['sha256'];pinned['result']='passed_in_stated_scope'
(F/'t3-mes-pinned-cut-reconciled.json').write_text(json.dumps(pinned,ensure_ascii=False,indent=2)+'\n')

assert read('t4-full-association-browser.json')['result']=='passed'
assert read('t4-original-final-ocr-incremental-browser.json')['result']=='passed'
assert read('t4-original-worker-recovery.json')['result']=='passed'
assert read('t7-persistence-after.json')['result']=='passed'
assert read('t5-final-rule-acceptance.json')['result']=='passed_in_stated_scope'
assert '67 passed' in (F/'t7-concurrency-final-regression.log').read_text()
assert '10 passed' in (F/'t7-final-local-publication.log').read_text()
assert 'passed' in (F/'t7-final-hours-resource-regression.log').read_text() and 'failed' not in (F/'t7-final-hours-resource-regression.log').read_text()
preserved=read('preexisting-tracked-preservation.json')
assert len(preserved)==27 and all(sha(r['path'])==r['baseline_sha256'] for r in preserved)

m=read('execution-manifest.json');baseline=read('baseline.json')
if not (F/'execution-manifest-before-remaining-plan.json').exists():
    (F/'execution-manifest-before-remaining-plan.json').write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n')
added=['tests/planning_original_recovery_browser.cjs','tests/test_planning_original_associations.py',
    'tests/planning_original_association_full_browser.cjs','tests/planning_original_incremental_browser.cjs',
    'tests/test_planning_original_hours.py','tests/planning_original_association_browser.cjs',
    'scripts/reconcile_planning_live_mes.py','scripts/audit_planning_final_persistence.py',
    'scripts/audit_planning_final_acceptance.py','scripts/planning_original_live_trial.py',
    'sql/033_original_ocr_associations.sql']
for path in added:m['changes_this_execution'].setdefault(path,{'before':baseline['files'].get(path)})
for path,v in m['changes_this_execution'].items():v['after']=sha(path)
m['code_digest']=hashlib.sha256(json.dumps({k:v['after'] for k,v in sorted(m['changes_this_execution'].items())},sort_keys=True).encode()).hexdigest()
m['at']=now;m['validation_status']='Associações/horas originais concluídas; 43 regras preservadas; regressão afetada e cópia integral/reinício aprovados. Ingestão original real, Calibri, cobertura cumulativa V06 e publicação permanecem incompletas.'
for migration in ['sql/031_planning_member_dependencies.sql','sql/032_planning_estimate_storage.sql','sql/033_original_ocr_associations.sql']:
    if migration not in m['isolated_migrations']:m['isolated_migrations'].append(migration)
for name in ['execution-manifest.json','execution-manifest-t7-current-candidate.json']:
    (F/name).write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n')

server=read('t7-current-server.json');worker=read('t4-original-worker.json')
assert all(Path(f'/proc/{x["pid"]}').exists() for x in [server,worker])
runtime={k:v['after'] for k,v in m['changes_this_execution'].items() if k.startswith('app/')}
start=int(next(line.split()[1] for line in Path('/proc/stat').read_text().splitlines() if line.startswith('btime ')))+float(Path(f'/proc/{server["pid"]}/stat').read_text().split()[21])/os.sysconf('SC_CLK_TCK')
assert not [p for p in runtime if Path(p).stat().st_mtime>start+1]
units={unit:int(subprocess.check_output(['systemctl','--user','show',unit,'-p','MainPID','--value'],text=True)) for unit in ['kanban-planning.service','kanban-raw-worker.service','kanban-mes.service','kanban-mes-mtg2.service']}
with zipfile.ZipFile('docs/raw-completa/conectores-pc.zip') as z:
    bundle=json.loads(z.read('manifest.json'));assert all(hashlib.sha256(z.read(p)).hexdigest()==h for p,h in bundle.items())
    assert bundle['raw_connectors/original_ocr.py']==sha('app/original_ocr.py')
state={'at':now,'revision':m['code_digest'],'execution_files_verified':len(m['changes_this_execution']),
    'runtime_digest':hashlib.sha256(json.dumps(runtime,sort_keys=True).encode()).hexdigest(),
    'isolated_server_pid':server['pid'],'isolated_worker_pid':worker['pid'],'isolated_base':'http://127.0.0.1:18113',
    'runtime_files_precede_server_start':True,'preexisting_tracked_preserved':27,
    'operational_pids':units,'operational_deployment_executed':False,'static_assets_shared_with_8113':True,
    'candidate_sources':read('t7-persistence-after.json')['sources'],'candidate_generations':read('t5-final-rule-acceptance.json')['current_planning'],
    'whole_delivery':'incomplete','bundle_sha256':sha('docs/raw-completa/conectores-pc.zip'),
    'validation_stages':{'after_associations_hours':'t7-current-regression.log: 577 passed; before later performance/concurrency changes',
        'affected_final':'t7-concurrency-final-regression.log: 67 passed',
        'local_serialization_final':'t7-final-local-publication.log: 10 passed; suites overlap, do not sum',
        'original_resource_identity_final':'t7-final-hours-resource-regression.log: current affected hours/resource/capacity tests'},
    'remaining':['current original SQLite and continuous real ingestion','Calibri effective 11pt','global dependency coverage and cumulative V06','final acceptance and publication with new source cut']}
(F/'t7-candidate-final-state.json').write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'revision':m['code_digest'],'files':len(m['changes_this_execution']),'pinned_mes_cut':295,'rules':43,'delivery':'incomplete'}))
