-- SKU families are classification metadata, not physical-piece identities.
CREATE TABLE IF NOT EXISTS planning_mtg.sku_family_rules (
 id text PRIMARY KEY, area text NOT NULL CHECK(area IN ('cantoneiras','perfis')),
 config jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(area,id)
);
CREATE TABLE IF NOT EXISTS planning_mtg.sku_family_heads (
 area text PRIMARY KEY, rules_id text NOT NULL,
 FOREIGN KEY(area,rules_id) REFERENCES planning_mtg.sku_family_rules(area,id)
);
CREATE TABLE IF NOT EXISTS planning_mtg.sku_family_mappings (
 area text NOT NULL, sku text NOT NULL CHECK(length(sku)>0),
 family text, status text NOT NULL, rule text NOT NULL, rules_id text NOT NULL,
 revision integer NOT NULL CHECK(revision>0), evidence jsonb NOT NULL DEFAULT '{}',
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(area,sku),
 FOREIGN KEY(area,rules_id) REFERENCES planning_mtg.sku_family_rules(area,id)
);
CREATE INDEX IF NOT EXISTS sku_family_lookup ON planning_mtg.sku_family_mappings(area,family,status);
CREATE TABLE IF NOT EXISTS planning_mtg.sku_family_history (
 area text NOT NULL, sku text NOT NULL, revision integer NOT NULL,
 family text, status text NOT NULL, rule text NOT NULL, rules_id text NOT NULL,
 evidence jsonb NOT NULL, recorded_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(area,sku,revision),
 FOREIGN KEY(area,sku) REFERENCES planning_mtg.sku_family_mappings(area,sku),
 FOREIGN KEY(area,rules_id) REFERENCES planning_mtg.sku_family_rules(area,id)
);
GRANT SELECT,INSERT ON planning_mtg.sku_family_rules,planning_mtg.sku_family_history TO mes_kanban_app;
GRANT SELECT,INSERT,UPDATE ON planning_mtg.sku_family_heads,planning_mtg.sku_family_mappings TO mes_kanban_app;
COMMENT ON TABLE planning_mtg.sku_family_mappings IS 'One classification per original SKU and area. Pending and unknown mappings are explicit. Never merges pieces, variants, orders or quantities.';
