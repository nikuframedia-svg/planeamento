# Planeamento simplificado — 21/09/2026

Publicado no serviço de ensaio `kanban-planning.service`, porta 8113, em
https://louise-pest-performed-atom.trycloudflare.com/planeamento.
O MES operacional não foi reiniciado. Não foram aplicadas migrações.

## Comportamento entregue

- Duas entradas: **Preencher manualmente** e **Carregar PDF**. A lista de OFs mantém-se como entrada inicial.
- O link existente `/planeamento/manual?of=OF266283&area=perfis&new=1` abre diretamente os campos.
- OF, OV e cliente resumidos; pesquisa em Alterar OF e detalhes oficiais em Ver dados da ordem.
- Uma página, dois grupos essenciais e Mais opções recolhido; ações no fim, sem barra a tapar campos.
- Referência pesquisável por OF, com perfil e comprimento nas candidatas; sem escolha arbitrária da primeira.
- Área sem predefinição quando não há uma decisão ou origem inequívoca; máquina por definir.
- Quantidade total e quantidade a preparar distintas, sem cópia ou desconto automático de produção.
- Perfil especial através de Outro perfil; dimensões condicionais; vírgula decimal normalizada no servidor.
- Histórico por campo e produção em diálogos que conservam o preenchimento. Erros abrem o grupo opcional afetado.
- PDF com uma única ação de edição, Abrir formulário. O desenho, carregamento, progresso e identificação documental permanecem no circuito existente.
- OF do PDF diferente da escolhida: confirmação antes de associar. Usar OF do PDF mantém a identificação documental; Voltar à OF selecionada abre o modo manual, sem atribuir indevidamente o PDF a essa ordem. Para corrigir a identificação documental, usar Resolver identificação no arquivo PDF.
- PDF já associado reabre os valores efetivos da ficha; ligar um PDF novo a uma peça existente preserva decisões humanas não alteradas explicitamente.
- Guardar apresenta confirmação, Adicionar outra peça desta OF e, quando existir, Abrir peça seguinte do PDF.
- Mudança com alterações pendentes oferece Guardar e continuar, Descartar alterações ou Continuar a editar.

## Contratos

Os identificadores dos campos e as regras de gravação permanecem os mesmos. O contrato de
catálogos acrescenta `help`, `group`, `required_on_ready` e `visibility`, com rótulos claros.
O servidor continua a validar opções, dimensões, revisões e quantidades.

`GET /planeamento/api/necessidades/por-origem?document=…&piece=…` devolve
`{"need_id": "UUID ou null"}` (o valor ausente é JSON null, não a string "null").
É uma consulta à ligação já existente; não cria fichas, não executa OCR e não altera o PDF.

O bloqueio CPIS mantém-se: guardar rascunhos e conferir quantidades é permitido; concluir
operacionalmente e exportar exige confirmação direta recente. A informação do OCR original
permanece separada, acessível em Consultas, e o seu conector não foi alterado nesta entrega.

## Verificação

**175 testes passaram** nas áreas afetadas (necessidades, browser, produção, fichas,
dossiês e escritor da macro). Depois do ajuste final de preservação dos valores humanos,
o percurso completo no browser foi repetido e passou.

- [Testes de regressão](planeamento-simples-2026-09-21/testes.txt).
- [Browser final em base descartável](planeamento-simples-2026-09-21/teste-browser-final.txt).
- [Verificação do link público, apenas leitura](planeamento-simples-2026-09-21/browser-publicado.json).
- [Formulário manual da OF266283](planeamento-simples-2026-09-21/publicado-of266283.png).
- [PDF real no mesmo formulário](planeamento-simples-2026-09-21/publicado-pdf.png).
- [Lista das peças do PDF](planeamento-simples-2026-09-21/publicado-pdf-lista.png).
- [Cantoneiras](planeamento-simples-2026-09-21/publicado-cantoneiras.png).
- [Ecrã de 390 px](planeamento-simples-2026-09-21/publicado-mobile.png).
- [Refluxo equivalente a 200% em computador](planeamento-simples-2026-09-21/publicado-200.png).

O teste a 200% usa largura CSS de 720 px, equivalente à redução de área útil de um
viewport de 1440 px. Foi verificada a ausência de transbordo horizontal. Os testes com
escritas usaram PostgreSQL descartável e um arquivo documental temporário. A verificação
pública não gravou fichas; as contagens operacionais finais eram zero fichas e zero novas
necessidades.

## Reversão

Cópia anterior às alterações:
`/home/luis/.local/state/planning-backups/ui-simple-20260921-102045`.

Para repor o aspeto anterior, restaurar a partir dessa cópia os templates `need_editor`,
`planning_hub` e `dossiers`, os JavaScript com os mesmos nomes e os CSS `need_editor` e
`planning_hub`, respeitando os caminhos relativos. Reiniciar apenas
`systemctl --user restart kanban-planning.service` e atualizar a página.

Os metadados adicionais e a consulta por origem são compatíveis e podem permanecer.
Não remover tabelas, decisões, PDFs ou revisões. Não restaurar globalmente o repositório;
se houver alterações posteriores nestes ficheiros, rever as diferenças antes de os repor.
