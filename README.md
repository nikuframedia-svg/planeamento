# Planeamento de Perfis e Cantoneiras

Projeto independente em `/home/luis/projects/planeamento`. Contém a aplicação da porta **8113**, o worker de projeções/capacidades, os dossiês, testes, migrações e documentação. Não contém o servidor web dos kanbans.

**Transferência concluída e verificada em 24/09/2026:** [resultado, provas e reversão](docs/separacao-2026-09-24/resultado.md).

## Organização

- `app/planning*.py`: necessidades, registo, cálculos, associações e fontes.
- `app/raw/`: projeções, capacidades, consultas, exportações e worker.
- `app/dossiers/`: entrada PDF, revisão documental e histórico.
- `app/web/`: entrada `planning_app.py`, rotas, páginas, JavaScript e estilos.
- `sql/`: esquema e migrações; 010–017 conservadas como dependências das fontes/fixtures.
- `tests/` e `scripts/`: testes e auditores do planeamento, incluindo os adaptadores partilhados necessários para conferir os MES.
- `data/dossiers/`: documentos, SQLite e configuração privada; excluídos do Git.
- `docs/separacao-2026-09-24/`: inventário e provas da separação. Os relatórios anteriores preservam os caminhos e revisões da execução histórica.

## Execução

O projeto tem `.env` privado e ambiente `.venv` próprios. A migração conservou exatamente os pacotes instalados no serviço validado; não depende do ambiente Python do MES. Para uma instalação nova com acesso aos pacotes bloqueados: `uv sync --frozen --extra dev`, seguido da configuração de `.env` a partir de `.env.example`.

```sh
cd /home/luis/projects/planeamento
MES_PLANNING_NEEDS_ENABLED=1 MES_PLANNING_RAW_ENABLED=1 MES_RAW_WORKSPACE_ENABLED=1 \
  .venv/bin/python -m uvicorn app.web.planning_app:app --host 127.0.0.1 --port 8113 --env-file .env
.venv/bin/python -m app.raw.worker
```

No servidor, as definições em `deploy/` são instaladas como unidades de utilizador `kanban-planning.service` e `kanban-raw-worker.service`. O endereço público e a porta 8113 mantêm-se.

O PostgreSQL central continua a fornecer os dados MES, macros, CPIS e planeamento. Os ficheiros Excel do Drive continuam na pasta de fontes `DATARESEARCHMTG`. Separar o código não cria outra base nem duplica decisões ou produção.

## Compatibilidade com os MES

O MES existente ainda importa módulos e páginas do planeamento. Os caminhos exclusivos do planeamento no projeto antigo são ligações para esta pasta; o código passa a ter aqui a sua localização principal. Os módulos usados pelos dois projetos, como configuração e normalização das fontes, têm cópias independentes. Nenhum ficheiro de configuração ou serviço MES 8100/8101 precisa de ser alterado ou reiniciado.

Os caminhos documentais antigos também apontam para `data/dossiers/` desta pasta. A mudança conserva os mesmos ficheiros, inodes e base SQLite, incluindo os bloqueios usados pelos processos existentes.

## Git (desde 28/09/2026)

O código está em git, só localmente. Ficam fora do histórico:

- `.env`, `data/` e `.venv`;
- a evidência pesada de `docs/validacao-planeamento-integral/`, que continua no disco (ver `.gitignore`).

**Cuidado com os ficheiros partilhados com o MES.** Os JS/CSS de `app/web/static/` são ligações físicas com `kanban-mes-mtg2/app/web/static/`. Por isso:

- editar sempre no próprio ficheiro;
- não usar `git checkout`, `git restore` nem `git stash` sobre eles: esses comandos criam um ficheiro novo e cortam a ligação, e o MES ficaria com a versão antiga;
- o código novo do planeamento vai para `app/sector/`, que o MES não importa.

## Validação e reversão

Os testes de escrita usam PostgreSQL descartável. A verificação de leitura do destino público está em `tests/planning_final_public_browser.cjs`. A prova específica desta separação compara fontes, projeções, decisões, históricos, documentos e processos antes/depois. As provas antigas em `docs/validacao-planeamento-integral/` continuam a documentar a candidata de origem; a separação não altera o motor de cálculo.

A cópia de reversão e o inventário exato dos caminhos transferidos estão indicados em `docs/separacao-2026-09-24/migration.json`. Para reverter, parar apenas as duas unidades de planeamento, repor as definições anteriores e os caminhos do inventário, conservando os dossiês atuais. Não substituir PostgreSQL por um backup antigo nem apagar alterações feitas depois da mudança.
