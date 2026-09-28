# C04 — Comparação Excel com produção OCR comprovada

24/09/2026. Revisão `4c91583691014c36cc7e3cc80b4c774197e80e63de84bc5280aef0bea3df72f4`,108 ficheiros. Aplicação inalterada desde `ff19b4af62c3a83724784447eed976fb0038f337b4143d547188ddb3171536a1`; manifesto anterior conservado em `execution-manifest-c02-abocardar-validated.json`. Mudaram apenas os dois auditores e os testes do comparador.

## Método

A opção `--source-proof` liga a comparação à prova independente de eventos centrais. O auditor de fontes lê novamente os2351 registos e confirma1389 totais de operação. Guarda também contagens/fingerprints integrais das folhas, registos, expansões, linhas importadas, decisões de associação e necessidades. O comparador recusa a prova se o código do auditor, o ledger, as entradas centrais ou as gerações publicadas tiverem mudado.

Cada diferença justificada exige:

1. Prova aprovada da mesma peça/operação, sem eventos incertos, IDs repetidos ou quantidades desconhecidas. A soma dos eventos tem de coincidir com o esperado da prova e com o contador publicado.
2. Quantidade necessária original igual à atual. Comprimento, stock e propriedade também têm de coincidir quando entram na fórmula. Alterações adicionais sem prova não são desculpadas por haver OCR.
3. Fórmula original reconhecida e cache antigo reconstruído: saldo, percentagem, perfis inteiros, área pendente, metros ou peso. O zero de uma célula Excel vazia é usado exclusivamente para reconstruir o cache, não para inventar produção atual.
4. Resultado atual recalculado independentemente a partir da produção provada. A contagem de perfis usa peças inteiras por barra; corte e operação secundária mantêm contadores distintos. No peso, a propriedade é exata; uma procura antiga diferente exige ainda a sua própria justificação de catálogo.

O ledger regista células, fórmula, eventos, resultado antigo e resultado novo. Nunca se aceita uma diferença apenas porque o rótulo da aplicação diz OCR. Uma fórmula diferente, um cache não explicado ou entradas alteradas continuam pendentes.

## Resultados

`c04-ocr-counter-auditor-tests.log`:**81 testes passaram em0,08s**,sem falhas/ignorados. Cobrem as regras anteriores e os novos confrontos; rejeitam provas incompletas, eventos repetidos, operação/área/quantidade erradas, caches/fórmulas divergentes e resultados arbitrários. São testes dos auditores; não constituem nova regressão da aplicação, que não mudou.

`c04-ocr-source-current.json`:2351 registos centrais,1389 totais(336Perfis/1053Cantoneiras),zero falhas no âmbito da prova. Esta verificação não aprova a ingestão viva nem o original Windows; a matriz completa de decisões humanas, conflitos e fallback continua separada.

`c04-ocr-counter-comparison.json`:966573 confrontos em83152 peças,no âmbito das23 regras aritméticas. **1695 diferenças justificadas**(403Perfis/1292Cantoneiras). De1802 pendentes passaram a **107**(88Perfis/19Cantoneiras). O programa termina com código1 e conserva todas as107 no ledger de pendências. Nenhum resultado pendente foi convertido em aprovação.

Comandos:

```bash
.venv/bin/python -m pytest -q tests/test_planning_excel_comparison.py tests/test_planning_selected_ocr_audit.py
PYTHONPATH=. .venv/bin/python scripts/audit_planning_selected_ocr.py --output c04-ocr-source-current
PYTHONPATH=. .venv/bin/python scripts/audit_planning_excel_comparison.py --population-proof c02-abocardar-population --source-proof c04-ocr-source-current --output c04-ocr-counter-comparison
```

## Pendências concretas

| Área/campo | Confrontos pendentes |
|---|---:|
| Perfis: área unitária / total | 12 / 15 |
| Perfis: perfis inteiros | 6 |
| Perfis: quantidade prevista / área pendente | 10 / 10 |
| Perfis: peso | 25 |
| Perfis: semana prevista | 2 |
| Perfis: saldo / percentagem cortada | 3 / 5 |
| Cantoneiras: saldo / quantidade prevista | 4 / 4 |
| Cantoneiras: peso | 11 |

A investigação das células localizou: dimensões ausentes e tubo20×10 sem interior válido; valores derivados literais em lugar de fórmulas; alguns saldos/percentagens ainda baseados na quantidade legada N; uma fórmula de área deslocada; pesos negativos com uma variante da fórmula original; e duas preparações locais com datas próprias. Estes diagnósticos ainda precisam de justificação/teste por campo antes de retirar os confrontos da lista. Não representam automaticamente erros novos da aplicação.

Exemplos preservados no ledger: Perfis2619,BT literal6 versus cálculo5;Perfis22,AS literal4 com4 já produzidas;Perfis5066,AX consulta colunas deslocadas;Perfis5121,tuboD20/espessura10 com cache de área positiva;Cantoneiras47033,peso antigo negativo numa fórmula direta;Perfis48/49,semanas de preparações locais. As20 regras fora desta auditoria e a restante matriz integral também continuam pendentes.

## Preservação

`c04-ocr-counter-final-state.json`:108 hashes da execução,27 tracked preexistentes,fontes centrais e gerações3559/3560 conferidos. Nenhuma escrita de dados, reconstrução, migração ou reinício nesta etapa. Servidor isolado1629587,porta18113;serviços operacionais preservados. Checklist conserva13 checkpoints,58 critérios,43 regras e6 casos. C00–C11 em curso,C12 por executar.
