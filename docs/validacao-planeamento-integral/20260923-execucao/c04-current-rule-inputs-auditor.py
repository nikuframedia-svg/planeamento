from pathlib import Path
from datetime import datetime,timezone
import json,os
os.environ['MES_PG_DSN']=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
from app import planning
from app.raw import query
report={'at':datetime.now(timezone.utc).isoformat(),'environment':'planning_integral clone read-only repeatable read','areas':{},'boundary':'Candidates requiring review: numeric non-null results whose rule has an empty input map. This inventory does not infer a numeric error or automatically reject constant/not-applicable rules.'}
with planning.connect(readonly=True) as c:
 c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
 assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
 for area in planning.AREAS:
  gen=query.generation(c,area);base,args=query.source(gen)
  rows=c.execute("WITH rows AS MATERIALIZED (SELECT m.row_key,c.values_json,c.detail->'calculation'->'rules' rules"+base+") SELECT rule.key field,count(*) n,count(*) FILTER (WHERE coalesce(rule.value->'inputs','{}'::jsonb)='{}'::jsonb) missing_inputs,min(r.row_key) FILTER (WHERE coalesce(rule.value->'inputs','{}'::jsonb)='{}'::jsonb) example FROM rows r CROSS JOIN LATERAL jsonb_each(r.rules) rule WHERE jsonb_typeof(r.values_json->rule.key)='number' GROUP BY rule.key ORDER BY rule.key",args).fetchall()
  report['areas'][area]={'generation':gen['id'],'numeric_rules':[dict(r) for r in rows]}
folder=Path('docs/validacao-planeamento-integral/20260923-execucao');(folder/'c04-current-rule-input-gaps.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print({a:[(r['field'],r['missing_inputs']) for r in v['numeric_rules'] if r['missing_inputs']] for a,v in report['areas'].items()})
