"""Read-only evidence: published Perfis versus recalculation with current code."""
from __future__ import annotations

from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT/'.env')
from app import planning, planning_population, planning_needs as needs
from app.raw import projection, query

with planning.connect(readonly=True) as conn:
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
    published = query.generation(conn,'perfis')
    base,args = query.source(published)
    before = {row['row_key']:{**row['detail'],'values':row['values_json']}
              for row in conn.execute('SELECT m.row_key,c.values_json,c.detail'+base+
                                      ' AND '+planning_population.active_sql(),args)}
    calculated,_,source_meta = projection.build_rows(conn,'perfis')
    after = {row['key']:row for row in calculated if planning_population.includes(row)}


def counts(rows):
    return {'active_lines':len(rows),
            'picking':sum(bool(row['values'].get('picking_week')) for row in rows.values()),
            'cut_dates':sum(bool(row['values'].get('cut_date')) for row in rows.values()),
            'picking_conflicts':sum(bool(row['values'].get('picking_conflict')) for row in rows.values()),
            'completed_cut':sum(any(source.get('operation')=='corte' and source.get('remaining')==0
                            for source in row.get('calculation',{}).get('production_sources',[])) for row in rows.values())}


recovered = [key for key,row in after.items() if row['values'].get('picking_week')
             and not before.get(key,{}).get('values',{}).get('picking_week')]
examples = []
for line in ('5589','5590'):
    match = next((row for row in after.values() if str(row.get('plan_key') or '').endswith(':'+line)
                  and row['values'].get('of')=='OF264774'),None)
    if match:
        examples.append({'plan_key':match['plan_key'], 'of':match['values']['of'],
                         'quantity_required':match['values'].get('quantity_required'),
                         'operations':[{k:source.get(k) for k in ('operation','value','remaining','excess','origin')}
                                       for source in match.get('calculation',{}).get('production_sources',[])]})

report={'published_generation':str(published['id']), 'source_snapshot':source_meta['snapshot']['snapshot_id'],
        'before':counts(before),'after_current_code':counts(after),
        'newly_recovered_picking_lines':len(recovered),
        'newly_recovered_keys':recovered,'kanban_examples':examples,
        'method':'Uma transação PostgreSQL REPEATABLE READ e só de leitura; nenhuma geração foi publicada.'}
out=ROOT/'docs/gantt-2026-09-24/reconciliation-before-after.json'
out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps(needs.serial(report),ensure_ascii=False,sort_keys=True,indent=2)+'\n')
print(json.dumps({key:report[key] for key in ('before','after_current_code','newly_recovered_picking_lines')},ensure_ascii=False))
