"""Explicit acceptance/exclusion examples for the independent H09 auditor."""
from datetime import date
import pytest
from app.raw.productivity import historical
from scripts.audit_planning_historical_cohorts import evaluate,equivalent


def event(key='a',sheet='s',quantity=10,**values):
    return {'key':key,'sheet_key':sheet,'area':'cantoneiras','operation':'112','date':'2026-09-22',
            'quantity':quantity,'length_mm':1000,'section_unit':20,'identity_valid':True,
            'material_type':'Cantoneira','profile':'L40','grade':'S235',**values}


def time(key='s',hours=2,**values):
    return {'key':key,'sheets':[key],'hours':hours,'start_date':'2026-09-22','end_date':'2026-09-22',
            'origin':'OCR',**values}


def compare(events,cohorts,**options):
    args={'area':'cantoneiras','operation':'112','method':'metres_hour','values':event(),
          'end':date(2026,9,23),'days':90,**options}
    expected=evaluate(events,cohorts,**args)
    actual=historical(events,cohorts,**{k:v for k,v in args.items() if k!='end'},as_of=args['end'])
    for key,value in expected.items():assert equivalent(actual[key],value),key
    return expected


def test_weighted_rate_excludes_both_sides_of_incomplete_pairs():
    result=compare([event('a','a',10),event('b','b',90),event('c','c',1000),event('d','d',None)],
                   [time('a',2),time('b',8),time('c',None),time('d',100)])
    assert (result['value'],result['volume'],result['hours'])==(10,100,10)
    assert len(result['excluded'])==2 and result['event_count']==2


@pytest.mark.parametrize('change',[{'quantity':None},{'quantity':-1},{'quantity':1.5},{'length_mm':None},
    {'identity_valid':False},{'operation':'113'},{'area':'perfis'},{'date':'2026-09-21'},{'date':None}])
def test_incomplete_event_rejects_the_whole_sheet_pair(change):
    result=compare([event(),event('bad',quantity=100,**change)] if 'quantity' not in change else
                   [event(),event('bad',**change)],[time()])
    assert result['cohorts']==[] and result['hours']==0 and result['volume']==0 and result['value'] is None
    assert result['excluded'][0]['reasons']


def test_duplicate_event_and_duplicate_time_are_not_counted_twice():
    e=event();c=time();result=compare([e,e],[c,c])
    assert result['value']==5 and result['event_count']==1 and result['hours']==2


def test_conflicting_event_versions_reject_the_pair():
    result=compare([event(),event(quantity=11)],[time()])
    assert result['value'] is None and 'Evento repetido com conteúdo divergente.' in result['excluded'][0]['reasons']


def test_overlapping_time_owners_cannot_select_one_silently():
    result=compare([event()],[time(),time('other',3,sheets=['s'])])
    assert result['cohorts']==[] and len(result['excluded'])==2


@pytest.mark.parametrize('hours',[None,0,-1])
def test_only_positive_known_hours_can_define_productivity(hours):
    assert compare([event()],[time(hours=hours)])['value'] is None


def test_window_rejects_the_entire_pair():
    result=compare([event()],[time()],days=1)
    assert result['cohorts']==[] and 'Período fora da janela histórica.' in result['excluded'][0]['reasons']


def test_normalized_lengths_allow_different_pieces_but_raw_units_do_not():
    rows=[event(),event('b',quantity=20,length_mm=2000,profile='L50')]
    result=compare(rows,[time(hours=5)])
    assert result['volume']==50 and result['value']==10
    assert compare(rows,[time(hours=5)],method='units_hour')['value'] is None


def test_area_rate_uses_each_proven_piece_section():
    rows=[event(area='perfis',operation='corte'),event('b',quantity=20,section_unit=50,area='perfis',operation='corte')]
    result=compare(rows,[time(hours=3)],area='perfis',operation='corte',method='area_hour')
    assert result['volume']==1200 and result['value']==400


def test_complete_explicit_allocation_separates_operation_time():
    rows=[event(quantity=20),event('drill',quantity=40,operation='113')]
    allocations=[{'area':'cantoneiras','operation':'112','hours':2},{'area':'cantoneiras','operation':'113','hours':4}]
    c=time(hours=6,origin='Manual',definition={'operation_hours':allocations})
    result=compare(rows,[c]);assert result['value']==10 and result['hours']==2 and result['event_count']==1
    c['definition']['operation_hours']=allocations[:1]
    result=compare(rows,[c]);assert result['value'] is None and result['cohorts']==[]


def test_stale_manual_hours_cannot_be_rescued_by_an_allocation():
    c=time(hours=None,origin='Manual',reason='As declarações de origem mudaram; rever substituição.',
           definition={'operation_hours':[{'area':'cantoneiras','operation':'112','hours':5}]})
    assert compare([event()],[c])['value'] is None
