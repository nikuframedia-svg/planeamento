# Execução integral — em curso

Esta é uma entrega intermédia, **não uma aprovação de R01–R11/C00–C12**.
O âmbito mantém-se integral e exclusivamente de planeamento.

## Estado consolidado em 24/09/2026

**44/58 critérios aprovados; 14 incompletos; 43 regras aprovadas. Entrega incompleta.** Associação e horas originais concluídas. Cópia integral de 83.156 peças reconstruída/reiniciada sem alterações inesperadas. Revisão candidata `9c5aaf04838fa3703d2fd5a61eee150fddbb4ac2787bcade3a569bee70c7b185`. Ver `t7-candidate-final-state.json`, `t5-final-rule-acceptance.json` e o plano do trabalho restante atualizado.

Drive: a base original SAIDA é de 10/09, mas a aplicação tem produção de 23/09 e backup de hoje noutro destino; ver `t3-analise-drive.md`. Não foi importada a cópia antiga como atual. Publicação real, Calibri, combinações globais/V06 e aceitação final continuam pendentes. As entradas abaixo conservam a cronologia e os resultados anteriores, incluindo falhas entretanto corrigidas.

## Ambiente e preservação

- Baseline Git: `ad0be0de677151c60eab04e83d5183341f06d0aa`, com numerosas alterações preexistentes. `baseline.json` conserva os hashes individuais anteriores. `execution-manifest.json` distingue os ficheiros alterados nesta execução.
- Backup integral: `/home/luis/.local/state/planning-backups/integral-20260923/database.dump`. Código anterior em `preexisting-source.tar.gz` na mesma pasta privada. Não repor integralmente sobre trabalho posterior.
- PostgreSQL de volume: container `planning-integral-20260923`, base `planning_integral`, porta local 44164. Segredo só em `isolated.json` na pasta privada anterior; não o copiar para relatórios. A cópia é integral, incluindo versões históricas.
- Servidor isolado: `http://127.0.0.1:18113`, `app.web.planning_app:app`, worker de dossiês desativado, diretório `/tmp/planning-integral-data`.
- Destino observado: serviço **de utilizador** `kanban-planning.service`, porta 8113; worker `kanban-raw-worker.service`. Não houve reinício dos MES nem publicação/reinício final do planeamento. Atenção: o serviço existente lê estáticos do workspace, pelo que edição desses ficheiros pode tornar o aspeto novo visível antes do reinício final; isso não constitui uma revisão validada/publicada em C12.
- A migração `027_planning_local_orders.sql` foi aplicada apenas às bases de teste, não ao destino final.

## Provas já obtidas

- Drive consultado realmente com rclone. Os três SHA-256 coincidem com o plano e os ficheiros locais: `drive-observation.json`, `baseline.json`.
- Inventário de todas as folhas/células, fórmulas partilhadas, valores guardados, validações, nomes e VBA. Inclui texto de Folha1 L/AN/AO/AP. `workbook-inventory.json`, ledgers comprimidos e `*-vba.txt`. `field-formula-inventory.json` relaciona 43 regras, 20 famílias e as diferenças iniciais formulário/RAW; a ligação e comparação numérica completa por regra ainda não foi concluída.
- Baseline de testes, antes de alterações: **95 passaram**. `baseline-tests.log`.
- Baseline real do browser: formulário exigia pesquisa; setas fechavam o grupo em Perfis; zero elementos arrastáveis; fonte renderizada WenQuanYi Zen Hei, não Calibri. `baseline-browser.json` e capturas.
- Motor `app/planning_calculations.py`, invocado depois da associação OCR pela projeção. Geometrias VBA e tabelas exatas; seleção de fonte por operação; campos derivados e motivos; fontes originais preservadas. Não se considera implementado o motor integral: taxas/carga/ocupação, pré-visualização e consumidores legados continuam por ligar.
- OF264774/ID34512 na cópia integral: corte 840, saldo/perfis/metragem/peso pendentes zero; total necessário 2 310 000 mm. `v01-projection-first.json`. As outras duas peças têm os seus próprios eventos (não os IDs1192/2037). API/browser/capacidades/exportação finais ainda por verificar em conjunto.
- Cantoneiras: resolução pela única operação aplicável da peça identificada ou código explicitamente registado; nunca só pela máquina. Peças com várias operações exigem evidência/decisão. Após reconstrução, **1053 de 75736 linhas** têm OCR principal numérico (`projection-progress.json`); uma dessas linhas é de teste local, as restantes são a cópia real. Falta auditoria integral de associações, exclusões e percursos de resolução.
- Registo direto de OF/OV novas nas duas áreas, persistência administrativa, releitura após reload, campos técnicos/restaurados, histórico e conflito atómico: `c03-tests.log`, `c03-browser.json`, `c03-created-raw.json`, capturas. Produção inicial local zero não cria eventos OCR. Falta segunda peça por OF nas duas áreas e sequência completa C03/C05/C09.
- Setas, foco, URL, arrasto intra/intergrupos, desafixação OF e persistência por área/vista: `c07-browser.json`; regressão anterior de browser voltou a passar. Ainda falta prova completa de largura, scroll do painel, reset e vista antiga.
- Controlo horizontal visível, Home/End e extremos nas duas áreas a 1440/1024/390/720 CSS px, com texto computado 14,6667px (11pt): `c08-browser.json`. **A fonte real ainda é Liberation Sans**. 720px é apenas ensaio de layout, não prova de zoom real200%.
- Regressão corrente: **125 passaram**, zero falhas/ignorados, `current-regression.log`, comando abaixo. As falhas intermédias foram mantidas nos logs anteriores; a dependência indevida de CPIS para OF local e a largura60px da vista Cantoneiras foram corrigidas.

```bash
RUN_PG_INTEGRATION=1 .venv/bin/python -m pytest -q tests/test_planning_integral_calculations.py tests/test_planning_integral_registration.py tests/test_planning_raw.py tests/test_raw_workspace.py tests/test_planning_registry.py tests/test_planning_needs.py tests/test_planning_evidence.py tests/test_original_ocr.py tests/test_capacity_revision.py
PLANNING_CHECK_BASE=http://127.0.0.1:18113 PLANNING_TEST_ISOLATED=1 node tests/planning_columns_integral_browser.cjs
PLANNING_CHECK_BASE=http://127.0.0.1:18113 PLANNING_TEST_ISOLATED=1 node tests/planning_scroll_integral_browser.cjs
PLANNING_CHECK_BASE=http://127.0.0.1:18113 PLANNING_TEST_ISOLATED=1 node tests/planning_registration_integral_browser.cjs
```

## Dependências externas comprovadas

- OCR original: `/health` da ponte127.0.0.1:18080 respondeu com `git_sha=5f6ab6f`. Não há caminho SQLite atual confirmado nem consola Windows acessível identificada. Publicação real e funcionamento contínuo continuam em falta. Uma exportação HTTP sem IDs não satisfaz C01. Pergunta enviada ao utilizador sobre acesso à consola, sem parar o trabalho independente.
- Calibri: não encontrada instalação local; instrumentação CDP confirma fallback. Foi solicitada uma origem autorizada/licenciada. C08.3 não pode ser aprovado com a declaração CSS.

## Próximos trabalhos obrigatórios

1. Completar C00 com mapeamento célula/regra/entrada/unidade e reprodução/estado dos fechos. Atualizar inventário dos campos após restauração; não confundir inventário com comparação aprovada.
2. C01/C02: reconciliar população completa das fontes MES com centro, eventos/expansões; integrar OCR original no motor, deduplicação entre fontes, operação auditada por conjunto homogéneo e diagnósticos rastreáveis. Confirmar cobertura após mudança de quantidade/geometria e decisões humanas.
3. C04/C09/C10: implementar/liga F12/F20/G06/G07/H01–H10; disponibilidade, horas reais, vigência, taxa histórica compatível ponderada, prioridade manual→histórico→Excel; não deixar campos antigos em cache. Capacidades atuais ainda distinguem confirmação/rascunho de forma incompatível com a estimativa pedida.
4. C05: pré-visualização segura no servidor, linha/revisão na resposta de gravação e publicação incremental das dependências. A reconstrução desta cópia demorou Perfis10,59s e Cantoneiras90,27s; **não satisfaz as provas de latência**. UI ainda consulta atualização a cada15s; gravar não devolve todos os derivados. Não esconder espera num pedido prolongado.
5. C06: população ativa baseada em `fechado_CPIS OU fechado_macro`, aplicada em todos os consumidores, histórico e matriz de fecho/reabertura. Estados CPIS observados: Em Aberto, Em Produção, Fechada, Pronta; desconhecido não é fechado.
6. Completar as provas C03/C07/C08 que faltam, incluindo formulário com pré-visualização, 2 peças/OF, scroll/foco no painel, reset, persistência de larguras e zoom real200%.
7. Comparação independente de toda a população calculável e todos os limites V01–V06. C11 inclui ainda toda a suite pg_integration exigida, reinícios, falhas de fonte/worker e volumes; os125 testes não substituem isso.
8. Só depois de C11 aprovado: C12, backup/migração aditiva/reversão seletiva, publicar serviço de planeamento, confirmar URL usada pelo utilizador e atualização real das fontes. Não reiniciar MES para testes.

Nenhum checkpoint completo foi aprovado nesta etapa. A checklist mantém todos os requisitos e critérios pendentes, sem reduzir o âmbito.

## Continuação C06/C09 — 23/09/2026

Mantém-se a entrega integral **em curso**, sem aprovação global de checkpoints.

- C06: `app/planning_population.py` centraliza CPIS fechado **OU** macro fechada; não usa percentagem de produção para fechar. `Pronta` permanece ativa, desconhecidos conservam diagnóstico. Todas as gerações continuam armazenadas; consulta `population=active|history|all`, por defeito ativo. O filtro é comum a RAW, pesquisa, paginação, facetas, análises, fórmulas, exportações e seleção em lote. Vistas antigas sem população explícita ficam ativas. Capacidades excluem também preparações locais de peças fechadas. Agregados por OF separam subconjuntos ativo/histórico, sem contaminar saldos.
- Prova independente completa (consulta às linhas macro e cópias CPIS sem chamar o classificador novo): **83 150 peças, zero divergências**. Perfis: **1 196 ativas + 6 218 históricas**. Cantoneiras: **17 779 ativas + 57 957 históricas**. Nenhuma peça fechada aparece nos itens de capacidade. `c06-independent-audit.json`; comando reproduzível `PYTHONPATH=. .venv/bin/python scripts/audit_planning_population.py` (o script lê exclusivamente a configuração privada da cópia isolada).
- Conservação: antes/depois idênticos para 413 078 linhas macro históricas, 2 351 registos de produção, 1 136 relações de expansão, 286 folhas validadas e tabelas locais de peças/preparação. Hashes dos conjuntos de IDs guardados; origens não são eliminadas. `c06-volume.json`, `c06-independent-audit.json`.
- C06: **11 testes** de matriz, fontes revistas, fecho CPIS, fecho macro, reabertura e conservação passaram. Os testes incluem exportação CSV/XLSX, análises, facetas, capacidade, vista antiga e rejeição de lote com peça fechada. Browser nas duas áreas passou (ativo/histórico/todos, vista guardada, reposição/reload): `c06-final-tests.log`, `c06-browser.json` e capturas.
- C09: `app/raw/worked_hours.py` e migração **028** reutilizam o armazenamento auditado `raw_objects`/`raw_object_versions` com tipo `worked_hours`. Registo por folha estável ou período contido numa semana ISO; máquina física, origem, operação opcional, revisão e horas reais independentes do calendário. A conferência mostra as declarações OCR sobrepostas e exige substituição explícita, sem somar ambas as fontes. Sobreposição manual é rejeitada. Alteração posterior da origem invalida a conferência, em vez de manter silenciosamente a correção anterior. Horas OCR inválidas não se tornam tempo utilizável nem são apagadas da fonte.
- UI: Definições → Capacidades e horas → Horas reais. Browser criou máquinas/declarações nas duas áreas, reabriu após reload, alterou **7→6h**, confirmou duas revisões e origem Manual. Um erro inicial na lista de tipos permitidos da rota HTTP foi reproduzido e corrigido; logs de falha preservados. `c09-browser.json`, `c09-browser-final.log`, capturas.
- Na cópia integral, as duas semanas/máquinas ensaiadas mostram **6h**, na API e no browser, preservando as **286 declarações OCR**. `c09-volume.json`, `c09-results-browser.json`. Estes registos são **de teste na cópia isolada**, não declarações de trabalho real no destino.
- Capacidade: rascunhos ativos entram na soma estimada; ausência de CPIS não impede estimativa. Quando existe resultado do motor, usa o saldo por operação recalculado em vez da quantidade antiga na preparação. Minutos/unidade normalizam para unidades/h em H07/H08; mistura de unidades ou operações não produz capacidade física agregada fictícia. OF264774/ID34512: **corte840, saldo0, quantidade de capacidade0, horas de corte0**, `v01-capacity-after-c09.json`.
- Regressão alargada: **147 passaram**, zero falhas/ignorados, `current-regression-c06-c09.log`. Após a guarda adicional de horas OCR inválidas, os **12 testes focalizados de horas** passaram em `c09-final-tests.log`. As provas de browser de horas e resultados estão nos scripts `tests/planning_worked_hours_browser.cjs` e `tests/planning_worked_hours_results_browser.cjs`.
- Alterações preexistentes de ficheiros tracked foram verificadas contra os hashes iniciais: `preexisting-tracked-preservation.json`. Nenhum MES foi reiniciado ou alterado nesta continuação. As migrações027/028 estão aplicadas **só nas bases isoladas/testes**.
- Servidor isolado mais recente: PID106847, sessão19943, porta18113. Código importado antes da guarda final de horas OCR inválidas; as próximas alterações de backend exigem novo reinício **deste servidor isolado**. As projeções mais recentes foram construídas pelo processo Python de verificação com código corrente. Configuração privada/backup mantêm os caminhos acima.

### Pendências que continuam obrigatórias

- C06 ainda exige auditoria final da navegação administrativa/consumidores antigos (`planning_hub.list_orders`, `planning.order_lines`) e repetição nas condições finais C11/C12. Não confundir a consulta histórica administrativa com a população ativa da RAW.
- C09 ainda não aprova o efeito imediato C05, nem a integração completa de H01–H08 com H09/H10. Alterar disponibilidade/taxa e comprovar todos os consumidores nos dois setores continua pendente.
- **H09/H10 continuam por implementar/integrar**: coortes de produção/horas compatíveis e ponderadas, janela configurável, prioridade manual→histórico→Excel, origem aplicada também na RAW/formulário/pré-visualização e tratamento de partilha de tempo entre operações. As horas manuais já podem servir esse motor, mas ainda não produzem taxa histórica.
- C05 continua reprovado por desempenho: reconstrução Perfis14s, Cantoneiras92,72s, capacidade21,39s. Não considerar o recálculo atual «imediato». Precisa de publicação incremental/linha devolvida pela gravação, pré-visualização partilhada e atualização sem F5 dentro dos limites do plano.
- Permanecem todas as outras pendências da lista anterior: C00 comparação integral independente, C01 OCR original real/contínuo, C02 auditoria de cobertura/associações, C03 paridade completa/segunda peça/pré-visualização, C04 fórmulas por ligar, C07 provas restantes, C08 Calibri real e zoom200%, C11 regressão total/volume/falhas/reinícios e C12 publicação final.

## Continuação C10/F12 — motor histórico e publicação por alterações

Esta secção substitui o estado anterior «H09/H10 por implementar», sem aprovar a entrega integral.

- `app/raw/productivity.py`: taxa histórica ponderada por máquina/operação/unidade/janela (90 dias configuráveis). O numerador e as horas correspondentes entram ou são excluídos juntos; uma folha mista não utiliza apenas a produção compatível com todas as horas. Geometrias diferentes podem contribuir com volume integral normalizado em m ou mm²; unidades/h exigem identidade dimensional compatível. IDs, horas, revisões, intervalo, volume e exclusões ficam numa evidência imutável consultável por hash.
- H10 partilhado entre RAW e capacidades: manual aplicável → histórico utilizável → Excel provisório. Conflitos manuais não caem silenciosamente para outra fonte. Thomas ×3 permanece exclusivamente na referência Excel, com fronteira Q=50/51. Taxas inválidas, operações não suportadas e ausência de volume/tempo mantêm motivo de indisponibilidade.
- Horas manuais podem conter repartição explícita por área/operação. A soma tem de coincidir com as horas declaradas; operações duplicadas/não suportadas são rejeitadas. A repartição alimenta H09 sem duplicar H03. Não há divisão automática de tempo entre operações.
- F12 é publicado a partir da carga agregada da máquina/semana e repetido em cada peça. Nos testes, 2h+8h para 14h disponíveis dão **71,428571…% nas duas linhas**; o ensaio de sobrecarga 1h+4h para4h dá125% nas duas. O valor da peça não é a sua contribuição individual.
- `publish_delta` conserva as versões anteriores e só substitui conteúdos alterados. Uma barreira transacional impede que um publicador REPEATABLE READ atrasado publique sobre uma geração entretanto atualizada, incluindo deltas vazios. A versão derivada de capacidades não provoca reconstruções em ciclo. Esta base incremental ainda não satisfaz C05: a construção principal continua integral.
- As linhas expandidas de produção são ligadas à respetiva peça resolvida, não a todas as peças da barra. A impressão digital inclui também alterações nos registos de produção e nas relações, mesmo sem alteração do cabeçalho da folha.
- Correção de dados comuns: quantidade/geometria canónicas prevalecem sobre cópias antigas nas preparações de operação, na RAW, nas capacidades e ao reabrir o formulário. Uma mudança50→51 na preparação de abocardar preserva4un.OCR de corte, dá saldo47 e4,7h de corte a10un./h. Guardar apenas uma nota na preparação antiga não repõe50. Valores antigos permanecem nas revisões.
- UI: janela histórica na máquina, repartição manual de tempo, origem/taxa/horas na RAW e capacidades e consulta «Histórico usado / exclusões» com percurso até aos eventos e declarações. A pré-visualização do formulário e a atualização sem F5 dentro de C05 continuam pendentes.
- Regressão: `current-regression-c10.log`, **166 passaram** (zero falhas/ignorados). Depois de acrescentar o caso F12 exato2+8/14, `c10-final-tests.log`, **18 passaram**. Suite exigida `RUN_PG_INTEGRATION=1 .venv/bin/python -m pytest -q -m pg_integration`: **23 passaram,809 deselecionados**, zero falhas/ignorados, `c11-pg-integration.log`. A deseleção é o filtro do marcador, não omissão disfarçada de testes falhados.
- Primeira auditoria integral desta versão: **83150 peças**, **18975 operações principais** RAW/capacidade comparadas e **111 conjuntos de evidência histórica**, zero divergências; `c10-full-audit-before-cant-hours.json`. Perfis tem318peças ativas com taxa histórica; Cantoneiras ainda nenhuma antes do ensaio de horas. F12 permanece indisponível onde não há calendário/carga completa utilizável; não foi inventada disponibilidade.
- Tempos dessa reconstrução: Perfis13,51s; Cantoneiras127,72s; capacidades49,09s. **C05 continua incompleto por desempenho**. Os testes de delta provam integridade de versões, não cumprimento dos limites2s/10s.
- Browser registou uma declaração de ensaio de4h na folha CantoneirasUID85727cd76ce3, máquinaPeddi8, operação112, com460,902m validados; esperado independente115,2255m/h. `c10-hours-browser.json` e captura. São horas artificiais de teste exclusivamente na cópia integral isolada, explicitamente identificadas na origem; não representam horas reais declaradas pela fábrica. Dois erros de seletor do script foram preservados nos logs iniciais e corrigidos para selecionar o controlo de âmbito/folha; a execução final passou.
- Servidor isolado reiniciado com esta versão: PID229144, sessão21110, porta18113. Serviços MES e destino8113 não reiniciados. Migrações continuam apenas nas bases isoladas.

### Pendências mantidas

C10 ainda depende de C01/C02 e exige completar as sequências de atualização C05 (produção/horas/janela/taxa sem F5 e nas latências pedidas). C09 precisa da prova integral de efeito imediato de disponibilidade/taxas nos dois setores. C00/C04 ainda precisam da comparação Excel independente completa e cobertura por campo; C03 de pré-visualização/segunda peça e sequência completa; C06 dos consumidores administrativos antigos; C07 de provas restantes; C08 de Calibri autorizada realmente renderizada e zoom200%; C11 de cenários de falha/reinício e matriz integral; C12 da disponibilização final. O OCR original real continua sem publicação central comprovada. Nenhum destes pontos é considerado cumprido por esta continuação.

### Fecho das provas desta continuação C10

- Auditoria integral depois das4h de ensaio Cantoneiras: **83150 peças**, **18975 operações principais**, **111 conjuntos históricos**, **zero divergências**. Perfis318peças ativas e Cantoneiras208peças ativas usam taxa histórica. Cantoneiras:460,902m/4h=**115,2255m/h**. `c10-full-audit.json`; script reproduzível `scripts/audit_planning_productivity.py --rebuild`. Tempos13,54s/133,77s/49,45s para Perfis/Cantoneiras/capacidades; continuam acima de C05.
- Browser final passou nas duas áreas: RAW e capacidades usam exatamente o mesmo hash, volume, horas e taxa; exclusões acessíveis, unidades legíveis (m/h,mm²/h). `c10-results-browser.json`, `c10-results-browser-units.log` e quatro capturas `c10-*-raw-historico.png`/`c10-*-capacidade-historico.png`. Os erros intermédios do script (escolha de outro período da mesma máquina e espera no nome incorreto do endpoint) estão conservados nos logs anteriores; a versão final escolhe o período da peça e passou.
- Auditoria independente de população/IDs repetida após C10: **zero divergências**, contagens1196+6218 em Perfis e17779+57957 em Cantoneiras mantidas; nenhuma peça fechada em capacidades. `c06-independent-audit.json` e `c06-after-c10-audit.log`.
- Manifesto de execução e checklist atualizados com hashes e provas. Os27ficheiros tracked que já estavam alterados no início continuam byte a byte iguais ao baseline. `preexisting-tracked-preservation.json`. **Entrega integral permanece incompleta/em curso**; não houve disponibilização no8113 nem reinício dos MES.

## Continuação C05 — cálculo por OF e pré-visualização sem gravação

- `projection.build_rows(...,orders=[...])` calcula todas as peças das OFs selecionadas. Não filtra apenas uma peça: conserva concorrentes que podem tornar uma associação ambígua. A conservação de aliases também lê só essas OFs. O resultado parcial **ainda não é publicado como uma geração integral**; a ligação à gravação/worker é trabalho seguinte. Teste compara a lista parcial, campo a campo, com a construção integral e inclui peças locais de outra OF.
- Medição de leitura na cópia integral: OF264774/3peças **1,41s**; OF250015/42peças **2,19s** (`c05-targeted-first.json`). Os eventos de produção ainda são lidos/processados integralmente neste caminho; não anunciar publicação incremental completa.
- `app/raw/preview.py` e `POST /planeamento/api/necessidades/prever`: ligação PostgreSQL **readonly**, snapshot consistente, catálogo/revisão/origem verificados no servidor; rejeita campos OCR/resultados enviados pelo cliente. Não chama comandos de gravação nem entrega outbox. Usa `calculations.recalculate` e a mesma seleção de taxa de RAW/capacidades; `productivity.apply_rows(...,persist=False)` não captura/persiste evidência. Fatos e tabelas vêm do servidor. Quantidade isolada conserva produção; nova geometria reavalia associações e não reinterpreta dimensões dos eventos históricos.
- O formulário apresenta resultados, unidades, origens e motivos; atualização automática após edição, com contador de pedidos que impede respostas antigas de substituir valores recentes. A consulta é separada da gravação. Factos importados continuam sem controlos manuais de produção.
- Rótulos da RAW/previsão corrigidos: «Quantidade cortada», «Quantidade abocardada» e «Produção principal» já não dizem macro quando o valor vem de OCR ou condição inicial local. A coluna F12 identifica ocupação da máquina/semana. A origem efetiva e o valor importado continuam consultáveis.
- Testes: `c05-preview-regression.log` **44passaram**; depois dos ajustes finais de rótulos/origens, `c05-preview-final-tests.log` **37passaram**, zero falhas/ignorados. Incluem ausência de novos registos/revisões/comandos/projeções/outbox durante preview, rejeição de produção inventada, paridade preview→gravação→RAW nas duas áreas e revisão obsoleta. A primeira tentativa de fixture Cantoneiras falhou por tentar inserir catálogo com a conta restrita da aplicação; corrigiu-se apenas a preparação da fixture para usar a conta administrativa descartável. Log inicial preservado.
- Browser final nas duas áreas passou: Q100→123→124→125 no formulário, revisão guardada **2→2**, quantidade persistida100. A resposta124 atrasada não substituiu125. `c05-preview-browser.json`, `c05-preview-browser-final.log` e capturas. Tempos **2978ms Perfis /3786ms Cantoneiras** desde a edição até à resposta (incluem debounce300ms), e **6ms/5ms** da resposta até aos resultados visíveis. São tempos de **pré-visualização**, não prova da gravação C05.3.
- V01 na API: OF264774/ID34512, Q841 simulada → **corte840, saldo1, quantidade prevista1**, sem gravar. L3000 simulada → produção/saldo desconhecidos por identidade alterada. Pedidos1,93s/1,91s; `c05-v01-preview-api.json` conserva payloads, respostas e fontes.
- Servidor isolado atual: **PID315204, sessão46726, porta18113**. Nenhum serviço MES ou serviço final8113 reiniciado. Os27ficheiros tracked preexistentes continuam iguais ao baseline.

### Falta fechar C05

A resposta da gravação ainda não devolve uma linha publicada atual; o worker continua a reconstruir áreas e agregados integralmente. Faltam publicar apenas as dependências afetadas, recalcular baldes antigos/novos, atualização de OCR≤10s, atualização semF5 de RAW/capacidades/exportações, recuperação de falhas/reinício e medição completa. A pré-visualização ainda não simula F12 sobre as outras peças da máquina/semana: mostra indisponível com motivo explícito. Falta ampliar paridade para edição de operações secundárias, duplicados/PDF e todas as alterações técnicas. **C05 permanece em curso, não aprovado.** As restantes pendências C00–C12 e dependências externas mantêm-se.

## Continuação C05 — publicação atómica ao guardar

- `app/raw/incremental.py` liga o cálculo das OFs afetadas à transação da gravação. Registo e edição/lote devolvem a linha calculada, a revisão e as versões publicadas sem esperar pelo worker. A OF completa mantém peças concorrentes nas verificações de identidade; eventos fora do âmbito não são substituídos por associações calculadas com população parcial. Totais por OF são publicados na mesma transação. As versões anteriores continuam consultáveis.
- `planning_hub.order_detail(...,conn=...)` e a evidência de associações reutilizam a ligação transacional. Uma nova OF local passa a ser visível durante a sua própria publicação, antes do commit, sem abrir outra ligação que desconheça a gravação.
- A geração parcial conserva a impressão digital/snapshot da última população integral e identifica OFs revistas, origem incremental e `source_refresh_pending`/`aggregates_pending`. Nunca declara processado um OCR novo de outra OF. Duas edições sucessivas de uma OF já atualizada funcionam sem worker; editar uma OF ainda desatualizada exige atualização. A reconstrução integral recupera todas as dependências pendentes.
- Na RAW, guardar carrega logo a versão publicada; pedidos de listagem atrasados não substituem uma consulta mais recente. A consulta de versões passa a cada2s e conserva uma edição aberta. Formulário/RAW distinguem «linha atualizada» de «agregados em processamento». A publicação de capacidades elimina o sinal de agregados pendentes quando termina.
- **9 testes passaram** em `c05-publish-atomic-tests.log`: preview, população por OF, publicação/repetição sem worker, origem externa ainda pendente, ausência de escrita parcial após falha provocada na segunda área, recuperação idempotente e paridade base/projeção/CSV/XLSX. Q120−64=56; segunda ediçãoQ130−64=66; nova peça7×2001mm comstock6000 exige4barras. O rollback conserva inclusive comandos/outbox/conteúdos/gerações, não só a peça.
- **Regressão alargada:176 passaram**, zero falhas/ignorados,186,51s, `current-regression-c05-publish.log`. Inclui RAW, registo, necessidades, evidência, OCR original, população, cálculos, horas, histórico e capacidades.
- Browser nas duas áreas, sem worker: formulário e edição na RAW passaram, segunda peça criada na mesmaOF. Perfis: pedidos8226/8048ms, resposta→visível714/110ms; Cantoneiras:8369/10924ms,736/940ms. `c05-publish-browser.json` e capturas `c05-*-published.png`. Os pedidos ainda são lentos e foram medidos separadamente; estes resultados só satisfazem a parcela de visibilidade da linha≤2s, não agregados≤10s.
- A primeira execução do browser falhou por procurar `[type=submit]` num botão de submissão implícita; não chegou a enviar a edição RAW. O relatório/log foram conservados. A repetição usa o nome acessível do botão e reutiliza a segunda peça Perfis já criada, evitando novo registo artificial. Não se alterou o comportamento esperado.
- Após reiniciar apenas o servidor isolado18113: mesmas quatro peças/revisões nas necessidades, projeções, API, CSV e XLSX, `c05-publication-after-restart.json`. Perfis originalQ103/rev5, segundaQ7/rev2; Cantoneiras originalQ102/rev4, segundaQ7/rev2. A auditoria inicial tentou exportar «barras» em Cantoneiras, campo que não pertence ao contrato, e foi corrigida para comparar só os campos aplicáveis. Outro ensaio foi interrompido pelo reinício antes de terminar; ambos os logs de falha foram preservados e não contam como provas passadas.
- Servidor isolado atual: PID383032, sessão55895, porta18113. Worker isolado não está em execução. Migrações027/028 continuam apenas nas bases de teste/cópia; nenhum serviço MES ou destino8113 foi reiniciado. Os27ficheiros tracked preexistentes mantêm os hashes iniciais.

### C05 ainda incompleto

A publicação parcial da linha não fecha as dependências históricas entre OFs e recursos. O worker e a capacidade ainda precisam de recálculo incremental, incluindo os períodos antigos/novos quando muda máquina/data, e das medições≤10s após OCR/configuração. Permanecem F12 na pré-visualização, paridade integral de operações secundárias/PDF e matriz completa de concorrência/falhas. As restantes pendências C00–C12 mantêm-se; não houve publicação final nem aprovação global.

### Reconstrução e reconciliação depois da publicação parcial

- `c05-full-audit.json`: **83152 peças**, **18977 operações principais** RAW/capacidade e **109 conjuntos históricos** reconstituídos independentemente, zero divergências. As peças ativas com taxa histórica permanecem318Perfis/208Cantoneiras. Tempos13,72s/117,42s/49,55s paraPerfis/Cantoneiras/capacidades: desempenho integral continua acima do limiteC05.
- `c05-population-audit.json`: Perfis1197ativas+6218históricas; Cantoneiras17780ativas+57957históricas. A diferença para a auditoria anterior são apenas as duas novas peças de teste. Necessidades/preparações4→6; hashes deIDs das fontes permanecem iguais:413078linhas macro,2351registos de produção,1136relações,286folhas. Nenhuma peça fechada reaparece na capacidade.
- `c05-publication-after-rebuild.json`: mesmas quatro peças/revisões/valores em base, API, CSV/XLSX. Os dois sinais de pendência ficam falsos depois da capacidade terminar. As provas anteriores ao reinício mantêm-se no relatório do browser; a auditoria posterior compara-as diretamente.
- Revisão final de frescura: `projection.rebuild` mantém `aggregates_pending=True` entre a publicação do núcleo e a publicação das capacidades. Evita retirar o aviso durante os cerca de50s em que a capacidade ainda está a ser preparada. Teste verifica explicitamente aviso presente após núcleo e ausente após capacidade. Esta alteração só afeta o estado intermédio, não os números auditados acima.

- Após o ajuste final de frescura: **39 testes passaram**, zero falhas/ignorados, `c05-publish-final-tests.log`. Nenhum checkpoint global é aprovado por esta etapa.
- Servidor isolado novamente carregado com o código final desta etapa: **PID407955, sessão33182, porta18113**. A releitura após reconstrução é repetida nesta revisão; os serviços8113/8100/8101 permanecem intocados.

## Continuação C05/C09 — capacidades por dependências e atualização sem F5

- `app/raw/capacity_scope.py` compara membros entre versões confirmadas. Seleciona os recursos antigos/novos das peças alteradas, todas as peças que partilham esses recursos nas duas áreas e recursos cujos eventos/horas/geometria histórica mudaram. Alterações de taxa, calendário, horas e identidade do recurso usam as configurações anteriores/atuais para encontrar dependências. Cursor ausente, nova macro, novo dia ou interpretação global de semanas regressam ao cálculo integral; estes percursos ainda precisam de otimização.
- A capacidade reutiliza o mesmo motor de itens/agregados. Publica apenas recursos afetados, elimina operações/períodos que deixaram de existir e conserva as outras versões. F12 é atualizado em todas as peças do recurso/período, incluindo pares de outra área. As estimativas de operações não afetadas continuam presentes. Guarda cursores exatos da RAW após publicar, sem confundir a versão do núcleo com a versão derivada.
- Entradas realmente inalteradas não provocam recálculo da máquina só porque uma publicação da OF removeu campos derivados. A publicação conserva/restaura os resultados de capacidade desses pares. Operações secundárias já atribuídas a uma máquina não incluem o grupo «Por definir» como dependência adicional.
- Uma gravação local sobre fontes integralmente atuais passa a manter o núcleo atual: todas as OFs modificadas foram publicadas na própria transação. As capacidades continuam pendentes até ao worker. Se já havia OCR/fonte externa por processar, a guarda conservadora anterior mantém essa pendência. Configurações de capacidade deixam de forçar reconstrução das macros, mas publicam imediatamente o aviso de agregados pendentes. O ano de semanas importadas continua dependência do núcleo.
- Worker: verificação local a cada2s; observação de rede/Drive e OCR original separados da fila crítica de recálculo. RAW e capacidades consultam versões a cada1s, sem acumular pedidos concorrentes. A capacidade atualiza automaticamente a tabela e o separador do detalhe aberto; formulários em edição ficam preservados. Respostas de listagem antigas não substituem as novas.
- **Regressão alargada:180 testes passaram**, zero falhas/ignorados,186,50s, `current-regression-c05-capacity.log`. Após os últimos ajustes de âmbito e proveniência, **31 testes passaram**,36,50s, `c05-capacity-final-provenance-tests.log`. Incluem5cenários incrementais: máquina/semana com recurso partilhado entre áreas; taxa/arquivo/remoção; taxa de operação secundária; par inalterado e origem Excel da principal.
- Primeiro ensaio de preparação na cópia integral demorou24,72s porque uma peça inalterada e sem máquina arrastava18503operações de «Por definir». A comparação de entradas e conservação dos derivados corrigem esse âmbito. O teste cobre o caso; não se aceitou simplesmente uma latência maior.
- Browser com worker real na cópia isolada: Q20→40, máquina1→2 e2027W01→W02, mantendo RAW e detalhes das duas semanas abertos. Perfis: pedido7875ms, resposta→RAW404ms, resposta→todos os agregados/detalhes2238ms. Cantoneiras:8793ms/1833ms/3566ms. SemF5. Semana antiga0h; nova4hPerfis e2hCantoneiras, para14hdisponíveis. `c05-capacity-incremental-browser.json` e capturas `c05-*-capacity-incremental.png`.
- Browser Definições→Capacidades e horas: taxa10→20un./hPerfis e20→40un./hCantoneiras; depois calendário2×7,5−1=14h→3×6−2=16h. Atualizações após resposta: taxa/calendário2794/3614msPerfis e4702/3686msCantoneiras. Com40un., carga final2/1h, livres14/15h, ocupação12,5/6,25%, turnos1/3 e1/6, capacidade física320/640un. e livre280/600un. Histórico conserva revisões. `c09-capacity-config-live-browser.json` e capturas `c09-*-config-live.png`.
- Estes recursos, taxas, calendários e quantidades são **ensaios artificiais exclusivamente na cópia isolada**, não configurações confirmadas da fábrica. Os aliases escolhidos também afetam outras peças da mesma máquina, como exigido pelo cálculo por dependências. Perfis passa a ter171peças ativas com taxa manual; a restrição de operações da configuração de ensaio Cantoneiras torna indisponíveis operações não confirmadas para esse recurso. As fontes não foram alteradas.
- Comparação integral inicialmente encontrou10diferenças na proveniência `reference_rate` de operações secundárias Cantoneiras302: estava a herdar50m/h da principal e depois a perder esse valor quando a taxa aplicada passou a unidades/h. Corrigido: referência da principal usa a célula original `Mt\h`; secundária não herda essa taxa. Cargas/ocupações não divergiam. Falha e diagnóstico preservados em `c05-capacity-delta-full-comparison-first-failure.*`/`c05-capacity-delta-differences.json`.
- Repetição final: **106848 linhas comparadas, zero diferenças**, em RAW, itens, semanas e máquinas nas duas áreas. Exclui exclusivamente o identificador da nova publicação na proveniênciaF12. O script inicializa a revisão, altera efetivamente duas taxas, recalcula incrementalmente, repõe os valores e compara com uma reconstrução forçada. Deltas1,167s/1,161s; reconstrução integral48,095s. `c05-capacity-delta-full-comparison.json`; `scripts/audit_planning_capacity_delta.py --exercise`. Esta prova demonstra equivalência da otimização, não substitui a comparação independente comExcel deC04.
- Auditoria independente de produtividade posterior:83152peças,18977operações principais,102conjuntos históricos, zero divergências. Uma linhaF12conhecida por área no período de ensaio;198peçasPerfis e208Cantoneiras usam histórico após as prioridades manuais de teste. `c05-capacity-current-audit.json`. Auditoria de população:1197+6218Perfis e17780+57957Cantoneiras; nenhuma fechada na capacidade ativa, `c05-capacity-population-audit.json`.
- Os27ficheiros tracked preexistentes continuam iguais à baseline. O worker **isolado**PID470674 foi parado após os ensaios para congelar a reconciliação. Não se tocou no worker operacionalPID239069 nem nos serviçosMES/destino8113. Migrações continuam apenas nas bases isoladas.

### Pendências obrigatórias mantidas

C05 ainda não aprova: chegada de OCR ao centro continua a poder reconstruir a área completa; faltam caminho incremental e medição≤10s desse evento, F12simulado no formulário, interpretação de semanas/macros em volume e matriz completa de falhas/concorrência/alterações. O recálculo de quantidade/máquina/semana/taxa/calendário ensaiado passou, sem generalizar essa prova a todos os disparadores. C09 precisa da sequência final de horas reaisH03/H09 semF5 e de completar os restantes critérios. C00/C04, C01/C02, C03, C06–C08, C10–C12 conservam as pendências anteriores. Nenhum checkpoint global é promovido a aprovado por esta etapa.

- Servidor isolado final recarregado: **PID524002, sessão26129, porta18113**. ReleituraAPI nesta revisão passou:Q40rev7Perfis/rev6Cantoneiras,2h/1h eocupação12,5%/6,25%, sem agregados pendentes; `c05-capacity-final-api.json`. Workerisolado permanece parado após a reconciliação.

## C05/C10 — Revisões OCR por OF e capacidades dependentes

Revisão de código: `3cf9be08338e59eeb8c4efd026a2611f9f4490223642a02d69bedf18b366240e`. Servidor de validação reiniciado: PID 633250, `localhost:18113`; worker isolado parado após o ensaio. Serviços operacionais de planeamento e MES/kanbans não reiniciados.

Implementado `app/raw/ocr_scope.py`: manifesto imutável de folhas/registos/referências, identidade resolvida pelo mesmo código do motor e comparação entre versões. A união das OFs antigas/novas inclui atribuições humanas e conserva populações completas para resolver ambiguidades. A publicação de produção, horas, peças e totais de OF é atómica. Mudanças de macro/CPIS/dia ou fontes locais não cobertas recorrem à reconstrução completa. Gravações locais integralmente cobertas atualizam o manifesto; fontes OCR pendentes nunca são marcadas como processadas.

O ensaio cria apenas duas folhas sintéticas na cópia integral: Perfis OF264576/5564V002, Q=42; Cantoneiras OF264999/ED13B206, Q=48, L=150 mm. Chegada de 10 unidades, correção para 25 unidades com horas de 2 para 4 e remoção são observadas com o worker real, RAW e capacidades abertas sem F5. Um leitor independente consulta as publicações comprometidas a cada 100 ms. Os tempos abaixo começam no commit central; não incluem transporte desde os PCs das origens.

| Área | Alteração | Publicação RAW observada | RAW no browser | Publicação capacidade observada | Capacidade no browser/API |
|---|---|---:|---:|---:|---:|
| perfis | insert | 2.264s | 2.696s | 3.674s | 3.781s |
| perfis | correct | 2.375s | 2.609s | 3.685s | 4.696s |
| perfis | remove | 3.500s | 3.542s | 4.708s | 5.626s |
| cantoneiras | insert | 6.317s | 7.641s | 8.430s | 9.808s |
| cantoneiras | correct | 4.695s | 6.492s | 6.910s | 8.810s |
| cantoneiras | remove | 6.141s | 7.349s | 8.253s | 9.523s |

Perfis: taxa manual de 20 un./h mantém precedência, com saldo de 32 para 17 e carga de 1,6 para 0,85 h. Cantoneiras: 10 × 0,15 m / 2 h = 0,75 m/h, saldo de 38 e carga de 7,6 h; revisão de 25 × 0,15 m / 4 h = 0,9375 m/h, saldo de 23 e carga de 3,68 h. Retirada da folha elimina essa contribuição histórica e volta à referência Excel de 120 m/h. Sem produção conhecida na peça, o saldo e a carga voltam a desconhecidos; não é inventado zero.

A primeira comparação integral encontrou 9 861 diferenças em linhas fechadas, zero nas ativas ou capacidades. A restauração dos derivados da capacidade estava a substituir estimativas acabadas de calcular no núcleo por versões antigas de linhas fechadas. Corrigido e coberto por teste: 2 h antigas de Excel não substituem 1 h manual recalculada; nenhuma peça fechada entra na carga ativa. A inicialização de operações sem OCR também foi corrigida: retirar a última folha conserva o acumulado Excel canónico conhecido. O diagnóstico e as primeiras falhas foram preservados em `c05-ocr-test-diagnosis.json` e `*-first-failure.*`.

Validação final: 189 testes de regressão antes do último ajuste, 49 testes finais das suites afetadas; 113 988 conteúdos de 7 datasets nas duas áreas sem diferenças face à reconstrução integral. Auditoria independente de 83 152 peças, 18 977 operações principais e 102 conjuntos históricos: zero falhas. População/IDs de fontes e objetos locais iguais ao ensaio anterior. As duas folhas sintéticas e os respetivos eventos foram retirados; versões RAW anteriores permanecem consultáveis. Os 27 ficheiros rastreados preexistentes continuam idênticos byte a byte à baseline.

Provas: `c05-ocr-incremental-browser.json`, capturas `c05-perfis-ocr-live.png`/`c05-cantoneiras-ocr-live.png`, `c05-ocr-delta-full-comparison.json`, `c05-ocr-current-audit.json`, `c05-ocr-population-audit.json`, `c05-ocr-final-api.json`, `current-regression-c05-ocr.log`, `c05-ocr-final-tests.log`.

Estado global continua incompleto. C05: F12 na pré-visualização, associações e restantes mudanças da matriz, estimativas históricas fechadas sob todas as alterações de configuração, semanas/macros em volume e restante recuperação/concorrência. C10: completar horas manuais, janela e vigências nas duas áreas. C00/C04: reconciliação numérica integral com Excel. C01/C02: publicação real/IDs estáveis do OCR original e reconciliação das três origens; o conector original tem intervalo padrão de 300 s, separado dos tempos central→browser acima. Calibri real, restantes critérios C03/C06/C07/C08/C09/C11 e publicação C12 também permanecem pendentes; nenhum checkpoint global foi aprovado por esta etapa.
## Continuação C05 — F12 na pré-visualização e igualdade após guardar

- O turno anterior produziu progresso verificável: correção da fixture de recurso e **9 testes F12 aprovados**. Nesta continuação, o motor de capacidades partilhado foi verificado em volume e no browser. O objetivo integral mantém-se ativo; nenhum checkpoint global passa a aprovado por esta etapa.
- `capacity_revision.calculate` é a implementação comum para publicação e simulação. A pré-visualização substitui a peça proposta uma vez, lê as versões atuais das restantes peças e inclui áreas que partilhem o mesmo recurso físico. Alterações de máquina/semana retiram a carga anterior e usam o novo calendário. Fonte pendente, população indisponível, recurso por confirmar, carga desconhecida ou disponibilidade sem valor positivo não originam percentagens inventadas. A ligação de simulação é readonly e não persiste evidência histórica.
- Cantoneiras com preparação112 e preparação209 conserva112 como operação principal. A operação secundária contribui com as suas próprias horas. Corrigida também uma omissão de apresentação: `hours_pct` estava excluído do contrato de Cantoneiras, apesar de o servidor o calcular. F12 passa a aparecer na pré-visualização e fica disponível como coluna calculada da RAW dessa área.
- **145 testes passaram** na regressão do motor, OCR, cálculos, população, produtividade, horas, necessidades e RAW. Depois da correção final da coluna Cantoneiras, **55 testes passaram**, incluindo os9cenários F12 e os contratos de apresentação. Logs: `c05-f12-regression.log` e `c05-f12-final-tests.log`. Casos incluem recurso partilhado entre áreas, outra peça alterada antes do worker, novo registo contado uma vez, máquina/semana antiga e nova, duas operações, fonte pendente, OF fechada e ocupação desconhecida.
- `c05-f12-full-comparison.json`: **113988 linhas**, **zero diferenças** entre a publicação anterior e a reconstrução integral com o motor extraído, comparando todos os conteúdos nos7datasets das duas áreas e excluindo apenas a época de publicaçãoF12. Tempos Perfis14,39s, Cantoneiras100,39s e capacidades50,38s. Esta prova é de equivalência do motor; não substitui a reconciliação independente com os Excel nem aprova a reconstrução global nos limitesC05.
- `c05-f12-browser.json`: pré-visualização real Q60 sem gravação. Perfis:3h/16h=**18,75%**; ao mudar recurso e semana,6h/14h=**42,857142857%**. Cantoneiras:1,5h/16h=**9,375%**; ao mudar,3h/14h=**21,428571429%**. O período anterior fica0h. Pedidos incluindo debounce:4,31–4,43s emPerfis,7,58–8,67s emCantoneiras; resposta→resultado visível6–28ms. A respostaQ61 é deliberadamente retida atéQ62 estar visível; a sua chegada não restaura o valor antigo. Capturas `c05-f12-*-preview.png` inspecionadas.
- `c05-f12-readonly-audit.json`: hashes/contagens antes e depois do browser iguais para necessidades, preparações, revisões, eventos, comandos, outbox, configurações, jobs, sinais, conteúdos/membros e gerações correntes. Revisões principais7→7 e6→6; quantidade persistida40 nas duas áreas. Worker isolado desligado durante esta medição.
- `c05-f12-save-browser.json`: worker real na cópia, formulários, RAW e detalhe de capacidades abertos. Na repetição final, Perfis40→60→40 e Cantoneiras60→40→60→40 (primeiro passo repõe a quantidade guardada pelo ensaio interrompido). Todos os resultados calculados da pré-visualização coincidem com a RAW guardada. Pedidos7,51–7,67s; resposta→RAW **0,89–1,954s**; resposta→capacidades/detalhe **1,99–3,905s**, semF5. Os limites2s/10s são verificados pelo teste, separadamente da latência do pedido. Quantidades finais40, revisõesPerfis11/Cantoneiras10.
- `c05-f12-saved-audit.json`: **5 XLSX** lidos pelo openpyxl coincidem com os CSV e a RAW para quantidade, saldo, horas e ocupação. Depois de reiniciar exclusivamente o servidor18113, a API e PostgreSQL conservam as mesmas revisões e valores; fontes/agregados sem pendência. Perfis2h/12,5%; Cantoneiras1h/6,25%.
- `c05-f12-current-audit.json`: **83152 peças**, **18977 operações principais** e **102 conjuntos de evidência histórica**, zero falhas na reconciliação independente de eventos/dimensões/horas e na igualdade RAW/capacidades/F12. `c05-f12-population-audit.json`:1197ativas+6218históricas emPerfis;17780ativas+57957históricas emCantoneiras; nenhuma fechada em capacidades. Identidades das fontes, necessidades e preparações iguais à etapa OCR anterior.
- Falhas intermédias e diagnósticos conservados em `c05-f12-diagnosis.json`: contrato de apresentação Cantoneiras corrigido; teste de browser corrigido para ler1,5 com vírgula decimal; fixtures de catálogo/recurso corrigidas sem alterar regras de negócio. As quantidades de ensaio foram repostas e as revisões legítimas conservadas.
- Servidor isolado final **PID741189, sessão67522, porta18113**. Worker de ensaioPID719347 desligado após os testes. Serviços8113/8100/8101 e worker operacional não reiniciados. Os27ficheiros tracked preexistentes continuam iguais ao baseline. Manifesto e checklist atualizados com hashes reais.

### Trabalho integral que continua pendente

Continuam necessários: confronto numérico independente de todos os campos/populações Excel; publicação real e reconciliação do OCR original; matriz completa de formulário/PDF e operações; associações e dependências históricas fechadas em todas as alterações; horas manuais, janela histórica e vigências; fecho/reabertura completo; restantes provas de colunas, zoom e resoluções, e Calibri11pt efetivamente renderizado; concorrência/falha/recuperação integral; regressão final e publicação exclusiva do Planeamento. Acesso à base/consola do original e origem licenciada da Calibri permanecem dependências externas. **C00–C11 em curso; C12 por executar.**

## C10 — Estimativas fechadas e dependências: desempenho ainda reprovado

Revisão de trabalho: `29799510eb288a964b7f8bcc5b1e03df4c29ca282570fb02fd09423bdae9df85`. A revisão anterior F12 permanece identificada pelo seu manifesto arquivado; não se atribuem as provas antigas à revisão nova.

- Corrigida a propagação de alterações de horas, taxa, janela e identidade de recurso às estimativas de peças fechadas. As peças continuam fora da carga ativa. Calendário isolado não provoca recálculo de estimativas fechadas. Detalhes RAW/capacidade abertos conservam o contexto e recebem a versão atual.
- Publicação parcial das estimativas conserva os conteúdos anteriores e combina os campos calculados no servidor PostgreSQL, preservando JSON de origem. O identificador derivado compromete o hash do conteúdo anterior e a alteração; a igualdade de conteúdo com reconstrução integral está coberta nas fixtures, mas ainda precisa da repetição integral em volume nesta revisão.
- `c10-patch-publication-tests.log`: **33 testes passaram**. Incluem prioridade manual→histórico→Excel, horas revistas, janela, nova produção, linhas fechadas, pesquisa e consulta de versões antigas. A regressão alargada anterior continha duas falhas de chamada incorreta da fixture já corrigidas; precisa de repetição final após as alterações de publicação.
- `c10-dependencies-browser.json`: **15 passos** concluídos, sem erros JavaScript e com os valores esperados. Perfis:8passos, máximo**6,091s**. Cantoneiras:7passos, máximo**24,739s**. **As sete medições Cantoneiras reprovam o limite10s**. Primeira estratégia demorava cerca25s; a publicação parcial ainda não resolveu o problema. O teste conserva a falha, não aumenta o limite de aprovação.
- `c10-dependencies-audit.json`: **10 provas históricas e15passos reconciliados independentemente**, incluindo volumes dos eventos, horas das revisões originais/manuais, taxa aplicada, horas estimadas, H03 e H01 inalterado. Amostras fechadas semF12; dados de origem e versões antigas preservados. Esta auditoria aprova aritmética/preservação, não desempenho.
- `c10-dependencies-profile.log`: recálculo instrumentado22,87s; publicaçãoRAW9,46s, cálculo8,97s e identificação de dependências3,92s. Somam-se esperas PostgreSQL, serialização repetida e cópias de estruturas. Restauro sem instrumentação20,36s. A declaração de horas foi reposta através de nova revisão legítima.
- Servidor isolado atualPID874954, porta18113. Worker isoladoPID875657 parado após o browser; perfil executado sem worker concorrente. Ensaios confinados à cópia. Serviços operacionais/kanbans intocados;27ficheiros tracked preexistentes preservados.

Falta nesta etapa: reduzir o tempo Cantoneiras abaixo10s, repetir browser e OCR afetado, regressão alargada, comparação integral e auditoria final após otimização. Mantêm-se todas as restantes pendências integrais: Excel, ligação real aoOCR original, cenários funcionais e interface, Calibri licenciada, falhas/concorrência e publicação. C00–C11 continuam em curso; C12 por executar.

- Repetição final com comando explícito: **34 testes passaram em73,65s**, zero falhas/ignorados, produtividade + capacidade incremental + pré-visualização F12. Log `c10-status-final-tests.log`. Não substitui a regressão alargada pendente nem corrige a falha de desempenho Cantoneiras.


### C10 — Otimizações, repetição completa e diferenças de evidência

Revisão `29ad8118ec3603a71654cf8b4edba3d94dd111d4b06d01910e274cd18ad95602` (91 ficheiros; manifesto anterior conservado em `execution-manifest-c10-v17.json`). Os 27 ficheiros tracked preexistentes continuam byte a byte iguais. Alterações e migrações apenas nos testes descartáveis/cópia integral; serviços operacionais e kanbans intocados.

Implementado: publicação parcial com decomposição JSON materializada e lotes de200; eliminação de cópias/serializações redundantes; cache do hash histórico; índice das peças com preparação secundária; índice de máquina/população com compatibilidade para membros antigos; entradas compactas do cálculo; pesquisa Unicode preservada; aviso PostgreSQL após commit para despertar o worker, mantendo consulta periódica de recuperação. Migrações029(LZ4),030(epochs) e031(dependências) aplicadas apenas à cópia/testes. O browser usa a data efetiva da aplicação para vigência; o ensaio OCR completa a reposição dos três passos antes de reprovar tempos, conservando o limite10s.

Provas atuais:
- `c10-final-browser.json`:15passos com valores esperados, zero erros JavaScript. Perfis máximo3,451s; Cantoneiras máximo10,724s. Duas falhas: janela1dia10,724s e janela90dias10,681s. Horas/taxas Cantoneiras abaixo10s. Desempenho global **reprovado**.
- `c10-final-ocr-incremental-browser.json`:6passos de inserir/corrigir/remover com valores esperados. Perfis capacidade4,797/6,721/5,523s. Cantoneiras17,528/12,639/15,596s:três falhas. Ambas as folhas sintéticas ausentes no fim; publicação corrente confirmada antes de parar apenas o worker isolado1061528.
- `c10-final-full-comparison.json`:113988linhas,5052diferenças (2843RAW Cantoneiras+2209itens capacidade). **Reprovado**, não substituir por uma declaração de equivalência. `c10-final-difference-classification.json` classifica todas: zero diferenças em `values_json`; hashes da evidência variam com a ordem de eventos excluídos;702linhas têm também janela histórica de operação adicional ainda em23/09 em vez24/09. A causa completa e a correção destas diferenças continuam pendentes.
- `c10-final-complementary-tests.log`:98testes passaram em126,13s; zero falhas/ignorados. Abrange worker/notificações, incremental, produtividade, capacidades, OCR, cálculos, horas e necessidades. Comando exato na checklist. Etapas anteriores conservadas separadamente:147testes antes das últimas otimizações,58compactos,50do índice e2casos de compatibilidade; não atribuir essas execuções à revisão final.
- `c10-final-history-audit.json`:7provas históricas e15passos reconciliados independentemente; H03/H09 e H01 preservado. Não aprova tempos.
- `c10-final-current-audit.json`:83152peças,18977operações principais,104históricos; zero falhas numéricas.
- `c10-final-population-audit.json`:83152peças e respetivo índice comparados com fontes; ativos/histórico corretos, nenhum fechado na carga ativa; identidades de fontes/necessidades/registos iguais à provaF12 anterior.
- Captura `c10-final-cantoneiras-closed.png` inspecionada: detalhe histórico mantém a peça, origem, taxa e horas; grelha permanece em Histórico/fechados.

Recálculo integral desta prova:Perfis12,291s,Cantoneiras73,790s,capacidades39,939s. Estes tempos não aprovam C05 e não medem uma atualização incremental. Regressão complementar iniciou após estes recálculos, durante a comparação de leitura final.

Estado final desta etapa: servidor isolado1061419 porta18113; worker isolado parado; fontes sintéticas removidas; recálculo integral atualizado. Falta corrigir consistência da evidência histórica, cumprir tempos Cantoneiras, repetir verificações afetadas e concluir a restante matriz. C00–C11 continuam em curso; C12 por executar.


### C10/C09 — Evidência consistente e referência semanal com horas manuais

Revisão `911c38b2d0d64f4b37f24292b892b33b13e590a4367c30ea8a28d485706416f5`,92ficheiros. Manifesto anterior conservado em `execution-manifest-c10-optimized.json`. Contratos RAWv9/capacidadev18 obrigam ao recálculo da evidência desta revisão. Sem novas migrações.

Corrigidas duas causas das5052diferenças anteriores:
1. Evidência histórica usa ordenação determinística de eventos/coortes/folhas e motivos; empates com conteúdo divergente também são determinísticos e continuam excluídos. A ordem de leitura PostgreSQL deixa de alterar o hash da mesma evidência.
2. Ao repor estimativas de capacidade de uma peça cujas entradas não mudaram, repõem-se apenas operações efetivamente representadas nos itens de capacidade. Diagnósticos de operações adicionais ainda por confirmar preservam a janela nova calculada pelo motor principal. O cálculo de capacidade usa a data passada à execução, sem reler o relógio no meio das linhas.

Corrigida ainda a referência semanal C09: a comparação de configuração inclui agora `worked_hours`, tal como a geração de capacidade. Deixou de rejeitar uma configuração atual só por existirem horas manuais; mudanças pendentes continuam rejeitadas.

Provas:
- `c10-evidence-regression.log`:**56passados em96,94s**, zero falhas/ignorados; comando exato na checklist. Inclui permutações de eventos/coortes, operação adicional por confirmar, referências atuais/pendentes e imutabilidade da referência guardada.
- `c10-evidence-browser.json`:15passos numericamente corretos, zero erros JavaScript. Perfis máximo3,391s; Cantoneiras janela1dia13,965s e90dias11,702s. **Duas falhas temporais mantidas**.
- `c10-evidence-ocr-incremental-browser.json`:6passos corretos. Perfis capacidade5,766/4,664/6,632s; Cantoneiras16,517/13,657/14,609s. **Três falhas temporais**. Confirmada ausência das duas folhas sintéticas e publicação atual no fim.
- `c10-evidence-full-comparison.json`:**113988linhas,zero diferenças** após os dois browsers, comparadas todas as14projeções/campos, excluindo apenas epoch F12. A reprovação anterior foi conservada; esta nova prova confirma a correção. Recálculo integral:Perfis12,248s,Cantoneiras72,677s,capacidade40,541s; não são tempos de atualização incremental.
- `c10-evidence-history-audit.json`:7provas históricas/15passos reconciliados independentemente; preservação H01, horas/taxas e versões.
- `c10-evidence-current-audit.json`:83152peças,18977operações principais,104históricos; zero falhas.
- `c10-evidence-population-audit.json`:83152peças e índice reconciliados com fontes; sem fechados na capacidade ativa; todas as identidades iguais à provaF12 anterior.
- `c09-reference-hours-browser.json`:preview aberto nos dois setores, período W2/2027 escolhido a partir de uma operação real existente na cópia, uma operação/Q40 em cada área. Zero erros. Browser sem gravação; gravação e revisões cobertas na regressão. Captura Cantoneiras inspecionada. A primeira tentativa escolheu W39/2026 sem operações e recebeu corretamente422; o teste passou a selecionar um período que contém operações.

Estado: servidor isolado1128639 porta18113,worker isolado1136217 parado após ensaios; fontes sintéticas removidas;27ficheiros tracked preexistentes preservados. Serviços operacionais/kanbans intocados. Mantêm-se desempenho Cantoneiras, comparação Excel integral, origem OCR original, cenários funcionais/interface/Calibri, recuperação/concorrência e publicação. C00–C11 em curso; C12 por executar.


### C05/C10 — Armazenamento de estimativas e atualização durante processamento

A revisão de armazenamento `836d0aad169aa724d5429e6b52202f83f421c9cb1330b748ae1be581627940f3` está conservada em `execution-manifest-c10-storage.json`. Acrescenta a migração032 apenas à cópia isolada e testes: versões de estimativa guardam a diferença para o detalhe completo de origem, com referência direta e leitura lógica compatível. Análises/exportações congeladas e versões antigas continuam disponíveis. O procedimento de materialização para reversão está em `c10-storage-reversao.md` e é exercitado por teste. Os leitores de capacidade recebem apenas os dados de que o cálculo necessita; a captura OCR reaproveita os factos da mesma transação e restringe o contexto administrativo às OFs afetadas.

- `c10-compact-storage-tests.log`:30 testes aprovados, incluindo reversão, análise/exportação congelada, estimativas fechadas e contexto/associações OCR. As falhas iniciais de SQL e fixture foram corrigidas e os logs conservados.
- `c10-storage-final-browser.json`:15 passos aprovados com valores corretos e sem erros JavaScript; máximo9,727s em Cantoneiras.
- `c10-storage-final-ocr-incremental-browser.json`:6 passos numericamente corretos; Cantoneiras inserção10,061s e remoção10,584s reprovam o limite10s. As publicações na base foram observadas em8,797s e9,121s, respetivamente. Todas as folhas sintéticas foram removidas. Esta falha permanece registada.
- `c10-storage-final-full-comparison.json`:113988 linhas dos14 datasets/áreas, zero diferenças face à reconstrução completa, excluindo apenas a época de publicaçãoF12. Tempos de reconstrução Perfis12,30s, Cantoneiras71,78s e capacidade33,06s; houve testes independentes em paralelo, pelo que estes tempos não são prova de desempenho incremental.
- `c10-storage-final-history-audit.json`:7 conjuntos de evidência e15 passos reconciliados independentemente. `c10-storage-final-current-audit.json`:83152 peças,18977 operações principais e104 conjuntos históricos, zero falhas. `c10-storage-final-population-audit.json`:população/índices corretos, nenhuma fechada na carga ativa e identidades das fontes/objetos locais iguais à provaF12.

A revisão seguinte `85d927cea2d6b6139c95417652ac25c2dda93c15b44d8b0b01ada3e040e05e2a` acrescenta estado pendente à consulta de versão e intervalo250ms apenas durante processamento (1s em repouso), tanto na RAW como nas capacidades. Conserva formulários abertos e não sobrepõe consultas automáticas. `c10-refresh-status-tests.log`:2 testes aprovados; a versão de capacidade mantém-se enquanto a fonte está pendente, e o sinal termina após publicação. Regressão alargada e browser desta revisão ainda em execução neste registo.

Os27 ficheiros tracked preexistentes continuam byte a byte iguais à baseline. Servidor operacional8113, worker operacional e kanbans8100/8101 não foram reiniciados nem alterados por esta etapa. Nenhum checkpoint global é aprovado: mantêm-se Excel, fontes reais OCR, matriz funcional/interface, Calibri, recuperação/concorrência e publicaçãoC12.


**Fecho das provas desta etapa:** `c10-storage-refresh-regression.log`: **180 testes aprovados em258,11s**, zero falhas/ignorados. Comando: `RUN_PG_INTEGRATION=1 .venv/bin/python -m pytest -q --tb=short tests/test_planning_capacity_preview.py tests/test_planning_capacity_incremental.py tests/test_planning_incremental.py tests/test_planning_productivity.py tests/test_capacity_revision.py tests/test_planning_ocr_incremental.py tests/test_planning_integral_calculations.py tests/test_planning_population.py tests/test_planning_worked_hours.py tests/test_raw_workspace.py tests/test_planning_needs.py tests/test_planning_worker_wakeup.py tests/test_planning_registry.py`.

`c10-refresh-browser.json`: os15passos históricos passaram; Perfis máximo3,636s, Cantoneiras6,432s; pedidos de gravação51–154ms medidos separadamente. A repetição da auditoria independente está em `c10-refresh-history-audit.json`:7conjuntos e15passos,zero falhas. `c10-refresh-ocr-incremental-browser.json`:6passos passaram; Perfis máximo3,820s e Cantoneiras9,182s.

O testeOCR foi depois reforçado para selecionar as colunas pela interface e comparar os valores realmente renderizados, com a precisão de4casas decimais da grelha. A primeira tentativa (`c10-visible-*`, revisão6fd39ee) revelou uma corrida no capturador da primeira resposta de capacidade, antes de qualquer mutação; foi corrigida no teste e a falha preservada. A aplicação permanece byte a byte igual à revisão85d927. Revisão final **863184f10a6aea04df7efe2a25fa70c8c57d491b04be8e719a0488dc129ed671**,93ficheiros no manifesto.

`c10-visible-final-ocr-incremental-browser.json`: seispassos aprovados, zero errosJavaScript. Commit→células visíveis: Perfis3,232/3,613/3,872s; Cantoneiras9,7275/7,397/9,164s. Cantoneiras inserção mostra saldo38 e7,6h; correção mostra23 e3,68h com origemHistórico; remoção volta a saldo/horas desconhecidos e referênciaExcel. Perfis conserva taxa manual20un./h e mostra32/1,6h e17/0,85h. Captura `c10-visible-final-cantoneiras-ocr-live.png` inspecionada. Diagnóstico readonly adicional `c07-reduced-columns-diagnostic.json` confirma campos/posições das três colunas fixas na vista reduzida; não substitui a matrizC07/C08.

Estado final `c10-refresh-final-state.json`: folhas sintéticas ausentes, nenhuma pendência de fontes/agregados, identidades de todas as fontes e objetos locais iguais à baselineF12. Servidor isolado **PID1278293, sessão77974, porta18113**, revisão atual de aplicação. Worker isolado **PID1284206 parado** depois dos ensaios; sessão71424. Operacional8113/worker239069 e kanbans8100/8101 intocados. Manifesto/checklist incluem as provas e mantêm estado integral em_curso;C12 por executar.

Próximo trabalho integral: concluir inventário célula/regra e comparaçãoExcel (C00/C04), integração real/reconciliação das três origensOCR (C01/C02), paridade formulário/PDF/operacoes, matriz de fecho/reabertura, colunas/zoom/Calibri e capacidades, cenários restantes de dependências/recuperação/concorrência e publicação apenas após os critérios integrais aprovados. A aprovação destes ensaios de desempenho não aprova o plano completo.


### C00/C04 — Quantidade estruturada e auditoria aritmética de população

Revisão `955de2782bef108804a916ea771aed6bc006623d5526c9e8ded75348b2bd76d2`, 98 ficheiros. Perfis passa a ler a quantidade estruturada AH; N permanece preservada como origem legada. Foram corrigidas 12 linhas históricas, sem alterar a população ativa nem os dados de origem. A leitura manual e PDF coincide em 7413 fontes; 7411 linhas RAW sem preparação local foram comparadas. As duas preparações associadas a macro mantêm os seus valores humanos. As 12 linhas corrigidas passaram no browser, incluindo área AP à precisão de apresentação.

`c04-structured-quantity-tests.log`: 63 testes passaram; `c04-structured-quantity-regression.log`: 101 testes passaram. O conjunto unitário de 32 testes é sobreposto e não deve ser somado. `c04-quantity-current-audit.json` verifica 83152 peças, 18977 operações principais e 104 conjuntos históricos; a auditoria de população preserva os IDs e não encontra fechados na carga ativa.

`c04-formula-population.json`: 717117 comparações aritméticas independentes em 83152 peças, sem diferenças no âmbito de 23 regras; 493 casos de catálogo cobrem 20 famílias. As entradas são os valores tipados e contadores selecionados: esta prova não aprova a seleção de fontes C01/C02 nem o confronto completo de caches e fórmulas Excel. `c00-contract-origin-inventory.json` inventaria 129 campos RAW, 40 campos por catálogo de formulário e 43 regras. A prova dos controlos efetivamente renderizados permanece pendente.

`c00-baseline-isolation-audit.json` aprova individualmente C00.1 e C00.4, com hashes, serviços, ambiente descartável e baseline. Nenhum checkpoint global está aprovado. Nova conferência dos 98 hashes e dos 27 ficheiros tracked preexistentes passou antes de iniciar o comparador direto Excel. Fontes/serviços operacionais e kanbans intocados.


### C04 — Comparação direta Excel, 292 comprimentos recuperados e motivos visíveis

Revisão `2353787bc73e5a4e125f2ff51013252c7585aee55954af79ef6475fd9307b590`, 101 ficheiros. Método, limites e resultados detalhados em `c04-excel-source-method.md`.

O novo comparador liga as 717117 verificações aritméticas às células/fórmulas/caches originais e às instruções textuais do layout. Encontrou 292 comprimentos Cantoneiras com agrupamento de milhares (`1 543`) que o importador legado deixara desconhecidos. O Planeamento recupera a entrada original com validação estrita; preserva a projeção importada e não inventa saldo/produção. Auditoria completa dos comprimentos e origem manual: 292 recuperados, uma entrada ainda desconhecida, zero divergências, hash das fontes igual ao anterior. As 292 peças são ativas e sem produção conhecida.

O motor passou a propagar motivos concretos de indisponibilidade; o detalhe Cálculos mostra esses motivos. Foi corrigida também a identificação dos cabeçalhos das tabelas auxiliares para acessibilidade. Contratos cálculo v2 / RAW v12; nova reconstrução apenas isolada. `c04-excel-source-regression.log`:126 testes passaram; `c04-excel-source-population.json`:717117 verificações/83152 peças e493 casos de catálogo passaram. Os207276 resultados indisponíveis deste âmbito têm motivo, sem a mensagem genérica anterior.

`c04-imported-lengths-browser.json`:292 linhas API e três amostras UI passaram, incluindo pesquisa e segunda página; comprimento/total e motivos renderizados conferidos, zero erros JavaScript. Falhas anteriores do ensaio foram conservadas e diagnosticadas. `c04-excel-source-current-audit.json`:83152 peças/18977 operações/104 históricos sem falhas. População, IDs e exclusão de fechados preservados. Fontes, 27 ficheiros tracked preexistentes e serviços operacionais/kanbans intocados.

**C04 não aprovado:** `c04-excel-comparison-classified.json` sai com código1 e conserva20014 diferenças ainda por investigar (847 Perfis,19167 Cantoneiras). A ausência de cache e de coluna equivalente é contada separadamente, sem se afirmar igualdade. Próxima prioridade: pesos unitários/pendentes Cantoneiras e diferenças restantes de contadores/área/barras; continuam também as20 regras e restantes gates integrais.

Servidor isolado PID1449546 porta18113, sessão73420; worker isolado não iniciado. Nenhum checkpoint global aprovado; C12 por executar.

### C04 — Pesos exatos e resultados visíveis

Revisão `95e3fc1f9c9f01e5e8b865f4e49063066eb40a7849d7bf796a370a1da6ef0f70`,104 ficheiros. Método e limites em `c04-result-columns-method.md`. Oito resultados adicionais apenas de leitura disponíveis nas duas RAW;137 campos no contrato. Cálculos mostra valores e origens; peso original de Cantoneiras separado do atual.

966573 verificações aritméticas/83152 peças/23 regras sem diferenças,493 casos de catálogo. Classificação de pesos com identidade/comprimento/tabela/caches comprovados. A comparação Excel ampliada conserva2590 diferenças(1069Perfis/1521Cantoneiras),com código1;250981 resultados indisponíveis têm motivo. Não aprova C04 nem seleção de fontes.95 testes passaram;12 testes do auditor são sobrepostos. Três amostras browser e seis exportações CSV/XLSX passaram,com hashes finais conferidos e captura do peso importado inspecionada.

Checklist atualizada com oito provas. Gerações3543/3544 inalteradas,27 tracked preexistentes preservados,servidor isolado1507575;nenhum worker isolado iniciado ou serviço operacional alterado. C00–C11 continuam em curso;C12 por executar. Prossegue a investigação de quantidade legada e referências deslocadas de área em Perfis.

### C04 — Reconciliação de quantidades, propriedades e saldos negativos

Revisão `c6367c4ac3d89afcc23eacd2829354a335b64b67a7ec45522155600d4ddc12a7`,104 ficheiros; apenas auditor/testes mudaram desde95e3fc1. Método em `c04-perfis-source-method.md`.43 testes do auditor passaram; comparação final completa dos966573 resultados termina com código1 e **1797 diferenças pendentes(486Perfis/1311Cantoneiras)**,redução líquida793.

Justificadas24 diferenças de totais AH/N,67 propriedades unitárias comQ=0,uma comQ ausente e180 resultados sem correspondência exata de área. Reforçada a justificação dos negativos: quantidade/produção e excesso têm de coincidir com as entradas e resultados antigo/novo independentes; divergências não comprovadas continuam pendentes. A prova intermédia foi preservada. Nenhuma mudança nos dados ou na aplicação,cujo browser e exportações permanecem na revisão95e3fc1.

Quatro novas provas registadas. A comparação dos ledgers identifica794 diferenças justificadas e uma reaberta pela verificação mais exigente(saldo Perfis,linha6555),redução líquida793. Fontes,104 hashes,27 tracked e gerações3543/3544 conferidos;serviços operacionais intocados. Não aprova C04 ou associação de fontes;20 regras fora da auditoria e restante matriz integral continuam por concluir. Próximos confrontos incluem contadores/OCR,dimensões ausentes,referência deslocada de área e duas preparações locais com datas próprias.

### C02 — OCR real central: correção do nome MAQ. ABOCARDAR

Revisão `ff19b4af62c3a83724784447eed976fb0038f337b4143d547188ddb3171536a1`,108 ficheiros; contrato RAWv13. Método em `c02-abocardar-method.md`. O auditor independente encontrou quatro totais bloqueados por dois registos cujo nome explícito de operação não era reconhecido. Corrigido o equivalente «MAQ. ABOCARDAR», mantendo nomes desconhecidos pendentes.

OF264774: peça34513 passa de100/135 Excel para840 cortadas/765 abocardadas OCR(saldos0/75);34514 passa a840/668 OCR(saldos0/172). A peça34512 mantém840 cortadas,saldo0 e identidade separada.80 testes passaram;1389 totais de operação foram conferidos nos2351 registos centrais,sem divergências no âmbito auditado. Browser3 peças,5 operações de capacidade e6 exportações passaram.966573 verificações aritméticas e auditorias de capacidade/histórico/população passaram.

Comparação Excel atual conserva1802 diferenças(491Perfis/1311Cantoneiras),mais5 após corrigir a seleção de produção. Falta ligar a evidência central às justificações por campo; não se aceita OCR como explicação automática. Ingestão original Windows e restante matriz C01/C02 continuam pendentes. Onze provas registadas, incluindo a reprodução das quatro falhas.

Fontes e necessidades com hashes idênticos antes/depois;27 tracked preexistentes preservados. Reconstrução apenas isolada,gerações3559/3560;servidor isolado1629587 substitui1507575. Nenhum worker isolado iniciado ou serviço operacional alterado. C00–C11 em curso,C12 por executar.

### C04 — Eventos OCR ligados à comparação por campo

Revisão `4c91583691014c36cc7e3cc80b4c774197e80e63de84bc5280aef0bea3df72f4`,108 ficheiros. Só auditores/testes mudaram; aplicação continua na revisãoff19b4a. Método e pendências detalhadas em `c04-ocr-counter-method.md`.

O comparador exige prova central atual, versão publicada igual, população de eventos completa, entradas compatíveis e reconstrução numérica da fórmula/cache antigo e resultado atual.81 testes passaram. A prova central repetida confirmou1389 totais nos2351 registos. Na comparação completa dos966573 resultados,1695 diferenças ficaram justificadas(403Perfis/1292Cantoneiras);**restam107(88Perfis/19Cantoneiras)**,código1. Nenhuma aprovação integral de C04 ou de ingestão de fontes.

Os casos restantes incluem dimensões ausentes/inválidas,derivados literais,quantidade legada N,uma fórmula de área deslocada,pesos negativos e duas datas de preparações locais. Diagnósticos preservados; falta completar justificações independentes e as restantes regras/criterios integrais. Quatro novas provas registadas;108 hashes,27 tracked,gerações3559/3560 e fontes centrais conferidos. Nenhuma alteração à base,aplicação ou serviços operacionais nesta etapa.

### C04 — Zero diferenças pendentes nas 23 regras auditadas

Revisão `4ab49ae490a2c652935aebcab7d899bc39b8a7468472b09b11f6461ad7f6b42f`,108 ficheiros; apenas comparador e testes alterados. Método em `c04-reconciled-cache-method.md`.143 testes passaram sem falhas ou ignorados. Comparação integral de966573 verificações/83152 peças termina com código0:zero diferenças pendentes neste âmbito,250978 resultados indisponíveis com motivo.

As107 pendências anteriores foram justificadas:25 geometrias,40 derivados literais,11 quantidades AH/N,15 pesos sem propriedade,10 pesos negativos,2 datas manuais auditadas,1 fórmula deslocada,1 saldo zero/barras,1 quantidade desconhecida/área e1 contadorOCR/peso direto. Delta prova que nenhum dos107 valores atuais ou caches antigos foi alterado. Execução intermédia com19pendências e código1 preservada com cópia do auditor correspondente.

108 hashes,27 tracked,fontes centrais,gerações3559/3560 e processos conferidos. Aplicação permaneceff19b4a;servidor isolado1629587 e serviços operacionais inalterados. Cinco provas registadas. C04 ainda incompleto:20 regras fora desta auditoria e restantes critérios/matriz integral pendentes;C00–C11 em curso,C12 por executar. Próximo trabalho: completar critérios de interface/registo e a cobertura das20 regras,sem repetir esta comparação sem alteração que a invalide.

### C07 — Colunas aprovadas no ambiente isolado

Revisão `c8276b95df312ed485d90177208fa44ba7db7b16a31255f1f53b13eec24be23e`,111ficheiros. C07.1–C07.4 aprovados após completar80movimentos,setas/foco/grupos/scroll/URL,arrasto nativo entre/dentro de grupos,137campos,larguras,vistas antigas/guardadas,reset e separação de áreas. Corrigido foco perdido ao redimensionar por teclado;falha real preservada emc07-complete-pointer-trial. Primeiro gesto de dragTo foi diagnosticado/corrigido no teste com eventos nativos rastreados.

Percurso finalc07-complete-focus-fixed passou nas duas áreas comzeroerrosJS. ConferênciaSQL comprova definições eversões;duas vistas legadas e duas guardadas adicionadas apenas no clone. Fontes/necessidades e gerações3559/3560 inalteradas,27tracked preservados,111hashes eJS servido conferidos. Nenhum reinício operacional. Método emc07-complete-method.md. R03/R04 ainda dependemC12;C08 e restantes checkpoints não aprovados por esta prova. C04 mantémzero diferenças nas23regras,restam20regras e matriz integral.

### C03 — Registo manual aprovado no ambiente isolado

Revisão `731c699358389503f68ed7d1b80a0c75a6606f221aaed53aa8f22e71ed253961`, 115 ficheiros. C03.1–C03.5 aprovados: duas OF novas com duas peças cada, contexto local, alteração/reabertura, idempotência, conflito de revisão, edição parcial, paridade RAW/formulário, resultados e carga em rascunho. Corrigida ausência da opção zero adicional em Cantoneiras; 27 testes PostgreSQL passaram. Ensaios browser e auditoria SQL passaram; seis necessidades anteriores e fontes preservadas, nenhum evento OCR criado. Método em `c03-complete-method.md`.

População 83156, gerações 3769/3770; 27 tracked preexistentes e serviços operacionais preservados. Worker isolado parado. Comparação C04 anterior permanece vinculada às gerações 3559/3560, sem extrapolação para o estado atual. C03 e C07 aprovados; restantes checkpoints e publicação integral pendentes.

### C08 — Acesso a todas as colunas e zoom real

Revisão `efb600edde8c45bf564c453a299e925417b6887a304973304ed2f942cbf7d17b`, 116 ficheiros. Corrigidas colunas tapadas pela fixação a 390 px e deslocamento automático atrás de colunas fixadas a 200%. Oito cenários nas duas áreas, 500 linhas, 548 verificações de colunas e 48 painéis passaram sem erros JS. 56 capturas preservadas. C08.1/C08.4 aprovados; C08.2 ainda requer tipografia das restantes páginas e C08.3 permanece dependente de Calibri autorizada (CDP: Liberation Sans).

Dados, gerações 3769/3770 e 27 tracked preservados; nenhum reinício operacional. Correção relevante ao relatório: bases/escritas de teste são isoladas, mas os estáticos são partilhados com Planeamento 8113 e já refletem as alterações. Igualdade de PID não comprova interface inalterada. C12 integral continua por executar; método em `c08-real-zoom-method.md`.

### C09 — Capacidades e horas aprovadas no ambiente de teste

Revisão `2e224c22c815c52246ec5f8d907f0d6c806d1800e0d033e994c1bf6faaa29af0`, 120 ficheiros. C09.1–C09.4 aprovados com 22 estados numéricos, 20 atualizações sem F5 (máximos 2278/3042 ms), reabertura, idempotência, história e rejeições atómicas. Horas reais 7→6 não mudam as 16 h disponíveis. A revisão atual das 3 folhas Perfis e 9 Cantoneiras confirma uma declaração manual de 6 h por recurso, sem duplicação. 43 testes passaram em 68,53 s.

Corrigida resposta tardia das peças que substituía o separador de parâmetros; reprodução e validação nas duas áreas preservadas. Retoma das provas numéricas de Perfis após falha de captura documentada e ligada por SHA. Método em `c09-complete-method.md`. SQL confere dez necessidades/fontes intactas, seis IDs de configuração e duas novas declarações apenas no clone. Gerações 4259/4260; worker isolado 1882801 parado. Estáticos partilhados com 8113, sem reinício operacional; C12 ainda pendente. C03/C07/C09 aprovados; restante plano continua incompleto.

### C06 — População nas consultas antigas, com lacuna restante identificada

Revisão `321dfb05ea40e871bd24d7f6e0a227a8d184fd40cf3ad3c9c92f7fa9db1f25c0`,126 ficheiros. Lista de OFs CPIS e seletor de linhas aplicam ativo/histórico/todos, com contagens por âmbito antes da paginação. Todas as cópias CPIS participam no fecho; desconhecidos continuam visíveis. Fichas existentes conservam acesso à origem fechada. Corrigida substituição de uma consulta recente por resposta atrasada.51 testes passaram em42,90s; browser e auditoria SQL passaram. Método em `c06-legacy-method.md`.

Auditoria de70280 OFs:1671 ativas/15560 linhas,68694 históricas/63894 linhas;85 OFs mistas pertencem aos dois âmbitos. Total79454 linhas com contextoCPIS. Identificadas36 OFs/3694 linhas importadas fora desse contexto, mais necessidades locais a rever: C06 não aprovado. Fontes/dez necessidades/gerações4259/4260 e27 tracked preservados. Servidor isolado2023637; nenhum worker isolado iniciado. Estáticos partilhados, mas controlos novos só surgem com contrato do backend (18113), preservando compatibilidade com processo8113 ainda antigo. Sem reinício operacional. C03/C07/C09 aprovados; C12 pendente.

### C06 — OFs sem CPIS, peças locais e associações reconciliadas

Revisão `3842d411e7d9d23a76d31bd49262d1d51caa42f0cbad1abac8c5742646eb026c`,130 ficheiros. Resolvida a lacuna das36 origens administrativas/3694linhas sem CPIS e das peças locais. Todas as83156identidades coincidem com RAW4259/4260:18981ativas/64175históricas. Fontes associadas contam uma peça e qualquer fecho de origem aplica-se à identidade. A origem P permanece visível como OF por identificar, sem OF inventada.

70testes passaram em78,03s;12testes de população/transições passaram em14,65s, com sobreposição (não somar). Browser abriu OFs locais/duas peças em ambas as áreas, referência sem duplicação, OF26499 e linhaCWA223E. POSTs somente de pré-visualização/consulta; hashes fontes/dez necessidades iguais. Método em `c06-complete-orders-method.md`.

27tracked e gerações preservados; servidor isolado2088150, sem worker isolado iniciado ou reinício operacional. Estáticos partilhados documentados. C06 permanece em curso: consumidor PDF `app/dossiers/cpis.py::read_context` ainda consulta só CPIS Perfis e confunde estados fora deOPEN_STATES com fecho. C03/C07/C09 aprovados; C11/C12 e restante plano pendentes.


### C06 — Continuação: dossiês e mudança dos IDs importados

Etapa ainda por consolidar no manifesto/checklist. Os dossiês passam a aplicar a população comum, mantendo a autorização de saída separada do fecho. `c06-dossiers-regression.log`: 163 testes passaram; `c06-dossiers-download-final.log`: passou a revalidação do fecho no download. `c06-dossiers-audit.json` compara 12 OFs/222 membros em 12 combinações observadas; não representa uma auditoria PDF de toda a população.

Reproduzida duplicação na RAW antiga após nova importação mudar os IDs de origem (`c06-legacy-raw-rebinding-before.log`). O construtor passa a resolver as associações atuais pelo mesmo helper da população canónica e remove o join administrativo capaz de multiplicar linhas. `c06-legacy-raw-rebinding-after.log`: 27 testes passaram em 49,76 s (população de OFs, RAW antiga e população comum); diff sem erros de whitespace. C06 permanece em curso. Ainda falta consolidar a evidência desta etapa e validar os consumidores no servidor isolado atualizado; não houve publicação operacional nesta etapa.

### C06 — Aprovado no ambiente isolado

Revisão `1162bd6f5bc676c5a18e15e83d5c62ad15128f26ef115604e7a1a364d9038cde`,137 ficheiros. Concluída a classificação comum nos dossiês e saídas; corrigida duplicação na RAW antiga após reimportação com novos IDs. Todas as7417identidades da RAW antiga coincidem com a geração4259; auditoria independente das83156peças e carga nas duas áreas passou:18981ativas/64175históricas. Contextos PDF:12OFs/222membros; amostra identificada, sem afirmação de OCRreal.

Regressão dossiês163passaram,downloadadicional1,RAW/população27,transições/H09/dossiês29,paginação2. Suites sobrepostas, não somar. Browserseisâmbitos,seleção/CSV de fechados e seis capturas passaram sem errosJS. PDFs,IDs,leituras e fontes conservados. Método/matriz em `c06-final-method.md`.

C06.1–C06.4 aprovados.137hashes,27tracked,fontes/deznecessidades e gerações4259/4260 conferidos; servidorisolado2165490. Processosoperacionaissemreinício; estáticospartilhadosdocumentados. C03/C06/C07/C09 aprovados; restantescheckpoints,C11/C12 epublicaçãointegralcontinuampendentes.

### C00 — Inventário e diagnóstico aprovados

Revisão `20280e3b1987852840457fe600d37b4f1e2f36f8238e7f1f72bbec73e018d907`,140ficheiros. Só ferramentas de inventário/diagnóstico alteradas.43regras com74origens concretas verificadas no XML/VBA dos ficheiros originais e esquema SQL.137campos principais,80entradas do catálogo de formulário,5administrativos e421ocorrências nos16contratos área/vista;20famílias classificadas.493casos de catálogo ligados à prova independente anterior. Corrigidas seis referências insuficientes/inválidas e a origem SQL de horas OCR.

Seis testes de extração passaram em0,14s. C00.3 liga seis grupos de diagnóstico à baseline/regressões; V01 relido na API4259 com três identidades corretas. Nenhuma alteração da aplicação,dados ou processos;140hashes,27tracked,fontes/necessidades e gerações4259/4260 preservados. Método em `c00-complete-method.md`.

C00 aprovado como inventário/diagnóstico. C00/C03/C06/C07/C09 aprovados;20regras ainda carecem da validação integralC04/C10. Ausências de metadados de unidade runtime explicitadas. FontesOCRoriginais,Calibri,C11/C12 e publicação integral permanecem pendentes.

### F01/F21/G12 — descrições, prazo e explicação dos resultados

Revisão `543b54546fcf2380e17ac592b26a13a11dc92c2361687048aaacc798543d886a`,143ficheiros. Auditoria independente:83156peças,1701766verificações,zero diferenças; descrição original conferida em83148origens únicas,oitolocais separadas. Gerações4275/4276.118testes passaram; browser emduasáreas sem erros. Corrigido detalhe object Object eidentificados data/origem/saldos poroperação.

Reconstrução manteve valoresnuméricos,identidades,fontes e27tracked. Únicovaloralterado:descrição vazia→nulo commotivo. Sóservidor18113reiniciado;estáticospartilhados8113/18113. ContratoC00atualizado por delta sem sobrescrever fontes. Trêsregras semânticas acrescentadas às23aritméticas;17ainda fora destas auditorias. C04/C11/C12 eentregaintegral incompletos. Método em `c04-semantic-method.md`.

### F12 e H01/H02/H04–H08 — agregados reconciliados

Revisão `4d6632794a76ff6ce819450cef03c8dc727a74e30845b4555743dda98e905152`, 144 ficheiros. Auditoria independente de 23494 operações, 185 grupos semanais e 21 máquinas: 115652 verificações, zero diferenças. F12 comparado com ocupação independente nas 18981 operações principais. Oito grupos têm disponibilidade confirmada e seis peças têm F12 conhecido; os restantes desconhecidos permanecem explícitos.

Paridade RAW/capacidade e aritmética dos 105 conjuntos históricos aceites também passaram. A escolha desses conjuntos e a prioridade das taxas ainda não são aprovadas. Sem escritas de dados/aplicação ou reinícios nesta etapa; fontes, configurações, versões4275–4282 e 27 tracked preservados. Método em `c04-capacity-arithmetic-method.md`.

34 regras abrangidas pelas auditorias independentes aritméticas/semânticas, com limites explícitos; nove ainda fora desse âmbito: F02, F03, F20, G01, G06, G07, H03, H09, H10. Cinco checkpoints continuam aprovados; entrega integral incompleta.

### F20/G07/G06/H10 — horas por operação e prioridade de taxas

Revisão `c3d70d991ee07d6db92f8e42ac52e67777a4b7a26effdfa4c7146da463307d2c`,148 ficheiros. 105999 estimativas de83156 peças:1343945 verificações de horas e938949 de prioridade/proveniência,sem diferenças.183fatores Thomas apenas no Excel;251 horas positivas,57957 zeros,47791 desconhecidas. H09 ainda tem de validar os105 históricos usados como entrada.

27 exemplos passaram;12casos browser,zeroerros,com paginação real;24exportações passaram. Corrigidas ferramentas de prova (operação secundária na fixture,paginação,leitor de células XLSX finais vazias),sem mudanças da aplicação. Métodos/tentativas preservados em `c04-operation-rate-method.md`.

Lacuna visual registada:as entradas de horas não explicitam comprimento/área,pendente C04.5. Auditorias específicas abrangem38regras; F02/F03/G01/H03/H09 ainda sem prova integral equivalente.148hashes,27tracked,fontes/configurações/gerações4275–4282/processos preservados. Sem escritas na aplicação/base ou reinícios. Entrega integral continua incompleta.

### Explicação completa das horas previstas

Revisão `1f7d5120cdd269d10f27dacbca135865fcbe1451bedec3bb4ae05a801a7cae80`,150 ficheiros. Cálculo e explicação partilham saldo,método,dimensão,volume,unidade,taxa e preparação; fator Excel explícito sem reaplicação. Regra por método, incluindo minutos/unidade e fixos; zero sem preparação. Publicação/preview/histórico/capacidade usam a mesma regra.

140 testes passaram;3060738 verificações nas105999 estimativas/83156 peças,zero diferenças.12casos RAW e2percursos de capacidade passaram,sem erros JS; capturas inspecionadas. Reconstrução4291–4298 não alterou qualquer valor escalar ou identidade. Fontes/configurações/27tracked preservados; apenas18113 reiniciado; estáticos partilhados8113/18113 conferidos.

Lacuna de theoretical_hours resolvida. C04.5 global continua pendente:inventário revelou outros derivados numéricos conhecidos com entradas vazias. F02/F03/G01/H03/H09 e matrizes/fontes/publicação continuam incompletos. Método em `c04-hours-detail-method.md`.

### Entradas e origens dos restantes derivados

Revisão `560f2323869dce3280fda156fc7956ac58378f8b3e9041f38bfe07a13fb4ed4e`,153 ficheiros;contrato v4. Produção/saldos/excesso/percentagens/geometria/comprimentos/pesos/perfis inteiros/ano e semana têm operandos efetivos, origem e motivo. Eventos OCR mantêm evidência; geometria inválida conserva fórmula; densidade explícita já não é rotulada sempre7850. Nomes do detalhe em português.

142 testes passaram;8147719 verificações de explicações nas83156peças,zero diferenças.966629 verificações aritméticas das23regras e1701766 semânticas atuais passaram;493casos de catálogo. Quatro percursos de browser,zero erros; capturas inspecionadas. Nenhum resultado numérico conhecido com mapa de entradas vazio.

Reconstrução4307–4314 preservou todos os valores e identidades,fontes/configurações/27tracked. Apenas18113reiniciado;estáticos partilhados com8113. Provas intermédias4301/4305 foram repetidas nas gerações finais4307/4308 após o finalizador rejeitar mistura. Método em `c04-derived-details-method.md`.

Cinco checkpoints aprovados; entrega integral incompleta. F02/F03/G01/H03/H09 continuam sem auditoria integral equivalente; completar fontes/associações,histórico,recálculo,Calibri/regressão/publicação. Próximo trabalho independente: H03 declarações únicas de horas e H09 aceitação/exclusão dos históricos.

### H03/H09 — declarações e conjuntos históricos conferidos

Revisão `283b85bd02bd4b0cc8a1dec5650fad9cd5f045a92da2deb81692d134d256643f`,158 ficheiros. Auditor independente H03 reconstrói286folhas/2351registos centrais e declarações manuais:1894verificações/185grupos semanais,zero diferenças. H09 decide os conjuntos antes de ler a seleção observada:107520verificações/105evidências/123contextos,105999estimativas e83156peças,zero diferenças. Três decisões de aceitação e711exclusões entre contextos;contagens não representam folhas físicas distintas.

64testes passaram,incluindo32exemplos dos auditores;6percursos browser passaram,zeroJS. Capturas inspecionadas. Horas parciais mantêm total desconhecido; conjuntos rejeitam numerador/denominador juntos. Provas usam os mesmos inputs e gerações4299–4314.158hashes,27tracked,fontes/configurações/processos preservados;sem alterações da aplicação/base/reinícios. Método em `c10-time-cohorts-method.md`.

40regras com auditoria independente específica;F02/F03/G01 ainda sem equivalente integral. C01/C02,matrizesC05/C10,Calibri,regressão final e publicação continuam pendentes;5/13checkpoints aprovados,entrega incompleta.

### Seleção por operação, formulário e desvalidação OCR

Revisão `a772dafbbd948b15ad6123ba0ceb1abd82de9c718b3963451f3e22b4830283de`, 165 ficheiros. Corrigidos acumulado Excel transferido entre operações, abertura RAW/formulário sem referências carregadas e falha de evidência/reconstrução quando desaparece um registo OCR com decisão humana. Decisão preservada; saldo desconhecido, com aviso.

552 testes passaram; browser opt-in executado separadamente e passou. Regressões afetadas e dois novos casos de remoção passaram. Oito estados de produção, três trocas de operação e duas aberturas RAW/formulário passaram. 1778925 verificações independentes da seleção, sem diferenças; as 43 regras têm agora auditorias específicas. 14 percursos de tipografia passaram; Calibri efetiva continua ausente.

C02.4/C02.5/C08.2 aprovados. C10.4 aprovado após reler as provas já existentes dos 15 passos de histórico e seis atualizações OCR; não repetir requisitos já demonstrados. Cinco checkpoints globais aprovados. Fontes/configurações/27 tracked preservados, gerações 4323/4324; servidor isolado 2629383. Publicação integral pendente. Método em `c02-sources-c05-forms-method.md`.

### OCR original ligado ao motor comum

Revisão `e94451e908ffe637e9218172abaaf184077400979b709e99df3b40d9d8406627`, 170 ficheiros. Eliminada a separação funcional do original: eventos centrais entram no matcher/seletor partilhado, mantêm IDs/origem e participam em revisões incrementais. Sobreposição com MES fica excluída de saldos e histórico. Diagnóstico por registo e revisão aplicada visíveis.48 testes afetados e browser final passaram.

Verificado o esquema original local: perfil/operação não garantidos. A associação automática só usa informação explícita suficiente; fixture do esquema real conserva exclusão com motivo. Próximo passo concreto: decisões humanas por ID estável original (a tabela atual aceita apenas ID numérico MES), depois horas originais. Acesso/publicação Windows real continua pendente.

Clone integral sem escritas/reconstrução, fontes/configurações/27tracked preservados; processos persistentes intactos. Backend novo testado em servidor descartável;18113 continua com a revisão anterior. Estáticos partilhados documentados. Nenhum novo checkpoint global aprovado; entrega incompleta. Método em `c01-original-pipeline-method.md`.

### 24/09/2026 — Revisão do objetivo a pedido do utilizador

Criado `docs/plano-trabalho-restante-planeamento-2026-09-24.md`: oito etapas T1–T8 cobrem os 31 critérios ainda não aprovados, preservando 27 critérios e cinco checkpoints aprovados. O plano integral passa a remeter para essa retoma; R01–R11/C00–C12 permanecem intactos. Reconciliadas observações desatualizadas da checklist, incluindo as 43 regras já auditadas e C10.4 já aprovado. C11.2/C11.4 têm provas parciais e ficam em curso; C01.2/C08.3 identificam as dependências externas. Nenhuma aprovação nova.

Trabalho interrompido registado: oito ficheiros da aplicação alterados após e94451e, mais SQL033 e teste de associações originais. Último ensaio: três passaram/um falhou (contagem seis versus dois; causa por confirmar), saída 1 recolhida da sessão existente. Primeira tarefa: concluir associação original; depois horas originais. Não foram corrigidos código/testes, executadas novas suites, alterados dados ou reiniciados/publicados serviços nesta revisão. O objetivo da app foi consultado e continua pausado; o texto do objetivo não é editável pelas ferramentas disponíveis.
