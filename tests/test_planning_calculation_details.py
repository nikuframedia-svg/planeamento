"""Derived explanations retain the effective operands and selected evidence."""
import pytest
from app.planning_calculations import calculate


def test_source_selection_exposes_ocr_excel_and_duplicate_event_evidence():
    fact={'record_id':7,'sheet_uid':'sheet','operation':'corte','quantity':4,'validated':True}
    result=calculate({'quantity_required':10,'length_mm':1000,'abocardar':'-'},
                     raw={'Ser.':9},operations=[{'operation':'corte','ocr_records':[fact,dict(fact)]}])
    assert result['values']['cut']==4 and result['values']['remaining']==6
    inputs=result['rules']['cut']['inputs']
    assert inputs['operation']=='corte' and inputs['ocr_total']==4 and inputs['excel_total']==9
    assert inputs['ocr_events']==[fact,fact]
    assert inputs['compatible'] is True and inputs['local_initial'] is False
    assert result['rules']['production_excess']['inputs']=={'Q':10,'produced':4}
    assert result['rules']['quantity_to_plan']['inputs']=={'Q':10,'produced':4,'operation':'corte'}


def test_unknown_ocr_keeps_excel_fallback_and_coverage_explanation():
    result=calculate({'quantity_required':10,'abocardar':'-'},raw={'Ser.':6},
        operations=[{'operation':'corte','ocr_records':[{'record_id':7,'quantity':None,'operation':'corte'}]}])
    assert result['values']['cut']==6
    rule=result['rules']['cut'];assert rule['source']=='Excel provisório'
    assert rule['inputs']['ocr_total'] is None and rule['inputs']['excel_total']==6
    assert rule['inputs']['coverage_reasons']


@pytest.mark.parametrize('mark,cut,boc,wanted',[('X',4,2,20),('-',4,None,40),(None,4,2,None)])
def test_final_percentage_identifies_both_operation_results(mark,cut,boc,wanted):
    result=calculate({'quantity_required':10,'abocardar':mark},raw={'Ser.':cut,'Aboc.':boc})
    assert result['values']['final_pct']==wanted
    inputs=result['rules']['final_pct']['inputs']
    assert inputs['cut_pct']==40 and inputs['boc_pct']==(20 if boc is not None else None)
    assert inputs['abocardar']==mark
    assert result['rules']['boc_remaining']['inputs']['abocardar']==mark


def test_secondary_absence_is_explained_without_a_fictitious_production_counter():
    result=calculate({'quantity_required':10,'operation':'119','operation_detail':'0'},area='cantoneiras',local_initial=True)
    assert result['values']['secondary_remaining']==0
    inputs=result['rules']['secondary_remaining']['inputs']
    assert inputs['operation_detail']=='0' and inputs['produced'] is None
    assert result['rules']['made']['inputs']['local_initial'] is True
    assert result['rules']['ocr_quantity']['reason']


def test_geometry_weights_lengths_and_manual_stock_have_their_effective_operands():
    result=calculate({'quantity_required':3,'material_type':'Varão quadrado','width_mm':10,'length_mm':2000,
                      'grade':'S235','stock_length_mm':12000,'abocardar':'-'},raw={'Ser.':1})
    rules=result['rules'];values=result['values']
    assert values['section_unit']==100 and values['weight_unit']==pytest.approx(1.57)
    assert rules['section_unit']['inputs']['width_mm']==10
    assert rules['weight_unit']['inputs']=={'A':100,'L':2000,'density_kg_m3':7850}
    assert rules['total_m']['inputs']=={'Q':3,'L':2000}
    assert rules['stock_length_mm']['inputs']['manual_stock_length_mm']==12000
    for name,rule in rules.items():
        if values.get(name) is not None:
            assert rule['inputs'] and rule['formula'] and rule['source'],name


def test_exact_catalogue_inputs_and_explicit_density_have_honest_provenance():
    result=calculate({'material_type':'Perfil U','profile':'UPN65x42','length_mm':1000},
                     sections={('perfil u','upn65x42'):[{'area':903,'cell':'C5'}]},density=9000)
    assert result['rules']['section_unit']['inputs']=={'material_type':'Perfil U','profile':'UPN65x42'}
    assert result['rules']['weight_unit']['inputs']['density_kg_m3']==9000
    assert '7850' not in result['rules']['weight_unit']['source']['rule']


def test_unknown_geometry_still_identifies_the_formula_attempted():
    result=calculate({'material_type':'Tubo redondo','outer_diameter_mm':20,'thickness_mm':12})
    rule=result['rules']['section_unit']
    assert result['values']['section_unit'] is None and rule['reason']
    assert 'π' in rule['formula']
    assert rule['inputs']['outer_diameter_mm']==20 and rule['inputs']['thickness_mm']==12


def test_cantoneiras_weight_and_iso_year_retain_original_inputs():
    result=calculate({'quantity_required':10,'operation':'119','operation_detail':'209','profile':'L TEST',
                      'length_mm':2000,'expected_date':'2027-01-01'},area='cantoneiras',raw={'Maq.':4},
                      weights={'l test':[{'kg_m':3,'cell':'C9'}]})
    assert result['rules']['weight_unit']['inputs']=={'profile':'L TEST','kg_m':3,'L':2000}
    assert result['values']['expected_year']==2026
    assert result['rules']['expected_year']['inputs']['expected_date']=='2027-01-01'
    assert result['rules']['expected_week']['inputs']==result['rules']['expected_year']['inputs']
