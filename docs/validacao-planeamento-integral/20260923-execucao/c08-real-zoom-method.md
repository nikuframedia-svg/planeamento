# C08 — Deslocamento horizontal, teclado e zoom real

Revisão `efb600edde8c45bf564c453a299e925417b6887a304973304ed2f942cbf7d17b`.

O teste `tests/planning_zoom_accessibility_browser.cjs` usa exclusivamente a aplicação de teste em 18113. Cada cenário abre um perfil Chromium temporário. Uma extensão local de teste aplica `chrome.tabs.setZoom(2)` e confirma `chrome.tabs.getZoom() === 2`. A janela conserva 1440 px, o viewport tem 720 CSS px, `devicePixelRatio` é 2 e `visualViewport.scale` é 1. Não se usa emulação de viewport nem escala de dispositivo para substituir zoom no cenário de 200%. As capturas desse cenário são feitas diretamente por CDP para conservar a imagem integral da janela ampliada.

## Falhas reproduzidas e correções

- `c08-real-zoom-first.json`: em Cantoneiras a 390 px, as colunas fixadas cobriam o centro da última coluna apesar de a barra estar no limite direito. Agora a grelha suspende a fixação horizontal quando esta não deixa espaço suficiente para ler as colunas seguintes. As escolhas guardadas de fixação não são alteradas.
- `c08-real-zoom-controls.json`: a 200%, o deslocamento automático centrava 60 cabeçalhos de Perfis atrás das colunas fixadas. A grelha passa a declarar `scroll-padding-left` correspondente à largura fixada efetiva. O browser reserva esse espaço ao deslocar o elemento selecionado. A navegação real por teclado confirma que a célula seguinte fica visível.
- `c08-real-zoom-pin-fixed.log`: uma falha intermédia do teste tentou clicar em «Última coluna» quando o arrasto já tinha chegado ao fim e o botão estava corretamente desativado. O teste regressa ao início antes de exercitar o botão; o comportamento da aplicação não foi alterado para esse caso.

## Resultado final

`c08-real-zoom-final.json` e respetivo log: código 0, oito cenários, zero falhas de acessibilidade verificadas e zero erros JavaScript. Perfis e Cantoneiras foram testados a 1440, 1024 e 390 px e com zoom real de 200%, sempre com 500 linhas carregadas e todas as colunas ativas.

As 65 colunas de Perfis e 72 de Cantoneiras foram percorridas em cada cenário: 548 verificações de posição e de elemento efetivamente atingido, sem colunas tapadas. O arrasto real da barra chegou ao limite direito nos oito casos; botões de primeira/última coluna e Home/End passaram. As preferências de fixação anteriores e posteriores coincidem.

Foram abertos 48 painéis: Colunas, Mais, Guardar vista, Fórmula, Análise e Fontes, nos oito cenários. Controlos acessíveis, deslocamento dentro dos painéis, movimentos de coluna com teclado, abertura do editor, foco inicial, cancelamento e reposição do foco passaram. O manifesto de capturas contém os SHA-256 das 56 imagens.

**Calibri continua ausente.** A instrumentação CDP identifica Liberation Sans em todos os cenários. Os controlos auditados usam aproximadamente 14,67 CSS px, equivalentes a 11 pt; isto não comprova a presença de Calibri. C08.3 e C08 global permanecem incompletos. A validação tipográfica de todas as páginas de Planeamento, além da RAW, continua identificada em C08.2.

## Dados, ficheiros e limite do isolamento

`c08-real-zoom-final-state.json` confere 116 ficheiros, as 27 alterações tracked preexistentes preservadas, as gerações 3769/3770 e os hashes das fontes/necessidades iguais aos de C03. Nenhum worker isolado ficou a correr e os processos operacionais não foram reiniciados.

Foi verificado por HTTP que **18113 e 8113 servem os mesmos ficheiros estáticos deste diretório**. A base e as escritas de teste são isoladas; a interface servida em 8113 pode refletir estas alterações sem reinício. Declarações anteriores de «serviços operacionais inalterados», baseadas apenas nos PID/comandos, devem ser entendidas exclusivamente como ausência de reinício, não como isolamento dos ficheiros servidos. Esta etapa não constitui publicação integral C12 nem migração da base operacional. Os ficheiros dos kanbans que já estavam alterados permanecem preservados.
