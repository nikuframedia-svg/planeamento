-- Planning follows retained source identities without a current snapshot ID.
-- The canonical view starts at production_lines, so it needs the same lookup
-- as the raw table. No source or retained publication is changed.
CREATE INDEX IF NOT EXISTS planning_core_identity_lookup
    ON core_mtg.production_lines (source_line_id) INCLUDE (snapshot_id);

-- Order-scoped recalculation uses the same normalization as source matching.
CREATE INDEX IF NOT EXISTS planning_normalized_order_lookup
    ON raw_mtg.plan_production_rows
    (snapshot_id, (regexp_replace(trim(production_order_no),'^OF[ ._-]*','','i')));
