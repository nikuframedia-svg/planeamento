# Plano de vistas por família e capacidade para MTG2 e MTG3

Este plano define uma vista compacta e desdobrável para conhecer a carteira, escolher máquinas, ordenar o trabalho pelo prazo adequado e comparar necessidades com capacidade. O objetivo é reduzir o trabalho em atraso nas próximas semanas e antecipar necessidades de máquinas, equipas e materiais ao longo dos próximos meses.

A primeira entrega deverá juntar agrupamento, máquinas e prioridades sobre uma base comum de operações. Na MTG3, **a prioridade passa a usar a Data Corte**. O gráfico abaixo do Gantt mostrará capacidade disponível e ocupação por família, com os dados desconhecidos visíveis. Calendários, famílias, decisões e resultados terão versões e ligação à base de pesquisa.

Documento de análise e implementação futura, preparado em 1 de outubro de 2026. Nesta análise foram consultados código e bases em leitura e produzidos os ficheiros deste diretório. As funcionalidades propostas ainda não foram implementadas. Datas operacionais e semanas usam Europe/Lisbon.

## 1 Decisões propostas

| Necessidade | Decisão |
| --- | --- |
| Compactar a vista | Árvore de grupos com totais calculados no servidor e carregamento dos detalhes quando o utilizador os abre. |
| Filtrar por famílias | Usar a família de SKU versionada, como M1 e M2, na Carteira, Gantt, operações e capacidade. Manter identificada a família de encomenda do CPIS. |
| Agrupar de várias maneiras | Predefinições por família, grupo de perfis, conjunto de referências, máquina, OF e obra. Permitir ordenar as dimensões. |
| Escolher uma máquina | Menu na operação e no grupo; escolhas em grupo são resolvidas operação a operação, com exceções visíveis. |
| Configurar a prioridade | Política por unidade, com substituição por OF ou ocorrência. MTG3 usa Data Corte; MTG2 conserva inicialmente picking quando utilizável, como proposta de continuidade. |
| Capacidade por unidade e família | Horas de ocupação divididas por horas de capacidade do mesmo período e âmbito. Recursos partilhados têm uma única identidade física. |
| Reduzir backlog | Cenário de 14 dias, comparado com o plano de referência, incluindo pendências que impedem a execução. |
| Antecipar necessidades | Horizonte proposto de 52 semanas, com detalhe diário próximo e agregação semanal ou mensal mais distante. |
| Registar livremente | Guardar decisões e texto introduzido, incluindo informação incompleta. Explicar o que ainda impede o cálculo ou uma colocação executável. |
| Conciliar com a BD | Gravar decisões na aplicação, espelhá-las na base de pesquisa e ligar as suas versões à ontologia. |

Os horizontes de 14 dias e 52 semanas são escolhas propostas neste plano, configuráveis. Não são prazos prometidos de redução do atraso nem uma previsão de novas encomendas.

## 2 O que os dados atuais permitem concluir

A análise quantitativa está em [diagnostico.json](/home/luis/projects/planeamento/docs/plano-vistas-familias-capacidade-2026-10-01/diagnostico.json). Foi obtida numa transação de leitura consistente da aplicação. O script [analisar.py](/home/luis/projects/planeamento/docs/plano-vistas-familias-capacidade-2026-10-01/analisar.py) permite repetir a recolha.

### Carteira ativa nas projeções RAW

Os números seguintes descrevem as **áreas documentais Perfis e Cantoneiras** e o saldo da operação principal. Não são uma medição de toda a carga física de cada unidade: existem operações seguintes, recursos partilhados e linhas cujo pavilhão difere da área do ficheiro.

| Medida em 01/10/2026 | Perfis | Cantoneiras |
| --- | ---: | ---: |
| Linhas ativas | 1 209 | 17 236 |
| OF distintas ativas | 271 | 157 |
| Linhas com saldo principal positivo | 1 169 | 15 824 |
| Linhas ativas com saldo principal desconhecido | 0 | 1 139 |
| Linhas positivas sem horas estimadas | 498 | 12 463 |
| Cobertura de horas nas linhas positivas | 57,4% | 21,2% |
| Linhas positivas sem máquina indicada | 419 | 12 794 |
| Linhas positivas com Data Corte anterior a 01/10 | 587 | 9 241 |
| Linhas positivas sem Data Corte | 32 | 3 918 |
| Horas principais conhecidas, documentais ou estimadas | 1 454,40 h | 1 854,10 h |

Estas horas são uma soma parcial de estimativas existentes. Não demonstram capacidade disponível nem duração para liquidar a carteira. Os saldos são provisórios em 1 145 das 1 169 linhas positivas de Perfis e em 15 811 das 15 824 de Cantoneiras. As contagens de lacunas sobrepõem-se: uma linha pode não ter máquina, horas e data.

Também há um problema de âmbito: 222 linhas positivas da área Perfis indicam pavilhão MTG3; 76 linhas positivas de Cantoneiras indicam outros pavilhões. O gráfico físico terá de resolver essa atribuição, conservar o âmbito documental e impedir duplicação entre áreas. A importação documental do Gantt contém 52 casos candidatos a duplicação entre setores, ainda sem prova de equivalência física.

### Famílias e os casos M1 e M2

O catálogo contém 31 603 referências literais de Cantoneiras, 329 agrupamentos e 251 referências sem família identificada. M1 e M2 estão confirmadas pelo utilizador; 34 famílias têm classificação inferida com evidência; 293 agrupamentos continuam por confirmar. Não existe ainda um catálogo equivalente de famílias de SKU para Perfis. Nessa área, grupos de perfis e famílias CPIS já permitem organizar a vista, mantendo os nomes das dimensões explícitos.

A etapa 1 inclui inventariar e mapear as famílias de SKU de MTG2 a partir das referências, descrições, variantes e ligações CPIS disponíveis, usando o mesmo contrato de evidência. Não se copiam automaticamente os prefixos de MTG3 para MTG2. Enquanto uma classificação não estiver sustentada, o gráfico conserva “Sem família SKU” ou “Candidata” e permite alternar para grupos de perfis.

| Caso | Situação observada | Consequência para a vista |
| --- | --- | --- |
| M1 | 181 linhas no histórico; zero linhas ativas pela regra atual de fecho. A macro fecha as 181 embora o estado CPIS apresentado seja “Em Produção”. | Mostrar “181 no histórico; 0 ativas” e o motivo. Disponibilizar histórico sem reabrir trabalho automaticamente. |
| M2 | 395 referências e linhas ativas em três OF. 377 têm saldo principal positivo; 18 têm saldo desconhecido. | Mostrar todos os membros e separar os que permitem estimativa dos que precisam de esclarecimento. |
| Máquina da M2 | 165 linhas indicam Ficep Rapid 25T, 207 Rapid 20T -1 e 23 não indicam máquina. | A linha compacta deve mostrar várias máquinas e os casos sem atribuição; não escolher uma máquina representativa para toda a família. |
| Datas da M2 | Data Corte entre 14 e 20 de agosto de 2026. As 377 linhas com saldo positivo têm essa data ultrapassada. | Caso adequado para ensaiar a prioridade por corte e a recuperação de atraso documental. |
| Horas da M2 | 68,73 h principais estimadas em 372 das 377 linhas positivas. As outras cinco não têm horas. | Útil como carga parcial para um piloto; não é uma promessa de terminar toda a M2 em 68,73 h. |

A classificação M2 não prova produção. A ontologia mantém uma associação MES indireta para um perfil completo; isso não confirma a produção individual das 395 referências.

### Capacidade e estado do planeamento

Há 29 recursos catalogados: 16 máquinas, oito postos, duas filas funcionais, um grupo de operadores e dois destinos. Somá-los como “29 máquinas” daria uma capacidade incorreta. O grupo de operadores e os postos impõem restrições às máquinas que deles dependem.

Não há objetos locais de calendário ou taxa confirmados. A fonte documental contém 105 disponibilidades: 103 históricas por validar e duas duplicadas por resolver. Os cinco registos de taxa nessa fonte são históricos. As taxas presentes nas próprias linhas e a produtividade histórica constituem outras origens de estimativa, sem substituir um calendário futuro.

Na consulta atual há zero escolhas “Planear” e zero planos aceites. O Gantt executável vazio não significa carteira vazia nem disponibilidade de 100%. Por isso, **a vista de necessidades deve funcionar mesmo antes de selecionar trabalho para execução**.

## 3 O que aproveitar e o que alterar

| Parte existente | Lacuna para este pedido | Alteração planeada |
| --- | --- | --- |
| RAW com família SKU e filtro M1/M2 | Esse catálogo não acompanha explicitamente todas as operações do Gantt | Transportar família, estado e versão até ao contrato das operações e às agregações. |
| Carteira com vistas por perfil, família, OF e referência | “Família” vem de `work_type_code` do CPIS | Expor “Família de SKU” e “Família da encomenda”; preservar a informação CPIS. |
| Gantt com máquina por ocorrência e alternativas técnicas | Falta atribuição por grupo e árvore expansível | Acrescentar configuração por grupo com resolução por ocorrência. |
| Prioridades em `integrated.py` e `inputs.py` | Picking tem precedência; solver e avaliação também têm tratamento especial de picking | Resolver uma política comum por unidade e marco, usada por todos os motores e indicadores. |
| Carga semanal em `source_plan.py` e simulação em `weekly.py` | Falta percentagem por unidade/família; simulação semanal exige que o lote caiba numa semana | Acrescentar ocupação por períodos e suporte a uma operação que atravessa semanas. |
| Cenários em `raw_objects`, versões e execuções em `raw_jobs` | Faltam políticas, conjuntos de referências e preferências de apresentação adequados | Estender os contratos e reutilizar histórico, revisão e idempotência. |
| Espelho aplicação → pesquisa | Atualmente não publica cenários, objetos de configuração ou resultados Gantt | Publicar conjuntos específicos de decisões, configurações e planos, com versões atuais e histórico. |
| Fonte documental do Gantt | Reconsulta a carga arquivada; MTG3 nessa carga é de 29/09, enquanto a RAW já usa 30/09 | Fazer a camada de operações atuais consumir a aplicação atual e ligar a evidência documental sem substituir decisões recentes. |

A data da consulta não deve ser apresentada como data de atualização do Excel ou da fábrica. As versões de Excel, CPIS, MES, classificações e decisões terão de acompanhar cada resultado.

## 4 Uma base de operações para todas as vistas

A unidade mínima de trabalho será uma **ocorrência de operação** de uma necessidade ou item, com quantidade, referência, variante técnica, recurso e fontes. Uma referência pode existir em várias OF e exigir várias operações. Uma família apenas agrupa essas ocorrências.

O contrato comum deverá conter:

| Grupo de dados | Campos essenciais |
| --- | --- |
| Identidade | `operation_uid`, chave atual, necessidade/item, OF, área documental, unidade de responsabilidade, número de ocorrência e assinatura técnica. |
| Classificação | Referência literal, família SKU, estado e versão do mapeamento; família CPIS separada; tipo de material, perfil, qualidade e revisão. |
| Saldo | Quantidade autorizada, saldo reconciliado/documental/desconhecido, unidade, fontes e conflito de cobertura. |
| Datas | Data de prioridade resolvida, marco a cumprir, precisão, política, substituição manual, origem e caráter provisório. |
| Recursos | Máquina de origem, escolha manual/automática, alternativas, elegibilidade, dependências de posto e operadores. |
| Tempo | Estimativa por alternativa, preparação, unidade da taxa, versão, incerteza e motivo quando desconhecida. |
| Plano | Cenário, revisão, execução de cálculo, estado, segmentos de ocupação, fixações, início real e compromisso aceite. |

As identidades atuais incluem a origem da linha. Uma atualização do Excel pode criar outra chave de ocorrência. A correspondência entre gerações deve continuar a exigir uma ligação única e tecnicamente compatível; decisões sem correspondência ficam pendentes, com histórico, em vez de serem transferidas por semelhança do código.

Três âmbitos usarão este contrato:

1. **Carteira e necessidades:** trabalho ativo conhecido, incluindo não selecionado e bloqueado.
2. **Cenário de planeamento:** conjunto explícito escolhido para estudar ou calendarizar.
3. **Execução aceite:** compromissos em vigor e trabalho iniciado, que ocupam os recursos mesmo quando ficam fora do filtro visual.

O filtro de apresentação não altera a seleção “Planear”, a prioridade nem um compromisso aceite. A ação “Usar este conjunto no cenário” realiza essa mudança de âmbito de forma explícita.

## 5 Vista compacta e desdobramento

### Agrupamentos e filtros

Predefinições propostas:

| Vista | Desdobramento inicial |
| --- | --- |
| Famílias | Unidade → família SKU → perfil → referência → OF → ocorrência de operação. |
| Perfis | Unidade → tipo de material → perfil e dimensões → referência → OF → operação. |
| Conjuntos | Conjunto guardado → referência → OF → operação. |
| Máquinas | Recurso físico → família ou perfil → OF → referência → operação. |
| Encomendas | Obra/OV → OF → família → referência → operação. |

É possível trocar a ordem, limitar os níveis e guardar a disposição. Um grupo de perfis usa tipo de material e geometria: valores textuais iguais como “12” não bastam para considerar dois materiais equivalentes. Qualidade, espessura e revisão permanecem acessíveis no detalhe.

Filtros comuns: unidade, família SKU, estado da classificação, família CPIS, conjunto de referências, material, perfil, máquina atribuída, alternativa possível, OF, cliente/obra, prazo, atrasado, sem máquina, sem horas, seleção e ativo/histórico. “Máquina atribuída” e “máquina possível” têm rótulos diferentes.

Vários valores dentro do mesmo filtro combinam-se por OU; dimensões diferentes combinam-se por E. A pesquisa e as contagens abrangem toda a população elegível, não apenas a página carregada. “Sem família” e classificações candidatas continuam disponíveis. O seletor M1 explica quando só existem resultados no histórico.

Conjuntos de referências podem ser criados colando uma lista, selecionando linhas ou guardando um filtro. Devem indicar se os membros estão congelados ou se o conjunto é dinâmico. Uma lista conserva a referência literal, apresenta desconhecidos e não funde grafias automaticamente. O mesmo SKU em duas OF continua a representar duas necessidades distintas.

### Conteúdo de uma linha fechada

Uma linha de grupo mostra nome e estado da classificação, OF e referências distintas, quantidade por unidade compatível, horas conhecidas, cobertura da estimativa, próxima data de prioridade, maior atraso, máquinas envolvidas e pendências. Exemplo de apresentação, com dados M2 desta análise:

```text
▸ M2   395 referências · 3 OF   68,73 h conhecidas   18 saldos por esclarecer
       Corte 14–20 ago · 2 máquinas indicadas · 23 linhas sem máquina
```

Ao abrir, surgem as linhas filhas mantendo filtro, janela de tempo e posição. O detalhe de uma ocorrência mostra as fontes, rota, máquina, alternativas, duração e quantidade. Alterar um campo abre a edição existente; a leitura do grupo não cria novos registos de produção.

Na linha temporal fechada, usar faixas de ocupação por período ou pequenos blocos por máquina. Um intervalo entre a primeira e a última data de uma família não representa ocupação contínua: as lacunas devem continuar visíveis. Quantidades de peças contam-se uma vez por item/lote; horas somam-se por ocorrência de operação. As OF distintas recalculam-se no grupo pai, sem somar as contagens dos filhos.

### Disposição proposta

```text
[Unidades] [Necessidades / Cenário / Aceite] [Horizonte] [Agrupar por] [Filtros]
[Cobertura] [Atraso conhecido] [Trabalho sem máquina] [Capacidade por confirmar]

ÁRVORE COM TOTAIS                      GANTT OU NECESSIDADES POR PERÍODO
▸ MTG3                                hoje | semana 1 | semana 2 | ...
  ▸ M2   prazo · horas · máquinas       blocos de ocupação e pendências
    ▸ perfil → referência → OF         detalhe progressivo
                                       [menu contextual de configuração]

CAPACIDADE DA MTG2 POR FAMÍLIA          CAPACIDADE DA MTG3 POR FAMÍLIA
por semana ou mês                     mesma janela e critérios explícitos
[máquinas e recursos partilhados]      [carga sem duração / sem recurso]

BACKLOG E NECESSIDADES FUTURAS
saldo inicial → entradas → conclusão prevista → saldo final → défice
```

Usar a tipografia e os controlos já existentes, números tabulares e colunas fixas para identificação. A proposta mantém fundo `#f5f8f8`, superfície `#ffffff`, texto `#20343b`, ação `#216d7a`, aviso `#b66b20` e erro `#b23b3b`. A cor de família mantém-se entre árvore e gráfico; aviso e certeza usam também texto ou padrão, para não depender da cor. A marca distintiva desta vista será a faixa de máquinas na própria linha do grupo, que abre a distribuição sem exigir percorrer centenas de referências.

Proposta de densidade: 32–36 px por linha compacta, opção confortável, identificação fixa, expansão por teclado e painel contextual recolhível. Não reduzir o texto até perder legibilidade. Grandes populações exigem paginação dos filhos e virtualização das linhas; não desenhar 17 mil linhas no browser ao abrir a página.

## 6 Menu de máquinas e decisões por grupo

O menu abre na família, perfil, conjunto, referência ou operação. Deve identificar o âmbito: unidade, operações abrangidas, OF, quantidade, dados desconhecidos e escolha atual. “Várias máquinas” é um estado válido do grupo.

O utilizador pode escolher automático, preferir uma máquina, atribuir uma máquina às ocorrências selecionadas, retirar a escolha manual ou guardar uma preferência para trabalho futuro. Atribuição e preferência têm semântica distinta: uma preferência admite outra alternativa explicada; uma atribuição manual mantém a escolha e expõe os impedimentos que precisem de resolução.

Fluxo para “M2 → máquina”:

1. Resolver o conjunto de ocorrências no servidor, com as versões que o utilizador viu.
2. Mostrar por máquina quantas são admissíveis, condicionais, incompatíveis ou já iniciadas, com carga estimada e cobertura.
3. Permitir aplicar às ocorrências elegíveis, guardar os restantes casos como decisões pendentes ou manter exceções individuais. Mostrar o resultado concreto antes da gravação do conjunto.
4. Gravar um identificador de ação comum e as decisões por ocorrência, numa transação e com `request_id` idempotente.
5. Recalcular horas, prazos, ocupação e conflitos. Permitir voltar ao automático e desfazer a ação em grupo através de uma nova revisão.

Não é necessário que todas as peças da família usem a mesma máquina. As condições de dimensão, qualidade, ferramentas, desenho, operação e cliente continuam a ser avaliadas por variante/ocorrência. Por exemplo, uma preferência de família não autoriza automaticamente trocar 112 por 119 nem resolve as condições técnicas já existentes para Peddi 6 ou XP T6.

Precedência proposta: trabalho iniciado e fixações coerentes → decisão explícita da ocorrência → referência e operação → conjunto guardado → família SKU e operação → grupo de perfis e operação → escolha automática. Uma regra específica incompatível fica visível como conflito; não se muda silenciosamente para outra. Duas regras com a mesma especificidade e destinos diferentes exigem resolução explícita no cenário.

“Aplicar ao conjunto atual” congela os membros e a versão. “Guardar preferência futura” conserva o seletor e a sua vigência. Novas referências não recebem retroativamente uma decisão apresentada como individual. O estado incompleto não impede guardar a intenção; impede apenas apresentar uma operação sem condições como execução validada.

## 7 Menu de prioridades e datas

### Política por unidade

| Âmbito | Fonte por defeito proposta | Marco avaliado |
| --- | --- | --- |
| MTG3 | Data Corte da linha, conservando a origem e substituições manuais | Conclusão da operação principal de corte/processamento correspondente. |
| MTG2 | Picking utilizável, mantendo a regra atual como proposta inicial | Disponibilidade das operações necessárias para esse picking. |
| OF ou ocorrência | Data ou marco escolhido pelo utilizador | Âmbito explicitamente indicado no menu. |

Na MTG3, a ausência de Data Corte produz “prioridade sem data”; não se preenche automaticamente com picking. Picking e galvanização continuam disponíveis como marcos relacionados. Se o utilizador quiser outra regra numa OF, a substituição fica registada. A política MTG2 pode ser alterada no mesmo menu; não se presume que a escolha indicada para MTG3 se estende à MTG2.

O menu contém unidade, campo prioritário, marco, comportamento quando falta data, data específica da OF, urgência, motivo e vigência. Para MTG3, a proposta é cumprir o corte até ao fim do dia local indicado. Uma data sem hora conserva precisão de dia; não inventa um turno. Uma semana de picking sem ano confirmado mantém a incerteza. A RAW atual tem 251 linhas positivas de Perfis com picking calculado, mas nenhum ano de picking explicitamente preenchido nessas linhas; a aceitação desse ano inferido precisa de ser tratada como uma escolha identificada.

Datas diferentes entre referências da mesma OF não devem ser esmagadas numa única data mínima. O grupo mostra a mais próxima, o intervalo e os conflitos; cada ocorrência conserva o seu prazo. Uma substituição global da OF deve indicar quais os marcos e linhas que altera. A chave da política inclui unidade e OF, evitando que a mesma OF numa outra unidade herde indevidamente a decisão.

### Cálculo comum

Criar um resolvedor único com saída `priority_date`, `priority_milestone`, `priority_source`, `priority_scope`, `policy_version`, `override_id`, `precision`, `provisional` e `missing_reason`. Usá-lo na Carteira, RAW, Gantt, simulação semanal, fila de backlog e gráficos.

Atualizar conjuntamente `inputs.py`, `integrated.py`, `baseline.py`, `solver.py`, `validation.py`, `weekly.py`, indicadores e marcadores visuais. O código atual tem objetivos e avaliação denominados `picking_lateness` e `picking_orders`; mudar só o campo `deadline` deixaria o significado do cálculo inconsistente.

Exemplo de aceitação: uma OF MTG3 com corte a 8 de outubro e picking a 20 de outubro deve aparecer e ser avaliada pelo corte a 8 de outubro. As operações posteriores conservam as suas próprias datas e dependências; não ficam todas artificialmente obrigadas a terminar no prazo de corte.

## 8 Gráfico de capacidade abaixo do Gantt

Mostrar dois painéis alinhados, MTG2 e MTG3, com a mesma janela temporal. Cada período apresenta horas de capacidade, horas ocupadas, percentagem ocupada, contribuição por família e trabalho por esclarecer. Abrir a unidade revela máquinas; abrir a máquina revela as famílias e ocorrências responsáveis pela carga.

Separar “necessidades”, “proposta” e “aceite”. Necessidade ainda sem colocação é procura de capacidade, não ocupação já reservada. Uma previsão documental por semana não deve ter a mesma aparência de uma execução horária validada.

### Definições e fórmulas

Para máquina física `m` e período `w`:

```text
C(m,w) = horas do calendário utilizável no período, descontadas paragens planeadas
H(o,m,w) = soma da interseção dos segmentos de ocupação de o com o período w
H(u,f,w) = soma de H das ocorrências únicas atribuídas à unidade u e família f

Ocupação(u,w) = 100 × H_alocado(u,w) / C(u,w)
Família na capacidade(u,f,w) = 100 × H(u,f,w) / C(u,w)
Família na carga(u,f,w) = 100 × H(u,f,w) / H_alocado(u,w)
Pressão das necessidades(u,w) = 100 × H_necessário_conhecido(u,w) / C(u,w)
```

A capacidade é o denominador anterior à alocação; não se subtrai a carga para voltar a dividir por uma “capacidade disponível” já reduzida. Horas-máquina, horas-pessoa, metros e peças são grandezas diferentes. Operadores aparecem num painel próprio e nas restrições, sem serem somados ao denominador de horas-máquina.

Uma operação que atravessa semanas contribui apenas com os segmentos de cada semana. Preparações entram na ocupação uma vez por preparação real. A soma das famílias, incluindo “Sem família” e agrupamentos candidatos, reconcilia com o total ocupado. Conjuntos de referências sobrepostos usam união de ocorrências; não podem formar uma divisão percentual aditiva sem uma regra de pertença exclusiva.

Exemplo exclusivamente ilustrativo: com 200 h de capacidade, 80 h M1, 40 h M2 e 20 h de outras famílias, a ocupação é 70%. A M1 usa 40% da capacidade e representa 57,1% da carga alocada. As 60 h restantes são livres apenas no âmbito do calendário e dos compromissos conhecidos. Se as necessidades conhecidas forem 220 h, a pressão é 110%; esse excesso deve ser visível.

### Âmbito e recursos partilhados

Equipamento, posto e operador não geram capacidade adicional por terem nós diferentes. Resolver cada recurso físico uma vez e conservar as restrições de composição e partilha já existentes.

Para um recurso partilhado, uma quota de capacidade por unidade só existe quando está configurada: `C(u,w) = Σ alpha(u,m,w) × C(m,w)`, com a soma das quotas de MTG2, MTG3 e eventual reserva não superior a 1. Sem quotas, mostrar a capacidade desse recurso numa faixa “Partilhada”, a carga de cada unidade e uma percentagem própria do recurso. O total unitário fica identificado como parcial; não atribuir 100% da mesma máquina às duas unidades.

O calendário de uma máquina não é automaticamente substituível pelo de outra. Mesmo com folga agregada, a vista deve identificar o recurso limitante e as famílias que só podem usar esse recurso. Compromissos aceites de outras OF, famílias ou cenários permanecem na ocupação física global.

### Valores desconhecidos e filtros

- Sem calendário: “capacidade por confirmar”, com horas conhecidas se existirem; sem percentagem inventada.
- Calendário confirmado fechado: capacidade zero; havendo necessidade, mostrar “sem capacidade” em vez de dividir por zero.
- Com carga parcial: mostrar percentagem da carga conhecida e a cobertura por operações/OF; não chamar à diferença “folga garantida”.
- Família desconhecida: segmento próprio, preservando a carga conhecida.
- Sem máquina ou duração: fila de carga pendente ao lado do gráfico; não representa zero horas.
- Filtrar M1 destaca a sua contribuição e mantém visível o restante ocupado. O denominador da unidade permanece estável; a opção “percentagem dentro da seleção” tem outro rótulo.
- Totais mensais e entre máquinas usam soma de horas dividida por soma de capacidade; nunca média simples de percentagens.

## 9 Cálculo de carga e confiança das estimativas

Reutilizar a hierarquia de taxas e a evidência já existentes: taxa aplicável confirmada, histórico tecnicamente compatível e estimativa documental identificada. A taxa depende de máquina, operação, material/geometria e vigência. Uma família comercial não basta para transferir produtividade entre variantes.

```text
Taxa em peças/h:  H = quantidade / taxa + preparação_min / 60
Taxa em m/h:      H = quantidade × comprimento_mm / 1000 / taxa + preparação_min / 60
Taxa em mm²/h:    H = quantidade × área_unitária_mm² / taxa + preparação_min / 60
Tempo em min/un:  H = quantidade × tempo_unitário / 60 + preparação_min / 60
```

Quantidade, dimensão ou unidade desconhecidas mantêm a estimativa desconhecida. Quando se usa uma taxa observada que já inclui perdas ou preparações, não voltar a aplicar o mesmo fator. Registar se a taxa mede execução líquida, tempo total observado ou outra base. Agrupar visualmente por família não justifica descontar preparações; essa redução exige uma sequência e uma regra técnica de setup.

Para melhorar as estimativas, medir coortes completas com produção e horas correspondentes, eliminando versões repetidas e sobreposições de cobertura. Não dividir as horas totais de uma folha por cada referência para fabricar várias observações independentes.

Plano de análise estatística: quantis por coorte e por contexto compatível; comparação de taxa atual com novas estimativas; validação em períodos posteriores com OF inteiras fora do treino; erro absoluto em horas, viés e cobertura dos intervalos. A validação temporal e por grupos evita tratar observações relacionadas como amostras independentes, conforme a [documentação de validação do scikit-learn](https://scikit-learn.org/stable/modules/cross_validation.html). O módulo local `insights.py` já contém parte deste percurso.

P50/P80/P90 só serão apresentados como quantis preditivos depois de calibrados em dados de validação. Sem amostra adequada, usar cenários explícitos de sensibilidade — taxa menor, nominal e maior — e explicar que não são probabilidades. Reamostragem, quando aplicável, deve agrupar por OF/coorte. Falhas comuns a um turno ou recurso não são simuladas como milhares de eventos independentes.

## 10 Redução do backlog no curto prazo

### Medir o que se pretende reduzir

Definir separadamente trabalho aberto, trabalho em atraso pelo marco da unidade e trabalho bloqueado. O principal indicador será a carga de atraso em horas de referência, acompanhado de OF que completam o marco, idade do atraso e cobertura dos saldos/durações.

Para comparar planos, as horas de referência de cada ocorrência ficam congeladas numa base de comparação. Mudar para uma máquina mais lenta ou alterar uma taxa não deve aparentar que foi eliminado mais backlog. Cancelamentos, fechos administrativos, reclassificações e correções de saldo aparecem como ajustes, separados da produção concluída.

```text
Backlog_final = Backlog_inicial + Entradas - Trabalho_concluído + Ajustes
Prazo indicativo de recuperação = Backlog_inicial / (Saída_média - Entrada_média)
```

A segunda expressão só se usa com unidades comparáveis e saída superior à entrada, assumidas constantes. Se a entrada iguala ou supera a saída, não há prazo finito de recuperação nesse cenário. É um diagnóstico simplificado, não uma promessa de data.

### Cenário de 14 dias

Comparar o plano de referência com alternativas executáveis sobre as mesmas versões: sequência por Data Corte, utilização de alternativas admissíveis, mudança de turnos/equipas, remoção de impedimentos e, quando autorizado tecnicamente, preparação conjunta. Mostrar o ganho marginal de cada ação e o novo recurso limitante.

Usar o motor OR-Tools já instalado e a proposta determinística existente. As restrições de precedência, exclusividade de máquina e capacidade cumulativa são adequadas a este tipo de agenda; a documentação primária descreve o [problema job shop](https://developers.google.com/optimization/scheduling/job_shop) e os [modelos de intervalos e recursos](https://github.com/google/or-tools/blob/stable/ortools/sat/docs/scheduling.md). Os objetivos de negócio abaixo são uma proposta específica desta aplicação.

Ordem proposta de objetivos, configurável e avaliada igualmente pelo solver e pelo verificador:

1. Respeitar trabalho iniciado, fixações, calendário, elegibilidade, material disponível, operadores e dependências.
2. Cumprir os marcos críticos e urgências explícitas; conservar na avaliação o trabalho que não coube, para não “melhorar” o atraso omitindo operações.
3. Reduzir a carga de backlog atrasado até ao fim da janela e concluir marcos completos de OF, evitando premiar apenas grande número de operações pequenas.
4. Evitar que trabalho antigo fique sempre para trás, reduzir preparações comprovadas e limitar alterações ao plano em vigor.

O prazo é uma meta avaliada, não uma razão para esconder trabalho inviável. O resultado mostra pronto, bloqueado, colocado e fora do horizonte. Uma proposta melhor continua a ter de passar o verificador independente. Se o cálculo parar por limite de tempo, conservar a melhor solução validada e indicar que não foi demonstrada ótima.

### Primeira sequência de atuação sugerida pelos dados

Começar pelo caso M2, por combinar um grupo confirmado, datas de corte ultrapassadas e estimativas disponíveis para grande parte das linhas positivas. Rever os 18 saldos desconhecidos e as 23 linhas sem máquina; escolher a participação de Rapid 20T -1 e Rapid 25T com base nas alternativas de cada ocorrência; acrescentar operações seguintes e calendários antes de prometer uma data final.

Em paralelo, tratar a grande população MTG3 sem máquina/horas por perfil, operação e evidência técnica. Atribuir todas essas linhas a uma máquina de família sem análise só deslocaria a incerteza para um gráfico aparentemente completo. Ordenar a fila de resolução por atraso, OF afetadas, horas recuperáveis conhecidas e dependências que desbloqueia; conservar contagem separada de carga ainda não quantificável.

## 11 Necessidades e capacidade a longo prazo

Proposta de horizonte móvel: primeiras quatro semanas com detalhe diário ou por turno; semanas 5–26 com capacidade semanal; semanas 27–52 com apresentação mensal, mantendo uma base temporal consistente para agregação. O backend atual aceita até 26 semanas e o menu expõe 4, 8, 12 e 16; a extensão longa exige um contrato próprio, não apenas outra opção no seletor.

O agregado distante prevê necessidades sem reservar minutos fictícios. À medida que uma semana se aproxima, o cenário detalha as operações sobre calendários e dados atuais. Compromissos próximos e trabalho iniciado formam a zona de estabilidade. Não somar a alocação agregada e a agenda detalhada do mesmo trabalho.

Projetar por unidade, família e recurso: carteira inicial, entradas comprometidas, saídas previstas, saldo final, carga por período, capacidade, défice e trabalho sem dados. Apresentar necessidades de material por especificação, equipas/competências e recursos externos quando existirem bases compatíveis. Se stocks, compras ou datas de chegada não estiverem ligados, mostrar “disponibilidade de material por confirmar”; quantidade de material requerida não prova material disponível.

Separar encomendas conhecidas de procura futura hipotética. Uma previsão estatística de entradas só deve aparecer depois de analisar histórico de chegada e cancelamento, validar fora da amostra e apresentar incerteza. Antes disso, disponibilizar cenários definidos pelo utilizador: carteira atual sem entradas novas, entradas adicionais explícitas e alterações de turnos ou recursos.

Dimensionamento indicativo: `horas_adicionais = max(0, carga_conhecida - capacidade_utilizável)` por recurso/processo compatível. A conversão em turnos ou pessoas exige horas por turno, competências e limites de simultaneidade; não divide indiscriminadamente horas de todas as máquinas por oito.

Uma operação longa pode ocupar várias semanas preservando a identidade do lote. Melhorar a simulação semanal atual para reservar capacidade ao longo dessas semanas, sem declarar conclusão na primeira. Dividir fisicamente um lote é outra decisão: só usar quando houver regra explícita, com conservação de quantidades, preparações e dependências.

## 12 Persistência e ligação à base de dados

### Responsabilidades

`dataresearchmtg` continua a guardar decisões operacionais da aplicação. `dataresearchmtg_planeamento_20260930` recebe as publicações para consulta, análise e ontologia. Uma gravação do menu deve ficar disponível imediatamente na aplicação, mesmo que o espelho esteja temporariamente atrasado. A indisponibilidade da pesquisa não perde a decisão.

Fluxo planeado:

```text
Excel / CPIS / MES / registos e edições manuais
                 ↓ identidades e cobertura de origem
Operações atuais + famílias + políticas + recursos + calendários
                 ↓ versão consistente
Carteira / árvore / cenário / Gantt / agregados de capacidade
                 ↓ gravações versionadas na aplicação
Espelho atómico para a base de pesquisa → consultas e ontologia
```

A evidência arquivada de rotas e máquinas continua a ser consultada com a sua versão. Não deve escrever por cima dos dados atuais que regressam da aplicação, nem criar um ciclo em que um resultado espelhado é importado como nova produção.

### Objetos e tabelas propostas

| Objeto | Persistência proposta | Identidade e histórico |
| --- | --- | --- |
| Disposição da vista | Estender `raw_objects` tipo `view` com contrato Gantt, dimensões, filtros, colunas e densidade | Revisão existente; âmbito pessoal/partilhado só quando houver identidade de utilizador suportada. |
| Conjunto de referências | Novo tipo `reference_set`; tabela de membros por versão para listas extensas | Chave de membro `(object_id, revision, area, sku_literal)`; seletor versionado quando dinâmico. |
| Política de prioridade | Novo tipo `priority_policy`, mais substituições no cenário/OF | Unidade, marco, fonte, precisão, vigência e revisão. |
| Preferência por grupo | Novo tipo `assignment_policy`; decisões materializadas em `machine_overrides` | Seletor, operação, recurso, modo, motivo, membros resolvidos e ação de origem. |
| Quotas de recurso partilhado | Novo tipo `capacity_policy` | Recurso físico, unidade, período e quota; soma de quotas limitada à capacidade. |
| Cenário e plano | Estender o objeto `gantt` e os resultados de `raw_jobs` | Versões de dados/políticas, conjunto de operações, objetivo e compromisso aceite. |
| Projeção para consultas | Geração imutável de factos por ocorrência, com dimensões pesquisáveis | Uma ocorrência por geração e âmbito; reconstruível a partir de fontes e decisões. |
| Agregados de carga | Cache por geração, plano, unidade, recurso, família e período | Horas conhecidas, capacidade, contagens de cobertura e versões; nunca fonte operacional autónoma. |

A implementação terá de estender os validadores Python e as restrições SQL de tipos de objeto. Reutilizar `raw_object_versions` e a proteção por `expected_revision`. Referências introduzidas livremente que ainda não existem no catálogo podem ficar no conjunto como pendentes; uma restrição de base não deve tornar impossível guardar essa intenção.

A composição de membros e as decisões por ocorrência devem ser publicadas na mesma transação. Usar chaves únicas e eventos de auditoria com autor, motivo, valores anteriores e posteriores. Uma repetição do mesmo pedido não cria uma segunda decisão ou ocupação.

### Espelho e ontologia

Acrescentar conjuntos específicos ao espelho: configurações relevantes, versões de conjuntos/políticas, seleções de planeamento, decisões de máquina, cabeçalhos de cálculo, ocorrências congeladas, plano atualmente aceite e seus segmentos. Não copiar indiscriminadamente conversas ou caches transitórias de `raw_objects`.

Publicar os ponteiros desses conjuntos atomicamente, como já acontece para os dados atuais. Cada resultado referencia as versões exatas de entrada. A leitura ativa usa apenas as versões em vigor; o histórico permanece consultável sem aumentar os totais atuais.

Na ontologia, ligar conjunto → membros, política → âmbito, decisão → ocorrência/recurso, prioridade → data/marco/fonte e alocação → cenário/ocorrência/recurso/período. Preservar a diferença entre preferência, escolha condicional, plano aceite e produção observada. “Planeada na máquina X” não passa a ser “produzida na máquina X”.

O catálogo de famílias continua a ter um só proprietário e uma revisão por referência. A nova interface consome o mapeamento existente e não cria outra tabela paralela de M1/M2. Para MTG2, incorporar futuramente famílias de SKU com o mesmo processo de evidência, sem confundir perfis técnicos com família CPIS.

## 13 Reconciliação e prevenção de duplicações

| Situação | Regra |
| --- | --- |
| Mesma necessidade no Excel e CPIS | Um item de trabalho ligado a várias fontes, depois de correspondência de identidade; não somar quantidades. |
| MES e acumulado Excel | Reutilizar o saldo reconciliado quando demonstrado; conservar divergência/cobertura desconhecida. Não usar soma nem máximo como deduplicação automática. |
| Correção manual de linha importada | Aplicar a revisão à necessidade ligada e preservar a origem; não criar outra necessidade por estar noutra fonte. |
| Nova referência manual | Criar identidade própria, classificar se possível e manter incerteza visível. |
| Mesma referência em duas OF | Duas necessidades distintas. |
| Operação repetida da mesma peça | Duas ocorrências com rota e posição distintas; nunca fundir por código de operação. |
| Referência presente em dois conjuntos | Uma ocorrência na união da seleção; pertenças múltiplas são metadados. |
| Mesmo recurso em MTG2 e MTG3 | Uma ocupação física com atribuição de responsabilidade; capacidade não duplicada. |
| Plano novo e plano anterior | Só compromissos em vigor ocupam capacidade; versões históricas e cenários alternativos não se somam. |
| Família reclassificada | Nova análise usa a versão nova; cálculo antigo conserva a classificação congelada. |

O OCR por exportação continua separado enquanto a associação a eventos e unidades não estiver demonstrada. A ligação nativa dependente da VPN permanece fora das pressuposições de disponibilidade deste plano.

## 14 Consultas e desempenho

Criar consultas de grupos, filhos, facetas, detalhes e capacidade sobre a mesma geração. A resposta inclui o âmbito, versão, totais globais e filtrados, cobertura e indicação de atualização pendente. Um cursor de paginação pertence a essa geração; não deve misturar filhos de uma versão com totais de outra.

Contrato de leitura proposto: áreas, população, vista necessidades/cenário/aceite, agrupamento ordenado, caminho aberto, filtros, intervalo temporal e cenário/revisão. Os valores dos filtros são parametrizados e os campos pertencem a uma lista permitida.

Separar a API de leitura da API de simulação e da gravação de decisões. Para alterações em grupo, a pré-visualização devolve membros, alternativas, impedimentos e impacto; a gravação verifica que as versões não mudaram. A concorrência devolve o conflito e conserva os dados introduzidos para reaplicação.

Índices previstos para geração/ocorrência, unidade/família, recurso/período, OF/referência e pertenças de conjuntos. Agregação no servidor e ausência de uma consulta por SKU. O cache inclui versões de famílias, políticas, calendário, taxas, plano e seleção, além das fontes. Não recalcular o solver por abrir uma linha ou mudar uma coluna.

Metas propostas a medir no equipamento atual: primeira página agregada até 2 s com cache; expansão até 500 ms com cache; paginação sem congelar o browser; recálculo pesado em segundo plano com resultado anterior identificado como desatualizado. Não são medições já obtidas. Manter o orçamento atual do solver como ponto de partida e medir antes de aumentá-lo. O horizonte anual usa agregação, não milhões de intervalos horários.

## 15 Sequência de implementação e entregas

| Etapa | Trabalho e ficheiros principais | Resultado verificável |
| --- | --- | --- |
| 1 Base comum e datas | Resolvedor de prioridade; dimensões de família e cobertura MTG2; âmbito documental/físico; `planning_dates.py`, `sector/portfolio.py`, `gantt/inputs.py`, `gantt/integrated.py` | A MTG3 é ordenada por corte em todas as vistas e motores; família SKU/CPIS distinguem-se; MTG2 tem mapeamento com cobertura e pendências explícitas. |
| 2 Árvore e conjuntos | API de grupos, predefinições, filtros, membros e vistas guardadas; `gantt/service.py`, rotas, `gantt.js`, template/CSS e objetos RAW | Abrir M2, filtrar, mudar agrupamento e voltar mantém dados, âmbito e totais. |
| 3 Máquinas por grupo | Políticas e decisões em conjunto; `gantt/machines.py`, reconciliação de decisões e histórico | Uma ação de família preserva exceções e decisões individuais; edição não perde membros ou repete trabalho. |
| 4 Capacidade e persistência | Calendários atuais, recursos partilhados, agregações temporais, gráfico sob o Gantt; `source_plan.py`, `weekly.py`, `raw/capacity.py`, espelho e SQL de integração | Horas da árvore, Gantt e gráfico reconciliam; ausência de dados é explícita; decisões chegam à pesquisa. |
| 5 Recuperação de atraso | Objetivo de 14 dias e comparação com referência; `solver.py`, `baseline.py`, `validation.py`, `insights.py` | Ganho medido em trabalho e marcos concluídos, preservando restrições e carga fora da seleção. |
| 6 Horizonte longo | Projeção semanal/mensal, entradas hipotéticas, materiais e cenários de capacidade | Uma necessidade é contada uma vez na transição entre horizonte agregado e detalhado. |

As migrações, versões de contrato e consultas acompanham a etapa que cria os dados; a ligação à BD não fica adiada para o fim. A configuração de calendários e recursos começa em paralelo com a vista, pois é o principal impedimento atual a percentagens executáveis.

Primeiro marco utilizável: filtrar/agrupar M2, desdobrar até uma ocorrência, ver e guardar a máquina, aplicar prioridade por corte e consultar horas conhecidas com a cobertura. O gráfico pode inicialmente dizer “capacidade por confirmar”; só passará a mostrar percentagens completas quando existir um denominador sustentado.

Segundo marco: piloto completo M2 sobre calendários atuais, saldos revistos e recursos tecnicamente elegíveis. Medir efeito antes de generalizar a toda a MTG3. Terceiro marco: duas unidades e recursos partilhados, com comparação de cenários e previsão de necessidades.

### Ativação e compatibilidade

Introduzir as alterações por versões de contrato e sinalizadores de funcionalidade. Criar primeiro os novos objetos e projeções, preencher as dimensões a partir das fontes e comparar as leituras em paralelo. Cenários antigos mantêm a interpretação com que foram guardados; a passagem para a política por unidade cria uma revisão nova. Resultados e planos aceites antigos não são reescritos com as regras atuais.

Antes da ativação, verificar contagens, saldos, decisões existentes e sobreposição dos recursos no conjunto completo; executar os casos de aceitação em base descartável e os percursos de interface. Só depois carregar a nova vista e ativar o cálculo no piloto. Reverter a funcionalidade deve conservar decisões e histórico; não exige apagar tabelas nem regressar a uma cópia antiga dos dados manuais.

## 16 Critérios de aceitação

### Vista e interação

1. O filtro M2 encontra as 395 referências da população atual desta análise; alterações posteriores são verificadas contra as fontes, sem fixar esse número para sempre.
2. M1 apresenta o histórico e explica a ausência de linhas ativas e a divergência de fecho; não cria backlog novo.
3. Expandir/recolher ou trocar família por perfil conserva o conjunto de ocorrências e os totais de cada medida no seu nível correto.
4. Um conjunto com referências repetidas ou que também pertencem a outro conjunto não duplica trabalho.
5. Atribuição em grupo mostra máquinas múltiplas, sem máquina, incompatibilidades e exceções; voltar ao automático remove apenas a decisão escolhida.
6. A navegação por teclado, pesquisa global, paginação e expansão funcionam na população real.

### Datas e cálculo

7. MTG3 com corte anterior ao picking é priorizada pelo corte no motor, lista, atraso e gráfico.
8. Data Corte ausente não recebe picking silenciosamente; substituição manual conserva motivo e fonte.
9. Operações posteriores não herdam indevidamente o prazo de corte; datas por unidade não entram em conflito por a OF ser a mesma.
10. Calendário desconhecido, fechado e disponível têm resultados diferentes; hora de verão, viragem de ano ISO e períodos parciais são testados.
11. As durações aplicam unidades compatíveis e setup uma vez; o saldo desconhecido nunca é convertido em zero.

### Capacidade e reconciliação

12. A soma das ocupações por família, incluindo sem família, reconcilia com os segmentos únicos do plano.
13. Uma máquina partilhada e os seus postos/operadores não duplicam capacidade; compromissos ocultos por um filtro continuam a ocupar recurso.
14. A ocupação de uma operação que atravessa semanas reconcilia com a sua duração total e respeita pausas de calendário.
15. A necessidade superior a 100% continua visível; filtrar M1 não altera silenciosamente o denominador.
16. Árvores, gráfico e exportação usam a mesma versão e âmbito; o histórico não aumenta a carga atual.

### Persistência e resultados

17. Repetir uma gravação produz uma só ação; edição concorrente não apaga decisões; reiniciar serviços conserva políticas e escolhas.
18. Alterações de Excel, rota, família ou referência transferem decisões apenas com correspondência comprovada.
19. Cada escolha e plano aceite chega à base de pesquisa com identidade, revisão e origem, sem ser interpretado como produção.
20. O motor e o verificador calculam o mesmo objetivo de prioridade/backlog; soluções impossíveis não são apresentadas como executáveis.
21. A redução prevista usa a mesma carteira, taxas de referência e janela do cenário de comparação; trabalho omitido, cancelado ou reclassificado não conta como produção.
22. A projeção longa declara entradas hipotéticas e desconhecidos, sem afirmar que prevê a procura futura real.

## 17 Dependências e decisões ainda necessárias

O plano assume inicialmente picking para MTG2 por continuidade, execução curta de 14 dias e previsão de 52 semanas. Estas opções serão configuráveis. A interpretação “Data Corte como objetivo de conclusão do corte” está explicitada para evitar confundi-la com hora de início da máquina.

Para percentagens e compromissos reais é necessário preencher os calendários atuais, determinar a atribuição dos recursos partilhados e resolver as condições técnicas e saldos que afetam o trabalho escolhido. A interface e a gravação podem avançar antes disso, mostrando o estado incompleto.

M1 tem um conflito entre a macro e o estado CPIS que requer reconciliação de origem antes de a tratar como carteira ativa. M2 é candidata ao piloto, mas as suas horas conhecidas não justificam por si só uma data de conclusão. O catálogo de famílias SKU da MTG2 integra a primeira etapa, mantendo candidatas por confirmar quando a evidência não basta. A associação inequívoca do OCR depende de resolver a ligação à origem; até existir, a vista conserva essa evidência separada.

## 18 Evidência e referências para a implementação

Resultados reproduzíveis desta análise:

- [Diagnóstico e versões consultadas](/home/luis/projects/planeamento/docs/plano-vistas-familias-capacidade-2026-10-01/diagnostico.json).
- [Carteira por família SKU](/home/luis/projects/planeamento/docs/plano-vistas-familias-capacidade-2026-10-01/familias.csv), [por perfil](/home/luis/projects/planeamento/docs/plano-vistas-familias-capacidade-2026-10-01/perfis.csv) e [por máquina indicada](/home/luis/projects/planeamento/docs/plano-vistas-familias-capacidade-2026-10-01/maquinas.csv).
- [Script de recolha em leitura](/home/luis/projects/planeamento/docs/plano-vistas-familias-capacidade-2026-10-01/analisar.py) e [resultado da execução](/home/luis/projects/planeamento/docs/plano-vistas-familias-capacidade-2026-10-01/execucao-analise.txt).
- [Auditoria anterior do catálogo e ontologia](/home/luis/projects/planeamento/docs/familias-sku-mtg3-2026-10-01/ontologia/auditoria.txt).

Pontos de partida no código: [Carteira](/home/luis/projects/planeamento/app/sector/portfolio.py), [âmbito da seleção](/home/luis/projects/planeamento/app/sector/scope.py), [operações integradas](/home/luis/projects/planeamento/app/gantt/integrated.py), [cenários](/home/luis/projects/planeamento/app/gantt/service.py), [regras de máquina](/home/luis/projects/planeamento/app/gantt/machines.py), [datas](/home/luis/projects/planeamento/app/planning_dates.py), [solver](/home/luis/projects/planeamento/app/gantt/solver.py), [verificador](/home/luis/projects/planeamento/app/gantt/validation.py), [capacidade](/home/luis/projects/planeamento/app/raw/capacity.py), [simulação semanal](/home/luis/projects/planeamento/app/gantt/weekly.py), [estatística](/home/luis/projects/planeamento/app/gantt/insights.py), [espelho da pesquisa](/home/luis/projects/planeamento/app/raw/research_sync.py) e [interface Gantt](/home/luis/projects/planeamento/app/web/templates/gantt.html).

As regras de negócio, prioridades e etapas deste documento são propostas para este sistema. As fontes técnicas externas sustentam o método de otimização e validação indicado; não confirmam a capacidade, taxas ou compatibilidade das máquinas da fábrica.
