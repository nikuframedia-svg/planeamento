"""Reuse independent rule audits only when their published populations still match."""
from datetime import datetime,timezone
from pathlib import Path
import hashlib,json,os

F=Path('docs/validacao-planeamento-integral/20260923-execucao')
PROOFS=['c04-derived-details-arithmetic.json','c04-derived-details-semantic.json',
    'c04-capacity-arithmetic-current.json','c04-operation-hours-first.json',
    'c04-rate-selection-first.json','c04-actual-hours-current.json',
    'c10-historical-cohorts-final.json','c02-source-policy-population.json']


def main():
    os.environ['MES_PG_DSN']=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
    from app import planning
    from app.raw import query
    from scripts.audit_planning_selected_ocr import source_fingerprints
    report={'at':datetime.now(timezone.utc).isoformat(),'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'environment':'planning_integral; read-only repeatable transaction','audits':{},'rules':{},'bridges':{},'failures':[],
        'boundary':'Reuses independent expectations, never the application calculator as an oracle. Current original-source fixtures have separate tests; real original ingestion and Calibri remain separate acceptance gates.'}
    with planning.connect(readonly=True) as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ');c.execute('SET LOCAL jit=off')
        assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
        sources=source_fingerprints(c);report['sources']=sources
        def bridge(area,dataset,version):
            key=f'{dataset}:{area}:{version}'
            if key in report['bridges']:return key
            old=query.generation(c,area,version,dataset=dataset);new=query.generation(c,area,dataset=dataset)
            osql,oa=query.source(old);nsql,na=query.source(new)
            comparison=c.execute('WITH old AS (SELECT m.row_key,c.values_json'+osql+'), new AS (SELECT m.row_key,c.values_json'+nsql+''')
                SELECT count(*) n,count(*) FILTER(WHERE old.row_key IS NULL OR new.row_key IS NULL) identities_changed,
                    count(*) FILTER(WHERE old.values_json IS DISTINCT FROM new.values_json) values_changed
                FROM old FULL JOIN new USING(row_key)''',oa+na).fetchone()
            report['bridges'][key]={**comparison,'reference':old['id'],'current':new['id']}
            if comparison['identities_changed'] or comparison['values_changed']:report['failures'].append(key)
            return key
        for name in PROOFS:
            data=json.loads((F/name).read_text())
            assert data['result'].startswith('passed') and not data['failures'],name
            if 'sources_after' in data:assert data['sources_after']==sources,name
            rules=data.get('rules') or sorted({r for a in data['areas'].values() for r in a['by_rule']})
            bridges=[]
            for area,v in data.get('areas',{}).items():
                version=v.get('generation',v.get('version'))
                if version:bridges.append(bridge(area,'planning',version))
                if v.get('capacity_generation'):bridges.append(bridge(area,'capacity_items',v['capacity_generation']))
            for area,versions in data.get('versions',{}).items():
                for dataset,version in versions.items():bridges.append(bridge(area,dataset,version))
            report['audits'][name]={'sha256':hashlib.sha256((F/name).read_bytes()).hexdigest(),
                'independent_checks':data.get('checks'),'source_cut_verified':'sources_after' in data,
                'reference_bridges':sorted(set(bridges)),'result':data['result']}
            for rule in rules:report['rules'].setdefault(rule,[]).append(name)
        expected={f'F{i:02}' for i in range(1,22)}|{f'G{i:02}' for i in range(1,13)}|{f'H{i:02}' for i in range(1,11)}
        assert set(report['rules'])==expected,(expected-set(report['rules']))
        report['current_planning']={area:query.generation(c,area)['id'] for area in planning.AREAS}
    report['coverage']='c04-derived-details-population.json'
    report['excel_comparison']='c04-reconciled-cache-comparison.json'
    report['current_rebuild']='t5-current-rebuild.json'
    report['restart']='t7-persistence-after.json'
    report['required_cases']={
        'V01':['c00-current-v01.json','c05-v01-preview-api.json','tests/test_planning_integral_calculations.py'],
        'V02':['tests/test_planning_integral_calculations.py','c04-derived-details-arithmetic.json'],
        'V03':['tests/test_planning_integral_calculations.py','c02-source-policy-population.json'],
        'V04':['tests/test_planning_integral_calculations.py','c04-operation-hours-first.json'],
        'V05':['tests/test_capacity_revision.py','c04-capacity-arithmetic-current.json'],
        'V06':{'state':'incomplete','remaining':'Combine creation, edits, configuration, OCR, closure by each source and reopening on the same retained identities, with all timings. Separate component proofs do not yet certify that cumulative sequence.'}}
    report['result']='passed_in_stated_scope' if not report['failures'] else 'failed'
    (F/'t5-final-rule-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n')
    print(report['result'],'rules',len(report['rules']),'population bridges',len(report['bridges']),'failures',report['failures'])
    assert not report['failures']


if __name__=='__main__':main()
