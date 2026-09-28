"""Retire the interrupted isolated fixture without deleting its human history."""
import json,os,uuid
from pathlib import Path
from psycopg.types.json import Jsonb
os.environ['MES_PG_DSN']=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
from app import planning,planning_needs as needs,planning_associations as associations
from app.raw import incremental
record='original:610a7dab-6837-4fa7-a810-e6596dbbe196:1:0'
p={'request_id':str(uuid.uuid5(uuid.NAMESPACE_URL,'isolated-retire:'+record)),
   'reason':'Ensaio C05 interrompido na cópia isolada; associação retirada após remover a fonte de teste. Histórico conservado.'}
with planning.connect() as c:
    assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
    _,actor,old=needs.command(c,p)
    if not old:
        before=incremental.baseline(c);prior=associations.latest(c,record)
        assert prior and prior['status']=='associated'
        assert prior['evidence']['instance_id']=='610a7dab-6837-4fa7-a810-e6596dbbe196'
        ids={a['need_id'] for a in prior['allocations']}
        assert ids=={'83a6626a-17d0-4fe4-b715-db9d8e03edae'}
        ident=uuid.uuid4()
        c.execute('''INSERT INTO planning_mtg.original_association_decisions
            (id,production_record_id,revision,status,allocations,evidence_hash,evidence,actor,reason)
            VALUES(%s,%s,%s,'unrelated','[]',%s,%s,%s,%s)''',
            (ident,record,prior['revision']+1,prior['evidence_hash'],Jsonb(prior['evidence']),actor,p['reason']))
        for nid in ids:needs.event(c,needs.load(c,nid),'production_association',actor,
            {'decision_id':str(ident),'record_id':record,'status':'unrelated','allocations':[],'reason':p['reason']})
        result=incremental.publish(c,before,['OF987080380'],ids,p['request_id'],refresh_hours=True)
        needs.finish(c,p,{'publication':result,'revision':prior['revision']+1})
print('Interrupted isolated fixture retired; all decision revisions retained.')
