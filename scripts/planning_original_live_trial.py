"""Controlled original OCR revisions; writes only to the acceptance clone."""
import argparse,json,os,sqlite3,time,uuid
from pathlib import Path

config=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())
os.environ['MES_PG_DSN']=config['dsn']
from app import planning,planning_needs as needs,original_ocr,planning_original_production
from app.raw import query

p=argparse.ArgumentParser()
p.add_argument('area',choices=planning.AREAS)
p.add_argument('action',choices=['inspect','insert','correct','remove','release','cleanup'])
p.add_argument('--local-c03',action='store_true',help='Use the retained C03 local piece in the same isolated clone')
args=p.parse_args()
keys={'perfis':'macro:mtg2_bf1cd6a25986791e:plan:5388','cantoneiras':'macro:mtg_397c8ea5e42480c1:plan:62819'}
if args.local_c03:
    fixture=json.loads(Path('docs/validacao-planeamento-integral/20260923-execucao/c03-complete-run.json').read_text())
    keys={area:fixture['areas'][area]['pieces'][0]['id'] for area in planning.AREAS}
state=Path('/tmp/planning-t4-original-'+args.area+'.json')
with planning.connect() as c:
    assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
    gen=query.generation(c,args.area);base,params=query.source(gen)
    row=c.execute('SELECT c.values_json,c.detail'+base+' AND m.row_key=%s',params+[keys[args.area]]).fetchone()
    values=row['values_json']
    current=needs.serial(planning_original_production.snapshot_token(c))
    generations=[query.generation(c,a) for a in planning.AREAS]
    settled=all(g['metadata'].get('original_ocr_snapshots',[])==current
        and not g['metadata'].get('aggregates_pending') and not g['metadata'].get('source_refresh_pending') for g in generations)
    source=json.loads(state.read_text()) if state.exists() else None
    if args.action=='cleanup':
        assert source and source['scope']=='T4 acceptance only'
        assert c.execute('SELECT id FROM ocr_original.instances WHERE id=%s AND source_label=%s',(source['instance'],'T4 isolated acceptance '+args.area)).fetchone()
        for table in ('snapshot_sheets','sheets','snapshots','sync_attempts'):
            c.execute('DELETE FROM ocr_original.'+table+' WHERE instance_id=%s',(source['instance'],))
        c.execute('DELETE FROM ocr_original.instances WHERE id=%s',(source['instance'],))
        c.commit()
        Path(source['path']).unlink();state.unlink()
    elif args.action=='release':
        from app import planning_associations as associations
        assert source and source['scope']=='T4 acceptance only'
        # End the controlled human association before withdrawing its source.
        # Keep every decision and audit event; no fixture history is truncated.
        records=associations.pending(values['of'],args.area,source='original',state='all')['records']
        for record in records:
            if not record['id'].startswith('original:'+source['instance']+':') or not record.get('decision'):continue
            associations.save({'request_id':str(uuid.uuid4()),'production_record_id':record['id'],
                'expected_revision':record['decision']['revision'],'evidence_hash':record['evidence_hash'],
                'status':'unrelated','allocations':[],'reason':'Fim do ensaio C05 na cópia isolada; decisões anteriores conservadas.'})
    elif args.action=='insert':
        assert not source,'Earlier isolated trial must be explicitly cleaned up'
        source={'scope':'T4 acceptance only','instance':str(uuid.uuid4()),'path':'/tmp/planning-t4-original-'+args.area+'.sqlite'}
        assert not Path(source['path']).exists()
        with sqlite3.connect(source['path']) as s:
            s.executescript('CREATE TABLE sheets(id INTEGER PRIMARY KEY,status TEXT,sheet_data TEXT,validated_at TEXT,revision INTEGER); CREATE TABLE production_rows(id INTEGER PRIMARY KEY,sheet_id INTEGER,row_index INTEGER,qtd REAL,of TEXT,sheet_iso_date TEXT,sheet_hours REAL,modelo TEXT,comp_mm REAL,profile_type TEXT,operation TEXT);')
            data={'template_name':'T4 isolated','header':{'area':args.area,'setor_maquina':values['machine']}}
            s.execute("INSERT INTO sheets VALUES(1,'validated',?,'2026-09-23 12:00:00',1)",(json.dumps(data),))
            # Retain a complete nonempty validated population after desvalidation.
            s.execute("INSERT INTO sheets VALUES(2,'validated',?,'2026-09-23 12:00:00',1)",(json.dumps({'header':{'area':args.area}}),))
            s.execute("INSERT INTO production_rows VALUES(1,1,0,10,?,'2026-09-23',2,?,?,?,?)",(values['of'],values['component_ref'],values['length_mm'],values['profile'],values['operation']))
        state.write_text(json.dumps(source)+'\n')
    elif args.action in ('correct','remove'):
        assert source and source['scope']=='T4 acceptance only'
        with sqlite3.connect(source['path']) as s:
            if args.action=='correct':
                s.execute('UPDATE sheets SET revision=2 WHERE id=1')
                s.execute('UPDATE production_rows SET qtd=25,sheet_hours=4 WHERE sheet_id=1')
            else:s.execute("UPDATE sheets SET revision=3,status='draft' WHERE id=1")
result=None
if args.action in ('insert','correct','remove'):
    result=original_ocr.publish(original_ocr.read_snapshot(source['path'],source['instance']),config['dsn'],label='T4 isolated acceptance '+args.area)
print(json.dumps(needs.serial({'area':args.area,'action':args.action,'key':keys[args.area],
    'committedMs':time.time()*1000,'version_before':gen['id'],'values_before':values,'publication':result,'source':source,'settled':settled})))
