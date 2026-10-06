"""Free input still preserves identity, revisions and source production."""
import uuid
from pathlib import Path

import psycopg
import pytest

from app import planning, planning_needs as needs, planning_catalogs as catalogs
from app.raw import registration as free, edits
from tests.test_planning_needs import canonical, registry, postgres16, vals, request

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def free_registration(canonical, postgres16, monkeypatch):
    with psycopg.connect(postgres16[0]) as conn:
        conn.execute((ROOT/'sql/042_free_registration.sql').read_text())
    monkeypatch.setenv('MES_PLANNING_FREE_ENTRY', '1')
    return canonical


def create_and_save(values, **extra):
    n = needs.resolve(request(area='perfis', production_order_no='OF4200', values=values, _allow_unresolved=True))
    return needs.save(request(area='perfis', need_id=n['need_id'], expected_revision=n['revision'],
                             catalog_version='s1', values=values, **extra))


def test_ready_without_cpis_or_excel_validation_persists_and_roundtrips(free_registration):
    entered = {'component_ref':'MANUAL-NEW','machine':'Máquina livre','length_mm':'a medir',
               'quantity_required':10,'quantity_to_plan':25,'operation':'operação manual',
               'cut_date':'sem data definida','notes':'=texto literal'}
    saved = create_and_save(entered, record_status='ready')
    assert saved['record_status'] == 'ready'
    assert saved['quantity_to_plan'] == 25
    assert saved['registration_warnings']
    detail = needs.detail(saved['need_id'])
    record = detail['records'][0]
    assert record['values_json']['length_mm'] is None
    assert record['values_json']['machine'] == 'Máquina livre'
    assert free.display_values(record, detail['need'])['length_mm'] == 'a medir'
    assert record['input_values'] == entered
    with planning.connect(readonly=True) as c:
        version = c.execute('SELECT input_values FROM planning_mtg.record_versions WHERE record_id=%s', (saved['record_id'],)).fetchone()
        assert version['input_values'] == entered


def test_repeat_save_reuses_identity_and_does_not_sum_quantities(free_registration):
    first = create_and_save(vals())
    second = create_and_save(vals())
    assert first['need_id'] == second['need_id']
    assert first['record_id'] == second['record_id']
    with planning.connect(readonly=True) as c:
        assert c.execute('SELECT count(*) n FROM planning_mtg.needs').fetchone()['n'] == 1
        assert c.execute('SELECT quantity_required FROM planning_mtg.needs').fetchone()['quantity_required'] == 100


def test_similar_input_counts_as_its_own_piece(free_registration):
    # 07/10/2026: uma peça possivelmente repetida já não fica «por associar» nem perde o saldo.
    first = create_and_save(vals())
    other = {**vals(), 'quantity_required':75}
    second = create_and_save(other)
    assert first['need_id'] != second['need_id']
    assert not second['identity_pending']
    with planning.connect(readonly=True) as c:
        assert not c.execute('SELECT bool_or(identity_pending) p FROM planning_mtg.needs').fetchone()['p']


def test_free_input_keeps_optimistic_lock_and_command_idempotency(free_registration):
    n = needs.resolve(request(area='perfis', production_order_no='OF4200', values=vals()))
    payload = request(area='perfis', need_id=n['need_id'], expected_revision=n['revision'],
                      catalog_version='s1', values=vals())
    first = needs.save(payload)
    assert needs.save(payload) == first
    with pytest.raises(planning.PlanningError) as exc:
        needs.save({**payload,'request_id':str(uuid.uuid4())})
    assert exc.value.status == 409


def test_normalization_keeps_original_invalid_data_out_of_calculations(free_registration):
    cat = catalogs.catalog('perfis')
    values, warnings = free.normalize({'quantity_required':'-9','length_mm':'NaN','notes':'=literal'},cat)
    assert values['quantity_required'] is None and values['length_mm'] is None
    assert values['notes'] == '=literal'
    assert {w['field'] for w in warnings} == {'quantity_required', 'length_mm', 'machine'}
    assert cat['free_entry']
    assert not next(f for f in cat['fields'] if f['id']=='quantity_to_plan')['editor_visible']
