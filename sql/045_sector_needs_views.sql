-- Vistas por família, prioridade por setor, conjuntos de referências, máquina por grupo e quotas
-- de recursos partilhados (plano de 01/10/2026). Tudo aditivo: nenhuma tabela existente muda.
-- As decisões ficam na aplicação; a base de pesquisa recebe-as pelo espelho (research_sync).
-- Sem BEGIN/COMMIT: a transação é aberta por scripts/migrate.py.

-- Política de prioridade por setor. Sem linha, vale a política por defeito do código.
CREATE TABLE planning_mtg.sector_priority_policies (
    area text PRIMARY KEY CHECK (area IN ('perfis', 'cantoneiras')),
    definition jsonb NOT NULL,
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    reason text NOT NULL CHECK (length(btrim(reason)) > 0),
    actor text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Substituição do prazo de uma OF inteira (reference = '*') ou de uma OF × referência.
-- A chave inclui o setor: a mesma OF noutro setor não herda a decisão.
CREATE TABLE planning_mtg.sector_priority_overrides (
    area text NOT NULL CHECK (area IN ('perfis', 'cantoneiras')),
    production_order_no text NOT NULL CHECK (production_order_no <> ''),
    reference text NOT NULL DEFAULT '*' CHECK (reference <> ''),
    id uuid NOT NULL UNIQUE,
    definition jsonb NOT NULL,
    reason text NOT NULL CHECK (length(btrim(reason)) > 0),
    actor text NOT NULL,
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (area, production_order_no, reference)
);

-- Conjuntos de referências: congelados (lista por revisão) ou dinâmicos (filtro guardado).
CREATE TABLE planning_mtg.sector_reference_sets (
    id uuid PRIMARY KEY,
    area text NOT NULL CHECK (area IN ('perfis', 'cantoneiras')),
    name text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 160),
    mode text NOT NULL CHECK (mode IN ('frozen', 'dynamic')),
    selector jsonb NOT NULL DEFAULT '{}'::jsonb,
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    archived boolean NOT NULL DEFAULT false,
    actor text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
-- Uma lista por revisão; a referência literal é a identidade (sem fundir grafias).
CREATE TABLE planning_mtg.sector_reference_set_members (
    set_id uuid NOT NULL REFERENCES planning_mtg.sector_reference_sets(id),
    revision integer NOT NULL CHECK (revision > 0),
    area text NOT NULL CHECK (area IN ('perfis', 'cantoneiras')),
    sku_literal text NOT NULL CHECK (sku_literal <> ''),
    PRIMARY KEY (set_id, revision, area, sku_literal)
);

-- Ações de máquina em grupo: um identificador comum para todas as decisões gravadas juntas.
CREATE TABLE planning_mtg.sector_machine_actions (
    id uuid PRIMARY KEY,
    request_id uuid NOT NULL UNIQUE,
    area text NOT NULL CHECK (area IN ('perfis', 'cantoneiras')),
    mode text NOT NULL CHECK (mode IN ('assign', 'prefer', 'automatic', 'future_preference', 'accept_suggestions', 'assign_each', 'undo')),
    resource_id text,
    reason text,
    actor text NOT NULL,
    scope jsonb NOT NULL,
    versions jsonb NOT NULL,
    summary jsonb NOT NULL,
    undoes uuid REFERENCES planning_mtg.sector_machine_actions(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT sector_machine_actions_reason CHECK (mode IN ('automatic', 'undo') OR length(btrim(coalesce(reason, ''))) > 0)
);

-- Decisão atual por ocorrência de operação (OF × referência × operação × ocorrência).
-- A assinatura técnica impede transferir a decisão para outra variante da peça.
CREATE TABLE planning_mtg.sector_machine_decisions (
    area text NOT NULL CHECK (area IN ('perfis', 'cantoneiras')),
    occurrence_key text NOT NULL,
    production_order_no text NOT NULL,
    reference text NOT NULL,
    operation_code text NOT NULL,
    occurrence integer NOT NULL CHECK (occurrence > 0),
    technical_signature text NOT NULL,
    mode text NOT NULL CHECK (mode IN ('assign', 'prefer')),
    resource_id text NOT NULL,
    reason text NOT NULL CHECK (length(btrim(reason)) > 0),
    -- Especificidade da ação que gravou: uma ação de família não substitui uma decisão mais específica.
    scope_level integer NOT NULL CHECK (scope_level BETWEEN 1 AND 9),
    action_id uuid NOT NULL REFERENCES planning_mtg.sector_machine_actions(id),
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    actor text NOT NULL,
    decided_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (area, occurrence_key)
);
CREATE INDEX sector_machine_decisions_order ON planning_mtg.sector_machine_decisions (area, production_order_no);

-- Histórico só de acrescentar: valor anterior e posterior de cada ocorrência por ação.
CREATE TABLE planning_mtg.sector_machine_decision_history (
    id bigserial PRIMARY KEY,
    action_id uuid NOT NULL REFERENCES planning_mtg.sector_machine_actions(id),
    area text NOT NULL,
    occurrence_key text NOT NULL,
    before jsonb,
    after jsonb,
    at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (action_id, area, occurrence_key)
);

-- Preferência para trabalho futuro: guarda o seletor e a vigência, não os membros.
CREATE TABLE planning_mtg.sector_machine_preferences (
    id uuid PRIMARY KEY,
    area text NOT NULL CHECK (area IN ('perfis', 'cantoneiras')),
    selector jsonb NOT NULL,
    specificity integer NOT NULL CHECK (specificity BETWEEN 1 AND 9),
    resource_id text NOT NULL,
    valid_from date,
    valid_until date,
    reason text NOT NULL CHECK (length(btrim(reason)) > 0),
    action_id uuid NOT NULL REFERENCES planning_mtg.sector_machine_actions(id),
    archived boolean NOT NULL DEFAULT false,
    actor text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (valid_until IS NULL OR valid_from IS NULL OR valid_until >= valid_from)
);

-- Quota de um recurso físico partilhado por setor. A soma das quotas em vigor não passa de 1
-- (verificado na aplicação, sob bloqueio, na mesma transação que grava).
CREATE TABLE planning_mtg.sector_capacity_quotas (
    resource_id text NOT NULL,
    area text NOT NULL CHECK (area IN ('perfis', 'cantoneiras', 'reserva')),
    valid_from date NOT NULL,
    valid_until date,
    share numeric NOT NULL CHECK (share >= 0 AND share <= 1),
    reason text NOT NULL CHECK (length(btrim(reason)) > 0),
    actor text NOT NULL,
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (resource_id, area, valid_from),
    CHECK (valid_until IS NULL OR valid_until >= valid_from)
);

-- Auditoria comum das configurações acima: quem, quando, motivo, antes e depois.
CREATE TABLE planning_mtg.sector_config_events (
    id bigserial PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('priority_policy', 'priority_override', 'reference_set', 'capacity_quota')),
    area text NOT NULL,
    subject text NOT NULL,
    action text NOT NULL,
    before jsonb,
    after jsonb,
    reason text,
    actor text NOT NULL,
    request_id uuid NOT NULL,
    at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (request_id, kind, subject)
);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mes_kanban_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON planning_mtg.sector_priority_policies,
            planning_mtg.sector_priority_overrides, planning_mtg.sector_machine_decisions,
            planning_mtg.sector_capacity_quotas TO mes_kanban_app;
        GRANT SELECT, INSERT, UPDATE ON planning_mtg.sector_reference_sets,
            planning_mtg.sector_machine_preferences TO mes_kanban_app;
        GRANT SELECT, INSERT ON planning_mtg.sector_reference_set_members, planning_mtg.sector_machine_actions,
            planning_mtg.sector_machine_decision_history, planning_mtg.sector_config_events TO mes_kanban_app;
        GRANT USAGE ON SEQUENCE planning_mtg.sector_machine_decision_history_id_seq,
            planning_mtg.sector_config_events_id_seq TO mes_kanban_app;
    END IF;
END $$;
