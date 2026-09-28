"""The independent Excel auditor must not excuse unexplained application data."""
from copy import deepcopy

import pytest

from scripts.audit_planning_excel_comparison import (
    exact_weight_difference, empty_input_difference, section_difference,
    structured_quantity_difference,
    nonnegative_difference, original_number,
    ocr_counter_difference,
    literal_derived_difference,
    missing_property_weight_difference, zero_balance_bars_difference,
    shifted_section_difference, manual_week_difference,
)


def fixture():
    def cell(address,value,formula=None):
        return {'cell':address,'value':value,'formula':formula}
    catalogue={'l100x100x10':[{'designation':cell('B7','L100X100X10'),
                            'property':cell('C7',15.1),'kg_m':15.1}],
               'l100x100x8':[{'designation':cell('B8','L100X100X8'),
                           'property':cell('C8',12.8),'kg_m':12.8}]}
    cells={'Q':cell('Q10','L100X100X10 '),'R':cell('R10',2000),
           'O':cell('O10',10),'AA':cell('AA10',4),
           'AP':cell('AP10',25.6,"IF(Q10=\"\",0,VLOOKUP(Q10,'Tabela pesos'!$B$3:$C$462,2,5)*R10/1000)"),
           'AS':cell('AS10',153.6)}
    values={'profile':'L100X100X10','length_mm':2000,'weight_unit':30.2,
            'quantity_required':10,'made':4}
    return cells,values,catalogue


@pytest.mark.parametrize('field,observed',[('weight_unit',30.2),('weight',181.2)])
def test_exact_weight_difference_traces_wrong_property_to_other_designation(field,observed):
    cells,values,catalogue=fixture()
    proof=exact_weight_difference({'field':field,'observed':observed},values,cells,catalogue)
    assert proof['classification']=='intentional_exact_weight_lookup'
    assert proof['original_implied_kg_m']==12.8
    assert proof['other_designations_with_that_property'][0]['designation']['value']=='L100X100X8'


@pytest.mark.parametrize('mutation', ['different_identity','different_length','wrong_application',
    'unknown_cached_property','different_counter','unexplained_pending_cache'])
def test_weight_audit_rejects_unsupported_explanations(mutation):
    cells,values,catalogue=fixture()
    if mutation=='different_identity':values['profile']='L100X100X8'
    elif mutation=='different_length':values['length_mm']=3000
    elif mutation=='wrong_application':values['weight_unit']=100
    elif mutation=='unknown_cached_property':cells['AP']['value']=19.99
    elif mutation=='different_counter':values['made']=5
    elif mutation=='unexplained_pending_cache':cells['AS']['value']=100
    assert exact_weight_difference({'field':'weight','observed':181.2},values,cells,catalogue) is None


def test_missing_or_divergent_exact_property_cannot_be_accepted_as_a_number():
    cells,values,catalogue=fixture()
    catalogue.pop('l100x100x10')
    values['weight_unit']=None
    check={'field':'weight_unit','observed':None}
    assert exact_weight_difference(check,values,cells,catalogue)['classification']=='intentional_missing_exact_weight'
    assert exact_weight_difference({**check,'observed':25.6},values,cells,catalogue) is None
    entries=deepcopy(catalogue['l100x100x8'])
    catalogue['l100x100x10']=entries+[dict(entries[0],kg_m=99)]
    assert exact_weight_difference(check,values,cells,catalogue)['classification']=='intentional_ambiguous_exact_weight'


def test_missing_original_designation_remains_unresolved():
    cells,values,catalogue=fixture()
    del cells['Q'];values['profile']='';values['weight_unit']=None
    assert exact_weight_difference({'field':'weight_unit','observed':None},values,cells,catalogue) is None


def test_zero_cache_for_empty_profile_is_explained_only_with_the_literal_original_rule():
    cells={'AP':{'value':0,'formula':'IF(Q4="",0,VLOOKUP(Q4,B3:C10,2,5))'}}
    assert empty_input_difference('cantoneiras','weight_unit',None,{'profile':''},cells)['classification']=='intentional_unknown_profile'
    assert empty_input_difference('cantoneiras','weight_unit',99,{'profile':''},cells) is None
    assert empty_input_difference('cantoneiras','weight_unit',None,{'profile':'known'},cells) is None
    cells['AP']['formula']='99-99'
    assert empty_input_difference('cantoneiras','weight_unit',None,{'profile':''},cells) is None


def test_unit_comparison_cannot_excuse_a_changed_observed_result():
    cells,values,catalogue=fixture()
    assert exact_weight_difference({'field':'weight_unit','observed':999},values,cells,catalogue) is None


def quantity_fixture():
    cells = {k: {'cell': k+'43', 'value': v} for k, v in
             {'N':62, 'AH':130, 'Q':1460, 'AM':1460, 'BR':90520}.items()}
    cells['BR']['formula'] = 'N43*Q43'
    return cells, {'quantity_required':130, 'length_mm':1460}


@pytest.mark.parametrize('field,observed', [('total_length',189800), ('total_m',189.8)])
def test_total_uses_structured_quantity_with_both_results_proven(field, observed):
    cells, values = quantity_fixture()
    proof = structured_quantity_difference({'field':field, 'observed':observed}, values, cells)
    assert proof['classification'] == 'intentional_structured_quantity'
    assert proof['independent_original_total_mm'] == 90520


@pytest.mark.parametrize('mutation', ['new_quantity','new_length','bad_cache','other_formula','bad_result'])
def test_quantity_explanation_rejects_unproven_differences(mutation):
    cells, values = quantity_fixture()
    observed = 189800
    if mutation == 'new_quantity': values['quantity_required'] = 131
    if mutation == 'new_length': values['length_mm'] = 1461
    if mutation == 'bad_cache': cells['BR']['value'] = 1
    if mutation == 'other_formula': cells['BR']['formula'] = 'AH43*AM43'
    if mutation == 'bad_result': observed = 90520
    assert structured_quantity_difference({'field':'total_length','observed':observed},values,cells) is None


def section_fixture(q=0):
    cells = {k: {'cell':k+'87', 'value':v} for k, v in
             {'AF':'Perfil T','AG':'T50x50','AH':q,'AP':0,'AX':0}.items()}
    cells['AX']['formula'] = ' IFERROR( IF(AH87 = "", "", AP87 / AH87 ), 0 )'
    cells['AP']['formula'] = 'IFERROR(_xlfn.XLOOKUP(AG87,AreaSecaoCorte!$B$3:$B$700,AreaSecaoCorte!$C$3:$C$700),IF(AF87="","",0))*AH87'
    values = {'material_type':'Perfil T','profile':'T50x50','quantity_required':q,'section_unit':600}
    table = {('perfil t','t50x50'):[{'cell':'C3','value':600}]}
    return cells,values,table


def test_zero_quantity_does_not_erase_independently_resolved_unit_property():
    cells,values,table=section_fixture()
    proof=section_difference({'field':'section_unit','observed':600},values,cells,table)
    assert proof['classification']=='intentional_unit_property_at_zero_quantity'
    cells['AH']['value']=None;values['quantity_required']=None;cells['AX']['value']=''
    assert section_difference({'field':'section_unit','observed':600},values,cells,table)['classification']=='intentional_unit_property_without_quantity'


@pytest.mark.parametrize('mutation', ['different_profile','different_dimension','bad_cache','different_formula','wrong_property','wrong_result'])
def test_property_explanation_requires_original_inputs_and_correct_result(mutation):
    cells,values,table=section_fixture()
    observed=600
    if mutation=='different_profile': values['profile']='T60x60'
    if mutation=='different_dimension': values['width_mm']=10
    if mutation=='bad_cache': cells['AX']['value']=999
    if mutation=='different_formula': cells['AX']['formula']='0'
    if mutation=='wrong_property': values['section_unit']=601
    if mutation=='wrong_result': observed=601
    assert section_difference({'field':'section_unit','observed':observed},values,cells,table) is None


@pytest.mark.parametrize('field', ['section_unit','section_total'])
def test_missing_exact_section_is_unknown_instead_of_cached_zero(field):
    cells,values,table=section_fixture(q=3)
    values['section_unit']=None
    assert section_difference({'field':field,'observed':None},values,cells,{})['classification']=='intentional_unresolved_exact_section'
    assert section_difference({'field':field,'observed':None},values,cells,table) is None
    cells['AP']['formula']='0'
    assert section_difference({'field':field,'observed':None},values,cells,{}) is None


def test_original_numbers_preserve_zero_and_validate_grouping():
    assert original_number(0) == 0
    assert original_number('1 543') == 1543
    assert original_number('1 54') is None
    assert original_number(None) is None


def excess_fixture(area):
    cells,values,table=section_fixture(q=15)
    values.update(quantity_required=15, cut=30, made=30, production_excess=15,
                  length_mm=2000, stock_length_mm=6000)
    for k,v in {'N':15,'V':30,'CD':-15,'AS':-15,'AX':600,'AY':-9000,'Q':2000,'BS':6000,'BT':-5,
                'O':15,'AA':30,'AG':-15,'R':2000,'AM':30,'BJ':60,'BK':-30}.items():
        # AG is a profile in Perfis but the signed balance in Cantoneiras.
        if k=='AG' and area=='perfis':continue
        cells[k]={'cell':k+'87','value':v}
    formulas={'CD':'N87-V87','AS':'IF(AH87="","",AH87-V87)',
              'AY':'IF(AX87="","",AS87*AX87)',
              'BT':'ROUNDUP(CD87/(ROUNDDOWN((BS87/Q87),0)),0)',
              'BK':'Tabela4[[#This Row],[comp.total (m)]]-Tabela4[[#This Row],[m prod.]]'}
    if area=='cantoneiras':formulas['AG']='Tabela4[[#This Row],[QTD]]-Tabela4[[#This Row],[Maq.]]'
    for k,f in formulas.items():cells[k]['formula']=f
    return cells,values,table


@pytest.mark.parametrize('area,field,old', [('perfis','bars',-5),('perfis','section_pending',-9000),
    ('perfis','remaining',-15),('perfis','quantity_to_plan',-15),
    ('cantoneiras','remaining_m',-30),('cantoneiras','remaining',-15)])
def test_excess_preserves_signed_excel_result_and_clips_pending_work(area,field,old):
    cells,values,table=excess_fixture(area)
    proof=nonnegative_difference(area,{'field':field,'observed':0},values,cells,table)
    assert proof['independent_original_result']==old
    assert proof['independent_current_result']==0
    assert proof['independent_excess']==15


@pytest.mark.parametrize('mutation', ['quantity','production','excess','cached_balance','cached_metres','length','formula','result'])
def test_negative_excel_does_not_justify_unexplained_zero(mutation):
    cells,values,table=excess_fixture('cantoneiras'); observed=0
    if mutation=='quantity':values['quantity_required']=14
    if mutation=='production':values['made']=31
    if mutation=='excess':values['production_excess']=0
    if mutation=='cached_balance':cells['AG']['value']=-16
    if mutation=='cached_metres':cells['BK']['value']=-31
    if mutation=='length':values['length_mm']=2001
    if mutation=='formula':cells['BK']['formula']='-30'
    if mutation=='result':observed=1
    assert nonnegative_difference('cantoneiras',{'field':'remaining_m','observed':observed},values,cells,table) is None


def ocr_fixture(area):
    def cell(k,v,formula=None):return {'cell':k+'10','value':v,'formula':formula}
    q,old,made=10,2,7
    values={'quantity_required':q,'cut':made,'made':made,'operation':'119','length_mm':2000,
            'stock_length_mm':6000,'material_type':'Varão quadrado','width_mm':10,
            'profile':'L100X100X10' if area=='cantoneiras' else '10','section_unit':100,
            'weight_unit':30.2 if area=='cantoneiras' else 1.57}
    source={'area':area,'key':'piece','operation':'corte' if area=='perfis' else '119',
            'result':'passed','issues':[],'uncertain_records':[],'expected':made,'observed':made}
    source['events']=[{'record_id':1,'sheet_uid':'a','child_key':None,'quantity':3,'operation':source['operation']},
                      {'record_id':2,'sheet_uid':'b','child_key':None,'quantity':4,'operation':source['operation']}]
    cells={k:cell(k,v) for k,v in {'N':q,'AH':q,'V':old,'Q':2000,'AM':2000,'BS':6000,
                                  'AF':'Varão quadrado','AJ':10,'AX':100}.items()}
    formulas={'CD':(8,'N10-V10'),'AS':(8,'IF(AH10="","",AH10-V10)'),
              'Y':(20,'IF((V10/VALUE($N10))*100=100,"X",((V10/VALUE($N10)))*100)'),
              'BT':(3,'ROUNDUP(CD10/(ROUNDDOWN((BS10/Q10),0)),0)'),
              'AY':(800,'IF(AX10="","",AS10*AX10)'),
              'DB':(12.56,'IFERROR(IF(((AY10/1000000)*(AM10/1000)*7850)<0,0,((AY10/1000000)*(AM10/1000)*7850)),"")')}
    for k,(v,f) in formulas.items():cells[k]=cell(k,v,f)
    catalogue={'l100x100x10':[{'designation':cell('B','L100X100X10'),'property':cell('C',15.1),'kg_m':15.1}]}
    if area=='cantoneiras':
        cells.update({k:cell(k,v) for k,v in {'O':q,'AA':old,'R':2000,'Q':'L100X100X10','AH':' ','AP':30.2,'AM':20,'BJ':4}.items()})
        cells.update(AG=cell('AG',8,'Tabela4[[#This Row],[QTD]]-Tabela4[[#This Row],[Maq.]]'),
                     BK=cell('BK',16,'Tabela4[[#This Row],[comp.total (m)]]-Tabela4[[#This Row],[m prod.]]'),
                     AS=cell('AS',241.6,'IF(Tabela4[[#This Row],[Fechado]]="x",0,(O10-AA10)*AP10)'))
    return cells,values,source,catalogue


@pytest.mark.parametrize('area,field,observed,old',[
    ('perfis','remaining',3,8),('perfis','quantity_to_plan',3,8),('perfis','cut_pct',70,20),
    ('perfis','bars',1,3),('perfis','section_pending',300,800),('perfis','weight',4.71,12.56),
    ('cantoneiras','remaining',3,8),('cantoneiras','quantity_to_plan',3,8),
    ('cantoneiras','remaining_m',6,16),('cantoneiras','weight',90.6,241.6)])
def test_ocr_change_requires_reconstructing_old_cache_and_new_result(area,field,observed,old):
    cells,values,source,weights=ocr_fixture(area)
    proof=ocr_counter_difference(area,{'field':field,'observed':observed},values,cells,source,{},weights)
    assert proof is not None
    assert proof['classification']=='intentional_verified_ocr_counter'
    assert proof['independent_original_result']==pytest.approx(old)
    assert proof['independent_current_result']==pytest.approx(observed)


@pytest.mark.parametrize('mutation',['no_proof','failed_proof','partial','wrong_operation','wrong_area',
    'bad_sum','duplicate_event','unknown_event_quantity','bad_selected','changed_quantity','bad_cache','other_formula','bad_result'])
def test_ocr_presence_alone_cannot_excuse_a_difference(mutation):
    cells,values,source,weights=ocr_fixture('perfis');observed=3
    if mutation=='no_proof':source=None
    if mutation=='failed_proof':source['result']='failed'
    if mutation=='partial':source['uncertain_records']=[99]
    if mutation=='wrong_operation':source['operation']='abocardar'
    if mutation=='wrong_area':source['area']='cantoneiras'
    if mutation=='bad_sum':source['expected']=8
    if mutation=='duplicate_event':source['events'].append(dict(source['events'][0]))
    if mutation=='unknown_event_quantity':source['events'][0]['quantity']=None
    if mutation=='bad_selected':values['cut']=8
    if mutation=='changed_quantity':values['quantity_required']=11
    if mutation=='bad_cache':cells['CD']['value']=9
    if mutation=='other_formula':cells['CD']['formula']='8'
    if mutation=='bad_result':observed=2
    assert ocr_counter_difference('perfis',{'field':'remaining','observed':observed},values,cells,source,{},weights) is None


def test_excel_blank_is_zero_only_in_reconstructed_cache_not_in_selected_production():
    cells,values,source,weights=ocr_fixture('perfis')
    del cells['V'];cells['CD']['value']=10
    proof=ocr_counter_difference('perfis',{'field':'remaining','observed':3},values,cells,source,{},weights)
    assert proof['excel_arithmetic_counter']==0 and proof['selected_counter_from_verified_events']==7
    values['cut']=None
    assert ocr_counter_difference('perfis',{'field':'remaining','observed':None},values,cells,source,{},weights) is None


def test_ocr_metre_and_section_comparisons_reject_changed_inputs():
    cells,values,source,weights=ocr_fixture('cantoneiras');values['length_mm']=3000
    assert ocr_counter_difference('cantoneiras',{'field':'remaining_m','observed':9},values,cells,source,{},weights) is None
    cells,values,source,weights=ocr_fixture('perfis');values['width_mm']=20
    assert ocr_counter_difference('perfis',{'field':'section_pending','observed':1200},values,cells,source,{},weights) is None


def test_closed_excel_weight_is_separate_from_current_historical_pending_weight():
    cells,values,source,weights=ocr_fixture('cantoneiras');cells['AH']['value']='X';cells['AS']['value']=0
    proof=ocr_counter_difference('cantoneiras',{'field':'weight','observed':90.6},values,cells,source,{},weights)
    assert proof['independent_original_result']==0 and proof['independent_current_result']==pytest.approx(90.6)


@pytest.mark.parametrize('field,old,new', [('remaining',-1,224),('cut_pct',100*176/175,44),('bars',-1,56)])
def test_structured_quantity_recalculates_production_dependent_results(field,old,new):
    cells,values,_,_=ocr_fixture('perfis')
    for col,value in {'N':175,'AH':400,'V':176,'Q':1278,'AM':1278,'CD':-1,'Y':100*176/175,'BT':-1}.items():
        cells[col]['value']=value
    values.update(quantity_required=400,cut=176,length_mm=1278)
    proof=structured_quantity_difference({'field':field,'observed':new},values,cells)
    assert proof['independent_original_result']==pytest.approx(old)
    values['cut']=177
    assert structured_quantity_difference({'field':field,'observed':new},values,cells) is None


@pytest.mark.parametrize('family,dimensions,formula,legacy',[
    ('Tubo redondo',{'AI':20,'AL':10},'AreaTuboRedondo(AI87,AL87)',100*3.141592653589793),
    ('Tubo redondo',{'AI':42.4},'AreaTuboRedondo(AI87,AL87)',0),
    ('Tubo quadrado',{'AJ':80},'AreaTuboQuadrado(AJ87,AL87)',0),
    ('Tubo retangular',{'AJ':70,'AK':40},'AreaTuboRetangular(AJ87,AK87,AL87)',0),
    ('Calha',{'AJ':40,'AK':22},'AreaCalha(AJ87,AK87,AL87)',0),
])
@pytest.mark.parametrize('field',['section_unit','section_total'])
def test_invalid_geometry_reconstructs_vba_cache_without_accepting_it_as_current(family,dimensions,formula,legacy,field):
    cells,values,_=section_fixture(q=2)
    cells['AF']['value']=family;cells['AG']['value']=None
    cells['AP'].update(value=legacy*2,formula=f'IFERROR(IF(AF87="{family}",{formula},0)*AH87,"")')
    cells['AX']['value']=legacy
    values.update(material_type=family,profile=None,section_unit=None)
    for col,key in [('AI','outer_diameter_mm'),('AJ','width_mm'),('AK','height_mm'),('AL','thickness_mm')]:
        cells[col]={'cell':col+'87','value':dimensions.get(col)};values[key]=dimensions.get(col)
    proof=section_difference({'field':field,'observed':None},values,cells,{})
    assert proof['classification']=='intentional_invalid_or_missing_geometry'
    assert proof['excel_geometric_area']==pytest.approx(legacy)
    cells['AP']['value']=1
    assert section_difference({'field':field,'observed':None},values,cells,{}) is None
    cells['AP'].update(value=legacy*2,formula='0')
    assert section_difference({'field':field,'observed':None},values,cells,{}) is None


@pytest.mark.parametrize('field,observed',[('quantity_to_plan',3),('section_pending',300),('weight',4.71),('bars',1)])
def test_literal_derived_perfis_recomputed_from_unchanged_inputs(field,observed):
    cells,values,_,_=ocr_fixture('perfis')
    cells['V']['value']=7
    cells['AS']['formula']=None
    cells['AY']['formula']=None
    if field=='bars':cells['BT']['formula']=None
    proof=literal_derived_difference('perfis',{'field':field,'observed':observed},values,cells,{})
    assert proof['classification']=='intentional_recalculated_literal_derived'
    assert proof['independent_current_result']==pytest.approx(observed)
    values['cut']=8
    assert literal_derived_difference('perfis',{'field':field,'observed':observed},values,cells,{}) is None


@pytest.mark.parametrize('field',['remaining','quantity_to_plan'])
def test_literal_cantoneiras_balance_does_not_override_known_production(field):
    cells,values,_,_=ocr_fixture('cantoneiras')
    cells['AA']['value']=7;cells['AG']['formula']=None;cells['AG']['value']=10
    proof=literal_derived_difference('cantoneiras',{'field':field,'observed':3},values,cells,{})
    assert proof['independent_original_result']==10
    cells['AG']['formula']='10'
    assert literal_derived_difference('cantoneiras',{'field':field,'observed':3},values,cells,{}) is None


@pytest.mark.parametrize('mutation',['none','property','length','production','cache','formula','result','ambiguous'])
def test_negative_direct_weight_requires_exact_property_and_same_inputs(mutation):
    cells,values,_,weights=ocr_fixture('cantoneiras')
    cells['AA']['value']=12;cells['AG']['value']=-2
    cells['AS'].update(value=-60.4,formula='(O10-AA10)*AP10')
    values.update(made=12,production_excess=2);observed=0
    if mutation=='property':values['weight_unit']=30
    if mutation=='length':values['length_mm']=2001
    if mutation=='production':values['made']=13
    if mutation=='cache':cells['AS']['value']=-61
    if mutation=='formula':cells['AS']['formula']='-60.4'
    if mutation=='result':observed=1
    if mutation=='ambiguous':weights['l100x100x10'].append({'kg_m':16})
    proof=nonnegative_difference('cantoneiras',{'field':'weight','observed':observed},values,cells,{},weights)
    if mutation=='none':assert proof['independent_original_result']==pytest.approx(-60.4)
    else:assert proof is None


def test_direct_excel_weight_does_not_apply_the_conditional_closure_rule():
    cells,values,source,weights=ocr_fixture('cantoneiras')
    cells['AS']['formula']='(O10-AA10)*AP10';cells['AH']['value']='X'
    proof=ocr_counter_difference('cantoneiras',{'field':'weight','observed':90.6},values,cells,source,{},weights)
    assert proof['independent_original_result']==pytest.approx(241.6)
    cells['AS']['value']=0
    assert ocr_counter_difference('cantoneiras',{'field':'weight','observed':90.6},values,cells,source,{},weights) is None


@pytest.mark.parametrize('mutation',['none','known_property','bad_area','bad_weight','formula','length','result'])
def test_unknown_weight_requires_independent_missing_property_and_old_cache(mutation):
    cells,values,_=section_fixture(q=3)
    values.update(section_unit=None,weight_unit=None,length_mm=2000)
    for col,value,formula in [('AS',0,None),('AY',0,'IF(AX87="","",AS87*AX87)'),('AM',2000,None),
        ('DB',0,'IFERROR(IF(((AY87/1000000)*(AM87/1000)*7850)<0,0,((AY87/1000000)*(AM87/1000)*7850)),"")')]:
        cells[col]={'cell':col+'87','value':value,'formula':formula}
    observed=None;table={}
    if mutation=='known_property':table={('perfil t','t50x50'):[{'cell':'C3','value':600}]}
    if mutation=='bad_area':cells['AY']['value']=1
    if mutation=='bad_weight':cells['DB']['value']=1
    if mutation=='formula':cells['DB']['formula']='0'
    if mutation=='length':values['length_mm']=2001
    if mutation=='result':observed=0
    proof=missing_property_weight_difference({'field':'weight','observed':observed},values,cells,table)
    if mutation=='none':assert proof['independent_original_result']==0 and proof['independent_current_result'] is None
    else:assert proof is None


@pytest.mark.parametrize('mutation',['none','production','quantity','length','cache','formula','result'])
def test_zero_bars_can_be_known_despite_excel_length_error(mutation):
    cells,values,_,_=ocr_fixture('perfis')
    cells['V']['value']=10;cells['CD']['value']=0
    cells['Q'].update(value='',formula='IF(AM10="","",AM10)');cells['AM']['value']=None
    cells['BT'].update(value='#VALUE!',type='e')
    values.update(cut=10,remaining=0,length_mm=None);observed=0
    if mutation=='production':values['cut']=9
    if mutation=='quantity':values['quantity_required']=11
    if mutation=='length':values['length_mm']=2000
    if mutation=='cache':cells['BT']['value']='#REF!'
    if mutation=='formula':cells['BT']['formula']='1/0'
    if mutation=='result':observed=1
    proof=zero_balance_bars_difference({'field':'bars','observed':observed},values,cells)
    if mutation=='none':assert proof['independent_current_result']==0
    else:assert proof is None


@pytest.mark.parametrize('mutation',['none','new_profile','shift','wrong_lookup_exists','total','result'])
def test_displaced_lookup_proves_translation_and_wrong_lookup_absence(mutation):
    from openpyxl.formula.translate import Translator
    cells,values,table=section_fixture(q=2)
    cells['AP'].update(value=1200,formula='IFERROR(IFERROR(_xlfn.XLOOKUP(AG87,AreaSecaoCorte!$B$3:$B$700,AreaSecaoCorte!$C$3:$C$700),IF(AF87="","",0))*AH87,"")')
    cells['AX']['formula']=Translator('='+cells['AP']['formula'],origin='AP87').translate_formula('AX87')[1:]
    cells['AN']={'cell':'AN87','value':0};cells['AO']={'cell':'AO87','value':'S355J2'}
    observed=600
    if mutation=='new_profile':values['profile']='T60x60'
    if mutation=='shift':cells['AX']['formula']=cells['AP']['formula']
    if mutation=='wrong_lookup_exists':table[('perfil t','s355j2')]=[{'cell':'C4','value':100}]
    if mutation=='total':cells['AP']['value']=1201
    if mutation=='result':observed=0
    proof=shifted_section_difference({'field':'section_unit','observed':observed},values,cells,table)
    if mutation=='none':assert proof['independent_current_result']==600 and proof['independent_original_result']==0
    else:assert proof is None


@pytest.mark.parametrize('mutation',['none','no_proof','wrong_operation','wrong_need','wrong_source','review',
    'event_revision','event_value','event_scope','event_missing','event_duplicate','changed_date','excel_date','result'])
def test_manual_week_requires_audited_persisted_operation_date(mutation):
    state={'need_id':'need','scope':'op','field':'expected_date','value':'2027-01-01',
           'human_decision':'write','source':{'kind':'manual'},'revision':3,'requires_review':False}
    change={'field':'expected_date','scope':'op','after':'2027-01-01','source':{'kind':'manual'},'decision':'write'}
    proof={'state':state,'operation':{'id':'op','need_id':'need','area':'perfis','code':'corte'},
           'link':{'need_id':'need','kind':'plan_line','source_id':'plan'},
           'event':{'need_id':'need','revision':3,'action':'preparation_saved','detail':{'changes':[change]}}}
    cells={'AV':{'cell':'AV48','value':'','formula':'IF(AR48="","",_xlfn.ISOWEEKNUM(AR48))'},
           'AW':{'cell':'AW48','value':1900,'formula':'YEAR(AR48)'}}
    values={'expected_date':'2027-01-01'};observed='2026-W53'
    if mutation=='no_proof':proof=None
    if mutation=='wrong_operation':proof['operation']['code']='abocardar'
    if mutation=='wrong_need':proof['operation']['need_id']='other'
    if mutation=='wrong_source':proof['link']['source_id']='other'
    if mutation=='review':state['requires_review']=True
    if mutation=='event_revision':proof['event']['revision']=2
    if mutation=='event_value':change['after']='2026-12-01'
    if mutation=='event_scope':change['scope']='other'
    if mutation=='event_missing':proof['event']['detail']['changes']=[]
    if mutation=='event_duplicate':proof['event']['detail']['changes'].append(deepcopy(change))
    if mutation=='changed_date':values['expected_date']='2027-01-02'
    if mutation=='excel_date':cells['AR']={'value':'2027-01-01'}
    if mutation=='result':observed='2027-W53'
    result=manual_week_difference({'field':'expected_week','observed':observed},values,cells,proof,'plan')
    if mutation=='none':assert result['independent_current_result']=='2026-W53'
    else:assert result is None
