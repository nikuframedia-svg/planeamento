**Revisão do Gantt de Perfis — 24/09/2026**

**Integração publicada em 25/09:** [máquinas, previsões, carga semanal e validação no navegador](SOURCE-INTEGRATION.md). A vista inicial já apresenta barras do planeamento existente.

**Correção da conclusão sobre os dados:** a [reavaliação de 25/09](REASSESSMENT.md) comprova máquinas, previsões, durações e capacidade semanal já existentes e identifica uma regressão adicional agora corrigida. A falta de objetos locais confirmados não significa falta desses dados nas fontes.

**Atualização de 25/09/2026:** as oito falhas de código e interface descritas abaixo foram corrigidas e verificadas. Este texto conserva o diagnóstico original; consultar [correções e validação](FIXES.md) para o estado atual. Continua por validar o desempenho do solver com operações reais calendarizáveis, porque ainda não há recursos físicos e horários confirmados.

A infraestrutura foi implementada e as melhorias de recuperação de dados estão presentes. A revisão encontrou falhas de cálculo e de calendarização que precisam de correção antes do uso operacional. Preencher os horários, por si só, não resolve os casos abaixo.

**1. [P1] O saldo da macro é reutilizado depois de alterar a quantidade necessária.**

Em [planning_estimates.py:24](/home/luis/projects/planeamento/app/planning_estimates.py:24), o fallback apenas verifica que `Qtd em Falta` é válida e não excede a quantidade atual. Não compara a quantidade atual com a quantidade da origem. A assinatura técnica usada em `compatible` não inclui a quantidade. Numa cópia em memória da OF264051, linha 33875, alterei a necessidade de 2 para 102 peças e recalculei: o saldo reconciliado continuou desconhecido, mas o saldo de planeamento continuou em 2. Isso permite subestimar a carga futura. A base operacional não foi alterada. [Evidência](quantity-live-readonly.json).

Correção: exigir coerência com a quantidade e identidade da origem antes de recuperar o saldo guardado. Se a quantidade mudou e não existe produção reconciliada suficiente para recalcular, devolver pendência. Validar aumentos e reduções da quantidade mantendo a geometria.

**2. [P1] O Gantt ignora a semana manual e o conflito entre semana e previsão.**

[inputs.py:258](/home/luis/projects/planeamento/app/gantt/inputs.py:258) constrói o alvo diretamente com `expected_date`/`cut_date`, sem consultar o resolvedor partilhado de período. Com Data Corte de 22/09/2026 e semana manual 2026-W43, `planning_dates.period()` devolve W43, mas o Gantt conserva o alvo de setembro. Com previsão manual em W39 e semana manual W40, o resolvedor devolve conflito; a operação continua `ready`, sem motivo de pendência, na entrada do Gantt.

Correção: integrar o resolvedor de datas na construção das operações, transportar o período escolhido e bloquear conflitos manuais. A interpretação deve ser a mesma na tabela, capacidade e Gantt; uma semana escolhida não deve fabricar uma hora de início.

**3. [P1] Uma fixação perfeitamente viável pode impedir toda a geração.**

[baseline.py:22](/home/luis/projects/planeamento/app/gantt/baseline.py:22) preenche capacidade por prioridade antes de reservar as fixações. Reproduzi duas operações na mesma máquina: A livre, 120 minutos; B fixada às 08:00, 60 minutos. A é colocada primeiro às 08:00 e B passa a ser impossível para o construtor inicial. A solução B 08:00–09:00 e A 09:00–11:00 é aceite pelo validador independente. Contudo, [service.py:259](/home/luis/projects/planeamento/app/gantt/service.py:259) termina em diagnóstico antes de chamar o CP-SAT.

Correção: tratar previamente as fixações e as suas dependências, reservando os intervalos necessários. Uma falha da heurística não deve ser confundida com incompatibilidade das restrições. Acrescentar este caso viável aos testes, além do caso já existente de duas fixações efetivamente sobrepostas.

**4. [P2] O atraso de Picking da OF pode ser calculado como zero quando há atraso.**

[validation.py:32](/home/luis/projects/planeamento/app/gantt/validation.py:32) calcula o fim apenas sobre as operações do grupo Picking. Uma operação da mesma OF marcada como urgente deixa de entrar nesse máximo. Exemplo reproduzido: corte 08:00–09:00, abocardar urgente 09:00–10:00, Picking às 09:00. O atraso da OF é 60 minutos, mas o vetor do validador regista zero no componente de Picking. O modelo CP-SAT usa todas as operações necessárias no máximo, criando também uma divergência entre o objetivo otimizado e o objetivo usado na comparação com a proposta inicial.

Correção: calcular a conclusão da OF sobre todas as operações necessárias, independentemente da classe de prioridade individual, e usar a mesma definição verificável no solver e no validador. Testar OF com operações de prioridades diferentes.

**5. [P2] A incerteza do corte não se propaga a abocardar.**

[baseline.py:52](/home/luis/projects/planeamento/app/gantt/baseline.py:52), [solver.py:194](/home/luis/projects/planeamento/app/gantt/solver.py:194) e o validador verificam apenas o saldo/taxa da própria operação. Num caso com saldo de corte provisório e abocardar com dados confirmados, a segunda barra é apresentada como confirmada, embora dependa da conclusão estimada do corte. O validador aceita esse resultado.

Correção: propagar a indicação de provisoriedade pelas dependências, incluindo o motivo e a operação que originou a hipótese. O verificador deve reconstruir essa propagação de forma independente.

**6. [P2] Uma proposta desatualizada pode continuar identificada como atual na interface.**

[gantt.js:64](/home/luis/projects/planeamento/app/web/static/gantt.js:64) usa `latest.stale` para desativar a aceitação, mas não atualiza a mensagem das fontes nem apresenta o motivo. O indicador usa apenas o estado do plano aceite. No navegador, ao simular uma resposta de tarefa com `stale: true`, a aceitação ficou desativada, o aviso ficou vazio e a página continuou a dizer «Fontes publicadas atuais». A proteção do servidor não é anulada, mas o utilizador não percebe que precisa de recalcular. [Resultado do ensaio](browser-results.json).

Correção: apresentar separadamente a atualidade da proposta aberta e do plano aceite. Ao atualizar fontes, atualizar também o estado da proposta e a ação de aceitação.

**7. [P2] Os marcos não aparecem no gráfico enquanto as operações não têm barras.**

[gantt.js:215](/home/luis/projects/planeamento/app/web/static/gantt.js:215) desenha marcos dentro do ciclo das barras calendarizadas. No piloto atual há 311 linhas de corte com Picking e 1.025 com Data Corte, mas o navegador tem zero marcos visíveis no gráfico. As datas ficam sobretudo nos tooltips das linhas. Isto limita a utilização prevista no plano para a fase em que ainda faltam horários.

Correção: apresentar marcos de OF/operação também para trabalho pendente, numa vista ou lista temporal legível, sem inventar execução de máquina.

**Cobertura de validação que ainda falta**

O validador também não deteta chaves de operação repetidas na entrada: `operation_by_key()` converte a lista para um dicionário e elimina duplicados antes de verificar cobertura. Reproduzi duas operações com a mesma chave a originar uma barra e `valid: true`. O construtor atual da população tende a produzir chaves únicas, pelo que esta é uma lacuna da barreira de integridade, não uma duplicação observada nos dados vivos. Acrescentar a verificação de unicidade antes da conversão.

As cinco medições anteriores têm zero operações calendarizadas e `optimization_seconds` próximo de zero. Comprovam captura e tratamento das pendências, mas não a meta do solver com carga nem a regressão máxima de 20% da latência das consultas durante uma otimização. Essa parte da definição de concluído continua por verificar.

**Estado observado e provas executadas**

- API operacional: 1.139 linhas de corte, 1.167 operações, 37 concluídas e 1.130 pendentes. Existem zero recursos físicos confirmados na entrada. As razões são 1.104 operações com «Máquina física por confirmar» e 26 com saldo desconhecido. Os dois motivos de saldo dessas 26 operações não são 52 operações diferentes. [Dados observados](live-status.json).
- Confirmadas as 311 linhas de corte com Picking e as 1.025 com Data Corte. A separação por operação e a exclusão de carga futura para saldos zero estão presentes.
- `uv run pytest -q tests/test_planning_gantt.py -k 'not browser' --tb=short`: **12 passaram, 1 excluído**, em 16,27 s. As fixtures usam PostgreSQL Docker descartável em porta efémera; não a porta operacional 5432. A suite passa mesmo com as falhas reproduzidas, mostrando que esses cenários não estavam cobertos.
- `uv run python /tmp/gantt-review-2026-09-24/repro.py`: reproduções exclusivamente em memória, com fonte de consulta simulada para a captura de datas. [Código](repro.py) e [resultados](repro-results.json).
- `node /tmp/gantt-review-2026-09-24/browser.cjs`: navegação apenas de leitura e resposta desatualizada simulada apenas no navegador; todos os pedidos de escrita foram bloqueados pelo ensaio. Sem erros JavaScript. [Código](browser.cjs), [resultados](browser-results.json) e [captura real](ui-current.png).

Prioridade de correção: saldo da macro, interpretação das decisões de datas e fixações viáveis; depois métricas de Picking, propagação da provisoriedade e avisos/marcos da interface. Em seguida, confirmar recursos físicos, completar os saldos em falta, configurar horários reais e repetir o piloto e as medições com operações efetivamente elegíveis.
