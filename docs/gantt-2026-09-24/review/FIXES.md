# Correções da revisão do Gantt — 25/09/2026

**Integração publicada em 25/09:** [máquinas, previsões, carga semanal e validação no navegador](SOURCE-INTEGRATION.md). A vista inicial já apresenta barras do planeamento existente.

**Reavaliação posterior:** a conclusão sobre máquinas em falta era demasiado abrangente e foi identificada uma regressão no leitor reduzido de capacidade. Consultar [REASSESSMENT.md](REASSESSMENT.md) para a correção, dados atuais e limitações que permanecem. Existem máquinas e capacidade semanal nas fontes; o Gantt ainda não as integra como recursos horários.

O diagnóstico de [REVIEW.md](REVIEW.md) mantém-se como registo histórico. As falhas de código foram corrigidas no projeto `planeamento`, e o serviço da porta 8113 e o worker RAW foram reiniciados com a versão corrigida. Os contratos RAW e de capacidade foram incrementados; o worker publicou as gerações 749 e 752, respetivamente, sem agregados pendentes.

| Achado | Correção e prova |
|---|---|
| P1 · saldo da macro após mudar a quantidade | `planning_estimates.select_balance()` compara quantidade necessária e assinatura técnica com a origem. Aumentos, reduções ou alteração técnica deixam o saldo de planeamento desconhecido quando não existe produção reconciliada. [Reprodução](fix-results.json) e [verificação da OF264051, linha 33875, sem escrita na base](quantity-fixed-readonly.json). |
| P1 · semana manual ignorada | A captura usa `planning_dates.period()` para corte e abocardar, conserva o período e a origem, e deixa conflitos manuais pendentes sem prazo operacional escolhido. [Reprodução](fix-results.json). |
| P1 · fixação viável rejeitada | A proposta inicial coloca fixações e predecessores antes do trabalho livre. O caso B fixado às 08:00, 60 min, A livre, 120 min, passa e termina às 11:00. [Reprodução](fix-results.json). |
| P2 · atraso de Picking da OF | O validador mede a conclusão da OF sobre todas as operações necessárias, incluindo urgências. O exemplo misto regista 60 minutos. [Reprodução](fix-results.json). |
| P2 · provisoriedade a jusante | As barras transportam motivos herdados do corte; o validador reconstrói a dependência e rejeita etiquetas incorretas. [Reprodução](fix-results.json). |
| P2 · proposta desatualizada invisível | A página mostra separadamente o estado da proposta e do plano aceite. Uma proposta desatualizada apresenta aviso e bloqueia a aceitação. [Ensaio no navegador](fix-browser-results.json). |
| P2 · marcos sem barras invisíveis | O gráfico agrega Picking, previsões, períodos escolhidos e marcos CPIS mesmo sem máquina ou barra. Setas distinguem marcos antes/depois do horizonte. [Captura](ui-fixed.png). |
| Validador · chaves repetidas | A validação rejeita chaves repetidas antes da conversão para dicionário. [Reprodução](fix-results.json). |

Validação executada:

- `uv run pytest -q tests/test_planning_gantt.py tests/test_capacity_revision.py tests/test_planning_capacity_incremental.py tests/test_planning_productivity.py tests/test_planning_calculation_details.py tests/test_planning_macro_revisions.py tests/test_planning_integral_calculations.py tests/test_planning_worker_wakeup.py -x --tb=short`: **123 passaram**.
- `uv run pytest -q tests/test_planning_gantt.py tests/test_raw_workspace.py -x --tb=short`: **42 passaram**.
- `uv run pytest -q tests/test_planning_macro_revisions.py tests/test_planning_capacity_incremental.py tests/test_capacity_revision.py -x --tb=short`: **26 passaram** após incrementar os contratos.
- `uv run pytest -q tests/test_planning_gantt.py -k browser -x --tb=short`: **1 passou**, cobrindo geração, aceitação, reabertura, marcos sem barras, proposta e plano aceite desatualizados. Bases de teste PostgreSQL descartáveis; nenhuma escrita de teste na base operacional.
- `uv run python docs/gantt-2026-09-24/review/repro.py`: [casos reproduzidos depois da correção](fix-results.json).
- `node docs/gantt-2026-09-24/review/browser-fixed.cjs`: consulta apenas de leitura na aplicação publicada. **1.167 operações, 59 marcadores agregados, zero barras, aviso de proposta desatualizada e aceitação bloqueada, sem erros JavaScript**. [Resultado](fix-browser-results.json) e [captura](ui-fixed.png).
- `uv run python scripts/benchmark_gantt.py`: cinco capturas idênticas depois da reconstrução, **1.167 operações, validação independente válida, mediana total 0,4958 s**. [Medições](../benchmark-five-runs.json), [manifesto](../manifest.json) e [relatório do validador](../validation-report.json).

Limite da medição registada acima: os 1.104 bloqueios de máquina foram causados pelo requisito de configuração local do Gantt e não demonstram ausência de máquinas nas fontes. As cinco medições têm zero barras e **não comprovam** o tempo de otimização com carga, a regressão de latência de consultas durante o solver nem uma calendarização horária operacional. A [reavaliação](REASSESSMENT.md) discrimina os dados existentes e o trabalho de integração que falta.
