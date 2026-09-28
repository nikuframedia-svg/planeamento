# Gantt de Perfis — execução e validação

## Âmbito

Implementado no projeto independente `planeamento` (porta 8113). O Gantt trata corte e abocardar de Perfis por linha técnica e operação. Material, stock, reservas de material e respetivas datas não entram na calendarização. A ausência de um calendário horário confirmado mantém a operação visível como pendência. Nenhum contador MES, Kanban ou da macro é escrito pelo Gantt.

O algoritmo combina sequência inicial determinística e otimização CP-SAT com intervalos opcionais por máquina, precedências, `NoOverlap` e um eixo de minutos úteis por recurso. A proposta final passa por um validador que não chama o solver. O orçamento de otimização é de 30 segundos; um resultado `FEASIBLE` não é apresentado como ótimo global. Referências de modelação: [job shop](https://developers.google.com/optimization/scheduling/job_shop), [flexible job shop](https://github.com/google/or-tools/blob/stable/examples/python/flexible_job_shop_sat.py), [estados CP-SAT](https://developers.google.com/optimization/cp/cp_solver).

## Reconciliação

O relatório [reconciliation-before-after.json](reconciliation-before-after.json) compara, na mesma transação de leitura, a geração publicada antes da atualização com o recálculo pelo código novo. Na fotografia de 24/09/2026: 1.139 linhas ativas, 1.025 com Data Corte, 59 Picking publicados antes, 311 recuperados pelo cálculo novo. São 252 linhas adicionais. A OF264774 preserva as linhas 5589 e 5590 como identidades separadas; o corte da 5590 está concluído e restam 20 peças para abocardar.

## Validação executada

| Etapa | Alteração e prova | Resultado / pendência |
|---|---|---|
| 1. Referência | Fotografia congelada e `scripts/reconcile_gantt_sources.py`. | Contagens de 24/09 guardadas; dados vivos não são usados como valores fixos de teste. |
| 2. Datas e Picking | `planning_dates.py`; testes de datas, cálculos e reconciliação antes/depois. | W da folha recuperada por OF, conflito preservado, Data Corte só para corte de Perfis. |
| 3. Saldos e tempos | `planning_estimates.py` e reutilização dos estimadores; testes de produtividade/capacidade e do saldo provisório. | Contadores não alterados; taxa e identidade verificadas; Cantoneiras mantida. |
| 4. Calendários | `planning_calendars.py`, editor e preview; testes de DST, reservas e cópia de semanas. | Minutos disponíveis exatos; calendário antigo continua semanal; horários reais ainda por preencher. |
| 5. Entrada/validação | `gantt/inputs.py` e `gantt/validation.py`; testes com 620 operações e proposta corrompida. | População completa e rejeição independente de barras inválidas. |
| 6. Proposta inicial | `gantt/baseline.py`; testes de pausa, fim de semana, precedência e fixação. | Proposta determinística validada em horários de teste. |
| 7. Otimização | `gantt/solver.py`; testes de enumeração independente, alternativas e vigência de taxas. | CP-SAT não substitui a proposta por uma solução pior; orçamento total limitado. |
| 8. Cenários/worker/API | Migração 037, `gantt/service.py`, worker e rotas; testes de revisão/idempotência, versão do motor e tarefa real no worker. | Enfileiramento e publicação concluídos; aceitação guardada pelo validador; código/dependências registados na tarefa. |
| 9. Interface | Página, editor e percurso de navegador em PostgreSQL descartável. | Gerar, ajustar, aceitar, comparar e reabrir sem erro JavaScript. |
| 10. Regressão/piloto | Suite abaixo, cinco medições e piloto operacional sem aceitação. | Funcionalidade ativa para Perfis; falta preencher horários reais e medir otimização com carga. |

- `uv run pytest -q tests/test_planning_raw.py tests/test_planning_needs.py tests/test_planning_incremental.py tests/test_planning_capacity_incremental.py tests/test_raw_workspace.py tests/test_capacity_revision.py tests/test_planning_productivity.py tests/test_planning_calculation_details.py tests/test_planning_gantt.py tests/test_planning_ocr_incremental.py tests/test_planning_worker_wakeup.py -x`: **136 passaram** na base PostgreSQL descartável. O DSN do teste tinha porta efémera Docker, embora o nome da base também fosse `dataresearchmtg`.
- `uv run pytest -q tests/test_planning_gantt.py`: **13 passaram** após a integração das reservas horárias. Inclui 620 operações além do limite de paginação, almoço, fim de semana, DST de Lisboa, dependências, conflito de fixações, taxas com vigências distintas na mesma máquina, reserva de outra área, ótimo de problema pequeno obtido por enumeração independente, migração e revisão de cenário, reabertura e comparação no navegador.
- `uv run pytest -q tests/test_planning_gantt.py tests/test_capacity_revision.py tests/test_raw_workspace.py tests/test_planning_capacity_incremental.py -x`: **57 passaram** após as alterações finais de calendários, reservas e solver.
- `node --check app/web/static/gantt.js` e `node --check app/web/static/capacity.js`: sem erros de sintaxe.
- O percurso do navegador gerou, ajustou prioridade, aceitou, comparou e reabriu um plano num PostgreSQL descartável. [Captura do piloto](gantt-piloto.png). Não houve erros JavaScript ou respostas HTTP inesperadas.
- Mudança apenas de comprimento de stock num teste de integração alterou a geração de origem, mas conservou a assinatura efetiva de calendarização e não marcou o plano como desatualizado. Uma alteração de recurso marcou-o como desatualizado.

## Medições

O [manifesto](manifest.json) contém versões e digest do código, da entrada e das fontes. As cinco medições estão em [benchmark-five-runs.json](benchmark-five-runs.json), com [entrada congelada](input-snapshot.json), [proposta inicial](initial-proposal.json), [proposta final](optimized-proposal.json) e [validação independente](validation-report.json). O comando foi `uv run python scripts/benchmark_gantt.py` e usa apenas acesso de leitura ao PostgreSQL.

As medições na população real avaliam o percurso sem calendários horários confirmados. Não comprovam a meta de desempenho quando todas as máquinas receberem horários e tarefas elegíveis; repetir as cinco medições e comparar a latência normal durante uma otimização com carga real antes de declarar essa meta satisfeita.

O [piloto na aplicação operacional](operational-pilot.json) enfileirou a tarefa HTTP em 0,029 s. O worker publicou a proposta inicial em 0,488 s e terminou em 0,568 s. Leu 1.167 operações; 37 estavam concluídas, 1.130 ficaram pendentes e nenhuma recebeu barra, pois ainda não há calendários horários confirmados. A validação independente passou com cobertura parcial; o solver indica que não havia operações elegíveis e não declara ótimo global. O cenário foi guardado e reaberto, mas a proposta não foi aceite como plano operacional. [Captura das pendências reais](gantt-operacional-pendencias.png).

## Ativação e reversão

A migração aditiva `sql/037_planning_gantt.sql` aceita os tipos `gantt` em objetos e tarefas sem apagar histórico. O código mantém `MES_PLANNING_GANTT_ENABLED=0` por defeito. A ativação local usa `/home/luis/.config/systemd/user/kanban-planning.service.d/gantt.conf` com `MES_PLANNING_GANTT_ENABLED=1`; só o servidor 8113 e `kanban-raw-worker.service` precisam de carregar o código novo. Os servidores MES das portas 8100/8101 não são tocados.

Para reverter a interface, retirar o override `gantt.conf`, executar `systemctl --user daemon-reload` e reiniciar somente `kanban-planning.service`. A reversão conserva os cenários, calendários, tarefas e histórico; não reverte produção nem substitui a base de dados. A ligação `/planeamento/gantt` passa a responder 404 quando a flag está desligada.

## Limites operacionais atuais

Sem horários confirmados para as máquinas físicas, o Gantt apresenta marcos, operações e motivos de pendência; não inventa turnos de oito horas. Reservas horárias confirmadas de outras áreas podem ser registadas no calendário e subtraem à capacidade da única máquina física. A carga semanal de outra área sem localização horária não é uma reserva exata. A primeira aceitação operacional com máquinas partilhadas requer os respetivos intervalos confirmados e nova validação do plano.
