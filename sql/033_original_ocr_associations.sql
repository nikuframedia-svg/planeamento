BEGIN;
-- Local decisions refer to immutable source coordinates; no OCR fact is changed.
CREATE TABLE IF NOT EXISTS planning_mtg.original_association_decisions (
 id uuid PRIMARY KEY,
 production_record_id text NOT NULL CHECK (production_record_id ~ '^original:[0-9a-f-]{36}:[0-9]+:[0-9]+$'),
 revision integer NOT NULL CHECK (revision > 0),
 status text NOT NULL CHECK(status IN ('associated','pending','unrelated')),
 allocations jsonb NOT NULL,
 evidence_hash text NOT NULL,
 evidence jsonb NOT NULL,
 actor text NOT NULL,
 reason text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(production_record_id,revision)
);
GRANT SELECT,INSERT ON planning_mtg.original_association_decisions TO mes_kanban_app;
COMMIT;
