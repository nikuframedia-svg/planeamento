"""Verify the Perfis writable AH quantity against RAW, form and PDF reading.

Optional rebuilding is allowed only on the explicit full isolated copy. Source
rows are hashed before/after; operational quantities in N are never rewritten.
"""
import argparse,hashlib,json,math,os,time
from datetime import datetime,timezone
from pathlib import Path

FOLDER=Path('docs/validacao-planeamento-integral/20260923-execucao')

def source_number(value):
 try:
  number=float(str(value).replace(',','.'))
  return number if math.isfinite(number) else None
 except (ValueError,TypeError):return None

def main():
 p=argparse.ArgumentParser();p.add_argument('--rebuild',action='store_true');p.add_argument('--output',default='c04-structured-quantity-after.json');args=p.parse_args()
 os.environ['MES_PG_DSN']=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
 from app import planning,planning_needs as needs
 from app.dossiers.cpis import _plan_values
 from app.raw import query,projection,capacity_revision
 def raw_sources(c):
  assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
  return c.execute("SELECT * FROM raw_mtg.plan_production_rows WHERE snapshot_id=%s ORDER BY excel_row",(planning.snapshot(c,'perfis')['snapshot_id'],)).fetchall()
 def digest(rows):return hashlib.sha256(json.dumps(rows,sort_keys=True,default=str).encode()).hexdigest()
 with planning.connect(readonly=True) as c:before=raw_sources(c)
 report={'at':datetime.now(timezone.utc).isoformat(),'environment':'isolated full copy localhost44164','rule':'Perfis writable QTD [un,] (AH), preserving explicit blank; N is fallback only when AH field is absent. Local effective human values remain authoritative.','source_sha256_before':digest(before),'rows':len(before),'timings_seconds':{},'failures':[],'source_disagreements':[]}
 if args.rebuild:
  for area in planning.AREAS:
   start=time.monotonic();projection.rebuild(area);report['timings_seconds'][area]=time.monotonic()-start;print('Rebuilt',area,report['timings_seconds'][area],flush=True)
  start=time.monotonic();capacity_revision.rebuild();report['timings_seconds']['capacity']=time.monotonic()-start;print('Rebuilt capacity',report['timings_seconds']['capacity'],flush=True)
 with planning.connect(readonly=True) as c:
  c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ');after=raw_sources(c)
  assert digest(after)==report['source_sha256_before']
  gen=query.generation(c,'perfis');base,params=query.source(gen)
  published={r['plan_key']:r for r in c.execute("SELECT m.row_key,c.values_json,c.detail->>'plan_key' plan_key,c.detail->>'need_id' need_id"+base,params)}
  report['version']=gen['id'];report['snapshot']=gen['metadata']['snapshot']['snapshot_id'];report['source_sha256_after']=digest(after)
  report['macro_without_local_override']=0;report['local_preparations']=[]
  for src in after:
   raw=src['row_data'];expected=source_number(raw['QTD [un,]'] if 'QTD [un,]' in raw else src['quantity_planned'])
   canonical={**src,'remaining_valid':False,'canonical_remaining':None,'cpis_status':None,'cpis_delivery_date':None}
   form=planning.line_data(canonical,'perfis',{})['values']['quantity_required'];pdf=_plan_values(src)['quantity_required']
   r=published.get(src['source_line_id']);values=r['values_json'] if r else {}
   item={'excel_row':src['excel_row'],'plan_key':src['source_line_id'],'legacy_N':src['quantity_planned'],'structured_AH':raw.get('QTD [un,]'),'expected':expected,'manual_source':form,'pdf_source':pdf,'raw_quantity':values.get('quantity_required'),'active':values.get('planning_active'),'raw_total_area':values.get('section_total'),'cached_AP':raw.get('Área de Seção de Corte [mm2]')}
   if expected!=source_number(src['quantity_planned']):report['source_disagreements'].append(item)
   if form!=expected or pdf!=expected:report['failures'].append(item)
   if not r:report['failures'].append({**item,'reason':'Source row missing from RAW'})
   elif r['need_id']:report['local_preparations'].append({'plan_key':src['source_line_id'],'need_id':r['need_id']})
   else:
    report['macro_without_local_override']+=1
    if values.get('quantity_required')!=expected:report['failures'].append(item)
  # Exercise the real common-manual source reader for each disputed line.
  for item in report['source_disagreements']:
   actual=needs.source_data({'kind':'plan_line','id':item['plan_key']},'perfis',c)
   item['common_manual_source']=actual['values']['quantity_required']
   if item['common_manual_source']!=item['expected']:report['failures'].append(item)
 report['result']='passed' if not report['failures'] else 'failed'
 (FOLDER/args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n')
 print(report['rows'],'source rows;',len(report['source_disagreements']),'N/AH differences;',len(report['failures']),'failures',flush=True)
 if report['failures']:raise SystemExit(1)

if __name__=='__main__':main()
