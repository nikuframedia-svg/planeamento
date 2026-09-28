"""Source contexts for V06; every write is restricted to the integral clone."""
import argparse,json,os,time,uuid
from pathlib import Path
from psycopg.types.json import Jsonb

P=Path('/home/luis/.local/state/planning-backups/integral-20260923')
os.environ['MES_PG_DSN']=json.loads((P/'isolated.json').read_text())['dsn']
os.environ['MES_DATA_DIR']='/tmp/planning-integral-data'
from app import planning,planning_needs as needs,planning_catalogs as catalogs,planning_hub as hub
from app.raw import query
from app.dossiers import store

F=Path('docs/validacao-planeamento-integral/20260923-execucao');STATE=Path(os.environ.get('PLANNING_V06_CONTEXT',str(F/'t9-v06-context.json')))


def run(action,area,need_id):
    with planning.connect(readonly=True) as c:assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
    assert str(store.root()).startswith('/tmp/planning-integral-data/')
    state=json.loads(STATE.read_text()) if STATE.exists() else {'scope':'V06 isolated acceptance only','areas':{}}
    assert state['scope']=='V06 isolated acceptance only'
    result={}
    if action=='init':
        assert not state['areas'],'Use the retained context; do not silently recreate identities'
        capacity=json.loads((F/'c05-capacity-live-fixtures.json').read_text())
        with planning.connect(readonly=True) as c:
            state['cpis_baseline']=str(hub._direct_version(c)['id'])
            for area in planning.AREAS:
                cat=catalogs.catalog(area,c);g=query.generation(c,area);sql,args=query.source(g)
                selector="c.values_json->>'of'='OF260755'" if area=='perfis' else "c.values_json->>'operation'='112'"
                row=c.execute("SELECT c.detail,c.values_json"+sql+" AND m.planning_active AND c.detail->>'origin'='macro' AND "+selector+" ORDER BY m.row_key LIMIT 1",args).fetchone()
                assert row
                fixture=next(x for x in capacity['areas'] if x['area']==area)
                state['areas'][area]={'row':{**row['detail'],'values':row['values_json']},'catalog':cat,
                    'snapshot':planning.snapshot(c,area)['snapshot_id'],'machines':fixture['machines'],'resources':fixture['resources'],
                    'instance':str(uuid.uuid4()),'original_path':str(P/('v06-'+area+'.db'))}
    else:
        a=state['areas'][area]
        if need_id:a['need_id']=need_id
        if action=='remember':result={'need_id':a['need_id']}
        elif action=='retire_original_fixture':
            # Retire only this earlier isolated trial; immutable snapshots and
            # human decisions remain available as historical test evidence.
            with planning.connect() as c:
                instance=c.execute('SELECT source_label,current_snapshot FROM ocr_original.instances WHERE id=%s',(a['instance'],)).fetchone()
                if instance:
                    assert instance['source_label'].startswith('V06 synthetic real-schema acceptance only')
                    c.execute('UPDATE ocr_original.instances SET current_snapshot=NULL WHERE id=%s',(a['instance'],))
                    a['retired_original_snapshot']=str(instance['current_snapshot'])
            result={'retired':bool(instance),'history_preserved':True}
        elif action.startswith('document'):
            doc='v06-'+a['instance'];piece=doc+'-piece'
            values=query.listing({'area':area,'population':'all','selected':[a['need_id']]})['rows'][0]['values']
            with store.connect() as c:
                if action=='document':
                    c.execute('INSERT INTO documents(id,sha256,filename,page_count,status,production_order,created_at,updated_at) VALUES(?,?,?,1,?,?,?,?)',
                        (doc,doc,'V06 isolated source.pdf','review',values['of'],'2026-09-24','2026-09-24'))
                    c.execute('INSERT INTO pieces(id,document_id,source_key,machine_group,index_page,index_ref,drawing_pages_json,raw_json,values_json) VALUES(?,?,?,?,1,?,?,?,?)',
                        (piece,doc,piece,area,values['component_ref'],'[1]','{}',json.dumps(values)))
                    a['document_id']=doc;a['piece_id']=piece
                else:
                    data=json.loads(c.execute('SELECT values_json FROM pieces WHERE id=?',(piece,)).fetchone()[0]);data['length_mm']+=5
                    c.execute('UPDATE pieces SET revision=revision+1,values_json=? WHERE id=?',(json.dumps(data),piece))
            result={'source':{'kind':'pdf','id':doc+'/'+piece},'values':values}
        elif action.startswith('mes'):
            row=query.listing({'area':area,'population':'all','selected':[a['need_id']]})['rows'][0];v=row['values']
            uid='v06-mes-'+a['instance']
            with planning.connect() as c:
                before=c.execute('SELECT * FROM mes_kanban.production_records WHERE sheet_uid=%s',(uid,)).fetchone()
                if action=='mes':
                    assert before is None,'Retain existing source identity; use mes_correct for a revision'
                    app='kanban-mes-mtg2' if area=='perfis' else 'kanban-mes'
                    c.execute("INSERT INTO mes_kanban.validated_sheets(sheet_uid,sheet_date,template_name,family,operator_name,image_sha256,raw_extraction,sheet_data,validated_by,source_app) VALUES(%s,'2026-09-23','V06 isolated test',%s,'Isolated test','v06-synthetic-not-factory','{}','{}','Isolated test',%s)",(uid,area,app))
                    rid=c.execute("""INSERT INTO mes_kanban.production_records(sheet_uid,row_index,sheet_date,family,operator_name,production_order,quantity,machine,model_ref,length_mm,profile_type,matched_plan_key,plan_snapshot_id,validated_at,hours_worked,extra)
                        VALUES(%s,0,'2026-09-23',%s,'Isolated test',%s,4,%s,%s,%s,%s,%s,%s,now(),2,%s) RETURNING id""",
                        (uid,area,v['of'],v['machine'],v['component_ref'],v['length_mm'],v['profile'],row['plan_key'],row['calculation']['macro_snapshot'],Jsonb({'operation_code':v['operation'],'test_scope':'V06 isolated copy only'}))).fetchone()['id']
                elif action=='mes_correct':
                    assert before and before['extra']['test_scope']=='V06 isolated copy only'
                    rid=before['id'];c.execute('UPDATE mes_kanban.production_records SET quantity=6,hours_worked=3,validated_at=now() WHERE id=%s',(rid,))
                else:raise ValueError(action)
                a.setdefault('mes_revisions',[]).append({'action':action,'before':needs.serial(before),'after':needs.serial(c.execute('SELECT * FROM mes_kanban.production_records WHERE id=%s',(rid,)).fetchone())})
            result={'record_id':rid,'sheet_uid':uid}
        elif action.startswith('cpis'):
            ident=uuid.uuid4();baseline=state['cpis_baseline']
            with planning.connect() as c:
                c.execute('INSERT INTO cpis_mtg.versions SELECT %s,source_name,source_view,%s,row_count,state_counts,now(),now(),now(),connector_version FROM cpis_mtg.versions WHERE id=%s',(ident,needs.digest([str(ident),action]),baseline))
                cols=[r['column_name'] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='cpis_mtg' AND table_name='orders' ORDER BY ordinal_position")]
                c.execute('INSERT INTO cpis_mtg.orders SELECT '+','.join('%s' if k=='version_id' else k for k in cols)+' FROM cpis_mtg.orders WHERE version_id=%s',(ident,baseline))
                if action=='cpis_close':c.execute("UPDATE cpis_mtg.orders SET status='Fechada' WHERE version_id=%s AND production_order_no=%s",(ident,a['row']['values']['of']))
            result={'revision':str(ident)}
        elif action.startswith('macro'):
            from scripts.planning_macro_revision_trial import publish
            with planning.connect() as c:revision=publish(c,area,a['snapshot'],a['row']['values']['of'],action=='macro_close')
            result={'revision':revision}
        else:raise ValueError(action)
    STATE.write_text(json.dumps(needs.serial(state),indent=2)+'\n')
    return {'context':needs.serial(state),'result':needs.serial(result),'committed_ms':time.time()*1000}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action');p.add_argument('--area',choices=planning.AREAS);p.add_argument('--need-id')
    a=p.parse_args();print(json.dumps(run(a.action,a.area,a.need_id)))
