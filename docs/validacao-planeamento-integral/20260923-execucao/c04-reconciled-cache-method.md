# C04 — Reconciliação dos 107 casos restantes

Revisão dos auditores: `4ab49ae490a2c652935aebcab7d899bc39b8a7468472b09b11f6461ad7f6b42f`.
Aplicação inalterada desde `ff19b4af62c3a83724784447eed976fb0038f337b4143d547188ddb3171536a1`.
Base isolada `planning_integral`, gerações Perfis 3559 e Cantoneiras 3560.

## Resultado e limites

`c04-reconciled-cache-comparison.json` passou com código 0: 966 573 verificações,
83 152 peças e 23 regras aritméticas. Não existem diferenças pendentes neste
âmbito. Os 250 978 resultados indisponíveis têm motivo. Colunas sem equivalente
físico no Excel, células não guardadas, dados desconhecidos e peças locais
continuam explicitamente separados de igualdade numérica.

Esta prova não aprova C04 integralmente. Continuam fora desta auditoria as vinte
regras F01/F02/F03/F12/F20/F21, G01/G06/G07/G12 e H01–H10, bem como os restantes
critérios do plano, a ingestão real do OCR original e a disponibilização final.

## Prova das diferenças

O delta `c04-reconciled-cache-delta.json` liga cada uma das 107 pendências da
comparação anterior à sua justificação. Os valores atuais da aplicação e os
valores guardados no Excel não mudaram em nenhum desses casos.

| Casos | Justificação comprovada |
|---:|---|
| 25 | Geometria inválida ou incompleta: reconstrução da aritmética VBA original; a ausência de espessura não estabelece área física zero. |
| 40 | Resultados derivados escritos como números no Excel; recalculados a partir de quantidade, produção e propriedades, preservando o stock como entrada. |
| 11 | Quantidade estruturada AH diferente da antiga N, com produção, comprimento e stock conferidos. |
| 15 | Propriedade física desconhecida: peso indisponível em vez de aceitar o zero derivado de uma área antiga sem correspondência. |
| 10 | Peso negativo antigo de Cantoneiras; correspondência exata da tabela e excesso de produção comprovados, saldo atual limitado a zero. |
| 2 | Datas manuais: operação, campo persistido, ligação à linha e evento de revisão conferidos; semana/ano ISO calculados independentemente. |
| 1 | Fórmula de área unitária copiada de AP para AX: tradução exata das referências, pesquisa deslocada para a qualidade sem correspondência e propriedade correta comprovadas. |
| 1 | Saldo conhecido zero exige zero barras mesmo com comprimento desconhecido; erro `#VALUE!` e fórmula originais preservados. |
| 1 | Quantidade desconhecida não equivale a zero na área total. |
| 1 | Fórmula direta de peso Cantoneiras com contador OCR comprovado; não aplica condição de fecho que essa fórmula não contém. |

As funções do auditor não usam a função de cálculo da aplicação como oráculo.
Os testes rejeitam entradas alteradas, resultados/cache incorretos, pesquisas
ambíguas, fórmulas incompatíveis e decisões manuais sem evento correspondente.

## Comandos e artefactos

```bash
.venv/bin/python -m pytest -q tests/test_planning_excel_comparison.py tests/test_planning_selected_ocr_audit.py
PYTHONPATH=. .venv/bin/python scripts/audit_planning_excel_comparison.py --population-proof c02-abocardar-population --source-proof c04-ocr-source-current --output c04-reconciled-cache-comparison
```

143 testes passaram, sem falhas nem ignorados (`c04-reconciled-cache-tests.log`).
A prova central anterior permanece válida: SHA do auditor de fontes, fingerprints
das tabelas, snapshots e gerações são verificados na transação de leitura.
As datas manuais são lidas na mesma transação que os resultados publicados.

A execução intermédia `c04-legacy-derived-comparison.json` terminou com 19
pendências e código 1. O código exato dessa execução foi preservado em
`c04-legacy-derived-auditor.py`, SHA `23904c55a003c8f936ec11fff8f7c05e745010530df0fd4f3e5c49200fe2e01a`.
Não atribuir a essa execução a revisão final do auditor.

`c04-reconciled-cache-final-state.json` confirma os 108 hashes, os 27 ficheiros
tracked preexistentes, as fontes centrais, as gerações e os processos. Nesta etapa
apenas o comparador e os seus testes mudaram; não houve escrita na base, reinício
de serviços nem publicação operacional.
