"""Observe linked source revisions before publishing planning results."""
import json
import sqlite3
from psycopg.types.json import Jsonb
from .. import planning, planning_needs as needs


def observations(links):
    if not links:return {}
    from ..dossiers import store
    path=store.root()/'dossiers.db'
    result={}
    try:
        conn=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)
        conn.row_factory=sqlite3.Row
        conn.execute('PRAGMA query_only=ON');conn.execute('BEGIN')
        try:
            for link in links:
                doc_id,piece_id=link['source_id'].split('/',1)
                row=conn.execute('''SELECT d.revision doc_revision,d.status,d.production_order,
                    p.revision piece_revision,p.state,p.values_json,p.drawing_pages_json
                    FROM documents d JOIN pieces p ON p.document_id=d.id
                    WHERE d.id=? AND p.id=?''',(doc_id,piece_id)).fetchone()
                if not row:
                    result[link['source_id']]={'state':'unavailable','reason':'A origem documental já não está disponível.'};continue
                version=f"{row['doc_revision']}:{row['piece_revision']}"
                valid=row['state'] not in ('excluded','superseded') and row['status'] not in ('queued','indexing','extracting','matching')
                result[link['source_id']]={'state':'available' if valid else 'unavailable','version':version,
                    'document_status':row['status'],'piece_state':row['state'],'of':row['production_order'],
                    'values':json.loads(row['values_json']),'pages':json.loads(row['drawing_pages_json']),
                    'reason':None if valid else 'A origem documental foi excluída, substituída ou aguarda nova leitura.'}
        finally:conn.rollback();conn.close()
    except (sqlite3.Error,OSError) as exc:
        # Keep prior human values and suggestions; publish the loss of evidence.
        return {link['source_id']:{'state':'unavailable','reason':'Origem documental indisponível ('+type(exc).__name__+').'} for link in links}
    return result


def refresh():
    """Commit suggestions/diagnostics once per source revision, before RAW work."""
    with planning.connect() as conn:
        links=conn.execute("SELECT * FROM planning_mtg.need_sources WHERE kind IN ('pdf','plan_line') ORDER BY source_id").fetchall()
        if not links:return {'changed':[]}
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('planning-needs-writes',0))")
        # A macro revision must refresh linked suggestions and the need revision
        # before the worker captures dependencies. Opening the form must not be
        # the first action that discovers it after RAW has been published.
        snapshots={area:planning.snapshot(conn,area)['snapshot_id'] for area in planning.AREAS}
        changed=[]
        pending={link['need_id'] for link in conn.execute("SELECT * FROM planning_mtg.need_sources WHERE kind='plan_line'")
                 if link['version']!=snapshots.get(link['payload'].get('area','perfis'))}
        for need_id in sorted(pending,key=str):
            need=needs.load(conn,need_id);before=need['revision']
            needs.refresh(conn,need,kinds={'plan_line'})
            if need['revision']!=before:changed.append(str(need_id))
        links=conn.execute("SELECT * FROM planning_mtg.need_sources WHERE kind='pdf' ORDER BY source_id").fetchall()
        observed=observations(links)
        for link in links:
            # Re-read after the lock: an editor may have refreshed this source.
            link=conn.execute("SELECT * FROM planning_mtg.need_sources WHERE kind='pdf' AND source_id=%s",(link['source_id'],)).fetchone()
            if not link:continue
            current=observed[link['source_id']];old=link['payload'];token=needs.digest(current)
            if old.get('document_dependency_token')==token:continue
            same=not old.get('document_dependency_token') and current['state']=='available' and current['version']==link['version'] and current['values']==old['values'] and current['of']==old['of']
            payload={**old,'document_dependency_token':token,'source_state':current['state'],'source_error':current['reason']}
            version=current.get('version',link['version'])
            if current['state']=='available':
                payload.update(version=version,of=current['of'],values=current['values'],pages=current['pages'],raw_evidence=current['values'].get('evidence',{}))
            conn.execute("UPDATE planning_mtg.need_sources SET version=%s,payload=%s,updated_at=now() WHERE kind='pdf' AND source_id=%s",(version,Jsonb(payload),link['source_id']))
            if same:continue
            need=needs.load(conn,link['need_id'])
            if current['state']=='available':
                for field in needs.PIECE_FIELDS:
                    value=Jsonb(current['values'].get(field))
                    conn.execute("UPDATE planning_mtg.field_state SET requires_review=requires_review OR (suggestion IS DISTINCT FROM %s::jsonb),suggestion=%s,source=%s WHERE need_id=%s AND scope='piece' AND field=%s",
                        (value,value,Jsonb({'kind':'pdf','id':link['source_id'],'version':version}),need['id'],field))
            else:
                conn.execute("UPDATE planning_mtg.field_state SET requires_review=true WHERE need_id=%s AND source->>'kind'='pdf' AND source->>'id'=%s",(need['id'],link['source_id']))
            conn.execute('UPDATE planning_mtg.needs SET revision=revision+1,updated_at=now() WHERE id=%s',(need['id'],))
            need=needs.load(conn,need['id'])
            needs.event(conn,need,'source_updated' if current['state']=='available' else 'source_unavailable','Sistema',{'previous':old,'current':payload})
            changed.append(str(need['id']))
        if changed:
            from . import projection
            projection.signal(conn,'documents')
        return {'changed':sorted(set(changed))}
