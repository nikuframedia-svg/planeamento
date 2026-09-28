# Publicação preparada; execução dependente de C11

Destino autorizado: `kanban-planning.service`, porta 8113, e `kanban-raw-worker.service`, ambos no gestor `systemctl --user`. O código e os estáticos estão no workspace atual. Os MES 8100/8101 não integram esta publicação.

**Não executado:** C11 ainda não está aprovado. O plano integral, secção 5, exige C00–C10 aprovados antes de C11 e C11 aprovado antes de C12. A autorização para publicar já foi dada; falta cumprir essas condições, não obter outra autorização.

## Preparação concreta

1. Fixar os hashes do `execution-manifest.json`; confirmar que os 27 ficheiros de trabalho preexistente continuam preservados. O estado da aplicação isolada está em `t7-candidate-final-state.json`.
2. Reconciliar a fonte original atual e o novo corte MES. A cópia de validação contém 286 folhas MES; a reconciliação aprovada usa o corte de 295 folhas. Na consulta posterior surgiram 314 folhas. Não copiar saldos antigos para o destino vivo.
3. Após C11, obter backup novo e consistente do PostgreSQL operacional e dos ficheiros de Planeamento efetivamente substituídos, em diretório privado. Registar instante, tamanho, hash, versão PostgreSQL e prova de leitura/restauro numa base descartável. O backup inicial de 23/09 não substitui esse backup de publicação.
4. Guardar as definições atuais das duas unidades, os PID, os hashes dos ficheiros e as revisões centrais. Parar apenas o serviço 8113 e o worker de Planeamento durante a janela de migração/publicação.
5. Aplicar sequencialmente as migrações aditivas `027` a `033` ainda não presentes no destino, incluindo as versões atuais de `031_planning_member_dependencies.sql` e `032_planning_estimate_storage.sql`. Não aplicar migrações de outros projetos. A migração 033 guarda todas as revisões das decisões originais.
6. Publicar exclusivamente os ficheiros da aplicação, SQL e recursos necessários indicados no manifesto; preservar alterações alheias. Os estáticos já são partilhados no workspace: a sua presença em 8113 não prova backend, worker ou esquema atualizados.
7. Iniciar `kanban-raw-worker.service` e `kanban-planning.service`; conferir os processos, porta 8113 e hashes carregados. Aguardar a publicação completa das revisões atuais, sem usar a geração do clone como se fosse a do destino.
8. Confirmar o endereço usado pelo utilizador e verificar, nesse endereço, as três fontes, OF264774 com os dados atuais, Cantoneiras, histórico/fechados, colunas, scroll, Calibri efetiva e atualização real posterior das fontes. Guardar respostas, revisões, capturas e tempos. C12 só aprova depois destas provas.

## Reversão seletiva

- Parar apenas as duas unidades de Planeamento e conservar o estado falhado para diagnóstico.
- Repor os ficheiros de código de Planeamento guardados antes da publicação. Não usar `git reset --hard`, substituir todo o workspace ou restaurar a base inteira sobre escritas MES posteriores.
- Conservar tabelas aditivas, necessidades, declarações, decisões 033, eventos e revisões. A reversão de código não autoriza apagar decisões humanas.
- Se o código anterior exigir o formato JSON anterior a 032, seguir a materialização dos detalhes documentada em `c10-storage-reversao.md`, previamente ensaiada na cópia descartável. Não remover campos compactados antes dessa materialização e comparação.
- Iniciar as duas unidades, verificar leitura do último conjunto íntegro e identificar revisões pendentes. Conservar a cópia nova do backup até a verificação final ficar aprovada.

O pacote `docs/raw-completa/conectores-pc.zip` foi regenerado a partir do leitor original atual. Preparar o pacote não comprova instalação, leitura da SQLite efetivamente usada, publicação real ou continuidade.
