# Instalar a importação unidirecional do OCR original

Este conector só lê a base SQLite original e publica no esquema `ocr_original` do
PostgreSQL central. Não envia planos, ordens, associações ou correções ao OCR original.
Não depende do Excel antigo nem do Drive. A aplicação OCR não precisa de ser alterada.

## Pré-condições

- No servidor, migração `021_original_ocr_import.sql` aplicada (já aplicada no ensaio).
- No PC, Python da aplicação MES com `psycopg` disponível.
- Ponte SSH existente ativa: PostgreSQL central em `127.0.0.1:15432` no PC.
- Identificação do caminho **efetivamente usado pelo processo original** para `app.db`.
  Não usar um backup antigo, nem deduzir o caminho a partir de um nome de pasta.

## Instalação

1. Extrair `ocr-original-importador.zip` em `C:\OCR-Suite`. O pacote contém apenas
   o módulo novo em `kanban-mes-mtg2\app\original_ocr.py` e os ficheiros do conector
   em `kit`. Não contém `.env`, credenciais, PDFs, SQLite ou dados de produção.
2. Na base central, definir uma palavra-passe própria para `ocr_original_importer`
   através da administração PostgreSQL. O papel só tem permissões no esquema da
   importação. Não reutilizar a conta CPIS ou alargar permissões sobre os MES.
3. Copiar `kit\original-ocr-import.env.example` para `kit\original-ocr-import.env`.
4. Preencher `ORIGINAL_OCR_SQLITE_PATH`, `ORIGINAL_OCR_PUBLISH_DSN` e gerar uma vez
   `ORIGINAL_OCR_INSTANCE_ID` com `[guid]::NewGuid().ToString()`. Conservar o UUID;
   uma reinstalação não deve criar uma segunda origem para a mesma base.
5. Executar a verificação local, sem publicação:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File C:\OCR-Suite\kit\start_original_ocr_import.ps1 -Check
   ```

6. Executar uma publicação única, depois de carregar estas variáveis no ambiente:

   ```powershell
   C:\OCR-Suite\kanban-mes-mtg2\.venv\Scripts\python.exe -m app.original_ocr
   ```

   Executar a partir de `C:\OCR-Suite\kanban-mes-mtg2`. Alternativamente, usar o script
   de arranque em modo normal e observar o primeiro ciclo no log antes de registar a tarefa.
7. Comparar contagens de folhas/linhas do relatório local e da interface central
   `/planeamento/ocr-original`. Registar os números efetivamente encontrados,
   sem usar as contagens de setembro como constantes.
8. Repetir a leitura e confirmar `unchanged: true`, sem duplicar linhas.
9. Registar a execução contínua:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File C:\OCR-Suite\kit\register_original_ocr_import.ps1
   ```

O intervalo inicial é 300 segundos; a tarefa impede instâncias simultâneas e a publicação
usa também exclusão mútua no PostgreSQL. O log fica em `kit\logs\original-ocr-import.log`.
Uma falha conserva a versão anterior. Quinze minutos sem confirmação ficam visíveis na
interface. A leitura utiliza transação SQLite consistente e modo só de leitura, incluindo
bases em WAL; não copiar diretamente um `app.db` vivo ignorando o WAL.

Uma regressão de revisões ou uma população validada subitamente vazia bloqueia a publicação.
Conferir a origem/restauro antes de alterar configuração. A ausência numa leitura parcial
não remove folhas do estado central; só uma publicação completa pode atualizar a população.

## Evidência ainda necessária

Os scripts PowerShell foram preparados neste servidor Linux; não foram executados em Windows.
O novo conector ainda não tem uma publicação real a partir do PC. A conclusão da instalação
exige guardar a saída de `-Check`, o primeiro sucesso, a repetição sem duplicação e a contagem
central correspondente. Não é necessário validar uma folha fictícia para fazer este ensaio.

Para parar, desativar a tarefa no Agendador do Windows. As versões já publicadas permanecem
para consulta e auditoria. Não existe sincronização inversa a desativar.
