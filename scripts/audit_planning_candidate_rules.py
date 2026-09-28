"""Run the independent rule auditors on one read-only repeatable database cut.

The complete source fingerprint is computed once for this transaction and reused
by its auditors. Their expected-value calculations remain separate implementations.
"""
import argparse,importlib,json,os,sys,time
from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path

F=Path('docs/validacao-planeamento-integral/20260923-execucao')
P=Path('/home/luis/.local/state/planning-backups/integral-20260923')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--only');parser.add_argument('--reuse-snapshot',action='store_true');options=parser.parse_args()
    os.environ['MES_PG_DSN']=json.loads((P/'isolated.json').read_text())['dsn'];os.environ['MES_DATA_DIR']='/tmp/planning-integral-data'
    from app import planning
    from scripts import audit_planning_selected_ocr as fingerprints
    original_connect=planning.connect;original_fingerprints=fingerprints.source_fingerprints
    book=str(P/'source-workbooks/Met2_Plan_Perfis.xlsm')
    jobs=[('formula_population','formula',['--workbook-root',str(P/'source-workbooks')]),
          ('calculation_details','details',[]),('semantic_results','semantic',['--require-detail']),
          ('capacity_arithmetic','capacity',[]),('operation_hours','operation-hours',['--require-detail','--workbook',book]),
          ('rate_selection','rate-selection',['--workbook',book]),('actual_hours','actual-hours',[]),
          ('historical_cohorts','historical-cohorts',[]),('production_sources','production-sources',[])]
    previous=json.loads((F/'t10-rule-batch.json').read_text()) if options.only else None
    if options.only:
        assert options.only in {j[1] for j in jobs};jobs=[j for j in jobs if j[1]==options.only]
    report={'at':datetime.now(timezone.utc).isoformat(),'environment':'planning_integral',
            'method':__doc__,'audits':[],'failures':[]}
    with original_connect(readonly=True) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ');conn.execute('SET LOCAL jit=off')
        assert conn.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
        assert conn.execute('SHOW transaction_read_only').fetchone()['transaction_read_only']=='on'
        report['snapshot']=conn.execute('SELECT pg_current_snapshot()::text snapshot').fetchone()['snapshot']
        if options.reuse_snapshot and previous and previous['snapshot']==report['snapshot']:
            report['sources']=previous['sources'];report['fingerprint_reuse']='Identical PostgreSQL MVCC snapshot: identical visible transaction set; source digests reused.'
        else:report['sources']=original_fingerprints(conn)
        if previous:
            assert previous['sources']==report['sources'],'A resumed auditor must use the same source contents'
            report['previous_attempt']=previous
            report['audits']=[a for a in previous['audits'] if a['report']!='t10-'+options.only+'.json']
            report['failures']=[n for n in previous['failures'] if n!=options.only]
        @contextmanager
        def shared_connect(*args,**kwargs):
            assert not args and kwargs=={'readonly':True},'Auditors must request read-only access'
            yield conn
        def same_sources(selected):
            assert selected is conn,'Source fingerprint belongs to this exact repeatable-read transaction'
            return report['sources']
        planning.connect=shared_connect;fingerprints.source_fingerprints=same_sources
        try:
            for module,name,options in jobs:
                start=time.monotonic();sys.argv=[module,'--output','t10-'+name,*options]
                item={'module':module,'report':'t10-'+name+'.json'};report['audits'].append(item)
                try:
                    importlib.import_module('scripts.audit_planning_'+module).main()
                    item['result']='passed'
                except (Exception,SystemExit) as exc:
                    item['result']='failed';item['error']=repr(exc);report['failures'].append(name)
                    # A SQL error aborts this immutable transaction; do not swap
                    # to a newer cut and present the reports as one population.
                    if conn.info.transaction_status.name=='INERROR':raise
                finally:
                    item['seconds']=time.monotonic()-start
                    (F/'t10-rule-batch.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
                print(name,item['result'],round(item['seconds'],2),flush=True)
        finally:planning.connect=original_connect;fingerprints.source_fingerprints=original_fingerprints
    report['result']='failed' if report['failures'] else 'passed'
    (F/'t10-rule-batch.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
    assert not report['failures'],report['failures']


if __name__=='__main__':main()
