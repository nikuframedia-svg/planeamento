-- Immutable research inputs; decisions remain in raw_objects/raw_object_versions.
CREATE TABLE planning_mtg.gantt_source_versions (
    id text PRIMARY KEY,
    provider text NOT NULL,
    sources jsonb NOT NULL,
    metadata jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE planning_mtg.gantt_source_rows (
    version_id text NOT NULL REFERENCES planning_mtg.gantt_source_versions(id),
    key text NOT NULL,
    payload jsonb NOT NULL,
    PRIMARY KEY (version_id, key)
);
CREATE TABLE planning_mtg.gantt_source_heads (
    provider text PRIMARY KEY,
    version_id text REFERENCES planning_mtg.gantt_source_versions(id),
    checked_at timestamptz,
    last_error text
);
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mes_kanban_app') THEN
        GRANT SELECT, INSERT ON planning_mtg.gantt_source_versions, planning_mtg.gantt_source_rows TO mes_kanban_app;
        GRANT SELECT, INSERT, UPDATE ON planning_mtg.gantt_source_heads TO mes_kanban_app;
    END IF;
END $$;
