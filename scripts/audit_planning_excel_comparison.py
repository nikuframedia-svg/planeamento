"""C04.2: attach actual Excel cells/caches to the independent population audit.

Read-only on the isolated database. Expectations come from the independently
recalculated ledger, whose checksum and publication versions are checked. This
does not treat every Excel difference as acceptable: unresolved differences are
retained in full, with a nonzero exit status, for investigation.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re

from scripts.audit_planning_formula_population import FOLDER, area_expected, equal, number, normalized, sheets


# Physical columns in the original workbooks, not labels of the new RAW.
COLUMNS = {
    'perfis': {
        'cut_pct': ('Y',), 'boc_pct': ('Z',), 'remaining': ('CD',),
        'quantity_to_plan': ('AS',), 'section_unit': ('AX',),
        'section_total': ('AP',), 'section_pending': ('AY',), 'total_length': ('BR',), 'total_m': ('BR',),
        'stock_length_mm': ('BS',), 'bars': ('BT',), 'weight': ('DB',),
        'expected_week': ('AV', 'AW'),
    },
    'cantoneiras': {
        'remaining': ('AG',), 'quantity_to_plan': ('AG',),
        'total_length': ('AM',), 'total_m': ('AM',), 'remaining_m': ('BK',),
        'weight_unit': ('AP',), 'weight': ('AS',), 'expected_week': ('B',),
    },
}
LAYOUT = {
    'cut_pct': 'R2', 'boc_pct': 'S2', 'final_pct': 'T2',
    'remaining': 'U2', 'boc_remaining': 'V2', 'section_total': 'AF2',
    'quantity_to_plan': 'AI2', 'expected_week': 'AK2', 'weight': 'AL2',
    'total_length': 'AN2', 'stock_length_mm': 'AO2', 'bars': 'AP2',
}
BOOKS = {
    'perfis': ('Met2_Plan_Perfis', 'Planeamento'),
    'cantoneiras': ('Met3_Plan_Cantoneiras', 'Plan_ produção'),
}
PERFIS_INPUTS = ('AH', 'N', 'V', 'W', 'T', 'AM', 'AR', 'Q',
                 'AF', 'AG', 'AI', 'AJ', 'AK', 'AL', 'AN', 'AO')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cells_for_area(area):
    stem, sheet = BOOKS[area]
    wanted = {col for columns in COLUMNS[area].values() for col in columns}
    # Inputs needed to diagnose a difference; copied unchanged to evidence.
    wanted.update(PERFIS_INPUTS if area == 'perfis'
                  else ('O', 'AA', 'R', 'Q', 'AH', 'AP', 'BJ'))
    rows = defaultdict(dict)
    path = FOLDER / (stem + '-cells.jsonl.gz')
    with gzip.open(path, 'rt') as stream:
        for line in stream:
            item = json.loads(line)
            if item['sheet'] != sheet:
                continue
            col, row = re.fullmatch(r'([A-Z]+)(\d+)', item['cell']).groups()
            if col in wanted and int(row) > 6:
                rows[int(row)][col] = item
    return rows, {'file': path.name, 'sha256': sha(path)}


def cached_value(area, field, cells):
    """Only unit conversion; never recalculate or silently repair the cache."""
    columns = COLUMNS[area].get(field, ())
    if not columns:
        return None, 'no_corresponding_macro_column'
    if not all(col in cells for col in columns):
        return None, 'cell_not_stored'
    if field == 'expected_week':
        if area == 'cantoneiras':
            return None, 'week_without_year'
        week, year = [number(cells[col]['value']) for col in columns]
        if week is None or year is None:
            return None, 'blank_or_error'
        return f'{int(year)}-W{int(week):02}', 'cached_year_and_week'
    cell = cells[columns[0]]
    # Perfis Y/Z explicitly emit the string X when the percentage equals 100.
    # Retain the literal in source_cells, while comparing its numeric meaning.
    if (area == 'perfis' and field in ('cut_pct', 'boc_pct')
            and str(cell['value']).strip().upper() == 'X'
            and re.search(r'=\s*100\s*,\s*"X"', cell.get('formula') or '', re.I)):
        return 100.0, 'excel_X_means_100_percent'
    value = number(cells[columns[0]]['value'])
    if value is None:
        return None, 'blank_or_error'
    if area == 'cantoneiras' and field == 'total_length':
        value *= 1000  # AM is metres; RAW contract is millimetres.
    if area == 'perfis' and field == 'total_m':
        value /= 1000  # BR is millimetres.
    return value, 'numeric_cache'


def unknown_source_difference(area, field, observed, values, cells):
    """Explain only a directly evidenced empty production cell, not any
    arbitrary OCR/macro difference. Source selection remains a separate gate.
    """
    if observed is not None:
        return None
    primary = ('cut', 'V') if area == 'perfis' else ('made', 'AA')
    dependent = {'remaining','quantity_to_plan','cut_pct','made_pct','remaining_m','bars','weight','section_pending'}
    if field in dependent:
        selected, column = primary
        raw = cells.get(column, {}).get('value')
        if values.get(selected) is None and (raw is None or str(raw).strip() == ''):
            return {'classification':'intentional_unknown_production',
                    'plan_rule':'§2 / §4.5: unknown production is not zero; dependent balances remain unknown',
                    'original_counter_cell':column, 'original_counter_value':raw,
                    'selected_counter':selected, 'selected_counter_value':None}
    return None


def weight_catalogue():
    rows = sheets('Met3_Plan_Cantoneiras', {'Tabela pesos'})['Tabela pesos']
    result = defaultdict(list)
    for row, cells in rows.items():
        if row < 3:
            continue
        name = cells.get('B', {}).get('value')
        if not name:
            continue
        result[normalized(name)].append({'designation': cells['B'],
            'property': cells.get('C', {'cell': f'C{row}', 'not_stored': True}),
            'kg_m': number(cells.get('C', {}).get('value'))})
    return result


def original_number(value):
    text = str(value if value is not None else '').strip()
    if re.fullmatch(r'\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d+)?', text):
        text = re.sub(r'[ \u00a0\u202f]', '', text)
    return number(text)


def exact_weight_difference(check, values, cells, catalogue):
    """Prove a weight discrepancy using the complete original B:C table.

    Identity and length must still match the original cells. A mere VLOOKUP
    formula or a changed selected quantity never automatically excuses a
    difference. The previous implied property is traced to actual other rows.
    """
    field = check['field']
    if field not in ('weight_unit', 'weight'):
        return None
    name = normalized(cells.get('Q', {}).get('value'))
    length = original_number(cells.get('R', {}).get('value'))
    if not name or name != normalized(values.get('profile')) or not length or length <= 0 or not equal(length, values.get('length_mm')):
        return None
    entries = catalogue.get(name, [])
    rates = {r['kg_m'] for r in entries if r['kg_m'] is not None and r['kg_m'] > 0}
    unit = next(iter(rates)) * length / 1000 if len(rates) == 1 else None
    if not equal(unit, values.get('weight_unit')):
        return None
    if field == 'weight_unit' and not equal(unit, check['observed']):
        return None
    evidence = {'plan_rule':'G08/G09: exact designation; no approximate property; dependent weight requires resolved unit property',
                'original_designation': cells['Q'], 'original_length': cells['R'],
                'exact_table_entries': entries, 'independent_unit_weight': unit}
    if not rates and check['observed'] is None:
        return {**evidence, 'classification':'intentional_missing_exact_weight'}
    if len(rates) > 1 and check['observed'] is None:
        return {**evidence, 'classification':'intentional_ambiguous_exact_weight'}
    cached_unit = number(cells.get('AP', {}).get('value'))
    formula = cells.get('AP', {}).get('formula') or ''
    if cached_unit is None or unit is None or equal(cached_unit, unit) or not re.search(r'VLOOKUP\(.*?,\s*2\s*,\s*5\s*\)', formula, re.I):
        return None
    implied = cached_unit / (length / 1000)
    wrong_entries = [r for key, rows in catalogue.items() if key != name
                     for r in rows if r['kg_m'] is not None and equal(r['kg_m'], implied)]
    if not wrong_entries:
        return None
    if field == 'weight':
        quantity = number(cells.get('O', {}).get('value'))
        production = number(cells.get('AA', {}).get('value'))
        if quantity is None or production is None or not equal(quantity, values.get('quantity_required')) or not equal(production, values.get('made')):
            return None
        old = number(cells.get('AS', {}).get('value'))
        if not equal(old, (quantity-production)*cached_unit) or not equal(check['observed'], max(quantity-production,0)*unit):
            return None
    return {**evidence, 'classification':'intentional_exact_weight_lookup',
            'original_lookup':cells['AP'], 'original_implied_kg_m':implied,
            'other_designations_with_that_property':wrong_entries}


def empty_input_difference(area, field, observed, values, cells):
    if area != 'cantoneiras' or observed is not None:
        return None
    if (field == 'weight_unit' and not normalized(cells.get('Q', {}).get('value'))
            and not normalized(values.get('profile'))
            and number(cells.get('AP', {}).get('value')) == 0
            and re.search(r'IF\(Q\d+\s*=\s*""\s*,\s*0\s*,', cells.get('AP', {}).get('formula') or '', re.I)):
        return {'classification':'intentional_unknown_profile',
                'plan_rule':'G08 / §4.5: an empty designation has no exact property; unknown is not zero',
                'original_profile':cells.get('Q'), 'original_zero_formula':cells['AP']}
    if (field in ('total_length','total_m') and values.get('quantity_required') is None
            and values.get('length_mm') is None
            and all(cells.get(col, {}).get('value') in (None, '') for col in ('O','R'))
            and number(cells.get('AM', {}).get('value')) == 0):
        return {'classification':'intentional_unknown_quantity_and_length',
                'plan_rule':'G04 / §4.5: Q and L are both missing; Excel treats empty cells as zero',
                'original_quantity':cells.get('O'), 'original_length':cells.get('R')}
    return None


def compact_formula(cell):
    return re.sub(r'\s+', '', cell.get('formula') or '').upper()


def structured_quantity_difference(check, values, cells):
    """Trace both totals to their literal input cells; AH supersedes legacy N."""
    field=check['field']
    if field not in ('total_length', 'total_m','remaining','cut_pct','bars'):
        return None
    old_q, q, old_l, length = [original_number(cells.get(k, {}).get('value'))
                              for k in ('N', 'AH', 'Q', 'AM')]
    if (None in (old_q, q, old_l, length) or min(old_q, q) < 0 or length <= 0
            or not old_q.is_integer() or not q.is_integer() or equal(old_q, q)
            or not equal(old_l, length) or not equal(q, values.get('quantity_required'))
            or not equal(length, values.get('length_mm'))):
        return None
    row = re.search(r'\d+$', cells['AH']['cell']).group()
    if field in ('remaining','cut_pct','bars'):
        production=original_number(cells.get('V',{}).get('value'))
        if production is None or production<0 or not production.is_integer() or not equal(production,values.get('cut')):
            return None
        old,new=old_q-production,max(q-production,0)
        if field=='cut_pct':
            if not old_q or not q or compact_formula(cells.get('Y',{}))!=f'IF((V{row}/VALUE($N{row}))*100=100,"X",((V{row}/VALUE($N{row})))*100)':return None
            old,new=100*production/old_q,100*production/q
        else:
            if compact_formula(cells.get('CD',{}))!=f'N{row}-V{row}' or not equal(number(cells.get('CD',{}).get('value')),old):return None
            if field=='bars':
                stock=original_number(cells.get('BS',{}).get('value'))
                if not stock or stock<length or not equal(stock,values.get('stock_length_mm')) or compact_formula(cells.get('BT',{}))!=f'ROUNDUP(CD{row}/(ROUNDDOWN((BS{row}/Q{row}),0)),0)':return None
                fit=math.floor(stock/length);old=math.copysign(math.ceil(abs(old)/fit),old);new=math.ceil(new/fit)
        if not equal(cached_value('perfis',field,cells)[0],old) or not equal(check['observed'],new):return None
        return {'classification':'intentional_structured_quantity','plan_rule':'F04/F07/F18: structured AH quantity replaces legacy N; selected production remains identical',
                'original_inputs':{k:cells.get(k) for k in ('N','AH','V','Q','AM','BS')},'original_result':cells[COLUMNS['perfis'][field][0]],
                'independent_original_result':old,'independent_current_result':new}
    if compact_formula(cells.get('BR', {})) != f'N{row}*Q{row}':
        return None
    divisor = 1000 if check['field'] == 'total_m' else 1
    if (not equal(number(cells.get('BR', {}).get('value')), old_q * old_l)
            or not equal(check['observed'], q * length / divisor)):
        return None
    return {'classification': 'intentional_structured_quantity',
            'plan_rule': 'F16: Q × L using the structured quantity AH; retain N as imported evidence',
            'original_inputs': {k: cells[k] for k in ('N', 'AH', 'Q', 'AM')},
            'original_total': cells['BR'], 'independent_original_total_mm': old_q * old_l,
            'independent_current_total_mm': q * length}


def section_catalogue():
    result = defaultdict(list)
    for row, cells in sheets('Met2_Plan_Perfis', {'AreaSecaoCorte'})['AreaSecaoCorte'].items():
        value = number(cells.get('C', {}).get('value'))
        if row >= 3 and value is not None and value > 0:
            key = (normalized(cells.get('A', {}).get('value')), normalized(cells.get('B', {}).get('value')))
            result[key].append({'cell': f'C{row}', 'value': value,
                                'source_cells': {k: cells.get(k) for k in ('A', 'B', 'C')}})
    return result


def original_section(values, cells, catalogue):
    columns = {'material_type': 'AF', 'profile': 'AG', 'outer_diameter_mm': 'AI',
               'width_mm': 'AJ', 'height_mm': 'AK', 'thickness_mm': 'AL'}
    original = {k: cells.get(col, {}).get('value') for k, col in columns.items()}
    prop, source = area_expected(original, catalogue)
    for k, v in original.items():
        # Geometric families often compose a profile name from their dimensions;
        # AG is not an input to their VBA formula. It IS required for a lookup.
        if k == 'profile' and source['kind'] == 'VBA':
            continue
        if k in ('material_type', 'profile'):
            if normalized(v) != normalized(values.get(k)):
                return None
        elif not equal(number(v), number(values.get(k))):
            return None
    return prop, source, {col: cells.get(col) for col in columns.values()}


def section_difference(check, values, cells, catalogue):
    """Unit property does not depend on Q; unresolved exact properties are unknown.

    Every geometric/catalogue input is checked against the original workbook.
    This is deliberately independent of application section or rule outputs.
    """
    field = check['field']
    if field not in ('section_unit', 'section_total'):
        return None
    resolved = original_section(values, cells, catalogue)
    if resolved is None:
        return None
    prop, source, source_cells = resolved
    q = number(cells.get('AH', {}).get('value'))
    if not equal(q, values.get('quantity_required')) or not equal(prop, values.get('section_unit')):
        return None
    expected = prop if field == 'section_unit' else prop * q if prop is not None and q is not None else None
    if not equal(check['observed'], expected):
        return None
    ax, ap = cells.get('AX', {}), cells.get('AP', {})
    row = re.search(r'\d+$', cells['AF']['cell']).group() if cells.get('AF', {}).get('cell') else None
    if row is None:
        return None
    canonical_division = compact_formula(ax) == f'IFERROR(IF(AH{row}="","",AP{row}/AH{row}),0)'
    evidence = {'plan_rule': 'F09/F10: unit property from geometry or exact catalogue, independent of quantity; unknown property is not zero',
                'original_inputs': {**source_cells, 'AH': cells.get('AH')},
                'independent_unit_area': prop, 'property_source': source,
                'original_unit': ax, 'original_total': ap}
    if field == 'section_unit' and prop is not None and prop > 0 and canonical_division:
        if q == 0 and number(ap.get('value')) == 0 and number(ax.get('value')) == 0:
            return {**evidence, 'classification': 'intentional_unit_property_at_zero_quantity'}
        if q is None and cells.get('AH', {}).get('value') in (None, '') and ax.get('value') in (None, ''):
            return {**evidence, 'classification': 'intentional_unit_property_without_quantity'}
    if (prop is None and source['kind'] == 'exact_lookup' and expected is None
            and number(ap.get('value')) == 0 and f'XLOOKUP(AG{row},AREASECAOCORTE!' in compact_formula(ap)
            and f'IF(AF{row}="","",0)' in compact_formula(ap)
            and (field == 'section_total' or (canonical_division and number(ax.get('value')) == 0))):
        return {**evidence, 'classification': 'intentional_unresolved_exact_section'}
    if prop is None and source['kind']=='VBA':
        legacy=legacy_geometric_section(cells,row)
        if (legacy is not None and q is not None and q>=0
                and equal(number(ap.get('value')),legacy*q)
                and (field=='section_total' or (canonical_division and q>0 and equal(number(ax.get('value')),legacy)))):
            return {**evidence,'classification':'intentional_invalid_or_missing_geometry',
                    'plan_rule':'F09/F10: dimensions must be sufficient and physically valid; blank thickness is not a zero-area material',
                    'excel_geometric_area':legacy,'excel_total_area':legacy*q}
    if (field=='section_total' and q is None and cells.get('AH',{}).get('value') in (None,'')
            and prop is not None and number(ap.get('value'))==0 and f'*AH{row},"")' in compact_formula(ap)):
        return {**evidence,'classification':'intentional_unknown_section_quantity',
                'plan_rule':'F10: required quantity is unknown; missing quantity is not zero'}
    return None


def legacy_geometric_section(cells,row):
    """Reconstruct the unguarded VBA arithmetic, only for its literal branch.

    This is NOT the current property: empty VBA arguments are evaluated as zero
    to explain the original cache, while physical validity is checked separately.
    """
    def dimension(col):
        value=cells.get(col,{}).get('value')
        return 0 if value in (None,'') else number(value)
    d,w,h,t=[dimension(col) for col in ('AI','AJ','AK','AL')]
    if any(v is None or v<0 for v in (d,w,h,t)):return None
    functions={
        'tubo redondo':('AreaTuboRedondo',('AI','AL'),math.pi*(d*d-(d-2*t)**2)/4),
        'tubo quadrado':('AreaTuboQuadrado',('AJ','AL'),w*w-(w-2*t)**2),
        'tubo retangular':('AreaTuboRetangular',('AJ','AK','AL'),w*h-(w-2*t)*(h-2*t)),
        'calha':('AreaCalha',('AJ','AK','AL'),h*t+2*w*t-2*t*t),
    }
    family=normalized(cells.get('AF',{}).get('value'))
    if family not in functions:return None
    function,cols,value=functions[family]
    branch=f'IF(AF{row}="{str(cells["AF"]["value"]).upper()}",{function.upper()}('+','.join(col+row for col in cols)+')'
    formula=compact_formula(cells.get('AP',{}))
    if re.sub(r'\s+','',branch) not in formula or f'*AH{row},"")' not in formula:return None
    return value


def literal_derived_difference(area,check,values,cells,sections):
    """Recompute explicitly derived fields whose original Excel cells are literals.

    Stock is still an input and is preserved. Literal results remain in evidence;
    they do not become permanent overrides of the mandatory planning formulas.
    """
    field=check['field']
    if field not in ({'quantity_to_plan','section_pending','weight','bars'} if area=='perfis' else {'remaining','quantity_to_plan'}):return None
    q_col,p_col=('AH','V') if area=='perfis' else ('O','AA')
    q,p=[original_number(cells.get(k,{}).get('value')) for k in (q_col,p_col)]
    if (q is None or p is None or min(q,p)<0 or not q.is_integer() or not p.is_integer()
            or not equal(q,values.get('quantity_required')) or not equal(p,values.get('cut' if area=='perfis' else 'made'))):return None
    row=re.search(r'\d+$',cells[q_col]['cell']).group();balance=max(q-p,0)
    literal_col='BT' if field=='bars' else 'AS' if area=='perfis' else 'AG'
    literal=cells.get(literal_col,{})
    old_literal=number(literal.get('value'))
    if literal.get('formula') or old_literal is None:return None
    new=balance;old=old_literal;property_proof=None
    if field in ('section_pending','weight'):
        resolved=original_section(values,cells,sections)
        if resolved is None or resolved[0] is None:return None
        prop,origin,inputs=resolved
        if not equal(prop,values.get('section_unit')) or not equal(prop,number(cells.get('AX',{}).get('value'))):return None
        old_area=old_literal*prop;new_area=balance*prop
        if not equal(number(cells.get('AY',{}).get('value')),old_area):return None
        if cells.get('AY',{}).get('formula') and compact_formula(cells['AY'])!=f'IF(AX{row}="","",AS{row}*AX{row})':return None
        old,new=old_area,new_area;property_proof={'property':prop,'source':origin,'inputs':inputs}
        if field=='weight':
            length=original_number(cells.get('AM',{}).get('value'))
            term=f'((AY{row}/1000000)*(AM{row}/1000)*7850)'
            if not length or length<=0 or not equal(length,values.get('length_mm')) or compact_formula(cells.get('DB',{}))!=f'IFERROR(IF({term}<0,0,{term}),"")':return None
            old=max(old_area/1e6*length/1000*7850,0);new=new_area/1e6*length/1000*7850
    elif field=='bars':
        stock,length=[original_number(cells.get(k,{}).get('value')) for k in ('BS','Q')]
        if not stock or not length or length<=0 or stock<length or not equal(stock,values.get('stock_length_mm')) or not equal(length,values.get('length_mm')):return None
        new=math.ceil(balance/math.floor(stock/length))
    if not equal(cached_value(area,field,cells)[0],old) or not equal(check['observed'],new):return None
    return {'classification':'intentional_recalculated_literal_derived',
            'plan_rule':'F11/F10/F15/F18/G03/G10: derived results are recomputed from current inputs; only stock has an explicit manual override',
            'original_literal':literal,'original_inputs':{k:cells.get(k) for k in (q_col,p_col,'BS','Q','AM','AX','AY')},
            'property_proof':property_proof,'independent_original_result':old,'independent_current_result':new}


def missing_property_weight_difference(check, values, cells, sections):
    """A zero cached area is not evidence of a known physical weight."""
    if check['field'] != 'weight' or check['observed'] is not None or values.get('weight_unit') is not None:
        return None
    property_proof = section_difference({'field':'section_unit','observed':None}, values, cells, sections)
    if not property_proof:
        return None
    row = re.search(r'\d+$', cells['AF']['cell']).group()
    unit, pending, area, length = [original_number(cells.get(col, {}).get('value')) for col in ('AX','AS','AY','AM')]
    term = f'((AY{row}/1000000)*(AM{row}/1000)*7850)'
    if (None in (unit, pending, area, length) or length <= 0 or not equal(length, values.get('length_mm'))
            or not equal(area, unit*pending)
            or compact_formula(cells.get('AY', {})) != f'IF(AX{row}="","",AS{row}*AX{row})'
            or compact_formula(cells.get('DB', {})) != f'IFERROR(IF({term}<0,0,{term}),"")'):
        return None
    old = max(area/1e6*length/1000*7850, 0)
    if not equal(number(cells['DB']['value']), old):
        return None
    return {'classification':'intentional_unknown_weight_property',
            'plan_rule':'F14/F15: unavailable unit property cannot establish a physical weight; cached zero is preserved separately',
            'property_proof':property_proof, 'original_inputs':{k:cells[k] for k in ('AX','AS','AY','AM','DB')},
            'independent_original_result':old, 'independent_current_result':None}


def zero_balance_bars_difference(check, values, cells):
    if check['field'] != 'bars' or check['observed'] != 0:
        return None
    q, legacy_q, produced = [original_number(cells.get(col, {}).get('value')) for col in ('AH','N','V')]
    if (q is None or q < 0 or not q.is_integer() or q != legacy_q or q != produced
            or not equal(q, values.get('quantity_required')) or not equal(produced, values.get('cut'))
            or values.get('remaining') != 0 or values.get('length_mm') is not None
            or cells.get('AM', {}).get('value') not in (None, '') or cells.get('Q', {}).get('value') != ''):
        return None
    row = re.search(r'\d+$', cells['AH']['cell']).group()
    if (compact_formula(cells.get('Q', {})) != f'IF(AM{row}="","",AM{row})'
            or compact_formula(cells.get('CD', {})) != f'N{row}-V{row}' or number(cells['CD']['value']) != 0
            or cells.get('BT', {}).get('type') != 'e' or cells['BT'].get('value') != '#VALUE!'
            or compact_formula(cells['BT']) != f'ROUNDUP(CD{row}/(ROUNDDOWN((BS{row}/Q{row}),0)),0)'):
        return None
    return {'classification':'intentional_zero_pending_bars',
            'plan_rule':'F18: known zero balance requires zero stock bars even when piece length is unknown',
            'original_inputs':{k:cells.get(k) for k in ('AH','N','V','Q','AM','CD','BS','BT')},
            'independent_balance':q-produced, 'independent_current_result':0}


def shifted_section_difference(check, values, cells, sections):
    if check['field'] != 'section_unit':
        return None
    resolved = original_section(values, cells, sections)
    if not resolved or resolved[0] is None or resolved[1]['kind'] != 'exact_lookup':
        return None
    prop, source, inputs = resolved
    q = original_number(cells.get('AH', {}).get('value'))
    if (q is None or q <= 0 or not equal(q, values.get('quantity_required'))
            or not equal(prop, check['observed']) or not equal(prop, values.get('section_unit'))
            or not equal(number(cells.get('AP', {}).get('value')), prop*q)
            or number(cells.get('AX', {}).get('value')) != 0
            or number(cells.get('AN', {}).get('value')) is None):
        return None
    wrong_profile = normalized(cells.get('AO', {}).get('value'))
    if not wrong_profile or any(key[1] == wrong_profile for key in sections):
        return None
    row = re.search(r'\d+$', cells['AF']['cell']).group()
    formula = compact_formula(cells.get('AP', {}))
    if (f'XLOOKUP(AG{row},AREASECAOCORTE!$B$3:$B$700,AREASECAOCORTE!$C$3:$C$700)' not in formula
            or f'IF(AF{row}="","",0)' not in formula or f'*AH{row},"")' not in formula):
        return None
    from openpyxl.formula.translate import Translator
    translated = Translator('='+formula, origin='AP'+row).translate_formula('AX'+row)[1:]
    if compact_formula(cells.get('AX', {})) != translated:
        return None
    return {'classification':'intentional_displaced_section_formula',
            'plan_rule':'F09: unit section uses actual family/profile, not the angle/grade referenced by a displaced Excel formula',
            'original_inputs':{**inputs, **{k:cells.get(k) for k in ('AN','AO','AH','AP','AX')}},
            'property_source':source, 'translation':{'from':'AP'+row,'to':'AX'+row,'formula':translated},
            'wrong_lookup_absent_from_catalogue':wrong_profile, 'independent_original_result':0,
            'independent_current_result':prop}


def manual_week_difference(check, values, cells, proof, plan_key):
    """Require persisted operation scope, human decision, source link and event."""
    if check['field'] != 'expected_week' or not proof:
        return None
    state, event, operation, link = [proof[k] for k in ('state','event','operation','link')]
    if (state.get('field') != 'expected_date' or state.get('requires_review')
            or state.get('human_decision') != 'write' or state.get('source', {}).get('kind') != 'manual'
            or state.get('value') != values.get('expected_date') or state.get('scope') != str(operation.get('id'))
            or operation.get('area') != 'perfis' or operation.get('code') != 'corte'
            or str(operation.get('need_id')) != str(state.get('need_id'))
            or str(link.get('need_id')) != str(state.get('need_id')) or link.get('kind') != 'plan_line'
            or link.get('source_id') != plan_key or str(event.get('need_id')) != str(state.get('need_id'))
            or event.get('revision') != state.get('revision') or event.get('action') != 'preparation_saved'):
        return None
    changes = event.get('detail', {}).get('changes', [])
    matching = [x for x in changes if x.get('field') == 'expected_date' and x.get('scope') == state['scope']]
    if (len(matching) != 1 or matching[0].get('after') != state['value']
            or matching[0].get('source', {}).get('kind') != 'manual' or matching[0].get('decision') != 'write'):
        return None
    try:
        year, week, _ = date.fromisoformat(state['value']).isocalendar()
    except (ValueError, TypeError):
        return None
    row = re.search(r'\d+$', cells.get('AV', {}).get('cell', ''))
    if not row:
        return None
    row = row.group(); expected = f'{year}-W{week:02}'
    if (check['observed'] != expected or cells.get('AR', {}).get('value') not in (None, '')
            or cells['AV'].get('value') != '' or number(cells.get('AW', {}).get('value')) != 1900
            or compact_formula(cells['AV']) != f'IF(AR{row}="","",_XLFN.ISOWEEKNUM(AR{row}))'
            or compact_formula(cells['AW']) != f'YEAR(AR{row})'):
        return None
    return {'classification':'intentional_audited_manual_date',
            'plan_rule':'F13: ISO week/year of the persisted manual expected date; empty Excel date is not a year-1900 schedule',
            'manual_evidence':proof,'original_inputs':{k:cells.get(k) for k in ('AR','AV','AW')},
            'independent_current_result':expected}


def nonnegative_difference(area, check, values, cells, sections, weights=None):
    """Prove the old signed calculation AND unchanged Q/production before clipping.

    A cached negative and a current zero alone are insufficient: changed OCR,
    quantity, geometry or arbitrary cached values must remain unresolved.
    """
    field = check['field']
    supported = ('remaining', 'quantity_to_plan', 'bars', 'section_pending') if area == 'perfis' else ('remaining', 'quantity_to_plan', 'remaining_m', 'weight')
    if field not in supported or check['observed'] != 0:
        return None
    q_col = ('AH' if field in ('quantity_to_plan', 'section_pending') else 'N') if area == 'perfis' else 'O'
    p_col = 'V' if area == 'perfis' else 'AA'
    q, produced = [original_number(cells.get(k, {}).get('value')) for k in (q_col, p_col)]
    if (q is None or produced is None or min(q, produced) < 0 or not q.is_integer() or not produced.is_integer()
            or produced <= q or not equal(q, values.get('quantity_required'))
            or not equal(produced, values.get('cut' if area == 'perfis' else 'made'))
            or not equal(values.get('production_excess'), produced-q)):
        return None
    row = re.search(r'\d+$', cells[q_col]['cell']).group()
    balance_col = ('AS' if q_col == 'AH' else 'CD') if area == 'perfis' else 'AG'
    formula = (f'IF(AH{row}="","",AH{row}-V{row})' if q_col == 'AH' else f'N{row}-V{row}') if area == 'perfis' else 'TABELA4[[#THISROW],[QTD]]-TABELA4[[#THISROW],[MAQ.]]'
    signed = q-produced
    if compact_formula(cells.get(balance_col, {})) != formula or not equal(number(cells.get(balance_col, {}).get('value')), signed):
        return None
    expected_old = signed
    evidence = {'plan_rule':'F07/F10/F18/G03/G05: nonnegative pending work; retain production excess separately',
                'original_quantity':cells[q_col], 'original_production':cells[p_col],
                'original_balance':cells[balance_col], 'selected_quantity':q,
                'selected_production':produced, 'independent_excess':produced-q}
    if field == 'bars':
        length, stock = [original_number(cells.get(k, {}).get('value')) for k in ('Q','BS')]
        if (not length or length <= 0 or not stock or stock < length
                or not equal(length, values.get('length_mm')) or not equal(stock, values.get('stock_length_mm'))
                or compact_formula(cells.get('BT', {})) != f'ROUNDUP(CD{row}/(ROUNDDOWN((BS{row}/Q{row}),0)),0)'):
            return None
        expected_old = -math.ceil(abs(signed)/math.floor(stock/length))
        evidence['original_stock_length'] = {k:cells[k] for k in ('Q','BS')}
    elif field == 'section_pending':
        resolved = original_section(values, cells, sections)
        if resolved is None or resolved[0] is None:
            return None
        prop, source, inputs = resolved
        if (not equal(prop, number(cells.get('AX', {}).get('value')))
                or compact_formula(cells.get('AY', {})) != f'IF(AX{row}="","",AS{row}*AX{row})'):
            return None
        expected_old = signed*prop
        evidence.update(independent_unit_area=prop, property_source=source, original_section_inputs=inputs)
    elif field == 'remaining_m':
        length = original_number(cells.get('R', {}).get('value'))
        if (not length or length <= 0 or not equal(length, values.get('length_mm'))
                or not equal(number(cells.get('AM', {}).get('value')), q*length/1000)
                or not equal(number(cells.get('BJ', {}).get('value')), produced*length/1000)
                or compact_formula(cells.get('BK', {})) != 'TABELA4[[#THISROW],[COMP.TOTAL(M)]]-TABELA4[[#THISROW],[MPROD.]]'):
            return None
        expected_old = signed*length/1000
        evidence['original_metre_inputs'] = {k:cells[k] for k in ('R','AM','BJ')}
    elif field == 'weight':
        name = normalized(cells.get('Q', {}).get('value'))
        length = original_number(cells.get('R', {}).get('value'))
        entries = (weights or {}).get(name, [])
        rates = {e['kg_m'] for e in entries if e['kg_m'] is not None and e['kg_m'] > 0}
        if (not name or name != normalized(values.get('profile')) or not length or length <= 0
                or not equal(length, values.get('length_mm')) or len(rates) != 1
                or compact_formula(cells.get('AS', {})) != f'(O{row}-AA{row})*AP{row}'):
            return None
        unit = next(iter(rates))*length/1000
        if not equal(unit, values.get('weight_unit')) or not equal(unit, number(cells.get('AP', {}).get('value'))):
            return None
        expected_old = signed*unit
        evidence.update(exact_weight_entries=entries, original_unit_weight=cells['AP'],
                        plan_rule='G09: unit weight × nonnegative principal balance; preserve excess')
    column = COLUMNS[area][field][0]
    if not equal(number(cells.get(column, {}).get('value')), expected_old):
        return None
    return {**evidence, 'classification':'intentional_nonnegative_balance',
            'original_result':cells[column], 'independent_original_result':expected_old,
            'independent_current_result':0}


def ocr_counter_difference(area, check, values, cells, source, sections, weights):
    """Reconcile an independently proven OCR total with the literal old formula.

    Blank-as-zero is used only to reconstruct a numeric Excel cache. The current
    counter must equal the independently verified, complete central event set.
    Unrelated quantity/property changes or unexplained caches are not excused.
    """
    field = check['field']
    supported = {'remaining','quantity_to_plan','cut_pct','bars','section_pending','weight'} if area=='perfis' else {'remaining','quantity_to_plan','remaining_m','weight'}
    code='corte' if area=='perfis' else str(values.get('operation') or '').strip()
    if (field not in supported or not source or source.get('result')!='passed'
            or source.get('area')!=area or source.get('operation')!=code
            or source.get('issues') or source.get('uncertain_records')):
        return None
    events=source.get('events') or []
    quantities=[number(e.get('quantity')) for e in events]
    if (not events or any(q is None or q<0 or not q.is_integer() for q in quantities)
            or any(e.get('record_id') is None or e.get('operation')!=code for e in events)
            or len({(e['record_id'],e.get('child_key')) for e in events})!=len(events)):
        return None
    produced=sum(quantities)
    if (not equal(produced,source.get('expected')) or not equal(produced,source.get('observed'))
            or not equal(produced,values.get('cut' if area=='perfis' else 'made'))):
        return None
    q_col=('AH' if field in ('quantity_to_plan','section_pending','weight') else 'N') if area=='perfis' else 'O'
    p_col='V' if area=='perfis' else 'AA'
    q=original_number(cells.get(q_col,{}).get('value'))
    literal=cells.get(p_col,{}).get('value')
    old_p=0 if literal is None or isinstance(literal,str) and not literal.strip() else original_number(literal)
    if (q is None or q<0 or not q.is_integer() or old_p is None or old_p<0 or not old_p.is_integer()
            or not equal(q,values.get('quantity_required')) or equal(old_p,produced)):
        return None
    row=re.search(r'\d+$',cells[q_col]['cell']).group()
    old_balance=q-old_p; balance=max(q-produced,0)
    balance_col=('AS' if q_col=='AH' else 'CD') if area=='perfis' else 'AG'
    balance_formula=(f'IF(AH{row}="","",AH{row}-V{row})' if q_col=='AH' else f'N{row}-V{row}') if area=='perfis' else 'TABELA4[[#THISROW],[QTD]]-TABELA4[[#THISROW],[MAQ.]]'
    # Percentages do not depend on a stored balance, but the remaining fields do.
    if field!='cut_pct' and (compact_formula(cells.get(balance_col,{}))!=balance_formula
            or not equal(number(cells.get(balance_col,{}).get('value')),old_balance)):
        return None
    old_result,new_result=old_balance,balance
    evidence={'plan_rule':'§2 / C02.4–C02.5: complete validated OCR takes precedence per piece/operation; never add it to Excel',
        'original_quantity':cells[q_col],'original_production':cells.get(p_col,{'cell':p_col+row,'not_stored':True}),
        'excel_arithmetic_counter':old_p,'selected_counter_from_verified_events':produced,
        'verified_events':events,'original_balance':cells.get(balance_col)}
    if field=='cut_pct':
        formula=f'IF((V{row}/VALUE($N{row}))*100=100,"X",((V{row}/VALUE($N{row})))*100)'
        if q<=0 or compact_formula(cells.get('Y',{}))!=formula:
            return None
        old_result,new_result=100*old_p/q,100*produced/q
    elif field=='bars':
        length,stock=[original_number(cells.get(col,{}).get('value')) for col in ('Q','BS')]
        if (not length or length<=0 or not stock or stock<length
                or not equal(length,values.get('length_mm')) or not equal(stock,values.get('stock_length_mm'))
                or compact_formula(cells.get('BT',{}))!=f'ROUNDUP(CD{row}/(ROUNDDOWN((BS{row}/Q{row}),0)),0)'):
            return None
        fit=math.floor(stock/length)
        old_result=math.copysign(math.ceil(abs(old_balance)/fit),old_balance)
        new_result=math.ceil(balance/fit)
        evidence['stock_and_length']={k:cells[k] for k in ('Q','BS')}
    elif field=='section_pending' or (area=='perfis' and field=='weight'):
        resolved=original_section(values,cells,sections)
        if resolved is None or resolved[0] is None:return None
        prop,origin,inputs=resolved
        if (not equal(prop,number(cells.get('AX',{}).get('value')))
                or compact_formula(cells.get('AY',{}))!=f'IF(AX{row}="","",AS{row}*AX{row})'):
            return None
        old_result,new_result=old_balance*prop,balance*prop
        evidence.update(independent_unit_area=prop,property_source=origin,original_property_inputs=inputs)
        if field=='weight':
            length=original_number(cells.get('AM',{}).get('value'))
            term=f'((AY{row}/1000000)*(AM{row}/1000)*7850)'
            if (not length or length<=0 or not equal(length,values.get('length_mm'))
                    or not equal(number(cells.get('AY',{}).get('value')),old_result)
                    or compact_formula(cells.get('DB',{}))!=f'IFERROR(IF({term}<0,0,{term}),"")'):
                return None
            old_result=max(old_result/1e6*length/1000*7850,0)
            new_result=new_result/1e6*length/1000*7850
            evidence.update(density_kg_m3=7850,original_length=cells['AM'])
    elif field=='remaining_m':
        length=original_number(cells.get('R',{}).get('value'))
        if (not length or length<=0 or not equal(length,values.get('length_mm'))
                or not equal(number(cells.get('AM',{}).get('value')),q*length/1000)
                or not equal(number(cells.get('BJ',{}).get('value')),old_p*length/1000)
                or compact_formula(cells.get('BK',{}))!='TABELA4[[#THISROW],[COMP.TOTAL(M)]]-TABELA4[[#THISROW],[MPROD.]]'):
            return None
        old_result,new_result=old_balance*length/1000,balance*length/1000
        evidence['original_metre_inputs']={k:cells[k] for k in ('R','AM','BJ')}
    elif field=='weight':
        name=normalized(cells.get('Q',{}).get('value'));length=original_number(cells.get('R',{}).get('value'))
        entries=weights.get(name,[]);rates={e['kg_m'] for e in entries if e['kg_m'] is not None and e['kg_m']>0}
        if (not name or name!=normalized(values.get('profile')) or not length or length<=0
                or not equal(length,values.get('length_mm')) or len(rates)!=1):return None
        unit=next(iter(rates))*length/1000;old_unit=number(cells.get('AP',{}).get('value'))
        if not equal(unit,values.get('weight_unit')) or old_unit is None:return None
        unit_reason=None
        if not equal(unit,old_unit):
            unit_reason=exact_weight_difference({'field':'weight_unit','observed':unit},values,cells,weights)
            if not unit_reason:return None
        direct=f'(O{row}-AA{row})*AP{row}'
        conditional=f'IF(TABELA4[[#THISROW],[FECHADO]]="X",0,{direct})'
        formula=compact_formula(cells.get('AS',{}))
        if formula not in (direct,conditional):return None
        old_result=0 if formula==conditional and normalized(cells.get('AH',{}).get('value'))=='x' else old_balance*old_unit
        new_result=balance*unit
        evidence.update(exact_weight_entries=entries,original_unit_weight=cells['AP'],
                        original_closure=cells.get('AH'),unit_weight_justification=unit_reason)
    cached,_=cached_value(area,field,cells)
    if not equal(cached,old_result) or not equal(check['observed'],new_result):return None
    return {**evidence,'classification':'intentional_verified_ocr_counter',
            'independent_original_result':old_result,'independent_current_result':new_result}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='c04-excel-comparison')
    parser.add_argument('--population-proof', default='c04-formula-population')
    parser.add_argument('--source-proof', help='Optional independently reconciled central OCR proof prefix')
    args = parser.parse_args()
    for name in (args.output, args.population_proof, *([args.source_proof] if args.source_proof else [])):
        if not re.fullmatch('[a-z0-9-]+', name):
            parser.error('Use simple proof prefixes')
    os.environ['MES_PG_DSN'] = json.loads(Path(
        '/home/luis/.local/state/planning-backups/integral-20260923/isolated.json'
    ).read_text())['dsn']
    from app import planning
    from app.raw import query

    proof_path = FOLDER / (args.population_proof + '.json')
    proof = json.loads(proof_path.read_text())
    arithmetic_path = FOLDER / proof['ledger']['file']
    assert sha(arithmetic_path) == proof['ledger']['sha256']
    assert proof['result'] == 'passed_in_stated_scope'
    for source in proof['sources']:
        assert sha(Path(source['file'])) == source['sha256']
    source_proof=None;verified_counters={}
    if args.source_proof:
        source_path=FOLDER/(args.source_proof+'.json');source_proof=json.loads(source_path.read_text())
        assert source_proof['result']=='passed_in_stated_scope' and not source_proof['failures']
        assert source_proof['script_sha256']==sha(Path('scripts/audit_planning_selected_ocr.py'))
        assert sha(FOLDER/source_proof['record_ledger']['file'])==source_proof['record_ledger']['sha256']
        verified_counters={(r['area'],r['key'],r['operation']):r for r in source_proof['selected']}
    weights = weight_catalogue()
    sections = section_catalogue()
    layout = {}
    with gzip.open(FOLDER / 'LayoutPlaneamentoPerfis-cells.jsonl.gz', 'rt') as f:
        for line in f:
            item = json.loads(line)
            if item['sheet'] == 'Folha1' and item['cell'] in LAYOUT.values():
                layout[item['cell']] = item
    report = {
        'at': datetime.now(timezone.utc).isoformat(),
        'environment': 'isolated planning_integral; readonly repeatable read',
        'command': f'PYTHONPATH=. .venv/bin/python scripts/audit_planning_excel_comparison.py --output {args.output} --population-proof {args.population_proof}',
        'script_sha256': sha(Path(__file__)),
        'expectations': {'file': proof_path.name, 'sha256': sha(proof_path),
                         'ledger_sha256': sha(arithmetic_path)},
        'sources': proof['sources'], 'cell_ledgers': {}, 'areas': {},
        'boundary': '23 arithmetic rules only. No approval of source association. Missing physical columns are explicitly separate from cache comparisons. Differences are not excused just because there is OCR, a local override, an approximate lookup or an old Excel cache.',
    }
    if source_proof:
        report['command']+=' --source-proof '+args.source_proof
        report['central_ocr_proof']={'file':source_path.name,'sha256':sha(source_path),'boundary':source_proof['boundary']}
    output = FOLDER / (args.output + '-rows.jsonl.gz')
    unresolved = FOLDER / (args.output + '-unresolved.jsonl.gz')
    counts = defaultdict(Counter)
    field_counts = defaultdict(lambda: defaultdict(Counter))
    with planning.connect(readonly=True) as c, gzip.open(output, 'wt') as dest, gzip.open(unresolved, 'wt') as problems:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        assert c.execute('SELECT current_database() n').fetchone()['n'] == 'planning_integral'
        date_proofs = defaultdict(list)
        for row in c.execute("""
            SELECT s.need_id::text need_id, l.source_id,
                   to_jsonb(s) state, to_jsonb(e) event,
                   to_jsonb(o) operation,
                   jsonb_build_object('need_id',l.need_id,'kind',l.kind,
                                      'source_id',l.source_id,'version',l.version) link
              FROM planning_mtg.field_state s
              JOIN planning_mtg.need_operations o ON o.need_id=s.need_id AND o.id::text=s.scope
              JOIN planning_mtg.need_sources l ON l.need_id=s.need_id AND l.kind='plan_line'
              JOIN planning_mtg.need_events e ON e.need_id=s.need_id AND e.revision=s.revision
             WHERE s.field='expected_date' AND e.action='preparation_saved'
        """):
            date_proofs[(row['need_id'], row['source_id'])].append(
                {k:row[k] for k in ('state','event','operation','link')})
        if source_proof:
            from scripts.audit_planning_selected_ocr import source_fingerprints
            assert source_fingerprints(c)==source_proof['source_fingerprints'],'Central inputs changed; repeat the source audit'
        for area in planning.AREAS:
            gen = query.generation(c, area)
            assert gen['id'] == proof['areas'][area]['version'], 'Re-run arithmetic on the current publication'
            snapshot = gen['metadata']['snapshot']['snapshot_id']
            assert snapshot == proof['areas'][area]['snapshot']
            if source_proof:
                assert gen['id']==source_proof['areas'][area]['generation'] and snapshot==source_proof['areas'][area]['snapshot']
            source_rows = {r['source_line_id']: r['excel_row'] for r in c.execute(
                'SELECT source_line_id,excel_row FROM raw_mtg.plan_production_rows WHERE snapshot_id=%s', (snapshot,))}
            base, params = query.source(gen)
            # Only observation/provenance; no application formula is an oracle.
            published = {r['row_key']: r for r in c.execute(
                "SELECT m.row_key,c.values_json,c.detail->>'plan_key' plan_key,"
                "c.detail->>'need_id' need_id,c.detail->'calculation'->'rules' rules" + base, params)}
            original, source_ledger = cells_for_area(area)
            report['cell_ledgers'][area] = source_ledger
            print(area, len(published), 'published rows;', len(original), 'original Excel rows', flush=True)
            with gzip.open(arithmetic_path, 'rt') as stream:
                for line in stream:
                    piece = json.loads(line)
                    if piece['area'] != area:
                        continue
                    actual = published.pop(piece['key'])
                    excel_row = source_rows.get(actual['plan_key'])
                    cells = original.get(excel_row, {})
                    counts[area]['pieces'] += 1
                    for check in piece['checks']:
                        field = check['field']
                        assert equal(actual['values_json'].get(field), check['observed']), 'Published value changed'
                        columns = COLUMNS[area].get(field, ())
                        cached, kind = cached_value(area, field, cells)
                        observed = check['observed']
                        justification = unknown_source_difference(area, field, observed, actual['values_json'], cells)
                        if not justification and area == 'cantoneiras':
                            justification = exact_weight_difference(check, actual['values_json'], cells, weights)
                        if not justification:
                            justification = empty_input_difference(area, field, observed, actual['values_json'], cells)
                        if not justification and area == 'perfis':
                            justification = structured_quantity_difference(check, actual['values_json'], cells)
                            if not justification:
                                justification = section_difference(check, actual['values_json'], cells, sections)
                            if not justification:
                                justification = missing_property_weight_difference(check, actual['values_json'], cells, sections)
                            if not justification:
                                justification = zero_balance_bars_difference(check, actual['values_json'], cells)
                            if not justification:
                                justification = shifted_section_difference(check, actual['values_json'], cells, sections)
                            if not justification and field == 'expected_week':
                                candidates = date_proofs.get((actual['need_id'], actual['plan_key']), [])
                                if len(candidates) == 1:
                                    justification = manual_week_difference(check, actual['values_json'], cells, candidates[0], actual['plan_key'])
                        if not justification:
                            justification = literal_derived_difference(area, check, actual['values_json'], cells, sections)
                        if not justification:
                            justification = nonnegative_difference(area, check, actual['values_json'], cells, sections, weights)
                        if not justification and source_proof:
                            primary='corte' if area=='perfis' else str(actual['values_json'].get('operation') or '').strip()
                            source=verified_counters.get((area,piece['key'],primary))
                            justification=ocr_counter_difference(area,check,actual['values_json'],cells,source,sections,weights)
                        if excel_row is None:
                            status = 'local_piece_without_original_excel'
                        elif not columns:
                            status = 'rule_without_corresponding_macro_column'
                        elif kind == 'cell_not_stored':
                            status = 'no_stored_excel_cell_to_compare'
                        elif kind == 'week_without_year':
                            status = 'intentional_unknown_year' if observed is None else 'unresolved'
                        elif equal(cached, observed):
                            status = 'same_value' if observed is not None else 'same_unavailable_value'
                        elif justification:
                            status = justification['classification']
                        else:
                            status = 'unresolved'
                        rule = (actual['rules'] or {}).get(field, {})
                        reason = rule.get('reason')
                        if observed is None:
                            counts[area]['unavailable'] += 1
                            counts[area]['with_reason' if reason else 'missing_reason'] += 1
                            if reason == 'Entradas necessárias desconhecidas.':
                                counts[area]['generic_reason_needs_review'] += 1
                        record = {
                            'area': area, 'key': piece['key'], 'of': piece['of'],
                            'reference': piece['reference'], 'excel_row': excel_row,
                            'workbook': BOOKS[area][0], 'sheet': BOOKS[area][1],
                            'source_cells': [cells.get(col, {'cell': f'{col}{excel_row}', 'not_stored': True}) for col in columns],
                            'layout_rule': layout.get(LAYOUT.get(field)) if area == 'perfis' else None,
                            'original_inputs': {col: cells[col] for col in (PERFIS_INPUTS if area == 'perfis' else ('O','AA','R','Q','AH','AP')) if col in cells},
                            'cached_value_in_raw_units': cached, 'cache_kind': kind,
                            **check, 'difference_from_cache': observed - cached if isinstance(observed, (int,float)) and isinstance(cached, (int,float)) else None,
                            'classification': status, 'need_id': actual['need_id'],
                            'difference_justification': justification if justification and status == justification['classification'] else None,
                            'application_unavailability_reason': reason,
                        }
                        text = json.dumps(record, ensure_ascii=False, default=str) + '\n'
                        dest.write(text)
                        counts[area][status] += 1
                        field_counts[area][field][status] += 1
                        if status == 'unresolved':
                            problems.write(text)
            assert not published, 'Arithmetic ledger omitted published rows'
            report['areas'][area] = {'version': gen['id'], 'snapshot': snapshot,
                'counts': dict(counts[area]), 'by_field': {k: dict(v) for k,v in field_counts[area].items()}}
            print(area, dict(counts[area]), flush=True)
    report['ledger'] = {'file': output.name, 'sha256': sha(output)}
    report['unresolved_ledger'] = {'file': unresolved.name, 'sha256': sha(unresolved)}
    report['result'] = 'differences_require_investigation' if any(x['unresolved'] or x['missing_reason'] for x in counts.values()) else 'passed_in_stated_scope'
    (FOLDER / (args.output + '.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(report['result'], flush=True)
    if report['result'] != 'passed_in_stated_scope':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
