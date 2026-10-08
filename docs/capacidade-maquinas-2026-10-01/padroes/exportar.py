"""Passo 1 (ambiente da aplicação): exporta as linhas do Excel MTG3 e a cópia CPIS para esta pasta. Só leitura.
.venv/bin/python docs/capacidade-maquinas-2026-10-01/padroes/exportar.py"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]; sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv; load_dotenv(ROOT / '.env')
from app import planning
OUT = Path(__file__).resolve().parent
with planning.connect(readonly=True) as c:
    snap = planning.snapshot(c, 'cantoneiras')
    rows = c.execute('SELECT source_line_id,excel_row,row_data FROM raw_mtg.plan_production_rows WHERE snapshot_id=%s', (snap['snapshot_id'],)).fetchall()
    cpis = c.execute('SELECT production_order_no,status,work_type_description,record_date FROM raw_mtg.cpis_rows WHERE snapshot_id=%s', (snap['snapshot_id'],)).fetchall()
with (OUT / 'mtg3.jsonl').open('w') as f:
    for r in rows:
        f.write(json.dumps({'_line': r['source_line_id'], '_row': r['excel_row'], **r['row_data']}, default=str, ensure_ascii=False) + '\n')
(OUT / 'cpis.json').write_text(json.dumps(cpis, default=str))
(OUT / 'fonte.json').write_text(json.dumps({'snapshot': snap['snapshot_id'], 'loaded_at': str(snap['loaded_at']), 'linhas': len(rows)}))
print(len(rows), snap['snapshot_id'])
