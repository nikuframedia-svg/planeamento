"""Compare incremental values with a full rebuild on the integral clone only."""
import argparse,gzip,hashlib,json,os,time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path

F=Path('docs/validacao-planeamento-integral/20260923-execucao')
P=Path('/home/luis/.local/state/planning-backups/integral-20260923')
DATASETS=['planning','production','production_hours','orders','capacity','capacity_items','capacity_machines']


def snapshot():
    from app import planning,planning_needs as needs
    from app.raw import query
    out={};aliases={};gens={}
    with planning.connect(readonly=True) as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ');c.execute('SET LOCAL jit=off')
        assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
        for area in planning.AREAS:
            for dataset in DATASETS:
                gen=query.generation(c,area,dataset=dataset);sql,args=query.source(gen);key=dataset+':'+area;rows={}
                for row in c.execute("SELECT m.row_key,c.values_json,c.detail->>'need_id' need_id,c.detail->>'plan_key' plan_key,c.detail->>'planning_key' planning_key"+sql,args):
                    logical=row['row_key']
                    if dataset=='planning':
                        logical=str(row['need_id']) if row['need_id'] else 'excel:'+str(row['plan_key']).rsplit(':',1)[-1]
                        aliases[row['row_key']]=logical
                    elif dataset=='capacity_items':
                        logical=aliases[row['planning_key']]+':'+str(row['values_json']['operation'])+':'+str(row['values_json']['machine_key'])
                    assert logical not in rows,(key,logical)
                    rows[logical]=needs.serial(row['values_json'])
                out[key]=rows;gens[key]={'id':gen['id'],'rows':len(rows),'metadata':needs.serial(gen['metadata'])}
    return out,gens


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--resume-core',action='store_true');parser.add_argument('--compare-saved-before',action='store_true');args=parser.parse_args()
    os.environ['MES_PG_DSN']=json.loads((P/'isolated.json').read_text())['dsn'];os.environ['MES_DATA_DIR']='/tmp/planning-integral-data';os.environ['MES_RAW_DRIVE_CHECK']='0'
    from app import planning,planning_needs as needs
    from app.raw import projection,capacity_revision as capacity,query
    report={'at':datetime.now(timezone.utc).isoformat(),'environment':'planning_integral; forced reconstruction',
            'method':'Compare every value of all seven datasets in both areas. Import snapshot keys are mapped to the same need or Excel line; no numeric field is ignored.',
            'comparisons':{},'failures':[]}
    if args.resume_core or args.compare_saved_before:
        file=F/'t10-rebuild-before-values.json.gz'
        with gzip.open(file,'rt') as f:before=json.load(f)
        cutoff=datetime.fromtimestamp(file.stat().st_mtime,timezone.utc)
        report['before']={};report['rebuilds']=[]
        with planning.connect(readonly=True) as c:
            for dataset in before:
                gen=c.execute('SELECT * FROM planning_mtg.raw_generations WHERE dataset=%s AND created_at<=%s ORDER BY id DESC LIMIT 1',(dataset,cutoff)).fetchone()
                assert gen;report['before'][dataset]={'id':gen['id'],'rows':gen['row_count'],'metadata':needs.serial(gen['metadata'])}
            for area in planning.AREAS if args.resume_core else []:
                gen=query.generation(c,area)
                assert gen['created_at']>cutoff and gen['metadata']['aggregates_pending'] and gen['metadata']['calculation_scope']=='full'
                assert gen['metadata']['core_source_fingerprint']==projection.fingerprint(c,area)
                report['rebuilds'].append({'area':area,'generation':gen['id'],'seconds':None})
        report['resume_reason']='Resume committed core reconstructions after the harness capacity-wrapper error.' if args.resume_core else 'Repeat the reconstruction after correcting local description parity; compare with the original saved incremental values.'
    else:
        before,report['before']=snapshot()
        with gzip.open(F/'t10-rebuild-before-values.json.gz','wt') as f:json.dump(before,f,sort_keys=True)
    def build(area):
        start=time.monotonic();g=projection.rebuild(area,force=True);return {'area':area,'seconds':time.monotonic()-start,'generation':g['id']}
    if not args.resume_core:
        with ThreadPoolExecutor(max_workers=2) as pool:report['rebuilds']=list(pool.map(build,['perfis','cantoneiras']))
    (F/'t10-full-rebuild-core.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
    start=time.monotonic();capacity.rebuild(force=True);report['capacity_seconds']=time.monotonic()-start
    after,report['after']=snapshot()
    for dataset,old in before.items():
        new=after[dataset];added=sorted(new.keys()-old.keys());removed=sorted(old.keys()-new.keys());changes=[]
        for key in sorted(old.keys()&new.keys()):
            diff={field:{'before':old[key].get(field),'after':new[key].get(field)} for field in old[key].keys()|new[key].keys() if old[key].get(field)!=new[key].get(field)}
            if diff:changes.append({'key':key,'differences':diff})
        report['comparisons'][dataset]={'before':len(old),'after':len(new),'added':added,'removed':removed,'changes':changes}
        if added or removed or changes:report['failures'].append(dataset)
    report['result']='failed' if report['failures'] else 'passed'
    (F/'t10-full-rebuild.json').write_text(json.dumps(report,indent=2,ensure_ascii=False,default=str)+'\n')
    print(report['result'],report['failures'],report['rebuilds'],report['capacity_seconds'],flush=True)
    assert not report['failures']


if __name__=='__main__':main()
