-- Índices de suporte à limpeza do histórico RAW (06/10/2026, scripts/raw_retention.py).
-- raw_member_content_hash e raw_content_detail_source servem as chaves estrangeiras
-- raw_members.content_hash e raw_contents.detail_source_hash: sem eles, cada conteúdo
-- apagado obriga a percorrer as tabelas inteiras.
--
-- Em produção as tabelas são grandes (milhões de linhas): os índices são criados ANTES,
-- sem bloquear gravações, com
--     python scripts/raw_retention.py --create-indexes --dsn <dono das tabelas>
-- e esta migração só os regista (não toma nenhum lock nas tabelas se já existirem e
-- forem válidos). Numa tabela grande sem índice recusa construí-lo aqui (um CREATE INDEX
-- normal bloquearia as gravações durante minutos). Numa base nova ou de testes cria-os.
-- Sem BEGIN/COMMIT: a transação é aberta por scripts/migrate.py.

DO $$
DECLARE
    spec record;
    valid boolean;
    big boolean;
BEGIN
    FOR spec IN
        SELECT * FROM (VALUES
            ('raw_member_content_hash', 'planning_mtg.raw_members',
             'CREATE INDEX raw_member_content_hash ON planning_mtg.raw_members(content_hash)'),
            ('raw_content_detail_source', 'planning_mtg.raw_contents',
             'CREATE INDEX raw_content_detail_source ON planning_mtg.raw_contents(detail_source_hash) '
             'WHERE detail_source_hash IS NOT NULL')
        ) AS v(name, tbl, ddl)
    LOOP
        SELECT i.indisvalid AND i.indisready INTO valid
        FROM pg_class x JOIN pg_index i ON i.indexrelid = x.oid
        WHERE x.relnamespace = 'planning_mtg'::regnamespace AND x.relname = spec.name;
        IF FOUND THEN
            IF NOT valid THEN
                RAISE EXCEPTION 'Índice planning_mtg.% inválido (criação interrompida). Apaga-o com DROP INDEX CONCURRENTLY planning_mtg.%; e corre python scripts/raw_retention.py --create-indexes.',
                    spec.name, spec.name;
            END IF;
            CONTINUE;
        END IF;
        SELECT x.reltuples > 100000 OR pg_relation_size(x.oid) > 64 * 1024 * 1024 INTO big
        FROM pg_class x WHERE x.oid = spec.tbl::regclass;
        IF big THEN
            RAISE EXCEPTION 'Falta o índice planning_mtg.% numa tabela grande (%). Cria primeiro com python scripts/raw_retention.py --create-indexes e repete a migração.',
                spec.name, spec.tbl;
        END IF;
        EXECUTE spec.ddl;
    END LOOP;
END $$;
