-- Reversão da migração 046 (seleção por membro). Só em caso de retorno à versão anterior da aplicação.
-- ATENÇÃO: apaga as decisões por membro, os pedidos e os eventos 'member'. Exportar antes:
--   \copy planning_mtg.sector_member_selection TO 'membros.csv' CSV HEADER
--   \copy (SELECT * FROM planning_mtg.sector_decision_events WHERE kind='member') TO 'eventos.csv' CSV HEADER
-- As decisões antigas (sector_selection) não são tocadas.
BEGIN;
DELETE FROM planning_mtg.sector_decision_events WHERE kind = 'member';
DROP INDEX planning_mtg.sector_decision_events_member;
DROP INDEX planning_mtg.sector_decision_events_request;
CREATE UNIQUE INDEX sector_decision_events_request ON planning_mtg.sector_decision_events (request_id, production_order_no, reference);
ALTER TABLE planning_mtg.sector_decision_events DROP CONSTRAINT sector_decision_events_kind_check;
ALTER TABLE planning_mtg.sector_decision_events ADD CONSTRAINT sector_decision_events_kind_check CHECK (kind IN ('selection'));
ALTER TABLE planning_mtg.sector_decision_events DROP COLUMN phase;
ALTER TABLE planning_mtg.sector_decision_events DROP COLUMN member_key;
DROP TABLE planning_mtg.sector_selection_requests;
DROP TABLE planning_mtg.sector_member_selection;
DELETE FROM planning_mtg.schema_migrations WHERE version = '046';
COMMIT;
