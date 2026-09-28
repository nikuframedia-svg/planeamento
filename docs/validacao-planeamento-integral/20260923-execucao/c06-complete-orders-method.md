# C06 — OFs sem CPIS, peças locais e identidades associadas

## Resultado e âmbito

A lista administrativa de Planeamento passa a incluir as peças importadas sem OF no CPIS, as peças exclusivamente locais e uma linha com OF inválida. A contagem usa as identidades de peça, incluindo associações de várias linhas de origem à mesma necessidade. Fechar qualquer origem associada fecha essa identidade; não fecha outra peça exclusivamente local da mesma OF. Não foram alteradas as regras de autorização da conclusão/saída operacional.

`planning_order_population.read` resolve as associações contra a importação atual pela mesma resolução usada na RAW. As origens sem associação única continuam separadas. Os registos locais acrescentam a peça uma vez por área, independentemente do número de operações. `summarize` aplica a regra de fecho comum, com todas as cópias CPIS, antes de contar e paginar. O seletor de linhas propaga a classificação da identidade associada a cada origem física.

As fontes macro/locais complementam o contexto administrativo apenas quando não existe contexto CPIS. Não se atribui um estado CPIS a essas OFs. A OF importada `26499` é consultável como `OF26499`, preservando os valores e IDs de origem. A linha `macro:mtg_397c8ea5e42480c1:plan:51449` tem `P` na origem: aparece como «OF por identificar», com referência CWA223E e ligação à RAW, sem criar OF fictícia nem oferecer seleção administrativa inválida.

O seletor «Procurar peça desta OF» usa necessidades/linhas ativas da área selecionada. Uma peça ligada à macro aparece uma vez como necessidade; não volta a aparecer pelas suas origens. Antes de abrir uma origem, o seletor confirma que continua ativa. Fichas e fontes históricas permanecem acessíveis pelos seus IDs.

## Provas

- `c06-complete-orders-regression.log`: 70 testes passaram em 78,03 s, sem falhas ou ignorados. Inclui consultas antigas, registos, necessidades, RAW, OFs sem CPIS, identidade inválida, associação de origens, contagens e preservação.
- `c06-complete-orders-transitions.log`: 12 testes passaram em 14,65 s. A sequência de fecho CPIS, fecho macro e reabertura foi ampliada para Perfis e Cantoneiras, com novas importações, acesso à geração anterior e rejeição da seleção em lote ativa de peças fechadas. Estes testes sobrepõem-se parcialmente à regressão anterior; os totais não devem ser somados.
- `c06-complete-orders-audit.json`: comparação de todas as **83 156 identidades** com as gerações imutáveis **4259/4260**, anteriores à alteração. Sem diferenças de chave, OF, área, classificação ou contagem. **18 981 ativas + 64 175 históricas = 83 156**. Compara ainda todos os agregados por OF/área nos três âmbitos, incluindo a identidade sem OF válida. Fontes e dez necessidades preservadas por hash.
- `c06-complete-orders-browser.json`: abriu as OFs locais das duas áreas, confirmou as duas peças/OF e os dois candidatos sem duplicação no formulário; abriu OF26499 sem inventar estado CPIS e chegou à linha CWA223E através da ligação RAW. Zero erros JavaScript. Os três POST observados são duas pré-visualizações e uma consulta RAW, todos de leitura; nenhum pedido de gravação.

## Ensaios e correções conservados

O primeiro ensaio tentou alterar uma fonte usando o utilizador de aplicação da base descartável; passou a usar o administrador dessa fixture. O mesmo ensaio identificou uma regressão real: a normalização eliminava identificadores CPIS curtos. A lista voltou a preservar esses registos administrativos originais.

O ensaio seguinte alterava a origem mantendo o mesmo identificador/hash de importação, pelo que a projeção publicada corretamente conservava a versão anterior. O teste passou a criar uma nova importação imutável, com novas chaves de origem, e confirma a resolução das associações e a preservação da origem fechada anterior (`c06-complete-orders-reopening.log`).

`c06-complete-orders-audit-missing-of.json/log` conserva a falha real de uma identidade omitida pelo hub: a linha com OF «P». A prova final inclui essa identidade e os seus agregados.

## Pendências

A lacuna das 36 OFs/3 694 linhas e das peças locais identificada na etapa anterior foi tratada. C06 permanece em curso até terminar a revisão dos consumidores PDF/dossiês: `app/dossiers/cpis.py::read_context` ainda consulta apenas a cópia CPIS de Perfis e usa a ausência em OPEN_STATES para emitir `of_closed`. É necessário distinguir o estado de planeamento das condições de exportação/conclusão, sem enfraquecer estas últimas. A listagem antiga «Registos guardados» é um registo histórico, não uma fila ativa.

C11 e C12 permanecem pendentes. As bases de teste são isoladas; os estáticos continuam partilhados com 8113. Nenhum serviço operacional ou kanban foi reiniciado e não houve migrações operacionais.
