# C00 — Inventário e diagnóstico concluídos

O inventário `c00-complete-traceability.json` cobre os 137 campos das duas RAW de planeamento, 80 entradas dos catálogos de formulário (40 por área), cinco campos administrativos, e 421 ocorrências de campos nos 16 contratos área/vista (oito vistas nas duas áreas). Não são 421 identificadores distintos. As colunas de fórmula local também foram consultadas: não há fórmulas personalizadas ativas neste clone.

As 43 regras têm entradas, unidades, exemplo esperado independente, implementação localizada e 74 referências verificadas. As células foram lidas diretamente do XML dos três ficheiros originais, incluindo texto, strings e fórmulas partilhadas. As fontes conservaram os hashes. O VBA foi reextraído do XLSM usando a dependência isolada `/tmp/planning-vba-tools` já disponível; código e hashes estão em `c00-verified-vba.json`. As referências SQL foram conferidas no esquema real da cópia isolada.

Corrigidas referências a células vazias (Q7/S7/W7/AR7), um intervalo invertido AS7:AM7, uma folha de Cantoneiras sem intervalo concreto e a atribuição incorreta de horas OCR a uma coluna inexistente de validated_sheets. A origem real de horas é production_records.hours_worked, agrupada pela folha. O resultado anterior está conservado em `c00-anchors-before.json`. Campos antigos material_available_date/material_lot não têm qualquer entrada preenchida na coluna de origem; essa ausência fica identificada, sem exemplo inventado.

As 20 famílias foram verificadas: 11 geometrias com função VBA concreta e nove famílias por correspondência exata da tabela, incluindo varão roscado. A evidência independente existente abrange 493 casos de catálogo. O inventário não confunde essa cobertura com a aprovação de todas as fórmulas: 23 regras têm auditoria aritmética integral e as 20 restantes mantêm a validação C04/C10 pendente. A ausência de metadados de unidade em alguns campos numéricos do contrato runtime está assinalada no inventário/final-state, com a unidade semântica documentada; não é escondida como ausência de dimensão.

Os seis grupos de problemas de C00.3 estão ligados à baseline e às regressões atuais em `c00-baseline-findings.json`. OF264774 foi relida na API da geração4259, conservando corte840 nas três peças e saldos de abocardar0/75/172. O diagnóstico atual de fontes mantém OCR original não configurado no clone; isso não prova acesso nem reconciliação da instância Windows. Calibri real continua pendente. Estes são requisitos de execução ainda abertos, não lacunas do diagnóstico inicial.

Seis testes do leitor de fontes passaram, incluindo strings compostas, instrução textual, fórmula partilhada cujo mestre não foi pedido e rejeição de referências invertidas/indefinidas. Não houve mudanças na aplicação, reconstruções da base ou reinícios nesta etapa. Fontes/necessidades,27ficheiros tracked preexistentes e gerações4259/4260 preservados. Os estáticos continuam partilhados com Planeamento8113 conforme documentado.

C00.1/C00.4 mantêm as provas anteriores de baseline/isolamento; C00.2/C00.3 aprovados nesta etapa. C00 global aprovado como inventário e diagnóstico. C01/C02/C04/C05/C08/C10/C11/C12 e publicação integral continuam pendentes.

## Mapa das 43 regras

| Regra | Campos | Origem verificada | Unidade | Exemplo esperado |
|---|---|---|---|---|
| F01 | description | Layout:Folha1:L2; Perfis:Planeamento:J7 | texto | Varão redondo, Ø20, L1200, S355JR: descrição contém estes quatro factos e não inventa espessura |
| F02 | cut, ocr_cut | Layout:Folha1:P2; Perfis:Planeamento:V7 | un. | 396 + 444 = 840; repetir o evento396 mantém840 |
| F03 | boc, ocr_boc | Layout:Folha1:Q17; Perfis:Planeamento:W144 | un. | 298 abocardadas permanece298 quando o corte é315 |
| F04 | cut_pct | Layout:Folha1:R2 | % | C315/Q500 = 63 |
| F05 | boc_pct | Layout:Folha1:S17 | % | B298/Q500 com abocardarSim = 59.6 |
| F06 | final_pct | Layout:Folha1:T7 | % | C315,B298,Q500: Sim59.6; Não63; desconhecido indisponível |
| F07 | remaining, production_excess | Layout:Folha1:U7; Perfis:Planeamento:AS7 | un. | Q500,C315 = 185; Q5,C7 = 0 com excesso2 |
| F08 | boc_remaining | Layout:Folha1:V7 | un. | Q500,B298,Sim = 202; Não = 0 |
| F09 | section_unit | Perfis:Planeamento:AX7; Perfis:AreaSecaoCorte:B3:C700; VBA:FuncAreaPerf.bas | mm² | VarãoØ20 = 314.1592653589793; tuboØ76.1,e3.25 = 743.8113306455535 |
| F10 | section_total, section_pending | Layout:Folha1:AF2; Perfis:Planeamento:AP7:AY7 | mm² | 314.1592653589793 × 48 = 15079.644737231007 total; saldo20 = 6283.185307179586 pendente |
| F11 | quantity_to_plan | Layout:Folha1:AI2; Perfis:Planeamento:AS7 | un. | Q100,P40 = 60; local novoQ100 sem produção = 100 |
| F12 | hours_pct | Layout:Folha1:AJ2; Perfis:Planeamento:AU7; Perfis:PlanDisponibilidadeSemanal:I2:K2 | % | (2h + 8h) / 14h = 71.42857142857143 em ambas as linhas |
| F13 | expected_week, expected_year | Layout:Folha1:AK2; Perfis:Planeamento:AV7:AW7 | semanaISO | 2027-01-01 = 2026-W53 |
| F14 | weight_unit | Perfis:Planeamento:DB7:DC7; VBA:FuncAreaPerf.bas | kg | A1000mm²,L2000mm,aço7850 = 15.7 |
| F15 | weight | Layout:Folha1:AL2; Perfis:Planeamento:DB7 | kg | 15.7kg × 60 = 942 |
| F16 | total_length, total_m | Layout:Folha1:AN2; Perfis:Planeamento:BR7 | mm e m | 48 × 1200 = 57600mm = 57.6m |
| F17 | stock_length_mm | Layout:Folha1:AO2; Perfis:Planeamento:BS7 | mm | L6000 sugere6000; L6001 sugere12000; manual9000 prevalece |
| F18 | bars | Layout:Folha1:AP2; Perfis:Planeamento:BT7 | un. | saldo5,S6000,L2500 = ceil(5/floor(6000/2500)) = 3 |
| F19 | remaining_m | Perfis:Planeamento:AS7; Perfis:Planeamento:AM7 | m | saldo60,L2000 = 120 |
| F20 | theoretical_hours | Perfis:Planeamento:AY7:AZ7; Perfis:CapacidadeMáquinas:C2 | h | 30000mm² / 10000mm²/h = 3h; ThomasExcelQ51 usa fator3, taxa manual não |
| F21 | deadline_status, overdue | Layout:Folha1:AH2; Perfis:Planeamento:AR11 | estado | data ontem com saldo1 = prazo ultrapassado; saldo desconhecido não é conclusão |
| G01 | made, ocr_quantity, ocr_op_* | Cantoneiras:Plan_ produção:AA7; Cantoneiras:Dados:H3:I3 | un. | op119=40,op209=15: principal40, nunca55 |
| G02 | made_pct | Cantoneiras:Plan_ produção:O7:AA7 | % | 40/100 × 100 = 40 |
| G03 | remaining, secondary_remaining, production_excess | Cantoneiras:Plan_ produção:AG7; Cantoneiras:Plan_ produção:S7:T7 | un. | Q100,principal40,secundária15 = 60 e85 |
| G04 | total_length, total_m | Cantoneiras:Plan_ produção:AM7 | mm e m | Q100,L2000 = 200000mm = 200m |
| G05 | remaining_m | Cantoneiras:Plan_ produção:BK7 | m | 60 × 2000 / 1000 = 120 |
| G06 | speed_m_h, rate_source, applied_rate_value, applied_rate_unit | Cantoneiras:Plan_ produção:AL7 | m/h ou método explícito | manual30m/h prevalece sobre histórico26.6666667 eExcel80 |
| G07 | theoretical_hours | Cantoneiras:Plan_ produção:AO7 | h | 120m / 30m/h = 4h |
| G08 | weight_unit | Cantoneiras:Plan_ produção:AP7; Cantoneiras:Tabela pesos:B3:C462 | kg | catálogo de ensaio3kg/m,L2000 = 6kg; realL45X45X4 usa célula comprovada |
| G09 | weight | Cantoneiras:Plan_ produção:AS7 | kg | 6kg × 60 = 360kg, sem multiplicar por operações |
| G10 | quantity_to_plan | Cantoneiras:Plan_ produção:AG7 | un. | Q100,P40 = 60 |
| G11 | expected_week, expected_year, imported_week | Cantoneiras:Plan_ produção:B7 | semanaISO | 2027-01-01 = 2026-W53; W39 sem ano fica por calendarizar |
| G12 | description, material_description, deadline_status, overdue | Cantoneiras:Plan_ produção:P7; Cantoneiras:Plan_ produção:L7 | texto e estado | preservar L45X45X4 S355J0 EN10025; saldo desconhecido não fecha a peça |
| H01 | available_hours | Perfis:PlanDisponibilidadeSemanal:F2:H2; SQL:planning_mtg.raw_objects:definition[kind=calendar] | h | 2 × 7.5 - 1 = 14 |
| H02 | planned_hours | Perfis:PlanDisponibilidadeSemanal:I2; Perfis:CapacidadeMáquinas:K2 | h | 2 + 8 = 10; uma operação fechada de5h não entra |
| H03 | actual_hours | SQL:planning_mtg.raw_objects:definition.hours[kind=worked_hours]; SQL:mes_kanban.production_records:hours_worked; SQL:mes_kanban.validated_sheets:sheet_uid | h | folha5h com10peças conta5h, nunca50h |
| H04 | free_hours | Perfis:PlanDisponibilidadeSemanal:J2 | h | 14 - 10 = 4; 14 - 16 = -2 |
| H05 | occupancy | Perfis:PlanDisponibilidadeSemanal:K2 | % | 10/14 × 100 = 71.42857142857143; 16/14 = 114.28571428571429 |
| H06 | equivalent_shifts | Perfis:CapacidadeMáquinas:L2 | turnos | 10 / 7.5 = 1.3333333333333333 sem arredondar a inteiro |
| H07 | capacity_total | Perfis:PlanDisponibilidadeSemanal:W2 | unidade do método | 14h × 30m/h = 420m; 2min/un. = 30un./h |
| H08 | capacity_free | Perfis:PlanDisponibilidadeSemanal:L2 | unidade do método | 4h × 30m/h = 120m; -2h × 30m/h = -60m |
| H09 | historical_rate | SQL:planning_mtg.raw_contents:detail.productivity; SQL:mes_kanban.production_records:quantity; SQL:mes_kanban.production_records:hours_worked | unidade/h | 100m/5h e300m/10h = 400/15 = 26.666666666666668 |
| H10 | rate_source, applied_rate_value, applied_rate_unit | Perfis:CapacidadeMáquinas:C2; Cantoneiras:Plan_ produção:AL7; SQL:planning_mtg.raw_objects:definition[kind=rate] | unidade/método | manual30 > histórico26.6666667 > Excel80; expirado não prevalece |
