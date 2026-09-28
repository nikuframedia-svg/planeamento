# Picking automático e ordem do formulário — 25/09/2026

O formulário passa a apresentar **OF/OV → Dados da peça → Características de corte**. Em Perfis, a semana de Picking é recuperada automaticamente pela OF, mesmo quando se cria uma peça sem ligação a uma linha Excel. A data correspondente aparece no formulário e na coluna **Data de Picking** do RAW.

A fonte continua a guardar semanas: a data é calculada com a política existente (segunda-feira da semana ISO; ano 2026 assumido se desconhecido). O campo factual `picking_year` permanece vazio quando não há confirmação. A pré-visualização mostra a origem, as linhas da folha Picking e a indicação de ano assumido. Não substitui Data Corte nem a entrega CPIS.

## Correções

- `planning_dates.picking_values()` centraliza a seleção efetiva. Distingue sugestões importadas de decisões manuais e conserva conflitos.
- A projeção RAW resolve Picking pela OF da necessidade, incluindo registos locais. Campos vazios guardados por formulários antigos já não apagam a recuperação pela OF. Uma decisão manual explícita prevalece; `clear` explícito continua a ser respeitado.
- A pré-visualização utiliza a mesma seleção. O formulário não envia os valores automaticamente apresentados como se fossem decisões manuais. Assim, uma atualização da folha Picking continua a chegar ao RAW.
- `picking_date` é uma coluna calculada de tipo data, com regra e evidência. Surge nas colunas predefinidas de Perfis. Vistas personalizadas mantêm a seleção de colunas; a nova coluna pode ser ativada em Colunas.
- Incrementados contratos de projeção, cálculos e capacidade para reconstruir resultados antigos.

## Validação

Comando:

```sh
uv run pytest -q tests/test_planning_picking_automatic.py tests/test_planning_integral_registration.py tests/test_planning_capacity_preview.py tests/test_planning_gantt.py -x --tb=short
```

**36 testes passaram**, incluindo PostgreSQL descartável e navegador. [Saída dos testes](tests.txt).

Casos cobertos: nova peça sem linha Excel; publicação no RAW; edição de outro campo; alteração da semana na fonte; conflito de semanas; prevalência de decisão manual; limpeza explícita; gravação sem transformar preenchimento automático em decisão; reabertura; regressões de capacidades e Gantt.

Validação no Cloudflare, sem guardar registos operacionais:

```sh
node docs/picking-automatico-2026-09-25/check-public.cjs
```

OF265270 recupera **W34 → 17/08/2026**. Ao mudar para uma OF sem Picking, o formulário retira o valor anterior. Layout confirmado também a 390 px. As linhas ativas publicadas têm **311 semanas e 311 datas de Picking**. Nenhum erro JavaScript/HTTP no ensaio público. [Resultado público](public-results.json), [formulário](manual-public.png), [mobile](manual-mobile-public.png).

Reiniciados apenas `kanban-planning.service` e `kanban-raw-worker.service`. Não foram alterados contadores de produção, fontes importadas ou registos manuais operacionais pelos ensaios. Não há migrações SQL novas.
