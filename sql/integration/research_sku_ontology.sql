-- Extend the existing research ontology; operational tables remain untouched.
-- Apply after research_live.sql, research_sku_families.sql and the base graph.
CREATE OR REPLACE FUNCTION consulta_v2.kg_familia_numero(t text)
 RETURNS numeric LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT CASE WHEN btrim(t) ~ '^[+]?[0-9]+([.,][0-9]+)?$'
             THEN replace(btrim(t),',','.')::numeric END
$$;

CREATE OR REPLACE VIEW consulta_v2.kg_familias_mapa AS
 SELECT m.*,CASE area WHEN 'cantoneiras' THEN 'MTG3' WHEN 'perfis' THEN 'MTG2' END setor,
  'kgf:sku:'||area||':'||sku sku_no,
  CASE WHEN familia IS NOT NULL THEN 'kgf:familia:'||area||':'||familia END familia_no
 FROM cadastro_v2.mapeamento_familias_sku m;

CREATE OR REPLACE VIEW consulta_v2.kg_familias_catalogo AS
 WITH contagens AS MATERIALIZED (
  SELECT area,familia,min(estado) estado,count(*) skus,min(versao_regras) versao_regras
  FROM consulta_v2.kg_familias_mapa WHERE familia IS NOT NULL GROUP BY area,familia
 )
 SELECT coalesce(f.area,c.area) area,coalesce(f.familia,c.familia) familia,
  CASE coalesce(f.area,c.area) WHEN 'cantoneiras' THEN 'MTG3' WHEN 'perfis' THEN 'MTG2' END setor_contexto,
  coalesce(f.estado,c.estado) estado_classificacao,coalesce(c.skus,0) skus_catalogados,
  coalesce(f.versao_regras,c.versao_regras) versao_regras,f.evidencia evidencia_classificacao,
  'kgf:familia:'||coalesce(f.area,c.area)||':'||coalesce(f.familia,c.familia) familia_no
 FROM cadastro_v2.familias_sku f FULL JOIN contagens c USING(area,familia);

CREATE OR REPLACE VIEW consulta_v2.kg_familias_fontes AS
 SELECT f.conjunto,f.versao,f.confirmada_em,v.metadata,v.linhas
 FROM origem_v2.aplicacao_fontes f JOIN origem_v2.aplicacao_versoes v ON v.id=f.versao
 WHERE f.conjunto IN ('application:sku_family_rules','application:sku_family_heads',
  'application:sku_family_mappings','excel:cantoneiras','mes:production_records','mes:validated_sheets',
  'application:records');

-- JSON-key selectivity in the version store has no column statistics. Keep
-- hash/merge joins local to this reader, avoiding an Excel scan per SKU.
CREATE OR REPLACE FUNCTION consulta_v2.kg_familias_observacoes()
 RETURNS TABLE(id text,area text,setor text,sku text,familia text,sku_no text,
  familia_no text,tipo text,ordem_original text,data_producao date,maquina_original text,
  versao_fonte text,versao_regras text,evidencia jsonb,ordem_codigo text,recurso_codigo text)
 LANGUAGE sql STABLE SET enable_nestloop='off' SET jit='off' AS $$
 WITH dados AS MATERIALIZED (
  SELECT conjunto,chave,dados,versao FROM consulta_v2.dados_aplicacao_atuais
  WHERE conjunto IN ('excel:cantoneiras','mes:production_records','mes:validated_sheets','application:records')
 ), mapa AS MATERIALIZED (SELECT * FROM consulta_v2.kg_familias_mapa),
 folhas AS MATERIALIZED (
  SELECT dados->>'sheet_uid' uid FROM dados
  WHERE conjunto='mes:validated_sheets' AND dados->>'source_app'='kanban-mes'
 ), mes AS MATERIALIZED (
  SELECT d.*,coalesce((dados->>'full_profile')::boolean,false) perfil_completo,
   CASE WHEN coalesce((dados->>'full_profile')::boolean,false)
    THEN dados->'extra'->'plan_identity'->>'component_ref' ELSE dados->>'model_ref' END sku,
   dados->'extra'->'plan_identity'->>'component_ref' referencia_associada
  FROM dados d JOIN folhas f ON f.uid=d.dados->>'sheet_uid'
  WHERE conjunto='mes:production_records'
   AND consulta_v2.kg_familia_numero(dados->>'quantity')>0
   AND (dados->>'sheet_date')::date<=CURRENT_DATE
 ), observacoes AS (
  SELECT 'kgf:evidencia:mes:'||(p.dados->>'id') id,m.area,m.setor,m.sku,m.familia,
   m.sku_no,m.familia_no,
   CASE WHEN p.perfil_completo THEN 'associacao_indireta_mes' ELSE 'registo_mes' END tipo,
   p.dados->>'production_order' ordem_original,(p.dados->>'sheet_date')::date data_producao,
   p.dados->>'machine' maquina_original,p.versao versao_fonte,m.versao_regras,
   jsonb_build_object('tipo_evidencia',CASE WHEN p.perfil_completo THEN 'documentary_association' ELSE 'validated_record' END,
    'estado_classificacao_sku',m.estado,
    'source_app','kanban-mes','record_id',p.dados->'id','sheet_uid',p.dados->'sheet_uid',
    'row_index',p.dados->'row_index','referencia_registada',p.dados->'model_ref',
    'referencia_associada',p.referencia_associada,'perfil_completo',p.perfil_completo,
    'quantidade_reportada',p.dados->'quantity','limite',
    CASE WHEN p.perfil_completo THEN 'Associacao indireta de perfil completo; nao confirma producao deste SKU ou de todos os membros da familia.'
     ELSE 'Registo positivo com referencia exata; operacao e reconciliacao com Excel nao confirmadas.' END) evidencia
  FROM mes p JOIN mapa m ON m.area='cantoneiras' AND m.sku=p.sku
  LEFT JOIN mapa frozen ON frozen.area=m.area AND frozen.sku=p.referencia_associada
  WHERE (p.perfil_completo OR frozen.sku IS NULL OR frozen.familia IS NOT DISTINCT FROM m.familia)
  UNION ALL
  SELECT 'kgf:evidencia:excel:'||(p.dados->>'source_line_id'),m.area,m.setor,m.sku,m.familia,
   m.sku_no,m.familia_no,
   CASE WHEN consulta_v2.kg_familia_numero(p.dados->>'quantity_made')>0
          OR consulta_v2.kg_familia_numero(p.dados->>'metres_produced')>0
        THEN 'acumulado_excel' ELSE 'planeamento_excel' END,
   p.dados->>'production_order_no',NULL::date,p.dados->>'cutting_machine',p.versao,m.versao_regras,
   jsonb_build_object('tipo_evidencia','documentary_counter','estado_classificacao_sku',m.estado,'snapshot_id',p.dados->'snapshot_id',
    'source_line_id',p.dados->'source_line_id','excel_row',p.dados->'excel_row',
    'pavilhao_original',p.dados->'pavilion','quantidade_planeada',p.dados->'quantity_planned',
    'quantidade_acumulada',p.dados->'quantity_made','metros_acumulados',p.dados->'metres_produced',
    'data_corte_prevista',p.dados->'cut_date',
    'limite','Contador ou atribuicao documental; nao confirma evento nem data real de producao. Nao somar com MES.')
  FROM dados p JOIN mapa m ON m.area='cantoneiras' AND m.sku=p.dados->>'component_ref'
  WHERE p.conjunto='excel:cantoneiras' AND upper(btrim(p.dados->>'pavilion'))='MTG3'
  UNION ALL
  SELECT 'kgf:evidencia:manual:'||(p.dados->>'id'),m.area,m.setor,m.sku,m.familia,
   m.sku_no,m.familia_no,'planeamento_manual',p.dados->>'production_order_no',NULL::date,
   p.dados->'values_json'->>'machine',p.versao,m.versao_regras,
   jsonb_build_object('tipo_evidencia','manual_planning','estado_classificacao_sku',m.estado,
    'record_id',p.dados->'id','revisao',p.dados->'revision','need_id',p.dados->'need_id',
    'operation_id',p.dados->'operation_id','estado_registo',p.dados->'record_status',
    'valores',p.dados->'values_json','valores_introduzidos',p.dados->'input_values',
    'source_plan_key',p.dados->'source_plan_key','avisos',p.dados->'registration_warnings',
    'limite','Preenchimento manual atual, incluindo rascunhos e edicoes RAW. Nao comprova producao nem se soma a Excel ou MES.')
  FROM dados p JOIN mapa m ON m.area=p.dados->>'area' AND m.sku=p.dados->>'component_ref'
  WHERE p.conjunto='application:records' AND m.area='cantoneiras'
 ), aliases AS (
  SELECT upper(btrim(nome_origem)) alias,min(recurso_codigo) recurso_codigo
  FROM cadastro_v2.alias_recursos GROUP BY 1 HAVING count(DISTINCT recurso_codigo)=1
 )
 SELECT o.*,CASE WHEN nullif(regexp_replace(upper(btrim(ordem_original)),'^OF[ ._-]*',''),'') IS NOT NULL THEN
  'OF'||regexp_replace(upper(btrim(ordem_original)),'^OF[ ._-]*','') END ordem_codigo,
  a.recurso_codigo
 FROM observacoes o LEFT JOIN aliases a ON a.alias=upper(btrim(o.maquina_original))
$$;

CREATE OR REPLACE VIEW consulta_v2.kg_familias_evidencias AS
 SELECT * FROM consulta_v2.kg_familias_observacoes();

CREATE OR REPLACE VIEW consulta_v2.kg_familias_resumo AS
 WITH evidencia AS MATERIALIZED (SELECT * FROM consulta_v2.kg_familias_evidencias),
 resumo AS (
  SELECT area,familia,count(*) FILTER(WHERE tipo='registo_mes') registos_mes,
   count(DISTINCT sku) FILTER(WHERE tipo='registo_mes') skus_com_mes,
   min(data_producao) FILTER(WHERE tipo='registo_mes') primeira_data_mes,
   max(data_producao) FILTER(WHERE tipo='registo_mes') ultima_data_mes,
   count(DISTINCT sku) FILTER(WHERE tipo='acumulado_excel') skus_com_acumulado_excel,
   count(DISTINCT sku) FILTER(WHERE tipo IN ('acumulado_excel','planeamento_excel')) skus_planeados_mtg3,
   count(*) FILTER(WHERE tipo='associacao_indireta_mes') associacoes_indiretas_mes,
   max(data_producao) FILTER(WHERE tipo='associacao_indireta_mes') ultima_data_indireta_mes,
   count(*) FILTER(WHERE tipo='planeamento_manual') registos_manuais,
   count(DISTINCT sku) FILTER(WHERE tipo='planeamento_manual') skus_planeados_manualmente
  FROM evidencia GROUP BY area,familia
 )
 SELECT c.*,coalesce(r.registos_mes,0) registos_mes,coalesce(r.skus_com_mes,0) skus_com_mes,
  r.primeira_data_mes,r.ultima_data_mes,coalesce(r.skus_com_acumulado_excel,0) skus_com_acumulado_excel,
  coalesce(r.skus_planeados_mtg3,0) skus_planeados_mtg3,
  coalesce(r.associacoes_indiretas_mes,0) associacoes_indiretas_mes,r.ultima_data_indireta_mes,
  CASE WHEN r.registos_mes>0 THEN 'producao_mes_registada'
   WHEN r.skus_com_acumulado_excel>0 THEN 'acumulado_documental_excel'
   WHEN r.associacoes_indiretas_mes>0 THEN 'associacao_indireta_por_confirmar'
   WHEN r.skus_planeados_mtg3>0 OR r.registos_manuais>0 THEN 'apenas_planeamento'
   ELSE 'sem_evidencia_mtg3_nestas_fontes' END estado_evidencia_producao,
  coalesce(r.registos_manuais,0) registos_manuais,
  coalesce(r.skus_planeados_manualmente,0) skus_planeados_manualmente
 FROM consulta_v2.kg_familias_catalogo c LEFT JOIN resumo r USING(area,familia);

-- New orders observed after the archived base load still have a graph node.
-- Its identity matches the base graph, which takes over if that order is loaded.
CREATE OR REPLACE VIEW consulta_v2.kg_familias_ordens AS
 WITH e AS MATERIALIZED (SELECT * FROM consulta_v2.kg_familias_evidencias)
 SELECT e.ordem_codigo codigo,array_agg(DISTINCT e.ordem_original) referencias_originais,
  array_agg(DISTINCT e.versao_fonte) versoes_fonte,
  CASE WHEN e.ordem_codigo ~ '^OF[0-9]+$' THEN 'observada_nas_fontes_atuais'
   ELSE 'referencia_de_of_por_confirmar' END estado,
  CASE WHEN e.ordem_codigo ~ '^OF[0-9]+$' THEN 'of:' ELSE 'kgf:referencia_of:' END||e.ordem_codigo no_id,
  CASE WHEN e.ordem_codigo ~ '^OF[0-9]+$' THEN 'of' ELSE 'referencia_of_por_confirmar' END tipo_no
 FROM e WHERE e.ordem_codigo IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM producao_v2.ordens o WHERE o.codigo=e.ordem_codigo)
 GROUP BY e.ordem_codigo;

CREATE OR REPLACE VIEW consulta_v2.kg_familias_nos AS
 SELECT familia_no id,'familia_sku'::text tipo,familia rotulo,to_jsonb(c) atributos
 FROM consulta_v2.kg_familias_catalogo c
 UNION ALL SELECT sku_no,'sku_catalogado',sku,to_jsonb(m) FROM consulta_v2.kg_familias_mapa m
 UNION ALL SELECT 'kgf:setor:'||codigo,'setor',designacao,to_jsonb(s) FROM cadastro_v2.setores s
 UNION ALL SELECT 'kgf:fonte:'||versao,'publicacao_aplicacao',conjunto,to_jsonb(f)
  FROM consulta_v2.kg_familias_fontes f
 UNION ALL SELECT e.id,'evidencia_familia',e.tipo||' / '||e.sku,to_jsonb(e)
  FROM consulta_v2.kg_familias_evidencias e
 UNION ALL SELECT no_id,tipo_no,codigo,to_jsonb(o) FROM consulta_v2.kg_familias_ordens o;

CREATE OR REPLACE VIEW consulta_v2.kg_familias_relacoes AS
 WITH mapa AS MATERIALIZED (SELECT * FROM consulta_v2.kg_familias_mapa),
 evidencia AS MATERIALIZED (SELECT * FROM consulta_v2.kg_familias_evidencias)
 SELECT 'kgf:membro:'||m.area||':'||m.sku id,m.sku_no origem,m.familia_no destino,
  'familia_classifica_sku'::text relacao,m.estado estado,
  jsonb_build_object('tipo_evidencia',CASE WHEN m.estado='confirmada_pelo_utilizador' THEN 'human_judgement' ELSE 'pattern_inference' END,
   'regra',m.regra,'versao_regras',m.versao_regras,'revisao',m.revisao,'evidencia_original',m.evidencia,
   'limite','Classificacao nao estabelece intercambiabilidade, identidade fisica, rota ou compatibilidade de maquina.') evidencia
 FROM mapa m WHERE m.familia IS NOT NULL
 UNION ALL SELECT 'kgf:artigo:'||a.id,'artigo:'||a.id,m.sku_no,'familia_referencia_artigo',
  'correspondencia_documental',jsonb_build_object('tipo_evidencia','exact_reference_match','setor',a.setor,'referencia',a.referencia)
  FROM cadastro_v2.artigos a JOIN mapa m ON m.setor=a.setor AND m.sku=a.referencia
 UNION ALL SELECT 'kgf:fonte_mapa:'||m.area||':'||m.sku,m.sku_no,'kgf:fonte:'||m.versao_sincronizacao,
  'familia_mapeamento_extraido_de','documental',jsonb_build_object('tipo_evidencia','structural_catalog','versao_regras',m.versao_regras)
  FROM mapa m
 UNION ALL SELECT 'kgf:contexto:'||f.area||':'||f.familia,f.familia_no,'kgf:setor:'||f.setor_contexto,
  'familia_catalogada_no_contexto','contexto_catalogo',
  jsonb_build_object('tipo_evidencia','structural_catalog','limite','Area do catalogo; nao afirma producao ou exclusividade neste setor.')
  FROM consulta_v2.kg_familias_catalogo f
 UNION ALL SELECT 'kgf:familia_evidencia:'||e.id,e.familia_no,e.id,
  'familia_tem_evidencia_'||e.tipo,e.tipo,e.evidencia||jsonb_build_object('versao_fonte',e.versao_fonte,'of',e.ordem_codigo)
  FROM evidencia e WHERE e.familia_no IS NOT NULL
 UNION ALL SELECT 'kgf:evidencia_sku:'||e.id,e.id,e.sku_no,'familia_evidencia_refere_sku',e.tipo,e.evidencia FROM evidencia e
 UNION ALL SELECT 'kgf:evidencia_setor:'||e.id,e.id,'kgf:setor:'||e.setor,
  'familia_evidencia_no_setor',e.tipo,e.evidencia FROM evidencia e
 UNION ALL SELECT 'kgf:evidencia_fonte:'||e.id,e.id,'kgf:fonte:'||e.versao_fonte,
  'familia_evidencia_extraida_de',e.tipo,e.evidencia FROM evidencia e
 UNION ALL SELECT 'kgf:evidencia_of:'||e.id,e.id,
  CASE WHEN o.codigo IS NOT NULL OR e.ordem_codigo ~ '^OF[0-9]+$'
   THEN 'of:' ELSE 'kgf:referencia_of:' END||e.ordem_codigo,
  CASE WHEN o.codigo IS NOT NULL OR e.ordem_codigo ~ '^OF[0-9]+$'
   THEN 'familia_evidencia_refere_of' ELSE 'familia_evidencia_refere_of_por_confirmar' END,e.tipo,
  e.evidencia||jsonb_build_object('of_original',e.ordem_original) FROM evidencia e
  LEFT JOIN producao_v2.ordens o ON o.codigo=e.ordem_codigo
  WHERE e.ordem_codigo IS NOT NULL
 UNION ALL SELECT 'kgf:evidencia_recurso:'||e.id,e.id,'recurso:'||r.codigo,
  CASE WHEN e.tipo IN ('registo_mes','associacao_indireta_mes')
   THEN 'familia_maquina_registada_mes' WHEN e.tipo='planeamento_manual'
   THEN 'familia_maquina_indicada_manualmente' ELSE 'familia_maquina_indicada_excel' END,e.tipo,
  e.evidencia||jsonb_build_object('maquina_original',e.maquina_original,'limite_recurso','Nao prova elegibilidade tecnica de outros SKUs da familia.')
  FROM evidencia e JOIN cadastro_v2.recursos r ON r.codigo=e.recurso_codigo;

-- Account for every source row, including unusable references and evidence
-- excluded from production claims. Absence from a family is never silent.
CREATE OR REPLACE VIEW consulta_v2.kg_familias_cobertura AS
 WITH dados AS MATERIALIZED (
  SELECT conjunto,dados,versao FROM consulta_v2.dados_aplicacao_atuais
  WHERE conjunto IN ('excel:cantoneiras','mes:production_records','mes:validated_sheets','application:records')
 ), fontes AS MATERIALIZED (
  SELECT 'kgf:evidencia:excel:'||(dados->>'source_line_id') id,conjunto,versao,
   dados->>'component_ref' sku,dados
  FROM dados WHERE conjunto='excel:cantoneiras'
  UNION ALL SELECT 'kgf:evidencia:mes:'||(p.dados->>'id'),p.conjunto,p.versao,
   CASE WHEN coalesce((p.dados->>'full_profile')::boolean,false)
    THEN p.dados->'extra'->'plan_identity'->>'component_ref' ELSE p.dados->>'model_ref' END,p.dados
  FROM dados p JOIN dados s ON s.conjunto='mes:validated_sheets'
   AND s.dados->>'source_app'='kanban-mes' AND s.dados->>'sheet_uid'=p.dados->>'sheet_uid'
  WHERE p.conjunto='mes:production_records'
  UNION ALL SELECT 'kgf:evidencia:manual:'||(dados->>'id'),conjunto,versao,dados->>'component_ref',dados
  FROM dados WHERE conjunto='application:records' AND dados->>'area'='cantoneiras'
 ), mapa AS MATERIALIZED (SELECT * FROM consulta_v2.kg_familias_mapa WHERE area='cantoneiras'),
 evidencia AS MATERIALIZED (SELECT * FROM consulta_v2.kg_familias_evidencias)
 SELECT p.id,p.conjunto,p.versao,p.sku,m.familia,m.estado estado_classificacao,
  e.tipo tipo_evidencia,
  CASE WHEN p.conjunto='excel:cantoneiras' AND upper(btrim(p.dados->>'pavilion')) IS DISTINCT FROM 'MTG3'
        THEN 'pavilhao_nao_mtg3'
   WHEN nullif(btrim(p.sku),'') IS NULL THEN 'sem_referencia'
   WHEN m.sku IS NULL THEN 'referencia_por_catalogar'
   WHEN p.conjunto='mes:production_records' AND coalesce(consulta_v2.kg_familia_numero(p.dados->>'quantity'),0)<=0
        THEN 'quantidade_nao_positiva'
   WHEN p.conjunto='mes:production_records' AND p.dados->>'sheet_date' IS NULL THEN 'sem_data'
   WHEN p.conjunto='mes:production_records' AND (p.dados->>'sheet_date')::date>CURRENT_DATE THEN 'data_futura'
   WHEN e.id IS NOT NULL AND m.familia IS NULL THEN 'integrada_sem_familia'
   WHEN e.id IS NOT NULL THEN 'integrada'
   WHEN p.conjunto='mes:production_records' AND frozen.sku IS NOT NULL
        AND frozen.familia IS DISTINCT FROM m.familia THEN 'conflito_referencia_associada'
   ELSE 'por_investigar' END estado_cobertura
 FROM fontes p LEFT JOIN mapa m ON m.sku=p.sku LEFT JOIN evidencia e ON e.id=p.id
 LEFT JOIN mapa frozen ON frozen.sku=p.dados->'extra'->'plan_identity'->>'component_ref';

-- Preserve the original graph definitions and their OIDs/dependent queries.
-- Reapplying this extension never appends its nodes or edges a second time.
DO $$
DECLARE pair text[]; definition text;
BEGIN
 FOREACH pair SLICE 1 IN ARRAY ARRAY[['kg_nos','kg_familias_nos'],['kg_relacoes','kg_familias_relacoes']] LOOP
  definition := pg_get_viewdef(format('consulta_v2.%I',pair[1])::regclass,true);
  IF position(pair[2] IN definition)=0 THEN
   EXECUTE format('CREATE OR REPLACE VIEW consulta_v2.%I AS %s UNION ALL SELECT * FROM consulta_v2.%I',
    pair[1],regexp_replace(definition,';[[:space:]]*$',''),pair[2]);
  END IF;
 END LOOP;
END $$;

CREATE OR REPLACE VIEW consulta_v2.kg_evidencias AS
 SELECT 'evidencia:'||id AS id,id AS relacao_id,
  CASE WHEN relacao LIKE 'familia_%' THEN coalesce(evidencia->>'tipo_evidencia','structural_catalog')
   WHEN relacao='tem_capacidade_declarada' THEN 'human_judgement'
   WHEN relacao IN ('tem_pendencia','avaliada_por') THEN 'data_quality_test'
   WHEN relacao LIKE 'corresponde_%' THEN 'inclusion_dependency_test'
   ELSE 'structural_catalog' END AS tipo_evidencia,
  estado,relacao AS metodo,evidencia AS fonte,
  CASE WHEN evidencia ? 'of' THEN 'OF:'||(evidencia->>'of') END AS grupo_independencia,
  'not_applicable'::text AS incerteza_estatistica,NULL::numeric AS probabilidade_de_compatibilidade,
  coalesce(evidencia->>'limite','A relacao conserva a fonte; nao mede probabilidade de execucao. Historico conta OF distintas e separa Excel de MES.') AS limite
 FROM consulta_v2.kg_relacoes;

COMMENT ON VIEW consulta_v2.kg_familias_resumo IS
 'Catalogo atual; classificacao e prova de producao sao eixos independentes. Nao soma quantidades de fontes, operacoes ou versoes. Data Corte nao e data real de producao.';
COMMENT ON VIEW consulta_v2.kg_familias_evidencias IS
 'Um identificador por observacao de origem. Perfil completo apenas sustenta associacao indireta. Novos registos chegam pela publicacao atomica existente da aplicacao.';
