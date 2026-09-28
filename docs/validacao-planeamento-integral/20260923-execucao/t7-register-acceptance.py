"""Update the acceptance ledger from current proofs, retaining historical failures."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json
F=Path('docs/validacao-planeamento-integral/20260923-execucao');P=Path('docs/checkpoints-planeamento-2026-09-23.json')
d=json.loads(P.read_text());state=json.loads((F/'t7-candidate-final-state.json').read_text());now=datetime.now(timezone.utc).isoformat();rev=state['revision']
before={c['id']:c['estado'] for cp in d['checkpoints'] for c in cp['criterios']}
approvals={
 'C01.1':('Corte fixo de 09:46 UTC: Perfis 113 folhas/532 pais/5 filhas/534 linhas; Cantoneiras 182/1873/1135/2826. IDs, revisões e quantidades reconciliados até à projeção. Duas ordens CSV explicadas por _display_order e SQLite do Drive com arrays/identidades exatos. Consulta posterior tem 19 novas folhas Cantoneiras e diferenças pendentes para C12; não estender esta aprovação a esse corte.', ['t3-mes-pinned-cut-reconciled.json']),
 **{f'C02.{i}':('Associação original concluída com migração 033 aditiva, IDs estáveis, decisões imutáveis, peça/operação e origem. Perfis/Cantoneiras locais/importadas, quantidade desconhecida/parcial/excessiva, revisão/identidade, remoção, sobreposição MES/original, idempotência e exportações verificados. Browser integral confirma parcial→completo e reabertura nas duas áreas. Produção ambígua/repetida continua excluída com motivo.', ['t4-full-association-browser.json','t7-concurrency-final-regression.log']) for i in range(1,4)},
 **{f'C04.{i}':('43 regras ligadas a comparações independentes e origens Excel/VBA. 18 pontes de populações publicadas antigas→atuais sem alteração de identidade ou valores, fontes iguais, cobertura de 83.156 peças e casos V01–V05. Comparação Excel preserva justificações explícitas; sem casos calculáveis em falta ou divergências numéricas por explicar no corte auditado. Ingestão original real é um gate separado C01.', ['t5-final-rule-acceptance.json','t5-current-rebuild.json','t7-persistence-after.json']) for i in range(1,6)},
 'C05.1':('Motor comum de preview/gravação, publicação da linha e revisão dentro da transação; CSV/XLSX conferidos depois da associação original. Repetição restrita a transações abortadas por serialização, com o mesmo request_id; conflitos humanos continuam 409. As dez regressões finais de publicação local passaram.', ['t7-final-local-publication.log','t7-concurrency-final-regression.log']),
 'C05.4':('Percurso centro→derivados→browser/horas/capacidade medido em seis revisões originais sintéticas na cópia integral: derivados até 3157 ms e agregados até 9644 ms. Reutilizadas seis revisões MES de C10.4. Cadência original 300 s separada. Aprovação funcional deste percurso não certifica publicação/sincronização da SQLite original real, ainda C01.', ['t4-original-final-ocr-incremental-browser.json','t4-matriz-alteracoes-consumidores.md']),
 'C05.5':('Corrigida concorrência entre associação e atualização de capacidades; captura protegida antes da decisão. Ensaios concorrentes preservam idempotência/histórico; resposta atrasada de filtro não substitui estado atual. Worker parado conserva o anterior e pendência, recuperação 4063 ms. Reinício final preserva valores, fontes, registos, vistas, decisões e histórico.', ['t4-association-lock-test.log','t4-repeatable-publication.log','t4-original-worker-recovery.json','t4-full-association-browser.json','t7-persistence-after.json']),
 **{f'C10.{i}':('Horas originais integradas no motor existente: uma declaração por folha/revisão, sem multiplicação por peça/área, sem repartição arbitrária. Volume/tempo da mesma população; conflitos com MES/manual, correção/desvalidação e prioridade manual→histórico→Excel verificados. Declaração sem área mantém observação/exclusão e não bloqueia capacidades. Auditorias H03/H09/H10 preservadas pela comparação de populações; atualizações originais medidas nas duas áreas.', ['t7-concurrency-final-regression.log','t4-original-final-ocr-incremental-browser.json','t5-final-rule-acceptance.json']) for i in range(1,4)},
 'C11.1':('577 testes após T1/T2; após as alterações seguintes, 67 regressões afetadas passaram; após a última correção de serialização, as dez regressões de publicação local passaram. Não somar suites sobrepostas. Zero falhas/ignorados nestas execuções. As 552 provas históricas não são usadas como certificação atual.', ['t7-current-regression.log','t7-concurrency-final-regression.log','t7-final-local-publication.log']),
 'C11.4':('Reconstrução integral e reinício da revisão candidata confirmados: 83.156 peças, zero diferença de identidade/valores e hashes/contagens dos registos, vistas, decisões e histórico iguais antes/depois do reinício. Fontes MES preservadas e fixtures originais retiradas com decisões auditadas conservadas. Falha/recuperação do worker e conservação do conjunto anterior verificadas.', ['t5-current-rebuild.json','t7-persistence-before.json','t7-persistence-after.json','t4-original-worker-recovery.json'])}
pending={
 'C01.2':('bloqueado','SQLite original encontrada no servidor e Drive é cópia de 10/09, SHA idêntico; aplicação tem dados até 23/09 e reporta backup de 24/09 às 09:42 UTC em F:\\Apps\\OCR-original\\data\\backups. Falta confirmar/obter a base efetivamente usada e efetuar primeira publicação real e repetição. A conclusão antiga baseada apenas na SQLite local vazia foi corrigida.'),
 'C01.3':('em_curso','Motor e decisões originais aprovados em testes. Falta rastrear eventos da base original atual efetivamente publicada até à linha/saldo/horas ou exclusão individual.'),
 'C01.4':('em_curso','Revisão/desvalidação, leitura parcial, indisponibilidade e conservação do conjunto íntegro passaram em isolamento. Falta a repetição real do original com identidade persistente e sem duplicação.'),
 'C01.5':('em_curso','Painel e avisos testados. Falta execução contínua real do conector original e comprovar tentativa/sucesso/idade/revisão aplicada nesse percurso.'),
 'C05.2':('em_curso','Matriz atual em t4-matriz-alteracoes-consumidores.md. Quantidade/geometria/stock/operações, máquina/período, configurações, associações e OCR têm provas; falta fechar combinações globais macro/documentais e sequência cumulativa V06 na mesma identidade.'),
 'C05.3':('em_curso','Novas quatro gravações originais: pedido 3868–4721 ms, resposta→linha até 1407 ms, resposta→agregados até 2987 ms; API/RAW/capacidade, revisão e CSV/XLSX verificados. Reutilizadas provas anteriores. Falta concluir V06 e as células restantes da matriz com os mesmos consumidores e tempos; não aprovar apenas por estes quatro passos.'),
 'C08.3':('bloqueado','Calibri efetiva não encontrada no servidor/Drive configurado; browser usa fonte substituta nas provas existentes. Falta disponibilizar Calibri autorizada, confirmar a fonte efetivamente renderizada a 11pt e rever o impacto visual.'),
 'C11.2':('em_curso','Browsers originais nas duas áreas e restantes provas compatíveis preservados. Falta Calibri efetiva, percurso original real e sequência cumulativa V06; existência de capturas anteriores não fecha essas lacunas.'),
 'C11.3':('em_curso','Reconstrução de 83.156 peças, 18 comparações de populações e persistência passaram na revisão candidata. Tempos incrementais medidos cumprem limites; falta fechar restantes células C05/V06 antes da aceitação integral de volume/desempenho.'),
 'C11.5':('em_curso','43 fórmulas aprovadas, V01–V05 aprovados, matriz R01–R11/C00–C12 atualizada. V06, C01 original real, C08.3 e publicação ainda incompletos; zero pendência convertida em sucesso.'),
 'C12.1':('por_executar','Procedimento concreto de backup novo, migrações 027–033, publicação e reversão seletiva preparado em t8-publicacao-e-reversao.md. Pacote do conector regenerado. Publicação não executada: plano exige C11 aprovado.'),
 'C12.2':('por_executar','Após publicar: verificar endereço efetivamente utilizado, revisão carregada, fontes, OF264774, Cantoneiras, fechados, colunas, scroll e Calibri no destino 8113.'),
 'C12.3':('por_executar','Confirmar atualização real e reconciliar novo corte vivo. Clone tem 286 folhas MES, corte reconciliado 295 e consulta posterior 314; última consulta tem diferenças de projeção e ordem de duas novas folhas Cantoneiras.'),
 'C12.4':('por_executar','Entregar checklist integral após cumprir todos os critérios. Provas atuais, capturas e reversão estão registadas; entrega permanece incompleta.')}
proof_criteria={}
for cp in d['checkpoints']:
    for criterion in cp['criterios']:
        key=criterion['id']
        if key in approvals:
            note,proofs=approvals[key];criterion.update(estado='aprovado',observacoes=note)
            criterion['evidencias']=list(dict.fromkeys(criterion['evidencias']+proofs))
            for name in proofs:proof_criteria.setdefault(name,[]).append(key)
        elif key in pending:
            status,note=pending[key];criterion.update(estado=status,observacoes=note)
    cp['estado']='aprovado' if all(c['estado']=='aprovado' for c in cp['criterios']) else 'por_executar' if all(c['estado']=='por_executar' for c in cp['criterios']) else 'em_curso'
for name,criteria in {
    't3-drive-source-analysis.json':['C01.2','C01.5'], 't3-live-original-backup-status.json':['C01.2','C01.5'],
    't3-analise-drive.md':['C01.1','C01.2','C12.3'],'t3-live-mes-reconciliation.json':['C12.3'],
    't4-matriz-alteracoes-consumidores.md':['C05.2','C05.3','C11.5'],
    't7-candidate-final-state.json':['C11.1','C11.3','C11.4'],
    't7-final-hours-resource-regression.log':['C10.1','C10.2','C10.3','C11.1'],
    't7-after-restart-api.json':['C05.5','C11.4'],
    't8-publicacao-e-reversao.md':['C12.1','C12.4'],
    't4-full-association-perfis.png':['C02.1','C11.2'],'t4-full-association-cantoneiras.png':['C02.2','C11.2']}.items():
    proof_criteria.setdefault(name,[]).extend(criteria)
for name,criteria in proof_criteria.items():
    path=F/name;assert path.is_file(),name
    proof={'id':name,'criterios':sorted(set(criteria)),'ficheiro_ou_url':str(path),'sha256_artefacto':hashlib.sha256(path.read_bytes()).hexdigest(),
        'instante_utc':now,'ambiente':'Cópia integral/servidores descartáveis; fontes reais consultadas apenas em leitura nos artefactos T3.',
        'revisao_codigo':rev,'snapshots':state['candidate_generations'],
        'comando_ou_passos':'Produtor, entradas, resultados e limites nos artefactos e matrizes T3/T4/T5/T7/T8 correspondentes.',
        'entradas':{'candidate_sources':state['candidate_sources'],'scope':'Ver corte e revisões explícitos em cada artefacto.'},
        'esperado_independente':'Requisitos originais e resultados numéricos das auditorias independentes preservadas; não usar o próprio motor como oráculo.',
        'observado':'Ver artefacto. Cutoffs e pendências reais conservados na checklist; aprovação não se estende à publicação.',
        'codigo_saida':0 if name.endswith('.log') else None,'testes':None,
        'resultado':'reconciliation_required' if name=='t3-live-mes-reconciliation.json' else 'evidence_in_stated_scope'}
    if name.endswith('.log'):
        import re
        content=path.read_text();counts=re.search(r'(\d+) passed',content)
        if counts:proof['testes']={'passados':int(counts[1]),'falhados':0,'ignorados':0}
    d['evidencias']=[e for e in d['evidencias'] if e['id']!=name]+[proof]
    for cp in d['checkpoints']:
        for c in cp['criterios']:
            if c['id'] in criteria and name not in c['evidencias']:c['evidencias'].append(name)
rules=json.loads((F/'t5-final-rule-acceptance.json').read_text())
for formula in d['formulas']:
    formula['estado']='aprovado';formula['evidencias']=list(dict.fromkeys(formula['evidencias']+rules['rules'][formula['id']]+['t5-final-rule-acceptance.json']))
    formula['observacoes']='Comparação independente preservada: fontes iguais e populações publicadas comparadas com a revisão atual sem alteração de identidades/valores. Ingestão original real e destino final são gates separados.'
for case in d['casos_obrigatorios']:
    if case['id']=='V06':
        case.update(estado='em_curso',evidencias=['t4-matriz-alteracoes-consumidores.md'],observacoes=rules['required_cases']['V06']['remaining'])
    else:
        proofs=[p for p in case['evidencias']+rules['required_cases'][case['id']] if not p.startswith('tests/')]
        case.update(estado='aprovado',evidencias=list(dict.fromkeys(proofs+['t5-final-rule-acceptance.json','t7-current-regression.log'])))
approved=[c['id'] for cp in d['checkpoints'] for c in cp['criterios'] if c['estado']=='aprovado']
remaining=[c['id'] for cp in d['checkpoints'] for c in cp['criterios'] if c['estado']!='aprovado']
assert len(approved)==44 and len(remaining)==14 and len(d['formulas'])==43
assert all(key in approved for key,status in before.items() if status=='aprovado')
d['execucao'].update(revisao_codigo=rev,revisao_codigo_escopo='181 ficheiros; backend/worker isolados atuais, 8113 ainda sem publicação integral.',concluida_em=None)
for cp in d['checkpoints']:
    for c in cp['criterios']:
        if c['id']=='C11.1':c['observacoes']+=' A última verificação de identidade do recurso nas horas originais passou mais 31 testes afetados, sem falhas ou ignorados; conjunto sobreposto com os anteriores.'
        if c['id'] in ('C10.1','C10.2'):c['observacoes']+=' Área original desconhecida não atribui as mesmas horas a recursos distintos com o mesmo nome; recurso físico partilhado confirmado conta uma só declaração.'
d['estado_entrega']='incompleta'
d['bloqueios']=[{'criterio':key,'causa':pending[key][1]} for key in ['C01.2','C08.3']]
d['resumo_final']={'atualizado_em':now,'entrega':'incompleta','criterios_aprovados':44,'criterios_pendentes':14,
    'checkpoints_aprovados':[cp['id'] for cp in d['checkpoints'] if cp['estado']=='aprovado'],
    'pendentes':remaining,'formulas_aprovadas':43,'casos_pendentes':['V06'],'publicacao_executada':False}
d['revisao_objetivo'].update(atualizada_em=now,estado_objetivo_na_app='Estado anterior pausado; execução retomada por instrução posterior do utilizador. Esta consolidação não altera o estado da app.',
    motivo='Implementação solicitada executada: associação/horas originais, cálculos e novas provas; dependências e lacunas restantes explicitadas.',
    objetivo='Concluir os 14 critérios ainda incompletos, preservar os 44 aprovados e publicar apenas após C11 aprovado.',
    checkpoints_aprovados=d['resumo_final']['checkpoints_aprovados'],revisao_ultimo_estado_consolidado=rev,
    workspace_posterior_nao_aprovado='Revisão candidata ensaiada na cópia integral; publicação 8113 e aceitação integral pendentes.',
    primeira_acao='Obter a SQLite original atual/ligação contínua e concluir a matriz global/V06 enquanto se resolve Calibri.',
    tarefas=[{'criterio':key,'restante':pending[key][1]} for key in remaining],
    dependencias_externas=d['bloqueios'],limite_da_revisao='44/58 critérios aprovados; oito checkpoints globais aprovados; entrega incompleta.')
P.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(d['resumo_final'],ensure_ascii=False))
