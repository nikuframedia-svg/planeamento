# Plano de alterações da Carteira de planeamento

Data: 02/10/2026. Âmbito: ecrã `/planeamento/carteira`, no sistema de planeamento de Perfis MTG2 e Cantoneiras MTG3.

Este plano transforma o esboço e as correções do Luís em requisitos de implementação. A alteração central é separar os filtros da lista, a seleção exata de perfis e a carga já atribuída às máquinas. Inclui requisitos, decisões propostas, ficheiros envolvidos, fases de execução e critérios de aceitação. A implementação funcional ainda não foi feita.

Clarificação do utilizador: a parte do nesting corresponde à alteração do filtro **Estado** para **Sem máquina atribuída**, **Planeado para nesting** e **Planeado para produção**. O requisito é apresentar/filtrar esses estados e aplicar a cor correspondente; não criar um novo fluxo de envio.

O código responsável está em `/home/luis/projects/planeamento`. O repositório `/home/luis/projects/kanban-mes-mtg2` contém ligações para parte desse código, mas não contém o módulo `app/sector` que serve a Carteira. As alterações devem ser realizadas no projeto de planeamento.

## 1. Resultado da análise do sistema atual

| Elemento | Comportamento verificado | Consequência para a alteração |
| --- | --- | --- |
| Página e filtros | Existem Setor, Ver por, Família SKU, Família da encomenda, Prazo, Máquina, Sinal, Estado, Pesquisar e Ordenar. | Adaptar os controlos existentes e acrescentar semanas; conservar os catálogos. |
| Totais | `portfolio.groups()` filtra primeiro e devolve `totals` dessa população. O frontend usa esses totais nos cartões. Uma pesquisa sem resultados devolveu todos os totais a zero. | Criar um resumo do setor independente dos filtros e manter um subtotal próprio da lista. |
| Vistas | Existem modelo → SKU → OF, obra/OV → OF, perfil → OF, família → OF, família SKU → referência → OF e cliente → OF. | Acrescentar OF → Perfil sem substituir as vistas existentes. |
| Detalhe | A seta expande subgrupos; não existe seleção individual por checkbox nem contagem selecionados/total. | Criar o detalhe pela lupa, com membros identificados e seleção parcial. |
| Planear | Grava uma decisão `selected` por setor, OF e referência. Na vista OF pode gravar `reference='*'`. | O contrato atual é insuficiente para selecionar exatamente 17 de 18 membros. |
| Limpar | Apaga a decisão específica, preservando o evento de histórico. Uma decisão de OF inteira pode voltar a prevalecer. | Desmarcar um membro tem de produzir uma exclusão efetiva da seleção, incluindo perante decisões herdadas. |
| Estado | Os estados atuais são proposta, selecionado, excluído e por decidir. | Os três novos estados de planeamento precisam de uma classificação própria; renomear estes quatro códigos daria resultados errados. |
| Nesting | A pesquisa em `app/`, `sql/` e `tests/` encontrou referências de OCR/exportação, mas não uma classificação de nesting na Carteira. | Identificar ou acrescentar o dado que distingue nesting de produção no planeamento. Não deduzir esse estado de uma cor ou de um campo do OCR. |
| Máquinas e horas | `occurrences.py`, `estimates.py` e `assignments.py` já tratam ocorrências, recursos, sugestões, horas e decisões de máquina. | Reutilizar estas fontes e distinguir máquina atribuída de sugerida. |
| Gantt | `scope.py` e `gantt/integrated.py` usam a seleção por OF/referência para determinar o trabalho considerado. | A seleção exata tem de chegar também ao Gantt; corrigir apenas o frontend não basta. |
| Interface | Existe uma camada visual comum, tipografia a 11 pt e estilos próprios da Carteira. | Manter os padrões existentes e limitar os novos estilos ao ecrã. |

Provas específicas, reproduzidas com linhas sintéticas e a função de escrita substituída por uma captura:

- Filtrar uma OF até mostrar uma única referência e usar o contrato atual da vista OF pode gravar `*`: duas linhas tornam-se selecionadas.
- Duas linhas da mesma OF/referência, mas com perfis diferentes, recebem a mesma decisão atual: selecionar uma pode selecionar a outra.
- O filtro de estado é aplicado em `groups()`, mas não em `matches()`, usado por `selection.apply()`: uma linha visível pode resultar em duas linhas abrangidas pela ação.
- Apagar uma decisão específica não desmarca o membro quando existe uma decisão `selected` na OF inteira.

Validação realizada: 20 testes existentes de Carteira e seleção aprovados; verificação de navegação da Carteira em Chromium aprovada. Os testes de persistência usaram PostgreSQL descartável. A aplicação operacional foi consultada por GET; não foram gravadas decisões nem reiniciados serviços.

A verificação atual também confirmou que a API de Família SKU funciona. A página `/planeamento/maquinas` respondeu 404: a Carteira nova não deve depender da disponibilidade dessa página para mostrar os seus KPIs.

Evidências: [registo da análise](/home/luis/projects/planeamento/docs/plano-carteira-perfis-2026-10-02/evidencia.json) e [captura da Carteira atual](/home/luis/projects/planeamento/docs/plano-carteira-perfis-2026-10-02/carteira-atual.png).

## 2. Requisitos pedidos

### Filtros e navegação

- **RF01 — Controlos:** manter Setor, Família de Produto, Família SKU, Máquina, pesquisa por texto, Estado e Ordenar.
- **RF02 — Nome:** substituir “Família da encomenda” por “Família de Produto” na Carteira, incluindo opções de vista e explicações. Conservar a origem atual `work_type_code/work_type_description` do CPIS; não fundir esta dimensão com Família SKU.
- **RF03 — Vista:** acrescentar `OF → Perfil`. A primeira camada é OF, a segunda perfil; a lupa mostra os membros exatos do grupo. Manter `Perfil → OF` e as restantes vistas.
- **RF04 — Semana:** substituir o controlo Prazo por seleção múltipla de semanas com checkboxes. Mostrar apenas semanas com trabalho em aberto do setor, ordenadas por ano e semana.
- **RF05 — Sinal:** retirar o filtro Sinal do ecrã. Conservar as regras internas de anulação, Eletrofer, validação e estado CPIS, bem como informação necessária para explicar impedimentos.
- **RF06 — Limpar filtros:** acrescentar “Limpar todos os filtros”. Limpar famílias, máquina, semanas, estado e pesquisa; conservar setor, seleção de trabalho e decisões guardadas. Vista e ordenação são preferências de apresentação e mantêm-se.
- **RF07 — Independência:** pesquisar, filtrar, ordenar, mudar a vista ou abrir/fechar grupos não altera a seleção nem a carga dos KPIs. Mudar de setor muda o contexto do resumo e usa uma seleção separada por setor.

### Linha principal e detalhe

- **RF08 — Agrupamento:** mostrar referência/perfil, metros, peças, OFs, quantidade sem máquina e quantidade em nesting, com unidades explícitas. Preservar informação de datas/máquinas que continue útil sem sobrecarregar a linha.
- **RF09 — Lupa:** abrir um dropdown ou painel expansível associado à linha, com todos os seus membros selecionáveis. Identificar cada membro por OF, referência, perfil e informação suficiente para distinguir variantes.
- **RF10 — Seleção individual:** permitir marcar e desmarcar cada membro. A checkbox principal seleciona todos os membros do grupo completo apresentado no detalhe.
- **RF11 — Contagem:** numa seleção parcial, mostrar `17/18`; o denominador é o total de membros desse grupo, não o número de peças, operações ou linhas carregadas no browser. Com todos selecionados, mostrar checkbox marcada; com nenhum, checkbox vazia.
- **RF12 — Persistência durante a navegação:** conservar a seleção ao filtrar, pesquisar, ordenar e expandir/recolher. Mostrar quantos selecionados estão fora da lista visível quando for relevante para a ação.
- **RF13 — Subtotal:** incluir “Subtotal da lista” com os resultados filtrados. É independente dos KPIs do setor e do impacto da seleção. OFs são contadas de forma distinta, não pela soma dos números de OF de cada grupo.
- **RF14 — Ações:** manter os dois botões pequenos da linha com os nomes exatos **Planear** e **Limpar**. O botão atual Excluir deixa de ocupar esse par de ações; a capacidade de exclusão com motivo e o seu histórico podem continuar no detalhe.

### KPIs e estados

- **RF15 — Três painéis:** Punção, Broca e Resumo do planeamento na MTG3. Punção inclui XP T4, XP T6, Peddi 6 e Peddi 8; Broca inclui Rapid 20-1, Rapid 20-2 e Rapid 25.
- **RF16 — Catálogo real:** usar identificadores e aliases do catálogo. A API atual também apresenta nomes XP T7, T8 e T9; confirmar a sua classificação no catálogo e não os ocultar por não aparecerem no desenho. Na MTG2, usar as áreas/processos do setor, sem apresentar máquinas da MTG3 como se fossem suas.
- **RF17 — Valores:** mostrar por máquina metros e horas atuais, e entre parênteses o acréscimo dos perfis selecionados, por exemplo `1 000 m (+100 m)`.
- **RF18 — Acréscimo:** recalcular ao marcar/desmarcar ou alterar explicitamente o destino da proposta. Confirmar uma proposta incorpora a carga nova no total e retira a mesma carga do acréscimo.
- **RF19 — Filtro Estado:** substituir as opções atuais por **1. Sem máquina atribuída; 2. Planeado para nesting; 3. Planeado para produção**, além da opção neutra Todos. Este controlo filtra a lista; não muda o estado dos registos. Manter separado o estado administrativo CPIS.
- **RF20 — Resumo:** mostrar os totais por esses estados. Metros e horas estão identificados; a última métrica manuscrita precisa de confirmação. A API deve disponibilizar também peças e OFs distintas para não exigir alteração de dados quando a legenda for fechada.
- **RF21 — Cores:** marcar uma linha dá-lhe fundo cinzento. Uma linha no estado **Planeado para nesting** tem fundo verde. Num grupo com apenas parte dos membros nesse estado, indicar `x/y` sem apresentar o grupo inteiro como estando em nesting.

## 3. Decisões propostas para executar o plano

Estas definições resolvem detalhes que não estão totalmente especificados no desenho. São propostas de implementação, não novas instruções atribuídas ao utilizador.

- **D01 — Origem de Semana:** derivar a semana ISO de `priority_day`, mantendo a política do setor: MTG3 usa Data Corte; MTG2 usa Picking utilizável e as alternativas já configuradas. Mostrar ano e intervalo de datas, por exemplo `2026 · S40 · 28/09–04/10`. Não usar apenas `imported_week`, nem inventar o ano de Picking. Trabalho sem data continua acessível em Todos e numa opção “Sem semana definida”.
- **D02 — Unidade da contagem:** um membro é um item/linha técnica da carteira, com identidade e variante próprias; as suas ocorrências de operação não aumentam o denominador do `17/18`. A interface pode agrupar visualmente, mas a decisão conserva a lista exata de membros e operações abrangidas.
- **D03 — Universo do grupo:** a lupa abre o conjunto completo do grupo identificado pelo setor, vista e caminho. Os filtros externos determinam quais os grupos apresentados; dentro da lupa pode haver pesquisa própria, sem alterar o total do grupo. As quantidades mostradas na linha devem ser identificadas como total do grupo ou subtotal visível quando diferirem.
- **D04 — Marcar e Planear:** a checkbox cria uma seleção de trabalho em preparação. Planear confirma os membros dessa linha que estão marcados e regista a decisão usada pelo Gantt. Quando for necessário aceitar uma máquina sugerida, apresentar o destino e aplicar essa atribuição explicitamente; filtrar por máquina nunca a atribui. Planear não equivale a aceitar um cenário Gantt nem a registar produção executada.
- **D05 — Limpar:** limpar a marcação/proposta dos membros abrangidos e, quando já existe, a decisão de inclusão no próximo planeamento, mantendo o propósito atual do botão. Não apagar máquina, histórico de nesting ou plano aceite. A operação deve desmarcar efetivamente mesmo perante seleção herdada de uma OF inteira. Alterar um plano aceite permanece no fluxo próprio de replaneamento.
- **D06 — Origem do estado de nesting:** representar a fase nos dados usados pelo planeamento, para que o filtro Estado e a cor verde leiam a mesma informação. O código analisado não demonstra uma regra que transforme `selected` em nesting: mapear a origem real e, se faltar, acrescentar a fase ao registo normal de planeamento, com histórico. Não acrescentar botão ou endpoint de “enviar para nesting”, exportação ou integração externa.
- **D07 — Estado de produção:** requer decisão de planeamento para produção com destino efetivo, ou evidência do plano em vigor. Uma sugestão automática de máquina ou uma checkbox temporária não chega. Trabalho com máquina mas sem decisão continua consultável em Todos; não se inventa um estado de produção.
- **D08 — Sobreposição dos estados:** “sem máquina” descreve a atribuição; nesting/produção descrevem fases. Se um item em nesting ainda não tem máquina, pode satisfazer os dois filtros. Os totais de cada linha do resumo são únicos dentro desse estado, mas as três linhas não são uma partição para somar. Se se pretender torná-las mutuamente exclusivas, é necessário definir a precedência de negócio antes dessa alteração.
- **D09 — Seleção e atualizações:** manter o rascunho durante a sessão e por setor. A persistência entre dispositivos pertence às decisões confirmadas. Uma nova importação reconcilia por identidade; itens novos não entram silenciosamente numa seleção anterior. Itens alterados/concluídos ficam identificados para revisão, preservando a restante seleção.

Pormenores ainda por fechar no produto: legenda da última métrica do resumo, eventual significado de Semana diferente da política atual e a origem de dados que distingue nesting de produção. A distinção entre estas fases é um requisito de dados anterior à ativação do novo filtro, não um novo fluxo de envio.

## 4. Regras de dados e cálculo obrigatórias

- **GD01 — Três conjuntos separados:** `F` representa os resultados da lista filtrada; `S` os IDs efetivamente selecionados; `B` a carga já atribuída no planeamento atual do setor. Alterar F não pode alterar B nem S.
- **GD02 — Base dos KPIs:** B usa trabalho ativo com atribuição efetiva, proveniente do plano atual ou de decisão confirmada. Máquina apenas sugerida não entra como atribuição. Usar a mesma versão de fontes para todos os painéis.
- **GD03 — Acréscimos:** para cada máquina, somar apenas a carga nova dos membros de S com destino identificado e que ainda não está contabilizada em B. Selecionar um item já incluído na base não duplica a carga. Reatribuições devem usar o fluxo existente e uma diferença por operação, evitando mostrar o total completo como acréscimo.
- **GD04 — Unidade:** metros = saldo de peças × comprimento em mm / 1 000. Peças e metros físicos contam uma vez por item. Horas contam por ocorrência de operação e recurso. Uma operação seguinte não duplica as peças ou os metros da operação principal no resumo.
- **GD05 — Horas:** reutilizar a duração correspondente à máquina, operação e saldo atuais. Uma taxa de XP não pode ser reutilizada na Rapid sem recálculo. Somar durações individuais; não dividir os metros totais pela média simples das velocidades.
- **GD06 — Desconhecidos:** saldo, comprimento ou duração desconhecidos não são zero. Mostrar total conhecido com quantidade de itens por confirmar. A seleção continua identificável mesmo quando parte da carga não pode ser calculada.
- **GD07 — Máquinas:** distinguir `assigned_resource_id` de `planning_resource_id`, porque este último pode conter sugestão. Agrupar por ID físico/aliases, não por igualdade aproximada de nomes. Peddi 6 mantém o processo Punção mesmo quando a operação é 119.
- **GD08 — Identidade:** usar `item`, `line_key`, identidade de ocorrência `v2:<uuid>` e assinatura técnica conforme o âmbito. Labels como L100×10, índice da tabela, nome da referência ou par OF/referência isolado não são IDs suficientes para a seleção exata.
- **GD09 — Conflitos:** validar versão das fontes, assinatura técnica, membros e revisões no servidor antes de Planear, Limpar e guardar decisões de planeamento. Uma seleção desatualizada devolve conflito e os membros afetados; nunca ampliar silenciosamente o conjunto.
- **GD10 — Legado:** preservar decisões atuais por OF/referência e respetiva precedência na transição. Introduzir decisões explícitas por membro que prevalecem sobre as herdadas, incluindo uma desmarcação explícita. A migração deve demonstrar que não muda o conjunto efetivamente selecionado; casos sem correspondência inequívoca ficam por rever.
- **GD11 — Histórico:** cada ação confirmada guarda autor, momento, IDs abrangidos, antes/depois, versão e `request_id`. Repetir o mesmo pedido não duplica eventos; reutilizar o ID com conteúdo diferente devolve conflito. Gravar ação, membros e evento numa transação.
- **GD12 — Regras de fábrica:** preservar reconciliação de saldos, restrições técnicas, operações seguintes e máquina de trabalho iniciado. Remover o filtro Sinal não remove essas regras.

## 5. Contratos e componentes a alterar

Manter FastAPI, Jinja, JavaScript e PostgreSQL existentes. Os nomes de novos módulos e endpoints abaixo são propostas; não são APIs já disponíveis.

| Componente | Alteração prevista |
| --- | --- |
| `app/web/templates/carteira.html` | Controlos revistos, semanas, limpar filtros, três painéis, checkbox, lupa, contador, subtotal e legendas. |
| `app/web/static/carteira.js` | Estado separado de filtros/seleção/aberturas; carregamento de membros; pré-visualização por IDs; ações exatas e proteção contra respostas atrasadas. |
| `app/web/static/carteira.css` | Cinzento/verde, seleção parcial, detalhe legível, painéis e adaptação ao ecrã. Verificar a precedência de `planeamento_ui.css`, carregado depois. |
| `app/sector/routes.py` | Semanas múltiplas, vista OF → Perfil e contratos separados para grupos, membros, KPIs, pré-visualização e ações. |
| `app/sector/portfolio.py` | Nomes, vista, filtros, facetas de semanas, grupos e subtotais; manter os totais filtrados fora da resposta do resumo global. |
| `app/sector/selection.py` | Decisões por membro e desmarcações explícitas; compatibilidade com seleção antiga; pedidos com conjunto exato. |
| `app/sector/occurrences.py`, `estimates.py`, `assignments.py` | Fonte comum para membros, recursos, horas e destinos; reutilizar validações e selos de pré-visualização. |
| Novos `app/sector/planning_status.py` e `portfolio_kpis.py` | Estado de nesting/produção e agregação global por máquina/estado. Manter funções puras testáveis para classificação e cálculo. |
| `app/sector/scope.py`, `board.py`, `app/gantt/integrated.py` | Fazer chegar a seleção precisa à população planeada e incluir as novas revisões nos selos de versões. O 18.º item não entra no Gantt por herança. |
| Nova migração em `sql/` | Persistência por membro, estados/fases e eventos necessários. Escolher o número livre no momento; não editar migrações já aplicadas. |
| `app/raw/research_sync.py` e integração de decisões | Incluir novos registos persistentes no espelho existente, com identidade e histórico; não espelhar rascunhos de UI. |
| `tests/test_sector_*.py` e `tests/carteira_browser.cjs` | Casos novos de seleção, filtros, cálculo, persistência, Gantt e interação. Atualizar o teste antigo que exige o filtro Sinal e oito cartões. |

Contratos propostos:

- **Grupos:** conservar `GET /planeamento/api/carteira`, acrescentando `vista=of_perfil` e `semanas=2026-W40&semanas=2026-W41`. Devolver `list_totals`, totais do grupo, contagens de membros e versão. A migração do campo antigo `totals` deve ter compatibilidade explícita.
- **Opções:** estender `GET /planeamento/api/carteira/opcoes?setor=...` com semanas disponíveis, respetivo ano/datas/contagem e novos estados. As semanas não desaparecem por causa de uma pesquisa momentânea noutra coluna.
- **Membros:** novo GET de membros do grupo, com setor, vista e caminho; paginação por cursor, total integral, IDs e selos de versão. O limite atual de 500 grupos nunca pode limitar silenciosamente “selecionar todos”. Para grupos grandes, o servidor resolve o conjunto completo e devolve um token congelado ou IDs paginados.
- **Resumo:** novo `GET /planeamento/api/carteira/kpis?setor=...`, limitado ao contexto do setor e versão. Não aceitar `q`, famílias, semanas, máquina, estado, vista ou caminho como filtros do cálculo.
- **Pré-visualização:** novo POST de consulta com setor, IDs exatos/token do grupo, exclusões, destinos e versão. Devolver carga base, deltas por máquina, membros sem destino/horas e selo. Não guardar decisões.
- **Planear/Limpar:** estender a ação de seleção com contrato explícito versionado, IDs e revisão esperada. Não reconstruir a intenção do utilizador a partir dos filtros de apresentação. Preservar os chamadores existentes, incluindo `plano.js`, através de adaptação validada.
- **Estado de planeamento:** grupos e membros devolvem a classificação e a sua origem; o filtro aplica essa classificação e a UI usa-a para o verde. Se for necessário persistir a fase, integrar o campo e a revisão nas gravações normais do planeamento, sem criar uma ação separada de envio.

Não introduzir duas fontes independentes para seleção: o resolver comum deve ser utilizado pela Carteira, ocorrências, Gantt e quadro. Incluir as novas tabelas/revisões nos hashes de dependências e invalidações de cache, além da geração RAW.

## 6. Guidelines de implementação e interface

- **GI01 — Repositório:** trabalhar em `/home/luis/projects/planeamento`. Há alterações preexistentes nos dois projetos; preservar o trabalho em curso e conferir ligações simbólicas antes de editar. Não implementar uma segunda Carteira no MES.
- **GI02 — Camadas:** cálculos, elegibilidade e classificação no servidor; frontend responsável por interação, rascunho e apresentação. Evitar copiar fórmulas de horas ou regras de seleção para JavaScript.
- **GI03 — Compatibilidade:** manter fontes CPIS/Excel/OCR e a distinção entre Família de Produto e Família SKU. Uma mudança de rótulo não justifica migrar classificações.
- **GI04 — Cache:** separar pedidos da lista, opções, membros e KPIs. Identificar respostas pelo setor, versão e sequência; descartar respostas antigas. Uma pesquisa não deve refazer a carga global nem apagar S.
- **GI05 — Âmbito visível:** o contador e as ações usam o mesmo conjunto de IDs. Se houver seleção escondida por filtros, indicá-la antes da ação. Planear numa linha não aplica a seleção de outras linhas.
- **GI06 — Checkbox:** usar estado indeterminado para seleção parcial e texto acessível “17 de 18 selecionados”. A lupa é um botão com nome, `aria-expanded` e associação ao painel. Suportar Tab, Espaço, Enter e Escape, devolvendo o foco à lupa ao fechar.
- **GI07 — Cores:** usar classes de estado e texto/ícone acessível, não estilos inline nem a cor como única informação. Verde tem precedência sobre cinzento nos membros confirmados em nesting; grupos mistos conservam contagem e indicação parcial.
- **GI08 — Estilo:** respeitar a tipografia de 11 pt e as variáveis da interface atual. Manter o setor e a referência legíveis. Em ecrãs estreitos, empilhar painéis e permitir scroll horizontal da tabela sem esconder ações essenciais; validar zoom a 200%.
- **GI09 — Falhas:** conservar a seleção se uma API falhar. Não mostrar verde nem consumir deltas antes da confirmação. Após timeout de escrita, consultar o resultado do mesmo `request_id` ou repetir idempotentemente, sem criar uma nova ação.
- **GI10 — Proteções existentes:** reutilizar a validação JSON, origem do pedido, identidade do utilizador e permissões de consulta/escrita. Não confiar num autor enviado pelo browser.
- **GI11 — Âmbito funcional:** não alterar o solver, a política de prazos, a reconciliação de produção nem a fonte oficial do plano como efeito lateral desta interface. Alterações em scope/digests servem para respeitar a seleção exata.
- **GI12 — Entrega:** publicar uma versão coerente de backend, frontend, migrações e workers. Validar flags necessárias por função; não dar como concluído só porque o código existe em disco. A página separada de máquinas não deve ser um requisito de navegação para estes KPIs.

## 7. Plano de execução

1. **Fixar contratos e caracterizar o legado.** Inventariar membros/variantes, decisões atuais, origens de semana e recursos. Fechar o contrato exato de seleção e a classificação dos três estados. Preparar casos de referência com 18 membros, incluindo duplicados de OF/referência, máquinas sugeridas, sem data e saldos desconhecidos. Saída: contratos e cenários verificáveis.
2. **Implementar a seleção precisa e a persistência.** Acrescentar decisões por membro e eventos, resolver com precedência clara, desmarcação efetiva e controlo de concorrência. Adaptar scope, Gantt, quadro e hashes. Demonstrar migração sem mudança do conjunto selecionado. Saída: Planear/Limpar seguros para 17/18 antes de mudar o ecrã.
3. **Implementar estados e KPIs.** Mapear a origem de cada um dos três estados e acrescentar o dado de fase onde faltar. Agregar a carga base do setor e calcular os deltas por IDs, máquina e operação. Distinguir sugestões, desconhecidos e fases. Saída: APIs consistentes e invariantes numéricas aprovadas.
4. **Rever filtros, vistas e tabela.** Acrescentar semanas e OF → Perfil, renomear família, retirar Sinal e acrescentar limpar filtros. Montar a lupa, seleção individual, contagens e subtotal, ligando às APIs exatas. Saída: fluxo completo sem perda de seleção.
5. **Aplicar apresentação e validar utilização.** Três painéis, cinzento/verde, grupos parcialmente selecionados/em nesting, teclado, zoom e ecrãs estreitos. Saída: validação no browser com dados de teste e sem erros HTTP/JavaScript.
6. **Verificar integração e preparar disponibilização.** Executar regressões de Carteira, seleção, máquinas, Gantt, quadro, autoria e espelho. Ensaiar migração e reversão numa base descartável. Preparar pacote coerente, smoke tests e critérios de retorno à versão anterior; disponibilização operacional é uma etapa posterior a este plano.

## 8. Critérios de aceitação

- **CA01 — Filtros não mexem nos KPIs:** guardar base e deltas; alterar separadamente pesquisa, família, SKU, máquina, semana, estado, vista e ordenação, incluindo pesquisa vazia de resultados. A base e os deltas mantêm-se para a mesma versão e seleção.
- **CA02 — Limpar filtros:** manter setor, IDs selecionados e decisões; limpar todos os filtros previstos. Nenhum pedido de escrita é emitido.
- **CA03 — Semanas:** selecionar duas semanas de anos distintos, incluindo fronteira dezembro/janeiro. Não misturar S01 de dois anos; não inventar datas para linhas sem prazo. Apenas semanas com trabalho aberto aparecem.
- **CA04 — OF → Perfil:** abrir OF, perfil e lupa. Metros/peças reconciliam com os membros; OFs não duplicam no subtotal. Fechar/abrir não perde seleção.
- **CA05 — 17/18 real:** carregar 18 membros, selecionar 17 e confirmar. Contador, IDs da ação, registos persistidos e população do Gantt abrangem exatamente os mesmos 17. O 18.º mantém o estado anterior.
- **CA06 — Colisões e legado:** repetir com duas linhas da mesma OF/referência, mas perfis/variantes diferentes, e com uma decisão herdada `*`. A ação parcial não se amplia; Limpar desmarca efetivamente.
- **CA07 — Grupos grandes:** selecionar todos num grupo que exceda a página/limite do endpoint. O contador e os membros persistidos incluem o conjunto integral conhecido da versão, sem limitar a seleção ao DOM.
- **CA08 — Deltas:** marcar, desmarcar e repetir o mesmo item. O acréscimo aparece uma vez; um item já na base acrescenta zero. Após confirmação, a base aumenta pela mesma carga e o delta correspondente desaparece.
- **CA09 — Horas e peças:** várias operações do mesmo item não duplicam peças/metros do resumo; cada ocorrência contribui com as suas horas. A duração respeita a máquina de destino. Desconhecido continua identificado como desconhecido.
- **CA10 — Filtro Estado e verde:** uma amostra com os três estados devolve apenas os membros correspondentes a cada opção. Selecionar “Planeado para nesting” não grava nada nem muda os KPIs; os membros já nesse estado aparecem a verde também depois de recarregar. Uma checkbox temporária ou campo OCR não produz verde. Um grupo misto mostra a proporção correta.
- **CA11 — Produção:** selecionado sem destino ou com mera sugestão não passa automaticamente a planeado para produção. Plano aceite/legado mantém proveniência; os filtros de estado seguem a definição acordada.
- **CA12 — Concorrência:** mudar revisão/saldo/máquina entre pré-visualização e gravação devolve conflito sem escrita parcial. Repetição idêntica é idempotente; mesmo ID com conteúdo diferente é rejeitado.
- **CA13 — Navegação e setores:** alternar rapidamente filtros e setor, atrasando respostas. Não aparecem membros, carga ou seleção de outro setor. A vista vazia não limpa S.
- **CA14 — Regresso e espelho:** decisões antigas continuam coerentes; novas decisões chegam às dependências e ao espelho. Uma nova importação não reativa silenciosamente um membro desmarcado.
- **CA15 — Interface:** validar desktop, largura de 390 px, zoom 200% e teclado. Contagem, foco, texto e cores permanecem compreensíveis, sem erro HTTP ou JavaScript.

Os 20 testes e o caso de browser executados nesta análise demonstram o comportamento atual, não a conclusão destes critérios novos. A entrega só fica concluída depois de os casos aplicáveis serem executados sobre a implementação alterada.

## 9. Fontes de implementação

- [Página da Carteira](/home/luis/projects/planeamento/app/web/templates/carteira.html), [interação atual](/home/luis/projects/planeamento/app/web/static/carteira.js) e [estilos](/home/luis/projects/planeamento/app/web/static/carteira.css).
- [Grupos, filtros e totais](/home/luis/projects/planeamento/app/sector/portfolio.py), [decisões atuais](/home/luis/projects/planeamento/app/sector/selection.py) e [rotas](/home/luis/projects/planeamento/app/sector/routes.py).
- [Ocorrências e identidades](/home/luis/projects/planeamento/app/sector/occurrences.py), [estimativas](/home/luis/projects/planeamento/app/sector/estimates.py), [atribuições](/home/luis/projects/planeamento/app/sector/assignments.py) e [política de prazos](/home/luis/projects/planeamento/app/sector/priority.py).
- [Âmbito selecionado](/home/luis/projects/planeamento/app/sector/scope.py), [entrada do Gantt](/home/luis/projects/planeamento/app/gantt/integrated.py) e [quadro do plano](/home/luis/projects/planeamento/app/sector/board.py).
- [Esquema atual de seleção](/home/luis/projects/planeamento/sql/040_sector_selection.sql), [decisões de máquina](/home/luis/projects/planeamento/sql/045_sector_needs_views.sql) e [espelho](/home/luis/projects/planeamento/app/raw/research_sync.py).
- [Testes da Carteira](/home/luis/projects/planeamento/tests/test_sector_portfolio.py), [testes de seleção](/home/luis/projects/planeamento/tests/test_sector_selection.py), [integração Gantt](/home/luis/projects/planeamento/tests/test_sector_gantt_integration.py) e [teste browser](/home/luis/projects/planeamento/tests/carteira_browser.cjs).
