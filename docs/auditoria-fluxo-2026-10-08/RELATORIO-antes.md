# Auditoria do fluxo de dados — antes (07/10/2026 23:08)

Gerado por `scripts/auditoria_fluxo.py`. Só leitura (SELECT em transação READ ONLY e GET às páginas).
Código da auditoria: `26a37b5f1aa6`; código da app lido: `26a37b5f1aa6`.

## Fontes

| Setor | Geração | Excel importado | Idade (dias) |
|---|---|---|---|
| cantoneiras | 6804 | mtg_cdd4dda73e0856f6 (2026-10-02T12:51) | 5,4 |
| perfis | 6803 | mtg2_364600c14b9687bf (2026-10-07T12:20) | 0,4 |
- Drive perfis: `Met2_Plan_Perfis.xlsm` modificado 2026-10-07 08:26
- Drive cantoneiras: `SAIDA/Met3_Plan_Cantoneiras.xlsm` modificado 2026-10-07 07:05 — **mais recente no Drive por importar (F16)**
- Camada v2: retratos mtg2_3da468582f1d59b6, mtg_7c7b2c4b9a8889ce

## Amostra

743 linhas de 18285 abertas (343 obrigatórias: todas as linhas das OF com Planeado e as marcadas como repetida, OCR>QTD ou OCR<Excel).

| Dimensão | Valor | Na amostra | Na população |
|---|---|---|---|
| atraso | atrasada | 451 | 7786 |
| atraso | em dia | 134 | 2873 |
| atraso | sem prazo | 158 | 7626 |
| estado | nesting | 361 | 3477 |
| estado | planeado | 147 | 147 |
| estado | sem_maquina | 235 | 14661 |
| fonte_saldo | Excel | 693 | 18192 |
| fonte_saldo | OCR | 50 | 93 |
| identidade | app | 143 | 2447 |
| identidade | v2 | 600 | 15838 |
| marca | 2.ª operação | 110 | 5234 |
| marca | OCR<Excel | 4 | 4 |
| marca | OCR>QTD | 40 | 40 |
| marca | abocardar | 6 | 16 |
| marca | repetida | 28 | 28 |
| marca | sem peso na tabela | 36 | 1457 |
| marca | sem peso nem geometria | 5 | 141 |
| origem_maquina | Carteira≠Tabela | 154 | 158 |
| origem_maquina | Tabela | 354 | 3466 |
| origem_maquina | nenhuma | 235 | 14661 |
| prazo | Data Corte | 539 | 10503 |
| prazo | Picking | 46 | 156 |
| prazo | estacionada | 33 | 2892 |
| prazo | sem prazo | 125 | 4734 |
| setor | cantoneiras | 489 | 17120 |
| setor | perfis | 254 | 1165 |

## Verificações por caso

Diferença = valor da página ≠ esperado pela regra. Cada diferença leva o defeito que a explica (F01…F26 do desenho «dados») ou «inexplicado».

| Verificação | Campo | Página | Casos | Batem | Diferentes | Por defeito |
|---|---|---|---|---|---|---|
| C01 | presente | carteira | 741 | 741 | 0 | — |
| C01 | presente | tabela | 743 | 743 | 0 | — |
| C02 | ocr_menor_excel | origem | 4 | 0 | 4 | F03 4 |
| C02 | saldo_a_planear | tabela | 743 | 743 | 0 | — |
| C02 | saldo | carga | 505 | 505 | 0 | — |
| C02 | saldo | carteira | 704 | 704 | 0 | — |
| C02 | saldo | tabela | 743 | 743 | 0 | — |
| C03 | metros | carga | 505 | 505 | 0 | — |
| C03 | metros | carteira | 704 | 704 | 0 | — |
| C03 | metros | tabela | 743 | 743 | 0 | — |
| C04 | kg | carga | 505 | 503 | 2 | F08 2 |
| C04 | kg | carteira | 704 | 685 | 19 | F08 19 |
| C05 | maquina_tabela | tabela | 743 | 743 | 0 | — |
| C05 | maquina | carteira | 704 | 704 | 0 | — |
| C05 | recurso | carga | 446 | 446 | 0 | — |
| C06 | horas | carga | 505 | 236 | 269 | F01 140, F02 129 |
| C07 | celula | carga | 505 | 505 | 0 | — |
| C07 | picking_semana | carga | 46 | 46 | 0 | — |
| C07 | prazo | carga | 505 | 505 | 0 | — |
| C07 | prazo | carteira | 704 | 704 | 0 | — |
| C08 | estado | carteira | 704 | 704 | 0 | — |
| C08 | tipo | carga | 505 | 505 | 0 | — |
| C09 | repetida | carteira | 28 | 0 | 28 | F06 28 |
| C13 | saldo_planeado | carteira | 147 | 147 | 0 | — |
| C14 | producao_acima_qtd | origem | 40 | 0 | 40 | F07 40 |
| C14 | registos_ocr | tabela | 743 | 743 | 0 | — |

**Inexplicadas: 0** de 362 diferenças.

## Três exemplos seguidos da origem ao ecrã

### cantoneiras · OF265565 · DLA132 (nesting, Excel)

```
Origem   : OF265565 · DLA132 · L65X65X6 · 3 054 mm · QTD 2 (linha 72390 do Excel)
           contador 0.0 («Maq.» vazio e «Qtd falta» = QTD: conta 0.); OCR None (registos [])
           máquina Tabela 'Peddi 8'; Carteira None; decisão None; Data Corte 2026-09-25T00:00:00
Esperado : saldo 2.0 (Excel); 6,11 m; 36,0 kg (Tabela de pesos); máquina Peddi 8 (tabela); nesting; prazo 2026-09-25 (Data Corte); célula (2026, 41); 0,051 h (Excel Mt\h de Peddi 8, fator 1)
Tabela   : saldo 2.0 / a planear 2.0 (Excel provisório); 6.108 m; 0.07144892159001273 h (Histórico 85.48764437689971)
Carteira : 2.0 peças; 6.11 m; 36.0 kg; máquina Peddi 8 (tabela); prazo 2026-09-25; estado nesting
Carga    : 2.0 peças; 0.07144892159001273 h (documental, Histórico); 36.037200000000006 kg; a vencer; célula [2026, 41]
Diferenças: C06 horas@carga 0.0509→0.0714 (F02)
```

### perfis · OF265724 · 116H4AS (nesting, Excel)

```
Origem   : OF265724 · 116H4AS · UPN80x45 · 5 476 mm · QTD 2 (linha 6778 do Excel)
           contador 0.0 («Ser.» vazio e «Qtd em Falta» = QTD: conta 0.); OCR None (registos [])
           máquina Tabela 'Vanguard'; Carteira None; decisão None; Data Corte 2026-09-04T00:00:00
Esperado : saldo 2.0 (Excel); 10,95 m; 94,6 kg (área × L × 7850); máquina Vanguard (tabela); nesting; prazo 2026-08-31 (Picking); célula (2026, 41); 0,161 h (Excel E/F de Vanguard, fator 1)
Tabela   : saldo 2.0 / a planear 2.0 (Excel provisório); 10.9526 m; 0.10239706373095171 h (Histórico 21484.991071428572)
Carteira : 2.0 peças; 10.95 m; 94.6 kg; máquina Vanguard (tabela); prazo 2026-08-31; estado nesting
Carga    : 2.0 peças; 0.10239706373095171 h (documental, Histórico); 94.57570100000002 kg; a vencer; célula [2026, 41]
Diferenças: C06 horas@carga 0.1613→0.1024 (F02)
```

### cantoneiras · OF264095 · IT221A (planeado, Excel)

```
Origem   : OF264095 · IT221A · L45X45X5 · 1 755 mm · QTD 16 (linha 52309 do Excel)
           contador 0.0 («Maq.» vazio e «Qtd falta» = QTD: conta 0.); OCR None (registos [])
           máquina Tabela 'Peddi 8'; Carteira 'Ficep XP T4'; decisão selected; Data Corte 2026-07-28T00:00:00
Esperado : saldo 16.0 (Excel); 28,08 m; 94,9 kg (Tabela de pesos); máquina Ficep XP T4 (carteira); planeado; prazo 2026-07-28 (Data Corte); célula (2026, 41); 0,234 h (Excel Mt\h de Ficep XP T4, fator 1)
Tabela   : saldo 16.0 / a planear 16.0 (Excel provisório); 28.08 m; 0.32846851968689544 h (Histórico 85.48764437689971)
Carteira : 16.0 peças; 28.08 m; 94.9 kg; máquina Ficep XP T4 (carteira); prazo 2026-07-28; estado planeado
Carga    : 16.0 peças; 0.32846851968689544 h (documental, Histórico); 94.9104 kg; no plano; célula [2026, 41]
Diferenças: C06 horas@carga 0.234→0.3285 (F01)
```

## Fechos globais (C11)

### cantoneiras

| | Peças | Metros | Toneladas | Sem peso |
|---|---|---|---|---|
| Carteira | 223 740 | 441 620,2 | 2 863,53 | 1 585 |
| Carga | 223 740 | 441 620,3 | 2 863,53 | 1 580 |
| Diferença | 0 | 0,1 | 0,00 | -5 |

Linhas excluídas na Carteira (fora da Carga): 0; operações noutro setor (fora dos totais da Carga, F14): 571; «sem peso» contado de fontes diferentes (F21).

| Estado | KPI linhas | Carteira linhas | KPI m | Carteira m | KPI t | Carteira t |
|---|---|---|---|---|---|---|
| planeado | 141 | 141 | 2 498,2 | 2 498,2 | 13,63 | 13,63 |
| nesting | 2 648 | 2 648 | 53 259,8 | 53 259,8 | 362,49 | 362,49 |
| sem_maquina | 14 380 | 14 380 | 385 862,2 | 385 862,2 | 2 487,41 | 2 487,41 |

Horas «Planeado» (KPI) contra «no plano» da Carga (células das 13 semanas; operações das linhas planeadas, incluindo as atrasadas que a grelha não mostra como «no plano»):

| Máquina | KPI h | Carga células h | Carga operações h | Defeito |
|---|---|---|---|---|
| Ficep Rapid 20T -1 | 0,5 | 0 | 0,45 | F12 |
| Ficep Rapid 25T | 6,5 | 0 | 6,50 | F12 |
| Ficep XP T4 | 26,3 | 0 | 26,32 | F12 |

Gantt simples (fonte: automatica; operações em falta: 26) contra a Carga, por OF × máquina (tolerância: 1 minuto por operação):

| OF | Máquina | Operações | Gantt h | Carga no plano h | Diferença h | Defeito |
|---|---|---|---|---|---|---|
| OF264094 | Ficep Rapid 20T -1 | 3 | 0,47 | 0,45 | 0,02 | — |
| OF264095 | Ficep XP T4 | 125 | 19,90 | 26,32 | -6,42 | F01 |
| OF264219 | Ficep Rapid 25T | 13 | 6,57 | 6,50 | 0,07 | — |

### perfis

| | Peças | Metros | Toneladas | Sem peso |
|---|---|---|---|---|
| Carteira | 81 318 | 71 736,6 | 1 125,04 | 177 |
| Carga | 81 318 | 71 736,6 | 1 125,04 | 177 |
| Diferença | 0 | 0,0 | 0,00 | 0 |

Linhas excluídas na Carteira (fora da Carga): 0; operações noutro setor (fora dos totais da Carga, F14): 0; «sem peso» contado de fontes diferentes (F21).

| Estado | KPI linhas | Carteira linhas | KPI m | Carteira m | KPI t | Carteira t |
|---|---|---|---|---|---|---|
| planeado | 6 | 6 | 71,1 | 71,1 | 2,80 | 2,80 |
| nesting | 880 | 880 | 66 780,0 | 66 780,0 | 952,95 | 952,95 |
| sem_maquina | 280 | 280 | 4 885,6 | 4 885,6 | 169,28 | 169,28 |

Horas «Planeado» (KPI) contra «no plano» da Carga (células das 13 semanas; operações das linhas planeadas, incluindo as atrasadas que a grelha não mostra como «no plano»):

| Máquina | KPI h | Carga células h | Carga operações h | Defeito |
|---|---|---|---|---|
| Serrote MEBA IS381 Pav 3 | 13,9 | 8,4 | 13,92 | F12 |

Gantt simples (fonte: automatica; operações em falta: 0) contra a Carga, por OF × máquina (tolerância: 1 minuto por operação):

| OF | Máquina | Operações | Gantt h | Carga no plano h | Diferença h | Defeito |
|---|---|---|---|---|---|---|
| OF265771 | Serrote MEBA IS381 Pav 3 | 1 | 5,45 | 5,44 | 0,01 | — |
| OF265941 | Serrote MEBA IS381 Pav 3 | 1 | 5,45 | 5,44 | 0,01 | — |
| OF265943 | Serrote MEBA IS381 Pav 3 | 4 | 3,08 | 3,04 | 0,04 | — |

## Associações MES (C14)

- cantoneiras: 3823 registos; estados {'unmatched': 281, 'incomplete': 366, 'technical_unique': 2784, 'explicit': 392}; produção acima da QTD em 37 linhas (+200,0 peças); 22 grupos k × QTD no mesmo dia e máquina; 2 imagens em várias folhas.
- perfis: 945 registos; estados {'unmatched': 6, 'incomplete': 1, 'technical_unique': 928, 'ambiguous': 10}; produção acima da QTD em 3 linhas (+195,0 peças); 1 grupos k × QTD no mesmo dia e máquina; 0 imagens em várias folhas.

## População (C01)

- cantoneiras: origem 17902 linhas ativas, app 17902; só na origem 0, só na app 0 (peças do registo manual: 0).
- perfis: origem 1208 linhas ativas, app 1208; só na origem 0, só na app 0 (peças do registo manual: 0).

## Correções manuais (C12)

- 4dedec31-aec0-4a66-9f50-5572b552c477 · operation = "corte" (select, 2026-09-23T14:36)
- 4dedec31-aec0-4a66-9f50-5572b552c477 · expected_date = "2026-09-23" (write, 2026-09-23T14:36)
- 6985aba7-170d-423b-a703-95c16ca0e255 · operation = "corte" (select, 2026-09-23T14:37)
- 6985aba7-170d-423b-a703-95c16ca0e255 · expected_date = "2026-09-23" (write, 2026-09-23T14:37)

## Previsão das regras decididas a 08/10 (--prever)

### cantoneiras

Razão = horas pela regra decidida ÷ horas de hoje, nas mesmas linhas (máquina efetiva = Tabela, horas conhecidas nas duas). < 1: as horas descem; > 1: sobem.

| Máquina efetiva | Linhas | Comparáveis | Horas hoje (Tabela) | Horas regra decidida | Razão | Total regra decidida | Sem horas | Fontes de hoje |
|---|---|---|---|---|---|---|---|---|
| Ficep Rapid 20T -1 | 771 | 771 | 172,0 | 172,0 | 1,00 | 172,0 | 0 | Excel provisório 771 |
| Ficep XP T4 | 362 | 208 | 122,7 | 122,7 | 1,00 | 148,2 | 0 | Excel provisório 210, Histórico 152 |
| Peddi 8 | 525 | 525 | 144,0 | 104,7 | 0,73 | 104,7 | 0 | Histórico 482, Excel provisório 43 |
| Ficep Rapid 25T | 289 | 285 | 99,1 | 99,1 | 1,00 | 100,0 | 0 | None 4, Excel provisório 285 |
| Ficep Rapid 20T -2 | 531 | 531 | 96,8 | 96,8 | 1,00 | 96,8 | 0 | Excel provisório 531 |
| Ficep XP T6 | 113 | 113 | 120,5 | 67,1 | 0,56 | 67,1 | 0 | Histórico 108, Excel provisório 5 |
| Peddi 6 | 109 | 109 | 34,9 | 34,9 | 1,00 | 34,9 | 0 | Excel provisório 109 |
| Ficep XP T7 | 1 | 1 | 0,0 | 0,0 | 1,00 | 0,0 | 0 | Excel provisório 1 |
| Ficep XP T8 | 1 | 1 | 0,0 | 0,0 | 1,00 | 0,0 | 0 | Excel provisório 1 |
| Ficep XP T9 | 1 | 1 | 0,0 | 0,0 | 1,00 | 0,0 | 0 | Excel provisório 1 |

Linhas sem máquina (horas na máquina sugerida, ver C06 na Carga): 14380.

F01: 154 linhas com máquina da Carteira diferente da Tabela: 36,3 h na máquina da Tabela contra 25,6 h na máquina efetiva (regra decidida).
F08: 1580 linhas sem peso na Tabela de pesos; 1439 calculáveis pela geometria (+237,2 t); 141 continuam sem peso.
OCR abaixo do Excel: 0 linhas, 0 peças e 0 m a mais de saldo face ao Excel. Decisão 2 de 08/10: o OCR continua a mandar; estas linhas vão para conferir no MES.

### perfis

Razão = horas pela regra decidida ÷ horas de hoje, nas mesmas linhas (máquina efetiva = Tabela, horas conhecidas nas duas). < 1: as horas descem; > 1: sobem.

| Máquina efetiva | Linhas | Comparáveis | Horas hoje (Tabela) | Horas regra decidida | Razão | Total regra decidida | Sem horas | Fontes de hoje |
|---|---|---|---|---|---|---|---|---|
| Vanguard | 312 | 176 | 543,1 | 855,7 | 1,58 | 855,7 | 136 | Histórico 312 |
| Serrote Disco pav 1 | 222 | 206 | 640,8 | 533,3 | 0,83 | 533,3 | 16 | Excel provisório 222 |
| Serrote MEBA IS381 Pav 3 | 169 | 169 | 306,3 | 364,8 | 1,19 | 364,8 | 0 | Excel provisório 169 |
| Serrote Doall Pav.1 | 50 | 50 | 77,8 | 93,9 | 1,21 | 93,9 | 0 | Histórico 50 |
| Serrote Fita Thomas IS639 Pav.1 | 131 | 131 | 55,0 | 54,0 | 0,98 | 54,0 | 0 | Excel provisório 131 |

Linhas sem máquina (horas na máquina sugerida, ver C06 na Carga): 278.

F01: 0 linhas com máquina da Carteira diferente da Tabela: 0,0 h na máquina da Tabela contra 0,0 h na máquina efetiva (regra decidida).
OCR abaixo do Excel: 4 linhas, 6 639,0 peças e 6 299,8 m a mais de saldo face ao Excel. Decisão 2 de 08/10: o OCR continua a mandar; estas linhas vão para conferir no MES.

| Máquina | Linhas | Área mm² | Horas coluna C | Horas coluna E/F |
|---|---|---|---|---|
| Serrote MEBA IS381 Pav 3 | 169 | 14 710 375 | 306,3 | 364,8 |
| Vanguard | 176 | 11 668 281 | 1 268,3 | 855,7 |
| Sem máquina | 253 | 9 775 371 | 0,0 | 0,0 |
| Serrote Disco pav 1 | 206 | 8 217 140 | 640,8 | 533,3 |
| Serrote Fita Thomas IS639 Pav.1 | 131 | 1 843 785 | 55,0 | 54,0 |
| Serrote Doall Pav.1 | 50 | 1 769 364 | 80,9 | 93,9 |

## C15 — Preenchimento automático: campo → fonte → regra → onde se usa

| Campo | Fonte(s) | Regra quando as fontes se contradizem | Onde se usa | No código |
|---|---|---|---|---|
| OV, Cliente, Descrição da obra, Estado, Entrega, Fim previsto | Cópias CPIS nos dois Excel; OF registada à mão (local_orders) | Cópia carregada mais tarde ganha, campo a campo; campo vazio herda da outra; com registo livre a OF local sobrepõe-se. O CPIS direto (vazio) substituiria as cópias. | Carteira, sinais (prioridade/anulada), prazo de reserva | confirmada: app/cpis_copies.py:19; app/planning_hub.py:204 |
| Família de Produto | cpis_rows do snapshot do próprio setor | Sem a regra «mais recente»: junta pelo snapshot da geração; código mais baixo quando há vários. | Filtro e vista da Carteira, Carga | confirmada: app/sector/occurrences.py:140; app/sector/portfolio.py:108 |
| Família SKU | Regra CSV em sku_family_rules | Só MTG3; sem regra, «Sem família SKU». | Filtros, conjuntos, aprendizagem | confirmada: app/raw/sku_families.py:104 |
| Referência, Perfil, QTD, Comp., material, dimensões | Excel; PDF (dossiê); registo manual | Valor escrito à mão > origem; campos não mexidos seguem a origem (OPERATION_FOLLOW só 7 campos — F20). | Identidade, metros, horas | confirmada: app/planning_needs.py:21,156,183; app/planning_needs.py:151 |
| Produção feita (cut, made) | MES OCR validado; Excel «Ser.»/«Maq.»; 0 local | OCR validado > Excel > 0 > desconhecido; sem máximo (decisão 2 de 08/10: o OCR substitui mesmo menor). | Saldo | confirmada: app/planning_calculations.py:114; app/planning_calculations.py:69 |
| Saldo (remaining, planning_remaining) | Cálculo acima; «Qtd em falta» manual; camada v2 | Qtd em falta > OCR > v2 (sem OCR e contadores iguais) > Excel. A v2 sobrepõe-se ao saldo principal (F04/F05). | Carteira (peças, metros, kg), Carga, Gantt | confirmada: app/gantt/research.py:278; app/gantt/research.py:237; app/planning_estimates.py:8 |
| Peso | MTG3: Tabela de pesos (kg/m exato e único); MTG2: área × L × 7850 | Pesos divergentes → desconhecido. Decisão F08 (08/10): sem perfil na tabela, geometria t(a+b−t)·7850/10⁶. | kg na Carteira e na Carga | confirmada: app/planning_calculations.py:299; app/planning_calculations.py:302 |
| Área de corte (MTG2) | Fórmula geométrica (FuncAreaPerf) ou AreaSecaoCorte exata | Fórmula > catálogo exato. | Horas e peso MTG2 | confirmada: app/planning_calculations.py:124 |
| Máquina (Tabela) | Registo manual; Excel «Máquina Corte» | Manual > Excel; segue a origem se ninguém a escreveu. | Máquina efetiva | confirmada: app/planning.py:287 |
| Máquina efetiva | Carteira (sector_member_machine) > Tabela > conjunto de famílias | Uma sugestão nunca é máquina efetiva; «Por definir», «Subcontrato», «MTG3»… = sem máquina. | Estado, Carga, Gantt | confirmada: app/sector/machine_choice.py:56; app/sector/machine_choice.py:18,25 |
| Máquina sugerida | Aprendizagem (Carteira 5, Tabela 1, histórico 1) > previsão (estimates.apply) | Ao Planear grava-se em sector_member_machine com origem «sugerida» (não alimenta a aprendizagem). | Lupa, Planear, coluna «sugerida» da Carga | confirmada: app/sector/selection.py:205; app/sector/selection.py:454,456 |
| 1.ª/2.ª Oper. (MTG3) | Excel; valores por defeito 119/0 | Excel > defeito. | Saldo, horas, operações seguintes | confirmada: app/raw/registration.py:20,23 |
| Data Corte | Excel; manual | Manual > Excel (segue a origem). | Prazo MTG3; prazo de reserva MTG2 | confirmada: app/sector/priority.py:63 |
| Picking (MTG2) | Folha Picking; coluna da linha; manual | Manual > folha (semana única) > linha; conflito → nenhum; ano deduzido pela Data Corte. | Prazo MTG2 | confirmada: app/planning_dates.py:50; app/planning_dates.py:134 |
| Prazo do setor | Data Corte; Picking; semana escolhida; Galvanização; coluna W | MTG3 Data Corte; MTG2 Picking → semana escolhida → Galvanização → Data Corte; W 2026/53 = estacionada. | Carteira (janela, semana), Carga (semana da carga), Gantt | confirmada: app/sector/priority.py:68; app/sector/priority.py:51 |
| Horas | Taxa confirmada; Histórico; tabela de velocidades; Excel (Mt\h / CapacidadeMáquinas) | Hoje: Manual > Histórico (¼–4× Excel) > tabela Excel > Excel (coluna C na MTG2, ×3 Thomas só no motor). Decidido a 08/10: Confirmada > Excel × eficiência, ×3 da Thomas em todo o lado, coluna E/F na MTG2. | Carteira (KPI), Carga, Gantt | confirmada: app/raw/productivity.py:362; app/raw/capacity_revision.py:69; app/sector/estimates.py:27,163 |
| Operação dos registos MES MTG3 | extra.operation_code → operação única aplicável da peça | Nunca deduzida da máquina. | Atribuição de produção à operação | confirmada: app/planning_production.py:15 |

## Pedidos às páginas

348 GET; erros: 1; 5xx: 0; tempo médio 247 ms.
