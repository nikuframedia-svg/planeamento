"""Compare retained V06 API rows, database revisions and both export formats."""
import csv,hashlib,json,math,os
from datetime import datetime,timezone
from pathlib import Path
import openpyxl

F=Path('docs/validacao-planeamento-integral/20260923-execucao')
P=Path('/home/luis/.local/state/planning-backups/integral-20260923')


def equivalent(observed,expected):
    if expected in (None,''):return observed in (None,'')
    if isinstance(expected,bool):return str(observed).lower()==str(expected).lower()
    if isinstance(expected,(float,int)):
        try:return math.isclose(float(str(observed).replace(',','.')),expected,rel_tol=1e-10,abs_tol=1e-8)
        except (TypeError,ValueError):return False
    return str(observed)==str(expected)


def main():
    os.environ['MES_PG_DSN']=json.loads((P/'isolated.json').read_text())['dsn']
    from app import planning
    from app.raw import query
    evidence=json.loads((F/'t10-v06-browser.json').read_text())
    report={'at':datetime.now(timezone.utc).isoformat(),'environment':'planning_integral; read-only',
            'method':'Compare each recorded API revision with the immutable database generation and its CSV/XLSX values.',
            'steps':[],'checks':0,'failures':[]}
    with planning.connect(readonly=True) as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
        for area in evidence['areas']:
            for step in area['steps']:
                assert step.get('validated') or step.get('history_events') is not None
                gen=query.generation(c,area['area'],step['version']);sql,args=query.source(gen)
                row=c.execute('SELECT c.values_json,c.detail'+sql+' AND m.row_key=%s',args+[step['row']['key']]).fetchone()
                assert row
                if row['values_json']!=step['row']['values']:report['failures'].append(area['area']+':'+step['name']+':database_values')
                if row['detail']['revision']!=step['need_revision']:report['failures'].append(area['area']+':'+step['name']+':database_revision')
                report['checks']+=2
                files={}
                for fmt in ['csv','xlsx']:
                    file=Path(step['exports'][fmt])
                    if fmt=='csv':
                        with file.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.reader(f,delimiter=';'))
                    else:
                        book=openpyxl.load_workbook(file,read_only=True,data_only=True);rows=list(book.active.values);book.close()
                    assert len(rows)==2,(file,len(rows))
                    for field,observed,expected in zip(step['exports']['columns'],rows[1],step['exports']['expected'],strict=True):
                        report['checks']+=1
                        if not equivalent(observed,expected):report['failures'].append({'area':area['area'],'step':step['name'],'format':fmt,'field':field,'observed':observed,'expected':expected})
                    files[fmt]={'file':str(file),'sha256':hashlib.sha256(file.read_bytes()).hexdigest()}
                report['steps'].append({'area':area['area'],'name':step['name'],'need_id':area['need_id'],'generation':step['version'],'need_revision':step['need_revision'],'history_events':step['history_events'],'files':files})
    report['result']='failed' if report['failures'] else 'passed'
    (F/'t10-v06-exports.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print(report['result'],report['checks'],'checks;',len(report['failures']),'failures')
    assert not report['failures']


if __name__=='__main__':main()
