# Plano de execução integral do planeamento

> Atualização autorizada em 24/09: o utilizador dispensou continuar a otimização para o limite de 10 s. Os tempos são reportados, mantendo a validação funcional, a atualização automática, a consistência, a persistência e a publicação como condições de entrega.


Data: 23/09/2026. Repositório: `/home/luis/projects/kanban-mes-mtg2`.

**Âmbito corrigido em 24/09/2026 por instrução do utilizador:** exclusivamente Planeamento de Perfis e Cantoneiras. A integração com a aplicação «OCR original» deixa de fazer parte desta execução ou das suas dependências. O histórico da versão anterior está em `validacao-planeamento-integral/20260923-execucao/t10-contract-before-scope-correction.md`.

## Estado final — 24/09/2026

Concluídos os 58 critérios das duas áreas e publicada a candidata validada no serviço de Planeamento 8113 e no worker. As fontes de Perfis e Cantoneiras incluem Drive, macros, CPIS, documentos e dados manuais. A tipografia 11 pt foi confirmada no browser. A integração com a aplicação OCR original foi excluída por instrução do utilizador. O resultado e as limitações estão no [relatório final](/home/luis/projects/kanban-mes-mtg2/docs/validacao-planeamento-integral/20260923-execucao/t10-entrega-final.md).

O estado atual e as provas estão no [trabalho restante](/home/luis/projects/kanban-mes-mtg2/docs/plano-trabalho-restante-planeamento-2026-09-24.md) e na [checklist](/home/luis/projects/kanban-mes-mtg2/docs/checkpoints-planeamento-2026-09-23.json). As referências ao OCR original no diagnóstico histórico da secção 3 não constituem requisitos atuais.

## 1. Instrução obrigatória para o LLM executor

Conclui todos os requisitos R01–R11 e checkpoints C00–C12 a partir do objetivo atualizado e das provas existentes. O utilizador autorizou a implementação integral e a publicação após validação. Não reiniciar o plano nem reduzir o âmbito aos cálculos ou à interface.

Durante a execução:

1. Lê o plano inteiro, o código real, as instruções aplicáveis do repositório e o estado de trabalho antes de editar. Preserva alterações preexistentes. Não uses `reset`, limpeza do workspace ou reposição integral de ficheiros para facilitar a implementação.
2. Para cada checkpoint: reproduz o problema, implementa a solução completa, verifica os critérios enumerados e guarda evidência. Atualiza a checklist com resultados reais, não com intenções.
3. `por_executar`, `em_curso`, `reprovado` e `bloqueado` significam **trabalho incompleto**. Só usa `aprovado` quando todos os critérios desse checkpoint tiverem passado, com provas acessíveis. Um teste ignorado, uma dependência inacessível ou uma demonstração simulada não satisfaz uma verificação real exigida.
4. Não declares concluído com TODOs funcionais, fórmulas por ligar, valores estáticos, botões sem efeito, importadores apenas preparados, testes necessários não executados ou erros sem diagnóstico. Não alteres um teste para aceitar o comportamento que este plano manda corrigir.
5. Continua autonomamente nas tarefas independentes quando encontrares um bloqueio. Regista o requisito afetado, a causa, o que verificaste e o que falta obter. Um bloqueio não autoriza omitir o requisito nem inventar o respetivo resultado.
6. Não substituas evidência por frases como «já existe», «parece funcionar», «o código calcula» ou «os testes antigos passaram». É obrigatório provar o comportamento final nos dados, na API e no browser, conforme cada checkpoint.
7. Depois de qualquer alteração que invalide uma prova anterior, volta a executar as verificações afetadas. O relatório final identifica a revisão de código, a versão dos dados e o ambiente usados.
8. Não envies dados de teste para produção. Testes de criação, alteração, fecho, reabertura, duplicação e correção de OCR usam PostgreSQL descartável ou cópia integral isolada. Nas fontes reais, faz consultas de leitura e reconciliação. A publicação final da aplicação usa o serviço de planeamento, sem reiniciar os MES para testar.
9. Mantém os cálculos numa implementação partilhada no servidor. Formulário, RAW, capacidades, análises e exportações não podem ter fórmulas divergentes. A pré-visualização não grava nem aceita produção OCR inventada pelo cliente.
10. A conclusão exige **R01–R11 cumpridos, C00–C12 aprovados e zero falhas obrigatórias pendentes**. Entrega a matriz de cumprimento, os resultados numéricos, as capturas e os comandos de validação. Se esta condição não se verificar, apresenta a entrega como incompleta e identifica os pontos restantes.

Nenhum texto consegue garantir o comportamento de qualquer LLM. Este plano define uma aceitação verificável: cumprir apenas parte dos pedidos não permite classificar a entrega como concluída.

## 2. Resultado final que o utilizador deve encontrar

| ID | Pedido e comportamento obrigatório | Checkpoints |
|---|---|---|
| R01 | «Registo de planeamento» abre um formulário que permite criar uma OF nova, OV nova e respetivos dados, sem procurar ou selecionar uma OF existente. Depois de guardar, a peça aparece na RAW da área, com cálculos e carga estimada quando existirem entradas suficientes. | C03, C04, C05 |
| R02 | O planeamento ativo exclui uma linha quando a OF estiver fechada no CPIS **ou** a linha estiver fechada na macro. Dados, documentos, produção e revisões ficam na base e são consultáveis no histórico. | C06, C11 |
| R03 | No painel Colunas, as setas para cima/baixo alteram a ordem, conservam o grupo aberto, o foco e a posição; não navegam para outra página. | C07 |
| R04 | Todas as colunas estão disponíveis. É possível arrastá-las entre posições e grupos de apresentação, guardar e recuperar a disposição. OF, OV e Referência podem ser desafixadas para permitir a ordenação pedida. | C07 |
| R05 | A RAW, incluindo Cantoneiras, tem uma barra horizontal acessível para chegar à primeira e à última coluna, mesmo com muitas linhas. | C08 |
| R06 | O planeamento usa uma fonte legível de **11 pontos**, com linhas, espaçamentos, campos e botões mais compactos. A fonte efetivamente renderizada é verificada. | C08 |
| R07 | Todos os campos calculados identificados neste plano funcionam na RAW e são recalculados quando mudam as entradas. As regras vêm dos Excel e do layout, com comparação numérica e origem visível. | C00, C02, C04, C05, C11 |
| R08 | Existe um local claro em Definições/Capacidades para registar manualmente máquinas, operações, períodos, turnos, horas por turno, indisponibilidades, horas trabalhadas e taxas. Guardar atualiza o planeamento. | C09, C05 |
| R09 | O histórico de produção validada e horas utilizáveis alimenta estimativas de capacidade. A prioridade é taxa manual aplicável, depois histórico válido, depois referência Excel válida. A estimativa funciona logo e identifica a sua origem. | C01, C02, C10, C05 |
| R10 | Cantoneiras dispõe de registo manual novo com os mesmos campos de entrada aplicáveis da sua RAW. Os campos calculados aparecem como resultados; os factos importados/OCR aparecem com a origem e não são falsificados como entrada manual. | C03, C04, C05 |
| R11 | A verificação do OCR prova que os dados são realmente obtidos, associados à peça e à operação e usados nos cálculos. Inclui as fontes de Perfis e Cantoneiras. | C01, C02, C04, C10 |

«Mover entre áreas» no painel Colunas refere-se aos grupos de apresentação das colunas. Não significa transferir ordens de produção de Perfis para Cantoneiras.

### Regras de dados já definidas

- A produção usada nos saldos vem do **OCR validado**, quando a associação, operação, quantidade e cobertura forem utilizáveis. Nunca somar o acumulado Excel ao acumulado OCR da mesma operação.
- Sem OCR utilizável, usar o acumulado Excel compatível, identificado como **Excel provisório**. Se nenhum existir, apresentar o motivo da ausência; não converter desconhecido em zero.
- Uma peça inteiramente nova criada localmente pode começar com produção zero, identificada como condição inicial local. Isso não cria uma folha nem um evento OCR.
- Produção a 100% não fecha automaticamente a OF. Excesso de produção pode gerar percentagens superiores a 100%; o saldo mínimo é zero e o excesso fica visível.
- A mudança apenas da quantidade necessária não apaga produção validada de uma peça cuja identidade técnica continua igual. Uma mudança de perfil, dimensões ou outra característica identificadora obriga a reavaliar a associação.
- A janela inicial proposta para produtividade histórica é 90 dias, configurável. Quantidades e horas têm de pertencer à mesma máquina, operação e população temporal compatível.
- Histórico de ordens fechadas continua disponível para produtividade histórica. Não entra na carga pendente do planeamento ativo.

## 3. Fontes e diagnóstico que não podem ser ignorados

### 3.1 Excel e Google Drive

Ficheiros locais em `/home/luis/projects/DATARESEARCHMTG/`, conferidos com o Drive nesta análise:

| Ficheiro | Drive | SHA-256 conferido |
|---|---|---|
| `LayoutPlaneamentoPerfis.xlsx` | [Layout](https://drive.google.com/file/d/13wlaUDR78_rTaz3p_dmQ2-1Nx7XKLL8p/view) | `f5b6e7812539b5edc153cea27d9b5ed251a3346b44d0c3f3cf991a136440685c` |
| `Met2_Plan_Perfis.xlsm` | [Perfis](https://drive.google.com/file/d/1T3fxlJVuw1Rl8m0lEj0P3tr9gi21C9Bd/view) | `bf1cd6a25986791e431160d812afa1de5e2e52e9013a9f989745033fe1fa61fc` |
| `Met3_Plan_Cantoneiras.xlsm` | [Cantoneiras](https://drive.google.com/file/d/1cPNbFrspKahw5XAYDSiQggwhScNFK7_8/view) | `397c8ea5e42480c1cd00f431860f8155f6ae34d60038bfa981341e15d9d8442d` |

Reconfirmar versões no início da execução. Se mudarem, guardar os novos hashes e refazer a reconciliação; não aplicar silenciosamente expectativas de outra versão.

Inventariar `Folha1` do layout; `Planeamento`, `PlanDisponibilidadeSemanal`, `CapacidadeMáquinas`, `AreaSecaoCorte` e intervalos nomeados de Perfis; `Plan_ produção`, `Plan_semanal`, `Tabela pesos`, `Dados` e restantes folhas referenciadas em Cantoneiras. Ler fórmulas, valores guardados, unidades, validações, catálogos e regras VBA relevantes. Algumas instruções do layout são **texto**, designadamente L, AN, AO e AP; procurar só células do tipo fórmula é insuficiente.

### 3.2 OCR: observações de 23/09/2026

Estas contagens são uma fotografia de diagnóstico, não constantes a colocar nos testes. A execução deve obter uma nova fotografia consistente e explicar alterações legítimas.

| Origem/resultado | Observado | Consequência |
|---|---|---|
| MES Perfis `kanban-mes-mtg2` | 104 folhas validadas; 478 registos de produção; 478 IDs únicos na projeção de produção | Os registos chegam ao centro, mas a chegada não prova que alimentam os saldos. |
| MES Cantoneiras `kanban-mes` | 182 folhas validadas, das quais 181 com produção; 1 873 registos, 109 sem quantidade conhecida | Validar separadamente folhas, registos e linhas expandidas. Quantidade em falta não é zero. |
| Projeção Cantoneiras | 2 826 linhas expandidas para os 1 873 registos; 2 210 linhas associadas a peças, mas todas com operação por confirmar | Não comparar linhas expandidas com registos como se fossem duplicados; falta resolver a operação. |
| RAW Cantoneiras | 75 735 linhas na geração consultada; nenhuma com produção OCR principal numérica | O OCR ainda não alimenta esta coluna como necessário. |
| Horas Perfis | Apenas 7 das 104 folhas têm horas conhecidas | A maioria da produção não pode produzir uma taxa histórica por hora sem dados adicionais. |
| Horas Cantoneiras | Nenhuma das 182 folhas tem horas declaradas utilizáveis na projeção consultada | É necessário permitir horas manuais e usar a referência Excel enquanto o histórico for insuficiente. |
| OCR original | `/health` respondeu; exportação de validados tinha 13 834 linhas de dados | O original tem dados acessíveis. O número refere-se à exportação, não a folhas ou IDs estáveis. |
| Publicação central do original | Zero instâncias/publicações confirmadas em `ocr_original`; `included_in_planning_balances: false` | Preparar ou instalar o conector não basta: faltam publicação real e utilização dos eventos nos saldos. |
| Importação antiga do original | 27 linhas em `raw_mtg.mtg2_producao_rows` | Não representa o conjunto atual do OCR original. |

A exportação `/export/cpis?validated_only=true` pertence ao OCR original; não prova acesso direto à base CPIS. O XLSX exportado não fornece os identificadores estáveis necessários para uma importação incremental segura.

### 3.3 Causas já localizadas no código

| Ficheiros | Problema ou trabalho concreto |
|---|---|
| `app/raw/projection.py`, `app/planning_raw.py`, `app/raw/calculations.py` | A projeção calcula campos antes de anexar o OCR; atualizar `ocr_cut`/`ocr_boc` depois não recalcula os saldos principais. Centralizar a resolução de fontes antes das fórmulas. |
| `app/planning_production.py`, `app/planning_associations.py` | Cantoneiras recebe `operacao_por_confirmar`. Implementar associação comprovada à operação, sem deduzi-la só pela máquina. |
| `app/original_ocr.py`, `docs/instalar-importacao-ocr-original.md` | Existe leitor SQLite e publicador, mas falta publicação real confirmada e integração com o motor de saldos. |
| `app/web/templates/need_editor.html`, `app/planning_needs.py`, `app/planning_catalogs.py` | O fluxo começa por uma OF existente; o contexto administrativo novo e a paridade entre RAW/formulário estão incompletos. |
| `app/web/static/raw_workspace.js`, `app/raw/objects.py` | A reconstrução do painel fecha grupos; falta arrastar; a normalização fixa as três primeiras colunas. |
| `app/raw/edits.py`, `app/raw/worker.py` | A gravação pode aguardar uma reconstrução longa, sem devolver logo os resultados novos. |
| `app/raw/capacity.py`, `app/raw/capacity_revision.py` | Já existem estruturas de configuração; estender o fluxo existente para horas manuais e prioridade de estimativas, evitando outro sistema paralelo. |

Usar esta localização como ponto de partida e confirmar os caminhos na revisão que for implementada.

## 4. Contrato dos campos: entradas, fórmulas e factos

Gerar um contrato único partilhado por formulário, RAW, pré-visualização e validação do servidor. Cada campo deve indicar identificador, rótulo, área, tipo, unidade, origem, possibilidade de edição, dependências e motivo de indisponibilidade. Não manter duas listas manuais que possam divergir.

### 4.1 Campos de entrada e identidade

| Campos | Como ficam |
|---|---|
| OF, OV, Cliente, Descrição da obra | Editáveis na criação local, sem dependência de uma OF prévia. Contexto local persistente, com origem manual. Uma futura associação CPIS preserva histórico e não duplica a ordem. |
| ID | Gerado pelo sistema; identificação Excel original preservada à parte quando existir. |
| Referência, Observações, Equipa, Pavilhão | Preenchimento manual com os mesmos identificadores e catálogos da RAW. |
| Data de corte, Semana/ano de picking, Data prevista, Semana/ano de planeamento | Entradas próprias, com validação e distinção entre picking e execução. Datas e semanas contraditórias geram validação, não escolha silenciosa. |
| Data CPIS/entrega | Dado CPIS preservado quando existe. Numa ordem local pode haver data de entrega manual claramente identificada, sem fingir proveniência CPIS. |
| Quantidade total necessária | Inteiro não negativo; é entrada de cálculo, não uma quantidade de produção validada. |
| Tipo de material/perfil nível 1, Designação/perfil nível 2 | Catálogos dependentes do Excel; alternativa manual para família ou perfil especial aplicável. |
| Diâmetro, Largura, Altura, Espessura, Comprimento, Ângulo, Qualidade | Mesmos campos técnicos aplicáveis da RAW; mostrar unidades e validar geometria. |
| Abocardar — Perfis | Valor explícito Sim/Não, compatível com X/− importados; indicação histórica desconhecida exige resolução. |
| Máquina, 1.ª operação, 2.ª operação — conforme área | Catálogos existentes; 2.ª operação com código 0 significa ausência, sem criar carga fictícia. |
| Requisitado?, Comprimento unitário de perfil | Requisição mantém estado desconhecido quando aplicável. Comprimento tem sugestão automática 6 000/12 000 mm e substituição manual identificada. |
| Descrição do material — Cantoneiras | Preservar texto importado. Numa peça nova, permitir descrição local coerente com os campos técnicos; não perder o original ao editar. |
| Velocidades, capacidades, turnos, horas | Registar em Definições/Capacidades com máquina/operação, unidade, período e vigência; disponibilizar o valor aplicado no detalhe da linha. |

Em Cantoneiras, incluir ainda qualquer campo de entrada aplicável que conste do contrato RAW final e não esteja enumerado acima. A prova de paridade deve comparar identificadores automaticamente: **zero campos editáveis da RAW sem correspondência no formulário**. Não basta copiar as doze colunas inicialmente visíveis.

Campos calculados surgem na pré-visualização e no detalhe, sem exigir preenchimento manual. Produção OCR, estado CPIS, fecho importado, última atividade e versões de origem são factos de leitura. «Todos os campos» não significa permitir editar um contador validado fingindo que veio do OCR.

### 4.2 Fórmulas de Perfis — nomes exatos e correspondência ao layout

Convenções: `Q` = quantidade necessária; `C` = cortada da fonte selecionada; `B` = abocardada da fonte selecionada; `L` = comprimento da peça em mm; `S` = comprimento do perfil inteiro em mm; `A` = área unitária da secção em mm². O corte e o abocardar têm fontes e saldos próprios.

| ID | Coluna / identificador RAW | Regra obrigatória |
|---|---|---|
| F01 | L — Descrição do Perfil / `description` | Compor material, perfil, dimensões aplicáveis, comprimento, ângulo e qualidade conhecidos; não introduzir zeros fictícios. Preservar descrição importada original separadamente. |
| F02 | P — Qtd Cortada / `cut` | Somatório dos eventos únicos de corte validados e associados, ou acumulado Excel provisório conforme a política de fonte. O rótulo principal deixa de dizer «macro» quando o valor usado é OCR. |
| F03 | Q — Qtd Abocardada / `boc` | Mesma regra, exclusivamente para abocardar. Preservar acumulados originais Excel e OCR em campos de comparação. |
| F04 | R — Percentual Cortado / `cut_pct` | `100 × C / Q`, para `Q > 0`. |
| F05 | S — Percentual Abocardada / `boc_pct` | `100 × B / Q`, se abocardar for necessário e `Q > 0`; caso não aplicável identificado. |
| F06 | T — Percentual Conclusão / `final_pct` | Percentual abocardado se necessário; caso contrário percentual cortado. Indicação de abocardar desconhecida não permite escolher uma operação final. |
| F07 | U — Qtd por Cortar / `remaining` | `max(Q − C, 0)`. Mostrar excesso separadamente quando `C > Q`. |
| F08 | V — Qtd por Abocardar / `boc_remaining` | `max(Q − B, 0)` quando necessário; zero quando explicitamente não aplicável. |
| F09 | Área unitária / `section_unit` | Geometria ou catálogo exato comprovado. Varão redondo `πd²/4`; quadrado `w²`; retangular `w×h`; tubo redondo `π[d²−(d−2t)²]/4`. Restantes famílias: regra VBA ou correspondência exata da tabela/intervalo nomeado inventariada em C00. Não aplicar uma forma genérica a IPE/HEA/UPN ou perfis especiais. |
| F10 | AF — Área de Seção de Corte / `section_total` | `A × Q`. Distinguir desta a área **pendente** de carga, `A × saldo de corte`. |
| F11 | AI — Quantidade Prevista / `quantity_to_plan` | Saldo da operação que se está a planear. Calcula também num registo local guardado com dados suficientes; não fica vazio só por não haver OF CPIS ou conclusão operacional. |
| F12 | AJ — Percentual de Horas Consumidas / `hours_pct` | `100 × soma das horas previstas da máquina na semana/ano / horas disponíveis dessa máquina no período`. É a ocupação agregada da máquina, repetida nas linhas que pertencem ao período. No Excel, `Planeamento!AU7` procura a referência máquina/semana em `PlanDisponibilidadeSemanal`, cuja coluna K divide I por H; I soma as horas previstas das linhas correspondentes. Não substituir pela contribuição individual da peça nem por horas reais. Identificar o significado no rótulo/detalhe. |
| F13 | AK — Semana Prevista / `expected_week` | Semana e ano ISO da data prevista. Conservar ano ISO; não usar `YEAR(data)` em conjunto com semana ISO. Quando planeamento for por semana manual, validar o par semana/ano e a coerência com a data. |
| F14 | Peso unitário / `weight_unit` | Para o aço correspondente à regra Excel: `A / 1 000 000 × L / 1 000 × 7 850`, em kg. Uma propriedade catalogada ou material com densidade diferente exige origem e regra compatíveis, não uma densidade assumida silenciosamente. |
| F15 | AL — Peso a Produzir / `weight` | `peso_unitário × quantidade_prevista` da peça. Não duplicar peso por existir uma operação adicional. |
| F16 | AN — Comprimento total registado / `total_length` | `Q × L`, em mm; é o total necessário, não apenas o saldo. |
| F17 | AO — Comprimento unitário de perfil / `stock_length_mm` | Sugestão `12 000` se `L > 6 000`, senão `6 000`. Uma substituição manual explícita prevalece e conserva a sua origem. |
| F18 | AP — Nº de perfis inteiros / `bars` | `ceil(saldo_corte / floor(S / L))`. Não substituir por `ceil(saldo_corte × L / S)`. Saldo conhecido zero dá zero. Com saldo positivo e `L > S`, apresentar impossibilidade de encaixe. |
| F19 | Metros por realizar / `remaining_m` | `saldo_corte × L / 1 000`. |
| F20 | Horas previstas por operação | `volume pendente / taxa aplicável`, na mesma unidade, acrescido de preparação apenas se existir um valor explícito. Usar mm²/h para a taxa de corte por área; outras operações exigem método próprio. |
| F21 | Prazo e atraso / `deadline_status`, `overdue` | Comparar a data pertinente com a data local e os saldos por operação. Distinguir saldo positivo de saldo desconhecido e prazo previsto de entrega; não declarar concluída uma peça sem dados. |

Para todas as famílias do catálogo atual, C00 deve listar a fonte da propriedade e C04 deve testar a respetiva resolução. Não é aceite terminar com apenas as quatro geometrias acima quando o Excel disponibiliza outras famílias.

### 4.3 Fórmulas de Cantoneiras

Cada operação tem o seu próprio `P_op` (produção validada/provisória), `saldo_op`, taxa e carga. A coluna principal refere-se à 1.ª operação; a segunda não herda o seu contador automaticamente.

| ID | Campo / identificador | Regra obrigatória |
|---|---|---|
| G01 | Produzida principal / `made`, `ocr_quantity` | `made` representa a produção da fonte selecionada. `ocr_quantity` e `ocr_op_<código>` mostram só OCR validado associado à operação. O acumulado macro original fica na comparação. |
| G02 | Percentagem realizada / `made_pct` | `100 × P_op / Q`, quando `Q > 0`. |
| G03 | Qtd. falta / `remaining` | `max(Q − P_op, 0)` para a operação principal; calcular separadamente a segunda operação quando exista. |
| G04 | Comprimento total / `total_length`, total em metros | `Q × L` em mm; dividir por 1 000 para metros. Identificar a unidade na coluna. |
| G05 | Metros em falta / `remaining_m` | `saldo_op × L / 1 000`. |
| G06 | Velocidade aplicada / `speed_m_h` | Taxa manual aplicável, histórica válida ou Excel provisória, com origem, unidade e vigência. Conservar a velocidade importada original à parte. |
| G07 | Horas previstas / `theoretical_hours` | `metros_em_falta / velocidade_m_h` para operações com taxa em m/h. Se outra operação usar unidades/h ou minutos/unidade, usar o método explicitamente definido. |
| G08 | Peso unitário / `weight_unit` | `kg_por_metro × L / 1 000`, com correspondência **exata** na Tabela pesos. Designações distintas ou resultados divergentes não permitem escolher arbitrariamente. |
| G09 | Peso a produzir / `weight` | `peso_unitário × saldo principal`; não multiplicar por número de operações. |
| G10 | Quantidade prevista / `quantity_to_plan` | Saldo da operação planeada, inclusive em registo local novo. |
| G11 | Semana e ano previstos | Mesmas regras ISO de F13. Uma semana importada sem ano comprovado fica por calendarizar, com motivo; não usar o ano da data de corte. |
| G12 | Descrição e prazo | Descrição original preservada; descrição local derivada de entradas conhecidas. Prazo e atraso seguem F21, considerando operações aplicáveis. |

### 4.4 Fórmulas de capacidades

| ID | Campo | Regra obrigatória |
|---|---|---|
| H01 | Horas disponíveis | `turnos × horas_por_turno − horas_indisponíveis`, ou soma dos intervalos válidos do calendário quando esse for o modo escolhido. Não somar ambos os modos. Indisponibilidade superior ao horário é erro de configuração. |
| H02 | Carga prevista | Soma das horas das operações ativas no recurso/período. Contar cada operação uma vez; mostrar cobertura das que ainda não têm cálculo. |
| H03 | Horas trabalhadas/reais | Somar declarações únicas de folha ou período, com correções manuais auditadas. Uma folha com dez peças não fornece dez vezes as mesmas horas. Declarações sobrepostas precisam de resolução. |
| H04 | Horas livres | `horas_disponíveis − carga_prevista`. Resultado negativo representa sobrecarga. |
| H05 | Ocupação | `100 × carga_prevista / horas_disponíveis`, se disponibilidade positiva. Não limitar a 100%. Disponibilidade zero com carga positiva mostra sobrecarga e percentagem indefinida. |
| H06 | Turnos equivalentes | `carga_prevista / horas_por_turno`; conservar fração. |
| H07 | Capacidade física total | `horas_disponíveis × taxa_por_hora`, por unidade/método compatível. Quando a configuração usar minutos/unidade, normalizar a taxa para `60 / minutos_por_unidade` antes deste produto. |
| H08 | Capacidade física livre | `horas_livres × taxa`, com sinal e unidade explícitos. Não somar metros e áreas nem converter operações incompatíveis. |
| H09 | Taxa histórica | `soma(volume válido do conjunto) / soma(horas correspondentes do mesmo conjunto)`. Não usar média simples das taxas nem todo o volume com apenas as poucas horas conhecidas. |
| H10 | Taxa aplicada | Manual aplicável e válida → histórico utilizável → Excel válido. Empates, conflitos, validade temporal ou unidade incompatível impedem seleção silenciosa. |

Em Perfis, conferir a coluna C de `CapacidadeMáquinas` e as unidades; E/F são evidência alternativa, não substituição automática. O fator Thomas ×3 para quantidade necessária **superior a 50** só pertence à referência/fallback Excel correspondente: `horas = área_pendente / (taxa_excel × 3)`. Não o reaplicar a uma taxa histórica medida ou manual. Testar Q=50 e Q=51.

Não reproduzir o corte de somatórios na linha 1 035 do Excel. Não copiar erros de pesquisas aproximadas de pesos, datas de 1900 ou valores guardados desatualizados como resultados corretos. Divergências intencionais devem constar da comparação, com fórmula e justificação.

### 4.5 Regras comuns do motor

- Calcular primeiro identidade, operação, fonte e saldo; só depois percentagens, áreas, comprimentos, perfis inteiros, pesos e carga. Publicar todos com a mesma revisão de entradas.
- Guardar valor sem arredondamentos intermédios de apresentação. `ceil` e `floor` de F18 são regras do cálculo. Inteiros e semanas têm comparação exata; grandezas contínuas usam tolerância de `max(1e-6, abs(esperado) × 1e-8)` no cálculo e igualdade à precisão de apresentação na UI. Qualquer tolerância diferente exige justificação por campo.
- Denominadores zero, geometria inválida, taxa ausente, fonte ambígua e dados desconhecidos produzem resultado indisponível com motivo específico, nunca `NaN`, infinito, zero inventado ou célula vazia inexplicada. Resultados zero dedutíveis, como saldo nulo, continuam zero.
- Quantidades negativas/fracionárias de peças e comprimentos/taxas negativos são rejeitados. Valores desconhecidos, não aplicáveis e zeros conhecidos são estados distintos.
- Cada derivado tem fórmula, entradas, unidades, origem, versão e motivo se não calculável. Totais parciais identificam número de linhas conhecidas/desconhecidas; não se apresentam como totais integrais.
- A RAW e as exportações mostram o valor calculado atual, mantendo os valores importados na comparação de origem. Não sobrescrever o Excel ou os factos OCR para obter concordância.

## 5. Checkpoints de implementação e validação

Cada critério abaixo é obrigatório. Guardar as provas numa pasta de execução, por exemplo `docs/validacao-planeamento-integral/<instante-UTC>/`, e referenciá-las na checklist.

Ordem de trabalho: começar por C00; resolver fontes/associações em C01–C02; implementar registo, motor e capacidades em C03–C04/C09–C10; concluir o recálculo transversal em C05. C06–C08 podem avançar depois de C00 enquanto houver uma dependência externa. C11 só aprova com C00–C10 aprovados; C12 depende de C11. A numeração organiza o âmbito e não autoriza deixar um checkpoint para trás.

### C00 — Baseline, inventário e ambiente de teste

- **C00.1** Guardar estado Git, versões relevantes, serviços, snapshots, hashes dos três ficheiros e manifesto do ambiente. Distinguir alterações preexistentes das desta execução.
- **C00.2** Produzir inventário completo de campos RAW/formulários e fórmulas F01–F21, G01–G12, H01–H10: ficheiro, folha, célula/intervalo/VBA, entradas, unidade e resultado esperado. Classificar todas as famílias de perfil com propriedade resolúvel ou motivo concreto de ausência.
- **C00.3** Reproduzir e documentar: registo exige OF existente; fecho não exclui corretamente; painel Colunas fecha; falta de arrastar; scroll/tipografia 11 pt; saldo incorreto do caso OF264774; produção de Cantoneiras incompleta. Se algum já tiver sido corrigido, provar o estado presente e manter a regressão correspondente.
- **C00.4** Preparar base descartável para testes e cópia integral isolada para volume/browser. Confirmar que os destinos de escrita de testes são esses ambientes. Guardar uma baseline dos testes existentes antes das alterações.

**Aprovação:** inventário cobre 100% dos campos e fórmulas aplicáveis; exemplos e origens estão identificados; ambiente isolado funciona. A mera existência de documentação antiga não aprova C00.

### C01 — Ingestão real e reconciliação de Perfis e Cantoneiras

- **C01.1** Para Perfis e Cantoneiras, comparar a população de folhas validadas e registos únicos na fonte, no centro e nas projeções, no mesmo instante/corte. Reconciliar todas as páginas, folhas sem produção, quantidades desconhecidas e expansões em peças filhas. Não usar `COUNT(*)` de linhas expandidas como contagem de eventos originais.
- **C01.2** Confirmar as fontes efetivamente utilizadas por Perfis e Cantoneiras e os backups atuais no Drive. Ler a SQLite/arquivo de forma consistente e só de leitura; reconciliar conteúdos completos, IDs e revisões com o centro. Não confundir a ordem visual com a identidade armazenada.
- **C01.3** Rastrear os eventos centrais reais de ambas as áreas até à peça/operação, saldos e horas ou ao motivo individual de exclusão. Quantidade ou operação desconhecida permanece explícita.
- **C01.4** Confirmar idempotência. Em isolamento, verificar correção, desvalidação, indisponibilidade e leitura parcial: conservar o último conjunto íntegro e identificar a pendência, sem duplicar produção.
- **C01.5** Confirmar continuidade das duas fontes e a revisão aplicada aos saldos. Distinguir a última tentativa de atualização, o último sucesso e a atualidade dos dados; comprovar dois ciclos automáticos e uma atualização real no destino.

**Provas:** relatório das duas áreas por IDs/revisões, conteúdos reconciliados, ciclos reais, rastreabilidade individual e cenários de falha. A aplicação «OCR original» está fora deste contrato por instrução do utilizador; não é um bloqueio.

### C02 — Associação, operações, deduplicação e fonte dos saldos

- **C02.1** Associar por identidade de peça suficiente: OF, referência, perfil/dimensões, comprimento e discriminadores necessários. OF/referência por si só não podem unir peças diferentes. Respeitar associações humanas válidas e invalidar apenas quando a identidade relevante muda.
- **C02.2** Implementar correspondência de operações de Cantoneiras a partir de informação comprovada da folha/linha e catálogos. Quando a máquina permita várias operações, disponibilizar decisão auditada por evento ou conjunto homogéneo; não escolher a 1.ª operação por conveniência.
- **C02.3** Deduplicar por origem, instância, folha, linha, revisão e peça filha, usando apenas a revisão validada vigente. Tratar produção repetida ou ambígua nas fontes das duas áreas: equivalência comprovada ou conflito por resolver, nunca soma automática.
- **C02.4** Escolher fonte **por peça e operação**. Definir objetivamente cobertura válida: quantidade numérica, revisão validada, identidade/operação resolvidas e ausência de conflito conhecido no conjunto considerado. Eventos conhecidos mas incompletos/ambíguos não podem desaparecer do diagnóstico para permitir usar um total parcial como completo. Aplicar fallback Excel provisório quando a cobertura não é utilizável.
- **C02.5** Testar OCR, Excel provisório, ausência de ambas, zero inicial local, conflito, excesso, corte versus abocardar e operação adicional. A diferença OCR/Excel é visível; não usar `max(OCR, Excel)`, não somar acumulados e não escolher Excel só por ser maior.

**Aprovação:** todas as produções resolúveis alimentam a operação certa; as restantes têm motivo e caminho de resolução. «Por confirmar» não pode ser usado em massa para contornar a implementação. As causas sistémicas que hoje impedem todo o OCR Cantoneiras têm de ser eliminadas.

### C03 — Registo manual realmente novo e completo

- **C03.1** Criar pela interface uma OF e OV inexistentes com cliente/contexto local. Guardar sem seleção anterior de OF e sem exigir sincronização CPIS para o registo local.
- **C03.2** Reutilizar necessidades, registos e revisão existentes; acrescentar armazenamento administrativo local quando necessário. Idempotência evita duplicação num duplo clique/reenvio; conflito de revisão não apaga trabalho.
- **C03.3** Executar em Perfis e Cantoneiras: criação, duas peças na mesma OF, alteração, reabertura no browser e releitura da base. Verificar persistência de todos os campos enviados e ausência de perda de campos omitidos numa edição parcial.
- **C03.4** Comparar automaticamente o contrato do formulário de Cantoneiras com todos os campos editáveis da RAW. Cada campo calculado deve surgir como resultado ou no detalhe; cada facto de leitura tem origem. Restaurar campos aplicáveis hoje ocultados por listas de campos retirados.
- **C03.5** Mostrar a linha nova na RAW e os resultados possíveis logo após guardar. Produção inicial zero é local e explícita. Quando houver máquina, período e parâmetros suficientes, incluir a carga estimada sem depender de estado operacional «ready». Manter distintas a estimativa de planeamento e a autorização para emissão/exportação operacional.

**Provas:** payload/resposta, consulta à base isolada, capturas dos dois formulários e das duas RAW, comparação de identificadores sem omissões.

### C04 — Motor integral de fórmulas e comparação com Excel

- **C04.1** Implementar F01–F21, G01–G12 e H01–H10 num motor partilhado. Retirar dependências de valores derivados antigos em cache quando as entradas mudam. Fixar unidades e política de valores desconhecidos.
- **C04.2** Criar comparação independente por campo: entradas, valor Excel guardado, fórmula original, resultado esperado recalculado, resultado da aplicação, diferença e justificação. O valor esperado não pode ser obtido chamando a própria função em teste. Incluir regras escritas como texto no layout.
- **C04.3** Cobrir famílias de perfil, tabelas de peso, operações e métodos de capacidade presentes na população atual. Testar: Q=0, produção zero/excessiva/desconhecida, comprimento 0/6 000/6 001/12 000/12 001, encaixe impossível, stock manual, abocardar Sim/Não/desconhecido, segunda operação 0, perfil desconhecido e catálogo ambíguo.
- **C04.4** Validar semanas na mudança de ano ISO, denominadores zero, unidades mm/m/mm²/kg/h, taxas inválidas, conflito de calendário e Thomas Q=50/51. Comparar as linhas depois da 1 035; não truncar população.
- **C04.5** Na cópia integral, produzir relatório de cobertura por campo/área: total, aplicável, entradas suficientes, calculado, indisponível com motivo, erro inesperado. Exigir zero casos calculáveis sem resultado e zero divergências numéricas não explicadas. Não limitar a análise à primeira página da RAW.

**Aprovação:** todos os campos do contrato têm regra implementada e evidência; os casos reais da secção 6 passam. «A fórmula existe no código» sem chegar ao valor RAW não basta.

### C05 — Recálculo completo e visível

- **C05.1** Pré-visualização no servidor usa o mesmo motor da gravação. Ao guardar, devolver os novos valores da linha e a respetiva revisão, sem esperar pela reconstrução integral de todas as áreas.
- **C05.2** Recalcular dependências quando muda quantidade, geometria, comprimento, stock, abocardar/operação, máquina, data/semana, taxa, calendário, horas, associação OCR ou revisão validada. Recalcular também agregados antigos e novos quando uma peça muda de máquina/período.
- **C05.3** Testar a sequência de alterações no browser e conferir resposta da API, RAW, base/projeção, detalhe de capacidades e exportação. Sem F5, os derivados da linha aparecem até 2 segundos após a resposta de gravação; os agregados afetados convergem até 10 segundos na cópia integral de referência. Medir separadamente tempo total do pedido, espera e atualização, sem esconder latência num pedido prolongado.
- **C05.4** Após uma nova revisão OCR chegar ao centro, refletir os saldos e dependências sem edição manual nem F5. Medir chegada ao centro → publicação dos derivados → atualização do browser; exigir até 10 segundos para as dependências afetadas no ambiente de referência. Reportar separadamente o intervalo de sincronização das fontes de Perfis e Cantoneiras.
- **C05.5** Concorrência, falha do worker e resposta atrasada não restauram valores antigos. Se agregados ainda estiverem em processamento, mostrar esse estado; não anunciar conclusão antes da revisão correta estar visível. Reiniciar o serviço isolado e confirmar persistência.

**Provas:** sequências antes/depois com revisão e tempos medidos. Não aprovar com temporizador longo que termina em «guardado» mantendo dados antigos.

### C06 — Fechados fora do ativo, intactos no histórico

- **C06.1** Aplicar a regra `fechado_CPIS OU fechado_macro` no servidor, com normalização explícita dos estados existentes. Estados desconhecidos ficam identificados, sem os transformar arbitrariamente em fechados.
- **C06.2** Usar a mesma população ativa em RAW, pesquisa, paginação, contagens, filtros/facetas, análises, seleção em lote, exportações ativas e carga pendente das capacidades. Vistas antigas não podem reintroduzir fechados no âmbito ativo.
- **C06.3** Oferecer consulta explícita de histórico/fechados e, se existir, de todos. Conservar IDs, registos, relações, OCR, documentos e revisões; demonstrar na base ausência de eliminação.
- **C06.4** Testar aberto/aberto, fechado/aberto, aberto/fechado e fechado/fechado, fecho e reabertura legítima da fonte. Preservar produção histórica para H09 sem voltar a carregá-la como trabalho pendente.

**Provas:** matriz de estados, contagens antes/depois em todos os consumidores e consulta dos mesmos IDs no histórico.

### C07 — Colunas: setas, arrastar, grupos e persistência

- **C07.1** Reproduzir o bug e corrigir reconstrução de `details`/estado do painel. Mover dez vezes nos dois sentidos, com e sem pesquisa: grupo permanece aberto, foco e scroll mantêm-se, URL não muda e não há submissão involuntária de formulário.
- **C07.2** Arrastar dentro do grupo e entre grupos de apresentação, incluindo primeiras/últimas posições; a lista e a grelha respeitam a mesma ordem. Oferecer alternativa por teclado/setas.
- **C07.3** Permitir fixar/desafixar OF, OV e Referência em vez de as impor sempre na normalização. Todas as colunas do contrato são acessíveis, sem duplicação ou desaparecimento.
- **C07.4** Persistir visibilidade, ordem, grupo, largura e fixação na vista/disposição adequada, separando áreas. Reabrir painel, recarregar página e recuperar vista antiga. «Repor vista» restaura o padrão da área sem perder dados.

**Provas:** teste de browser com assertivas sobre ordem/URL/grupos, captura ou vídeo curto e resposta de persistência.

### C08 — Barra horizontal e tipografia 11 pt

- **C08.1** Manter barra horizontal do contentor da RAW acessível junto da grelha, sem ter de descer milhares de linhas. Se o browser usar barras sobrepostas ocultas, disponibilizar um controlo horizontal visível sincronizado. Arrastar e chegar comprovadamente à última coluna em Perfis e Cantoneiras.
- **C08.2** Aplicar uma fonte legível e `font-size: 11pt` aos textos, cabeçalhos, menus, inputs, seleções e botões do planeamento. A 100% de zoom, 11pt corresponde aproximadamente a 14,67 CSS px; 11px não cumpre o pedido. Reduzir altura e espaçamento sem cortar caracteres nem ocultar controlos.
- **C08.3** Verificar com instrumentação do browser a fonte efetivamente renderizada e o tamanho de 11 pt. A fonte substituta existente é aceite por instrução do utilizador; Calibri não é obrigatória.
- **C08.4** Validar 1 440 px, 1 024 px, 390 px e zoom 200%, menus abertos, muitas colunas, teclado e células editáveis. Nenhuma coluna inacessível, texto sobreposto, foco perdido ou controlo cortado. Manter a compactação sem depender de zoom global reduzido.

**Provas:** capturas, métricas do contentor/scroll, primeira/última coluna e nome real da fonte renderizada.

### C09 — Registo manual de capacidades e horas

- **C09.1** Disponibilizar acesso claro a «Definições → Capacidades e horas» a partir do planeamento, reutilizando as configurações existentes. Incluir máquina física, nomes equivalentes, operações, período, turnos, horas/turno, indisponibilidades, taxas/unidades e vigência.
- **C09.2** Permitir horas efetivamente trabalhadas por máquina/período ou folha, com data, origem manual e revisão. Distinguir disponibilidade planeada de horas reais; mostrar sobreposições com declarações OCR e permitir resolução sem duplicação.
- **C09.3** Guardar atomicamente, reabrir e editar com histórico, validação de unidades, idempotência e conflitos. Taxas de máquinas partilhadas só contam uma vez no recurso físico; calendários concorrentes não são somados automaticamente.
- **C09.4** Demonstrar H01–H08 e o efeito imediato de mudar turnos, horas, indisponibilidade ou taxa nos dois setores. Alteração de horas reais afeta H03/H09, não altera por si só as horas disponíveis H01.

**Provas:** configuração e resultados numéricos antes/depois, histórico e persistência na base isolada.

### C10 — Capacidades a partir do histórico

- **C10.1** Calcular H09 com conjunto rastreável de eventos e horas correspondentes, agrupado por máquina, operação, unidade e janela. Deduplicar horas por folha/período e resolver partilha de tempo entre operações; não repartir tempo sem regra comprovada.
- **C10.2** Publicar número de folhas/eventos, volume abrangido, horas, intervalo, exclusões e cobertura. Se faltarem horas/quantidades, excluir o par incompatível do numerador e denominador ou deixar a estimativa indisponível com motivo; nunca usar produção de todas as folhas e só horas de sete.
- **C10.3** Aplicar H10 e mostrar a origem na RAW/capacidades: manual, histórico ou Excel provisório. Taxa histórica válida começa a servir a estimativa automaticamente. Distinguir estimativa de parâmetro confirmado, sem exigir confirmação manual para cada estimativa histórica válida.
- **C10.4** Testar nova produção validada, horas manuais adicionadas, revisão, mudança de janela, taxa manual em vigor/expirada e fallback. Atualizar as estimativas dependentes sem F5; produzir pelo menos um caso numérico de Perfis e um de Cantoneiras no ambiente isolado e confrontar os dados reais disponíveis.

**Aprovação:** cobertura limitada dos dados reais é visível, não impede o funcionamento do mecanismo nem justifica uma taxa inventada. Sem horas reais utilizáveis em Cantoneiras, a interface mostra a referência Excel até existir base válida.

### C11 — Regressão integral, volume e auditoria final

- **C11.1** Executar testes unitários/integrados relevantes, incluindo os existentes de RAW, registo, necessidades, evidência, produção de Perfis/Cantoneiras e capacidades. Alterar expectativas antigas apenas quando a regra mudou neste plano; manter testes das invariantes de identidade, revisão e preservação de dados.
- **C11.2** Executar cenários reais de browser em base isolada: R01–R10, fontes MES de Perfis e Cantoneiras, fallback, fechos, recálculo, colunas, scroll e fonte 11 pt. Cobrir dados manuais, importados e mistos em ambas as áreas.
- **C11.3** Executar reconstrução e auditoria sobre a cópia integral, verificando todas as páginas/linhas, volume maior que 1 035, cobertura dos cálculos e os tempos C05. Não degradar o tempo de resposta da grelha através de carregamento integral no browser.
- **C11.4** Reconstruir/reiniciar e repetir os casos críticos: sem duplicação de eventos/horas/peças, sem perda de vistas ou registos locais, sem eliminação de históricos. Falha de fonte conserva última versão íntegra com aviso de antiguidade.
- **C11.5** Cruzar R01–R11 × C00–C12 × provas. Zero requisito sem evidência, zero falha obrigatória, zero teste necessário ignorado. Comparações Excel têm todas as divergências resolvidas ou justificadas por regra explicitamente identificada neste plano.

Comandos de partida, a adaptar ao ambiente isolado e aos testes adicionados:

```bash
.venv/bin/python -m pytest -q tests/test_planning_raw.py tests/test_raw_workspace.py tests/test_planning_registry.py tests/test_planning_needs.py tests/test_planning_evidence.py tests/test_original_ocr.py tests/test_capacity_revision.py
RUN_PG_INTEGRATION=1 .venv/bin/python -m pytest -q -m pg_integration
```

Inspecionar os destinos configurados antes de executar scripts de browser existentes (`raw_workspace_browser.cjs`, `raw_cantoneiras_browser.cjs`, `capacity_revision_browser.cjs` e outros pertinentes). Os testes novos devem exercitar o comportamento, não reproduzir a implementação. Guardar comando exato, código de saída, totais passados/falhados/ignorados e identificação do ambiente. Falhas preexistentes devem ser documentadas e avaliadas; não podem ser ocultadas num total global «verde».

### C12 — Disponibilização e prova no destino final

- **C12.1** Preparar alterações/migrações aditivas, cópia de segurança e reversão seletiva. Publicar a revisão validada no serviço de planeamento de destino (`kanban-planning.service`, porta 8113, e worker correspondente), dentro da execução solicitada; não reiniciar os MES 8100/8101 por rotina.
- **C12.2** Confirmar o endereço efetivamente usado pelo utilizador. Fazer verificação final de leitura no serviço disponibilizado: identidade da revisão, fontes, caso OF264774, amostra Cantoneiras, exclusão de fechados, colunas e scroll/fonte. Uma validação apenas em localhost de outra revisão não basta.
- **C12.3** Confirmar uma atualização real de fontes e o worker operacional. Comparar resultados publicados com a versão validada; diferença de snapshot exige reconciliação, não cópia de valores esperados antigos.
- **C12.4** Entregar checklist com os 13 checkpoints aprovados, matriz dos 11 requisitos, resultados Excel/aplicação, cobertura integral, testes, capturas, limitações legítimas dos dados e procedimento de reversão. Não declarar «tudo concluído» se algum requisito funcional ou verificação obrigatória ficar em falta.

## 6. Casos de validação obrigatórios e resultados esperados

### V01 — Erro real: OCR existente não altera o saldo

Perfis: **OF264774 / CI5421A3004 / ID 34512**, tubo 76 × 2,6 mm, comprimento 2 750 mm, quantidade necessária 840, sem abocardar.

- Folha 113, UID `9cf539376e00`, registo 1192: **396** unidades.
- Folha 112, UID `dfb96386112e`, registo 2037: **444** unidades.
- Produção das duas folhas: 18/09/2026; validações observadas em 21 e 22/09/2026.
- Na versão consultada: OCR cortado 840, mas por cortar 840, quantidade prevista 840, perfis inteiros 420 e metros pendentes 2 310.
- Resultado exigido com essas entradas e fonte OCR: cortadas **840**, percentual cortado/final **100%**, por cortar **0**, quantidade prevista **0**, perfis inteiros **0**, metros pendentes **0**, peso pendente **0** quando a propriedade unitária estiver resolvida. Comprimento total necessário permanece **2 310 000 mm**. Não fechar automaticamente a OF.
- Linhas ID 34513 e 34514 da mesma OF/referência têm outros perfis/comprimentos; não recebem estes 840 por coincidência de OF/referência.

Provar na API, RAW, capacidade, exportação e relatório de origem. Usar fotografia fixa deste caso nos testes isolados; no destino vivo, comparar com as entradas atualizadas do momento.

### V02 — Layout e arredondamento de perfis inteiros

- `Folha1!A2:AP2`: quantidade 48, comprimento 1 200 mm, varão redondo Ø20. Área unitária `100π`; área total **15 079,644737231007 mm²**; total de comprimento **57 600 mm**; stock sugerido **6 000 mm**. Com 48 cortadas, saldo e perfis pendentes são zero.
- `Folha1!A4:AP4`: tubo Ø76,1 × 3,25 mm, uma unidade. Área unitária/total **743,8113306455535 mm²**. A propriedade não desaparece quando muda apenas a quantidade.
- Caso limite isolado: saldo 5, peça 2 500 mm, perfil 6 000 mm → cabem 2 peças/perfil → **3 perfis**. A fórmula alternativa pelo comprimento total daria 3 neste caso; adicionar saldo **7**, peça **2 001** mm, perfil **6 000** mm → cabem 2 → **4 perfis**, enquanto a divisão de comprimento total daria 3. Esta divergência tem de ser testada.
- Comprimento 6 000 → sugestão 6 000; comprimento 6 001 → 12 000; comprimento 12 001 com saldo positivo → não cabe na sugestão 12 000, com motivo visível. Stock manual 12 000 prevalece sobre sugestão 6 000 quando escolhido.

### V03 — Corte e abocardar separados

Caso isolado: Q=500, C=315, B=298, abocardar Sim → corte **63%**, abocardar/final **59,6%**, por cortar **185**, por abocardar **202**. Sem abocardar → final **63%**, saldo de abocardar zero. Nunca usar 315+298 como produção de uma só operação.

### V04 — Cantoneiras: peça, operação e peso

Usar uma linha real do snapshot atual, com célula de origem registada, e a peça de referência **OF250015 / DLR777**, `L45X45X4 S355J0 EN10025`, comprimento **737 mm**, operações **119/0**, se continuar no snapshot. Código 0 não gera segunda carga. O peso vem de correspondência exata, com valor e célula explicitados.

Caso isolado complementar: Q=100, produção principal=40, L=2 000 mm, taxa aplicável=30 m/h → saldo **60**, realizado **40%**, total **200 m**, pendente **120 m**, horas **4**. Com catálogo de teste independente de **3 kg/m**, peso unitário **6 kg** e pendente **360 kg**. Esses 3 kg/m são dados de teste, não propriedade atribuída à peça real anterior.

Adicionar produção de segunda operação distinta e verificar que nem contador, peso nem horas da primeira são duplicados.

### V05 — Capacidade manual e histórico

- 2 turnos × 7,5 h − 1 h indisponível → **14 h disponíveis**. Carga de 10 h → **4 h livres**, **71,428571…%** de ocupação e **1,333333… turnos**. A 30 m/h → capacidade total **420 m** e livre **120 m**.
- Com carga de 16 h → livres **−2 h**, ocupação **114,285714…%**; não truncar sobrecarga.
- Duas peças da mesma máquina/semana com 2 h e 8 h previstas, para 14 h disponíveis: F12 mostra **71,428571…% nas duas linhas**. Não mostra 14,285714…% numa e 57,142857…% na outra; essas são contribuições individuais, não o campo original do Excel.
- Histórico compatível: 100 m/5 h e 300 m/10 h → taxa **400/15 = 26,666666… m/h**, não média simples 25 m/h. Várias peças na mesma folha não repetem as horas.
- Duas sugestões de calendário Vanguard de 80 h e 32 h no mesmo período/recurso → conflito visível, nunca 112 h por soma automática. Uma configuração manual aplicável resolve a escolha com histórico.
- `2027-01-01` → semana ISO **53**, ano ISO **2026**. Não guardar 2027-W53.

### V06 — Alterações, fechos e novo registo

Criar ordem inexistente em cada área; guardar; alterar quantidade e comprimento; mudar máquina/semana; adicionar taxa e horas no ambiente isolado; receber nova revisão OCR de teste; fechar via cada fonte e voltar a abrir legitimamente. Em cada passo, conferir a linha, os agregados, a persistência, a origem e os tempos C05. IDs e histórico mantêm-se.

## 7. Evidência e formato do relatório final

Cada prova referenciada na checklist deve conter:

- Identificador do requisito/checkpoint/critério; data/hora; ambiente; revisão de código; snapshots e hashes das fontes pertinentes.
- Comando ou passos reproduzíveis, entradas, valor/estado esperado independente, valor/estado observado e resultado.
- Caminho para saída de testes, consulta SQL sem credenciais, JSON de API, comparação numérica, captura ou registo de browser, conforme aplicável.
- Para cobertura: totais e exclusões justificadas. Para tempo: início/fim, tempos medidos e condição de aprovação. Para OCR: IDs estáveis e percurso até ao saldo.

Entregáveis mínimos da execução:

1. Inventário de campos/fórmulas e manifesto das fontes.
2. Reconciliação das três origens OCR, incluindo funcionamento real do original.
3. Comparação Excel/aplicação para F01–F21, G01–G12 e H01–H10, com cobertura de toda a população calculável.
4. Relatórios de API, base e browser dos checkpoints, testes de regressão e desempenho.
5. Matriz R01–R11, checklist C00–C12 preenchida com provas, revisão publicada e reversão.

O executor termina apenas quando os entregáveis estiverem completos e todos os critérios obrigatórios tiverem evidência aprovada. Se existir um bloqueio externo real, entrega os trabalhos concluídos e declara explicitamente o restante **incompleto**; não converte falta de acesso, falta de dados ou falta de validação em sucesso.
