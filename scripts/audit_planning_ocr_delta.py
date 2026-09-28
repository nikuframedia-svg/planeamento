"""Whole-population equivalence after real OCR deltas in the isolated copy."""
import os,json,time,hashlib,argparse
from pathlib import Path
from datetime import datetime,timezone
folder=Path('docs/validacao-planeamento-integral/20260923-execucao')
os.environ['MES_PG_DSN']=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
from app import planning,planning_needs as needs
from app.raw import projection,capacity_revision,query
parser=argparse.ArgumentParser()
parser.add_argument('--output',default='c05-ocr-delta-full-comparison.json')
options=parser.parse_args()
report={'at':datetime.now(timezone.utc).isoformat(),'environment':'isolated full copy localhost44164/planning_integral',
 'method':'Every content field in planning, production, production_hours, orders and three capacity datasets; only F12 publication epoch excluded. Compare the existing publication with forced complete core and capacity calculation.',
 'before':{},'after':{},'differences':[]}
def capture(target):
 output={}
 with planning.connect(readonly=True) as c:
  c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
  assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
  assert not c.execute("SELECT 1 FROM mes_kanban.validated_sheets WHERE sheet_uid LIKE 'c05-ocr-live-isolated-%%'").fetchone()
  for area in planning.AREAS:
   for dataset in ['planning','production','production_hours','orders','capacity_items','capacity','capacity_machines']:
    g=query.generation(c,area,dataset=dataset);base,args=query.source(g);key=dataset+':'+area
    target[key]={'version':g['id'],'count':g['row_count'],'metadata':g['metadata']};data={}
    with c.cursor(name='compare_'+area+'_'+dataset) as cursor:
     cursor.execute('SELECT m.row_key,c.values_json,c.detail'+base,args)
     for r in cursor:
      for rule in r['detail'].get('calculation',{}).get('rules',{}).values():rule.pop('capacity_fingerprint',None)
      data[r['row_key']]=hashlib.sha256(json.dumps(r,sort_keys=True,default=str).encode()).hexdigest()
    output[key]=data
 return output
before=capture(report['before']);report['full_seconds']={}
for area in planning.AREAS:
 t=time.monotonic();projection.rebuild(area,force=True);report['full_seconds'][area]=time.monotonic()-t;print(area,report['full_seconds'][area],flush=True)
t=time.monotonic();capacity_revision.rebuild(force=True);report['full_seconds']['capacity']=time.monotonic()-t
print('capacity',report['full_seconds']['capacity'],flush=True)
after=capture(report['after'])
for dataset,data in before.items():
 for key in data.keys()|after[dataset].keys():
  if data.get(key)!=after[dataset].get(key):report['differences'].append({'dataset':dataset,'key':key,'before_hash':data.get(key),'after_hash':after[dataset].get(key)})
report['rows_compared']=sum(len(x) for x in before.values());report['result']='passed' if not report['differences'] else 'failed'
(folder/options.output).write_text(json.dumps(needs.serial(report),ensure_ascii=False,indent=2)+'\n')
print(report['rows_compared'],'rows;',len(report['differences']),'differences',flush=True)
assert not report['differences'],report['differences'][:5]
