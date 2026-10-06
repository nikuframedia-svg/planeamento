"""Production is selected per operation; changing order must not move counters."""
from app.planning_calculations import calculate
from app.planning_calculations import production_source
import pytest
from scripts.audit_planning_production_sources import select_counter


def test_cantoneiras_swapped_primary_does_not_inherit_other_operation_excel():
    result=calculate({'quantity_required':10,'operation':'119','operation_detail':'112'},area='cantoneiras',
        raw={'1ª Oper.':112,'2ª Oper.':119,'Maq.':8},
        operations=[{'operation':'112','macro_quantity':8},{'operation':'119','macro_quantity':None}])
    values=result['values'];sources={s['operation']:s for s in result['operations']}
    assert values['made'] is None and values['remaining'] is None
    assert sources['119']['excel'] is None and sources['119']['origin']=='Indisponível'
    assert 'operação 112' in sources['119']['reason']
    assert sources['112']['excel']==8 and sources['112']['remaining']==2
    assert values['secondary_remaining']==2


def test_cantoneiras_new_primary_without_operation_evidence_does_not_take_old_excel():
    result=calculate({'quantity_required':10,'operation':'113'},area='cantoneiras',
        raw={'1ª Oper.':112,'Maq.':8})
    assert result['values']['made'] is None and result['values']['ocr_quantity'] is None


def test_cantoneiras_selected_operation_keeps_its_own_explicit_counter():
    result=calculate({'quantity_required':10,'operation':'119'},area='cantoneiras',
        raw={'1ª Oper.':112,'2ª Oper.':119,'Maq.':8},
        operations=[{'operation':'119','macro_quantity':3}])
    assert result['values']['made']==3 and result['values']['remaining']==7


def test_cantoneiras_matching_original_primary_and_legacy_unbound_input_are_preserved():
    for raw in ({'1ª Oper.':112,'Maq.':8},{'Maq.':8}):
        result=calculate({'quantity_required':10,'operation':'112'},area='cantoneiras',raw=raw)
        assert result['values']['made']==8 and result['values']['remaining']==2


def fact(quantity=3,**values):
    return {'record_id':1,'sheet_uid':'s','row_index':0,'operation':'corte','quantity':quantity,**values}


@pytest.mark.parametrize('records,macro,flags,expected,origin',[
    ([fact()],9,{},3,'OCR validado'),
    ([fact()],1,{},3,'OCR validado'),
    ([fact(0)],9,{},0,'OCR validado'),
    ([],0,{},0,'Excel provisório'),
    ([],9,{},9,'Excel provisório'),
    ([],None,{},None,'Indisponível'),
    ([],None,{'local_initial':True},0,'Condição inicial local'),
    ([fact(None)],9,{},9,'Excel provisório'),
    ([fact(None)],None,{'local_initial':True},None,'Indisponível'),
    ([fact(-1)],9,{},9,'Excel provisório'),
    ([fact(1.5)],9,{},9,'Excel provisório'),
    ([fact(),fact()],9,{},3,'OCR validado'),
    ([fact(),fact(4)],9,{},9,'Excel provisório'),
    ([fact(),fact(4,child_key='second')],9,{},7,'OCR validado'),
    ([fact(validated=False)],9,{},9,'Excel provisório'),
    ([fact(operation='abocardar')],9,{},9,'Excel provisório'),
    ([fact()],9,{'compatible':False},None,'Indisponível'),
    ([fact(source='mes'),fact(source='original')],9,{},9,'Excel provisório'),
    ([], -1, {}, None, 'Indisponível'),
    ([], 1.5, {}, None, 'Indisponível'),
])
def test_selection_priority_and_complete_coverage(records,macro,flags,expected,origin):
    operation={'operation':'corte','ocr_records':records}
    wanted=select_counter(operation,macro,**flags)
    assert wanted['value']==expected and wanted['origin']==origin
    observed=production_source(operation,macro,**flags)
    for key,value in wanted.items():
        assert (sorted(observed[key]) if key=='coverage_reasons' else observed[key])==value


@pytest.mark.parametrize('warning',[{'ocr_partial':True},{'requires_operation_review':True},
                                  {'coverage_reasons':['Evento não resolvido.']}])
def test_incomplete_known_evidence_cannot_disappear_to_allow_partial_ocr(warning):
    operation={'operation':'corte','ocr_records':[fact()],**warning}
    wanted=select_counter(operation,9)
    assert wanted['value']==9 and wanted['ocr'] is None and wanted['coverage_reasons']
    observed=production_source(operation,9)
    assert observed['value']==wanted['value'] and observed['origin']==wanted['origin']


def test_corte_and_abocardar_choose_independent_sources_and_excess():
    result=calculate({'quantity_required':10,'abocardar':'X'},raw={'Ser.':5,'Aboc.':2},
                     operations=[{'operation':'corte','ocr_records':[fact(12)]}])
    assert result['values']['cut']==12 and result['values']['boc']==2
    assert result['values']['remaining']==0 and result['values']['boc_remaining']==8
    assert result['values']['production_excess']==2
    assert [s['origin'] for s in result['operations']]==['OCR validado','Excel provisório']


@pytest.mark.parametrize('area,counter,falta,values',[
    ('cantoneiras','Maq.','Qtd falta',{'operation':'112'}),
    ('perfis','Ser.','Qtd em Falta',{'abocardar':'-'})])
def test_blank_excel_counter_counts_zero_when_the_sheet_confirms_the_full_balance(area,counter,falta,values):
    # Auditoria 06/10 (A4-01/A4-02/A2-F2): 'Maq.'/'Ser.' vazio com «falta» = QTD era saldo
    # desconhecido no RAW; só a pesquisa de 29/09 o preenchia, e só nas linhas que conhecia.
    base={'quantity_required':10,'length_mm':1000,'stock_length_mm':6000,**values}
    result=calculate(base,area=area,raw={counter:None,falta:10})
    v=result['values']
    assert v['remaining']==10 and v['quantity_to_plan']==10 and v['remaining_m']==10 and v['bars']==2
    assert result['rules']['remaining']['source']=='Excel provisório'
    # Folha contraditória, coluna ausente ou quantidade alterada: continua desconhecido.
    assert calculate(base,area=area,raw={counter:'',falta:7})['values']['remaining'] is None
    assert calculate(base,area=area,raw={falta:10})['values']['remaining'] is None
    assert calculate({**base,'quantity_required':12},area=area,raw={counter:None,falta:10})['values']['remaining'] is None
