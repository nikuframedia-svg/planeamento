-- Definições por setor (06/10/2026): horário dos turnos, dias de trabalho e feriados.
-- Os turnos de cada máquina continuam nos calendários (raw_objects kind='calendar'), que são a
-- capacidade usada por todo o planeamento; esta tabela guarda só o modelo que os gera.
-- Sem BEGIN/COMMIT: a transação é aberta por scripts/migrate.py.

CREATE TABLE planning_mtg.sector_settings (
    area text PRIMARY KEY CHECK (area IN ('perfis', 'cantoneiras')),
    definition jsonb NOT NULL,
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    actor text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mes_kanban_app') THEN
        GRANT SELECT, INSERT, UPDATE ON planning_mtg.sector_settings TO mes_kanban_app;
    END IF;
END $$;
