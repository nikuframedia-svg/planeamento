"""Shared planning calculations, after identity and production source resolution.

Inputs are server-resolved facts. No cached derived value is an input to this
module. Quantities are pieces, lengths mm, section areas mm², masses kg.
"""
from __future__ import annotations

from datetime import date
from . import planning_dates
import math
import re

CONTRACT = 'planning-integral-20260925-v11'  # v11 (08/10): peso das cantoneiras pela geometria sem Tabela de pesos (F08) e milhares com espaço («1 200») em todos os números (F19); v10 (07/10): «Qtd em falta» do registo manual, aço 7850 sem Qual. e PDF sem Excel começa a 0; v9 (06/10): semana prevista MTG3 pela Data Corte; v8: contador Excel vazio conta 0 quando a folha o confirma

# Origem do saldo quando o planeador escreve a «Qtd em falta» no registo manual (07/10/2026).
DECLARED_ORIGIN = 'Qtd em falta (registo manual)'
# Família da evidência de produção: a «Qtd em falta» só desconta a produção registada depois dela quando
# a fonte é da mesma família (OCR, incluindo o ainda nada produzido, ou contador do Excel).
EVIDENCE = {'OCR validado': 'ocr', 'Condição inicial local': 'ocr', 'Excel provisório': 'excel'}

# Keep the attempted rule visible even when its operands are unavailable/invalid.
GEOMETRY = {
    'varão redondo': ('π × d² / 4', ('outer_diameter_mm',)),
    'varão nervurado': ('π × d² / 4', ('outer_diameter_mm',)),
    'varão quadrado': ('w²', ('width_mm',)),
    'varão retangular': ('w × h', ('width_mm', 'height_mm')),
    'barra': ('w × h', ('width_mm', 'height_mm')),
    'tubo redondo': ('π × (d² − (d − 2t)²) / 4', ('outer_diameter_mm', 'thickness_mm')),
    'tubo quadrado': ('w² − (w − 2t)²', ('width_mm', 'thickness_mm')),
    'tubo retangular': ('w × h − (w − 2t) × (h − 2t)', ('width_mm', 'height_mm', 'thickness_mm')),
    'calha': ('h × t + 2w × t − 2t²', ('width_mm', 'height_mm', 'thickness_mm')),
    'cantoneira': ('h × t + w × t − t²', ('width_mm', 'height_mm', 'thickness_mm')),
    'chapa': ('w × t', ('width_mm', 'thickness_mm')),
}


# Milhares separados por espaço, como o Excel escreve «1 543» em Cantoneiras!Comp. Só grupos completos de três:
# espaços soltos podiam juntar dois números num facto novo.
THOUSANDS = re.compile(r'[+-]?\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d+)?')
SPACES = re.compile(r'[ \u00a0\u202f]')


def number(value):
    """O único leitor de números da app (08/10, F19): vírgula decimal e milhares com espaço («1 200»)."""
    try:
        text = str(value).strip()
        if SPACES.search(text) and THOUSANDS.fullmatch(text):
            text = SPACES.sub('', text)
        n = float(text.replace(',', '.'))
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


def quantity(value):
    n = number(value)
    return n if n is not None and n >= 0 and n.is_integer() else None


def positive(value):
    n = number(value)
    return n if n is not None and n > 0 else None


def key(value):
    return re.sub(r'\s+', ' ', str(value or '').strip().casefold()).replace('rectangular', 'retangular')


def abocardar(value):
    if value is True or key(value).lstrip("'") in ('x', 'sim'): return True
    if value is False or key(value) in ('-', 'não', 'nao'): return False
    return None


# Peso das cantoneiras pela geometria (08/10, F08): secção L sem raio de concordância, t × (a + b − t) mm², em aço
# de 7850 kg/m³. Fica a ±2 % do nominal, um pouco abaixo por faltar o raio (L40X40X3: 1,81 contra 1,84 kg/m;
# L100X100X10: 14,9 contra 15,1 kg/m).
STEEL_DENSITY = 7850
ANGLE_ORIGIN = 'Peso estimado pela geometria (±2 %)'
ANGLE_FORMULA = 't × (a + b − t) × 7850 / 10⁶'


def angle_kg_m(profile):
    """kg/m de uma cantoneira «L a×b×t» (ex.: L40X40X3), ou None quando o perfil não se lê assim."""
    try:
        from .gantt.machines import dimensions  # a pedido: o MES partilha este módulo sem o Gantt
    except ImportError:
        return None
    text = str(profile or '').strip()
    found = dimensions(text) or (dimensions(text.split()[0]) if text else None)
    if not found:
        return None
    a, b, t = found
    if not 0 < t < min(a, b):
        return None
    return {'kg_m': t * (a + b - t) * STEEL_DENSITY / 1e6, 'a': a, 'b': b, 't': t}


# Coluna de saldo do próprio Excel para cada contador (Qtd em falta = QTD − contador).
EXCEL_REMAINING = {'Ser.': 'Qtd em Falta', 'Maq.': 'Qtd falta'}


def excel_counter(raw, column, required):
    """Contador do Excel; a célula vazia conta 0 quando a própria folha o confirma.

    Regra de 06/10/2026: é o que o Excel faz (falta = QTD − contador) e o que a
    vista kanban_plan_lines já fazia (qtd_minus_maq_blank_zero). Coluna ausente,
    texto inválido ou uma «falta» diferente da quantidade continuam desconhecidos.
    """
    raw = raw or {}
    value = raw.get(column)
    if (column in raw and (value is None or str(value).strip() == '') and required is not None
            and quantity(raw.get(EXCEL_REMAINING[column])) == required):
        return 0
    return value


def production_source(operation, macro=None, *, local_initial=False, compatible=True):
    """Select a complete operation total, preserving incomplete evidence.

    Evidence producers must include unresolved candidates in coverage_reasons.
    Identity/operation checks are made by the server before calling this function.
    """
    op = operation or {}
    facts = op.get('ocr_records') or []
    reasons = list(op.get('coverage_reasons') or [])
    if op.get('ocr_partial'): reasons.append('Produção OCR com quantidades em falta.')
    if op.get('requires_operation_review'): reasons.append('Operação por confirmar.')
    if not compatible: reasons.append('Identidade técnica alterada; associação por rever.')
    unique = {}; sources = set()
    for fact in facts:
        identity = (fact.get('source', 'mes'), fact.get('instance_id'), fact.get('sheet_uid'),
                    fact.get('record_id'), fact.get('row_index'), fact.get('child_key'))
        if fact.get('operation') not in (None, op.get('operation')):
            reasons.append('Evento de outra operação.'); continue
        value = quantity(fact.get('quantity'))
        if value is None: reasons.append('Quantidade OCR desconhecida ou inválida.')
        if fact.get('validated') is False: reasons.append('Revisão OCR não validada.')
        if identity in unique and unique[identity] != value:
            reasons.append('Revisões ou quantidades em conflito para o mesmo evento.')
        unique[identity] = value
        sources.add((fact.get('source', 'mes'), fact.get('instance_id')))
    if len(sources) > 1 and not op.get('cross_source_reconciled'):
        reasons.append('Sobreposição entre origens OCR por resolver.')
    usable = bool(unique) and not reasons
    ocr = sum(unique.values()) if usable else None
    original = quantity(macro)
    if usable: value, origin = ocr, 'OCR validado'
    elif compatible and original is not None: value, origin = original, 'Excel provisório'
    elif local_initial and not facts and not reasons: value, origin = 0, 'Condição inicial local'
    else: value, origin = None, 'Indisponível'
    return {'value': value, 'origin': origin, 'ocr': ocr, 'excel': original,
            'difference': ocr-original if ocr is not None and original is not None else None,
            'records': facts, 'coverage_reasons': list(dict.fromkeys(reasons)),
            'reason': None if value is not None else '; '.join(dict.fromkeys(reasons)) or 'Sem produção OCR utilizável nem acumulado Excel conhecido.'}


def section(values, table=None):
    """VBA FuncAreaPerf + exact AreaSecaoCorte B:C; no generic I/H formula."""
    family = key(values.get('material_type'))
    d,w,h,t = [positive(values.get(k)) for k in ('outer_diameter_mm','width_mm','height_mm','thickness_mm')]
    value = None; formula = None
    if family in ('varão redondo','varão nervurado') and d:
        value,formula = math.pi*d*d/4, 'π × d² / 4'
    elif family == 'varão quadrado' and w:
        value,formula = w*w, 'w²'
    elif family in ('varão retangular','barra') and w and h:
        value,formula = w*h, 'w × h'
    elif family == 'tubo redondo' and d and t and 2*t<d:
        value,formula = math.pi*(d*d-(d-2*t)**2)/4, 'π × (d² − (d − 2t)²) / 4'
    elif family == 'tubo quadrado' and w and t and 2*t<w:
        value,formula = w*w-(w-2*t)**2, 'w² − (w − 2t)²'
    elif family == 'tubo retangular' and w and h and t and 2*t<min(w,h):
        value,formula = w*h-(w-2*t)*(h-2*t), 'w × h − (w − 2t) × (h − 2t)'
    elif family == 'calha' and w and h and t and 2*t<h and t<w:
        value,formula = h*t+2*w*t-2*t*t, 'h × t + 2w × t − 2t²'
    elif family == 'cantoneira' and w and h and t and t<min(w,h):
        value,formula = h*t+w*t-t*t, 'h × t + w × t − t²'
    elif family == 'chapa' and w and t:
        value,formula = w*t, 'w × t'
    if family in GEOMETRY:
        return value, {'formula': GEOMETRY[family][0], 'source': 'Met2_Plan_Perfis.xlsm · FuncAreaPerf',
                       'reason': None if value is not None else 'Dimensões ausentes ou geometria inválida.'}
    candidates = (table or {}).get((family,key(values.get('profile'))), [])
    areas = {positive(r.get('area')) for r in candidates} - {None}
    if len(areas)==1:
        return next(iter(areas)), {'formula': 'Correspondência exata família/perfil', 'sources': candidates}
    return None, {'formula': 'Correspondência exata família/perfil', 'reason': 'Catálogo com áreas divergentes.' if len(areas)>1 else 'Sem propriedade exata disponível para a família e o perfil.', 'sources': candidates}


def calculate(values, *, area='perfis', raw=None, operations=(), local_initial=False,
              compatible=True, sections=None, weights=None, today=None, density=None, declared_remaining=None,
              declared_produced=None, declared_origin=None):
    """Pure calculation used by projection and previews; returns values + provenance.

    `declared_remaining` é a «Qtd em falta» escrita no registo manual; `declared_produced` e `declared_origin`
    são a produção que o cálculo conhecia quando foi escrita e a fonte dela. Saldo = máx(escrito − produção
    registada depois, 0), no máximo a QTD. Só se desconta quando a fonte de agora é da mesma família
    (EVIDENCE); sem produção conhecida nesse momento ou com outra fonte, não se desconta nada. Cada saldo
    guarda a produção medida e a fonte dela (`measured`, `measured_origin`), com ou sem «Qtd em falta».
    """
    v = dict(values); raw = raw or {}; today = today or date.today(); rules = {}
    q = quantity(v.get('quantity_required')); length = positive(v.get('length_mm'))
    declared = quantity(declared_remaining); typed_at = quantity(declared_produced)
    v['quantity_required'] = q
    ops = {str(op['operation']): dict(op) for op in operations}
    mark = abocardar(v.get('abocardar'))
    primary = 'corte' if area=='perfis' else str(v.get('operation') or '').strip()
    applicable = [primary]
    if area=='perfis' and mark is not False: applicable.append('abocardar')
    if area=='cantoneiras' and str(v.get('operation_detail') or '').strip() not in ('','0'):
        applicable.append(str(v['operation_detail']).strip())
    resolved = {}
    for code in dict.fromkeys(applicable):
        op = ops.get(code, {'operation': code})
        macro = excel_counter(raw, 'Ser.', q) if code=='corte' else raw.get('Aboc.') if code=='abocardar' else op.get('macro_quantity')
        original_primary = str(raw.get('1ª Oper.') or '').strip()
        other_operation_excel = False
        if area=='cantoneiras' and code==primary and macro is None:
            # An explicit operation counter is already scoped by the evidence
            # producer. The unscoped legacy fallback belongs to the original
            # primary operation, even after the planner changes the sequence.
            if not original_primary or original_primary==code:macro=excel_counter(raw, 'Maq.', q)
            else:other_operation_excel=quantity(raw.get('Maq.')) is not None
        result = production_source(op, macro, compatible=compatible, local_initial=local_initial)
        if other_operation_excel and result['value'] is None:
            result['reason'] += f' O acumulado Excel pertence à operação {original_primary}.'
        result.update(measured=result['value'], measured_origin=result['origin'])
        if code == primary and declared is not None and q is not None:
            measured = result['value']
            same = EVIDENCE.get(result['origin']) is not None and EVIDENCE.get(result['origin']) == EVIDENCE.get(declared_origin)
            since = max(0, measured - typed_at) if same and measured is not None and typed_at is not None else 0
            # Outra fonte (ex.: escrita com o contador do Excel, agora conta o OCR validado): não se desconta, mas
            # fica dito ao lado do campo para o valor escrito não ficar esquecido.
            result['declared_source_changed'] = bool(typed_at is not None and EVIDENCE.get(declared_origin)
                                                     and EVIDENCE.get(result['origin']) and not same)
            result.update(value=q - max(min(declared, q) - since, 0), origin=DECLARED_ORIGIN, reason=None)
        made = result['value']
        result.update(operation=code, remaining=max(q-made,0) if q is not None and made is not None else None,
                      percent=100*made/q if q and made is not None else None,
                      excess=max(made-q,0) if made is not None and q is not None else None)
        resolved[code] = result

    def put(field, value, formula, unit=None, inputs=None, source=None, reason=None):
        v[field] = value
        rules[field] = {'formula': formula, 'unit': unit, 'inputs': inputs or {}, 'source': source,
                        'contract': CONTRACT, 'reason': reason if value is None else None}
        if value is None and not rules[field]['reason']: rules[field]['reason']='Entradas necessárias desconhecidas.'

    principal = resolved[primary]
    quantity_reason = 'Quantidade necessária ausente ou inválida; deve ser um inteiro não negativo.' if q is None else None
    length_reason = 'Comprimento da peça ausente ou inválido; deve ser positivo.' if length is None else None

    def balance_reason(result):
        return quantity_reason or result['reason']

    def percentage_reason(result):
        if result is None:
            return 'Operação não necessária.'
        return quantity_reason or ('Quantidade necessária zero.' if q == 0 else result['reason'])

    def production_inputs(result, operation):
        result = result or {}
        event_fields = ('source','instance_id','sheet_uid','record_id','row_index',
                        'child_key','operation','quantity','validated')
        return {'operation':operation,'ocr_total':result.get('ocr'),'excel_total':result.get('excel'),
                'local_initial':bool(local_initial),'compatible':bool(compatible),
                'ocr_events':[{k:f[k] for k in event_fields if k in f} for f in result.get('records',[])],
                'coverage_reasons':result.get('coverage_reasons',[])}

    put('remaining', principal['remaining'], 'max(Q − produção principal, 0)', 'un.',
        {'Q':q,'produced':principal['value']}, principal['origin'],balance_reason(principal))
    put('production_excess',principal['excess'],'max(produção − Q, 0)','un.',
        {'Q':q,'produced':principal['value']},principal['origin'],balance_reason(principal))
    put('quantity_to_plan', principal['remaining'], 'Saldo da operação planeada', 'un.',
        {'Q':q,'produced':principal['value'],'operation':primary},principal['origin'],balance_reason(principal))
    if area=='perfis':
        for code,field in [('corte','cut'),('abocardar','boc')]:
            r=resolved.get(code)
            inputs=production_inputs(r,code)
            if code=='abocardar': inputs['abocardar']=v.get('abocardar')
            put(field, r['value'] if r else None, 'Produção selecionada da operação', 'un.', inputs,
                source=r['origin'] if r else 'Não aplicável',reason=r['reason'] if r else 'Operação não necessária.')
            put(field+'_pct',r['percent'] if r else None,'100 × produção / Q','%',{'Q':q,field:r['value'] if r else None},
                source=r['origin'] if r else 'Não aplicável',reason=percentage_reason(r))
        boc=resolved.get('abocardar')
        put('boc_remaining',boc['remaining'] if boc else 0,'max(Q − B, 0) se necessário; 0 se não aplicável','un.',
            {'Q':q,'B':boc['value'] if boc else None,'abocardar':v.get('abocardar')},
            boc['origin'] if boc else 'Não aplicável',balance_reason(boc) if boc else None)
        final = v['boc_pct'] if mark is True else v['cut_pct'] if mark is False else None
        put('final_pct',final,'Percentagem da operação final','%',
            {'abocardar':v.get('abocardar'),'cut_pct':v['cut_pct'],'boc_pct':v['boc_pct']},
            source=rules['boc_pct' if mark else 'cut_pct']['source'] if mark is not None else 'Operação final por confirmar',
            reason='Necessidade de abocardar por confirmar.' if mark is None else rules['boc_pct' if mark else 'cut_pct']['reason'])
    else:
        put('made',principal['value'],'Produção selecionada da operação principal','un.',production_inputs(principal,primary),source=principal['origin'],reason=principal['reason'])
        put('made_pct',principal['percent'],'100 × produção / Q','%',{'Q':q,'made':principal['value']},source=principal['origin'],reason=percentage_reason(principal))
        for code,r in resolved.items():
            v['ocr_op_'+code]=r['ocr']
        ocr_inputs=production_inputs(principal,primary)
        ocr_inputs.pop('excel_total');ocr_inputs.pop('local_initial')
        put('ocr_quantity',principal['ocr'],'Soma dos eventos OCR únicos com cobertura válida','un.',ocr_inputs,
            'OCR validado', '; '.join(principal['coverage_reasons']) or 'Sem produção OCR utilizável para a operação principal.')
        secondary = next((r for code,r in resolved.items() if code!=primary),None)
        put('secondary_remaining',secondary['remaining'] if secondary else 0,'Saldo separado da segunda operação','un.',
            {'Q':q,'produced':secondary['value'] if secondary else None,'operation_detail':v.get('operation_detail')},
            secondary['origin'] if secondary else 'Não aplicável',balance_reason(secondary) if secondary else None)
    put('total_length',q*length if q is not None and length else None,'Q × L','mm',{'Q':q,'L':length},source='Quantidade e comprimento atuais da peça',reason=quantity_reason or length_reason)
    put('total_m',v['total_length']/1000 if v['total_length'] is not None else None,'Q × L / 1000','m',{'Q':q,'L':length},source='Quantidade e comprimento atuais da peça',reason=quantity_reason or length_reason)
    remaining=v['remaining']
    put('remaining_m',0 if remaining==0 else remaining*length/1000 if remaining is not None and length else None,'saldo × L / 1000','m',{'saldo':remaining,'L':length},source=principal['origin'],reason=balance_reason(principal) or length_reason)
    unit,property_rule=section(v,sections)
    section_inputs={'material_type':v.get('material_type'),'profile':v.get('profile')}
    section_inputs.update({k:positive(v.get(k)) for k in GEOMETRY.get(key(v.get('material_type')),('',()))[1]})
    put('section_unit',unit,property_rule.get('formula'),'mm²',section_inputs,source=property_rule,reason=property_rule.get('reason'))
    put('section_total',unit*q if unit is not None and q is not None else None,'A × Q','mm²',{'A':unit,'Q':q},source=property_rule,reason=quantity_reason or property_rule.get('reason'))
    put('section_pending',0 if remaining==0 else unit*remaining if unit is not None and remaining is not None else None,'A × saldo','mm²',{'A':unit,'saldo':remaining},source=property_rule,reason=balance_reason(principal) or property_rule.get('reason'))
    stock=positive(v.get('stock_length_mm'))
    manual = stock is not None and v.get('stock_length_origin')!='Sugestão automática'
    if not manual: stock=12000 if length and length>6000 else 6000 if length else None
    v['stock_length_origin']='Substituição manual/importada' if manual else 'Sugestão automática'
    put('stock_length_mm',stock,'12000 se L > 6000; 6000 caso contrário; substituição explícita prevalece','mm',{'L':length,'manual_stock_length_mm':stock if manual else None},v['stock_length_origin'],length_reason)
    pieces=math.floor(stock/length) if stock and length else 0
    put('bars',0 if remaining==0 else math.ceil(remaining/pieces) if remaining is not None and pieces else None,
        'ceil(saldo / floor(S / L))','un.',{'saldo':remaining,'S':stock,'L':length},source=principal['origin']+' · '+v['stock_length_origin'],reason='A peça não cabe no perfil inteiro.' if stock and length and length>stock else balance_reason(principal) or length_reason or ('Comprimento do perfil inteiro ausente ou inválido.' if stock is None else None))
    weight_unit=None; weight_source=None; weight_reason=None
    if area=='cantoneiras':
        candidates=(weights or {}).get(key(v.get('profile')),[])
        rates={positive(r.get('kg_m')) for r in candidates}-{None}
        kg_m=next(iter(rates)) if len(rates)==1 else None
        weight_source=candidates
        weight_inputs={'profile':v.get('profile'),'kg_m':kg_m,'L':length}
        # Sem um kg/m único na Tabela de pesos, a cantoneira L a×b×t pesa-se pela geometria (08/10, F08).
        # O «Peso un. Kg» do Excel continua fora: é um PROCV aproximado, errado em vários perfis (auditoria A5-F6).
        angle=angle_kg_m(v.get('profile')) if kg_m is None else None
        if angle:
            kg_m=angle['kg_m']
            weight_source={'rule':ANGLE_ORIGIN,'designation':v.get('profile'),'kg_m':kg_m,'formula':ANGLE_FORMULA,
                           'table':candidates}
            weight_inputs.update(kg_m=kg_m,a=angle['a'],b=angle['b'],t=angle['t'],density_kg_m3=STEEL_DENSITY)
        if kg_m is not None and length: weight_unit=kg_m*length/1000
        weight_reason='Pesos divergentes para a designação exata.' if len(rates)>1 else 'Sem peso exato ou comprimento conhecido.'
    else:
        # Aço 7850 kg/m³ pela Qual. ou, sem Qual., por defeito (07/10/2026: só para o peso).
        if density is None and (not str(v.get('grade') or '').strip() or re.match(r'^(S\d|C\d|B\d|DX\d)',str(v.get('grade') or '').upper())): density=7850
        if unit is not None and length and positive(density): weight_unit=unit/1e6*length/1000*density
        weight_source={'density_kg_m3':density,'rule':'Met2 Planeamento!DB/DC · aço 7850 kg/m³' if density==7850 else 'Densidade explícita' if positive(density) else 'Densidade por confirmar'}
        weight_inputs={'A':unit,'L':length,'density_kg_m3':density}
        weight_reason='Área, comprimento ou densidade do material por confirmar.'
    put('weight_unit',weight_unit,'kg/m × L / 1000' if area=='cantoneiras' else 'A / 1000000 × L / 1000 × densidade','kg',weight_inputs,source=weight_source,reason=weight_reason)
    put('weight',weight_unit*remaining if weight_unit is not None and remaining is not None else None,'peso unitário × saldo principal','kg',{'weight_unit':weight_unit,'remaining':remaining},source=weight_source,reason=balance_reason(principal) if remaining is None else weight_reason)
    v['original_description']=raw.get('Des. Material') or raw.get('Descrição do Perfil') or raw.get('Descrição')
    description_inputs={k:v[k] for k in ('material_type','profile','grade') if v.get(k)}
    description_parts=[str(value) for value in description_inputs.values()]
    for field,label in [('outer_diameter_mm','Ø'),('width_mm','Largura'),('height_mm','Altura'),('thickness_mm','Esp.'),('length_mm','Comp.'),('angle_deg','Ângulo')]:
        if v.get(field) is not None:
            description_inputs[field]=v[field]
            description_parts.append(f'{label} {v[field]}'+('°' if field=='angle_deg' else ' mm'))
    description=' · '.join(description_parts)
    put('description',description or None,'Concatenação dos dados técnicos conhecidos',inputs=description_inputs,
        source='LayoutPlaneamentoPerfis.xlsx · Folha1!L2' if area=='perfis' else 'Contrato G12 · dados técnicos conhecidos',
        reason='Sem dados técnicos conhecidos para compor a descrição.')
    if area=='cantoneiras':
        current_description=v.get('material_description')
        material_description=current_description or v['original_description'] or description or None
        put('material_description',material_description,'Texto atual da peça; original preservado separadamente; composição técnica quando não existe texto',
            inputs={'current_description':current_description,'original_description':v['original_description'],'technical_description':description or None},
            source='Texto original importado' if material_description and material_description==v['original_description'] else 'Dados atuais da peça',
            reason='Sem descrição importada, local ou dados técnicos conhecidos.')
    year,week,period_source=planning_dates.period(v,area=area,operation=primary,cantoneiras_week=v.get('imported_week'))
    if area=='cantoneiras' and year is None and week is not None and period_source.startswith('Semana W importada'):
        # Mesmo ano que a capacidade deduz para a semana W (07/10/2026): o mais recente sem saltar para o futuro.
        deduced=planning_dates.infer_iso_year(week,today,prefer_past=True)
        if deduced is not None:year,week,period_source=deduced,planning_dates.positive_week(week),'Semana W importada — ano deduzido'
    period_inputs={k:v.get(k) for k in ('expected_date','cut_date','planned_year','planned_week','operation')}
    put('expected_week',f'{year}-W{week:02}' if year is not None else None,'Ano e semana ISO da previsão aplicável',inputs=period_inputs,source=period_source,reason=period_source if year is None else None)
    put('expected_year',year,'Ano ISO da previsão aplicável',inputs=period_inputs,source=period_source,reason=period_source if year is None else None)
    picking=planning_dates.picking_deadline(v.get('picking_week'),v.get('picking_year'),anchor=v.get('cut_date') or today) if area=='perfis' and not v.get('picking_conflict') else None
    inferred_year=picking['year'] if picking and picking['provisional'] else None
    put('picking_deadline',picking['at'] if picking else None,'Segunda-feira da semana ISO de Picking às 08:00 em Lisboa; sem ano, o ano em que a semana fica mais perto da Data Corte (ou de hoje)',
        inputs={'week':v.get('picking_week'),'year':v.get('picking_year'),'inferred_year':inferred_year},
        source=picking['origin'] if picking else 'Picking por confirmar',reason='Semana Picking ausente ou em conflito.' if not picking else None)
    put('picking_date',picking['at'][:10] if picking else None,'Data local da segunda-feira da semana de Picking',
        inputs={'week':v.get('picking_week'),'year':v.get('picking_year'),
                'inferred_year':inferred_year,
                'origin':v.get('picking_origin'),'evidence':v.get('picking_evidence') or []},
        source=v.get('picking_origin') or (picking['origin'] if picking else 'Picking por confirmar'),
        reason='Semanas de Picking contraditórias.' if v.get('picking_conflict') else 'Semana/ano de Picking por confirmar.' if not picking else None)
    v['picking_deadline_provisional']=bool(picking and picking['provisional'])
    v['picking_year_inferred']=inferred_year
    cut_due=v.get('expected_date') or (v.get('cut_date') if area=='perfis' and principal['remaining'] not in (None,0) else None)
    deadline=(picking['at'] if picking else None) or cut_due or v.get('planned_finish_date') or v.get('delivery_date')
    deadline_source='Picking' if picking else 'Previsão de corte' if cut_due else 'Fim previsto da Produção' if v.get('planned_finish_date') else 'Entrega' if v.get('delivery_date') else None
    past=None
    try:past=date.fromisoformat(str(deadline)[:10])<today if deadline else None
    except ValueError:pass
    balances=[r['remaining'] for r in resolved.values()]
    unknown=any(x is None for x in balances) or (area=='perfis' and mark is None)
    pending=any(x is not None and x>0 for x in balances)
    deadline_inputs={'deadline':deadline,'deadline_source':deadline_source,
                     'local_date':today.isoformat(),'operation_balances':{code:r['remaining'] for code,r in resolved.items()},
                     'operations_known':not (area=='perfis' and mark is None)}
    put('overdue',past and pending if past is not None and not unknown else None,'Prazo local ultrapassado e saldo positivo',
        inputs=deadline_inputs,source=deadline_source,reason='Saldo desconhecido.' if unknown else 'Sem data válida.')
    put('deadline_status','Conclusão por confirmar' if unknown else 'Sem data' if past is None else 'Prazo ultrapassado' if past and pending else 'Trabalho concluído' if not pending else 'Dentro do prazo',
        'Comparação de prazo e saldos por operação',inputs=deadline_inputs,source=deadline_source or 'Política de prazo sem data aplicável')
    return {'values':v,'rules':rules,'operations':list(resolved.values()),'contract':CONTRACT}
