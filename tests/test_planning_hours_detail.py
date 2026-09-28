"""Calculation explanations must expose the actual volume and time units."""
import pytest
from app.raw import capacity

@pytest.mark.parametrize('method,q,length,section,rate,setup,volume,unit,hours,dimension',[
 ('metres_hour',60,2000,None,30,30,120,'m',4.5,'length_mm'),
 ('area_hour',5,None,120,200,12,600,'mm²',3.2,'section_unit'),
 ('units_hour',15,None,None,20,6,15,'un.',.85,None),
 ('minutes_unit',8,None,None,4,10,8,'un.',.7,None),
 ('fixed_minutes',80,None,None,45,15,None,None,1,None),
 ('metres_hour',0,None,None,30,30,0,'m',0,'length_mm'),
 ('metres_hour',60,None,None,30,0,None,'m',None,'length_mm'),
 ('area_hour',5,None,None,200,0,None,'mm²',None,'section_unit'),
])
def test_explanation_uses_effective_volume_and_preparation(method,q,length,section,rate,setup,volume,unit,hours,dimension):
    values={'quantity_to_plan':q,'length_mm':length,'section_unit':section}
    selected={'method':method,'value':rate,'setup_minutes':setup}
    value,reason=capacity.estimate(values,selected,'119')
    applied={'rate':selected,'hours':value,'reason':reason,'source':'Manual','factor':1,'history_hash':'proof'}
    rule=capacity.estimate_rule(values,applied)
    inputs=rule['inputs']
    assert inputs['quantity']==q and inputs['rate']==selected
    assert inputs['volume']==volume and inputs['volume_unit']==unit
    assert inputs['setup_minutes']==(0 if q==0 else setup)
    assert inputs['method']==method and rule['unit']=='h'
    assert rule['source']=='Manual' and rule['history_hash']=='proof' and rule['contract']
    if dimension:assert inputs[dimension]==values[dimension]
    if method=='minutes_unit':assert '×' in rule['formula'] and '/ 60' in rule['formula']
    if method=='fixed_minutes':assert 'fixos' in rule['formula'] and '/ 60' in rule['formula']
    if q==0:assert '0 h' in rule['formula']
    if hours is None:assert value is None and rule['reason']
    else:assert value==pytest.approx(hours)


def test_excel_factor_explains_already_multiplied_rate_without_applying_it_twice():
    values={'quantity_to_plan':60,'section_unit':200}
    applied={'source':'Excel provisório','rate':{'method':'area_hour','value':600},'hours':20,'reason':None,'factor':3,'history_hash':'proof'}
    rule=capacity.estimate_rule(values,applied)
    assert rule['inputs']['excel_factor']==3
    assert rule['inputs']['reference_rate_value']==200
    assert rule['inputs']['volume']==12000
    assert rule['inputs']['rate']['value']==600


def test_unknown_rate_retains_unknown_method_and_reason():
    rule=capacity.estimate_rule({'quantity_to_plan':10,'length_mm':2000},
        {'source':None,'rate':None,'hours':None,'reason':'Taxa por confirmar','history_hash':'proof'})
    assert rule['inputs']['method'] is None and rule['inputs']['volume'] is None
    assert rule['inputs']['setup_minutes'] is None
    assert rule['reason']=='Taxa por confirmar'
