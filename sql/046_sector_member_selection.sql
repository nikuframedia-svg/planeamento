-- Seleção exata por membro na Carteira (plano de 02/10/2026, docs/plano-carteira-perfis-2026-10-02).
-- Um membro é uma linha técnica da carteira (row_key da projeção). A chave muda a cada importação do
-- Excel; a aplicação reencontra o membro pelos selection_aliases que a projeção já conserva para
-- identidades físicas únicas. Sem correspondência inequívoca, a decisão fica por rever e não passa
-- para outra linha.
-- Precedência: decisão do membro → (OF, referência) → (OF, '*'). 'cleared' é uma desmarcação explícita
-- que vence uma decisão herdada da OF ou da referência.
-- A fase (nesting/produção) faz parte da decisão Planear; não há um envio separado.
-- Nenhuma tabela existente perde dados; sector_selection continua a ser lida como legado.
-- Sem BEGIN/COMMIT: a transação é aberta por scripts/migrate.py.

CREATE TABLE planning_mtg.sector_member_selection (
    area text NOT NULL CHECK (area IN ('perfis', 'cantoneiras')),
    member_key text NOT NULL CHECK (member_key <> ''),
    production_order_no text NOT NULL,
    reference text NOT NULL,
    decision text NOT NULL CHECK (decision IN ('selected', 'excluded', 'cleared')),
    phase text CHECK (phase IN ('nesting', 'producao')),
    reason text,
    actor text NOT NULL,
    decided_at timestamptz NOT NULL DEFAULT now(),
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    request_id uuid NOT NULL,
    seen jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (area, member_key),
    CONSTRAINT sector_member_selection_phase CHECK ((decision = 'selected') = (phase IS NOT NULL)),
    CONSTRAINT sector_member_selection_exclusion_reason CHECK (decision <> 'excluded' OR length(btrim(coalesce(reason, ''))) > 0)
);
CREATE INDEX sector_member_selection_order ON planning_mtg.sector_member_selection (area, production_order_no);

-- Um pedido (request_id) por ação confirmada: repetir o mesmo conteúdo devolve o resultado gravado;
-- o mesmo identificador com outro conteúdo é recusado.
CREATE TABLE planning_mtg.sector_selection_requests (
    request_id uuid PRIMARY KEY,
    area text NOT NULL CHECK (area IN ('perfis', 'cantoneiras')),
    action text NOT NULL CHECK (action IN ('selected', 'excluded', 'cleared')),
    content_hash text NOT NULL,
    actor text NOT NULL,
    at timestamptz NOT NULL DEFAULT now(),
    result jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- Os eventos passam a identificar o membro e a fase; os eventos antigos ficam como estão.
ALTER TABLE planning_mtg.sector_decision_events ADD COLUMN member_key text;
ALTER TABLE planning_mtg.sector_decision_events ADD COLUMN phase text CHECK (phase IN ('nesting', 'producao'));
ALTER TABLE planning_mtg.sector_decision_events DROP CONSTRAINT sector_decision_events_kind_check;
ALTER TABLE planning_mtg.sector_decision_events ADD CONSTRAINT sector_decision_events_kind_check
    CHECK (kind IN ('selection', 'member'));
DROP INDEX planning_mtg.sector_decision_events_request;
CREATE UNIQUE INDEX sector_decision_events_request
    ON planning_mtg.sector_decision_events (request_id, production_order_no, reference, coalesce(member_key, ''));
CREATE INDEX sector_decision_events_member ON planning_mtg.sector_decision_events (area, member_key, at)
    WHERE member_key IS NOT NULL;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mes_kanban_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON planning_mtg.sector_member_selection TO mes_kanban_app;
        GRANT SELECT, INSERT ON planning_mtg.sector_selection_requests TO mes_kanban_app;
    END IF;
END $$;
