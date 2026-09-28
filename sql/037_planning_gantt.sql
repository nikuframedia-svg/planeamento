-- Gantt scenarios use the existing revision, idempotency and job audit stores.
ALTER TABLE planning_mtg.raw_objects DROP CONSTRAINT IF EXISTS raw_objects_kind_check;
ALTER TABLE planning_mtg.raw_objects ADD CONSTRAINT raw_objects_kind_check CHECK
 (kind IN ('view','formula','format','resource','calendar','rate','conversation','analysis','period','week_reference','worked_hours','gantt'));
ALTER TABLE planning_mtg.raw_jobs DROP CONSTRAINT IF EXISTS raw_jobs_kind_check;
ALTER TABLE planning_mtg.raw_jobs ADD CONSTRAINT raw_jobs_kind_check CHECK
 (kind IN ('proposal','analysis','gantt'));
