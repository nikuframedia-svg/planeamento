BEGIN;
CREATE SCHEMA IF NOT EXISTS ocr_original;
CREATE TABLE IF NOT EXISTS ocr_original.instances (
 id uuid PRIMARY KEY, source_label text NOT NULL, current_snapshot uuid, confirmed_at timestamptz
);
CREATE TABLE IF NOT EXISTS ocr_original.snapshots (
 id uuid PRIMARY KEY, instance_id uuid NOT NULL REFERENCES ocr_original.instances(id),
 content_hash text NOT NULL, captured_at timestamptz NOT NULL, published_at timestamptz NOT NULL DEFAULT now(),
 sheet_count integer NOT NULL, production_count integer NOT NULL, stoppage_count integer NOT NULL,
 UNIQUE(instance_id,content_hash)
);
CREATE TABLE IF NOT EXISTS ocr_original.sheets (
 instance_id uuid NOT NULL REFERENCES ocr_original.instances(id), sheet_id bigint NOT NULL,
 content_hash text NOT NULL, source_revision integer, payload jsonb NOT NULL,
 PRIMARY KEY(instance_id,sheet_id,content_hash)
);
CREATE TABLE IF NOT EXISTS ocr_original.snapshot_sheets (
 snapshot_id uuid NOT NULL REFERENCES ocr_original.snapshots(id), instance_id uuid NOT NULL,
 sheet_id bigint NOT NULL, content_hash text NOT NULL,
 PRIMARY KEY(snapshot_id,sheet_id),
 FOREIGN KEY(instance_id,sheet_id,content_hash) REFERENCES ocr_original.sheets(instance_id,sheet_id,content_hash)
);
CREATE TABLE IF NOT EXISTS ocr_original.sync_attempts (
 id uuid PRIMARY KEY, instance_id uuid NOT NULL, started_at timestamptz NOT NULL,
 finished_at timestamptz NOT NULL DEFAULT now(), success boolean NOT NULL, snapshot_id uuid,
 error_code text, details jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS original_attempt_date ON ocr_original.sync_attempts(finished_at DESC);
-- Separate importer role: no grants in CPIS, MES or planning.
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='ocr_original_importer') THEN CREATE ROLE ocr_original_importer LOGIN; END IF; END $$;
GRANT USAGE ON SCHEMA ocr_original TO ocr_original_importer,mes_kanban_app;
GRANT SELECT,INSERT ON ALL TABLES IN SCHEMA ocr_original TO ocr_original_importer;
GRANT UPDATE(current_snapshot,confirmed_at) ON ocr_original.instances TO ocr_original_importer;
GRANT SELECT ON ALL TABLES IN SCHEMA ocr_original TO mes_kanban_app;
COMMIT;
