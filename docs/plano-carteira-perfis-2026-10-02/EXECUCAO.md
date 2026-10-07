# Execução do plano da Carteira (02/10/2026)

Plano: [PLANO.md](PLANO.md). Estado: **ativo em produção desde 02/10/2026 ~19:17** (autorizado pelo Luís): migração 046 aplicada, `kanban-planning` e `kanban-research-sync` reiniciados, vistas da base de pesquisa aplicadas, ecrã antigo removido (cópia em `~/.local/state/planning-carteira-membros/antes-20261002/`, com as definições anteriores das vistas `consulta_v2`). Teste de browser aprovado contra a produção.

## 07/10/2026 (noite): velocidade

O Luís pediu: «foca-te na velocidade do sistema, está muito lento». Fizeram-se quatro trabalhos em worktrees, cada um com um revisor (correção e produção/MES) e uma ronda de correções quando foi preciso. **Ativo desde as 21:00**: os três serviços foram parados e arrancados com o merge `422f296`.

**Causas encontradas:**
- **Memória do servidor esgotada:**
  - o `pyrefly` (verificador de Python da extensão do editor Antigravity) estava com 24 GB;
  - a swap estava cheia (31/31 GB);
  - às 15:00 o sistema matou o `kanban-planning` por falta de memória (pico de 10,1 GB). O serviço voltou sozinho 5 s depois.
  - Com autorização do Luís, o `pyrefly` foi reiniciado: a memória usada desceu de 52 para 21 GB.
- **Processador partilhado com os testes do PP1:** carga de 15 a 38 em 20 núcleos. Os processos do PP1 passaram a `nice 15` (à mão, temporário).
- **Caches esvaziadas a toda a hora:** a cada dado novo, a página seguinte refazia tudo (Gantt simples até 61 s).
- **Cada exportação do OCR** (~50 por dia útil) regravava as 15 611 linhas de `original:*`, porque `source_export.version`/`line` iam dentro de cada linha.
- **A lista de ordens** relia as importações inteiras a cada pedido.

**O que mudou:**
- **Exportação do OCR** (`app/raw/ocr_export.py`, `research_sync.py`):
  - a versão fica só nos metadados da geração; contrato da projeção `http-export-v2`;
  - uma exportação normal grava 1 conteúdo em vez de 15 610 (de ~52 MB para alguns KB; publicação de 3,9 para 1 s);
  - um minuto sem exportação nova sai logo;
  - houve uma regravação única às 21:00.
- **Caches e arranque** (`app/sector/cache.py` e `warmup.py`, mais portfolio, occurrences, board, load, KPIs, routes, `plano.js`, `setor_carga.js`):
  - **chaves:** dependem só do que cada página usa;
  - **dados novos:** a página responde logo com a versão anterior (marcada) e refaz uma vez em segundo plano, um cálculo de cada vez, com prioridade;
  - **erros:** um erro repetido volta a aparecer, em vez de ficar escondido;
  - **arranque:** aquecimento dos dois setores (cantoneiras 136 s, perfis 16 s).
  - Interruptores: `MES_PLANNING_WARMUP_SECTORS` e `MES_PLANNING_WARMUP_DISABLED=1`.
- **Lista de ordens** (`app/planning_hub.py`, `planning_order_population.py`): as importações são lidas uma vez por versão. A consulta das linhas da macro passou de 4,0 para 0,7 s. As respostas são iguais byte a byte (teste de referência).
- **Pequenas:**
  - o Gantt técnico recalcula sozinho uma vez quando a proposta é de outra versão do motor;
  - `.eyebrow` passa a 11 pt;
  - o motivo das quotas de capacidade passa a opcional.

**Medido em produção (antes → depois):**

| Pedido | Antes | Depois |
|---|---|---|
| Gantt simples MTG3 | 61 s | 0,18 s |
| Lista de ordens | 8,4 s | 5,2 s no 1.º pedido, 0,26 s depois |
| Carga MTG3 | 1,2 s | 0,5 s |
| Carteira e KPI | 0,2–0,6 s | 0,2–0,6 s |
| Pelo link | — | todas as páginas abaixo de 1 s |

A app fica com 2,1 GB depois do aquecimento.

**Testes:**
- Suite completa: 1177 passam, 11 falham (as mesmas de antes).
- `carteira_browser`, `setor_browser` e `manual_browser` passam contra a produção, com as gravações intercetadas.

**Limpeza do disco:** agendada para 07/10 às 23:30.
- Timer `planning-retention-20261007`; script `~/.local/state/planning-retention/noite-2026-10-07.sh`; registo `noite-2026-10-07.log`.
- Passos: índices de apoio CONCURRENTLY → migração 050 → `raw_retention.py --execute`, online → `VACUUM (ANALYZE)`.

**Por fazer:**
- **`ocr_original.export_rows`:** guarda uma cópia completa por versão (~22 MB por exportação, ~1,1 GB por dia útil). Proposta: migração 051 com conteúdos por hash e membros por intervalo de versões. Precisa de coordenação com o MES.
- **Detalhe da OF** (`/api/ordens/{of}`, 0,4–2,4 s): falta um índice em `raw_mtg.cpis_rows` (CONCURRENTLY, dono `dataresearchmtg_owner`).
- **`pyrefly`:** vai voltar a crescer se continuar a analisar `~/PPX_MVP_WORKTREES`. A correção duradoura é uma definição do editor do Luís.
- **Problema anterior, MES:** o MES não tem `app/cpis_copies.py`, mas o `planning_hub.py` partilhado importa-o desde 06/10, por isso o MES não arranca até isto se resolver.

## 07/10/2026: mínimo de burocracia (só os dados essenciais, gravar sempre)

Plano aprovado: `~/.claude/plans/esta-horrivel-n-o-existe-gleaming-clarke.md`. Pedido do Luís: «se eu não preencher os campos que não são essenciais, deixa validar na mesma… quero o mínimo de burocracias». Decisões dele: Planear numa linha sem máquina usa a sugerida; em «Mais opções» sai tudo menos Observações.

**Estado: ativo desde 07/10/2026 às 09:42**, com autorização do Luís. Os passos foram os de `scripts/ativar_2026-10-07.sh`, feitos à mão, e o recálculo completo terminou às 09:44 (gerações 5951/5952 com o contrato v10; capacidade 5956/5959 com o v34; ~1 GB).

**Verificação depois de ativar** (só leitura, gravações intercetadas):
- **Browser:** `carteira_browser`, `setor_browser` e `manual_browser` passam contra a produção. O formulário mostra só os campos essenciais, «Mais opções» tem só Observações, as notas não aparecem antes de escrever e o texto está a 11 pt. O link público serve a mesma versão.
- **Números:**
  - proposta: MTG2 995 linhas, MTG3 8 210;
  - sugestões: MTG3 14 355 das 14 396 linhas sem máquina, MTG2 299 de 478;
  - capacidade: semanas sem ano 932 → 0;
  - 0 calendários criados;
  - `identity_pending` 0.
- Ensaio do Planear só de leitura: L45X45X5 com 1 842 linhas planeadas, das quais 1 501 com a máquina sugerida.
- **Registos:** sem erros nem 5xx.

**Ficou por fazer depois da ativação:**
- **Gantt técnico:** a proposta de 24/09 fica «calculada com outra versão do motor» e não recalcula sozinha, porque só recalcula quando mudam as fontes.
- **Rótulos `.eyebrow`:** continuam a 9 pt em `planeamento_ui.css`.
- **Motivo das quotas de capacidade:** ainda é obrigatório.
- **«Ano de Picking confirmado»:** continua no Gantt técnico.
- **427 linhas fechadas das cantoneiras:** mudam de saldo a cada recálculo completo (problema antigo, desde 06/10).
- **Primeira chamada da Carga e dos KPI depois de um reinício:** demora 25–31 s.
- **Disco a 94%** (problemas que já existiam):
  - cada exportação do OCR regrava ~15 500 linhas em `raw_contents`, porque `detail.source_export.version` faz parte do conteúdo (~60 MB por exportação, 39 só hoje);
  - pastas de teste do PP1 em `/tmp` (21 GB);
  - arquivo de WAL do CRM (4,6 GB/dia).

**Como foi feito.** Três partes em cópias isoladas (worktrees), cada uma com dois revisores (correção; produção, MES e hard links), mais uma verificação de cada ronda de correções. Os revisores encontraram dois bloqueios na Parte 1 (a ligação automática ao Excel podia apagar o saldo das duas linhas; uma peça nova de uma linha reimportada ficava quase vazia), corrigidos e verificados.

**Dados essenciais.**

| Para quê | MTG2 Perfis | MTG3 Cantoneiras |
|---|---|---|
| Gravar | OF | OF |
| Entrar na Carteira | QTD inteiro | QTD inteiro |
| Metros | Comp. | Comp. |
| Planear | Máquina (sugerida se faltar) | Máquina (sugerida se faltar) |
| Horas | Máquina + Tipo + Designação (ou Ø/L/A/E) | Máquina + Comp. + 1.ª Oper. (defeito 119) |
| Prazo | Picking (sozinho), senão Data Corte | Data Corte |

**Parte 1: preenchimento manual.**
- **Campos que saem do ecrã** (os valores guardados ficam):
  - Previsão de execução, Semana/Ano de planeamento, Requisitado?;
  - Comprimento unitário do perfil, Quantidade a preparar agora;
  - Variante, Outras operações, Perfil especial, Forma da secção, Picking ano.
  - «Mais opções» fica só com Observações. Saiu também a lista morta `required_on_ready`.
- **Avisos.** Só os cinco essenciais (QTD, comprimento, máquina, área de corte, operação não numérica), em nota discreta ao lado do campo. Aparecem depois de mexer no campo ou de carregar em Guardar e nunca bloqueiam.
- **Valores por defeito:**
  - cantoneiras: 1.ª Oper. 119 e 2.ª Oper. 0 (limpar volta ao defeito);
  - Abocardar só X ou «-»;
  - densidade 7850 sem Qual.;
  - peça de PDF sem linha do Excel começa «sem produção».
- **Peça possivelmente repetida** (`identity_pending` deixa de existir). Liga-se sozinha à linha do Excel só quando, ao mesmo tempo:
  - há exatamente uma linha com a mesma OF e Referência;
  - essa linha está livre;
  - os campos escritos não a contradizem;
  - a QTD é igual ou está vazia.

  Caso contrário, conta como peça própria. O estado diz «…, ligada à linha do Excel».
- **«Qtd em falta»** (campo novo `remaining_declared`): passa a ser o saldo da operação principal.
  - Desconta a produção registada depois na mesma fonte.
  - Ao lado aparece «saldo atual: N», com «(fonte mudou)» quando a fonte da produção muda.
  - Substitui a conferência da quantidade.
- **Campos não mexidos seguem a origem.** Quando o valor do Excel ou do PDF muda, os campos que ninguém escreveu acompanham, incluindo Data Corte, Máquina, Equipa, Pav., Observações, Abocardar e 2.ª Oper. Um campo escrito à mão fica, com a nota «(Excel: X)».
- **Saíram:**
  - a conferência da quantidade e «Concluir preparação»;
  - o diálogo do PDF de outra OF (usa a OF do PDF);
  - «peças semelhantes»;
  - as caixas amarelas do PDF;
  - o aviso ao sair, que só aparece se houver algo escrito.
- **Sem 409 depois de importar:**
  - Excel mudado no disco: só nos caminhos interativos; o worker continua a parar;
  - catálogo na pré-visualização;
  - revisões: junta só os campos mudados (`changed_fields`).

  Os separadores antigos, sem `changed_fields`, continuam a receber 409.
- **Datas escondidas** (Previsão, Semana/Ano de planeamento): deixam de contar nas peças registadas e ficam só de leitura na Tabela. Os 2 registos de produção passam a ter o prazo da Data Corte, como na Carteira.
- **Semana W sem ano** (cantoneiras): ano deduzido, com a mesma regra da capacidade (`infer_iso_year(..., prefer_past=True)`).
- Contrato de cálculo `planning-integral-20260925-v10`.

**Parte 2: Carteira e Gantt.**
- **Planear numa linha sem máquina** grava a máquina sugerida como escolha da Carteira e planeia.
  - Ordem da sugestão: preferência aprendida dentro da ficha técnica, senão a previsão (`estimates`).
  - Só entram máquinas do setor, e nunca por cima de textos da Tabela como «Subcontrato».
  - A lupa mostra a mesma máquina. Fica marcada com a origem «sugerida» e não alimenta a aprendizagem.
  - Mensagem: «N planeadas; M com a máquina sugerida (podes mudar)».
- **Conflitos:** planeia o que não mudou e diz o que ficou de fora. Grupos até 3 000 linhas são enviados linha a linha.
- **Bloqueios** sempre por esta ordem: seleção → conjuntos de famílias → máquina. As sugestões calculam-se antes dos bloqueios e a escrita é em lote.
- **«Estado CPIS por confirmar»** deixa de tirar linhas da proposta: +21 linhas MTG2, +0 MTG3. As 3 386 MTG3 «Sem estado CPIS» estão fora por outras razões: 2 531 estacionadas S53, 782 sem prazo, 73 anuladas.
- **Gantt:**
  - Máquina escolhida por uma pessoa (Carteira, Tabela/Excel, conjunto, preferência aplicada ou escolha manual no Gantt):
    - «rota por confirmar», «Rota CPIS difere» e «sequência» passam a avisos;
    - a operação seguinte pode usar a máquina do Excel mesmo fora da ficha.
  - O motivo da escolha manual é opcional e a «regra técnica» saiu do ecrã.
  - Proposta desatualizada:
    - recalcula sozinha (no máximo 2 vezes, só quando as fontes mudaram);
    - não há duplicados na fila;
    - um separador antigo que carregue em Aceitar recebe o 409 de antes.
- **Motivos opcionais** («Sem motivo indicado»): Excluir, prazo, política e decisão de máquina por grupo.
- **Abocardar** desconhecido = sem operação de abocardar.
- **Dados reais:** MTG3: 14 355 das 14 396 linhas sem máquina recebem sugestão (41 ficam sem). MTG2: 299 de 478.

**Parte 3: Definições, Tabela e Capacidades.**
- **Máquina «confirmada»** deixa de ser precisa: conta qualquer máquina do setor no catálogo (+12 máquinas).
  - A caixa saiu das Definições.
  - Só se criam calendários para máquinas com turnos padrão > 0 (nunca calendários a 0).
- **Horas reais corrigidas à mão:** a conferência faz-se ao gravar, «Substituir as horas OCR» vem por defeito e a origem por defeito é «Correção manual».
- **Ano da semana W** deduzido; a confirmação por importação saiu.
- **Tabela:**
  - saiu «Guardar N linhas?»;
  - com `partial: true` (só o ecrã novo envia) grava as linhas que não mudaram e diz quais ficaram de fora e porquê («O Excel mudou nesta linha.», «A linha mudou entretanto.»);
  - faz uma leitura por versão.
- **`capacity.js`:** as caixas «Confirmo…» vêm marcadas.
- **Separadores das velocidades:** primeiro as operações mais usadas.
- **Contratos:** `capacity_revision` v34 (com as máquinas do catálogo) e `ESTIMATE_CONTRACT` v4.

**Testes:**
- Suite completa com browser no ramo final: 1079 passam, 55 saltados, 11 falham.
- As 11 falhas já falham no c074a8f: historical_cohort_audit ×5, macro_revisions ×2, original_hours ×2, sku_families ×2 (CSV fora do git).
- Novos: `tests/test_manual_essentials.py`, `tests/test_planear_sugerida.py`, `tests/test_fewer_confirmations.py`, mais testes em `test_sector_selection.py`, `test_integrated_gantt.py` e `test_manual_to_carteira.py`. `planning_browser.cjs` e `planning_gantt_browser.cjs` foram reescritos.

**Ativar** (`scripts/ativar_2026-10-07.sh`):
- Os passos são: parar → código → hard links → arrancar.
- Hard links com o MES: `need_editor.js`, `need_editor.css` e `capacity.js` escrevem-se no mesmo ficheiro físico.
- **Antes:** pedir para fechar ou recarregar os separadores abertos (Registar, Tabela, Carteira, Gantt).
- **Durante:** o primeiro recálculo completo (contratos v10, v34 e v4) ocupa cerca de 1–1,5 GB e dura 2–3 min. Nesse tempo as gravações ficam à espera.
- **Depois:**
  - os cenários do Gantt ficam desatualizados e recalculam ao abrir;
  - confirmar no log: sem Traceback, ImportError ou ValueError;
  - novas gerações `planning:*` e `capacity:*`;
  - testes de browser contra a produção, com as gravações intercetadas: `carteira_browser.cjs`, `setor_browser.cjs`, `manual_browser.cjs`.

**Retorno:**
1. Parar os três serviços.
2. `git diff --name-only c074a8f HEAD | xargs git checkout c074a8f --`.
3. Repor os 3 hard links da mesma forma.
4. Arrancar.

Voltar atrás provoca outro recálculo completo. As máquinas sugeridas gravadas identificam-se por `sector_member_machine.seen->>'origem'='sugerida'`.

## 06/10/2026 (tarde): Carga completa, Gantt por turno e por dia, nomes do CPIS, auditoria

Plano aprovado: `~/.claude/plans/esta-horrivel-n-o-existe-gleaming-clarke.md`. Ponto de partida guardado no commit `6c284b0`. Ativo a 06/10 ao longo da tarde, com 3 reinícios do kanban-planning.

**Só as máquinas do setor.** Novo `app/sector/members.py`: uma máquina é de um setor pela unidade (MTG2/MTG3) e pelo tipo (máquina/posto) do catálogo de recursos. A área dos calendários deixa de contar.
- Usado em `settings.machine_rows`, `family_sets.machines` e `shifts.write` (o calendário fica com o setor da máquina).
- Medição antes da mudança: `scripts/audit_sector_members.py`. Mesmas máquinas nas duas regras; as cantoneiras tinham 467 operações na Soldadura e 91 na Quinadora MTG2.
- Esse trabalho aparece agora como nota (`elsewhere`) no Gantt e na Carga, nunca como linha.

**Gantt por turno e por dia.**
- `app/sector/week.py`: `shift_at` (a madrugada conta para o 3.º turno do dia anterior), `split_by_shift`, `labelled_windows`, `bands`, `hour_ticks`, `day_bounds`. As horas são reais em UTC: 25/10 tem 25 h.
- `board.py`:
  - `_built` com cache e pormenores privados por segmento;
  - `boxes_from_proposal(area=)` filtra o setor e guarda `timed`;
  - cada caixa traz `shifts` (horas por dia e turno);
  - previsões sem horas recebem a estimativa da Carteira (`hours_estimated`);
  - novo `day()` e rota `GET /planeamento/api/setor/quadro/dia?setor&dia&maquina`.
- Ecrã `plano.*`:
  - os dias do cabeçalho são clicáveis (todas as máquinas); a célula abre a máquina nesse dia;
  - eixo 00–24 com faixas dos turnos e totais «N.º turno: planeado / capacidade h»;
  - linha «agora» e faixa «Sem hora marcada»;
  - ◀ ▶, «Voltar à semana», URL `?dia=&maquina=`.

**Carga e turnos com o que Capacidades e Disponibilidade mostravam.** Novo `app/sector/load_sources.py`:
- horas segundo o Excel e peso por linha, a partir de `capacity_items`, escalados ao saldo atual;
- horas reais declaradas e calendário do Excel, a partir de `capacity`;
- cálculo de cada operação.

Os conjuntos `capacity*` juntam os dois setores, por isso filtra-se sempre pela área da linha. `load.py` acrescenta:
- **semana:** `excel_hours`, `actual_hours` e `excel_calendar_hours`;
- **`totals` por máquina:** separador «Máquinas»;
- **novas funções:** `operations()` e `production()`, com as rotas `/carga/operacoes` e `/carga/producao`.

No ecrã ficam os separadores Semanas | Máquinas. O resumo da célula mostra Capacidade · Horas previstas · Horas segundo o Excel · Horas reais declaradas · Peso. Há a lista de operações com «Ver cálculo» e a «Produção registada».

**Páginas antigas e configuração.**
- `/planeamento/capacidades` e `/disponibilidade` redirecionam (302) para a Carga, mas só nesta app. O MES partilha `raw_routes.py`, `capacity.js` (hard link) e `raw_panels.js`, e lá ficam como estavam. Por isso `capacity.*` **não foram apagados**.
- Saíram do menu. Links atualizados em `gantt.html` e `insights.py`.
- **Definições do setor** ganharam:
  - nomes e operações de cada máquina (aliases);
  - «válida desde» e «Arquivar» nas taxas;
  - a secção «Horas reais corrigidas à mão» (`raw/horas/prever` + `raw/objects/worked_hours`).
- **Calendários antigos «só turnos»:** contam pelas horas (`shifts.week_hours`) e `regenerate` não os reescreve. Hoje não existe nenhum (os 624 têm horários).

**Nomes com base no CPIS.**
- Fonte única: `app/web/static/nomes.json` (nome, campo CPIS, coluna Excel, explicação), `app/naming.py` e `static/nomes.js` (explicação no cursor de `[data-nome]`, carregado no menu).
- Trocas feitas:
  - «Designação da obra», «Descrição» e «Obra» → «Descrição da obra»;
  - «Data CPIS · entrega» e «Entrega» → «Data de entrega»;
  - «Tipo de obra», «Família da encomenda (CPIS)» e «Família de Produto (CPIS)» → «Família de Produto»;
  - «Obra / OV» → «OV»;
  - «Fim Produção» → «Fim previsto da Produção»;
  - «Entrou» → «Data de registo».
- Proteção: `tests/test_naming.py` proíbe os sinónimos antigos.
- Nota acrescentada a `regras-confirmadas-2026-09-10.md`: nos dados, «Data Cpis» = data de entrega. Fica por confirmar com o Luís.

**Factos dos dados vistos pelo caminho** (entram no relatório da auditoria):
- As folhas OCR quase não trazem horas trabalhadas: em todo o motor de capacidade só há 18 h, no Serrote Doall na S40.
- 11 724 linhas MTG3 não têm velocidade Mt\h ou comprimento no Excel, por isso não têm «Horas segundo o Excel».

**Testes:**
- `tests/test_sector_shifts.py`: membros do setor, área de casa do calendário, calendários antigos;
- `tests/test_naming.py`;
- `tests/setor_browser.cjs`: dia hora a hora, máquinas do setor, resumo, cálculo, produção, separador Máquinas, redirecionamentos, Definições novas.

**Ambiente:** a pasta `~/.cache/ms-playwright` voltou a desaparecer. Reinstalar com `cd ~/.cache/planeamento-playwright && node node_modules/playwright-core/cli.js install chromium`.

## 06/10/2026: definições do setor, carga e turnos, Gantt semanal e preenchimento manual

Plano aprovado: `~/.claude/plans/esta-horrivel-n-o-existe-gleaming-clarke.md`. **Ativo desde 06/10 ~12:46** (049 aplicada, kanban-planning, kanban-raw-worker e kanban-research-sync reiniciados).

O que há de novo para quem usa:
- **Carga e turnos** (`/planeamento/setor/carga`, menu principal): máquina × 13 semanas. Cada célula tem turnos, capacidade, carga = no plano + a vencer + a vencer na máquina sugerida, − / + turno e a recomendação com «Aplicar». A recomendação para tirar turnos só aparece nas 3 primeiras semanas, porque mais à frente a carga ainda está a chegar. Clicar na célula abre os turnos por dia (− / +) e as OF com horas, peças, metros, prazo e atraso, com ligações para a Carteira e o Gantt dessa semana. O atrasado conta na semana atual.
- **Definições do setor** (`/planeamento/setor/definicoes`, em «Mais»): máquinas (confirmada, turnos padrão, próximas semanas, ficha de capacidades corrigível, taxas Excel/confirmadas), horário dos 3 turnos, dias de trabalho, feriados e regras do setor.
- **Gantt** (`/planeamento/gantt`): uma semana de cada vez (seg a dom), com «planeado / capacidade h» por dia e por máquina. A origem é o plano aceite; sem ele, a proposta automática; sem ela, as previsões.
- **Preenchimento manual**:
  - um só campo OF: escreve-se a OF e vêm OV, cliente, obra, data de entrega, setor e a lista de peças da OF; escolher a peça preenche o resto. Uma OF desconhecida fica como OF nova.
  - A primeira secção tem as colunas do Excel de cada setor (`planning_catalogs.FIRST_SECTION`). Nas cantoneiras, 1.ª/2.ª operação, a designação e a qualidade são lidas da linha do Excel, e não há Abocardar nem Picking.
  - Saiu a «Previsão de requisição de material».
  - Pode-se arrastar um PDF para o formulário: é enviado para os dossiês, mostra as peças lidas e abre a peça escolhida.
- **Ano do Picking deduzido**: o ano em que a semana fica mais perto da Data Corte, ou de hoje quando não há Data Corte (`planning_dates.infer_iso_year`). Em dezembro, a semana 1 é do ano seguinte. Vale no editor, nos cálculos, na RAW e na prioridade: na MTG2 o Picking passa a ser usado. Impacto medido a 06/10: 252 das 1 798 linhas abertas passam da Data Corte para o Picking; 28 mudam de semana.

Técnico:
- Modelo de turnos: `app/sector/shifts.py`. `shift_plan`/`day_shifts`/`manual` ficam dentro dos calendários; o 3.º turno parte-se à meia-noite; um feriado é um dia sem horário.
- Gravação em lote: `objects.save(..., signal=False)` + um único `finish_batch`.
- Feriados aplicados a 06/10 pela própria API: 364 calendários MTG3 + 260 MTG2 reescritos, com histórico. O autor ficou «Utilizador não identificado» porque o pedido foi feito em localhost, sem o Caddy.
- Definições: `app/sector/settings.py` e a tabela `planning_mtg.sector_settings` (049). A regeneração ignora máquinas não confirmadas, porque não podem ter calendário.
- Carga: `app/sector/load.py`. Gantt semanal: `app/sector/week.py`, `board.py` e `service.snapshot(area)`. Ficha local: `resource.definition.capacity_override`, usada em `gantt/machines.py`.
- Espelho: `sector_settings` em `research_sync.APPLICATION_TABLES` e a vista `consulta_v2.definicoes_setor_atuais`.
- Testes:
  - `tests/test_sector_shifts.py` (turnos, feriados, recomendação, mudança de hora, ano do Picking, campos por setor, lote com um só sinal, regeneração);
  - `tests/setor_browser.cjs` (Carga, Definições, Gantt semanal, 390 px; gravações intercetadas);
  - `tests/test_sector_needs.py` (ano deduzido na prioridade).
- Correção à parte: `raw/preview.py` dava 500 quando a referência escrita já existia na OF (datas por serializar).
- Lição: os módulos Python carregados «a pedido» leem o disco. Mudar uma assinatura usada por um módulo ainda não carregado parte o serviço em produção antes do reinício (aconteceu à pré-visualização entre 12:40 e 12:46).

Limites conhecidos:
- Nos dias já passados da semana, a proposta não tem horas.
- As 14 operações seguintes da MTG3 continuam bloqueadas.
- As 6 linhas MTG2 do perfil «80» não têm área de corte, logo não têm horas.
- O PDF demora 15–30 s por página.
- A recomendação da semana atual inclui todo o atrasado; muitas vezes nem 3 turnos chegam, e a página diz isso mesmo.

## 05–06/10/2026: máquina por conjunto de famílias, Gantt fiel à máquina escolhida e correções

**Ativo em produção** (migração 048; reiniciados `kanban-planning`, `kanban-research-sync` e `kanban-raw-worker`). Plano em `~/.claude/plans/esta-horrivel-n-o-existe-gleaming-clarke.md`.

**Máquina efetiva, igual em todo o sistema** (`app/sector/machine_choice.py`):
- **Ordem:** escolha feita na Carteira («Atribuir máquina») → coluna Máquina da Tabela → máquina do conjunto de famílias.
- «Por definir», «Sem máquina», «MTG3» e outros textos do género contam como sem máquina.
- **Quem a usa:** estado, Planear, lista vermelha, números das máquinas, ocorrências, Gantt e quadro.
- Uma linha que só tem a máquina do conjunto fica em «Planeado para nesting» e pode ser planeada.

**Conjuntos de famílias** (página `/planeamento/carteira/conjuntos`, `family_sets.py`):
- grupo de famílias SKU com uma máquina pré-definida;
- cada família está num só conjunto;
- só se aplica à MTG3, porque a MTG2 não tem famílias SKU.

**Atribuir máquina** (`member_machine.py`):
- na frase das linhas marcadas, escolhe-se a máquina e carrega-se em «Atribuir»; vem pré-escolhida a sugestão aprendida;
- fica gravado na aplicação, com histórico; o Excel não muda;
- as linhas continuam marcadas, para se poder carregar logo em Planear.

**Aprender preferências** (`machine_learning.py`):
- **fontes:** escolhas da Carteira (peso 5), máquinas da Tabela e o histórico do Excel (29 429 escolhas ligadas a perfil e referência);
- **contexto:** família+perfil → família+espessura → perfil → família; mínimo de 3 escolhas e 60%;
- **é só sugestão:** nunca atribui;
- entra como primeiro critério da máquina sugerida;
- a 05/10 deu sugestão a 8 931 das 14 400 linhas sem máquina da MTG3.

**Gantt:**
- **Máquina mantida:** a máquina do planeador fica sempre, mesmo fora da ficha de capacidades, sem avisos, e vale como confirmação técnica para a proposta automática.
- **Linhas sem máquina não entram.**
- **Importações novas:** as linhas planeadas já não desaparecem do Gantt depois de uma nova importação (a decisão é procurada pelas chaves antigas).

**Dados (aprovados pelo Luís):**
- **25 decisões antigas sem máquina** limpas (lista em `limpeza-25-2026-10-05.json`).
- **12 máquinas principais** confirmadas.
- **624 calendários horários** (52 semanas desde 2026-W41, seg–sex, turnos de 7,5 h a partir das 06:00):
  - **MTG3**, pelo débito observado: Rapid 20T-1/20T-2/25T e XP T4 2 turnos; XP T6 3; Peddi 8 e Peddi 6 1.
  - **MTG2**, por `PlanDisponibilidadeSemanal`: Disco e MEBA 1; Fita/Thomas 2; Vanguard 3; Doall 1.
  - **Ajustar:** editar os calendários na Tabela / Disponibilidade.

**Resultado:**
- **Proposta automática na MTG3:** coloca as 28 operações principais planeadas. As 14 seguintes (Plasma, Fresadora…) continuam com «compatibilidade técnica», «saldo» e «sequência» por confirmar.
- **MTG2:** as 6 linhas planeadas (perfil «80») não têm área de corte unitária no Excel, por isso não há duração.
- **Validação nos dados reais: 87/87.** Cada linha Planeado está no Gantt e no quadro na mesma máquina que a Carteira; a OF264219 / W061635 fica na Rapid 25T.

**Correções:**
- Planear em grupo e o botão do quadro já não anulam exclusões; o botão do quadro abrange a OF inteira (todas as OV) e só aparece com linhas planeáveis.
- **Pedido repetido** devolve o resultado gravado, mesmo que o grupo tenha mudado.
- **Ecrã da Carteira:**
  - protegido de erros em `renderMarked` e na lupa;
  - tokens atualizados depois de um conflito ou de atribuir;
  - vista guardada em cada linha;
  - ticket na paginação da lupa;
  - aviso «a atualizar as horas».
- Entradas inválidas já não dão erro 500; já não aparecem pendentes falsos; as decisões antigas são comparadas com a referência sem espaços; o código novo entra no carimbo do Gantt.

**Fica por fazer:**
- **Exceções grandes:** a lista de exceções não é comprimida (só pesa em grupos com mais de cerca de 6 000 linhas por marcar).
- **Abrir grupos durante uma mudança de vista:** ainda usa a vista nova.
- **Página Máquinas (desligada):** chaves colididas em `assignments.py`.
- **Operações seguintes:** precisam de regras técnicas para entrar na proposta automática.
- **MTG2:** falta a área de corte unitária.
- **Fora do âmbito:** disco principal em RAID 0, a 90%, sem cópia externa.

## Simplificação pedida pelo Luís (02/10/2026, ao fim do dia)

O Luís achou o primeiro ecrã complexo e desenhou o que quer (esboço em papel). Mudou também a regra: **não há fase nesting/produção**. Ativo desde ~20:40 (migração 047 + reinício).

**Estados (cada linha tem um só):**
1. **Planeado** = Planear e Máquina preenchida;
2. **Planeado para nesting** = tem Máquina, ainda sem Planear;
3. **Sem máquina atribuída** = coluna Máquina vazia (também uma decisão antiga sem máquina).

**Sem máquina não se planeia:** Planear grava só as linhas com máquina e diz quantas ficaram de fora; recusa se nenhuma tiver. Vale também para o botão Planear do quadro do plano.

**Ecrã:**
- uma linha de título;
- filtros em duas linhas: Setor, Família de Produto, Família SKU, Ver por (Perfil por defeito) / Pesquisar, Máquina, Prazo (semanas com caixas), Ordem, Estado, Limpar filtros;
- painéis Punção | Broca | Resumo. Em cada máquina, `metros (+marcados) horas (+marcados)`. A carga é o Planeado; o «+» são as linhas marcadas em nesting dessa máquina. O Resumo tem as colunas Metros, Horas e Marcados (+ no Planeado, − no Nesting, metros marcados sem máquina);
- tabela: caixa, Perfil, lupa e `x/y`; Planear/Limpar com «Planeado: X m»; Metros, Peças, OF, Sem máquina, Em nesting. Por baixo do cabeçalho, uma linha de Subtotal;
- cores: cinzento = marcada; verde = toda em nesting.

**Saiu:** a barra «Planear para», o painel «Outras» (as máquinas fora do catálogo só aparecem numa linha pequena, se tiverem carga planeada), as linhas «com máquina, por planear», Data Corte, a coluna Máquinas, «Como ler» e «Excluir» (o backend mantém a exclusão para o legado).

**Migração `sql/047_member_selection_no_phase.sql`:** retira a coluna `phase` (não havia decisões por membro gravadas). Para voltar atrás: `reverter_046.sql`, sem as linhas que mexem em `phase`.

As secções abaixo descrevem a primeira versão (fase nesting/produção), **substituída** por esta.

## Primeira versão (substituída) — o que mudou para quem usa

- Filtros: Setor, Ver por, Família de Produto (antes «Família da encomenda»), Família SKU, Máquina, **Semana** (várias, com caixas), **Estado** (1. Sem máquina atribuída · 2. Planeado para nesting · 3. Planeado para produção), Pesquisar, Ordenar e **Limpar todos os filtros**. Sinal e Prazo saíram do ecrã (as regras de anulada/Eletrofer/validação/CPIS continuam a funcionar por dentro).
- Vista nova **OF → Perfil**; as outras ficam.
- Cada linha tem caixa de marcar (com `17/18` quando parcial), **Planear**, **Limpar** e a **lupa**. A lupa mostra todos os membros do grupo, um a um, com pesquisa própria, «Marcar todos», «Desmarcar todos» e «Excluir marcados…» (com motivo).
- A marcação é um rascunho desta sessão e deste setor: filtrar, pesquisar, ordenar ou mudar a vista não a altera. Planear/Limpar numa linha gravam só os membros marcados dessa linha; sem nada marcado, o grupo inteiro.
- «Planear para»: nesting (por defeito) ou produção, na barra da marcação.
- Painéis em cima: Punção (XP T4, XP T6, Peddi 6, Peddi 8), Broca (Rapid 20-1, 20-2, 25), «Outras» (inclui XP T7/T8/T9, que não estão no catálogo) e o Resumo por estado. MTG2: um painel com as máquinas da MTG2. Cada máquina: `metros · horas (+acréscimo da marcação)` e, em pequeno, «com máquina, por planear».
- Cores: cinzento = marcado (rascunho); verde = planeado para nesting (só depois de gravado); grupos mistos mostram `Nesting 3/18`.

## Decisões da primeira versão (1, 2 e 3 substituídas pela regra acima)

1. **Origem do nesting:** não existia em lado nenhum (OCR, Excel, CPIS). A fase passou a ser gravada **com a própria decisão Planear** (campo `phase`), sem botão nem envio separados. Se a fábrica tiver outra fonte de verdade para «já está em nesting», é só trocar a origem em `planning_status.py`.
2. **Produção** = Planear com fase produção **e** máquina efetiva, ou decisão antiga (anterior à fase) com máquina — é o que o Gantt já recebe. Sem máquina, Planear não chega para produção.
3. **Carga atual de cada máquina (B)** = trabalho com Planear **e** máquina efetiva (o que entra no Gantt). O trabalho com máquina no Excel mas sem Planear aparece à parte («com máquina, por planear»), para não esconder os 18 km da Peddi 8.
4. **Acréscimo** = membros marcados ainda não planeados que já têm máquina efetiva. Membros sem máquina aparecem como «sem máquina, fora das máquinas», com a máquina sugerida só como indicação. Aceitar sugestões continua no fluxo próprio (Tabela / Máquinas).
5. **Identidade de um membro** = linha da carteira (`row_key`). Essa chave muda a cada importação do Excel; a decisão é reencontrada pelos `selection_aliases` que a projeção já guarda para identidades físicas únicas. Linhas novas nunca herdam uma decisão; decisões sem correspondência ficam listadas como «por rever» no âmbito do Gantt.
6. **Legado:** as 34 decisões antigas por OF/referência ficam como estão e continuam a valer; a decisão do membro tem precedência. Novas ações só gravam por membro (nunca mais `*`). Limpar um membro coberto por uma decisão antiga grava uma desmarcação explícita. O botão Planear do quadro do plano continua a funcionar (grava os membros exatos da OF).

## Ficheiros

- Base de dados: `sql/046_sector_member_selection.sql` (tabela de decisões por membro, pedidos idempotentes, eventos com membro/fase). Reversão ensaiada: [reverter_046.sql](reverter_046.sql).
- Regras: `app/sector/decisions.py` (precedência), `planning_status.py` (três estados), `portfolio_kpis.py` (carga, acréscimo, resumo), `portfolio.py` (semanas, OF → Perfil, membros, contagens, subtotal), `selection.py` (Planear/Limpar exatos, conflitos, idempotência).
- Gantt e dependências: `scope.py`, `gantt/integrated.py`, `gantt/inputs.py`, `occurrences.py` passam a ler as decisões por membro; o selo do Gantt só muda quando existir a primeira decisão por membro (cenários atuais não ficam desatualizados com a instalação). Espelho: `raw/research_sync.py` + vista `consulta_v2.selecao_planear_membros_atual` em `sql/integration/research_sector_decisions.sql`.
- Ecrã: `templates/carteira2.html`, `static/carteira2.{js,css}` (os antigos `carteira.*` foram apagados; cópia em `~/.local/state/planning-carteira-membros/antes-20261002/`).
- APIs novas: `GET /planeamento/api/carteira/membros`, `POST …/contagens`, `GET …/kpis` (só aceita o setor), `POST …/previsao`; `GET /planeamento/api/carteira` aceita `vista=of_perfil` e `semanas=` (várias) e devolve `list_totals` (o antigo `totals` continua igual); `POST …/selecao` aceita `membros` (chave + token) ou `grupo` (com selo e exceções).

## Testes

- `tests/test_sector_selection.py` (PostgreSQL descartável com 039/040/046): 17 de 18 gravados e iguais aos do Gantt; colisão OF/referência com perfis diferentes; decisão herdada `*` + Limpar; conflito sem escrita parcial; pedido repetido; mesmo pedido com outro conteúdo recusado; grupo de 1 200 membros com selo; reimportação por alias; produção exige máquina.
- `tests/test_sector_carteira.py`: semanas na viragem 2026/2027; OF → Perfil e subtotal com OF distintas; total do grupo vs. visíveis; filtro Estado; carga/acréscimo/horas por ocorrência; máquinas fora do catálogo; KPIs iguais com qualquer filtro.
- `tests/carteira_browser.cjs` contra dados reais (gravação intercetada): lupa 236/237, Escape devolve o foco, filtros e «Limpar todos os filtros» não mexem na marcação nem na carga, semanas múltiplas, Planear envia só os membros marcados com a fase, 390 px sem scroll horizontal.
- `tests/integrated_gantt_browser.cjs`: Carteira → Planear → Gantt → máquina → excluir na lupa → sai do Gantt.

## Ativar (feito a 02/10/2026)

1. Aplicar a migração: `.venv/bin/python scripts/migrate.py apply`
2. Reiniciar o serviço: `systemctl --user restart kanban-planning`
3. Reiniciar o espelho quando conveniente: `systemctl --user restart kanban-research-sync` e aplicar `sql/integration/research_sector_decisions.sql` na base de pesquisa.
4. Confirmar: abrir `/planeamento/carteira`; correr `CARTEIRA_BASE=http://127.0.0.1:8113 node tests/carteira_browser.cjs`.
5. Apagar `templates/carteira.html` e `static/carteira.{js,css}`.

Retorno: repor os ficheiros anteriores do git, reiniciar o serviço e, se for preciso, correr `reverter_046.sql` (apaga as decisões por membro; exportar antes).

## Pendente de produto

- Legenda da última métrica manuscrita do resumo: a API já dá metros, horas, peças, OF e linhas por estado.
- Uma decisão de máquina feita na página Máquinas conta para a carga (via ocorrências), mas o estado «Sem máquina atribuída» olha para a coluna Máquina da Tabela. Hoje não há nenhuma dessas decisões gravadas (0), por isso não há diferença.
- As horas do trabalho sem máquina são desconhecidas por definição; mostra-se à parte a estimativa nas máquinas sugeridas.
