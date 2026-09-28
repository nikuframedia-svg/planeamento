# F20/G07 e G06/H10 — Horas por operação e prioridade de taxas

Duas auditorias independentes, apenas de leitura no clone, abrangem as 83 156 peças (ativo e histórico) e 105 999 estimativas por operação. Não chamam o estimador ou seletor de taxas da aplicação.

`c04-operation-hours-first.json` contém 1 343 945 verificações sem diferenças. Recalcula o saldo com a quantidade necessária e o contador selecionado, aplica a unidade da taxa e preparação explícita, distingue zero de desconhecido e confere a paridade RAW/23 494 operações de capacidade. Compara taxas manuais com os objetos originais, históricas com a evidência imutável e Excel com a coluna C do ficheiro original de Perfis ou o valor importado de Cantoneiras. As 183 aplicações do fator Thomas ×3 pertencem exclusivamente ao fallback Excel. As colunas E/F não substituem C.

Cobertura das horas: 251 estimativas positivas, 57 957 zeros conhecidos e 47 791 desconhecidas. Estas últimas mantêm motivo explícito; não são contadas como exemplos numéricos positivos. Quantidades, dimensões e contadores selecionados são entradas desta auditoria: ingestão/associação continua em C01/C02.

`c04-rate-selection-first.json` contém 938 949 verificações sem diferenças. Determina a data de aplicação por operação, vigência, recurso, área, operação e âmbito de material/perfil dos objetos manuais; depois aplica a prioridade manual → histórico → Excel. Confere a janela histórica, método, origem, taxa e fator. Há 970 estimativas manuais, 3 738 históricas, 56 784 Excel e 44 507 sem taxa. Os 105 históricos referenciados são entradas cuja aceitação/exclusão ainda exige a auditoria H09. Não se aprova H09 por verificar H10 com esses conjuntos como entrada.

Os ledgers comprimidos guardam, por identidade/operação, esperado, observado, entradas e proveniência. Os resumos contêm hashes dos ledgers, dos auditores, das configurações e do Excel original. Todos os valores foram confrontados com tolerância max(1e-6, abs(esperado) × 1e-8).

27 exemplos passaram em 0,60 s: área/h, metros/h, unidades/h, minutos/unidade, minutos fixos, preparação explícita, saldo zero sem dimensão, dimensões desconhecidas, taxa manual vigente/expirada/futura, âmbito incompatível, conflito sem fallback silencioso e Thomas Q=50/51. Os esperados são números literais independentes; tanto o motor como os auditores são confrontados com esses exemplos.

A prova final `c04-operation-rate-final.json` verifica 12 exemplos no browser, seis por área, com zero erros JavaScript: fontes manual/histórica/Excel e resultados positivos/zero/desconhecido. A OF260260 tem 867 peças na pesquisa, e a peça pretendida foi encontrada através de paginação real para a segunda página. Há 12 capturas. A prova confirma números e fontes apresentados; **não aprova toda a explicação dos cálculos**: a revisão visual confirmou que as entradas de `theoretical_hours` mostram quantidade/taxa mas ainda não explicitam comprimento/área que determinam o volume. Esse complemento permanece em C04.5.

24 exportações CSV/XLSX passaram em `c04-operation-rate-export-verified-exports.json`, com os ficheiros e hashes preservados. Expectativas numéricas vêm das auditorias independentes; as exportações usam a versão publicada da API.

Três problemas das ferramentas de validação foram corrigidos sem alterar a aplicação:

- O primeiro exemplo desconhecido de Cantoneiras referia-se à segunda operação, não ao resultado principal exportado. O substituto foi escolhido na população atual e os esperados novamente obtidos dos ledgers, preservando a fixture anterior.
- O percurso inicial do browser assumia que a peça estaria nas primeiras 500 linhas. A prova final usa o botão Seguinte até localizar a identidade, sem alterar o filtro ou a população para ocultar peças.
- O leitor XLSX assumia uma tupla de células retangular. O XML do primeiro ficheiro confirma que C1 existe e C2 é omitida por estar vazia. O leitor agora interpreta uma célula final omitida como desconhecida; continua a conferir todos os cabeçalhos e a exigir valores quando o esperado é conhecido. A exportação da aplicação não foi modificada.

Os relatórios falhados, produtores anteriores e exportação inicial foram preservados. As fontes, configurações, gerações4275–4282, 27 ficheiros tracked preexistentes e processos foram novamente conferidos. Nenhuma alteração da aplicação/base nem reinício nesta etapa. Os estáticos partilhados8113/18113 mantêm a condição documentada anteriormente.

As auditorias específicas abrangem agora 38 regras. F02/F03/G01/H03/H09 ainda não têm auditoria integral equivalente; a explicação dos derivados, fontes reais e matrizes C02/C05/C10/C11 também continuam pendentes. C04 global e C12 não são aprovados.

Comandos principais:

```
PYTHONPATH=. .venv/bin/python scripts/audit_planning_operation_hours.py --output c04-operation-hours-first
PYTHONPATH=. .venv/bin/python scripts/audit_planning_rate_selection.py --output c04-rate-selection-first
.venv/bin/python -m pytest -q --tb=short tests/test_planning_operation_hours.py tests/test_planning_productivity.py::test_priority_expiry_conflict_and_thomas_factor_only_excel
PLANNING_CHECK_BASE=http://127.0.0.1:18113 PLANNING_TEST_ISOLATED=1 PLANNING_PROOF=c04-operation-rate-final node tests/planning_operation_rate_browser.cjs
PLANNING_CHECK_BASE=http://127.0.0.1:18113 PLANNING_TEST_ISOLATED=1 .venv/bin/python scripts/audit_planning_result_exports.py --fixture c04-operation-rate-final.json --output c04-operation-rate-export-verified
```
