-- Optional comparison with the existing, versioned CPIS Mac import.
-- One output row per planning identity, even with several CPIS candidates.
CREATE OR REPLACE VIEW consulta_v2.planeamento_cpis_atual AS
 SELECT p.*,c.candidatos,c.identidades_cpis,
 CASE WHEN c.candidatos=0 THEN 'sem_correspondencia'
      WHEN c.candidatos=1 THEN 'candidata_por_confirmar'
      ELSE 'varias_candidatas' END AS associacao_cpis
 FROM consulta_v2.planeamento_atual p
 CROSS JOIN LATERAL (
   SELECT count(*) candidatos,
     coalesce(jsonb_agg(jsonb_build_object('versao',x.versao_id,'exp_id',x.exp_id,
       'comprimento_mm',x.comprimento_mm,'quantidade',x.quantidade_componente,
       'perfil',x.perfil_origem,'gama',x.gama_codigo)),'[]') identidades_cpis
   FROM producao_v2.componentes_cpis x
   WHERE x.simulada IS NOT TRUE
     AND x.ordem_codigo IN (p.valores->>'of',regexp_replace(p.valores->>'of','^OF',''))
     AND x.referencia=p.valores->>'component_ref'
 ) c;
COMMENT ON VIEW consulta_v2.planeamento_cpis_atual IS 'Coincidências são candidatas. As quantidades CPIS não são somadas às quantidades Excel/manuais, nem uma coincidência confirma uma identidade física.';
CREATE OR REPLACE VIEW consulta_v2.planeamento_duplicados_potenciais AS
 SELECT valores->>'of' ordem,valores->>'component_ref' referencia,
        valores->>'length_mm' comprimento,valores->>'profile' perfil,
        count(*) linhas,jsonb_agg(jsonb_build_object('area',area,'chave',chave,'necessidade',necessidade_id)) identidades
 FROM consulta_v2.planeamento_atual
 WHERE nullif(valores->>'of','') IS NOT NULL AND nullif(valores->>'component_ref','') IS NOT NULL
 GROUP BY valores->>'of',valores->>'component_ref',valores->>'length_mm',valores->>'profile'
 HAVING count(*)>1;
