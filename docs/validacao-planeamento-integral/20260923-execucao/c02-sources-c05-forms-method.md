# Seleção de produção, abertura do formulário e perda de validação OCR

Ambiente: cópia `planning_integral`, porta 18113. Gerações de planeamento 4323/4324; 83 156 peças. As fontes e as 27 alterações tracked anteriores foram preservadas. Os estáticos são partilhados com o Planeamento 8113; apenas o servidor isolado foi reiniciado. Publicação integral ainda pendente.

## Correções funcionais

- Cantoneiras: mudar a operação principal não transfere o acumulado `Maq.` da operação original para a nova. O formulário mostra produção/saldo desconhecidos e explica a operação a que o Excel pertence; regressa ao acumulado original ao selecionar novamente essa operação.
- RAW → «Abrir formulário»: a lista de referências é carregada antes de resolver a linha pedida, sem abrir um diálogo intermédio. O erro de linha inexistente foi reproduzido antes da correção; abertura e pré-visualização passaram nas duas áreas.
- Um registo de produção removido/desvalidado deixa de interromper a consulta de evidência e a reconstrução. A decisão humana permanece no histórico; a produção e o saldo ficam desconhecidos, com aviso. A publicação incremental coincide com a reconstrução completa no teste descartável.

## Verificação

- `c02-source-policy-population.json`: 1 778 925 verificações independentes de seleção, saldos, excesso, percentagens e preservação das entradas; zero diferenças. Esperados derivados de evidência de operação e células originais, sem chamar o seletor da aplicação. C01/C02 continuam responsáveis pela ingestão real e pela matriz completa de associação.
- `c02-source-policy-central.json`: reconciliação independente dos 2 351 registos centrais e 1 389 totais OCR selecionados.
- `c02-source-policy-details-final.json` e `c02-source-policy-semantic.json`: explicações e semântica das gerações atuais, sem diferenças. Um erro de variável na gravação do relatório foi corrigido; tentativa preservada em `c02-source-policy-details-output-error.*`.
- `c02-source-policy-regression.log`: 140 testes passaram. Browser: oito estados (OCR/Excel/zero local/desconhecido, nas duas áreas) e troca 112→119→112; zero erros JS. A primeira tentativa de abrir peças históricas no âmbito ativo foi corrigida no produtor de prova; tentativas conservadas.
- `c11-current-regression.log`: 552 passaram e um browser opt-in foi omitido pelo comando normal. Esse teste foi executado separadamente com `RUN_PLANNING_BROWSER=1`: `c11-common-editor-browser.log`, um passou. Atualizadas apenas expectativas antigas sobre a pré-visualização e campos de data/picking agora editáveis, conforme o plano. O teste verifica criação, gravação, PDF, identidade comum, decisões humanas, reabertura e adaptações de ecrã.
- Correção de desvalidação: 39 regressões existentes passaram em `c02-removed-evidence-regression.log`; o novo caso falhou apenas por procurar «validado» no aviso «produção validada». Corrigida a asserção textual, `c02-removed-evidence-final.log` passou. `c02-removed-evidence-projection.log` passou e compara publicação incremental e completa, sem converter ausência em zero.
- `c08-pages-browser.json`: 14 páginas/tamanhos, 2 170 elementos visíveis com 11 pt, declaração Calibri e sem transbordo horizontal do documento. **Calibri efetiva não confirmada: permanece Liberation Sans.** As sete rotas cobrem início, formulário das duas áreas, dossiês, capacidades, disponibilidade e OCR original; a RAW já tem prova própria.

Comandos: `PYTHONPATH=. .venv/bin/python scripts/audit_planning_production_sources.py --output c02-source-policy-population`; `RUN_PG_INTEGRATION=1 .venv/bin/python -m pytest -q --tb=short tests/test_planning*.py tests/test_raw_workspace.py tests/test_original_ocr.py tests/test_capacity_revision.py`; browsers com `PLANNING_CHECK_BASE=http://127.0.0.1:18113 PLANNING_TEST_ISOLATED=1 node tests/<ficheiro>.cjs`.

As 43 regras têm agora auditoria independente específica no âmbito documentado. Isso não aprova automaticamente C04, a ingestão original, as decisões entre origens, o recálculo transversal ou a publicação. C01/C02, fecho das matrizes C04/C05/C10, Calibri, C11/C12 permanecem pendentes. Não somar suites sobrepostas.
