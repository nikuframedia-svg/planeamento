"""Independent operation-load examples, including explicit setup and unknowns."""
import pytest
from app.raw.capacity import estimate
from scripts.audit_planning_operation_hours import expected_hours


@pytest.mark.parametrize('method,q,length,section,rate,setup,wanted',[
 ('metres_hour',60,2000,None,30,0,4),
 ('metres_hour',60,2000,None,30,30,4.5),
 ('area_hour',5,None,120,200,0,3),
 ('area_hour',5,None,120,200,12,3.2),
 ('units_hour',15,None,None,20,0,0.75),
 ('units_hour',15,None,None,20,6,0.85),
 ('minutes_unit',8,None,None,4,0,8/15),
 ('minutes_unit',8,None,None,4,10,0.7),
 ('fixed_minutes',80,None,None,45,15,1),
 ('metres_hour',0,None,None,30,30,0),
 ('area_hour',0,None,None,200,12,0),
 ('minutes_unit',0,None,None,4,10,0),
 ('metres_hour',None,2000,None,30,0,None),
 ('metres_hour',60,None,None,30,0,None),
 ('metres_hour',60,0,None,30,0,None),
 ('area_hour',5,None,None,200,0,None),
 ('area_hour',5,None,0,200,0,None),
])
def test_hours_match_independent_examples(method,q,length,section,rate,setup,wanted):
    values={'quantity_to_plan':q,'length_mm':length,'section_unit':section}
    selected={'method':method,'value':rate,'setup_minutes':setup}
    observed,reason=estimate(values,selected,'corte' if method=='area_hour' else '119')
    independent=expected_hours(q,selected,length,section,True)
    if wanted is None:
        assert observed is independent is None
        assert reason
    else:
        assert observed==pytest.approx(wanted,rel=1e-8,abs=1e-6)
        assert independent==pytest.approx(wanted,rel=1e-8,abs=1e-6)
        assert reason is None


@pytest.mark.parametrize('case,wanted_source,wanted_rate,wanted_factor',[
 ('manual','Manual',20,1),('expired','Histórico',10,1),
 ('future','Histórico',10,1),('wrong_profile','Histórico',10,1),
 ('conflict',None,None,1),('history','Histórico',10,1),
 ('excel_51','Excel provisório',15,3),('excel_50','Excel provisório',5,1),
 ('absent',None,None,1),
])
def test_rate_priority_with_explicit_applicability(case,wanted_source,wanted_rate,wanted_factor):
    from app.raw.productivity import select_rate
    from scripts.audit_planning_rate_selection import choose
    values={'machine':'Serrote Fita Thomas IS639 Pav.1','quantity_required':50 if case=='excel_50' else 51,
            'material_type':'Tubo rectangular','profile':'100x50x3'}
    definition={'resource_id':'r','area':'perfis','operation':'corte','method':'area_hour',
                'value':20,'confirmed':True,'valid_from':'2026-01-01','material_type':'Tubo retangular'}
    if case=='expired':definition['valid_until']='2026-09-23'
    if case=='future':definition['valid_from']='2026-09-25'
    if case=='wrong_profile':definition['profile']='100x50x4'
    records=[{'id':'manual-1','definition':definition}] if case in ('manual','expired','future','wrong_profile','conflict') else []
    if case=='conflict':records.append({'id':'manual-2','definition':dict(definition)})
    history={'method':'area_hour','value':None if case.startswith('excel') or case=='absent' else 10}
    excel=None if case=='absent' else {'method':'area_hour','value':5}
    expected=choose(values,'perfis','corte','r',records,history,excel,'2026-09-24')
    actual=select_rate(values,area='perfis',operation='corte',resource_id='r',manual=records,
                       historical_rate=history,excel=excel,when='2026-09-24')
    for result in (expected,actual):
        assert result['source']==wanted_source
        assert (result['rate'] or {}).get('value')==wanted_rate
        if case!='conflict':assert result['factor']==wanted_factor
    if case=='conflict':assert sorted(actual['candidates'])==expected['candidates']==['manual-1','manual-2']
