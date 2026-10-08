-- Cenários e replaneamento (Etapa 5, ponto 8, 08/10/2026).
-- Um cenário é uma lista de alterações simuladas sobre o plano em uso (cancelar OF/OV/linha, máquina parada,
-- turnos, pessoas em falta, urgente, prazo). Simular não grava nada fora destas tabelas; «Aplicar» grava as
-- alterações reais nos sítios de sempre (calendários, exclusões da Carteira, substituições de prazo), numa só
-- transação, e guarda em applied_summary o que foi gravado (antes/depois) para o «Desfazer» por alteração.
-- As pessoas em falta nunca se aplicam (só simulação).
-- Sem resultados guardados: a comparação recalcula-se ao abrir.
-- plan_scenario_changes só acrescenta: retirar uma alteração marca removed_at/removed_by.
-- plan_scenario_requests: idempotência (o mesmo request_id com o mesmo conteúdo devolve o mesmo resultado).
-- Sem BEGIN/COMMIT: a transação é aberta por scripts/migrate.py.

CREATE TABLE planning_mtg.plan_scenarios (
    id uuid PRIMARY KEY,
    area text NOT NULL CHECK (area IN ('perfis', 'cantoneiras')),
    name text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 120),
    status text NOT NULL DEFAULT 'aberto' CHECK (status IN ('aberto', 'aplicado', 'arquivado')),
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    applied_at timestamptz,
    applied_by text,
    applied_summary jsonb,
    CONSTRAINT plan_scenarios_applied CHECK (status <> 'aplicado' OR (applied_at IS NOT NULL AND applied_by IS NOT NULL))
);
CREATE INDEX plan_scenarios_area ON planning_mtg.plan_scenarios (area, status, created_at DESC);

CREATE TABLE planning_mtg.plan_scenario_changes (
    id uuid PRIMARY KEY,
    scenario_id uuid NOT NULL REFERENCES planning_mtg.plan_scenarios(id),
    kind text NOT NULL CHECK (kind IN ('cancelar', 'maquina_parada', 'turnos', 'pessoas_em_falta', 'urgente', 'prazo')),
    target jsonb NOT NULL DEFAULT '{}'::jsonb,
    params jsonb NOT NULL DEFAULT '{}'::jsonb,
    reason text,
    position integer NOT NULL CHECK (position > 0),
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    removed_at timestamptz,
    removed_by text,
    CONSTRAINT plan_scenario_changes_removed CHECK ((removed_at IS NULL) = (removed_by IS NULL)),
    UNIQUE (scenario_id, position)
);

CREATE TABLE planning_mtg.plan_scenario_requests (
    request_id uuid PRIMARY KEY,
    area text NOT NULL CHECK (area IN ('perfis', 'cantoneiras')),
    scenario_id uuid,
    action text NOT NULL,
    content_hash text NOT NULL,
    actor text NOT NULL,
    at timestamptz NOT NULL DEFAULT now(),
    result jsonb NOT NULL DEFAULT '{}'::jsonb
);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mes_kanban_app') THEN
        GRANT SELECT, INSERT, UPDATE ON planning_mtg.plan_scenarios TO mes_kanban_app;
        GRANT SELECT, INSERT, UPDATE ON planning_mtg.plan_scenario_changes TO mes_kanban_app;
        GRANT SELECT, INSERT ON planning_mtg.plan_scenario_requests TO mes_kanban_app;
    END IF;
END $$;
