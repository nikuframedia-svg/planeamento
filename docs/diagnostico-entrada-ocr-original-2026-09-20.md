# Entrada do OCR original na base central — diagnóstico de 20/09/2026

## Resultado

O OCR original no PC tem dados atuais que não estão a chegar ao PostgreSQL
central. A integração central está ligada a um Excel antigo no Drive, enquanto
a aplicação já consegue exportar milhares de linhas de folhas validadas.

As verificações foram de leitura. Não foram validadas folhas, alterados
ficheiros operacionais, carregados dados no PostgreSQL ou executadas tarefas
de atualização no PC.

## Evidência observada

| Verificação | Resultado |
|---|---|
| PC, `/health`, através da ponte HTTP `127.0.0.1:18080` | HTTP 200; `status=ok`; versão anunciada `5f6ab6f` |
| PC, `/admin/queue-status` | Worker ativo; fila OCR com zero itens |
| PC, `/excel?limit=50` | Ecrã indica 15.608 linhas registadas, incluindo folhas não validadas |
| PC, `/export/cpis?validated_only=true` | HTTP 200; 13.260 linhas de folhas validadas; 2.580 com data de setembro de 2026 |
| Data de produção recente na exportação | 17/09/2026, considerando datas não futuras |
| Drive, `SAIDA/Kanbans_Producao_NOVO.xlsx` | 13.045 bytes; data de modificação apresentada: 19/05/2026 |
| Hash SHA-256 Drive/local/PostgreSQL | Igual nos três: `5a875211345b1543480669b11e673263580a7aebc2b74176f439c00dd664ed0d` |
| PostgreSQL, `raw_mtg.mtg2_producao_rows` | 27 linhas; última importação 21/08/2026; produção de abril |
| Sincronização do servidor | Último ciclo concluído em 20/09 às 12:18 UTC; sem importações pendentes |

O endpoint denominado `/export/cpis` é uma exportação dos dados da própria
aplicação OCR no formato destinado ao CPIS. Não é uma consulta à base CPIS.
O código da versão `5f6ab6f` confirma que `validated_only=true` aplica
`s.status = 'validated'` à consulta de produção.

O ficheiro de exportação foi obtido apenas para inspeção em memória/ficheiro
temporário. A evidência persistida é agregada, sem nomes de operadores.

## Onde o circuito está desligado

1. O importador central
   `DATARESEARCHMTG/load_mtg2_producao_to_postgres.py` lê exclusivamente
   `SAIDA/Kanbans_Producao_NOVO.xlsx`, folhas `Registos` e `Horas e Paragens`.
2. `DATARESEARCHMTG/scripts/sync_drive.sh` só agenda esse importador quando o
   conteúdo desse ficheiro muda. O hash atual é o mesmo que já foi importado;
   repetir a importação não traria as linhas atuais do OCR.
3. No código da versão anunciada pela aplicação do PC (`5f6ab6f`),
   `scripts/drive_pull.py` limita o transporte partilhado aos dois MES:

   ```python
   _MES_EXPORT_PORTS = {
       "BaseDados_Cantoneiras_MTG3": 8100,
       "BaseDados_Perfis_MTG2": 8101,
   }
   ```

   A função `push_outputs()` ignora ficheiros que não estejam nessa lista,
   registando `saida ignorada: ... nao pertence aos Kanbans MES`. Assim,
   `Kanbans_Producao_NOVO.xlsx` não é permitido nessa versão. A função
   `fetch_exports()` também só admite os exports dos dois MES.

4. A exclusão foi introduzida no commit `80596f4`, de 11/09/2026, com a mensagem
   «Keep original OCR inputs and backups local; retain Drive for MES».
5. A validação de uma folha no OCR deposita um CSV. A atualização do Excel
   agregado é um passo distinto, executado pelo conversor
   `kanban_refs/06_Kanban_OCR/kanban_csv2excel_novo_layout.py`. A rotina de
   validação não chama esse conversor.

As regras da versão anunciada pelo PC explicam a exclusão atual do transporte.
A estagnação do Excel já existia antes de 11/09; não é possível atribuir toda
a história do problema a esse commit.

## O que ainda não está comprovado no PC

O acesso disponível é HTTP, não uma consola Windows. O hash anunciado pelo
processo web identifica o seu código, mas não demonstra o conteúdo atual do
script executado pela tarefa agendada, eventuais alterações locais, os caminhos
efetivos ou o resultado do conversor CSV→Excel. Isso exige consultar os logs e
o estado da tarefa no PC. Não se afirma que o conversor esteja parado apenas
porque o Excel do Drive não mudou.

O `/admin/refs-status` não respondeu dentro do limite de 12 segundos; os
endpoints de saúde, fila, consulta e exportação usados no diagnóstico
responderam. Este timeout não foi usado como explicação para a falha de saída.

## Correção necessária

- Estabelecer uma publicação própria para os dados validados do OCR original,
  com identificação da origem, folha, linha e versão.
- Adaptar o importador central ao contrato dessa publicação. A exportação
  atual tem folha `Folha1` e 27 colunas; o importador antigo espera outro
  formato. Renomear a exportação não resolve o problema.
- Preservar a identidade dos registos para que novas sincronizações não
  dupliquem produção nem confundam revisões com novas peças.
- Mostrar última tentativa, última confirmação e contagens publicadas para
  este terceiro sistema separadamente dos dois MES.
- Confirmar no PC a execução da tarefa e comparar as contagens de origem e
  destino antes de declarar a ligação operacional.

A exportação atual contém cinco linhas com data de 2028 e outras datas antigas
atípicas. Estão preservadas; precisam de conferência e não devem ser corrigidas
ou descartadas automaticamente durante uma futura importação.

Reprodução da inspeção do código anunciado pelo PC:

```bash
git -C /home/luis/projects/ocr show 5f6ab6f:scripts/drive_pull.py
git -C /home/luis/projects/ocr show 5f6ab6f:backend/app/web/export.py
git -C /home/luis/projects/ocr show 5f6ab6f:backend/app/web/main.py
```

[Evidência agregada](planeamento-cpis-2026-09-20/diagnostico-ocr-original.json).
