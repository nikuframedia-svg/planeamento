# OCR original no motor de Planeamento

Foi confirmada uma lacuna funcional independente do acesso ao Windows: a fonte original era publicada apenas numa consulta separada, sem alimentar as operações. Esta etapa liga os snapshots centrais ao cálculo comum, à deteção incremental, à evidência do formulário e ao diagnóstico de cada registo.

Identidade de evento: `original:<instância>:<folha>:<linha>`. A origem continua `ocr_original`; não se escrevem factos na base MES. Revisão e hash da folha acompanham a evidência. A associação automática exige a identidade técnica suficiente do matcher comum e uma operação explícita compatível. OF/referência isoladas, máquina ou sequência principal não autorizam a operação.

Snapshots/revisões alterados invalidam o fingerprint e participam no conjunto de OFs antigas/novas a recalcular. Repetição conserva a geração; correção/retirada altera os derivados e conserva a versão anterior. O painel distingue a revisão publicada na origem da revisão efetivamente aplicada ao Planeamento. Cada registo mostra a área, a operação, a ligação à peça ou o motivo de exclusão.

Produção potencialmente repetida entre original e MES mantém conflito, sem somar acumulados. A exclusão aplica-se também à produtividade histórica. A evidência do formulário preserva os avisos de cobertura e não apresenta o total parcial como completo.

## Provas e limites

`tests/test_planning_original_production.py` usa SQLite e PostgreSQL descartáveis. Os testes de associação automática acrescentam perfil e operação explícitos à fixture para provar o contrato completo; **estes campos não são garantidos pelo esquema original real**, consultado em `/home/luis/projects/ocr/backend/app/web/db.py`. Há também um teste com o esquema original sem estes campos: conserva a quantidade original e apresenta exclusão individual, sem inventar associação.

`c01-original-pipeline-regression.log`: 68 testes passaram numa revisão intermédia. `c01-original-pipeline-current-regression.log`: regressão final afetada, incluindo associação a necessidade local, conflito, revisões, retirada e browser. `c01-original-browser-final.log` repete só a inspeção de interface após corrigir a descrição antiga da fonte separada. Não somar suites sobrepostas. As tentativas anteriores registam dois erros da fixture e uma incompatibilidade date/string corrigida no adaptador.

`c01-original-source-browser.json/png`: browser num servidor temporário e base descartável; duas linhas, uma com associação e outra sem identidade suficiente. API e texto visível conferidos; captura inspecionada. **Não constitui ingestão real do PC Windows.** Nenhuma escrita no clone integral ou nas fontes reais; os serviços persistentes não foram reiniciados nesta etapa. JS/template partilhados documentados.

## Trabalho necessário para completar C01/C02

1. Disponibilizar decisão humana por ID estável do original, reutilizando o percurso de associação. A tabela atual de decisões aceita apenas IDs numéricos MES; o adaptador não inventa uma correspondência para contornar esta limitação.
2. Ligar horas originais utilizáveis e a respetiva classificação de área/operação aos conjuntos históricos, evitando duplicação entre fontes.
3. Confirmar a SQLite/processo no PC Windows, primeira publicação real e repetição contínua. O acesso ainda falta; um teste descartável não satisfaz esse requisito.
4. Medir o percurso completo da fonte original e validar as resoluções humanas no browser; concluir as restantes matrizes e publicação.

C01/C02 não são aprovados globalmente por esta etapa. A entrega integral permanece incompleta.
