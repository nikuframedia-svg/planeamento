"""Independent acceptance examples from the 23 September execution plan."""
import math

import pytest

from app.planning_calculations import calculate, production_source, section


@pytest.mark.parametrize('structured,expected',[(130,130),(0,0),(None,None),('',None),('inválido',None)])
def test_structured_quantity_agrees_with_pdf_source_and_preserves_unknown(structured,expected):
    from app import planning
    from app.dossiers.cpis import _plan_values
    row=dict(row_data={'QTD [un,]':structured,'QTD':62},quantity_planned=62,
             component_ref='A',production_order_no='OF4200',source_line_id='s:43',excel_row=43,
             remaining_valid=False,canonical_remaining=None,cpis_status='Em Aberto',
             cpis_delivery_date=None,closed_x=False,sales_order_no='OV4200',customer_name='Cliente')
    result=planning.line_data(row,'perfis',{})
    assert result['values']['quantity_required']==_plan_values(row)['quantity_required']==expected
    assert row['quantity_planned']==row['row_data']['QTD']==62
    # Cantoneiras has its own QTD input, not the Perfis AH field.
    assert planning.line_data(row,'cantoneiras',{})['values']['quantity_required']==62
    del row['row_data']['QTD [un,]']
    assert planning.line_data(row,'perfis',{})['values']['quantity_required']==62


@pytest.mark.parametrize('original,expected', [('1 543',1543),('1\u00a0543',1543),
    ('1\u202f543,5',1543.5),('12 345 678',12345678),('1 54',None),
    ('1 2',None),('1 543 mm',None),('',None),(None,None)])
def test_cantoneiras_grouped_length_uses_original_cell_without_changing_source(original,expected):
    from app import planning
    row=dict(row_data={'Comp.':original},length_mm=None,quantity_planned=1,
             component_ref='A',production_order_no='OF4200',source_line_id='s:43',excel_row=43,
             remaining_valid=False,canonical_remaining=None,cpis_status=None,
             cpis_delivery_date=None,closed_x=False,sales_order_no=None,customer_name=None)
    value=planning.line_data(row,'cantoneiras',{})['values']['length_mm']
    assert value==expected
    assert row['length_mm'] is None and row['row_data']['Comp.']==original
    if expected is not None:
        # Independent numeric expectation from the single-piece source.
        assert calculate({'quantity_required':1,'length_mm':value},area='cantoneiras')['values']['total_length']==expected


def event(n, record=1, **kw):
    return {'record_id':record,'sheet_uid':str(record),'row_index':0,'quantity':n,'operation':'corte',**kw}


def test_v01_validated_840_recalculates_all_balances_without_closing():
    result=calculate({'quantity_required':840,'length_mm':2750,'material_type':'Tubo redondo',
                      'outer_diameter_mm':76,'thickness_mm':2.6,'abocardar':'-','status':'Em Aberto'},
                     operations=[{'operation':'corte','ocr_records':[event(396,1192),event(444,2037)]}],density=7850)
    v=result['values']
    assert v['cut']==840 and v['cut_pct']==v['final_pct']==100
    assert all(v[k]==0 for k in ('remaining','quantity_to_plan','bars','remaining_m','weight'))
    assert v['total_length']==2310000 and v['status']=='Em Aberto'
    assert result['operations'][0]['origin']=='OCR validado'


def test_v02_layout_properties_and_quantity_changes():
    v=calculate({'quantity_required':48,'length_mm':1200,'material_type':'Varão redondo',
                 'outer_diameter_mm':20,'abocardar':'-'},raw={'Ser.':48})['values']
    assert v['section_unit']==pytest.approx(314.1592653589793)
    assert v['section_total']==pytest.approx(15079.644737231007)
    assert v['total_length']==57600 and v['stock_length_mm']==6000 and v['bars']==0
    for q in (1,5):
        v=calculate({'quantity_required':q,'material_type':'Tubo redondo','outer_diameter_mm':76.1,'thickness_mm':3.25})['values']
        assert v['section_unit']==pytest.approx(743.8113306455535)
        assert v['section_total']==pytest.approx(743.8113306455535*q)


@pytest.mark.parametrize('q,length,stock,bars',[(5,2500,6000,3),(7,2001,6000,4),(1,6000,None,1),
 (1,6001,None,1),(1,12000,None,1),(1,12001,None,None),(0,12001,None,0),(5,2500,12000,2)])
def test_bar_fit_not_total_length_approximation(q,length,stock,bars):
    r=calculate({'quantity_required':q,'length_mm':length,'stock_length_mm':stock},local_initial=True)
    assert r['values']['bars']==bars
    if bars is None:assert r['rules']['bars']['reason']=='A peça não cabe no perfil inteiro.'


@pytest.mark.parametrize('mark,final,balance',[('X',59.6,202),('-',63,0),(None,None,202)])
def test_v03_cut_and_boc_are_separate(mark,final,balance):
    v=calculate({'quantity_required':500,'abocardar':mark},raw={'Ser.':315,'Aboc.':298})['values']
    assert v['cut_pct']==63 and v['final_pct']==final
    assert v['remaining']==185 and v['boc_remaining']==balance


def test_v04_exact_weight_and_second_operation():
    r=calculate({'quantity_required':100,'length_mm':2000,'profile':'L TEST','operation':'119','operation_detail':'209'},
        area='cantoneiras',weights={'l test':[{'kg_m':3,'cell':'C9'}]},
        operations=[{'operation':'119','ocr_records':[event(40,operation='119')]},
                    {'operation':'209','ocr_records':[event(15,2,operation='209')]}])
    v=r['values']
    assert (v['made'],v['remaining'],v['made_pct'])==(40,60,40)
    assert (v['total_m'],v['remaining_m'],v['weight_unit'],v['weight'])==(200,120,6,360)
    assert v['secondary_remaining']==85
    assert v['ocr_op_119']==40 and v['ocr_op_209']==15


def test_production_source_policy_and_duplicate_events():
    op={'operation':'corte','ocr_records':[event(4),event(4)]}
    assert production_source(op,100)['value']==4
    assert production_source(op,100)['difference']==-96
    assert production_source({},3)['origin']=='Excel provisório'
    assert production_source({},local_initial=True)['value']==0
    assert production_source({})['value'] is None
    op['ocr_records'].append(event(None,2))
    assert production_source(op,8)['value']==8
    assert production_source(op,8)['ocr'] is None
    assert production_source(op,local_initial=True)['value'] is None
    assert production_source({'ocr_records':[event(1),event(2)]},9)['origin']=='Excel provisório'


def test_cross_source_conflicts_cannot_be_summed():
    op={'operation':'corte','ocr_records':[event(5,source='mes'),event(5,source='original')]}
    assert production_source(op,7)['value']==7
    assert 'Sobreposição' in production_source(op)['reason']


@pytest.mark.parametrize('family,dims,expected',[
 ('Tubo quadrado',{'width_mm':10,'thickness_mm':1},36),
 ('Tubo retangular',{'width_mm':10,'height_mm':20,'thickness_mm':1},56),
 ('Calha',{'width_mm':10,'height_mm':20,'thickness_mm':1},38),
 ('Cantoneira',{'width_mm':10,'height_mm':20,'thickness_mm':1},29),
 ('Chapa',{'width_mm':10,'thickness_mm':2},20),
 ('Barra',{'width_mm':10,'height_mm':2},20),
 ('Varão nervurado',{'outer_diameter_mm':20},100*math.pi),
])
def test_vba_geometry_families(family,dims,expected):
    assert section({'material_type':family,**dims})[0]==pytest.approx(expected)


def test_catalog_is_exact_and_ambiguous_properties_stay_unknown():
    v={'material_type':'Perfil U','profile':'UPN65x42'}
    assert section(v,{('perfil u','upn65x42'):[{'area':903}]})[0]==903
    assert section(v,{('perfil u','upn65x42'):[{'area':903},{'area':999}]})[0] is None
    assert section({**v,'profile':'UPN65x43'},{('perfil u','upn65x42'):[{'area':903}]})[0] is None


def test_iso_year_zero_and_unknowns_are_not_invented():
    v=calculate({'quantity_required':0,'expected_date':'2027-01-01'},local_initial=True)['values']
    assert v['expected_week']=='2026-W53' and v['cut_pct'] is None
    assert calculate({'quantity_required':10})['values']['remaining'] is None
    assert calculate({'quantity_required':-1})['values']['quantity_required'] is None
    v=calculate({'quantity_required':5,'abocardar':'-'},raw={'Ser.':7})['values']
    assert v['final_pct']==140 and v['remaining']==0 and v['production_excess']==2


@pytest.mark.parametrize('area,primary', [('perfis','corte'), ('cantoneiras','119')])
def test_missing_production_reason_reaches_dependent_results(area, primary):
    r=calculate({'quantity_required':10,'length_mm':1000,'abocardar':'-',
                 'operation':primary,'material_type':'Varão redondo','outer_diameter_mm':20,
                 'profile':'L TEST'},area=area,density=7850,
                weights={'l test':[{'kg_m':3}]})
    source_reason=r['rules']['cut' if area=='perfis' else 'made']['reason']
    assert 'Sem produção OCR' in source_reason
    for field in ('remaining','quantity_to_plan','remaining_m','bars','weight',
                  'cut_pct' if area=='perfis' else 'made_pct'):
        assert r['values'][field] is None
        assert r['rules'][field]['reason']==source_reason,field
    if area=='perfis':
        assert r['rules']['final_pct']['reason']==source_reason
        assert r['rules']['boc_pct']['reason']=='Operação não necessária.'
        assert r['values']['boc_remaining']==0
        assert r['rules']['boc_remaining']['reason'] is None


def test_unavailable_reasons_distinguish_quantity_length_property_and_zero():
    missing_q=calculate({'length_mm':1000,'abocardar':'-'},raw={'Ser.':5})
    for field in ('remaining','quantity_to_plan','production_excess','cut_pct','total_length'):
        assert 'Quantidade necessária' in missing_q['rules'][field]['reason']
    missing_length=calculate({'quantity_required':10,'abocardar':'-'},raw={'Ser.':5})
    for field in ('total_length','total_m','remaining_m','stock_length_mm','bars'):
        assert 'Comprimento da peça' in missing_length['rules'][field]['reason']
    assert 'propriedade exata' in missing_length['rules']['section_total']['reason']
    zero=calculate({'quantity_required':0,'abocardar':'-'},local_initial=True)
    assert zero['rules']['cut_pct']['reason']=='Quantidade necessária zero.'
    for field in ('remaining','remaining_m','bars'):
        assert zero['values'][field]==0 and zero['rules'][field]['reason'] is None
    # Every unknown derived result in these independent failure scenarios is
    # explained by the missing input, rather than a generic catch-all message.
    for result in (missing_q,missing_length,zero):
        assert all(rule['reason'] and rule['reason']!='Entradas necessárias desconhecidas.'
                   for field,rule in result['rules'].items() if result['values'][field] is None)


def test_cantoneiras_operation_requires_piece_evidence_not_machine():
    from app.planning_production import operation_for_record, operations_for_line, attach_operation_evidence
    line={'source_app':'kanban-mes','plan_key':'piece1','quantity_planned':100,'quantity_made':10,
          'operation_inputs':{'1ª Oper.':119,'2ª Oper.':0}}
    record={'id':1,'sheet_uid':'s1','row_index':0,'source_app':'kanban-mes','machine':'Ficep',
            'association_status':'technical_unique','resolved_plan_keys':['piece1'],
            'resolved_plan_refs':[{'plan_key':'piece1','assumed_quantity':40}]}
    assert operation_for_record(record)=='operacao_por_confirmar'
    attach_operation_evidence([line],[record])
    assert record['operation']=='119'
    assert record['operation_basis']['kind']=='sole_piece_operation'
    assert line['operations'][0]['ocr_quantity']==40
    assert len(operations_for_line(line))==1
    line['operation_inputs']['2ª Oper.']=209
    attach_operation_evidence([line],[record])
    assert record['operation']=='operacao_por_confirmar'
    assert all(op['ocr_quantity'] is None and op['coverage_reasons'] for op in line['operations'])


def test_perfis_new_template_machines_count_as_cut():
    # A12-F1: os modelos de 22/09 (TPL290-294) usam nomes curtos sem «Serrote».
    from app.planning_production import operation_for_record
    for machine in ('DISCO PAV1','FITA PAV1','DOALL PAV1','MEBA','Serrote Disco pav 1',
                    'Serrote Fita Thomas IS639 Pav.1','Vanguard'):
        assert operation_for_record({'source_app':'kanban-mes-mtg2','machine':machine})=='corte',machine
    for machine in ('MAQ. ABOCARDAR','Abocardar'):
        assert operation_for_record({'source_app':'kanban-mes-mtg2','machine':machine})=='abocardar'
    assert operation_for_record({'source_app':'kanban-mes-mtg2','machine':'Posto X'})=='operacao_por_confirmar'


def test_cantoneiras_full_bar_child_with_second_operation_keeps_siblings():
    # A12-F3: num registo de barra completa, a regra «única operação da peça»
    # aplica-se a cada filho. Um filho com 2.ª operação fica por confirmar,
    # mas não tira a produção aos irmãos de uma só operação.
    from app.planning_production import operation_for_record, attach_operation_evidence
    def line(key,first,second=0):
        return {'source_app':'kanban-mes','plan_key':key,'quantity_planned':4,'quantity_made':None,
                'operation_inputs':{'1ª Oper.':first,'2ª Oper.':second}}
    lines=[line('a','112'),line('b','112','111'),line('c','119')]
    record={'id':4268,'sheet_uid':'s','row_index':0,'source_app':'kanban-mes','machine':'Ficep Rapid 25T',
            'full_profile':True,'association_status':'technical_unique','resolved_plan_keys':['a','b','c'],
            'resolved_plan_refs':[{'plan_key':k,'assumed_quantity':4} for k in 'abc']}
    attach_operation_evidence(lines,[record])
    assert record['operation']=='operacao_por_confirmar'
    assert record['operation_by_plan_key']=={'a':'112','c':'119'}
    a,b,c=(x['operations'] for x in lines)
    assert a[0]['operation']=='112' and a[0]['ocr_quantity']==4 and not a[0]['coverage_reasons']
    assert c[0]['operation']=='119' and c[0]['ocr_quantity']==4
    assert a[0]['ocr_records'][0]['operation']=='112'
    # A peça com 1.ª e 2.ª operação continua a precisar de evidência própria.
    assert all(op['ocr_quantity'] is None for op in b)
    assert b[0]['coverage_reasons']==['Registo 4268: identidade ou operação por confirmar.']
    # Registo de uma só peça mantém a regra antiga, sem mapa por filho.
    single={'id':5,'source_app':'kanban-mes','association_status':'technical_unique','resolved_plan_keys':['b']}
    assert operation_for_record(single,lines)=='operacao_por_confirmar' and 'operation_by_plan_key' not in single
    # Quando todos os filhos concordam, o registo inteiro tem a operação.
    record['resolved_plan_keys']=['a'];lines[0]['operations']=None
    assert operation_for_record(record,lines)=='112' and 'operation_by_plan_key' not in record


def test_known_ambiguous_event_prevents_partial_total_becoming_complete():
    from app.planning_production import attach_operation_evidence
    line={'source_app':'kanban-mes-mtg2','plan_key':'p','operation_inputs':{'Ser.':20,'Aborc.':'-'},'quantity_planned':100}
    records=[{'id':1,'sheet_uid':'s','row_index':0,'source_app':'kanban-mes-mtg2','machine':'MEBA',
              'association_status':'explicit','resolved_plan_keys':['p'],
              'resolved_plan_refs':[{'plan_key':'p','assumed_quantity':10}]},
             {'id':2,'source_app':'kanban-mes-mtg2','machine':'MEBA','association_status':'ambiguous','association_candidates':['p','other']}]
    attach_operation_evidence([line],records)
    op=line['operations'][0]
    assert op['ocr_quantity'] is None
    assert production_source(op,20)['origin']=='Excel provisório'
