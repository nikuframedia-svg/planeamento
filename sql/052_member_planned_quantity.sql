-- Planear parte de uma OF (Etapa 3, P5, 08/10/2026).
-- planned_quantity: peças planeadas da linha (operação principal). NULL = a linha inteira, como até aqui.
-- made_at_plan: produção já feita na linha (QTD − saldo) no momento de planear. A produção registada depois
-- consome primeiro a parte planeada (decisions.planned_open); quando a parte chega a 0, a linha volta a
-- «Planeado para nesting» pelo resto, sem gravar nada.
-- Só uma decisão 'selected' pode ter quantidade. Os eventos guardam planned_quantity e made_at_plan em detail,
-- sem colunas novas. Nenhum dado existente muda: as decisões atuais ficam com NULL (linha inteira).
-- Sem BEGIN/COMMIT: a transação é aberta por scripts/migrate.py.

ALTER TABLE planning_mtg.sector_member_selection
    ADD COLUMN planned_quantity integer CHECK (planned_quantity IS NULL OR planned_quantity > 0),
    ADD COLUMN made_at_plan numeric CHECK (made_at_plan IS NULL OR made_at_plan >= 0),
    ADD CONSTRAINT sector_member_selection_partial
        CHECK ((planned_quantity IS NULL AND made_at_plan IS NULL) OR (decision = 'selected' AND planned_quantity IS NOT NULL));

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mes_kanban_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON planning_mtg.sector_member_selection TO mes_kanban_app;
    END IF;
END $$;
