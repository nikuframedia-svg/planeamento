# MTG2 Perfis: o que os dados permitem fazer de facto

**Atualização de 10/09/2026:** as [regras confirmadas pela operação](/home/luis/projects/kanban-mes-mtg2/docs/planeamento-mtg2-2026-09-09/regras-confirmadas-2026-09-10.md) substituem as hipóteses deste relatório sobre prazos, disponibilidade/stock, transferência de parcelas entre corte e abocardar e registo em OF fechadas. Picking é a semana de necessidade do setor seguinte; stock/SAP fica para a fase 2; não há passagem de parcelas para abocardar nem novos registos em OF fechadas no CPIS. Os contadores acumulam peças boas, sendo Abocardar para `Aboc.` e as restantes máquinas para `Ser.`. As medições abaixo continuam a referir-se aos dados de 09/09.

**É viável construir um planeamento assistido útil. O primeiro âmbito que os dados sustentam melhor é uma fila por lotes na MEBA, ligada ao trabalho de abocardar. Ainda não há evidência suficiente para prometer um calendário automático fiável de toda a MTG2.** Esta conclusão resulta de cruzar quantidades, operações, versões do plano, produção validada, fórmulas VBA e folhas digitalizadas. O benefício inicial seria identificar o trabalho certo e os bloqueios, propor uma sequência e acompanhar a execução.

A referência é 09/09/2026, snapshot `mtg2_d92027db24c68fee`. A comparação temporal usa `mtg2_04272ec2df94d0b9`, de 08/09. Mantém-se o âmbito da pasta Drive descrito no [relatório inicial](/home/luis/projects/kanban-mes-mtg2/docs/planeamento-mtg2-2026-09-09/relatorio.md). Este aprofundamento não executou macros, alterou a aplicação, escreveu na base de dados ou emitiu ordens de produção. A análise de carga é um cálculo offline, sem atribuir datas de execução.

**A unidade de decisão deve ser o lote que satisfaz uma necessidade da operação seguinte.** A referência comercial, a linha do Excel, a operação e o lote executado têm de manter relações explícitas. Uma mesma referência pode aparecer em vários comprimentos; um corte pode servir uma etapa que ainda não está concluída; um pedido grande pode ser executado em vários lotes. Sem esta distinção, um algoritmo pode ordenar corretamente uma lista que representa o trabalho errado.

**1. O universo candidato é menor do que parece, mas há um âmbito inicial bem definido.**

| Filtro aplicado ao plano | Resultado | Significado |
|---|---:|---|
| Todas as linhas | 6.993 | Incluem histórico e trabalho já concluído |
| Saldo de corte positivo válido, sem `Fechado=X` | 1.597 | Ainda inclui conflitos com o estado CPIS |
| Das anteriores, OF `Em Produção` ou `Em Aberto` | 1.083 linhas, 271 OF, 86.197 peças | Universo candidato de corte |
| Máquina, qualidade, perfil classificado como completo, área positiva e entrega preenchidos | 388 linhas de 127 OF | Permite calcular e comparar uma proposta inicial |
| Todas as linhas de corte candidatas da OF cumprem esse filtro | 120 OF, 368 linhas | Cobertura dos cortes pendentes listados; não comprova conjunto completo |
| Linhas candidatas atribuídas à MEBA | 117, das quais 116 cumprem o filtro básico | Âmbito mais delimitado para um piloto |

As outras 495 linhas com falta positiva estão em OF fechadas no CPIS; 19 não têm estado utilizável. Devem conservar-se como exceções até se resolver a contradição. O estado ativo também não prova, sozinho, que a necessidade continue fisicamente válida.

Nas 1.083 linhas candidatas não existe preenchimento de `Data Material` nem de `Nº lote`. Isto significa ausência de confirmação de disponibilidade ligada às linhas, não ausência física de material. As 388 linhas com campos básicos continuam a precisar dessa confirmação, do calendário e de regras de execução.

**2. Parte dos dados em falta pode ser tratada por conjuntos pequenos.**

Há 280 linhas sem qualidade do aço, distribuídas por 21 OF e **23 conjuntos de OF, tipo e perfil**. Três OF concentram 246 dessas linhas:

| OF | Linhas sem qualidade | Perfis |
|---|---:|---|
| OF265424 | 117 | IPE330: 93; HEA240: 24 |
| OF265528 | 79 | Tubo 50×50×3: 78; barra 30×8: 1 |
| OF265004 | 50 | Tubo 50×50×3 |

É possível apresentar uma confirmação por conjunto, com as referências abrangidas, desde que a especificação desse conjunto confirme uma qualidade comum. Não é legítimo escolher a qualidade mais frequente da fábrica ou transportar a qualidade de outro componente apenas por pertencer à mesma OF. A pesquisa em linhas fechadas com a mesma referência, tipo e perfil não encontrou uma qualidade que permitisse resolver automaticamente estas 280 linhas.

O ficheiro [confirmacoes-qualidade.csv](/home/luis/projects/kanban-mes-mtg2/docs/planeamento-mtg2-2026-09-09/confirmacoes-qualidade.csv) deixa os 23 conjuntos preparados para essa verificação.

Há 431 linhas sem máquina. Para **122**, encontrei o mesmo tipo, perfil e qualidade conhecida em pelo menos três OF fechadas, sempre com uma única máquina indicada. Isto permite propor uma máquina com a explicação do precedente. Não demonstra limites físicos, aperto, ângulo, comprimento admissível ou disponibilidade. Os [122 candidatos](/home/luis/projects/kanban-mes-mtg2/docs/planeamento-mtg2-2026-09-09/sugestoes-maquinas.csv) estão marcados como não autorizados. As sugestões abrangem 22 combinações de perfil e máquina.

O registo de execução também mostra alternativas à máquina atualmente indicada no plano: em 24 registos de corte com identidade coincidente, a máquina registada difere da indicação atual, após normalizar os nomes. Por exemplo, há produção no Thomas para referências agora atribuídas ao Doall. Isto pode refletir alternativas ou mudanças posteriores do plano; não autoriza intercâmbio geral entre essas máquinas.

Das 46 linhas ativas com área zero, 40 correspondem a cinco possíveis diferenças de nomenclatura com o catálogo interno: `HEA240/HEA240A`, `HEB300/HEB300B`, `UPN80/UPN80x45`, `UPN65/UPN65x42` e `UPN100/UPN100x50`. São correspondências propostas para confirmação. As outras seis usam `UKT305x152x49`; não foi aplicada uma substituição presumida.

**3. Há trabalho real que uma fila de corte perderia.**

Nas OF ativas existem 41 linhas não fechadas assinaladas para abocardar. Três já têm saldo de corte zero; 39 não têm contador de abocardar preenchido. O vazio deve manter-se desconhecido.

| Linha e necessidade | Quantidade | Cortadas no contador | Abocardadas no contador | Leitura dos contadores |
|---|---:|---:|---:|---|
| 5571 — OF264759 / CI5021A4000 | 1.050 | 942 | 359 | 108 por cortar; 583 já cortadas à espera de abocardar; 691 de abocardar no total |
| 5573 — OF264760 / CI5021A4000, 2.600 mm | 840 | 840 | 209 | Corte sem falta; 631 ainda por abocardar |

São saldos derivados dos contadores da fonte, sujeitos à reconciliação da produção e sem considerar perdas ou retrabalho não registados. Na OF264760 existe também a linha 5572, com a mesma referência mas **3.250 mm**, e 396 peças ainda por cortar. Juntar apenas OF e referência confundiria estes trabalhos.

O sistema deveria mostrar quanto trabalho já pode seguir para abocardar e qual o lote necessário para alimentar essa operação. Poderia assim recomendar terminar uma necessidade em curso antes de acumular mais peças cortadas. Para garantir um conjunto final completo faltam relações de componentes e operações confirmadas; partilhar uma OF entre perfis, colunas e chapa não estabelece essa relação quantitativa.

**4. O retorno de produção já permite controlo, mas exige reconciliação explícita.**

Na linha 6682, **OF265528 / referência 2880**, a quantidade pedida é 72, o contador de corte é 60 e faltam 12. O MES contém três registos de 26/08 com 15, 30 e 15 peças: 60 no total. Os valores são consistentes com produção já incorporada no contador. Subtrair novamente os 60 às 12 em falta faria desaparecer trabalho pendente. Esta coincidência não substitui uma confirmação de incorporação de eventos, mas demonstra por que a regra de soma automática é inadequada.

Entre os dois snapshots, 6.989 linhas mantêm uma identidade única coerente; quatro foram excluídas por IDs repetidos. Houve alterações de saldo em 33 linhas e alterações de fecho em 25. As diferenças somam uma redução de 915 no saldo de corte bruto da fonte, incluindo sobreprodução. **Não são prova de 915 peças produzidas fisicamente em 09/09**: podem representar registos anteriores incorporados nessa atualização.

Dos 128 registos MES, 25 têm mais de uma linha candidata atual quando se usa somente OF e referência. São necessários o vínculo à versão original, comprimento/perfil e uma identidade persistente. Três vínculos apontam para um snapshot que já não está entre os cinco conservados no PostgreSQL; os outros 125 mantêm correspondência de posição e identidade com o plano atual. A posição da linha continua a não ser uma identidade permanente.

O circuito correto teria duas fontes de estado: saldo confirmado na fonte e eventos novos cuja incorporação nesse saldo ainda não ocorreu. Cada evento deve ter identidade e operação. Ao importar um novo plano, o sistema confirma o que foi incorporado e mantém os casos ambíguos em revisão. Deve guardar a versão do plano que estava comprometida, permitindo comparar execução e alterações posteriores.

**5. A quantidade de histórico não equivale a conhecer os tempos.**

Revi diretamente as páginas digitalizadas. No histórico, a linha Excel 84403, OF264870 / `5504T065`, apresenta **64** na coluna `Qtd [m]`. Na [folha digitalizada de 18/08](</home/luis/projects/DATARESEARCHMTG/Kanban's MTG2/18-08-2026.PDF>), o valor é 64 na coluna de quantidade, com comprimento 200 mm: corresponde a 12,8 m de peças. Outros registos da mesma folha apresentam a mesma situação. Há, portanto, evidência de quantidades de peças guardadas sob um cabeçalho de metros. Não foi atribuída essa unidade a todas as 13.442 linhas sem verificação.

Os 128 registos MES modernos vêm de 23 folhas validadas. Só **três folhas têm horas**, todas da Vanguard, somando 28 horas quando contadas uma vez por folha. Duas dessas folhas incluem pelo menos uma referência com área zero no plano, impedindo a comparação integral pelo modelo de secção.

Na folha de 27/08, as quatro linhas têm área utilizável. A fórmula histórica da Vanguard estima **33,3 horas**, enquanto a folha regista **10 horas**. O modelo não reproduz esta observação. Não se pode concluir que um coeficiente único de 3,3 resolva todas as referências: faltam observações sobre preparação, modo de execução, operações incluídas e distribuição das horas entre referências. Para a MEBA, não há horas preenchidas nestes registos validados que permitam uma calibração própria.

Assim, consigo produzir carga teórica e testar cenários. Não consigo retirar destes dados tempos atuais fiáveis por tarefa, eficiência por operador, disponibilidade efetiva ou horas exatas de conclusão. A solução é começar com estimativas operacionais explícitas e medir quantidade, duração e interrupções por lote. Estas medições devem alimentar a previsão, preservando a diferença entre horas de turno e horas de execução.

**6. O cálculo de carga revela por que é necessário dividir e libertar lotes.**

Reconstruindo área unitária × saldo, usando as capacidades de 11/11/2024 e o fator de três do Thomas quando a quantidade original excede 50:

| Máquina | Linhas ativas com máquina e área | Horas teóricas, sem preparação | Linhas que excedem 8 horas nesse modelo |
|---|---:|---:|---:|
| Disco | 188 | 624,7 | 4 |
| Vanguard | 127 | 695,1 | 12 |
| MEBA | 117 | 187,5 | 7 |
| Thomas | 55 | 20,4 | 0 |
| Doall | 125 | 130,2 | 2 |

Esta tabela inclui linhas sem qualidade; exclui linhas sem máquina ou com área zero. Não é a carga total comprovada da MTG2. Oito horas é apenas um limiar de comparação, não um turno confirmado. A [lista calculada](/home/luis/projects/kanban-mes-mtg2/docs/planeamento-mtg2-2026-09-09/carga-teorica-nao-calendarizada.csv) conserva OF, referência, comprimento, quantidade e origem do prazo.

Uma única linha, **OF264343 / CD04J001**, tem 41.304 peças em falta, quase 48% das 86.197 peças candidatas. No modelo do Disco ocupa 463,8 horas. A data de corte é 20/07; a entrega CPIS é 30/10. Uma regra que começasse pela data de corte mais antiga e executasse toda a quantidade de seguida poderia ocupar a máquina com esta linha durante muito tempo, adiando outras necessidades.

O planeamento deve permitir quantidades parciais autorizadas e limitar o que é libertado para a operação seguinte. No MES já existem referências executadas em várias parcelas, como o exemplo de 15 + 30 + 15 peças. Isso demonstra a existência de execução parcelada em alguns casos, sem estabelecer automaticamente tamanhos mínimos ou regras válidas para todos os trabalhos.

Os cenários de metade/dobro da velocidade, guardados nos resultados, mostram a sensibilidade da carga ao parâmetro. Não são intervalos estatísticos de confiança. O parâmetro atual da Vanguard falha uma comparação observada; não seria defensável transformar os totais acima diretamente em datas prometidas.

**Correção da verificação anterior das macros.** A primeira comparação usou a quantidade `N` onde a fórmula de área usa `AH`. Repetindo o cálculo com o argumento correto, **as 5.684 linhas geométricas recalculáveis coincidem com o Excel; não restam as oito divergências reportadas anteriormente**. Há 12 linhas em que N e AH diferem, 1.298 que dependem do catálogo e 11 sem entradas numéricas suficientes. Os dois campos de quantidade devem manter o seu significado próprio.

Reproduzir a fórmula continua a não validar os seus argumentos. As linhas 6752 e 6753, OF265695 / `5096V001` e `5096V002`, têm comprimento 2,9 mm, ângulos 1.404 e 674 e tipo `Varão redondo`. O cálculo aritmético coincide, mas a interpretação dimensional exige revisão. Uma hipótese seria dimensões deslocadas de um tubo; não foi aplicada essa correção sem desenho ou confirmação. A classificação atual de “perfil completo” não deteta esta incoerência.

**O sistema que construiria com esta evidência.**

1. **Mapa de necessidades por operação.** Mostrar os cortes pendentes, peças disponíveis para abocardar, trabalho posterior desconhecido, conflitos CPIS e produção por reconciliar. Identidade persistente com distinção de comprimento, operação e revisão.
2. **Fila proposta por máquina e lote.** Partir das máquinas já indicadas, de material confirmado e de prioridades de destino confirmadas. Mostrar quantidades, carga estimada, operações seguintes e razão da escolha. Limitar lotes grandes para não consumir toda a capacidade disponível nem acumular trabalho intermédio.
3. **Confirmações por conjunto.** Apresentar os 23 conjuntos sem qualidade, cinco correspondências de catálogo e precedentes de máquina. Conservar a aprovação e a fonte técnica; nunca transformar uma sugestão em facto silenciosamente.
4. **Compromisso do turno e retorno.** Guardar a fila aceite, executar, registar tempos por lote e reconciliar quantidades. Replanear o restante trabalho a partir desse estado, mantendo visível o que mudou.

**Começaria pela MEBA e pelo respetivo trabalho de abocardar.** Há 116 linhas de corte com campos básicos preenchidos e exemplos claros de precedência e trabalho em curso. Para transformar esse âmbito numa fila executável, faltam confirmações concretas: material para os lotes escolhidos, horas disponíveis, compatibilidade operacional e estimativas iniciais de tempo/preparação. A indicação atual da máquina é um ponto de partida para revisão. Não é preciso normalizar toda a fábrica antes de iniciar esse piloto.

Consigo construir já o mapa de necessidades, as exceções, os agrupamentos, a proposta explicada e o acompanhamento de versões. Com aquelas confirmações, consigo construir e operar um piloto assistido. Ficam dependentes de dados adicionais a promessa autónoma de horas de conclusão, a escolha livre entre máquinas, a otimização com stock real de barras/remanescentes e a garantia de conjuntos finais completos. Nenhuma percentagem de poupança ou redução de prazo foi demonstrada nesta análise.

**Evidência reproduzível.** O [script de análise](/home/luis/projects/kanban-mes-mtg2/docs/planeamento-mtg2-2026-09-09/analise_aprofundada.py) gera os CSV e [resultados detalhados](/home/luis/projects/kanban-mes-mtg2/docs/planeamento-mtg2-2026-09-09/resultados-aprofundamento.json), com identificação e hashes dos extratos. A correção das macros está também em [validacao-macros.json](/home/luis/projects/kanban-mes-mtg2/docs/planeamento-mtg2-2026-09-09/validacao-macros.json). Fontes primárias adicionais: [plano de perfis](/home/luis/projects/DATARESEARCHMTG/Met2_Plan_Perfis.xlsm), [histórico de perfis](/home/luis/projects/DATARESEARCHMTG/Modelo_BaseDados_PerfisCantoneiras.xlsx), tabelas `raw_mtg`, `core_mtg`, `mes_kanban` e backup MTG2 de 09/09, já identificados no relatório inicial.
