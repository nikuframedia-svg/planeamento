"""H03 boundary examples with explicit expected totals and independent oracle."""
from copy import deepcopy
import pytest
from app.raw import worked_hours
from scripts.audit_planning_actual_hours import source_observations, resource_cohorts, digest, canonical


RESOURCE={'id':'physical','definition':{'aliases':[{'area':'perfis','name':'Saw'},{'area':'cantoneiras','name':'Drill'}]}}


def observations(hours=8, rows=10):
    sheets=[{'sheet_uid':'s','source_app':'kanban-mes-mtg2','sheet_no':1,'sheet_date':'2026-09-22','validated_at':'2026-09-23'}]
    records=[{'sheet_uid':'s','hours_worked':hours,'machine':'Saw'} for _ in range(rows)]
    return source_observations(sheets,records)[0]


def declaration(observed, **changes):
    definition={'resource_id':'physical','confirmed':True,'mode':'period','start_date':'2026-09-21',
                'end_date':'2026-09-27','hours':6,'operation':None,'basis_hash':digest(observed)}
    definition.update(changes)
    return {'id':'correction','revision':2,'definition':definition}


def assert_cohorts(observed, declarations, expected):
    independent=resource_cohorts(RESOURCE,declarations,observed)
    actual=worked_hours.resolve(RESOURCE,declarations,observed)
    assert {r['key']:canonical(r) for r in actual}=={r['key']:canonical(r) for r in independent}
    assert {r['key']:r['hours'] for r in independent}==expected
    return independent


def test_ten_piece_records_declare_eight_hours_once():
    assert_cohorts(observations(),[],{'perfis:s':8})


@pytest.mark.parametrize('hours',[None,-1,25])
def test_missing_or_invalid_sheet_time_never_becomes_zero(hours):
    assert_cohorts(observations(hours),[],{'perfis:s':None})


def test_divergent_sheet_declarations_remain_unknown():
    sheets=[{'sheet_uid':'s','source_app':'kanban-mes-mtg2','sheet_no':1,'sheet_date':'2026-09-22','validated_at':'2026-09-23'}]
    records=[{'sheet_uid':'s','hours_worked':h,'machine':'Saw'} for h in (8,8,7)]
    observed,projection=source_observations(sheets,records)
    assert projection['perfis:s']['original_hours']==[7,8]
    assert_cohorts(observed,[],{'perfis:s':None})


def test_manual_zero_replaces_all_reviewed_source_hours():
    obs=observations();assert_cohorts(obs,[declaration(obs,hours=0)],{'manual:correction':0})


def test_changed_source_invalidates_review_without_readding_ocr():
    obs=observations();manual=declaration(obs);obs[0]['hours']=9;obs[0]['original_hours']=[9]
    result=assert_cohorts(obs,[manual],{'manual:correction':None})
    assert 'mudaram' in result[0]['reason']


def test_conflicting_manual_periods_are_both_unknown():
    obs=observations();first=declaration(obs);other=deepcopy(first);other['id']='other'
    result=assert_cohorts(obs,[first,other],{'manual:correction':None,'manual:other':None})
    assert all('sobrepostas' in r['reason'] for r in result)


def test_unconfirmed_correction_does_not_replace_ocr():
    obs=observations();assert_cohorts(obs,[declaration(obs,confirmed=False)],{'perfis:s':8})


def test_manual_period_without_ocr_is_still_known():
    assert_cohorts([],[declaration([])],{'manual:correction':6})


def test_shared_resource_correction_counts_two_areas_once():
    obs=observations();second={**obs[0],'key':'cantoneiras:s','area':'cantoneiras','machine':'Drill','machines':['Drill']}
    obs=[second,obs[0]]
    manual=declaration(sorted(obs,key=lambda r:r['key']))
    result=assert_cohorts(obs,[manual],{'manual:correction':6})
    assert len(result[0]['sheets'])==2


def test_independent_oracle_includes_original_overlap_before_sheet_replacement():
    mes=observations()[0]
    original={**mes,'key':'original:instance:1','sheet_uid':'original:instance:1','origin':'OCR original',
        'instance_id':'instance','revision':1,'areas':['perfis']}
    sheet=declaration([mes],mode='sheet',sheet_key=mes['key'])
    result=assert_cohorts([mes,original],[sheet],{'manual:correction':None})
    assert len(result[0]['sheets'])==2
    period=declaration(sorted([mes,original],key=lambda o:o['key']),hours=8)
    assert_cohorts([mes,original],[period],{'manual:correction':8})
    assert_cohorts([mes,{**original,'revision':2}],[period],{'manual:correction':None})
    assert_cohorts([mes],[period],{'manual:correction':None})
