"""Close/reopen real-size CPIS populations, writing only to the acceptance clone."""
import json,os,time,uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path
from psycopg.types.json import Jsonb

PRIVATE=Path('/home/luis/.local/state/planning-backups/integral-20260923')
os.environ['MES_PG_DSN']=json.loads((PRIVATE/'isolated.json').read_text())['dsn']
from app import planning,planning_hub as hub,planning_needs as needs
from app.raw import projection,capacity,query

F=Path('docs/validacao-planeamento-integral/20260923-execucao')
report={'at':datetime.now(timezone.utc).isoformat(),'scope':'Isolated CPIS context; no source/operational writes','steps':[]}
if (F/'t9-cpis-revision-trial.json').exists():
    (F/'t9-cpis-revision-trial.json').rename(F/('t9-cpis-revision-trial-history-'+str(time.time_ns())+'.json'))


def refresh():
    start=time.perf_counter()
    def build(area):
        t=time.perf_counter();g=projection.rebuild(area)
        return area,{'seconds':time.perf_counter()-t,'generation':g['id'],'rows':g['row_count'],
                     'scope':g['metadata'].get('calculation_scope'),'orders':g['metadata'].get('updated_orders',[])}
    with ThreadPoolExecutor(max_workers=2) as pool:areas=dict(pool.map(build,planning.AREAS))
    t=time.perf_counter();capacity.rebuild()
    return {'areas':areas,'capacity_seconds':time.perf_counter()-t,'central_seconds':time.perf_counter()-start}


def publish(baseline,orders,status):
    """A complete committed version, like a connector publication; no partial update."""
    started=time.perf_counter();ident=uuid.uuid4()
    with planning.connect() as c:
        c.execute('INSERT INTO cpis_mtg.versions SELECT %s,source_name,source_view,%s,row_count,state_counts,now(),now(),now(),connector_version FROM cpis_mtg.versions WHERE id=%s',
                  (ident,needs.digest([str(baseline),str(ident),orders,status]),baseline))
        cols=[r['column_name'] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='cpis_mtg' AND table_name='orders' ORDER BY ordinal_position")]
        c.execute('INSERT INTO cpis_mtg.orders SELECT '+','.join('%s' if k=='version_id' else k for k in cols)+' FROM cpis_mtg.orders WHERE version_id=%s',(ident,baseline))
        if status is not None:
            c.execute('UPDATE cpis_mtg.orders SET status=%s WHERE version_id=%s AND production_order_no=ANY(%s)',(status,ident,orders))
    return str(ident),time.perf_counter()-started


with planning.connect() as c:
    assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
    direct=hub._direct_version(c)
    if direct:
        assert direct['source_name']=='C05 isolated CPIS context','Never replace an unrelated CPIS trial'
        baseline=direct['id']
    else:
        # Preserve all imported CPIS copies and every field consumed by planning.
        source=hub._order_rows(c,None,'',None);baseline=uuid.uuid4()
        c.execute('INSERT INTO cpis_mtg.versions(id,source_name,source_view,content_sha256,row_count,queried_at,last_confirmed_at,connector_version) VALUES(%s,%s,%s,%s,%s,now(),now(),%s)',
                  (baseline,'C05 isolated CPIS context','imported CPIS copies, validation only',needs.digest(needs.serial(source)),len(source),'isolated-trial'))
        fields=[k for k in source[0] if k!='area']
        with c.cursor() as cur:
            cur.executemany('INSERT INTO cpis_mtg.orders(version_id,source_row_no,'+','.join(fields)+',row_data) VALUES('+','.join(['%s']*(len(fields)+3))+')',
                [(baseline,i,*[row[k] for k in fields],Jsonb(needs.serial(row))) for i,row in enumerate(source,1)])
    targets=[]
    for area in planning.AREAS:
        g=query.generation(c,area);sql,args=query.source(g)
        r=c.execute("SELECT m.row_key,c.values_json->>'of' of"+sql+" AND m.planning_active AND c.detail->>'origin'='macro' ORDER BY m.row_key LIMIT 1",args).fetchone()
        assert r;targets.append({'area':area,**r})
report['baseline']=str(baseline);report['targets']=targets
report['provisioning']=refresh()
try:
    for status in ('Fechada',None):
        revision,source_seconds=publish(baseline,[t['of'] for t in targets],status)
        result={'state':status or 'reopened','source_revision':revision,'source_publication_seconds':source_seconds,**refresh()}
        for target in targets:
            row=query.listing({'area':target['area'],'population':'all','selected':[target['row_key']]})['rows'][0]
            assert row['values']['planning_active'] is (status is None)
        result['within_10_seconds']=result['central_seconds']<=10
        report['steps'].append(result);print(json.dumps(result),flush=True)
finally:
    if not report['steps'] or report['steps'][-1]['state']!='reopened':
        publish(baseline,[],None);refresh()
    report['result']='passed' if len(report['steps'])==2 and all(r['within_10_seconds'] for r in report['steps']) else 'incomplete'
    (F/'t9-cpis-revision-trial.json').write_text(json.dumps(report,indent=2)+'\n')
