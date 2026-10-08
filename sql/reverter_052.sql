-- Reversão da migração 052 (quantidade parcial no Planear). Só em caso de retorno à versão anterior da aplicação.
-- ATENÇÃO: as linhas planeadas em parte passam a planeadas inteiras (a quantidade perde-se). Exportar antes:
--   \copy (SELECT * FROM planning_mtg.sector_member_selection WHERE planned_quantity IS NOT NULL) TO 'parciais.csv' CSV HEADER
-- Os eventos (sector_decision_events.detail) guardam a quantidade e ficam como estão.
BEGIN;
ALTER TABLE planning_mtg.sector_member_selection DROP CONSTRAINT sector_member_selection_partial;
ALTER TABLE planning_mtg.sector_member_selection DROP COLUMN made_at_plan;
ALTER TABLE planning_mtg.sector_member_selection DROP COLUMN planned_quantity;
DELETE FROM planning_mtg.schema_migrations WHERE version = '052';
COMMIT;
