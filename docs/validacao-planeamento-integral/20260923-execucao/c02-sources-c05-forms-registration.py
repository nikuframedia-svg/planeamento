from pathlib import Path
from datetime import datetime,timezone
import json,hashlib
folder=Path('docs/validacao-planeamento-integral/20260923-execucao');read=lambda n:json.loads((folder/n).read_text());sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
# The last regression extends an existing execution file after the state check.
m=read('execution-manifest.json');state=read('c02-sources-c05-forms-final-state.json');path='tests/test_planning_ocr_incremental.py'
assert {k for k,v in m['changes_this_execution'].items() if sha(k)!=v['after']}=={path}
assert '1 passed' in (folder/'c02-removed-evidence-projection.log').read_text()
m['changes_this_execution'][path]['after']=sha(path)
m['code_digest']=hashlib.sha256(json.dumps({k:v['after'] for k,v in sorted(m['changes_this_execution'].items())},sort_keys=True).encode()).hexdigest();m['at']=datetime.now(timezone.utc).isoformat()
state.update(revision=m['code_digest'],at=m['at'],removed_ocr_evidence_regression=True,removed_ocr_incremental_equals_full=True)
for name,data in [('execution-manifest.json',m),('execution-manifest-c02-sources-c05-forms.json',m),('c02-sources-c05-forms-final-state.json',state)]:
 (folder/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
exec(Path('/tmp/register_c04_excel_source.py').read_text().split("add('c04-excel-source-regression.log'")[0])
entries=[
 ('c02-source-policy-population.json',['C02.4','C02.5','C04.1','C04.5'],'Auditor independente de seleção: 1778925 verificações, 83156 peças, zero diferenças.'),
 ('c02-source-policy-central.json',['C02.1','C02.3','C11.3'],'2351 registos centrais; 1389 totais OCR; nenhuma divergência no âmbito documentado.'),
 ('c02-source-policy-details-final.json',['C04.5','C11.3'],'8147719 verificações de explicação; zero diferenças.'),
 ('c02-source-policy-semantic.json',['C04.1','C04.5'],'1701766 verificações semânticas; zero diferenças.'),
 ('c02-source-policy-regression.log',['C02.4','C02.5','C04.3','C11.1'],'140 testes passaram.'),
 ('c02-source-policy-preview-browser.json',['C02.4','C02.5','C05.1'],'112→119→112: o acumulado Excel pertence só à operação original; três passos passaram.'),
 ('c02-source-policy-states-browser.json',['C02.4','C02.5','C04.5'],'Oito estados visíveis nas duas áreas, esperados independentes; zero erros JS.'),
 ('c05-direct-form-browser.json',['C03.4','C05.1','C11.2'],'Abrir formulário a partir da RAW e pré-visualizar a peça certa passou nas duas áreas.'),
 ('c05-direct-form-before.log',['C05.1'],'Reprodução: uma linha existente não abria porque as referências ainda não tinham sido carregadas.'),
 ('c02-removed-evidence-before.log',['C01.4','C02.1','C05.5'],'Reprodução: desaparecimento do registo OCR interrompia a consulta de evidência com erro 404.'),
 ('c02-removed-evidence-final.log',['C01.4','C02.1','C05.5'],'Registo removido mantém decisão, produção desconhecida e aviso; teste passou.'),
 ('c02-removed-evidence-projection.log',['C01.4','C02.1','C05.4','C05.5'],'Remoção com decisão humana: publicação incremental igual à reconstrução completa; saldo desconhecido; passou.'),
 ('c11-current-regression.log',['C11.1'],'552 testes passaram; browser opt-in foi executado separadamente.'),
 ('c11-common-editor-browser.log',['C03.4','C05.1','C11.1','C11.2'],'Browser opt-in passou: manual/PDF, gravação, reabertura, identidade e decisões humanas.'),
 ('c08-pages-browser.json',['C08.2','C08.3','C11.2'],'14 percursos, 2170 elementos a 11pt, sem transbordo horizontal; Calibri efetiva continua ausente.'),
 ('c02-source-policy-rebuild.json',['C04.5','C11.3'],'Reconstrução 4323/4324 preservou valores escalares, identidades e fontes.'),
 ('c02-sources-c05-forms-final-state.json',['C00.1','C11.3'],'165 ficheiros conferidos; 27 tracked, fontes, configurações e processos operacionais preservados.'),
 ('c02-sources-c05-forms-method.md',['C02.4','C02.5','C04.5','C05.1','C08.2','C11.1'],'Método, comandos, tentativas, limites e trabalho restante.'),
]
names=set()
for name,criteria,observed in entries:
 failure=name in ('c05-direct-form-before.log','c02-removed-evidence-before.log')
 add(name,criteria,'Ver comando e produtor em c02-sources-c05-forms-method.md.',observed,observed,exit_code=1 if failure else 0);names.add(name)
for e in d['evidencias']:
 if e['id'] in names:
  e['ambiente']='Cópia integral planning_integral 44164/18113; testes em PostgreSQL descartável. Estáticos partilhados com 8113; apenas backend isolado reiniciado.'
  e['entradas']={'generations':state['generations'],'contract':state['contract'],'boundary':'Ingestão real do OCR original, matriz integral de associações e publicação continuam pendentes.'}
  if e['codigo_saida']:e['resultado']='Falha reproduzida antes da correção; prova final correspondente passou.'
  if e['id']=='c08-pages-browser.json':e['resultado']='Passou tamanho e adaptação; Calibri efetiva não disponível. C08.3 permanece incompleto.'
for cp in d['checkpoints']:
 for c in cp['criterios']:
  if c['id'] in ('C02.4','C02.5'):
   c['estado']='aprovado';c['observacoes']='Seleção por peça/operação, cobertura incompleta, fallback compatível, zero local, conflitos, excesso e operações separadas conferidos independentemente em toda a população publicada e em casos dedicados. Oito estados browser e troca de operação passaram. Ingestão e decisões humanas/entre origens permanecem C01/C02.1–C02.3.'
  if c['id']=='C08.2':
   c['estado']='aprovado';c['observacoes']='Declaração Calibri e 11pt conferidas na RAW e em todas as restantes páginas: 14 percursos, 2170 elementos visíveis, sem transbordo do documento. Verificação da fonte efetiva é C08.3, ainda incompleta.'
  if c['id']=='C10.4':
   c['estado']='aprovado';c['observacoes']='Provas existentes relidas e hashes conferidos: c10-refresh-browser.json/c10-refresh-history-audit.json cobrem 15 passos de horas, janela 1/90 dias, taxa manual vigente/expirada/desativada e fallback nas duas áreas; c10-visible-final-ocr-incremental-browser.json cobre inserção/correção/remoção, seis passos sem F5 dentro do limite. H03/H09 atuais confrontam os dados centrais disponíveis. Ingestão real original permanece C01; não exigir novamente os mesmos cenários já aprovados.'
  if c['id'].startswith('C04.'):
   c['observacoes']+=' F02/F03/G01 agora têm auditoria independente de seleção: 1778925 verificações, zero diferenças. As 43 regras dispõem de auditorias específicas no âmbito documentado; falta fechar a aceitação integrada, sem repetir provas não invalidadas.'
  if c['id']=='C11.1':c['observacoes']='Regressão conjunta atual: 552 passaram; único browser opt-in executado separadamente e passou. Após correção de OCR removido, 39 regressões afetadas passaram e dois novos casos de evidência/publicação passaram. Suites sobrepostas não somadas.'
for rule in d['formulas']:
 if rule['id'] in ('F02','F03','G01'):
  rule['estado']='em_curso';rule['observacoes']='Seleção por operação auditada independentemente na população completa, casos dedicados e browser; ingestão e associação permanecem nos gates próprios.'
  for name in ['c02-source-policy-population.json','c02-source-policy-regression.log','c02-source-policy-preview-browser.json','c02-source-policy-states-browser.json']:
   if name not in rule['evidencias']:rule['evidencias'].append(name)
d['execucao']['revisao_codigo']=rev
assert len(d['checkpoints'])==13 and sum(len(c['criterios']) for c in d['checkpoints'])==58 and len(d['formulas'])==43
assert [c['id'] for c in d['checkpoints'] if c['estado']=='aprovado']==['C00','C03','C06','C07','C09']
p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
with (folder/'PROGRESSO.md').open('a') as f:
 f.write(f'\n### Seleção por operação, formulário e desvalidação OCR\n\nRevisão `{rev}`, 165 ficheiros. Corrigidos acumulado Excel transferido entre operações, abertura RAW/formulário sem referências carregadas e falha de evidência/reconstrução quando desaparece um registo OCR com decisão humana. Decisão preservada; saldo desconhecido, com aviso.\n\n552 testes passaram; browser opt-in executado separadamente e passou. Regressões afetadas e dois novos casos de remoção passaram. Oito estados de produção, três trocas de operação e duas aberturas RAW/formulário passaram. 1778925 verificações independentes da seleção, sem diferenças; as 43 regras têm agora auditorias específicas. 14 percursos de tipografia passaram; Calibri efetiva continua ausente.\n\nC02.4/C02.5/C08.2 aprovados. C10.4 aprovado após reler as provas já existentes dos 15 passos de histórico e seis atualizações OCR; não repetir requisitos já demonstrados. Cinco checkpoints globais aprovados. Fontes/configurações/27 tracked preservados, gerações 4323/4324; servidor isolado 2629383. Publicação integral pendente. Método em `c02-sources-c05-forms-method.md`.\n')
for e in d['evidencias']:
 if e['id'] in names:assert sha(e['ficheiro_ou_url'])==e['sha256_artefacto']
print('Registered',len(names),'proofs; revision',rev,'; four additional criteria approved; full delivery incomplete.')
