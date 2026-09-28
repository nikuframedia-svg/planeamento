# Armazenamento de estimativas: aplicação e reversão

Âmbito: tabelas de projeção `planning_mtg`. As fontes CPIS, macros e OCR não são alteradas. A migração `sql/032_planning_estimate_storage.sql` foi aplicada apenas à cópia integral isolada e às bases descartáveis dos testes.

A migração acrescenta `detail_source_hash` e `detail_patch` a `raw_contents`, duas funções de leitura e as vistas `raw_resolved_contents` e `raw_capacity_contents`. As linhas antigas continuam legíveis. Cada nova estimativa aponta diretamente para o detalhe completo de origem, sem uma cadeia de referências. Os valores e o texto de pesquisa continuam armazenados na própria versão; os hashes e épocas de navegação mantêm-se imutáveis.

Na disponibilização C12, aplicar a migração antes de iniciar esta revisão do serviço de Planeamento e do worker. A disponibilização continua dependente da aprovação C11 e da cópia de segurança/revisão de código prevista no plano.

Para regressar a uma revisão anterior que lê diretamente `raw_contents.detail`:

1. Parar apenas o serviço de Planeamento e o seu worker. Conservar o backup e a revisão de código em execução.
2. Materializar o detalhe das versões compactas numa transação:

```sql
BEGIN;
UPDATE planning_mtg.raw_contents stored
SET detail=resolved.detail,
    detail_source_hash=NULL,
    detail_patch=NULL
FROM planning_mtg.raw_resolved_contents resolved
WHERE stored.hash=resolved.hash
  AND stored.detail_source_hash IS NOT NULL;

SELECT count(*) AS remaining_compact_versions
FROM planning_mtg.raw_contents
WHERE detail_source_hash IS NOT NULL;
-- O resultado tem de ser zero antes de confirmar a transação.
COMMIT;
```

3. Repor a revisão de código previamente guardada e iniciar o Planeamento e o worker. As colunas, funções e vistas aditivas podem permanecer instaladas.
4. Verificar RAW, histórico, capacidade e uma análise/exportação guardada. Não apagar `raw_contents` nem as versões de navegação para reverter esta alteração.

A reversão muda apenas a representação física. O teste `test_analysis_and_export_keep_frozen_estimates_with_shared_source_detail` compara todos os resultados de planeamento/capacidade e a evidência/exportação congelada antes e depois desta materialização.
