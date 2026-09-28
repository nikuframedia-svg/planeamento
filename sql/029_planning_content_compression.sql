-- Planning projections retain complete immutable source/derived versions.
-- Use the PostgreSQL 16 LZ4 compressor for future large JSON values: rewriting
-- thousands of estimates should not repeatedly pay pglz compression costs.
-- Existing rows, hashes and versions remain unchanged. Reversible with pglz.
ALTER TABLE planning_mtg.raw_contents ALTER COLUMN detail SET COMPRESSION lz4;
ALTER TABLE planning_mtg.raw_contents ALTER COLUMN values_json SET COMPRESSION lz4;
