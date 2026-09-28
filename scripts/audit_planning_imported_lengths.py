"""Trace grouped Cantoneiras lengths from original cells to form and RAW."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

FOLDER = Path('docs/validacao-planeamento-integral/20260923-execucao')


def expected_length(text):
    # Independently parse the Portuguese thousands grouping, without calling
    # the application's numeric reader to obtain the expected result.
    if text is None:
        return None
    parts = str(text).strip().replace('\u00a0', ' ').replace('\u202f', ' ').split(' ')
    if not parts or not re.fullmatch(r'\d{1,3}', parts[0]):
        return None
    if len(parts) < 2 or not all(re.fullmatch(r'\d{3}', part) for part in parts[1:]):
        return None
    return sum(int(part) * 1000 ** i for i, part in enumerate(reversed(parts)))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', required=True)
    p.add_argument('--baseline')
    args = p.parse_args()
    assert re.fullmatch('[a-z0-9-]+', args.output)
    os.environ['MES_PG_DSN'] = json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
    from app import planning, planning_needs
    from app.raw import query
    out = {'at': datetime.now(timezone.utc).isoformat(), 'environment': 'planning_integral readonly',
           'method': 'Independent groups of three from original Comp. when legacy length_mm is NULL; source strings unchanged.',
           'rows': [], 'failures': []}
    with planning.connect(readonly=True) as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        assert c.execute('SELECT current_database() n').fetchone()['n'] == 'planning_integral'
        gen = query.generation(c, 'cantoneiras')
        snapshot = gen['metadata']['snapshot']['snapshot_id']
        source = c.execute("SELECT source_line_id,excel_row,length_mm,row_data->>'Comp.' original FROM raw_mtg.plan_production_rows WHERE snapshot_id=%s ORDER BY excel_row", (snapshot,)).fetchall()
        out.update(version=gen['id'], snapshot=snapshot, source_count=len(source),
                   source_lengths_sha256=hashlib.sha256(json.dumps(source,sort_keys=True,default=str).encode()).hexdigest())
        if args.baseline:
            baseline = json.loads((FOLDER / args.baseline).read_text())
            assert out['source_lengths_sha256'] == baseline['source_lengths_sha256']
            out['unchanged_against'] = args.baseline
        base, params = query.source(gen)
        published = {r['plan_key']:r for r in c.execute("SELECT m.row_key,c.values_json,c.detail->>'plan_key' plan_key,c.detail->>'need_id' need_id"+base,params)}
        for row in source:
            if row['length_mm'] is not None:
                continue
            expected = expected_length(row['original'])
            actual = published[row['source_line_id']]
            v = actual['values_json']
            item = {'key': actual['row_key'], 'of': v['of'], 'reference': v['component_ref'],
                    'excel_row':row['excel_row'], 'cell':f"R{row['excel_row']}", 'original':row['original'],
                    'expected_length':expected, 'observed_length':v['length_mm'],
                    'quantity':v['quantity_required'], 'total_length':v['total_length'],
                    'remaining':v['remaining'], 'remaining_m':v['remaining_m'],
                    'active':v['planning_active'], 'need_id':actual['need_id']}
            manual = planning_needs.source_data({'kind':'plan_line','id':row['source_line_id']}, 'cantoneiras', c)
            item['manual_source_length'] = manual['values']['length_mm']
            if item['manual_source_length'] != expected:
                out['failures'].append({**item, 'failure':'manual source differs'})
            if actual['need_id']:
                item['scope']='local override; source parity deferred'
            elif v['length_mm'] != expected:
                out['failures'].append(item)
            out['rows'].append(item)
    out['result']='passed_in_stated_scope' if not out['failures'] else 'failed'
    (FOLDER/(args.output+'.json')).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
    print(len(out['rows']), 'legacy NULL lengths;', sum(r['expected_length'] is not None for r in out['rows']), 'recoverable;', len(out['failures']), 'failures',flush=True)
    if out['failures']:
        raise SystemExit(1)


if __name__=='__main__':
    main()
