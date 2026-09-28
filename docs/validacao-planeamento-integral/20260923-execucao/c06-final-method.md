# C06 — Fecho da validação no ambiente isolado

A regra é fecho explícito no CPIS **ou** numa origem macro da identidade. «Pronta», ausência de estado e estados desconhecidos não são fecho. A autorização operacional continua a exigir CPIS direto válido e os restantes requisitos de saída; preparar/consultar uma peça ativa não concede essa autorização.

## Alterações finais

- Dossiês consultam CPIS direto atual ou todas as cópias importadas atuais nas duas áreas. Preservam múltiplas OVs e distinguem `of_closed`, `of_not_operational` e estados desconhecidos. Linhas fechadas continuam disponíveis para correspondência histórica, com os mesmos IDs.
- A classificação da peça considera todas as origens associadas. A emissão manual confere novamente o fecho tanto ao propor como ao descarregar o resultado, incluindo registos locais sem `source_plan_key`.
- A RAW antiga resolve associações para os novos IDs de uma importação imutável através do mesmo leitor de pertença da projeção principal. O join administrativo que poderia multiplicar origens foi removido. Necessidades sem peça/registo atual não são reintroduzidas arbitrariamente.

## Matriz de aceitação

| Critério | Prova e âmbito |
|---|---|
| C06.1 — classificação comum | `c06-dossiers-current-population.json`: comparação independente com CPIS/macro de todas as 83 156 peças publicadas, índices de dependência incluídos. `c06-final-transitions.log`: estados normalizados/desconhecidos, cópias CPIS, matriz dos quatro estados, ambas as áreas e dossiês. |
| C06.2 — mesmos consumidores | `c06-complete-orders-audit.json`: todas as 83 156 identidades e contagens OF/área. `c06-legacy-raw-population-audit.json`: todas as 7 417 identidades Perfis na RAW antiga, três âmbitos. `c06-final-pagination.log`: paginação efetiva de populações mistas nas duas áreas, sem perdas/duplicações e facetas coerentes. `c06-final-transitions.log`: consultas, pesquisa, seleção, análises, CSV/XLSX, vistas antigas, contagens e carga. `c06-final-browser.json`: seis âmbitos visíveis, seleção/exportação de fechado rejeitada no ativo e preservada no histórico, sem erros JS. |
| C06.3 — histórico intacto | `c06-final-transitions.log`: preservação de IDs, registos OCR e importações anteriores, PDF efetivo e bytes, IDs das peças e leituras após fecho/reabertura; nenhuma autorização de saída incorreta. `c06-final-state.json`: hashes das fontes/necessidades e gerações preservados. As provas anteriores `c06-complete-orders-browser.json` e `c06-legacy-browser.json` comprovam detalhe histórico, necessidades/registos e acessos sem CPIS. |
| C06.4 — transições e H09 | `c06-final-transitions.log`: importações imutáveis fechado/reaberto nas duas áreas; quatro combinações CPIS/macro; produção de peças fechadas alimenta taxa histórica ponderada da peça ativa sem voltar a entrar na carga pendente. `c06-legacy-raw-rebinding-after.log`: relações mantidas quando a reimportação muda os IDs físicos. |

## Execuções e limites

- Dossiês/saídas/registos: 163 testes passaram em 68,86 s; teste adicional do download passou em 6,77 s. A execução final de transições voltou a incluir os 15 casos de população dos dossiês.
- RAW antiga/população de OFs/população comum: 27 testes passaram em 49,76 s.
- Transições finais, dossiês e produtividade de fechados: 29 testes passaram em 36,35 s. A paginação acrescentada passou em duas áreas: 2 testes em 9,41 s. Existem sobreposições entre suites; não somar estes números como casos distintos.
- `c06-dossiers-audit.json`: amostra real das 12 combinações observadas, 12 OFs/222 membros comparados; não se afirma consulta PDF exaustiva de 7 417 peças. O PDF persistido dos testes usa resposta de visão simulada, apenas para validar conservação e reclassificação. Não demonstra ingestão OCR original, que pertence a C01.
- `c06-legacy-raw-rebinding-before.log` conserva a falha real de duplicação. `c06-dossiers-tests-first.log` conserva o erro inicial relativo a múltiplas OVs; uma OV confirmada em comum é suficiente para o documento com várias OVs. `c06-dossiers-download.log` conserva a falha de preparação da fixture XLSM; a versão final usa uma linha realmente existente no template.
- Browser 18113, PostgreSQL `planning_integral` 44164 e bases descartáveis. Nenhuma migração ou escrita de teste na base operacional. O servidor isolado foi reiniciado para carregar o código atual; os processos operacionais permanecem os mesmos. Os estáticos são partilhados com Planeamento 8113, como documentado anteriormente.
- C06 aprovado apenas no ambiente validado. C11, C12, o restante plano e a publicação integral continuam pendentes. Não se declara R02 entregue no destino final antes de C12.
