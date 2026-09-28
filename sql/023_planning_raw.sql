-- Additive: no changes to source, production or preparation identities.
CREATE TABLE IF NOT EXISTS planning_mtg.raw_views (
 id uuid PRIMARY KEY, name text NOT NULL, revision integer NOT NULL DEFAULT 1,
 settings jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS planning_mtg.raw_analyses (
 id uuid PRIMARY KEY, request_hash text NOT NULL, title text NOT NULL,
 status text NOT NULL CHECK(status IN ('queued','running','done','failed')),
 question text NOT NULL, dataset jsonb NOT NULL, result jsonb,
 error text, model text, parent_id uuid REFERENCES planning_mtg.raw_analyses(id),
 saved boolean NOT NULL DEFAULT false, created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT,INSERT,UPDATE ON planning_mtg.raw_views,planning_mtg.raw_analyses TO mes_kanban_app;
