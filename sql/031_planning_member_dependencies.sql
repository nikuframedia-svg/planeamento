-- Navigation data for current planning dependencies. Logical row contents and
-- retained source versions are unchanged; NULL keeps the legacy query fallback.
ALTER TABLE planning_mtg.raw_members ADD COLUMN IF NOT EXISTS planning_machine text;
ALTER TABLE planning_mtg.raw_members ADD COLUMN IF NOT EXISTS planning_active boolean;
UPDATE planning_mtg.raw_members m
SET planning_machine=coalesce(c.values_json->>'machine',''),
    planning_active=(c.values_json->>'planning_active')::boolean
FROM planning_mtg.raw_contents c
WHERE m.content_hash=c.hash AND m.dataset IN ('planning:perfis','planning:cantoneiras')
  AND m.last_generation IS NULL AND m.planning_active IS NULL
  AND c.values_json->>'planning_active' IN ('true','false');
CREATE INDEX IF NOT EXISTS raw_member_closed_machine
ON planning_mtg.raw_members(dataset,planning_machine,row_key)
WHERE last_generation IS NULL AND planning_active=false;
CREATE INDEX IF NOT EXISTS raw_member_legacy_dependencies
ON planning_mtg.raw_members(dataset)
WHERE last_generation IS NULL AND planning_active IS NULL;
