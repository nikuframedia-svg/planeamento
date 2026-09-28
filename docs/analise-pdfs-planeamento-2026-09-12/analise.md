# Dos PDFs ao planeamento — análise dos três dossiês

É viável construir um sistema que leia os PDFs, identifique os desenhos destinados a Vanguard/serrote e crie as necessidades de produção preenchidas automaticamente. O ficheiro de planeamento atual é o resultado do trabalho de transcrição que se pretende substituir. Não é uma condição para importar uma OF nova e não é necessário preencher um formulário por trabalho.

O fluxo proposto é **PDF + CPIS → necessidades estruturadas → cálculo de carga → distribuição pelas máquinas e calendário**. O Excel existente serve, nesta análise, para conferir a extração contra exemplos já preparados pela empresa. O programa pode voltar a produzir um Excel de saída, se for necessário conservar esse formato.

## O que foi efetivamente analisado

Foram processadas por OCR local as 101 páginas dos três anexos: 75 de `OF263785.pdf`, 9 de `OF265931.pdf` e 17 de `OF265941.pdf`. Não foi encontrada uma camada de texto extraível em nenhuma página. Foram inspecionados visualmente os índices, os desenhos selecionados e as tabelas que determinam as quantidades.

O cruzamento foi realizado por consultas de leitura ao CPIS e ao planeamento importados no PostgreSQL. O snapshot de perfis utilizado é `mtg2_aa2d59af81541c37`, carregado em 10/09/2026 às 12:20 UTC. Não é uma consulta em direto ao CPIS de 12/09. Os PDFs foram fornecidos pelo utilizador; não foram escritos dados na base operacional nem no XLSM.

Resultado da amostra: **10 linhas selecionadas, 7 de Vanguard e 3 de serrote, num total de 276 peças necessárias**. Oito têm correspondência única no planeamento existente, com igualdade de referência normalizada, quantidade, comprimento e qualidade. Duas pertencem a uma OF presente no CPIS e ausente do planeamento importado.

Esta amostra combina OCR com interpretação visual e conferência. Não é um importador autónomo já integrado na aplicação, nem demonstra uma taxa de acerto automática em dossiês novos. O OCR simples da página completa não recuperou de forma fiável os cabeçalhos verticais, as cruzes das matrizes e todos os números manuscritos.

## As linhas obtidas dos PDFs

Os dados técnicos da tabela seguinte foram lidos nos PDFs. O Excel foi consultado posteriormente para comparação.

| OF | Referência da peça/variante | Distribuição no PDF | Perfil no PDF | Comprimento (mm) | Peças | Qualidade | Página do desenho | Comparação com o plano |
|---|---|---|---|---:|---:|---|---:|---|
| 263785 | 1234.T.120 | Vanguard | UPN80 | 480 | 36 | S355J2 | 32 | Linha 6963: quantidade, comprimento e qualidade iguais |
| 263785 | 1234.T.121 | Vanguard | UPN80 | 346 | 36 | S355J2 | 33 | Linha 6964: quantidade, comprimento e qualidade iguais |
| 263785 | 1234.T.122 | Vanguard | UPN80 | 500 | 36 | S355J2 | 34 | Linha 6965: quantidade, comprimento e qualidade iguais |
| 265931 | CI25J001 | Serrote | Tubo Ø114 × 3 | 1200 | 6 | S275JR | 4 | OF existente no CPIS, sem linha no plano importado |
| 265931 | CI25J003 | Serrote | Tubo Ø60 × 3 | 1760 | 6 | S275JR | 5 | OF existente no CPIS, sem linha no plano importado |
| 265941 | pr.3 | Serrote | R80 | 539 | 52 | S355J2 | 6 | Linha 6932: quantidade, comprimento e qualidade iguais |
| 265941 | pr.4 | Vanguard | HEB320 | 12450 | 26 | S355J2 | 7 | Linha 6933: quantidade, comprimento e qualidade iguais |
| 265941 | pr.5 | Vanguard | HEB320 | 12450 | 26 | S355J2 | 8 | Linha 6934: quantidade, comprimento e qualidade iguais |
| 265941 | pr.8 | Vanguard | HEB320 | 13450 | 26 | S355J2 | 9 | Linha 6935: quantidade, comprimento e qualidade iguais |
| 265941 | pr.9 | Vanguard | HEB320 | 13450 | 26 | S355J2 | 10 | Linha 6936: quantidade, comprimento e qualidade iguais |

São necessidades brutas do dossiê, não produção nova nem saldos de execução confirmados. Não se escreveram valores em `Ser.` ou `Aboc.`.

### OF263785: o índice seleciona, o desenho fornece a quantidade

Na página 1, as referências `1234.T.120`, `1234.T.121` e `1234.T.122` estão marcadas na coluna **Vanguard**. As células de quantidade dessas linhas do índice estão vazias. Os desenhos das páginas 32–34 indicam **36 peças em cada cartucho**. Um importador que exigisse quantidade no índice perderia estes três trabalhos.

O plano manual usa as referências sem pontos e o perfil `UPN80x45`. O PDF escreve `UPN80`; na página 33, a secção está cotada com 80 e 45 mm. A normalização deve conservar o valor original e a sua origem.

Os desenhos também mostram pormenores que não podem desaparecer numa transcrição: ângulos de 67,5° nas páginas 32/34; ângulos de 68° e chanfros assinalados `4 × 45°` na página 33. A coluna `Ang,` do Excel vale zero nestas três linhas. Isto exige esclarecer o significado desse campo antes de o preencher com uma cota do desenho; não foi tratado automaticamente como erro do Excel.

O nome do ficheiro fornece a OF. As listas de expedição contêm a OV2602409, permitindo conferir a ligação ao CPIS. O documento refere MCA; o CPIS identifica TECPOLES GMBH como cliente. A identidade não pode depender apenas de igualdade do nome de cliente.

### OF265931: criar linhas que ainda não existem no planeamento

A matriz da capa marca **serrote** para `CI23JJ01` e `CI23JJ02`, os desenhos de corte dos dois fustes. As páginas 4 e 5 contêm tabelas com várias versões. Só a linha **Fuste 3,0m Fix. Flange** tem a quantidade **6** preenchida em cada uma.

As variantes selecionadas são `CI25J001` e `CI25J003`. As referências dos desenhos são `CI.23/14.A4.J01` e `CI.23/14.A4.J02`. O sistema precisa de guardar separadamente referência do índice, referência do desenho e referência da variante. Não são strings intercambiáveis sem contexto.

Não se devem importar as restantes variantes das tabelas. Os números da coluna `Ref` identificam variantes e não são quantidades. Também não se deve importar para serrote a barra `CB01C504` da página 8: na matriz, o seu destino indicado é guilhotina.

A OF existe no CPIS importado: **OV2607672, ECLIPSE DIFFUSION, Em Aberto, data CPIS 02/10/2026**. Não tem linhas no plano de perfis nem no de cantoneiras importados. Portanto, os dois trabalhos podem ser preparados a partir do PDF e enriquecidos pelo CPIS sem existir transcrição prévia no Excel.

### OF265941: divisão explícita entre serrote e Vanguard

A página 2 marca `pr.3` para serrote e `pr.4`, `pr.5`, `pr.8`, `pr.9` para Vanguard. Os desenhos nas páginas 6–10 fornecem as cinco necessidades da tabela.

Em `pr.3`, as quantidades por conjunto são 26 + 26, e o total é 52. São representações da mesma necessidade: não se somam novamente ao total. Nas restantes quatro peças, o total manuscrito de 26 coincide com a quantidade do conjunto.

O PDF contém **“3ªPRIORIDADE = 52X”**, também presente na designação do CPIS. É possível capturar automaticamente essa indicação. Falta definir o seu âmbito antes de a comparar com prioridades de outras obras: o número isolado não demonstra uma classificação global da fábrica.

O PDF escreve `HEB320`; o plano usa `HEB320B`. A correspondência por OF, referência, comprimento, quantidade e qualidade é única, mas o importador deve resolver a nomenclatura através do catálogo, preservando a diferença original.

As oito linhas já existentes na amostra têm a coluna `Máquina Corte` vazia. A distribuição dos PDFs permite acrescentar uma indicação de destino. **Serrote** continua a ser um grupo: não determina sozinho qual dos serrotes concretos deve receber o trabalho.

## O preenchimento automático

| Informação | Fonte que o sistema deve utilizar |
|---|---|
| Identificação da OF | Capa do dossiê ou nome controlado do ficheiro; conferir OF/OV no CPIS |
| OV, cliente comercial, designação e estado | CPIS; conservar também os valores originais do documento |
| Desenhos destinados a Vanguard/serrote | Matriz de distribuição e cruzes nas células, associadas à referência da linha |
| Referência técnica, perfil, dimensões, qualidade e quantidade | Desenhos e linhas efetivamente selecionadas nas tabelas de variantes |
| Revisão e detalhes técnicos | Cartucho, notas e geometria cotada, com página de origem |
| Indicações de prioridade e entrega no dossiê | Extração literal, com âmbito e significado separados da prioridade calculada |
| Data CPIS | Consulta ao CPIS; as capas de OF265931/OF265941 têm o campo de entrega prevista vazio |
| Produção realizada | Fonte de execução reconciliada; os dossiês fornecidos não provam o que já foi produzido |
| Máquina concreta para o grupo serrote | Regra de compatibilidade e capacidade, após a extração |
| Data de corte, início/fim e sequência | Resultados do motor de planeamento, não campos que alguém tenha de preencher por OF |

## Como construir o circuito

1. Detetar um PDF novo ou revisto na pasta acordada. Guardar identidade, versão e hash para não importar duas vezes a mesma necessidade.
2. Classificar páginas e corrigir orientação. Localizar a matriz de distribuição, ler os cabeçalhos verticais e identificar as cruzes por célula. As cruzes indicam destinos; não estabelecem, por si só, a ordem temporal das operações.
3. Resolver cada referência selecionada para o desenho ou tabela correspondente. Identificar variante ativa, quantidade total e revisão. Índice, desenho e lista de expedição são fontes da mesma peça, não três necessidades distintas.
4. Extrair campos com uma combinação de OCR, interpretação visual e regras por tipo de documento. Guardar página e região que sustentam cada campo. Conferir quantidades contra conjuntos/totais quando existam.
5. Associar ao CPIS e aplicar a regra de OF aberta usando o estado mais recente disponível. Uma OF sem transcrição prévia pode gerar linhas novas. Divergências de identidade, revisão ou quantidade ficam identificadas, sem correção silenciosa a partir do Excel antigo.
6. Criar ou atualizar as necessidades na base do planeador. Uma revisão modifica a necessidade correspondente; não incrementa produção realizada nem acrescenta outra cópia da mesma peça. A revisão humana concentra-se nas ambiguidades, sem preenchimento integral de fichas.
7. Calcular carga, selecionar máquinas compatíveis e construir o calendário. Publicar a proposta com o prazo de referência, início/fim calculados e atrasos identificados.

## O que os PDFs resolvem e o que falta para calendarizar

Estes documentos resolvem uma parte importante da preparação que vinha a ser feita manualmente: **qual peça, para que grupo de máquina, em que quantidade, com que perfil/material e dimensões**. Incluem ainda furação, recortes, chanfros e revisões que podem melhorar a estimativa de trabalho.

Para gerar datas e sequência operacional, falta ligar essa informação a três regras principais:

- **Prazo e prioridade:** as três OF não têm Picking positivo no snapshot consultado. O CPIS fornece 15/01/2027, 02/10/2026 e 29/10/2026, respetivamente. É preciso a regra que transforma o compromisso final em necessidade da MTG2, reservando o trabalho posterior. O W8/2027 da OF263785 e a data CPIS de janeiro devem conservar os seus significados; não são automaticamente a mesma data nem um erro. A prioridade textual da OF265941 necessita de âmbito para participar na comparação entre obras.
- **Duração:** usar o perfil, quantidade, cortes, furos, recortes e preparações com tempos válidos por recurso. Por exemplo, `pr.4` contém anotações de 16 × Ø22 e 1 × Ø13. Estimar apenas pela secção de corte não representa todo esse trabalho. O PDF não fornece uma duração de execução comprovada.
- **Capacidade e início possível:** horários úteis, operadores partilhados, carga já ocupada, compatibilidades dos serrotes e condições de libertação de operações. A disponibilidade de matéria-prima continua fora da integração automática desta fase, conforme o âmbito já definido.

O motor pode então comparar alternativas por cumprimento de prazos e preparações, calculando as datas de corte em vez de as pedir a alguém. O preenchimento a partir dos PDFs é viável com esta estrutura; a amostra não é ainda um motor de calendarização implementado.

## Resultados e fontes

- [Amostra preenchida, 10 linhas em CSV](/home/luis/projects/kanban-mes-mtg2/docs/analise-pdfs-planeamento-2026-09-12/amostra-preenchida.csv).
- [Linhas, proveniência, comparações e limitações em JSON](/home/luis/projects/kanban-mes-mtg2/docs/analise-pdfs-planeamento-2026-09-12/linhas-extraidas.json).
- [OF263785.pdf](/home/luis/.codex/attachments/191b4b8e-1a5e-4f99-99ce-c85ac7ff340b/OF263785.pdf): índice p. 1; desenhos p. 32–34; listas p. 63–69.
- [OF265931.pdf](/home/luis/.codex/attachments/3fc711ec-14b7-4673-b912-47a3e15d366e/OF265931.pdf): matriz na capa; variantes de serrote p. 4–5; exclusão de guilhotina p. 8.
- [OF265941.pdf](/home/luis/.codex/attachments/dfe73c88-f0b0-4339-bc27-82d6af437dc5/OF265941.pdf): identificação/prioridade p. 1; índice p. 2; desenhos p. 6–10.
