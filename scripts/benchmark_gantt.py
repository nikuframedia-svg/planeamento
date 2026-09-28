"""Read-only, repeatable benchmark of the currently published Perfis generation.

Usage: uv run python scripts/benchmark_gantt.py
Never writes to PostgreSQL and never invents production calendars.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
import json
import resource
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / '.env')

from app import planning, planning_needs as needs
from app.gantt import inputs, baseline, solver, validation

OUT = ROOT / 'docs/gantt-2026-09-24'
OUT.mkdir(parents=True, exist_ok=True)
FROZEN = datetime(2026, 9, 24, 19, 0, tzinfo=timezone.utc)


def save(name, value):
    (OUT / name).write_text(json.dumps(needs.serial(value), ensure_ascii=False,
                                        sort_keys=True, indent=2) + '\n')


def capture():
    with planning.connect(readonly=True) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        return inputs.capture(conn, {}, FROZEN)


measurements = []
reference = None
for number in range(1, 6):
    started = time.perf_counter()
    snapshot = capture()
    captured = time.perf_counter()
    initial = baseline.build(snapshot)
    prepared = time.perf_counter()
    optimized, technical = solver.optimize(snapshot, initial)
    checked = validation.validate(snapshot, optimized)
    finished = time.perf_counter()
    assert checked['valid'], checked['errors']
    assert optimized['score'] <= initial['score']
    fingerprint = needs.digest(snapshot)
    if reference is None:
        reference = fingerprint
        save('input-snapshot.json', snapshot)
        save('initial-proposal.json', initial)
        save('optimized-proposal.json', optimized)
        save('validation-report.json', checked)
    assert fingerprint == reference, 'As fontes mudaram entre as medições.'
    measurements.append({'run': number, 'snapshot_digest': fingerprint,
                         'capture_seconds': round(captured-started, 4),
                         'initial_seconds': round(prepared-captured, 4),
                         'optimization_seconds': round(finished-prepared, 4),
                         'total_seconds': round(finished-started, 4),
                         'peak_rss_kb': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                         'operations': len(snapshot['operations']),
                         'scheduled': len(optimized['bars']),
                         'score': optimized['score'], 'solver': technical})

code_files = sorted([*ROOT.joinpath('app/gantt').glob('*.py'),
                     ROOT/'app/planning_dates.py', ROOT/'app/planning_estimates.py',
                     ROOT/'app/planning_calendars.py'])
code_hash = sha256(b''.join(path.read_bytes() for path in code_files)).hexdigest()
manifest = {'frozen_at': FROZEN.isoformat(), 'source_references': snapshot['source_references'],
            'snapshot_digest': reference, 'code_sha256': code_hash,
            'python_dependencies': {name: version(name) for name in ('ortools','psycopg','fastapi','pytest')},
            'code_files': [str(path.relative_to(ROOT)) for path in code_files],
            'calendar_limit': 'Sem horários confirmados, a medição não mede otimização de carga real.'}
save('manifest.json', manifest)
save('benchmark-five-runs.json', {'measurements': measurements,
    'median_total_seconds': statistics.median(x['total_seconds'] for x in measurements),
    'median_capture_seconds': statistics.median(x['capture_seconds'] for x in measurements)})
print(json.dumps({'operations':len(snapshot['operations']), 'scheduled':len(optimized['bars']),
                  'median_seconds':statistics.median(x['total_seconds'] for x in measurements),
                  'valid':checked['valid']}, ensure_ascii=False))
