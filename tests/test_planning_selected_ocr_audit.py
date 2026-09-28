from copy import deepcopy
import pytest
from scripts.audit_planning_selected_ocr import reconcile


def fixture():
    plan={'key':'macro:new:1','area':'cantoneiras','source_app':'kanban-mes','of':'OF264296',
          'reference':'DLT334D','profile':'L90X90X7','length':3321,
          'raw':{'1ª Oper.':119,'2ª Oper.':0}}
    record={'id':2098,'sheet_uid':'sheet','row_index':7,'source_app':'kanban-mes',
            'production_order':'264296','model_ref':'DLT334D','profile_type':'L90X90X7',
            'length_mm':None,'quantity':4,'machine':'Peddi 8','validated_at':'2026-09-23T10:16:31+00:00',
            'matched_plan_key':'old:1','frozen':{'component_ref':'DLT334D','profile_type':'L90X90X7','length_mm':3321},'extra':{}}
    return {'new:1':plan},record


def test_frozen_identity_and_sole_operation_prove_event_without_machine_guess():
    plans,r=fixture()
    accepted,uncertain,resolution=reconcile([r],plans)
    event=accepted['macro:new:1','119'][0]
    assert event['quantity']==4 and event['record_id']==2098
    assert event['operation_basis']['kind']=='only_same_operation_on_every_resolved_child'
    assert not uncertain
    assert resolution[0]['complete_identity']


@pytest.mark.parametrize('change',['length','profile','order','reference','ambiguous','missing_geometry'])
def test_ref_alone_cannot_prove_identity(change):
    plans,r=fixture()
    if change=='length':r['frozen']['length_mm']=1000
    if change=='profile':r['frozen']['profile_type']='L90X90X8'
    if change=='order':r['production_order']='264297'
    if change=='reference':r['frozen']['component_ref']='OTHER'
    if change=='ambiguous':plans['new:2']={**plans['new:1'],'key':'macro:new:2'}
    if change=='missing_geometry':r['frozen']['length_mm']=None
    accepted,_,_=reconcile([r],plans)
    assert not accepted


def test_two_operations_require_explicit_source_code():
    plans,r=fixture();plans['new:1']['raw']['2ª Oper.']=116
    accepted,uncertain,_=reconcile([r],plans)
    assert not accepted and uncertain['macro:new:1']==[2098]
    r['extra']['operation_code']='116'
    accepted,uncertain,_=reconcile([r],plans)
    assert list(accepted)==[('macro:new:1','116')] and not uncertain


def test_missing_frozen_identity_and_order_is_unresolved_without_crashing():
    plans,r=fixture();r['frozen']=None;r['production_order']=None
    assert not reconcile([r],plans)[0]


def test_expansion_uses_each_child_quantity_and_never_the_parent_total():
    plans,r=fixture();plans['new:2']={**plans['new:1'],'key':'macro:new:2','reference':'SECOND','length':500}
    r.update(quantity=999,full_profile=True,children=[
        {'plan_key':'new:1','assumed_quantity':4}, {'plan_key':'new:2','assumed_quantity':7}])
    accepted,_,_=reconcile([r],plans)
    assert accepted['macro:new:1','119'][0]['quantity']==4
    assert accepted['macro:new:2','119'][0]['quantity']==7
    r['children'][1]['plan_key']='missing'
    assert not reconcile([r],plans)[0]


def test_unknown_child_quantity_is_retained_for_coverage_diagnostics():
    plans,r=fixture();r.update(full_profile=True,children=[{'plan_key':'new:1','assumed_quantity':None}])
    accepted,_,_=reconcile([r],plans)
    assert accepted['macro:new:1','119'][0]['quantity'] is None
    r['children']=[]
    assert not reconcile([r],plans)[0]


def test_explicit_abocardar_name_is_distinct_from_cutting():
    plans,r=fixture();plans['new:1'].update(area='perfis',source_app='kanban-mes-mtg2')
    r.update(source_app='kanban-mes-mtg2',machine='MAQ. ABOCARDAR')
    accepted,_,_=reconcile([r],plans)
    assert list(accepted)==[('macro:new:1','abocardar')]
