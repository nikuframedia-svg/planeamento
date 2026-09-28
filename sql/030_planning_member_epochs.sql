-- Resolve current/frozen navigation epochs without scanning every retained
-- revision. Complements the existing index beginning with first_generation.
CREATE INDEX IF NOT EXISTS raw_member_closing_epoch
ON planning_mtg.raw_members(dataset,last_generation,first_generation);
