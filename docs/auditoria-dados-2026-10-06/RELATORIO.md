# Auditoria dos dados e da lógica do planeamento — 06/10/2026

Escrito para: o Luís.

## Em resumo
- **Âmbito:** 364 agentes recalcularam os dados a partir das fontes (Excel, CPIS, folhas OCR, camada de pesquisa) e compararam-nos com o que a app mostra. Cada problema foi reproduzido por um segundo agente, que também procurou uma decisão escrita que o justificasse.
- **Resultado:** 128 problemas reportados.
  - 95 confirmados;
  - 32 funcionam como foi decidido (lista para confirmares);
  - 1 não se reproduziu;
  - 240 verificações deram certo, com números.
- **Corrigidos e ativos:** todos os erros de código confirmados, em duas rondas, com testes e dois revisores cada uma. Commits `893f0b0` (planeamento) e `930dbd0` (sincronização do Drive).
- **Não corrigidos:** os problemas da origem (Excel, CPIS, folhas OCR) e algumas decisões tuas. Estão nas secções 3 e 4.

## 1. O que mudou nos números (já ativo)
- **Cantoneiras:** 2 511 linhas abertas estavam sem saldo porque a coluna «Maq.» estava vazia. Agora têm saldo, como no Excel. A carteira MTG3 passa de cerca de 352 mil para **456 533 m** por fazer.
- **Máquinas confirmadas:** desde a confirmação de 05/10 não tinham horas do motor, porque os códigos das operações eram comparados em formatos diferentes. Agora têm horas: 3 833 operações nas cantoneiras e 717 nos perfis.
- **Taxa histórica:** as horas do turno contavam uma vez por cada página da folha, e uma taxa podia sair de uma só página. Corrigido com amostra mínima e plausibilidade (entre ¼ e 4 vezes a velocidade do Excel). Na Peddi 8, operação 119, a taxa fica em 107 m/h (o Excel diz 120).
- **Saldos antigos da camada de pesquisa (29/09):** deixam de passar por cima do Excel de 02/10 quando houve produção depois. São 7 linhas nos perfis (−84 peças) e 4 nas cantoneiras (−21).
- **Perfis:** 245 linhas tinham saldo na Carteira e não na Carga nem no Gantt. Agora têm nos três.
- **Folhas «DISCO PAV1» e «FITA PAV1»:** passam a contar como corte (46 linhas ativas, 27 OF).
- **Cantoneiras, peça com 2.ª operação:** já não anula a produção da barra de perfil completo (63 linhas ativas).
- **CPIS, cópia mais recente** (decisão tua de 06/10):
  - **conflitos:** de 152 OF para 0;
  - **fim previsto da Produção:** volta a aparecer em 92 OF;
  - **estado:** passa a ser mostrado tal como vem.
- **«2026/53» das cantoneiras:** é um marcador de linhas paradas. As 2 892 linhas deixam de contar como atrasadas e passam a «estacionada».
- **Carga:** aparecem as máquinas do setor sem calendário que têm trabalho (Fresadora, Plasma manual, Prensa, Abocardar). «Atrasado» passa a ter uma só definição: prazo antes de hoje.
- **Gantt técnico:** usa a mesma área de corte, o mesmo Picking, o mesmo saldo e as mesmas taxas que a Carga.
- **Sugestões de máquina:** deixam de propor máquinas que a ficha de capacidades exclui. São 114 sugestões a menos nas cantoneiras e 99 nos perfis.
- **Drive:** se o Excel for gravado numa subpasta, o sistema passa a avisar. Foi o que aconteceu a 30/09: a versão dos perfis ficou 48 h por importar.

## 2. Corrigido no código mas por confirmar contigo
- **6 OF** (OF264498, OF264564, OF264628, OF265034, OF265050, OF265586) voltaram a contar como abertas, porque a cópia CPIS mais recente diz «Em Produção». A outra diz «Fechada», e a OF265586 tem até fim real a 10/09. Convém confirmar no CPIS.
- **Cantoneiras:** pela Data Corte, quase toda a carga das máquinas está atrasada. Ou as Datas Corte no Excel estão por atualizar, ou o atraso é real.

## 3. Problemas na origem (quem resolve)
- **Planeadores (Excel):**
  - OF com gralhas: OF2629695, OF26422 e uma linha «26499» sem prefixo.
  - «Ficep XP T7/T8/T9» na OF266654: provavelmente célula arrastada.
  - Velocidade Mt\h arrastada na OF264158 (de 46 a 360 m/h).
  - 12 linhas de perfis repetidas (OF265943, OF266302), que a Carteira conta a dobrar.
  - Folha Picking: 550 de 784 linhas com semana 0.
  - 11 724 linhas das cantoneiras sem velocidade Mt\h ou comprimento.
  - Nomes de perfis diferentes entre a folha AreaSecaoCorte e o planeamento (HEA240 contra HEA240A): 172 linhas ficam sem área.
  - A Tabela de pesos das cantoneiras não tem 27 perfis em uso.
- **MES / folhas OCR:**
  - Horas escritas «7:30» ou «7H5» são gravadas como 730 ou 75 e rejeitadas; perde-se 31% das folhas com horas.
  - A maior parte das folhas não traz horas trabalhadas.
  - Duas folhas foram validadas duas vezes com a mesma imagem (OF262550).
  - Há linhas repetidas na mesma folha (OF265710, OF265256, OF265358).
  - 47% dos registos das cantoneiras não têm código de operação.
  - 10 registos com a OF mal lida.
- **Informática / CPIS:**
  - O CPIS direto nunca funcionou (tarefa no PC da fábrica). A app usa as duas cópias dentro dos Excel.
  - A camada de pesquisa está parada em 29/09.
  - A exportação do OCR original (127.0.0.1:18080) falhou 538 vezes hoje.
- **Ficha de capacidades:** exclui a Rapid 25T para L200X200X24, mas o Excel mostra 369 linhas produzidas nela. Também faltam os limites da 2.ª operação (Saca bocados, Fresadora, Prensa).

## 4. Precisa da tua decisão (nada foi aplicado)
- **Disco a 88%:**
  - o histórico de cálculos guardado (RAW) cresce 39 GB em 14 dias e só 2,2% está em uso. Proposta: limpeza com retenção, depois de backup.
  - Há 11,5 GB de backups do CRM dentro da pasta do Drive do planeamento, que atrasam cada sincronização cerca de 45 minutos. Onde devem ficar?
- **Arranque do servidor:** se o servidor reiniciar, a app não volta sozinha (serviço sem arranque automático) e o link Cloudflare é temporário. Proposta: ligar o arranque automático e um link fixo.
- **Calendários:** acabam em 2027-W39. Existe a função para os prolongar sozinha (`settings.extend_horizon`), por ligar.
- **Horas da Thomas:** a Carga usa o fator ×3 da Thomas nas «Horas segundo o Excel»; a Carteira e o Gantt não, por decisão de 01/10.
- **Crontab:** o comentário diz 07:15/13:15, mas corre às 08:15 e 14:15 (hora de Berlim). Corrige-se à mão.

## 5. Funciona como decidido (32)
Ver `evidencia/principal_final.json`, problemas com `verdict` = `funciona_como_decidido`. Alguns exemplos:
- a Carteira usa a velocidade do Excel e não a histórica (01/10);
- a máquina nunca serve de prova para a produção;
- a Picking com semana 0 conta como sem semana.

## Anexo
- `manifesto.json`: retrato dos dados auditados.
- `evidencia/principal_final.json` e `evidencia/a10_a11.json`: todos os problemas, com comandos para reexecutar.
- `evidencia/correcoes_ronda1.json` e `evidencia/correcoes_ronda2.json`: o que foi corrigido, com números antes e depois.
