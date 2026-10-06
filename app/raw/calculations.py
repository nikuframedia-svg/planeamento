"""Auditable derived geometry/weights. Catalog matches are exact, never approximate Excel lookups."""
from collections import defaultdict
from datetime import date,datetime
from zoneinfo import ZoneInfo
from .. import planning,planning_raw as raw,planning_needs as needs,planning_catalogs as catalogs,planning_dates


def sections(conn, snapshot):
    """Exact properties from the same B:C table used by Planeamento!AP."""
    result=defaultdict(list)
    for row in conn.execute("SELECT excel_row,row_data FROM raw_mtg.other_sheet_rows WHERE snapshot_id=%s AND sheet_name='AreaSecaoCorte' ORDER BY excel_row",(snapshot,)).fetchall():
        cells=row['row_data'].get('values',[])
        if row['excel_row']<3 or len(cells)<3:continue
        value=raw.number(cells[2])
        if value is not None and value>0 and cells[1]:
            result[(catalogs.key(cells[0]),catalogs.key(cells[1]))].append({'area':value,'snapshot':snapshot,'sheet':'AreaSecaoCorte','cell':'C'+str(row['excel_row'])})
    return result


def recalculate(row, section_table, weight_table):
    """Resolve operation sources before all derivatives, on one row revision."""
    from ..planning_calculations import calculate
    v=row['values'];original=row['original']
    compatible=not row.get('plan_key') or needs.signature(v)==needs.signature(original)
    if row['area']=='cantoneiras':
        # The imported description describes the imported geometry. Apply the
        # same choice in previews and saved projections when that identity
        # changes, while preserving the original text as separate evidence.
        imported=planning._text(row['raw'].get('Des. Material'))
        v['material_description']=(imported if compatible else None) or ' '.join(str(v.get(k) or '') for k in ('profile','grade')).strip()
    operations=row.get('operations',[])
    manual_quantity=('quantity_to_plan' in row.get('input_values',{}))
    declared_quantity=v.get('quantity_to_plan')
    # «Nada produzido ainda» vale para qualquer peça sem linha do Excel, também a que veio de um PDF
    # (07/10/2026); antes só a peça escrita à mão, e a do PDF ficava sem saldo.
    excel=row.get('plan_key') or any(s.get('kind')=='plan_line' for s in row.get('sources') or [])
    result=calculate(v,area=row['area'],raw=row['raw'],operations=operations,
        local_initial=bool(row.get('need_id') and not excel),
        compatible=compatible,sections=section_table,weights=weight_table,
        today=datetime.now(ZoneInfo(planning.settings.display_timezone)).date(),
        density=7850 if row['area']=='perfis' and row.get('plan_key') else None,
        declared_remaining=v.get('remaining_declared'))  # «Qtd em falta»: só o registo manual a guarda
    row['values']=result['values']
    if manual_quantity:
        row['values']['quantity_to_plan']=declared_quantity
        result['rules']['quantity_to_plan']={'formula':'Quantidade declarada','unit':'un.','source':'Registo manual','inputs':{'quantity_to_plan':declared_quantity}}
    row['calculation'].update(contract=result['contract'],rules=result['rules'],production_sources=result['operations'],compatible=compatible)
    for source in result['operations']:
        row['warnings'].extend(source['coverage_reasons'])
        if source['excess'] is not None and source['excess']>0:row['warnings'].append('Produção superior à quantidade necessária.')
    row['warnings']=list(dict.fromkeys(row['warnings']))
    return row


def weights(conn,snapshot):
    result=defaultdict(list)
    rows=conn.execute("SELECT excel_row,row_data FROM raw_mtg.other_sheet_rows WHERE snapshot_id=%s AND sheet_name='Tabela pesos' ORDER BY excel_row",(snapshot,)).fetchall()
    for r in rows:
        cells=r['row_data'].get('values',[])
        if len(cells)<3 or not cells[1]:continue
        n=raw.number(cells[2])
        if n is not None and n>0:result[catalogs.key(cells[1])].append({'kg_m':n,'snapshot':snapshot,'sheet':'Tabela pesos','row':r['excel_row'],'designation':cells[1]})
    return result


def enrich(values,original,source,weight_table,area):
    v=values;rules={};q=raw.number(v.get('quantity_required'));length=raw.number(v.get('length_mm'));planned=raw.number(v.get('quantity_to_plan'))
    geometry_compatible=needs.signature(v)==needs.signature(original)
    # A quantity edit alone does not invalidate a proven unit property.
    unit=raw.number(source.get('Área de Seção de Corte Unit. [mm2]')) if geometry_compatible else None
    if unit is not None and unit>0:
        v['section_unit']=unit
        v['section_total']=unit*q if q is not None else None
        rules['section_total']={'formula':'section_unit × quantity_required','unit':'mm²','inputs':{'section_unit':unit,'quantity_required':q},'source':'Área de Seção de Corte Unit. [mm2]'}
    candidates=weight_table.get(catalogs.key(v.get('profile')),[])
    rates={x['kg_m'] for x in candidates}
    if len(rates)==1 and length is not None and length>0:
        kg_m=next(iter(rates));v['weight_unit']=kg_m*length/1000
        if planned is not None:v['weight']=v['weight_unit']*planned
        rules['weight']={'formula':'kg_m × length_mm / 1000 × quantity_to_plan','unit':'kg','inputs':{'kg_m':kg_m,'length_mm':length,'quantity_to_plan':planned},'sources':candidates}
    elif len(rates)>1:
        v['weight_unit']=None;v['weight']=None;rules['weight']={'error':'Designação com pesos unitários divergentes na tabela de origem.'}
    if length is not None and q is not None:rules['total_length']={'formula':'quantity_required × length_mm','unit':'mm','inputs':{'quantity_required':q,'length_mm':length}}
    if v.get('remaining_m') is not None:rules['remaining_m']={'formula':'remaining × length_mm / 1000','unit':'m','inputs':{'remaining':v.get('remaining'),'length_mm':length}}
    if v.get('bars') is not None:rules['bars']={'formula':'ceil(remaining / floor(stock_length_mm / length_mm))','inputs':{k:v.get(k) for k in ('remaining','stock_length_mm','length_mm')},'limitations':['Não considera perdas de corte nem confirma stock.']}
    for key,numerator in [('cut_pct','cut'),('boc_pct','boc'),('made_pct','made')]:
        if v.get(key) is not None:rules[key]={'formula':numerator+' / quantity_required × 100','unit':'%','inputs':{numerator:v.get(numerator),'quantity_required':q},'source':'Acumulado importado da macro; OCR separado.'}
    if v.get('final_pct') is not None:rules['final_pct']={'formula':'boc_pct' if v.get('abocardar')=='X' else 'cut_pct','unit':'%','inputs':{'abocardar':v.get('abocardar')},'limitations':['Percentagem da operação final; não fecha a OF.']}
    if v.get('theoretical_hours') is not None:rules['theoretical_hours']={'formula':'remaining_m / speed_m_h','unit':'h','inputs':{'remaining_m':v.get('remaining_m'),'speed_m_h':v.get('speed_m_h')},'source':'Velocidade importada; conferir vigência antes de usar na capacidade.'}
    today=datetime.now(ZoneInfo(planning.settings.display_timezone)).date()
    picking=(planning_dates.picking_deadline(v.get('picking_week'),v.get('picking_year'),anchor=v.get('cut_date') or today)
             if area=='perfis' and not v.get('picking_conflict') else None)
    deadline=(picking['at'] if picking else None) or v.get('expected_date') or (
        v.get('cut_date') if area=='perfis' else None) or v.get('planned_finish_date') or v.get('delivery_date')
    try:past=date.fromisoformat(str(deadline)[:10])<today
    except ValueError:past=False
    balances=[v.get('remaining')]
    if area=='perfis' and v.get('abocardar')=='X':balances.append(v.get('boc_remaining'))
    pending=any(x is None or x>0 for x in balances)
    v['deadline_status']='Prazo ultrapassado — conclusão por confirmar' if past and pending else 'Sem data' if not deadline else 'Consultar por operação'
    v['overdue']=past and pending
    return rules
