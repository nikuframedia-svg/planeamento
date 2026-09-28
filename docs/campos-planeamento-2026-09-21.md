# Simplificação dos campos do planeamento

O formulário comum de PDF e preenchimento manual passa a ter, por ordem:
Características de corte; Mais opções (sempre aberto); Dados da peça;
Trabalho a preparar; Guardar. Ângulo, qualidade e comprimento são sempre visíveis.
Não há pedido de nome, login novo ou caixa de quantidade a preparar.

## Catálogos verificados

Foi consultado o XLSM local importado, verificando o hash contra o snapshot:

- Perfis: `mtg2_9ed22bcb188e3cd1`, SHA-256
  `9ed22bcb188e3cd1af91bddf8350c29a632ea4ff98832e819a09a4859656d7a7`.
  A validação x14 de AF aponta para `AreaSecaoCorte!$A$3:$A$700`.
  Foram encontradas 20 famílias. AG usa `INDIRECT(SUBSTITUTE($AF7, " ", ""))`;
  os intervalos com nome fornecem as opções dependentes. `UPN50x25` e
  `UPN50x38` permanecem distintos. As famílias sem opções têm escrita manual.
- Cantoneiras: `mtg_0221b462085e3379`, SHA-256
  `0221b462085e33792fa8374cb49abf7b6af4b0695d9db5764b3b1a0c565000fa`.
  Nível 1 em `Dados!E3:E6`, quatro famílias; designações de Tabela pesos apenas
  nas famílias com associação comprovada. Operações principais/adicionais conservam códigos.

Os identificadores `material_type` e `profile` continuam iguais. Os rótulos são
Tipo de perfil nível 1 / Tipo de perfil nível 2. A API de catálogos fornece
`editor_visible`, `order`, `group`, `mode_by_family` e representação da checkbox.

## Regras de gravação

A migração `sql/022_planning_order_registration.sql` acrescenta apenas uma tabela
com a primeira gravação e a previsão por OF. A data é calculada na zona configurada
por `MES_DISPLAY_TIMEZONE` (predefinição Europe/Lisbon) e o instante é guardado em UTC.
A inserção faz parte da mesma transação da ficha. O backfill usa `min(records.created_at)`;
necessidades por guardar, PDFs e importações não iniciam a contagem. Repetições,
novas peças e novas áreas não reiniciam os sete dias. A data manual antiga permanece
separada. Não são enviados pedidos de requisição a outro sistema.

A preparação concluída usa o saldo completo de uma conferência válida ou de uma
única linha de macro associada. Valores desconhecidos permitem rascunhos e impedem
conclusão; zero não gera linha. Uma nova conclusão regista o cálculo pelo Sistema.
Editar observações ou reabrir não recalcula a quantidade anterior. Propostas verificam
novamente a evidência e o saldo antes de gerar a cópia.

A checkbox de Abocardar grava `X`/`-`; desconhecidos históricos exigem confirmação.
As operações internas continuam separadas e consultáveis no diálogo de produção.
Uma ficha antiga de abocardar não pode sobrepor silenciosamente a checkbox do corte.
Os campos removidos não são apagados quando omitidos, e a saída deixa U/Chanfro intacta.
VBA, fórmulas, datas fora do mapeamento, contadores e convenção do ângulo permanecem.

Não existe autenticação individual nesta instalação. Todas as novas decisões humanas
recebem a identificação **Utilizador não identificado** no servidor; nomes enviados
por clientes antigos não são tratados como identidade autenticada. Cálculos recebem
**Sistema**. Os autores antigos permanecem no histórico. Idempotência e revisões mantêm-se.

## Publicação e limites

Destino: serviço de ensaio `kanban-planning.service`, porta 8113.
O MES operacional na porta 8101 não necessita de reinício.
A consulta CPIS direta continua sem confirmação: rascunhos e conferências são permitidos,
conclusão operacional e exportação permanecem bloqueadas. O importador do OCR original
não foi alterado nesta entrega.

## Reversão

Cópia anterior: `/home/luis/.local/state/planning-backups/fields-20260921-231027`.
Para repor apenas a interface anterior, restaurar seletivamente os templates e assets
`need_editor`, `planning_hub` e `dossiers` dessa cópia e reiniciar o serviço de ensaio.
As regras de servidor e dados podem permanecer; não remover a tabela de primeira gravação.
Uma reversão completa de código deve usar a mesma cópia, preservando alterações posteriores.
A migração é aditiva, sem alterações às colunas antigas; a interface anterior pode ler
as fichas sem apagar decisões nem a data registada.

## Validação e evidência

- **191 testes de regressão passaram**: necessidades, formulários, fichas, evidência
  de produção, dossiês, exportação e browser. Registo em
  `planeamento-campos-2026-09-21/testes.txt`.
- **2 casos adicionais de exportação passaram**, verificando `X` e `-`, conservação
  de U/Chanfro, VBA, fórmulas, datas e produção. Registo em `testes-exportacao.txt`.
- A revisão final dos saldos passou **30 testes**, incluindo um caso adicional:
  a geometria alterada deixa de autorizar o saldo automático da macro; uma conferência
  explícita permite prosseguir. Registo em `testes-saldo-final.txt`.
- Ensaio final de browser em PostgreSQL descartável e SQLite temporária:
  `browser-final.txt`. Inclui gravação sem nome, erro seguido de gravação bem-sucedida,
  previsão criada uma única vez, família com seleção e família manual, preservação
  das edições, checkbox, conferência, PDF/manual sem duplicação e múltiplas peças.
- Verificação pública apenas de leitura em `browser-publicado.json`:
  OF266236, PDF real OF266229, Cantoneiras, 390 px e largura CSS equivalente a 200%.
  Não foram criadas fichas nem produção na base operacional para estes ensaios.
- O teste existente da produção com **315 cortadas e 298 abocardadas** mantém-se
  na regressão; corte e abocardar não são somados como a mesma operação.

Capturas do serviço de ensaio:

- [Manual](planeamento-campos-2026-09-21/publicado-manual.png).
- [PDF](planeamento-campos-2026-09-21/publicado-pdf.png).
- [Cantoneiras](planeamento-campos-2026-09-21/publicado-cantoneiras.png).
- [390 px](planeamento-campos-2026-09-21/publicado-mobile.png).
- [Refluxo a 720 px CSS](planeamento-campos-2026-09-21/publicado-200.png).

A migração 022 foi aplicada no serviço de ensaio. Não existiam fichas anteriores
para preencher a tabela por backfill nesta instalação. A cópia de segurança da base
está em `planning-before-022.sql` na pasta de reversão indicada acima.
