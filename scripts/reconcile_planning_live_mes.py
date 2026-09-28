"""Read-only comparison of MES source CSVs with the central validated archive.

No sheet-view/recheck/validation endpoint is called. Saved evidence contains IDs,
counts and hashes; raw operator/customer fields are compared only in memory.
"""
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
import argparse,csv,hashlib,io,json,re,sqlite3,urllib.request
from dotenv import load_dotenv


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()


def fetch(url):
    with urllib.request.urlopen(url,timeout=15) as response:return response.read()


def population(base):
    found=set();page=1;pages=1
    while page<=pages:
        body=fetch(base+'/?status=validated&page='+str(page)).decode()
        found.update(re.findall(r'href="/sheet/([a-zA-Z0-9_-]+)(?:\?|/csv|\")',body))
        match=re.search(r'Página \d+ de (\d+)',body)
        if match:pages=int(match[1])
        page+=1
    return found,pages


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--cantoneiras-backup',type=Path)
    parser.add_argument('--output',default='t3-live-mes-reconciliation')
    args=parser.parse_args()
    assert re.fullmatch('[a-z0-9-]+',args.output)
    load_dotenv('.env')
    from app import planning
    from app.templates_spec import get_template
    from app.sheet_schema import canonicalize_extraction,is_v2
    from app.web.export import neutralize_xlsx
    folder=Path('docs/validacao-planeamento-integral/20260923-execucao')
    report={'at':datetime.now(timezone.utc).isoformat(),'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'mode':'read-only source listing/CSV and central PostgreSQL','areas':{},'failures':[],
        'boundary':'Perfis and Cantoneiras: read-only live sources, central archive and current production projections.'}
    with planning.connect(readonly=True) as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        rows=c.execute('SELECT source_app,sheet_uid,sheet_no,template_name,sheet_data,cross_check,validated_at FROM mes_kanban.validated_sheets ORDER BY source_app,sheet_uid').fetchall()
        report['central_before_sha256']=digest(rows)
        counts=c.execute('SELECT v.source_app,count(DISTINCT p.id) records,count(r.production_record_id) children FROM mes_kanban.validated_sheets v LEFT JOIN mes_kanban.production_records p USING(sheet_uid) LEFT JOIN mes_kanban.production_record_plan_refs r ON r.production_record_id=p.id GROUP BY v.source_app').fetchall()
        projection_checks={}
        for app,area in [('kanban-mes-mtg2','perfis'),('kanban-mes','cantoneiras')]:
            records=c.execute('SELECT p.id,p.sheet_uid,p.row_index,p.validated_at,p.full_profile,p.quantity FROM mes_kanban.production_records p JOIN mes_kanban.validated_sheets v USING(sheet_uid) WHERE v.source_app=%s ORDER BY p.id',(app,)).fetchall()
            children=c.execute('SELECT production_record_id,plan_key,assumed_quantity FROM mes_kanban.production_record_plan_refs WHERE production_record_id=ANY(%s)',([r['id'] for r in records],)).fetchall()
            refs={}
            for child in children:refs.setdefault(child['production_record_id'],[]).append(child)
            expected=[]
            for record in records:
                base=(record['id'],record['sheet_uid'],record['row_index'],record['validated_at'].isoformat())
                expanded=refs.get(record['id']) or ([{'plan_key':'incomplete','assumed_quantity':None}] if record['full_profile'] else [{'plan_key':None,'assumed_quantity':record['quantity']}])
                expected.extend((*base,child['plan_key'],float(child['assumed_quantity']) if child['assumed_quantity'] is not None else None) for child in expanded)
            gen=c.execute('SELECT id,created_at FROM planning_mtg.raw_generations WHERE dataset=%s ORDER BY id DESC LIMIT 1',('production:'+area,)).fetchone()
            actual=[]
            for r in c.execute('SELECT c.values_json,c.detail FROM planning_mtg.raw_members m JOIN planning_mtg.raw_contents c ON c.hash=m.content_hash WHERE m.dataset=%s AND m.first_generation<=%s AND (m.last_generation IS NULL OR m.last_generation>%s)',('production:'+area,gen['id'],gen['id'])):
                d,v=r['detail'],r['values_json']
                actual.append((d['record_id'],d['sheet_uid'],d['row_index'],datetime.fromisoformat(d['validated_at']).isoformat(),(d.get('child') or {}).get('plan_key'),v.get('quantity')))
            projection_checks[area]={'generation':gen['id'],'created_at':gen['created_at'],
                'parent_ids':len(records),'frozen_children':len(children),'expanded_rows':len(actual),
                'unknown_parent_quantities':sum(r['quantity'] is None for r in records),
                'sheets_without_production':sorted({r['sheet_uid'] for r in rows if r['source_app']==app}-{r['sheet_uid'] for r in records}),
                'missing_or_changed':list((Counter(expected)-Counter(actual)).elements()),
                'extra_or_changed':list((Counter(actual)-Counter(expected)).elements()),
                'expected_sha256':digest(sorted(expected,key=repr)),'observed_sha256':digest(sorted(actual,key=repr))}
    archived_source={}
    if args.cantoneiras_backup:
        backup=args.cantoneiras_backup.resolve()
        with sqlite3.connect(backup.as_uri()+'?mode=ro',uri=True) as s:
            s.row_factory=sqlite3.Row;s.execute('PRAGMA query_only=ON');s.execute('BEGIN')
            archived_source={r['uid']:dict(r) for r in s.execute("SELECT uid,status,revision,validated_at,sheet_data FROM sheets WHERE status='validated'")}
        report['cantoneiras_backup']={'path':str(backup),'sha256':hashlib.sha256(backup.read_bytes()).hexdigest(),
            'validated_sheets':len(archived_source),'read_only':True}
    def check(args):
        base,row=args;data=row['sheet_data'] or {}
        legacy=row['source_app']=='kanban-mes-mtg2' and not is_v2(data)
        if legacy:data=canonicalize_extraction(data,get_template(row['template_name']))
        header=data.get('header') or {}
        source=fetch(base+'/sheet/'+row['sheet_uid']+'/csv')
        parsed=list(csv.reader(io.StringIO(source.decode('utf-8-sig'))))
        fields=get_template(row['template_name']).display_fields(data) if row['source_app']=='kanban-mes-mtg2' else parsed[0][6:]
        expected=[]
        for value in data.get('rows',[]):
            if value.get('_deleted') is True:continue
            if not any(not str(k).startswith('_') and v is not None and str(v).strip() for k,v in value.items()):continue
            prefix=[row['sheet_no'],'validated',header.get('operador'),header.get('data'),header.get('setor_maquina'),len(expected)+1]
            # Only the Perfis CSV endpoint applies this export escaping.
            escape=neutralize_xlsx if row['source_app']=='kanban-mes-mtg2' else lambda x:x
            expected.append(['' if v is None else str(escape(v)) for v in prefix+[value.get(f) for f in fields]])
        observed=parsed[1:]
        differences=[]
        for i in range(max(len(expected),len(observed))):
            if i>=len(expected) or i>=len(observed):differences.append({'row':i+1,'kind':'missing_row'});continue
            for j in range(max(len(expected[i]),len(observed[i]))):
                if j>=len(expected[i]) or j>=len(observed[i]) or expected[i][j]!=observed[i][j]:
                    differences.append({'row':i+1,'column':parsed[0][j] if j<len(parsed[0]) else str(j)})
        without_ordinal=lambda rows:Counter(tuple(r[:5]+r[6:]) for r in rows)
        same_facts=without_ordinal(expected)==without_ordinal(observed)
        backup=archived_source.get(row['sheet_uid'])
        same_stored_rows=bool(backup and json.loads(backup['sheet_data'])==data)
        visible=[r for r in data.get('rows',[]) if r.get('_deleted') is not True and
            any(not str(k).startswith('_') and v is not None and str(v).strip() for k,v in r.items())]
        display_order=[r.get('_display_order') for r in visible]
        display_matches=False
        if differences and same_stored_rows and all(type(n) is int for n in display_order) and len(set(display_order))==len(display_order):
            ordered=[r for _,r in sorted(zip(display_order,expected))]
            ordered=[r[:5]+[str(i+1)]+r[6:] for i,r in enumerate(ordered)]
            display_matches=ordered==observed
        return {'uid':row['sheet_uid'],'sheet_no':row['sheet_no'],'template':row['template_name'],'source_sha256':hashlib.sha256(source).hexdigest(),
            'expected_sha256':digest(expected),'observed_sha256':digest(observed),'rows':len(observed),'differences':differences,
            'legacy_read_adapter':legacy,'same_row_multiset':same_facts,
            'backup_revision':backup['revision'] if backup else None,'backup_stored_identity_exact':same_stored_rows,
            'export_display_order':display_order if display_matches else None,
            'classification':'display_order_only_proven_by_sqlite' if display_matches else 'row_order_changed' if differences and same_facts else 'content_changed' if differences else 'exact'}
    for app,area,port in [('kanban-mes-mtg2','perfis',18101),('kanban-mes','cantoneiras',18100)]:
        base=f'http://127.0.0.1:{port}';ids,pages=population(base);central={r['sheet_uid']:r for r in rows if r['source_app']==app}
        with ThreadPoolExecutor(max_workers=4) as pool:checks=list(pool.map(check,[(base,central[k]) for k in sorted(ids&central.keys())]))
        after,after_pages=population(base)
        result={'source_pages':pages,'source_sheets':len(ids),'central_sheets':len(central),
            'source_only':sorted(ids-central.keys()),'central_only':sorted(central.keys()-ids),
            'source_population_stable':ids==after and pages==after_pages,'checks':checks,
            'central_event_counts':next(r for r in counts if r['source_app']==app),
            'central_projection':projection_checks[area]}
        report['areas'][area]=result
        # Only accept export reordering with exact stored SQLite identities and
        # a deterministic display-order mapping; equal multisets alone are insufficient.
        if result['source_only'] or result['central_only'] or not result['source_population_stable'] or any(r['differences'] and r['classification']!='display_order_only_proven_by_sqlite' for r in checks):report['failures'].append(area)
        if projection_checks[area]['missing_or_changed'] or projection_checks[area]['extra_or_changed']:report['failures'].append(area+':projection')
        print(area,'source',len(ids),'central',len(central),'differing sheets',sum(bool(r['differences']) for r in checks),flush=True)
    with planning.connect(readonly=True) as c:
        after=c.execute('SELECT source_app,sheet_uid,sheet_no,template_name,sheet_data,cross_check,validated_at FROM mes_kanban.validated_sheets ORDER BY source_app,sheet_uid').fetchall()
        report['central_after_sha256']=digest(after)
    if report['central_before_sha256']!=report['central_after_sha256']:report['failures'].append('central_changed_during_read')
    report['result']='passed' if not report['failures'] else 'differences_require_reconciliation'
    (folder/(args.output+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n')
    print(report['result'],flush=True)


if __name__=='__main__':main()
