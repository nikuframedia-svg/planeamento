"""Lightweight source membership for administrative planning consumers.

Uses the same current-source resolution and identity grouping as RAW, without
rebuilding calculations, capacity or production evidence just to list orders.

`Source` holds what depends only on the imported macro files. An import never
changes in place (a new file is a new snapshot), so the hub can keep one
`Source` per set of snapshots; `assemble` adds the application's own data
(needs, records, links, local orders) on every call.
"""
from collections import defaultdict

from . import planning, planning_population as population
from .dossiers.models import order_number

_ROWS = '''SELECT r.snapshot_id,r.source_line_id,r.production_order_no,
    r.sales_order_no,r.customer_name,r.designation,r.component_ref,r.closed_x,
    r.row_data->'Fechado' closure,
    (p.closed_x IS TRUE AND p.remaining_valid IS TRUE AND p.remaining_quantity<=0
     AND (p.source_app='kanban-mes-mtg2' OR coalesce(r.row_data->>'2ª Oper.','') IN ('','0'))) complete
    FROM raw_mtg.plan_production_rows r LEFT JOIN analytics_mtg.kanban_plan_lines p
      ON p.snapshot_id=r.snapshot_id AND p.plan_key=r.source_line_id AND p.snapshot_id=ANY(%(snapshots)s)
    WHERE r.snapshot_id=ANY(%(snapshots)s)'''
# The snapshot filter is repeated on the view side on purpose: PostgreSQL does not carry
# r.snapshot_id=ANY(...) across the join, and without it the view is computed for every
# retained import (07/10/2026, production: 4.0 s and 1.7 GB read instead of 0.7 s).


def _line(area, row):
    """One macro line as its own planning identity (what it is unless a need claims it)."""
    return {'key':'macro:'+row['source_line_id'],'area':area,'of':order_number(row['production_order_no']),
            'need_id':None,'source_keys':[row['source_line_id']],'references':[row['component_ref']],
            'macro_closure_values':[row['closed_x'],row['closure']],'complete':row['complete'] is True}


def _group(area, key, lines, need):
    """One need with the macro lines it claims (each line given as its own identity, see _line)."""
    return {'key':key,'area':area,'of':need['production_order_no'] if need else lines[0]['of'],
            'need_id':key if need else None,
            'source_keys':[k for line in lines for k in line['source_keys']],
            'references':list(dict.fromkeys([need['component_ref']] if need else [r for line in lines for r in line['references']])),
            'macro_closure_values':[v for line in lines for v in line['macro_closure_values']],
            'complete':bool(lines) and not need and all(line['complete'] for line in lines)}


class Source:
    """The macro lines of one set of imported snapshots and what follows from them alone.

    Read-only once built: `singles` and `summaries` are shared by every request that uses
    this Source, so callers copy before changing them.
    """

    def __init__(self, snapshots, rows):
        from . import planning_hub as hub
        areas = {s['snapshot_id']: 'perfis' if dataset == 'ds-met2-perfis' else 'cantoneiras'
                 for dataset, s in snapshots.items()}
        self.singles = [_line(areas[r['snapshot_id']], r) for r in rows]
        copies = defaultdict(list)
        for row, single in zip(rows, self.singles):
            copies[single['of']].append({'production_order_no':single['of'],'sales_order_no':row['sales_order_no'],
                'customer_name':row['customer_name'],'observations':row['designation']})
        # Administrative context from the macro copies, per OF (insertion order = first line).
        self.summaries = {of: hub._order_summary(group) for of, group in copies.items()}

    @classmethod
    def load(cls, conn, snapshots, *, orders=None):
        sql, params = _ROWS, {'snapshots': [s['snapshot_id'] for s in snapshots.values()]}
        if orders is not None:
            sql += " AND regexp_replace(trim(r.production_order_no),'^OF[ ._-]*','','i')=ANY(%(orders)s)"
            params['orders'] = [of[2:] for of in orders]
        return cls(snapshots, conn.execute(sql + ' ORDER BY r.snapshot_id,r.excel_row,r.source_line_id', params).fetchall())


def read(conn, snapshots, *, orders=None):
    members, fallback, _ = assemble(conn, Source.load(conn, snapshots, orders=orders))
    return members, fallback


def assemble(conn, source):
    """Members and administrative context: the imported lines plus the application's needs.

    Returns (members, fallback, singles). `singles[i]` is the index of members[i] in
    source.singles when the member is that shared, unchanged line, otherwise None.
    """
    from . import planning_hub as hub, planning_needs as needs, planning_local_orders
    ns = {str(n['id']): n for n in conn.execute('SELECT * FROM planning_mtg.needs').fetchall()} if hub._table(conn,'planning_mtg','needs') else {}
    records = conn.execute('SELECT DISTINCT need_id,area FROM planning_mtg.records WHERE need_id IS NOT NULL').fetchall() if ns else []
    links = conn.execute("SELECT * FROM planning_mtg.need_sources WHERE kind='plan_line'").fetchall() if ns else []
    owners = defaultdict(set)
    for link in links:
        area = link['payload'].get('area','perfis')
        try:
            current = needs.source_data({'kind':'plan_line','id':link['source_id']},area,conn)
        except planning.PlanningError:
            continue
        owners[(area,current['id'])].add(str(link['need_id']))
    # Group order: a line on its own keeps its place; a need takes the place of its first line;
    # needs known only from records come last.
    sequence, groups = [], {}
    for index, line in enumerate(source.singles):
        candidates = owners.get((line['area'],line['source_keys'][0]), ())
        if len(candidates) != 1:
            sequence.append(index)
            continue
        group = (line['area'], next(iter(candidates)))
        if group not in groups:
            groups[group] = []
            sequence.append(group)
        groups[group].append(line)
    for record in records:
        group = (record['area'], str(record['need_id']))
        if group not in groups:
            groups[group] = []
            sequence.append(group)
    members, singles = [], []
    for item in sequence:
        if isinstance(item, int):
            members.append(source.singles[item])
            singles.append(item)
        else:
            area, key = item
            members.append(_group(area, key, groups[item], ns.get(key)))
            singles.append(None)
    local = {r['production_order_no']:r for r in conn.execute('SELECT * FROM planning_mtg.local_orders').fetchall()} if planning_local_orders.available(conn) else {}
    contexts = dict.fromkeys(source.summaries)
    for n in ns.values():
        contexts.setdefault(n['production_order_no'])
    for of in local:
        contexts.setdefault(of)
    fallback = {}
    imported_ofs = {m['of'] for m in members if m['source_keys']}
    for of in contexts:
        values = local.get(of,{}).get('values_json',{})
        if of in local or of not in source.summaries:
            summary = hub._order_summary([{'production_order_no':of,'sales_order_no':values.get('ov'),
                'customer_name':values.get('customer'),'observations':values.get('designation'),
                'delivery_date':values.get('delivery_date')}])
        else:
            summary = dict(source.summaries[of])
        summary.update(administrative_origin='Manual local' if of in local or of not in imported_ofs else 'Macro — sem contexto CPIS',
                       local_order=local.get(of))
        if of is None:
            from urllib.parse import urlencode
            summary.update(administrative_origin='Macro — OF por identificar',unidentified=True,
                raw_links=[{'key':m['key'],'area':m['area'],'reference':', '.join(str(r) for r in m['references'] if r),
                    'href':'/planeamento/raw?'+urlencode({'area':m['area'],'q':next(iter(m['references']),'') or ''})}
                    for m in members if m['of'] is None])
        fallback[of] = summary
    return members, fallback, singles


def tally(result, member, closure):
    """Add one classified identity to the per-OF, per-area counts."""
    bucket=result.setdefault(member['of'],{}).setdefault(member['area'],
        {'lines':0,'active':0,'history':0,'complete':True,'unknown_states':[]})
    bucket['lines']+=1
    bucket['active' if closure['active'] else 'history']+=1
    bucket['complete']=bucket['complete'] and member['complete']
    for unknown in closure['unknown_states']:
        if unknown not in bucket['unknown_states']:bucket['unknown_states'].append(unknown)


def classify(member, context):
    return population.classify({**member,'status_values':context.get('status_values',[])})


def summarize(members, contexts):
    """Count identities per area after classifying all associated source lines."""
    result={}
    for member in members:
        closure=classify(member,contexts.get(member['of'],{}))
        member['population']=closure
        tally(result,member,closure)
    return result
