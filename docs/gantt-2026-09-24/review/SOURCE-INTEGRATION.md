# Integração do planeamento existente no Gantt — 25/09/2026

A conclusão «faltam máquinas físicas, logo não há barras» confundia ausência de configuração local com ausência de dados. A ligação das máquinas e a apresentação do plano existente estão agora implementadas e publicadas em `/planeamento/gantt`.

## Resultado verificado com dados publicados

| Verificação | Resultado |
|---|---:|
| Operações abrangidas | 1.167 |
| Máquinas recuperadas do plano | 5 |
| Operações por executar com máquina e previsão utilizável | 778 |
| Dessas previsões, com duração positiva coerente com o saldo | 731 |
| Barras na janela inicial de 12 semanas, desde 21/09 | 398 |
| Previsões anteriores, acessíveis pelo seletor de semana | 380 |
| Operações concluídas excluídas das barras futuras | 37 |
| Operações sem máquina/previsão utilizável, conservadas na lista | 352 |

A partição é completa: 778 + 37 + 352 = 1.167. As 731 previsões com duração são parte das 778; não se somam à cobertura. Uma previsão pode ser apresentada com duração desconhecida, explicitamente indicada. O saldo e a duração continuam provisórios quando a fonte o exige.

A disponibilidade semanal da macro está ligada às mesmas máquinas. Na semana 39/2026, MEBA tem 12,96 h de carga conhecida para 10 h importadas. Vanguard conserva o conflito 32/80 h, com ambas as linhas de origem; esses valores não são somados nem escolhidos automaticamente. Semanas não preenchidas continuam desconhecidas.

## Alterações

- `app/gantt/inputs.py`: resolve máquinas já nomeadas no plano, reutiliza recursos configurados por ligação/nome inequívoco e atribui uma identidade estável às origens importadas. Transporta a disponibilidade semanal da fotografia usada pela geração publicada, dentro da mesma transação. A inexistência de um novo objeto local deixou de causar «máquina por indicar» para nomes conhecidos.
- `app/gantt/source_plan.py`: leitor da disponibilidade com evidência/conflitos e construção pura da vista de previsões/carga. Exclui concluídas, respeita semana manual, conserva conflitos de datas, valida a quantidade da duração e não herda Data Corte para abocardar. Não cria intervalos horários a partir de capacidade semanal.
- `app/gantt/service.py`: publica essa vista junto das operações atuais. A aceitação continua reservada ao serviço e validador de propostas horárias.
- Interface: abre diretamente o planeamento existente, agrupa por máquina, mostra saldo/carga em cada barra, permite consultar outras semanas e filtrar máquinas, apresenta capacidades e conflitos, e fornece detalhe da linha e origens. Dados atuais ficam separados dos snapshots históricos; abrir uma proposta antiga não substitui o plano atual. A aceitação fica desativada na vista de previsões.

A barra de previsão ocupa o dia ou semana indicado na fonte; não representa uma duração corrida de máquina. As horas constam da carga estimada. A vista da proposta horária mantém segmentos úteis e dependências. Com os dados atuais, 813 operações têm duração e ficam dependentes de horários diários; não são 813 máquinas desconhecidas. Outras pendências distinguem máquina ausente, saldo e parâmetros técnicos. Não foram inventados turnos, alteradas quantidades produzidas ou introduzidas restrições de stock.

## Validação e provas

- `uv run pytest -q tests/test_gantt_source_plan.py tests/test_planning_gantt.py -x --tb=short`: **22 testes passaram**, incluindo solver, calendário, aceitação e navegador em PostgreSQL descartável. [Saída](source-plan-tests.txt).
- Os testes novos verificam fotografia publicada (não a última importação), duplicados/conflitos de disponibilidade, prevalência de calendário confirmado, cobertura acima de 500 operações, duração incompatível com o saldo, distinção de dia/semana, exclusão de concluídas e não herança de Data Corte para abocardar.
- O teste de navegador de integração cobre abertura das fontes, seleção de barra, geração, ajuste de prioridade, aceitação, reabertura e identificação de propostas desatualizadas.
- `node docs/gantt-2026-09-24/review/source-plan-browser.cjs`: verificação operacional **só de leitura**, incluindo filtro por máquina, outras semanas, escala, seleção, consulta de cenário histórico e dimensões desktop/mobile. **Zero erros JavaScript/HTTP**. [Resultado](source-plan-browser-results.json), [desktop](source-plan-live.png), [mobile](source-plan-mobile.png).
- Cinco pedidos completos ao endpoint de operações: 1,119 / 1,116 / 1,071 / 1,108 / 1,096 segundos; mediana 1,108 s. Isto mede a consulta do plano existente, não o desempenho do solver com execução real.
- [Entrada/resultado congelados](source-plan-frozen.json.gz) e [manifesto das fontes, ficheiros e dependências](source-plan-manifest.json). Fotografia publicada observada: planeamento 781, capacidade 784. Estes números são evidência desta execução, não constantes de código.

## Publicação e reversão

Reiniciados apenas `kanban-planning.service` e `kanban-raw-worker.service`; ambos ativos. Os serviços MES não foram reiniciados. A flag existente continua a controlar o acesso. A reversão operacional pode desativar `MES_PLANNING_GANTT_ENABLED` e reiniciar os dois serviços, preservando cenários, produção e histórico. Esta integração não acrescenta migrações nem escreve configuração ou produção na base operacional.

Continua por validar a otimização com carga operacional em calendários diários preenchidos. A disponibilidade semanal existente não define horas de abertura/pausa; a vista de previsões já é utilizável independentemente dessa configuração.
