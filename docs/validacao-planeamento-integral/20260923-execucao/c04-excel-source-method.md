# C04 — Células originais, comprimentos e motivos de indisponibilidade

Revisão `2353787bc73e5a4e125f2ff51013252c7585aee55954af79ef6475fd9307b590`, 101 ficheiros no manifesto. Cópia isolada `planning_integral`, PostgreSQL localhost44164; aplicação localhost18113. Esta etapa não altera as fontes importadas nem os serviços operacionais.

## Problemas encontrados e corrigidos

O confronto direto com as células originais revelou **292 comprimentos de Cantoneiras** escritos como texto com milhares separados por espaço, por exemplo `1 543`. A projeção importada `length_mm` estava NULL, embora a célula `Comp.` e o cálculo Excel AM comprovassem o comprimento. O leitor de Planeamento recupera esses valores a partir da célula original quando o comprimento importado é desconhecido. Só aceita grupos completos de três dígitos; `1 54`, `1 2` e texto com unidades não são convertidos silenciosamente. São aceites espaço comum, espaço não separável e espaço não separável estreito. A célula e a projeção importada ficam intactas.

`c04-imported-lengths-before.json` regista as 292 divergências antes da republicação. `c04-imported-lengths-final.json` confere as 293 linhas de comprimento legado desconhecido: 292 recuperadas e uma ainda sem entrada. O resultado esperado é construído por decomposição independente dos grupos de milhares. A RAW e a origem real do formulário coincidem. O hash das colunas de origem de todas as 75735 linhas de Cantoneiras permanece igual.

Todas as 292 peças estão **ativas e com produção desconhecida**. Recuperar o comprimento permite calcular total necessário e propriedades com entradas suficientes; não inventa produção nem saldo. A auditoria aritmética recuperou 576 resultados antes indisponíveis no âmbito examinado: 292 comprimentos totais e 284 pesos unitários; nas outras oito peças, a propriedade exata continua sem resolução.

A auditoria encontrou também motivos genéricos e motivos incorretos propagados para derivados. Por exemplo, peso pendente desconhecido por falta de produção podia mencionar área/comprimento/densidade, apesar de estas propriedades serem conhecidas. O motor passa a propagar a causa efetiva: quantidade necessária, produção desconhecida, comprimento, propriedade, operação não aplicável ou quantidade zero. Zeros dedutíveis conservam zero e não exibem erro. A versão do contrato de cálculo passou a v2 e a projeção RAW a v12.

O painel **Cálculos** apresenta agora uma coluna com o motivo de indisponibilidade. A instrumentação do browser detetou ainda que os cabeçalhos das tabelas auxiliares eram expostos como células comuns; foi acrescentado `scope="col"`, e a verificação de cabeçalho passou.

## Comparação independente com Excel

`scripts/audit_planning_excel_comparison.py` junta os 717117 resultados da auditoria aritmética independente às células efetivas de cada linha Excel. Verifica os hashes dos ficheiros, do ledger aritmético e as versões publicadas. Conserva célula, fórmula original, cache, entradas, esperado, observado, diferença e classificação. Não chama o cálculo da aplicação para obter o esperado.

- AM de Cantoneiras é convertido de metros para os milímetros do contrato RAW.
- O texto `X` nas percentagens de Perfis só é interpretado como 100 quando a fórmula original contém explicitamente essa condição.
- Células não guardadas e campos sem coluna equivalente são contados à parte, não apresentados como igualdade numérica.
- Uma produção original vazia com contador selecionado desconhecido explica a preservação de desconhecido nos derivados, em vez do zero implícito do Excel. O ledger conserva ambos os factos. Isto não aprova a associação/seleção de OCR C01/C02.
- Saldos negativos convertidos para zero e semanas sem ano comprovado têm classificação explícita.
- Existência de OCR, preparação local, pesquisa aproximada ou cache antigo não constitui por si só uma justificação automática.

`c04-excel-comparison-classified.json` terminou deliberadamente com **código 1**, porque ainda há **20014 diferenças por investigar**: 847 Perfis e 19167 Cantoneiras. O ledger `-unresolved.jsonl.gz` conserva todas. A primeira comparação e as etapas intermédias também estão preservadas.

| Classificação | Verificações |
|---|---:|
| Mesmo valor numérico/textual | 416902 |
| Mesmo valor indisponível | 6335 |
| Célula original não guardada | 27089 |
| Regra sem coluna equivalente na macro | 105387 |
| Peça local sem Excel original | 44 |
| Semana sem ano comprovado | 64605 |
| Saldo negativo limitado a zero | 735 |
| Produção vazia permanece desconhecida | 76006 |
| Diferença por investigar | 20014 |

Há **207276 resultados indisponíveis** nas 23 regras auditadas: todos têm motivo e nenhum conserva a mensagem genérica anterior. A cobertura não inclui automaticamente os restantes campos/regras, todas as origens de entrada ou a matriz integral de casos C04.

## Validação

- `c04-excel-source-regression.log`: **126 testes passaram em 105,87s**, sem falhas/ignorados. Comando completo na checklist.
- `c04-excel-source-unit-tests.log`: 71 testes passaram; conjunto sobreposto, não somar como testes distintos.
- `c04-excel-source-population.json`: **717117 verificações em 83152 peças**, 23 regras e 493 casos de catálogo/20 famílias; zero diferenças aritméticas no âmbito declarado.
- `c04-imported-lengths-browser.json`: **292 linhas verificadas na API e três amostras no browser**, incluindo navegação para uma segunda página. Comprimento, total e motivos conferidos; zero erros JavaScript. Captura `c04-imported-lengths-reasons-browser.png` inspecionada.
- As primeiras tentativas de browser foram conservadas: uma pressupunha estados de produção/fecho que estas 292 linhas não têm; outra revelou a semântica dos cabeçalhos; outra precisava de navegar na paginação real. O teste final usa os estados efetivos e os controlos reais de paginação, sem alterar os dados para fabricar a amostra.
- `c04-excel-source-current-audit.json`: 83152 peças, 18977 operações principais e 104 conjuntos históricos, sem falhas.
- `c04-excel-source-population-audit.json`: população/índices corretos, nenhum fechado na carga ativa; identidades iguais à auditoria anterior à correção.
- `c04-excel-source-final-state.json`: 101 hashes da execução e 27 ficheiros tracked preexistentes preservados/verificados, fontes de comprimento intactas e serviços operacionais conservados.

Servidor isolado atual PID1449546, porta18113, sessão73420. Não foi iniciado worker isolado nesta etapa. A reconstrução da cópia isolada demorou 12,06s Perfis, 68,18s Cantoneiras e 31,82s capacidades; estes tempos não são prova de desempenho incremental C05.

## Próximo trabalho

Investigar as diferenças restantes, começando por pesos Cantoneiras (9926 unitários e 8020 pendentes) e diferenças de contadores/fontes. Perfis mantém diferenças de área, barras, quantidade e duas preparações locais com data distinta. Completar as restantes 20 regras, associação real das três origens, campos/formulários/PDF, matrizes funcionais/interface, Calibri, recuperação e publicação final. C00–C11 continuam em curso; C12 por executar. Nenhum checkpoint global foi aprovado por esta etapa.
