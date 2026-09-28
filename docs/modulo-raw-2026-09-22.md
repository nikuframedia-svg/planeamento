# RAW de Perfis — implementação de 22/09/2026

A vista adicional está em `/planeamento/raw`. O formulário manual/PDF e a página
inicial continuam disponíveis. A migração 023 cria apenas vistas e análises
persistidas. As novas decisões de requisição e comprimento unitário são guardadas
nas fichas e no histórico já existentes.

## Dados e edição

A projeção auditada contém 7.391 linhas, em 74 páginas de 100. A enumeração integral
foi verificada sem omissões nem repetições. Os 23 IDs do layout fornecido têm uma
correspondência única na macro. Os exemplos não foram importados como decisões.

A tabela usa o contexto CPIS, as linhas da macro e preparações existentes. Uma
origem já associada reutiliza a necessidade. Não há fusão apenas por referência.
A edição de uma célula resolve a origem e grava o rascunho na mesma transação,
com revisão e idempotência. Os restantes valores importados não passam a ser
classificados como decisões humanas só porque outra célula foi editada.

Os acumulados da macro e a produção validada são circuitos distintos. O cruzamento
reutiliza a recuperação histórica, expansão das referências e separação das
operações. A auditoria encontrou evidência OCR associada a 273 linhas de corte e
27 de abocardar. Ausência de evidência não é zero. Associações humanas substituem
a contribuição automática correspondente.

A paginação mantém uma versão em memória. Depois de uma reinicialização ou de a
versão sair da cache, o servidor exige atualização explícita. A interface avisa
quando encontra uma versão mais recente. Uma análise guardada conserva os dados
congelados independentemente desta cache.

## Analista

O transporte existente Bedrock Mantle foi reutilizado com prompt próprio, sem
alterar o prompt de transcrição PDF. O ensaio real terminou com `xai.grok-4.6`:
soma do saldo conhecido por máquina sobre as 7.391 linhas, sete grupos e um saldo
desconhecido identificado. A análise está guardada como
“Saldo de corte por máquina · ensaio real”.

O modelo produz uma consulta estruturada limitada a campos permitidos; o servidor
calcula os resultados. Uma segunda resposta escolhe a apresentação. Não existem
ferramentas de escrita operacional, SQL livre ou execução de código gerado.
O JSON inclui os dados congelados, resultados, evidência e apresentação. O HTML
usa um renderizador local, sem scripts ou dependências remotas. O texto do modelo
é identificado como interpretação; as tabelas e gráficos usam os cálculos do servidor.

São suportadas soma, contagem, contagem distinta, média, mínimo e máximo,
um agrupamento e filtro de análise, e comparação de duas somas separadas. Os
filtros da RAW aplicam-se antes da análise e abrangem todas as páginas. Resultados
com mais de 500 grupos pedem um filtro ou agrupamento mais abrangente.

## Validação

- Bateria principal: **200 testes passaram**, incluindo regressão de fichas,
  conferências, exportação, dossiês e browser.
- Revisão final de proveniência e edição: **41 testes passaram**, incluindo
  browser RAW e formulário comum.
- Cálculos adicionais: **5 testes passaram**, incluindo área geométrica,
  valores inválidos e distinção entre `false`, zero e desconhecido.
- Testes de escrita executados em PostgreSQL descartável; não foi criada produção
  nem preparação fictícia na instalação central.
- Browser: edição por teclado, evidência mantendo o texto por guardar, histórico,
  pesquisa, 390 px e largura equivalente a 200%.
- Publicação: consulta da tabela e da análise real pelo URL público.

Evidências em `docs/raw-2026-09-22/`: `testes.txt`, `testes-finais.txt`,
`testes-calculos.txt`, `auditoria-layout.json`, `paginacao-real.json`,
`llm-real.json`, `analise-real.html` e capturas `publicado-*.png`.

Capturas: [tabela](raw-2026-09-22/publicado-tabela.png), [análise real](raw-2026-09-22/publicado-analise.png), [edição](raw-2026-09-22/browser-edicao.png) e [390 px](raw-2026-09-22/publicado-mobile.png).

## Configuração e reversão

Aplicar `sql/023_planning_raw.sql` com o administrador da base, em transação.
Ativar `MES_PLANNING_RAW_ENABLED=1` no serviço de ensaio. O conector do modelo usa
a configuração existente dos dossiês, com perfil de instruções separado.

Nesta instalação, a ativação encontra-se em
`~/.config/systemd/user/kanban-planning.service.d/raw.conf`.
Foi reiniciado apenas `kanban-planning.service`, na porta 8113.

Para desativar a RAW e a sua ligação na navegação, mudar a variável para `0`,
executar `systemctl --user daemon-reload` e reiniciar o serviço de ensaio.
Não remover tabelas, decisões nem análises. A cópia anterior de código e a cópia
do esquema de planeamento estão em
`/home/luis/.local/state/planning-backups/raw-20260922/`.

O processo de ensaio usa um worker da aplicação e dois trabalhos de análise
simultâneos. Trabalhos interrompidos por reinicialização ficam identificados;
podem ser repetidos numa nova análise. Trabalhos em fila são retomados.

## Limites mantidos

A primeira versão RAW é de Perfis. As horas e pesos sem base comprovada continuam
indisponíveis; não foi criado um motor de capacidade nem uma otimização de corte.
A estimativa de barras não inclui perdas de corte e não confirma stock.
“Requisitado?” é uma declaração local; não envia requisições.

O CPIS continua importado da macro, sem confirmação direta. Guardar rascunhos e
exportar relatórios analíticos é permitido; a conclusão operacional e a saída da
macro mantêm o bloqueio existente por falta de confirmação CPIS recente.

## Contrato das colunas

| Excel | Campo | Controlo |
|---|---|---|
| A | ID (`id`) | Consulta / cálculo |
| B | Cliente (`customer`) | Consulta / cálculo |
| C | Descrição da obra (`designation`) | Consulta / cálculo |
| D | OV (`ov`) | Consulta / cálculo |
| E | OF (`of`) | Consulta / cálculo |
| F | Data de corte (`cut_date`) | date |
| G | Data CPIS · entrega (`delivery_date`) | Consulta / cálculo |
| H | Semana de picking (`picking_week`) | number |
| I | Equipa (`team`) | select |
| J | Pavilhão (`pavilion`) | text |
| K | Referência (`component_ref`) | text |
| L | Descrição do perfil (`description`) | Consulta / cálculo |
| M | Observações locais (`notes`) | text |
| N | Abocardar (`abocardar`) | checkbox |
| O | Quantidade total necessária (`quantity_required`) | number |
| P | Cortada · macro (`cut`) | Consulta / cálculo |
| Q | Abocardada · macro (`boc`) | Consulta / cálculo |
| R | % cortada (`cut_pct`) | Consulta / cálculo |
| S | % abocardada (`boc_pct`) | Consulta / cálculo |
| T | % operação final (`final_pct`) | Consulta / cálculo |
| U | Por cortar (`remaining`) | Consulta / cálculo |
| V | Por abocardar (`boc_remaining`) | Consulta / cálculo |
| W | Tipo de perfil nível 1 (`material_type`) | select |
| X | Tipo de perfil nível 2 (`profile`) | select |
| Y | Diâmetro (mm) (`outer_diameter_mm`) | number |
| Z | Largura (mm) (`width_mm`) | number |
| AA | Altura (mm) (`height_mm`) | number |
| AB | Espessura (mm) (`thickness_mm`) | number |
| AC | Comprimento (mm) (`length_mm`) | number |
| AD | Ângulo (°) (`angle_deg`) | number |
| AE | Qualidade (`grade`) | text |
| AF | Área total das secções (mm²) (`section_total`) | Consulta / cálculo |
| AG | Máquina de corte (`machine`) | select |
| AH | Data prevista de execução (`expected_date`) | date |
| AI | Quantidade prevista (`quantity_to_plan`) | Consulta / cálculo |
| AJ | % horas consumidas (`hours_pct`) | Consulta / cálculo |
| AK | Semana prevista (`expected_week`) | Consulta / cálculo |
| AL | Peso a produzir (kg) (`weight`) | Consulta / cálculo |
| AM | Requisitado? (`material_requested`) | tristate |
| AN | Comprimento total necessário (mm) (`total_length`) | Consulta / cálculo |
| AO | Comprimento unitário considerado (mm) (`stock_length_mm`) | number |
| AP | Estimativa de perfis inteiros (`bars`) | Consulta / cálculo |
