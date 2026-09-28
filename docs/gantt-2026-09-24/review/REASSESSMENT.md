# Reavaliação dos dados disponíveis — 25/09/2026

**Integração publicada em 25/09:** [máquinas, previsões, carga semanal e validação no navegador](SOURCE-INTEGRATION.md). A vista inicial já apresenta barras do planeamento existente.

A afirmação anterior de que faltavam máquinas confundiu ausência de configuração local com ausência de informação nas fontes. O catálogo importado e as linhas de planeamento já identificam as máquinas. O Gantt horário consulta apenas objetos locais `resource` confirmados; não existem esses objetos, pelo que a sua população de recursos fica vazia. Isso é uma lacuna de integração da implementação.

Consulta de leitura consistente da geração 781 de Perfis, depois da correção do recálculo de capacidade:

| Informação existente | Linhas de corte |
|---|---:|
| Linhas ativas | 1.139 |
| Máquina indicada | 914 |
| Data Corte indicada | 1.025 |
| Máquina e Data Corte | 801 |
| Duração positiva calculada | 813 |
| Saldo positivo, máquina, Data Corte e duração positiva | **731** |
| Picking recuperado | 311 |

As cinco máquinas usadas no plano são Disco pav. 1 (302 linhas), Vanguard (228), MEBA (209), Thomas (125) e Doall (50). Existem 225 linhas sem máquina indicada. Entre os 1.104 bloqueios antes apresentados como «Máquina física por confirmar», 884 operações já tinham máquina na origem e 220 não tinham. O rótulo agregado «Por definir» não conta como máquina. As restantes 26 pendências de saldo são um grupo distinto.

Também existe disponibilidade semanal importada em `PlanDisponibilidadeSemanal`, semana 39/2026:

| Máquina | Horas semanais | Linha Excel |
|---|---:|---:|
| Vanguard | 80 | 101 |
| Doall | 8 | 102 |
| Vanguard | 32 | 103 |
| Disco pav. 1 | 8 | 104 |
| Thomas | 8 | 105 |
| MEBA | 10 | 106 |

Esses valores são capacidade semanal, não intervalos de abertura por dia. A fonte tem duas entradas de Vanguard para o mesmo período e não contém semanas posteriores à 39/2026 nesta tabela. Não foi identificado um horário diário confirmado que permita derivar instantes exatos de máquina. Isso limita a calendarização horária; não elimina a informação disponível para mostrar previsões por máquina e carga estimada.

Foi descoberta e corrigida uma regressão adicional da entrega anterior. A função SQL `raw_capacity_detail()` retirava a quantidade/identidade original e `Qtd em Falta` antes de chamar a nova validação do saldo. O cálculo completo ainda encontrava esses dados, mas o recálculo de capacidade apagava as durações provisórias: a geração 765 tinha apenas 26 durações positivas. A migração [038_planning_balance_evidence.sql](/home/luis/projects/planeamento/sql/038_planning_balance_evidence.sql) conserva essa evidência no leitor reduzido. A identificação incremental também passou a considerar a quantidade e a identidade de origem. Depois da reconstrução, existem novamente **813 durações positivas e zero divergências entre saldo de origem selecionado e quantidade usada na estimativa**.

O diagnóstico do Gantt foi corrigido para distinguir «máquina indicada no planeamento; ligação ao Gantt por configurar» de «máquina da operação por indicar». A API e o detalhe conservam agora a máquina e a duração de origem mesmo que a operação não tenha um recurso horário configurado. Não foram criadas confirmações factuais ou horários fictícios para remover o bloqueio.

A implementação continua incompleta no aproveitamento visual do plano: precisa de apresentar o planeamento existente por máquina/data e a carga já calculada, com a proveniência apropriada, e de ligar os recursos importados ao modelo sem exigir nova introdução de dados conhecidos. Essa vista de previsões não pode ser apresentada como uma sequência ao minuto já validada pelo solver. A validade do calendário horário e o desempenho com carga real continuam por provar.

Provas:

- [Auditoria reproduzível de leitura](audit_available_data.py) e [dados disponíveis](available-data.json), com origens, máquinas, capacidades, exemplos e gerações.
- Teste novo `test_macro_balance_survives_capacity_storage_and_origin_changes_invalidate`: falhou antes da migração e passou depois, verificando também recálculo incremental contra completo.
- `uv run pytest -q tests/test_planning_capacity_incremental.py tests/test_planning_gantt.py tests/test_capacity_revision.py -x --tb=short`: **41 testes passaram**, incluindo o percurso do navegador.
- Migração aplicada e serviços de planeamento/worker reiniciados; capacidade publicada com contrato `capacity-20260925-integral-v27`, sem agregados pendentes. Nenhum contador de produção foi alterado.
