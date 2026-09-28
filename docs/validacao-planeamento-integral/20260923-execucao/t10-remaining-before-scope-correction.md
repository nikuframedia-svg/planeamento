> Revisão de execução após auditoria aprofundada: 37 critérios aprovados, 21 por fechar. Foram reabertos C02.1, C02.4, C05.5, C09.2, C10.1, C10.3 e C11.1. A exigência é agora fonte legível a 11 pt; Calibri deixou de ser obrigatória. O estado anterior abaixo é histórico e será substituído pelas provas finais desta revisão.

# Trabalho restante — Planeamento de Perfis e Cantoneiras

Atualizado em 24/09/2026 após a implementação solicitada. **44 de 58 critérios aprovados; 14 incompletos. Entrega incompleta.**

O âmbito é exclusivamente o Planeamento. As aprovações anteriores e os MES 8100/8101 foram preservados. A versão anterior deste plano está em `docs/validacao-planeamento-integral/20260923-execucao/plano-restante-antes-implementacao.md`.

## Concluído e validado

- Associação manual original concluída nas duas áreas: fixture corrigida, migração 033, histórico por evento, decisões locais/importadas, quantidade desconhecida/parcial/excessiva, identidade/revisão, reabertura e publicação. Conflitos MES/original continuam identificados e excluídos de somas automáticas.
- Horas originais integradas no motor existente, uma declaração por folha/revisão, volume e horas da mesma população, controlo de sobreposições e prioridade manual → histórico → Excel. Área desconhecida não multiplica horas nem bloqueia capacidades.
- As 43 regras e V01–V05 foram aceites com auditorias independentes reutilizadas: 18 comparações de populações antigas/atuais sem diferenças de identidade ou valores. Reconstrução de 83.156 peças e reinício sem perda de registos, vistas ou histórico.
- Corrigidas concorrência entre gravação/worker e respostas atrasadas dos filtros. Quatro gravações originais na cópia integral: pedido entre 3,868 e 4,721 s; resposta→linha até 1,407 s; resposta→agregados até 2,987 s. Seis revisões originais chegaram aos agregados até 9,644 s. Recuperação do worker em 4,063 s.
- Regressões: 577 testes após T1/T2, 67 afetados após as alterações seguintes e dez de publicação local após a correção de serialização e 31 de horas/recursos/capacidade após a última verificação de identidade do recurso. São conjuntos sobrepostos; não se somam. Os 552 testes históricos não certificam esta execução.
- MES reconciliado no corte de 09:46 UTC: 113 folhas Perfis e 182 Cantoneiras. O backup do Drive confirmou que as diferenças nas folhas 686/735 eram de apresentação, preservando identidades armazenadas. Surgiram depois mais 19 folhas Cantoneiras; esse novo corte tem diferenças por reconciliar.

Checkpoints globais aprovados: **C00, C02, C03, C04, C06, C07, C09 e C10**. Também aprovados individualmente C01.1, C05.1/.4/.5 e C11.1/.4.

## Estado da fonte original

Existe uma SQLite original neste servidor: `/home/luis/projects/DATARESEARCHMTG/SAIDA/app.db`. É idêntica à cópia no Drive e está datada de 10/09. A aplicação original tem 14.008 linhas validadas, incluindo produção de 23/09, e reporta backup de 24/09 às 09:42 UTC, de 112,65 MB, em `F:\Apps\OCR-original\data\backups`. A cópia antiga não foi importada como se fosse atual. A conclusão anterior baseada apenas numa base local vazia foi corrigida.

Análise completa: [t3-analise-drive.md](/home/luis/projects/kanban-mes-mtg2/docs/validacao-planeamento-integral/20260923-execucao/t3-analise-drive.md).

## 1. Ingestão original real — quatro critérios

- [ ] **C01.2** — SQLite original encontrada no servidor e Drive é cópia de 10/09, SHA idêntico; aplicação tem dados até 23/09 e reporta backup de 24/09 às 09:42 UTC em F:\Apps\OCR-original\data\backups. Falta confirmar/obter a base efetivamente usada e efetuar primeira publicação real e repetição. A conclusão antiga baseada apenas na SQLite local vazia foi corrigida.
- [ ] **C01.3** — Motor e decisões originais aprovados em testes. Falta rastrear eventos da base original atual efetivamente publicada até à linha/saldo/horas ou exclusão individual.
- [ ] **C01.4** — Revisão/desvalidação, leitura parcial, indisponibilidade e conservação do conjunto íntegro passaram em isolamento. Falta a repetição real do original com identidade persistente e sem duplicação.
- [ ] **C01.5** — Painel e avisos testados. Falta execução contínua real do conector original e comprovar tentativa/sucesso/idade/revisão aplicada nesse percurso.

## 2. Recálculo e sequência cumulativa V06 — dois critérios

- [ ] **C05.2** — Matriz atual em t4-matriz-alteracoes-consumidores.md. Quantidade/geometria/stock/operações, máquina/período, configurações, associações e OCR têm provas; falta fechar combinações globais macro/documentais e sequência cumulativa V06 na mesma identidade.
- [ ] **C05.3** — Novas quatro gravações originais: pedido 3868–4721 ms, resposta→linha até 1407 ms, resposta→agregados até 2987 ms; API/RAW/capacidade, revisão e CSV/XLSX verificados. Reutilizadas provas anteriores. Falta concluir V06 e as células restantes da matriz com os mesmos consumidores e tempos; não aprovar apenas por estes quatro passos.

Partir da [t4-matriz-alteracoes-consumidores.md](/home/luis/projects/kanban-mes-mtg2/docs/validacao-planeamento-integral/20260923-execucao/t4-matriz-alteracoes-consumidores.md). Reutilizar C03, C06 e os 15 passos/seis atualizações de C10.4. Não apresentar a duração de reconstrução integral como atualização incremental.

## 3. Calibri efetiva — um critério

- [ ] **C08.3** — Calibri efetiva não encontrada no servidor/Drive configurado; browser usa fonte substituta nas provas existentes. Falta disponibilizar Calibri autorizada, confirmar a fonte efetivamente renderizada a 11pt e rever o impacto visual.

## 4. Aceitação integrada — três critérios

- [ ] **C11.2** — Browsers originais nas duas áreas e restantes provas compatíveis preservados. Falta Calibri efetiva, percurso original real e sequência cumulativa V06; existência de capturas anteriores não fecha essas lacunas.
- [ ] **C11.3** — Reconstrução de 83.156 peças, 18 comparações de populações e persistência passaram na revisão candidata. Tempos incrementais medidos cumprem limites; falta fechar restantes células C05/V06 antes da aceitação integral de volume/desempenho.
- [ ] **C11.5** — 43 fórmulas aprovadas, V01–V05 aprovados, matriz R01–R11/C00–C12 atualizada. V06, C01 original real, C08.3 e publicação ainda incompletos; zero pendência convertida em sucesso.

## 5. Publicação e verificação — quatro critérios

- [ ] **C12.1** — Procedimento concreto de backup novo, migrações 027–033, publicação e reversão seletiva preparado em t8-publicacao-e-reversao.md. Pacote do conector regenerado. Publicação não executada: plano exige C11 aprovado.
- [ ] **C12.2** — Após publicar: verificar endereço efetivamente utilizado, revisão carregada, fontes, OF264774, Cantoneiras, fechados, colunas, scroll e Calibri no destino 8113.
- [ ] **C12.3** — Confirmar atualização real e reconciliar novo corte vivo. Clone tem 286 folhas MES, corte reconciliado 295 e consulta posterior 314; última consulta tem diferenças de projeção e ordem de duas novas folhas Cantoneiras.
- [ ] **C12.4** — Entregar checklist integral após cumprir todos os critérios. Provas atuais, capturas e reversão estão registadas; entrega permanece incompleta.

Procedimento preparado: [t8-publicacao-e-reversao.md](/home/luis/projects/kanban-mes-mtg2/docs/validacao-planeamento-integral/20260923-execucao/t8-publicacao-e-reversao.md). A publicação já está autorizada; aguarda as condições C11 do plano, sem necessidade de nova autorização.

## Revisão e controlo das provas

Revisão candidata `9c5aaf04838fa3703d2fd5a61eee150fddbb4ac2787bcade3a569bee70c7b185`, 181 ficheiros. Backend e worker isolados estão atualizados. A publicação integral em 8113 não foi executada; os estáticos partilhados não provam backend ou esquema atualizado.

Estado técnico: [t7-candidate-final-state.json](/home/luis/projects/kanban-mes-mtg2/docs/validacao-planeamento-integral/20260923-execucao/t7-candidate-final-state.json). Cálculos: [t5-final-rule-acceptance.json](/home/luis/projects/kanban-mes-mtg2/docs/validacao-planeamento-integral/20260923-execucao/t5-final-rule-acceptance.json).

Testes escrevem apenas em bases descartáveis ou na cópia isolada. Repetir provas aprovadas apenas quando alterações posteriores as invalidarem. C11 depende de C00–C10 aprovados; C12 depende de C11. O contrato original permanece em [plano-execucao-integral-planeamento-2026-09-23.md](/home/luis/projects/kanban-mes-mtg2/docs/plano-execucao-integral-planeamento-2026-09-23.md).
