-- CPIS direto, fichas sem linha Excel e conferências de produção.
-- Migração aditiva: não altera necessidades, saldos ou factos MES existentes.
BEGIN;

CREATE SCHEMA IF NOT EXISTS cpis_mtg;

CREATE TABLE IF NOT EXISTS cpis_mtg.versions (
    id uuid PRIMARY KEY,
    source_name text NOT NULL DEFAULT 'CPIS',
    source_view text NOT NULL,
    content_sha256 char(64) NOT NULL UNIQUE,
    row_count integer NOT NULL CHECK (row_count >= 0),
    state_counts jsonb NOT NULL DEFAULT '{}'::jsonb,
    queried_at timestamptz NOT NULL,
    published_at timestamptz NOT NULL DEFAULT now(),
    last_confirmed_at timestamptz NOT NULL,
    connector_version text NOT NULL
);

CREATE TABLE IF NOT EXISTS cpis_mtg.sync_attempts (
    id uuid PRIMARY KEY,
    started_at timestamptz NOT NULL,
    finished_at timestamptz NOT NULL,
    success boolean NOT NULL,
    version_id uuid REFERENCES cpis_mtg.versions(id),
    row_count integer,
    error_code text,
    error_message text,
    details jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS cpis_sync_attempts_finished_idx
    ON cpis_mtg.sync_attempts(finished_at DESC);

CREATE TABLE IF NOT EXISTS cpis_mtg.orders (
    version_id uuid NOT NULL REFERENCES cpis_mtg.versions(id) ON DELETE CASCADE,
    source_row_no integer NOT NULL CHECK (source_row_no > 0),
    production_order_no text,
    production_order_original text,
    sales_order_no text,
    customer_name text,
    responsible_dp text,
    actual_start_date timestamp,
    planned_finish_date timestamp,
    actual_finish_date timestamp,
    observations text,
    work_type_code text,
    work_type_description text,
    production_order_weight_kg numeric,
    record_date timestamp,
    received_dp_date timestamp,
    status text,
    delivery_date timestamp,
    received_dl_date timestamp,
    planned_start_date timestamp,
    sap_order text,
    factory_unit text,
    row_data jsonb NOT NULL,
    PRIMARY KEY (version_id, source_row_no)
);

CREATE INDEX IF NOT EXISTS cpis_orders_version_of_idx
    ON cpis_mtg.orders(version_id, production_order_no);
CREATE INDEX IF NOT EXISTS cpis_orders_version_status_idx
    ON cpis_mtg.orders(version_id, status);

ALTER TABLE IF EXISTS planning_mtg.records
    ALTER COLUMN source_snapshot_id DROP NOT NULL,
    ALTER COLUMN source_plan_key DROP NOT NULL,
    ALTER COLUMN source_excel_row DROP NOT NULL,
    ALTER COLUMN source_filename DROP NOT NULL,
    ALTER COLUMN source_payload SET DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS source_kind text NOT NULL DEFAULT 'plan_line',
    ADD COLUMN IF NOT EXISTS source_id text,
    ADD COLUMN IF NOT EXISTS source_version text,
    ADD COLUMN IF NOT EXISTS record_status text NOT NULL DEFAULT 'draft',
    ADD COLUMN IF NOT EXISTS provenance_json jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE IF EXISTS planning_mtg.record_versions
    ALTER COLUMN source_snapshot_id DROP NOT NULL,
    ADD COLUMN IF NOT EXISTS source_kind text NOT NULL DEFAULT 'plan_line',
    ADD COLUMN IF NOT EXISTS source_id text,
    ADD COLUMN IF NOT EXISTS source_version text,
    ADD COLUMN IF NOT EXISTS record_status text NOT NULL DEFAULT 'draft',
    ADD COLUMN IF NOT EXISTS provenance_json jsonb NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS planning_mtg.reconciliations (
    request_id uuid PRIMARY KEY,
    production_order_no text NOT NULL,
    area text NOT NULL CHECK (area IN ('perfis', 'cantoneiras')),
    component_ref text NOT NULL,
    operation text NOT NULL,
    accepted_required numeric,
    accepted_remaining numeric,
    macro_snapshot_id text,
    cpis_version text,
    evidence_fingerprint char(64) NOT NULL,
    evidence_json jsonb NOT NULL,
    actor text NOT NULL,
    reason text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS planning_reconciliations_identity_idx
    ON planning_mtg.reconciliations(production_order_no, area, component_ref, operation, created_at DESC);

CREATE TABLE IF NOT EXISTS planning_mtg.output_proposals (
    id uuid PRIMARY KEY,
    request_id uuid NOT NULL UNIQUE,
    request_hash char(64) NOT NULL,
    record_refs jsonb NOT NULL,
    cpis_version text NOT NULL,
    macro_snapshot_id text NOT NULL,
    macro_sha256 char(64) NOT NULL,
    proposal_fingerprint char(64) NOT NULL,
    summary_json jsonb NOT NULL,
    actor text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    exported_at timestamptz
);

GRANT USAGE ON SCHEMA cpis_mtg TO mes_kanban_app;
REVOKE UPDATE ON cpis_mtg.sync_attempts, cpis_mtg.orders FROM mes_kanban_app;
GRANT SELECT, INSERT, UPDATE ON cpis_mtg.versions TO mes_kanban_app;
GRANT SELECT, INSERT ON cpis_mtg.sync_attempts, cpis_mtg.orders TO mes_kanban_app;
GRANT SELECT, INSERT ON planning_mtg.reconciliations TO mes_kanban_app;
GRANT SELECT, INSERT, UPDATE ON planning_mtg.output_proposals TO mes_kanban_app;

COMMIT;
