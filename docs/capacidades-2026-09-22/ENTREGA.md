# Cantoneiras, capacidades e disponibilidade semanal — entrega de 22/09/2026

Publicado no serviço de ensaio `kanban-planning.service` (8113), no endereço já utilizado. O trabalhador `kanban-raw-worker.service` está ativo. As aplicações de validação OCR não foram reiniciadas nem receberam escritas de produção de teste.

- [Cantoneiras](https://louise-pest-performed-atom.trycloudflare.com/planeamento/raw?area=cantoneiras).
- [Capacidades das máquinas](https://louise-pest-performed-atom.trycloudflare.com/planeamento/capacidades).
- [Disponibilidade semanal](https://louise-pest-performed-atom.trycloudflare.com/planeamento/disponibilidade?area=cantoneiras).

## Resultado funcional

Cantoneiras tem uma disposição inicial independente: OF, OV e Referência fixas; Data de corte, Tipo de material, QTD, Descrição integral do material, Comprimento, 1.ª/2.ª operação, Equipa e Pavilhão. Qtd. falta e Fechado permanecem disponíveis no menu e no detalhe, mas não são selecionados inicialmente. O menu Colunas inclui «Repor vista de Cantoneiras». As vistas gravadas com colunas explícitas mantêm essa seleção. Os códigos têm a descrição do catálogo acessível; o código 0 da segunda operação não produz outra tarefa.

A descrição original `Des. Material` aparece tanto na tabela como na comparação de origem. Uma alteração técnica conserva o original e compõe uma descrição local apenas a partir de valores conhecidos. Manual/PDF continuam nos serviços e na identidade existentes; não foi criada outra forma de registo.

As duas páginas novas apresentam conjuntos calculados no servidor, com paginação e acesso às peças. Clicar na máquina abre:

1. Peças e cálculos: entradas, origem da quantidade, fórmula, taxa, vigência, fatores e motivos de revisão.
2. Calendário e parâmetros: sugestões, decisões locais, conflitos, áreas/metros, peso e cobertura; horas disponíveis/livres, ocupação e turnos.
3. Comparação com Excel: ficheiro, versão, folha, célula, valor guardado e fórmula. As fórmulas não são executadas; o VBA não é aberto.
4. Produção registada: eventos validados e horas declaradas na folha, com as datas próprias. Recursos partilhados permitem consultar cada área; as horas não são repetidas por peça.

«Configurar» permite manter máquinas físicas e equivalências explícitas, operações suportadas, taxas com âmbito/vigência, calendários, exceções e confirmações do ano da semana importada. A cópia de calendários mostra a comparação antes da confirmação. Há revisão, idempotência e histórico; não se pede nome ou novo login.

A previsão ou semana da preparação não é substituída pela data de corte. Para estimar trabalho **por calendarizar**, a vigência da taxa é avaliada na data local da consulta e essa utilização fica identificada no detalhe; isso não atribui uma semana de execução.

A referência semanal é construída pelo servidor, apresentada para confirmação e guardada com as peças, quantidades, especificações e versões consideradas. O cumprimento usa essa revisão explícita e eventos OCR da semana, separando produção associada, fora do plano e por conferir. Uma revisão técnica incompatível fica fora do numerador. A ausência de OCR continua desconhecida. A referência criada agora não é apresentada como prova do plano que vigorava antes da gravação.

## Importação e reconciliação

Antes da importação foram guardados o estado do workspace, os importadores, a macro anterior e uma cópia PostgreSQL:

`/home/luis/.local/state/planning-backups/capacidades-20260922T210215Z`

O importador existente de Perfis publicou `mtg2_bf1cd6a25986791e`, SHA-256:

`bf1cd6a25986791e431160d812afa1de5e2e52e9013a9f989745033fe1fa61fc`

A importação contém **7.413 linhas**; os **18 controlos** da publicação passaram. A RAW publicada contém 7.413 linhas lógicas de Perfis e 75.303 de Cantoneiras nesta população. O hash da macro foi novamente verificado após as leituras e mantém-se igual ao ficheiro descarregado.

Cantoneiras conserva `mtg_79ca6d60785198f2`. A associação W39 → 2026 foi gravada com a confirmação já dada pelo utilizador, vinculada apenas a esta versão. Ver `confirmacao-w39.json`.

| Máquina — Cantoneiras W39/2026 | Horas teóricas recalculadas |
|---|---:|
| Peddi 6 | 28,48 |
| Peddi 8 | 154,72 |
| Ficep XP T4 | 248,06 |
| Ficep XP T6 | 138,07 |
| Ficep Rapid 20T -1 | 112,49 |
| Ficep Rapid 20T -2 | 124,81 |
| Ficep Rapid 25T | 92,54 |
| Total da operação principal | **899,17** |

São **3.609 operações principais**, não fechadas na macro, com quantidade em falta canónica, comprimento e velocidade conhecidos. Existem ainda **1.021 operações adicionais** no período, que não herdam automaticamente a quantidade ou a velocidade da primeira operação. O resultado é uma estimativa da macro; não é carga confirmada nem horas reais. A consulta mostra separadamente as divergências do estado CPIS.

Foram encontradas **1.757 entradas de capacidade de Perfis com linha de origem depois da 1.035**. Estão incluídas na população de cálculo; a cobertura identifica entradas sem cálculo válido. Quantidades negativas, taxas inválidas e propriedades desconhecidas não aumentam a disponibilidade.

A linha **OF250015 / DLR777** foi verificada na base e no browser: `L45X45X4 S355J0 EN10025`, 737 mm, operações 119/0. A Vanguard mantém as duas sugestões da W39, **80 h e 32 h**, num conflito único sem soma ou escolha automática.

Os cálculos de Perfis consultam C em `CapacidadeMáquinas`. E/F são evidência alternativa, não substituições automáticas. O fator Thomas ×3 acima de 50 peças só aparece na estimativa/comparação histórica; não é aplicado ao cálculo com taxa confirmada. Os turnos da comparação usam as 7,5 h presentes na fórmula de origem, sem o arredondamento a inteiros do Excel. As configurações locais podem definir outra duração de referência explicitamente.

## Fontes e desempenho

A migração `sql/026_capacity_revision.sql` acrescenta evidência de folhas, observações de metadados do Drive, tipos de objeto para período/referência semanal e índices de consulta. Não altera factos OCR ou estruturas do CPIS.

O trabalhador verifica metadados do Drive a cada cinco minutos quando `MES_RAW_DRIVE_CHECK=1`. Distingue última tentativa/consulta, hash e alteração remotos, versão importada e geração RAW. **Não descarrega/importa uma macro nesse ciclo.** O horário existente de importação do Drive mantém-se inalterado. A releitura da base não é apresentada como confirmação direta CPIS.

Depois de importar o novo snapshot, as estatísticas antigas faziam o PostgreSQL estimar uma única linha e escolher uma junção muito lenta. Foram atualizadas as estatísticas. Os dois importadores existentes passaram a executar `ANALYZE` nas quatro tabelas relevantes após a validação e antes do COMMIT, evitando essa situação nos próximos snapshots.

Medições sobre a base publicada, sem enviar o conjunto completo ao browser:

| Consulta | Perfis | Cantoneiras |
|---|---:|---:|
| Página de 100 linhas | 103 ms | 225 ms |
| Estados abertos + ordenação numérica | 104 ms | 686 ms |

A geração é preparada em segundo plano; o cálculo inicial não pertence ao tempo de cada página. Resultados e medições estão em `validation.json`.

## Verificação

Foram usados PostgreSQL descartável, a cópia integral `raw_capacity_test_20260922` e os ficheiros lidos sem escrita. Gravações de configuração e da referência semanal pelo browser foram feitas apenas no serviço de teste em 8119. Não foi guardada uma referência semanal fictícia na aplicação operacional.

Execuções de testes, com sobreposição entre comandos:

- `test_capacity_revision.py`, `test_raw_workspace.py`, `test_planning_fields.py`, `test_perfis_revision.py`: 79 passaram na execução inicial.
- `test_capacity_revision.py`, `test_raw_workspace.py`, `test_dossier_macro.py`: 40 passaram; inclui preservação da saída XLSM.
- Após os ajustes de evidência, `test_capacity_revision.py` + `test_raw_workspace.py`: 28 passaram.
- `test_capacity_revision.py` foi ampliado: **8 passaram**, incluindo falha do Drive, referência obsoleta, geometria alterada e quantidade local invalidada.
- Verificação final desses oito testes, do caso **315 cortadas / 298 abocardadas** e de recurso partilhado: **10 passaram**.
- Importador Perfis: **10 testes** passaram.
- `tests/capacity_revision_browser.cjs`: layout, 80/32 h, fórmulas/células, 899,17 h, referência semanal, configuração auditada, teclado, 390 px e ampliação a 200% passaram.
- O link público foi verificado nas três páginas; descrição e total reconciliados. O painel de fontes confirmou os hashes do Drive e da importação.

Capturas finais do serviço publicado:

- `cantoneiras-publicada.png`
- `capacidades-publicadas.png`
- `disponibilidade-publicada.png`

Capturas adicionais de ensaio: `vanguard-conflito.png`, `comparacao-excel.png`, `cumprimento-ensaio.png`, `disponibilidade-390.png`, `disponibilidade-200.png`. A referência mostrada na captura de cumprimento pertence à base descartável.

## Reversão

Para desativar a RAW nova e as duas páginas, definir `MES_RAW_WORKSPACE_ENABLED=0` no ambiente de `kanban-planning.service`, parar `kanban-raw-worker.service` e reiniciar apenas o serviço de planeamento. A interface RAW anterior volta a abrir. Este percurso foi verificado com a migração aditiva aplicada: a RAW anterior respondeu 200 e as novas páginas ficaram desativadas.

Não apagar tabelas, referências, decisões, calendários, ficheiros ou snapshots. Ao reativar, os dados continuam disponíveis. Para reverter código, extrair a cópia para outro diretório e comparar somente os ficheiros desta entrega: o workspace já continha alterações anteriores. Não repor globalmente diretórios nem restaurar o dump sobre decisões posteriores. A macro nova pode permanecer importada ao reverter apenas a interface.

A observação de metadados é desativável independentemente com `MES_RAW_DRIVE_CHECK=0`; o drop-in instalado é `~/.config/systemd/user/kanban-raw-worker.service.d/drive-metadata.conf`. Os caminhos opcionais são `MES_RAW_WORKBOOK_ROOT` e `MES_RCLONE_BIN`.

## Condições que continuam em aberto

- CPIS continua importado da macro, **sem confirmação direta**. Concluir preparações e exportar a macro continuam bloqueados conforme a regra existente.
- A disponibilidade confirmada exige confirmar recursos, taxas e calendários. Os parâmetros históricos não foram aceites em nome do utilizador.
- A Vanguard continua por conferir; outras semanas de Cantoneiras sem confirmação do ano permanecem incompletas.
- Erros de peso, operações adicionais sem evidência e horas reais ausentes aparecem com cobertura ou «Por confirmar».
- O fator histórico Thomas e as regras auxiliares XP/Rapid não foram ativados automaticamente. Não há seleção automática de máquinas, confirmação de stock, distribuição do trabalho ou escrita para os OCRs.
