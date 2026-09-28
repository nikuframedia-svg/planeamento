# Formulário de planeamento — Perfis e cantoneiras

**Documento histórico da proposta de formulário.** O fluxo principal atual recebe dossiês PDF em `/planeamento` e prepara uma cópia da macro existente. Este formulário continua disponível em `/planeamento/manual`; não é uma etapa obrigatória da transcrição PDF → macro nem representa o motor futuro de calendarização.

O formulário manual pesquisa OF pelo número, cliente, designação ou referência e usa a linha exata do ficheiro importado para preencher a ficha. Abrange `Met2_Plan_Perfis.xlsm` e `Met3_Plan_Cantoneiras.xlsm` através da base `dataresearchmtg` e do circuito de importação existente.

As fichas são guardadas no PostgreSQL em `planning_mtg.records`, com revisões em `planning_mtg.record_versions`. Cada revisão guarda responsável, data, valores e origem. O utilizador pode reabrir uma ficha, editar e guardar uma revisão. Uma importação nova exige atualizar a ligação à mesma identidade técnica; correspondências ambíguas são recusadas.

Os valores são dados de preparação/planeamento e quantidades acumuladas declaradas. Guardar a ficha não é um evento novo de produção e não incrementa Ser./Aboc. nem modifica o XLSM. A separação evita somar de novo quantidades que já estavam no ficheiro. A percentagem apresentada é da operação selecionada, não da obra inteira. Um contador desconhecido fica vazio.

## Campos

- Contexto preenchido pela origem: OF, OV, cliente, designação, estado CPIS e data fim da Produção.
- Linha técnica: referência, material, designação, perfil, qualidade, diâmetro, largura, altura, espessura, comprimento e ângulo; indicação de perfil especial.
- Operações: corte/abocardar, Aborc., Chanf., Ponteira e outras indicações originais de cantoneiras.
- Necessidade: quantidade necessária, quantidade a planear, quantidade boa acumulada e percentagem calculada.
- Previsões humanas: Data Corte, execução, Picking/ano, semana/ano de finalização e capacidade semanal informada.
- Organização: máquina do catálogo da área, equipa, pavilhão, requisição de material, data de material, lote e observações.

O Picking dos perfis é relacionado diretamente pela OF com a folha Picking importada, incluindo linhas cujo Excel não tem a fórmula copiada. O ano não é inventado. OF fechada ou desconhecida no CPIS da última importação não é permitida para nova gravação. Os estados aceites nesta versão são `Em Aberto` e `Em Produção`; a página identifica que esse estado é da importação, não de uma consulta em direto ao CPIS.

## Arranque

Aplicar `sql/018_planning_registry.sql` com uma conta administrativa no Postgres. É uma migração aditiva e concede à conta `mes_kanban_app` apenas as permissões necessárias nas novas tabelas. Usa as variáveis de ligação já existentes em `.env` (`MES_PG_DSN` ou `MES_PG_*`).

A página é incluída na aplicação existente e também tem um arranque independente, sem captura/OCR:

```bash
.venv/bin/python -m uvicorn app.web.planning_app:app --host 127.0.0.1 --port 8112 --env-file .env
```

Se a porta estiver ocupada, usar outra porta livre. O servidor de trabalho deste pedido usa uma porta atribuída automaticamente, indicada na resposta ao utilizador. Não foi feita publicação na instalação Windows nem no endereço externo da fábrica.

## Como automatizar com os recursos existentes

1. **Preparar o trabalho pendente:** consultar as OF permitidas, usar o saldo canónico de cada linha/operação e incorporar fichas revistas sem duplicar necessidades importadas. As divergências ficam para confirmação.
2. **Estimar carga:** nos perfis, usar a secção por peça e a quantidade pendente com a taxa da máquina; nas cantoneiras, usar horas teóricas válidas ou metros pendentes/taxa. Acrescentar preparação. O código e as fórmulas existentes permitem calcular, mas as taxas históricas ainda precisam de validação operacional.
3. **Preencher o calendário:** colocar o trabalho em horas úteis de máquinas compatíveis, protegendo a necessidade do setor seguinte expressa pelo Picking. Preservar Data Corte como previsão humana e Data CPIS como compromisso final. Guardar início/fim calculados separadamente.
4. **Escolher a sequência:** satisfazer compromissos confirmados, depois reduzir mudanças de material/perfil. Não aceitar uma melhoria de carga sem mostrar as obras prejudicadas. A experiência com 112 linhas reais demonstrou que agrupar perfis pode reduzir preparações e, simultaneamente, atrasar algumas linhas.
5. **Replanear:** uma importação de novas necessidades ou saldos volta a calcular o trabalho ainda por fazer, conservando o que já está em execução e as decisões fixadas pelo responsável. Um registo direto de execução é opcional para reduzir a demora dessa atualização.

Para um plano operacional fiável, são indispensáveis horários/operadores, compatibilidades, tempos/preparações e regras de prioridade (Picking com ano/dia e tratamento de semanas vencidas). Não são dedutíveis com segurança apenas do catálogo ou das quantidades. A integração SAP fica na segunda fase, conforme confirmado; indisponibilidades comunicadas podem bloquear trabalhos na primeira fase. Abocardar exige a sua regra de entrada própria, sem inferir transferências de parcelas.

O formulário e a persistência estão implementados. Um motor de calendarização automática ligado às fichas ainda não está implementado: a análise acima define como o construir com as fontes existentes e quais os parâmetros que faltam confirmar.

## Verificação

`tests/test_planning_registry.py` cobre validação, pesquisa, origem exata, recuperação Picking, gravação/reabertura, revisões, pedidos repetidos, conflito entre edições, bloqueio por CPIS, importação nova e isolamento entre áreas. Os testes de escrita usam PostgreSQL descartável:

```bash
RUN_PG_INTEGRATION=1 .venv/bin/python -m pytest -q tests/test_planning_registry.py
```

Nenhuma linha de produção fictícia foi gravada na base operacional para testar a página.
