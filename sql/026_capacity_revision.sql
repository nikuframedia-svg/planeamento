-- Additive source evidence and weekly references; no changes to production facts.
ALTER TABLE planning_mtg.raw_objects DROP CONSTRAINT IF EXISTS raw_objects_kind_check;
ALTER TABLE planning_mtg.raw_objects ADD CONSTRAINT raw_objects_kind_check CHECK
 (kind IN ('view','formula','format','resource','calendar','rate','conversation','analysis','period','week_reference'));
CREATE TABLE IF NOT EXISTS planning_mtg.raw_workbook_evidence (
 snapshot_id text PRIMARY KEY, source_sha256 text NOT NULL, source_filename text NOT NULL,
 sheets jsonb NOT NULL, read_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS planning_mtg.raw_drive_observations (
 area text PRIMARY KEY, attempted_at timestamptz NOT NULL DEFAULT now(), checked_at timestamptz,
 remote_sha256 text, remote_modified_at timestamptz, remote_filename text, error text
);
GRANT SELECT,INSERT,UPDATE ON planning_mtg.raw_workbook_evidence,planning_mtg.raw_drive_observations TO mes_kanban_app;
CREATE INDEX IF NOT EXISTS raw_content_bucket ON planning_mtg.raw_contents((values_json->>'bucket_key'));
CREATE INDEX IF NOT EXISTS raw_content_resource ON planning_mtg.raw_contents((values_json->>'machine_key'));
