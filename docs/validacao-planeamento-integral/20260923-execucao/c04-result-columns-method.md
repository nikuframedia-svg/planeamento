# C04 — Resultados visíveis e pesos exatos

Revisão `95e3fc1f9c9f01e5e8b865f4e49063066eb40a7849d7bf796a370a1da6ef0f70`,104 ficheiros,24/09/2026. Cópia isolada `planning_integral`,porta18113; gerações3543/3544 inalteradas. Não houve reconstrução ou alteração de dados nesta etapa.

O contrato RAW expõe peso unitário, metros totais e excesso nas duas áreas; área pendente em Perfis e saldo da segunda operação em Cantoneiras. São oito campos adicionais apenas de leitura,137 campos no total. O detalhe mostra valor atual, fórmula, entradas/unidade, origem e motivo. Cantoneiras conserva o peso Excel original separado do atual em Dados e origem.

A auditoria independente passou de717117 para966573 verificações em83152 peças,23 regras. Acrescenta os campos acima e resolve o contador secundário pela operação selecionada. Zero diferenças aritméticas;493 casos de catálogo/20 famílias. A seleção/associação dos contadores continua sujeita a C01/C02.

A comparação com Excel verifica designação e comprimento originais, consulta a Tabela pesos completa e confere ambos os resultados antes de justificar uma diferença. Exemplo OF264345/DLT304: L100X100X10,3635mm,Tabela pesos!C7=15,1kg/m,resultado54,8885kg. O cache46,528kg implica12,8kg/m de outra designação. Correspondência ausente/divergente permanece desconhecida. Não se aceitam diferenças de contador ou resultados arbitrários como explicação automática.

Foram justificadas16333 diferenças por ausência de propriedade exata e1290 por procura aproximada antiga,22 por perfil vazio e2 por quantidade/comprimento vazios. No âmbito antigo restaram2368 diferenças; o âmbito ampliado inclui mais222 e conserva2590(1069Perfis/1521Cantoneiras). Não são2590 erros comprovados da aplicação: são confrontos por investigar. O comparador termina com código1. Todos os250981 resultados indisponíveis auditados têm motivo. C04 permanece incompleto, assim como20 regras fora desta auditoria e os restantes critérios integrais.

Provas: `c04-weight-columns-tests.log`(95 testes,49,11s); `c04-excel-weight-auditor-tests-final.log`(12 sobrepostos); `c04-result-columns-population.json`; `c04-result-columns-excel.json` e ledgers completos; `c00-result-columns-inventory.json`.

Browser: três amostras, oito campos, pesquisa/paginação, valores na grelha e no detalhe, origemC7/densidade7850, resultado indisponível e edição impedida; zero erros JavaScript. `c04-result-columns-browser.json` contém resultados. Captura `c04-result-columns-cantoneiras-known-origin.png` inspecionada:54,8885 atual e46,528 importado. `c04-result-columns-exports.json`:seis CSV/XLSX na mesma publicação,comparados com valores esperados independentes; desconhecidos vazios. Hash da fixture final e dos seis ficheiros verificados.

`c04-result-columns-final-state.json`:104 hashes atuais,27 tracked preexistentes preservados,processos operacionais239043/239069 iguais,servidor isolado1507575. Nenhum worker isolado iniciado. Kanbans operacionais intocados. Checklist contém as oito provas; nenhum checkpoint global aprovado.
