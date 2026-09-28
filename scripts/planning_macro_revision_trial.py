"""New immutable macro IDs at full volume; writes only to the acceptance clone."""
import json,os,time,uuid,hashlib,re,shutil
from zipfile import ZipFile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path
from psycopg.types.json import Jsonb

PRIVATE=Path('/home/luis/.local/state/planning-backups/integral-20260923')
os.environ['MES_PG_DSN']=json.loads((PRIVATE/'isolated.json').read_text())['dsn']
from app import planning,planning_needs as needs
from app.raw import projection,capacity_revision as capacity,query

F=Path('docs/validacao-planeamento-integral/20260923-execucao')


def refresh(*,force=False):
    start=time.perf_counter()
    def build(area):
        t=time.perf_counter();g=projection.rebuild(area,force=force)
        return area,{'seconds':time.perf_counter()-t,'generation':g['id'],'rows':g['row_count'],
                     'scope':g['metadata'].get('calculation_scope'),'orders':g['metadata'].get('updated_orders',[])}
    with ThreadPoolExecutor(max_workers=2) as pool:areas=dict(pool.map(build,planning.AREAS))
    t=time.perf_counter();capacity.rebuild(force=force)
    return {'areas':areas,'capacity_seconds':time.perf_counter()-t,'central_seconds':time.perf_counter()-start}


def publish(conn,area,previous,of,closed):
    """Copy the actual XLSM and change only closure cells for this isolated OF."""
    target=('mtg2_' if area=='perfis' else 'mtg_')+'isolated_'+uuid.uuid4().hex[:12]
    source=conn.execute('SELECT * FROM audit_mtg.snapshots WHERE snapshot_id=%s',(previous,)).fetchone()
    original=Path(source['source_path'])
    if not original.is_file() or hashlib.sha256(original.read_bytes()).hexdigest()!=source['source_sha256']:
        original=PRIVATE/'source-workbooks'/source['source_filename']
    assert hashlib.sha256(original.read_bytes()).hexdigest()==source['source_sha256']
    directory=PRIVATE/'macro-context';directory.mkdir(exist_ok=True)
    path=directory/(target+'.xlsm')
    if closed:
        positions=[r['excel_row'] for r in conn.execute('SELECT excel_row FROM raw_mtg.plan_production_rows WHERE snapshot_id=%s AND production_order_no=%s',(previous,of))]
        assert positions
        with ZipFile(original) as src,ZipFile(path,'w') as dest:
            for entry in src.infolist():
                data=src.read(entry.filename)
                if entry.filename=='xl/worksheets/sheet1.xml':
                    column='AB' if area=='perfis' else 'AH';pending=set(positions)
                    def replace_cell(match):
                        row=int(match[1])
                        if row not in pending:return match[0]
                        pending.remove(row)
                        return b'<c r="'+(column+str(row)).encode()+b'" t="inlineStr"><is><t>X</t></is></c>'
                    data=re.sub(rb'<c\b[^>]*\br="'+column.encode()+rb'(\d+)"[^>]*(?:/>|>.*?</c>)',replace_cell,data)
                    for row in pending:
                        cell=(column+str(row)).encode();replacement=b'<c r="'+cell+b'" t="inlineStr"><is><t>X</t></is></c>'
                        data,count=re.subn(rb'(<row\b[^>]*\br="'+str(row).encode()+rb'"[^>]*>.*?)(</row>)',lambda m:m[1]+replacement+m[2],data)
                        assert count==1,(area,row,count)
                dest.writestr(entry,data)
    else:shutil.copyfile(original,path)
    with ZipFile(path,'a') as archive:archive.comment=('Isolated acceptance context '+target).encode()
    source_hash=hashlib.sha256(path.read_bytes()).hexdigest()
    for table in ('audit_mtg.snapshots','raw_mtg.plan_production_rows','analytics_mtg.kanban_plan_lines',
                  'core_mtg.customers','core_mtg.sales_orders','core_mtg.production_orders',
                  'core_mtg.machines','core_mtg.production_lines','raw_mtg.cpis_rows','raw_mtg.other_sheet_rows','raw_mtg.machine_rows','raw_mtg.workbook_sheets',
                  'planning_mtg.raw_workbook_evidence'):
        schema,name=table.split('.')
        kind=conn.execute('SELECT table_type FROM information_schema.tables WHERE table_schema=%s AND table_name=%s',(schema,name)).fetchone()
        if kind['table_type']=='VIEW':continue
        cols=[r['column_name'] for r in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s AND is_generated='NEVER' ORDER BY ordinal_position",(schema,name))]
        expressions=[];params=[]
        for k in cols:
            if k=='snapshot_id':expressions.append('%s');params.append(target)
            elif k=='loaded_at' and table=='audit_mtg.snapshots':expressions.append('now()')
            elif k=='source_sha256':expressions.append('%s');params.append(source_hash)
            elif k=='source_path':expressions.append('%s');params.append(str(path))
            elif k=='source_size_bytes':expressions.append('%s');params.append(path.stat().st_size)
            elif k=='source_line_id' or table=='analytics_mtg.kanban_plan_lines' and k=='plan_key':
                expressions.append('%s||'+k);params.append(target+':')
            else:expressions.append(k)
        conn.execute('INSERT INTO '+table+'('+','.join(cols)+') SELECT '+','.join(expressions)+' FROM '+table+' WHERE snapshot_id=%s',params+[previous])
    if closed:
        conn.execute("UPDATE raw_mtg.plan_production_rows SET closed_x=true,row_data=row_data||%s WHERE snapshot_id=%s AND production_order_no=%s",(Jsonb({'Fechado':'X'}),target,of))
        conn.execute('UPDATE core_mtg.production_lines SET closed_x=true WHERE snapshot_id=%s AND production_order_no=%s',(target,of))
    # As in the real importer, refresh statistics after loading a complete
    # snapshot. Otherwise PostgreSQL can choose a quadratic view join while
    # assuming the new snapshot contains one row.
    for table in ('audit_mtg.snapshots','raw_mtg.plan_production_rows','core_mtg.production_lines','core_mtg.production_orders','core_mtg.customers'):
        conn.execute('ANALYZE '+table)
    assert conn.execute('SELECT 1 FROM analytics_mtg.kanban_plan_lines WHERE snapshot_id=%s LIMIT 1',(target,)).fetchone()
    return target


def main():
    started=datetime.now(timezone.utc).isoformat()
    report={'at':started,'scope':'Complete isolated snapshots and XLSM copies; operational workbooks untouched. Only selected closure cells differ.','steps':[]}
    path=F/'t9-macro-revision-trial.json'
    if path.exists():path.rename(F/('t9-macro-revision-trial-history-'+str(time.time_ns())+'.json'))
    with planning.connect(readonly=True) as c:
        assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
        baseline={'perfis':'mtg2_bf1cd6a25986791e','cantoneiras':'mtg_397c8ea5e42480c1'}
        targets=[]
        for area in planning.AREAS:
            g=query.generation(c,area);sql,args=query.source(g)
            r=c.execute("SELECT m.row_key,c.values_json->>'of' of"+sql+" AND m.planning_active AND c.detail->>'origin'='macro' ORDER BY m.row_key LIMIT 1",args).fetchone()
            targets.append({'area':area,**r})
    report.update(baseline=baseline,targets=targets)
    try:
        for closed in (True,False):
            t=time.perf_counter()
            with planning.connect() as c:
                revisions={x['area']:publish(c,x['area'],baseline[x['area']],x['of'],closed) for x in targets}
            step={'state':'closed' if closed else 'reopened','source_revisions':revisions,'source_publication_seconds':time.perf_counter()-t,**refresh()}
            step['identities']=[]
            for target in targets:
                rows=query.listing({'area':target['area'],'population':'all','selected':[target['row_key']]})['rows']
                assert len(rows)==1,(target,len(rows))
                row=rows[0];assert row['values']['planning_active'] is (not closed)
                step['identities'].append({'requested':target['row_key'],'key':row['key'],'aliases':row.get('selection_aliases')})
            step['within_10_seconds']=step['central_seconds']<=10
            report['steps'].append(step);print(json.dumps(step),flush=True)
    finally:
        if not report['steps'] or report['steps'][-1]['state']!='reopened':
            with planning.connect() as c:
                for target in targets:publish(c,target['area'],baseline[target['area']],target['of'],False)
            report['recovery']=refresh()
        report['result']='passed' if len(report['steps'])==2 and all(s['within_10_seconds'] for s in report['steps']) else 'incomplete'
        path.write_text(json.dumps(report,indent=2,default=str)+'\n')


if __name__=='__main__':main()
