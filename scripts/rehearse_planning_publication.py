"""Build the candidate on the restored operational backup, never on live MES."""
import gzip,json,os,time
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path

F=Path('docs/validacao-planeamento-integral/20260923-execucao')
P=Path('/home/luis/.local/state/planning-backups/integral-20260923/publication-20260924')


def main():
    os.environ['MES_PG_DSN']=json.loads((P/'restore.json').read_text())['dsn']
    os.environ['MES_DATA_DIR']=str(P/'rehearsal-data');os.environ['MES_RAW_DRIVE_CHECK']='0'
    from app import planning,planning_needs as needs
    from app.raw import worker,query
    from scripts.audit_planning_actual_hours import load_inputs
    report={'at':datetime.now(timezone.utc).isoformat(),'environment':'planning_restore',
            'boundary':'Candidate publication of the restored real MES/Drive cut; no operational writes.',
            'cycles':[],'areas':{},'failures':[]}
    def sources(c):
        return {table:c.execute("SELECT count(*) n,md5(string_agg(h,'' ORDER BY h)) hash FROM (SELECT md5(to_jsonb(t)::text) h FROM "+table+' t) x').fetchone()
                for table in ['mes_kanban.validated_sheets','mes_kanban.production_records','mes_kanban.production_record_plan_refs']}
    with planning.connect() as c:
        assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_restore'
        report['sources_before']=sources(c)
        c.execute(Path('sql/035_planning_order_dependency_lookup.sql').read_text())
        c.execute(Path('sql/036_planning_order_members.sql').read_text())
    for cycle in range(3):
        start=time.monotonic();ok=worker.refresh_sources();assert ok
        with planning.connect(readonly=True) as c:
            versions={a:{d:query.generation(c,a,dataset=d)['id'] for d in ['planning','production','production_hours','capacity']} for a in planning.AREAS}
        report['cycles'].append({'cycle':cycle+1,'seconds':time.monotonic()-start,'versions':versions})
        (F/'t10-publication-rehearsal.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
        print('cycle',cycle+1,report['cycles'][-1]['seconds'],flush=True)
    assert all(r['versions']==report['cycles'][0]['versions'] for r in report['cycles']), 'Repeated publication must be idempotent'
    ledger=F/'t10-real-event-lineage.jsonl.gz'
    with planning.connect(readonly=True) as c,gzip.open(ledger,'wt') as out:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ');c.execute('SET LOCAL jit=off')
        _,expected_hours,_,_,_=load_inputs(c)
        for area,app in [('perfis','kanban-mes-mtg2'),('cantoneiras','kanban-mes')]:
            parents=c.execute('SELECT p.id,p.sheet_uid,p.row_index,p.validated_at,p.full_profile,p.quantity FROM mes_kanban.production_records p JOIN mes_kanban.validated_sheets v USING(sheet_uid) WHERE v.source_app=%s ORDER BY p.id',(app,)).fetchall()
            children=defaultdict(list)
            for child in c.execute('SELECT production_record_id,plan_key,assumed_quantity FROM mes_kanban.production_record_plan_refs WHERE production_record_id=ANY(%s)',([r['id'] for r in parents],)):
                children[child['production_record_id']].append(child)
            expected=[]
            for parent in parents:
                expanded=children[parent['id']] or ([{'plan_key':'incomplete','assumed_quantity':None}] if parent['full_profile'] else [{'plan_key':None,'assumed_quantity':parent['quantity']}])
                for child in expanded:expected.append((parent['id'],parent['sheet_uid'],parent['row_index'],parent['validated_at'].isoformat(),child['plan_key'],float(child['assumed_quantity']) if child['assumed_quantity'] is not None else None))
            gen=query.generation(c,area,dataset='production');base,args=query.source(gen)
            events=[{**r['detail'],'values':r['values_json']} for r in c.execute('SELECT c.detail,c.values_json'+base,args)]
            observed=[(r['record_id'],r['sheet_uid'],r['row_index'],datetime.fromisoformat(r['validated_at']).isoformat(),(r.get('child') or {}).get('plan_key'),r['values'].get('quantity')) for r in events]
            assert Counter(expected)==Counter(observed),(area,'source/projected event differences')
            gen=query.generation(c,area);assert not gen['metadata'].get('aggregates_pending') and not gen['metadata'].get('source_refresh_pending')
            base,args=query.source(gen);usage=defaultdict(list)
            for row in c.execute("SELECT m.row_key,c.detail->'calculation'->'production_sources' sources"+base,args):
                for operation in row['sources'] or []:
                    for record in operation.get('records',[]):
                        usage[str(record['record_id'])].append({'piece':row['row_key'],'operation':operation['operation'],'origin':operation['origin'],'coverage':operation['coverage_reasons'],'quantity':record.get('quantity')})
            states=Counter()
            for event in events:
                uses=usage[str(event['record_id'])];v=event['values'];usable=[u for u in uses if u['origin']=='OCR validado']
                state='used' if usable else 'excluded';states[state]+=1
                reason=None if usable else {'association':v.get('association_status'),'operation':v.get('operation'),'warnings':event.get('warnings',[]),'counter_coverage':uses}
                assert usable or reason['association'] or reason['warnings'] or uses,(area,event['key'],'missing exclusion diagnostic')
                out.write(json.dumps(needs.serial({'area':area,'event':event['key'],'record_id':event['record_id'],'sheet_uid':event['sheet_uid'],'validated_at':event['validated_at'],'state':state,'uses':usable,'exclusion':reason}),ensure_ascii=False)+'\n')
            hg=query.generation(c,area,dataset='production_hours');base,args=query.source(hg)
            actual={area+':'+r['row_key']:r for r in c.execute('SELECT m.row_key,c.values_json,c.detail'+base,args)}
            wanted={k:v for k,v in expected_hours.items() if k.startswith(area+':')};assert actual.keys()==wanted.keys()
            for key,expected in wanted.items():
                assert actual[key]['values_json']==expected['values'],key
                assert sorted(actual[key]['detail']['original_hours'],key=str)==sorted(expected['original_hours'],key=str),key
            report['areas'][area]={'pieces':gen['row_count'],'parents':len(parents),'expanded_events':len(events),'states':dict(states),'sheets':len(actual),'hour_declarations_match_independent_source_reader':True}
        report['sources_after']=sources(c);assert report['sources_after']==report['sources_before']
    report['result']='passed';report['event_ledger']=ledger.name
    (F/'t10-publication-rehearsal.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
    print(report['result'],report['areas'],flush=True)


if __name__=='__main__':main()
