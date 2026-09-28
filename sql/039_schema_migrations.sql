-- Registo das migrações aplicadas (28/09/2026).
-- Até aqui as migrações eram aplicadas à mão e não ficava registo do que corria na base.
-- A partir de 039, scripts/migrate.py aplica cada migração numa transação única e grava-a
-- nesta tabela na mesma transação. As 010–038 ficam registadas como linha de base,
-- depois de conferido o estado da base (comando `baseline 038`).
-- Sem BEGIN/COMMIT próprios: a transação é aberta pelo programa.
CREATE SCHEMA IF NOT EXISTS planning_mtg;

CREATE TABLE IF NOT EXISTS planning_mtg.schema_migrations (
    version text PRIMARY KEY CHECK (version ~ '^[0-9]{3}$'),
    filename text NOT NULL,
    sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    applied_at timestamptz NOT NULL DEFAULT now(),
    applied_by text NOT NULL,
    note text
);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mes_kanban_app') THEN
        GRANT SELECT ON planning_mtg.schema_migrations TO mes_kanban_app;
    END IF;
END $$;
