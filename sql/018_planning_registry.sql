-- Fichas de planeamento ligadas a uma linha e versão do Excel importado.
-- Aditivo: não altera saldos, necessidades, macros ou registos MES existentes.
BEGIN;

CREATE SCHEMA IF NOT EXISTS planning_mtg;

CREATE TABLE IF NOT EXISTS planning_mtg.records (
    id uuid PRIMARY KEY,
    area text NOT NULL CHECK (area IN ('perfis', 'cantoneiras')),
    production_order_no text NOT NULL,
    component_ref text NOT NULL,
    source_snapshot_id text NOT NULL,
    source_plan_key text NOT NULL,
    source_excel_row integer NOT NULL,
    source_filename text NOT NULL,
    source_payload jsonb NOT NULL,
    values_json jsonb NOT NULL,
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    actor text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS planning_records_area_updated_idx
    ON planning_mtg.records (area, updated_at DESC);
CREATE INDEX IF NOT EXISTS planning_records_order_idx
    ON planning_mtg.records (production_order_no);

CREATE TABLE IF NOT EXISTS planning_mtg.record_versions (
    request_id uuid PRIMARY KEY,
    request_hash text NOT NULL,
    record_id uuid NOT NULL REFERENCES planning_mtg.records(id),
    revision integer NOT NULL,
    source_snapshot_id text NOT NULL,
    source_payload jsonb NOT NULL,
    values_json jsonb NOT NULL,
    actor text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (record_id, revision)
);

GRANT USAGE ON SCHEMA planning_mtg TO mes_kanban_app;
GRANT SELECT, INSERT, UPDATE ON planning_mtg.records TO mes_kanban_app;
GRANT SELECT, INSERT ON planning_mtg.record_versions TO mes_kanban_app;

COMMIT;
