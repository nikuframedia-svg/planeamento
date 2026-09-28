# C06 — População nas consultas antigas de Planeamento

Esta etapa corrige a lista de OFs CPIS e o seletor de linhas importadas. Não aprova C06 global nem C12.

## Alterações

- A população é aplicada antes da contagem e da paginação: ativo, histórico ou todos. O estado CPIS é um filtro adicional; «todos os estados» não reintroduz fechados no ativo.
- A classificação usa a regra comum `CPIS fechado OU linha fechada na macro`, incluindo espaços, maiúsculas, marca textual e booleano. Todas as cópias CPIS de uma OF participam na decisão, mesmo quando apenas uma corresponde à pesquisa.
- Estados desconhecidos e Pronta permanecem ativos quando nenhuma fonte declara fecho. Os estados desconhecidos têm diagnóstico visível; um estado nulo não desaparece do filtro «todos».
- OFs com linhas ativas e fechadas podem aparecer nos dois âmbitos, com contagens de linhas distintas. Por isso, não se somam as contagens de OFs para obter «todos».
- A consulta de detalhe e as fichas existentes continuam disponíveis. Atualizar a origem de uma ficha existente consulta também linhas fechadas, preservando a identidade. As regras de autorização da conclusão/saída operacional não foram relaxadas.
- A lista ignora respostas anteriores quando o utilizador já iniciou outra consulta.
- Como os estáticos são partilhados com 8113, os novos controlos só são renderizados quando o backend anuncia suporte. Um processo antigo mantém os controlos anteriores; o JavaScript aceita a resposta anterior sem mostrar um rótulo indefinido. Isto não substitui a publicação C12.

## Provas

`c06-legacy-regression-final.log`: 51 testes passaram em 42,90 s, sem falhas ou ignorados. PostgreSQL descartável. Inclui a matriz nas duas áreas, fonte CPIS direta/importada, fecho por qualquer cópia, histórico/todos, pesquisa, contagens, paginação, estados desconhecidos/nulos, rejeição de população inválida, reabertura, leitura de ficha e preservação de registos. A regressão RAW mantém produção histórica e exclusão da carga ativa.

`c06-legacy-audit.json`: leitura independente das fontes na cópia integral. Reconstrói todas as OFs e contagens por área, sem chamar o classificador de fecho. Compara a população completa produzida pela função usada pela API; verifica adicionalmente primeira página, página intermédia, última e página seguinte ao fim, em cada âmbito. A população completa não é reduzida às páginas amostradas. Contagens: 70 280 OFs CPIS; 1 671 OFs/15 560 linhas ativas, 68 694 OFs/63 894 linhas históricas, 70 280 OFs/79 454 linhas no total. Fontes e necessidades mantêm os hashes da etapa C09.

`c06-legacy-browser.json`: browser real em localhost:18113, três âmbitos, contagens e linhas visíveis, pesquisa de uma OF fechada, consulta dos mesmos IDs no histórico, recarga para ativo e resposta ativa real retida enquanto uma consulta histórica mais recente termina. Sem erros JavaScript nem pedidos de escrita. Capturas `c06-legacy-active.png`, `c06-legacy-history.png`, `c06-legacy-all.png`.

## Ensaios conservados

- `c06-legacy-before.log`: falha antes da alteração por ausência do contrato de população nas linhas.
- `c06-legacy-regression-first.log`: faltavam duas colunas reais do catálogo de Cantoneiras na fixture descartável. A fixture foi completada.
- `c06-legacy-regression.log`: o teste esperava 400 para entrada inválida, mas o contrato de PlanningError é 422. Corrigida a expectativa; a aplicação não foi alterada para acomodar o teste.
- `c06-legacy-browser-startup.*`: browser iniciado antes da disponibilidade HTTP do servidor isolado; nova execução só depois de confirmar a resposta HTTP.
- `c06-legacy-audit-restructure.json`: interrompida uma auditoria somente de leitura que recalculava a população integral para cada uma de cerca de 1 400 páginas. O comparador atual verifica a mesma população inteira uma vez por âmbito, mais os limites de paginação. A interrupção não foi tratada como aprovação.
- As provas anteriores à compatibilidade de templates e ao reforço do detalhe histórico foram conservadas. Só os artefactos finais são usados para a conclusão desta etapa.

## Pendências explícitas

O hub anterior é centrado em OFs existentes no CPIS. Das 83 148 linhas importadas atuais, 3 694 não pertencem a essa população administrativa e não estão incluídas na aprovação deste âmbito. O auditor regista a quantidade de OFs e exemplos em `outside_hub_cpis_scope`. A revisão seguinte tem de tratar essas OFs, necessidades exclusivamente locais, origens associadas e os restantes seletores antigos. Não se assume que a consulta administrativa cubra toda a RAW.

Continuam pendentes os critérios integrais C06, a regressão final C11 e a publicação C12. Não houve migração ou escrita na base operacional, nem reinício de serviços operacionais ou kanbans. Apenas o servidor isolado de Planeamento foi reiniciado.
