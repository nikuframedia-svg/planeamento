-- Entered values are kept independently of their usable numeric/date projection.
-- No source counters or validated production records are changed by registration.
ALTER TABLE planning_mtg.needs
 ADD COLUMN IF NOT EXISTS input_values jsonb NOT NULL DEFAULT '{}',
 ADD COLUMN IF NOT EXISTS identity_pending boolean NOT NULL DEFAULT false,
 ADD COLUMN IF NOT EXISTS identity_candidates jsonb NOT NULL DEFAULT '[]';
ALTER TABLE planning_mtg.records
 ADD COLUMN IF NOT EXISTS input_values jsonb NOT NULL DEFAULT '{}',
 ADD COLUMN IF NOT EXISTS registration_warnings jsonb NOT NULL DEFAULT '[]';
ALTER TABLE planning_mtg.record_versions
 ADD COLUMN IF NOT EXISTS input_values jsonb NOT NULL DEFAULT '{}',
 ADD COLUMN IF NOT EXISTS registration_warnings jsonb NOT NULL DEFAULT '[]';

GRANT UPDATE(input_values,registration_warnings) ON planning_mtg.record_versions TO mes_kanban_app;
