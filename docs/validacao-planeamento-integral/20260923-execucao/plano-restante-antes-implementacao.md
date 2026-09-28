# Plano do trabalho restante — Planeamento

Data: 24/09/2026. Estado: plano de retoma; implementação pausada e entrega incompleta.

**Objetivo:** concluir o Planeamento de Perfis e Cantoneiras a partir do código existente, cumprir as lacunas de R01–R11/C00–C12 e publicar a revisão final validada. O âmbito é exclusivamente o Planeamento; os kanbans/MES operacionais são preservados.

Este plano resulta da leitura do código, checklist, manifestos e últimos resultados. Mantém os critérios do [plano integral](/home/luis/projects/kanban-mes-mtg2/docs/plano-execucao-integral-planeamento-2026-09-23.md) e passa a orientar a retoma. Não foram executadas alterações funcionais ou novos testes nesta revisão documental.

## 1. Ponto de partida

| Situação verificada | Consequência para a retoma |
|---|---|
| C00, C03, C06, C07 e C09 aprovados nas provas registadas. | Preservar inventário/isolamento, registo novo nas duas áreas, exclusão de fechados com histórico, colunas e capacidades/horas manuais. Não reimplementar estes módulos. |
| C02.4/.5, C08.1/.2/.4 e C10.4 aprovados. | Reaproveitar política de fontes, scroll, compactação/11pt e atualização das estimativas. Calibri efetiva continua pendente. |
| As 43 regras têm auditorias específicas nos snapshots documentados. | Fechar compatibilidade e aceitação integrada em T5; não recomeçar 43 implementações ou auditorias. |
| C10.4 tem 15 passos de histórico e seis atualizações OCR nas duas áreas. | Não repetir horas/janela/taxa/fallback e inserção/correção/remoção sem uma alteração que invalide a respetiva prova. |
| Original central já ligado ao motor e diagnóstico por evento, testado em ambiente descartável. | Terminar associação humana e horas, depois provar a fonte real. Fixtures não certificam publicação Windows. |
| Cinco checkpoints globais aprovados; oito incompletos. | Não interpretar 5/13 como percentagem de esforço. Faltam C01, C02, C04, C05, C08, C10, C11 e C12. |

Último estado consolidado: `e94451e908ffe637e9218172abaaf184077400979b709e99df3b40d9d8406627`, 170 ficheiros, [manifesto de estado](/home/luis/projects/kanban-mes-mtg2/docs/validacao-planeamento-integral/20260923-execucao/c01-original-pipeline-final-state.json). O workspace contém trabalho posterior incompleto: oito ficheiros da aplicação alterados, a migração `033_original_ocr_associations.sql` e `test_planning_original_associations.py`. O identificador desse estado consolidado **não certifica o código atual**.

Último teste do trabalho interrompido: **3 passados, 1 falhado, 17,21 s**. `test_original_revised_fact_rejects_old_proof_and_retains_history` esperava duas decisões e encontrou seis ao contar a tabela inteira. Falta confirmar se a causa é isolamento da fixture ou comportamento da aplicação. [Resultado preservado](/home/luis/projects/kanban-mes-mtg2/docs/validacao-planeamento-integral/20260923-execucao/c02-original-human-first.log).

No último estado registado, o servidor isolado persistente ainda tinha carregada a revisão anterior `a772daf…`; o backend mais recente foi ensaiado num servidor descartável. A publicação integral no serviço 8113 não foi efetuada. Os estáticos são partilhados com esse serviço, pelo que a sua presença não prova backend, migrações e worker atualizados.

## 2. Sequência de execução

| Etapa | Resultado a entregar | Dependências |
|---|---|---|
| T1 | Associação humana do original concluída, sem perda ou duplicação de produção. | Código interrompido existente; execução isolada. |
| T2 | Horas originais a alimentar corretamente horas reais e produtividade. | T1 para resolver área/operação quando necessário. |
| T3 | Fontes reais reconciliadas e original a publicar continuamente. | Acesso ao PC/SQLite original; fecho após T1/T2. |
| T4 | Lacunas de recálculo, concorrência e recuperação fechadas. | T1/T2; percurso real depende de T3. |
| T5 | Aceitação integrada das 43 regras e cobertura final. | Revisão funcional estabilizada em T1–T4. |
| T6 | Calibri real a 11pt comprovada. | Fornecimento/instalação autorizada da fonte. |
| T7 | Regressão, volume, reinício e matriz final aprovados. | C00–C10 completos; T1–T6. |
| T8 | Planeamento publicado e verificado no endereço utilizado. | C11 aprovado em T7. |

**Começar por T1 e seguir para T2.** T3 e T6 têm dependências externas identificadas; enquanto indisponíveis, concluir as partes independentes de T4/T5. Isso não permite aprovar os critérios bloqueados nem publicar como entrega integral.

## 3. T1 — Concluir associações do OCR original

Critérios: C02.1–C02.3; contribui para C01.3 e C05.

- [ ] Diagnosticar e corrigir o teste falhado, preservando a exigência de histórico correto por evento. Não alterar a expectativa apenas para aceitar seis linhas.
- [ ] Consolidar a migração 033 e o percurso completo de decisão por ID estável `original:instância:folha:linha`: listar pendentes, escolher peça/operação, guardar, reabrir e publicar os derivados.
- [ ] Validar Perfis e Cantoneiras, necessidades locais e ligadas a linhas importadas, operação explícita e decisão humana quando os dados originais não a determinam.
- [ ] Conservar quantidade desconhecida, impedir distribuição excessiva e tornar visível a quantidade ainda não atribuída numa distribuição parcial. Não apresentar cobertura parcial como completa.
- [ ] Preservar a associação quando só muda a quantidade necessária; reavaliar quando mudam identidade técnica, revisão/quantidade da fonte ou validação. Manter decisões antigas no histórico, sem reaplicar provas inválidas.
- [ ] Conferir os diagnósticos das peças ligadas à macro: a decisão humana deve resolver o motivo correspondente sem conservar um bloqueio obsoleto nem apagar outros conflitos.
- [ ] Fechar os casos ainda sem prova de peças filhas, ambiguidade, duplicação/revisão e sobreposição MES/original. Equivalência precisa de prova; conflito não resolvido continua identificado e excluído da soma.
- [ ] Verificar idempotência, conflito de revisão, atomicidade, remoção/desvalidação e atualização na API/browser nas duas áreas; executar as regressões MES afetadas pela alteração ao código partilhado.

**Fecho:** produção resolúvel ligada à peça/operação certa; restante produção com motivo e caminho de resolução; zero quantidade inventada ou duplicada; testes obrigatórios desta etapa aprovados. Preservar C02.4/.5 e verificar apenas o impacto da nova associação na seleção de fontes.

Ficheiros em curso: `app/planning_associations.py`, `app/planning_original_production.py`, `app/original_ocr.py`, `app/raw/projection.py`, `app/raw/ocr_scope.py`, `app/web/need_routes.py`, `app/web/templates/need_editor.html`, `app/web/static/need_editor.js`, `sql/033_original_ocr_associations.sql` e `tests/test_planning_original_associations.py`.

## 4. T2 — Integrar horas originais e fechar o histórico

Critérios: C10.1–C10.3; regras H03/H09/H10.

- [ ] Acrescentar as declarações de horas originais ao percurso de `publish_hours`, que atualmente consulta apenas folhas MES.
- [ ] Identificar cada declaração por origem/instância/folha ou período/revisão, contando-a uma única vez mesmo com várias peças.
- [ ] Resolver máquina, área, operação e período com informação comprovada. Tempo partilhado sem regra válida fica indisponível com motivo; não repartir arbitrariamente.
- [ ] Resolver ou excluir sobreposições entre original, MES e horas manuais sem apagar o histórico das declarações.
- [ ] Emparelhar volume e horas da mesma população temporal; apresentar folhas/eventos, volume, horas, janela, exclusões e cobertura.
- [ ] Comprovar que correção, remoção/desvalidação e associação original atualizam as estimativas dependentes, respeitando manual → histórico válido → Excel provisório.
- [ ] Integrar as novas provas com H03/H09/H10 já auditados e com C10.4 aprovado. Repetir apenas os percursos afetados.

**Fecho:** horas únicas, taxa histórica ponderada com numerador/denominador compatíveis e origem visível. Ausência de horas reais utilizáveis conserva o fallback identificado; não autoriza inventar uma taxa.

## 5. T3 — Provar ingestão real e reconciliação

Critérios: C01.1–C01.5.

- [ ] Comparar fonte, centro e projeção de Perfis/Cantoneiras no mesmo corte: todas as páginas, IDs únicos, folhas sem produção, quantidades desconhecidas e peças filhas. As contagens centrais existentes não substituem essa comparação.
- [ ] Confirmar no PC original o caminho da SQLite usada pelo processo e leitura consistente em modo só de leitura, incluindo WAL; preservar a identidade persistente da instância.
- [ ] Efetuar e documentar a primeira publicação real no centro e uma repetição idempotente. O último clone auditado tinha zero instâncias originais.
- [ ] Demonstrar eventos reais até à linha/operação/saldo e horas aplicáveis, ou o motivo individual de exclusão. Não confundir existência no esquema central com revisão aplicada ao planeamento.
- [ ] Confirmar funcionamento contínuo e distinguir última tentativa, última publicação com sucesso, data da origem e revisão aplicada. Reportar o intervalo de sincronização separadamente da latência interna.
- [ ] Completar em ambiente isolado os cenários ainda sem prova válida: revisão, desvalidação, indisponibilidade e leitura parcial. Confirmar conservação do último conjunto íntegro e aviso de antiguidade/erro.

**Dependência externa:** acesso ao PC/processo/SQLite original para instalação/verificação real. Código local do original, exportação HTTP e conector preparado já existem; não satisfazem essa dependência.

**Fecho:** reconciliação por IDs/revisões das três origens e prova real de primeira publicação, repetição e continuidade do original, sem escrever factos de teste nas fontes operacionais.

## 6. T4 — Fechar recálculo e recuperação

Critérios: C05.1–C05.5; parte do caso V06.

- [ ] Completar uma matriz única de mudanças × consumidores, marcando primeiro as provas existentes e executando apenas células sem cobertura ou invalidadas.
- [ ] Cobrir quantidade, geometria/comprimento, stock, abocardar/operação adicional, máquina, data/semana, taxa, calendário, horas, associação e revisão OCR; incluir as alterações globais e fontes macro/documentais aplicáveis ainda sem prova.
- [ ] Ao mudar máquina/período, conferir os agregados antigos e novos. Na associação/revisão original, conferir todas as peças e estimativas dependentes.
- [ ] Conferir o mesmo resultado/revisão na pré-visualização, gravação, API, RAW, detalhe de capacidades e exportação/saída afetada.
- [ ] Medir resposta e atualização separadamente: derivados da linha até 2 s após a resposta; agregados e nova revisão OCR central até 10 s na cópia integral. Conservar as medições já válidas.
- [ ] Completar concorrência, resposta atrasada, falha/recuperação do worker e reinício isolado: não reaparecem valores antigos; processamento pendente continua visível até à revisão correta.

**Fecho:** matriz obrigatória coberta e tempos cumpridos no ambiente de referência. Os 15 passos de histórico e seis atualizações OCR de C10.4 não são novas tarefas; só se repetem se T1/T2 invalidarem a prova correspondente.

## 7. T5 — Fechar os cálculos e a comparação Excel

Critérios: C04.1–C04.5; casos V01–V05.

- [ ] Ligar cada uma das 43 regras à auditoria independente já existente, origem Excel/layout, revisão e snapshot; eliminar da lista de pendências as antigas notas de regras sem auditoria entretanto concluída.
- [ ] Conferir a compatibilidade dessas provas com a revisão final. Recalcular apenas regras/populações afetadas; justificar continuidade das restantes sem misturar snapshots silenciosamente.
- [ ] Fechar a cobertura integral por campo/área: total, aplicável, entradas suficientes, calculado, indisponível com motivo e erro inesperado; incluir toda a população, também após a linha 1 035.
- [ ] Reconciliar a comparação Excel/aplicação e as divergências intencionais já classificadas; nenhuma divergência fica sem regra e justificação.
- [ ] Confirmar cobertura dos limites já exigidos no plano: famílias/catálogos, zeros/desconhecidos/excessos, comprimentos/stock/encaixe, operações, semanas ISO, unidades, taxas/calendários e Thomas Q=50/51. Executar apenas lacunas reais ou casos afetados.
- [ ] Associar as provas V01–V05 aos respetivos IDs, incluindo OF264774 e os casos numéricos do plano original, em vez de deixar entradas vazias na matriz.

**Fecho:** zero caso calculável sem resultado e zero diferença não explicada; todos os derivados têm regra, entradas, unidade, origem e motivo quando indisponíveis. Não iniciar outra auditoria geral se as provas compatíveis já satisfizerem o critério.

## 8. T6 — Concluir Calibri efetiva

Critério: C08.3.

- [ ] Localizar/obter instalação ou ficheiros autorizados de Calibri e disponibilizá-los no ambiente de destino.
- [ ] Verificar por instrumentação do browser que a fonte efetivamente renderizada é Calibri, mantendo 11pt. A prova anterior encontrou Liberation Sans.
- [ ] Verificar apenas o impacto da mudança da fonte na compactação, controlos e acessibilidade; reaproveitar C08.1/.2/.4 já aprovados.

**Dependência externa:** fornecimento autorizado da fonte ainda não disponível.

**Fecho:** Calibri real comprovada; a mera declaração CSS ou uma fonte substituta não aprova C08.3.

## 9. T7 — Fechar regressão, volume e evidência final

Critérios: C11.1–C11.5. Depende de C00–C10 aprovados.

- [ ] Fixar a revisão candidata e as migrações necessárias; atualizar o ambiente isolado para essa revisão. Identificar também as versões carregadas pelos processos, não apenas os ficheiros em disco.
- [ ] Executar os testes relevantes afetados e os obrigatórios ainda sem resultado válido, incluindo associação/horas originais. Corrigir falhas; não somar suites sobrepostas nem apresentar os 552 testes históricos como validação do código interrompido.
- [ ] Fechar os percursos de browser R01–R10 e das três fontes, usando provas existentes quando compatíveis; completar os casos manuais/importados/mistos ainda sem cobertura.
- [ ] Reconstruir a cópia integral na revisão candidata e verificar população/cobertura/volume e tempos afetados. Reconciliar resultados com T5; não repetir toda a aritmética sem uma mudança relevante.
- [ ] Reiniciar/reconstruir e conferir os casos críticos: sem duplicação de peças/eventos/horas, sem perda de vistas/registos locais/histórico, última fonte íntegra preservada após falha.
- [ ] Fechar V06 e a matriz dos 11 requisitos, 13 checkpoints, 58 critérios, 43 regras e seis casos. C11.2/C11.4 já têm provas parciais e devem ser tratados como trabalho em curso, não como testes nunca iniciados.

**Fecho:** revisão candidata identificada, zero falha obrigatória ou teste necessário ignorado, C00–C11 aprovados e provas acessíveis. A publicação continua em T8.

## 10. T8 — Publicar e verificar no destino final

Critérios: C12.1–C12.4. Depende de C11 aprovado.

- [ ] Preparar backup, migrações aditivas realmente necessárias e reversão seletiva. Preservar as alterações preexistentes; não repor o workspace inteiro.
- [ ] Publicar a revisão validada no `kanban-planning.service` (porta 8113) e worker correspondente; aplicar as migrações pendentes, incluindo 033 apenas depois de consolidada.
- [ ] Determinar e confirmar o endereço efetivamente usado pelo utilizador e a revisão que responde nesse destino.
- [ ] Fazer a verificação final de leitura: fontes/revisões, OF264774, amostra Cantoneiras, exclusão de fechados, colunas, scroll e Calibri.
- [ ] Comprovar uma atualização real de fontes e o worker operacional; reconciliar qualquer diferença entre snapshot de teste e dados publicados.
- [ ] Entregar checklist, matriz, comparação numérica/cobertura, resultados de testes, capturas e reversão; declarar limitações legítimas dos dados sem as confundir com funcionalidades em falta.

**Fecho:** R01–R11 cumpridos, C00–C12 aprovados e zero falha obrigatória pendente, no serviço realmente utilizado. Não reiniciar os MES 8100/8101 para testar o Planeamento.

## 11. Disciplina de execução

1. Repetir uma prova apenas quando houver alteração identificada que a invalide, falha por corrigir ou critério ainda sem cobertura.
2. Fechar T1 antes de começar nova implementação independente. Cada alteração deve servir uma tarefa enumerada; não acrescentar funcionalidades/refatorizações alheias ao plano.
3. Atualizar a checklist com o estado atual de cada critério, mantendo o histórico em `PROGRESSO.md` e nos artefactos. Não acumular notas contraditórias de pendências já resolvidas.
4. As dependências Windows e Calibri permanecem explícitas. Avançar no trabalho independente sem inventar sucesso nem substituir a prova real por uma simulação.
5. Testes com escritas usam base descartável/cópia integral isolada. Fontes reais servem para leitura/reconciliação; a disponibilização final segue T8.

Registo de execução: [checklist atual](/home/luis/projects/kanban-mes-mtg2/docs/checkpoints-planeamento-2026-09-23.json). Histórico e provas: [PROGRESSO.md](/home/luis/projects/kanban-mes-mtg2/docs/validacao-planeamento-integral/20260923-execucao/PROGRESSO.md).
