"""Durable OCR change detection and atomic publication of complete affected OFs.

The checkpoint contains source facts, not counts or timestamps. Old and new
identities participate in the closure, including human allocations to other OFs.
Unknown source changes conservatively use the full projection path.
"""
from psycopg.types.json import Jsonb
from .. import planning, planning_needs as needs
from . import projection, query, productivity


def capture(conn,area,*,facts=None):
    app='kanban-mes-mtg2' if area=='perfis' else 'kanban-mes'
    sheets={r['sheet_uid']:r['hash'] for r in conn.execute(
        "SELECT sheet_uid,md5(v::text) hash FROM mes_kanban.validated_sheets v WHERE source_app=%s",(app,))}
    allocated={}
    orders={str(r['id']):r['production_order_no'] for r in conn.execute('SELECT id,production_order_no FROM planning_mtg.needs')}
    for d in conn.execute('SELECT DISTINCT ON(production_record_id) production_record_id,allocations FROM planning_mtg.association_decisions ORDER BY production_record_id,revision DESC'):
        allocated[d['production_record_id']]={orders[a['need_id']] for a in d['allocations'] if a['need_id'] in orders}
    records={}
    for fact in projection.source_facts(conn,area) if facts is None else facts:
        related=allocated.get(fact['id'],set()) | ({fact['of']} if fact['of'] else set())
        records[str(fact['id'])]={'hash':needs.digest([needs.serial(fact),sheets[fact['sheet_uid']]]),'orders':sorted(related)}
    return {'contract':'ocr-scope-v1','base':projection.fingerprint(conn,area,include_ocr=False),'sheets':sheets,'records':records}


def store(conn,manifest):
    digest=needs.digest(manifest)
    conn.execute("INSERT INTO planning_mtg.raw_contents(hash,values_json,detail,search_text) VALUES(%s,'{}',%s,'') ON CONFLICT DO NOTHING",
        (digest,Jsonb({'ocr_manifest':manifest})))
    return digest


def identify(conn,current,manifest):
    saved=conn.execute("SELECT detail->'ocr_manifest' manifest FROM planning_mtg.raw_contents WHERE hash=%s",
        (current['metadata'].get('ocr_manifest'),)).fetchone()
    before=saved['manifest'] if saved else None
    if not before or before.get('contract')!=manifest['contract'] or before.get('base')!=manifest['base']:return None
    old=before['records'];new=manifest['records']
    changed={key for key in old.keys()|new.keys() if old.get(key)!=new.get(key)}
    records=set(changed);orders=set()
    # Whole OF populations and all linked allocations must be calculated together.
    # Taking a transitive closure also handles a source record moving between OFs.
    links=[(key,set(item['orders'])) for source in (old,new) for key,item in source.items()]
    while True:
        size=(len(records),len(orders))
        for key,related in links:
            if key in records or orders.intersection(related):records.add(key);orders.update(related)
        if size==(len(records),len(orders)):break
    return {'orders':sorted(orders),'records':sorted(records),'changed_records':sorted(changed)}


def publish(conn,area,current,fp,manifest,scope,*,facts=None):
    orders=scope['orders']
    if orders:rows,events,source=projection.build_rows(conn,area,orders=orders,facts=facts)
    else:
        rows=[];source={}
        events=projection.enrich(conn,area,[],planning.snapshot(conn,area)['snapshot_id'],facts=facts)
    selected=set(scope['records'])
    events=[event for event in events if str(event['record_id']) in selected]
    meta={**current['metadata'],**source,'core_source_fingerprint':fp,'source_refresh_pending':False,
        'aggregates_pending':True,'ocr_manifest':store(conn,manifest),'calculation_scope':'ocr_orders',
        'updated_orders':orders,'changed_ocr_records':scope['changed_records']}
    for key in ('core_generation','capacity_fingerprint','last_incremental_fingerprint','incremental_source','incremental_request'):meta.pop(key,None)
    pg=query.generation(conn,area,dataset='production');base,args=query.source(pg)
    old_events={r['row_key'] for r in conn.execute("SELECT m.row_key"+base+" AND c.detail->>'record_id'=ANY(%s)",args+[scope['records']])}
    projection.publish_delta(conn,'production:'+area,fp,events,meta,
        remove=old_events-{event['key'] for event in events},expected_generation=pg['id'])
    projection.publish_hours(conn,area,fp,meta)
    configs=conn.execute("SELECT * FROM planning_mtg.raw_objects WHERE kind IN ('resource','calendar','rate','period','worked_hours') AND NOT archived").fetchall()
    productivity.apply_rows(conn,area,rows,configs)
    base,args=query.source(current)
    old_keys={r['row_key'] for r in conn.execute("SELECT m.row_key"+base+" AND c.values_json->>'of'=ANY(%s)",args+[orders])}
    gen=projection.publish_delta(conn,'planning:'+area,fp,rows,meta,
        remove=old_keys-{row['key'] for row in rows},expected_generation=current['id'])
    og=query.generation(conn,area,dataset='orders');order_rows=projection.order_rows(rows)
    projection.publish_delta(conn,'orders:'+area,fp,order_rows,meta,
        remove=set(orders+[of+':history' for of in orders])-{row['key'] for row in order_rows},expected_generation=og['id'])
    return gen
