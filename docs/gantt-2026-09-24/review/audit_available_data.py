"""Read-only reconciliation of existing source data and the Gantt input gates."""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / '.env')
from app import planning, planning_population, planning_estimates
from app.raw import query

with planning.connect(readonly=True) as conn:
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
    generation = query.generation(conn, 'perfis')
    capacity = query.generation(conn, 'perfis', dataset='capacity')
    base, args = query.source(generation)
    rows = conn.execute('SELECT m.row_key,c.values_json,c.detail' + base +
                        ' AND ' + planning_population.active_sql(), args).fetchall()
    snapshot = planning.snapshot(conn, 'perfis')['snapshot_id']
    configs = conn.execute("SELECT kind,definition FROM planning_mtg.raw_objects "
                           "WHERE NOT archived AND kind IN ('resource','calendar','rate')").fetchall()
    imported = conn.execute("SELECT excel_row,row_data FROM raw_mtg.other_sheet_rows "
        "WHERE snapshot_id=%s AND sheet_name='PlanDisponibilidadeSemanal' ORDER BY excel_row",
        (snapshot,)).fetchall()

totals = Counter()
machines = {}
mismatches = []
examples = []
for row in rows:
    values, detail = row['values_json'], row['detail']
    machine = values.get('machine')
    estimate = next((e for e in detail.get('calculation', {}).get('operation_estimates', [])
                     if e['operation'] == 'corte'), {})
    balance = planning_estimates.select_balance({**detail, 'values': values, 'area': 'perfis'}, 'corte')
    positive = isinstance(estimate.get('hours'), (int, float)) and estimate['hours'] > 0
    remaining = balance['planning_remaining']
    known_date = bool(values.get('cut_date'))
    counts = {
        'lines': True, 'machine_known': bool(machine), 'cut_date_known': known_date,
        'machine_and_cut_date': bool(machine) and known_date,
        'positive_duration': positive, 'picking_known': bool(values.get('picking_week')),
        'pending_machine_date_duration': bool(remaining and machine and known_date and positive),
    }
    for key, value in counts.items():
        totals[key] += bool(value)
    group = machines.setdefault(machine or '(sem máquina)', Counter())
    group['lines'] += 1
    group['positive_duration'] += positive
    if remaining != estimate.get('quantity'):
        mismatches.append({'key': row['row_key'], 'source_balance': remaining,
                           'estimate_quantity': estimate.get('quantity')})
    if positive and known_date and values['cut_date'] >= '2026-09-24' and len(examples) < 5:
        examples.append({'of': values.get('of'), 'line': values.get('id'), 'machine': machine,
                         'cut_date': values['cut_date'], 'remaining': remaining,
                         'hours': estimate['hours'], 'duration_origin': estimate.get('source')})

calendars = []
for row in imported:
    values = row['row_data'].get('values', [])
    if len(values) >= 8 and values[2] == 2026:
        calendars.append({'excel_row': row['excel_row'], 'year': values[2], 'week': values[1],
                          'machine': values[3], 'shifts': values[5],
                          'hours_per_shift': values[6], 'weekly_hours': values[7]})
result = {
    'checked_at': datetime.now(timezone.utc).isoformat(), 'database_writes': 0,
    'snapshot': snapshot, 'planning_generation': generation['id'], 'capacity_generation': capacity['id'],
    'capacity_contract': capacity['metadata'].get('contract'),
    'aggregates_pending': generation['metadata'].get('aggregates_pending'),
    'totals': totals, 'machines': machines,
    'local_configuration_counts': dict(Counter(item['kind'] for item in configs)),
    'availability_2026': calendars,
    'balance_estimate_mismatches': mismatches, 'future_examples': examples,
}
target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name('available-data.json')
target.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + '\n')
print(json.dumps({k: result[k] for k in ('planning_generation','capacity_contract',
      'aggregates_pending','totals','machines','future_examples')}, ensure_ascii=False, indent=2))
print('balance_estimate_mismatches:', len(mismatches))
