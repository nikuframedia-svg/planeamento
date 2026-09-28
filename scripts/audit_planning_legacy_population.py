"""Read-only independent audit of imported-order scopes on the full test clone."""
import hashlib
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

folder = Path('docs/validacao-planeamento-integral/20260923-execucao')
os.environ['MES_PG_DSN'] = json.loads(Path(
    '/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
from app import planning, planning_hub
from scripts.audit_planning_selected_ocr import source_fingerprints

report = {'at': datetime.now(timezone.utc).isoformat(), 'environment': 'planning_integral clone',
          'scope': 'CPIS orders and imported macro lines in legacy hub; local-only needs are not covered',
          'method': 'Independent raw SQL inputs and explicit state matrix; no shared closure classifier',
          'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'scopes': {}}
with planning.connect(readonly=True) as conn:
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
    assert conn.execute('SELECT current_database() n').fetchone()['n'] == 'planning_integral'
    report['source_fingerprints_before'] = source_fingerprints(conn)
    snaps = conn.execute('''SELECT DISTINCT ON(dataset_id) snapshot_id,dataset_id
        FROM audit_mtg.snapshots WHERE dataset_id IN ('ds-met2-perfis','ds-2638099daddc474e')
        ORDER BY dataset_id,loaded_at DESC,snapshot_id DESC''').fetchall()
    areas = {r['snapshot_id']: 'perfis' if r['dataset_id'] == 'ds-met2-perfis' else 'cantoneiras' for r in snaps}
    direct = conn.execute('SELECT id FROM cpis_mtg.versions ORDER BY last_confirmed_at DESC LIMIT 1').fetchone()
    if direct:
        cpis = conn.execute('SELECT production_order_no,status FROM cpis_mtg.orders WHERE version_id=%s', (direct['id'],)).fetchall()
    else:
        cpis = conn.execute('SELECT production_order_no,status FROM raw_mtg.cpis_rows WHERE snapshot_id=ANY(%s)', (list(areas),)).fetchall()
    closed_orders = {}
    for r in cpis:
        if r['production_order_no'] is not None:
            of = r['production_order_no']
            closed_orders[of] = closed_orders.get(of, False) or str(r['status'] or '').strip().lower() in ('fechada', 'fechado')
    lines = conn.execute('''SELECT r.production_order_no,r.snapshot_id,r.source_line_id,r.closed_x,
        r.row_data->>'Fechado' closed FROM raw_mtg.plan_production_rows r
        JOIN analytics_mtg.kanban_plan_lines p ON p.snapshot_id=r.snapshot_id AND p.plan_key=r.source_line_id
        WHERE r.snapshot_id=ANY(%s)''', (list(areas),)).fetchall()
    counts = defaultdict(lambda: {'active': defaultdict(int), 'history': defaultdict(int), 'all': defaultdict(int)})
    for r in lines:
        of, area = r['production_order_no'], areas[r['snapshot_id']]
        closed = closed_orders.get(of, False) or r['closed_x'] is True or str(r['closed'] or '').strip().lower() in ('x', 'true', '1')
        counts[of]['history' if closed else 'active'][area] += 1
        counts[of]['all'][area] += 1
    report['imported_lines'] = len(lines)
    report['cpis_orders'] = len(closed_orders)
    missing = {of: dict(value['all']) for of, value in counts.items() if of not in closed_orders}
    report['outside_hub_cpis_scope'] = {
        'orders': len(missing), 'lines': sum(sum(value.values()) for value in missing.values()),
        'reason': 'Imported OF absent from current CPIS; separate from local-only needs. Follow-up required for full C06.',
        'examples': sorted(str(of) for of in missing)[:10]}
for scope in ('active', 'history', 'all'):
    expected = {of: dict(counts[of][scope]) for of, closed in closed_orders.items()
                if scope == 'all' or (bool(counts[of][scope]) if counts[of]['all'] else closed == (scope == 'history'))}
    result = planning_hub._order_population(population=scope)
    version = result['version']
    observed = {row['of']: row['plan'] for row in result['orders']}
    assert len(observed) == len(result['orders']), (scope, 'duplicate OF')
    assert observed == expected, (scope, 'population or line-count mismatch')
    pages = (len(observed) + 99) // 100
    checked_pages = sorted({1, max(1, pages // 2), max(1, pages), pages + 1})
    for page in checked_pages:
        paged = planning_hub.list_orders(population=scope, page=page, page_size=100, version=version)
        assert paged['total'] == len(expected) and paged['pages'] == pages
        assert paged['orders'] == result['orders'][(page - 1) * 100:page * 100]
    report['scopes'][scope] = {'orders': len(observed), 'pages': pages, 'endpoint_pages_checked': checked_pages, 'version': version,
        'lines': sum(sum(counts.values()) for counts in observed.values()),
        'sha256': hashlib.sha256(json.dumps(observed, sort_keys=True).encode()).hexdigest()}
    print(json.dumps({'scope': scope, **report['scopes'][scope]}), flush=True)
with planning.connect(readonly=True) as conn:
    report['source_fingerprints_after'] = source_fingerprints(conn)
assert report['source_fingerprints_before'] == report['source_fingerprints_after']
report['result'] = 'passed_in_stated_scope'
(folder/'c06-legacy-audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'result': report['result'], 'scopes': report['scopes']}))
