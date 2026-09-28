# Regras de planeamento e registo MTG2 — confirmação de 10/09/2026

Este documento incorpora as seis respostas operacionais recebidas em 10/09/2026 e a clarificação anterior de `Data Corte`. Substitui as hipóteses anteriores sobre contadores, datas, stock, escolha de máquinas, passagem de parcelas entre corte e abocardar e registo em OF fechadas. A aplicação ainda não foi alterada; são requisitos para a proposta de sistema.

**Os contadores acumulam peças boas, por linha de produção.**

Cada novo registo válido de produção acrescenta a quantidade boa ao contador anterior da linha correspondente:

| Máquina do registo | Contador que recebe o incremento |
|---|---|
| Abocardar | `Aboc.` |
| Todas as restantes opções autorizadas | `Ser.` |

As peças rejeitadas são registadas no verso do Kanban e não contam como produção boa. Não se somam aos contadores. `Ser.` deve ser entendido como o acumulador das restantes máquinas abrangidas pela regra, sem reduzir o seu significado apenas a serrotes específicos.

A soma tem de ocorrer uma única vez por registo. Uma nova importação, exportação ou cópia do mesmo Kanban não é nova produção. A correspondência deve preservar a linha de origem e distinguir OF, referência e comprimento/perfil, pois existem referências repetidas na mesma OF e IDs repetidos no Excel.

Como decisão técnica proposta, o incremento é aplicado quando o registo é validado; uma correção posterior ajusta a contribuição identificada desse registo. Continua por definir onde se escreve o contador autoritativo e como a atualização é reconhecida na importação seguinte do Excel. A resposta operacional confirma a regra de soma, mas não prova que o circuito atual já implemente essa soma automaticamente.

**As três referências de prazo têm funções diferentes.**

| Campo | Significado confirmado | Utilização proposta no sistema |
|---|---|---|
| `Data Corte` | Data prevista de corte | Referência do planeamento atual; origem humana provável, ainda não confirmada |
| `Picking` | Semana em que o setor seguinte demanda a obra/material pronto | Orientar a necessidade de entrega da MTG2 ao setor seguinte |
| `Data Cpis` | Data fim prevista para a Produção entregar a obra no último setor | Avaliar o impacto futuro nos restantes setores e no compromisso final de produção |

Não se converte `Data Cpis` diretamente no prazo de corte nem se aplica uma antecedência fixa presumida. Para calendarizar o Picking, falta definir o ano e o dia limite dentro da semana. Também falta acordar o comportamento quando Picking e Data Corte não estão alinhados.

No snapshot de 09/09 `mtg2_d92027db24c68fee`, das 1.083 linhas de corte candidatas em OF ativas, 165 têm Picking positivo, 625 estão vazias e 293 têm zero. O sistema não deve transformar zero/vazio numa semana de necessidade. A alternativa proposta é usar Data Corte como referência provisória nesses casos, assinalando a ausência de Picking para revisão. Esta alternativa é uma proposta, não uma regra já confirmada pela empresa.

**O controlo de stock fica fora da primeira fase.**

Não existe controlo de stock de matéria-prima no ficheiro. A integração com SAP para matéria-prima pertence à segunda fase. Também não existe gestão de stock de produto acabado: a produção responde às necessidades das linhas e as quantidades boas realizadas constam de `Ser.` e `Aboc.`.

A primeira fase propõe carga, sequência e acompanhamento das necessidades, sem declarar disponibilidade de material, fazer reservas de stock ou exigir uma integração de armazém para funcionar. A viabilidade material continua a ser verificada pela operação no processo existente; o planeador pode ajustar a fila perante uma indisponibilidade conhecida. Não se apresenta o plano como uma garantia de material disponível.

Também não se calcula stock intermédio físico através de `Ser. − Aboc.`. Os contadores representam execução das respetivas operações, não inventário de peças numa localização. O saldo de uma operação e o stock são conceitos diferentes.

**A lista de escolhas de máquina vem da folha `Dados`, coluna B.**

O catálogo deve ser lido dessa coluna na versão do ficheiro utilizada. Na fotografia de 09/09, foram encontrados:

- Serrote Disco pav 1;
- Serrote MEBA IS381 Pav 3;
- Serrote Fita Thomas IS639 Pav.1;
- Serrote Fita Maqfort Pav 3;
- Vanguard;
- Corte Tubo Laser;
- Abocardar;
- MTG3;
- Serrote Doall Pav.1;
- Subcontrato.

Estes são os valores de escolha confirmados pela fonte indicada. A sua presença não fornece horários, capacidades ou compatibilidade de cada trabalho com cada recurso. As outras colunas da folha não devem ser tratadas como relações máquina/equipa/material apenas por aparecerem na mesma linha. Existe a designação `Corte Tubo Plasma` na folha de capacidades antiga; não foi assumida equivalência com `Corte Tubo Laser`.

**Corte e abocardar são operações distintas, sem passagem de parcelas entre elas.**

Retira-se da proposta a transferência automática de parcelas cortadas para abocardar e a regra de libertar trabalho para abocardar a partir da diferença entre os contadores. Os registos e as filas das operações mantêm-se separados.

A proibição de passagem de parcelas não define, por si só, a regra completa de entrada na fila de abocardar. Essa regra continua a precisar de descrição operacional. Também não permite concluir que todos os registos dentro de uma mesma operação tenham de representar a quantidade total da linha. Os contadores continuam a acumular as quantidades boas efetivamente registadas.

Os exemplos anteriores de “peças já cortadas prontas para passar para abocardar” deixam de sustentar decisões automáticas de planeamento. Uma eventual diferença entre quantidade autorizada e `Aboc.` pode descrever o saldo dessa operação quando ela é exigida; não demonstra disponibilidade física ou autorização de transferência.

**OF fechada no CPIS não admite novos registos de produção.**

O programa deve procurar para registo apenas OF abertas no CPIS. Uma OF fechada pode ter sido anulada com quantidades ainda por executar; um saldo positivo no Excel não permite ultrapassar esta regra.

A filtragem deve abranger pesquisa/seleção e a validação final do novo registo, usando o estado CPIS mais recente disponível. Uma seleção feita antes de a OF fechar não autoriza um registo posterior ao fecho. Uma OF sem estado CPIS confirmado também não deve ser apresentada como aberta. Registos históricos permanecem como histórico; não são novas autorizações de produção.

Nos dados analisados existem os estados `Em Aberto`, `Em Produção` e `Fechada`. A tradução proposta de “OF abertas” é permitir `Em Aberto` e `Em Produção`, bloqueando `Fechada` e estados desconhecidos. Esta enumeração é uma interpretação técnica a validar antes de codificar a regra. Não existe autorização para uma exceção manual que permita registar numa OF ainda fechada no CPIS.

**O âmbito da primeira versão fica assim definido.**

1. Importar necessidades e estado CPIS, mantendo a origem e a identidade da linha.
2. Apresentar para novo registo apenas OF abertas, segundo o mapeamento de estados validado.
3. Escolher a máquina a partir de `Dados!B` e acumular peças boas no contador correto, uma vez por registo.
4. Propor filas separadas por operação/máquina, usando Data Corte e a necessidade expressa pelo Picking; mostrar impacto na Data CPIS.
5. Usar calendários e tempos confirmados para calcular carga e previsões; guardar a proposta aceite e acompanhar a execução.
6. Manter stock de matéria-prima/SAP para a segunda fase e não introduzir gestão de stock de produto acabado.

**Os pontos ainda em aberto são específicos.**

- Horas úteis e restrições de operadores por recurso; tempos de preparação e execução por operação, incluindo validade das capacidades antigas.
- Data limite associada ao Picking, incluindo ano, dia da semana, campos vazios/zero e conflitos com Data Corte.
- Regra operacional para um trabalho entrar na fila de abocardar, sem passagem de parcelas do corte.
- Mapeamento exato dos estados CPIS permitidos e frequência de atualização do estado consultado.
- Quantidade autorizada quando `QTD` e `QTD [un,]` diferem, significado dos contadores vazios e dos sinais de operação ainda não esclarecidos.
- Destino da escrita dos contadores, identificação dos registos já incorporados e tratamento de correções, evitando somas repetidas.
- Qualidades/dimensões por corrigir e compatibilidades de trabalhos com os recursos do catálogo.

As contagens de 09/09 são evidência da fotografia analisada; não representam uma nova medição dos dados operacionais de 10/09.
