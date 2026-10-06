-- Validated HTTP export has no native sheet/row IDs. Keep it separate from
-- native OCR events; a new snapshot replaces the current population.
CREATE TABLE IF NOT EXISTS ocr_original.export_sources (
 id text PRIMARY KEY, source_url text NOT NULL, current_version text,
 attempted_at timestamptz, confirmed_at timestamptz, last_error text
);
CREATE TABLE IF NOT EXISTS ocr_original.export_versions (
 id text PRIMARY KEY, source_id text NOT NULL REFERENCES ocr_original.export_sources(id),
 content_hash text NOT NULL, captured_at timestamptz NOT NULL DEFAULT now(),
 row_count integer NOT NULL CHECK(row_count>0), metadata jsonb NOT NULL,
 UNIQUE(source_id,content_hash)
);
CREATE TABLE IF NOT EXISTS ocr_original.export_rows (
 version_id text NOT NULL REFERENCES ocr_original.export_versions(id),
 row_key text NOT NULL, payload jsonb NOT NULL,
 PRIMARY KEY(version_id,row_key)
);
GRANT SELECT ON ocr_original.export_sources,ocr_original.export_versions,ocr_original.export_rows TO mes_kanban_app;
GRANT SELECT,INSERT,UPDATE ON ocr_original.export_sources TO ocr_original_importer;
GRANT SELECT,INSERT ON ocr_original.export_versions,ocr_original.export_rows TO ocr_original_importer;
