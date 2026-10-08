-- Reversão da migração 053 (edição manual do Gantt). Só em caso de retorno à versão anterior da aplicação.
-- ATENÇÃO: os ajustes feitos no Gantt e o seu histórico perdem-se; a previsão volta ao cálculo automático.
-- As máquinas que o Gantt gravou na Carteira (sector_member_machine, origem «gantt») ficam como estão.
-- Exportar antes:
--   \copy (SELECT * FROM planning_mtg.sector_plan_adjustments) TO 'ajustes.csv' CSV HEADER
--   \copy (SELECT * FROM planning_mtg.sector_plan_adjustment_events) TO 'ajustes_eventos.csv' CSV HEADER
BEGIN;
DROP TABLE planning_mtg.sector_plan_adjustment_events;
DROP TABLE planning_mtg.sector_plan_adjustments;
DELETE FROM planning_mtg.schema_migrations WHERE version = '053';
COMMIT;
