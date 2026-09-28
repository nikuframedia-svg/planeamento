"""Legacy planning consumers obey the same closure boundary as RAW.

All source changes below use the disposable PostgreSQL fixture, never a live DB.
"""
import os
from datetime import datetime, timezone

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from app import cpis_sync, planning, planning_hub
from app.web.planning_app import app
from tests.test_planning_registry import registry, postgres16, direct_row, payload

pytestmark = [pytest.mark.pg_integration, pytest.mark.skipif(
    os.environ.get('RUN_PG_INTEGRATION') != '1', reason='Disposable PostgreSQL opt-in')]


def test_hub_population_controls_require_backend_contract(registry):
    from app.web.planning_routes import templates
    with TestClient(app) as client:
        current = client.get('/planeamento').text
    assert 'id="population"' in current
    # The operational process can still serve shared static files before C12.
    # Its old route supplies no contract: don't offer scopes its API ignores.
    legacy = templates.get_template('planning_hub.html').render(version='legacy')
    assert 'id="population"' not in legacy
    assert '<option value="open" selected>' in legacy


@pytest.mark.parametrize('direct', [False, True])
@pytest.mark.parametrize('status,macro,active', [
    ('Em Aberto', '', True), (' FeChAdA ', '', False),
    ('Em Produção', ' x ', False), ('FECHADO', 'true', False),
    ('Pronta', '-', True), ('Estado novo', '#VALUE!', True), (None, '', True),
])
def test_legacy_population_matrix(registry, direct, status, macro, active):
    with psycopg.connect(registry, autocommit=True) as conn:
        conn.execute('UPDATE raw_mtg.cpis_rows SET status=%s', (status,))
        conn.execute("UPDATE raw_mtg.plan_production_rows SET row_data=row_data || %s",
                     (Jsonb({'Fechado': macro}),))
    if direct:
        cpis_sync.publish([{**direct_row('OF4200'), 'status': status}],
                          datetime.now(timezone.utc), central_dsn=registry)
    with TestClient(app) as client:
        for scope, present in [('active', active), ('history', not active), ('all', True)]:
            response = client.get('/planeamento/api/ordens', params={'populacao': scope})
            assert response.status_code == 200, response.text
            result = response.json()
            assert result['total'] == int(present), (scope, result)
            assert result['pages'] == int(present)
            assert len(result['orders']) == int(present)
            if present:
                assert result['orders'][0]['plan'] == {'perfis': 2, 'cantoneiras': 1}
                if status == 'Estado novo':
                    assert result['orders'][0]['population_unknown_states']
            searched = client.get('/planeamento/api/ordens', params={
                'populacao': scope, 'estado': 'all', 'q': 'REF-A', 'tamanho': 1}).json()
            assert searched['total'] == int(present)
            assert client.get('/planeamento/api/ordens', params={
                'populacao': scope, 'pagina': 2, 'tamanho': 1}).json()['orders'] == []
            for area, count in [('perfis', 2), ('cantoneiras', 1)]:
                lines = client.get('/planeamento/api/linhas', params={
                    'area': area, 'of': 'OF4200', 'populacao': scope})
                assert lines.status_code == 200, lines.text
                assert len(lines.json()['lines']) == (count if present else 0)
                assert all(line['population']['active'] is active for line in lines.json()['lines'])
        assert len(client.get('/planeamento/api/ordens/OF4200').json()['plan_lines']) == 3
        assert bool(client.get('/planeamento/api/ofs').json()['orders']) is active
        assert client.get('/planeamento/api/ordens', params={'populacao': 'invalid'}).status_code == 422
        assert client.get('/planeamento/api/linhas', params={
            'area': 'perfis', 'of': 'OF4200', 'populacao': 'invalid'}).status_code == 422


def test_mixed_order_counts_closed_copy_and_history_are_preserved(registry):
    saved = planning.save_record(payload())
    with psycopg.connect(registry, autocommit=True) as conn:
        conn.execute("UPDATE raw_mtg.plan_production_rows SET closed_x=true WHERE source_line_id='s1:10'")
        before = conn.execute('SELECT row_to_json(r)::text FROM planning_mtg.records r ORDER BY id').fetchall()
    active = planning_hub.list_orders()
    history = planning_hub.list_orders(population='history')
    assert active['orders'][0]['plan'] == {'perfis': 1, 'cantoneiras': 1}
    assert history['orders'][0]['plan'] == {'perfis': 1}
    # Refreshing evidence for an existing preparation must keep its closed source readable.
    assert planning.refresh_source(saved['id'])['source']['plan_key'] == 's1:10'
    with psycopg.connect(registry, autocommit=True) as conn:
        conn.execute("UPDATE raw_mtg.cpis_rows SET status='Fechada' WHERE snapshot_id='c1'")
    assert planning_hub.list_orders(state='open')['total'] == 0
    closed = planning_hub.list_orders(population='history')['orders'][0]
    assert set(closed['status_values']) == {'Em Produção', 'Fechada'}
    assert closed['plan'] == {'perfis': 2, 'cantoneiras': 1}
    assert planning.get_record(saved['id'])['record']['id'] == saved['id']
    with psycopg.connect(registry, autocommit=True) as conn:
        assert conn.execute('SELECT row_to_json(r)::text FROM planning_mtg.records r ORDER BY id').fetchall() == before
        assert conn.execute('SELECT count(*) FROM raw_mtg.plan_production_rows').fetchone()[0] == 3
        conn.execute("UPDATE raw_mtg.cpis_rows SET status='Em Produção'")
        conn.execute('UPDATE raw_mtg.plan_production_rows SET closed_x=false')
    assert planning_hub.list_orders()['orders'][0]['plan'] == {'perfis': 2, 'cantoneiras': 1}
    assert planning_hub.list_orders(population='history')['total'] == 0
