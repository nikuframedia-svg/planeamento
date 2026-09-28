"""Check analytical CSV/XLSX result columns against the independent UI fixture."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
import re
from pathlib import Path
from urllib.request import Request, urlopen

from openpyxl import load_workbook

FOLDER = Path('docs/validacao-planeamento-integral/20260923-execucao')
BASE = os.environ.get('PLANNING_CHECK_BASE')
assert BASE == 'http://127.0.0.1:18113' and os.environ.get('PLANNING_TEST_ISOLATED') == '1'


def post(path, payload):
    request = Request(BASE + path, data=json.dumps(payload).encode(),
        headers={'Content-Type':'application/json','Origin':BASE})
    with urlopen(request, timeout=30) as response:
        assert response.status == 200
        return response.read()


parser=argparse.ArgumentParser()
parser.add_argument('--fixture',default='c04-result-columns-browser.json')
parser.add_argument('--output',default='c04-result-columns')
args=parser.parse_args()
if not re.fullmatch(r'[a-z0-9-]+\.json',args.fixture) or not re.fullmatch(r'[a-z0-9-]+',args.output):
    parser.error('Use simple proof filenames/prefixes')
fixture = json.loads((FOLDER/args.fixture).read_text())
assert fixture['result'] == 'passed'
report = {'at':datetime.now(timezone.utc).isoformat(), 'base':BASE,
          'command':f'PLANNING_CHECK_BASE=http://127.0.0.1:18113 PLANNING_TEST_ISOLATED=1 .venv/bin/python scripts/audit_planning_result_exports.py --fixture {args.fixture} --output {args.output}',
          'method':'Exports use the same frozen publication as the API. Expected numeric values were independently computed for the browser fixture; neither export is the oracle for the other.',
          'fixture_file':args.fixture,
          'fixture_sha256':hashlib.sha256((FOLDER/args.fixture).read_bytes()).hexdigest(),
          'exports':[]}
for index, sample in enumerate(fixture['samples']):
    payload={'area':sample['area'],'population':'all','selected':[sample['key']],
             'columns':['component_ref',*sample['expected']]}
    api=json.loads(post('/planeamento/api/raw/consultas',payload))
    assert len(api['rows'])==1
    payload['version']=api['version']
    labels={field['id']:field['label'] for field in api['columns']}
    for extension in ('csv','xlsx'):
        data=post('/planeamento/api/raw/exportar/'+extension,payload)
        path=FOLDER/f'{args.output}-export-{index}.{extension}'
        path.write_bytes(data)
        if extension=='csv':
            rows=list(csv.reader(io.StringIO(data.decode('utf-8-sig')),delimiter=';'))
        else:
            book=load_workbook(io.BytesIO(data),read_only=True,data_only=True)
            rows=list(book['RAW'].values);book.close()
        assert len(rows)==2 and list(rows[0])==[labels[field] for field in payload['columns']]
        assert rows[1][0]==sample['reference']
        observed={}
        for column,(field,expected) in enumerate(sample['expected'].items(),1):
            raw=rows[1][column]
            value=None if raw in (None,'') else float(str(raw).replace(',','.'))
            observed[field]=value
            if expected is None:
                assert value is None,(sample['key'],field,value)
            else:
                assert value is not None and abs(value-expected)<=max(1e-6,abs(expected)*1e-8),(sample['key'],field,expected,value)
        report['exports'].append({'file':path.name,'sha256':hashlib.sha256(data).hexdigest(),
            'request':payload,'expected':sample['expected'],'observed':observed,'result':'passed'})
report['result']='passed'
(FOLDER/(args.output+'-exports.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(len(report['exports']),'CSV/XLSX exports passed; unknown values remain blank')
