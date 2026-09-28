# F12 e H01/H02/H04–H08 — Reconciliação integral dos agregados

A auditoria `scripts/audit_planning_capacity_arithmetic.py` lê a cópia isolada em transação consistente e sem escrita. Não chama funções de cálculo de capacidade/produtividade da aplicação. Abrange as 23 494 operações publicadas, os 185 grupos recurso/semana e as 21 máquinas, deduplicando grupos partilhados entre áreas e verificando igualdade entre as cópias. Confirma também que cada operação corresponde a uma peça ativa e a um grupo existente.

A carga é somada a partir das horas publicadas de todas as operações. Se houver alguma hora desconhecida, o total integral permanece desconhecido; a cobertura e a soma parcial são conferidas separadamente. A disponibilidade é recalculada diretamente dos objetos de calendário confirmados e respetivo recurso (`turnos × horas por turno − indisponibilidade`), com identificação do calendário escolhido. Horas livres, ocupação, turnos equivalentes e capacidades físicas são calculados independentemente. Taxas em minutos/unidade são normalizadas; misturas de operações/unidades, taxas ausentes e preparação impedem um total físico incompatível.

F12 compara a ocupação agregada assim obtida com o valor repetido em cada uma das 18 981 operações principais ativas. A prova não usa a ocupação publicada como esperado. As versões são: RAW4275/4276; itens4277/4280; semanas4278/4281; máquinas4279/4282.

Resultado: **115 652 verificações, zero diferenças**. Há apenas oito grupos semanais com disponibilidade confirmada e seis peças com F12 conhecido (três por área). Os restantes 177 grupos semanais não têm disponibilidade confirmada; 18 têm carga incompleta. Entre as 21 máquinas, seis têm carga integral conhecida e 15 têm carga incompleta. Não se confundem ausências legítimas com milhares de exemplos numéricos completos. Os 22 estados e casos de zero/sobrecarga/unidades dos ensaios anteriores C09 complementam esta fotografia real.

O ledger `c04-capacity-arithmetic-current-rows.jsonl.gz` guarda as entradas por operação, calendários identificados, esperado e observado de cada grupo e comparação F12 por peça. O resumo contém o hash do ledger e da configuração completa consultada. Fontes e configurações foram reconferidas no estado final; nenhuma alteração de dados, aplicação ou processos foi feita nesta etapa.

A auditoria complementar `c04-semantic-capacity-parity.json` passou nas 83 156 peças, 18 981 operações principais e 105 conjuntos históricos. Confere a concordância RAW/capacidades e a aritmética dos conjuntos históricos já aceites. **Não valida independentemente a escolha ou exclusão desses conjuntos.**

Estas oito regras juntam-se às 23 regras aritméticas anteriores e três semânticas, mantendo limites de fonte e seleção explícitos. Continuam fora destas auditorias integrais: F02, F03, F20, G01, G06, G07, H03, H09 e H10. A escolha das operações/associações (C01/C02), o cálculo individual das horas (F20/G07), as horas reais únicas (H03), a seleção histórica e prioridade de taxas (H09/H10) continuam a exigir as provas próprias. C04/C10/C11/C12 não são aprovados por esta reconciliação.

Comandos:

```
PYTHONPATH=. .venv/bin/python scripts/audit_planning_capacity_arithmetic.py --output c04-capacity-arithmetic-current
PYTHONPATH=. .venv/bin/python scripts/audit_planning_productivity.py --output c04-semantic-capacity-parity.json
```
