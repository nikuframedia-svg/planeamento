-- Store changing estimates separately from immutable, potentially large source
-- detail. Values/search stay directly indexed; every reader gets the same row.
ALTER TABLE planning_mtg.raw_contents
  ADD COLUMN IF NOT EXISTS detail_source_hash text REFERENCES planning_mtg.raw_contents(hash),
  ADD COLUMN IF NOT EXISTS detail_patch jsonb;
ALTER TABLE planning_mtg.raw_contents ALTER COLUMN detail_patch SET COMPRESSION lz4;

CREATE OR REPLACE FUNCTION planning_mtg.raw_estimated_detail(source_detail jsonb, patch jsonb)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE AS $$
DECLARE
  expanded jsonb := source_detail || '{}'::jsonb;
  calculation jsonb := coalesce(expanded->'calculation','{}'::jsonb);
BEGIN
  RETURN expanded || jsonb_build_object(
    'original',coalesce(expanded->'original','{}'::jsonb) || (patch->'original'),
    'calculation',calculation || jsonb_build_object(
      'rules',coalesce(calculation->'rules','{}'::jsonb) || (patch->'rules'),
      'operation_estimates',patch->'operation_estimates'));
END
$$;

CREATE OR REPLACE VIEW planning_mtg.raw_resolved_contents AS
SELECT c.hash,c.values_json,c.search_text,c.created_at,
  CASE WHEN c.detail_source_hash IS NULL THEN c.detail
    ELSE planning_mtg.raw_estimated_detail(source.detail,c.detail_patch) END AS detail
FROM planning_mtg.raw_contents c
LEFT JOIN planning_mtg.raw_contents source ON source.hash=c.detail_source_hash;

GRANT SELECT ON planning_mtg.raw_resolved_contents TO mes_kanban_app;

-- Capacity consumes a small part of the detail. Extract it from the retained
-- source before applying the patch, avoiding reconstruction of unused payloads.
CREATE OR REPLACE FUNCTION planning_mtg.raw_capacity_detail(source_detail jsonb, patch jsonb)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $$
DECLARE
  expanded jsonb := source_detail || '{}'::jsonb;
  calculation jsonb := coalesce(expanded->'calculation','{}'::jsonb);
  original jsonb := coalesce(expanded->'original','{}'::jsonb) || coalesce(patch->'original','{}'::jsonb);
  rules jsonb := coalesce(calculation->'rules','{}'::jsonb) || coalesce(patch->'rules','{}'::jsonb);
  small_original jsonb;
  small_rules jsonb;
BEGIN
  -- Preserve absent keys versus explicit nulls without starting two SQL
  -- aggregates for every historical piece during a resource recalculation.
  small_original :=
    CASE WHEN original ? 'speed_m_h' THEN jsonb_build_object('speed_m_h',original->'speed_m_h') ELSE '{}'::jsonb END ||
    CASE WHEN original ? 'theoretical_hours' THEN jsonb_build_object('theoretical_hours',original->'theoretical_hours') ELSE '{}'::jsonb END;
  small_rules :=
    CASE WHEN rules ? 'hours_pct' THEN jsonb_build_object('hours_pct',rules->'hours_pct') ELSE '{}'::jsonb END ||
    CASE WHEN rules ? 'theoretical_hours' THEN jsonb_build_object('theoretical_hours',rules->'theoretical_hours') ELSE '{}'::jsonb END;
  IF patch ? 'operation_estimates' THEN
    calculation := calculation || jsonb_build_object('operation_estimates',patch->'operation_estimates');
  END IF;
  RETURN expanded-ARRAY['raw','sources','ocr_evidence','operations','original','calculation'] || jsonb_build_object(
    'original',small_original,
    'calculation',(calculation-'rules') || jsonb_build_object('rules',small_rules),
    'raw',jsonb_build_object('Fechado',expanded->'raw'->'Fechado',
      'Horas Consumidas',expanded->'raw'->'Horas Consumidas',
      'h teor. Falta',expanded->'raw'->'h teor. Falta',
      'Quantidade Prevista',expanded->'raw'->'Quantidade Prevista',
      'Mt\h',expanded->'raw'->'Mt\h'));
END
$$;

CREATE OR REPLACE VIEW planning_mtg.raw_capacity_contents AS
SELECT c.hash,c.values_json,
  planning_mtg.raw_capacity_detail(coalesce(source.detail,c.detail),c.detail_patch) AS detail
FROM planning_mtg.raw_contents c
LEFT JOIN planning_mtg.raw_contents source ON source.hash=c.detail_source_hash;

GRANT SELECT ON planning_mtg.raw_capacity_contents TO mes_kanban_app;
