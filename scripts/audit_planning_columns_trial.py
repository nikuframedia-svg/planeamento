"""Verify persisted C07 browser views without writing business or source data."""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

FOLDER=Path('docs/validacao-planeamento-integral/20260923-execucao')
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    os.environ['MES_PG_DSN']=json.loads(Path(
        '/home/luis/.local/state/planning-backups/integral-20260923/isolated.json'
    ).read_text())['dsn']
    from app import planning
    from app.raw import query
    from scripts.audit_planning_selected_ocr import source_fingerprints
    fixture=json.loads((FOLDER/'c07-complete-fixture.json').read_text())
    browser=json.loads((FOLDER/'c07-complete-focus-fixed.json').read_text())
    assert browser['result']=='passed' and not browser['errors']
    assert browser['base']=='http://127.0.0.1:18113'
    result={'at':datetime.now(timezone.utc).isoformat(),'environment':'isolated planning_integral',
            'browser_sha256':sha(FOLDER/'c07-complete-focus-fixed.json'),'areas':{}}
    with planning.connect(readonly=True) as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
        sources=source_fingerprints(c)
        assert sources==fixture['sources_before']
        result['source_fingerprints']=sources
        for area, proof in browser['areas'].items():
            assert query.generation(c,area)['id']==fixture['generations'][area]
            saved=c.execute('SELECT * FROM planning_mtg.raw_objects WHERE id=%s',(proof['saved']['id'],)).fetchone()
            assert saved['kind']=='view' and saved['area']==area and saved['revision']==1 and not saved['archived']
            for k,v in proof['layout'].items():assert saved['definition'][k]==v
            versions=c.execute('SELECT * FROM planning_mtg.raw_object_versions WHERE object_id=%s',(saved['id'],)).fetchall()
            assert len(versions)==1 and versions[0]['definition']==saved['definition']
            legacy=c.execute('SELECT * FROM planning_mtg.raw_objects WHERE id=%s',(fixture['views'][area]['id'],)).fetchone()
            assert legacy['definition']==fixture['views'][area]['raw_definition'] and legacy['revision']==1
            assert len(proof['arrow_moves'])==40
            assert all(x['before']['scroll']==x['after']['scroll']>0 for x in proof['arrow_moves'])
            starts=[x for x in proof['drag_trace'] if x['type']=='dragstart']
            assert len(starts)==2 and all(x['id']=='of' and x['trusted'] for x in starts)
            result['areas'][area]={'generation':fixture['generations'][area], 'saved_view':str(saved['id']),
                'saved_definition':saved['definition'],'legacy_view':str(legacy['id']),
                'legacy_stored_definition_unchanged':True,'arrow_moves':40,'native_drags':2,
                'resize':proof['resize'],'reset':proof['reset']}
    preserved=json.loads((FOLDER/'preexisting-tracked-preservation.json').read_text())
    assert all(sha(x['path'])==x['baseline_sha256'] for x in preserved)
    result['preexisting_tracked_preserved']=len(preserved)
    previous=json.loads((FOLDER/'c04-reconciled-cache-final-state.json').read_text())
    for pid,cmd in previous['operational_processes'].items():
        assert Path('/proc',pid,'cmdline').read_bytes().replace(b'\0',b' ').decode().strip()==cmd
    assert Path('/proc',str(previous['isolated_server_pid']),'cmdline').read_bytes().replace(b'\0',b' ').decode().strip()==previous['isolated_command']
    result['operational_processes']=previous['operational_processes']
    result['isolated_server_pid']=previous['isolated_server_pid']
    result['isolated_command']=previous['isolated_command']
    with urlopen('http://127.0.0.1:18113/static/raw_workspace.js',timeout=10) as response:
        served=hashlib.sha256(response.read()).hexdigest()
    assert served==sha('app/web/static/raw_workspace.js')
    result['served_workspace_js_sha256']=served
    result['result']='passed_in_stated_scope'
    result['boundary']='C07 layout only. Two legacy fixture views and two saved browser views added only to the isolated database; source/need tables and planning generations unchanged. No operational service restart.'
    (FOLDER/'c07-complete-persistence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n')
    print('C07: persisted layouts/history, legacy definitions, source fingerprints, generations and served JS verified.')


if __name__=='__main__':
    main()
