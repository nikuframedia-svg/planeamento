-- Controlos independentes dos cálculos Python sobre o snapshot fixo.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '30s';

WITH candidate AS (
  SELECT r.*, o.cpis_delivery_date,
         nullif(btrim(r.row_data->>'Máquina Corte'), '') IS NOT NULL
         AND nullif(btrim(r.row_data->>'Qual.'), '') IS NOT NULL
         AND (r.row_data->>'Área de Seção de Corte [mm2]')::numeric > 0
         AND (r.row_data->>'_profile_fully_dimensioned')::boolean
         AND o.cpis_delivery_date IS NOT NULL AS basic
  FROM raw_mtg.plan_production_rows r
  JOIN analytics_mtg.kanban_plan_lines p
    ON p.snapshot_id = r.snapshot_id AND p.plan_key = r.source_line_id
  JOIN core_mtg.production_orders o
    ON o.snapshot_id = r.snapshot_id AND o.production_order_no = r.production_order_no
  WHERE r.snapshot_id = 'mtg2_d92027db24c68fee'
    AND p.remaining_valid AND p.remaining_quantity > 0 AND NOT p.closed_x
    AND o.cpis_status IN ('Em Produção', 'Em Aberto')
), complete_orders AS (
  SELECT production_order_no, count(*) AS lines
  FROM candidate GROUP BY production_order_no HAVING bool_and(coalesce(basic, false))
)
SELECT count(*) AS active_lines,
       count(*) FILTER (WHERE basic) AS basic_lines,
       count(*) FILTER (WHERE row_data->>'Máquina Corte' = 'Serrote MEBA IS381 Pav 3') AS meba_lines,
       count(*) FILTER (WHERE basic AND row_data->>'Máquina Corte' = 'Serrote MEBA IS381 Pav 3') AS meba_basic_lines,
       (SELECT count(*) FROM complete_orders) AS complete_cut_orders,
       (SELECT sum(lines) FROM complete_orders) AS their_lines,
       count(DISTINCT (production_order_no, material_type, profile_type))
          FILTER (WHERE row_data->>'Qual.' IS NULL) AS missing_grade_groups
FROM candidate;

SELECT count(*) AS active_abocardar_lines,
       count(*) FILTER (WHERE r.quantity_remaining_source <= 0) AS no_cut_remaining,
       count(*) FILTER (WHERE r.row_data->>'Aboc.' IS NOT NULL) AS abocardar_counter_present
FROM raw_mtg.plan_production_rows r
JOIN core_mtg.production_orders o USING (snapshot_id, production_order_no)
WHERE r.snapshot_id = 'mtg2_d92027db24c68fee'
  AND NOT r.closed_x AND r.row_data->>'Aborc.' = 'X'
  AND o.cpis_status IN ('Em Produção', 'Em Aberto');

SELECT excel_row, production_order_no, component_ref, length_mm,
       quantity_planned, row_data->>'Ser.' AS cut_counter,
       row_data->>'Aboc.' AS abocardar_counter, quantity_remaining_source
FROM raw_mtg.plan_production_rows
WHERE snapshot_id = 'mtg2_d92027db24c68fee'
  AND excel_row IN (5200, 5571, 5572, 5573, 6682, 6752, 6753)
ORDER BY excel_row;

ROLLBACK;
