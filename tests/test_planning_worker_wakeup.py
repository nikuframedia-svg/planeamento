from tests.test_raw_workspace import workspace,database,canonical,registry,postgres16
from app import planning
from app.raw import projection
from app.raw.wakeup import LocalChanges


def test_capacity_waits_for_both_area_publications(monkeypatch):
    from threading import Barrier
    from app.raw import worker
    arrived=Barrier(2);completed=set();statuses=[]
    def build(area):
        arrived.wait(timeout=3)
        completed.add(area)
    def capacity():
        assert completed==set(planning.AREAS)
        statuses.append('capacity complete')
    monkeypatch.setattr(worker.projection,'rebuild',build)
    monkeypatch.setattr(worker.capacity,'rebuild',capacity)
    monkeypatch.setattr(worker,'source_status',lambda source,**kwargs:None)
    from app.raw import document_dependencies
    monkeypatch.setattr(document_dependencies,'refresh',lambda:{'changed':[]})
    worker.refresh_sources()
    assert statuses==['capacity complete']


def test_capacity_stays_at_last_coherent_revision_until_area_recovers(workspace,monkeypatch):
    from app.raw import worker,capacity_revision,query
    for area in planning.AREAS:projection.rebuild(area)
    capacity_revision.rebuild()
    with planning.connect(readonly=True) as c:
        before={a:query.generation(c,a,dataset='capacity')['id'] for a in planning.AREAS}
    original=worker.projection.rebuild
    def broken(area):
        if area=='cantoneiras':raise RuntimeError('isolated failure')
        return original(area,force=True)
    monkeypatch.setattr(worker.projection,'rebuild',broken)
    assert worker.refresh_sources() is False
    with planning.connect(readonly=True) as c:
        assert {a:query.generation(c,a,dataset='capacity')['id'] for a in planning.AREAS}==before
        state=c.execute("SELECT * FROM planning_mtg.raw_worker_state WHERE source='capacity'").fetchone()
        assert not state['available'] and 'incompleta' in state['error']
        assert all(query.generation(c,a)['metadata']['aggregates_pending'] for a in planning.AREAS)
        assert query.generation(c,'cantoneiras')['metadata']['source_refresh_pending']
        count=c.execute('SELECT count(*) n FROM planning_mtg.raw_generations').fetchone()['n']
    # A persistent failure leaves one pending revision, without generating an
    # unbounded history of identical error publications.
    monkeypatch.setattr(worker.projection,'rebuild',lambda area: (_ for _ in ()).throw(RuntimeError('still unavailable')) if area=='cantoneiras' else original(area))
    assert worker.refresh_sources() is False
    with planning.connect(readonly=True) as c:assert c.execute('SELECT count(*) n FROM planning_mtg.raw_generations').fetchone()['n']==count
    import json
    from app.web.raw_workspace_routes import available
    for area in planning.AREAS:assert json.loads(available(area,str(before[area]),'capacity').body)['pending']
    monkeypatch.setattr(worker.projection,'rebuild',original)
    assert worker.refresh_sources() is True
    with planning.connect(readonly=True) as c:
        assert all(not query.generation(c,a)['metadata']['aggregates_pending'] for a in planning.AREAS)


def test_refresh_status_tracks_pending_core_without_changing_capacity(workspace):
    import json
    import uuid
    from app.raw import capacity_revision,query
    from app.web.raw_workspace_routes import available

    for area in planning.AREAS:projection.rebuild(area)
    capacity_revision.rebuild()
    with planning.connect(readonly=True) as c:
        versions={dataset:str(query.generation(c,'perfis',dataset=dataset)['id'])
                  for dataset in ('planning','capacity','capacity_machines')}
    for dataset,version in versions.items():
        assert json.loads(available('perfis',version,dataset).body)=={
            'available':False,'version':version,'pending':False}

    with planning.connect() as c:projection.mark_aggregates_pending(c,str(uuid.uuid4()))
    for dataset,version in versions.items():
        status=json.loads(available('perfis',version,dataset).body)
        assert status['pending'] is True
        assert status['available'] is (dataset=='planning')
        if dataset!='planning':assert status['version']==version

    capacity_revision.rebuild(force=True)
    for dataset,version in versions.items():
        status=json.loads(available('perfis',version,dataset).body)
        assert status['pending'] is False
        assert status['available'] is True


def test_capacity_rejects_source_committed_after_successful_area_refresh(workspace,canonical):
    import pytest
    import psycopg
    from app.raw import capacity_revision,query
    for area in planning.AREAS:projection.rebuild(area)
    capacity_revision.rebuild()
    with planning.connect(readonly=True) as c:
        previous=query.generation(c,'perfis',dataset='capacity')['id']
    with psycopg.connect(canonical) as c:
        from tests.test_planning_ocr_incremental import source
        source(c)
    with pytest.raises(planning.PlanningError,match='origem'):
        capacity_revision.rebuild()
    with planning.connect(readonly=True) as c:
        assert query.generation(c,'perfis',dataset='capacity')['id']==previous
    for area in planning.AREAS:projection.rebuild(area)
    capacity_revision.rebuild()
    with planning.connect(readonly=True) as c:
        assert query.generation(c,'perfis',dataset='capacity')['id']!=previous


def test_worker_wakes_only_after_commit_and_reconnects(workspace):
    changes=LocalChanges()
    try:
        assert changes.wait(0) is False
        with planning.connect() as c:
            projection.signal(c,'rate')
            assert changes.wait(0) is False
        assert changes.wait(1) is True
        assert changes.wait(0) is False
        changes.connection.close()
        assert changes.wait(0) is False
        with planning.connect() as c:projection.signal(c,'worked_hours')
        assert changes.wait(1) is True
    finally:changes.close()
