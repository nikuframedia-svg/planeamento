-- Seleção do trabalho a planear: botão «Planear» da Carteira (Passo 6 do plano de 28/09/2026).
-- Uma decisão por OF × referência; reference = '*' quer dizer a OF inteira.
-- A decisão mais específica ganha: (OF, referência) sobrepõe-se a (OF, '*').
-- sector_decision_events guarda todas as mudanças; a aplicação só pode acrescentar.
-- Sem BEGIN/COMMIT: a transação é aberta por scripts/migrate.py.

CREATE TABLE planning_mtg.sector_selection (
    area text NOT NULL CHECK (area IN ('perfis', 'cantoneiras')),
    production_order_no text NOT NULL CHECK (production_order_no <> ''),
    reference text NOT NULL CHECK (reference <> ''),
    decision text NOT NULL CHECK (decision IN ('selected', 'excluded')),
    reason text,
    actor text NOT NULL,
    decided_at timestamptz NOT NULL DEFAULT now(),
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    seen jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (area, production_order_no, reference),
    CONSTRAINT sector_selection_exclusion_reason CHECK (decision = 'selected' OR length(btrim(coalesce(reason, ''))) > 0)
);

CREATE TABLE planning_mtg.sector_decision_events (
    id bigserial PRIMARY KEY,
    area text NOT NULL CHECK (area IN ('perfis', 'cantoneiras')),
    kind text NOT NULL CHECK (kind IN ('selection')),
    production_order_no text NOT NULL,
    reference text NOT NULL,
    action text NOT NULL CHECK (action IN ('selected', 'excluded', 'cleared')),
    reason text,
    actor text NOT NULL,
    at timestamptz NOT NULL DEFAULT now(),
    request_id uuid NOT NULL,
    detail jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX sector_decision_events_order ON planning_mtg.sector_decision_events (area, production_order_no, at);
CREATE UNIQUE INDEX sector_decision_events_request ON planning_mtg.sector_decision_events (request_id, production_order_no, reference);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mes_kanban_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON planning_mtg.sector_selection TO mes_kanban_app;
        GRANT SELECT, INSERT ON planning_mtg.sector_decision_events TO mes_kanban_app;
        GRANT USAGE ON SEQUENCE planning_mtg.sector_decision_events_id_seq TO mes_kanban_app;
    END IF;
END $$;
