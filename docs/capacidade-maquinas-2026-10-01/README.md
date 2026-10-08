# Capacidade das máquinas MTG2/MTG3 e reforço do algoritmo — 1 de outubro de 2026

Estudo feito sobre os Excel atuais (MTG3 de 30/09, MTG2 de 29/09), o MES (folhas desde 19/08) e a camada v2, só em leitura. Os números repetem-se com `analisar.py` nesta pasta. Nada disto altera o Excel, o MES ou decisões gravadas.

## 1. O que os dados dizem sobre a capacidade

**MTG3 — débito executado por semana (16 semanas completas, 08/06–27/09).** Cada linha do Excel tem o dia em que foi produzida, a máquina, os metros e as horas teóricas trabalhadas (`h teor. Trab` = metros ÷ velocidade). Somando por máquina e semana obtém-se o trabalho realmente executado, **na mesma unidade das horas da carteira**:

| Máquina | Horas teóricas/semana (P25 – mediana – P75) | Metros/semana (mediana) |
| --- | --- | ---: |
| Ficep Rapid 20T-1 | 63 – **72** – 78 | 3 228 |
| Ficep Rapid 20T-2 | 59 – **73** – 81 | 3 283 |
| Ficep Rapid 25T | 62 – **77** – 85 | 2 643 |
| Ficep XP T4 | 79 – **86** – 104 | 10 378 |
| Ficep XP T6 | 74 – **95** – 100 | 10 858 |
| Peddi 8 | 39 – **52** – 75 | 6 165 |
| Peddi 6 | 15 – **19** – 23 (2 semanas sem registo) | 1 017 |

As três Rapid executam ~72–77 h/semana sem nenhuma semana vazia: trabalham perto do limite (cerca de 2 turnos). Ficaram de fora 1 394 linhas com várias datas («20+21/08»), 1 947 com data zero do Excel e 6 352 sem data.

**Quão previsível é?** Prevendo cada semana com a mediana das 8 anteriores (24 semanas de teste): erro de **17–30%** por máquina (Peddi 6: 41%). O intervalo P25–P75 contém a semana real em 38–53% dos casos. Conclusão: usar um intervalo, nunca uma data exata.

**Velocidades do Excel (`Mt\h`).** Quase fixas por máquina: Rapid 20T 45 m/h, Rapid 25T 35 m/h, Peddi 6 50 m/h. XP T4/T6 e Peddi 8 variam entre 80, 100 e 120 m/h sem relação limpa com a espessura; usa-se a mediana por máquina e perfil (com 3 ou mais linhas), senão a da máquina.

**MTG2 — disponibilidade declarada.** `PlanDisponibilidadeSemanal` tem 2025–2026: Disco pav.1 mediana 37,5 h, Fita/Thomas 75 h, MEBA 37,5 h, Vanguard 112,5 h por semana. A W39/2026 tem linhas isoladas de 8 h e um conflito na Vanguard (80 h e 32 h), por isso usa-se a mediana de todas as semanas, com amplitude, e exigem-se pelo menos 4 semanas. O Excel MTG2 não tem datas de produção por linha, logo não há débito executado para a MTG2.

**MES.** Só 3–5 folhas por máquina têm horas utilizáveis; as horas estão escritas de muitas formas («7.30hs», «11:30», «7,5 H», «150») e o campo convertido no MES tem valores impossíveis (730, 1130 h). O rendimento real em m/h fica como controlo indicativo (`mes-horas-e-rendimento.csv`), não como base. **Corrigir a leitura das horas no MES é uma melhoria do lado do MES**, não deste projeto.

## 2. O que mudou no algoritmo

1. **Capacidade com cenários identificados.** Por recurso: calendário confirmado → orçamento confirmado → débito observado (MTG3, mediana ou P25) → disponibilidade declarada (MTG2, mediana ou P25, por validar) → por confirmar. A vista escolhe o cenário («Só confirmada» desliga as estimativas). Uma estimativa nunca aparece como «confirmada».
2. **Pressão calculada só sobre o que tem capacidade conhecida.** Postos sem dados (plasma, prensa, soldadura) deixaram de tornar todo o setor «por confirmar»; a sua procura aparece à parte. Postos compostos contam o posto quando tem capacidade própria, senão as máquinas que o compõem — nunca os dois.
3. **Recurso limitante e semanas de carga por máquina**, ao ritmo da capacidade do cenário.
4. **Horas estimadas** para linhas sem horas no Excel: metros ÷ velocidade mediana do Excel da máquina e perfil (MTG3); saldo × área ÷ taxa mm²/h (MTG2, sem o ×3 da Thomas). Sempre separadas das horas documentais. Operações seguintes continuam sem horas, porque não há taxas para elas.
5. **Máquina sugerida** para linhas sem máquina, por esta ordem: máquina das outras linhas da mesma OF, operação e perfil (mesma preparação); precedente da peça em 2 ou mais OF, depois 1; sem condições de terceiros (mercado nacional da Peddi 6, mudança 112 → 119); menor carga em semanas; trabalho mais urgente primeiro. Uma sugestão nunca tira trabalho a uma máquina atribuída.
6. **«Aceitar as sugestões»** no menu de máquinas: cada ocorrência do grupo recebe a sua máquina sugerida, com a sua elegibilidade, numa única ação que se pode desfazer.
7. **Gantt:**
   - prefere a máquina das linhas da mesma OF, operação e perfil;
   - não escolhe uma opção condicional de terceiros só pelo código do recurso (antes, sem calendários, ganhava a ordem alfabética);
   - com velocidades divergentes no Excel para a mesma máquina e perfil, usa a mediana ponderada, declarada como estimativa, em vez de deixar a duração desconhecida.
8. **Corrigido:** uma decisão de máquina gravada para outra variante técnica podia aparecer como «preferência» quando a escolha automática coincidia com a mesma máquina.

## 3. Validação da sugestão de máquina

Nas 3 051 linhas da MTG3 que já têm máquina no Excel, escondi a máquina e comparei com a sugestão (`validacao-sugestoes.csv`):

| Situação | Linhas | Mesma máquina | Mesmo tipo (Rapid/XP/Peddi) |
| --- | ---: | ---: | ---: |
| Grupo com linhas vizinhas já decididas pelo planeador | 2 936 | 99,9% | 99,9% |
| **Grupo novo, sem vizinhas** | 115 | **51,3%** | **89,6%** |

A máquina do Excel está entre as candidatas em 99,6% das linhas. O primeiro valor mede sobretudo coerência com o resto do lote. **O número honesto para decisões novas é o segundo**: o tipo de máquina acerta-se em 9 de cada 10 casos, mas entre máquinas equivalentes (as três Rapid) a escolha do planeador não se explica pelos dados — o algoritmo usa a carga. Testei também o histórico do mesmo perfil noutras referências: só +3,5 pontos, por isso não entrou.

## 4. Carga atual que resulta (horizonte de 12 semanas, cenário mediana)

> **Atualizado ao fim do dia:** a tabela abaixo é anterior à análise dos padrões. O código 112/119 não decide a máquina; o que decide é o tamanho da série. Com essa regra, as Rapid ficam a ~12 semanas e o recurso limitante passa a ser a Peddi 8 (~33). Ver [PORQUE.md](PORQUE.md).

| Recurso | Carga (h) | das quais estimadas | Capacidade/semana | Semanas de carga |
| --- | ---: | ---: | --- | ---: |
| Ficep Rapid 20T-2 | 2 683 | 2 547 | 73 h · observada | **36,7** |
| Ficep Rapid 20T-1 | 2 595 | 2 377 | 72 h · observada | **36,2** |
| Ficep Rapid 25T | 1 720 | 1 564 | 77 h · observada | 22,4 |
| Peddi 8 | 1 037 | 0 | 52 h · observada | 20,1 |
| Serrote Disco pav 1 | 654 | 10 | 37,5 h · declarada | 17,4 |
| Peddi 6 | 194 | 137 | 19 h · observada | 10,3 |
| Serrote MEBA | 268 | 36 | 37,5 h · declarada | 7,1 |
| Vanguard | 662 | 209 | 112,5 h · declarada | 5,9 |
| Ficep XP T4 / T6 | 137 / 150 | 0 / 37 | 86 / 95 h · observada | 1,6 / 1,6 |

**Leitura para o planeador:** quase todo o trabalho sem máquina da MTG3 é operação 119 (broca), que só as Rapid (e a Peddi 6, com condição de mercado nacional) fazem. Isto dá ~7 000 h teóricas para ~220 h/semana das três Rapid. As XP (punção, 112) têm folga, mas não fazem 119 sem uma decisão técnica explícita. **Antes de agir sobre este número é preciso confirmar se as ~12 500 linhas MTG3 sem máquina são de facto trabalho a fazer** (muitas estão em 64 OF atrasadas, algumas com mais de 90 dias). Se forem, o gargalo é real e estrutural, não de planeamento.

## 5. Limites

- O débito observado mede o que foi **executado**, não o máximo possível: em semanas com pouca procura subestima a capacidade.
- Horas estimadas usam a velocidade do Excel, que já é uma convenção do planeador; o MES não tem horas suficientes para a calibrar.
- Postos de segundas operações, abocardar e laser/plasma continuam sem capacidade nem taxas.
- A semana é ISO (segunda a domingo). A fábrica parece usar quinta a quarta em parte do ano; não está confirmado.

## Ficheiros

`debito-semanal-mtg3.csv`, `validacao-previsao-semanal.csv`, `validacao-sugestoes.csv`, `carga-por-maquina.csv`, `velocidades-excel.csv`, `mes-horas-e-rendimento.csv` e `resumo.json`. Código: `app/sector/throughput.py`, `app/sector/estimates.py`, `app/sector/capacity.py`; testes em `tests/test_capacity_study.py`.
