# Sistemas representados na base central — 20/09/2026

Consulta executada em `dataresearchmtg`, no PostgreSQL do container `postgres`,
às 21:10 UTC de 20/09/2026. A transação de inventário usou leitura apenas e
isolamento repeatable read. Não foram executados importadores, sincronizações,
alterações de produção ou migrações.

O âmbito é a base central que alimenta os MES e o planeamento Metalogalva.
Não é um inventário das outras aplicações e bases instaladas no servidor.

## Sistemas e fontes encontrados

| Sistema/fonte | Origem comprovada | Dados encontrados | Atualização registada |
|---|---|---|---|
| OCR/MES Perfis | `source_app=kanban-mes-mtg2`, escrita em `mes_kanban` | 77 folhas de produção, 381 registos | Última validação 18/09/2026; última data de produção 17/09/2026 |
| OCR/MES Cantoneiras | `source_app=kanban-mes`, escrita em `mes_kanban` | 73 folhas de produção com 727 registos; 1 folha adicional com 2 paragens | Última validação de produção 18/09/2026; última produção 17/09/2026. Paragens: evento de 06/08 e validação de 07/08 |
| OCR original MTG2 | Excel `SAIDA/Kanbans_Producao_NOVO.xlsx` publicado pelo PC no Drive e importado | 27 linhas de produção e 9 linhas de horas/paragens | Importação 21/08/2026. Produção de 15–17/04/2026; horas/paragens de 25/03–14/04/2026 |
| Planeamento de Perfis | `Met2_Plan_Perfis.xlsm` | 7.199 linhas da versão mais recente | Importação 20/09/2026 |
| Planeamento de Cantoneiras | `Met3_Plan_Cantoneiras.xlsm` | 75.192 linhas da versão mais recente | Importação 20/09/2026 |
| Mestre de componentes de chapa | `listaofs_mtg3.xlsx` | 170.094 linhas de origem | Importação 05/08/2026 |
| Planeamento/produção de chapa por Excel | `plan_chapa.xlsm` | 20.903 linhas de plano, 11.684 nestings, 20.618 linhas de Kanban diário | Importação 05/08/2026; última data do Kanban diário 15/07/2026 |
| Preparação/expedição de chapa | `Exp.chapaMTG3.xlsm` | 21.229 linhas de expedição, com quantidades preparadas/expedidas e dados auxiliares | Importação 05/08/2026 |
| Colaboradores | `ListaColaboradores.xlsx`, identificada pelo importador como exportação SAP | 720 registos de colaboradores | Importação 09/08/2026 |

As contagens de Excel acima referem-se à versão mais recente de cada fonte,
incluindo os seus estados históricos. Não são contagens de trabalho aberto.
Existem cinco versões retidas de cada macro de Perfis/Cantoneiras; somá-las
duplicaria informação. As linhas de diferentes etapas de chapa também não
devem ser somadas como se fossem peças diferentes.

Os 27 registos do OCR original têm os seguintes rótulos importados:
21 `OK`, 3 `DIVERGÊNCIA` e 3 `AVISO`. A presença do ficheiro não comprova a
cobertura de toda a produção atual desse sistema. Não existem folhas desse
terceiro OCR em `mes_kanban.validated_sheets`: o percurso é via Excel.

Diagnóstico posterior na mesma data: a exportação atual do OCR no PC contém
13.260 linhas de folhas validadas, incluindo 2.580 com data de setembro. A
antiguidade encontrada acima pertence à integração central, não à totalidade
dos dados existentes no OCR. Ver o
[diagnóstico da entrada do OCR original](diagnostico-entrada-ocr-original-2026-09-20.md).

## CPIS: cópias importadas e integração direta

Há dados CPIS nas seguintes origens:

- `raw_mtg.cpis_rows`: 12.362 linhas na cópia de Perfis e 70.129 na cópia de
  Cantoneiras, nas respetivas versões mais recentes.
- `raw_mtg.chapa_auxiliary_rows`: 68.970 linhas da folha `CPIS_Dados` de
  `plan_chapa.xlsm` e 68.971 da folha homónima de `Exp.chapaMTG3.xlsm`.
- `raw_mtg.chapa_master_rows`: mestre de OF/componentes proveniente de
  `listaofs_mtg3.xlsx`.

São cópias com sobreposição de ordens e não uma lista de OFs distintas obtida
por soma. A coluna `loaded_at` indica importação; não informa quando a consulta
CPIS dentro de cada Excel foi atualizada.

A integração direta tem estruturas criadas, mas não dados publicados:

- `cpis_mtg.versions`: **0 versões**.
- `cpis_mtg.orders`: **0 linhas**.
- `cpis_mtg.sync_attempts`: **1 tentativa, falhada**, em 20/09/2026.
- Nenhuma foreign table PostgreSQL encontrada nesta base.

## Preparações e documentos

As quatro tabelas de `planning_mtg` estão vazias: fichas, revisões, conferências
e propostas de saída ainda não têm registos nesta base.

O circuito PDF tem armazenamento separado no mesmo servidor:
`/home/luis/projects/kanban-mes-mtg2/data/dossiers/dossiers.db` (SQLite).
Foi consultado com `mode=ro` e `query_only=ON`:

- 5 documentos; 2 em estado `ready` e 3 em `review`.
- 12 registos de peças e 7 necessidades.
- 57 eventos de auditoria.
- 0 exportações e 0 propostas de exportação registadas.

O estado `ready` de um PDF não demonstra produção nem confirmação direta CPIS.

## Organização dos dados

- `raw_mtg`: linhas tal como importadas dos Excel, com valores originais.
- `core_mtg`: ordens, linhas, clientes, máquinas, colaboradores e componentes
  de chapa derivados das importações.
- `analytics_mtg`: vistas de consulta, cruzamento e indicadores; não são novas
  fontes independentes.
- `mes_kanban`: folhas e factos de produção/paragem validados pelos dois MES.
- `audit_mtg`: versões dos ficheiros, lotes de importação e verificações.
- `cpis_mtg`: estruturas para publicação da futura leitura direta CPIS.
- `planning_mtg`: preparação local, revisões, conferências e propostas.

## Limites de atualização e qualidade

O OCR original, chapa e colaboradores têm importações antigas face às dos
planos de Perfis/Cantoneiras. Os registos mais recentes dos dois MES têm data
de produção de 17/09, embora tenham sido validados em 18/09.

Foram encontradas 7 datas de fabrico futuras nos nestings de chapa, incluindo
2029, e 1.516 datas ausentes. Estas datas precisam de interpretação/validação
e não foram usadas como prova de atualização da fonte.

Fontes de verificação no código:

- `DATARESEARCHMTG/scripts/sync_drive.sh`: sincronização Drive e escolha dos
  importadores por ficheiro.
- `DATARESEARCHMTG/load_mtg2_producao_to_postgres.py`: produção do OCR original.
- `DATARESEARCHMTG/load_chapa_to_postgres.py`: mestre, plano e expedição de chapa.
- `pc-suite-kit/README.md`: arquitetura das três aplicações no PC da fábrica.

A [evidência agregada da consulta](planeamento-cpis-2026-09-20/inventario-sistemas-bd.json)
conserva contagens, datas, versões e tabelas, sem nomes de operadores ou credenciais.
