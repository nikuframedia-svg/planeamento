# Explicação partilhada das horas previstas

A lacuna identificada na etapa anterior foi corrigida. O mesmo código do servidor obtém agora as entradas usadas no cálculo numérico e na sua explicação: saldo, método, dimensão, volume pendente, unidade, taxa e preparação aplicada. A RAW ativa, o histórico e as operações de capacidade conservam a mesma regra com contrato `planning-operation-hours-20260924-v1`. O contrato de capacidade passou para v19 e a impressão digital RAW inclui o contrato das horas, invalidando publicações antigas.

Cada método tem uma fórmula própria: área/h, metros/h, unidades/h, minutos/unidade e minutos fixos. A preparação não é aplicada quando o saldo conhecido é zero. Dimensão desconhecida mantém volume desconhecido quando há saldo positivo. O fallback Excel conserva o fator e a taxa anterior ao fator, sem multiplicar novamente a taxa aplicada. A explicação mostra a operação adicional separadamente.

Na RAW, tanto Cálculos como Taxas e horas apresentam a explicação. Rótulos e métodos aparecem em português; a taxa é mostrada de forma compacta com unidade, origem e vigência quando disponíveis. O objeto completo de origem continua na API. A vista de capacidades mostra fórmula, volume usado e preparação junto dos dados da peça. As capturas foram inspecionadas e confirmam esses campos visíveis.

Antes da implementação, dez testes de explicação falhavam. A regressão afetada passou com **140 testes em106,49s**, incluindo os dez casos novos, cálculo, produtividade, capacidades, preview e RAW. Nenhum teste ignorado. Os exemplos isolados incluem minutos fixos e preparação explícita, que não têm exemplos positivos na população atual.

A reconstrução isolada conservou todas as identidades e **todos os valores escalares publicados**, sem uma única alteração: gerações RAW4275/4276 →4291/4292; itens4293/4296; semanas4294/4297; máquinas4295/4298. A reconstrução demorou15,22s Perfis,98,76s Cantoneiras e39,25s capacidades. Estes tempos de reconstrução integral não são uma aprovação da latência incremental C05.

A auditoria independente foi ampliada para conferir as entradas, dimensões, volume, preparação, fórmulas por método, origem, motivo, versão e igualdade entre regra principal/estimativa/operação de capacidade. **3 060 738 verificações passaram nas83 156peças e105 999estimativas**, incluindo23 494operações de capacidade. Zero diferenças. Os esperados não chamam as funções de cálculo da aplicação; a escolha/aceitação dos contadores e históricos continua nos critérios próprios. O ledger guarda uma prova por identidade/operação.

No browser, os12exemplos da RAW passaram, com positivos/zero/desconhecido, métodos/unidades, fontes e paginação. Dois percursos adicionais de RAW→histórico→capacidades confirmaram a mesma evidência histórica e o volume aplicado, com igualdade à precisão de apresentação. Zero erros JavaScript. Não foram repetidas as24exportações da etapa anterior: o exportador não mudou e a igualdade de todos os valores foi comprovada; essas exportações continuam explicitamente vinculadas à revisão anterior.

Apenas o servidor isolado18113 foi reiniciado. Os processos operacionais mantêm PID/comando. Os dois JavaScript são partilhados e servidos por8113/18113, com hashes novamente conferidos. Isso não publica backend/migrações/worker em8113. Fontes Excel/OCR, configurações, necessidades e27ficheiros tracked preexistentes preservados.

O inventário posterior `c04-current-rule-input-gaps.json` identifica outros resultados numéricos conhecidos com entradas vazias: produção selecionada, saldos, quantidade prevista, excesso, área unitária, comprimento total em metros e peso unitário, conforme a área. São candidatos concretos a revisão; a igualdade numérica não demonstra que a explicação esteja completa, e uma entrada vazia não prova por si só erro em constante/não aplicável. A consulta SQL está em `c04-current-rule-inputs-auditor.py`.

A lacuna específica de `theoretical_hours` está resolvida. C04.5 global continua em curso por esses outros derivados. F02/F03/G01/H03/H09 continuam sem auditoria integral equivalente; ingestão real, matrizes transversais, fonte Calibri, regressão final e publicação continuam pendentes. Não se aprova C04 ou o plano integral nesta etapa.

Comandos:

```
RUN_PG_INTEGRATION=1 .venv/bin/python -m pytest -q --tb=short tests/test_planning_hours_detail.py tests/test_planning_operation_hours.py tests/test_planning_productivity.py tests/test_capacity_revision.py tests/test_raw_workspace.py tests/test_planning_capacity_preview.py tests/test_planning_integral_calculations.py
PYTHONPATH=. .venv/bin/python scripts/audit_planning_operation_hours.py --require-detail --output c04-hours-detail-population
PLANNING_CHECK_BASE=http://127.0.0.1:18113 PLANNING_TEST_ISOLATED=1 PLANNING_PROOF=c04-hours-detail-raw node tests/planning_operation_rate_browser.cjs
PLANNING_CHECK_BASE=http://127.0.0.1:18113 PLANNING_TEST_ISOLATED=1 node tests/planning_hours_detail_capacity_browser.cjs
PYTHONPATH=. .venv/bin/python docs/validacao-planeamento-integral/20260923-execucao/c04-current-rule-inputs-auditor.py
```
