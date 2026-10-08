# Auditoria do fluxo de dados — depois (08/10/2026 08:56)

Gerado por `scripts/auditoria_fluxo.py`. Só leitura (SELECT em transação READ ONLY e GET às páginas).
Código da auditoria: `252b9c0cfdef`; código da app lido: `252b9c0cfdef`.

## Fontes

| Setor | Geração | Excel importado | Idade (dias) |
|---|---|---|---|
| cantoneiras | 6856 | mtg_841273ac945fed28 (2026-10-08T07:39) | 0,0 |
| perfis | 6855 | mtg2_364600c14b9687bf (2026-10-07T12:20) | 0,8 |
- Drive perfis: `Met2_Plan_Perfis.xlsm` modificado 2026-10-07 08:26
- Drive cantoneiras: `SAIDA/Met3_Plan_Cantoneiras.xlsm` modificado 2026-10-07 07:05
- Camada v2: retratos mtg2_3da468582f1d59b6, mtg_7c7b2c4b9a8889ce

## Amostra

705 linhas de 17822 abertas (305 obrigatórias: todas as linhas das OF com Planeado e as marcadas como repetida, OCR>QTD ou OCR<Excel).

| Dimensão | Valor | Na amostra | Na população |
|---|---|---|---|
| atraso | atrasada | 424 | 7388 |
| atraso | em dia | 123 | 2804 |
| atraso | sem prazo | 158 | 7630 |
| estado | nesting | 351 | 4683 |
| estado | planeado | 134 | 134 |
| estado | sem_maquina | 220 | 13005 |
| fonte_saldo | Excel | 670 | 17759 |
| fonte_saldo | OCR | 35 | 63 |
| identidade | app | 139 | 2461 |
| identidade | v2 | 566 | 15361 |
| marca | 2.ª operação | 96 | 4924 |
| marca | OCR<Excel | 5 | 5 |
| marca | OCR>QTD | 24 | 24 |
| marca | abocardar | 6 | 16 |
| marca | repetida | 28 | 28 |
| marca | sem peso na tabela | 33 | 1452 |
| marca | sem peso nem geometria | 4 | 4 |
| origem_maquina | Carteira≠Tabela | 154 | 158 |
| origem_maquina | Tabela | 331 | 4659 |
| origem_maquina | nenhuma | 220 | 13005 |
| prazo | Data Corte | 501 | 10036 |
| prazo | Picking | 46 | 156 |
| prazo | estacionada | 33 | 2892 |
| prazo | sem prazo | 125 | 4738 |
| setor | cantoneiras | 451 | 16657 |
| setor | perfis | 254 | 1165 |

## Verificações por caso

Diferença = valor da página ≠ esperado pela regra. Cada diferença leva o defeito que a explica (F01…F26 do desenho «dados») ou «inexplicado».

| Verificação | Campo | Página | Casos | Batem | Diferentes | Por defeito |
|---|---|---|---|---|---|---|
| C01 | presente | carteira | 704 | 704 | 0 | — |
| C01 | presente | tabela | 705 | 705 | 0 | — |
| C02 | ocr_menor_excel | origem | 5 | 0 | 5 | F03 5 |
| C02 | saldo_a_planear | tabela | 705 | 705 | 0 | — |
| C02 | saldo | carga | 483 | 483 | 0 | — |
| C02 | saldo | carteira | 681 | 681 | 0 | — |
| C02 | saldo | tabela | 705 | 705 | 0 | — |
| C03 | metros | carga | 483 | 483 | 0 | — |
| C03 | metros | carteira | 681 | 681 | 0 | — |
| C03 | metros | tabela | 705 | 705 | 0 | — |
| C04 | kg | carga | 483 | 482 | 1 | inexplicado 1 |
| C04 | kg | carteira | 681 | 680 | 1 | inexplicado 1 |
| C05 | maquina_tabela | tabela | 705 | 705 | 0 | — |
| C05 | maquina | carteira | 681 | 681 | 0 | — |
| C05 | recurso | carga | 435 | 435 | 0 | — |
| C06 | horas | carga | 483 | 483 | 0 | — |
| C07 | celula | carga | 483 | 483 | 0 | — |
| C07 | picking_semana | carga | 46 | 46 | 0 | — |
| C07 | prazo | carga | 483 | 483 | 0 | — |
| C07 | prazo | carteira | 681 | 681 | 0 | — |
| C08 | estado | carteira | 681 | 681 | 0 | — |
| C08 | tipo | carga | 483 | 483 | 0 | — |
| C09 | repetida | carteira | 28 | 28 | 0 | — |
| C13 | saldo_planeado | carteira | 134 | 134 | 0 | — |
| C14 | producao_acima_qtd | origem | 24 | 0 | 24 | F07 24 |
| C14 | registos_ocr | tabela | 705 | 705 | 0 | — |

**Inexplicadas: 2** de 31 diferenças.

## Três exemplos seguidos da origem ao ecrã

### cantoneiras · OF265509 · XZ354027 (nesting, Excel)

```
Origem   : OF265509 · XZ354027 · L90X90X7 · 1 749 mm · QTD 2 (linha 73199 do Excel)
           contador 0.0 («Maq.» vazio e «Qtd falta» = QTD: conta 0.); OCR None (registos [])
           máquina Tabela 'Ficep Rapid 25T'; Carteira None; decisão None; Data Corte 2026-09-25T00:00:00
Esperado : saldo 2.0 (Excel); 3,50 m; 33,6 kg (Tabela de pesos); máquina Ficep Rapid 25T (tabela); nesting; prazo 2026-09-25 (Data Corte); célula (2026, 41); 0,100 h (Excel Mt\h de Ficep Rapid 25T, fator 1)
Tabela   : saldo 2.0 / a planear 2.0 (Excel provisório); 3.498 m; 0.09994285714285715 h (Excel provisório 35.0)
Carteira : 2.0 peças; 3.5 m; 33.6 kg; máquina Ficep Rapid 25T (tabela); prazo 2026-09-25; estado nesting
Carga    : 2.0 peças; 0.09994285714285715 h (documental, Excel provisório); 33.61578 kg; a vencer; célula [2026, 41]
Diferenças: nenhuma
```

### perfis · OF265724 · 116H4AS (nesting, Excel)

```
Origem   : OF265724 · 116H4AS · UPN80x45 · 5 476 mm · QTD 2 (linha 6778 do Excel)
           contador 0.0 («Ser.» vazio e «Qtd em Falta» = QTD: conta 0.); OCR None (registos [])
           máquina Tabela 'Vanguard'; Carteira None; decisão None; Data Corte 2026-09-04T00:00:00
Esperado : saldo 2.0 (Excel); 10,95 m; 94,6 kg (área × L × 7850); máquina Vanguard (tabela); nesting; prazo 2026-08-31 (Picking); célula (2026, 41); 0,161 h (Excel E/F de Vanguard, fator 1)
Tabela   : saldo 2.0 / a planear 2.0 (Excel provisório); 10.9526 m; 0.16133763567028453 h (Excel provisório 13636.0)
Carteira : 2.0 peças; 10.95 m; 94.6 kg; máquina Vanguard (tabela); prazo 2026-08-31; estado nesting
Carga    : 2.0 peças; 0.16133763567028453 h (documental, Excel provisório); 94.57570100000002 kg; a vencer; célula [2026, 41]
Diferenças: nenhuma
```

### cantoneiras · OF264095 · IT221A (planeado, Excel)

```
Origem   : OF264095 · IT221A · L45X45X5 · 1 755 mm · QTD 16 (linha 52309 do Excel)
           contador 0.0 («Maq.» vazio e «Qtd falta» = QTD: conta 0.); OCR None (registos [])
           máquina Tabela 'Peddi 8'; Carteira 'Ficep XP T4'; decisão selected; Data Corte 2026-07-28T00:00:00
Esperado : saldo 16.0 (Excel); 28,08 m; 94,9 kg (Tabela de pesos); máquina Ficep XP T4 (carteira); planeado; prazo 2026-07-28 (Data Corte); célula (2026, 41); 0,234 h (Excel Mt\h de Ficep XP T4, fator 1)
Tabela   : saldo 16.0 / a planear 16.0 (Excel provisório); 28.08 m; 0.23399999999999999 h (Excel provisório 120.0)
Carteira : 16.0 peças; 28.08 m; 94.9 kg; máquina Ficep XP T4 (carteira); prazo 2026-07-28; estado planeado
Carga    : 16.0 peças; 0.23399999999999999 h (estimada, Estimativa: velocidade do Excel de Ficep XP T4, 120 m/h); 94.9104 kg; no plano; célula [2026, 41]
Diferenças: nenhuma
```

## Fechos globais (C11)

### cantoneiras

| | Peças | Metros | Toneladas | Sem peso |
|---|---|---|---|---|
| Carteira | 218 980 | 431 319,8 | 2 987,90 | 3 |
| Carga | 218 980 | 431 319,9 | 2 987,90 | 3 |
| Diferença | 0 | 0,1 | 0,00 | 0 |

Linhas excluídas na Carteira (fora da Carga): 0; operações noutro setor (fora dos totais da Carga, F14): 0; «sem peso» contado de fontes diferentes (F21).

| Estado | KPI linhas | Carteira linhas | KPI m | Carteira m | KPI t | Carteira t |
|---|---|---|---|---|---|---|
| planeado | 128 | 128 | 2 270,8 | 2 270,8 | 7,91 | 7,91 |
| nesting | 3 833 | 3 833 | 85 109,4 | 85 109,4 | 600,14 | 600,14 |
| sem_maquina | 12 726 | 12 726 | 343 939,6 | 343 939,6 | 2 379,84 | 2 379,84 |

Horas «Planeado» (KPI) contra «no plano» da Carga (células das 13 semanas; operações das linhas planeadas, incluindo as atrasadas que a grelha não mostra como «no plano»):

| Máquina | KPI h | Carga células h | Carga operações h | Defeito |
|---|---|---|---|---|
| Ficep Rapid 20T -1 | 0,5 | 0 | 0,45 | F12 |
| Ficep XP T4 | 18,8 | 0 | 18,75 | F12 |

Gantt simples (fonte: automatica; operações em falta: 0) contra a Carga, por OF × máquina (tolerância: 1 minuto por operação):

| OF | Máquina | Operações | Gantt h | Carga no plano h | Diferença h | Defeito |
|---|---|---|---|---|---|---|
| OF264094 | Ficep Rapid 20T -1 | 3 | 0,47 | 0,45 | 0,02 | — |
| OF264095 | Ficep XP T4 | 125 | 19,90 | 18,75 | 1,15 | — |

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
| Serrote MEBA IS381 Pav 3 | 16,6 | 10,1 | 16,58 | F12 |

Gantt simples (fonte: automatica; operações em falta: 0) contra a Carga, por OF × máquina (tolerância: 1 minuto por operação):

| OF | Máquina | Operações | Gantt h | Carga no plano h | Diferença h | Defeito |
|---|---|---|---|---|---|---|
| OF265771 | Serrote MEBA IS381 Pav 3 | 1 | 6,48 | 6,48 | -0,00 | — |
| OF265941 | Serrote MEBA IS381 Pav 3 | 1 | 6,48 | 6,48 | -0,00 | — |
| OF265943 | Serrote MEBA IS381 Pav 3 | 4 | 3,65 | 3,62 | 0,03 | — |

## Associações MES (C14)

- cantoneiras: 3823 registos; estados {'unmatched': 281, 'incomplete': 368, 'technical_unique': 3174}; produção acima da QTD em 21 linhas (+58,0 peças); 18 grupos k × QTD no mesmo dia e máquina; 2 imagens em várias folhas.
- perfis: 945 registos; estados {'unmatched': 6, 'incomplete': 1, 'technical_unique': 928, 'ambiguous': 10}; produção acima da QTD em 3 linhas (+195,0 peças); 1 grupos k × QTD no mesmo dia e máquina; 0 imagens em várias folhas.

## População (C01)

- cantoneiras: origem 16937 linhas ativas, app 16937; só na origem 0, só na app 0 (peças do registo manual: 0).
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
| Ficep XP T4 | 438 | 284 | 229,8 | 229,8 | 1,00 | 255,4 | 0 | Excel provisório 438 |
| Ficep Rapid 25T | 573 | 569 | 196,6 | 196,6 | 1,00 | 197,5 | 0 | None 4, Excel provisório 569 |
| Ficep Rapid 20T -1 | 850 | 850 | 170,5 | 170,5 | 1,00 | 170,5 | 0 | Excel provisório 850 |
| Ficep XP T6 | 399 | 399 | 165,6 | 165,6 | 1,00 | 165,6 | 0 | Excel provisório 399 |
| Ficep Rapid 20T -2 | 882 | 882 | 142,6 | 142,6 | 1,00 | 142,6 | 0 | Excel provisório 882 |
| Peddi 8 | 667 | 667 | 120,0 | 120,0 | 1,00 | 120,0 | 0 | Excel provisório 667 |
| Peddi 6 | 99 | 99 | 28,8 | 28,8 | 1,00 | 28,8 | 0 | Excel provisório 99 |
| Ficep XP T5 | 1 | 0 | 0,0 | 0,0 | — | 0,0 | 1 | None 1 |
| Ficep XP T7 | 1 | 0 | 0,0 | 0,0 | — | 0,0 | 1 | Excel provisório 1 |

Linhas sem máquina (horas na máquina sugerida, ver C06 na Carga): 12726.

F01: 154 linhas com máquina da Carteira diferente da Tabela: 26,0 h na máquina da Tabela contra 25,6 h na máquina efetiva (regra decidida).
F08: 1440 linhas sem peso na Tabela de pesos; 1436 calculáveis pela geometria (+224,4 t); 4 continuam sem peso.
OCR abaixo do Excel: 1 linhas, 40,0 peças e 86,6 m a mais de saldo face ao Excel. Decisão 2 de 08/10: o OCR continua a mandar; estas linhas vão para conferir no MES.

### perfis

Razão = horas pela regra decidida ÷ horas de hoje, nas mesmas linhas (máquina efetiva = Tabela, horas conhecidas nas duas). < 1: as horas descem; > 1: sobem.

| Máquina efetiva | Linhas | Comparáveis | Horas hoje (Tabela) | Horas regra decidida | Razão | Total regra decidida | Sem horas | Fontes de hoje |
|---|---|---|---|---|---|---|---|---|
| Vanguard | 312 | 176 | 855,7 | 855,7 | 1,00 | 855,7 | 136 | Excel provisório 312 |
| Serrote Disco pav 1 | 222 | 206 | 533,3 | 533,3 | 1,00 | 533,3 | 16 | Excel provisório 222 |
| Serrote MEBA IS381 Pav 3 | 169 | 169 | 364,8 | 364,8 | 1,00 | 364,8 | 0 | Excel provisório 169 |
| Serrote Doall Pav.1 | 50 | 50 | 93,9 | 93,9 | 1,00 | 93,9 | 0 | Excel provisório 50 |
| Serrote Fita Thomas IS639 Pav.1 | 131 | 131 | 54,0 | 54,0 | 1,00 | 54,0 | 0 | Excel provisório 131 |

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
| Família de Produto | cpis_rows do snapshot do próprio setor | Sem a regra «mais recente»: junta pelo snapshot da geração; código mais baixo quando há vários. | Filtro e vista da Carteira, Carga | confirmada: app/sector/occurrences.py:166; app/sector/portfolio.py:132 |
| Família SKU | Regra CSV em sku_family_rules | Só MTG3; sem regra, «Sem família SKU». | Filtros, conjuntos, aprendizagem | confirmada: app/raw/sku_families.py:104 |
| Referência, Perfil, QTD, Comp., material, dimensões | Excel; PDF (dossiê); registo manual | Valor escrito à mão > origem; campos não mexidos seguem a origem (OPERATION_FOLLOW só 7 campos — F20). | Identidade, metros, horas | confirmada: app/planning_needs.py:25,160,188; app/planning_needs.py:155 |
| Produção feita (cut, made) | MES OCR validado; Excel «Ser.»/«Maq.»; 0 local | OCR validado > Excel > 0 > desconhecido; sem máximo (decisão 2 de 08/10: o OCR substitui mesmo menor). | Saldo | confirmada: app/planning_calculations.py:148; app/planning_calculations.py:103 |
| Saldo (remaining, planning_remaining) | Cálculo acima; «Qtd em falta» manual; camada v2 | Qtd em falta > OCR > v2 (sem OCR e contadores iguais) > Excel. A v2 sobrepõe-se ao saldo principal (F04/F05). | Carteira (peças, metros, kg), Carga, Gantt | confirmada: app/gantt/research.py:262; app/gantt/research.py:239; app/planning_estimates.py:8 |
| Peso | MTG3: Tabela de pesos (kg/m exato e único); MTG2: área × L × 7850 | Pesos divergentes → desconhecido. Decisão F08 (08/10): sem perfil na tabela, geometria t(a+b−t)·7850/10⁶. | kg na Carteira e na Carga | confirmada: app/planning_calculations.py:342; app/planning_calculations.py:345 |
| Área de corte (MTG2) | Fórmula geométrica (FuncAreaPerf) ou AreaSecaoCorte exata | Fórmula > catálogo exato. | Horas e peso MTG2 | confirmada: app/planning_calculations.py:158 |
| Máquina (Tabela) | Registo manual; Excel «Máquina Corte» | Manual > Excel; segue a origem se ninguém a escreveu. | Máquina efetiva | confirmada: app/planning.py:277 |
| Máquina efetiva | Carteira (sector_member_machine) > Tabela > conjunto de famílias | Uma sugestão nunca é máquina efetiva; «Por definir», «Subcontrato», «MTG3»… = sem máquina. | Estado, Carga, Gantt | confirmada: app/sector/machine_choice.py:56; app/sector/machine_choice.py:18,25 |
| Máquina sugerida | Aprendizagem (Carteira 5, Tabela 1, histórico 1) > previsão (estimates.apply) | Ao Planear grava-se em sector_member_machine com origem «sugerida» (não alimenta a aprendizagem). | Lupa, Planear, coluna «sugerida» da Carga | confirmada: app/sector/selection.py:205; app/sector/selection.py:454,456 |
| 1.ª/2.ª Oper. (MTG3) | Excel; valores por defeito 119/0 | Excel > defeito. | Saldo, horas, operações seguintes | confirmada: app/raw/registration.py:20,23 |
| Data Corte | Excel; manual | Manual > Excel (segue a origem). | Prazo MTG3; prazo de reserva MTG2 | confirmada: app/sector/priority.py:63 |
| Picking (MTG2) | Folha Picking; coluna da linha; manual | Manual > folha (semana única) > linha; conflito → nenhum; ano deduzido pela Data Corte. | Prazo MTG2 | confirmada: app/planning_dates.py:50; app/planning_dates.py:134 |
| Prazo do setor | Data Corte; Picking; semana escolhida; Galvanização; coluna W | MTG3 Data Corte; MTG2 Picking → semana escolhida → Galvanização → Data Corte; W 2026/53 = estacionada. | Carteira (janela, semana), Carga (semana da carga), Gantt | confirmada: app/sector/priority.py:68; app/sector/priority.py:51 |
| Horas | Taxa confirmada; Histórico; tabela de velocidades; Excel (Mt\h / CapacidadeMáquinas) | Hoje: Manual > Histórico (¼–4× Excel) > tabela Excel > Excel (coluna C na MTG2, ×3 Thomas só no motor). Decidido a 08/10: Confirmada > Excel × eficiência, ×3 da Thomas em todo o lado, coluna E/F na MTG2. | Carteira (KPI), Carga, Gantt | por rever: app/raw/productivity.py:442; app/raw/capacity_revision.py:?; app/sector/estimates.py:? |
| Operação dos registos MES MTG3 | extra.operation_code → operação única aplicável da peça | Nunca deduzida da máquina. | Atribuição de produção à operação | confirmada: app/planning_production.py:15 |

## Comparação com `docs/auditoria-fluxo-2026-10-08/evidencia/antes-20261007T2308.json`

Resumo: {'explicada': 311, 'só antes': 47, 'só depois': 9, 'inexplicada': 69, 'origem mudou': 83}

| Caso | Verificação | Campo | Página | Antes | Depois | Esperado | Estado |
|---|---|---|---|---|---|---|---|
| cantoneiras|OF264095|IT220D|L45X45X5|1060|4|1 | C06 | horas | carga | 0.0496 | 0.0353 | 0.0353 | inexplicada |
| cantoneiras|OF264095|IT220E|L45X45X5|1060|4|1 | C06 | horas | carga | 0.0496 | 0.0353 | 0.0353 | inexplicada |
| cantoneiras|OF264095|IT256D|L45X45X5|1052|4|1 | C06 | horas | carga | 0.0492 | 0.0351 | 0.0351 | inexplicada |
| cantoneiras|OF264095|IT256E|L45X45X5|1052|4|1 | C06 | horas | carga | 0.0492 | 0.0351 | 0.0351 | inexplicada |
| cantoneiras|OF264095|IT259D|L45X45X5|1177|2|1 | C06 | horas | carga | 0.0275 | 0.0196 | 0.0196 | inexplicada |
| cantoneiras|OF264095|IT259E|L45X45X5|1177|2|1 | C06 | horas | carga | 0.0275 | 0.0196 | 0.0196 | inexplicada |
| cantoneiras|OF264095|IT259FA|L45X45X5|1177|2|1 | C06 | horas | carga | 0.0275 | 0.0196 | 0.0196 | inexplicada |
| cantoneiras|OF264095|IT259FB|L45X45X5|1177|2|1 | C06 | horas | carga | 0.0275 | 0.0196 | 0.0196 | inexplicada |
| cantoneiras|OF264095|IT283D|L45X45X5|1628|2|1 | C06 | horas | carga | 0.0381 | 0.0271 | 0.0271 | inexplicada |
| cantoneiras|OF264095|IT283E|L45X45X5|1628|2|1 | C06 | horas | carga | 0.0381 | 0.0271 | 0.0271 | inexplicada |
| cantoneiras|OF264095|IT285D|L45X45X5|1795|2|1 | C06 | horas | carga | 0.042 | 0.0299 | 0.0299 | inexplicada |
| cantoneiras|OF264095|IT285E|L45X45X5|1795|2|1 | C06 | horas | carga | 0.042 | 0.0299 | 0.0299 | inexplicada |
| cantoneiras|OF264095|IT291D|L45X45X5|1170|2|1 | C06 | horas | carga | 0.0274 | 0.0195 | 0.0195 | inexplicada |
| cantoneiras|OF264095|IT291E|L45X45X5|1170|2|1 | C06 | horas | carga | 0.0274 | 0.0195 | 0.0195 | inexplicada |
| cantoneiras|OF264095|IT294FA|L45X45X5|1294|2|1 | C06 | horas | carga | 0.0303 | 0.0216 | 0.0216 | inexplicada |
| cantoneiras|OF264095|IT294FB|L45X45X5|1294|2|1 | C06 | horas | carga | 0.0303 | 0.0216 | 0.0216 | inexplicada |
| cantoneiras|OF264346|DLA157|L45X45X4|1082|16|1 | C06 | horas | carga | 0.1443 | 0.3847 | 0.3847 | inexplicada |
| cantoneiras|OF264346|DLA158|L45X45X4|461|16|1 | C06 | horas | carga | 0.0615 | 0.1639 | 0.1639 | inexplicada |
| cantoneiras|OF264346|DLA433D|L75X75X6|4000|8|1 | C06 | horas | carga | 0.2667 | 0.7111 | 0.7111 | inexplicada |
| cantoneiras|OF264346|DLA46|L70X70X6|2160|8|1 | C06 | horas | carga | 0.144 | 0.384 | 0.384 | inexplicada |
| cantoneiras|OF264346|DLA7|L70X70X6|2200|8|1 | C06 | horas | carga | 0.1467 | 0.3911 | 0.3911 | inexplicada |
| perfis|OF265215|PR_R2|M10|42|3|1 | C06 | horas | carga | 0.0184 | 0.0153 | 0.0153 | inexplicada |
| perfis|OF265261|9731Q003|108X4|2896|3|1 | C06 | horas | carga | 0.0816 | 0.0972 | 0.0972 | inexplicada |
| perfis|OF265627|3826K001|48.3X2.9|95|3|1 | C06 | horas | carga | 0.0672 | 0.0658 | 0.0658 | inexplicada |
| perfis|OF265627|3826K002|60.3X2.9|2700|1|1 | C06 | horas | carga | 0.0283 | 0.0277 | 0.0277 | inexplicada |
| perfis|OF265627|5136V002|76.1X3.2|2002|1|1 | C06 | horas | carga | 0.0397 | 0.0389 | 0.0389 | inexplicada |
| perfis|OF265676|CC0111A4613|20X10X1|550|13|1 | C06 | horas | carga | 0.0487 | 0.0405 | 0.0405 | inexplicada |
| perfis|OF265704|7182V001|76.1X3.2|229|3|1 | C06 | horas | carga | 0.119 | 0.1167 | 0.1167 | inexplicada |
| perfis|OF265704|CCAB18A4105|88.9X4|300|1|1 | C06 | horas | carga | 0.0577 | 0.0566 | 0.0566 | inexplicada |
| perfis|OF265706|CA1497A4502|10|104|2|1 | C06 | horas | carga | 0.0122 | 0.0102 | 0.0102 | inexplicada |
| perfis|OF265850|CA1012A4028|10|277|1|1 | C06 | horas | carga | 0.0061 | 0.0051 | 0.0051 | inexplicada |
| perfis|OF265850|CA1012A4029|21.3X2.6|22|1|1 | C06 | horas | carga | 0.0119 | 0.0099 | 0.0099 | inexplicada |
| perfis|OF265924|5877T6103|12X12|80|4|1 | C06 | horas | carga | 0.0449 | 0.0374 | 0.0374 | inexplicada |
| perfis|OF266052|CI5422A4001|20X10X1|445|2|1 | C06 | horas | carga | 0.0075 | 0.0062 | 0.0062 | inexplicada |
| perfis|OF266052|CI7712A4002|60.3X2.9|230|2|1 | C06 | horas | carga | 0.0816 | 0.0679 | 0.0679 | inexplicada |
| perfis|OF266126|4708N101|20|45|4|1 | C06 | horas | carga | 0.098 | 0.0816 | 0.0816 | inexplicada |
| perfis|OF266126|A393S001|76.1X3.2|1502|1|1 | C06 | horas | carga | 0.0571 | 0.0476 | 0.0476 | inexplicada |
| perfis|OF266126|CI7712A4002|60.3X2.9|50|1|1 | C06 | horas | carga | 0.0408 | 0.0339 | 0.0339 | inexplicada |
| perfis|OF266134|CI7712A4002|60.3X2.9|125|10|1 | C06 | horas | carga | 0.283 | 0.2775 | 0.2775 | inexplicada |
| perfis|OF266193|4303V001|76.1X3.2|453|10|1 | C06 | horas | carga | 0.3966 | 0.3889 | 0.3889 | inexplicada |
| perfis|OF266193|4303V002|60.3X2.9|981|12|1 | C06 | horas | carga | 0.3396 | 0.333 | 0.333 | inexplicada |
| perfis|OF266193|4303V003|76.1X3.2|453|1|1 | C06 | horas | carga | 0.0397 | 0.0389 | 0.0389 | inexplicada |
| perfis|OF266193|4303V004|76.1X3.2|518|1|1 | C06 | horas | carga | 0.0397 | 0.0389 | 0.0389 | inexplicada |
| perfis|OF266193|4303V005|60.3X2.9|228|2|1 | C06 | horas | carga | 0.0566 | 0.0555 | 0.0555 | inexplicada |
| perfis|OF266193|5145P003|76.1X3.2|434|6|1 | C06 | horas | carga | 0.238 | 0.2333 | 0.2333 | inexplicada |
| perfis|OF266209|3378V004|114X3.6|2185|2|1 | C06 | horas | carga | 0.052 | 0.0619 | 0.0619 | inexplicada |
| perfis|OF266209|3378V004|76X3.6|5325|2|1 | C06 | horas | carga | 0.0341 | 0.0406 | 0.0406 | inexplicada |
| perfis|OF266209|CI6518A4010|133X4|400|2|1 | C06 | horas | carga | 0.0675 | 0.0804 | 0.0804 | inexplicada |
| perfis|OF266211|CI7115A4001|108X4|70|1|1 | C06 | horas | carga | 0.0707 | 0.0693 | 0.0693 | inexplicada |
| perfis|OF266221|CI7812A4002|76.1X3.25|125|1|1 | C06 | horas | carga | 0.0403 | 0.0395 | 0.0395 | inexplicada |
| perfis|OF266221|CT0501A4513|10|300|2|1 | C06 | horas | carga | 0.0122 | 0.0102 | 0.0102 | inexplicada |
| perfis|OF266221|CT2715A4001|16|230|2|1 | C06 | horas | carga | 0.0314 | 0.0261 | 0.0261 | inexplicada |
| perfis|OF266221|CT2715A4056|12|82|2|1 | C06 | horas | carga | 0.0176 | 0.0147 | 0.0147 | inexplicada |
| perfis|OF266221|CT3115A4053|16|136|4|1 | C06 | horas | carga | 0.0627 | 0.0522 | 0.0522 | inexplicada |
| perfis|OF266222|CT3115A4052|12|370|1|1 | C06 | horas | carga | 0.0088 | 0.0073 | 0.0073 | inexplicada |
| perfis|OF266287|CI7812A4200|76.1X3.25|427|4|1 | C06 | horas | carga | 0.161 | 0.1579 | 0.1579 | inexplicada |
| perfis|OF266304|CI5422A4001|20X10X1|445|3|1 | C06 | horas | carga | 0.0078 | 0.0076 | 0.0076 | inexplicada |
| perfis|OF266304|CI7712A4002|60.3X2.9|230|3|1 | C06 | horas | carga | 0.0849 | 0.0832 | 0.0832 | inexplicada |
| perfis|OF266311|CI7712A4002|60.3X2.9|150|1|1 | C06 | horas | carga | 0.0283 | 0.0277 | 0.0277 | inexplicada |
| perfis|OF266364|CA2219A4161|10.6|300|9|1 | C06 | horas | carga | 0.0619 | 0.0515 | 0.0515 | inexplicada |

## Pedidos às páginas

348 GET; erros: 1; 5xx: 0; tempo médio 320 ms.
