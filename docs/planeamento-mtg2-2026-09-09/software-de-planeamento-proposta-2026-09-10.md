# Software de planeamento Metalogal — proposta revista em 10/09/2026

O produto principal proposto é um planeador da produção MTG2: transforma necessidades em carga, distribui trabalho pelas máquinas e pelo calendário, propõe uma sequência e mostra quais os compromissos que não cabem. Deve funcionar com os dados atuais do Excel e CPIS. Um registo simples de execução pode melhorar a frequência de atualização numa etapa posterior.

Esta proposta incorpora a correção de âmbito do utilizador: a prioridade é planeamento, não construir um MES. O formulário pedido pela Metalogal serve para preparar/corrigir as necessidades e os parâmetros que o planeamento utiliza.

## O que foi verificado novamente

Foi consultada diretamente a Drive e descarregado novamente `Met2_Plan_Perfis.xlsm`, modificado em 10/09/2026 às 07:03:33 UTC. O SHA-256 é `aa2d59af81541c37165b4d611ed698dad97bcbc9b7cf74ca3db8ace7cf572968`, igual ao ficheiro local e ao snapshot `mtg2_aa2d59af81541c37`, carregado às 12:20:07 UTC. Foram relidas as folhas de planeamento, Picking, disponibilidade semanal, capacidades e catálogo. Consultas e experiências foram executadas em leitura apenas; não foram publicados planos nem alterados registos operacionais.

O universo documental usado tem saldo de corte válido e positivo, sem Fechado=X, e CPIS Em Aberto ou Em Produção. São 1.074 linhas, 268 OF e 85.453 peças. A atribuição destes estados ao conceito operacional de OF aberta continua a ser uma interpretação a fechar antes de implementar o bloqueio de registo. Estas contagens não demonstram disponibilidade de material.

| Evidência atual | Consequência para o planeamento |
|---|---|
| 432 linhas sem máquina indicada | Atribuição automática exige compatibilidades por tipo/dimensão/operação. A lista Dados!B só dá as escolhas. |
| 603 linhas com Data Corte anterior a 10/09; 118 sem essa data | É preciso distinguir necessidades vencidas, previsões antigas e falta de prioridade. |
| 52 linhas com Data Corte posterior à entrega CPIS | Mostrar conflito de compromissos antes de transformar datas em fila. |
| Não existe disponibilidade configurada para a semana atual nas linhas da folha semanal | O calendário deve ser configurado por recurso/semana, pelo responsável. |
| Capacidades específicas usadas nas fórmulas têm cabeçalho de 11/11/2024 | Servem para testar uma estimativa inicial, não para prometer uma duração atual. |
| Na MEBA, 68 linhas/27 OF/8.404 peças têm destino Colunas/Pav. 6 | A vista das necessidades do setor seguinte tem utilidade concreta. São cerca de 83% das peças candidatas da MEBA. |

## Uma melhoria de dados que já é possível

A folha Picking tem 800 OF únicas, sem duplicações. Ao relacioná-la diretamente com a OF, recuperam-se semanas positivas para **239 linhas de 81 OF** cujo Picking está vazio/zero no Planeamento. A cobertura sobe de **166 para 405 linhas**, sem conflitos entre semanas positivas das duas fontes.

Nas células CG5769, CG6291 e CG6808, verificadas diretamente no XLSM, falta a fórmula. Outras células CG fazem XLOOKUP da OF para a mesma tabela Picking. Portanto, a relação já existe na lógica do ficheiro; o software pode aplicá-la a todas as linhas sem depender de fórmulas copiadas manualmente. Não é necessário inventar essa informação nem pedi-la novamente ao funcionário.

Das 405 linhas, 71 apontam para a semana 37, 60 para 38, 45 para 39 e duas para 40; 227 apontam para semanas anteriores à atual. O ano e o dia limite dentro da semana ainda devem ser definidos operacionalmente.

Exemplo: a **OF265760** tem 19 linhas/367 peças, Picking **39** na folha de origem, Data Corte **02/10** e CPIS **30/10**. Interpretando as semanas como ISO de 2026, a previsão de corte é posterior à semana em que o setor seguinte pede o material. O sistema deve recuperar a necessidade, sinalizar a incompatibilidade e procurar uma alternativa depois de atribuída uma máquina compatível. A entrega CPIS de outubro não elimina a necessidade anterior do setor seguinte.

## Como funcionaria o software

**1. Juntar as necessidades que têm de ser satisfeitas.** O planeador entra por obra e destino: por exemplo, trabalhos que Colunas precisa de receber numa determinada semana. O sistema importa OF, cliente, designação, referências, dimensões, qualidades, quantidades necessárias, saldos e indicações de operação. Recupera Picking pela OF. Mostra em separado informação em falta, conflitos e OF que deixaram de estar abertas.

A OF permite preencher o contexto da obra. A referência técnica exige selecionar a linha exata: há referências repetidas na mesma OF, inclusive com igual comprimento e perfil diferente. O sistema conserva essa identidade ao planear e atualizar saldos.

**2. Calcular a carga e distribuir capacidade.** Cada necessidade de uma operação corresponde a trabalho ainda por executar. O sistema estima duração a partir de parâmetros aprovados, acrescenta preparações e ocupa apenas as horas disponíveis. Começa por manter a máquina indicada nas linhas em que a atribuição existe. Só pode propor outra máquina quando a compatibilidade estiver validada.

O calendário inclui horas úteis, paragens previstas e limites dos operadores quando partilhados. Não se deve concluir que duas máquinas conseguem trabalhar simultaneamente só porque ambas existem no catálogo. Trabalho que ultrapassa o horizonte continua visível como carga futura; trabalho sem dados suficientes aparece como pendência de preparação, sem uma data inventada.

**3. Escolher a sequência em função dos compromissos.** Picking exprime a necessidade do setor seguinte; Data Corte conserva a previsão humana; Data CPIS representa o compromisso final da Produção. A proposta de política é proteger primeiro as necessidades confirmadas e procurar agrupamentos de perfil/qualidade quando estes não prejudicam os compromissos protegidos. O comportamento para semanas vencidas, ausência de Picking e conflitos requer uma regra do planeador.

O responsável pode fixar uma prioridade, reservar capacidade para uma obra ou definir a quantidade autorizada para um período. A necessidade de fracionar a execução de linhas enormes deve ser acordada; não se infere qualquer passagem de parcelas do corte para abocardar.

**4. Mostrar o resultado e permitir comparar alternativas.** O ecrã principal apresenta o plano por máquina/dia/semana, as necessidades que consegue satisfazer e as que ficam de fora. Ao lado, uma vista por OF/destino mostra quando acabam os trabalhos MTG2 abrangidos. Só pode declarar uma obra pronta na MTG2 quando todas as operações necessárias e respetivas dependências forem conhecidas. A conclusão numa máquina não é a conclusão de toda a Produção.

O planeador pode simular menos um turno, uma urgência, uma alteração de quantidade ou o uso de outra máquina compatível. O software devolve as mudanças de prazo e os trabalhos prejudicados. A versão aceite fica guardada; o trabalho já iniciado e os compromissos fixados são protegidos no replaneamento.

**5. Atualizar o que ainda falta.** A primeira versão pode reler o Excel e recalcular o plano quando mudam necessidades ou contadores. Comparando 09/09 com 10/09, em 6.989 identidades estáveis e não duplicadas, observei alterações de Ser. em 17 linhas; não houve alterações de Aboc., máquina, Data Corte ou Picking nessas identidades. Isto demonstra que já existe uma fonte de atualizações de quantidade. Não demonstra quando ocorreu fisicamente a produção nem autoriza voltar a somar essas diferenças aos saldos importados.

Mais tarde, a confirmação de peças boas a partir de uma tarefa planeada pode atualizar o saldo mais cedo. O objetivo desse registo é melhorar o planeamento. Os eventos têm de ser reconciliados com o Excel para não contar produção duas vezes. Para melhorar tempos, também é preciso observar duração de execução; quantidade isolada não mede velocidade.

## O que demonstrou a experiência com dados reais

Foi executado um cenário offline sobre **112 das 113 linhas MEBA**, correspondentes a 31 OF e 10.155 peças. Uma linha de seis peças foi excluída por falta de qualidade. Ambas as sequências são construídas para a experiência; nenhuma representa uma fila operacional observada.

- Sequência A: Data Corte, depois OF e linha — **106 preparações** no modelo.
- Sequência B: mesma ordenação entre datas; dentro de cada data, agrupar tipo/perfil/qualidade — **62 preparações**.

Os números incluem a preparação inicial: 105 e 61 mudanças posteriores. Com 20 minutos **hipotéticos** por preparação, a diferença seria 14 h 40 min. A execução teórica comum é 178,71 h, calculada pela taxa histórica de 48.024 mm²/h. O total seria 214,04 h e 199,37 h, respetivamente. O calendário de demonstração assume 7,5 h/dia, de segunda a sexta, a partir de 14/09; não verifica material, feriados ou operadores.

**Reduzir o total não melhora todos os compromissos.** No cenário agrupado, 87 linhas terminam mais cedo, sete no mesmo momento e **18 mais tarde**. A última linha MEBA incluída da OF264576 termina cerca de **3 h 21 min mais tarde**. A comparação não otimiza Picking. É uma demonstração concreta de por que o sistema deve mostrar quem perde com cada alteração, em vez de escolher apenas a sequência com menos mudanças.

Não são poupanças medidas nem datas prometidas à fábrica. São resultados reproduzíveis que demonstram o mecanismo de comparação e a necessidade de objetivos de prazo. Variar a velocidade em ±25% também altera muito a conclusão do cenário; essas variações são hipóteses de sensibilidade, não um intervalo de confiança.

## O formulário pedido pela empresa dentro deste produto

O formulário passa a ser a ficha de preparação da necessidade. OF/cliente/obra vêm do contexto existente; referência, perfil, dimensões, qualidade, quantidade e operações vêm da linha selecionada. Para uma nova linha ou perfil especial, o responsável introduz os dados técnicos que faltam, com campos condicionais ao tipo de perfil.

Data Corte é a previsão humana. Data/semana calculadas são resultados do plano e ficam separadas dessa previsão. Capacidade é configurada uma vez por recurso/período. Quantidade realizada e percentagem por linha/operação são calculadas a partir de contadores reconciliados. Não se pede a alguém que escreva uma percentagem nem se somam Ser. e Aboc. como se fossem peças distintas da obra.

A expressão ditada “organização de matéria-prima” permanece ambígua: há campos de requisição, material e lote, mas não foi inventada uma equivalência. Mantêm-se as regras já confirmadas: SAP/stock de matéria-prima na segunda fase; sem gestão de produto acabado; abocardar separado; sem transferência automática de parcelas; OF fechada no CPIS não admite novo registo.

## Proposta concreta para a primeira versão

Construir primeiro **necessidades + recuperação Picking + carga por recurso + plano semanal + comparação de cenários + revisão de exceções + atualização pelo Excel**. Usar MEBA como primeiro recurso para validar tempos e calendário, mantendo todas as necessidades MTG2 visíveis. Depois alargar a atribuição automática às máquinas com compatibilidades confirmadas e às operações com regras completas.

As confirmações imprescindíveis para confiar no plano são calendário e operadores, tempos/preparações, compatibilidades de máquina e política de prioridade/Picking. A matéria-prima pode ser tratada por bloqueios comunicados pelo responsável nesta fase. A entrada em abocardar precisa de regra própria. Um MES completo não é pré-requisito para este produto entregar valor.

Fontes locais: [ficheiro analisado](/home/luis/projects/DATARESEARCHMTG/Met2_Plan_Perfis.xlsm), [regras confirmadas](regras-confirmadas-2026-09-10.md), [resultados reproduzíveis](experiencia-planeamento-2026-09-10.json) e [experiência offline](experiencia-planeamento-2026-09-10.py).
