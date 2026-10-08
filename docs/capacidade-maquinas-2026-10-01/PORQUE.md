# Porque é que cada cantoneira vai para cada máquina — padrões nos dados (1/10/2026)

Pergunta: porque é que o algoritmo dizia que as Rapid tinham ~36 semanas de carga, e como escolhe o planeador entre punção (XP, Peddi) e broca (Rapid)?

Fontes:
- Excel MTG3 de 30/09/2026: 77 635 linhas, das quais 59 979 já produzidas em 2026.
- A ficha `capaciadades cantoneira (1).xlsx`: é o mesmo ficheiro recebido a 29/09 (SHA-256 idêntico), com o tipo de furo, os perfis mínimo e máximo, o graminho e o número de cabeços de cada máquina.

Reprodução:
1. `.venv/bin/python padroes/exportar.py`
2. `uv run --with pandas --with scikit-learn python padroes/analisar.py`

## 1. O código 112/119 não decide a máquina

A ficha diz: XP e Peddi 8 fazem 112 (punção); as Rapid fazem 119 (broca). O que foi realmente produzido em 2026 diz outra coisa:

| Código no Excel | Peddi | Rapid | XP |
| --- | ---: | ---: | ---: |
| 112 | 2 525 linhas | 2 726 | 5 481 |
| 119 | 6 777 | 29 474 | **12 363** |

Quase 19 mil linhas com 119 foram produzidas em punçoadoras. Prever o processo pelo código acerta só **47%** dos metros. O algoritmo seguia a ficha («119 só nas Rapid»), e daí vinham as ~36 semanas de carga nas Rapid.

## 2. O que decide de facto: o tamanho da série

A decisão é tomada por lote: **99,5%** dos grupos OF × perfil vão inteiros para a mesma família de máquina. Ao nível do grupo, o fator mais forte é a **média de peças por linha**:

| Peças por linha | Rapid | XP | Peddi |
| --- | ---: | ---: | ---: |
| 1–2 | 80% | 13% | 7% |
| 3–5 | 66% | 23% | 11% |
| 6–10 | 41% | 39% | 21% |
| 11–20 | 15% | 49% | 37% |
| mais de 20 | 4–7% | 64–74% | 22–29% |

A seguir vêm três limites físicos:
- **espessura acima de 9,5 mm** vai para broca em 87–100% dos casos;
- **aba acima de 120 mm** vai sempre para Rapid (as punçoadoras param em L120);
- **comprimento acima de 6 m** vai para Rapid em 87% dos casos.

**Regra:** média de 8 ou mais peças por linha, espessura até 9,5 mm e aba até 120 → punção; caso contrário → broca. Acerta **88–89%** dos metros e é estável entre 5 e 10 peças, por isso não depende de afinar o limiar. Uma árvore de decisão validada em OF que nunca viu não faz melhor (88,7%).

**O 8 já estava no Excel.** A folha `Analise maq` tem «factor de selecção maq = 8» e a fórmula `SE(P ≥ 8; "Xp"; "Rapid")`. A fórmula está avariada (`#DIV/0!`), mas os dados mostram que o planeador aplica essa regra à mão. Faz sentido técnico: a punção exige preparar ferramentas e compensa em séries; a broca não precisa de ferramenta por furo e serve as séries baixas, a chapa grossa e as abas grandes.

**O que não explica as exceções (~11% dos metros).** Testei a carga das punçoadoras: grandes séries vão para Rapid em 4,0% dos metros em semanas normais e 4,8% em semanas muito carregadas — praticamente igual. A hipótese de transbordo foi rejeitada. As exceções são grandes séries de Metalogalva (L70×70×6), RTE e Tecpoles que foram para a broca, provavelmente por razões técnicas que o Excel não regista: furos perto da aba (graminho), número de diâmetros acima dos cabeços, desenho. A ficha dá esses limites por máquina, mas o Excel não tem as cotas de furação da peça.

## 3. Entre as três Rapid

- Cada OF × perfil fica sempre numa só Rapid (99,98%); a OF inteira numa só Rapid em 92% dos casos.
- O tamanho conta: abas de 100 ou mais vão sobretudo para a 25T (56–63%); abaixo de L60 nunca vão para a 25T, porque a ficha começa em L60. Entre L60 e L100, sobretudo as 20T.
- A Rapid 20T-2 só ganhou peso a partir de fevereiro de 2026; desde julho, as três repartem cerca de 1/3 cada.
- O cliente não explica a escolha. Fora do tamanho, os dados não mostram outro critério: na prática é repartição de carga.

## 4. O trabalho sem máquina, revisto

São 13 912 linhas MTG3 sem máquina com peças em falta (~298 km, em 97 OF). 293 km têm código 119. Pela regra real das séries, **~204 km vão para punção e ~94 km para broca**. É sobretudo trabalho futuro (Data Corte de setembro de 2026 a janeiro de 2027), concentrado em grandes séries: as quatro OF de Tecpoles (OF262667–70, 70–90 peças por linha, ~94 km) e as OF da PROEF.

## 5. O que mudou no algoritmo

1. **Candidatas:** para 119, a XP T4, a XP T6 e a Peddi 8 passam a ser alternativas **condicionais**, só porque o histórico mostra essa prática nelas (mais de 5 mil linhas cada; mínimo exigido: 20). A condição é explícita: «Código 119 em punção: prática observada no Excel, confirmar furação e desenho». A ficha não foi alterada; a divergência ficha/prática fica visível.
2. **Regra das séries** na máquina sugerida e no Gantt (para operações sem máquina), logo a seguir à coesão do lote (mesma OF, operação e perfil).
3. Carga resultante, ao ritmo do débito observado (mediana):

| Máquina | Antes (só ficha) | Agora |
| --- | ---: | ---: |
| Rapid 20T-1 / 20T-2 / 25T | 36 / 37 / 22 semanas | 11,8 / 11,8 / 11,8 |
| XP T4 / XP T6 | 1,6 / 1,6 | 9,3 / 8,6 |
| Peddi 8 | 20 | **32,9** |
| Peddi 6 | 10 | 3,3 |

## 6. Recomendação para o planeador

A Peddi 8 passa a ser o recurso limitante: tem 1 037 h já atribuídas no Excel, e o algoritmo junta-lhe as linhas das mesmas OF e perfis (sobretudo L45×45×5) para não partir lotes. As XP T4/T6 fazem o mesmo processo, cobrem todos os perfis da Peddi 8 (até L120×12, contra L120×8) e estão a ~9 semanas. **Passar parte desses lotes da Peddi 8 para as XP é o ganho mais claro.** No ecrã, isso faz-se com «Máquina…» no grupo e «Atribuir» numa XP; fica registado e pode ser desfeito.

## 7. Limites

- Mede a prática do planeador, não a melhor decisão possível.
- As causas das exceções (graminho, diâmetros, desenho) não estão nos dados; só a confirmação técnica as resolve.
- Validação da sugestão máquina a máquina em grupos novos: 115 linhas de poucas OF; acerta a família em 74% nessa amostra. O teste grande é o dos 7 858 grupos (89%).
