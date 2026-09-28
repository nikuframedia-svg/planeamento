"""Durable per-order dependencies for macro, CPIS and local/document revisions."""
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from psycopg.types.json import Jsonb
from psycopg import sql
from .. import planning, planning_needs as needs, planning_hub as hub
from ..dossiers.models import order_number


def macro_inputs(conn,area,snapshot,*,force=False):
    # Imported snapshots are immutable. CPIS, documents and human revisions do
    # not require hashing every cell of an unchanged 75k-line workbook again.
    key=needs.digest(['macro-order-inputs-v5',area,snapshot])
    saved=conn.execute("SELECT detail->'macro_inputs' value FROM planning_mtg.raw_contents WHERE hash=%s",(key,)).fetchone()
    if saved and not force:return saved['value']
    columns=conn.execute("SELECT column_name,is_generated,generation_expression FROM information_schema.columns WHERE table_schema='raw_mtg' AND table_name='plan_production_rows' ORDER BY ordinal_position").fetchall()
    # The operational schema already hashes every raw cell with a generated
    # SHA-256 column. Reuse it alongside ALL normalized fields; do not hash
    # tens of thousands of large JSON blobs again on each import. Schemas
    # without that exact generated expression retain the full raw JSON.
    hashed=any(c['column_name']=='row_hash' and c['is_generated']=='ALWAYS'
        and c['generation_expression']=="encode(digest((row_data)::text, 'sha256'::text), 'hex'::text)" for c in columns)
    omitted={'snapshot_id','source_line_id'}|({'row_data'} if hashed else set())
    selected=sql.SQL(',').join(sql.Identifier(c['column_name']) for c in columns if c['column_name'] not in omitted)
    rows=conn.execute(sql.SQL('''SELECT regexp_replace(trim(production_order_no),'^OF[ ._-]*','','i') of,
        md5(string_agg(md5(record_send(r)),'' ORDER BY excel_row)) hash
        FROM (SELECT {} FROM raw_mtg.plan_production_rows WHERE snapshot_id=%s) r GROUP BY 1''').format(selected),(snapshot,)).fetchall()
    unknown=[];orders={}
    for row in rows:
        of=order_number(row['of'])
        if of:orders[of]=row['hash']
        else:unknown.append(row)
    catalogs=[]
    for table in ('other_sheet_rows','machine_rows'):
        catalogs.append(conn.execute("SELECT md5(string_agg(h,'' ORDER BY h)) hash FROM (SELECT md5((to_jsonb(t)-'snapshot_id'-'source_line_id')::text) h FROM raw_mtg."+table+' t WHERE snapshot_id=%s) x',(snapshot,)).fetchone()['hash'])
    if area=='perfis':
        from .. import planning_catalogs
        src=conn.execute('SELECT source_path,source_sha256 FROM audit_mtg.snapshots WHERE snapshot_id=%s',(snapshot,)).fetchone()
        path=Path(src['source_path']) if src.get('source_path') else None
        if path and path.is_file():
            stat=path.stat()
            catalogs.append(needs.digest(planning_catalogs.workbook_ranges(str(path),stat.st_mtime_ns,stat.st_size,src['source_sha256'])))
        else:catalogs.append('Workbook named ranges unavailable; database catalogue only')
    value={'orders':orders,'unknown':unknown,'catalogs':catalogs}
    # A force rebuild can inspect deliberately modified disposable fixtures;
    # never change an immutable cache entry used by retained generations.
    conn.execute("INSERT INTO planning_mtg.raw_contents(hash,values_json,detail,search_text) VALUES(%s,'{}',%s,'') ON CONFLICT DO NOTHING",(key,Jsonb({'macro_inputs':value})))
    return value


def capture(conn,area,*,force=False):
    from . import projection,capacity
    from .. import planning_calculations
    snapshot=planning.snapshot(conn,area)['snapshot_id']
    macro=macro_inputs(conn,area,snapshot,force=force)
    orders=defaultdict(dict,{of:{'macro':value} for of,value in macro['orders'].items()})
    local_needs=conn.execute('SELECT * FROM planning_mtg.needs ORDER BY id').fetchall()
    from .. import planning_associations as assoc,planning_local_orders
    local_orders=conn.execute('SELECT * FROM planning_mtg.local_orders ORDER BY production_order_no').fetchall() if planning_local_orders.available(conn) else []
    relevant=set(orders)|{n['production_order_no'] for n in local_needs}|{n['production_order_no'] for n in local_orders}
    contexts=defaultdict(list)
    for row in hub._order_rows(conn,hub._direct_version(conn),'',None,only_ofs=sorted(relevant)):
        of=order_number(row['production_order_no'])
        if of:contexts[of].append(row)
    for of,rows in contexts.items():orders[of]['cpis']=needs.digest(sorted((needs.serial(r) for r in rows),key=needs.digest))
    by_need={}
    for row in local_needs:
        of=row['production_order_no'];by_need[str(row['id'])]=of
        orders[of].setdefault('needs',[]).append(needs.serial(row))
    for row in conn.execute('SELECT * FROM planning_mtg.need_sources ORDER BY need_id,kind,source_id'):
        of=by_need.get(str(row['need_id']))
        if of:orders[of].setdefault('sources',[]).append(needs.serial(row))
    for row in assoc.latest_all(conn):
        affected={by_need.get(a['need_id']) for a in row['allocations']}
        affected.add(order_number((row['evidence'] or {}).get('production_order')))
        for of in affected-{None}:orders[of].setdefault('decisions',[]).append(needs.serial(row))
    for row in local_orders:orders[row['production_order_no']]['local']=needs.serial(row)
    # Catalogues and reference formulas may affect every piece. Only a proven
    # unchanged catalogue allows an order-scoped calculation.
    return {'contract':'source-scope-v7','engine':[projection.RAW_CONTRACT,planning_calculations.CONTRACT,capacity.ESTIMATE_CONTRACT],
            'day':datetime.now(ZoneInfo(planning.settings.display_timezone)).date().isoformat(),
            'catalogs':macro['catalogs'],'unknown':macro['unknown'],'orders':{of:needs.digest(value) for of,value in sorted(orders.items())}}


def store(conn,manifest):
    key=needs.digest(manifest)
    conn.execute("INSERT INTO planning_mtg.raw_contents(hash,values_json,detail,search_text) VALUES(%s,'{}',%s,'') ON CONFLICT DO NOTHING",(key,Jsonb({'source_manifest':manifest})))
    return key


def identify(conn,current,manifest,ocr):
    from . import ocr_scope
    saved=conn.execute("SELECT detail->'source_manifest' manifest FROM planning_mtg.raw_contents WHERE hash=%s",(current['metadata'].get('source_manifest'),)).fetchone()
    before=saved['manifest'] if saved else None
    if not before or any(before.get(k)!=manifest.get(k) for k in ('contract','engine','day','catalogs','unknown')):return None
    prior=ocr_scope.load(conn,current)
    if not prior or prior.get('contract')!=ocr.get('contract'):return None
    old,new=before['orders'],manifest['orders']
    orders={of for of in old.keys()|new.keys() if old.get(of)!=new.get(of)}
    return ocr_scope.closure(prior,ocr,orders=orders)
