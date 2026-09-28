# Análise aprofundada: Excel, CPIS, planeamento e produção OCR

Data: 20/09/2026. Auditoria aos ficheiros reais, PostgreSQL central, arquivo PDF,
código e respostas da API. As consultas desta auditoria não alteraram produção,
ordens CPIS ou ficheiros Excel.

## Conclusão

O Excel contém ligações reais ao CPIS. A implementação anterior identificou
apenas parte dessas ligações e foi apresentada como mais completa do que está.
Há falhas concretas na associação da produção, na identificação das áreas e na
conclusão das operações. A publicação da página e os testes anteriores não
demonstram que estas regras de negócio estão corretas.

O bloqueio observado para a consulta SQL direta é de rede: deste servidor,
`10.200.10.30:5432` não respondeu ao teste TCP. A autenticação nem chegou a ser
tentada pelo servidor CPIS. Não é evidência de credenciais erradas ou de que o
Excel não tenha acesso no PC da fábrica.

## 1. O que existe dentro dos Excel

### Ligação às ordens

As duas macros contêm uma ligação ODBC `CPIS` com:

- Servidor `10.200.10.30`, porta `5432`, base `cpis`.
- Utilizador guardado na configuração; valor omitido desta auditoria.
- Sem palavra-passe guardada em `xl/connections.xml`.
- Consulta à vista `public.ordensfabrico_listagem_excel_vw`.
- A consulta de Perfis acrescenta `OF > 250000`; Cantoneiras consulta a vista inteira.

A configuração Excel indica `ReadOnly=0`. Isto não demonstra quais são os
privilégios efetivos da conta. O novo diagnóstico força uma transação de leitura.

### Segunda ligação, encontrada no Power Query

Dentro do pacote DataMashup de Perfis existe esta consulta:

```sql
select * from mtg2.pickingprodcab_pesq_vw
```

É executada por `Odbc.Query("dsn=cpis", ...)`. O Power Query renomeia `id`, `of`
e `semana` para `ID`, `OF` e `Semana`, remove o prefixo OF e carrega a folha
`Picking`. A consulta «Picking Planeamento» referencia «Picking CPIS».

Na cópia atual há 784 registos de Picking, para 784 OFs: 550 têm semana `0` e
234 têm uma semana entre 1 e 53. O valor `0` não é uma semana de calendário.
A folha não fornece um ano separado; não se deve inventá-lo a partir do ano
atual ou do identificador numérico.

O conector implementado consulta apenas a vista de ordens. Ainda não consulta
esta vista de Picking diretamente.

### VBA e atualização

Foram inspecionados os módulos VBA, sem os executar. Não foi encontrada uma
credencial de base de dados nos módulos inspecionados. As referências a
password encontradas em Perfis são pedidos de autorização para ações do livro.
O código `Workbook_Open` encontrado está comentado. Atualizar uma tabela
dinâmica também não prova que a consulta ODBC ao CPIS foi executada.

As datas de gravação internas são 18/09/2026 07:40:40 UTC para Perfis e
07:26:47 UTC para Cantoneiras. São datas de gravação dos ficheiros, não
comprovativos da última consulta CPIS. Os hashes dos ficheiros locais coincidem
com os das versões importadas. A reimportação de 20/09 atualizou `loaded_at`,
sem demonstrar uma nova leitura CPIS.

Evidência: [ligações e Power Query](planeamento-cpis-2026-09-20/auditoria-ligacoes-excel.json).

## 2. Porque ainda não foi possível ler o CPIS daqui

A rota observada para `10.200.10.30` sai pela interface pública do servidor.
O teste TCP ao endereço e porta retirados do Excel terminou por timeout em
6 segundos. Não existe nesta configuração uma rota privada utilizável para
essa rede.

A ponte SSH ativa encaminha:

| Sentido | Destino |
|---|---|
| Servidor → PC | Aplicações web nas portas 8080, 8100 e 8101 |
| PC → servidor | PostgreSQL central, através de `localhost:15432` no PC |

Esta ponte não encaminha o CPIS da fábrica para o servidor e não disponibiliza
uma shell no PC. Os endpoints de saúde dos dois MES responderam e identificaram
instâncias Windows. Isso comprova as aplicações acessíveis, não a ligação CPIS.

O utilizador não sabe se existe uma VPN. A existência de uma VPN não foi
assumida. Também não foi assumido que falta criar uma conta nova: primeiro há
que testar a configuração ODBC que o Excel já utiliza no PC.

Foi preparado o script
[`diagnose_cpis_readonly.ps1`](/home/luis/projects/pc-suite-kit/diagnose_cpis_readonly.ps1).
No PC onde o Excel atualiza:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\OCR-Suite\kit\diagnose_cpis_readonly.ps1 -Workbook "CAMINHO_REAL\Met2_Plan_Perfis.xlsm"
```

O script lê a ligação do XLSM, usa o DSN existente, força uma transação
`REPEATABLE READ READ ONLY`, verifica a base efetiva e consulta colunas,
contagens, estados de OFs de exemplo, Picking e nomes de vistas relacionadas.
Guarda um relatório sem credenciais e faz rollback da transação de leitura.
Um erro de autenticação, DSN ou rede é registado por SQLSTATE, sem divulgar
a mensagem original que possa conter dados de ligação.

**Este script ainda não foi executado no PC nem validado num PowerShell local.**
O ambiente desta auditoria é Linux e não dispõe dessa sessão Windows. Não é
apresentado como evidência de acesso direto conseguido.

## 3. O universo real de ordens

Valores das duas cópias importadas, não da base CPIS ao vivo:

| Indicador | Perfis | Cantoneiras |
|---|---:|---:|
| Linhas CPIS / OFs distintas | 12.362 | 70.129 |
| Em Aberto | 339 | 729 |
| Em Produção | 1.020 | 1.107 |
| Total aberto ou em produção | 1.359 | 1.836 |
| Abertas com linhas no plano da própria área | 351 | 376 |
| Abertas sem linhas no plano da própria área | 1.008 | 1.460 |
| Linhas técnicas no plano, todos os estados | 7.199 | 75.192 |

A união inclui **1.921 OFs potencialmente abertas**. Dessas, **1.265 não têm
linhas em nenhum dos dois planos**. Não se devem somar os dois totais de OFs:
há muitas ordens presentes nas duas cópias.

A listagem CPIS dentro de cada macro não é uma classificação de trabalho dessa
área. É contexto administrativo. Uma OF aparecer no Excel de Cantoneiras não
prova que precisa de operações de Cantoneiras.

Há 100 OFs com estados diferentes entre cópias:

| Perfis | Cantoneiras | OFs |
|---|---|---:|
| Em Aberto | Em Produção | 2 |
| Em Aberto | Fechada | 32 |
| Em Produção | Fechada | 53 |
| Fechada | Em Produção | 3 |
| Pronta | Em Produção | 10 |

Logo, 98 conflitos alteram a decisão «pode ser preparada operacionalmente».
O facto de uma cópia estar no ficheiro gravado mais tarde não autoriza a escolher
essa cópia como estado oficial. É preciso confirmar o CPIS.

Na cópia de Cantoneiras há **521 OFs abertas com número até 250000**. O filtro
do Excel de Perfis impede que essa consulta ofereça uma lista completa.

Não foram encontradas OFs duplicadas dentro de cada uma destas versões CPIS.
Isto é uma observação dos ficheiros atuais, não uma garantia futura sobre OVs.

## 4. Qualidade e significado dos campos CPIS

Nas OFs abertas da cópia de Cantoneiras faltam OV e cliente em 357 registos;
na de Perfis faltam em 21. Há 715 ordens abertas sem data de entrega na primeira
e 295 na segunda. A interface deve preservar estas ausências.

Fim previsto da Produção e entrega diferem em 358 ordens abertas na cópia de
Perfis, incluindo casos em que só uma das datas está preenchida. Há 290 com
fim de produção posterior à entrega. Estas diferenças têm de estar visíveis,
sem transformar um dos campos no outro.

As 35 colunas da vista exportadas para Excel incluem informação adicional
útil: `observacoesdp`, `observacoesintdp`, `datupdobsdp`, semanas de produção
e entrega, `dificuldadeof`, `codpie` e `elementopep`. A interface atual usa
apenas parte dessa informação. `datupdobsdp` é atualização das observações DP;
não é a data da última consulta da fonte nem de todas as alterações da OF.

Há ordens administrativamente «Em Produção» com observações «NÃO ENTROU EM
PRODUÇÃO». As duas informações devem ser apresentadas com os seus significados;
nenhuma comprova isoladamente a produção de uma peça.

### Erros provocados pelo formato das células

A inspeção do XML original confirmou:

| Campo | Valor numérico no XML | Resultado do leitor Excel |
|---|---|---|
| `semdataentregadl` | `8` | `1900-01-08` |
| `percent` | `100` | `1900-04-09` |
| `satus` | `1` | `1900-01-01` |
| `idof` | Número da ordem de `2 × 10^17` | `#VALUE!` |

O estilo de data aplicado às células leva o openpyxl a converter códigos e
semanas em datas. Os valores importados de `idof` estão todos representados
pelo mesmo erro nos dois ficheiros. Não podem ser usados como chave interna.
Os números muito grandes guardados como números Excel também exigem cuidado
com precisão; não se pode reconstruir a identidade SQL exata por suposição.

A importação alternativa deve aplicar tipos por coluna e preservar também a
representação original da célula. A leitura SQL direta deve confirmar os tipos
nativos e conservar identificadores sem passagem por ponto flutuante.

Evidência: [campos CPIS](planeamento-cpis-2026-09-20/auditoria-campos-cpis.json) e
[XML versus leitor](planeamento-cpis-2026-09-20/auditoria-formatos-excel.json).

## 5. A necessidade física é diferente da operação

Foram encontrados **256 grupos OF + referência em Perfis com geometrias
diferentes**, envolvendo 640 linhas. Em Cantoneiras foram encontrados dois
grupos, envolvendo quatro linhas.

Exemplo: OF266068 / `7450V001` contém cinco linhas, com comprimentos de
1.725, 1.925, 3.150, 4.150 e 5.150 mm e dois perfis. Juntar tudo pela referência
mistura peças diferentes.

O Excel de Perfis contém esta lógica, observada diretamente nas fórmulas:

- `Qtd em Falta = QTD − Ser.`: saldo de corte.
- `Fechado`: se há indicação de abocardar, verifica `Aboc. >= QTD`; caso
  contrário verifica `Ser. >= QTD`.

Há 79 linhas com indicação `Aborc. = X`; 39 já têm saldo de corte zero,
mas apenas 31 estão fechadas. Não é correto concluir toda a execução pelo
saldo de corte.

Exemplo confirmado na API: **OF264760** devolve `execution_complete=true`,
apesar de a macro apresentar uma peça com 840 cortadas, 572 abocardadas e
`Fechado` vazio. A diferença de 268 unidades pertence ao abocardamento.
Esta OF tem ainda um conflito administrativo entre as duas cópias CPIS.

Outro exemplo: **OF264763 / CI5121A4030**, 315 necessárias, 315 cortadas,
298 abocardadas. A necessidade de conferir as 17 restantes não desaparece
por o saldo de corte ser zero. A OF como um todo continua pendente na API
por causa de outras linhas; o erro de agregação da produção desta peça
está confirmado na secção seguinte.

### Informação existente que não chega ao detalhe

- 5.742 linhas de Perfis têm `Máquina Corte` em `row_data`, mas a coluna
  canónica `cutting_machine` está vazia nas 7.199 linhas. O importador de
  Perfis não mapeia esse campo, e o detalhe novo consulta a coluna vazia.
- Há 5.533 valores `Ser.` e 172 valores `Aboc.` preservados nos dados brutos.
  A vista analítica devolve `quantity_made=NULL` para Perfis por contrato;
  o painel não deve apresentar isso como se o Excel não tivesse acumulados.
- Em Cantoneiras, o contrato analítico atual trata `Maq.` vazio como zero em
  18.608 linhas (`qtd_minus_maq_blank_zero`). Isto já existe antes desta
  interface. Precisa de ser explicitado; não é a mesma regra que OCR ausente
  igual a zero, nem deve ser alterado silenciosamente durante esta correção.

Evidência: [operações](planeamento-cpis-2026-09-20/auditoria-operacoes.json) e
[estados devolvidos pela API](planeamento-cpis-2026-09-20/auditoria-conclusao-operacoes.json).

## 6. O que os dois OCRs realmente permitem afirmar

| Indicador | Perfis | Cantoneiras |
|---|---:|---:|
| Folhas validadas, incluindo paragens | 77 | 74 |
| Registos na tabela de produção | 381 | 727 |
| OFs reconhecíveis após normalização | 73 | 60 |
| Última data de produção | 17/09/2026 | 17/09/2026 |
| Última validação, UTC | 18/09 07:48:25 | 18/09 14:27:15 |
| Registos sem quantidade | 0 | 109 |
| Registos sem comprimento na coluna principal | 4 | 727 |
| Identidade técnica preservada em `extra` | 253 | 110 |

Os 727 comprimentos vazios não significam que toda a geometria de Cantoneiras
desapareceu: parte está nas identidades congeladas e referências filhas.
Essa evidência precisa de ser lida antes de procurar correspondências atuais.
Há ainda 14 registos de Cantoneiras com identificações de OF que não seguem
o formato normal, incluindo marcas de repetição; necessitam da recuperação
do contexto da folha, não apenas de acrescentar o prefixo `OF`.

### Referências antigas e perfil completo

Em Perfis, nenhuma chave principal de produção aponta para a versão atual;
252 ainda existem em versões históricas importadas. Em Cantoneiras, 110
chaves principais existem na versão atual; muitas outras apontam para
versões já ausentes.

Foram executados os recuperadores existentes em memória, sem gravar alterações:

- Perfis: 77 folhas passaram a verificação existente de preparação da exportação.
  Isto não certifica a identidade de todas as linhas antigas sem expansão.
- Cantoneiras: das 73 folhas de produção, 21 ficaram incompletas por **86 linhas
  de perfil completo sem snapshot de validação identificável**. A outra folha
  validada é de paragens.
- Há também 48 referências filhas guardadas para dois registos de Cantoneiras,
  todas com quantidade zero. Estes zeros são factos históricos a preservar.

Não se pode reconstruir a quantidade dessas 86 linhas usando o saldo atual.
Pode ser necessário recuperar o ficheiro histórico ou fazer uma associação
humana auditada. A necessidade de conferência deve ficar visível por linha.

### Falhas no cruzamento atual

O classificador novo aceita 375 registos de Perfis e 358 de Cantoneiras como
`technical_unique`. Em **356 dos registos de Cantoneiras**, fá-lo sem comprimento
na evidência principal e sem referências filhas. Considerar que existe uma só
linha atual não substitui a identidade histórica.

Ficam sem correspondência 4 registos de Perfis e 259 de Cantoneiras; outros
2 de Perfis são ambíguos. Estes números descrevem o algoritmo atual, não uma
certificação de que as associações aceites são corretas.

O total apresentado no painel também mistura operações:

| Peça | Necessário | OCR corte | OCR abocardar | Total atualmente apresentado |
|---|---:|---:|---:|---:|
| OF265541 / CI1822A4001 | 1 | 1 | 1 | 2 |
| OF264763 / CI5121A4030 | 315 | 315 | 298 | 613 |

Os registos individuais já contêm as máquinas, mas a agregação ignora a
operação. Além disso, expressões `quantity || 0` transformam quantidades
desconhecidas em zero quando há um registo associado.

Um exemplo real da sobreposição entre circuitos é OF265569 / DLT319:
28 necessárias, 14 no acumulado da macro, saldo 14 e 14 validadas no OCR.
A igualdade numérica não demonstra se são os mesmos acontecimentos. Somar
14 + 14 para concluir 28 ou descontar novamente 14 ao saldo seria injustificado.

Evidência: [recuperação Perfis](planeamento-cpis-2026-09-20/recuperacao-kanban-mes-mtg2.json),
[recuperação Cantoneiras](planeamento-cpis-2026-09-20/recuperacao-kanban-mes.json),
[agregação incorreta](planeamento-cpis-2026-09-20/auditoria-ocr-operacoes-interface.json) e
[exemplos de saldos](planeamento-cpis-2026-09-20/auditoria-saldos-exemplos.json).

## 7. Catálogos e controlos que os dados justificam

| Informação | Controlo fundamentado nos dados |
|---|---|
| OF | Pesquisa/seleção no CPIS; estado e contexto apenas de consulta |
| Referência existente | Pesquisa dentro da OF, com geometria e variante visíveis |
| Nova referência | Texto, com identidade separada da operação e da máquina |
| Máquinas / equipas | Seleção em catálogos independentes de cada área |
| Perfis H/I/PFC/T/U/UB/UC/W e varão roscado | Designações normalizadas dos intervalos nomeados |
| Tubos, barras e outras famílias sem lista preenchida | Dimensões numéricas adequadas à família |
| Qualidade, pavilhão, observações locais | Texto, sem fingir que existe catálogo CPIS comprovado |
| Picking | Semana sugerida pela consulta própria; ano só quando conhecido |
| Produção | Consulta de evidência por operação; alteração de interpretação auditada |

As listas de máquinas e equipas foram comparadas integralmente: 10 máquinas
e 28 equipas em Perfis; 12 máquinas e 26 equipas em Cantoneiras. A exclusão
de «Rendimento» como máquina e «Equipa» como nome de equipa é correta.

Persistem problemas no formulário:

- O catálogo de operações de Cantoneiras inclui indevidamente o texto de
  cabeçalho «2ª Operação» como opção.
- O servidor impõe `corte/abocardar` como operação principal também em
  Cantoneiras, embora existam códigos de furação, forja, soldadura e chanfro.
- Há variantes duplicadas como `Tubo Redondo` / `Tubo redondo` e tipos
  acrescentados pelo código sem origem distinta das opções do Excel.
- Os intervalos de tubos em `AreaSecaoCorte` estão vazios. O formulário não
  pode obrigar a selecionar um perfil normalizado inexistente, nem mostrar
  perfis H/I como alternativa para um tubo.
- O servidor valida semanas entre 1 e 53, mas ainda não verifica se a semana
  53 existe no ano escolhido.
- O contrato de proveniência tem colunas, mas a interface não regista a
  decisão humana e a sugestão separadamente para cada campo.

## 8. Lista, PDFs e saída: o que está ligado e o que falta

Erros reproduzidos por pedidos GET:

- OF266229: a lista diz «ambas», sem linhas de plano nem produção. A origem
  dessa classificação é aparecer nas duas cópias CPIS; não é evidência de área.
- OF266198: a lista mostra apenas «Em Produção», enquanto o detalhe reconhece
  conflito «Pronta / Em Produção». O filtro é aplicado antes de juntar as
  cópias e esconde parte do conflito.

O arquivo PDF atual tem cinco documentos, doze peças e sete necessidades
registadas. Não há ainda fichas no registo PostgreSQL de preparações. O PDF
OF266229, que aparecia sem linhas na captura antiga, está agora guardado como
pronto e tem uma peça; isso é estado da preparação PDF, não produção realizada.

A análise do código mostra que a integração ainda não é comum aos dois percursos:

1. O circuito PDF consulta `raw_mtg.cpis_rows` da macro de Perfis, sem consultar
   a nova fonte SQL direta.
2. O bloqueio por confirmação CPIS recente está no percurso de preparação
   manual, mas não no circuito anterior de exportação PDF.
3. A deduplicação de necessidades PDF vive em SQLite; as novas fichas manuais
   não partilham essa identidade. Ainda falta impedir de forma comum que a
   mesma necessidade seja preparada por ambos os percursos.
4. O serviço de saída manual reutiliza o escritor XML, mas não oferece ainda
   uma proposta comum que aceite fichas manuais e peças PDF juntas.
5. Ao concluir uma ficha, a frescura é consultada na versão mais recente,
   mas o estado da OF pode ser consultado numa versão antiga indicada pelo
   cliente. Há que confirmar a OF na versão atual no momento da conclusão.
6. A conferência de saldo recebe do cliente a evidência a assinar. A evidência
   e as dependências devem ser reconstruídas no servidor, incluindo operação,
   identidade técnica e IDs/revisões dos acontecimentos OCR.

Evidência: [exemplos da API](planeamento-cpis-2026-09-20/auditoria-api-exemplos.json)
e [inventário PDF](planeamento-cpis-2026-09-20/auditoria-pdf.json).

## 9. Ordem das correções necessárias

1. **Corrigir as conclusões atualmente erradas:** separar operações nos totais
   OCR; não concluir abocardamento pelo saldo de corte; preservar desconhecidos;
   manter conflitos CPIS visíveis; identificar a área por trabalho comprovado.
2. **Validar o acesso que o Excel já usa:** executar o diagnóstico no PC,
   confirmar ambas as vistas, tipos nativos, contagens e estados dos exemplos.
   Autenticação e permissões continuam por verificar.
3. **Corrigir os dados importados:** tipos por coluna, identificadores sem perda
   de precisão, máquinas e acumulados de Perfis recuperados dos campos próprios,
   versão/importação e confirmação da fonte com datas diferentes.
4. **Reutilizar a evidência histórica:** identidades congeladas, marcas de
   repetição, referências expandidas, operações e fila explícita de casos
   irrecuperáveis. Nunca atribuir produção apenas porque resta uma candidata.
5. **Unificar a preparação:** identidade física partilhada entre PDF e manual,
   metadados de campos por família, proveniência por campo e revisão da decisão
   humana apenas quando mudam as suas dependências.
6. **Unificar as condições de saída:** CPIS recente e OF atualmente permitida,
   macro e revisões fixadas na proposta, comparação das células e cópia XLSM.

Casos de aceitação concretos desta auditoria:

- OF266229 não recebe a área «ambas» apenas por estar em dois Excel.
- OF266198 mostra o mesmo conflito na lista e no detalhe.
- OF264760 não desaparece de «Por fazer» por ter corte concluído.
- OF264763 / CI5121A4030 mostra corte 315 e abocardamento 298 em linhas separadas.
- OF265541 não apresenta duas peças produzidas por juntar corte e abocardamento.
- OF266068 / 7450V001 mantém as cinco geometrias distintas.
- As 86 linhas antigas de perfil completo incompleto continuam por conferir.
- Uma OF que fecha numa nova versão CPIS não pode ser concluída usando a antiga.
- O percurso PDF obedece às mesmas regras de confirmação CPIS que o manual.

## 10. Como reproduzir e limites desta auditoria

O script principal executa consultas numa transação PostgreSQL de leitura
consistente e gera um relatório JSON:

```bash
.venv/bin/python scripts/audit_planning_data.py \
  --output docs/planeamento-cpis-2026-09-20/auditoria-dados.json
```

Contagens, exemplos de geometria, qualidade e associações estão em
[`auditoria-dados.json`](planeamento-cpis-2026-09-20/auditoria-dados.json).
As restantes evidências foram recolhidas por consultas de leitura, inspeção
de ZIP/XML/VBA e pedidos GET às APIs. O arquivo SQLite foi aberto com `mode=ro`.

Esta entrega acrescenta a auditoria e o diagnóstico, sem aplicar as correções
funcionais acima. Não houve nova publicação da aplicação nesta análise. A
consulta real CPIS permanece pendente; os resultados importados não certificam
o estado atual da fábrica. O diagnóstico PowerShell foi revisto, mas não foi
executado neste ambiente. Os testes anteriores da aplicação não foram usados
como substituto destas verificações com dados reais.
