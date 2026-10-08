-- Edição manual do Gantt simples (Etapa 4, 08/10/2026): ajustes («âncoras») feitos no Gantt.
-- Um ajuste = setor + OF + máquina + dia (e hora opcional). Abrange todo o trabalho Planeado aberto da OF nessa
-- máquina, que a previsão (forecast.py → dispatch.py) põe seguido a partir desse dia ou dessa hora.
-- Um só estado: ativo. Acaba quando é retirado ou desfeito, quando outro ajuste da mesma OF e máquina o substitui,
-- ou quando a OF deixa de ter trabalho Planeado nessa máquina (a aplicação deduz isto na leitura e grava-o na
-- gravação seguinte, com o motivo). O cálculo automático nunca apaga um ajuste.
-- previous_machine: quando o ajuste mudou a OF de máquina, a escolha da Carteira que existia antes em cada linha e a
-- revisão gravada pelo ajuste, para o Desfazer só repor a máquina se a escolha atual ainda for a do ajuste.
-- O Excel nunca muda (a Data Corte e a Tabela ficam como estão).
-- sector_plan_adjustment_events só acrescenta (um evento por ação; o mesmo request_id e ação não se repetem).
-- Sem BEGIN/COMMIT: a transação é aberta por scripts/migrate.py.

CREATE TABLE planning_mtg.sector_plan_adjustments (
    id uuid PRIMARY KEY,
    area text NOT NULL CHECK (area IN ('perfis', 'cantoneiras')),
    production_order_no text NOT NULL CHECK (production_order_no <> ''),
    resource_id text NOT NULL CHECK (resource_id <> ''),
    machine_name text NOT NULL,
    day date NOT NULL,
    start_at timestamptz,
    active boolean NOT NULL DEFAULT true,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    ended_at timestamptz,
    ended_reason text,
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    previous_machine jsonb,
    request_id uuid NOT NULL,
    CONSTRAINT sector_plan_adjustments_ended CHECK (active = (ended_at IS NULL))
);
-- Um só ajuste ativo por setor, OF e máquina.
CREATE UNIQUE INDEX sector_plan_adjustments_active ON planning_mtg.sector_plan_adjustments (area, production_order_no, resource_id)
    WHERE active;
CREATE INDEX sector_plan_adjustments_area ON planning_mtg.sector_plan_adjustments (area, created_at);

CREATE TABLE planning_mtg.sector_plan_adjustment_events (
    id bigserial PRIMARY KEY,
    adjustment_id uuid NOT NULL REFERENCES planning_mtg.sector_plan_adjustments (id),
    area text NOT NULL CHECK (area IN ('perfis', 'cantoneiras')),
    action text NOT NULL CHECK (action IN ('mover', 'retirar', 'desfazer', 'substituir', 'terminar', 'repor')),
    actor text NOT NULL,
    at timestamptz NOT NULL DEFAULT now(),
    request_id uuid NOT NULL,
    detail jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX sector_plan_adjustment_events_area ON planning_mtg.sector_plan_adjustment_events (area, id);
-- O pedido do ecrã (request_id) com a ação pedida não se grava duas vezes. Os efeitos noutros ajustes do mesmo
-- pedido («substituir», «terminar», «repor») levam um request_id derivado do pedido e do ajuste afetado.
CREATE UNIQUE INDEX sector_plan_adjustment_events_request ON planning_mtg.sector_plan_adjustment_events (request_id, action);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mes_kanban_app') THEN
        GRANT SELECT, INSERT, UPDATE ON planning_mtg.sector_plan_adjustments TO mes_kanban_app;
        GRANT SELECT, INSERT ON planning_mtg.sector_plan_adjustment_events TO mes_kanban_app;
        GRANT USAGE ON SEQUENCE planning_mtg.sector_plan_adjustment_events_id_seq TO mes_kanban_app;
    END IF;
END $$;
