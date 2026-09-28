-- Dedicated publisher on the central database. CPIS source credentials remain separate.
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='cpis_connector') THEN
  CREATE ROLE cpis_connector LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
 END IF;
END $$;
GRANT USAGE ON SCHEMA cpis_mtg TO cpis_connector;
GRANT SELECT,INSERT,UPDATE ON cpis_mtg.versions TO cpis_connector;
GRANT SELECT,INSERT ON cpis_mtg.orders,cpis_mtg.sync_attempts TO cpis_connector;
-- No password is embedded or changed. Provision it separately on installation.
