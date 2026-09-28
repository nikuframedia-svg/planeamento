-- The compact capacity reader must retain the same macro-balance evidence as
-- the complete planning reader. This replaces only a derived read function;
-- imported quantities, production records and stored decisions are unchanged.
CREATE OR REPLACE FUNCTION planning_mtg.raw_capacity_detail(source_detail jsonb, patch jsonb)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $$
DECLARE
  expanded jsonb := source_detail || '{}'::jsonb;
  calculation jsonb := coalesce(expanded->'calculation','{}'::jsonb);
  original jsonb := coalesce(expanded->'original','{}'::jsonb) || coalesce(patch->'original','{}'::jsonb);
  rules jsonb := coalesce(calculation->'rules','{}'::jsonb) || coalesce(patch->'rules','{}'::jsonb);
  small_original jsonb := '{}'::jsonb;
  small_rules jsonb;
  field text;
BEGIN
  -- Keep absent keys absent, and retain quantity plus all fields consulted by
  -- planning_needs.signature(). Unrelated source evidence remains compressed.
  FOREACH field IN ARRAY ARRAY[
    'speed_m_h','theoretical_hours','quantity_required','component_ref',
    'identity_discriminator','material_type','profile','grade','length_mm',
    'outer_diameter_mm','width_mm','height_mm','thickness_mm','angle_deg'
  ] LOOP
    IF original ? field THEN
      small_original := small_original || jsonb_build_object(field,original->field);
    END IF;
  END LOOP;
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
      'Qtd em Falta',expanded->'raw'->'Qtd em Falta',
      'Mt\h',expanded->'raw'->'Mt\h'));
END
$$;
