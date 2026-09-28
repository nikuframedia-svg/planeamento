-- Aditivo; as tabelas MES e as origens importadas não são alteradas.
BEGIN;
CREATE TABLE IF NOT EXISTS planning_mtg.needs (
 id uuid PRIMARY KEY, production_order_no text NOT NULL, original_order text NOT NULL,
 component_ref text NOT NULL DEFAULT '', discriminator text NOT NULL DEFAULT '',
 specification jsonb NOT NULL DEFAULT '{}', quantity_required numeric,
 revision integer NOT NULL DEFAULT 1, technical_revision integer NOT NULL DEFAULT 1,
 actor text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS planning_needs_of ON planning_mtg.needs(production_order_no);
CREATE TABLE IF NOT EXISTS planning_mtg.need_operations (
 id uuid PRIMARY KEY, need_id uuid NOT NULL REFERENCES planning_mtg.needs(id),
 area text NOT NULL CHECK(area IN ('perfis','cantoneiras')), code text NOT NULL,
 sequence integer NOT NULL DEFAULT 1, UNIQUE(need_id,area,code)
);
CREATE TABLE IF NOT EXISTS planning_mtg.need_sources (
 kind text NOT NULL, source_id text NOT NULL, need_id uuid NOT NULL REFERENCES planning_mtg.needs(id),
 version text NOT NULL, payload jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(kind,source_id)
);
CREATE TABLE IF NOT EXISTS planning_mtg.need_commands (
 request_id uuid PRIMARY KEY, request_hash text NOT NULL, result jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS planning_mtg.need_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, need_id uuid NOT NULL REFERENCES planning_mtg.needs(id),
 revision integer NOT NULL, action text NOT NULL, actor text NOT NULL, detail jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS planning_mtg.field_state (
 need_id uuid NOT NULL REFERENCES planning_mtg.needs(id), scope text NOT NULL DEFAULT 'piece',
 field text NOT NULL, value jsonb, suggestion jsonb, source jsonb NOT NULL DEFAULT '{}',
 human_decision text, actor text, decided_at timestamptz, revision integer NOT NULL,
 PRIMARY KEY(need_id,scope,field)
);
ALTER TABLE planning_mtg.field_state ADD COLUMN IF NOT EXISTS requires_review boolean NOT NULL DEFAULT false;
ALTER TABLE planning_mtg.field_state ADD COLUMN IF NOT EXISTS decision_source jsonb;
CREATE TABLE IF NOT EXISTS planning_mtg.association_decisions (
 id uuid PRIMARY KEY, production_record_id bigint NOT NULL, revision integer NOT NULL,
 status text NOT NULL CHECK(status IN ('associated','pending','unrelated')),
 allocations jsonb NOT NULL, evidence_hash text NOT NULL, evidence jsonb NOT NULL,
 actor text NOT NULL, reason text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(production_record_id,revision)
);
CREATE TABLE IF NOT EXISTS planning_mtg.need_conferences (
 id uuid PRIMARY KEY, need_id uuid NOT NULL REFERENCES planning_mtg.needs(id),
 operation_id uuid NOT NULL REFERENCES planning_mtg.need_operations(id),
 accepted_required numeric NOT NULL CHECK(accepted_required>=0),
 accepted_remaining numeric NOT NULL CHECK(accepted_remaining>=0 AND accepted_remaining<=accepted_required),
 evidence_hash text NOT NULL, evidence jsonb NOT NULL, actor text NOT NULL, reason text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS planning_mtg.audit_outbox (
 id uuid PRIMARY KEY, document_id text NOT NULL, piece_id text NOT NULL,
 event jsonb NOT NULL, delivered_at timestamptz, attempts integer NOT NULL DEFAULT 0,
 last_error text, created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE planning_mtg.records ADD COLUMN IF NOT EXISTS need_id uuid REFERENCES planning_mtg.needs(id),
 ADD COLUMN IF NOT EXISTS operation_id uuid REFERENCES planning_mtg.need_operations(id);
CREATE UNIQUE INDEX IF NOT EXISTS planning_record_need_operation ON planning_mtg.records(operation_id) WHERE operation_id IS NOT NULL;
GRANT SELECT,INSERT,UPDATE ON planning_mtg.needs,planning_mtg.need_operations,planning_mtg.need_sources,
 planning_mtg.field_state,planning_mtg.audit_outbox TO mes_kanban_app;
GRANT SELECT,INSERT ON planning_mtg.need_commands,planning_mtg.need_events,
 planning_mtg.association_decisions,planning_mtg.need_conferences TO mes_kanban_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA planning_mtg TO mes_kanban_app;
COMMIT;
