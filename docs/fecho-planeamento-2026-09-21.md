# Planeamento comum e importação do OCR original — 21/09/2026

## Estado da entrega

A interface comum está ativa no **serviço de ensaio** `kanban-planning.service`, porta 8113.
O serviço operacional MES de Perfis (8101) não foi reiniciado.

Implementado no servidor:

- Necessidades com UUID, operações e origens PDF/macro separadas; resolução concorrente e idempotente.
- Formulário comum de Perfis/Cantoneiras, com catálogos reais, dimensões condicionais e validação no servidor.
- Ligação PDF/manual sem somar quantidades; diferenças exigem decisão explícita.
- Associações humanas de produção, incluindo repartição de quantidades conhecidas e referências filhas congeladas.
- Conferências sem linha de macro e invalidação por alterações relevantes.
- Histórico por campo, sugestões separadas dos valores humanos, versão de catálogo e fila auditável para o arquivo documental.
- Proposta comum de saída de Perfis com deduplicação de seleções PDF/ficha.
- Conector independente e armazenamento/consulta separados para o OCR original.

**Ainda não comprovado:** execução do conector no PC da fábrica. A base central tem zero
publicações deste novo conector. A interface apresenta esta ausência explicitamente.
A ponte disponível dá acesso HTTP às aplicações e encaminhamento PostgreSQL; não dá uma
consola Windows para instalar ou registar a tarefa. Não se afirma que os dados atuais do
OCR original já estejam sincronizados.

O CPIS direto também continua sem uma versão publicada. Rascunhos e conferências estão
permitidos; conclusão operacional e saídas continuam bloqueadas por essa razão.

## Contratos e compatibilidade

Migrações aplicadas: `020_planning_needs.sql` e `021_original_ocr_import.sql`.
São aditivas e não alteram tabelas de factos MES, fontes CPIS ou acumulados Excel.
O esquema `ocr_original` tem um papel de publicação próprio, sem permissões nas tabelas MES/CPIS.

`GET /planeamento/api/catalogos?contrato=2` devolve o contrato do novo editor.
Os endpoints existentes continuam disponíveis. As gravações antigas são adaptadas à
identidade comum quando a funcionalidade está ativa; identidades históricas ambíguas
exigem conferência em vez de serem fundidas arbitrariamente.

O editor é `/planeamento/preparar`; `/planeamento/manual` usa-o quando
`MES_PLANNING_NEEDS_ENABLED=1`. Cada peça PDF tem a ação **Preparar peça**.
A revisão da leitura documental continua no circuito PDF existente.

O UUID da necessidade é estável; a especificação técnica tem revisão própria. Quantidade,
máquina e linha de origem não são usados como chave física permanente. Um novo documento
não incrementa a necessidade. A mesma seleção por dois percursos produz uma linha de saída.

As decisões humanas e respetivo histórico ficam no PostgreSQL. A reprodução de auditoria
no SQLite usa um outbox e recibos idempotentes; falhas de entrega não anulam decisões
já gravadas. O serviço de ensaio volta a tentar a entrega a cada 30 segundos.

As associações humanas substituem a interpretação local anterior do registo; nunca
alteram os dados OCR. Quantidade desconhecida não pode ser repartida. Uma referência
expandida exige o filho histórico e não soma o pai. As conferências não alteram contadores.

## Catálogos verificados nas versões importadas

| Área | Máquinas | Materiais | Equipas | Operações principais | Opções adicionais |
|---|---:|---:|---:|---:|---:|
| Perfis | 10 | 21 | 28 | 2 | 0 |
| Cantoneiras | 12 | 4 | 26 | 4 | 8 |

Foram disponibilizadas 482 designações nas famílias de Perfis e 130 designações
classificadas da tabela de Cantoneiras. São contagens observadas, não constantes do código.
Perfis usa os intervalos definidos do XLSM verificado pelo hash da importação, quando
este ficheiro está disponível. Snapshots antigos sem ficheiro usam os intervalos legados
auditados (N:AG, linhas 2–150). Não se misturam famílias para preencher listas vazias.

As indicações adicionais A/B de Cantoneiras são preservadas como indicações, sem contador
atribuído. Um material genérico como Varão exige escolher a geometria, sem presumir uma
secção redonda. Campos e opções históricos permanecem visíveis; a conclusão exige revisão
quando deixam de corresponder ao catálogo.

## Quantidades na saída

- Uma nova linha de Perfis recebe a **quantidade a planear explicitamente escolhida**.
  A necessidade total continua preservada na entidade central. Se forem diferentes,
  a cópia inclui essa distinção nas observações e na comparação por célula.
- Numa linha existente, a cópia conserva o contrato de necessidade e acumulados da macro.
  Uma preparação parcial pode ser guardada localmente; a exportação dessa linha exige
  selecionar o saldo completo. Não se reduz silenciosamente a necessidade para simular
  uma calendarização parcial.
- A máquina de abocardar não é escrita em Máquina Corte. Abocardar sem linha na macro
  exige primeiro preparar o corte. Não há exportação XLSM de Cantoneiras.
- Uma nova revisão relevante da peça, PDF, associação, saldo ou macro invalida a saída.

## Validação

A suite completa passou com **641 testes** (incluindo PostgreSQL descartável e browser),
antecedendo os últimos ajustes dirigidos de revisão/quantidade. Os resultados posteriores
estão nos relatórios separados abaixo; não são somados à contagem da suite completa.
A verificação final dirigida passou com **54 testes**, incluindo browser, em 47,23 segundos.

- [Suite completa](planeamento-fecho-2026-09-21/testes.txt).
- [Verificações finais dirigidas](planeamento-fecho-2026-09-21/testes-finais-direcionados.txt).
- [Saída e quantidades](planeamento-fecho-2026-09-21/testes-saida-quantidades.txt).
- [Browser publicado, apenas leitura](planeamento-fecho-2026-09-21/browser-publicado.json).
- [Percurso manual, base descartável](planeamento-fecho-2026-09-21/manual-desktop.png).
- [Percurso PDF, mesma necessidade, base descartável](planeamento-fecho-2026-09-21/pdf-desktop.png).
- [Cantoneiras no serviço publicado](planeamento-fecho-2026-09-21/publicado-cantoneiras.png).
- [PDF real no editor publicado](planeamento-fecho-2026-09-21/publicado-pdf.png).
- [Ecrã estreito](planeamento-fecho-2026-09-21/publicado-mobile.png).

A verificação no URL público não criou fichas ou produção de teste. Depois dela, a base
operacional continuava com zero preparações e zero necessidades novas. Os testes que
gravaram decisões usaram bases descartáveis e arquivos temporários.

## Reversão

Backup anterior à migração:
`/home/luis/.local/state/planning-backups/2026-09-21/planning-before-020.sql`.

Para regressar à interface anterior, alterar apenas o drop-in
`~/.config/systemd/user/kanban-planning.service.d/needs.conf` para
`Environment=MES_PLANNING_NEEDS_ENABLED=0`, executar `systemctl --user daemon-reload`
e reiniciar `kanban-planning.service`. Conservar o código de compatibilidade e todas as
tabelas novas. Não fazer reset do workspace nem remover colunas com dados.

A interface anterior foi mantida através desta opção. Não se promete compatibilidade
com qualquer commit antigo: o patch de serialização de UUIDs deve acompanhar uma reversão
de código que ainda leia fichas com as novas ligações.

No PC, a reversão do conector é desativar a tarefa **OCR Original Importacao Central**.
Não apagar os snapshots centrais nem alterar a SQLite original.
