from pathlib import Path
import json,os,time,hashlib
from pydantic_core import from_json
os.environ['MES_PG_DSN']=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
from app import planning
r={'fields':0,'mismatches':[],'timings':{'standard':0,'pydantic':0}}
with planning.connect(readonly=True) as c:
 c.execute('SET LOCAL jit=off')
 with c.cursor(name='decode_audit') as cur:
  cur.execute("SELECT m.row_key,c.values_json::text,c.detail::text FROM planning_mtg.raw_members m JOIN planning_mtg.raw_capacity_contents c ON c.hash=m.content_hash WHERE m.dataset IN ('planning:perfis','planning:cantoneiras') AND m.last_generation IS NULL")
  for row in cur:
   for field in ['values_json','detail']:
    s=row[field];t=time.perf_counter();a=json.loads(s);r['timings']['standard']+=time.perf_counter()-t
    t=time.perf_counter();b=from_json(s);r['timings']['pydantic']+=time.perf_counter()-t
    r['fields']+=1
    if a!=b or json.dumps(a,sort_keys=True)!=json.dumps(b,sort_keys=True):r['mismatches'].append({'key':row['row_key'],'field':field})
r['result']='passed' if not r['mismatches'] else 'failed'
Path('docs/validacao-planeamento-integral/20260923-execucao/t4-json-decoder-parity.json').write_text(json.dumps(r,indent=2));print(json.dumps(r))
