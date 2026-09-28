# C09 — Capacidades, horas e persistência

Revisão `2e224c22c815c52246ec5f8d907f0d6c806d1800e0d033e994c1bf6faaa29af0`, 120 ficheiros da execução. Os ensaios de gravação usam exclusivamente planning_integral/18113.

## Percurso e cálculo independente

O browser segue RAW → Capacidades → Definições · Capacidades e horas. Usa as duas peças de C03 em cada área, sem alterar as suas necessidades ou registos. Cada recurso tem 23 unidades pendentes em W1/2027. O teste altera separadamente turnos, horas por turno, indisponibilidade, taxa, método, disponibilidade zero, sobrecarga e horas reais. As páginas de observação da RAW e da disponibilidade permanecem abertas, sem F5.

Foram conferidos 11 estados por área: baseline, oito alterações de calendário/taxa e duas declarações/revisões de horas reais. Além dos valores, a prova exige a revisão publicada da configuração, evitando aceitar uma versão antiga quando duas configurações produzem o mesmo resultado. Os 20 passos medidos ficaram abaixo de 10 segundos: máximo de 2278 ms em Perfis e 3042 ms em Cantoneiras após a resposta de gravação.

Estado final em cada recurso: `3 × 6 − 2 = 16 h` disponíveis; taxa `4 min/un. = 15 un./h`; carga `23 × 4 / 60 = 1,533333… h`; horas livres `14,466666…`; ocupação `9,583333… %`; turnos equivalentes `0,255555…`; capacidade total `240 un.` e livre `217 un.`. As horas reais são 6 h e não alteram a disponibilidade. H01–H08 são reconstruídas no teste e novamente pelo auditor SQL, sem chamar o motor para obter o esperado.

O cenário de disponibilidade zero conserva carga positiva, horas livres negativas e ocupação indefinida. O cenário de sobrecarga conserva ocupação superior a 100% e capacidade livre negativa. Unidades/h e minutos/unidade foram exercitados explicitamente.

## Persistência, conflitos e origem

Cada gravação é reenviada com a mesma chave: a resposta é idêntica e não surge outra revisão. Calendário, taxa e horas são reabertos após recarga do editor. Revisões antigas são rejeitadas com 409; indisponibilidade excessiva e método desconhecido são rejeitados com 422, sem mudar objeto nem histórico.

`c09-overlap-review.json` relê as declarações anteriores pela interface atual e pela capacidade publicada. Em Perfis há três folhas abrangidas: uma com 8 h e duas sem horas conhecidas; a decisão manual de 6 h produz uma única declaração de 6 h, não 14 h. Em Cantoneiras as nove folhas abrangidas não têm horas conhecidas; a declaração manual de 6 h é contada uma vez. A origem OCR permanece intacta e o histórico manual é preservado. Esta revisão faz apenas pré-visualizações e leituras, sem gravar objetos.

A regressão atual passou: **43 testes em 68,53 s, zero falhas ou ignorados**. Inclui recurso partilhado entre áreas, operações contadas uma vez, calendários importados concorrentes não somados, sobreposições, correções manuais auditadas, revisão de fonte que invalida uma conferência, unidades incompatíveis, taxa histórica ponderada, prioridade e vigência. Comando:

```bash
RUN_PG_INTEGRATION=1 .venv/bin/python -m pytest -q tests/test_planning_worked_hours.py tests/test_capacity_revision.py tests/test_planning_productivity.py tests/test_raw_workspace.py::test_shared_capacity_aggregates_each_operation_once tests/test_raw_workspace.py::test_capacity_methods_unknown_zero_and_overload
```

## Falha real corrigida no painel

Ao abrir uma máquina e mudar rapidamente de «Peças e cálculos» para «Calendário e parâmetros», a resposta pendente das peças reutilizava a mesma secção e substituía o separador escolhido. `c09-tab-race-reproduced.json` reproduz a falha atrasando a resposta real, sem substituir os dados. A correção atribui uma secção própria a cada seleção e ignora respostas dirigidas a secções já desligadas do documento. `c09-tab-race-fixed.json` passa nas duas áreas; o detalhe final também mostra todos os resultados numéricos esperados.

## Retoma e ensaios preservados

`c09-complete-capture-trial.json` contém os 11 estados de Perfis, reabertura e quatro rejeições já aprovados; falhou depois, apenas ao capturar uma página em segundo plano. A retoma conservou esses estados, verificou de novo os valores atuais, colocou a página em primeiro plano para a captura e executou o detalhe corrigido. Cantoneiras executou o percurso completo na retoma. O artefacto final identifica o SHA da prova anterior e do script correspondente; o auditor verifica essa ligação. Os testes concluídos não foram substituídos por valores reconstruídos ou por intenções.

Outros ensaios preservam erros do teste: seleção de um rótulo de `select` demasiado estrita; confirmação de descarte não aceite ao fechar o editor; expectativa HTTP 400 onde o contrato devolve 422; comparação do ano numérico com o texto enviado pelo formulário; e expectativa de horas OCR conhecidas em Cantoneiras, onde as nove origens têm horas desconhecidas. O primeiro ensaio de taxas com o mesmo resultado foi reforçado com verificação de revisão e um valor diferente. Estes erros não são classificados como defeitos da aplicação. A condição de corrida do separador é uma falha real, reproduzida separadamente antes da correção.

Comando do percurso final:

```bash
PLANNING_CHECK_BASE=http://127.0.0.1:18113 PLANNING_TEST_ISOLATED=1 PLANNING_CHECK_PREFIX=c09-complete-final PLANNING_CHECK_RESUME=c09-complete-capture-trial node tests/planning_capacity_complete_browser.cjs
```

## Estado e limites

`c09-complete-persistence.json` verifica os 22 estados, seis IDs de configuração, duas novas declarações de horas, histórico contínuo e valores publicados. As dez necessidades e os hashes das fontes centrais/macros são iguais ao baseline. As restantes configurações foram preservadas. Gerações finais RAW: Perfis 4259, Cantoneiras 4260. O worker isolado 1882801 foi parado após o ensaio; o servidor isolado permanece 1783048.

Os processos operacionais não foram reiniciados e as 27 alterações tracked preexistentes mantêm os seus hashes. Conforme documentado em C08, os estáticos são partilhados com Planeamento 8113; a correção de interface também é servida nessa porta. Isto não equivale à publicação integral C12. As comparações anteriores C03/C04 permanecem vinculadas às configurações e gerações identificadas nas suas provas.

C09.1–C09.4 aprovados neste âmbito. R08 ainda depende de C05/C12; as matrizes completas de recálculo, histórico, falhas, ingestão original e a entrega integral continuam pendentes.
