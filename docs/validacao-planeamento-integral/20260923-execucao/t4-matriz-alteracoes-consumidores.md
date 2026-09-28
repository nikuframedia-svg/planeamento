# Alterações, consumidores e limites das provas

As referências abaixo são relativas a esta pasta. Testes adicionais estão no diretório `tests`. Os tempos são os observados nas provas referidas, não uma estimativa de desempenho.

| Alteração | Consumidores conferidos | Provas aproveitadas/novas | Estado |
|---|---|---|---|
| Nova OF/OV, peças locais, quantidade, comprimento, edição parcial | Formulário, API, RAW, identificação, auditoria, capacidade | `c03-complete-zero-fixed.json`, `c03-complete-persistence.json`, `c05-publish-browser.json` | Percursos aprovados; identidade reutilizada nos ensaios originais atuais |
| Geometria, stock, abocardar, operação, semana ISO | Preview, gravação, RAW, detalhe de regras, capacidade, CSV/XLSX | `c05-direct-form-browser.json`, `c05-f12-save-browser.json`, `tests/test_planning_incremental.py`, `t7-final-local-publication.log` | Provas de comportamento existentes e regressão atual |
| Máquina e período | Recurso antigo/novo, áreas partilhadas e totais semanais | `c05-capacity-incremental-browser.json`, `tests/test_planning_capacity_incremental.py`, `t7-concurrency-final-regression.log` | Provas existentes compatíveis; não substituem a sequência cumulativa V06 |
| Taxa, calendário, horas manuais, janela, prioridade | RAW, capacidades, histórico, origem e cobertura | `c10-refresh-browser.json`, `c10-refresh-history-audit.json`, `c10-historical-cohorts-final.json` | Reutilizados os 15 passos já aprovados de C10.4 |
| Inserção, correção e retirada MES | Centro, derivados, browser e capacidades | `c10-visible-final-ocr-incremental-browser.json` | Reutilizadas as seis atualizações aprovadas |
| Inserção, correção e desvalidação original | Centro, RAW, browser, horas/produtividade e capacidades | `t4-original-final-ocr-incremental-browser.json` | Seis atualizações em cópia integral; derivados até 3,157 s e agregados até 9,644 s |
| Associação original parcial/completa | Decisão, revisão, RAW, capacidade, reabertura e recarga; CSV/XLSX nos testes de integração | `t4-full-association-browser.json`, `t1-association-perfis-browser.json`, `t1-association-cantoneiras-browser.json`, `t7-concurrency-final-regression.log` | Quatro gravações integrais: pedido 3,868–4,721 s; resposta→linha até 1,407 s; resposta→agregados até 2,987 s |
| Fonte original com área/horas desconhecidas | Observações preservadas, exclusões, contagem única, capacidade | `tests/test_planning_original_hours.py`, `t7-concurrency-final-regression.log` | Sem atribuição arbitrária de área nem multiplicação de horas |
| Concorrência entre gravação e worker | Transação, publicação, idempotência e histórico | `t4-association-lock-test.log`, `t4-repeatable-publication.log`, `t7-final-local-publication.log` | Conflitos de negócio continuam 409; só transações abortadas por serialização são repetidas |
| Respostas de filtro atrasadas | Seleção atual da origem/estado, formulário de decisão | `t4-full-association-browser.json` | Resposta antiga não substitui a atual; controlos desativados durante gravação |
| Worker indisponível/recuperação | Estado pendente, saldo anterior, nova revisão e capacidade | `t4-original-worker-recovery.json` | Recuperação observada em 4,063 s na cópia integral |
| Reconstrução/reinício | 83.156 peças, fontes, valores, registos, vistas, decisões e histórico | `t5-current-rebuild.json`, `t7-persistence-before.json`, `t7-persistence-after.json` | Zero alterações inesperadas ou perdas; reconstrução integral não é apresentada como atualização incremental de 10 s |
| Fecho/reabertura por CPIS/macro | Ativo/histórico, agregados, exportações e identidade | Provas C06 e `tests/test_planning_population.py` | C06 preservado; integrar estes passos na mesma sequência V06 ainda pendente |
| Alteração global de fontes macro/documentais e combinações da matriz | Todos os consumidores afetados | Provas parciais C05/C06 e reconstrução integral | Falta concluir a cobertura das combinações e a sequência cumulativa V06; C05.2/.3 não aprovados |

O percurso de sincronização real do original continua pendente em C01. A cadência configurada de 300 s não é confundida com o limite de 10 s após a chegada ao centro. As medições com fontes sintéticas acima só escreveram na cópia isolada.
