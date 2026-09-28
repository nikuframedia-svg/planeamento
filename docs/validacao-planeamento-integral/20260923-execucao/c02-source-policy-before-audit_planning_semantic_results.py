"""Independent F01/F21/G12 audit from inputs and selected production counters.

Does not call the application calculation/description/deadline functions.
Counter provenance is a separate C01/C02 acceptance gate.
"""
from __future__ import annotations
import argparse,gzip,hashlib,json,math,os,re
from collections import Counter
from datetime import date,datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo

FOLDER=Path('docs/validacao-planeamento-integral/20260923-execucao')
DIMENSIONS={'outer_diameter_mm':('Ø','mm'),'width_mm':('Largura','mm'),
 'height_mm':('Altura','mm'),'thickness_mm':('Esp.','mm'),'length_mm':('Comp.','mm'),'angle_deg':('Ângulo','°')}

def numeric(value):
 if isinstance(value,bool):return None
 try:
  n=float(str(value).replace(',','.'))
  return n if math.isfinite(n) else None
 except (ValueError,TypeError):return None

def count(value):
 n=numeric(value)
 return n if n is not None and n>=0 and n.is_integer() else None

def mark(value):
 if value is True:return True
 if value is False:return False
 text=str(value or '').strip().casefold().lstrip("'")
 return True if text in ('x','sim') else False if text in ('-','não','nao') else None

def description_parts(values):
 # Known textual attributes and dimension facts; unknowns produce no zero token.
 parts=[('text',str(values[k])) for k in ('material_type','profile','grade') if values.get(k)]
 for field,(label,unit) in DIMENSIONS.items():
  if values.get(field) is not None:parts.append((label,numeric(values[field]),unit))
 return parts

def observed_parts(description):
 if not description:return []
 result=[]
 for part in description.split(' · '):
  if not part:continue
  found=False
  for label,unit in DIMENSIONS.values():
   match=re.fullmatch(re.escape(label)+r' (.+?)\s*'+re.escape(unit),part)
   if match:
    result.append((label,numeric(match[1]),unit));found=True;break
  if not found:result.append(('text',part))
 return result

def deadline(values,area,selected,today):
 q=count(values.get('quantity_required'))
 primary='corte' if area=='perfis' else str(values.get('operation') or '').strip()
 codes=[primary];unknown_operation=False
 if area=='perfis':
  applicable=mark(values.get('abocardar'))
  if applicable is not False:codes.append('abocardar')
  unknown_operation=applicable is None
 else:
  secondary=str(values.get('operation_detail') or '').strip()
  if secondary not in ('','0',primary):codes.append(secondary)
 counters={str(s['operation']):count(s.get('value')) for s in selected}
 balances={code:max(q-counters[code],0) if q is not None and counters.get(code) is not None else None for code in codes}
 unknown=unknown_operation or any(v is None for v in balances.values())
 pending=any(v is not None and v>0 for v in balances.values())
 value=values.get('expected_date') or values.get('delivery_date')
 try:due=date.fromisoformat(str(value)[:10]) if value else None
 except ValueError:due=None
 overdue=None if unknown or due is None else due<today and pending
 if unknown:status='Conclusão por confirmar'
 elif due is None:status='Sem data'
 elif overdue:status='Prazo ultrapassado'
 elif pending:status='Dentro do prazo'
 else:status='Trabalho concluído'
 return {'overdue':overdue,'deadline_status':status},{'required':q,'counters':counters,'balances':balances,
   'abocardar_unknown':unknown_operation,'deadline':value,'deadline_origin':'expected_date' if values.get('expected_date') else 'delivery_date' if values.get('delivery_date') else None,'today':str(today)}

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--output',default='c04-semantic-results');parser.add_argument('--require-detail',action='store_true');args=parser.parse_args()
 assert re.fullmatch('[a-z0-9-]+',args.output)
 os.environ['MES_PG_DSN']=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
 from app import planning
 from app.raw import query
 from scripts.audit_planning_selected_ocr import source_fingerprints
 today=datetime.now(ZoneInfo(planning.settings.display_timezone)).date()
 report={'at':datetime.now(timezone.utc).isoformat(),'environment':'planning_integral isolated repeatable read, no writes',
  'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'rules':['F01','F21','G12'],
  'application_day':str(today),'detail_required':args.require_detail,'boundary':'Reconstruct descriptions from typed facts and deadlines from selected per-operation counters, not precomputed balances. C01/C02 selection correctness remains separately gated.',
  'areas':{},'failures':[]}
 ledger=FOLDER/(args.output+'-rows.jsonl.gz')
 with planning.connect(readonly=True) as c,gzip.open(ledger,'wt',encoding='utf8') as out:
  c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
  assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
  report['sources_before']=source_fingerprints(c)
  for area in planning.AREAS:
   gen=query.generation(c,area);base,params=query.source(gen)
   raw={r['source_line_id']:r['material_description'] for r in c.execute('SELECT source_line_id,material_description FROM raw_mtg.plan_production_rows WHERE snapshot_id=%s',(gen['metadata']['snapshot']['snapshot_id'],))}
   info={'generation':gen['id'],'created_at':str(gen['created_at']),'rows':0,'checks':0,'deadline_states':Counter(),'original_descriptions_checked':0,'without_single_source':0}
   rows=c.execute("SELECT m.row_key,c.values_json,c.detail->>'plan_key' plan_key,c.detail->'original'->>'material_description' source_description,c.detail->'calculation'->'production_sources' selected,c.detail->'calculation'->>'contract' contract,jsonb_build_object('description',c.detail->'calculation'->'rules'->'description','material_description',c.detail->'calculation'->'rules'->'material_description','deadline_status',c.detail->'calculation'->'rules'->'deadline_status','overdue',c.detail->'calculation'->'rules'->'overdue') rules"+base,params)
   for row in rows:
    values=row['values_json'];expected=description_parts(values);actual=observed_parts(values.get('description'))
    wanted,inputs=deadline(values,area,row['selected'] or [],today)
    checks={'description':Counter(expected)==Counter(actual),'deadline_status':wanted['deadline_status']==values.get('deadline_status'),'overdue':wanted['overdue'] is values.get('overdue')}
    detail_expected={}
    if args.require_detail:
     detail_expected['description']={k:values[k] for k in ('material_type','profile','grade') if values.get(k)}
     detail_expected['description'].update({k:values[k] for k in DIMENSIONS if values.get(k) is not None})
     detail_expected['deadline_status']=detail_expected['overdue']={
       'deadline':inputs['deadline'],'deadline_source':inputs['deadline_origin'],'local_date':str(today),
       'operation_balances':inputs['balances'],'operations_known':not inputs['abocardar_unknown']}
     checks['contract']=row['contract']=='planning-integral-20260923-v4'
     for field,expected_inputs in detail_expected.items():
      rule=row['rules'].get(field) or {}
      checks[field+'_inputs']=rule.get('inputs')==expected_inputs
      checks[field+'_source']=bool(rule.get('source'))
      checks[field+'_unavailable_reason']=values.get(field) is not None or bool(rule.get('reason'))
     checks['description_separators']=not (values.get('description') or '').startswith(' · ')
     if area=='cantoneiras':
      rule=row['rules'].get('material_description') or {};given=rule.get('inputs') or {}
      checks['material_description_inputs']=set(given)=={'current_description','original_description','technical_description'}
      checks['material_description_technical']=given.get('technical_description')==values.get('description')
      checks['material_description_original']=given.get('original_description')==values.get('original_description')
      checks['material_description_precedence']=values.get('material_description')==(given.get('current_description') or given.get('original_description') or given.get('technical_description') or None)
      checks['material_description_source']=bool(rule.get('source'))
      checks['material_description_unavailable_reason']=values.get('material_description') is not None or bool(rule.get('reason'))
    original=None
    if row['plan_key'] in raw:
     # Original typed source text remains available even after manual edits.
     original=raw[row['plan_key']] or ''
     checks['original_description']=original==(row['source_description'] or '')
     info['original_descriptions_checked']+=1
    else:info['without_single_source']+=1
    result={'area':area,'key':row['row_key'],'expected_description_parts':expected,'observed_description':values.get('description'),
       'expected_deadline':wanted,'observed_deadline':{k:values.get(k) for k in wanted},'deadline_inputs':inputs,
       'original_source':original,'preserved_original':row['source_description'],'checks':checks}
    if args.require_detail:result.update(expected_detail_inputs=detail_expected,observed_rules=row['rules'],contract=row['contract'])
    out.write(json.dumps(result,ensure_ascii=False,default=str)+'\n')
    for field,ok in checks.items():
     if not ok:report['failures'].append({'area':area,'key':row['row_key'],'field':field,'expected':expected if field=='description' else original if field=='original_description' else wanted.get(field,detail_expected),
        'observed':values.get('description') if field=='description' else row['source_description'] if field=='original_description' else values.get(field,row['rules']),'inputs':inputs})
    info['rows']+=1;info['checks']+=len(checks);info['deadline_states'][values.get('deadline_status')]+=1
   report['areas'][area]=info;print(area,info['rows'],'pieces;',len(report['failures']),'differences',flush=True)
  report['sources_after']=source_fingerprints(c)
 assert report['sources_before']==report['sources_after']
 report['ledger']={'file':ledger.name,'sha256':hashlib.sha256(ledger.read_bytes()).hexdigest()}
 report['result']='passed' if not report['failures'] else 'failed'
 (FOLDER/(args.output+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n')
 print(report['result'],sum(a['checks'] for a in report['areas'].values()),'checks',len(report['failures']),'differences',flush=True)
 if report['failures']:raise SystemExit(1)

if __name__=='__main__':main()
