# C07 — Painel Colunas completo no ambiente isolado

Revisão `c8276b95df312ed485d90177208fa44ba7db7b16a31255f1f53b13eec24be23e`,
111 ficheiros conferidos. Base `planning_integral`, servidor `127.0.0.1:18113`,
gerações Perfis 3559 e Cantoneiras 3560. C07.1–C07.4 aprovados neste ambiente;
R03/R04 continuam dependentes da disponibilização e verificação C12.

## Correção

Ao redimensionar uma coluna com as setas do teclado, `render()` substituía o
cabeçalho e perdia o foco. `raw_workspace.js` identifica agora o separador pela
coluna e devolve-lhe o foco sem deslocar a grelha. A falha foi reproduzida em
`c07-complete-pointer-trial.json`: depois de aumentar a largura de OV, o elemento
focado deixava de ser o separador. O mesmo requisito passou após a correção.

Não houve alteração do motor de cálculo, migração, reconstrução das gerações ou
reinício operacional. A auditoria C04 das 23 regras mantém-se válida; esta etapa
não aprovou as outras vinte regras nem a entrega integral.

## Critérios demonstrados

| Critério | Prova |
|---|---|
| C07.1 | 80 movimentos efetivos nas duas áreas: dez em cada sentido, com e sem pesquisa. Comparação da ordem antes/depois com o destino esperado; grupo aberto, foco no mesmo controlo, URL e scroll não nulo preservados. |
| C07.2 | Quatro arrastos nativos, com `isTrusted=true` e origem OF registada: entre grupos e dentro do grupo de destino, primeira e última posições. Todas as colunas visíveis e os cabeçalhos na ordem esperada. Alternativa por teclado/setas testada. |
| C07.3 | 65 campos Perfis e 72 Cantoneiras acessíveis, sem perdas nem duplicações. OF, OV e Referência desafixadas; fixação padrão recuperada na reposição. Visibilidade de Observações alterada e persistida. |
| C07.4 | Larguras alteradas pelo rato (+37px) e teclado (+10px), com foco conservado. Visibilidade, ordem, grupos, fixação e larguras recuperados após recarga e num novo contexto de browser através de vista guardada. Duas vistas antigas realmente armazenadas sem o novo formato foram carregadas. Reposição persistente e troca de áreas passaram. SQL confirma definições, versões e preservação dos dados de negócio. |

Larguras de OV: Perfis 120 → 157 → 167px; Cantoneiras 110 → 147 → 157px.
Zero erros JavaScript. As capturas finais mostram as grelhas com a disposição
guardada; a de Cantoneiras foi também inspecionada visualmente.

## Artefactos e reprodução

```bash
# Executar uma vez: cria duas vistas antigas somente na cópia isolada.
PYTHONPATH=. .venv/bin/python scripts/setup_planning_columns_trial.py
PLANNING_CHECK_BASE=http://127.0.0.1:18113 PLANNING_TEST_ISOLATED=1 PLANNING_CHECK_PREFIX=c07-complete-focus-fixed node tests/planning_columns_complete_browser.cjs
PYTHONPATH=. .venv/bin/python scripts/audit_planning_columns_trial.py
node --check app/web/static/raw_workspace.js
node --check tests/planning_columns_complete_browser.cjs
```

O preparador recusa sobrescrever a fixture existente; os IDs ficam em
`c07-complete-fixture.json`. Para repetir o browser, escolher outro prefixo para
conservar as provas anteriores. Cada execução bem-sucedida cria duas novas vistas
apenas na base isolada. Não usar o serviço 8113 para estes ensaios.

- `c07-complete-focus-fixed.json` e `.log`: percurso final aprovado.
- `c07-complete-focus-fixed-perfis.png` e `-cantoneiras.png`: grelhas finais.
- `c07-complete-persistence.json`: conferência SQL em leitura, fingerprints das
  fontes/necessidades, gerações, processos e hash do JavaScript servido.
- `c07-complete-final-state.json`: revisão, 111 hashes e 27 ficheiros tracked
  preexistentes preservados.

Os primeiros ensaios `c07-complete-first` e `c07-complete-drag-trial` falharam por
um gesto automatizado incorreto: `dragTo` deslocava o painel para o destino antes
de pressionar o rato na posição antiga da origem. O evento registou `rate_source`
em vez de OF. O ensaio final inicia o arrasto real na origem visível e só depois
desloca o painel; não usa eventos artificiais para fingir um arrasto bem-sucedido.

Calibri, zoom a 200%, OCR original, restantes critérios do plano e publicação
final continuam fora desta aprovação. Os requisitos e identificadores do plano
foram preservados integralmente.
