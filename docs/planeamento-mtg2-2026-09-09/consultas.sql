-- Auditoria de viabilidade MTG2 Perfis, 2026-09-09.
-- Todas as consultas são de leitura. O snapshot é intencionalmente fixo.
-- Depois da retenção de snapshots, estas consultas podem deixar de devolver
-- a mesma fotografia. Os resultados agregados estão em metricas.json.
-- Execução: docker exec -i -u postgres postgres psql -X -v ON_ERROR_STOP=1
--           -d dataresearchmtg < consultas.sql

BEGIN READ ONLY;
SET LOCAL statement_timeout = '60s';

SELECT snapshot_id, source_filename, source_sha256, loaded_at, loader_version
FROM audit_mtg.snapshots
WHERE snapshot_id = 'mtg2_d92027db24c68fee';

SELECT count(*) AS cut_backlog_lines,
       count(DISTINCT production_order_no) AS production_orders,
       sum(remaining_quantity) AS pieces,
       sum(remaining_quantity * length_mm / 1000) AS metres
FROM analytics_mtg.kanban_plan_lines
WHERE snapshot_id = 'mtg2_d92027db24c68fee'
  AND remaining_valid AND remaining_quantity > 0 AND NOT closed_x;

SELECT o.cpis_status, count(*) AS lines,
       count(DISTINCT p.production_order_no) AS production_orders,
       sum(p.remaining_quantity) AS pieces
FROM analytics_mtg.kanban_plan_lines p
JOIN core_mtg.production_orders o USING (snapshot_id, production_order_no)
WHERE p.snapshot_id = 'mtg2_d92027db24c68fee'
  AND p.remaining_valid AND p.remaining_quantity > 0 AND NOT p.closed_x
GROUP BY o.cpis_status ORDER BY o.cpis_status;

SELECT count(*) AS generic_backlog_lines, sum(remaining_quantity) AS pieces
FROM core_mtg.production_lines
WHERE snapshot_id = 'mtg2_d92027db24c68fee' AND included_in_backlog;

SELECT count(*) FILTER (WHERE r.row_data->>'Máquina Corte' IS NOT NULL) AS source_machine,
       count(*) FILTER (WHERE r.cutting_machine IS NOT NULL) AS typed_machine,
       count(*) FILTER (WHERE r.row_data->>'Qual.' IS NULL) AS missing_grade,
       count(*) FILTER (WHERE (r.row_data->>'Área de Seção de Corte [mm2]')::numeric = 0) AS zero_area
FROM raw_mtg.plan_production_rows r
JOIN analytics_mtg.kanban_plan_lines p
  ON p.snapshot_id = r.snapshot_id AND p.plan_key = r.source_line_id
WHERE p.snapshot_id = 'mtg2_d92027db24c68fee'
  AND p.remaining_valid AND p.remaining_quantity > 0 AND NOT p.closed_x;

-- Subconjunto para simulação: ainda sem prova de stock, turnos e elegibilidade.
SELECT count(*) AS simulation_candidate_lines,
       count(DISTINCT p.production_order_no) AS simulation_candidate_orders
FROM raw_mtg.plan_production_rows r
JOIN analytics_mtg.kanban_plan_lines p
  ON p.snapshot_id = r.snapshot_id AND p.plan_key = r.source_line_id
JOIN core_mtg.production_orders o
  ON o.snapshot_id = r.snapshot_id AND o.production_order_no = r.production_order_no
WHERE p.snapshot_id = 'mtg2_d92027db24c68fee'
  AND p.remaining_valid AND p.remaining_quantity > 0 AND NOT p.closed_x
  AND o.cpis_status IN ('Em Produção', 'Em Aberto')
  AND nullif(btrim(r.row_data->>'Máquina Corte'), '') IS NOT NULL
  AND nullif(btrim(r.row_data->>'Qual.'), '') IS NOT NULL
  AND (r.row_data->>'Área de Seção de Corte [mm2]')::numeric > 0
  AND (r.row_data->>'_profile_fully_dimensioned')::boolean
  AND o.cpis_delivery_date IS NOT NULL;

SELECT r.excel_row, r.production_order_no, r.component_ref,
       r.quantity_planned, r.quantity_remaining_source, r.closed_x,
       r.row_data->>'Aborc.' AS abocardar_required,
       r.row_data->>'Aboc.' AS abocardar_source_counter
FROM raw_mtg.plan_production_rows r
WHERE r.snapshot_id = 'mtg2_d92027db24c68fee'
  AND r.row_data->>'Aborc.' = 'X' AND NOT r.closed_x
ORDER BY r.excel_row;

SELECT sheet_name, excel_row, row_data
FROM raw_mtg.other_sheet_rows
WHERE snapshot_id = 'mtg2_d92027db24c68fee'
  AND sheet_name IN ('CapacidadeMáquinas', 'PlanDisponibilidadeSemanal')
ORDER BY sheet_name, excel_row;

SELECT external_row_number, count(*) AS occurrences,
       array_agg(production_order_no ORDER BY excel_row) AS production_orders
FROM raw_mtg.plan_production_rows
WHERE snapshot_id = 'mtg2_d92027db24c68fee'
GROUP BY external_row_number HAVING count(*) > 1;

SELECT count(*) AS production_rows, count(DISTINCT p.sheet_uid) AS sheets,
       min(p.sheet_date) AS first_date, max(p.sheet_date) AS last_date,
       count(DISTINCT p.sheet_uid) FILTER (WHERE p.hours_worked IS NOT NULL) AS sheets_with_hours,
       sum(p.hours_worked) AS incorrect_repeated_row_hours
FROM mes_kanban.production_records p
JOIN mes_kanban.validated_sheets s USING (sheet_uid)
WHERE s.source_app = 'kanban-mes-mtg2';

SELECT sum(hours_once_per_sheet) AS hours_at_sheet_level
FROM (
    SELECT p.sheet_uid, max(p.hours_worked) AS hours_once_per_sheet
    FROM mes_kanban.production_records p
    JOIN mes_kanban.validated_sheets s USING (sheet_uid)
    WHERE s.source_app = 'kanban-mes-mtg2'
    GROUP BY p.sheet_uid
) h;

SELECT excel_row, production_order_no, component_ref, profile_type, length_mm,
       quantity_remaining_source, row_data->>'Qual.' AS material_grade,
       row_data->>'Máquina Corte' AS machine,
       row_data->>'comp.per. utilizar (mm)' AS bar_length_source,
       row_data->>'Ang,' AS angle_source
FROM raw_mtg.plan_production_rows
WHERE snapshot_id = 'mtg2_d92027db24c68fee' AND excel_row IN (5980, 5983)
ORDER BY excel_row;

ROLLBACK;
