"""Synthetic central OCR revisions in the isolated acceptance clone only."""
import os,json,time,argparse
from pathlib import Path
from psycopg.types.json import Jsonb
folder=Path('docs/validacao-planeamento-integral/20260923-execucao')
os.environ['MES_PG_DSN']=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
from app import planning,planning_needs as needs
from app.raw import query
p=argparse.ArgumentParser();p.add_argument('area',choices=planning.AREAS);p.add_argument('action',choices=['inspect','insert','correct','remove']);o=p.parse_args()
keys={'perfis':'macro:mtg2_bf1cd6a25986791e:plan:5388','cantoneiras':'macro:mtg_397c8ea5e42480c1:plan:62819'}
uid='c05-ocr-live-isolated-'+o.area
with planning.connect() as c:
 assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
 gen=query.generation(c,o.area);base,args=query.source(gen)
 data=c.execute('SELECT c.values_json,c.detail'+base+' AND m.row_key=%s',args+[keys[o.area]]).fetchone();v=data['values_json'];detail=data['detail']
 previous=c.execute('SELECT id,quantity,hours_worked FROM mes_kanban.production_records WHERE sheet_uid=%s',(uid,)).fetchone()
 rid=previous['id'] if previous else None
 if o.action=='insert':
  assert previous is None,'Remove only the earlier synthetic trial before repeating'
  app='kanban-mes-mtg2' if o.area=='perfis' else 'kanban-mes'
  c.execute("INSERT INTO mes_kanban.validated_sheets(sheet_uid,sheet_date,template_name,family,operator_name,image_sha256,raw_extraction,sheet_data,validated_by,source_app) VALUES (%s,'2026-09-22','C05 isolated test',%s,'Isolated test','c05-synthetic-not-factory','{}','{}','Isolated test',%s)",(uid,o.area,app))
  rid=c.execute("""INSERT INTO mes_kanban.production_records(sheet_uid,row_index,sheet_date,family,operator_name,production_order,quantity,machine,model_ref,length_mm,profile_type,matched_plan_key,plan_snapshot_id,validated_at,hours_worked,extra)
   VALUES (%s,0,'2026-09-22',%s,'Isolated test',%s,10,%s,%s,%s,%s,%s,%s,now(),2,%s) RETURNING id""",
   (uid,o.area,v['of'],v['machine'],v['component_ref'],v['length_mm'],v['profile'],detail['plan_key'],gen['metadata']['snapshot']['snapshot_id'],Jsonb({'operation_code':v['operation'],'test_scope':'C05 isolated copy only'}))).fetchone()['id']
 elif o.action=='correct':
  assert previous
  c.execute('UPDATE mes_kanban.production_records SET quantity=25,hours_worked=4 WHERE id=%s AND sheet_uid=%s',(rid,uid))
 elif o.action=='remove':
  assert previous
  c.execute('DELETE FROM mes_kanban.production_records WHERE id=%s AND sheet_uid=%s',(rid,uid))
  c.execute('DELETE FROM mes_kanban.validated_sheets WHERE sheet_uid=%s',(uid,))
 # This event is the transaction commit, not an application save response.
 c.commit();committed=time.time()*1000
 print(json.dumps(needs.serial({'area':o.area,'action':o.action,'committedMs':committed,'key':keys[o.area],
    'record_id':rid,'sheet_uid':uid,'version_before':gen['id'],'values_before':v,
    'hours_formula':'remaining / 20 units per hour' if o.area=='perfis' else 'remaining * 0.15 metres / (produced * 0.15 metres / worked hours); OCR historical rate precedes Excel 120 metres per hour'})))
