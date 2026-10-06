-- Durable maps arrive with the application's atomic publication.
-- One (area,sku) identity in the application implies one row here.
CREATE SCHEMA IF NOT EXISTS cadastro_v2;
CREATE OR REPLACE VIEW cadastro_v2.mapeamento_familias_sku AS
 SELECT dados->>'area' area,dados->>'sku' sku,dados->>'family' familia,
        dados->>'status' estado,dados->>'rule' regra,dados->>'rules_id' versao_regras,
        (dados->>'revision')::integer revisao,dados->'evidence' evidencia,
        dados->>'updated_at' atualizado_em,versao versao_sincronizacao,confirmada_em
 FROM consulta_v2.dados_aplicacao_atuais WHERE conjunto='application:sku_family_mappings';
CREATE OR REPLACE VIEW cadastro_v2.familias_sku AS
 SELECT d.dados->>'area' area,f.key familia,f.value->>'estado' estado,
        f.value evidencia,d.dados->>'id' versao_regras
 FROM consulta_v2.dados_aplicacao_atuais d
 JOIN consulta_v2.dados_aplicacao_atuais h ON h.conjunto='application:sku_family_heads'
   AND h.dados->>'rules_id'=d.dados->>'id'
 CROSS JOIN LATERAL jsonb_each(d.dados->'config'->'families') f
 WHERE d.conjunto='application:sku_family_rules';
CREATE OR REPLACE VIEW consulta_v2.planeamento_com_familias_sku AS
 -- Expand each versioned dataset once before joining JSON keys. Without this
 -- boundary, a family filter can make PostgreSQL scan planning per SKU.
 WITH p AS MATERIALIZED (SELECT * FROM consulta_v2.planeamento_atual),
 m AS MATERIALIZED (
   SELECT area,sku,familia,estado,regra,versao_regras FROM cadastro_v2.mapeamento_familias_sku
 )
 SELECT p.*,m.familia familia_sku,m.estado familia_sku_estado,m.regra familia_sku_regra,
        m.versao_regras familia_sku_versao
 FROM p LEFT JOIN m ON m.area=p.area AND m.sku=p.valores->>'component_ref';
CREATE OR REPLACE VIEW consulta_v2.resumo_familias_sku AS
 SELECT area,familia_sku,familia_sku_estado,
        count(DISTINCT valores->>'component_ref') skus_distintos,
        count(DISTINCT valores->>'of') ofs,count(*) linhas_planeamento
 FROM consulta_v2.planeamento_com_familias_sku
 GROUP BY area,familia_sku,familia_sku_estado;
COMMENT ON VIEW cadastro_v2.mapeamento_familias_sku IS 'Original SKU is preserved. Classification includes evidence and pending states; does not establish physical-work identity.';
COMMENT ON VIEW consulta_v2.resumo_familias_sku IS 'Distinct SKUs across the full current planning snapshot, including historical/closed orders. Does not sum production quantities.';
