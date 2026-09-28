"""Read-only comparison of the published candidate with the restored real cut."""
import hashlib,json,subprocess
from datetime import datetime,timezone
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

F=Path('docs/validacao-planeamento-integral/20260923-execucao')
P=Path('/home/luis/.local/state/planning-backups/integral-20260923/publication-20260924')


def reconcile_rows(expected,actual,area,dataset):
    """Compare decoded JSON, including numbers such as 0 and 0.0, not JSON text."""
    cursors=[];result={'rows_compared':0,'value_differences':[],'detail_differences':[],
                       'linked_source_refresh_timestamps':[]}
    for c in [expected,actual]:
        gen=query_generation(c,area,dataset)
        from app.raw import query
        base,args=query.source(gen)
        cur=c.cursor(name='published_'+area+'_'+dataset)
        cur.execute('SELECT m.row_key,c.values_json,c.detail'+base+' ORDER BY m.row_key COLLATE "C"',args)
        cursors.append(cur)
    try:
        while True:
            before,after=[cur.fetchmany(256) for cur in cursors]
            assert len(before)==len(after),(area,dataset,'row count')
            if not before:break
            for left,right in zip(before,after):
                assert left['row_key']==right['row_key'],(area,dataset,'row identity')
                key=left['row_key'];result['rows_compared']+=1
                if left['values_json']!=right['values_json']:result['value_differences'].append(key)
                a,b=left['detail'],right['detail']
                if a!=b and dataset=='planning':
                    # The source refresh records when each environment read
                    # the same linked revision. Compare every other fact.
                    x,y=a.get('sources',[]),b.get('sources',[])
                    if len(x)==len(y):
                        for source_left,source_right in zip(x,y):
                            if source_left.get('updated_at')!=source_right.get('updated_at'):
                                old,new=source_left.pop('updated_at',None),source_right.pop('updated_at',None)
                                if source_left==source_right and source_left.get('kind') in ('plan_line','pdf'):
                                    result['linked_source_refresh_timestamps'].append({'key':key,'source':source_left.get('source_id'),
                                        'rehearsed':old,'published':new,'unchanged_source_revision_and_payload':True})
                                else:
                                    source_left['updated_at']=old;source_right['updated_at']=new
                if a!=b:result['detail_differences'].append(key)
    finally:
        for cur in cursors:cur.close()
    return result


def query_generation(conn,area,dataset):
    from app.raw import query
    return query.generation(conn,area,dataset=dataset)


def main():
    load_dotenv('.env')
    from app import planning
    from app.raw import query
    manifest=json.loads((F/'t10-candidate-manifest.json').read_text())
    report={'at':datetime.now(timezone.utc).isoformat(),'candidate':manifest['candidate'],
            'mode':__doc__,'datasets':{},'sources':{},'processes':{},'failures':[]}
    mismatches=[path for path,wanted in manifest['files'].items()
                if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=wanted]
    report['runtime']={'files_checked':len(manifest['files']),'mismatches':mismatches}
    if mismatches:report['failures'].append('candidate_files_changed')
    for unit in ['kanban-planning.service','kanban-raw-worker.service','kanban-mes.service','kanban-mes-mtg2.service']:
        properties=dict(line.split('=',1) for line in subprocess.check_output(
            ['systemctl','--user','show',unit,'-p','MainPID','-p','ActiveState','-p','ActiveEnterTimestamp'],text=True).splitlines())
        assert properties['ActiveState']=='active',unit
        if unit in ['kanban-planning.service','kanban-raw-worker.service']:
            environment=Path('/proc/'+properties['MainPID']+'/environ').read_bytes().split(b'\0')
            candidate=next(v.decode().split('=',1)[1] for v in environment if v.startswith(b'PLANNING_CANDIDATE_ID='))
            assert candidate==manifest['candidate'],unit
            properties['candidate']=candidate
        report['processes'][unit]=properties
    deployed=json.loads((F/'t10-deployment.json').read_text())
    for unit in ['kanban-mes.service','kanban-mes-mtg2.service']:
        assert int(report['processes'][unit]['MainPID'])==deployed['units_before'][unit]
    restore=json.loads((P/'restore.json').read_text())['dsn']
    with psycopg.connect(restore,row_factory=dict_row) as expected,planning.connect(readonly=True) as actual:
        for c,name in [(expected,'planning_restore'),(actual,'dataresearchmtg')]:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            c.execute('SET LOCAL jit=off')
            assert c.execute('SELECT current_database() n').fetchone()['n']==name
        for table in ['mes_kanban.validated_sheets','mes_kanban.production_records','mes_kanban.production_record_plan_refs']:
            sql="SELECT count(*) n,md5(string_agg(h,'' ORDER BY h)) hash FROM (SELECT md5(to_jsonb(t)::text) h FROM "+table+' t) x'
            before,after=[c.execute(sql).fetchone() for c in [expected,actual]]
            report['sources'][table]={'rehearsed':before,'published':after}
            if before!=after:report['failures'].append(table+':source_cut_changed')
        for area in planning.AREAS:
            for dataset in ['planning','production','production_hours','orders','capacity','capacity_items','capacity_machines']:
                key=dataset+':'+area;populations=[]
                for c in [expected,actual]:
                    gen=query.generation(c,area,dataset=dataset);base,args=query.source(gen)
                    data=c.execute("SELECT count(*) n,md5(string_agg(md5(m.row_key||c.values_json::text),'' ORDER BY m.row_key COLLATE \"C\")) values_hash,md5(string_agg(md5(m.row_key||c.detail::text),'' ORDER BY m.row_key COLLATE \"C\")) detail_hash"+base,args).fetchone()
                    populations.append({'generation':gen['id'],**data})
                    if dataset=='planning':
                        assert not gen['metadata'].get('aggregates_pending') and not gen['metadata'].get('source_refresh_pending'),key
                before,after=populations
                same_values=all(before[f]==after[f] for f in ['n','values_hash'])
                same_details=before['detail_hash']==after['detail_hash']
                comparison={}
                if not same_values or not same_details:
                    comparison=reconcile_rows(expected,actual,area,dataset)
                    same_values=not comparison['value_differences']
                    same_details=not comparison['detail_differences']
                report['datasets'][key]={'rehearsed':before,'published':after,'same_values':same_values,'same_details':same_details,
                    'comparison':comparison,'numeric_comparison':'JSON numeric values compare exactly; decimal formatting is not a value difference.'}
                if not same_values:report['failures'].append(key+':values')
                if not same_details:report['failures'].append(key+':provenance')
                print(key,'values',same_values,'detail',same_details,flush=True)
    report['result']='failed' if report['failures'] else 'passed'
    (F/'t10-published-candidate-comparison.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
    print(report['result'],report['failures'],flush=True)
    assert not report['failures']


if __name__=='__main__':main()
