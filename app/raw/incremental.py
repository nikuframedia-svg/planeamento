"""Atomic publication of locally affected OFs, with explicit aggregate freshness.

Partial publication never stamps an unprocessed source population as current.
The worker can recover from the durable generation metadata and source signal.
"""
from functools import wraps
from psycopg.errors import SerializationFailure
from .. import planning, planning_needs as needs
from . import projection, query, productivity


def retry_serialization(operation):
    """Retry only transactions PostgreSQL has aborted, using the same command ID."""
    @wraps(operation)
    def run(*args,**kwargs):
        for attempt in range(3):
            try:return operation(*args,**kwargs)
            except SerializationFailure:
                if attempt==2:
                    raise planning.PlanningError('Os dados estão a ser atualizados. Repete a gravação com a revisão atual.',409) from None
    return run


def baseline(conn):
    if not conn.execute("SELECT to_regclass('planning_mtg.raw_generations') t").fetchone()['t']:return None
    # Keep worker publications outside the complete local decision transaction.
    # Lock capacity before the area builders, matching the publisher dependency
    # order; taking only the dataset lock at publish time leaves the captured
    # generation vulnerable to an unrelated capacity refresh.
    for key in ['capacity-revision',*('raw-build:'+area for area in planning.AREAS)]:
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(key,))
    result={}
    for area in planning.AREAS:
        try:gen=query.generation(conn,area)
        except planning.PlanningError as exc:
            if exc.status==503:continue
            raise
        result[area]={'generation':gen,'fingerprint':projection.fingerprint(conn,area)}
    return result


def can_edit_orders(gen,fingerprint,orders):
    meta=gen['metadata']
    if meta.get('core_source_fingerprint',meta.get('source_fingerprint'))==fingerprint:return True
    # A second edit of already refreshed OFs is safe without claiming that
    # untouched OFs or aggregates have caught up with the external sources.
    return meta.get('last_incremental_fingerprint')==fingerprint and set(orders).issubset(meta.get('updated_orders',[]))


def publish(conn,before,orders,need_ids,request_id,*,refresh_hours=False):
    if before is None:return {'status':'workspace_unavailable','rows':[],'areas':{}}
    orders=sorted(set(orders));need_ids={str(n) for n in need_ids}
    output={'status':'published','rows':[],'areas':{},'aggregates_pending':True,'source_refresh_pending':False}
    configs=conn.execute("SELECT * FROM planning_mtg.raw_objects WHERE kind IN ('resource','calendar','rate','period','worked_hours') AND NOT archived").fetchall()
    for area,prior in before.items():
        gen=prior['generation']
        complete=gen['metadata'].get('core_source_fingerprint',gen['metadata'].get('source_fingerprint'))==prior['fingerprint']
        output['source_refresh_pending']=output['source_refresh_pending'] or not complete
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('raw-build:'+area,))
        rows,events,meta=projection.build_rows(conn,area,orders=orders)
        fingerprint=projection.fingerprint(conn,area)
        old=conn.execute("SELECT m.row_key FROM planning_mtg.raw_members m JOIN planning_mtg.raw_contents c ON c.hash=m.content_hash WHERE m.dataset=%s AND m.last_generation IS NULL AND c.values_json->>'of'=ANY(%s)",('planning:'+area,orders)).fetchall()
        old_keys={r['row_key'] for r in old};new_keys={r['key'] for r in rows}
        touched=old_keys|new_keys
        # Do not replace unrelated events generated without their complete OF population.
        scoped_events=[e for e in events if e['values'].get('of') in orders or touched.intersection(e.get('planning_keys',[]))]
        try:
            pg=query.generation(conn,area,dataset='production');source,params=query.source(pg)
            old_events=conn.execute("SELECT m.row_key"+source+" AND (c.values_json->>'of'=ANY(%s) OR coalesce(c.detail->'planning_keys','[]') ?| %s)",params+[orders,list(touched)]).fetchall()
            removed={r['row_key'] for r in old_events}-{e['key'] for e in scoped_events}
            projection.publish_delta(conn,'production:'+area,needs.digest(['local-production',request_id,area]),scoped_events,
                {**pg['metadata'],**meta,'core_source_fingerprint':fingerprint if complete else pg['metadata'].get('core_source_fingerprint',pg['metadata'].get('source_fingerprint')),
                    'incremental_request':str(request_id),'source_refresh_pending':not complete},remove=removed,expected_generation=pg['id'])
        except planning.PlanningError as exc:
            if exc.status!=503:raise
        if refresh_hours:
            projection.publish_hours(conn,area,needs.digest(['local-hours',request_id,area]),{**meta,'core_source_fingerprint':fingerprint,'source_refresh_pending':not complete})
        productivity.apply_rows(conn,area,rows,configs)
        updated=set(orders)
        if gen['metadata'].get('last_incremental_fingerprint')==prior['fingerprint']:
            updated.update(gen['metadata'].get('updated_orders',[]))
        metadata={**gen['metadata'],'incremental_source':meta,
            'core_source_fingerprint':fingerprint if complete else gen['metadata'].get('core_source_fingerprint',gen['metadata'].get('source_fingerprint')),
            'last_incremental_fingerprint':fingerprint,'updated_orders':sorted(updated),
            'source_refresh_pending':not complete,'aggregates_pending':True,'incremental_request':str(request_id)}
        if complete:
            from . import ocr_scope
            metadata['ocr_manifest']=ocr_scope.store(conn,ocr_scope.capture(conn,area))
        metadata.pop('core_generation',None);metadata.pop('capacity_fingerprint',None)
        new=projection.publish_delta(conn,'planning:'+area,needs.digest(['local-planning',request_id,area,fingerprint]),rows,
            metadata,remove=old_keys-new_keys,expected_generation=gen['id'])
        # Order totals are cheap and belong to the same transaction/revision.
        order_rows=projection.order_rows(rows)
        try:
            og=query.generation(conn,area,dataset='orders')
            projection.publish_delta(conn,'orders:'+area,needs.digest(['local-orders',request_id,area]),order_rows,
                {**og['metadata'],'source_refresh_pending':not complete,'incremental_request':str(request_id)},
                remove=set(orders+['%s:history'%of for of in orders])-{r['key'] for r in order_rows},expected_generation=og['id'])
        except planning.PlanningError as exc:
            if exc.status!=503:raise
        output['areas'][area]={'version':str(new['id']),'updated_orders':orders,'rows_recalculated':len(rows)}
        output['rows'].extend({**r,'version':str(new['id'])} for r in rows if r.get('need_id') in need_ids)
    if not before:output['status']='initial_projection_pending'
    return needs.serial(output)
