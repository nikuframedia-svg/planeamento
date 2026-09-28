import os,json,hashlib,argparse
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--output',default='c06-independent-audit.json');options=parser.parse_args()
cfg=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text());os.environ['MES_PG_DSN']=cfg['dsn']
from app import planning
from app.raw import query
out={'environment':'isolated full copy localhost:44164','method':'Independent source lookup per piece; no call to planning_population.classify or active_sql','areas':{}}
with planning.connect(readonly=True) as c:
 c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
 gens={a:query.generation(c,a) for a in planning.AREAS}
 snapshots=[g['metadata']['snapshot']['snapshot_id'] for g in gens.values()]
 cpis={}
 direct=c.execute('SELECT id FROM cpis_mtg.versions ORDER BY id DESC LIMIT 1').fetchone()
 if direct:
  source=c.execute('SELECT production_order_no,status FROM cpis_mtg.orders WHERE version_id=%s',(direct['id'],)).fetchall()
 else:
  source=c.execute('SELECT production_order_no,status FROM raw_mtg.cpis_rows WHERE snapshot_id=ANY(%s)',(snapshots,)).fetchall()
 for r in source:
  cpis.setdefault(r['production_order_no'],set()).add(str(r['status'] or '').strip().lower())
 active=set();closed=set()
 for area,gen in gens.items():
  source=c.execute("SELECT source_line_id,closed_x,row_data->>'Fechado' mark FROM raw_mtg.plan_production_rows WHERE snapshot_id=%s",(gen['metadata']['snapshot']['snapshot_id'],)).fetchall()
  macro={r['source_line_id']:r for r in source}
  base,args=query.source(gen);rows=c.execute('SELECT m.row_key,m.planning_machine,m.planning_active,c.values_json,c.detail'+base,args).fetchall()
  failures=[];counts={'active':0,'history':0};locals_count=0
  for r in rows:
   v,d=r['values_json'],r['detail'];source=macro.get(d.get('plan_key'))
   macro_closed=bool(source and (source['closed_x'] is True or str(source['mark'] or '').strip().lower() in ('x','true','1')))
   cpis_closed=bool(cpis.get(v['of'],set())&{'fechada','fechado'})
   expected=not(macro_closed or cpis_closed)
   if not source:locals_count+=1
   if expected != v['planning_active']:failures.append({'key':r['row_key'],'expected_active':expected,'observed_active':v['planning_active']})
   if r['planning_active']!=expected or r['planning_machine']!=str(v.get('machine') or ''):
    failures.append({'key':r['row_key'],'dependency_index':{'expected_active':expected,'active':r['planning_active'],'expected_machine':v.get('machine') or '', 'machine':r['planning_machine']}})
   counts['active' if expected else 'history']+=1
   (active if expected else closed).add(r['row_key'])
  out['areas'][area]={'version':gen['id'],'snapshot':gen['metadata']['snapshot']['snapshot_id'],'cpis_version':gen['metadata']['cpis_version'],'expected_from_sources':counts,'compared':len(rows),'dependency_index_compared':len(rows),'local_without_macro':locals_count,'mismatches':failures}
  assert not failures, failures[:3]
 for area in planning.AREAS:
  gen=query.generation(c,area,dataset='capacity_items');base,args=query.source(gen)
  rows=c.execute("SELECT c.detail->>'planning_key' piece"+base,args).fetchall()
  excluded=[r['piece'] for r in rows if r['piece'] not in active or r['piece'] in closed]
  out['areas'][area]['capacity_version']=gen['id'];out['areas'][area]['capacity_closed_or_missing_pieces']=excluded
  assert not excluded,excluded[:3]
 identities={}
 for table,keys in [('raw_mtg.plan_production_rows','snapshot_id,source_line_id'),('mes_kanban.production_records','id,sheet_uid,row_index'),('mes_kanban.production_record_plan_refs','production_record_id,plan_key'),('mes_kanban.validated_sheets','sheet_uid'),('planning_mtg.need_sources','need_id,kind,source_id'),('planning_mtg.needs','id'),('planning_mtg.records','id')]:
  rows=c.execute('SELECT '+keys+' FROM '+table+' ORDER BY '+keys).fetchall()
  identities[table]={'count':len(rows),'identity_sha256':hashlib.sha256(json.dumps(rows,sort_keys=True,default=str).encode()).hexdigest()}
 out['identities']=identities
(Path('docs/validacao-planeamento-integral/20260923-execucao')/options.output).write_text(json.dumps(out,indent=2,default=str))
print({a:x['compared'] for a,x in out['areas'].items()})
