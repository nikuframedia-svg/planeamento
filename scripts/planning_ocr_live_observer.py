"""Observe committed RAW/capacity rows independently of the browser (100ms poll)."""
import os,json,sys,time,math
from pathlib import Path
os.environ['MES_PG_DSN']=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
from app import planning
area,key,op,remaining,hours=sys.argv[1:];remaining=json.loads(remaining);hours=json.loads(hours)
assert area in planning.AREAS
result={};started=time.monotonic()
with planning.connect(readonly=True) as c:
 assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
 print(json.dumps({'ready':True}),flush=True)
 while time.monotonic()-started<30:
  for dataset,row_key,name,expected in [('planning',key,'raw',remaining),('capacity_items',key+':'+op,'capacity',remaining)]:
   if name in result:continue
   row=c.execute("SELECT m.first_generation,c.values_json FROM planning_mtg.raw_members m JOIN planning_mtg.raw_contents c ON c.hash=m.content_hash WHERE m.dataset=%s AND m.row_key=%s AND m.last_generation IS NULL",(dataset+':'+area,row_key)).fetchone()
   if not row:continue
   v=row['values_json'];quantity=v.get('remaining' if name=='raw' else 'quantity')
   if quantity!=expected:continue
   if name=='capacity':
    actual=v.get('planned_hours')
    if hours is None and actual is not None or hours is not None and (actual is None or not math.isclose(actual,hours,rel_tol=1e-9,abs_tol=1e-9)):continue
   result[name]={'observedMs':time.time()*1000,'membershipGeneration':row['first_generation']}
  if len(result)==2:break
  time.sleep(.1)
assert len(result)==2,result
print(json.dumps({'publication':result,'pollMs':100}),flush=True)
