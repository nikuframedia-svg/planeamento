# Planeamento CPIS, preparação e produção OCR

> Revisão posterior, 20/09/2026: a
> [auditoria aprofundada](analise-aprofundada-cpis-planeamento-2026-09-20.md)
> encontrou falhas funcionais com dados reais. Foram entretanto corrigidas a
> mistura de operações OCR, a ocultação de estados CPIS contraditórios, a área
> inferida da cópia CPIS e a ausência de bloqueio de confirmação direta na saída
> PDF. Os detalhes, testes e limites estão em
> [Correções após a auditoria](correcoes-planeamento-2026-09-20.md).
> A entrega completa continua pendente: a leitura real CPIS no PC, os catálogos,
> a integração comum dos dados PDF e a resolução humana de associações precisam
> do trabalho restante identificado na auditoria.

## Estado da entrega em 20/09/2026

A página `/planeamento` usa a OF como entrada principal. A lista consolidada
mostra OF/OV, estado administrativo CPIS, área, linhas existentes, PDF,
preparação e execução. O circuito anterior de documentos continua em
`/planeamento/dossies` e o formulário comum em `/planeamento/manual`.

A base central recebeu a migração aditiva `sql/019_cpis_planning_hub.sql`.
Foram reimportadas, sem alterar os ficheiros XLSM, as versões:

- Perfis: `mtg2_756950d5721977a8`, 7.199 linhas de plano e 12.362 linhas CPIS.
- Cantoneiras: `mtg_da883132feefabc2`, 75.192 linhas de plano e 70.129 linhas CPIS.

Os catálogos visíveis na API contêm 10 máquinas e 28 equipas de Perfis; 12
máquinas, 26 equipas e 13 operações de Cantoneiras. As listas continuam
independentes, mesmo quando os valores ocupam linhas diferentes na folha
`Dados`.

A leitura real do CPIS foi tentada deste servidor em 20/09/2026. A ligação a
`10.200.10.30:5432` terminou indisponível e a falha ficou registada em
`cpis_mtg.sync_attempts`. Por isso, o estado atual é deliberadamente **“CPIS
importado da macro — sem confirmação direta”**. É possível consultar e guardar
rascunhos; concluir uma preparação ou gerar uma nova cópia operacional fica
bloqueado.

## Componentes

- `app/cpis_sync.py`: consulta read-only, validação e publicação atómica.
- `app/planning_hub.py`: lista consolidada, detalhe, produção e conferências.
- `app/planning.py`: catálogos, contrato de campos e fichas auditadas.
- `app/planning_output.py`: proposta e cópia XLSM de fichas manuais de Perfis.
- `app/dossiers/*`: circuito PDF existente, conservado e partilhando a mesma
  origem e o mesmo escritor XLSM.
- `sql/019_cpis_planning_hub.sql`: versões CPIS, tentativas, proveniência,
  conferências e propostas de saída.

## Ativação no PC da fábrica

1. Atualizar a aplicação e aplicar `sql/019_cpis_planning_hub.sql` na base
   central.
2. Criar no CPIS um utilizador com acesso apenas de leitura à vista
   `public.ordensfabrico_listagem_excel_vw`.
3. Acrescentar ao `.env` de `kanban-mes-mtg2`:

   ```ini
   CPIS_DSN=host=10.200.10.30 port=5432 dbname=cpis user=UTILIZADOR_SO_LEITURA password=SEGREDO sslmode=prefer
   CPIS_SYNC_INTERVAL_SECONDS=300
   CPIS_FRESH_SECONDS=900
   MES_DISPLAY_TIMEZONE=Europe/Lisbon
   ```

4. No kit do PC, executar `register_cpis_sync.ps1`. O script usa a ponte para
   o PostgreSQL central, mas mantém a credencial CPIS separada.
5. Confirmar no log `data/_logs/cpis-sync.log` um resultado `ok` e comparar a
   contagem publicada com a consulta local.
6. Confirmar visualmente em `/planeamento` a indicação **CPIS direto**, hora da
   confirmação e possibilidade de concluir a preparação.

Não ativar operacionalmente com base apenas num teste simulado. A primeira
leitura no PC é uma condição de aceitação ainda pendente.

## Comportamento de segurança dos dados

- Uma sincronização falhada conserva a última versão completa.
- Uma versão é publicada numa única transação; contagens divergentes anulam a
  publicação.
- A integração CPIS não escreve na origem.
- Fichas e conferências não escrevem produção OCR nem incrementam acumulados.
- Ausência de OCR permanece “desconhecida”, sem ser convertida em zero.
- Referências expandidas usam os filhos congelados e não somam novamente o pai.
- Associações técnicas ambíguas ficam visíveis para decisão humana.
- A cópia XLSM é vinculada às revisões das fichas, versão CPIS e hash da macro;
  qualquer alteração exige nova comparação.

## Verificação executada

- 18 testes de registo/CPIS/PostgreSQL descartável, incluindo publicação sem
  duplicação, OF sem plano, rascunho manual, conferência idempotente e saída
  XLSM manual.
- 124 testes dos dossiês, extração e escritor XLSM.
- Regressão completa da aplicação: 590 testes passaram e 13 integrações
  opcionais ficaram ignoradas por configuração.
- Importadores: 18/18 controlos de Perfis e 13/13 de Cantoneiras.
- Ensaio browser desktop e 390 px, sem erros de consola, incluindo a OF266229
  e o bloqueio de conclusão sem CPIS direto.

Evidência visual:

- [Lista e detalhe da OF](planeamento-cpis-2026-09-20/percurso-of-desktop.png)
- [Preparação manual](planeamento-cpis-2026-09-20/percurso-preparacao-desktop.png)
- [Lista em ecrã estreito](planeamento-cpis-2026-09-20/lista-of-mobile.png)

## Reversão

1. No PC, desativar a tarefa `OCR Planeamento CPIS Sync`.
2. Repor a versão anterior da aplicação e reiniciar a tarefa web de Perfis.
3. Manter as tabelas novas: são aditivas e a versão anterior não as consulta.
   Isto conserva fichas, conferências e auditoria para uma reativação.
4. Se for necessário recuperar a importação anterior, reexecutar o importador
   com a cópia XLSM arquivada. O importador publica por transação.

Não apagar `cpis_mtg`, `planning_mtg`, os SQLite de dossiês ou as cópias XLSM
como parte da reversão.

## Limitações conhecidas

- A leitura CPIS real ainda precisa de validação no PC da fábrica.
- A exportação XLSM manual é apenas de Perfis; Cantoneiras continua com lista,
  formulário, persistência, OCR e conferência.
- Não existe calendarização automática, otimização de máquinas, gestão de
  stock ou atualização automática dos acumulados de produção.
- A informação CPIS importada pode conter divergências entre as duas macros;
  esses campos aparecem em conflito e não são resolvidos escolhendo uma cópia.

  **Substituído a 06/10/2026 (decisão do Luís).** Quando as duas cópias CPIS
  importadas discordam, manda a cópia mais recente, para todos os campos
  (estado, fim previsto da Produção, data de entrega, responsável, descrição,
  cliente…). «Mais recente» é a cópia cujo Excel foi carregado mais tarde
  (`audit_mtg.snapshots.loaded_at`); em empate, a linha com maior data de
  registo. Se a cópia recente não tiver um campo preenchido, fica o valor da
  outra. O estado mostra-se tal como vem (Em Aberto, Em Produção, Pronta,
  Fechada…), sem aviso de conflito. Também deixa de bastar uma cópia dizer
  «Fechada» (regra C06 de 23/09): vale o estado da cópia mais recente.
  Código: `cpis_copies.latest_first`, `planning_hub._order_summary`
  e `sector/board.not_in_plans`. O CPIS direto (`cpis_mtg`), se vier a existir,
  mantém a regra antiga.
