# Entrega do Planeamento de Perfis e Cantoneiras — 24/09/2026

Revisão publicada: `3800fea868fea5cce87b714e48a2e7d18cb4d2d2bc2a48f6bcfbb7561b08ca0c` (181 ficheiros de execução, incluindo os não acompanhados pelo Git). Destino: [Planeamento](https://louise-pest-performed-atom.trycloudflare.com/planeamento), `kanban-planning.service`, porta 8113, e `kanban-raw-worker.service`.

O âmbito acordado é exclusivamente o Planeamento de Perfis e Cantoneiras. A integração da aplicação OCR original foi retirada pelo utilizador; é aceite fonte substituta a 11 pt. O limite agregado de 10 s deixou de bloquear a entrega por instrução do utilizador, conservando as medições.

## Resultado publicado

| Área | Peças ativas | Histórico | Total | Folhas MES | Eventos expandidos |
|---|---:|---:|---:|---:|---:|
| Perfis | 1.139 | 6.275 | 7.414 | 113 | 534 |
| Cantoneiras | 17.743 | 58.533 | 76.276 | 205 | 3.145 |
| Total | 18.882 | 64.808 | 83.690 | 318 | 3.679 |

As 318 folhas foram reconciliadas por identidade e conteúdo com as fontes e o arquivo central. Eventos, quantidades, validações e peças filhas coincidem com a projeção. Quatro folhas Cantoneiras apresentam apenas outra ordem de exportação, demonstrada pelo `_display_order` da SQLite. Não há divergências de conteúdo por explicar. Provas: `t10-drive-mes-content.json` e `t10-final-live-mes-reconciliation.json`.

A primeira publicação das fontes reais depois do arranque produziu as gerações RAW 717/718 e capacidades 720/723. O worker confirmou o conjunto coerente às 14:49:37 UTC. Foram observados dois ciclos automáticos completos posteriores, idempotentes. Esta prova demonstra a aplicação do corte real e a continuidade; não afirma que alguém criou uma nova validação MES durante a observação. Provas: `t10-published-revision.json` e `t10-published-automatic-cycles.json`.

Os 14 conjuntos publicados coincidem com o ensaio realizado sobre o backup operacional do mesmo corte: valores, identidades e proveniência. Apenas os instantes de atualização de duas ligações à macro diferem entre os ambientes; versões, identidades e conteúdos dessas ligações são iguais. A comparação usa ordem binária explícita das chaves para evitar diferenças de ordenação semântica nos hashes. Prova: `t10-published-candidate-comparison.json`.

## Matriz de cumprimento

| Requisito | Resultado e provas principais |
|---|---|
| R01 — Registo novo | Formulários das duas áreas, criação e edição nas mesmas peças V06; `t10-v06-browser.json`, `t10-v06-exports.json`, `t10-public-browser.json` |
| R02 — Fechados | Fecho/reabertura macro e CPIS preservam IDs e histórico; ativo/histórico/todos verificados no destino; `t10-v06-browser.json`, `t10-public-browser.json` |
| R03 — Setas de colunas | Ordem alterada e reposta conservando o grupo aberto; `t10-public-browser.json`, provas C07 preservadas na checklist |
| R04 — Colunas e disposição | Todas as colunas disponíveis, arrastar/grupos/persistência nas provas C07; seleção completa e ordenação repetidas no destino |
| R05 — Scroll | Primeira/última coluna alcançadas nas duas áreas; provas de 1440/1024/390 px e zoom preservadas; `t10-public-browser.json`, `t9-zoom.json` |
| R06 — 11 pt | 14,6667 px a 96 dpi; browser identifica Liberation Sans efetiva; RAW, registo e capacidades verificados; `t10-public-browser.json`, `t9-typography.json` |
| R07 — Cálculos | 43 regras, comparação independente e ligação à candidata; `t10-final-rule-acceptance.json`, `t10-rule-batch.json` |
| R08 — Capacidades manuais | Taxas/horas, cobertura, agregados antigos/novos e prioridade verificadas; `t10-v06-browser.json`, `t10-v06-final-ui-browser.json`, provas C09 |
| R09 — Histórico | Horas da mesma população, exclusões e prioridade manual → histórico → Excel; `t10-actual-hours.json`, `t10-historical-cohorts.json`, `t10-rate-selection.json` |
| R10 — Registo Cantoneiras | Criação, campos, fontes e resultados no percurso completo; `t10-v06-browser.json`, `t10-v06-exports.json`, `t10-public-browser.json` |
| R11 — Produção real | Folhas reais fonte → centro → projeção; motivo individual de utilização/exclusão; `t10-final-live-mes-reconciliation.json`, `t10-real-event-lineage.jsonl.gz`, comparação publicada |

A [checklist integral](../../checkpoints-planeamento-2026-09-23.json) contém os 58 critérios C00–C12, os 11 requisitos e V01–V06. A matriz de alterações e consumidores está em `t10-matriz-alteracoes-consumidores.md`.

## Validação e limites das provas

- Nove auditores independentes cobrem as 43 regras. Os resultados do corte de validação foram ligados à candidata através de 12 comparações sem alterações de valores. Os relatórios identificam regras, entradas, esperado, observado e exclusões. As diferenças intencionais face ao Excel mantêm a justificação no contrato e nas auditorias C04.
- V06 contém 32 passos nas mesmas peças e 512 comparações API/base/CSV/XLSX. Os casos OF264774, geometria, operações, semanas ISO, unidades e Thomas Q=50/51 mantêm as provas indicadas em `t10-final-rule-acceptance.json`.
- A reconstrução da cópia de validação preservou 83.156 peças e os 14 conjuntos. O ensaio do corte operacional mais recente contém 83.690 peças. Estes cortes são distintos e não foram apresentados como a mesma população.
- Reinício da cópia integral preservou valores, decisões, relações documentais, ficheiros, históricos e recibos de auditoria. A entrega de um evento documental real no ambiente isolado passou de pendente a entregue; a repetição entregou zero eventos. Provas: `t10-persistence-before.json`, `t10-persistence-after.json`, `t10-document-audit-delivery-final.json`.
- Os lotes de regressão afetados estão associados aos critérios. Falhas antigas foram conservadas com a prova que as encerra; os 552 testes históricos não são usados como certificação desta revisão.
- No último percurso de gravação no browser, a resposta chegou à linha em 96–479 ms e aos agregados em 1,397–2,278 s. Foram medidos cerca de 10,5–10,7 s em revisões de macro. A reconstrução integral demorou 39,32 s em Perfis, 72,50 s em Cantoneiras e 36,94 s nas capacidades; não é uma atualização incremental. O utilizador dispensou continuar a otimização do limite agregado.
- CPIS é atualmente obtido através da macro e a interface identifica essa origem. Quantidades desconhecidas, operações ambíguas e cobertura incompleta continuam explícitas: não são transformadas em zeros nem em produção confirmada. A reconciliação identifica 109 eventos-pai Cantoneiras com quantidade desconhecida na fonte.

## Publicação e reversão

As migrações aditivas 027–036 passaram. Os hashes das tabelas MES mantiveram-se iguais durante a aplicação. Os MES 8100/8101 conservam os PID anteriores: 1206893 e 2736938. O backend 8113 e o worker carregaram a candidata, confirmada através dos hashes dos ficheiros e da identificação dos processos.

O backup final consistente foi obtido antes da publicação; um backup operacional anterior do mesmo corte foi efetivamente restaurado e ensaiado. Existem ainda cópia SQLite documental e arquivo dos ficheiros. A reposição seletiva dos 45 ficheiros com hash anterior foi ensaiada. O procedimento e os caminhos privados estão em [t10-publicacao-e-reversao.md](t10-publicacao-e-reversao.md). Não é necessário restaurar a base inteira sobre validações MES posteriores.

Ao converter a unidade transitória 8113 numa definição persistente equivalente, o systemd exigiu um segundo `daemon-reload` depois da paragem. O serviço arrancou com sucesso; ocorrência registada em `t10-deployment.json`.

## Capturas e reprodução

Capturas do destino: [Perfis / OF264774](t10-published-raw-perfis.png), [Cantoneiras](t10-published-raw-cantoneiras.png), [fontes Perfis](t10-published-sources-perfis.png), [fontes Cantoneiras](t10-published-sources-cantoneiras.png). A prova de fontes aguarda as três tabelas carregadas. Os testes de scroll ativam todas as colunas: a disposição compacta inicial de Cantoneiras cabe em 1440 px e, nessa situação, as setas ficam corretamente desativadas.

As tentativas anteriores do browser foram preservadas. Incluem uma espera inicial expirada, a tentativa de deslocar uma tabela sem excesso de largura e duas interrupções `ERR_NETWORK_CHANGED` do browser. O percurso final completo passou; esses ficheiros antigos não são usados para certificar a publicação. A única mensagem de consola restante é o favicon 404, sem erro JavaScript ou pedido funcional falhado.

Comandos de leitura para repetir as verificações do destino, a partir do repositório:

```sh
PLANNING_PUBLIC_BASE=https://louise-pest-performed-atom.trycloudflare.com node tests/planning_final_public_browser.cjs
.venv/bin/python -m scripts.audit_planning_published_candidate
.venv/bin/python -m scripts.reconcile_planning_live_mes --cantoneiras-backup /home/luis/.local/state/planning-backups/integral-20260923/mes-cantoneiras-20260924-123002.db --output t10-final-live-mes-reconciliation
```

O primeiro teste usa apenas leituras e disposição local do browser; não grava produção. Os restantes leem as bases. Novas validações reais posteriores a esta entrega podem legitimamente exigir outro corte de comparação.
