# Entradas e origens dos campos calculados

Esta etapa completa as explicações de produção selecionada, saldos, excessos,
percentagens, áreas, comprimentos, pesos, perfis inteiros e calendário ISO.
O contrato passa a `planning-integral-20260923-v4`; a alteração invalida a
projeção pelo fingerprint existente.

Os contadores identificam operação, OCR utilizável, acumulado Excel, eventos
considerados, compatibilidade, condição inicial local e limitações da cobertura.
Eventos repetidos permanecem na explicação; o valor selecionado continua a usar
a deduplicação do motor. A produção OCR de Cantoneiras tem uma regra separada
e não apresenta o acumulado Excel como se fosse OCR.

As geometrias inválidas conservam a fórmula tentada e os operandos conhecidos.
O peso explica área/densidade ou a propriedade exata kg/m, além do comprimento.
A origem já não declara densidade 7850 quando foi fornecida outra densidade.
Ano e semana ISO partilham as entradas originais. A interface traduz as entradas
e os identificadores dos resultados que não têm coluna na área atual.

## Provas atuais

- Dez falhas reproduzidas em `c04-derived-details-before.log`; os mesmos casos
  passaram. Regressão integrada: 142 testes, nenhum ignorado, 76,08 segundos.
- `c04-derived-details-population.json`: 8 147 719 verificações das explicações
  em 7 417 peças de Perfis e 75 739 de Cantoneiras; zero diferenças.
- `c04-derived-details-input-gaps.json`: nenhum resultado numérico conhecido
  com mapa de entradas vazio nas duas áreas.
- `c04-derived-details-arithmetic.json`: 966 629 verificações das 23 regras
  aritméticas já auditadas, zero diferenças; 493 casos de catálogo. Esperados
  calculados pelo auditor independente, com tabelas dos ficheiros Excel.
- `c04-derived-details-semantic.json`: 1 701 766 verificações de descrição e
  prazo, zero diferenças.
- Dois percursos de detalhe dos derivados e dois de descrição/prazo passaram
  no navegador, sem erros JavaScript. Capturas de Perfis e Cantoneiras foram
  inspecionadas; operandos, fórmula, origem e motivo são legíveis.
- A reconstrução 4291/4292 → 4307/4308 preservou todos os valores escalares,
  identidades e fingerprints das fontes. Tempos: Perfis 16,49 s, Cantoneiras
  108,94 s, capacidade 68,05 s. São reconstruções integrais, não uma aprovação
  dos tempos incrementais de C05.

## Comandos

```bash
RUN_PG_INTEGRATION=1 .venv/bin/python -m pytest -q --tb=short tests/test_planning_calculation_details.py tests/test_planning_integral_calculations.py tests/test_planning_description_deadline.py tests/test_raw_workspace.py tests/test_planning_capacity_preview.py tests/test_planning_hours_detail.py tests/test_planning_operation_hours.py tests/test_capacity_revision.py
PYTHONPATH=. .venv/bin/python scripts/audit_planning_calculation_details.py
PYTHONPATH=. .venv/bin/python scripts/audit_planning_formula_population.py --output c04-derived-details-arithmetic
PYTHONPATH=. .venv/bin/python scripts/audit_planning_semantic_results.py --require-detail --output c04-derived-details-semantic
PLANNING_CHECK_BASE=http://127.0.0.1:18113 PLANNING_TEST_ISOLATED=1 PLANNING_PROOF=c04-derived-details-browser-final node tests/planning_calculation_details_browser.cjs
PLANNING_CHECK_BASE=http://127.0.0.1:18113 PLANNING_TEST_ISOLATED=1 PLANNING_PROOF=c04-derived-details-semantic-browser node tests/planning_semantic_detail_browser.cjs
```

## Limites e preservação

O auditor de explicações compara operandos com os dados efetivamente utilizados
e a evidência selecionada; não prova independentemente a associação OCR nem a
seleção do catálogo. A aritmética e a semântica têm auditores distintos. Esta
etapa não acrescenta aprovação integral a F02/F03/G01/H03/H09, C04 ou C11.

O inventário de mapas vazios é diagnóstico: a sua ausência, por si só, não
prova que todas as fórmulas sejam completas ou corretas. Os testes e auditores
suportam apenas os âmbitos explicitamente descritos. As exportações de valores
da etapa anterior não foram repetidas: o exportador não mudou e todos os valores
escalares se mantiveram; essas provas conservam a revisão anterior.

As escritas de teste ocorreram em PostgreSQL descartável e no clone integral.
Apenas o servidor isolado 18113 foi reiniciado. Os estáticos são partilhados
com 8113; backend, migrações e worker operacionais ainda não foram publicados.
As 27 alterações tracked preexistentes, os Excel, as fontes centrais e as
configurações foram verificados por hash. O primeiro finalizador comparava
hashes de configurações com âmbitos diferentes; foi corrigido para conferir
separadamente recursos/taxas e recursos/calendários/taxas. Não houve alteração
dessas configurações.

As primeiras auditorias de explicações e semântica usaram as gerações
intermédias 4301/4305, ainda durante a publicação da capacidade. O finalizador
rejeitou a mistura de gerações. Essas provas estão preservadas com o prefixo
`c04-derived-details-intermediate-`; ambas foram repetidas após terminar a
reconstrução, sobre 4307/4308. A auditoria aritmética, os percursos de browser
e o inventário de entradas já usavam as gerações finais.

Os produtores anteriores dos auditores semântico e de browser estão arquivados.
O primeiro browser dos derivados passou, mas revelou nomes técnicos na revisão
visual; a versão final traduz esses nomes e tem novas capturas e prova próprias.
O manifesto e `c04-derived-details-final-state.json` identificam a revisão atual.
