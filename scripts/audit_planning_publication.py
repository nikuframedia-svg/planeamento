"""Read back C05 browser writes in the full isolated copy, including exports."""
import argparse,csv,io,json,os
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import Request,urlopen
from openpyxl import load_workbook

parser=argparse.ArgumentParser()
parser.add_argument('--stage',choices=['before-restart','after-restart','after-rebuild'],required=True)
args=parser.parse_args()
folder=Path('docs/validacao-planeamento-integral/20260923-execucao')
os.environ['MES_PG_DSN']=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
from app import planning
from app.raw import query
base='http://127.0.0.1:18113'
report={'at':datetime.now(timezone.utc).isoformat(),'stage':args.stage,'base':base,
        'environment':'isolated full copy localhost44164 / planning_integral','areas':[]}
browser=json.loads((folder/'c05-publish-browser.json').read_text())
assert not browser.get('failure') and not browser['errors']

def post(path,payload):
    request=Request(base+path,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
    return urlopen(request,timeout=30).read()

with planning.connect(readonly=True) as c:
    assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
    for trial in browser['areas']:
        area=trial['area'];original=trial['final'];second=next(r for r in trial['second']['publication']['rows'] if r['area']==area)
        ids=[original['need_id'],second['need_id']];params={'area':area,'selected':ids,
            'columns':['component_ref','quantity_required','remaining']+(['bars'] if area=='perfis' else [])}
        actual=json.loads(post('/planeamento/api/raw/consultas',params))
        assert len(actual['rows'])==2
        sqlrows=query.listing(params,conn=c)['rows']
        assert sorted(sqlrows,key=lambda r:r['key'])==sorted(actual['rows'],key=lambda r:r['key'])
        expected={r['need_id']:r for r in [original,second]}
        for row in actual['rows']:
            want=expected[row['need_id']]
            assert row['revision']==want['revision']
            assert row['values']['remaining']==row['values']['quantity_required']==want['values']['quantity_required']
            saved=c.execute('SELECT revision,quantity_required FROM planning_mtg.needs WHERE id=%s',(row['need_id'],)).fetchone()
            assert saved['revision']==row['revision'] and saved['quantity_required']==row['values']['quantity_required']
            if area=='perfis' and row['need_id']==second['need_id']:assert row['values']['bars']==4
        csv_data=post('/planeamento/api/raw/exportar/csv',params).decode('utf-8-sig')
        csv_rows=list(csv.reader(io.StringIO(csv_data),delimiter=';'))[1:]
        xlsx_data=post('/planeamento/api/raw/exportar/xlsx',params)
        book=load_workbook(io.BytesIO(xlsx_data),data_only=True)
        xlsx_rows=list(book['RAW'].values)[1:]
        normalized={r['values']['component_ref']:[r['values'].get(k) for k in params['columns'][1:]] for r in actual['rows']}
        assert {r[0]:[None if v=='' else float(v.replace(',','.')) for v in r[1:]] for r in csv_rows}==normalized
        assert {r[0]:list(r[1:]) for r in xlsx_rows}==normalized
        for name,body in [('csv',csv_data),('xlsx',xlsx_data)]:
            path=folder/f'c05-published-{args.stage}-{area}.{name}'
            path.write_bytes(body if isinstance(body,bytes) else body.encode())
        report['areas'].append({'area':area,'version':actual['version'],'pending':{
            k:actual.get(k,False) for k in ['aggregates_pending','source_refresh_pending']},
            'rows':[{'id':r['need_id'],'revision':r['revision'],'of':r['values']['of'],
                     'values':normalized[r['values']['component_ref']]} for r in actual['rows']],
            'csv_rows':csv_rows,'xlsx_rows':xlsx_rows,
            'browser_timings_ms':{k:{f:trial[k][f] for f in ['requestMs','responseToVisibleMs']} for k in ['form','raw']}})
        for k in ['form','raw']:assert trial[k]['responseToVisibleMs']<=2000
report['result']='passed'
(folder/f'c05-publication-{args.stage}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n')
print('Passed: same revisions in stored needs, published projections, API, CSV and XLSX; browser response to visible <=2s in both areas.')
