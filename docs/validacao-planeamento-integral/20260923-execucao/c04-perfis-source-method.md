# C04 — Quantidades, propriedades e saldos negativos

24/09/2026. Revisão `c6367c4ac3d89afcc23eacd2829354a335b64b67a7ec45522155600d4ddc12a7`,104 ficheiros. Apenas `scripts/audit_planning_excel_comparison.py` e `tests/test_planning_excel_comparison.py` mudaram relativamente à revisão95e3fc1 da aplicação. Manifesto anterior conservado em `execution-manifest-c04-results-validated.json`. Não houve alteração de dados, reconstrução, migração, reinício ou alteração de serviço operacional.

## Método

- F16: conferir AH(quantidade estruturada),N(legada),AM/Q(comprimento) e a fórmula literal BR=N×Q. O cache tem de coincidir com N×Q; o resultado atual tem de coincidir com AH×AM. Justificados24 confrontos(12 linhas em mm e metros). Zero numérico é preservado pelo leitor de entradas do auditor, incluindo N=0.
- F09: a área unitária é independente da quantidade. Resolver novamente dimensões/VBA ou catálogo completo original; confirmar as entradas tipadas. Nas famílias geométricas, AG não é uma entrada da fórmula e pode ser uma designação composta a partir das dimensões. Nas famílias de catálogo, a correspondência da designação é obrigatória. A fórmula literal AX=IFERROR(IF(AH="","",AP/AH),0) explica67 caches zero com Q=0 e um cache vazio com quantidade ausente; a propriedade atual corresponde à resolução independente.
- F09/F10:180 resultados sem correspondência exata de área passam de cache zero a desconhecido, com fórmula original de fallback zero e consulta independente do catálogo. A ausência/divergência não recebe uma propriedade aproximada. Dimensões em falta e referências deslocadas que ainda não têm explicação completa continuam pendentes.
- F07/F10/F18/G03/G05: a passagem de resultado negativo para zero exige quantidade e produção numéricas originais iguais às selecionadas, excesso correto e saldo antigo reconstruído. Para perfis inteiros, reconstruir ROUNDUP negativo afastando de zero, com stock e comprimento originais. Para área pendente, resolver propriedade independentemente e verificar AX. Para metros de Cantoneiras, conferir metros totais/produzidos e a fórmula estruturada BK. Um cache negativo e resultado atual zero já não bastam para justificar a diferença; casos sem estas provas regressam à lista pendente.

Nenhuma função de cálculo da aplicação é usada como resultado esperado. A seleção e associação OCR continua fora desta auditoria; contadores diferentes não são automaticamente aceites. Não se alteraram testes para aceitar divergências da aplicação.

## Resultados e reprodução

`c04-perfis-source-auditor-tests-final.log`:43 testes passaram em0,04s. Inclui rejeição de alterações de quantidade, produção, excesso, dimensão, propriedade, fórmula, cache e resultado. Comando: `.venv/bin/python -m pytest -q tests/test_planning_excel_comparison.py`. São testes do auditor, não nova regressão completa da aplicação.

`PYTHONPATH=. .venv/bin/python scripts/audit_planning_excel_comparison.py --population-proof c04-result-columns-population --output c04-perfis-source-final` percorreu966573 resultados/83152 peças. Termina com código1 e1797 diferenças pendentes(486Perfis/1311Cantoneiras),menos793 líquidos que os2590 anteriores. Ambos os ledgers completos e hashes estão no JSON. As250981 indisponibilidades auditadas mantêm motivo. A aritmética de23 regras passou na prova de população inalterada; estas justificações não aprovam as outras20 regras nem C01/C02.

Perfis ainda pendentes:saldo101,quantidade prevista62,percentagem corte105,área unitária12,área total15,área pendente62,barras101,peso26,semana2. Cantoneiras:saldo338,quantidade prevista338,metros pendentes334,peso301. A lista completa identifica cada campo/peça e as células pertinentes.

A tentativa intermédia `c04-perfis-source-comparison.json` conserva2368 diferenças,antes da correção do leitor numérico zero,paridade das entradas geométricas e verificação ampliada dos negativos. Não é a prova final. `c04-perfis-source-classification-delta.json` compara as listas anterior/final,contando separadamente novas justificações e casos reabertos pela exigência de prova mais forte.

`c04-perfis-source-final-state.json` confirma104 hashes,27 tracked preexistentes preservados,fontes e ledgers com hashes conferidos,gerações3543/3544 iguais,servidor isolado1507575 e processos operacionais239043/239069 iguais. Checklist mantém13 checkpoints,58 critérios,43 regras e6 casos obrigatórios. Nenhum checkpoint global aprovado; publicaçãoC12 por executar.
