from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os
folder=Path('docs/validacao-planeamento-integral/20260923-execucao');read=lambda n:json.loads((folder/n).read_text());sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
m=read('execution-manifest.json');previous=read('c02-sources-c05-forms-final-state.json');assert m['code_digest']==previous['revision']
changed=['app/planning_hub.py','app/planning_production.py','app/planning_associations.py','app/raw/projection.py','app/raw/ocr_scope.py','app/web/templates/ocr_original.html']
added=['app/planning_original_production.py','tests/test_planning_original_production.py','tests/planning_original_source_browser.cjs','app/original_ocr.py','app/web/static/ocr_original.js']
assert {k for k,v in m['changes_this_execution'].items() if sha(k)!=v['after']}==set(changed)
assert not set(added)&set(m['changes_this_execution'])
assert '48 passed' in (folder/'c01-original-pipeline-current-regression.log').read_text()
assert '1 passed' in (folder/'c01-original-browser-final.log').read_text()
b=read('c01-original-source-browser.json');assert b['result']=='passed' and not b['errors'] and len(b['records'])==2
assert b['script_sha256']==sha('tests/planning_original_source_browser.cjs')
preserved=read('preexisting-tracked-preservation.json');assert len(preserved)==27 and all(sha(r['path'])==r['baseline_sha256'] for r in preserved)
command=lambda pid:Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0',b' ').decode().strip()
for pid,cmd in previous['operational_processes'].items():assert command(pid)==cmd
assert command(previous['isolated_server_pid'])==previous['isolated_command']
os.environ['MES_PG_DSN']=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
from app import planning
from app.raw import query
from scripts.audit_planning_selected_ocr import source_fingerprints
with planning.connect(readonly=True) as c:
 c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
 assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
 sources=source_fingerprints(c);assert sources==previous['source_fingerprints']
 versions={a:{dataset:query.generation(c,a,dataset=dataset)['id'] for dataset in ('planning','capacity_items','capacity','capacity_machines','production','production_hours')} for a in planning.AREAS}
 assert versions==previous['capacity_versions']
 originals=c.execute('SELECT count(*) n FROM ocr_original.instances').fetchone()['n'];assert originals==0
 configs={str(r['id']):dict(r) for r in c.execute("SELECT * FROM planning_mtg.raw_objects WHERE NOT archived AND kind IN ('resource','calendar','rate')")}
 assert hashlib.sha256(json.dumps(configs,sort_keys=True,default=str).encode()).hexdigest()==previous['configuration_sha256']
for path in changed+added:m['changes_this_execution'][path]={'before':read('baseline.json')['files'].get(path),'after':sha(path)}
m['code_digest']=hashlib.sha256(json.dumps({k:v['after'] for k,v in sorted(m['changes_this_execution'].items())},sort_keys=True).encode()).hexdigest();m['at']=datetime.now(timezone.utc).isoformat()
m['validation_status']='OCR original ligado ao motor, revisões incrementais, bloqueio de sobreposição e diagnóstico por evento.48 testes e browser final passaram. Esquema real sem identidade/operação exige associação humana ainda por ligar; ingestão Windows e entrega integral incompletas.'
state={k:v for k,v in previous.items() if k in ('source_workbooks','operational_processes','configuration_sha256','hours_contract','capacity_contract','contract','isolated_server_pid','isolated_command','generations','capacity_versions')}
state.update(at=m['at'],revision=m['code_digest'],execution_files_verified=len(m['changes_this_execution']),previous_stage='c02-sources-c05-forms-final-state.json',preexisting_tracked_preserved=27,source_fingerprints=sources,whole_delivery='incomplete',original_instances_in_full_clone=originals,this_stage_database_writes='Disposable test databases only; full clone unchanged',this_stage_process_restarts=False,isolated_persistent_server_loaded_revision=previous['revision'],current_code_browser_tested_in_disposable_server=True,full_clone_not_rebuilt_this_stage=True,regression_tests=48,browser_final_tests=1,static_assets_shared_with_operational_planning=True)
for name,data in [('execution-manifest.json',m),('execution-manifest-c01-original-pipeline.json',m),('c01-original-pipeline-final-state.json',state)]:
 (folder/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
exec(Path('/tmp/register_c04_excel_source.py').read_text().split("add('c04-excel-source-regression.log'")[0])
entries=[('c01-original-pipeline-current-regression.log',['C01.3','C01.4','C01.5','C02.3','C05.4','C11.1'],'48 passaram: snapshot original, revisões/repetição/retirada, saldo comum, ligação local, conflitos, evidência e regressões MES.'),('c01-original-browser-final.log',['C01.3','C01.5','C11.2'],'Browser final passou após corrigir a descrição antiga e a apresentação de OF/operação.'),('c01-original-source-browser.json',['C01.3','C01.5','C11.2'],'Dois registos: identidade suficiente e identidade ausente; estado da revisão aplicada e diagnósticos individuais conferidos.'),('c01-original-source-browser.png',['C01.3','C11.2'],'Captura do browser descartável; não representa fonte Windows real.'),('c01-original-schema-reference.json',['C01.2','C01.3'],'Esquema do código original consultado; perfil/operação não garantidos. Não comprova base/processo em execução no PC.'),('c01-original-pipeline-method.md',['C01.3','C01.4','C01.5','C02.3','C05.4'],'Método, distinção de fixtures, limitações e próximos trabalhos explícitos.'),('c01-original-pipeline-final-state.json',['C00.1','C11.3'],'Fontes/configurações/gerações/27tracked/processos persistentes preservados; testes do novo backend num servidor descartável.')]
names=set()
for name,criteria,observed in entries:
 add(name,criteria,'Ver c01-original-pipeline-method.md e produtores referidos.',observed,observed);names.add(name)
for e in d['evidencias']:
 if e['id'] in names:
  e['ambiente']='SQLite/PostgreSQL/servidor descartáveis para os testes; clone integral apenas leitura. Nenhum reinício persistente. Estáticos partilhados com Planeamento.'
  e['entradas']={'scope':'Fixtures descartáveis; fonte real Windows não validada','full_clone_original_instances':0,'persistent_server_loaded_revision':previous['revision']}
for cp in d['checkpoints']:
 for c in cp['criterios']:
  if c['id'] in ('C01.3','C01.5'):c['observacoes']+=' Ligação funcional do original ao motor implementada e testada: snapshots atuais, revisões incrementais, derivados, origem e diagnóstico por registo.48 testes e browser passaram. Falta associação humana dos IDs originais, horas originais e publicação real no PC. Não aprovar C01 por fixtures.'
  if c['id']=='C02.3':c['observacoes']+=' Original e MES mantêm IDs/origens distintos; sobreposição não entra em saldos nem produtividade histórica. Prova descartável passou. Equivalência/decisões humanas de original ainda pendentes.'
  if c['id']=='C11.1':c['observacoes']+=' Etapa original:48 testes afetados e um browser final passaram; não somar suites sobrepostas.'
d['execucao']['revisao_codigo']=rev
assert len(d['checkpoints'])==13 and sum(len(c['criterios']) for c in d['checkpoints'])==58 and len(d['formulas'])==43
p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
with (folder/'PROGRESSO.md').open('a') as f:
 f.write(f'\n### OCR original ligado ao motor comum\n\nRevisão `{rev}`, {len(m["changes_this_execution"])} ficheiros. Eliminada a separação funcional do original: eventos centrais entram no matcher/seletor partilhado, mantêm IDs/origem e participam em revisões incrementais. Sobreposição com MES fica excluída de saldos e histórico. Diagnóstico por registo e revisão aplicada visíveis.48 testes afetados e browser final passaram.\n\nVerificado o esquema original local: perfil/operação não garantidos. A associação automática só usa informação explícita suficiente; fixture do esquema real conserva exclusão com motivo. Próximo passo concreto: decisões humanas por ID estável original (a tabela atual aceita apenas ID numérico MES), depois horas originais. Acesso/publicação Windows real continua pendente.\n\nClone integral sem escritas/reconstrução, fontes/configurações/27tracked preservados; processos persistentes intactos. Backend novo testado em servidor descartável;18113 continua com a revisão anterior. Estáticos partilhados documentados. Nenhum novo checkpoint global aprovado; entrega incompleta. Método em `c01-original-pipeline-method.md`.\n')
for e in d['evidencias']:
 if e['id'] in names:assert sha(e['ficheiro_ou_url'])==e['sha256_artefacto']
print(json.dumps({'revision':rev,'files':len(m['changes_this_execution']),'proofs':len(names),'tests':48,'original_instances_real_clone':0,'delivery':'incomplete'}))
