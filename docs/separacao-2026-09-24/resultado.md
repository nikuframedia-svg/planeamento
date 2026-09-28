# Planeamento transferido para projeto próprio

Concluído em 24/09/2026. A localização principal passa a ser **`/home/luis/projects/planeamento`**. O serviço 8113 e o worker arrancam com essa pasta de trabalho, `.env` e ambiente Python próprios. O endereço público mantém-se:

[Abrir Planeamento](https://louise-pest-performed-atom.trycloudflare.com/planeamento)

## O que foi transferido

Código do planeamento e dependências locais, páginas e recursos estáticos, testes, auditores, migrações, ferramentas de instalação e documentação. O novo projeto não inclui `app/web/main.py`, o servidor dos kanbans. A pasta `data/dossiers/` foi transferida atomicamente, preservando os ficheiros, a SQLite e os bloqueios em uso.

Foram mantidas 261 ligações de compatibilidade no projeto antigo porque os MES ainda importam módulos do planeamento e porque as referências históricas precisam de continuar acessíveis. Os recursos estáticos usam ligações físicas para respeitar a política de `StaticFiles`; os restantes caminhos usam ligações simbólicas. As ligações apontam do projeto antigo para o novo. O Planeamento não depende da pasta antiga para carregar código, configuração ou Python.

Os módulos partilhados necessários para conferir as fontes MES têm cópias locais independentes. O PostgreSQL central e a pasta de fontes Excel/Drive `DATARESEARCHMTG` continuam nos mesmos locais; não foram duplicados dados de produção.

## Verificação

| Prova | Resultado |
|---|---|
| Código de execução | 100 ficheiros da aplicação copiados sem alterar o conteúdo; manifesto da distribuição separada com 131 ficheiros |
| Python | Ambiente próprio; mesmas 49 versões de pacotes; entradas de execução relocalizadas |
| Importações | 52 módulos carregados exclusivamente da nova pasta |
| Arranque antes da mudança | Oito páginas, recursos estáticos e as duas APIs de dados passaram com PostgreSQL em leitura |
| Testes selecionados | 33 passaram em bases descartáveis; recolha de 748 testes sem erro, sem alegar execução dos restantes |
| PostgreSQL antes/depois | 14 conjuntos publicados e 19 tabelas de fontes, decisões e histórico sem diferenças |
| Documentos | Mesmas tabelas, ficheiros e inode da SQLite; integridade confirmada |
| Serviços | Backend PID 775034 e worker PID 775035, ambos na nova pasta |
| MES 8100/8101 | Mesmos PID 1206893/2736938; 27 ficheiros com alterações preexistentes preservados |
| Compatibilidade | Nenhuma ligação quebrada; recursos estáticos também respondem através do MES existente |
| Browser público | Perfis, Cantoneiras, OF264774, ativo/histórico, fontes, colunas, scroll, formulários, capacidades e 11 pt passaram |

A candidata da distribuição separada é `bcf1ca4c061062719cf549899b883660830ee8e8020b218cfab206f294f92677`. A identidade foi confirmada nos dois processos. O motor de cálculo mantém o conteúdo da candidata anterior; não foi reconstruído nem alterado por esta separação.

## Provas e ocorrências conservadas

- `migration.json`: inventário, caminhos, pacotes, processos, localização do backup e estado final.
- `runtime-manifest.json`: hashes da distribuição separada.
- `import-check.json` e `staged-http.json`: autonomia de importações e arranque.
- `final-relocation-tests.log`: 33 testes aprovados. A fixture antiga de registo foi completada com a migração 020, necessária ao modelo atual; as tentativas anteriores sem essa tabela foram preservadas. A aplicação não foi alterada para satisfazer o teste.
- `before.json` e `after.json`: comparação de fontes, resultados, histórico e documentos. O auditor foi corrigido para consultar a pendência nos conjuntos atuais de planeamento, em vez da metadata histórica dos conjuntos auxiliares.
- `public-browser.json` e `published-*.png`: prova e capturas após a mudança. Uma tentativa interrompida por alteração de rede do browser foi conservada separadamente; o percurso final passou.

A instalação offline do ambiente Python não encontrou uma roda já bloqueada no cache. Foi utilizada uma cópia independente do ambiente efetivamente instalado, conservando as versões e corrigindo os caminhos de arranque. Não foram atualizadas bibliotecas.

## Reversão

Backup privado: `/home/luis/.local/state/planning-backups/relocation-20260924T154640Z`.

Contém as definições e complementos anteriores das duas unidades, a árvore original em `legacy-tree/`, a SQLite consistente anterior à mudança e a cópia documental usada na validação preparatória. O inventário identifica cada caminho substituído.

Para reverter, parar apenas `kanban-planning.service` e `kanban-raw-worker.service`; guardar alterações de código posteriores; repor os caminhos originais a partir do inventário e das cópias. Transferir **o diretório documental atual**, conservando os dados novos, usando a mesma troca atómica de diretório/ligação. Repor as definições e a identificação anteriores das unidades, executar `systemctl --user daemon-reload` e iniciar as duas unidades. Não reiniciar os MES, nem restaurar um PostgreSQL antigo sobre produção atual. Conferir dados, fontes e endereço depois da reversão.

Para repetir a comparação de leitura da migração, sem alterações de dados desde o corte guardado:

```sh
cd /home/luis/projects/planeamento
.venv/bin/python -m scripts.verify_standalone after
PLANNING_PUBLIC_BASE=https://louise-pest-performed-atom.trycloudflare.com node tests/planning_final_public_browser.cjs
```

Validações ou edições reais posteriores podem produzir diferenças legítimas em relação ao corte `before.json`. As provas históricas da execução integral permanecem intactas em `docs/validacao-planeamento-integral/`; esta entrega acrescenta a verificação da nova localização.
