# Auditoria do fluxo de dados (Etapa 0, 08/10/2026)

Script que confere, linha a linha, se o que as páginas mostram (Tabela, Carteira, KPIs, Carga, Gantt) é o que a
origem diz (Excel importado, folhas OCR validadas do MES, decisões da Carteira, Definições). Só lê: SELECT numa
transação READ ONLY e GET às páginas. Não grava nada em lado nenhum, exceto os ficheiros desta pasta.

- `scripts/auditoria_fluxo.py` — linha de comandos (lê a origem e as páginas, verifica, escreve a evidência).
- `scripts/auditoria_fluxo_regras.py` — as regras, em funções puras (saldo, metros, peso, horas, prazo, semana da
  carga, máquina efetiva, amostra, comparação). Testes: `tests/test_auditoria_fluxo.py`.

## Como correr

Na raiz do projeto (ou numa worktree: o `.env` vem de `--env`, por defeito o da produção; nunca é impresso):

```
# antes de corrigir: auditoria completa + impacto das regras decididas a 08/10
.venv/bin/python scripts/auditoria_fluxo.py --tag antes --prever

# corrida pequena para experimentar (20 linhas por setor, sem o Gantt)
.venv/bin/python scripts/auditoria_fluxo.py --tag teste --limite 20 --sem-gantt

# depois de uma ativação: compara pela identidade estável e explica cada mudança
.venv/bin/python scripts/auditoria_fluxo.py --tag depois \
    --comparar docs/auditoria-fluxo-2026-10-08/evidencia/antes-AAAAMMDDThhmm.json \
    --efeitos docs/auditoria-fluxo-2026-10-08/efeitos-etapa1.json
```

Cuidados: não corre enquanto a limpeza da base (`planning-retention-20261007`) estiver ativa; evitar as 08:15 e
as 14:15 (importações do Excel). Os pedidos às páginas são um de cada vez, 0,2 s entre eles, 60 s de limite, no
máximo 800 (`--max-pedidos`), e param à 3.ª resposta 5xx. Uma resposta «stale» faz esperar até 3 × 10 s.
Com o servidor sem memória, correr com `nice -n 10`.

## O que sai

- `evidencia/<tag>-<AAAAMMDDThhmm>.json` — manifesto (commits, gerações, retratos do Excel, observação do Drive,
  fontes da camada v2), cobertura da amostra, um registo por linha auditada (origem, esperado, valor em cada
  página, diferença, defeito que a explica) e os fechos globais. Acima de 5 MB fica comprimido (`.json.gz`).
- `RELATORIO-<tag>.md` — contagens por verificação, 3 exemplos reais seguidos da origem ao ecrã, fechos globais,
  associações MES, previsão (`--prever`), o mapa C15 e a comparação (`--comparar`).

## Amostra

Cerca de 400 linhas abertas, escolhidas de forma determinística (sha1 da identidade): todas as linhas das OF com
Planeado, todas as repetidas, as com OCR acima da QTD e as com OCR abaixo do Excel; depois cada valor de cada
dimensão (setor, fonte do saldo, origem da máquina, estado, fonte do prazo, atraso, identidade v2/app e marcas)
até 5 casos. Identidade estável entre importações: setor, OF, referência, perfil, comprimento, QTD e ordem entre
repetidas.

## Verificações

| Código | O que confere |
|---|---|
| C01 | População ativa: a linha está na Tabela e na Carteira (e os totais origem/app). |
| C02 | Saldo: OCR validado substitui o contador do Excel (mesmo menor); contador vazio = 0 com «Qtd falta» = QTD. |
| C03 | Metros = saldo × comprimento ÷ 1000 na Tabela, Carteira e Carga. |
| C04 | Peso: Tabela de pesos ou geometria (MTG3), área × L × 7850 (MTG2); desconhecido nunca é 0. |
| C05 | Máquina efetiva: Carteira → Tabela → conjunto de famílias, igual em todas as páginas. |
| C06 | Horas pela regra decidida: volume ÷ velocidade do Excel da máquina efetiva ÷ eficiência; ×3 Thomas (QTD > 50); MTG2 coluna E/F. |
| C07 | Prazo do setor e célula da Carga (semana ISO do prazo; antes da semana atual → Atrasado). |
| C08 | Estado da Carteira (Planeado / nesting / sem máquina) = tipo na Carga (no plano / a vencer / sugerida). |
| C09 | Linhas repetidas contadas sem aviso. |
| C10 | Frescura: idade do Excel, ficheiro mais recente no Drive por importar, fontes da camada v2. |
| C11 | Fechos: Carteira = Carga (peças, m, t, sem peso); KPI por estado = Carteira; KPI Planeado = «no plano»; Gantt = Carga. |
| C12 | Correções manuais (field_state com decisão humana). |
| C13 | Planear não é produzir: o saldo da linha planeada é o da produção registada. |
| C14 | Associações MES: registos por linha, não associados, ambíguos, k × QTD no mesmo dia, produção acima da QTD. |
| C15 | Mapa «campo preenchido automaticamente → fonte → regra quando as fontes se contradizem → onde se usa», confirmado no código. |

Cada diferença leva o defeito que a explica (F01…F26 do desenho «dados» de 07/10) ou «inexplicado».

## Efeitos esperados (`--comparar`)

`efeitos-etapa1.json` declara, antes de corrigir, o que cada correção deve mudar. Na comparação, cada valor de
página que mudou fica «explicado» (um efeito declarado cobre-o; com `"fecha": true` só se a diferença para o
esperado desapareceu), «origem mudou» (os valores de origem do caso mudaram: houve importação pelo meio) ou
«inexplicado».

## Aproximações conhecidas

- A associação MES é refeita pela regra da app (chave do retrato, depois referência + comprimento + perfil na OF),
  sem as decisões manuais de associação nem a identidade guardada no `cross_check` da folha.
- A identidade «v2/app» é deduzida pela presença da mesma linha no retrato do Excel que a camada v2 usa.
- A «Qtd em falta» do registo manual e as peças registadas à mão (2 rascunhos a 07/10) ficam fora dos casos.
- Taxas «Confirmadas» com intervalos de dimensão não são aplicadas (hoje há 0 taxas na tabela de velocidades).
- A eficiência por máquina ainda não existe nas Definições: vale 100 % até a Etapa 2 a acrescentar
  (`efficiency` / `eficiencia` por id ou nome do recurso).
