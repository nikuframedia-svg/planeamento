# Interface do planeamento — resultado e próxima ação

A captura enviada pelo utilizador mostrava a leitura anterior da OF266229: o PDF tinha sido recebido, mas a dependência da matriz impediu a extração e o sufixo `/33` provocou uma confirmação desnecessária. A leitura atual contém `5877T5102`, 42 unidades de UPN50x38, comprimento 200 mm. Falta escolher o destino de corte.

## Problemas observados

- A etapa de leitura aparecia concluída a verde apesar de não ter encontrado peças.
- «Conferir identificação e distribuição» não indicava uma ação concreta nem explicava a origem do problema.
- O fluxo interno, a importação CPIS e a macro tinham mais destaque do que o resultado útil.
- O documento ocupava metade do espaço, começava na capa e competia com a tabela; a evidência de todos os campos aparecia aberta.
- A escolha de um destino exigia entrar no formulário completo da peça.

## Alterações

- Resumo inicial com referências encontradas, unidades e próxima ação específica. A conclusão da leitura e a preparação para produção são estados distintos.
- Escolha de Serrote ou Vanguard num diálogo próprio, sem opção escolhida previamente, sem nome, motivo ou confirmação dos restantes campos. Uma revisão concorrente mantém a proteção HTTP 409.
- OF fechada apresentada como consulta, com explicação curta e sem uma ação para resolver o encerramento.
- Dados CPIS e detalhes técnicos recolhidos. «Ver desenho» abre a página da peça selecionada; na OF266229, a página 2.
- Edição com campos principais primeiro; dimensões, operações e observações nos detalhes. Valores complementados pelo Plano são apresentados como valores efetivos e só os campos editados são enviados.
- Tipografia maior, unidades explícitas e tabela convertida em cartões no telemóvel.

## Verificação

Nove verificações no browser, incluindo escolha e edição através da API real numa cópia SQLite isolada. Sete testes Python dirigidos aprovados. Sem erros JavaScript ou transbordo horizontal a 390, 768, 1500 e 1920 px. Sintaxe JavaScript e `git diff --check` aprovados.

O endereço público respondeu HTTP 200 e foi verificado no browser. A máquina real da OF266229 continua por atribuir, com a revisão 25: as escolhas feitas durante os testes ficaram apenas na cópia isolada.

Resultados em [validacao.json](./validacao.json). Capturas: [resultado](./resultado-of266229.png), [escolha de destino](./escolha-destino.png) e [telemóvel](./telemovel-of266229.png).
