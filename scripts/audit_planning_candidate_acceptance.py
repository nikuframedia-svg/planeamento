"""Bridge the nine independent audits to the final retained candidate values."""
import hashlib,json,os
from datetime import datetime,timezone
from pathlib import Path

F=Path('docs/validacao-planeamento-integral/20260923-execucao')
P=Path('/home/luis/.local/state/planning-backups/integral-20260923')


def main():
    os.environ['MES_PG_DSN']=json.loads((P/'isolated.json').read_text())['dsn'];os.environ['MES_DATA_DIR']='/tmp/planning-integral-data'
    from app import planning,planning_needs as needs
    from app.raw import query
    batch=json.loads((F/'t10-rule-batch.json').read_text());assert batch['result']=='passed'
    report={'at':datetime.now(timezone.utc).isoformat(),'environment':'planning_integral; read-only repeatable read',
            'method':__doc__,'rules':{},'audits':{},'bridges':{},'source_bridges':{},'failures':[]}
    with planning.connect(readonly=True) as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ');c.execute('SET LOCAL jit=off')
        assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
        def rows(gen):
            sql,args=query.source(gen);result={};kind=gen['dataset'].split(':')[0]
            for r in c.execute("SELECT m.row_key,c.values_json,c.detail->>'need_id' need_id,c.detail->>'plan_key' plan_key"+sql,args):
                key=r['row_key']
                if kind in ('planning','capacity_items'):
                    key=str(r['need_id']) if r['need_id'] else 'excel:'+str(r['plan_key']).rsplit(':',1)[-1]
                    if kind=='capacity_items':key+=':'+str(r['values_json']['operation'])+':'+str(r['values_json']['machine_key'])
                assert key not in result,(gen['dataset'],key)
                result[key]=r['values_json']
            return result
        def bridge(area,dataset,version):
            key=f'{dataset}:{area}:{version}'
            if key in report['bridges']:return key
            old=query.generation(c,area,version,dataset=dataset);new=query.generation(c,area,dataset=dataset)
            before,after=rows(old),rows(new)
            missing=sorted(before.keys()-after.keys());extra=sorted(after.keys()-before.keys())
            changes=[k for k in before.keys()&after.keys() if before[k]!=after[k]]
            report['bridges'][key]={'before':old['id'],'current':new['id'],'rows_before':len(before),'rows_current':len(after),
                'missing':missing,'extra':extra,'changed_values':changes,'sha256':needs.digest(after)}
            if missing or extra or changes:report['failures'].append(key)
            if dataset=='planning':
                a,b=old['metadata']['snapshot']['snapshot_id'],new['metadata']['snapshot']['snapshot_id']
                macro=[]
                for snap in (a,b):
                    cache=needs.digest(['macro-order-inputs-v5',area,snap])
                    stored=c.execute("SELECT detail->'macro_inputs' value FROM planning_mtg.raw_contents WHERE hash=%s",(cache,)).fetchone()
                    assert stored,(area,snap);macro.append(stored['value'])
                same=macro[0]==macro[1]
                report['source_bridges'][area]={'audited_macro':a,'current_macro':b,'every_normalized_macro_field_and_raw_cell_unchanged':same}
                if not same:report['failures'].append(area+':macro_inputs')
            return key
        for item in batch['audits']:
            file=F/item['report'];data=json.loads(file.read_text());assert data['result'].startswith('passed') and not data['failures']
            rules=data.get('rules') or sorted({r for a in data.get('areas',{}).values() for r in a.get('by_rule',{})})
            bridges=[]
            for area,v in data.get('areas',{}).items():
                version=v.get('generation',v.get('version'))
                if version:bridges.append(bridge(area,'planning',version))
                if v.get('capacity_generation'):bridges.append(bridge(area,'capacity_items',v['capacity_generation']))
            for area,versions in data.get('versions',{}).items():
                for dataset,version in versions.items():bridges.append(bridge(area,dataset,version))
            report['audits'][file.name]={'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'bridges':sorted(set(bridges)),'result':data['result']}
            for rule in rules:report['rules'].setdefault(rule,[]).append(file.name)
        expected={f'F{i:02}' for i in range(1,22)}|{f'G{i:02}' for i in range(1,13)}|{f'H{i:02}' for i in range(1,11)}
        assert set(report['rules'])==expected,expected-set(report['rules'])
        historical=json.loads((F/'t10-capacity.json').read_text())
        for area,versions in historical['versions'].items():
            old=query.generation(c,area,versions['capacity'],dataset='capacity');new=query.generation(c,area,dataset='capacity')
            for field in ['history_inputs_hash','reference_inputs','configuration_digest']:
                assert old['metadata'][field]==new['metadata'][field],(area,field)
                report['source_bridges'][area][field+'_unchanged']=True
    report['required_cases']={'V01':['c05-v01-preview-api.json','tests/test_planning_integral_calculations.py'],
        'V02':['t10-formula.json','tests/test_planning_integral_calculations.py'],
        'V03':['t10-production-sources.json','tests/test_planning_integral_calculations.py'],
        'V04':['t10-operation-hours.json','tests/test_planning_integral_calculations.py'],
        'V05':['t10-capacity.json','tests/test_capacity_revision.py'],
        'V06':['t10-v06-browser.json','t10-v06-completion-browser.json','t10-v06-final-ui-browser.json','t10-v06-exports.json']}
    report['timing_acceptance']='User instruction 24/09: retain measured aggregate latency as a reported limitation, without blocking publication at 10 seconds.'
    report['result']='failed' if report['failures'] else 'passed'
    (F/'t10-final-rule-acceptance.json').write_text(json.dumps(report,indent=2,ensure_ascii=False,default=str)+'\n')
    print(report['result'],len(report['rules']),'rules',len(report['bridges']),'population bridges',report['failures'],flush=True)
    assert not report['failures']


if __name__=='__main__':main()
