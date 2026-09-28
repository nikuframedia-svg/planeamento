# Matriz final — Planeamento de Perfis e Cantoneiras

As provas históricas continuam guardadas. Esta matriz substitui as pendências da matriz t4. A aplicação OCR original está fora do âmbito. Em 24/09, o utilizador dispensou continuar a otimização do limite de 10 segundos; as medições permanecem nos relatórios.

| Alteração | Consumidores e provas | Aceitação |
|---|---|---|
| OF/OV nova, peça local, campos omitidos | Formulário, API, RAW, histórico; `c03-complete-zero-fixed.json`, `c03-complete-persistence.json`, `t10-v06-browser.json` | Preservadas as provas compatíveis de registo e as mesmas necessidades V06 |
| Quantidade, comprimento, geometria, stock, operações | Preview/gravação, RAW, base, capacidade, CSV/XLSX; `t10-description-preview-regressions.log`, `t10-rebuild-parity-regressions.log`, `t10-v06-exports.json` | 512 comparações dos 32 passos; zero diferenças |
| Máquina, semana e ano | Destinos antigos/novos, recursos partilhados, agregados; `t10-order-navigation-regressions.log`, `t10-v06-browser.json` | Comparação incremental com cálculo completo passou |
| Taxa, calendário, horas e prioridade de estimativa | `t10-deferred-evidence-regressions.log`, `t10-actual-hours.json`, `t10-rate-selection.json`, `t10-historical-cohorts.json` | Valores, origem, cobertura e exclusões auditados independentemente |
| Inserção/correção/retirada MES, associações e peças filhas | `t10-final-query-regressions.log`, `t10-production-sources.json`, `t10-v06-browser.json` | Revisões antigas não voltam a controlar resultados; histórico preservado |
| Documento ligado, macro e CPIS | Sugestões, revisão, dados humanos, ativo/histórico, saldos/capacidade; `t10-linked-revision-tests.log`, `t10-v06-browser.json`, `t10-v06-completion-browser.json` | Fecho e reabertura nas mesmas necessidades; revisão documental propagada |
| Catálogos, interpretação global de semanas e motor | Reconstrução integral conservadora quando as dependências globais mudam; `t10-order-navigation-regressions.log`, `t10-full-rebuild.json` | 83.156 peças, 14 conjuntos, zero diferenças. Reconstrução: Perfis 39,32 s, Cantoneiras 72,50 s, capacidades 36,94 s; não apresentada como delta de 10 s |
| Concorrência, worker indisponível e respostas atrasadas | `t10-order-navigation-regressions.log`, provas compatíveis C05/C09 de corrida no browser | Capacidade publicada só com ambas as áreas atuais; último conjunto coerente preservado |
| Reinício, documentos e auditoria | `t10-persistence-before.json`, `t10-persistence-after.json`, `t10-document-audit-delivery-final.json` | Todas as populações, tabelas, ficheiros e recibos iguais; entrega idempotente |
| Corte real do Drive/MES | `t10-drive-mes-content.json`, `t10-live-mes-reconciliation.json`, `t10-publication-rehearsal.json`, `t10-automatic-source-cycles.json` | 113/205 folhas, eventos/horas reconciliados, repetição e dois ciclos autónomos completos |

As nove auditorias independentes foram ligadas à candidata em `t10-final-rule-acceptance.json`: 43 regras e 12 comparações de populações sem diferenças. O manifesto da candidata está em `t10-candidate-manifest.json`.

Na última prova de gravação real no browser, a linha atualizou em 96–479 ms e os agregados em 1,397–2,278 s. Nas revisões de macro foram observados cerca de 10,5–10,7 s; os ensaios anteriores, incluindo os mais lentos, não foram apagados.
