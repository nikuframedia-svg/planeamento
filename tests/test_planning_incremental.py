"""Affected-order calculation must retain full identity/ambiguity populations."""
import pytest
from app import planning, planning_needs as needs
from app.raw import projection
from tests.test_raw_workspace import workspace, database, canonical, registry, postgres16
from tests.test_planning_needs import request, vals, save


def test_selected_order_build_matches_full_population_and_keeps_peer_pieces(workspace):
    for of in ('4200','4201'):
        n=needs.resolve(request(area='perfis',production_order_no=of,values=vals()))
        save(n)
    with planning.connect(readonly=True) as c:
        full,_,_=projection.build_rows(c,'perfis')
        partial,_,_=projection.build_rows(c,'perfis',orders=['4200'])
        assert len(partial)==3  # Two different macro pieces plus the local piece.
        assert needs.serial(partial)==needs.serial([r for r in full if r['values']['of']=='OF4200'])
        other,_,_=projection.build_rows(c,'perfis',orders=['OF4201'])
        assert len(other)==1 and other[0]['values']['of']=='OF4201'
        with pytest.raises(planning.PlanningError):projection.build_rows(c,'perfis',orders=['4200/33'])


@pytest.mark.parametrize('area',['perfis','cantoneiras'])
def test_preview_is_read_only_uses_shared_engine_and_matches_saved_piece(workspace,area):
    from app.raw import preview, edits, query, objects
    from psycopg.types.json import Jsonb
    import uuid, psycopg
    if area=='cantoneiras':
        with psycopg.connect(workspace) as c:
            c.execute("INSERT INTO raw_mtg.other_sheet_rows VALUES ('c1','Dados',3,%s),('c1','Tabela pesos',3,%s)",
                (Jsonb({'values':[None,'Ficep XP T4',None,None,'Cantoneira',None,None,112,'CORTE']}),Jsonb({'values':[None,'L TEST',3]})))
    v={**vals(),'length_mm':2000,'abocardar':False,'expected_date':'2026-09-23'} if area=='perfis' else {
        'component_ref':'NEW-C','material_type':'Cantoneira','profile':'L TEST','length_mm':2000,
        'quantity_required':100,'operation':'112','operation_detail':'0','machine':'Ficep XP T4','expected_date':'2026-09-23'}
    resource=objects.save({'request_id':str(uuid.uuid4()),'name':'Preview test resource','definition':{
        'aliases':[{'area':area,'name':v['machine']}],'operations':[v['operation']],'confirmed':True}},'resource')
    objects.save({'request_id':str(uuid.uuid4()),'name':'Preview test rate','definition':{'resource_id':resource['id'],
        'area':area,'operation':v['operation'],'method':'units_hour' if area=='perfis' else 'metres_hour',
        'value':10 if area=='perfis' else 30,'valid_from':'2026-01-01','confirmed':True}},'rate')
    payload={'area':area,'production_order_no':'OF998811','catalog_version':'s1' if area=='perfis' else 'c1','values':v}
    def stored():
        with planning.connect(readonly=True) as c:
            return {table:c.execute('SELECT count(*) n FROM planning_mtg.'+table).fetchone()['n'] for table in
                ('needs','records','need_events','record_versions','need_commands','raw_generations','raw_contents','raw_signals','audit_outbox')}
    before=stored();result=preview.preview(payload)
    assert result['saved'] is False and result['preview'] is True and stored()==before
    expected_hours=10 if area=='perfis' else 200/30
    assert result['row']['values']['remaining']==100
    assert result['row']['values']['theoretical_hours']==pytest.approx(expected_hours)
    if area=='cantoneiras':assert result['row']['values']['weight']==600
    saved=edits.prepare({**payload,'request_id':str(uuid.uuid4()),'record_status':'draft'})
    projection.rebuild(area)
    actual=query.listing({'area':area,'selected':[saved['need_id']]})['rows'][0]
    for field in ('remaining','quantity_to_plan','remaining_m','total_length','weight','bars','section_unit','theoretical_hours','rate_source'):
        assert actual['values'].get(field)==result['row']['values'].get(field),field
    with pytest.raises(planning.PlanningError,match='servidor'):
        preview.preview({**payload,'values':{**v,'ocr_cut':999}})
    with pytest.raises(planning.PlanningError):preview.preview({**payload,'operations':[{'ocr_records':[{'quantity':999}]}]})


def test_preview_quantity_keeps_macro_production_and_rejects_stale_revision(workspace):
    import uuid
    from app.raw import preview, edits, query
    p={'area':'perfis','catalog_version':'s1','source':{'kind':'plan_line','id':'s1:10','version':'s1'},
       'values':{'quantity_required':120,'operation':'corte'}}
    before=preview.preview(p)
    assert before['row']['values']['cut']==64 and before['row']['values']['remaining']==56
    saved=edits.prepare({**p,'request_id':str(uuid.uuid4())})
    projection.rebuild('perfis')
    actual=query.listing({'selected':[saved['need_id']]})['rows'][0]
    assert actual['values']['remaining']==before['row']['values']['remaining']
    # 07/10/2026: uma revisão antiga já não dá 409; a pré-visualização calcula sobre a peça atual.
    assert preview.preview({**p,'need_id':saved['need_id'],'expected_revision':1})['need_revision']==saved['revision']


def test_save_publishes_current_row_without_worker_then_allows_another_edit(workspace):
    import uuid
    from app.raw import edits, query
    projection.rebuild('perfis');projection.rebuild('cantoneiras')
    old=query.listing({});row=next(r for r in old['rows'] if r['plan_key']=='s1:10')
    payload={'request_id':str(uuid.uuid4()),'area':'perfis','version':old['version'],
        'edits':[{'key':row['key'],'expected_revision':0,'values':{'quantity_required':120}}]}
    saved=edits.update_batch(payload)
    assert edits.update_batch(payload)==saved
    nid=saved['items'][0]['need_id'];published=saved['publication']
    assert published['status']=='published' and published['aggregates_pending']
    calculated=next(r for r in published['rows'] if r['area']=='perfis' and r['need_id']==nid)
    assert calculated['values']['cut']==64 and calculated['values']['remaining']==56
    after=query.listing({});new=next(r for r in after['rows'] if r['need_id']==nid)
    assert after['version']==published['areas']['perfis']['version']
    assert after['total']==old['total'] and row['key'] in new['selection_aliases']
    assert query.listing({'version':old['version']})['rows'][0]['revision']==0
    again=edits.update_batch({'request_id':str(uuid.uuid4()),'area':'perfis','version':after['version'],
        'edits':[{'key':new['key'],'expected_revision':new['revision'],'values':{'quantity_required':130}}]})
    assert next(r for r in again['publication']['rows'] if r['area']=='perfis')['values']['remaining']==66
    # Local source dependencies are complete; aggregates remain pending.
    # The worker does not rebuild the full core just to apply this local edit.
    with planning.connect(readonly=True) as c:
        gen=query.generation(c,'perfis')
        assert gen['metadata']['core_source_fingerprint']==projection.fingerprint(c,'perfis')
    assert str(projection.rebuild('perfis')['id'])==query.listing({})['version']
    projection.rebuild('perfis')
    rebuilt=query.listing({})
    assert not rebuilt.get('source_refresh_pending')
    assert rebuilt['aggregates_pending']
    from app.raw import capacity
    capacity.rebuild()
    assert not query.listing({})['aggregates_pending']
    assert rebuilt['total']==old['total']
    assert next(r for r in rebuilt['rows'] if r['need_id']==nid)['values']['remaining']==66


def test_new_local_order_publishes_inside_its_atomic_transaction(workspace):
    import uuid
    from app.raw import edits,query
    projection.rebuild('perfis');projection.rebuild('cantoneiras')
    old=query.listing({})
    p={'request_id':str(uuid.uuid4()),'area':'perfis','production_order_no':'OF998833','catalog_version':'s1',
       'values':{**vals(),'quantity_required':7,'length_mm':2001,'stock_length_mm':6000,'abocardar':False}}
    created=edits.prepare(p)
    row=query.listing({'selected':[created['need_id']]})['rows'][0]
    assert row['values']['remaining']==7 and row['values']['bars']==4
    assert row['revision']==created['revision']
    assert query.listing({})['total']==old['total']+1
    assert len(created['publication']['rows'])==1
    assert edits.prepare(p)==created


def test_local_publication_does_not_claim_an_unprocessed_ocr_revision_is_current(workspace):
    import uuid,psycopg
    from app.raw import edits,query
    projection.rebuild('perfis');projection.rebuild('cantoneiras')
    old=query.listing({});original=next(r for r in old['rows'] if r['plan_key']=='s1:11')
    with psycopg.connect(workspace) as c:
        c.execute("INSERT INTO mes_kanban.validated_sheets(sheet_uid,sheet_date,template_name,family,operator_name,image_sha256,raw_extraction,sheet_data,validated_by,source_app) VALUES ('pending-new-source','2026-09-22','t','perfis','Teste','hash','{}','{}','Teste','kanban-mes-mtg2')")
        c.execute("INSERT INTO mes_kanban.production_records(sheet_uid,row_index,sheet_date,family,operator_name,production_order,quantity,machine,model_ref,length_mm,profile_type,matched_plan_key,plan_snapshot_id,validated_at) VALUES ('pending-new-source',0,'2026-09-22','perfis','Teste','4200',1,'MEBA','REF-A',3003,'108x3','s1:11','s1',now())")
    result=edits.prepare({'request_id':str(uuid.uuid4()),'area':'perfis','production_order_no':'OF998844',
        'catalog_version':'s1','values':{**vals(),'quantity_required':7,'abocardar':False}})
    after=query.listing({});still_old=next(r for r in after['rows'] if r['plan_key']=='s1:11')
    assert still_old['values']['cut']==original['values']['cut']==64
    assert after['source_refresh_pending'] and after['aggregates_pending']
    with pytest.raises(planning.PlanningError,match='fontes mudaram'):
        edits.update_batch({'request_id':str(uuid.uuid4()),'area':'perfis','version':after['version'],
            'edits':[{'key':still_old['key'],'expected_revision':0,'values':{'notes':'Cannot edit stale source'}}]})
    projection.rebuild('perfis')
    final=query.listing({});current=next(r for r in final['rows'] if r['plan_key']=='s1:11')
    assert current['values']['cut']==1 and current['values']['remaining']==99
    assert next(r for r in final['rows'] if r['need_id']==result['need_id'])['values']['remaining']==7
    assert not final.get('source_refresh_pending')


def test_publication_failure_rolls_back_piece_generation_and_command_together(workspace,monkeypatch):
    import uuid
    from app.raw import edits,query
    projection.rebuild('perfis');projection.rebuild('cantoneiras')
    payload={'request_id':str(uuid.uuid4()),'area':'perfis','production_order_no':'OF998855','catalog_version':'s1',
        'values':{**vals(),'quantity_required':7,'length_mm':2001,'stock_length_mm':6000,'abocardar':False}}
    def snapshot():
        with planning.connect(readonly=True) as c:
            counts={t:c.execute('SELECT count(*) n FROM planning_mtg.'+t).fetchone()['n'] for t in
                ('needs','records','need_events','need_commands','raw_generations','raw_members','raw_contents','raw_signals','audit_outbox')}
            return counts,{a:query.listing({'area':a},conn=c) for a in planning.AREAS}
    before=snapshot();original=projection.publish_delta
    def fail_second_area(conn,dataset,*args,**kwargs):
        if dataset=='planning:cantoneiras':raise RuntimeError('Injected publication failure after the first area')
        return original(conn,dataset,*args,**kwargs)
    monkeypatch.setattr(projection,'publish_delta',fail_second_area)
    with pytest.raises(RuntimeError,match='Injected publication failure'):edits.prepare(payload)
    assert snapshot()==before
    monkeypatch.setattr(projection,'publish_delta',original)
    saved=edits.prepare(payload)
    assert edits.prepare(payload)==saved
    current=query.listing({'selected':[saved['need_id']]})
    assert len(current['rows'])==1 and current['rows'][0]['values']['bars']==4


def test_published_revision_matches_database_csv_and_xlsx_without_worker(workspace):
    import uuid,csv,io
    from openpyxl import load_workbook
    from app.raw import edits,query,exports
    projection.rebuild('perfis');projection.rebuild('cantoneiras')
    before=query.listing({});piece=next(r for r in before['rows'] if r['plan_key']=='s1:10')
    saved=edits.update_batch({'request_id':str(uuid.uuid4()),'area':'perfis','version':before['version'],
        'edits':[{'key':piece['key'],'expected_revision':0,'values':{'quantity_required':120}}]})
    nid=saved['items'][0]['need_id'];params={'area':'perfis','selected':[nid],
        'columns':['quantity_required','cut','remaining']}
    with planning.connect(readonly=True) as c:
        need=needs.load(c,nid);row=query.listing(params,conn=c)['rows'][0]
        assert need['revision']==row['revision']==saved['items'][0]['revision']
        assert need['quantity_required']==row['values']['quantity_required']==120
    csv_data,_=exports.table(params,'csv');csv_row=list(csv.reader(io.StringIO(csv_data),delimiter=';'))[1]
    assert [float(v.replace(',','.')) for v in csv_row]==[120,64,56]
    xlsx_data,_=exports.table(params,'xlsx');book=load_workbook(io.BytesIO(xlsx_data),data_only=True)
    assert list(book['RAW'].values)[1]==(120,64,56)


def test_repeatable_local_save_recovers_after_concurrent_capacity_commit(workspace,monkeypatch):
    import uuid
    from concurrent.futures import ThreadPoolExecutor,TimeoutError
    from threading import Event
    from app.raw import capacity_revision,incremental,edits,query
    for area in planning.AREAS:projection.rebuild(area)
    payload={'request_id':str(uuid.uuid4()),'area':'perfis','production_order_no':'OF998866',
        'catalog_version':'s1','values':{**vals(),'quantity_required':7,'abocardar':False}}
    calculated=Event();release=Event();saving=Event()
    calculate=capacity_revision.calculate;baseline=incremental.baseline
    def paused_calculation(*args,**kwargs):
        result=calculate(*args,**kwargs);calculated.set()
        assert release.wait(15)
        return result
    def observed_baseline(conn):
        saving.set()
        return baseline(conn)
    monkeypatch.setattr(capacity_revision,'calculate',paused_calculation)
    monkeypatch.setattr(incremental,'baseline',observed_baseline)
    with ThreadPoolExecutor(max_workers=2) as pool:
        worker=pool.submit(capacity_revision.rebuild)
        try:
            if not calculated.wait(5):worker.result(timeout=1)
            assert calculated.is_set()
            human=pool.submit(edits.prepare,payload)
            assert saving.wait(5)
            with pytest.raises(TimeoutError):human.result(timeout=.2)
        finally:release.set()
        worker.result(timeout=15);saved=human.result(timeout=15)
    assert saved['publication']['status']=='published'
    assert edits.prepare(payload)==saved
    current=query.listing({'selected':[saved['need_id']]})['rows']
    assert len(current)==1 and current[0]['values']['remaining']==7
    with planning.connect(readonly=True) as c:
        assert c.execute("SELECT count(*) n FROM planning_mtg.needs WHERE production_order_no='OF998866'").fetchone()['n']==1
