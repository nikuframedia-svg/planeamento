"""Independent H03 audit: central sheet declarations -> manual review -> weeks.

No application observation/resolution/capacity functions are used as an oracle.
Includes central original snapshots and audited original decisions. Live source
ingestion remains a separate C01 requirement.
"""
from __future__ import annotations
from collections import defaultdict, Counter
from datetime import date, datetime, timezone
from decimal import Decimal
import argparse, hashlib, json, math, os
from pathlib import Path
from uuid import UUID

FOLDER = Path('docs/validacao-planeamento-integral/20260923-execucao')
SOURCE_AREAS = {'kanban-mes-mtg2':'perfis', 'kanban-mes':'cantoneiras'}


def serial(value):
    def convert(item):
        if isinstance(item, Decimal):return float(item)
        if isinstance(item, UUID):return str(item)
        return item.isoformat()
    return json.loads(json.dumps(value,ensure_ascii=False,default=convert,allow_nan=False))


def digest(value):
    return hashlib.sha256(json.dumps(serial(value),ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def number(value):
    try:
        result=float(str(value).replace(',','.'))
        return result if math.isfinite(result) else None
    except (TypeError,ValueError):return None


def source_observations(sheets, records):
    """Sheet facts are independent of the count of piece/production rows."""
    facts=defaultdict(list)
    for record in records:facts[record['sheet_uid']].append(record)
    observed=[];projections={}
    for sheet in sheets:
        area=SOURCE_AREAS.get(sheet['source_app'])
        if area is None:continue
        rows=facts[sheet['sheet_uid']]
        hours=sorted({float(r['hours_worked']) for r in rows if r['hours_worked'] is not None})
        machines=sorted({r['machine'] for r in rows if r['machine'] not in (None,'')})
        hours_value=number(hours[0]) if len(hours)==1 else None
        machine=machines[0] if len(machines)==1 else None
        key=area+':'+sheet['sheet_uid']
        projected={'sheet':sheet['sheet_no'],'source':sheet['source_app'],'machine':machine,
                   'hours_worked':hours_value,'production_date':sheet['sheet_date']}
        o={'key':key,'area':area,'sheet_uid':sheet['sheet_uid'],'sheet':sheet['sheet_no'],
           'date':sheet['sheet_date'],'machine':machine,'hours':hours_value,'origin':'OCR',
           'machines':machines or [machine],'original_hours':hours}
        if hours_value is not None and not 0<=hours_value<=24:
            o['hours']=None;o['hours_reason']='Horas da folha inválidas: exige um valor entre 0 e 24 h.'
        observed.append(o)
        projections[key]={'values':projected,'original_hours':hours,'original_machines':machines,
                          'validated_at':sheet['validated_at'],'record_count':len(rows)}
    return observed,projections


def reviewed_rows(definition, resource, observations):
    aliases={(a['area'],a['name']) for a in resource['definition']['aliases']}
    if definition['mode']=='sheet':
        selected=[o for o in observations if o['key']==definition['sheet_key']]
        if selected and selected[0].get('date'):
            peers=[o for o in observations if o.get('date')==selected[0]['date'] and observation_aliases(o)&aliases]
            if any(origin(o)!=origin(selected[0]) for o in peers):return peers
        return selected
    return [o for o in observations if o['date'] and definition['start_date']<=o['date']<=definition['end_date']
            and observation_aliases(o)&aliases]


def observation_aliases(o):
    return {(area,machine) for area in o.get('areas',[o['area']]) for machine in o.get('machines',[o.get('machine')])}


def origin(o):return ('original',o.get('instance_id')) if o.get('origin')=='OCR original' else ('mes',None)


def periods_overlap(a,b):
    if a['resource_id']!=b['resource_id']:return False
    if a['mode']==b['mode']=='sheet':return a['sheet_key']==b['sheet_key']
    return max(a['start_date'],b['start_date'])<=min(a['end_date'],b['end_date'])


def resource_cohorts(resource, declarations, observations):
    manual=[d for d in declarations if d['definition'].get('confirmed') and d['definition']['resource_id']==resource['id']]
    claimed=set();cohorts=[]
    for record in manual:
        d=record['definition'];rows=reviewed_rows(d,resource,observations)
        claimed.update(o['key'] for o in rows)
        unchanged=digest(sorted(rows,key=lambda o:o['key']))==d['basis_hash']
        collision=any(other['id']!=record['id'] and periods_overlap(d,other['definition']) for other in manual)
        partial=d['mode']=='sheet' and any(o['key']!=d['sheet_key'] for o in rows)
        reason='Sobreposição entre origens: revê o conjunto numa declaração por período.' if partial else 'As declarações de origem mudaram; rever substituição.' if not unchanged else 'Declarações manuais sobrepostas.' if collision else None
        cohorts.append({'key':'manual:'+record['id'],'hours':None if reason else d['hours'],'origin':'Manual',
                        'revision':record['revision'],'operation':d.get('operation'),'start_date':d['start_date'],
                        'end_date':d['end_date'],'sheets':sorted(o['key'] for o in rows),'sheet_evidence':rows,
                        'definition':d,'reason':reason})
    aliases={(a['area'],a['name']) for a in resource['definition']['aliases']}
    for o in observations:
        if o['key'] in claimed or o['machine'] is None or not observation_aliases(o)&aliases:continue
        uncertain=o.get('origin')=='OCR original' and o['area'] is None and not observation_aliases(o).issubset(aliases)
        overlap=any(p['key']!=o['key'] and p['date']==o['date'] and o['date'] and origin(p)!=origin(o) and observation_aliases(p)&aliases for p in observations)
        reason='Sobreposição entre origens de horas por resolver.' if overlap else 'Área da folha original por confirmar; a máquina pode corresponder a recursos físicos distintos.' if uncertain else o.get('hours_reason') or ('Horas da folha desconhecidas.' if o['hours'] is None else None)
        cohorts.append({'key':o['key'],'hours':None if overlap or uncertain else o['hours'],'origin':o['origin'],'start_date':o['date'],
                        **({'revision':o['revision']} if 'revision' in o else {}),
                        'end_date':o['date'],'operation':None,'sheets':[o['key']],'sheet_evidence':[o],
                        'reason':reason})
    return cohorts


def canonical(cohort):
    result=dict(cohort)
    result['sheets']=sorted(result.get('sheets',[]))
    result['sheet_evidence']=sorted(result.get('sheet_evidence',[]),key=lambda o:o['key'])
    return result


def load_inputs(conn):
    sheets=serial(conn.execute('SELECT sheet_uid,source_app,sheet_no,sheet_date,validated_at FROM mes_kanban.validated_sheets ORDER BY sheet_uid').fetchall())
    records=serial(conn.execute('SELECT id,sheet_uid,hours_worked,machine FROM mes_kanban.production_records ORDER BY id').fetchall())
    configs=serial(conn.execute("SELECT * FROM planning_mtg.raw_objects WHERE NOT archived AND kind IN ('resource','worked_hours') ORDER BY id").fetchall())
    observations,projections=source_observations(sheets,records)
    original_sheets=[];decisions=[];revisions={}
    if conn.execute("SELECT to_regclass('ocr_original.instances') t").fetchone()['t']:
        original_sheets=serial(conn.execute('''SELECT s.* FROM ocr_original.instances i JOIN ocr_original.snapshot_sheets x ON x.snapshot_id=i.current_snapshot
            JOIN ocr_original.sheets s USING(instance_id,sheet_id,content_hash) ORDER BY s.instance_id,s.sheet_id''').fetchall())
        if conn.execute("SELECT to_regclass('planning_mtg.original_association_decisions') t").fetchone()['t']:
            decisions=serial(conn.execute('SELECT DISTINCT ON(production_record_id) * FROM planning_mtg.original_association_decisions ORDER BY production_record_id,revision DESC').fetchall())
        revisions={str(r['id']):r['technical_revision'] for r in conn.execute('SELECT id,technical_revision FROM planning_mtg.needs')}
        from scripts.audit_planning_original_time import read
        original_observed,original_projected=read(original_sheets,decisions,revisions)
        observations.extend(original_observed);projections.update(original_projected)
    resources={r['id']:r for r in configs if r['kind']=='resource' and r['definition'].get('confirmed')}
    declarations=[r for r in configs if r['kind']=='worked_hours']
    return observations,projections,resources,declarations,{'sheets':sheets,'records':records,'configurations':configs,
        'original_sheets':original_sheets,'original_decisions':decisions,'technical_revisions':revisions}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='c04-actual-hours');args=parser.parse_args()
    assert args.output.replace('-','').isalnum()
    os.environ['MES_PG_DSN']=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
    from app import planning
    from app.raw import query
    from scripts.audit_planning_selected_ocr import source_fingerprints
    report={'at':datetime.now(timezone.utc).isoformat(),'rules':['H03'],'environment':'planning_integral clone, repeatable read, no writes',
            'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'boundary':__doc__,
            'checks':0,'failures':[],'versions':{},'areas':{},'weeks':[],'unassigned_dates':[]}
    def check(name,actual,expected,**context):
        report['checks']+=1
        if actual!=expected:report['failures'].append({'check':name,'actual':actual,'expected':expected,**context})
    with planning.connect(readonly=True) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        assert conn.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
        report['sources_before']=source_fingerprints(conn)
        observed,expected_projection,resources,declarations,inputs=load_inputs(conn)
        report['inputs']=inputs;report['observations']=observed
        report['input_sha256']=digest(inputs)
        report['configuration_sha256']=digest(inputs['configurations'])
        weekly={};weekly_areas=defaultdict(set)
        for area in planning.AREAS:
            report['versions'][area]={}
            gen=query.generation(conn,area,dataset='production_hours');base,params=query.source(gen)
            report['versions'][area]['production_hours']=gen['id']
            actual={area+':'+r['row_key']:r for r in conn.execute('SELECT m.row_key,c.values_json,c.detail'+base,params)}
            wanted={k:p for k,p in expected_projection.items() if k.startswith(area+':')}
            check('all_central_sheets_projected',sorted(actual),sorted(wanted),area=area)
            for key,p in wanted.items():
                if key not in actual:continue
                row=actual[key]
                check('sheet_values',row['values_json'],p['values'],key=key)
                check('original_hours',sorted(row['detail']['original_hours'],key=str),sorted(p['original_hours'],key=str),key=key)
                check('original_machines',sorted(row['detail']['original_machines']),p['original_machines'],key=key)
                for field in ('validated_at','source_revision','source_content_hash'):
                    if field in p:check('sheet_'+field,row['detail'].get(field),p[field],key=key)
            report['areas'][area]={'sheets':len(wanted),'known_hours':sum(x['values']['hours_worked'] is not None for x in wanted.values()),
                                   'piece_records':sum(x['record_count'] for x in wanted.values())}
            gen=query.generation(conn,area,dataset='capacity');base,params=query.source(gen)
            report['versions'][area]['capacity']=gen['id']
            for r in conn.execute('SELECT m.row_key,c.values_json,c.detail'+base,params):
                key=r['row_key'];weekly_areas[key].add(area)
                if key in weekly:check('shared_resource_same_week',r,weekly[key],key=key)
                else:weekly[key]=r
        expected_weeks=defaultdict(list);covered_aliases=set();resource_evidence={}
        def place(machine,cohort):
            try:year,week,_=date.fromisoformat(cohort['start_date']).isocalendar()
            except (TypeError,ValueError):report['unassigned_dates'].append(cohort);return
            expected_weeks[f'{machine}|{year}|{week}'].append(cohort)
        for resource in resources.values():
            aliases={(a['area'],a['name']) for a in resource['definition']['aliases']}
            check('resource_aliases_unique',bool(aliases & covered_aliases),False,resource=resource['id'])
            covered_aliases.update(aliases)
            cohorts=resource_cohorts(resource,declarations,observed);resource_evidence[resource['id']]=cohorts
            for cohort in cohorts:place(resource['id'],cohort)
        for o in observed:
            if observation_aliases(o)&covered_aliases:continue
            if o['area'] not in SOURCE_AREAS.values():
                report.setdefault('unassigned_areas',[]).append(o);continue
            resolved=o
            if o['machine']:
                resource={'id':'unconfigured','definition':{'aliases':[{'area':o['area'],'name':o['machine']}]}}
                resolved=next(r for r in resource_cohorts(resource,[],observed) if r['key']==o['key'])
            place(o['area']+':'+str(o['machine'] or 'Por definir'),{'key':o['key'],'sheets':[o['key']],
                  'origin':o['origin'],'hours':resolved['hours'],'sheet_evidence':[o],'reason':resolved.get('reason',o.get('hours_reason')),
                  'start_date':o['date']})
        check('all_dated_declarations_have_a_bucket',sorted(set(expected_weeks)-set(weekly)),[])
        for key,row in weekly.items():
            ev=expected_weeks.get(key,[]);published=row['detail'].get('actual_evidence',[])
            # Unconfigured OCR buckets omit the date field in stored evidence;
            # dates were used independently above solely for week assignment.
            for e in ev:
                if 'end_date' not in e:e.pop('start_date',None)
            expected={e['key']:canonical(e) for e in ev}
            actual={e['key']:canonical(e) for e in published}
            check('unique_declarations',len(actual),len(published),key=key)
            check('exact_time_evidence',actual,expected,key=key)
            known=[e['hours'] for e in ev if e['hours'] is not None]
            total=sum(known) if ev and len(known)==len(ev) else None
            coverage={'known':len(known),'total':len(ev),'sum_known':sum(known) if known else None}
            check('actual_hours',row['values_json'].get('actual_hours'),total,key=key)
            check('actual_coverage',row['detail'].get('actual_coverage'),coverage,key=key)
            report['weeks'].append({'key':key,'areas':sorted(weekly_areas[key]),'machine':row['values_json']['machine'],
                                    'year':row['values_json'].get('year'),'week':row['values_json'].get('week'),
                                    'expected':total,'observed':row['values_json'].get('actual_hours'),
                                    'coverage':coverage,'declarations':list(expected.values())})
        report['resource_cohorts']=resource_evidence
        report['manual_declarations']={'total':len(declarations),'confirmed':sum(bool(d['definition'].get('confirmed')) for d in declarations)}
        report['sources_after']=source_fingerprints(conn)
    assert report['sources_before']==report['sources_after']
    report['result']='failed' if report['failures'] else 'passed'
    (FOLDER/(args.output+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(report['result'],report['checks'],'checks;',len(report['weeks']),'weeks;',len(report['failures']),'failures',flush=True)
    assert not report['failures'],report['failures'][:1]


if __name__=='__main__':main()
