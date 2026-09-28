# RAW completa — entrega de software e validação, 22/09/2026

A nova interface está publicada **no serviço de ensaio** `kanban-planning.service`, porta 8113, em `/planeamento/raw`. A publicação adiciona o trabalhador `kanban-raw-worker.service`; não substitui os serviços dos dois MES. Os conectores no PC ainda precisam da validação real descrita no final deste documento.

## Funcionalidades implementadas

- Perfis e Cantoneiras, contratos próprios, paginação de 25/50/100/250/500 linhas e consultas no PostgreSQL. OF, OV e Referência fixas, tabela compacta, datas `dd-mm-aaaa`, decimais portugueses, deslocamento dentro da tabela. Características ocultas na vista inicial.
- Pesquisa múltipla, filtros e opções por coluna sobre todo o conjunto, ordenação por várias colunas, escolha individual de colunas, larguras, densidade e vistas com versões, duplicação e arquivo.
- Registo manual/PDF na mesma transação de identidade, ligação à macro e gravação. Candidatas ambíguas não deixam fichas aparentes guardadas; campos humanos são preservados. A confirmação apresenta **Ver na RAW**. O trabalhador publica as alterações sem exportar/reimportar Excel.
- Edição local de células e colagem de lotes com comparação, validação integral, revisão e idempotência. Falha de uma linha reverte o lote. As fontes oficiais, produção e cálculos não são campos de edição livre.
- Cálculos tipados, evidência por operação, produção dos dois MES já existentes, referências expandidas sem contar pai e filhos simultaneamente. Distribuição humana da produção, substituição/revogação de associações e conferência de saldo sem linha de macro.
- Capacidade por recurso físico/semana: equivalências explícitas de máquinas, calendários, cópia de semanas com comparação, taxas com vigência e âmbito, métodos próprios por área, rascunhos separados, sobrecarga e trabalho por calendarizar. Fontes históricas são sugestões a confirmar. Horas declaradas contam uma vez por folha e mostram cobertura.
- Fórmulas seguras com pré-visualização, verificação de unidades/ciclos, formatação condicional, resumos, indicadores, barras e linhas, consulta das linhas de suporte, CSV/XLSX filtrados.
- Chat persistente, propostas estruturadas pelo modelo, revisão da conta e confirmação humana. Análises automáticas, suspensão/reativação, arquivo, revisões e resultados históricos. Exportação JSON e HTML autónomo com gráficos e dados de suporte.
- Trabalhador independente: consulta de fontes a cada 60 segundos, sinalização de alterações locais, até dois cálculos simultâneos, recuperação de trabalhos interrompidos, último resultado preservado em caso de erro. O recálculo não pede uma nova fórmula ao LLM.
- Estado de cada consulta com tentativa, confirmação e erro. CPIS continua identificado como importado, sem confirmação direta. Conclusão operacional e saída da macro conservam o bloqueio de atualização CPIS.

## Organização técnica

| Componente | Implementação |
|---|---|
| Contratos e consulta | `app/raw/contracts.py`, `query.py`, `projection.py` |
| Identidade/gravação | `app/raw/edits.py` e serviços comuns `planning_needs`, `planning_associations` |
| Cálculos/capacidade | `app/raw/calculations.py`, `capacity.py` |
| Fórmulas/análises | `app/raw/expressions.py`, `analysis.py` |
| Vistas e auditoria | `app/raw/objects.py` |
| Exportações | `app/raw/exports.py` |
| Trabalhador | `app/raw/worker.py` |
| HTTP/interface | `app/web/raw_workspace_routes.py`, `raw_workspace.html`, ficheiros `raw_*.js/css` |

A migração **024** acrescenta gerações de consulta, conteúdos por hash, intervalos de validade, objetos/versionamento, conversas, trabalhos/resultados e estado do trabalhador. Conteúdo igual é reutilizado; não se copia toda a população em cada consulta HTTP. A navegação aceita versões durante sete dias; resultados históricos conservam os conteúdos de suporte. Não há limpeza destrutiva de versões nesta entrega.

A migração **025** cria a conta `cpis_connector`, sem palavra-passe predefinida, com permissões de publicação apenas nas tabelas `cpis_mtg`. Foi verificado que não pode inserir produção nem alterar fichas. Não substitui a conta de leitura no CPIS.

Os pedidos de escrita conservam revisão, identificador idempotente e autoria definida no servidor. A interface continua sem nome/login obrigatório. As decisões documentais utilizam a fila transacional existente para o SQLite.

## Evidência de validação

Resultados separados por comando; os grupos sobrepõem-se e não devem ser somados:

| Ensaio | Evidência |
|---|---|
| Regressões de fichas, catálogos, produção, RAW, escritor XLSM e importador original | `final-tests.txt`: 86 testes passaram |
| RAW, identidade, fontes, capacidade partilhada, fórmulas e trabalhador | `workspace-release-tests.txt`: 22 testes passaram |
| Associação conservadora de referências e operações | `reference-association-test.txt`: 12 testes passaram |
| Pré-visualização, execução e histórico analítico | `analysis-final-tests.txt`: 3 testes passaram |
| Formulário manual/PDF no browser | `form-browser-tests.txt` e `cantoneiras-browser-test.txt`: passaram |
| RAW e registo legado | `release-tests.txt`: 28 passaram; 13 testes opcionais de ambiente externo não executados |
| Browser com população real, modelo real, confirmação e exportação | `real-browser-tests.txt` e `browser-real-analysis.json` |
| Browser público, ambas as áreas, fontes, 390 px e 200% | `published-browser-tests.txt` |
| Exportação com entradas relevantes, resultados históricos e HTML autónomo | `compact-exports-test.txt`: 3 passaram; `compact-export-validation.json` e `offline-report-test.txt` |
| Reversão por configuração, com migrações presentes | `rollback-test.txt` |
| Pacote isolado dos conectores | `connector-package-tests.txt`; execução Windows pendente |

Foram usados PostgreSQL descartável, uma cópia integral separada `raw_workspace_test_20260922` e arquivo SQLite temporário. As gravações de ensaio, parâmetros fictícios e confirmações do browser foram feitos nesses ambientes. Não foram inseridos factos de produção fictícios na base operacional.

A população de consulta verificada contém **7.391 linhas de Perfis e 75.303 de Cantoneiras**. No ensaio da geração já preparada, páginas/pesquisas/filtros ficaram abaixo de um segundo; ver `full-population.json`. Preparar inicialmente os conteúdos é uma operação de segundo plano mais demorada. Estes números são diagnóstico desta versão, não limites nem constantes do código.

O exemplo real **OF264763 / CI5121A4030** conserva **315 cortadas e 298 abocardadas** na macro e no OCR, em colunas distintas. Ver `production-315-298.json` e `published-production.png`.

O transporte real Bedrock Mantle foi exercitado com `xai.grok-4.6`. Foram corrigidos e testados o arredondamento de um argumento e a equivalência de literais numéricos na confirmação do browser (`100.0`/`100`). Falhas de proposta não modificam o plano. O modelo propõe; a execução dos cálculos é feita pelo servidor.

O relatório autónomo inclui as entradas utilizadas, identificadores, versões e fórmulas de suporte; não transporta todas as células originais do Excel alheias à análise. Os resultados permanecem exatamente iguais aos da execução guardada. A exportação CSV/XLSX neutraliza texto interpretável como fórmula, incluindo nomes de colunas, preservando os números negativos como números.

## Capturas

- `published-perfis.png`, `published-cantoneiras.png`: tabela publicada.
- `columns.png`: seleção de colunas dentro dos grupos.
- `published-production.png`: caso real de corte/abocardar.
- `capacity.png`, `capacity-sources.png`: matriz e sugestões históricas.
- `formula.png`, `chat.png`, `analysis-preview.png`, `report.png`: fórmula e percurso analítico no ensaio.
- `published-sources.png`: estado real das fontes.
- `published-mobile.png`, `published-zoom200.png`: adaptação do ecrã.
- `cantoneiras-manual.png`, `cantoneiras-pdf.png`: os dois percursos de Cantoneiras, na base descartável.
- `exemplo-relatorio.html`: relatório autónomo real do ensaio, com os resultados e gráficos guardados.
- Os percursos do formulário encontram-se também nas capturas `../planeamento-campos-2026-09-21/manual-desktop.png` e `pdf-desktop.png`, renovadas pelo teste isolado.

## O que depende da fábrica

**Não foi demonstrada uma leitura SQL direta do CPIS a partir do PC.** A tentativa a `10.200.10.30:5432` a partir deste servidor terminou em timeout. A ponte permite consultar a saúde web do OCR original, mas não disponibiliza uma sessão remota para instalar processos. Não se utilizou o Excel do Drive como se fosse uma consulta CPIS atual.

**Não existe ainda uma instância do importador original confirmada no PostgreSQL central.** A interface apresenta essa ausência explicitamente. `connectors-status.json` contém o diagnóstico, distinto do estado dos dois MES que já publicam produção validada.

Calendários atuais, equivalências físicas e taxas de máquinas precisam de confirmação humana. Os dados históricos podem ser consultados/carregados como sugestões, mas não foram declarados válidos para as semanas atuais. O fator Thomas ×3 não foi ativado. Ausência de parâmetros produz “Por confirmar”.

Estas dependências impedem encerrar a aceitação integral da ligação à fábrica. Não impedem consultar, editar rascunhos, preparar análises ou configurar cenários. Não permitem contornar os bloqueios operacionais CPIS.

## Instalar os conectores no PC

O pacote **`conectores-pc.zip`** é independente: não substitui o código das aplicações OCR. Contém os dois leitores, scripts e exemplos de configuração. Não contém credenciais, SQLite, PDFs ou dados de produção. O gerador é `scripts/build_raw_connector_bundle.py`; os hashes estão em `conectores-manifest.json`.

1. Extrair o pacote numa pasta própria, por exemplo `C:\OCR-Suite\RawConnectors`.
2. Identificar o Python existente com `psycopg` e confirmar a SQLite efetivamente usada pelo processo original. O caminho não deve ser escolhido apenas pelo nome de uma pasta ou por ser um backup recente. O OCR original analisado usa `data\app.db` a partir da raiz da sua instalação; confirmar a instalação ativa no PC.
3. Copiar `original.env.example` para `original.env`. Definir caminho, uma identidade de instância permanente e DSN de publicação com a conta `ocr_original_importer`. Gerar o UUID uma única vez. No servidor, a palavra-passe dessa conta é provisionada separadamente, sem reutilizar credenciais CPIS.
4. Verificar e publicar duas vezes, a partir da pasta extraída, substituindo o caminho do Python pelo que existir no PC:

```powershell
.\start.ps1 -Source original -Python 'C:\OCR-Suite\kanban-mes-mtg2\.venv\Scripts\python.exe' -Check
.\start.ps1 -Source original -Python 'C:\OCR-Suite\kanban-mes-mtg2\.venv\Scripts\python.exe'
.\start.ps1 -Source original -Python 'C:\OCR-Suite\kanban-mes-mtg2\.venv\Scripts\python.exe'
```

Comparar contagens, hashes, datas e revisões da origem com `/planeamento/ocr-original`. A segunda leitura igual deve renovar a confirmação sem duplicar eventos. SQLite é aberta em leitura consistente, incluindo WAL, sem invocar migrações ou gravações da aplicação original.

5. Para CPIS, executar no utilizador/PC que usa o Excel:

```powershell
.\diagnose_cpis_readonly.ps1 -Workbook 'CAMINHO_REAL\Met2_Plan_Perfis.xlsm'
```

O diagnóstico usa a configuração ODBC da macro, transação de leitura e a vista integral. Não imprime a palavra-passe, não abre Excel/VBA e não publica resultados operacionais. Depois de demonstrado o acesso, configurar `cpis.env` com **duas ligações separadas**: `CPIS_DSN` para leitura da vista e `CPIS_PUBLISH_DSN` para a conta central `cpis_connector`. A ponte existente expõe o PostgreSQL central no PC em `127.0.0.1:15432`; deve estar ativa. Provisionar a palavra-passe central separadamente, por exemplo através de `\password cpis_connector` na administração PostgreSQL.

```powershell
.\start.ps1 -Source cpis -Python 'C:\OCR-Suite\kanban-mes-mtg2\.venv\Scripts\python.exe'
```

Comparar população integral, estados, múltiplas OVs e confirmação na aplicação. Só depois registar execução contínua:

```powershell
.\register.ps1 -Source original -Python 'C:\OCR-Suite\kanban-mes-mtg2\.venv\Scripts\python.exe'
.\register.ps1 -Source cpis -Python 'C:\OCR-Suite\kanban-mes-mtg2\.venv\Scripts\python.exe'
```

As tarefas executam a cada 300 segundos dentro do processo, impedem instâncias simultâneas e conservam logs na pasta `logs`. Desativar uma eventual tarefa anterior do mesmo conector antes de ativar esta instalação. O original só publica para a base central; não recebe planos ou correções.

**PowerShell e as ligações reais no PC ainda não foram executados nesta entrega.** Guardar os relatórios de diagnóstico, primeira publicação, repetição sem duplicação e comparação com a interface antes de considerar estes pontos encerrados.

## Publicação e reversão

Configuração publicada:

- `MES_PLANNING_RAW_ENABLED=1`, `MES_PLANNING_NEEDS_ENABLED=1` já existentes.
- `MES_RAW_WORKSPACE_ENABLED=1` no drop-in `raw-workspace.conf` do serviço de ensaio.
- Unidade do trabalhador: `deploy/kanban-raw-worker.service`.
- Migrações 024 e 025 aplicadas com transação e `ON_ERROR_STOP`.
- Backup anterior: caminho registado em `../raw-completa-backup.txt`, incluindo dump PostgreSQL e ficheiros existentes.

Para voltar à interface RAW anterior, mantendo todos os dados:

```bash
systemctl --user disable --now kanban-raw-worker.service
```

Alterar **apenas** `Environment=MES_RAW_WORKSPACE_ENABLED=0` no ficheiro `~/.config/systemd/user/kanban-planning.service.d/raw-workspace.conf`, depois:

```bash
systemctl --user daemon-reload
systemctl --user restart kanban-planning.service
```

Não remover tabelas, fichas, vistas, calendários, associações ou análises. A interface anterior abre com a migração aditiva presente. Para reativar, repor o valor `1`, arrancar o trabalhador e reiniciar apenas o serviço de ensaio. Os conectores do PC são desativados nas respetivas tarefas agendadas, sem apagar o histórico central.
