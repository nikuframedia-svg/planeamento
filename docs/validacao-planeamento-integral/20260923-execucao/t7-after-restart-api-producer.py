from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,urllib.request

F=Path('docs/validacao-planeamento-integral/20260923-execucao');base='http://127.0.0.1:18113'
report={'at':datetime.now(timezone.utc).isoformat(),'base':base,'checks':{},
    'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
def query(area,ids):
    p=urllib.request.Request(base+'/planeamento/api/raw/consultas',
        data=json.dumps({'area':area,'population':'all','selected':ids}).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(p,timeout=15) as r:return json.load(r)
fixture=json.loads((F/'c03-complete-run.json').read_text())
for area in ['perfis','cantoneiras']:
    ids=[p['id'] for p in fixture['areas'][area]['pieces']];r=query(area,ids)
    assert len(r['rows'])==2 and not r['aggregates_pending']
    assert {x['key'] for x in r['rows']}==set(ids)
    assert {x['values']['remaining'] for x in r['rows']}=={15,8}
    report['checks'][area]={'version':r['version'],'ids':ids,'remaining':[x['values']['remaining'] for x in r['rows']]}
expected=json.loads((F/'c00-current-v01.json').read_text())['expected_from_verified_central_events']
r=query('perfis',list(expected));assert len(r['rows'])==3
report['checks']['OF264774']=[]
for row in r['rows']:
    v=row['values']
    for field,value in expected[row['key']].items():assert v[field]==value,(row['key'],field)
    if str(v['id'])=='34512':assert v['bars']==0
    report['checks']['OF264774'].append({'key':row['key'],**{k:v.get(k) for k in ['of','id','component_ref','quantity_required','cut','boc','remaining','boc_remaining','bars']}})
with urllib.request.urlopen(base+'/static/need_editor.js',timeout=15) as response:content=response.read()
assert hashlib.sha256(content).hexdigest()==hashlib.sha256(Path('app/web/static/need_editor.js').read_bytes()).hexdigest()
report['checks']['served_editor_sha256']=hashlib.sha256(content).hexdigest();report['result']='passed'
(F/'t7-after-restart-api.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print('Current isolated API, retained C03 identities, OF264774 and served editor verified.')
