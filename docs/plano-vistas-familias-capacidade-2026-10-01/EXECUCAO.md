# Execução do plano de vistas por família e capacidade — 1 de outubro de 2026

Implementação no ramo `codex/automatic-machine-planning`, por cima do trabalho ainda não gravado do Gantt integrado (copiado antes de começar para `~/.local/state/planning-vistas-familias/antes-20261001/`). **Nada foi ainda ativado no serviço real**: a migração 045 não está aplicada, o interruptor está desligado e as classificações MTG2 não foram instaladas. Ver «Ativação» no fim.

## O que ficou feito, por etapa do plano

| Etapa | Estado | Onde |
| --- | --- | --- |
| 1 Base comum e datas | Feita | `app/sector/priority.py`, `app/sector/occurrences.py`, `app/gantt/{integrated,inputs,solver,validation}.py`, `app/sector/portfolio.py` |
| 1 Famílias SKU MTG2 | Análise feita; instalação à espera de autorização | `docs/familias-sku-mtg2-2026-10-01/` |
| 2 Árvore e conjuntos | Feita | `app/sector/tree.py`, `app/sector/sets.py`, `app/sector/needs_view.py`, `app/web/static/needs.{js,css}` |
| 3 Máquinas por grupo | Feita | `app/sector/assignments.py` (lido pelo Gantt em `integrated.py`) |
| 4 Capacidade e persistência | Feita; percentagens à espera de calendários | `app/sector/capacity.py`, `app/gantt/weekly.py`, `app/raw/research_sync.py`, `sql/045_*.sql`, `sql/integration/research_sector_decisions.sql` |
| 5 Recuperação de atraso | Parcial: medição feita, objetivo do motor por mudar | `app/gantt/backlog.py` |
| 6 Horizonte longo | Parcial: procura até 52 semanas | `app/sector/tree.py` (`periods`), `capacity.py` |

### Prazos (secção 7)

- Um só resolvedor por setor. **MTG3: Data Corte**, avaliada como conclusão da operação principal até ao fim do dia em Lisboa. Sem Data Corte fica «prioridade sem data»; nunca se preenche com o Picking.
- **MTG2: Picking com ano confirmado**, depois Galvanização e Data Corte (continuidade). O Picking sem ano só entra se a política do setor aceitar um ano assumido — é uma escolha registada, não automática. Hoje nenhuma linha MTG2 tem ano de Picking, por isso a MTG2 está, na prática, pela Data Corte.
- Operações seguintes guardam o seu marco (Galvanização); não herdam o prazo de corte.
- Substituição por OF ou OF × referência, com motivo, revisão e histórico; a chave inclui o setor.
- O motor e o verificador avaliam o mesmo objetivo: Picking pela OF inteira **no seu setor**; Data Corte por operação. Cenários antigos mantêm o significado com que foram calculados.
- A Carteira usa a mesma regra para a janela de prazo e ganhou o filtro «Família SKU», separado da «Família da encomenda (CPIS)».

### Base de operações, árvore e conjuntos (secções 4 e 5)

- Uma linha por ocorrência de operação de **todo** o trabalho ativo, escolhido ou não, com a mesma identidade do Gantt (`v2:…`).
- Árvore com cinco vistas (Famílias, Perfis, Conjuntos, Máquinas, Encomendas) e níveis escolhidos; filtros por família, máquina, conjunto, pendências e pesquisa (OU dentro do filtro, E entre filtros); totais sobre toda a população; paginação dos filhos; detalhe da ocorrência com fontes, rota, alternativas, horas e histórico.
- Peças e metros contam uma vez por item; horas somam por ocorrência; OF e referências recontadas em cada grupo.
- Conjuntos congelados (lista colada ou grupo congelado) e dinâmicos (filtro guardado), com revisões. A referência literal é a identidade; desconhecidas ficam pendentes.
- M1: a vista explica «181 linhas no histórico; 0 ativas», fechadas pela macro, estado CPIS «Em Produção».

### Máquina por grupo (secção 6)

- Pré-visualização no servidor: por máquina, quantas ocorrências são admissíveis, condicionais, excluídas ou sem alternativa; depois, para a máquina escolhida, o resultado ocorrência a ocorrência.
- Modos: atribuir, preferir, voltar ao automático, preferência futura (referência, conjunto congelado, família SKU ou grupo de perfis, com vigência). Desfazer cria nova revisão e não mexe em ocorrências alteradas depois.
- Uma ação de família não substitui uma decisão mais específica. Trabalho iniciado conserva a máquina. Uma decisão nunca passa para outra variante técnica.
- O Gantt aplica: iniciado → escolha do cenário → decisão da ocorrência → preferências por especificidade → automático. Atribuição incompatível bloqueia com motivo; preferência incompatível volta ao automático com explicação; preferências em conflito ficam visíveis.

### Capacidade e atraso (secções 8 a 11)

- Gráfico por setor abaixo do Gantt: procura conhecida por prazo, empilhada por família (cor fixa por família), ocupação do plano aceite ou de uma proposta, capacidade confirmada como traço; «?» quando por confirmar. Vista em tabela e lista de máquinas.
- Postos compostos e operadores não somam horas-máquina; filas funcionais e destinos não entram. Recurso usado pelos dois setores sem quota fica na faixa «Partilhada»; quotas por setor com soma ≤ 100%.
- Painel de 14 dias por setor: atraso + prazo na janela → entradas (sem previsão) → conclusão prevista pelo plano aceite → saldo → capacidade → défice. Desconhecidos ficam como desconhecidos.
- A simulação semanal passou a reservar semanas consecutivas para um lote longo, sem o dar por concluído na primeira semana e sem o partir por semanas não seguidas.
- Cada proposta do Gantt mede agora o atraso concluído em 14 dias com horas de referência congeladas, comparado com a sequência inicial.

### Base de pesquisa e ontologia (secção 12)

O espelho publica também a seleção «Planear», políticas, substituições, conjuntos, decisões e preferências de máquina, quotas, configuração (recursos, calendários, taxas, cenários) e os planos aceites com os seus segmentos. `sql/integration/research_sector_decisions.sql` cria as vistas `consulta_v2.*_atuais`, `planos_aceites_segmentos` e liga tudo à ontologia (`kg_nos`/`kg_relacoes`). «Planeada na máquina X» nunca passa a «produzida».

## O que os dados reais mostram (leitura de 1/10/2026)

| Medida | MTG2 Perfis | MTG3 Cantoneiras |
| --- | ---: | ---: |
| Ocorrências ativas (principal + seguintes) | 1 191 | 22 591 |
| Horas principais conhecidas | 1 454,40 h | 1 854,10 h |
| Procura já em atraso (horas conhecidas) | 1 056,64 h | 801,97 h |
| Ocorrências sem máquina | 441 | 19 540 |

M2: 395 referências, 3 OF, 68,73 h conhecidas, 99% de cobertura das horas nas linhas principais com saldo. Todas as alternativas de máquina da MTG3 aparecem **condicionais** (graminho, ferramentas e desenho por confirmar) — por isso uma atribuição em grupo fica gravada, mas o Gantt só a calendariza depois de confirmadas as condições. Não há nenhum calendário confirmado: todas as percentagens ficam «por confirmar».

Famílias SKU MTG2: 3 853 referências; só 6 famílias com evidência forte (H92, PA3, PA30, PA31, PA5, PA51); 461 códigos de modelo/projeto e 338 candidatas por confirmar (por exemplo CI7712, presente em 451 OF). Nenhuma foi dada como confirmada.

Tempos medidos com os dados reais: árvore 0,35 s, abrir um grupo 0,30 s, capacidade a 52 semanas 0,38 s, menu de máquina 0,11 s. Depois de uma mudança de dados ou decisões, a base é refeita em cerca de 8 s em segundo plano; entretanto a vista mostra a versão anterior, assinalada.

## Verificação

- 21 testes de regras e medição de atraso (`tests/test_sector_needs.py`), 9 com PostgreSQL descartável e migração 045 (`tests/test_sector_decisions_db.py`), 3 de integração com o Gantt (`tests/test_sector_gantt_integration.py`).
- Bateria alargada: 150 testes aprovados (Gantt, Carteira, seleção, famílias, integração de dados, produtividade, RAW).
- Ensaio com os dados reais só em leitura e capturas da interface numa instância temporária (porta 8123, já parada), sem gravar nada.
- SQL da ontologia aplicado duas vezes numa cópia descartável do esquema da base de pesquisa: sem duplicar nós; vistas e relações conferidas com dados sintéticos publicados pelo próprio espelho.

```bash
RUN_PG_INTEGRATION=1 MES_PLANNING_V2_ENABLED=0 MES_PLANNING_SELECTION_ENABLED=0 .venv/bin/python -m pytest -q \
  tests/test_sector_needs.py tests/test_sector_decisions_db.py tests/test_sector_gantt_integration.py \
  tests/test_integrated_gantt.py tests/test_sector_portfolio.py tests/test_sector_selection.py \
  tests/test_planning_gantt.py tests/test_gantt_source_plan.py tests/test_sku_families.py tests/test_data_integration.py -k 'not browser'
```

Os testes de browser antigos (`*.cjs`) apontam para um Playwright que já não está na cache do npm; ficaram por correr.

## O que ficou por fazer, e porquê

1. **Calendários e taxas atuais** — sem eles não há denominador nem calendarização ao minuto. É trabalho de dados do planeador, não de código.
2. **Objetivo do motor para 14 dias** (etapa 5): a medição existe; mudar a ordem dos objetivos só faz sentido com calendários confirmados para a comparar com dados.
3. **Previsão de entradas e materiais** (etapa 6): não há histórico de chegadas nem stocks ligados; a vista diz «sem previsão de entradas» em vez de inventar.
4. **Coluna de prazo na RAW**: a RAW é partilhada com o MES por ligação; mudar lá exige coordenação.
5. Ordenar os níveis da árvore por arrastar: hoje segue a ordem da lista de dimensões.

## Ativação (precisa de autorização)

1. `.venv/bin/python scripts/migrate.py apply --dry-run` e depois `apply` (migração 045, só tabelas novas).
2. Opcional: instalar as candidatas MTG2 — `.venv/bin/python -m app.raw.sku_families --area perfis --analysis docs/familias-sku-mtg2-2026-10-01` (faz o RAW recalcular os Perfis).
3. Na base de pesquisa, numa transação: `sql/integration/research_sector_decisions.sql`.
4. Ligar `MES_PLANNING_FAMILY_VIEWS_ENABLED=1` no suplemento do `kanban-planning.service` e reiniciar `kanban-planning.service` e `kanban-research-sync.service`.

Reverter: desligar o interruptor e reiniciar. As tabelas e decisões ficam; nada é apagado. A política de prazo da MTG3 pela Data Corte vale assim que o código novo for carregado, mesmo com o interruptor desligado (é a regra aprovada no plano).

## Atualização — estudo de capacidade e reforço do algoritmo (1/10/2026, tarde)

Ver [docs/capacidade-maquinas-2026-10-01/README.md](../capacidade-maquinas-2026-10-01/README.md). Em resumo:

- a capacidade passa a ter cenários identificados (débito executado da MTG3, disponibilidade declarada da MTG2, só confirmada);
- as horas em falta são estimadas e as máquinas em falta são sugeridas, sempre separadas do que é documental ou decidido;
- o menu de máquinas ganhou «Aceitar as sugestões»;
- o Gantt tem melhores desempates;
- a vista mostra o recurso limitante de cada setor.

A migração 045 ganhou o modo de ação `accept_suggestions`; continua por aplicar.

Bateria: 163 testes aprovados.

## Página «Máquinas» e ativação (1/10/2026, noite)

**Página nova `/planeamento/maquinas`**, com quatro separadores:
- **Carga por máquina:** semanas de trabalho e marca do «depois do equilíbrio».
- **Sugestões de máquina:** por lote; «Aceitar», «Outra máquina…» ou várias de uma vez.
- **Equilibrar carga:** mudanças propostas da fila mais longa para máquinas com folga e capacidade técnica; muda só a máquina, nunca retira trabalho.
- **Histórico:** com «Desfazer».

Cada gravação é uma única ação, que se pode desfazer. Código em `app/sector/workbench.py` e no modo `assign_each` das decisões de máquina.

Correção: o leitor de perfis aceita «L40xx40x3» (grafia da ficha). Antes, muitas peças apareciam com «perfil por interpretar».

**Ativação:**
- [x] Migração 045 aplicada na base da aplicação.
- [x] `sql/integration/research_sector_decisions.sql` aplicado na base de pesquisa, com leitura para `mtg_planeamento_20260930`. As definições anteriores de `kg_nos`/`kg_relacoes` estão em `~/.local/state/planning-vistas-familias/antes-20261001/research-kg-views-antes.sql`.
- [ ] Interruptor e reinício (bloqueado ao assistente por ser implantação; correr à mão):

```bash
cp deploy/kanban-planning.service.d/family-views.conf ~/.config/systemd/user/kanban-planning.service.d/
systemctl --user daemon-reload
systemctl --user restart kanban-planning.service kanban-raw-worker.service kanban-research-sync.service
```

Bateria: 166 testes aprovados.

## Aspeto visual e ensaio do fluxo (1/10/2026, fim do dia)

- **Menu único** em todas as páginas do planeamento: `app/web/templates/_app_nav.html` + `app/web/static/planeamento_ui.css`
  (cabeçalho escuro, «Mais» para Capacidades, Disponibilidade, PDF, Manual e OCR; títulos com hierarquia; foco visível).
  Os botões próprios de cada página (abas dos PDFs, Fichas, Fontes, vistas da área) ficam numa linha de ações por baixo, com os mesmos ids.
- Cada ligação só aparece com a página ligada: `app/web/templates_env.py` dá `raw_enabled`, `selection_enabled` e `views_enabled`
  a todos os routers. «Máquinas» só aparece depois do reinício com `MES_PLANNING_FAMILY_VIEWS_ENABLED=1`.
- Tabela e Capacidades ocupam o ecrã em coluna (`body.pl-fill`); o Gantt tem um índice fixo das secções.
- Telemóvel: menu desliza na horizontal, item atual centrado, «Mais» abre por cima.
- **Ensaios:** 904 testes + 11 de browser passam. Os 55 testes de browser tinham caminhos fixos para um Playwright/Chromium
  que já não existiam; agora usam `tests/playwright_core.cjs` (procura em `PLAYWRIGHT_CORE`, `node_modules` ou `~/.cache/planeamento-playwright`).
- **Máquinas no browser** (`tests/sector_machines_browser.cjs`, opcional via `PLANNING_MACHINES_BROWSER_BASE`): com os dados reais,
  aceitar 2 lotes, escolher outra máquina, equilibrar e desfazer enviam o pedido certo; as gravações são intercetadas no browser (0 ações na base real).
- **Auditoria de dados** (só leitura): carga de cada máquina no painel = soma das horas das suas ocorrências; semanas = carga ÷ capacidade;
  sugestões nunca em trabalho que já tem máquina; propostas de equilíbrio nunca mexem em trabalho iniciado nem decisões gravadas;
  totais da Carteira = ocorrências (MTG2 75,8 km, 12 % sem máquina; MTG3 363,5 km, 81 % sem máquina). 0 falhas.
