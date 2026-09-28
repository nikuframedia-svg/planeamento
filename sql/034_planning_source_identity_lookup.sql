-- Retained planning links resolve an immutable source_line_id across snapshots.
-- The existing (snapshot_id, source_line_id) key cannot serve that lookup
-- efficiently as the import history grows. This index changes no source data.
CREATE INDEX IF NOT EXISTS planning_source_identity_lookup
    ON raw_mtg.plan_production_rows (source_line_id)
    INCLUDE (snapshot_id, excel_row);
