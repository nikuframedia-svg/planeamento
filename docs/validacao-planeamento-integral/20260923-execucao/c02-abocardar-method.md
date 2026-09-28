# C02 — Reconciliação central e nome equivalente de abocardar

24/09/2026. Revisão `ff19b4af62c3a83724784447eed976fb0038f337b4143d547188ddb3171536a1`,108 ficheiros. Manifesto anterior `execution-manifest-c04-perfis-source-validated.json` conserva c6367c4. Apenas Planeamento; fontes/serviços operacionais e kanbans preservados.

## Falha reproduzida

A auditoria independente `audit_planning_selected_ocr.py` lê as identidades importadas, os registos validados centrais e as expansões históricas. Resolve a identidade por chave de snapshot ou combinação técnica completa e única. Cantoneiras exige código explícito ou a mesma operação única em todas as peças filhas; não infere operação pela máquina. Quantidades por filho, IDs, folha, linha e validação são confrontados com os factos efetivamente selecionados. Os hashes das entradas e o ledger por registo ficam na prova final.

A primeira execução técnica (`c02-selected-ocr-first.log`) encontrou uma identidade congelada nula; o acesso foi corrigido e testado. A execução seguinte, `c02-selected-ocr-audit.json`, conferiu 2351 registos centrais e identificou quatro totais utilizáveis não selecionados. A aplicação só reconhecia o nome exato «Abocardar». Os registos2065/2066 usam «MAQ. ABOCARDAR» e ficavam com operação por confirmar, bloqueando a cobertura de corte e abocardar nas duas peças.

A correção aceita esse nome explícito equivalente, normalizando espaços e maiúsculas. Nomes desconhecidos continuam pendentes. O contrato RAW passa de v12 a v13 para invalidar publicações antigas. Não altera a associação técnica, quantidades, folhas ou dados importados.

## Resultados numéricos

Todas pertencem a OF264774/referência CI5421A3004, Q=840; continuam ativas e separadas por identidade técnica.

| ID / linha | Perfil / comprimento | Antes: corte / abocardar | Depois: corte / abocardar | Saldos depois: corte / abocardar |
|---|---|---|---|---|
| 34512 / 5588 | 76×2,6 / 2750mm | 840 / não aplicável | 840 / não aplicável | 0 / 0 |
| 34513 / 5589 | 89×3 / 2050mm | 100 Excel / 135 Excel | 840 OCR / 765 OCR | 0 / 75 |
| 34514 / 5590 | 114×3,2 / 2300mm | 840 Excel / desconhecido | 840 OCR / 668 OCR | 0 / 172 |

As três têm barras e peso principal pendentes zero. Comprimentos totais necessários mantêm-se 2310000,1722000 e1932000mm, respetivamente. Não se somam corte e abocardar nem se transfere produção entre os três perfis.

## Provas e limites

- `c02-abocardar-regression.log`:80 testes passaram em30,19s,zero falhas/ignorados. Evidência, cálculos, auditor e atualização OCR. Os12 testes iniciais do auditor são sobrepostos.
- `c02-selected-ocr-final.json`:2351 registos centrais examinados;1389 totais de operação selecionados conferidos(336Perfis/1053Cantoneiras),zero divergências.1338 registos têm identidade/operação resolvida;1013 ficam com diagnóstico individual. Registos originais, peças filhas e totais de operação são populações diferentes.
- `c02-abocardar-browser.json`:API/grelha/detalhe das três peças; campos numéricos, origens OCR, ausência de avisos de cobertura e registos2065/2066 visíveis. Zero erros JavaScript. Captura34513 inspecionada:135 Excel separado de765 OCR; corte840 composto pelos seus próprios eventos.
- `c02-abocardar-capacity.json`:cinco operações conferidas,três cortes0 e abocardar75/172,sem duplicação do peso principal.
- `c02-abocardar-exports.json`:seis CSV/XLSX, nove resultados por peça, comparados com a fixture independente; SHA da fixture e artefactos verificados.
- `c02-abocardar-current-audit.json`:83152 peças,18977 operações principais e104 conjuntos históricos,zero falhas. Reconstrução isolada Perfis11,58s/Cantoneiras66,74s/capacidade21,85s; estes não são tempos C05 de atualização incremental.
- `c02-abocardar-population.json`:966573 verificações independentes/23 regras,493 casos de catálogo,zero falhas. `c02-abocardar-population-audit.json` confirma população/índices e exclusão de fechados.
- `c02-abocardar-excel.json`:**1802 diferenças ainda por investigar**,491Perfis/1311Cantoneiras,código1. São mais5 que antes porque a produção correta passa a divergir dos acumulados antigos. A prova central confirma os eventos; falta ligar as justificações por campo à comparação Excel. Não se classifica uma diferença apenas por existir OCR.

Não há decisões humanas de associação nesta fotografia isolada. Esta auditoria não aprova a ingestão viva, a base/processo Windows do OCR original, a reconciliação entre origens nem toda a matriz de fallback/revisões. C01/C02 continuam incompletos; F02/F03/G01 recebem evidência parcial, não aprovação integral. As20 regras fora da auditoria aritmética e os restantes critérios do plano permanecem pendentes.

## Preservação e ambiente

`c02-abocardar-before.json`/`after.json` conservam valores das três peças e hashes completos das tabelas de folhas validadas, registos, filhos, linhas importadas e necessidades: todos iguais antes/depois. Apenas publicações derivadas foram reconstruídas. Gerações atuais Perfis3559/Cantoneiras3560.

`c02-abocardar-final-state.json`:108 hashes da execução e27 tracked preexistentes conferidos. Servidor isolado1507575 substituído por1629587,porta18113,DSN privado isolado verificado; nenhum worker isolado iniciado. Processos operacionais239043/239069 iguais. Sem novas migrações. Checklist conserva13 checkpoints,58 critérios,43 regras e6 casos; nenhum checkpoint global aprovado,C12 por executar.
