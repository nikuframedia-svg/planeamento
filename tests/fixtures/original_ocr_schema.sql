-- Schema observed read-only in the real server SQLite on 2026-09-24.
-- No factory records are included.
CREATE TABLE sheets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    image_path TEXT NOT NULL,
    captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL DEFAULT 'pending',
    operador TEXT,
    sheet_data TEXT,
    raw_extraction TEXT,
    dq_audit TEXT,
    extracted_at TIMESTAMP,
    validated_at TIMESTAMP,
    error_message TEXT
, image_rotation INTEGER NOT NULL DEFAULT 0, shadow_scoring_json TEXT, shadow_scored_at TIMESTAMP, page_hint TEXT, capture_group TEXT, needs_review INTEGER NOT NULL DEFAULT 0, review_reason TEXT, unidade_id INTEGER REFERENCES unidades(id), shadow_triaged_at TIMESTAMP, shadow_triage_note TEXT, factory_csv_name TEXT, revision INTEGER NOT NULL DEFAULT 0, side_locked INTEGER NOT NULL DEFAULT 0);
CREATE TABLE production_rows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sheet_id INTEGER NOT NULL REFERENCES sheets(id) ON DELETE CASCADE,
    row_index INTEGER NOT NULL,
    -- denormalised from sheet header / footer
    operador TEXT,
    sheet_date TEXT,                  -- DD-MM-YYYY as captured (kept as text; query via substr/julianday)
    sheet_iso_date TEXT,              -- YYYY-MM-DD for SQL date() comparisons
    captured_at TIMESTAMP,
    validated_at TIMESTAMP,
    sheet_status TEXT,
    sheet_hours REAL,                 -- footer.horas_trabalhadas as decimal hours
    sheet_total_qty INTEGER,          -- sum(qtd) of the sheet (for ratios)
    -- row data
    pri TEXT,
    cliente TEXT,
    ov TEXT,
    of TEXT,
    modelo TEXT,
    qtd INTEGER,
    comp_mm INTEGER,
    larg_mm INTEGER,
    lote TEXT,
    coni TEXT,
    esp REAL,
    lbase INTEGER,
    ltopo INTEGER, m2 REAL, nesting TEXT, qtd_metros REAL, cesta_n TEXT, inicio TEXT, fim TEXT, dbase INTEGER, dtopo INTEGER, sucata INTEGER, fecho TEXT, human_fields TEXT,
    UNIQUE (sheet_id, row_index)
);
