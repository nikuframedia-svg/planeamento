-- Application-only forecast. No material request is sent to any other system.
BEGIN;
CREATE TABLE IF NOT EXISTS planning_mtg.order_registration (
 production_order_no text PRIMARY KEY,
 first_registered_at timestamptz NOT NULL,
 display_timezone text NOT NULL,
 predicted_material_request_date date NOT NULL
);
-- Only demonstrated record creation counts, never needs/PDF/snapshot creation.
WITH earliest AS (
 SELECT 'OF'||regexp_replace(upper(trim(production_order_no)), '^OF', '') AS of_no,
        min(created_at) AS first_at
 FROM planning_mtg.records
 WHERE upper(trim(production_order_no)) ~ '^(OF)?[0-9]+$'
 GROUP BY 1
), configured AS (
 SELECT coalesce(nullif(current_setting('planning.display_timezone',true),''),'Europe/Lisbon') AS tz
)
INSERT INTO planning_mtg.order_registration
 SELECT of_no,first_at,tz,(first_at AT TIME ZONE tz)::date+7 FROM earliest CROSS JOIN configured
 ON CONFLICT(production_order_no) DO NOTHING;
GRANT SELECT,INSERT ON planning_mtg.order_registration TO mes_kanban_app;
COMMIT;
