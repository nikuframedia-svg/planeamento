"""Read the browser's XLSX files and reconcile its final saved revisions with PostgreSQL."""
import json
import math
import os
from urllib.request import Request, urlopen
from pathlib import Path
from datetime import datetime, timezone
from openpyxl import load_workbook

folder=Path('docs/validacao-planeamento-integral/20260923-execucao')
os.environ['MES_PG_DSN']=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
from app import planning, planning_needs as needs
from app.raw import query

browser=json.loads((folder/'c05-f12-save-browser.json').read_text())
assert browser['result']=='passed'
report={'at':datetime.now(timezone.utc).isoformat(),'environment':'isolated full copy localhost44164/18113','areas':[]}
with planning.connect(readonly=True) as c:
    c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
    assert c.execute('SELECT current_database() name').fetchone()['name']=='planning_integral'
    for area in browser['areas']:
        evidence={'area':area['area'],'need_id':area['need_id'],'exports':[]}
        for step in area['steps']:
            book=load_workbook(step['xlsx'],read_only=True,data_only=True)
            rows=list(book['RAW'].values);assert len(rows)==2
            assert all(math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-8) for a,b in zip(rows[1],step['csv']['values']))
            evidence['exports'].append({'quantity':step['quantity'],'file':step['xlsx'],'headers':rows[0],'values':rows[1]})
            book.close()
        final=area['steps'][-1]
        need=needs.load(c,area['need_id'])
        data=query.listing({'area':area['area'],'selected':[area['need_id']]},conn=c)
        row=data['rows'][0];gen=query.generation(c,area['area'])
        assert need['revision']==row['revision']==final['save']['revision']
        assert need['quantity_required']==row['values']['quantity_required']==40
        assert not gen['metadata'].get('aggregates_pending') and not gen['metadata'].get('source_refresh_pending')
        assert row['values']==final['actual']['values']
        request=Request('http://127.0.0.1:18113/planeamento/api/raw/consultas',
            data=json.dumps({'area':area['area'],'selected':[area['need_id']]}).encode(),
            headers={'Content-Type':'application/json'})
        with urlopen(request,timeout=30) as response:api=json.load(response)
        assert api['rows'][0]['revision']==row['revision']
        assert api['rows'][0]['values']==needs.serial(row['values'])
        assert not api.get('aggregates_pending') and not api.get('source_refresh_pending')
        evidence['api_after_restart']={'revision':api['rows'][0]['revision'],'values':api['rows'][0]['values'],
            'aggregates_pending':api.get('aggregates_pending'),'source_refresh_pending':api.get('source_refresh_pending')}
        evidence.update(revision=row['revision'],values=row['values'],generation=gen['id'],metadata=gen['metadata'])
        report['areas'].append(evidence)
report['result']='passed'
(folder/'c05-f12-saved-audit.json').write_text(json.dumps(needs.serial(report),ensure_ascii=False,indent=2)+'\n')
print(sum(len(a['exports']) for a in report['areas']),'XLSX exports and both final database revisions equal the browser and CSV; Q40 restored in both areas.',flush=True)
