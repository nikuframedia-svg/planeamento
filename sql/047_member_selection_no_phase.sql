-- Sem fase nesting/produção na decisão Planear (pedido do Luís, 02/10/2026).
-- «Planeado para nesting» passa a ser calculado: a linha tem Máquina mas ainda não foi planeada.
-- Na altura desta migração não havia decisões por membro gravadas; a coluna phase não tinha dados.
-- Sem BEGIN/COMMIT: a transação é aberta por scripts/migrate.py.

ALTER TABLE planning_mtg.sector_member_selection DROP CONSTRAINT sector_member_selection_phase;
ALTER TABLE planning_mtg.sector_member_selection DROP COLUMN phase;
ALTER TABLE planning_mtg.sector_decision_events DROP COLUMN phase;
