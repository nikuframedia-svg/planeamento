"""Compare legacy order membership with every immutable published RAW identity."""
import os,json,hashlib
from pathlib import Path
from collections import defaultdict
from datetime import datetime,timezone

folder=Path('docs/validacao-planeamento-integral/20260923-execucao')
os.environ['MES_PG_DSN']=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
from app import planning,planning_hub as hub,planning_order_population as membership
from app.raw import query
from scripts.audit_planning_selected_ocr import source_fingerprints

report={'at':datetime.now(timezone.utc).isoformat(),'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'environment':'planning_integral isolated clone, read only','method':'All current source identities compared to immutable RAW generations published before this change; complete per-OF per-area counts in all scopes',
    'areas':{},'scopes':{},'failures':[]}
expected={scope:defaultdict(lambda:defaultdict(int)) for scope in ('active','history','all')}
with planning.connect(readonly=True) as c:
    c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
    assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
    report['sources_before']=source_fingerprints(c)
    members,fallback=membership.read(c,hub._latest_snapshots(c))
    copies=defaultdict(list)
    for row in hub._order_rows(c,hub._direct_version(c),'',None):copies[row['production_order_no']].append(row)
    contexts={**fallback,**{of:hub._order_summary(rows) for of,rows in copies.items()}}
    membership.summarize(members,contexts)
    actual={(m['area'],m['key']):m for m in members}
    seen=set()
    for area in ('perfis','cantoneiras'):
        gen=query.generation(c,area);base,args=query.source(gen)
        rows=c.execute("SELECT m.row_key,c.values_json->>'of' of,(c.values_json->>'planning_active')::boolean active"+base,args).fetchall()
        report['areas'][area]={'generation':gen['id'],'rows':len(rows),'active':sum(r['active'] for r in rows)}
        for row in rows:
            identity=(area,row['row_key']);seen.add(identity);member=actual.get(identity)
            if not member or (member['of'],member['population']['active'])!=(row['of'],row['active']):
                report['failures'].append({'identity':identity,'expected':row,'actual':member})
            expected['all'][row['of']][area]+=1
            expected['active' if row['active'] else 'history'][row['of']][area]+=1
    for identity in set(actual)-seen:report['failures'].append({'unexpected_identity':identity})
    report['source_members']=len(members)
    report['supplemental_orders']={of:{'origin':r['administrative_origin']} for of,r in fallback.items() if of not in copies}
for scope in expected:
    result=hub._order_population(population=scope)
    observed={r['of']:r['plan'] for r in result['orders'] if r['plan']}
    target={of:dict(counts) for of,counts in expected[scope].items()}
    for of in set(observed)|set(target):
        if observed.get(of)!=target.get(of):report['failures'].append({'scope':scope,'of':of,'expected':target.get(of),'actual':observed.get(of)})
    report['scopes'][scope]={'orders_with_pieces':len(observed),'administrative_orders':len(result['orders'])-len(observed),
        'pieces':sum(sum(r.values()) for r in observed.values()),'population_hash':hashlib.sha256(json.dumps(sorted(observed.items(),key=lambda r:str(r[0])),sort_keys=True).encode()).hexdigest()}
with planning.connect(readonly=True) as c:report['sources_after']=source_fingerprints(c)
assert report['sources_before']==report['sources_after']
report['result']='passed' if not report['failures'] else 'failed'
(folder/'c06-complete-orders-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n')
print(json.dumps({k:report[k] for k in ['result','areas','scopes','source_members']},default=str))
assert not report['failures'], report['failures'][:3]
