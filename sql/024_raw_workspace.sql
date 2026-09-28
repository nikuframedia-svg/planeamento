-- Additive RAW workspace. Originals, validated production and historical reports stay untouched.
CREATE TABLE IF NOT EXISTS planning_mtg.raw_generations (
 id bigserial PRIMARY KEY, dataset text NOT NULL, fingerprint text NOT NULL,
 metadata jsonb NOT NULL, row_count integer NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(dataset,fingerprint)
);
CREATE INDEX IF NOT EXISTS raw_generation_latest ON planning_mtg.raw_generations(dataset,id DESC);
CREATE TABLE IF NOT EXISTS planning_mtg.raw_contents (
 hash text PRIMARY KEY, values_json jsonb NOT NULL, detail jsonb NOT NULL,
 search_text text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS raw_content_of ON planning_mtg.raw_contents((values_json->>'of'));
CREATE INDEX IF NOT EXISTS raw_content_machine ON planning_mtg.raw_contents((values_json->>'machine'));
CREATE TABLE IF NOT EXISTS planning_mtg.raw_members (
 dataset text NOT NULL, row_key text NOT NULL, first_generation bigint NOT NULL,
 last_generation bigint, content_hash text NOT NULL REFERENCES planning_mtg.raw_contents(hash),
 PRIMARY KEY(dataset,row_key,first_generation)
);
CREATE UNIQUE INDEX IF NOT EXISTS raw_member_current ON planning_mtg.raw_members(dataset,row_key) WHERE last_generation IS NULL;
CREATE INDEX IF NOT EXISTS raw_member_navigation ON planning_mtg.raw_members(dataset,first_generation,last_generation);
CREATE TABLE IF NOT EXISTS planning_mtg.raw_signals (
 topic text PRIMARY KEY, revision bigint NOT NULL DEFAULT 1, changed_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS planning_mtg.raw_objects (
 id uuid PRIMARY KEY, kind text NOT NULL CHECK(kind IN ('view','formula','format','resource','calendar','rate','conversation','analysis')),
 name text NOT NULL, area text, revision integer NOT NULL DEFAULT 1,
 definition jsonb NOT NULL, archived boolean NOT NULL DEFAULT false,
 actor text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS raw_objects_kind ON planning_mtg.raw_objects(kind,area,archived);
CREATE TABLE IF NOT EXISTS planning_mtg.raw_object_versions (
 object_id uuid NOT NULL REFERENCES planning_mtg.raw_objects(id), revision integer NOT NULL,
 definition jsonb NOT NULL, name text NOT NULL, archived boolean NOT NULL,
 actor text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(object_id,revision)
);
CREATE TABLE IF NOT EXISTS planning_mtg.raw_messages (
 id bigserial PRIMARY KEY, conversation_id uuid NOT NULL REFERENCES planning_mtg.raw_objects(id),
 role text NOT NULL CHECK(role IN ('user','assistant')), content text NOT NULL, proposal jsonb,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS planning_mtg.raw_jobs (
 id uuid PRIMARY KEY, kind text NOT NULL CHECK(kind IN ('proposal','analysis')),
 object_id uuid NOT NULL REFERENCES planning_mtg.raw_objects(id), object_revision integer NOT NULL,
 fingerprint text NOT NULL, status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','done','failed')),
 input jsonb NOT NULL, result jsonb, error text, model text, worker text,
 attempts integer NOT NULL DEFAULT 0, heartbeat_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz,
 UNIQUE(object_id,object_revision,fingerprint)
);
CREATE INDEX IF NOT EXISTS raw_jobs_queue ON planning_mtg.raw_jobs(status,created_at);
CREATE INDEX IF NOT EXISTS raw_jobs_results ON planning_mtg.raw_jobs(object_id,finished_at DESC) WHERE status='done';
-- Views keep their IDs and previous settings. Conversion is performed by the versioned view service.
INSERT INTO planning_mtg.raw_objects(id,kind,name,definition,revision,actor)
 SELECT id,'view',name,settings,revision,'Valor histórico — origem detalhada não disponível'
 FROM planning_mtg.raw_views ON CONFLICT DO NOTHING;
INSERT INTO planning_mtg.raw_object_versions(object_id,revision,definition,name,archived,actor)
 SELECT id,revision,definition,name,archived,actor FROM planning_mtg.raw_objects WHERE kind='view' ON CONFLICT DO NOTHING;
GRANT SELECT,INSERT,UPDATE,DELETE ON planning_mtg.raw_generations,planning_mtg.raw_contents,planning_mtg.raw_members,
 planning_mtg.raw_signals,planning_mtg.raw_objects,planning_mtg.raw_object_versions,planning_mtg.raw_messages,planning_mtg.raw_jobs TO mes_kanban_app;
GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA planning_mtg TO mes_kanban_app;

CREATE TABLE IF NOT EXISTS planning_mtg.raw_worker_state (
 source text PRIMARY KEY, attempted_at timestamptz, confirmed_at timestamptz,
 error text, available boolean NOT NULL DEFAULT false
);
GRANT SELECT,INSERT,UPDATE ON planning_mtg.raw_worker_state TO mes_kanban_app;
