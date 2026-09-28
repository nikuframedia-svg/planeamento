from pathlib import Path
import gzip,json,os,hashlib
f=Path('docs/validacao-planeamento-integral/20260923-execucao')
hours=json.loads((f/'c04-actual-hours-current.json').read_text())
history=json.loads((f/'c10-historical-cohorts-final.json').read_text())
assert hours['result']==history['result']=='passed'
fixture={'actual':[],'historical':[], 'input_proofs':{n:hashlib.sha256((f/n).read_bytes()).hexdigest() for n in ('c04-actual-hours-current.json','c10-historical-cohorts-final.json')}}
for area in ('perfis','cantoneiras'):
 for kind in ('known','partial'):
  wanted=next(w for w in hours['weeks'] if area in w['areas'] and w['year'] and w['week'] and
              ((w['expected'] is not None and any(len(e['sheets'])>0 and e['origin']=='Manual' for e in w['declarations'])) if kind=='known' else w['expected'] is None and w['coverage']['sum_known']))
  fixture['actual'].append({'area':area,'kind':kind,**wanted})
positive={}
with gzip.open(f/history['ledger']['file'],'rt') as stream:
 for line in stream:
  row=json.loads(line)
  if row['expected']['value'] is not None:
   for hash_value in row['context']['hashes']:positive[hash_value]=row
os.environ['MES_PG_DSN']=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
from app import planning
from app.raw import query
with planning.connect(readonly=True) as c:
 assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
 for area in planning.AREAS:
  gen=query.generation(c,area);base,args=query.source(gen)
  for row in c.execute("SELECT m.row_key,c.values_json,c.detail->'calculation'->'operation_estimates' estimates"+base+" AND c.values_json->>'planning_active'='true'",args):
   selected=next((e for e in row['estimates'] or [] if e.get('source')=='Histórico' and e.get('hours') and e.get('history_hash') in positive),None)
   if not selected:continue
   expected=positive[selected['history_hash']]['expected']
   fixture['historical'].append({'area':area,'key':row['row_key'],'of':row['values_json']['of'],'reference':row['values_json']['component_ref'],
                                'generation':gen['id'],'operation':selected['operation'],'hash':selected['history_hash'],'expected':expected})
   break
assert len(fixture['historical'])==2
(f/'c10-cohorts-browser-fixture.json').write_text(json.dumps(fixture,ensure_ascii=False,indent=2)+'\n')
print('Four actual-time and two historical-rate cases prepared from independent expected results.')
