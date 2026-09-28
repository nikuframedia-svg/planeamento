# H03 e H09 — horas reais e conjuntos históricos

Esta etapa verifica as duas regras sobre a população atual, sem alterar a
aplicação, a base isolada ou os serviços. As fontes reais adicionais e a
associação dos eventos continuam nos checkpoints C01/C02.

## Horas reais (H03)

`scripts/audit_planning_actual_hours.py` lê diretamente as 286 folhas centrais
e os 2 351 registos de produção. Reconstrói uma declaração por folha, a partir
dos valores distintos de horas e máquina; dez peças com as mesmas horas não
produzem dez declarações. Compara a população e os valores originais completos
com as projeções `production_hours`.

O auditor lê depois as configurações dos recursos e as seis declarações
manuais não arquivadas, cinco confirmadas. Confere o hash da revisão da origem,
substituições integrais, períodos sobrepostos e declarações não confirmadas.
Não chama as funções da aplicação que resolvem observações, horas ou capacidade.
Calcula de novo os grupos semanais e a cobertura conhecida/desconhecida.

Resultado: **1 894 verificações em 185 grupos semanais, zero diferenças**.
Há sete folhas de Perfis com horas conhecidas e nenhuma de Cantoneiras. Quatro
grupos têm total real conhecido; os restantes mantêm os desconhecidos. As
declarações manuais existentes no clone são ensaios, não declarações de fábrica.

## Taxas históricas (H09)

`scripts/audit_planning_historical_cohorts.py` parte das horas reconstruídas
diretamente pelo leitor independente H03. Lê os 3 304 eventos publicados e
as características atuais das peças; 2 679 eventos têm associação considerada
utilizável pela projeção. A correção dessas associações é uma dependência C02,
não uma conclusão desta auditoria.

Para cada contexto atualmente usado, recalcula a janela, recurso, operação e
método. Decide a aceitação ou exclusão do par volume/horas: datas, horas
positivas, identidade, quantidade, dimensões, compatibilidade, sobreposição,
versões repetidas e repartição explícita completa. Confere todos os motivos
de exclusão, conjuntos aceites, eventos/folhas, totais e taxa ponderada. Não usa
os conjuntos aceites publicados como entrada do cálculo esperado.

Resultado: **107 520 verificações, 105 evidências imutáveis e 123 contextos**,
abrangendo **105 999 estimativas em 83 156 peças**, sem diferenças. Entre esses
contextos existem três decisões de aceitação e 711 de exclusão. Estes números
contam decisões por contexto, não folhas físicas distintas. Três contextos têm
taxa positiva: 30 625 mm²/h, 124 223,60007118613 mm²/h e 115,2255 m/h. Os demais
não inventam produtividade a partir de dados incompletos.

O ledger guarda o esperado independente e o observado por contexto. O hash
de cada evidência imutável foi recalculado. Os hashes dos inputs H03 e H09 são
iguais, demonstrando que as duas auditorias usaram as mesmas fontes e declarações.

## Testes e interface

Os 32 exemplos dos novos auditores passaram. A regressão com os testes de horas
reais e produtividade da aplicação passou: **64 testes, nenhum ignorado,
45,39 segundos**. Não somar estes dois números: os 32 estão incluídos nos 64.

Os casos incluem repetição de horas por peça, valores divergentes, zero manual,
revisão desatualizada, períodos sobrepostos, recurso partilhado entre áreas,
volume incompleto, média ponderada, janela, duplicados, repartição de operações
e exclusão conjunta do numerador e denominador.

Seis percursos de browser passaram, sem erros JavaScript: horas conhecidas e
parciais em ambas as áreas, mais uma taxa histórica por área. Os esperados da
fixture vêm dos auditores independentes. Cada tabela de evidência foi conferida;
motivos de exclusão e valores foram comparados. Capturas inspecionadas confirmam
que quatro horas conhecidas entre sete declarações não aparecem como total
completo e que os conjuntos históricos mostram o numerador/denominador usados.

O primeiro comando de regressão continha o nome de um ficheiro inexistente;
terminou sem executar testes. O comando corrigido está abaixo. O primeiro
browser verificou as quatro horas reais e parou num seletor que confundia um
cabeçalho com uma célula. O teste foi corrigido para `columnheader`; o segundo
percurso completo passou. Logs e produtores anteriores foram conservados.
Nenhuma destas correções alterou a aplicação.

```bash
PYTHONPATH=. .venv/bin/python scripts/audit_planning_actual_hours.py --output c04-actual-hours-current
PYTHONPATH=. .venv/bin/python scripts/audit_planning_historical_cohorts.py --output c10-historical-cohorts-final
RUN_PG_INTEGRATION=1 .venv/bin/python -m pytest -q --tb=short tests/test_planning_actual_hours_audit.py tests/test_planning_historical_cohort_audit.py tests/test_planning_worked_hours.py tests/test_planning_productivity.py
PLANNING_CHECK_BASE=http://127.0.0.1:18113 PLANNING_TEST_ISOLATED=1 node tests/planning_time_cohorts_browser.cjs
```

## Limites da aprovação

H03/H09 juntam-se às 38 regras com auditoria independente específica, perfazendo
40 das 43 regras. F02/F03/G01 ainda precisam de uma auditoria equivalente da
política completa de seleção dos contadores. Isto não aprova integralmente
C04, C10 ou C11: faltam fontes C01/C02, matrizes de atualização C05/C10 e
regressão final. C12 permanece por executar.

As gerações 4299–4314 foram apenas lidas; não houve reconstrução ou reinício.
As 27 alterações tracked preexistentes, fontes, configurações, ficheiros Excel
e processos foram novamente conferidos. A revisão e os hashes constam de
`c10-time-cohorts-final-state.json` e do manifesto arquivado desta etapa.
