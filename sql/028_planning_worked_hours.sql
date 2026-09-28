-- Planning-only declarations reuse the audited configuration store.
ALTER TABLE planning_mtg.raw_objects DROP CONSTRAINT IF EXISTS raw_objects_kind_check;
ALTER TABLE planning_mtg.raw_objects ADD CONSTRAINT raw_objects_kind_check CHECK
 (kind IN ('view','formula','format','resource','calendar','rate','conversation','analysis','period','week_reference','worked_hours'));
