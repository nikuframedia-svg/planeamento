# Base original, Drive e dados atuais

Consultas de 24/09/2026, apenas de leitura, usando o `gdrive:` já autenticado e a aplicação original acessível pela ponte local 18080.

| Evidência | Resultado |
|---|---|
| `gdrive:SAIDA/app.db` | 98.832.384 bytes; modificação 10/09/2026 09:30:25 UTC |
| `/home/luis/projects/DATARESEARCHMTG/SAIDA/app.db` | Mesmo SHA-256 da cópia no Drive: `cff995ad2dd912b4ced412f9ced36cc478f8ed5bb681acd8edaa999928a344bd` |
| Leitura consistente dessa SQLite | 4.393 folhas validadas, 12.021 linhas validadas; última validação em 10/09 |
| Exportação atual da aplicação original | 14.008 linhas validadas; 174 registos datados de 23/09. Cinco datas futuras de 2028 conservadas e identificadas no relatório, sem as usar como prova de atualidade |
| Estado de backup da aplicação original | Backup bem-sucedido em 24/09 às 09:42:14 UTC, 112.652.288 bytes, destino `F:\Apps\OCR-original\data\backups`; tarefa horária ativa |
| Pesquisa recursiva no Drive configurado | Nenhuma SQLite original mais recente encontrada. Os backups de 24/09 em `SAIDA/backups/kanban-mes*` pertencem aos MES |

**Conclusão:** existem dados originais mais recentes do que 10 de setembro. A cópia `SAIDA/app.db` no servidor/Drive está desatualizada relativamente à aplicação. O backup atual reporta outro destino. O caminho efetivamente aberto pelo processo original e o transporte desse backup atual para o Planeamento continuam por comprovar; não foi importada a cópia antiga como se fosse atual.

O GET `/admin/refs-status` demorou mais do que o limite inicial de 15 s; uma consulta com limite de 55 s devolveu o estado acima. Não foi chamado o POST que desencadeia um backup, nem alterada a aplicação original.

O backup MES Cantoneiras de 24/09 também foi lido em SQLite `mode=ro`, com hash conferido contra o Drive. Nas folhas 686 e 735, os arrays guardados coincidem exatamente com o arquivo central. A ordem do CSV corresponde ao campo `_display_order`; a comparação inicial confundia posição visível com identidade armazenada. Os hashes dos CSV e dos dados esperados continuam iguais aos do corte inicial de 09:46 UTC.

Durante o trabalho entraram outras 19 folhas de Cantoneiras: o conjunto consultado passou de 182 para 201 folhas. Essa consulta posterior tem diferenças de projeção e duas novas folhas cuja ordem ainda requer reconciliação. A prova do corte inicial não certifica esse novo conjunto nem a futura publicação.

Provas: `t3-drive-source-analysis.json`, `t3-live-original-backup-status.json`, `t3-current-original-http-export.json`, `t3-local-original-read.json`, `t3-mes-pinned-cut-reconciled.json` e `t3-live-mes-reconciliation.json`.
