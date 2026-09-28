"""Refresh current estimates on closed pieces without adding them to active load."""
from . import productivity

FIELDS=('hours_pct','theoretical_hours','rate_source','applied_rate_value','applied_rate_unit','speed_m_h',
        'planning_remaining','planning_balance_origin','planning_balance_provisional')


def patch(row):
    calculation=row.get('calculation',{})
    return {'values':{k:row['values'][k] for k in FIELDS if k in row['values']},
        'search_text':' '.join(str(v) for v in row['values'].values() if v is not None).casefold(),
        'rules':{k:calculation['rules'][k] for k in ('hours_pct','theoretical_hours') if k in calculation.get('rules',{})},
        'operation_estimates':calculation.get('operation_estimates',[]),
        'original':{k:v for k,v in row.get('original',{}).items() if k in ('speed_m_h','theoretical_hours')}}


def recalculate(conn,area,rows,configs,context,source,today):
    if not rows:return {}
    # apply_rows replaces estimate lists/rules and scalar values. Snapshot only
    # those fields; copying immutable source data recursively wastes time and
    # sends unrelated original fields back to PostgreSQL.
    before={r['key']:patch(r) for r in rows}
    productivity.apply_rows(conn,area,rows,configs,persist=False,context=context,source=source,today=today)
    result={}
    for row in rows:
        current=patch(row)
        if current!=before[row['key']]:result[row['key']]=current
    return result
