# Como construir o planeamento a partir do Excel atual

**Atualização de 10/09/2026:** as [confirmações operacionais](/home/luis/projects/kanban-mes-mtg2/docs/planeamento-mtg2-2026-09-09/regras-confirmadas-2026-09-10.md) substituem as hipóteses deste texto sobre datas, contadores, material e passagem de parcelas. A [proposta atualizada](/home/luis/projects/kanban-mes-mtg2/docs/planeamento-mtg2-2026-09-09/proposta-para-validacao-operacional.md) incorpora essas respostas. A disponibilidade de material assumida no exemplo abaixo é apenas uma hipótese do exercício anterior; a integração de stock fica para a segunda fase.

**O sistema seria um organizador de trabalho por máquina.** Para cada trabalho teria de saber o que falta fazer, até quando é necessário, em que máquinas é permitido fazê-lo, se o material está disponível e quanto tempo provavelmente ocupa. Depois colocaria os trabalhos na fila de cada máquina, dentro das horas disponíveis.

O aprofundamento de 09/09/2026 incluiu a extração estática do VBA dos quatro livros com macros, as fórmulas, os botões, as ligações a dados e as consultas Power Query. Foram encontrados 59 módulos no conjunto. No livro de perfis são 25 módulos, com 33 procedimentos/funções e 1.495 linhas de código incluindo comentários e linhas vazias. O inventário atual da pasta Drive continua com os mesmos 131 ficheiros. As macros foram lidas; não foram executadas nem alteradas.

**O que os botões fazem efetivamente.**

| Rotina do Excel de perfis | Comportamento observado no código | O que aproveitar |
|---|---|---|
| `Planeamento` e `Planeamento_Vanguard` | Escondem colunas e ajustam a apresentação | Os campos que o planeador consulta; não atribuem automaticamente datas ou máquinas |
| `Registar_1`, `Armazem`, `Expedicao`, `Impressao` | Alteram colunas visíveis e a posição na folha | Diferentes listas para planeador, registo, armazém e expedição |
| `FuncAreaPerf` | Onze funções calculam secções de tubos, varões, calhas, cantoneiras, barras e chapa | Converter geometria e quantidades numa estimativa de esforço de corte |
| `AbrirSemana` | Recolhe o previsto e o contador de produção à abertura; escreve num histórico externo | Guardar o compromisso que existia no início do período |
| `FecharSemana` | Compara contadores de abertura e fecho, separa área planeada cumprida e produção adicional, calcula cumprimento | Comparar o plano original com a execução sem perder as alterações |
| `InseForm1/2/3` e `VeriForm` | Copiam/verificam fórmulas em intervalos definidos | Substituir dependências de cópia manual por cálculos consistentes |
| `Botão60_Click` | Copia campos para a folha `Perfis` de `Armazem Chapa.xlsx` | Investigar a ligação operacional ao armazém; não comprova stock disponível |
| `ImpoColu` | Tenta atualizar tabelas dinâmicas em `TabDinPlaneamento` e `TabDinPlaneamentoAboc` | Indício de uma ligação anterior ao planeamento de colunas |

As duas folhas referidas por `ImpoColu` não existem no livro atual. O código de atualização na abertura do livro está comentado. A rotina de armazém usa posições de colunas que já não correspondem ao significado esperado: filtra a coluna 50 e escreve `X` em `AX`, atualmente a área unitária. Esta rotina não aparece associada aos botões identificados no ficheiro atual. São sinais de código antigo; não é correto assumir que todas as macros ainda representam o processo em utilização.

Nos livros de cantoneiras as rotinas encontradas alteram principalmente a apresentação. Nos dois livros de chapa existe uma rotina que arquiva e apaga linhas fechadas ou com erro de pesquisa. Não foi encontrado nesses procedimentos um motor que distribua trabalhos pelas horas disponíveis das máquinas.

**O Excel contém a informação de partida para uma fila.** `AQ` guarda a máquina indicada, `I` a data de corte e `AR` uma data prevista. Nas células inspecionadas, estas atribuições são valores guardados, não resultados de uma fórmula que escolha automaticamente a máquina ou uma vaga. A ausência de fórmula não prova se foram escritos à mão ou importados de outro sistema; demonstra que este livro não apresenta um cálculo automático dessas escolhas.

`K`, a data CPIS, procura a data `dataentregadl` na lista de ordens. A ligação CPIS lê uma vista de ordens de fabrico; a consulta de Picking lê `mtg2.pickingprodcab_pesq_vw`. Picking traz OF e semana. Esta semana é um sinal de necessidade/prioridade, não uma prova de que o material já está separado no armazém.

É necessário manter três datas distintas: quando o destino precisa das peças; quando o corte deveria estar concluído para permitir os passos seguintes; e quando o novo plano prevê executar o trabalho. No backlog, 431 linhas têm a data de corte 14 dias antes da entrega CPIS, mas há muitos outros intervalos. Não se deve aplicar uma antecedência universal de duas semanas a todos os produtos.

**O saldo de corte já tem uma regra verificável.** A fórmula de `Qtd em Falta` é `N − V`: quantidade pedida menos o contador `Ser.`. A aplicação deve continuar a consumir o resultado pelo contrato específico MTG2, preservando a origem. No livro atual, `Ser.` é preenchido sobretudo por números e ocasionalmente por somas como `4+8`. Para abocardar existe outro contador, e a fórmula de `Fechado` considera esse contador quando a operação está assinalada. Um trabalho cortado pode, por isso, continuar aberto por falta de outra operação.

**Consegui reconstruir os cálculos das macros.** Transcrevendo as onze funções geométricas para um cálculo independente, foi possível recalcular 5.684 linhas, todas coincidentes com o valor guardado no Excel. A primeira comparação tinha oito divergências porque usava a quantidade `N`; a fórmula de área usa `AH`. A verificação foi corrigida no [aprofundamento](/home/luis/projects/kanban-mes-mtg2/docs/planeamento-mtg2-2026-09-09/conclusao-aprofundada.md). Há ainda 11 linhas sem entradas numéricas suficientes e 1.298 linhas que exigem o catálogo de perfis. Podemos reutilizar a lógica sem executar o Excel; reproduzir a fórmula não equivale a validar fisicamente todas as dimensões.

O cálculo de horas usa a área de corte e a capacidade histórica da máquina. Por exemplo, para um tubo redondo calcula a área do anel de metal na secção, multiplica pelos cortes previstos e divide pela capacidade. A preparação, movimentação, corte em feixe e outras operações exigem complementos. As capacidades disponíveis são antigas; o primeiro resultado deve ser uma estimativa identificada, ajustada posteriormente com execução observada.

**Um exemplo de como colocaria trabalho num dia.** Selecionaram-se apenas três trabalhos reais, todos com MEBA indicada no plano. Este exercício não é o plano completo da máquina: há outros trabalhos que também disputam capacidade.

Para mostrar o mecanismo, suponha-se um dia com oito horas úteis, os materiais confirmados e 20 minutos de preparação por trabalho. As durações abaixo usam a fórmula de corte com a capacidade histórica da MEBA, acrescida dessa preparação hipotética.

| Ordem no exemplo | Trabalho real | Quantidade | Data de corte na fonte | Entrega CPIS | Tempo aproximado com preparação |
|---|---|---:|---|---|---:|
| 1 | OF264576 / 5564V001 — tubo 60 × 2,6 | 42 | 28/08/2026 | 11/09/2026 | 45 min |
| 2 | OF264576 / 5564V002 — tubo 108 × 3 | 42 | 28/08/2026 | 11/09/2026 | 1 h 12 min |
| 3 | OF264760 / CI5021A4000 — tubo 76 × 2,6, comprimento 3.250 mm | 396 | 04/09/2026 | 18/09/2026 | 5 h 17 min |

As duas primeiras tarefas têm necessidade mais próxima. Dentro deste pequeno exemplo, entram primeiro. A terceira entra depois. O total, antes de arredondar, é cerca de 7 h 13 min, deixando aproximadamente 47 minutos das oito horas. O sistema só acrescentaria outro trabalho que coubesse e estivesse disponível. Estes números ilustram a regra; não são tempos medidos nem uma ordem autorizada para a fábrica.

As datas de corte já passaram. O sistema deve assinalar esse atraso e verificar o impacto nos passos seguintes; terminar o corte não garante cumprir a entrega CPIS. Se o material da primeira tarefa não estiver disponível, ela fica bloqueada e a fila é recalculada com outro trabalho executável. Se a terceira tarefa demorar mais do que o previsto, o restante é reagendado. Uma divisão em lotes só deve ser feita quando permitida pelo processo.

**O que o planeador teria de confirmar no início.** Uma pequena tabela com as horas disponíveis por máquina; a indicação de material disponível para os trabalhos escolhidos; as máquinas autorizadas e alternativas; e as prioridades excecionais. O resto seria obtido das linhas do plano e dos registos de produção. O sistema apresentaria uma proposta e explicaria cada decisão, incluindo o trabalho que ficou de fora.

Depois de aceite o plano, guardar-se-ia essa versão, à semelhança da intenção de `AbrirSemana`. No fecho, comparar-se-ia a execução com essa versão e atualizar-se-ia apenas o saldo ainda não incorporado na fonte. Essa informação permitiria corrigir as estimativas futuras.

**As macros revelam três fontes adicionais que ainda não estão disponíveis.** `Historico_Plan_Perfis.xlsx` é referido em `HistPlan.bas`, na unidade de rede `I:`. `Armazem Chapa.xlsx`, folha `Perfis`, é referido em `Module8.bas`, na unidade `G:`. `PadraoPerfis.xlsx` aparece na ligação externa do livro. Nenhum foi encontrado no inventário da pasta Drive nem na pesquisa pelos nomes nos projetos locais consultados. O primeiro pode esclarecer a comparação previsto/realizado; o segundo pode esclarecer o circuito de armazém. O conteúdo e a atualização desses ficheiros não foram confirmados.

Fontes: VBA extraído de `Met2_Plan_Perfis.xlsm`, especialmente `Module11.bas`, `Module6.bas`, `HistPlan.bas`, `FuncAreaPerf.bas`, `VeriForm.bas`, `Module8.bas` e `ImpoColu.bas`; fórmulas e ligações do mesmo livro; snapshot `mtg2_d92027db24c68fee`, linhas 5387, 5388 e 5572. Ver [inventário das macros](/home/luis/projects/kanban-mes-mtg2/docs/planeamento-mtg2-2026-09-09/inventario-macros.json) e [resultados da reconstrução e do exemplo](/home/luis/projects/kanban-mes-mtg2/docs/planeamento-mtg2-2026-09-09/validacao-macros.json).
