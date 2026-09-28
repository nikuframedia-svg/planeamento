"""Independent aggregate capacity arithmetic over every published operation.

Checks F12/H01/H02/H04-H08 from immutable item values and original configuration
objects. Selection of operations/rates/historical cohorts remains a separate gate.
No application capacity or productivity calculation functions are called.
"""
from __future__ import annotations
import argparse,gzip,hashlib,json,math,os
from collections import defaultdict,Counter
from datetime import date,datetime,timezone
from pathlib import Path

FOLDER=Path('docs/validacao-planeamento-integral/20260923-execucao')
RULES=['F12','H01','H02','H04','H05','H06','H07','H08']

def same(observed,expected):
 if expected is None:return observed is None
 if isinstance(expected,(int,float)) and not isinstance(expected,bool):
  return isinstance(observed,(int,float)) and not isinstance(observed,bool) and math.isfinite(observed) and abs(observed-expected)<=max(1e-6,abs(expected)*1e-8)
 return observed==expected

def physical(rate,operation):
 if not rate:return None
 value=rate.get('value');method=rate.get('method')
 if not isinstance(value,(int,float)) or value<=0 or not math.isfinite(value) or rate.get('setup_minutes'):return None
 units={'area_hour':'mm²','metres_hour':'m','units_hour':'un.','minutes_unit':'un.'}
 if method not in units:return None
 return str(operation),units[method],60/value if method=='minutes_unit' else value

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--output',default='c04-capacity-arithmetic');args=parser.parse_args()
 assert args.output.replace('-','').isalnum()
 os.environ['MES_PG_DSN']=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
 from app import planning
 from app.raw import query
 from scripts.audit_planning_selected_ocr import source_fingerprints
 report={'at':datetime.now(timezone.utc).isoformat(),'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
  'environment':'planning_integral clone, repeatable read, no writes','rules':RULES,'versions':{},'checks':0,'failures':[],
  'boundary':'Arithmetic from every published operation and direct configuration records. C01/C02 operation selection, F20/G07 item estimates, H03 actual-hour cohorts and H09/H10 rate selection remain separately gated.'}
 ledger=FOLDER/(args.output+'-rows.jsonl.gz')
 def check(name,actual,expected,**context):
  report['checks']+=1
  if not same(actual,expected):report['failures'].append({'check':name,'actual':actual,'expected':expected,**context})
 with planning.connect(readonly=True) as conn,gzip.open(ledger,'wt',encoding='utf8') as out:
  conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
  assert conn.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
  report['sources_before']=source_fingerprints(conn)
  objects={str(r['id']):dict(r) for r in conn.execute("SELECT * FROM planning_mtg.raw_objects WHERE NOT archived AND kind IN ('resource','calendar','rate')")}
  report['configuration_sha256']=hashlib.sha256(json.dumps(objects,sort_keys=True,default=str).encode()).hexdigest()
  resources={key:r for key,r in objects.items() if r['kind']=='resource'}
  calendars={key:r for key,r in objects.items() if r['kind']=='calendar'}
  rates={key:r for key,r in objects.items() if r['kind']=='rate'}
  groups={dataset:{} for dataset in ('capacity','capacity_machines')};plans={};items={}
  for area in planning.AREAS:
   report['versions'][area]={}
   for dataset in ('planning','capacity_items','capacity','capacity_machines'):
    gen=query.generation(conn,area,dataset=dataset);base,params=query.source(gen);report['versions'][area][dataset]=gen['id']
    detail="'{}'::jsonb" if dataset=='planning' else 'c.detail'
    for r in conn.execute('SELECT m.row_key,c.values_json,'+detail+' detail'+base,params):
     key=r['row_key'];row={'key':key,'values':r['values_json'],'detail':r['detail']}
     if dataset=='planning':plans[(area,key)]=row['values'];continue
     if dataset=='capacity_items':
      check('unique_operation_identity',key in items,False,area=area,key=key);items[key]=row;continue
     if key in groups[dataset]:check('shared_resource_same_summary',row,groups[dataset][key],dataset=dataset,key=key)
     else:groups[dataset][key]=row
  by_bucket=defaultdict(list);by_machine=defaultdict(list)
  for row in items.values():
   v=row['values'];by_bucket[v['bucket_key']].append(row);by_machine[v['machine_key']].append(row)
   check('operation_bucket_exists',v['bucket_key'] in groups['capacity'],True,key=row['key'])
   check('operation_machine_exists',v['machine_key'] in groups['capacity_machines'],True,key=row['key'])
   piece=plans.get((v['area'],row['detail']['planning_key']))
   check('active_piece_exists',bool(piece and piece.get('planning_active')),True,key=row['key'])
  expected_weekly={};populations={};known=Counter()
  for dataset,grouped in groups.items():
   counts=Counter()
   for key,row in grouped.items():
    v=row['values'];detail=row['detail'];machine=v['machine_key'];resource=resources.get(machine);rd=resource['definition'] if resource else {}
    live=(by_bucket if dataset=='capacity' else by_machine).get(key,[])
    values=[r['values'].get('planned_hours') for r in live];known_load=[n for n in values if n is not None]
    load=math.fsum(known_load) if len(known_load)==len(values) else None
    chosen=[];available=shift=None
    if dataset=='capacity':
     for ident,obj in calendars.items():
      d=obj['definition']
      if rd.get('confirmed') and d.get('confirmed') and d.get('resource_id')==machine and (d.get('year'),d.get('week'))==(v.get('year'),v.get('week')):chosen.append((ident,d))
     if len(chosen)==1:
      d=chosen[0][1];available=d['shifts']*d['hours_per_shift']-d.get('exception_hours',0);shift=d['hours_per_shift']
      check('calendar_nonnegative',available>=0,True,key=key)
      check('calendar_source_id',(detail.get('source_calendar') or {}).get('id'),chosen[0][0],key=key)
    else:shift=rd.get('shift_hours')
    free=None if available is None or load is None else available-load
    expected={'available_hours':available,'planned_hours':load,'free_hours':free,
      'occupancy':100*load/available if available is not None and available>0 and load is not None else None,
      'equivalent_shifts':load/shift if shift and load is not None else None,
      'capacity_total':None,'capacity_free':None,'lines_total':len(live),'unknown_load':len(values)-len(known_load)}
    selected=[]
    if live:
     selected=[physical((r['detail'].get('applied_rate') or {}).get('rate'),r['values']['operation']) for r in live]
    else:
     # Empty-resource summaries can expose an explicit configured physical rate.
     for obj in rates.values():
      d=obj['definition']
      if d.get('resource_id')!=machine:continue
      if dataset=='capacity':
       if not v.get('year') or not v.get('week'):continue
       monday=date.fromisocalendar(int(v['year']),int(v['week']),1).isoformat()
       if d['valid_from']>monday or d.get('valid_until') and d['valid_until']<monday:continue
      selected.append(physical(d,d.get('operation')) if d.get('confirmed') else None)
    unit=None
    if selected and None not in selected and len(set(selected))==1:
     _,unit,rate=selected[0]
     expected['capacity_total']=available*rate if available is not None else None
     expected['capacity_free']=free*rate if free is not None else None
    for field,value in expected.items():check(field,v.get(field),value,dataset=dataset,key=key)
    check('capacity_unit',detail.get('capacity_unit'),unit,dataset=dataset,key=key)
    coverage=(detail.get('coverage') or {}).get('planned_hours') or {}
    for field,value in {'known':len(known_load),'total':len(values),'sum_known':math.fsum(known_load)}.items():check('load_coverage_'+field,coverage.get(field),value,dataset=dataset,key=key)
    for field,value in expected.items():counts[field+('_known' if value is not None else '_unknown')]+=1
    if dataset=='capacity':expected_weekly[key]=expected
    trace={'dataset':dataset,'key':key,'expected':expected,'observed':v,'physical_unit':unit,
      'calendar_ids':[c[0] for c in chosen],'operation_inputs':[{'key':r['key'],'hours':r['values'].get('planned_hours'),'rate':(r['detail'].get('applied_rate') or {}).get('rate'),'operation':r['values']['operation']} for r in live]}
    out.write(json.dumps(trace,ensure_ascii=False,default=str)+'\n')
   populations[dataset]={'rows':len(grouped),'coverage':dict(counts)}
  primary=0
  for item in items.values():
   v=item['values']
   if not v['primary_operation']:continue
   primary+=1;expected=expected_weekly[v['bucket_key']]['occupancy'];piece=plans[(v['area'],item['detail']['planning_key'])]
   check('F12_independent_aggregate',piece.get('hours_pct'),expected,key=item['key'])
   known[v['area']+('_known' if expected is not None else '_unknown')]+=1
   out.write(json.dumps({'rule':'F12','item':item['key'],'piece':item['detail']['planning_key'],'bucket':v['bucket_key'],'expected':expected,'observed':piece.get('hours_pct')})+'\n')
  report.update(populations=populations,operation_items=len(items),raw_pieces=len(plans),primary_operations=primary,F12_coverage=dict(known))
  report['sources_after']=source_fingerprints(conn)
  check('sources_preserved',report['sources_after'],report['sources_before'])
 report['ledger']={'file':ledger.name,'sha256':hashlib.sha256(ledger.read_bytes()).hexdigest()}
 report['result']='failed' if report['failures'] else 'passed'
 (FOLDER/(args.output+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n')
 print(report['result'],report['checks'],'checks',report['operation_items'],'operations',report['primary_operations'],'primary',len(report['failures']),'differences',flush=True)
 if report['failures']:raise SystemExit(1)

if __name__=='__main__':main()
