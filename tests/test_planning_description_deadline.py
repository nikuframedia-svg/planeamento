"""Description and deadline rules retain the facts needed to explain the result."""
from datetime import date
import pytest
from app.planning_calculations import calculate
from app.raw import contracts,expressions


def test_sparse_description_has_no_empty_prefix_or_invented_dimensions():
    result=calculate({'length_mm':1200,'angle_deg':0},local_initial=True)
    assert result['values']['description']=='Comp. 1200 mm · Ângulo 0°'
    rule=result['rules']['description']
    assert rule['inputs']=={'length_mm':1200,'angle_deg':0}
    assert rule['source']=='LayoutPlaneamentoPerfis.xlsx · Folha1!L2'
    empty=calculate({})
    assert empty['values']['description'] is None and empty['rules']['description']['reason']


def test_local_material_text_and_original_remain_separate():
    result=calculate({'profile':'L50X50X5','grade':'S355','material_description':'Texto local revisto'},
                     area='cantoneiras',raw={'Des. Material':'Texto importado original'})
    assert result['values']['material_description']=='Texto local revisto'
    assert result['values']['original_description']=='Texto importado original'
    assert result['rules']['material_description']['inputs']['original_description']=='Texto importado original'
    assert result['rules']['material_description']['source']=='Dados atuais da peça'


def test_imported_description_changes_with_proposed_geometry_and_restores():
    from app.raw.calculations import recalculate
    values={'component_ref':'P1','profile':'L50X50X5','grade':'S355','length_mm':1000,
            'material_description':'L50X50X5 S355 1000'}
    row={'area':'cantoneiras','plan_key':'imported:1','values':{**values,'length_mm':1001},
         'original':dict(values),'raw':{'Des. Material':'L50X50X5 S355 1000'},
         'calculation':{},'warnings':[]}
    recalculate(row,{},{});
    assert row['values']['material_description']=='L50X50X5 S355'
    assert row['values']['original_description']=='L50X50X5 S355 1000'
    row['values']['length_mm']=1000
    recalculate(row,{},{});
    assert row['values']['material_description']=='L50X50X5 S355 1000'


def test_local_material_description_matches_a_fresh_reconstruction():
    from app.raw.calculations import recalculate
    row={'area':'cantoneiras','need_id':'local','plan_key':None,'sources':[],
         'values':{'profile':'L50X50X5','grade':'S355','length_mm':1000},
         'original':{},'raw':{},'calculation':{},'warnings':[]}
    recalculate(row,{},{});assert row['values']['material_description']=='L50X50X5 S355'
    row['values']['length_mm']=1001
    recalculate(row,{},{});assert row['values']['material_description']=='L50X50X5 S355'


@pytest.mark.parametrize('area,values,raw,expected,overdue',[
 ('perfis',{'quantity_required':100,'abocardar':'-'},{'Ser.':40},'Prazo ultrapassado',True),
 ('perfis',{'quantity_required':100,'abocardar':'X'},{'Ser.':100,'Aboc.':40},'Prazo ultrapassado',True),
 ('perfis',{'quantity_required':100,'abocardar':'X'},{'Ser.':100},'Conclusão por confirmar',None),
 ('perfis',{'quantity_required':100,'abocardar':None},{'Ser.':100,'Aboc.':100},'Conclusão por confirmar',None),
 ('perfis',{'quantity_required':100,'abocardar':'-'},{'Ser.':120},'Trabalho concluído',False),
 ('cantoneiras',{'quantity_required':100,'operation':'119','operation_detail':'0'},{'Maq.':40},'Prazo ultrapassado',True),
 ('cantoneiras',{'quantity_required':100,'operation':'119','operation_detail':'209'},{'Maq.':100},'Conclusão por confirmar',None),
])
def test_deadline_identifies_date_origin_day_and_each_operation(area,values,raw,expected,overdue):
    result=calculate({**values,'expected_date':'2026-09-23','delivery_date':'2026-10-01'},area=area,raw=raw,today=date(2026,9,24))
    assert result['values']['deadline_status']==expected
    assert result['values']['overdue'] is overdue
    for field in ('deadline_status','overdue'):
        inputs=result['rules'][field]['inputs']
        assert inputs['deadline']=='2026-09-23' and inputs['deadline_source']=='expected_date'
        assert inputs['local_date']=='2026-09-24'
        assert set(inputs['operation_balances'])=={r['operation'] for r in result['operations']}
        if overdue is None:assert result['rules']['overdue']['reason']


def test_delivery_fallback_and_same_day_are_not_overdue():
    result=calculate({'quantity_required':10,'abocardar':'-','delivery_date':'2026-09-24'},raw={'Ser.':0},today=date(2026,9,24))
    assert result['values']['overdue'] is False and result['values']['deadline_status']=='Dentro do prazo'
    assert result['rules']['overdue']['inputs']['deadline_source']=='delivery_date'
    result=calculate({'quantity_required':10,'abocardar':'-','expected_date':'invalid','delivery_date':'2026-09-01'},raw={'Ser.':0},today=date(2026,9,24))
    assert result['values']['overdue'] is None and result['values']['deadline_status']=='Sem data'


def test_stock_count_and_static_capacity_units_are_declared():
    fields=contracts.mapping('perfis')
    assert fields['bars']['unit']=='un.'
    result=expressions.compile_ast(expressions.parse('[bars] * [stock_length_mm]',fields),fields)
    assert result.unit=='mm'
    capacities=contracts.mapping('perfis','capacity')
    assert capacities['draft_hours']['unit']=='h'
    assert capacities['reference_equivalent_shifts']['unit']=='turnos'
