"""C10/F12 reconciliation in the explicitly isolated full copy; no source writes."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import time

parser=argparse.ArgumentParser()
parser.add_argument('--rebuild',action='store_true')
parser.add_argument('--output',default='c10-full-audit.json')
args=parser.parse_args()
cfg=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())
os.environ['MES_PG_DSN']=cfg['dsn']
from app import planning
from app.raw import projection, query, capacity

folder=Path('docs/validacao-planeamento-integral/20260923-execucao')
out={'at':datetime.now(timezone.utc).isoformat(),'environment':'isolated full copy localhost:44164',
     'command':'PYTHONPATH=. .venv/bin/python scripts/audit_planning_productivity.py'+(' --rebuild' if args.rebuild else '')+' --output '+args.output,
     'areas':{},'timings_seconds':{},'failures':[]}
with planning.connect(readonly=True) as c:
    assert c.execute('SELECT current_database() name').fetchone()['name']=='planning_integral'
if args.rebuild:
    for area in planning.AREAS:
        start=time.monotonic();projection.rebuild(area)
        out['timings_seconds'][area]=time.monotonic()-start
        print(area,out['timings_seconds'][area],flush=True)
    start=time.monotonic();capacity.rebuild();out['timings_seconds']['capacity']=time.monotonic()-start
    print('capacity',out['timings_seconds']['capacity'],flush=True)

def close(a,b):
    if a is None or b is None:return a is b
    return math.isclose(float(a),float(b),rel_tol=1e-9,abs_tol=1e-8)

def check(ok,description,**details):
    if not ok:out['failures'].append({'check':description,**details})

with planning.connect(readonly=True) as c:
    c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
    plans={};events={};hours={};hashes=set();items={}
    for area in planning.AREAS:
        gen=query.generation(c,area);base,params=query.source(gen)
        rows=c.execute("SELECT m.row_key,c.values_json,c.detail->'calculation' calculation"+base,params).fetchall()
        plans[area]={r['row_key']:r for r in rows}
        sources=Counter(str(r['values_json'].get('rate_source')) for r in rows)
        active_sources=Counter(str(r['values_json'].get('rate_source')) for r in rows if r['values_json'].get('planning_active'))
        out['areas'][area]={'version':gen['id'],'metadata':gen['metadata'],'rows':len(rows),
            'rate_sources_all':dict(sources),'rate_sources_active':dict(active_sources)}
        for r in rows:
            for estimate in (r['calculation'] or {}).get('operation_estimates',[]):
                if estimate.get('history_hash'):hashes.add(estimate['history_hash'])
        eg=query.generation(c,area,dataset='production');base,params=query.source(eg)
        for r in c.execute('SELECT m.row_key,c.values_json,c.detail'+base,params):
            events[area+':'+r['row_key']]={'area':area,**r}
        hg=query.generation(c,area,dataset='production_hours');base,params=query.source(hg)
        for r in c.execute('SELECT m.row_key,c.values_json,c.detail'+base,params):hours[area+':'+r['row_key']]=r
        cg=query.generation(c,area,dataset='capacity_items');base,params=query.source(cg)
        items[area]=c.execute('SELECT c.values_json,c.detail'+base,params).fetchall()
        wg=query.generation(c,area,dataset='capacity');base,params=query.source(wg)
        buckets={r['row_key']:r['values_json'] for r in c.execute('SELECT m.row_key,c.values_json'+base,params)}
        compared=0;known=0;sample=None
        for item in items[area]:
            iv=item['values_json'];detail=item['detail'];piece=plans[area][detail['planning_key']]['values_json']
            check(piece['planning_active'],'capacity contains closed piece',area=area,key=detail['planning_key'])
            if not iv['primary_operation']:continue
            compared+=1
            for raw_name,cap_name in [('theoretical_hours','planned_hours'),('applied_rate_value','applied_rate_value')]:
                check(close(piece.get(raw_name),iv.get(cap_name)),'RAW/capacity '+raw_name,area=area,key=detail['planning_key'],raw=piece.get(raw_name),capacity=iv.get(cap_name))
            check(piece.get('rate_source')==iv.get('rate_source'),'RAW/capacity source',area=area,key=detail['planning_key'])
            occupancy=buckets[iv['bucket_key']]['occupancy']
            check(close(piece.get('hours_pct'),occupancy),'F12 repeated aggregate',area=area,key=detail['planning_key'])
            if occupancy is not None:known+=1
            if iv.get('rate_source')=='Histórico' and iv.get('planned_hours') is not None and iv['planned_hours']>0 and sample is None:
                sample={'key':detail['planning_key'],'values':piece,'capacity':iv,'applied_rate':detail['applied_rate']}
        out['areas'][area].update(capacity_version=cg['id'],capacity_items=len(items[area]),primary_compared=compared,
            f12_known_rows=known,historical_sample=sample)
    # Independent arithmetic and evidence resolution; do not call the productivity engine.
    history_results=[]
    manual={str(r['id']):r for r in c.execute("SELECT * FROM planning_mtg.raw_objects WHERE kind='worked_hours'")}
    for digest in sorted(hashes):
        proof=c.execute("SELECT detail->'productivity' p FROM planning_mtg.raw_contents WHERE hash=%s",(digest,)).fetchone()['p']
        total_volume=total_hours=0;seen=set()
        for cohort in proof['cohorts']:
            volume=0
            for ident in cohort['events']:
                check(ident not in seen,'duplicate accepted historical event',hash=digest,event=ident);seen.add(ident)
                e=events.get(ident);check(e is not None,'historical event exists',hash=digest,event=ident)
                if e is None:continue
                linked=e['detail'].get('planning_keys',[])
                check(len(linked)==1,'unique historical piece',event=ident)
                if len(linked)!=1:continue
                v=plans[e['area']][linked[0]]['values_json'];q=e['values_json']['quantity']
                volume+=q*(v['length_mm']/1000 if proof['method']=='metres_hour' else v['section_unit'] if proof['method']=='area_hour' else 1)
            check(close(volume,cohort['volume']),'cohort volume from events and dimensions',hash=digest,cohort=cohort['key'],expected=volume,observed=cohort['volume'])
            if cohort['hours_origin']=='OCR':
                check(len(cohort['sheets'])==1,'one OCR time per sheet',hash=digest)
                expected=hours[cohort['sheets'][0]]['values_json']['hours_worked']
                check(close(expected,cohort['hours']),'cohort hours from declaration',hash=digest)
            if cohort['hours_origin']=='Manual':
                declaration=manual[cohort['key'].split(':')[1]]
                allocation=cohort.get('allocation')
                expected=allocation['hours'] if allocation else declaration['definition']['hours']
                check(close(expected,cohort['hours']) and declaration['revision']==cohort['hours_revision'],'manual hours and revision',hash=digest)
                if allocation:check(allocation in declaration['definition']['operation_hours'],'explicit operation partition',hash=digest)
            total_volume+=volume;total_hours+=cohort['hours']
        expected=total_volume/total_hours if total_volume>0 and total_hours>0 else None
        check(close(expected,proof['value']),'weighted rate',hash=digest,expected=expected,observed=proof['value'])
        check(close(total_hours,proof['hours']) and close(total_volume,proof['volume']),'matching totals',hash=digest)
        history_results.append({'hash':digest,'method':proof['method'],'window':proof['window'],
            'cohorts':len(proof['cohorts']),'events':len(seen),'volume':total_volume,'hours':total_hours,
            'expected_rate':expected,'observed_rate':proof['value'],'excluded_cohorts':len(proof['excluded'])})
    out['history']=history_results
out['result']='passed' if not out['failures'] else 'failed'
(folder/args.output).write_text(json.dumps(out,ensure_ascii=False,indent=2,default=str)+'\n')
print({a:{k:v for k,v in r.items() if k in ('rows','primary_compared','f12_known_rows','rate_sources_active')} for a,r in out['areas'].items()},flush=True)
print('Histories',len(out['history']),'failures',len(out['failures']),flush=True)
assert not out['failures'],out['failures'][:3]
