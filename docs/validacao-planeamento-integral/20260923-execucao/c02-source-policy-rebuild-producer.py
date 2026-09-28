from pathlib import Path
import json,os,hashlib,time
from datetime import datetime,timezone
folder=Path('docs/validacao-planeamento-integral/20260923-execucao')
os.environ['MES_PG_DSN']=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
os.environ['MES_DATA_DIR']='/tmp/planning-integral-data'
os.environ['MES_DOSSIER_WORKER_DISABLED']='1'
for proc in Path('/proc').iterdir():
 if not proc.name.isdigit():continue
 try:
  cmd=(proc/'cmdline').read_bytes()
  if b'app.raw.worker' not in cmd:continue
  env=dict(v.decode().split('=',1) for v in (proc/'environ').read_bytes().split(b'\0') if b'=' in v)
  assert env.get('MES_PG_DSN')!=os.environ['MES_PG_DSN'],'Isolated worker is live'
 except (FileNotFoundError,PermissionError,ProcessLookupError):pass
from app import planning
from app.raw import projection,query,capacity
from scripts.audit_planning_selected_ocr import source_fingerprints

def read_values(c,area):
 g=query.generation(c,area);base,args=query.source(g)
 rows={r['row_key']:r['values_json'] for r in c.execute('SELECT m.row_key,c.values_json'+base,args)}
 return g['id'],rows
r={'at':datetime.now(timezone.utc).isoformat(),'environment':'planning_integral clone, rebuild only','before':{},'after':{},'timings':{},'value_changes':[],'unexpected_changes':[]}
values={}
with planning.connect(readonly=True) as c:
 assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
 r['sources_before']=source_fingerprints(c)
 for area in planning.AREAS:r['before'][area],values[area]=read_values(c,area)
for area in planning.AREAS:
 t=time.monotonic();projection.rebuild(area,force=True);r['timings'][area]=time.monotonic()-t;print(area,'rebuilt',r['timings'][area],flush=True)
t=time.monotonic();capacity.rebuild();r['timings']['capacity']=time.monotonic()-t;print('capacity rebuilt',r['timings']['capacity'],flush=True)
with planning.connect(readonly=True) as c:
 for area in planning.AREAS:
  r['after'][area],current=read_values(c,area)
  assert set(current)==set(values[area]),'Identity changed'
  for key,old in values[area].items():
   new=current[key]
   changed={field:{'before':old.get(field),'after':new.get(field)} for field in set(old)|set(new) if old.get(field)!=new.get(field)}
   if changed:
    r['value_changes'].append({'area':area,'key':key,'fields':changed})
    if changed:r['unexpected_changes'].append(r['value_changes'][-1])
 r['sources_after']=source_fingerprints(c)
assert r['sources_after']==r['sources_before']
r['result']='passed' if not r['unexpected_changes'] else 'failed'
(folder/'c02-source-policy-rebuild.json').write_text(json.dumps(r,ensure_ascii=False,indent=2,default=str)+'\n')
print('Result',r['result'],'changed rows',len(r['value_changes']),'unexpected',len(r['unexpected_changes']),flush=True)
assert not r['unexpected_changes'],r['unexpected_changes'][:2]
