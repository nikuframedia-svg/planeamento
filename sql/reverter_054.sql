-- Reversão da migração 054 (cenários). Só em caso de retorno à versão anterior da aplicação.
-- ATENÇÃO: os cenários e as suas alterações perdem-se. O que um cenário já aplicou (turnos e paragens nos
-- calendários, exclusões na Carteira, prazos e urgentes nas substituições de prazo) fica gravado nesses sítios e
-- NÃO é desfeito por este script. Exportar antes, se for preciso:
--   \copy (SELECT * FROM planning_mtg.plan_scenarios) TO 'cenarios.csv' CSV HEADER
--   \copy (SELECT * FROM planning_mtg.plan_scenario_changes) TO 'cenarios_alteracoes.csv' CSV HEADER
BEGIN;
DROP TABLE planning_mtg.plan_scenario_requests;
DROP TABLE planning_mtg.plan_scenario_changes;
DROP TABLE planning_mtg.plan_scenarios;
DELETE FROM planning_mtg.schema_migrations WHERE version = '054';
COMMIT;
