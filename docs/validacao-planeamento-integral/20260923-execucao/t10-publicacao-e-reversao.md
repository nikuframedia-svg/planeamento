# Publicação e reversão seletiva

Destino autorizado: `kanban-planning.service`, porta 8113, e `kanban-raw-worker.service`. Os MES 8100/8101 conservam os seus processos e dados. C00–C11 estão aprovados na checklist; a exceção de latência foi autorizada pelo utilizador em 24/09.

O pacote completo da candidata, incluindo ficheiros não acompanhados pelo Git, está identificado em `t10-candidate-manifest.json`: 181 ficheiros de execução e migrações 027–036. Os 27 ficheiros preexistentes acompanhados pelo Git permanecem intactos.

Os backups privados estão em `/home/luis/.local/state/planning-backups/integral-20260923/publication-20260924/`:

- `pre-publication-final.dump`: backup consistente mais recente de PostgreSQL, hash em `t10-pre-publication-backup.json`.
- `operational.dump`: backup restaurado integralmente no ensaio. Migrações e publicação da candidata passaram, com as 318 folhas reais e 83.690 peças; `t10-publication-rehearsal.json`.
- `dossiers.sqlite3` e `document-files.tar.gz`: SQLite consistente e ficheiros documentais; `t10-document-operational-backup.json`.
- `candidate-source.tar.gz`, definições anteriores das unidades e `reversal-rehearsal/`: código e reversão ensaiada dos 45 ficheiros com hash anterior.

## Aplicação

1. Confirmar os hashes da candidata e C00–C11. Guardar PID das quatro unidades.
2. Preservar a definição da unidade transitória do serviço 8113 numa unidade persistente equivalente, para permitir parar/iniciar sem perder a configuração. Conservar os drop-ins.
3. Parar apenas `kanban-planning.service` e `kanban-raw-worker.service`. Executar `systemctl --user daemon-reload` depois da paragem da unidade transitória, para o systemd reconhecer a definição persistente.
4. Aplicar sequencialmente as migrações aditivas 027–036 com `ON_ERROR_STOP`. Conferir que as tabelas MES não mudaram por ação da migração.
5. Iniciar as duas unidades; registar os novos PID e a candidata nos registos privados da publicação.
6. Aguardar a reconstrução das projeções com as fontes atuais. Conferir os contratos RAW v22/capacidades v24 e a ausência de pendência. A reconstrução inicial não é uma medição de atualização incremental.
7. Conferir endereço público, dados reais, OF264774, Cantoneiras, fechos, colunas, scroll, fonte efetiva 11 pt, primeira revisão aplicada após o reinício e ciclos automáticos seguintes.

## Reversão

1. Parar apenas as duas unidades de Planeamento e guardar o diagnóstico.
2. Repor os 45 ficheiros anteriores a partir de `preexisting-source.tar.gz`, usando os hashes `before` do manifesto histórico. A extração e igualdade desses 45 ficheiros foram ensaiadas em `t10-selective-code-restore.json`. Não usar `git reset`, nem substituir alterações preexistentes.
3. Se o leitor anterior não compreender a migração 032, materializar os detalhes conforme `c10-storage-reversao.md`, cuja equivalência tem regressões dedicadas. Preservar todos os valores, decisões e épocas de histórico.
4. Conservar tabelas/colunas aditivas 027–036 e registos humanos. Não restaurar o PostgreSQL inteiro sobre novas validações MES. A reversão não apaga dados criados depois do backup.
5. Iniciar as duas unidades, confirmar o último conjunto íntegro, fontes e acessos. Se necessário, repor a configuração guardada das unidades mantendo um ficheiro persistente que permita o arranque.

O resultado efetivo da execução fica em `t10-deployment.json`; o browser e a reconciliação final têm relatórios próprios. A execução passou: candidata publicada, 14 conjuntos reconciliados, browser público e dois ciclos automáticos confirmados. O fecho está em `t10-entrega-final.md`.
