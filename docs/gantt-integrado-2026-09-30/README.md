# Gantt integrado MTG2/MTG3 e escolha de máquinas

Implementação de 30/09/2026 no projeto `planeamento`, ramo `codex/automatic-machine-planning`.

Ativada na aplicação local em `http://127.0.0.1:8113`: migração 041 aplicada, primeira versão publicada com 39.477 ocorrências documentais, 29 identidades de recursos e timer horário ligado. A consulta seguinte conservou a mesma versão, sem duplicar linhas. A seleção real permanece vazia e o Gantt apresenta zero operações até o utilizador marcar **Planear**. Não existem recursos/calendários horários confirmados nesta configuração; a ligação direta à fábrica não foi configurada.

## Fluxo de utilização

1. Criar ou atualizar a informação de planeamento na aplicação. Dados incompletos podem ser guardados, mas conservam as suas pendências.
2. Na **Carteira**, escolher o setor e marcar o trabalho com **Planear**. A decisão específica OF/referência prevalece sobre a decisão para toda a OF; uma exclusão explícita é respeitada.
3. O **Gantt** recebe apenas a interseção entre essa seleção e a informação de planeamento atualmente ativa. Uma OF aberta na CPIS, uma máquina escrita no Excel ou uma sugestão documental não acrescentam trabalho ao cenário.
4. Abrir a operação para ver máquina de origem, sugestão, decisão aceite, alternativas e condições. Escolher **Automático**, fixar apenas a máquina com motivo, ou **Voltar ao automático**. A fixação horária tem controlo próprio.
5. **Gerar proposta** calcula toda a seleção do cenário; filtros e paginação da interface não limitam o cálculo. **Aceitar proposta** conserva a aceitação explícita existente. Alterar apenas a máquina guarda a decisão sem iniciar um cálculo automaticamente.

Uma operação selecionada pode ficar **bloqueada**: a seleção autoriza a sua inclusão, mas não confirma saldo, compatibilidade, duração ou calendário. A conclusão da operação principal conserva as operações seguintes pendentes. A seleção real do utilizador não é alterada por importações ou testes.

## Base comum e versões

- `app/sector/scope.py` concentra a seleção e a correspondência com a informação atual da aplicação. Linhas novas ou revistas da aplicação funcionam antes da próxima importação da fábrica.
- `app/gantt/research.py` lê a cópia `dataresearchmtg_planeamento_20260930` numa transação consistente, exclusivamente de leitura. Consultas em conjunto substituem consultas sequenciais por OF.
- A migração `041_integrated_machine_planning.sql` cria versões imutáveis, linhas congeladas e um ponteiro para a última versão utilizável no armazenamento da aplicação. Publicação idempotente, transacional e com bloqueio de concorrência.
- A identidade da ocorrência inclui setor, OF, origem, ocorrência, código de operação e identidade técnica/revisão. Operações repetidas não partilham decisões. A transferência entre versões exige correspondência técnica única.
- Recursos físicos recebem uma correspondência explícita e comum aos setores. Correspondências ambíguas ficam pendentes. Equipamento, posto e operadores têm papéis diferentes.
- Carteira, projeção RAW, Gantt e carga reutilizam saldos por operação. Contadores Excel e OCR divergentes não são combinados pelo máximo. Reconciliado, documental e desconhecido continuam distintos.
- Alterar geometria, quantidade, qualidade ou rota impede reutilizar a variante antiga como confirmação técnica. Alterar a máquina principal não atribui essa máquina às operações seguintes.
- As possíveis duplicações entre setores continuam como casos de revisão, sem consolidação automática.

## Atribuição e regras

`app/gantt/machines.py` reúne capacidades, rota, recurso existente e histórico compatível. Cada alternativa conserva elegibilidade (**admissível**, **condicional**, **excluída**), condições, origem e evidência. O histórico documental e a produção MES são apresentados separadamente; contagens de outras OFs não confirmam elegibilidade técnica.

Regras técnicas confirmadas são versionadas no recurso, com âmbito de variante/revisão ou perfil/qualidade, operação, autor e motivo. O menu permite confirmar condições com evidência. A condição de mercado nacional da Peddi 6 exige âmbito da OF e não se transfere para outros clientes. São explícitas a confirmação dos três diâmetros da XP T6 e a alteração 112→119. As preferências de equipa de Perfis são documentais. Não existe um limiar inventado de lote para MEBA.

Trabalho iniciado conserva a máquina da execução. Escolhas manuais incompatíveis ou sem correspondência bloqueiam a aceitação. Sem calendários e durações comparáveis, a sugestão é documental, estável, com condições e desempate explicado. Havendo comparação utilizável, prazo e estabilidade participam na escolha e na otimização.

## Calendarização e gestão

- Contrato v2 com `areas`, identidade da ocorrência, várias predecessoras, versões das fontes e duração por alternativa. Leitura dos cenários antigos mantida.
- Hierarquia de duração: taxa confirmada aplicável → histórico com horas e produção correspondentes → estimativa documental identificada. Taxas MTG3 positivas são lidas da fonte; unidades ou âmbitos incompatíveis mantêm duração desconhecida. O fator legado Thomas ×3 não justifica uma mudança de máquina.
- Vanguard, Quinadora e outros recursos comuns têm uma única ocupação física. Os dois operadores do pav.1 são modelados num calendário comum, com consumo nos segmentos efetivos de trabalho. Postos e equipamentos não somam capacidade duplicada.
- Dependências múltiplas, repetições, trabalho bloqueado e trabalho fora do horizonte são conservados. Validação independente verifica sobreposições, capacidade partilhada, precedências, calendários, vigência das taxas e fixações.
- A proposta determinística validada fica disponível antes da otimização. O motor conserva a melhor proposta validada, com orçamento de 30 segundos.
- Horizonte inicial de 12 semanas, configurável, em Europe/Lisbon. Lotes inteiros; não se inventa uma regra de divisão.
- `weekly.py` oferece previsão semanal apenas com orçamento sustentado e unidades compatíveis. As previsões documentais/condicionais têm identificação própria e não criam horas fictícias de execução.
- `insights.py` apresenta cobertura, carga estimada e fila de pendências por urgência e trabalho conhecido. Produtividade observada usa grupos completos de produção/horas, com mediana, quantis, amostra, período e exclusões. A avaliação temporal reserva OFs posteriores e elimina essas OFs do treino. Histórico sem datas demonstráveis não entra nessa avaliação.
- Fontes, configuração, decisões, alternativas, estimativas e resultados ficam congelados em cada execução. Mudanças durante o cálculo ou antes da aceitação são detetadas; trabalho manual e iniciado é preservado.

## Atualização e ativação

Configuração independente da ligação principal da aplicação:

```dotenv
MES_PLANNING_SELECTION_ENABLED=1
MES_PLANNING_V2_ENABLED=1
MES_PLANNING_V2_DATABASE=dataresearchmtg_planeamento_20260930
MES_PLANNING_V2_ACCESS_FILE=/caminho/privado/copy-access.json
```

Alternativamente, usar `MES_PLANNING_V2_DSN`. O ficheiro de acesso e as credenciais não pertencem ao repositório. A leitura rejeita uma base de destino diferente da configurada.

Aplicar a migração 041 e publicar a primeira versão antes de ativar. Comandos no diretório do projeto:

```bash
.venv/bin/python scripts/migrate.py apply --dry-run
.venv/bin/python scripts/migrate.py apply
.venv/bin/python -m app.gantt.research --check
.venv/bin/python -m app.gantt.research
systemctl --user restart kanban-planning.service kanban-raw-worker.service
```

O timer `planning-research-refresh.timer` consulta a camada documental de hora a hora. Uma falha conserva a última versão utilizável, indica o erro e mantém visível a data das fontes. A data de consulta não transforma a fotografia antiga em dados recentes da fábrica.

`app/gantt/cpis_tables.py` acrescenta uma importação coerente de dez tabelas CPIS necessárias às OFs escolhidas: OFs, linhas, componentes, ocorrências de operação, peças, artigos, gamas, linhas de gama, catálogo de operações e planeamento. Usa ligação opcional `MES_PLANNING_CPIS_DSN` e esquema `MES_PLANNING_CPIS_SCHEMA=dados`; permanece desligada enquanto a origem não estiver configurada. Unidades dos tempos, códigos de máquina e estados numéricos são conservados sem interpretações inventadas. Alterações de rota tornam-se pendências de revisão.

A integração `app/raw/research_sync.py`, desenvolvida em paralelo, publica a informação da aplicação em `origem_v2.aplicacao_*`. O adaptador do Gantt continua a cruzar a camada canónica com a informação atual da aplicação e não depende de essa publicação já ter ocorrido para usar um registo novo.

Para reverter a utilização do contrato v2, definir `MES_PLANNING_V2_ENABLED=0`, reiniciar aplicação/worker e parar o timer. As versões e decisões guardadas permanecem disponíveis. A seleção obrigatória continua ligada através do seu próprio sinalizador. Nenhum rollback elimina tabelas ou versões.

## Verificação

Ensaios em PostgreSQL descartável e browser cobrem seleção obrigatória, informação ausente, exclusões específicas, registos novos, escolha só da máquina, persistência, retorno ao automático, regras técnicas, trabalho iniciado, operações repetidas, mudança 112→119, unidades/saldos desconhecidos, partilha de operadores, importação idempotente, correção de fontes, falha de conector, mudança de fontes durante o cálculo e aceitação do Gantt anterior.

Foram verificados 105 casos distintos. A verificação principal terminou com **100 testes aprovados** (139,71 s), incluindo dois percursos no browser. A conferência posterior acrescentou regressões para correspondências entre importações, produção parcial, metadados de publicação, tipo de material e operações sem código; as verificações dirigidas passaram. Foram também verificados a sintaxe Python/JavaScript e o diff. Três testes de browser de outras funcionalidades ficaram fora deste conjunto.

Para repetir a verificação principal em bases descartáveis, desligar os sinalizadores de utilização por defeito no processo de teste; as fixtures da integração ativam v2 de forma controlada:

```bash
MES_PLANNING_V2_ENABLED=0 MES_PLANNING_SELECTION_ENABLED=0 .venv/bin/python -m pytest -q \
  tests/test_integrated_gantt.py tests/test_sector_portfolio.py tests/test_sector_selection.py \
  tests/test_planning_gantt.py tests/test_gantt_source_plan.py \
  tests/test_planning_productivity.py tests/test_raw_workspace.py \
  -k 'not browser or test_browser_selection_manual_automatic or test_gantt_browser_generate_accept_and_reopen'
```

A evidência de utilização local está em [verificacao-local.json](verificacao-local.json) e [gantt-local-selecao-vazia.png](gantt-local-selecao-vazia.png); o menu foi exercitado com dados sintéticos em [menu-maquinas-ensaio.png](menu-maquinas-ensaio.png).

Os três casos reais pedidos foram reproduzidos em leitura, com seis ocorrências em conjunto:

- OF265844/CDPTM001: saldo principal zero e alternativas documentais; histórico Peddi 8 não confirma ferramentas, desenho ou revisão.
- OF266558/DLR477D: estado documental divergente, principal 119 e segunda operação 111 com saldo desconhecido.
- OF264754/CI5221A4006: variantes conservadas e abocardar separado da operação principal.

Os resultados, condições e identificação das fontes estão em [casos-verificados.json](casos-verificados.json). Estas OFs não foram marcadas para Planear na base real.

A calendarização real exige que o utilizador escolha trabalho, confirme as condições técnicas necessárias e forneça taxas/calendários ou orçamentos utilizáveis. A atualização direta da fábrica exige a ligação CPIS configurada. Estes requisitos de dados permanecem visíveis na aplicação.
