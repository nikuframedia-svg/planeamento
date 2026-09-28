"""Prevent duplication and unsupported claims in the planning evidence shown to people."""
from copy import deepcopy

import pytest

from app import planning_hub, planning_production as evidence


def line(key='s1:10', **overrides):
    return {'plan_key': key, 'snapshot_id': 's1', 'source_app': 'kanban-mes-mtg2',
            'component_ref': 'CI5121A4030', 'profile_type': '88.9x3', 'length_mm': 3003,
            'quantity_planned': 315, 'remaining_valid': True, 'remaining_quantity': 0,
            'operation_inputs': {'Ser.': 315, 'Aboc.': 298, 'Aborc.': 'X'}, **overrides}


def record(index=1, **overrides):
    return {'id': index, 'sheet_uid': f'sheet-{index}', 'row_index': 0,
            'source_app': 'kanban-mes-mtg2', 'matched_plan_key': 's1:10',
            'model_ref': 'CI5121A4030', 'profile_type': '88.9x3', 'length_mm': 3003,
            'quantity': 315, 'machine': 'MEBA', 'plan_refs': [], **overrides}


def attach(plans, records):
    planning_hub._production_associations(records, plans)
    evidence.attach_operation_evidence(plans, records)
    return plans[0]['operations']


def test_cut_and_abocardar_have_separate_quantities_and_evidence():
    operations = attach([line()], [record(), record(2, machine='Abocardar', quantity=129),
                                  record(3, machine='Abocardar', quantity=169)])
    cut, aboc = operations
    assert (cut['ocr_quantity'], cut['macro_remaining']) == (315, 0)
    assert (aboc['ocr_quantity'], aboc['macro_remaining']) == (298, 17)
    assert [r['record_id'] for r in cut['ocr_records']] == [1]
    assert [r['record_id'] for r in aboc['ocr_records']] == [2, 3]


@pytest.mark.parametrize('name', ['MAQ. ABOCARDAR', ' Maq.   Abocardar '])
def test_recorded_abocardar_alias_does_not_block_cut_or_lose_abocardar(name):
    cut, aboc = attach([line()], [record(quantity=315), record(2,machine=name,quantity=171)])
    assert cut['ocr_quantity'] == 315
    assert aboc['ocr_quantity'] == 171
    assert cut['coverage_reasons'] == aboc['coverage_reasons'] == []
    assert [r['record_id'] for r in cut['ocr_records']] == [1]
    assert [r['record_id'] for r in aboc['ocr_records']] == [2]


def test_unknown_machine_is_not_assumed_to_be_abocardar():
    cut, aboc = attach([line()], [record(machine='Máquina partilhada',quantity=171)])
    assert cut['ocr_quantity'] is None and aboc['ocr_quantity'] is None
    assert cut['coverage_reasons'] and aboc['coverage_reasons']


def test_ocr_abocardar_remains_visible_when_macro_does_not_indicate_need():
    operations = attach([line(operation_inputs={'Ser.':1}, quantity_planned=1)],
                        [record(quantity=1), record(2, machine='Abocardar', quantity=1)])
    assert len(operations)==2
    assert operations[0]['ocr_quantity']==operations[1]['ocr_quantity']==1
    assert operations[1]['macro_remaining'] is None and operations[1]['requires_need_review']


@pytest.mark.parametrize('quantity,expected', [(0, 0), (None, None), (7, 7)])
def test_full_profile_uses_frozen_child_quantity_without_parent(quantity, expected):
    parent = record(quantity=100, full_profile=True,
                    plan_refs=[{'plan_key': 's1:10', 'assumed_quantity': quantity}])
    cut, aboc = attach([line()], [parent])
    assert cut['ocr_quantity'] == expected
    assert cut['ocr_partial'] == (quantity is None)
    assert aboc['ocr_quantity'] is None


def test_full_profile_without_frozen_children_is_incomplete():
    parent = record(quantity=100, full_profile=True)
    cut, _ = attach([line()], [parent])
    assert parent['association_status'] == 'incomplete'
    assert cut['ocr_quantity'] is None


def test_missing_geometry_is_not_a_safe_unique_match():
    item = record(matched_plan_key='old:10', length_mm=None)
    cut, _ = attach([line()], [item])
    assert item['association_status'] == 'incomplete'
    assert cut['ocr_quantity'] is None


def test_frozen_geometry_can_recover_historical_identity():
    item = record(matched_plan_key='old:10', length_mm=None,
                  frozen_identity={'component_ref': 'CI5121A4030', 'profile_type': '88.9x3',
                                   'length_mm': 3003})
    cut, _ = attach([line(), line('s1:11', length_mm=1500)], [item])
    assert item['association_status'] == 'technical_unique'
    assert item['resolved_plan_keys'] == ['s1:10']
    assert cut['ocr_quantity'] == 315


def test_absence_unknown_operation_and_unknown_quantity_stay_unknown():
    for records in ([], [record(machine='Máquina desconhecida')], [record(quantity=None)]):
        cut, _ = attach([line()], records)
        assert cut['ocr_quantity'] is None


def test_only_relevant_operation_dependencies_change_conference():
    first = line()
    attach([first], [record()])
    before = evidence.conference_evidence(first, 'corte', 'version1')
    changed = deepcopy(first)
    changed['operation_inputs']['Aboc.'] = 299
    attach([changed], [record()])
    assert evidence.conference_evidence(changed, 'corte', 'version1') == before
    changed['remaining_quantity'] = 1
    attach([changed], [record()])
    assert evidence.conference_evidence(changed, 'corte', 'version1') != before


def test_cantoneiras_machine_does_not_authorize_cut_operation():
    item = record(source_app='kanban-mes', machine='Ficep XP T4')
    cant = line(source_app='kanban-mes', operation_inputs={'1ª Oper.': 'A', '2ª Oper.': 'B'})
    operations = attach([cant], [item])
    assert item['operation'] == 'operacao_por_confirmar'
    assert operations[0]['requires_operation_review']
    assert evidence.conference_evidence(cant, 'corte', 'version1') is None
