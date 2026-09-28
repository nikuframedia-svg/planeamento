-- Locate the complete current OF without reading all its retained JSON epochs.
-- This is navigation data only. Frozen generations keep their original content.
ALTER TABLE planning_mtg.raw_members ADD COLUMN IF NOT EXISTS planning_order text;
UPDATE planning_mtg.raw_members m SET planning_order=c.values_json->>'of'
FROM planning_mtg.raw_contents c
WHERE m.content_hash=c.hash AND m.dataset IN ('planning:perfis','planning:cantoneiras')
  AND m.last_generation IS NULL AND m.planning_order IS NULL
  AND c.values_json->>'of' IS NOT NULL;
CREATE INDEX IF NOT EXISTS raw_member_current_order
ON planning_mtg.raw_members(dataset,planning_order,row_key)
WHERE last_generation IS NULL;
