# Correções após a auditoria de planeamento — 20/09/2026

Esta intervenção corrige problemas encontrados com dados reais. Não constitui
a conclusão da especificação completa de integração CPIS/planeamento/PDF/OCR.
Os ficheiros locais anteriores foram preservados. Não houve migração, alteração
de acumulados das macros ou escrita nas tabelas operacionais de produção.

## Comportamento corrigido

- A lista filtra as OFs e depois conserva todas as linhas das fontes para essas
  identidades. Uma cópia aberta deixa de esconder a outra cópia fechada/pronta.
- Várias OVs da mesma OF são preservadas e não são, por si só, um conflito.
- A área vem de linhas técnicas, peças PDF ou preparações existentes. A presença
  da OF numa cópia CPIS de Perfis não atribui a área Perfis.
- O filtro «Por fazer» considera o fecho declarado na macro e as operações
  adicionais. Ordens com conflitos, necessidades PDF ou preparações locais
  permanecem para conferência, mesmo com o plano importado fechado. Esta regra
  é conservadora: não prova a conclusão integral da OF.
- Corte e abocardar apresentam acumulados, saldos e registos OCR separados.
  A ausência de evidência ou de quantidade mantém o valor desconhecido. Zero
  congelado numa referência expandida continua zero.
- Referências expandidas usam apenas as quantidades dos filhos preservados na
  validação; o pai não entra novamente no total. Sem distribuição histórica,
  a associação fica incompleta.
- Sem ligação explícita ao snapshot atual, uma correspondência técnica exige
  referência, perfil e comprimento conhecidos e uma única candidata. São
  consultadas as identidades congeladas e as chaves históricas disponíveis.
- Uma operação de abocardamento encontrada no OCR, mas não indicada na macro,
  aparece separadamente com necessidade por confirmar.
- A conferência usa evidência calculada pelo servidor, vinculada à peça,
  geometria, operação e versão. Um pedido do browser não pode fornecer totais
  ou identificadores OCR arbitrários como prova. Uma alteração relevante
  invalida a decisão; mudar apenas o acumulado de abocardar não invalida a
  conferência de corte.
- Concluir uma preparação verifica a versão CPIS atual. Uma versão antiga em
  que a OF estava aberta não autoriza concluir depois do seu fecho.
- A validação da quantidade a planear usa o saldo da operação selecionada.
- A saída PDF, incluindo CSV e comparação XLSM, exige confirmação CPIS direta
  recente. A versão CPIS entra na assinatura da proposta. O ecrã explica o
  bloqueio e conserva a preparação.
- A importação Excel é apresentada como importação, sem ser confundida com a
  hora de consulta direta ao CPIS. Os OCRs mostram separadamente a validação
  e a data de produção.

## Casos reais consultados, sem alteração

| Caso | Resultado observado após a correção |
|---|---|
| OF264763 / CI5121A4030 | Macro/OCR de corte: 315/315; saldo corte: 0. Macro/OCR de abocardar: 298/298; saldo abocardar: 17. |
| OF265541 / CI1822A4001 | OCR: 1 corte e 1 abocardamento separados. A necessidade de abocardar não está indicada na macro e fica por conferir. |
| OF264760 | «Fechada» e «Em Produção» visíveis; não sai do filtro «Por fazer». |
| OF266198 | «Pronta» e «Em Produção» visíveis na lista e no detalhe; área Cantoneiras. |
| OF266229 | Sem linha de plano, área Perfis sustentada pela peça PDF. Preparação guardada e saída bloqueada sem CPIS direto. |

Estes valores pertencem às versões importadas
`mtg2_756950d5721977a8` e `mtg_da883132feefabc2`. Não provam o estado atual
da base CPIS. A concordância entre macro e OCR também não prova que cobrem os
mesmos eventos; os acumulados não são somados nem descontados automaticamente.

## Verificação

- Bateria completa com `RUN_PG_INTEGRATION=1 .venv/bin/pytest -q --tb=short`:
  **623 testes passaram**, incluindo PostgreSQL descartável.
- Depois do último ajuste relativo a operações OCR ausentes na macro:
  **11 testes de evidência passaram**, incluindo o novo caso adicional.
- JavaScript validado com `node --check`; módulos Python compilados; sem
  problemas de whitespace em `git diff --check`.
- Browser Chromium: pesquisa de OF, conflito de estados, evidência por
  operação, abertura da conferência com saldo 17, bloqueio PDF e vista 390 px.
  Sem erros JavaScript e sem deslocamento horizontal na vista estreita.
- Os testes de escrita usam bases PostgreSQL descartáveis, SQLite temporários
  e cópias XLSM. Nenhuma folha real foi validada para testar.

Evidência visual:

- [Corte e abocardar da mesma peça](planeamento-cpis-2026-09-20/correcao-peca-operacoes.png).
- [Lista e detalhe](planeamento-cpis-2026-09-20/correcao-operacoes-desktop.png).
- [Conflito de estados](planeamento-cpis-2026-09-20/correcao-conflito-desktop.png).
- [Dossiê e motivo do bloqueio](planeamento-cpis-2026-09-20/correcao-pdf-desktop.png).
- [Ecrã estreito](planeamento-cpis-2026-09-20/correcao-operacoes-mobile.png).

## Publicação e reversão

Atualizada a instância de consulta `kanban-planning.service`, porta 8113,
usada pelo link temporário trycloudflare. Não foi atualizada a instalação
Windows no PC da fábrica nesta intervenção nem reiniciado o MES operacional.

Para retirar esta versão de consulta, parar apenas
`systemctl --user stop kanban-planning.service`. As aplicações OCR e os dados
mantêm-se. Uma reposição de código deve usar uma cópia anterior conhecida,
preservando as alterações locais e todas as bases. Não usar `git reset` ou
`git clean`: há trabalho anterior ainda não registado no Git.

## Limites que permanecem

- O acesso direto CPIS a partir da fábrica continua sem validação real. O Excel
  contém a ligação ODBC, mas isso não cria uma rota utilizável neste servidor.
  O diagnóstico read-only do kit do PC está preparado e ainda não foi executado.
- O contexto técnico dos PDFs continua ligado à importação de Perfis. Nesta
  correção partilha o bloqueio de saída; a unificação de campos e proveniência
  com as preparações manuais permanece incompleta.
- Os códigos de operação de Cantoneiras não são deduzidos da máquina. As
  quantidades associadas à peça aparecem com operação por confirmar, sem
  conferência de corte/abocardar fabricada. Falta o fluxo específico para
  escolher e auditar essa associação.
- As conferências atuais requerem uma linha técnica identificada. A conferência
  de uma necessidade manual/PDF sem linha prévia exige o modelo comum ainda
  pendente. Dados insuficientes ficam por resolver.
- Catálogos, dimensões condicionais, importação Picking e proveniência campo a
  campo mantêm os problemas identificados na auditoria, fora destas correções.
- A saída operacional real não foi ensaiada: permanece bloqueada pela falta de
  confirmação CPIS. Os testes de exportação usam fontes de teste explícitas.
