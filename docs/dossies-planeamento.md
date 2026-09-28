# Dossiês de fabrico → preenchimento da macro

Implementação atualizada em 15 de setembro de 2026. A aplicação recebe os PDFs, pede a um modelo com visão a leitura da distribuição e dos desenhos, cruza os resultados com o CPIS e o catálogo técnico e produz uma **cópia conferível de `Met2_Plan_Perfis.xlsm`**. A entrada principal está em `/planeamento`; o formulário anterior continua em `/planeamento/manual`.

O conector está implementado e a API está ligada. A configuração atual e os resultados dos primeiros ensaios com modelos reais estão registados abaixo. Os testes automatizados usam respostas de modelo explicitamente simuladas e não representam uma medição de precisão nos dossiês.

## Ligar a API

1. Abrir a aplicação no computador onde corre o servidor: `http://127.0.0.1:8113/planeamento` no arranque independente usado neste projeto, ou `/planeamento` na porta da aplicação principal.
2. Abrir **Ligação ao modelo**.
3. Preencher o endereço base, o identificador de um modelo com visão e a chave.
4. Escolher **Chat Completions (compatível)**, **Responses** ou **Amazon Bedrock (Converse)**, conforme a API.
5. Guardar e usar **Testar leitura de imagem**. O teste envia apenas uma imagem com um texto de exemplo.
6. Usar **Processar PDFs pendentes**. Novos PDFs carregados depois de configurar a API entram automaticamente na fila.

Nos formatos compatíveis, o endereço base inclui o prefixo da API, como `https://api.exemplo.com/v1`. O conector acrescenta `/chat/completions` ou `/responses` quando o sufixo não está já presente. A autenticação usa `Authorization: Bearer`. APIs com outro protocolo/autenticação precisam de um adaptador; não é assumida compatibilidade com qualquer endpoint HTTP.

Para **Amazon Bedrock Runtime**, escolher `Amazon Bedrock (Converse)`, indicar o endpoint regional (por exemplo, `https://bedrock-runtime.eu-central-1.amazonaws.com`) e o identificador de um modelo com visão ou perfil de inferência. Um exemplo é `eu.anthropic.claude-sonnet-4-6`, com entrada em Frankfurt e encaminhamento dentro da região geográfica europeia. A disponibilidade efetiva depende das permissões da conta. O conector envia as imagens em base64 na API Converse e usa a chave Bedrock no cabeçalho Bearer, conforme a [documentação da AWS](https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys.html) e o [formato Converse](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html).

A configuração atual, pedida pelo utilizador, é **Grok 4.6 no Bedrock Mantle**: região `us-west-2` (Oregon), modelo `xai.grok-4.6`, formato `Chat Completions` e endereço base `https://bedrock-mantle.us-west-2.api.aws/openai/v1`. O conector acrescenta `/chat/completions`; mantém-se a chave Bedrock em Bearer. A [ficha oficial da AWS](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-xai-grok-4-6.html) indica Oregon para este modelo no Mantle. A consulta ao catálogo de Oregon confirmou `status=available` e a inferência real terminou com HTTP 200.

O nível de raciocínio está em `high`, com 24 000 tokens de saída e até 600 segundos de espera por pedido. **Ligação ao modelo** permite escolher o nível de raciocínio suportado pelo fornecedor; vazio conserva o predefinido desse modelo. Em Responses é enviado `reasoning.effort`; em Chat Completions, `reasoning_effort`. O conector Converse continua a usar os parâmetros predefinidos de raciocínio. Os limites `timeout_s` (10–900) e `max_tokens` (256–128000) podem ser guardados pelo endpoint de configuração; o limite efetivo continua a depender do modelo. Um timeout de leitura não repete automaticamente uma inferência que pode ainda estar a correr no fornecedor. Uma resposta marcada pelo fornecedor como incompleta por limite de tokens é rejeitada mesmo quando o texto visível parece ser JSON completo.

Uma API local pode usar `http://127.0.0.1:porta/v1`, sem chave. Uma API remota deve usar HTTPS. O conector envia páginas renderizadas como imagens e também o texto nativo do PDF quando existe; não exige um programa de OCR separado.

A chave fica no servidor, em `MES_DATA_DIR/dossiers/model.json`, criada com permissões 0600 em Linux. Nenhum endpoint devolve a chave. Ao alterar o modelo, deixar a chave vazia mantém a anterior. A configuração através de um endereço público exige o código `MES_ADMIN_TOKEN` do servidor; a configuração pelo endereço local não exige esse código. Não se deve enviar a chave na conversa ou no URL.

Também se pode configurar pelo ambiente, em alternativa à página:

```dotenv
MES_DOSSIER_API_URL=https://api.exemplo.com/v1
MES_DOSSIER_MODEL=identificador-do-modelo-com-visao
MES_DOSSIER_API_KEY=preencher-no-servidor
MES_DOSSIER_API_FORMAT=chat_completions
MES_DOSSIER_REASONING_EFFORT=
```

Quando algum destes valores é definido no ambiente, a edição pela página fica desativada, para haver uma única origem de configuração. Reiniciar o servidor depois de alterar o ambiente. As chaves existentes do OCR kanban (Gemini, Claude ou Qwen) não são utilizadas automaticamente por este conector.

Os formatos de imagem e os dois protocolos seguem a [documentação oficial de visão da OpenAI](https://developers.openai.com/api/docs/guides/images-vision#analyze-images). A saída do modelo é validada localmente contra esquemas Pydantic; respostas truncadas ou incompatíveis não originam linhas aceites. Para servidores compatíveis antigos, o limite `max_completion_tokens` é trocado por `max_tokens` apenas se a API recusar explicitamente esse parâmetro.

No Grok 4.6 através de Mantle, o conector atual de Chat Completions força uma única chamada à função de saída `record_result`, cujo contrato contém o esquema da leitura. Apenas os argumentos dessa chamada são usados; texto explicativo adicional é ignorado. A aplicação não executa ações solicitadas pelo modelo. Nomes inesperados, chamadas múltiplas, recusas e respostas truncadas são rejeitados. O conector Responses conserva `text.format` com esquema nativo. A validação local continua obrigatória em ambos, incluindo quantidades, campos permitidos e evidência; `finish_reason=length` rejeita toda a resposta e mostra explicitamente o limite atingido.

Nos ensaios da OF263785, os modos de saída textual `strict/json_schema` e `json_object` entraram em ciclos de repetição até 24 000 tokens. A chamada de função concluiu a página 27 em 15,8 segundos no ensaio e em 31,3 segundos na fila. Depois da adaptação, o inventário concluiu as 75 páginas e a extração terminou as três peças, conforme a validação abaixo.

Nos ensaios reais, houve respostas com vários objetos JSON concatenados mesmo com `strict`. Quando todos os objetos estão completos e são semanticamente idênticos, a aplicação remove apenas as repetições e valida normalmente o único resultado. Uma diferença, texto adicional ou fragmento torna a resposta ambígua e dá origem a **uma única nova leitura** com uma instrução de correção; os conteúdos diferentes não são cortados, fundidos ou aproveitados parcialmente. Se a repetição falhar, ficam os checkpoints anteriores e a leitura para. Respostas truncadas por limite de tokens, timeouts e erros de acesso não usam esta repetição de formato.

## Utilização

Carregar um ou vários PDFs em **Adicionar dossiês de fabrico**. O limite é 80 MB e 250 páginas por PDF. Os ficheiros originais são conservados. Um PDF repetido reutiliza o dossiê já recebido; se o mesmo conteúdo vier com outra OF no nome, a aplicação assinala a identificação incompatível.

Sem API, os PDFs ficam em **Aguarda API**. Com API, passam pelas seguintes etapas:

1. Inventário do conteúdo de todas as páginas, incluindo matriz, lista de corte, desenhos, capa, orientação, referências, aliases e seleções explícitas.
2. Criação de itens de trabalho independentes da máquina. Uma matriz aplicável continua a determinar as referências abrangidas; na sua ausência, uma linha preenchida de lista de corte ou um desenho com quantidade explícita pode criar o item.
3. Associação de listas, desenhos e notas pela referência e pelos aliases, seguida da leitura detalhada dos campos e da evidência. A associação impede que a mesma peça seja contada duas vezes.
4. Consulta da OF no CPIS, das linhas da mesma OF no Planeamento e de um histórico limitado às referências encontradas. Os valores efetivos conservam a origem de cada campo.
5. Resolução do material e da máquina quando existe correspondência segura; os restantes campos aparecem como dúvidas localizadas antes da preparação da saída.

A fila guarda checkpoints por página e desenho, ligados ao hash do PDF e às versões do modelo, instruções, esquema e preparação visual. **Retomar leitura** aproveita apenas os passos compatíveis. Uma troca de contrato arquiva os resultados derivados anteriores e volta a validá-los com a nova configuração.

No conector atual do Grok, o inventário lê uma página por pedido. Uma resposta truncada continua a ser rejeitada; a página recebe uma única segunda leitura com instrução compacta e sem ampliações adicionais. Nos outros conectores, um lote inconsistente é decomposto por página. Timeouts não são repetidos automaticamente, porque o fornecedor pode continuar a executar o primeiro pedido. Rede, quota, acesso, servidor, filtro de conteúdo, formato e limite de saída aparecem como causas distintas.

Cada tentativa conserva duração, identificador do fornecedor, motivo de conclusão e contagens de tokens, sem pedido, resposta, cabeçalhos de autenticação ou credenciais. A interface mostra um resumo da última tentativa quando há uma interrupção.

É possível **reler apenas a página atual** ou **reler um desenho**. A primeira ação conserva os restantes inventários e invalida associações dependentes; a segunda conserva inventário e ligação, mas reconstrói todas as variantes obtidas na mesma leitura. Ambas executam diretamente, arquivam o resultado anterior e registam automaticamente a ação. A releitura integral continua disponível para uma mudança mais ampla.

As imagens enviadas ao modelo incluem sempre a página inteira e, quando necessário, ampliações de grelhas, cartuchos, qualidade, quantidade e cotas. A orientação indicada pelo inventário é passada à preparação; quando não está determinada, a ampliação conserva a orientação original. A aplicação não roda uma lista apenas por a região ter forma de retrato. Uma matriz compacta pode receber uma única vista complementar a 90°, porque um eixo contém por vezes as máquinas e o outro referências impressas verticalmente; a legenda identifica-a como a mesma região, sem duplicar quantidades. Matrizes que ocupam quase toda a página também podem ser segmentadas com sobreposição e repetição geométrica da faixa de cabeçalho. A legenda conserva a ligação entre as coordenadas da vista transformada e a região normalizada na página original. A deteção usa OpenCV e não contém referências, máquinas ou respostas esperadas; os recortes não alteram o PDF e o pedido continua limitado a vinte imagens.

Quando uma referência aparece numa lista e num desenho próprio, os dois blocos são associados ao mesmo item. A origem da seleção fica registada separadamente das páginas usadas como apoio. Uma matriz tem precedência para as referências que abrange; sem matriz aplicável, apenas linhas explicitamente preenchidas e desenhos com informação de fabrico inequívoca são selecionados. Formulários vazios, quantidades de produto na capa e variantes de catálogo não se transformam em necessidades. Empates entre páginas igualmente específicas continuam a exigir uma escolha.

Cada linha principal mostra **referência, perfil, quantidade, comprimento, máquina e estado**. A página apresenta o valor efetivo e a sua origem curta; leitura original, evidências, catálogo, histórico e diferenças ficam nos detalhes. Uma correção ou escolha pode ser guardada diretamente, sem nome nem justificação obrigatórios. Nas divergências, as escolhas **Usar PDF** e **Manter plano** ficam ligadas aos valores, à evidência e à linha do plano efetivamente apresentada; qualquer alteração relevante volta a abrir apenas essa dúvida. O histórico conserva data, valores anteriores e seguintes, revisão e uma descrição automática da ação.

O perfil literal nunca é substituído na extração. O resolvedor usa `AreaSecaoCorte` da mesma versão da macro e só aceita uma equivalência única. Por exemplo, pode conservar `UPN80` no PDF e preparar `Perfil U / UPN80x45` para a macro. Candidatos múltiplos ou ausência no catálogo bloqueiam a saída. Dimensões de tubos podem ser derivadas deterministicamente de uma secção como `114x3`; a resolução identifica essa origem e verifica espessuras geometricamente impossíveis.

Uma linha indevidamente incluída pode ser excluída diretamente; a extração original e a alteração permanecem no histórico. O sistema volta a comparar o total das linhas ativas com a quantidade do índice depois de corrigir ou excluir variantes. Alterações de especificação quando já existe produção registada bloqueiam a escrita dessa revisão na macro até à reconciliação operacional.

## Entrada por pasta

Opcionalmente, configurar uma pasta **exclusiva de dossiês de fabrico**:

```dotenv
MES_DOSSIER_INBOX=/caminho/para/dossies
```

O servidor verifica a pasta a cada 15 segundos, espera que os ficheiros estejam sem alterações há pelo menos 10 segundos e importa até dez ficheiros novos/alterados por passagem. A pesquisa não é recursiva. A assinatura do ficheiro impede importações repetidas. Falhas de abertura e PDFs inválidos aparecem na página. Esta pasta é independente da entrada de folhas kanban.

## O que é preenchido na macro

O adaptador confere os cabeçalhos da linha 6 da folha `Planeamento`. As colunas de entrada são:

| Coluna | Informação |
|---|---|
| E | OF |
| L | Referência da peça/variante |
| AF–AM / AO | Tipo, chave de perfil, quantidade, diâmetro/largura/altura/espessura, comprimento e qualidade |
| AN | Preservada. Os ângulos documentais ficam nas observações enquanto a convenção da máquina não estiver definida. |
| T | Indicação de abocardar explicitamente sustentada pelo desenho |
| U | Chanfro apenas depois de confirmar a equivalência entre a indicação técnica e `Chanf.` |
| AQ | Vanguard, apenas quando existe uma correspondência única no catálogo de máquinas |
| AT | Origem do PDF, páginas, operações e observações |
| A | Identificador novo, apenas nas linhas acrescentadas |

Cliente, OV, designação e data CPIS continuam ligados às fórmulas existentes. A coluna AE (ponteira) também é calculada na macro atual: preserva-se a fórmula e guarda-se a indicação documental em AT. A distribuição genérica **Serrote** não escolhe automaticamente um serrote concreto. Não se calculam datas, capacidade ou tempos nesta entrega.

Quando a referência já existe e coincide, a linha não é repetida. Ainda assim, pode receber Vanguard em AQ, proveniência ou operações em falta. Uma máquina concreta já atribuída é preservada; uma incompatibilidade entre essa máquina e o PDF bloqueia a saída. Campos vazios podem ser completados a partir de valores sustentados pelo PDF. Diferenças preenchidas precisam de conferência; uma revisão ou mudança de encaminhamento não acrescenta outra necessidade física. Referências fisicamente distintas com o mesmo texto exigem um discriminador explícito.

**Descarregar macro preenchida** começa por voltar a consultar o CPIS e verificar o hash do ficheiro de origem. A aplicação mostra linha, célula, valor anterior, valor proposto e motivo. Essa proposta fica auditada e vinculada ao download; se mudar entretanto, é necessário conferir uma nova comparação.

O adaptador valida todos os cabeçalhos que pode escrever e limita as alterações a A, E, L, T/U, AF–AM, AO, AQ e AT. Gera uma cópia XLSM por alteração localizada do XML, preservando VBA e os restantes membros. As fórmulas são mantidas/prolongadas; os caches das linhas alteradas são limpos e é pedido recálculo completo. **Abrir a cópia no Excel para recalcular antes de a integrar no processo normal.** Não há avaliação de VBA no servidor.

As quantidades executadas, datas de produção e expedições existentes são preservadas. A aplicação não sobrescreve o ficheiro original nem escreve nas tabelas importadas do CPIS. Também existe uma saída CSV das linhas, com proteção de campos de texto contra interpretação como fórmulas.

## Arranque e persistência

Instalar as dependências a partir do lockfile e arrancar o módulo independente:

```bash
uv sync --extra dev
.venv/bin/uvicorn app.web.planning_app:app --host 127.0.0.1 --port 8113 --env-file .env
```

O módulo também está integrado no arranque da aplicação principal. Há locks entre processos, com implementações para Linux e Windows, para impedir que os dois servidores processem o mesmo dossiê simultaneamente. `MES_DOSSIER_WORKER_DISABLED=1` desativa a fila e a observação da pasta em processos de teste.

Estado persistente em `MES_DATA_DIR/dossiers/`: PDFs originais, SQLite com documentos, execuções, checkpoints atuais e arquivados, tentativas do modelo, linhas, decisões e propostas/exportações, configuração do modelo e locks. A migração é aditiva; resultados antigos sem contrato de processamento ficam sujeitos a revalidação na próxima leitura. Incluir este diretório nos backups. A funcionalidade usa o PostgreSQL existente apenas para leitura; não precisa de nova migração no CPIS nem de uma linha prévia na folha Planeamento.

## Verificação e limites

Os testes cobrem entrada de PDFs, deduplicação, retoma compatível, releitura seletiva, contratos HTTP dos três formatos, segredo da API, diagnóstico seguro por tentativa, limite de saída com repetição compacta, controlo de origem, resolução do catálogo, requisitos geométricos por família, validade das decisões, OF ausentes do plano, revisão de quantidades, identidade física, produção existente, substituição de revisões, comparação por célula e preservação da macro. A interface foi verificada em desktop e telemóvel.

Verificação de 15/09/2026: a suite completa do repositório terminou com **589 testes aprovados e 9 ignorados**. Abrange lista de corte e desenho isolado sem matriz, formulários vazios, precedência da matriz, associação sem duplicação, orientação, referências normalizadas, proveniência do plano e catálogo, máquina por resolver, ações sem autor/motivo e preservação da macro. A migração aditiva e a base publicada passaram `integrity_check` e a verificação de chaves estrangeiras. A configuração pública continua sem expor a chave do fornecedor.

A verdade conferida dos cinco PDFs está congelada em `tests/fixtures/dossier_reference_2026-09.json`. O corpus contém **12 necessidades e 323 peças**: 212 Vanguard, 69 Serrote e 42 ainda sem máquina. As três OF anteriores conservam as 10 necessidades e 276 peças da regressão original. O comparador separa a leitura documental atual dos valores técnicos complementados e recebe uma captura JSON com os documentos e respetivas peças:

```bash
.venv/bin/python scripts/evaluate_dossier_reference.py --actual captura-dossies.json --report relatorio.json
```

Este corpus deteta omissões, inclusões, identidades repetidas e diferenças na leitura literal, nos valores efetivos, no destino, no comprimento, na quantidade, na qualidade e na página. A captura final da API pública passou sem diferenças. O [relatório da execução real](./validacao-dossies-reais-2026-09-15.json) regista estados, proveniência, tentativas, publicação e bloqueios, sem credenciais. Continua a ser um conjunto conhecido, preparado a partir de conferência humana, e não mede precisão fora da amostra.

Foi gerada uma cópia de teste da macro real com as duas linhas já conferidas da OF265931 (6 × tubo 114×3×1200 e 6 × tubo 60×3×1760). O VBA e os restantes membros ZIP não alterados foram comparados byte a byte. O original manteve o seu hash. Este teste valida o adaptador da macro; não valida a leitura autónoma de um modelo. O recálculo no Excel e a execução na instalação Windows ainda precisam de conferência nesse ambiente.

Em 15/09 foi ainda gerada `data/dossiers/exports/Planeamento_validacao_10_necessidades_20260915.xlsm` com as dez linhas da referência: duas novas e oito enriquecidas. Foram conferidas 75 células de tubo redondo, varão redondo, UPN e HEB; o segundo ficheiro gerado foi byte a byte idêntico, o VBA ficou idêntico e apenas `xl/workbook.xml` e a folha Planeamento mudaram. O [relatório estrutural](./validacao-macro-dossies-2026-09-15.json) regista hashes, colunas e limites. Essa cópia foi construída sobre a origem `aa2d59…`; a sincronização posterior importou `bb7d77…`, pelo que a cópia fica apenas como prova estrutural e não deve ser usada como proposta do plano atual. O recálculo no Excel Windows continua a ser uma condição separada.

Na configuração inicial com Claude Sonnet 4.6 através de Frankfurt, em 14/09/2026, a AWS respondeu **HTTP 429 — `Too many tokens per day`**, tanto para Sonnet 4.6 como nos pedidos mínimos de diagnóstico com Sonnet 4.5 e Nova Pro. Este resultado não permite concluir se a quota foi consumida ou se a conta tem uma quota inicial reduzida/indisponível. A aplicação identifica este limite diário e não repete imediatamente o pedido.

No teste posterior, com **Sol no Mantle em `us-east-1` e a mesma chave por instrução expressa do utilizador**, o pedido com uma imagem de teste chegou ao endpoint correto e devolveu **HTTP 401**, código `access_denied`, tipo `permission_denied_error`. A mensagem da AWS afirma que `openai.gpt-5.6-sol` não está disponível para esta conta e remete para AWS Sales para opções de acesso. O [diagnóstico guardado](./diagnostico-api-mantle-2026-09-14.json) contém endpoint, identificador do pedido e a mensagem completa, sem credenciais. Este erro é distinto do limite diário anterior; não se alteraram políticas IAM, permissões ou faturação. A aplicação apresenta a indisponibilidade do modelo para a conta sem divulgar o diagnóstico bruto do fornecedor.

O utilizador forneceu depois uma nova chave, que substituiu a anterior no servidor. O teste com essa chave, o mesmo endpoint e o mesmo modelo voltou a devolver **HTTP 401 — `access_denied`**, com a mesma mensagem de indisponibilidade para a conta. O [diagnóstico com a nova chave](./diagnostico-api-mantle-chave-nova-2026-09-14.json) regista a resposta completa sem credenciais.

Depois de autorizada a troca de modelo, Qwen3 VL 235B, Mistral Large 3 e Kimi K2.5 responderam à inferência no Mantle. Os primeiros ensaios com a capa da OF265931 revelaram respostas incompletas ou associações erradas das cruzes da distribuição. Não foram aceites como necessidades para a macro. A tentativa da fila com Qwen ficou interrompida no primeiro lote, sem linhas criadas.

O ensaio com **Grok 4.6 / xhigh**, nas páginas 1 e 2 da OF265931, terminou em 381 segundos com saída conforme o esquema. Identificou a ausência da coluna Vanguard, mas deixou a associação das cruzes de serrote em dúvida e devolveu `routes=[]`. Isto confirma a ligação e a leitura parcial, **não uma extração completa ou correta do dossiê**. O [diagnóstico do ensaio](./diagnostico-grok-4-6-oregon-2026-09-14.json) conserva a saída, a configuração, a duração e o consumo, sem credenciais. A [comparação dos modelos](./comparacao-modelos-visao-2026-09-14.md) distingue os benchmarks públicos destes ensaios locais.

O teste seguinte, com a mesma capa na orientação de leitura e a matriz ampliada, identificou corretamente **CI23JJ01 e CI23JJ02 para serrote**, sem outras referências. Terminou em 69 segundos; o [diagnóstico](./diagnostico-grok-4-6-detalhe-2026-09-14.json) distingue este ensaio com recorte manual de uma extração automática completa. A preparação automática de pormenores foi integrada depois deste resultado. A versão atual conserva todas as páginas originais, deteta grelhas depois de rotações de digitalização e segmenta matrizes grandes sem enviar quatro cópias rodadas do mesmo recorte.

Depois dos ajustes de integração descritos acima, a fila normal concluiu as **nove páginas reais da OF265931**. O inventário automático selecionou apenas `CI23JJ01` e `CI23JJ02` para serrote, sem Vanguard. A leitura dos desenhos produziu, sem correção manual de campos, `CI25J001` — 6 × tubo redondo 114×3×1200, S275JR — e `CI25J003` — 6 × tubo redondo 60×3×1760, S275JR. O CPIS confirmou OF265931, OV2607672, ECLIPSE DIFFUSION, estado Em Aberto e ausência de linhas prévias no plano. O [registo da extração final](./diagnostico-grok-4-6-conclusao-2026-09-14.json) conserva as respostas do fornecedor sem credenciais.

A aplicação gerou `data/dossiers/exports/Planeamento_OF265931_Grok46_20260914.xlsm`, acrescentando as duas necessidades nas linhas 7000–7001. A [validação da saída](./validacao-of265931-grok-2026-09-14.json) confirma as células, o hash inalterado do original, o VBA idêntico e que apenas a folha Planeamento e a opção de recálculo do workbook mudaram; todas as outras linhas e membros ZIP ficaram byte a byte iguais. O recálculo no Excel continua por verificar no ambiente Windows.

A validação final da **OF263785** inventariou as 75 páginas e extraiu `1234.T.120` (36 × 480 mm), `1234.T.121` (36 × 346 mm) e `1234.T.122` (36 × 500 mm), todas UPN80 e S355J2. As listas de conjunto ficaram como apoio e as páginas de desenho são exclusivamente 32, 33 e 34. A leitura de `T.121` mostrou instabilidade entre 68° e 98° em repetições independentes; a aplicação nunca escreveu esses valores em AN, passou a assinalar ângulos de extremidade diferentes e a nota ativa foi corrigida para 68° em ambas as extremidades por uma ação auditada. O snapshot atual marca as linhas 6963–6965 como fechadas e deixa a quantidade de entrada vazia, além de a continuação da matriz na página 2 não mostrar cabeçalhos. Estes bloqueios mantêm o dossiê em **Conferir** e impedem a exportação.

A **OF265931** concluiu as 9 páginas e produziu exatamente as duas variantes de serrote: `CI25J001`, 6 × tubo 114×3×1200, e `CI25J003`, 6 × tubo 60×3×1760, ambas S275JR. Uma execução esgotou as duas tentativas do índice e outra atingiu timeout numa extração; as páginas e a primeira peça ficaram guardadas, a retoma não duplicou o pedido temporizado e completou apenas o passo pendente. A identificação literal `OF265931/26` fica conservada, mas deixou de exigir confirmação depois de a OF base coincidir com o ficheiro e o CPIS. O dossiê está **Preparado**.

A **OF265941** concluiu integralmente as 17 páginas e as cinco necessidades: `pr.3` (52 × R80×539 para serrote) e `pr.4`, `pr.5`, `pr.8`, `pr.9` (26 unidades cada de HEB320, com 12 450 ou 13 450 mm, para Vanguard), todas S355J2. A capa e a grande matriz deixaram de interromper o dossiê. A identificação `OF265941/33` fica conservada sem uma confirmação de sufixo; a interpretação de `pr.3` como barra redonda R80 face ao tipo `Varão redondo` do plano continua visível como a dúvida técnica concreta.

A **OF260221** confirmou o caminho sem matriz: a primeira linha preenchida da lista de corte originou uma única necessidade `CI.77/12.A4.002`, 5 × tubo `Ø 2″ S.L` × 170, S235JR. As linhas impressas mas vazias não foram selecionadas. A leitura original do modelo confundiu o comprimento manuscrito com 190 e o símbolo do perfil; a conferência visual corrigiu os valores através da API, preservando a resposta e o evento anteriores. A referência normalizada encontrou a linha 1556 da mesma OF e completou o valor efetivo `60.3x2.9`, diâmetro 60,3, espessura 2,9 e **Serrote Fita Thomas IS639 Pav.1**, todos com proveniência do plano. `OF260221/35` ficou conservada como identificação documental coerente. Como o CPIS e a linha estão fechados e já têm 5 unidades produzidas, a peça permanece consultável e não origina uma nova necessidade operacional.

A **OF266229** confirmou o desenho isolado sem matriz: a página 2 originou uma única necessidade `5877T5102`, 42 × 200 mm, S355J2, com secção 50 × 38 e as operações de dois furos Ø14 e recorte. As 5 unidades da capa não substituíram nem multiplicaram as 42 peças do desenho. As cotas selecionaram unicamente `UPN50x38` no catálogo e rejeitaram o histórico `UPN50x25`; nenhuma quantidade ou produção de outra OF foi copiada. A OV do CPIS pertence à lista de cinco OV do PDF, e `OF266229/33` foi associada à OF base sem divergência. A única decisão pendente é a máquina: os registos geometricamente compatíveis não têm uma atribuição, por isso a aplicação mostra **Por atribuir** em vez de copiar o serrote de uma geometria diferente.

Estes ensaios não constituem uma medição estatística de precisão para todos os formatos. O motor de sequência, capacidade e datas continua a ser a etapa seguinte, alimentada por necessidades estruturadas já verificadas.

Antes do uso regular, o piloto deve reservar pelo menos 20 dossiês novos e 100 necessidades que não tenham sido usados para ajustar a extração. O registo do piloto mede omissões/inclusões, erros críticos não sinalizados, linhas sem correção humana, duração, consumo do fornecedor e tempo de conferência. A aceitação exige zero erros críticos silenciosos, zero omissões ou inclusões indevidas sem alerta, pelo menos 70% das linhas sem correção de campos e evidência compreensível nas restantes. A cópia XLSM tem ainda de ser aberta no Excel Windows com as funções da instalação para confirmar o recálculo de tubos, redondo, UPN e HEB.
