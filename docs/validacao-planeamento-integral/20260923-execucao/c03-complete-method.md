# C03 — Registo manual completo, ambiente isolado

Revisão `731c699358389503f68ed7d1b80a0c75a6606f221aaed53aa8f22e71ed253961`.
Aplicação em localhost:18113 e base planning_integral. A publicação C12 continua pendente.

O percurso cria OF/OV sem seleção anterior e duas peças por OF, em Perfis e Cantoneiras. `c03-complete-run.json` conserva as respostas da criação original; repetições reutilizam as mesmas quatro identidades. O teste altera a primeira peça, reabre o formulário, confere todos os valores enviados, repete a gravação com a mesma chave de idempotência e verifica uma edição parcial e um conflito de revisão sem perda de dados. As seis necessidades anteriores permanecem byte a byte iguais na representação SQL auditada.

Foi corrigida a opção «0 · Sem segunda operação» de Cantoneiras: o motor já reconhecia zero, mas o catálogo do formulário não permitia escolhê-lo. A opção é não contável e indica a regra de planeamento como origem. Zero não pode ser operação principal, não duplica uma opção existente no Excel e não cria uma segunda operação. Os testes PostgreSQL passaram: 27, sem falhas ou ignorados (`c03-zero-operation-tests.log`).

`c03-complete-zero-fixed.json` comprova os percursos nas duas áreas e a paridade de todos os campos editáveis da RAW. `c03-complete-results-final.json` compara o DOM com todos os resultados calculados aplicáveis ao contrato de cada área. Factos de produção são de leitura e mostram «Condição inicial local»; nenhuma escrita é feita pelo ensaio de resultados. Os campos internos do motor que não pertencem ao contrato da área são identificados explicitamente, sem exigir campos de Perfis em Cantoneiras.

O auditor SQL independente (`c03-complete-persistence.json`) reconstrói quantidade, comprimento, peso e horas: Perfis usa geometria circular de diâmetro 20 mm e densidade 7850 kg/m³; Cantoneiras usa a propriedade exata de 3,77 kg/m. As taxas manuais são 10 e 20 un./h. As peças finais têm 15 unidades × 2500 mm e 8 × 1500 mm em cada área. Cada peça tem um registo em rascunho e uma operação. As cargas de Perfis são 1,5 e 0,8 h; as de Cantoneiras, 0,75 e 0,4 h. Nenhum evento OCR ou vínculo importado foi criado para estas OF.

A RAW atualizou as linhas sem F5 entre 19 e 1217 ms após a resposta de gravação. As próprias gravações demoraram entre 4932 e 6268 ms no ensaio final. Os resultados agregados também foram conferidos após convergência; esta prova não certifica toda a matriz de desempenho C05.

Os ensaios falhados estão preservados. `first` consultava o nome errado do atributo de estado; `persistence-trial` não canonicalizava o booleano de abocardar; `canonical-trial` não esperava o formulário da segunda peça; `sequence-trial` encontrou a ausência real da opção zero, corrigida na aplicação. O primeiro ensaio `results` exigia campos internos fora do contrato de Cantoneiras; a prova final limita-se aos campos aplicáveis, conforme C03.4.

`c03-complete-final-state.json` verifica 115 ficheiros da execução, as 27 alterações tracked preexistentes preservadas, os processos operacionais sem reinício e a ausência do worker isolado após o ensaio. População atual: 7417 Perfis e 75739 Cantoneiras; gerações 3769/3770. A comparação integral anterior C04 permanece vinculada às gerações 3559/3560 e às suas 83152 peças. As quatro peças novas são cobertas por C03; as provas integrais serão atualizadas na validação final.

C03.1–C03.5 aprovados neste ambiente. R01/R10 ainda dependem de C04/C05/C12. Não há aprovação da ingestão original Windows, das restantes 20 regras ou da entrega integral.

Correção do âmbito de isolamento, verificada na etapa C08: as bases e escritas de teste são isoladas, mas os ficheiros estáticos do diretório de trabalho são partilhados pelo Planeamento 18113 e 8113. A conferência de PID/comando apenas prova ausência de reinício; não prova que a interface servida em 8113 permaneceu inalterada. Ver `c08-real-zoom-final-state.json`. A publicação integral C12 continua pendente.
