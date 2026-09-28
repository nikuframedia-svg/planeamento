# Produto — preenchimento automático da macro de planeamento

**Atualização de 15/09/2026:** o fluxo de receção de PDFs, conector de visão configurável, cruzamento CPIS, revisão e geração de uma cópia conferível da macro está implementado. Os três PDFs foram processados integralmente pela API Grok 4.6 sob o contrato visual v3. O comparador independente confirmou as 10 necessidades e 276 peças esperadas, sem omissões, inclusões ou diferenças nos campos críticos. Os três dossiês permanecem em conferência por dúvidas documentais e bloqueios reais do snapshot atual da macro; isso impede uma cópia operacional prematura. A instalação, utilização, mapeamento de colunas, diagnóstico e limites estão no [guia de dossiês de planeamento](/home/luis/projects/kanban-mes-mtg2/docs/dossies-planeamento.md). O corpus inicial está congelado, mas a precisão fora da amostra continua dependente do piloto com documentos novos.

## Âmbito corrigido

A primeira etapa é substituir o trabalho de copiar à mão os dados dos PDFs para a macro/ficheiro de planeamento existente. O termo «macro de planeamento» é usado aqui para o destino desse preenchimento, conforme a clarificação do utilizador. Não se está a definir nesta fase um novo nível de planeamento geral da fábrica.

**Entrada: PDFs e contexto do CPIS. Saída: as linhas da macro de planeamento preenchidas com os dados correspondentes.**

A automatização da sequência, das máquinas concretas e das datas vem depois, utilizando essa informação estruturada. A fase inicial não depende de um formulário nem de alguém ter criado previamente a OF no ficheiro de planeamento.

## O processo atual e a substituição pretendida

Hoje, uma pessoa recebe o dossiê, identifica os desenhos relevantes para Vanguard/serrote, interpreta as peças e quantidades, procura a OF e o contexto no CPIS e transcreve os campos para o planeamento.

O sistema deve executar essa mesma preparação e produzir um resultado conferível no formato utilizado pela operação:

1. Detetar um PDF novo ou uma revisão na pasta acordada.
2. Identificar a OF e conferir a ligação à OV no CPIS.
3. Ler a distribuição dos desenhos para Vanguard e serrote.
4. Localizar os desenhos e as variantes selecionadas.
5. Extrair referências, quantidades, materiais, perfis, dimensões e restantes indicações que correspondam aos campos de destino.
6. Completar o contexto da OF pelo CPIS e aplicar as regras de normalização já definidas.
7. Preparar as linhas e preencher o destino acordado, preservando a estrutura e os cálculos da macro.
8. Identificar apenas os campos ambíguos ou incompatíveis que precisem de revisão.

Não se deve exigir que a pessoa volte a escrever toda a ficha para confirmar a extração.

## Contrato de preenchimento: campo a campo

O trabalho de implementação começa por mapear cada coluna da macro para a sua fonte e regra. Esse mapa é reutilizável; não se cria uma configuração nova para cada OF.

| Grupo de campos | Fonte e regra |
|---|---|
| OF e OV | Capa/nome controlado do PDF, conferidos contra o CPIS |
| Cliente, designação e estado da OF | CPIS, conservando separadamente nomes ou designações diferentes presentes no documento |
| Desenho e referência da peça | Índice e desenho; preservar também a referência da variante quando não for igual à referência do desenho |
| Quantidade necessária | Quantidade selecionada/total efetiva; distinguir quantidade por conjunto, total e número identificador de uma variante |
| Material e qualidade | Indicação técnica do desenho, com origem identificada |
| Perfil, diâmetro, largura, altura, espessura e comprimento | Desenho ou catálogo de perfis validado; conservar o valor original e a normalização |
| Vanguard/serrote | Cruzes na matriz de distribuição associadas à referência correta |
| Operações, ângulos e observações | Indicações explícitas do documento, depois de definida a equivalência com os campos da macro |
| Dados do CPIS que já alimentam o planeamento | Mesma origem e significado, sem os reinterpretar como novas datas calculadas |
| Áreas, metros, percentagens ou outros valores calculados | Fórmulas existentes verificadas ou cálculo equivalente, sem os apresentar como valores lidos no PDF |
| Execução já registada | Preservar e reconciliar a fonte existente; um dossiê de fabrico não é um registo de produção realizada |

Um campo sem informação na fonte não deve receber um valor inventado. Por exemplo, a distribuição «Serrote» não identifica automaticamente um dos serrotes concretos. Uma cota angular do desenho também não deve ser colocada na coluna de ângulo sem conhecer a convenção utilizada nessa coluna.

## O que a amostra já demonstrou

Foram analisadas as 101 páginas dos três PDFs fornecidos, com OCR e conferência visual. Identificaram-se dez linhas para Vanguard/serrote:

- OF263785: três referências de Vanguard, com 36 peças cada.
- OF265941: quatro referências de Vanguard e uma de serrote, num total de 156 peças.
- OF265931: duas variantes para serrote, com seis peças cada.

Oito linhas correspondem às que já tinham sido introduzidas à mão no planeamento, com referência normalizada, quantidade, comprimento e qualidade conferidos. As duas da OF265931 podem ser preparadas a partir do PDF e do CPIS mesmo sem existir uma linha anterior no plano importado.

Esta amostra conferida é agora o primeiro corpus de regressão do importador. Não demonstra precisão fora da amostra. A leitura autónoma combina o modelo visual, extração pela estrutura do dossiê, evidência por campo, validações técnicas, resolução de catálogo e comparação com CPIS/macro; uma saída JSON válida, isoladamente, não torna uma linha aceitável.

## Como tornar esta primeira etapa um produto

### Uma entrada automática

O utilizador mantém o processo de disponibilizar os dossiês. O sistema acompanha a pasta acordada, regista cada documento e processa-o em segundo plano. Deve conseguir retomar uma leitura interrompida e evitar nova importação do mesmo conteúdo.

### Uma extração com origem identificada

Cada valor extraído mantém a ligação ao documento, página e região de onde veio. O sistema distingue índice, desenho, tabela de variantes e lista de conjunto para não criar várias necessidades a partir das diferentes representações da mesma peça.

A leitura é organizada por tipos de documento e regras reutilizáveis. Não deve depender de números de OF ou de páginas fixas codificados a partir dos três exemplos.

### Um resultado no destino de trabalho

A saída corresponde às colunas que a operação já utiliza. Durante a validação, é produzida numa cópia ou área de preparação para comparação. A escrita regular na macro fica suportada por um mapeamento explícito de campos, preservação de fórmulas/estrutura e controlo de versões.

Uma base estruturada pode guardar os dados e a proveniência por trás deste processo. Isso prepara o motor de planeamento seguinte sem obrigar a empresa a mudar primeiro toda a sua interface de trabalho.

### Revisão concentrada nas dúvidas

A interface mostra o que foi preparado, o que falta resolver e a evidência da dúvida. A revisão pode corrigir um número manuscrito, escolher entre referências ambíguas ou resolver uma revisão incompatível. Não é um formulário obrigatório para voltar a introduzir os dados de cada OF.

### Atualizações sem duplicação

Receber o mesmo PDF não deve acrescentar outra cópia das linhas. Uma alteração de quantidade ou desenho deve ser relacionada com a necessidade anterior, preservando a produção já registada. Uma mudança de especificação depois de haver execução fica identificada, sem assumir que as peças anteriores satisfazem a revisão nova.

A ligação ao CPIS consulta também OF ainda ausentes do planeamento. O estado mais recente disponível deve impedir novas ações em OF fechadas, conforme a regra já confirmada, conservando o histórico.

## Critério de sucesso da primeira entrega

A primeira entrega está cumprida quando um conjunto representativo de dossiês novos consegue originar o preenchimento correto das colunas abrangidas, sem transcrição integral por uma pessoa.

A avaliação compara o resultado com uma conferência independente dos PDFs e mede:

- Referências omitidas ou indevidamente incluídas.
- Erros de variante, quantidade, material, dimensões e distribuição.
- Campos críticos errados que não foram assinalados.
- Percentagem de linhas que prosseguem sem correção.
- Tempo de trabalho humano poupado por dossiê.
- Comportamento perante revisões, importações repetidas e falhas de processamento.

As dez linhas analisadas são casos iniciais úteis, mas a avaliação deve incluir dossiês que não tenham sido usados para ajustar a extração. O Excel manual ajuda a comparar resultados; divergências têm de ser conferidas no documento, porque o preenchimento manual também pode conter erros.

## Etapa seguinte: automatizar o cálculo do planeamento

Depois de a entrada de dados estar estruturada e fiável, acrescenta-se o cálculo de carga, atribuição a máquinas, sequência e datas. Esse motor utiliza as necessidades produzidas pela primeira etapa, o trabalho realizado e as regras de tempos, capacidade, prioridades e prazos.

Essas regras são necessárias ao cálculo posterior. Não devem impedir que se entregue primeiro a automatização do preenchimento da macro, nem ser usadas para alargar antecipadamente o âmbito à gestão de toda a fábrica.

A sequência de produto fica, portanto: **substituir a transcrição dos PDFs → consolidar os dados de trabalho → automatizar o planeamento sobre esses dados**.

Fontes: [análise dos PDFs](/home/luis/projects/kanban-mes-mtg2/docs/analise-pdfs-planeamento-2026-09-12/analise.md), [amostra preenchida](/home/luis/projects/kanban-mes-mtg2/docs/analise-pdfs-planeamento-2026-09-12/amostra-preenchida.csv) e [regras operacionais confirmadas](/home/luis/projects/kanban-mes-mtg2/docs/planeamento-mtg2-2026-09-09/regras-confirmadas-2026-09-10.md).
