"""Compare every current incremental result with a forced full clone rebuild."""
import os,json,hashlib,time,argparse,uuid
from pathlib import Path
from datetime import datetime,timezone
folder=Path('docs/validacao-planeamento-integral/20260923-execucao')
os.environ['MES_PG_DSN']=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
from app import planning,planning_needs as needs
from app.raw import query,capacity_revision,objects
parser=argparse.ArgumentParser();parser.add_argument('--exercise',action='store_true');options=parser.parse_args()
report={'at':datetime.now(timezone.utc).isoformat(),'environment':'isolated full copy localhost44164/planning_integral',
        'method':'All row contents in both areas, before and after forced full capacity calculation. Only the capacity provenance epoch in F12 is excluded.',
        'before':{},'after':{},'differences':[]}

def capture(target):
    result={}
    with planning.connect(readonly=True) as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
        for area in planning.AREAS:
            for dataset in ['planning','capacity_items','capacity','capacity_machines']:
                g=query.generation(c,area,dataset=dataset);base,args=query.source(g);key=dataset+':'+area
                target[key]={'version':g['id'],'count':g['row_count'],'source':g['metadata']}
                hashes={}
                with c.cursor(name='rows_'+area+'_'+dataset) as cursor:
                    cursor.execute('SELECT m.row_key,c.values_json,c.detail'+base,args)
                    for r in cursor:
                        for rule in r['detail'].get('calculation',{}).get('rules',{}).values():rule.pop('capacity_fingerprint',None)
                        hashes[r['row_key']]=hashlib.sha256(json.dumps(r,sort_keys=True,default=str).encode()).hexdigest()
                result[key]=hashes
    return result
if options.exercise:
    # Establish the current code's initial publication, then exercise real deltas
    # before comparing them against the independent complete traversal.
    started=time.monotonic();capacity_revision.rebuild(force=True)
    report['initialization_seconds']=time.monotonic()-started
    fixtures=json.loads((folder/'c05-capacity-live-fixtures.json').read_text())
    original=[];report['exercise']=[]
    for area in fixtures['areas']:
        ident=area['resources'][1]['rate']['id']
        with planning.connect(readonly=True) as c:obj=c.execute('SELECT * FROM planning_mtg.raw_objects WHERE id=%s',(ident,)).fetchone()
        original.append(obj)
        objects.save({'request_id':str(uuid.uuid4()),'id':str(obj['id']),'expected_revision':obj['revision'],
            'name':obj['name'],'definition':{**obj['definition'],'value':obj['definition']['value']*1.25}},'rate')
    for restore in [False,True]:
        if restore:
            for obj in original:
                objects.save({'request_id':str(uuid.uuid4()),'id':str(obj['id']),'expected_revision':obj['revision']+1,
                    'name':obj['name'],'definition':obj['definition']},'rate')
        started=time.monotonic();capacity_revision.rebuild();elapsed=time.monotonic()-started
        with planning.connect(readonly=True) as c:
            meta=query.generation(c,'perfis',dataset='capacity')['metadata']
            assert meta['calculation_scope']=='resources'
        report['exercise'].append({'restored':restore,'elapsed_seconds':elapsed,'affected_resources':meta['affected_resources']})
        print('Incremental rate revision',restore,elapsed,flush=True)
before=capture(report['before'])
start=time.monotonic();capacity_revision.rebuild(force=True);report['full_rebuild_seconds']=time.monotonic()-start
print('Forced full capacity calculation',report['full_rebuild_seconds'],flush=True)
after=capture(report['after'])
for dataset in before:
    for key in before[dataset].keys()|after[dataset].keys():
        if before[dataset].get(key)!=after[dataset].get(key):report['differences'].append({'dataset':dataset,'key':key,'before_hash':before[dataset].get(key),'after_hash':after[dataset].get(key)})
report['rows_compared']=sum(len(r) for r in before.values());report['result']='passed' if not report['differences'] else 'failed'
(folder/'c05-capacity-delta-full-comparison.json').write_text(json.dumps(needs.serial(report),ensure_ascii=False,indent=2)+'\n')
print(report['rows_compared'],'rows compared;',len(report['differences']),'differences',flush=True)
assert not report['differences'],report['differences'][:5]
