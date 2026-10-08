# Planeamento: dados certos, Carteira, Carga e turnos, Gantt, Cenários e Definições (08/10/2026)

Escrito para: o Luís.

## Em resumo
- **Ativação 1** (08/10, 09:35–09:39, cerca de 4 min sem serviço): Etapas 1 e 2, dados certos e Carteira/Carga.
- **Ativação 2** (08/10, 11:05, 16 s sem serviço + 1 min de aquecimento): Etapas 3 a 5, com as migrações 052, 053 e 054.
- **Auditoria «depois»** (705 linhas reais, origem → Tabela → Carteira → Carga → Gantt): os únicos casos sem explicação eram defeitos do próprio script de auditoria, já corrigido. As restantes diferenças são problemas da origem, conhecidos.
- **Testes:** suíte completa com 1 393 a passar. As 9 falhas são as de sempre (2 por CSV fora do git). Os 9 testes de browser passam contra a produção, com as gravações intercetadas.

## 1. Problemas encontrados e corrigidos
| # | Problema | Evidência | Correção |
|---|---|---|---|
| F01 | Horas calculadas para a máquina da Tabela e não para a escolhida na Carteira | OF264095: 26,3 h na Carteira contra 19,9 h no Gantt | As horas seguem a máquina efetiva. Hoje: 18,75 h na Tabela, na Carteira e na Carga |
| F02 | Cada página usava uma velocidade diferente (histórico, Excel, com ou sem ×3 da Thomas) | Vanguard: 21 485 mm²/h medidos contra 9 200 do Excel | Uma só regra (decisão tua): Confirmada > Excel × eficiência da máquina; ×3 da Thomas como no Excel; MTG2 pela coluna E/F |
| F16 | Excel das cantoneiras com 5 dias | O de 07/10 estava em `SAIDA/`; a importação só lia a raiz | O sync carrega o mais recente entre a raiz e `SAIDA/` (decisão tua). Já carregou o de 07/10 |
| F04/F05 | Camada de pesquisa parada a 29/09 ainda mandava no saldo | 307 linhas fechadas mudavam de saldo a cada recálculo | O saldo principal é sempre o da app; a camada de pesquisa só fica nas operações seguintes |
| F08 | Linhas das cantoneiras sem peso | 1 580 linhas | Peso pela geometria quando a Tabela de pesos não tem o perfil. Hoje restam 3 |
| F06/F07 | Linhas repetidas e produção acima da QTD contadas sem aviso | 14 linhas repetidas (+477 m); 21 linhas com produção > QTD | Aviso numa linha, só quando há casos |
| F09/F21 | Desconhecido mostrado como 0 (kg, metros, peças) | OF266133: 0,0 kg | Mostra «—» e conta à parte; uma só fonte para os kg |
| F12/F13 | Trabalho Planeado atrasado invisível na Carga; recomendação contraditória | XP T4 S41: 243 h no detalhe contra 30 h na grelha | Atrasado separado por tipo; a recomendação diz «inclui N h atrasadas» |
| F17 | Serrotes do pav.1 bloqueados no Gantt técnico | 460 operações | O grupo de operadores limita quantos trabalham, não o horário |
| F18 | Posto Fita pav.1 contado a dobrar com o Doall e a Thomas | 60 + 30 h | Uma só capacidade, com nota na linha |
| F19/F20/F24/F25/F26 | Leitores de números diferentes; edição na Tabela congelava campos; dia de Berlim; sugestões com linhas excluídas; dois rótulos para «sem família» | — | Corrigidos |
| S01 | Gravar uma parte das Definições apagava as outras chaves | `settings.py` | Corrigido |
| — | Mudar só a quantidade numa linha já planeada não gravava | `selection.py` | Corrigido (necessário para o «%») |

Ficou como decidiste: **o OCR substitui o Excel mesmo quando é menor**. As 4 linhas MTG2 com +6 639 peças (ex.: OF265528) estão no relatório «depois» para conferir no MES.

## 2. Funcionalidades
- **Carteira:**
  - cabeçalho e Subtotal fixos ao fazer scroll, alinhados com o scroll horizontal;
  - KPIs da semana escolhida no Prazo, iguais à célula da Carga;
  - ordenação por data de corte mais próxima (cantoneiras) ou de picking mais próxima (perfis), com atrasadas, sem data e estacionadas tratadas à parte;
  - botão **«%»** para planear parte de uma OF em peças ou metros. Mostra o saldo, o escolhido e o resto; o resto fica na Carteira; a parte planeada chega à Carga, à duração e ao Gantt; planear não regista produção.
- **2.ª operação das cantoneiras:** Saca bocados, Plasma manual, Fresadora e Prensa saíram de todas as listas, com uma linha «N operações de 2.ª operação fora do plano». Os cálculos não mudaram.
- **Carga e turnos:** barra de vistas com Máquinas · Setores · Perfis · Famílias de produto · Famílias SKU · Calendário · Capacidade e prazos · Cenários. Todas as vistas somam igual às máquinas, semana a semana.
- **Capacidade e prazos:**
  - OF que atrasam, em risco e já em atraso;
  - recurso limitante (Peddi 8 nas cantoneiras, recupera a 05/01/2027; Serrote Disco pav 1 nos perfis, 22/01/2027);
  - mapa máquina × dia ou × semana: 100 % = «completa», nunca erro;
  - riscos principais com margem em dias úteis;
  - bloco «Previsão com dados em falta», com o motivo.
- **Calendário diário:**
  - previsão por dia: capacidade, OF, conclusões, cortes, pickings e entregas;
  - clicar num dia abre o detalhe por máquina;
  - «Realizado neste dia» (MES) sempre separado da previsão.
- **Gantt:**
  - mostra o plano em uso do motor;
  - **edição manual:** arrastar ao dia ou mudar dia, hora e máquina no diálogo; faixa «Edição manual ativa · … · Desfazer»; caixas «Fixada»; impacto e avisos depois de gravar, nunca bloqueios.
  - Mudar de máquina grava também a escolha da Carteira.
  - Regra: a alteração fica até a retirares ou até a OF deixar de ter trabalho planeado nessa máquina.
- **Cenários:**
  - tipos: cancelar OF, OV ou linha; máquina parada; turnos; pessoas em falta; urgente; prazo;
  - comparação com o plano em uso: o que passa ou deixa de atrasar, Δ de conclusão por OF com o porquê, máquinas e pessoas;
  - «Aplicar» só com confirmação, com Desfazer por alteração; as pessoas em falta ficam só como simulação.
- **Definições «Planeamento»:**
  - eficiência por máquina, com o medido ao lado (ex.: Peddi 8 71 % do Excel);
  - folga (2 dias úteis);
  - clientes prioritários;
  - pessoas por máquina e por turno;
  - política de prazo;
  - cada parâmetro diz o que muda e se é medido ou pressuposto. Cada fator aplica-se num só sítio.

## 3. Números iguais entre páginas (auditoria «depois», 08/10)
| | Peças | Metros | Toneladas |
|---|---|---|---|
| Cantoneiras: Carteira = Carga | 218 980 | 431 320 | 2 987,9 |
| Perfis: Carteira = Carga | 81 318 | 71 737 | 1 125,0 |

- KPI da semana 41 = célula da Carga, máquina a máquina, nos dois setores.
- Σ horas da previsão = Σ horas da Carga em todas as máquinas.

## 4. Motor de cenários e replaneamento: solução e porquê
É uma **fila por máquina, determinística e de capacidade finita** (`app/sector/dispatch.py` + `forecast.py`), sobre a mesma população e as mesmas horas da Carga.
- **Porque não o CP-SAT que já existia:**
  - nunca colocou uma ordem com dados reais;
  - não aguenta as ~17 000 operações das cantoneiras;
  - não dá sempre o mesmo resultado;
  - não explica porque mudou.
- **A fila:**
  - calcula as cantoneiras em menos de 2 s;
  - explica cada atraso («acaba quando a máquina fizer as X h que tem à frente»);
  - compara cenário e plano em uso com as mesmas entradas, por isso a diferença é só o efeito das alterações.
- O Gantt técnico (CP-SAT) ficou como estudo.

## 5. Pendentes
- **Contigo:**
  - limpeza do disco de 07/10 a meio: falta memória partilhada no Postgres, o que obriga a reiniciar a base, e falta uma permissão de tabelas temporárias;
  - apagar o `SAIDA/Met2_Plan_Perfis.xlsm` antigo (21/09) do Drive;
  - prazo das cantoneiras: Data Corte (fica) ou a semana W;
  - confirmar que Fita pav.1 = Fita + Doall + Thomas;
  - as 4 OF com linhas repetidas;
  - pessoas disponíveis por turno (preencher nas Definições).
- **Origem:**
  - OF com gralhas;
  - 5 735 linhas sem Data Corte;
  - folhas OCR repetidas;
  - horas «7:30» mal lidas;
  - Tabela de pesos incompleta.
- **Fora de âmbito por falta de dados:** setups, operadores por grupo, famílias SKU dos perfis.
- **Timer semanal de prolongamento dos calendários** (acabam em 2027-W39): precisa de autorização.
