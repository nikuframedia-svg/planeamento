-- Administrative context for locally registered orders, independent of CPIS.
BEGIN;
CREATE TABLE IF NOT EXISTS planning_mtg.local_orders (
 production_order_no text PRIMARY KEY,
 values_json jsonb NOT NULL DEFAULT '{}',
 revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 actor text NOT NULL
);
CREATE TABLE IF NOT EXISTS planning_mtg.local_order_history (
 production_order_no text NOT NULL REFERENCES planning_mtg.local_orders,
 revision integer NOT NULL,
 values_json jsonb NOT NULL,
 changed_at timestamptz NOT NULL DEFAULT now(),
 actor text NOT NULL,
 PRIMARY KEY (production_order_no, revision)
);
GRANT SELECT,INSERT,UPDATE ON planning_mtg.local_orders TO mes_kanban_app;
GRANT SELECT,INSERT ON planning_mtg.local_order_history TO mes_kanban_app;
COMMIT;
