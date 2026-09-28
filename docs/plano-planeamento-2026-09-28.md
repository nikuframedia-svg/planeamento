# Planeamento MTG3 e MTG2 — o que pediste, como vai funcionar e os passos para lá chegar

*Aprovado pelo Luís a 28/09/2026. É uma análise e um plano: ainda não foi alterado código, serviços nem base de dados. Cada semana só começa quando o Luís disser "avança com a semana X". Decisões tomadas: MTG3 primeiro; a aplicação propõe e o Excel continua oficial até à data de passagem; o wall é a fila de cada máquina no Gantt do sistema; painel vermelho com 3 dias úteis e todas as OF abertas no CPIS; referência mestre = código do modelo no início da referência. Provas e programas da análise em `/home/luis/projects/kanban-mes-mtg2/docs/analise-planeamento-2026-09-25/pedido-2026-09-28/`.*

## Em resumo

- **Tudo o que pediste é possível com os dados que já existem.** Começamos por MTG3 Cantoneiras, como decidiste.
- **Um primeiro planeamento utilizável fica pronto em cerca de 3 semanas:** escolher o trabalho, dar máquina, ver a fila de cada máquina no Gantt e ter o painel vermelho. MTG3 completo leva cerca de 5 semanas. MTG2 leva mais 2 a 3.
- **Durante a transição o Excel continua a ser o plano oficial.** A aplicação mostra propostas. No dia combinado com o planeador, a aplicação passa a mandar nesse setor.
- **A Carteira abre por referência, como pediste:** primeiro o modelo (por exemplo DLT), depois cada referência (SKU) e depois as OF. Há também um **Catálogo de referências** para ver em que máquinas cada SKU já foi feito.
- **A máquina não sai da 1.ª operação,** ao contrário do que parecia. Os dados mostram que o 119 e o 112 aparecem nas 7 máquinas. Por isso a aplicação vai **sugerir duas máquinas, com as provas**, e quem decide é o planeador.
- **O trabalho mais urgente é o que ainda não tem máquina:** 107 km em MTG3, já atrasados ou para as próximas 3 semanas. Dar-lhe máquina é a primeira decisão a pedir ao planeador.
- **Antes de construir há três arrumações** que protegem o que se faz: guardar o código num histórico, confirmar as cópias de segurança e pôr login.

## O que pediste e como vai ficar

| O que pediste | O que vais ver na aplicação | Quando |
|---|---|---|
| Validar o que se quer planear, antes do Gantt e do wall | Página **"Carteira"** com todo o trabalho aberto e o botão **"Planear"**. Só o que for planeado segue para o Gantt | Semana 1 |
| Agrupar várias OF por tema | **Vista padrão por referência:** referência mestre (o modelo, por exemplo DLT) → referência específica (SKU, por exemplo DLT319) → OF. Cada nível mostra os totais e as máquinas. Há outras vistas: por OF/obra, por perfil (L45), por família e por cliente | Semana 1 |
| Ver em que máquina se faz cada referência | **"Catálogo de referências":** pesquisa-se um SKU ou uma referência mestre e vê-se em que máquinas já foi feita (OF, km, última vez) e em que máquina está o trabalho aberto | Semana 2 |
| Máquina automática a partir dos dados | Para cada grupo de peças, as máquinas que já fizeram esse perfil e a fila de cada uma. Mais tarde, duas sugestões automáticas | Semanas 2 e 4 |
| L45: escolher em bloco ou em detalhe | Vista por perfil: "atribuir este perfil a…" (bloco) ou peça a peça (detalhe), vendo antes o efeito na fila da máquina | Semana 2 |
| O wall | A fila de cada máquina **no Gantt do sistema**, pela ordem publicada, com o que já foi feito | Semana 3 |
| Painel vermelho | Tabela vermelha com três situações: aberta e não planeada; planeada e sem avanço; parada há mais de 3 dias úteis | Semanas 3 a 5 |
| Família de produto | Coluna, filtro e pesquisa por família | Semana 1 |
| "Setor" em vez de "Área" | No registo: **"Setor: MTG2 Perfis / MTG3 Cantoneiras"** | Semana 1 |

## Como vai funcionar no dia a dia — um exemplo com uma OF real

A **OF264095** (Painhas, "POSTES YDT") tem escrito "1 PRIORIDADE" e está atrasada desde 28/07. Ainda tem 6,2 km por cortar: 2,4 km já com máquina e 3,8 km sem máquina.

1. **Carteira.** A Carteira de MTG3 abre na vista por referência: cada modelo, com as suas referências e as OF que as pedem. Na vista por OF (um clique), a OF264095 aparece no topo, com a etiqueta "1 PRIORIDADE" e a indicação "atrasada". A aplicação já a propõe para planear.
2. **Planear.** O planeador confirma com o botão "Planear". Fica registado quem o fez e quando.
3. **Máquina.** Na vista por perfil (L45), o planeador vê os perfis desta OF que ainda não têm máquina. Para cada um vê:
   - que máquinas já cortaram esse perfil, quantos km e quando;
   - quantas semanas de trabalho cada máquina tem em fila.

   Escolhe a máquina. Antes de gravar, a aplicação mostra o efeito, por exemplo: "a fila da XP T4 passa de 1,6 para 1,8 semanas" (números de exemplo).
4. **Fila.** A aplicação calcula a fila de cada máquina para as próximas semanas, pela ordem: primeiro a prioridade escrita, depois a Data Corte, e só depois o número `P` do Excel.
5. **Publicar.** O planeador revê o Gantt e carrega em "Publicar". Essa versão fica fixa. No Gantt, cada máquina mostra a sua fila, e esta OF aparece em primeiro nas máquinas escolhidas.
6. **Acompanhar.** Quando o MES valida folhas desta OF, o Gantt mostra o que já foi feito. Se passarem mais de 3 dias úteis sem produção, a OF aparece no painel vermelho.

## O que os dados mostraram (o essencial)

- **A carteira de MTG3 tem 336 km por cortar em 119 OF.** 258 km ainda não têm máquina. Em MTG3, o planeador dá máquina à OF inteira ou a nada.
- **O mais urgente:**
  - 107 km sem máquina, já atrasados ou para as próximas 3 semanas;
  - ao mesmo tempo, as máquinas XP estão ocupadas com 34 km que só são precisos depois de 18/10.
- **Capacidade das 7 máquinas de MTG3:** cerca de 31 km por semana num ritmo que se atinge em 3 de cada 4 semanas.
  - Tudo o que é para cortar até 18/10 dá cerca de 4 semanas de trabalho. **Não cabe em 3 semanas.**
- **Há informação escrita nas descrições do Excel que ninguém estava a usar:**
  - 5 OF com prioridade escrita;
  - 8 OF marcadas **"anulada"** que continuam abertas (29 km; confirmei no Excel original);
  - 1 OF feita fora, na Eletrofer (2,9 km);
  - 4 OF que só se podem fazer depois de uma validação.
- **As referências têm o modelo no início do código.** DLT220 e DLT319 são do modelo DLT; CI7812A4046 é do CI7812.
  - Em MTG3 há 31.374 referências diferentes. A regra proposta dá 342 modelos, e só 0,3% das linhas ficam "por confirmar".
  - Os 20 maiores modelos (DLT, DLA, DLR, H92, QT, ED4, DLS, CWA, CWR…) cobrem 56% das linhas.
  - Nos postes DLT, DLA e DLR o código bate com o modelo escrito na OF em 96–98% dos casos.
  - Em MTG2 a mesma regra dá 808 modelos, com 2,9% por confirmar.
  - **A mesma referência passa por várias máquinas.** A DLT319, por exemplo, aparece em 66 OF, cortada em 4 máquinas diferentes. Por isso vale a pena ver o histórico por referência.
- **A família de produto está em todas as OF abertas.**
  - Em MTG3 quase não separa nada: 96,5% é "Postes Treliçados".
  - Em MTG2 é útil: há 13 famílias, e ajuda a sugerir a máquina.
- **Painel vermelho, com as tuas regras** (3 dias úteis; todas as OF abertas no CPIS):
  - Há 1.924 OF abertas no CPIS. **1.238 não têm peças em nenhum dos dois planos e estão abertas há mais de 3 dias úteis.** 530 foram registadas antes de 2025, e as mais antigas são de 2014. Aparecem na secção "Sem peças nos planos".
  - Nos planos, a 27/09, ficariam a vermelho 89 OF em MTG3 (de 145) e 98 em MTG2 (de 261). Com os dados de 28/09 são 94 e 132.
  - A 28/09 a fábrica voltou a enviar folhas do MES, com produção de 25 a 27/09. Continuam por validar 416 folhas de MTG3 e 19 de MTG2.
- **O Excel não guarda quando se planeou,** porque reescreve a semana todas as semanas. Por isso a aplicação tem de passar a registar cada decisão com data e autor.

## Os passos, semana a semana

Cada passo diz: **o que é**, **porquê**, **o que vais ver** e **como se sabe que está pronto**. O pormenor técnico está no fim do documento.

### Semana 1 — Arrumar a casa e começar a escolher o trabalho

**Passo 1 — Guardar o código num histórico (git)**

- **O que é.** Cada alteração ao código fica gravada com data e descrição. É como o histórico de versões de um documento.
- **Porquê.** Hoje, se uma alteração correr mal, não há forma segura de voltar atrás.
- **Cuidado especial.** O MES da fábrica usa alguns ficheiros desta aplicação. O histórico não pode estragar essas ligações.
- **Pronto quando** o código está guardado e o MES continua a funcionar igual.

**Passo 2 — Confirmar as cópias de segurança e registar as alterações à base de dados**

- **O que é.**
  - Confirmar que a cópia diária das 03:00 inclui a base do planeamento. Hoje não sei se inclui, porque o script só é legível pelo administrador. Vou pedir-te autorização antes de usar `sudo`.
  - Criar uma lista das alterações feitas à estrutura da base, que hoje são aplicadas à mão.
- **Porquê.** A partir daqui a aplicação guarda decisões do planeador que não existem em mais lado nenhum. Perdê-las seria perder trabalho.
- **Pronto quando** há uma cópia confirmada e testada, e a lista de alterações está em dia.

**Passo 3 — Login e endereço fixo**

- **O que é.**
  - Cada pessoa entra com o seu utilizador e a sua palavra-passe, num endereço fixo: `planeamento.nikufra.ai`.
  - A aplicação passa a arrancar sozinha depois de um reinício do servidor.
  - O endereço temporário de hoje é desligado.
- **Porquê.** Hoje qualquer pessoa com o link pode alterar, e tudo fica como "Utilizador não identificado". Sem login não se sabe quem planeou nem quem publicou.
- **O que vais ver.** Um ecrã de login. Há também um utilizador só de consulta, para quem só vê o Gantt.
- **Precisa de ti.** Criar o registo DNS no Squarespace e dar-me a lista de pessoas e o que cada uma pode fazer.
- **Pronto quando** só entra quem tem utilizador e cada gravação fica com o nome de quem a fez.

**Passo 4 — "Setor" em vez de "Área"**

- **O que é.** No registo ao planeamento e nas páginas principais, o campo "Área" passa a "Setor", com "MTG2 Perfis" e "MTG3 Cantoneiras".
- **Porquê.** Foi o que pediste, e é mais claro para quem usa.
- **Cuidado.** Só muda o nome que se vê. O que está guardado na base não muda, para não estragar nada. "Área de Seção de Corte" (a área do perfil em mm²) não se mexe.
- **Pronto quando** o registo mostra "Setor" e tudo o que já existia continua a funcionar.

**Passo 5 — Página "Carteira" de MTG3: ver todo o trabalho aberto, agrupado por referência**

- **O que é.** Uma página nova com todo o trabalho por fazer em MTG3.
- **Vista padrão — por referência,** como pediste:
  - **1.º nível — referência mestre:** o modelo no início do código, por exemplo DLT, DLA, ED4. Mostra os totais em aberto (peças, metros, OF), o prazo mais apertado e as máquinas onde esse trabalho está.
  - **2.º nível — referência específica (SKU):** por exemplo DLT319. Mostra o mesmo, e ainda as máquinas onde essa referência já foi feita antes.
  - **3.º nível — as OF** que pedem essa referência, com quantidades e Data Corte.
- **Outras vistas, a um clique:**
  - por OF, agrupadas por obra/encomenda;
  - por perfil (L45);
  - por família;
  - por cliente.
- **Filtros:** família, cliente, prazo (atrasado, próximas 3 semanas, mais tarde, sem data) e sinais.
- **Etiquetas** com o que está escrito no Excel: prioridade, "anulada", Eletrofer, "fabricar após validação". As OF duvidosas ou anuladas aparecem, mas por marcar e com o motivo.
- **Como se tira a referência mestre.** Por uma regra sobre o código:
  - "letras + número + letra + número" guarda a parte antes da 2.ª letra: ED4T40 → ED4, CI7812A4046 → CI7812;
  - "número + letra + número" guarda o número: 1283V053 → 1283;
  - "letras + número" guarda só as letras: DLT319 → DLT, DLR9312D → DLR, ZE-626 → ZE.

  Há também uma tabela de exceções, que o planeador pode corrigir. Casos que a regra não resolva aparecem como "modelo por confirmar": 0,3% das linhas em MTG3 e 2,9% em MTG2.
- **Porquê.** Hoje o trabalho aberto está espalhado por 76.799 linhas de Excel. A vista por referência junta o mesmo modelo e a mesma peça de todas as OF.
- **Pronto quando:**
  - os totais batem certo com a análise: 13.637 linhas e 336 km em MTG3;
  - o planeador confirmou a regra do modelo com os 15 maiores modelos.

**Passo 6 — Botão "Planear": validar o que se quer planear**

- **O que é.** Na Carteira, o planeador marca o que quer planear e carrega em "Planear". Pode marcar em qualquer nível:
  - uma referência mestre inteira;
  - uma referência (SKU) em todas as OF;
  - uma OF inteira;
  - só uma referência dentro de uma OF.

  Pode também excluir, dizendo porquê.
- **Proposta automática.** A aplicação já vem com uma proposta marcada, pela ordem:
  1. prioridade escrita;
  2. o que já está atrasado;
  3. o que é para as próximas 3 semanas.

  Pára quando se atinge a capacidade das máquinas. O que não cabe aparece numa lista à parte, "não cabe".
- **Porquê.** É o teu pedido principal: só o que foi validado segue para o Gantt e para o wall.
- **Fica registado** quem planeou, quando e porquê. É daqui que o painel vermelho vai saber "planeada há X dias".
- **Pronto quando** o planeador consegue planear e desmarcar por modelo, por SKU ou por OF, e cada ação fica registada com o nome.

**No fim da semana, 1 hora com o planeador:**

- rever a proposta de seleção;
- confirmar a regra da referência mestre com os maiores modelos;
- decidir o que fazer às 8 OF "anuladas", à OF da Eletrofer e às que esperam validação;
- decidir se o estado "Pronta" do CPIS conta como aberta;
- dar o feriado municipal e os encerramentos.

### Semana 2 — Dar máquina ao trabalho

**Passo 7 — Capacidade de cada máquina**

- **O que é.** Para cada máquina, quantos metros corta por semana, tirado do histórico real. A aplicação guarda dois valores:
  - **"Prometível":** o que a máquina atinge em 3 de cada 4 semanas. Por exemplo, a XP T4 cerca de 9.800 m e a Peddi 8 cerca de 4.600 m.
  - **"Provável":** o valor do meio.
- **Porquê.** Sem saber quanto cada máquina faz, não se pode dizer se o plano cabe. Nas últimas 16 semanas, as seis máquinas mais usadas **nunca** atingiram o valor do meio todas na mesma semana. Por isso promete-se o valor mais baixo.
- **Precisa do planeador:** confirmar ou corrigir estes valores.
- **Pronto quando** cada máquina tem os seus dois valores confirmados.

**Passo 8 — Limites das máquinas**

- **O que é.** Uma lista do que cada máquina não pode fazer. Por exemplo:
  - perfis acima de L120 só vão às Rapid e à Peddi 6;
  - a operação 221 vai para a Rapid 20T-1;
  - há limites de aba e de espessura em algumas máquinas.
- **Porquê.** Assim a aplicação nunca sugere uma máquina impossível.
- **Precisa da produção:** confirmar que são limites reais e não só hábitos. Os dados mostram hábitos, não especificações técnicas.
- **Pronto quando** a lista está confirmada por quem conhece as máquinas.

**Passo 9 — Catálogo de referências: ver em que máquina se faz cada SKU**

- **O que é.** Uma página de pesquisa, para MTG3 e MTG2.
  - Escreve-se uma referência (por exemplo DLT319) ou um modelo (por exemplo DLT).
  - Pesquisar um modelo mostra todas as suas referências. Carregar numa referência mostra o detalhe.
- **O que vais ver para cada referência:**
  - as variantes técnicas: perfil, comprimento, qualidade e operação;
  - **em que máquinas já foi feita:** quantas OF, quantos km e a última data;
  - em que máquina está o trabalho aberto dessa referência, e em que OF.
- **Exemplo.** A DLT319 aparece em 66 OF e o plano já a pôs em 4 máquinas: Rapid 20T-1, Rapid 20T-2, Rapid 25T e Peddi 6. A produção segue a máquina do plano em 98,8% dos registos.
- **Porquê.** É o "sítio" que pediste para ver por SKU onde se faz. É também a prova que alimenta as sugestões de máquina: "esta peça já foi feita na máquina X".
- **De onde vêm os dados:**
  - o histórico dos planos que a aplicação já importa, com as linhas fechadas e antigas;
  - a produção validada no MES, que diz onde a peça foi realmente cortada.
- **Pronto quando** pesquisar qualquer referência dos planos mostra o seu histórico de máquinas e o trabalho em aberto.

**Passo 10 — Vista L45: dar máquina em bloco ou em detalhe**

- **O que é.** Uma vista que junta o mesmo perfil de várias OF. Por exemplo, todos os L45X45X5. Tem três níveis:
  - **bloco:** "atribuir todo este perfil a…";
  - **por OF:** "este perfil desta OF vai para…";
  - **detalhe:** peça a peça.
- **O que vais ver.**
  - Para cada grupo: as máquinas que já fizeram esse perfil (km, última vez, cliente) e a fila de cada máquina em semanas.
  - Antes de gravar: o efeito na carga, por exemplo "XP T4: de 1,6 para 1,8 semanas".
- **Porquê em bloco e em detalhe.** Pôr um perfil inteiro numa máquina é rápido, mas pode sobrecarregá-la. As abas 40–45 sozinhas dão cerca de 7,6 km por semana. O detalhe permite repartir.
- **Regras:**
  - uma escolha feita peça a peça ganha sempre à escolha do bloco;
  - peças novas que o Excel acrescente a um grupo já atribuído herdam a máquina;
  - OF novas não herdam nada.
- **Pronto quando** o planeador consegue dar máquina aos cerca de 100 km urgentes, vendo a carga.

**No fim da semana, com o planeador e a produção:**

- confirmar os limites e a capacidade;
- decidir as máquinas do trabalho urgente, incluindo se as XP passam a fazê-lo em vez do que é para depois de 18/10.

### Semana 3 — Plano no Gantt e painel vermelho

**Passo 11 — Calcular a fila de cada máquina**

- **O que é.** Com o trabalho planeado e as máquinas escolhidas, a aplicação monta a fila de cada máquina, semana a semana, pela ordem:
  1. prioridade escrita;
  2. Data Corte;
  3. número `P` do Excel.

  Usa peças inteiras, a capacidade prometível e os feriados, por exemplo 05/10.
- **Porquê.** É isto que diz o que cada máquina faz esta semana e nas seguintes, e onde há sobrecarga ou folga.
- **Cuidado.** A semana que já está a decorrer não se reordena sozinha, para não baralhar quem está a trabalhar.
- **Pronto quando** a fila respeita a ordem, as peças inteiras e a capacidade.

**Passo 12 — Publicar e ver no Gantt do sistema (o wall)**

- **O que é.** O planeador revê o plano e carrega em "Publicar".
  - Essa versão fica fixa: ninguém a altera depois. Uma nova publicação substitui a anterior, e ficam as duas guardadas.
  - O Gantt do sistema mostra essa versão, com uma linha por máquina e as barras pela ordem da fila.
  - Carregar numa máquina mostra a sua fila em lista, com o que já foi feito.
- **Na transição** o Gantt diz claramente **"Proposta — o Excel é o plano oficial"**, para ninguém trabalhar por dois planos. Na data de passagem, o aviso sai.
- **Porquê fixar a versão.** Para depois se comparar o prometido com o feito, sem que o plano mude por baixo.
- **Nota.** As datas das barras são uma estimativa pelo ritmo de cada máquina, não um horário ao minuto. O Gantt diz isso.
- **Pronto quando** o planeador publica e cada máquina mostra a sua fila no Gantt.

**Passo 13 — Painel vermelho: "aberta e não planeada" e "parada"**

- **O que é.** Uma tabela vermelha na aplicação. Nesta semana entram duas situações.
- **A — Aberta no CPIS e não planeada.**
  - Entram todas as OF abertas no CPIS, como decidiste, ordenadas pela urgência.
  - Estão separadas em MTG3, MTG2, "as duas" e "Sem peças nos planos".
  - **Decisão de 28/09:** a secção "Sem peças nos planos" mostra só as OF registadas no CPIS há menos de 3 meses. As mais antigas vão para "Dados a corrigir", como candidatas a fechar no CPIS. As OF com peças nos planos aparecem sempre.
  - Enquanto o Excel for oficial, conta como "planeada" o que tem máquina no Excel ou foi planeado na aplicação.
- **C — Parada.**
  - A OF já começou, mas passaram **mais de 3 dias úteis sem produção** e ainda faltam peças.
  - Em MTG2 conta a operação em curso: corte ou abocardar.
- **Aviso de atualidade.** No topo: "última produção validada: …" e quantas folhas estão por validar no MES. Assim, uma OF não parece parada só porque as folhas ainda não foram validadas.
- **Os dias úteis** seguem o calendário de cada setor: feriados nacionais, o municipal e os encerramentos. MTG3 também trabalha aos fins de semana, por isso o calendário é configurável por setor.
- **Pronto quando** as contagens batem certo com a análise.

**No fim da semana, com o planeador:** fazer a primeira publicação a sério, ainda como proposta, e rever o Gantt máquina a máquina.

### Semanas 4 e 5 — Completar MTG3

- **Passo 14 — Sugestão automática de máquina.**
  - Para cada grupo de peças, a aplicação sugere as 2 máquinas mais prováveis. Diz porquê: "o mesmo cliente fez este perfil na XP T6 em agosto".
  - Nunca atribui sozinha. Nos testes com OF novas, a máquina escolhida pelo planeador estava nas duas sugestões em 6 a 7 de cada 10 casos.
- **Passo 15 — Painel vermelho "planeada e sem avanço" e lista "Dados a corrigir".**
  - Passam a vermelho as OF planeadas há mais de 3 dias úteis sem produção.
  - Os problemas de dados vão para uma lista à parte, que não é vermelha, e é para quem corrige os dados:
    - OF ausentes do CPIS;
    - números de OF mal escritos;
    - anuladas ainda abertas;
    - 610 linhas de MTG2 que o CPIS dá como fechadas.
- **Passo 16 — Fecho da semana e passagem para o Excel.**
  - No fim de cada semana, a aplicação compara o publicado com o feito e mostra o que ficou por fazer, e porquê.
  - Até à data de passagem, o planeador pode descarregar o plano num ficheiro com as colunas do Excel, para não ter de escrever tudo duas vezes.
- **Também nestas semanas:**
  - "Setor" no resto dos ecrãs;
  - a família também na lista de OF;
  - a Data Corte passa a contar nos prazos de MTG3. Hoje a aplicação só a usa em Perfis.

### Semanas 6 a 8 — MTG2 Perfis

- **O mesmo percurso:** Carteira, "Planear", máquinas, fila e Gantt. O Gantt de Perfis que já existe passa a mostrar só o que foi planeado.
- **Diferenças de MTG2:**
  - a família ajuda a sugerir a máquina;
  - a capacidade ainda não está medida (o MES indica cerca de 10 a 13 km por semana);
  - falta definir com o planeador quando é que uma peça entra na fila do abocardar.

### Sempre, desde a semana 1 (fábrica)

- Validar as folhas que estão por validar no MES: 416 de MTG3 e 19 de MTG2.
- Começar a registar as horas nas folhas do Disco e da Vanguard. Recuperar as horas já escritas nas folhas de MTG3.
- Comparar todas as semanas o que se planeou com o que se fez. É assim que a capacidade fica cada vez mais certa.

## O que preciso de ti e do planeador

| Quem | O quê | Quando |
|---|---|---|
| Tu | Autorizar: guardar o código no git, usar `sudo` para ver as cópias de segurança, e o login | Início da semana 1 |
| Tu | Registo DNS `planeamento.nikufra.ai` e a lista de utilizadores | Semana 1 |
| Tu | Restringir a partilha da pasta do Drive | Quando puderes |
| Planeador | Rever a seleção proposta, confirmar a regra da referência mestre e rever os casos especiais (anuladas, Eletrofer, validações, "Pronta", feriado municipal) | Fim da semana 1 |
| Planeador + produção | Confirmar a capacidade e os limites das máquinas; decidir as máquinas do trabalho urgente | Fim da semana 2 |
| Planeador | Primeira publicação e revisão do Gantt | Fim da semana 3 |
| Tu + planeador | Data de passagem: a partir de quando a aplicação manda em MTG3 | Depois de 2 ou 3 semanas de propostas |

## Como vamos confirmar que funciona

- **Testes automáticos.** Pequenos programas que verificam as regras sozinhos. Por exemplo:
  - uma escolha peça a peça ganha à escolha do bloco;
  - uma versão publicada não pode ser alterada;
  - os dias úteis contam bem com feriados;
  - o MES continua a funcionar depois de cada mudança.
- **Totais iguais aos da análise.** Por exemplo, os 336 km de MTG3.
- **A regra da referência mestre** é testada com exemplos fixos: ED4T40 → ED4, DLT319 → DLT, 1283V053 → 1283, CI7812A4046 → CI7812. O Catálogo mostra, para a DLT319, as 4 máquinas onde já foi feita.
- **Ensaio completo numa cópia da base de dados,** antes de mexer na verdadeira: planear → dar máquina → publicar → ver no Gantt → uma produção do MES reduz o que falta.
- **Cada passo é ligado com um interruptor.** Se algo correr mal, desliga-se sem apagar nada.

## Riscos e cuidados

- **O Excel e a aplicação podem discordar.** A aplicação guarda a máquina que o Excel tinha quando se decidiu. Se o Excel mudar depois, aparece "para rever"; nunca se apaga em silêncio.
- **O MES usa ficheiros desta aplicação.** Todo o código novo fica num sítio separado, e cada mudança é testada também no MES.
- **Fora deste plano, mas a resolver:**
  - o MES do PC da fábrica corre uma versão diferente da do servidor e não está todo no git;
  - a leitura de PDF e o chat enviam dados para um serviço de IA fora da UE (decisão tua).

## Pequeno glossário

| Termo | O que quer dizer |
|---|---|
| Carteira | Todo o trabalho aberto por fazer |
| Referência mestre | O modelo, tirado do início do código da peça (DLT, DLA, ED4, CI7812…) |
| Referência específica (SKU) | O código completo de uma peça, por exemplo DLT319 |
| Grupo OF × perfil | As peças de uma OF com o mesmo perfil (por exemplo, todas as peças L50X50X5 de uma OF). É a unidade em que se escolhe a máquina |
| Vista L45 | Vista que junta o mesmo perfil de várias OF |
| Publicar | Fixar uma versão do plano, com data e autor, que já não muda |
| Capacidade prometível | O que a máquina corta em 3 de cada 4 semanas |
| Git | Histórico do código que permite voltar atrás |
| Migração | Uma alteração à estrutura da base de dados |
| Interruptor | Uma definição que liga ou desliga uma funcionalidade sem mexer no código |

## Estado

- 28/09/2026: plano aprovado. Guardadas a análise, as provas e os programas (só leitura), com um índice em `pedido-2026-09-28/README.md`.
- 28/09/2026, 07:28 UTC: o planeador gravou versões novas dos dois Excel. As provas usam as de 25/09. A semana 1 começa com as mais recentes.
- 28/09/2026, semana 1 em curso (registos `9ad3704` a `6c96735`):
  - **Passo 1:** código no git.
  - **Passo 2:** cópia diária das decisões às 02:30, com o restauro testado; registo de migrações, com a linha de base 010–038 e a 039.
  - **Passo 4:** "Setor" em vez de "Área" nos ecrãs principais.
  - **Passo 5:** Carteira de MTG3 por referência, em `/planeamento/carteira`.
  - **Passo 6:** "Planear" / "Excluir" / "Limpar", com o histórico só de acrescentar; migração 040 aplicada.
  - **Passo 3:** parte da aplicação pronta e desligada.
  - Os 8 testes de prazo desatualizados foram corrigidos.
- Falta para fechar a semana 1:
  - registo DNS `planeamento.nikufra.ai`;
  - lista de utilizadores;
  - autorização para o bloco do Caddy (`deploy/caddy-planeamento.caddyfile`) e para desligar o túnel temporário;
  - reunião com o planeador.

---

## Anexo técnico (para a implementação)

- **Código novo num pacote próprio, `app/sector/`,** com router próprio incluído só por `app/web/planning_app.py`.
  - O MES usa por ligação `planning*.py`, `raw/` e as rotas, e os JS são ligações físicas com contagem 2 (confirmado).
  - Os módulos partilhados só importam o código novo quando for preciso, e um teste confirma que o MES continua a importar.
- **Referência mestre:**
  - função única `master_reference(ref)` com as 3 regras do Passo 5 (em MTG3 dá 342 modelos, 0,3% por confirmar);
  - tabela de exceções `reference_master_override (area, ref_pattern, master, actor, decided_at)`, editável pelo planeador.
- **Vista padrão da Carteira:** agregação mestre → SKU → OF feita na base de dados, na leitura.
- **Catálogo:** `GET /planeamento/api/referencias?q=` junta:
  - a população `history` da projeção (máquina do plano);
  - a produção validada do MES por referência (máquina onde foi realmente cortada).
- **As decisões ficam em tabelas próprias, fora da projeção RAW:**
  - `sector_selection (area, of, reference)`, onde `reference='*'` quer dizer a OF inteira. Marcar um modelo ou um SKU grava os pares OF × referência abrangidos;
  - `sector_assignment (area, of, profile_key, operation)`;
  - `sector_line_override (line_identity)`;
  - `sector_decision_events`, onde só se acrescenta.

  A máquina final resolve-se na leitura: linha → grupo → Excel. A projeção só ganha `line_identity`, `profile_key` e os sinais, com uma única subida de `RAW_CONTRACT` (`app/raw/projection.py:12`).

  Porquê: uma reconstrução completa leva 72 s e 37 s, e a edição bloqueia `raw-build`. O saldo usa `remaining`/`remaining_m` da projeção.
- **Publicação:**
  - tabelas `plan_publication` e `plan_publication_line`, onde só se acrescenta;
  - um índice parcial único garante uma publicação ativa por setor;
  - a aplicação só tem permissão para acrescentar linhas; no cabeçalho só muda `status`.
- **Capacidade:** tabela `machine_week_capacity` com o valor prometível (percentil 25) e o provável (mediana). Não se usam os objetos `calendar`/`rate`, que mudam as horas do RAW.
- **Fila:** `app/sector/weekly_queue.py`, calculada a pedido.
  - Desempate: prioridade → Data Corte → P → OF → linha.
  - Peças inteiras; a semana corrente fica congelada.
- **Login:**
  - Caddy com `basic_auth`, remoção de `X-Auth-User` vindo do browser e envio do utilizador com um segredo partilhado;
  - na aplicação, um middleware confere o segredo com `hmac.compare_digest` e guarda o utilizador num `ContextVar`, que `human_actor()` lê (`app/planning_registration.py:35-37`);
  - `MES_PLANNING_AUTH_REQUIRED=1` recusa escritas sem utilizador;
  - o túnel `kanban-planning-tunnel.service` é desligado;
  - `kanban-planning.service` passa a `enabled`.
- **Migrações:**
  - `schema_migrations` e um script que as aplica, cada uma numa transação;
  - um teste aplica 010→fim numa base vazia (as 026 e 028 são perigosas).
- **Interruptores** em ficheiros do systemd: `MES_PLANNING_SELECTION_ENABLED`, `…_WALL_ENABLED`, `…_ALERTS_ENABLED`, `…_AUTH_REQUIRED`.
- **Painel A:** reaproveita `planning_hub._order_population` (`app/planning_hub.py:309-419`), com cache de 60 s. O relógio conta desde o registo no CPIS.
- **"Pronta":** passa a ter uma só regra (`planning_population.py:11` contra `planning_hub.py:22`).
- **Data Corte em MTG3:** `planning_calculations.py:297` passa a considerá-la.
- **Setor:** `planning.AREAS` e `sectorLabel()`; ecrãs `need_editor.html:27-28`, `planning_hub.html:49`, `raw_workspace.html:24`. Os valores guardados não mudam (restrições CHECK em `sql/018`, `019` e `020`).
- **Família:** `work_type`/`work_type_code` a partir de `cpis_sync.py:32-33`; filtro em `/api/ordens`.
- **Gantt de Perfis (MTG2):** filtrar a seleção em `app/gantt/inputs.py:165-167` e juntar a revisão da seleção às referências de atualidade (`inputs.py:67-79`).
- **Conflitos:** cada decisão tem `revision`, um conflito devolve 409, e publicar confere o resumo das entradas.
