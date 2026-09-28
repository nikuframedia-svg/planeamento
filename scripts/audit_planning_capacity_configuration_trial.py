"""Reconcile C09 configuration UI results against independent arithmetic and SQL."""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

FOLDER=Path('docs/validacao-planeamento-integral/20260923-execucao')
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    os.environ['MES_PG_DSN']=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
    from app import planning
    from app.raw import query
    from scripts.audit_planning_selected_ocr import source_fingerprints
    baseline=json.loads((FOLDER/'c09-complete-baseline.json').read_text())
    browser=json.loads((FOLDER/'c09-complete-final.json').read_text())
    fixture=json.loads((FOLDER/'c03-complete-run.json').read_text())
    assert browser['result']=='passed' and not browser['errors']
    assert browser['script_sha256']==sha('tests/planning_capacity_complete_browser.cjs')
    if browser.get('resumed_source'):
        resume=browser['resumed_source']
        assert resume['sha256']==sha(FOLDER/resume['file'])
        previous=json.loads((FOLDER/resume['file']).read_text())
        assert previous['error'].startswith('page.screenshot: Timeout')
        assert previous['script_sha256']==sha(FOLDER/'c09-complete-capture-trial-browser.cjs')
        for area,data in previous['areas'].items():
            assert data['steps']==browser['areas'][area]['steps']
            assert data['rejected']==browser['areas'][area]['rejected']
            assert browser['areas'][area]['resume_validation']['values']['actual_hours']==6
    report={'at':datetime.now(timezone.utc).isoformat(),'environment':'isolated planning_integral; read-only repeatable read',
            'script_sha256':sha(__file__),'browser_sha256':sha(FOLDER/'c09-complete-final.json'),
            'baseline_sha256':sha(FOLDER/'c09-complete-baseline.json'),'areas':{},'failures':[]}

    def equal(actual,expected):
        if expected is None:assert actual is None
        else:assert isinstance(actual,(int,float)) and abs(actual-expected)<=max(1e-6,abs(expected)*1e-8),(actual,expected)

    def expected(settings):
        rate=60/settings['rate'] if settings['method']=='minutes_unit' else settings['rate']
        available=settings['shifts']*settings['hours']-settings['exception']
        load=23/rate
        result={'available_hours':available,'planned_hours':load,'free_hours':available-load,
                'occupancy':100*load/available if available>0 else None,'equivalent_shifts':load/settings['hours'],
                'capacity_total':available*rate,'capacity_free':(available-load)*rate,'pending_quantity':23,'lines_total':2}
        if 'actual' in settings:result['actual_hours']=settings['actual']
        return result

    allowed_changes=set()
    for area,data in browser['areas'].items():
        assert len(data['steps'])==11 and len(data['rejected'])==4
        for step in data['steps']:
            independent=expected(step['settings'])
            for key,value in independent.items():
                equal(step['values'][key],value)
                equal(step['api']['rows'][0]['values'][key],value)
                equal(step['expected'][key],value)
            if step['saved']:
                assert step['response_to_visible_ms']<=10000
                allowed_changes.add(step['saved']['response']['id'])
            if step['name'].startswith('horas_reais_'):
                assert step['shown'][7]==str(step['settings']['actual'])
                assert step['values']['available_hours']==16
        assert [s['name'] for s in data['steps']][-2:]==['horas_reais_7','horas_reais_6']
        allowed_changes.update(data[k]['response']['id'] for k in ['reset_calendar','reset_rate'])

    with planning.connect(readonly=True) as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
        sources=source_fingerprints(c);assert sources==baseline['source_fingerprints']
        needs={str(r['id']):r['hash'] for r in c.execute('SELECT id,md5(to_jsonb(n)::text) hash FROM planning_mtg.needs n')}
        assert needs==baseline['needs']
        current={str(r['id']):json.loads(json.dumps(dict(r),default=str)) for r in c.execute("SELECT * FROM planning_mtg.raw_objects WHERE kind IN ('resource','calendar','rate','worked_hours')")}
        original={r['id']:r for r in baseline['objects']}
        assert set(current)-set(original)<=allowed_changes
        assert all(current[id]==row for id,row in original.items() if id not in allowed_changes)
        assert len(set(current)-set(original))==2
        report.update(source_fingerprints=sources,preexisting_needs_preserved=len(needs),configuration_ids_changed=sorted(allowed_changes),new_worked_hours=2,
                      unchanged_other_configurations=sum(id not in allowed_changes for id in original))
        for area,entry in fixture['areas'].items():
            name='C05 Ensaio '+area+' 1'
            conditions=[{'field':k,'op':'eq','value':v} for k,v in [('machine',name),('year',2027),('week',1)]]
            weekly=query.listing({'area':area,'dataset':'capacity','filters':conditions},c)
            assert weekly['total']==1
            row=weekly['rows'][0]
            final={'shifts':3,'hours':6,'exception':2,'method':'minutes_unit','rate':4,'actual':6}
            for key,value in expected(final).items():equal(row['values'][key],value)
            assert row['capacity_unit']=='un.' and not row['calendar_conflict']
            assert len(row['actual_evidence'])==1 and row['actual_evidence'][0]['origin']=='Manual'
            assert not row['actual_evidence'][0]['sheets']
            ids=[p['id'] for p in entry['pieces']]
            raw=query.listing({'area':area,'population':'all','selected':ids},c)
            assert raw['total']==2 and not raw.get('aggregates_pending')
            for i,id in enumerate(ids):
                v=next(r['values'] for r in raw['rows'] if r['need_id']==id)
                q=15 if i==0 else 8
                equal(v['remaining'],q);equal(v['theoretical_hours'],q*4/60)
                equal(v['hours_pct'],100*(23*4/60)/16)
                assert v['rate_source']=='Manual' and v['preparation_status']=='Rascunho'
            objects=[r for r in current.values() if r['id'] in allowed_changes and
                     (r['name'].startswith(name) or r['name']=='C09 Completo horas '+area)]
            assert len(objects)==3
            histories={}
            for obj in objects:
                versions=[dict(v) for v in c.execute('SELECT * FROM planning_mtg.raw_object_versions WHERE object_id=%s ORDER BY revision',(obj['id'],))]
                assert [v['revision'] for v in versions]==list(range(1,obj['revision']+1))
                assert versions[-1]['definition']==obj['definition']
                histories[obj['id']]=versions
            report['areas'][area]={'generation':raw['version'],'capacity_generation':weekly['version'],
                'expected':expected(final),'row':row,'raw':raw['rows'],'histories':histories,
                'max_response_to_visible_ms':max(s['response_to_visible_ms'] or 0 for s in browser['areas'][area]['steps'])}
    report['result']='passed_in_stated_scope'
    report['boundary']='C09 configurations and H01-H08 in two isolated resources; complements shared-resource/overlap integration tests. Does not prove full C05/C10 matrix or final publication.'
    (FOLDER/'c09-complete-persistence.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n')
    print('C09 SQL and independent arithmetic: 22 states, six configuration IDs, two new manual-hour declarations; all ten needs and central sources preserved.')


if __name__=='__main__':main()
