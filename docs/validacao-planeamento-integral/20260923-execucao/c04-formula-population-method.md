# C00/C04 — Origens, aritmética e quantidade estruturada

Revisão: `955de2782bef108804a916ea771aed6bc006623d5526c9e8ded75348b2bd76d2` (98 ficheiros no manifesto). Ambiente: cópia integral `planning_integral`, localhost44164; browser isolado18113. Fontes operacionais intocadas.

## Cobertura comprovada

- `c00-contract-origin-inventory.json`:61 campos RAW de Perfis,68 de Cantoneiras,40 entradas de catálogo de formulário em cada área. Nenhum campo editável da RAW ausente desses catálogos. Todas as43 regras têm âncoras de origem, entradas, unidade e exemplo esperado independente. Os nomes/validações dos Excel e as20 famílias de perfil estão incluídos. Isto inventaria os contratos; não prova sozinho todos os controlos efetivamente renderizados.
- `c04-formula-population.json`:83152 peças,717117 verificações aritméticas (111221 Perfis;605896 Cantoneiras), zero diferenças.509265 resultados conhecidos e207852 indisponíveis comparados como tal.493 casos adicionais exercitam as20 famílias, incluindo todas as correspondências exatas presentes nas tabelas de propriedades.
- Regras cobertas por esta auditoria de população: F04–F11, F13–F19, G02–G05 e G08–G11. F17 compara7411 linhas sem preparação local com BS ou a sugestão do layout; as quatro linhas com preparação local ficam fora desse confronto de origem. A regra de substituição manual continua coberta por testes de gravação/cálculo.
- O ledger comprimido `c04-formula-population-rows.jsonl.gz` conserva a identificação de cada peça, entradas, propriedade/célula aplicável, resultado esperado, observado e igualdade para cada verificação. A tolerância é a do plano: `max(1e-6, abs(esperado) × 1e-8)`.

## Diferença encontrada e corrigida

Em12 linhas históricas de Perfis, `quantity_planned` herdava a coluna N enquanto o cálculo original AP usa a entrada estruturada AH (`QTD [un,]`). A leitura de comparação PDF também usa AH. O problema não aparecia numa mera comparação de reconstrução incremental/completa: ambas usavam a mesma entrada errada.

`planning.line_data` passa a ler AH em Perfis. Uma célula presente mas vazia/inválida permanece desconhecida; zero permanece zero; só a ausência do campo permite o fallback legado. Cantoneiras conserva o seu contrato. A mudança de contrato de projeção v9→v10 invalida as gerações antigas.

Exemplos independentes:

| Linha Excel | N preservada | AH aplicada | Área AP esperada e observada |
|---|---:|---:|---:|
|43|62|130|81250 mm²|
|519|175|400|349800,6340139555 mm²|
|568|0|40|12566,370614359173 mm²|
|1369|200|700|520667,9314518875 mm²|
|4347|40|1|962,1127501618741 mm²|

`c04-structured-quantity-before.json` conserva o erro anterior. `c04-structured-quantity-final.json` verifica7413 linhas de origem, a leitura do formulário e do PDF,7411 linhas RAW sem substituição local e as duas preparações locais conservadas. Nas12 divergências N/AH, a leitura real da origem manual também coincide com AH. O hash de todos os dados de origem antes/depois da reconstrução é igual. Nas12linhas corrigidas, a área coincide com AP.

`c04-structured-quantity-browser.json` comprova as12 linhas em Histórico após reinício do servidor isolado: quantidade AH e área AP nas células visíveis, N e AH preservadas no detalhe original, nenhuma linha passa para a população ativa. Captura inspecionada: `c04-structured-quantity-browser.png`.

## Validação e limites

- 32 testes unitários passaram, incluindo AH130/0/vazia/inválida, fallback só quando o campo está ausente e contrato Cantoneiras intacto.
- 63 testes da leitura comum, campos, necessidades e cálculos passaram (`c04-structured-quantity-tests.log`).
- 101 testes de regressão RAW, incremental, OCR, produtividade, capacidade, pré-visualização e população passaram (`c04-structured-quantity-regression.log`). Estes conjuntos têm sobreposição; não somar como testes distintos.
- `c04-quantity-current-audit.json`:83152 peças,18977 operações principais,104 conjuntos históricos,zero falhas. `c04-quantity-population-audit.json`:populações e índices corretos; nenhuma fechada na carga ativa; identidades iguais à baselineF12.

A expectativa aritmética é calculada independentemente, a partir das entradas tipadas e contadores selecionados. Não chama o motor em teste para obter o esperado. A resolução de propriedades é confrontada com tabelas extraídas diretamente dos Excel e com as funções VBA transcritas independentemente.

**Ainda falta C04 integral:** seleção/associação das fontes (C01/C02); confronto por campo de todos os valores Excel guardados e fórmulas originais com a aplicação; restantes20 regras, métodos de capacidade e casos obrigatórios completos; verificação integral dos motivos de indisponibilidade e paridade efetiva da interface. A auditoria de23 regras não aprova os43 requisitos nem o checkpoint inteiro. O inventário referencia explicitamente as provas de população disponíveis e mantém as restantes sem aprovação.
