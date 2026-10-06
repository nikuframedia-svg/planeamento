-- Conjuntos de famílias com máquina pré-definida e máquina escolhida na Carteira (05/10/2026).
-- Ordem da máquina efetiva de uma linha (operação principal): escolha da Carteira → coluna Máquina da
-- Tabela → conjunto de famílias SKU. Nada disto altera o Excel; tudo fica na aplicação, com histórico.
-- Sem BEGIN/COMMIT: a transação é aberta por scripts/migrate.py.

-- Um conjunto = grupo de famílias SKU criado pelo planeador, com uma máquina pré-definida.
-- Uma família só pode estar num conjunto ativo por setor (garantido pela aplicação).
CREATE TABLE planning_mtg.sector_family_sets (
    id uuid PRIMARY KEY,
    area text NOT NULL CHECK (area IN ('perfis', 'cantoneiras')),
    name text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 120),
    families text[] NOT NULL CHECK (cardinality(families) > 0),
    resource_id text NOT NULL,
    machine_name text NOT NULL,
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    archived boolean NOT NULL DEFAULT false,
    actor text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX sector_family_sets_name ON planning_mtg.sector_family_sets (area, lower(name)) WHERE NOT archived;

-- Máquina escolhida na Carteira para um membro (linha), reencontrada entre importações pelos aliases.
CREATE TABLE planning_mtg.sector_member_machine (
    area text NOT NULL CHECK (area IN ('perfis', 'cantoneiras')),
    member_key text NOT NULL CHECK (member_key <> ''),
    production_order_no text NOT NULL,
    reference text NOT NULL,
    resource_id text NOT NULL,
    machine_name text NOT NULL,
    actor text NOT NULL,
    decided_at timestamptz NOT NULL DEFAULT now(),
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    request_id uuid NOT NULL,
    seen jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (area, member_key)
);
CREATE INDEX sector_member_machine_order ON planning_mtg.sector_member_machine (area, production_order_no);

ALTER TABLE planning_mtg.sector_decision_events DROP CONSTRAINT sector_decision_events_kind_check;
ALTER TABLE planning_mtg.sector_decision_events ADD CONSTRAINT sector_decision_events_kind_check
    CHECK (kind IN ('selection', 'member', 'machine', 'family_set'));
ALTER TABLE planning_mtg.sector_decision_events DROP CONSTRAINT sector_decision_events_action_check;
ALTER TABLE planning_mtg.sector_decision_events ADD CONSTRAINT sector_decision_events_action_check
    CHECK (action IN ('selected', 'excluded', 'cleared', 'machine', 'machine_cleared', 'set_saved', 'set_archived'));
ALTER TABLE planning_mtg.sector_selection_requests DROP CONSTRAINT sector_selection_requests_action_check;
ALTER TABLE planning_mtg.sector_selection_requests ADD CONSTRAINT sector_selection_requests_action_check
    CHECK (action IN ('selected', 'excluded', 'cleared', 'machine', 'family_set'));

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mes_kanban_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON planning_mtg.sector_member_machine TO mes_kanban_app;
        GRANT SELECT, INSERT, UPDATE ON planning_mtg.sector_family_sets TO mes_kanban_app;
    END IF;
END $$;
