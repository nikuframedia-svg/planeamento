"""Lightweight source membership for administrative planning consumers.

Uses the same current-source resolution and identity grouping as RAW, without
rebuilding calculations, capacity or production evidence just to list orders.
"""
from collections import defaultdict

from . import planning, planning_population as population
from .dossiers.models import order_number


def read(conn, snapshots, *, orders=None):
    from . import planning_hub as hub, planning_needs as needs, planning_local_orders
    areas = {s['snapshot_id']: 'perfis' if dataset == 'ds-met2-perfis' else 'cantoneiras'
             for dataset, s in snapshots.items()}
    rows = conn.execute('''SELECT r.snapshot_id,r.source_line_id,r.production_order_no,
        r.sales_order_no,r.customer_name,r.designation,r.component_ref,r.closed_x,
        r.row_data->'Fechado' closure,
        (p.closed_x IS TRUE AND p.remaining_valid IS TRUE AND p.remaining_quantity<=0
         AND (p.source_app='kanban-mes-mtg2' OR coalesce(r.row_data->>'2ª Oper.','') IN ('','0'))) complete
        FROM raw_mtg.plan_production_rows r LEFT JOIN analytics_mtg.kanban_plan_lines p
          ON p.snapshot_id=r.snapshot_id AND p.plan_key=r.source_line_id
        WHERE r.snapshot_id=ANY(%s)''' + (" AND regexp_replace(trim(r.production_order_no),'^OF[ ._-]*','','i')=ANY(%s)" if orders is not None else '') +
        ' ORDER BY r.snapshot_id,r.excel_row,r.source_line_id',
        (list(areas),[of[2:] for of in orders]) if orders is not None else (list(areas),)).fetchall()
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
    grouped = defaultdict(list)
    contexts = defaultdict(list)
    for row in rows:
        area = areas[row['snapshot_id']]
        candidates = owners[(area,row['source_line_id'])]
        key = next(iter(candidates)) if len(candidates)==1 else 'macro:'+row['source_line_id']
        grouped[(area,key)].append(row)
        of = order_number(row['production_order_no'])
        contexts[of].append({'production_order_no':of,'sales_order_no':row['sales_order_no'],
            'customer_name':row['customer_name'],'observations':row['designation']})
    for record in records:
        grouped.setdefault((record['area'],str(record['need_id'])),[])
    members=[]
    for (area,key), origins in grouped.items():
        need = ns.get(key)
        of = need['production_order_no'] if need else order_number(origins[0]['production_order_no'])
        members.append({'key':key,'area':area,'of':of,'need_id':key if need else None,
            'source_keys':[r['source_line_id'] for r in origins],
            'references':list(dict.fromkeys([need['component_ref']] if need else [r['component_ref'] for r in origins])),
            'macro_closure_values':[v for r in origins for v in (r['closed_x'],r['closure'])],
            'complete':bool(origins) and not need and all(r['complete'] is True for r in origins)})
    local = {r['production_order_no']:r for r in conn.execute('SELECT * FROM planning_mtg.local_orders').fetchall()} if planning_local_orders.available(conn) else {}
    for n in ns.values():
        contexts.setdefault(n['production_order_no'],[])
    for of in local:
        contexts.setdefault(of,[])
    fallback={}
    imported_ofs={m['of'] for m in members if m['source_keys']}
    for of, copies in contexts.items():
        values = local.get(of,{}).get('values_json',{})
        if of in local or not copies:
            copies=[{'production_order_no':of,'sales_order_no':values.get('ov'),
                'customer_name':values.get('customer'),'observations':values.get('designation'),
                'delivery_date':values.get('delivery_date')}]
        summary=hub._order_summary(copies)
        summary.update(administrative_origin='Manual local' if of in local or of not in imported_ofs else 'Macro — sem contexto CPIS',
                       local_order=local.get(of))
        if of is None:
            from urllib.parse import urlencode
            summary.update(administrative_origin='Macro — OF por identificar',unidentified=True,
                raw_links=[{'key':m['key'],'area':m['area'],'reference':', '.join(str(r) for r in m['references'] if r),
                    'href':'/planeamento/raw?'+urlencode({'area':m['area'],'q':next(iter(m['references']),'') or ''})}
                    for m in members if m['of'] is None])
        fallback[of]=summary
    return members,fallback


def summarize(members, contexts):
    """Count identities per area after classifying all associated source lines."""
    result={}
    for member in members:
        context=contexts.get(member['of'],{})
        closure=population.classify({**member,'status_values':context.get('status_values',[])})
        member['population']=closure
        bucket=result.setdefault(member['of'],{}).setdefault(member['area'],
            {'lines':0,'active':0,'history':0,'complete':True,'unknown_states':[]})
        bucket['lines']+=1
        bucket['active' if closure['active'] else 'history']+=1
        bucket['complete']=bucket['complete'] and member['complete']
        for unknown in closure['unknown_states']:
            if unknown not in bucket['unknown_states']:bucket['unknown_states'].append(unknown)
    return result
