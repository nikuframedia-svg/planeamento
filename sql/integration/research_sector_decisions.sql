-- Decisões de planeamento na base de pesquisa e na ontologia (plano de 01/10/2026, secção 12).
-- Lê só as versões atuais publicadas atomicamente pela aplicação (origem_v2 / dados_aplicacao_atuais).
-- Aplicar depois de research_live.sql, research_sku_families.sql e research_sku_ontology.sql.
-- Reaplicar não duplica nós nem relações. Planeada na máquina X nunca passa a «produzida na máquina X».

CREATE OR REPLACE VIEW consulta_v2.selecao_planear_atual AS
 SELECT dados->>'area' area,dados->>'production_order_no' of,dados->>'reference' referencia,
  dados->>'decision' decisao,dados->>'reason' motivo,dados->>'actor' autor,
  (dados->>'decided_at')::timestamptz decidida_em,(dados->>'revision')::integer revisao,versao versao_sincronizacao
 FROM consulta_v2.dados_aplicacao_atuais WHERE conjunto='application:sector_selection';

CREATE OR REPLACE VIEW consulta_v2.politicas_prioridade_atuais AS
 SELECT dados->>'area' area,dados->'definition' definicao,(dados->>'revision')::integer revisao,
  dados->>'reason' motivo,dados->>'actor' autor,(dados->>'updated_at')::timestamptz atualizada_em,versao versao_sincronizacao
 FROM consulta_v2.dados_aplicacao_atuais WHERE conjunto='application:sector_priority_policies';

CREATE OR REPLACE VIEW consulta_v2.substituicoes_prazo_atuais AS
 SELECT dados->>'area' area,dados->>'production_order_no' of,dados->>'reference' referencia,
  dados->>'id' id,dados->'definition' definicao,dados->>'reason' motivo,dados->>'actor' autor,
  (dados->>'revision')::integer revisao,(dados->>'updated_at')::timestamptz atualizada_em,versao versao_sincronizacao
 FROM consulta_v2.dados_aplicacao_atuais WHERE conjunto='application:sector_priority_overrides';

CREATE OR REPLACE VIEW consulta_v2.conjuntos_referencias_atuais AS
 SELECT s.dados->>'id' id,s.dados->>'area' area,s.dados->>'name' nome,s.dados->>'mode' modo,
  s.dados->'selector' seletor,(s.dados->>'revision')::integer revisao,(s.dados->>'archived')::boolean arquivado,
  m.dados->>'sku_literal' referencia,s.versao versao_sincronizacao
 FROM consulta_v2.dados_aplicacao_atuais s
 LEFT JOIN consulta_v2.dados_aplicacao_atuais m ON m.conjunto='application:sector_reference_set_members'
  AND m.dados->>'set_id'=s.dados->>'id' AND m.dados->>'revision'=s.dados->>'revision'
 WHERE s.conjunto='application:sector_reference_sets';

CREATE OR REPLACE VIEW consulta_v2.decisoes_maquina_atuais AS
 SELECT d.dados->>'area' area,d.dados->>'occurrence_key' ocorrencia,d.dados->>'production_order_no' of,
  d.dados->>'reference' referencia,d.dados->>'operation_code' operacao,(d.dados->>'occurrence')::integer ocorrencia_rota,
  d.dados->>'technical_signature' assinatura_tecnica,d.dados->>'mode' modo,d.dados->>'resource_id' recurso_id,
  r.dados->'definition'->>'research_code' recurso_codigo,r.dados->>'name' recurso_nome,
  d.dados->>'reason' motivo,(d.dados->>'scope_level')::integer especificidade,d.dados->>'action_id' acao_id,
  (d.dados->>'revision')::integer revisao,d.dados->>'actor' autor,(d.dados->>'decided_at')::timestamptz decidida_em,
  d.versao versao_sincronizacao
 FROM consulta_v2.dados_aplicacao_atuais d
 LEFT JOIN consulta_v2.dados_aplicacao_atuais r ON r.conjunto='application:planning_configuration'
  AND r.chave='object:'||(d.dados->>'resource_id')
 WHERE d.conjunto='application:sector_machine_decisions';

CREATE OR REPLACE VIEW consulta_v2.preferencias_maquina_atuais AS
 SELECT p.dados->>'id' id,p.dados->>'area' area,p.dados->'selector' seletor,(p.dados->>'specificity')::integer especificidade,
  p.dados->>'resource_id' recurso_id,r.dados->'definition'->>'research_code' recurso_codigo,
  (p.dados->>'valid_from')::date valida_desde,(p.dados->>'valid_until')::date valida_ate,
  p.dados->>'reason' motivo,(p.dados->>'archived')::boolean arquivada,p.versao versao_sincronizacao
 FROM consulta_v2.dados_aplicacao_atuais p
 LEFT JOIN consulta_v2.dados_aplicacao_atuais r ON r.conjunto='application:planning_configuration'
  AND r.chave='object:'||(p.dados->>'resource_id')
 WHERE p.conjunto='application:sector_machine_preferences';

CREATE OR REPLACE VIEW consulta_v2.quotas_capacidade_atuais AS
 SELECT q.dados->>'resource_id' recurso_id,r.dados->'definition'->>'research_code' recurso_codigo,q.dados->>'area' area,
  (q.dados->>'share')::numeric quota,(q.dados->>'valid_from')::date valida_desde,(q.dados->>'valid_until')::date valida_ate,
  q.dados->>'reason' motivo,(q.dados->>'revision')::integer revisao,q.versao versao_sincronizacao
 FROM consulta_v2.dados_aplicacao_atuais q
 LEFT JOIN consulta_v2.dados_aplicacao_atuais r ON r.conjunto='application:planning_configuration'
  AND r.chave='object:'||(q.dados->>'resource_id')
 WHERE q.conjunto='application:sector_capacity_quotas';

CREATE OR REPLACE VIEW consulta_v2.planos_aceites_segmentos AS
 SELECT a.dados->>'scenario_id' cenario_id,a.dados->>'job_id' calculo_id,a.dados->>'operation_key' ocorrencia_gantt,
  a.dados->>'area' area,a.dados->>'of' of,a.dados->>'reference' referencia,a.dados->>'operation' operacao,
  (a.dados->>'occurrence')::integer ocorrencia_rota,a.dados->>'resource_id' recurso_id,
  r.dados->'definition'->>'research_code' recurso_codigo,
  (a.dados->>'started_at')::timestamptz + make_interval(mins => (a.dados->>'start_minute')::integer) inicio_planeado,
  (a.dados->>'started_at')::timestamptz + make_interval(mins => (a.dados->>'end_minute')::integer) fim_planeado,
  a.dados->'segments' segmentos_minutos,(a.dados->>'provisional')::boolean provisorio,a.dados->'priority' prioridade,
  a.versao versao_sincronizacao
 FROM consulta_v2.dados_aplicacao_atuais a
 LEFT JOIN consulta_v2.dados_aplicacao_atuais r ON r.conjunto='application:planning_configuration'
  AND r.chave='object:'||(a.dados->>'resource_id')
 WHERE a.conjunto='application:accepted_plans' AND a.dados->>'kind'='segment';

-- Graph extension: nodes and relations for policies, sets, decisions, quotas and allocations.
CREATE OR REPLACE VIEW consulta_v2.kg_decisoes_nos AS
 SELECT 'kgd:politica:'||area id,'politica_prioridade'::text tipo,area||' r'||revisao rotulo,to_jsonb(p) atributos
  FROM consulta_v2.politicas_prioridade_atuais p
 UNION ALL SELECT 'kgd:substituicao:'||area||':'||of||':'||referencia,'substituicao_prazo',of||' / '||referencia,to_jsonb(s)
  FROM consulta_v2.substituicoes_prazo_atuais s
 UNION ALL SELECT DISTINCT ON (id) 'kgd:conjunto:'||id,'conjunto_referencias',nome,
  to_jsonb(c) - 'referencia' FROM consulta_v2.conjuntos_referencias_atuais c WHERE NOT arquivado
 UNION ALL SELECT 'kgd:decisao_maquina:'||area||':'||ocorrencia,'decisao_maquina',ocorrencia,to_jsonb(d)
  FROM consulta_v2.decisoes_maquina_atuais d
 UNION ALL SELECT 'kgd:preferencia:'||id,'preferencia_maquina',seletor->>'kind'||' '||(seletor->>'value'),to_jsonb(p)
  FROM consulta_v2.preferencias_maquina_atuais p WHERE NOT arquivada
 UNION ALL SELECT 'kgd:quota:'||recurso_id||':'||area||':'||valida_desde,'quota_capacidade',coalesce(recurso_codigo,recurso_id)||' '||area,to_jsonb(q)
  FROM consulta_v2.quotas_capacidade_atuais q
 UNION ALL SELECT DISTINCT ON (cenario_id) 'kgd:plano:'||cenario_id,'plano_aceite',cenario_id,
  jsonb_build_object('cenario_id',cenario_id,'calculo_id',calculo_id,'limite','Compromisso planeado; não é produção observada.')
  FROM consulta_v2.planos_aceites_segmentos
 UNION ALL SELECT 'kgd:alocacao:'||cenario_id||':'||ocorrencia_gantt,'alocacao_planeada',of||' / '||operacao,to_jsonb(a)
  FROM consulta_v2.planos_aceites_segmentos a;

CREATE OR REPLACE VIEW consulta_v2.kg_decisoes_relacoes AS
 WITH setores AS (SELECT * FROM (VALUES ('perfis','MTG2'),('cantoneiras','MTG3')) v(area,setor))
 SELECT 'kgd:politica_setor:'||p.area id,'kgd:politica:'||p.area origem,'kgf:setor:'||s.setor destino,
  'politica_prioridade_do_setor'::text relacao,'decisao_utilizador'::text estado,
  jsonb_build_object('tipo_evidencia','human_judgement','definicao',p.definicao,'revisao',p.revisao) evidencia
  FROM consulta_v2.politicas_prioridade_atuais p JOIN setores s USING(area)
 UNION ALL SELECT 'kgd:substituicao_of:'||x.area||':'||x.of||':'||x.referencia,'kgd:substituicao:'||x.area||':'||x.of||':'||x.referencia,
  'of:'||x.of,'prazo_substituido_na_of','decisao_utilizador',
  jsonb_build_object('tipo_evidencia','human_judgement','of',x.of,'motivo',x.motivo,'definicao',x.definicao,
   'limite','Vale só neste setor; a mesma OF noutro setor não herda o prazo.')
  FROM consulta_v2.substituicoes_prazo_atuais x
 UNION ALL SELECT 'kgd:membro_conjunto:'||c.id||':'||c.referencia,'kgd:conjunto:'||c.id,'kgf:sku:'||c.area||':'||c.referencia,
  'conjunto_contem_referencia','decisao_utilizador',
  jsonb_build_object('tipo_evidencia','human_judgement','modo',c.modo,'revisao',c.revisao,
   'limite','Pertença é metadado; a referência literal não é fundida com grafias parecidas.')
  FROM consulta_v2.conjuntos_referencias_atuais c WHERE NOT c.arquivado AND c.referencia IS NOT NULL
 UNION ALL SELECT 'kgd:decisao_recurso:'||d.area||':'||d.ocorrencia,'kgd:decisao_maquina:'||d.area||':'||d.ocorrencia,
  coalesce('recurso:'||d.recurso_codigo,'kgd:recurso_aplicacao:'||d.recurso_id),
  CASE d.modo WHEN 'assign' THEN 'decisao_atribui_maquina' ELSE 'decisao_prefere_maquina' END,'decisao_utilizador',
  jsonb_build_object('tipo_evidencia','human_judgement','of',d.of,'motivo',d.motivo,'especificidade',d.especificidade,
   'limite','Escolha de planeamento; não certifica compatibilidade técnica nem produção nessa máquina.')
  FROM consulta_v2.decisoes_maquina_atuais d
 UNION ALL SELECT 'kgd:decisao_of:'||d.area||':'||d.ocorrencia,'kgd:decisao_maquina:'||d.area||':'||d.ocorrencia,'of:'||d.of,
  'decisao_maquina_na_of','decisao_utilizador',jsonb_build_object('tipo_evidencia','human_judgement','of',d.of)
  FROM consulta_v2.decisoes_maquina_atuais d
 UNION ALL SELECT 'kgd:decisao_sku:'||d.area||':'||d.ocorrencia,'kgd:decisao_maquina:'||d.area||':'||d.ocorrencia,
  'kgf:sku:'||d.area||':'||d.referencia,'decisao_maquina_refere_sku','decisao_utilizador',
  jsonb_build_object('tipo_evidencia','human_judgement','operacao',d.operacao,'ocorrencia_rota',d.ocorrencia_rota)
  FROM consulta_v2.decisoes_maquina_atuais d
 UNION ALL SELECT 'kgd:preferencia_alvo:'||p.id,'kgd:preferencia:'||p.id,
  CASE p.seletor->>'kind' WHEN 'sku_family' THEN 'kgf:familia:'||p.area||':'||(p.seletor->>'value')
   WHEN 'reference' THEN 'kgf:sku:'||p.area||':'||(p.seletor->>'value')
   WHEN 'set' THEN 'kgd:conjunto:'||(p.seletor->>'value')
   ELSE 'kgd:grupo_perfis:'||p.area||':'||(p.seletor->>'value') END,
  'preferencia_aplica_a','decisao_utilizador',
  jsonb_build_object('tipo_evidencia','human_judgement','operacao',p.seletor->>'operation','valida_desde',p.valida_desde,'valida_ate',p.valida_ate)
  FROM consulta_v2.preferencias_maquina_atuais p WHERE NOT p.arquivada
 UNION ALL SELECT 'kgd:preferencia_recurso:'||p.id,'kgd:preferencia:'||p.id,coalesce('recurso:'||p.recurso_codigo,'kgd:recurso_aplicacao:'||p.recurso_id),
  'preferencia_para_recurso','decisao_utilizador',
  jsonb_build_object('tipo_evidencia','human_judgement','limite','Preferência admite outra alternativa explicada.')
  FROM consulta_v2.preferencias_maquina_atuais p WHERE NOT p.arquivada
 UNION ALL SELECT 'kgd:quota_recurso:'||q.recurso_id||':'||q.area||':'||q.valida_desde,'kgd:quota:'||q.recurso_id||':'||q.area||':'||q.valida_desde,
  coalesce('recurso:'||q.recurso_codigo,'kgd:recurso_aplicacao:'||q.recurso_id),'quota_de_recurso_partilhado','decisao_utilizador',
  jsonb_build_object('tipo_evidencia','human_judgement','quota',q.quota,'area',q.area)
  FROM consulta_v2.quotas_capacidade_atuais q
 UNION ALL SELECT 'kgd:alocacao_plano:'||a.cenario_id||':'||a.ocorrencia_gantt,'kgd:alocacao:'||a.cenario_id||':'||a.ocorrencia_gantt,
  'kgd:plano:'||a.cenario_id,'alocacao_do_plano','planeado',jsonb_build_object('tipo_evidencia','structural_catalog')
  FROM consulta_v2.planos_aceites_segmentos a
 UNION ALL SELECT 'kgd:alocacao_recurso:'||a.cenario_id||':'||a.ocorrencia_gantt,'kgd:alocacao:'||a.cenario_id||':'||a.ocorrencia_gantt,
  coalesce('recurso:'||a.recurso_codigo,'kgd:recurso_aplicacao:'||a.recurso_id),'alocacao_planeada_no_recurso','planeado',
  jsonb_build_object('tipo_evidencia','structural_catalog','inicio',a.inicio_planeado,'fim',a.fim_planeado,'of',a.of,
   'limite','Planeada nesta máquina; não é produção observada.')
  FROM consulta_v2.planos_aceites_segmentos a
 UNION ALL SELECT 'kgd:alocacao_of:'||a.cenario_id||':'||a.ocorrencia_gantt,'kgd:alocacao:'||a.cenario_id||':'||a.ocorrencia_gantt,
  'of:'||a.of,'alocacao_refere_of','planeado',jsonb_build_object('tipo_evidencia','structural_catalog','of',a.of)
  FROM consulta_v2.planos_aceites_segmentos a WHERE a.of IS NOT NULL;

DO $$
DECLARE pair text[]; definition text;
BEGIN
 FOREACH pair SLICE 1 IN ARRAY ARRAY[['kg_nos','kg_decisoes_nos'],['kg_relacoes','kg_decisoes_relacoes']] LOOP
  definition := pg_get_viewdef(format('consulta_v2.%I',pair[1])::regclass,true);
  IF position(pair[2] IN definition)=0 THEN
   EXECUTE format('CREATE OR REPLACE VIEW consulta_v2.%I AS %s UNION ALL SELECT * FROM consulta_v2.%I',
    pair[1],regexp_replace(definition,';[[:space:]]*$',''),pair[2]);
  END IF;
 END LOOP;
END $$;

COMMENT ON VIEW consulta_v2.decisoes_maquina_atuais IS
 'Decisão atual por ocorrência (OF × referência × operação × ocorrência), com assinatura técnica. Escolha de planeamento, não produção.';
COMMENT ON VIEW consulta_v2.planos_aceites_segmentos IS
 'Segmentos do plano aceite em vigor por cenário. Planeado; nunca somar a produção observada.';

-- Seleção por membro da Carteira (plano de 02/10/2026). 'cleared' é uma desmarcação explícita que vence
-- a decisão antiga da OF ou da referência. Sem fase: «nesting» = tem máquina e ainda não foi planeado (calculado).
DROP VIEW IF EXISTS consulta_v2.selecao_planear_membros_atual;
CREATE VIEW consulta_v2.selecao_planear_membros_atual AS
 SELECT dados->>'area' area,dados->>'member_key' membro,dados->>'production_order_no' of,dados->>'reference' referencia,
  dados->>'decision' decisao,dados->>'reason' motivo,dados->>'actor' autor,
  (dados->>'decided_at')::timestamptz decidida_em,(dados->>'revision')::integer revisao,versao versao_sincronizacao
 FROM consulta_v2.dados_aplicacao_atuais WHERE conjunto='application:sector_member_selection';
COMMENT ON VIEW consulta_v2.selecao_planear_membros_atual IS
 'Decisão Planear atual por membro (linha da carteira). Precedência: membro, depois OF × referência, depois OF inteira. Planeado, não produzido.';

-- Máquina escolhida na Carteira por membro e conjuntos de famílias SKU com máquina pré-definida (05/10/2026).
-- Ordem da máquina efetiva: Carteira → coluna Máquina da Tabela → conjunto de famílias. Planeado, não produzido.
CREATE OR REPLACE VIEW consulta_v2.maquina_carteira_atual AS
 SELECT dados->>'area' area,dados->>'member_key' membro,dados->>'production_order_no' of,dados->>'reference' referencia,
  dados->>'resource_id' recurso_id,dados->>'machine_name' maquina,dados->>'actor' autor,
  (dados->>'decided_at')::timestamptz decidida_em,(dados->>'revision')::integer revisao,versao versao_sincronizacao
 FROM consulta_v2.dados_aplicacao_atuais WHERE conjunto='application:sector_member_machine';
CREATE OR REPLACE VIEW consulta_v2.conjuntos_familias_atuais AS
 SELECT dados->>'area' area,dados->>'id' id,dados->>'name' nome,dados->'families' familias,
  dados->>'resource_id' recurso_id,dados->>'machine_name' maquina,(dados->>'archived')::boolean arquivado,
  (dados->>'revision')::integer revisao,dados->>'actor' autor,versao versao_sincronizacao
 FROM consulta_v2.dados_aplicacao_atuais WHERE conjunto='application:sector_family_sets';

-- Definições do setor (06/10/2026): horário dos turnos, dias de trabalho e feriados que geram os calendários.
-- Os turnos de cada máquina e semana estão nos calendários (configuração 'calendar'), não aqui.
CREATE OR REPLACE VIEW consulta_v2.definicoes_setor_atuais AS
 SELECT dados->>'area' area,dados->'definition'->'template' horario_turnos,dados->'definition'->'workdays' dias_trabalho,
  dados->'definition'->'holidays' feriados,(dados->>'revision')::integer revisao,dados->>'actor' autor,
  (dados->>'updated_at')::timestamptz atualizada_em,versao versao_sincronizacao
 FROM consulta_v2.dados_aplicacao_atuais WHERE conjunto='application:sector_settings';
COMMENT ON VIEW consulta_v2.definicoes_setor_atuais IS
 'Modelo de turnos por setor (MTG2 perfis, MTG3 cantoneiras). Capacidade planeada, não produção observada.';
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='mtg_planeamento_20260930') THEN
  GRANT SELECT ON consulta_v2.definicoes_setor_atuais TO mtg_planeamento_20260930;
 END IF;
END $$;
