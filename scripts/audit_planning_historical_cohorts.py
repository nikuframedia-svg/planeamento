"""Independent H09 eligibility and arithmetic for all current estimate contexts.

Time comes from central declarations and reviewed manual objects through the
independent H03 reader. Production facts and technical association are read from
the published event population; C01/C02 association correctness remains a gate.
No application productivity, time resolution, or rate selection is called.
"""
from __future__ import annotations
from collections import defaultdict,Counter
from datetime import date,datetime,timedelta,timezone
import argparse,gzip,hashlib,json,math,os
from pathlib import Path
from zoneinfo import ZoneInfo
from scripts.audit_planning_actual_hours import load_inputs,resource_cohorts,digest,number,FOLDER
from scripts.audit_planning_rate_selection import operation_context,rate_day,norm

SCOPE=('material_type','profile','grade')
DIMENSIONS=('length_mm','outer_diameter_mm','width_mm','height_mm','thickness_mm','angle_deg')
UNITS={'area_hour':'mm²/h','metres_hour':'m/h','units_hour':'un./h'}
REASONS={
    'time_versions':'Declaração de horas repetida com conteúdo divergente.',
    'time_date':'Data das horas desconhecida.', 'window':'Período fora da janela histórica.',
    'hours':'Horas positivas desconhecidas; zero horas não define produtividade.',
    'empty':'Sem produção correspondente às horas.', 'time_operation':'Horas de outra operação.',
    'event_versions':'Evento repetido com conteúdo divergente.',
    'overlap':'Evento abrangido por mais de uma declaração de horas.',
    'mixed':'Tempo partilhado por operações/áreas sem repartição comprovada.',
    'identity':'Associação técnica ou operação do evento por confirmar.',
    'date_range':'Data do evento incompatível com o período de horas.',
    'event_date':'Data de produção desconhecida.',
    'scope':'Família, perfil ou qualidade incompatíveis com esta estimativa.',
    'quantity':'Quantidade de produção desconhecida ou inválida.',
    'dimensions':'Dimensões incompatíveis para produtividade em unidades/h.',
    'volume':'Volume do evento sem dimensão comprovada.', 'method':'Método histórico desconhecido.',
}


def evaluate(events,cohorts,*,area,operation,method,values,end,days):
    start=end-timedelta(days=days-1)
    sheet_events=defaultdict(list)
    for event in events:sheet_events[event['sheet_key']].append(event)
    candidates=[]
    for cohort in cohorts:
        rows=[e for sheet in cohort['sheets'] for e in sheet_events[sheet]]
        allocations=(cohort.get('definition') or {}).get('operation_hours') or []
        if not allocations:
            candidates.append((cohort,rows));continue
        allocated={(a['area'],str(a['operation'])) for a in allocations}
        complete=all((e.get('area'),str(e.get('operation'))) in allocated for e in rows)
        for allocation in allocations:
            adjusted={**cohort,'key':cohort['key']+':'+allocation['area']+':'+allocation['operation'],
                      'parent_key':cohort['key'],'allocation':allocation,'operation':allocation['operation'],
                      'hours':allocation['hours'] if cohort.get('hours') is not None and complete else None,
                      'reason':cohort.get('reason') or (None if complete else 'Repartição não abrange todas as operações dos eventos.')}
            candidates.append((adjusted,[e for e in rows if e.get('area')==allocation['area'] and str(e.get('operation'))==allocation['operation']]))
    owners=defaultdict(set);time_versions=defaultdict(set)
    for cohort,rows in candidates:
        time_versions[cohort['key']].add(digest(cohort))
        for row in rows:owners[row['key']].add(cohort['key'])
    accepted=[];excluded=[];seen=set()
    for cohort,rows in sorted(candidates,key=lambda c:(c[0]['key'],digest(c[0]))):
        ident=cohort['key']
        if ident in seen:continue
        seen.add(ident);reasons=set()
        if len(time_versions[ident])>1:reasons.add(REASONS['time_versions'])
        try:first,last=date.fromisoformat(cohort['start_date']),date.fromisoformat(cohort['end_date'])
        except (KeyError,TypeError,ValueError):first=last=None;reasons.add(REASONS['time_date'])
        if first and (first<start or last>end or first>last):reasons.add(REASONS['window'])
        hours=number(cohort.get('hours'))
        if hours is None or hours<=0:reasons.add(cohort.get('reason') or REASONS['hours'])
        if not rows:reasons.add(REASONS['empty'])
        if cohort.get('operation') and str(cohort['operation'])!=operation:reasons.add(REASONS['time_operation'])
        unique=defaultdict(list)
        for event in rows:unique[event['key']].append(event)
        volume=0
        for key,versions in sorted(unique.items()):
            if len({digest(e) for e in versions})>1:reasons.add(REASONS['event_versions'])
            event=sorted(versions,key=digest)[0]
            if len(owners[key])>1:reasons.add(REASONS['overlap'])
            if (event.get('area'),str(event.get('operation')))!=(area,operation):reasons.add(REASONS['mixed'])
            if not event.get('identity_valid'):reasons.add(REASONS['identity'])
            try:
                produced=date.fromisoformat(event['date'])
                if first is None or not first<=produced<=last:reasons.add(REASONS['date_range'])
            except (KeyError,TypeError,ValueError):reasons.add(REASONS['event_date'])
            if method=='units_hour' and any(norm(event.get(k))!=norm(values.get(k)) for k in SCOPE):reasons.add(REASONS['scope'])
            q=number(event.get('quantity'))
            if q is None or q<0 or not q.is_integer():reasons.add(REASONS['quantity']);continue
            if method=='units_hour':
                if any(number(event.get(k))!=number(values.get(k)) for k in DIMENSIONS):reasons.add(REASONS['dimensions'])
                volume+=q
            elif method in ('area_hour','metres_hour'):
                size=number(event.get('section_unit' if method=='area_hour' else 'length_mm'))
                if (size is None or size<=0) and q:reasons.add(REASONS['volume'])
                else:volume+=q*(size or 0)/(1000 if method=='metres_hour' else 1)
            else:reasons.add(REASONS['method'])
        if reasons:
            excluded.append({'key':ident,'sheets':sorted(cohort['sheets']),'events':sorted(unique),'reasons':sorted(reasons)})
        else:
            accepted.append({'key':ident,'sheets':sorted(cohort['sheets']),'events':sorted(unique),
                             'hours':hours,'volume':volume,
                             'orders':sorted({e['of'] for versions in unique.values() for e in versions if e.get('of')}),
                             'start_date':str(first),'end_date':str(last),
                             'hours_origin':cohort.get('origin'),'hours_revision':cohort.get('revision'),
                             'allocation':cohort.get('allocation')})
    total_hours=sum(c['hours'] for c in accepted);total_volume=sum(c['volume'] for c in accepted)
    return {'cohorts':accepted,'excluded':excluded,'hours':total_hours,'volume':total_volume,
            'value':total_volume/total_hours if total_volume>0 and total_hours>0 else None,
            'event_count':len({e for c in accepted for e in c['events']}),
            'sheet_count':len({s for c in accepted for s in c['sheets']}),
            'window':{'start':str(start),'end':str(end),'days':days},'method':method,'unit':UNITS[method]}


def equivalent(a,b):
    if isinstance(a,(int,float)) and isinstance(b,(int,float)) and not isinstance(a,bool) and not isinstance(b,bool):
        return math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-7)
    if isinstance(a,dict) and isinstance(b,dict):return set(a)==set(b) and all(equivalent(a[k],b[k]) for k in a)
    if isinstance(a,list) and isinstance(b,list):return len(a)==len(b) and all(equivalent(x,y) for x,y in zip(a,b))
    return a==b


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='c10-historical-cohorts');args=parser.parse_args()
    assert args.output.replace('-','').isalnum()
    os.environ['MES_PG_DSN']=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
    from app import planning
    from app.raw import query
    from scripts.audit_planning_selected_ocr import source_fingerprints
    today=datetime.now(ZoneInfo(planning.settings.display_timezone)).date()
    report={'at':datetime.now(timezone.utc).isoformat(),'rules':['H09'],'boundary':__doc__,
            'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'environment':'planning_integral clone, read-only repeatable read','versions':{},'checks':0,'failures':[],
            'day':str(today),'areas':{},'histories':[]}
    def check(name,actual,expected,**context):
        report['checks']+=1
        if not equivalent(actual,expected):report['failures'].append({'check':name,'actual':actual,'expected':expected,**context})
    with planning.connect(readonly=True) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        assert conn.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
        report['sources_before']=source_fingerprints(conn)
        observed,_,resources,declarations,inputs=load_inputs(conn)
        report['hours_input_sha256']=digest(inputs)
        aliases={(a['area'],a['name']):r for r in resources.values() for a in r['definition']['aliases']}
        periods=conn.execute("SELECT area,definition FROM planning_mtg.raw_objects WHERE NOT archived AND kind='period'").fetchall()
        plans={};events=[];contexts={};hashes=set();time_sets={}
        for area in planning.AREAS:
            gen=query.generation(conn,area);base,params=query.source(gen);snapshot=gen['metadata']['snapshot']['snapshot_id']
            report['versions'][area]={'planning':gen['id']};counts=Counter()
            with conn.cursor(name='historical_pieces_'+area) as cursor:
                cursor.execute("SELECT m.row_key,c.values_json,c.detail->'calculation'->'operation_estimates' estimates,c.detail->'calculation'->>'compatible' compatible,c.detail->'calculation'->>'historical_compatible' historical_compatible,c.detail->'preparations' preparations"+base,params)
                for row in cursor:
                    values=row['values_json'];counts['pieces']+=1
                    plans[(area,row['row_key'])]=(values,row['compatible']!='false' and row['historical_compatible']!='false')
                    primary='corte' if area=='perfis' else str(values.get('operation') or '')
                    for estimate in row['estimates'] or []:
                        counts['estimates']+=1;op=str(estimate['operation'])
                        vals=operation_context(values,op,primary,row['preparations'] or [])
                        machine=vals.get('machine');resource=aliases.get((area,machine))
                        resource=resource or {'id':area+':'+str(machine),'definition':{'aliases':[{'area':area,'name':machine}]}}
                        ident=resource['id'];days=resource['definition'].get('history_window_days',90)
                        end=min(today,rate_day(vals,area,snapshot,periods,today))
                        method='area_hour' if area=='perfis' and op=='corte' else 'metres_hour' if area=='cantoneiras' else 'units_hour'
                        scope={k:vals.get(k) for k in SCOPE+DIMENSIONS} if method=='units_hour' else {}
                        context_key=digest([ident,area,op,method,str(end),days,scope])
                        if ident not in time_sets:time_sets[ident]=resource_cohorts(resource,declarations,observed) if machine else []
                        digest_value=estimate.get('history_hash');check('history_hash_present',bool(digest_value),True,area=area,key=row['row_key'],operation=op)
                        if not digest_value:continue
                        hashes.add(digest_value)
                        context=contexts.setdefault(context_key,{'resource':ident,'area':area,'operation':op,'method':method,
                            'values':scope,'end':str(end),'days':days,'hashes':set(),'uses':0,'sample':row['row_key']})
                        context['hashes'].add(digest_value);context['uses']+=1
            report['areas'][area]=dict(counts)
        for area in planning.AREAS:
            gen=query.generation(conn,area,dataset='production');base,params=query.source(gen);report['versions'][area]['production']=gen['id']
            for row in conn.execute('SELECT m.row_key,c.values_json,c.detail'+base,params):
                v,d=row['values_json'],row['detail'];linked=d.get('planning_keys',[])
                piece=plans.get((area,linked[0])) if len(linked)==1 else None
                events.append({**(piece[0] if piece else {}),'key':area+':'+row['row_key'],
                    'sheet_key':str(d['sheet_uid']) if d.get('source')=='ocr_original' or str(d.get('sheet_uid','')).startswith('original:') else area+':'+str(d.get('sheet_uid') or 'unknown:'+row['row_key']),
                    'area':area,'operation':v.get('operation'),'machine':v.get('machine'),
                    'date':v.get('production_date'),'quantity':v.get('quantity'),
                    'identity_valid':bool(piece and piece[1] and v.get('association_status') in ('associated','explicit','technical_unique'))})
        proofs={r['hash']:r['proof'] for r in conn.execute("SELECT hash,detail->'productivity' proof FROM planning_mtg.raw_contents WHERE hash=ANY(%s)",(sorted(hashes),))}
        report['events']={'total':len(events),'identity_valid':sum(e['identity_valid'] for e in events)}
        report['unique_histories']=len(hashes);report['contexts']=len(contexts)
        reasons=Counter();accepted_count=excluded_count=0
        ledger=FOLDER/(args.output+'-contexts.jsonl.gz')
        with gzip.open(ledger,'wt',encoding='utf8') as out:
            for key,context in sorted(contexts.items()):
                expected=evaluate(events,time_sets[context['resource']],area=context['area'],operation=context['operation'],
                                  method=context['method'],values=context['values'],end=date.fromisoformat(context['end']),days=context['days'])
                accepted_count+=len(expected['cohorts']);excluded_count+=len(expected['excluded'])
                reasons.update(reason for c in expected['excluded'] for reason in c['reasons'])
                for hash_value in sorted(context['hashes']):
                    proof=proofs.get(hash_value);check('immutable_evidence_exists',proof is not None,True,context=key,hash=hash_value)
                    if proof is None:continue
                    check('immutable_evidence_hash',digest({'productivity':proof}),hash_value,context=key)
                    for field,wanted in expected.items():
                        actual=proof.get(field)
                        if field in ('cohorts','excluded'):actual=sorted(actual or [],key=lambda r:r['key'])
                        check(field,actual,wanted,context=key,hash=hash_value)
                    expected_scope=context['values'] if context['method']=='units_hour' else None
                    if expected_scope is not None:check('scope',proof.get('scope'),{k:expected_scope[k] for k in SCOPE},context=key)
                    report['histories'].append({'context':key,'hash':hash_value,'area':context['area'],
                        'operation':context['operation'],'resource':context['resource'],'uses':context['uses'],
                        'cohorts':len(expected['cohorts']),'excluded':len(expected['excluded']),
                        'volume':expected['volume'],'hours':expected['hours'],'value':expected['value']})
                    out.write(json.dumps({'context':{**context,'hashes':sorted(context['hashes'])},'expected':expected,'observed':proof},ensure_ascii=False)+'\n')
        report['ledger']={'file':ledger.name,'sha256':hashlib.sha256(ledger.read_bytes()).hexdigest()}
        report['cohort_checks']={'accepted':accepted_count,'excluded':excluded_count,'exclusion_reasons':dict(reasons)}
        report['sources_after']=source_fingerprints(conn)
    assert report['sources_before']==report['sources_after']
    report['result']='failed' if report['failures'] else 'passed'
    (FOLDER/(args.output+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(report['result'],report['checks'],'checks',report['unique_histories'],'histories',report['contexts'],'contexts',len(report['failures']),'failures',flush=True)
    assert not report['failures'],report['failures'][:1]


if __name__=='__main__':main()
