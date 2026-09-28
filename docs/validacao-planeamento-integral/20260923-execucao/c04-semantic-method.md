# F01, F21 e G12 — Descrições, prazo e detalhe dos cálculos

A auditoria independente confere as 83 156 peças das gerações 4275/4276, incluindo histórico e oito peças locais. Reconstrói a descrição a partir dos factos técnicos conhecidos, compara os elementos textuais e numéricos e recalcula os saldos por operação usando quantidade necessária e contadores selecionados. Não chama as funções de cálculo da aplicação. A seleção/proveniência desses contadores continua dependente de C01/C02.

Foram verificadas 1 701 766 condições, sem diferenças. A comparação direta do texto original abrange 83 148 peças com origem única; as oito peças locais não têm original Excel para comparar. A origem, entradas, contrato v3 e motivos de indisponibilidade foram conferidos em toda a população. O resultado é relativo à data local de 24/09/2026; a impressão digital da projeção já inclui o dia local e agora também inclui a versão do motor. A prova por peça está em `c04-semantic-results-final-rows.jsonl.gz`, com hash no resumo JSON.

A descrição já não começa com um separador quando só há dimensões conhecidas. A descrição de Cantoneiras conserva texto atual, texto original e composição técnica separadamente. A explicação de prazos identifica a data considerada, a sua origem (execução/entrega), a data local e os saldos das operações. Valores desconhecidos não se tornam zero nem confirmam conclusão. Foram declaradas unidades fixas antes ausentes para número de perfis e campos de capacidade; taxas/unidades físicas dependentes do método não receberam uma unidade fixa fictícia.

A regressão afetada passou com 118 testes em 110,30 s, incluindo 11 casos novos de descrição esparsa, texto original/local, prazo, operação desconhecida, excesso, código 0, entrega, data inválida e unidades. Antes da correção, esses 11 casos falhavam. Os testes integrados usam PostgreSQL descartável.

No browser, a primeira prova útil revelou `[object Object]` nos saldos por operação. O detalhe agora apresenta os valores aninhados e rótulos em português. A prova final `c04-semantic-detail-verified.json` passou em Perfis e Cantoneiras, com zero erros JavaScript e duas capturas. A tentativa intermédia `c04-semantic-detail-final.json` passou em Perfis mas falhou ao procurar a referência C03-cantoneiras-1 com o ID de C03-cantoneiras-2. A API confirmou os dois IDs em `c04-semantic-browser-fixture.json`; corrigiu-se apenas a pesquisa do teste. As tentativas e os produtores anteriores foram preservados.

A reconstrução de RAW e capacidades manteve todos os valores numéricos e identidades das gerações anteriores 4259/4260. A única alteração de valor foi uma descrição vazia passar a nulo, com motivo explícito de indisponibilidade. Esta igualdade preserva os resultados numéricos existentes; não equivale a repetir a comparação histórica com todos os Excel. As fontes, dez necessidades locais/ligadas e 27 ficheiros tracked preexistentes foram preservados. As referências de código históricas do inventário C00 têm agora um delta em `c00-semantic-contract-delta.json`; as fontes Excel/VBA/SQL não foram alteradas.

Apenas o servidor isolado 18113 foi reiniciado. Os processos operacionais mantêm PID/comando. O JavaScript está num diretório partilhado: as portas 8113 e 18113 servem a mesma versão alterada, comprovada por SHA. Isso não constitui publicação do backend, migrações ou worker operacional. C12 continua por executar.

As três regras têm prova independente semântica, além das 23 regras com prova aritmética anterior. As 17 restantes fora destas auditorias são F02, F03, F12, F20, G01, G06, G07 e H01–H10. Não se aprova C04 integral nem a entrega: faltam esses âmbitos e as matrizes/fontes dependentes de C01/C02/C05/C10/C11/C12.

Comandos principais:

```
RUN_PG_INTEGRATION=1 .venv/bin/python -m pytest -q --tb=short tests/test_planning_description_deadline.py tests/test_planning_integral_calculations.py tests/test_raw_workspace.py tests/test_planning_fields.py tests/test_planning_needs.py tests/test_planning_capacity_preview.py
PYTHONPATH=. .venv/bin/python scripts/audit_planning_semantic_results.py --require-detail --output c04-semantic-results-final
PLANNING_CHECK_BASE=http://127.0.0.1:18113 PLANNING_TEST_ISOLATED=1 PLANNING_PROOF=c04-semantic-detail-verified node tests/planning_semantic_detail_browser.cjs
node --check app/web/static/raw_workspace.js
```
