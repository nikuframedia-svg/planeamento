"""One-way import: read factory SQLite, publish separate central snapshots.

Does not import any module from the original OCR or open its DB for writing.
The original OCR receives no business data from PostgreSQL.
"""
from __future__ import annotations
import argparse
import hashlib
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid
from datetime import date, datetime, timezone
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

def serial(value):
    return json.loads(json.dumps(value,ensure_ascii=False,allow_nan=False,default=lambda v:float(v) if isinstance(v,Decimal) else str(v) if isinstance(v,uuid.UUID) else v.isoformat()))


def digest(value):
    return hashlib.sha256(json.dumps(serial(value),sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def uid(value):
    return uuid.UUID(str(value))



def read_snapshot(path,instance_id):
    path=Path(path).resolve(strict=True)
    # Read the live WAL consistently, not an unsafe filesystem copy or immutable=1.
    conn=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=10)
    conn.row_factory=sqlite3.Row
    try:
        conn.execute('PRAGMA query_only=ON');conn.execute('BEGIN')
        required={'sheets':{'id','status','sheet_data','validated_at'},'production_rows':{'sheet_id','row_index'}}
        for table,columns in required.items():
            available={r['name'] for r in conn.execute('PRAGMA table_info('+table+')')}
            if not columns<=available:raise ValueError('unexpected_source_schema:'+table)
        sheets=[dict(r) for r in conn.execute("SELECT * FROM sheets WHERE status='validated' ORDER BY id")]
        production={}
        for r in conn.execute("SELECT p.* FROM production_rows p JOIN sheets s ON s.id=p.sheet_id WHERE s.status='validated' ORDER BY p.sheet_id,p.row_index"):
            row=dict(r);row.pop('id',None)
            production.setdefault(row['sheet_id'],[]).append(row)
        result=[];row_count=0;stop_count=0;production_dates=[]
        for s in sheets:
            data=json.loads(s['sheet_data'] or '{}')
            if not isinstance(data,dict):raise ValueError('invalid_sheet_payload')
            rows=production.get(s['id'],[])
            if len({r['row_index'] for r in rows})!=len(rows):raise ValueError('duplicate_source_row')
            template=data.get('template_name') or ''
            header=data.get('header') or {}
            # Keep all raw data even if a historical template cannot be classified.
            stoppage=('parage' in str(template).casefold())
            stops=data.get('rows',[]) if stoppage else []
            flags=[]
            for row in rows:
                rawdate=row.get('sheet_iso_date')
                if rawdate:
                    try:
                        parsed=date.fromisoformat(rawdate)
                        if parsed>date.today():flags.append({'row':row['row_index'],'code':'future_production_date','value':rawdate})
                        else:production_dates.append(parsed)
                    except ValueError:flags.append({'row':row['row_index'],'code':'invalid_production_date','value':rawdate})
            payload={'sheet':s,'data':data,'production':rows,'stoppages':stops,'template':template,
                     'machine':header.get('setor_maquina'),'quality_flags':flags}
            result.append({'sheet_id':s['id'],'source_revision':s.get('revision'),'content_hash':digest(payload),'payload':payload})
            row_count+=len(rows);stop_count+=len(stops)
        return {'instance_id':str(uid(instance_id)),'captured_at':datetime.now(timezone.utc).isoformat(),
                'data_recency':{'latest_production_date':str(max(production_dates)) if production_dates else None,
                    'dated_rows':len(production_dates),'future_or_invalid_dates':sum(len(s['payload']['quality_flags']) for s in result)},
                'sheets':result,'sheet_count':len(result),'production_count':row_count,'stoppage_count':stop_count,
                'content_hash':digest([(s['sheet_id'],s['content_hash']) for s in result])}
    finally:conn.rollback();conn.close()


def publish(snapshot,dsn,label='OCR original'):
    instance=uid(snapshot['instance_id']);attempt=uuid.uuid4();started=datetime.now(timezone.utc)
    with psycopg.connect(dsn,row_factory=dict_row,connect_timeout=5) as conn:
        if not conn.execute("SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0)) locked",('original-ocr:'+str(instance),)).fetchone()['locked']:
            raise RuntimeError('sync_already_running')
        conn.execute('INSERT INTO ocr_original.instances(id,source_label) VALUES (%s,%s) ON CONFLICT(id) DO NOTHING',(instance,label))
        old=conn.execute('SELECT * FROM ocr_original.instances WHERE id=%s FOR UPDATE',(instance,)).fetchone()
        previous=conn.execute('''SELECT s.sheet_id,s.source_revision FROM ocr_original.snapshot_sheets x
            JOIN ocr_original.sheets s USING(instance_id,sheet_id,content_hash) WHERE x.snapshot_id=%s''',(old['current_snapshot'],)).fetchall() if old['current_snapshot'] else []
        known={s['sheet_id']:s['source_revision'] for s in previous}
        if previous and not snapshot['sheets']:raise ValueError('unexpected_empty_validated_population')
        for s in snapshot['sheets']:
            if known.get(s['sheet_id']) is not None and s['source_revision'] is not None and s['source_revision']<known[s['sheet_id']]:raise ValueError('source_revision_regressed')
            if digest(s['payload'])!=s['content_hash']:raise ValueError('invalid_sheet_hash')
        if snapshot['sheet_count']!=len(snapshot['sheets']) or snapshot['production_count']!=sum(len(s['payload']['production']) for s in snapshot['sheets']):raise ValueError('source_count_mismatch')
        if digest([(s['sheet_id'],s['content_hash']) for s in snapshot['sheets']])!=snapshot['content_hash']:raise ValueError('invalid_snapshot_hash')
        existing=conn.execute('SELECT id FROM ocr_original.snapshots WHERE instance_id=%s AND content_hash=%s',(instance,snapshot['content_hash'])).fetchone()
        sid=existing['id'] if existing else uuid.uuid4()
        if not existing:
            conn.execute('''INSERT INTO ocr_original.snapshots(id,instance_id,content_hash,captured_at,sheet_count,production_count,stoppage_count)
                VALUES (%s,%s,%s,%s,%s,%s,%s)''',(sid,instance,snapshot['content_hash'],snapshot['captured_at'],snapshot['sheet_count'],snapshot['production_count'],snapshot['stoppage_count']))
            for s in snapshot['sheets']:
                conn.execute('''INSERT INTO ocr_original.sheets(instance_id,sheet_id,content_hash,source_revision,payload)
                    VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',(instance,s['sheet_id'],s['content_hash'],s['source_revision'],Jsonb(s['payload'])))
                conn.execute('INSERT INTO ocr_original.snapshot_sheets(snapshot_id,instance_id,sheet_id,content_hash) VALUES (%s,%s,%s,%s)',(sid,instance,s['sheet_id'],s['content_hash']))
            published=conn.execute('SELECT count(*) n FROM ocr_original.snapshot_sheets WHERE snapshot_id=%s',(sid,)).fetchone()['n']
            if published!=snapshot['sheet_count']:raise ValueError('published_count_mismatch')
        conn.execute('UPDATE ocr_original.instances SET current_snapshot=%s,confirmed_at=now() WHERE id=%s',(sid,instance))
        conn.execute('INSERT INTO ocr_original.sync_attempts(id,instance_id,started_at,success,snapshot_id,details) VALUES (%s,%s,%s,true,%s,%s)',(attempt,instance,started,sid,Jsonb({'unchanged':bool(existing),'sheets':snapshot['sheet_count'],'rows':snapshot['production_count'],
            'captured_at':snapshot['captured_at'],'data_recency':snapshot.get('data_recency')})))
        if str(old['current_snapshot'])!=str(sid):
            # Delivered only on commit; the planner still polls after a lost
            # notification or restart. No planning-table write is required.
            conn.execute("SELECT pg_notify('planning_raw_changed','original_ocr')")
    return {'snapshot_id':str(sid),'unchanged':bool(existing),'sheets':snapshot['sheet_count'],'rows':snapshot['production_count']}


def run_once(path,instance_id,dsn):
    started=datetime.now(timezone.utc)
    try:
        with psycopg.connect(dsn,row_factory=dict_row,connect_timeout=5) as guard:
            locked=guard.execute("SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0)) locked",('original-ocr-reader:'+str(uid(instance_id)),)).fetchone()['locked']
            if not locked:return {'skipped':'sync_already_running'}
            return publish(read_snapshot(path,instance_id),dsn)
    except Exception as exc:
        # Error classes/codes only: never print DSNs or raw authentication errors.
        code=str(exc) if isinstance(exc,ValueError) and ':' not in str(exc) else type(exc).__name__
        try:
            with psycopg.connect(dsn,connect_timeout=5) as conn:
                conn.execute('INSERT INTO ocr_original.sync_attempts(id,instance_id,started_at,success,error_code) VALUES (%s,%s,%s,false,%s)',(uuid.uuid4(),uid(instance_id),started,code[:100]))
        except psycopg.Error:pass
        return {'error':code}


def status(conn=None):
    from . import planning
    if conn is None:
        with planning.connect(readonly=True) as connection:return status(connection)
    if not conn.execute("SELECT to_regclass('ocr_original.instances') name").fetchone()['name']:return {'state':'not_configured','label':'OCR original — importação não configurada'}
    rows=conn.execute('''SELECT i.*,s.sheet_count,s.production_count,s.stoppage_count,s.captured_at,s.published_at FROM ocr_original.instances i
        LEFT JOIN ocr_original.snapshots s ON s.id=i.current_snapshot ORDER BY i.source_label''').fetchall()
    last=conn.execute('SELECT * FROM ocr_original.sync_attempts ORDER BY finished_at DESC LIMIT 1').fetchone()
    now=datetime.now(timezone.utc)
    for row in rows:
        age=(now-row['confirmed_at']).total_seconds() if row['confirmed_at'] else None
        row['state']='confirmed' if age is not None and 0<=age<=900 else 'stale'
        row['last_attempt']=conn.execute('SELECT finished_at,success,error_code,snapshot_id FROM ocr_original.sync_attempts WHERE instance_id=%s ORDER BY finished_at DESC LIMIT 1',(row['id'],)).fetchone()
        success=conn.execute('SELECT finished_at,snapshot_id,details FROM ocr_original.sync_attempts WHERE instance_id=%s AND success ORDER BY finished_at DESC LIMIT 1',(row['id'],)).fetchone()
        row['last_successful_publication']=success
        row['data_recency']=(success['details'].get('data_recency') if success else None)
        row['last_consistent_read_at']=(success['details'].get('captured_at') if success else None)
    from . import planning_associations
    human_supported=planning_associations.original_decisions_available(conn)
    applied={}
    if conn.execute("SELECT to_regclass('planning_mtg.raw_generations') t").fetchone()['t']:
        for area in planning.AREAS:
            generation=conn.execute("SELECT id,created_at,metadata FROM planning_mtg.raw_generations WHERE dataset=%s ORDER BY id DESC LIMIT 1",('planning:'+area,)).fetchone()
            if generation:
                applied[area]={'generation':generation['id'],'published_at':generation['created_at'],
                    'snapshots':generation['metadata'].get('original_ocr_snapshots',[])}
    current=sorted((str(r['id']),str(r['current_snapshot'])) for r in rows if r['current_snapshot'])
    included=bool(current) and len(applied)==len(planning.AREAS) and all(sorted(tuple(s) for s in a['snapshots'])==current for a in applied.values())
    return serial({'state':'available' if rows else 'not_configured','instances':rows,'last_attempt':last,
        'included_in_planning_balances':included,'planning_publications':applied,'human_association_supported':human_supported})


def query(*,of='',model='',machine='',date_from='',date_to='',page=1):
    from . import planning
    from .dossiers.models import order_number
    page=max(int(page),1);conditions=[];args=[]
    if of:
        normalized=order_number(of)
        if not normalized:raise planning.PlanningError('Indica uma OF válida.')
        conditions.append("regexp_replace(upper(r.value->>'of'),'^OF','')=%s");args.append(normalized[2:])
    if model:conditions.append("s.payload->>'template' ILIKE %s");args.append('%'+model+'%')
    if machine:conditions.append("s.payload->>'machine' ILIKE %s");args.append('%'+machine+'%')
    for value,operator in ((date_from,'>='),(date_to,'<=')):
        if value:
            try:date.fromisoformat(value)
            except ValueError:raise planning.PlanningError('Indica datas válidas.') from None
            conditions.append("r.value->>'sheet_iso_date' "+operator+' %s');args.append(value)
    with planning.connect(readonly=True) as conn:
        state=status(conn)
        if state['state']=='not_configured':return {'records':[],'total':0,'page':page,'source':state}
        base=''' FROM ocr_original.instances i JOIN ocr_original.snapshot_sheets x ON x.snapshot_id=i.current_snapshot
            JOIN ocr_original.sheets s ON (s.instance_id,s.sheet_id,s.content_hash)=(x.instance_id,x.sheet_id,x.content_hash)
            CROSS JOIN LATERAL jsonb_array_elements(s.payload->'production') r(value)'''
        if conditions:base+=' WHERE '+' AND '.join(conditions)
        total=conn.execute('SELECT count(*) n'+base,args).fetchone()['n']
        rows=conn.execute("SELECT s.instance_id,s.sheet_id,s.content_hash,s.payload->'sheet'->>'validated_at' validation_time,s.payload->>'template' template,s.payload->>'machine' machine,s.payload->'quality_flags' quality_flags,r.value data"+base+' ORDER BY s.sheet_id DESC,(r.value->>\'row_index\')::integer LIMIT 50 OFFSET %s',(*args,(page-1)*50)).fetchall()
        from . import planning_original_production
        keys=['original:'+str(r['instance_id'])+':'+str(r['sheet_id'])+':'+str(r['data']['row_index']) for r in rows]
        diagnostics=planning_original_production.diagnostics(conn,keys)
        for row,key in zip(rows,keys):
            row['source_url']='https://mtg2.nikufra.ai/sheet/'+str(row['sheet_id'])
            row['source_event_key']=key;row['planning']=diagnostics[key]
        return serial({'records':rows,'total':total,'page':page,'source':state})


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--watch',action='store_true');parser.add_argument('--check',action='store_true');args=parser.parse_args()
    path=os.environ.get('ORIGINAL_OCR_SQLITE_PATH');instance=os.environ.get('ORIGINAL_OCR_INSTANCE_ID');dsn=os.environ.get('ORIGINAL_OCR_PUBLISH_DSN')
    if not path or not instance or (not dsn and not args.check):parser.error('Configura ORIGINAL_OCR_SQLITE_PATH, ORIGINAL_OCR_INSTANCE_ID e ORIGINAL_OCR_PUBLISH_DSN.')
    if args.check:
        snap=read_snapshot(path,instance);print(json.dumps({k:v for k,v in snap.items() if k!='sheets'}));return
    interval=max(int(os.environ.get('ORIGINAL_OCR_INTERVAL_SECONDS','300')),30)
    while True:
        result=run_once(path,instance,dsn)
        print(json.dumps(result),flush=True)
        if not args.watch:
            if result.get('error'):raise SystemExit(1)
            break
        time.sleep(interval)

if __name__=='__main__':main()
