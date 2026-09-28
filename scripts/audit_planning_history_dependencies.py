"""Independent arithmetic and retained-version audit of the history browser trial."""
import argparse,json,math,os
from pathlib import Path
from datetime import datetime,timezone

parser=argparse.ArgumentParser();parser.add_argument('--output',default='c10-dependencies-audit.json');parser.add_argument('--browser',default='c10-dependencies-browser.json');args=parser.parse_args()
folder=Path('docs/validacao-planeamento-integral/20260923-execucao')
os.environ['MES_PG_DSN']=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
from app import planning,planning_needs as needs
from app.raw import query,productivity

browser=json.loads((folder/args.browser).read_text())
fixtures=json.loads((folder/'c10-dependencies-fixtures.json').read_text())
report={'at':datetime.now(timezone.utc).isoformat(),'environment':'isolated full copy localhost44164',
    'browser_result':browser.get('result'),'timing_failures':browser.get('timingFailures'),
    'scope':'Numeric results, evidence, actual/available hours and immutable versions; timing checked separately by browser.',
    'areas':[],'history':[]}
def equal(actual,expected):
    if expected is None:assert actual is None
    else:assert isinstance(actual,(int,float)) and math.isclose(actual,expected,rel_tol=1e-9,abs_tol=1e-8),(actual,expected)

with planning.connect(readonly=True) as c:
    c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
    assert c.execute('SELECT current_database() name').fetchone()['name']=='planning_integral'
    checked=set()
    def verify_history(digest):
        proof=productivity.evidence(digest)
        if digest in checked:return proof
        checked.add(digest);volume=hours=0;seen=set()
        for cohort in proof['cohorts']:
            subtotal=0
            for ident in cohort['events']:
                assert ident not in seen;seen.add(ident)
                area,key=ident.split(':',1);gen=query.generation(c,area,dataset='production');base,params=query.source(gen)
                event=c.execute('SELECT c.values_json,c.detail'+base+' AND m.row_key=%s',params+[key]).fetchone()
                assert len(event['detail']['planning_keys'])==1
                gen=query.generation(c,area);base,params=query.source(gen)
                piece=c.execute('SELECT c.values_json'+base+' AND m.row_key=%s',params+event['detail']['planning_keys']).fetchone()['values_json']
                q=event['values_json']['quantity']
                subtotal+=q*(piece['section_unit'] if proof['method']=='area_hour' else piece['length_mm']/1000 if proof['method']=='metres_hour' else 1)
            equal(cohort['volume'],subtotal);volume+=subtotal;hours+=cohort['hours']
            if cohort['hours_origin']=='Manual':
                ident=cohort['key'].split(':')[1]
                definition=c.execute('SELECT definition FROM planning_mtg.raw_object_versions WHERE object_id=%s AND revision=%s',
                    (ident,cohort['hours_revision'])).fetchone()['definition']
                equal(cohort['hours'],definition['hours'])
            else:
                assert len(cohort['sheets'])==1
                area,key=cohort['sheets'][0].split(':',1);gen=query.generation(c,area,dataset='production_hours');base,params=query.source(gen)
                original=c.execute("SELECT c.values_json->'hours_worked' hours"+base+' AND m.row_key=%s',params+[key]).fetchone()['hours']
                equal(cohort['hours'],original)
        equal(proof['volume'],volume);equal(proof['hours'],hours);equal(proof['value'],volume/hours if volume>0 and hours>0 else None)
        report['history'].append({'hash':digest,'volume':volume,'hours':hours,'rate':proof['value'],'events':len(seen),'window':proof['window']})
        return proof
    for trial in browser['areas']:
        f=next(a for a in fixtures['areas'] if a['area']==trial['area']);area=f['area'];out={'area':area,'steps':[]}
        for step in trial['steps']:
            source='Excel provisório' if step['label']=='window-1' else 'Manual' if step['label']=='manual-current' else 'Histórico'
            rate=f['excel_rate'] if source=='Excel provisório' else f['base_rate']*2 if source=='Manual' else f['base_rate']/2 if step['label']=='double-hours' else f['base_rate']
            for kind in ('active','closed'):
                row=step[kind];v=row['values'];original=f[kind]['values_json']
                volume=original['remaining']*(original['section_unit'] if area=='perfis' else original['length_mm']/1000)
                assert v['rate_source']==source;equal(v['applied_rate_value'],rate);equal(v['theoretical_hours'],volume/rate)
                if kind=='closed':assert v['hours_pct'] is None and not row['population']['active']
                estimate=next(e for e in row['calculation']['operation_estimates'] if e['operation']==original['operation'])
                history=verify_history(estimate['history_hash'])
                if source=='Histórico':equal(history['value'],rate)
                if source=='Excel provisório':assert history['value'] is None and history['window']['days']==1
            generation=c.execute('SELECT * FROM planning_mtg.raw_generations WHERE id=%s',(step['capacityVersion'],)).fetchone()
            fp=generation['metadata']['source_fingerprint']
            weekly=c.execute("SELECT * FROM planning_mtg.raw_generations WHERE dataset=%s AND metadata->>'source_fingerprint'=%s ORDER BY id DESC LIMIT 1",('capacity:'+area,fp)).fetchone()
            base,params=query.source(weekly);key=f['resource']['id']+'|'+str(f['year'])+'|'+str(f['week'])
            row=c.execute('SELECT c.values_json,c.detail'+base+' AND m.row_key=%s',params+[key]).fetchone()
            evidence=row['detail']['actual_evidence'];known=[e['hours'] for e in evidence if e['hours'] is not None]
            equal(row['values_json']['actual_hours'],sum(known) if evidence and len(known)==len(evidence) else None)
            equal(row['detail']['actual_coverage']['sum_known'],sum(known) if known else None)
            target=next(e for e in evidence if f['cohort']['sheets'][0] in e['sheets'])
            equal(target['hours'],f['cohort']['hours']*(2 if step['label']=='double-hours' else 1))
            out['steps'].append({'label':step['label'],'source':source,'rate':rate,'target_actual_hours':target['hours'],
                'availability':row['values_json']['available_hours'],'actual_coverage':row['detail']['actual_coverage']})
        assert len({s['availability'] for s in out['steps']})==1
        old=query.listing({'area':area,'version':str(f['generation']),'population':'all','selected':[f['active']['row_key'],f['closed']['row_key']]},conn=c)['rows']
        for kind in ('active','closed'):
            before=next(r for r in old if r['key']==f[kind]['row_key'])
            assert before['values']==f[kind]['values_json']
            now=query.listing({'area':area,'population':'all','selected':[before['key']]},conn=c)['rows'][0]
            assert now['raw']==before['raw'] and now['sources']==before['sources']
            for field in ('rate_source','applied_rate_value','theoretical_hours'):assert now['values'][field]==before['values'][field]
        report['areas'].append(out)
report['result']='passed'
(folder/args.output).write_text(json.dumps(needs.serial(report),ensure_ascii=False,indent=2)+'\n')
print(len(report['history']),'historical proofs;',sum(len(a['steps']) for a in report['areas']),'browser steps reconciled independently.')
