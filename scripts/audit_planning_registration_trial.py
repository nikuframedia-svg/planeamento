"""C03: independently reconcile four local browser pieces in the isolated copy."""
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

FOLDER=Path('docs/validacao-planeamento-integral/20260923-execucao')
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    os.environ['MES_PG_DSN']=json.loads(Path(
        '/home/luis/.local/state/planning-backups/integral-20260923/isolated.json'
    ).read_text())['dsn']
    from app import planning
    from app.raw import query
    from scripts.audit_planning_selected_ocr import source_fingerprints
    baseline=json.loads((FOLDER/'c03-complete-baseline.json').read_text())
    fixture=json.loads((FOLDER/'c03-complete-run.json').read_text())
    browser=json.loads((FOLDER/'c03-complete-zero-fixed.json').read_text())
    assert browser['result']=='passed' and not browser['errors']
    ids={p['id'] for area in fixture['areas'].values() for p in area['pieces']}
    assert len(ids)==4
    report={'at':datetime.now(timezone.utc).isoformat(),'environment':'isolated planning_integral; readonly repeatable read',
            'command':'PYTHONPATH=. .venv/bin/python scripts/audit_planning_registration_trial.py',
            'script_sha256':sha(__file__),'baseline_sha256':sha(FOLDER/'c03-complete-baseline.json'),
            'browser_sha256':sha(FOLDER/'c03-complete-zero-fixed.json'),'areas':{},'failures':[]}
    def equal(actual,expected):
        assert isinstance(actual,(int,float)) and abs(actual-expected)<=max(1e-6,abs(expected)*1e-8),(actual,expected)
    with planning.connect(readonly=True) as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
        current=source_fingerprints(c)
        for table,v in baseline['sources'].items():
            if table!='planning_mtg.needs':assert current[table]==v,table
        needs={str(r['id']):r['hash'] for r in c.execute('SELECT id,md5(to_jsonb(n)::text) hash FROM planning_mtg.needs n')}
        assert set(needs)-set(baseline['needs'])==ids
        assert all(needs[id]==value for id,value in baseline['needs'].items())
        report['preexisting_needs_preserved']=len(baseline['needs'])
        report['source_fingerprints']=current
        rates={r['definition']['area']:r['definition'] for r in baseline['rates']}
        assert {r['kg_m'] for r in baseline['cant_weight_entries']}=={3.77}
        for area,entry in fixture['areas'].items():
            expected_ids={p['id'] for p in entry['pieces']}
            stored=c.execute('SELECT * FROM planning_mtg.needs WHERE production_order_no=%s',(entry['order'],)).fetchall()
            assert {str(n['id']) for n in stored}==expected_ids
            assert c.execute('SELECT count(*) n FROM mes_kanban.production_records WHERE production_order=%s',(entry['order'],)).fetchone()['n']==0
            context=c.execute('SELECT * FROM planning_mtg.local_orders WHERE production_order_no=%s',(entry['order'],)).fetchone()
            assert context['values_json']=={'ov':'OV-C03-'+area,'customer':'Cliente C03 isolado','designation':'Obra C03 '+area,'delivery_date':'2027-01-15'}
            assert c.execute('SELECT count(*) n FROM planning_mtg.local_order_history WHERE production_order_no=%s',(entry['order'],)).fetchone()['n']==1
            rows=query.listing({'area':area,'population':'all','selected':list(expected_ids)},c)
            assert len(rows['rows'])==2 and not rows.get('aggregates_pending')
            capacity=query.listing({'area':area,'dataset':'capacity_items','filters':[{'field':'of','op':'eq','value':entry['order']}]},c)
            assert capacity['total']==2
            rate=10 if area=='perfis' else 20
            assert rates[area]['method']=='units_hour' and rates[area]['value']==rate
            pieces=[]
            for index,piece in enumerate(entry['pieces']):
                id=piece['id'];quantity,length=(15,2500) if index==0 else (8,1500)
                row=next(r for r in rows['rows'] if r['need_id']==id);v=row['values']
                for name,value in {'quantity_required':quantity,'length_mm':length,'remaining':quantity,'quantity_to_plan':quantity,
                                   'total_length':quantity*length,'theoretical_hours':quantity/rate,'cut' if area=='perfis' else 'made':0}.items():equal(v[name],value)
                unit=math.pi*100/1e6*length/1000*7850 if area=='perfis' else 3.77*length/1000
                equal(v['weight_unit'],unit);equal(v['weight'],quantity*unit)
                assert v['planning_active'] and v['preparation_status']=='Rascunho' and v['rate_source']=='Manual'
                ops=c.execute('SELECT * FROM planning_mtg.need_operations WHERE need_id=%s',(id,)).fetchall()
                assert len(ops)==1 and ops[0]['code']==('corte' if area=='perfis' else '112')
                records=c.execute('SELECT * FROM planning_mtg.records WHERE need_id=%s',(id,)).fetchall()
                assert len(records)==1 and records[0]['record_status']=='draft'
                if area=='cantoneiras':assert records[0]['values_json']['operation_detail']=='0'
                assert c.execute('SELECT count(*) n FROM planning_mtg.need_sources WHERE need_id=%s',(id,)).fetchone()['n']==0
                item=next(r for r in capacity['rows'] if r['values']['component_ref']==v['component_ref'])
                assert item['values']['primary_operation'] and item['values']['draft']
                equal(item['values']['planned_hours'],quantity/rate)
                assert item['values']['operation']==ops[0]['code']
                pieces.append({'id':id,'quantity':quantity,'length_mm':length,'expected_unit_weight':unit,
                               'expected_pending_weight':quantity*unit,'expected_hours':quantity/rate,'row':row,
                               'capacity_item':item,'operation_count':1,'record_count':1,'imported_source_count':0})
            report['areas'][area]={'order':entry['order'],'generation':rows['version'],'capacity_generation':capacity['version'],
                                  'local_context':context['values_json'],'pieces':pieces,'ocr_events':0}
    report['result']='passed_in_stated_scope'
    report['boundary']='C03 four local browser pieces, known manual rates and exact property. Existing sources/needs unchanged; no operational writes. Does not approve OCR ingestion, all C05 dependencies or whole C04.'
    (FOLDER/'c03-complete-persistence.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n')
    print('C03 SQL: four pieces, two local orders, draft loads, one operation each, no OCR events, unchanged preexisting needs and source tables.')


if __name__=='__main__':
    main()
