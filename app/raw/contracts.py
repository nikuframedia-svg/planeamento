"""Stable field identifiers, types and dimensions shared by query, formulas and UI."""
from .. import planning, planning_catalogs as catalogs, planning_raw as legacy

GROUPS={'identity':'Identificação','quantity':'Quantidades','technical':'Características','work':'Preparação','material':'Material','production':'Produção OCR e acompanhamento','calculated':'Colunas calculadas'}
NUMBERS={'id','picking_week','quantity_required','cut','boc','cut_pct','boc_pct','final_pct','remaining','boc_remaining','outer_diameter_mm','width_mm','height_mm','thickness_mm','length_mm','angle_deg','section_total','section_unit','quantity_to_plan','hours_pct','weight','total_length','stock_length_mm','bars','ocr_cut','ocr_boc','ocr_quantity','made','made_pct','remaining_m','speed_m_h','theoretical_hours','weight_unit','quantity','hours_worked','known_records','unassigned_records','available_hours','planned_hours','free_hours','occupancy','unknown_load','actual_hours','week','year','known_remaining_total','remaining_known_lines','lines_total'}
NUMBERS.update({'reference_equivalent_shifts','reference_hours','macro_hours','reference_available_hours','reference_shifts','reference_hours_per_shift','equivalent_shifts','area_load','metres','draft_hours','draft_unknown','capacity_total','capacity_free','pending_quantity','pending_metres','pending_area'})
DATES={'cut_date','delivery_date','expected_date','production_date','last_activity'}
EXTRA=[('deadline_status','Prazo e trabalho pendente','work',None),('overdue','Prazo ultrapassado','work',None),('status','Estado CPIS','identity',None),('preparation_status','Preparação','work',None),('remaining_m','Metros por realizar','quantity',None),('section_unit','Área unitária comprovada (mm²)','technical',None),('ocr_cut','Cortada · OCR validado','production',None),('ocr_boc','Abocardada · OCR validado','production',None),('last_activity','Última atividade na OF','production',None),('unassigned_records','Registos por associar na OF','production',None),('execution_status','Execução acompanhada','production',None)]
CANT=[s for s in legacy.SPECS if s[0] not in {'abocardar','cut','boc','cut_pct','boc_pct','final_pct','boc_remaining','section_total','bars'}]
CANT += [('made','Produção principal','quantity',None),('made_pct','% realizado','quantity',None),('operation','1.ª operação','work','select'),('operation_detail','Operação adicional','work','select'),('speed_m_h','Velocidade aplicada (m/h)','work',None),('theoretical_hours','Horas previstas','work',None),('ocr_quantity','Produção OCR associada','production',None)]
CANT_DEFAULT=['of','ov','component_ref','sku_family','sku_family_status','cut_date','material_type','quantity_required','material_description','length_mm','operation','operation_detail','team','pavilion']
CANT += [('material_description','Descrição do material','identity',None),('macro_closed','Fechado · macro','quantity',None),('imported_week','Semana W · macro','work',None)]
EXTRA += [('rate_source','Origem da taxa aplicada','work',None),('applied_rate_value','Taxa aplicada','work',None),('applied_rate_unit','Unidade da taxa','work',None)]
EXTRA += [('planned_week','Semana de planeamento','work','number'),('planned_year','Ano de planeamento','work','number')]
EXTRA += [('weight_unit','Peso unitário (kg)','technical',None),
          ('total_m','Comprimento total necessário (m)','technical',None),
          ('production_excess','Excesso de produção principal (un.)','technical',None),
          ('section_pending','Área pendente de corte (mm²)','technical',None)]
CANT += [('secondary_remaining','Saldo da segunda operação (un.)','quantity',None)]
NUMBERS.update({'applied_rate_value','imported_week','planned_week','planned_year'})
NUMBERS.update({'total_m','production_excess','section_pending','secondary_remaining','planning_remaining'})
DATES.update({'planned_start_date','planned_finish_date','picking_date'})
EXTRA += [('planning_remaining','Saldo para calendarizar (un.)','quantity',None),
          ('planning_balance_origin','Origem do saldo de planeamento','quantity',None),
          ('planning_balance_provisional','Saldo provisório','quantity',None),
          ('planned_start_date','Início previsto da Produção','work',None),
          ('planned_finish_date','Fim previsto da Produção','work',None),
          ('picking_origin','Origem do Picking','work',None),
          ('picking_deadline','Necessidade de Picking','work',None)]
UNITS={k:'un.' for k in ('quantity_required','cut','boc','remaining','boc_remaining','quantity_to_plan','ocr_cut','ocr_boc','ocr_quantity','made','quantity')}
UNITS.update({k:'%' for k in ('cut_pct','boc_pct','final_pct','hours_pct','made_pct','occupancy')})
UNITS.update({k:'mm' for k in ('outer_diameter_mm','width_mm','height_mm','thickness_mm','length_mm','total_length','stock_length_mm')})
UNITS.update(reference_hours='h',macro_hours='h',reference_available_hours='h',equivalent_shifts='turnos',area_load='mm²',metres='m',pending_quantity='un.',pending_area='mm²',pending_metres='m')
UNITS.update(section_total='mm²',section_unit='mm²',weight='kg',remaining_m='m',speed_m_h='m/h',theoretical_hours='h',available_hours='h',planned_hours='h',free_hours='h',hours_worked='h',actual_hours='h',angle_deg='°')
UNITS.update(weight_unit='kg',total_m='m',production_excess='un.',section_pending='mm²',secondary_remaining='un.')
UNITS.update(planning_remaining='un.')
UNITS.update(bars='un.',draft_hours='h',reference_equivalent_shifts='turnos',reference_shifts='turnos',reference_hours_per_shift='h/turno')


def fields(area='perfis',dataset='planning'):
    planning.check_area(area)
    specs=(legacy.SPECS if area=='perfis' else CANT)+[s for s in EXTRA if area=='perfis' or s[0] not in ('ocr_cut','ocr_boc','section_unit','section_pending')]
    if dataset in ('production','original'):
        specs=[(k,l,'production',None) for k,l in [('of','OF'),('ov','OV'),('component_ref','Referência'),('machine','Máquina'),('operation','Operação'),('production_date','Data de produção'),('quantity','Quantidade validada'),('length_mm','Comprimento (mm)'),('hours_worked','Horas declaradas'),('source','Sistema de origem'),('sheet','Folha'),('association_status','Associação')]]
    if dataset=='production_hours':specs=[(k,l,'production',None) for k,l in [('machine','Máquina da folha'),('production_date','Data de produção'),('hours_worked','Horas declaradas na folha'),('sheet','Folha'),('source','Sistema de origem')]]
    if dataset=='capacity':
        specs=[(k,l,'work',None) for k,l in [('machine','Máquina'),('week','Semana ISO'),('year','Ano ISO'),('available_hours','Horas disponíveis'),('planned_hours','Carga prevista (h)'),('actual_hours','Horas reais declaradas'),('free_hours','Horas livres'),('occupancy','Ocupação (%)'),('unknown_load','Peças por confirmar')]]
    if dataset in ('capacity','capacity_machines','capacity_items'):
        spec=[('machine','Máquina'),('machine_key','Recurso'),('bucket_key','Período / recurso'),('week','Semana ISO'),('year','Ano ISO'),
              ('quantity','Quantidade abrangida'),('metres','Metros'),('area_load','Área (mm²)'),('weight','Peso conhecido (kg)'),
              ('planned_hours','Carga prevista (h)'),('reference_hours','Estimativa segundo a macro (h)'),('macro_hours','Horas guardadas no Excel'),
              ('available_hours','Horas disponíveis confirmadas'),('reference_available_hours','Horas disponíveis · sugestão'),('reference_shifts','Turnos · sugestão'),('reference_hours_per_shift','Horas/turno · sugestão'),
              ('free_hours','Horas livres'),('occupancy','Ocupação (%)'),('equivalent_shifts','Turnos equivalentes'),('reference_equivalent_shifts','Turnos equivalentes segundo a macro'),('actual_hours','Horas reais declaradas'),
              ('unknown_load','Operações por confirmar'),('lines_total','Operações abrangidas'),('draft_hours','Carga dos rascunhos conhecida (h)'),('draft_unknown','Rascunhos por confirmar'),
              ('capacity_total','Capacidade física total'),('capacity_free','Capacidade física livre'),('pending_quantity','Peças pendentes'),('pending_metres','Metros pendentes'),('pending_area','Área pendente (mm²)')]
        if dataset=='capacity_items':spec += [('of','OF'),('component_ref','Referência'),('area','Área'),('operation','Operação'),('status','Estado CPIS'),('primary_operation','Operação principal'),('draft','Rascunho'),('quantity_required','Necessário')]
        specs=[(k,l,'work',None) for k,l in spec]
    if dataset=='orders':
        specs=[(k,l,'identity',None) for k,l in [('of','OF'),('ov','OV'),('customer','Cliente'),('status','Estado CPIS'),('quantity_required','Quantidade abrangida'),('remaining','Saldo integral (quando todas as peças são conhecidas)'),('known_remaining_total','Saldo das peças com informação conhecida'),('remaining_known_lines','Peças com saldo conhecido'),('lines_total','Peças abrangidas'),('unassigned_records','Registos por associar'),('last_activity','Última atividade na OF')]]
    from .registration import enabled as free_entry
    if dataset=='planning' and free_entry() and not any(s[0]=='operation' for s in specs):specs.append(('operation','Operação','work','select'))
    if dataset=='planning' and free_entry():specs=[(k,l,g,'number' if k=='quantity_to_plan' else 'text' if k in ('customer','ov','designation','delivery_date') else t) for k,l,g,t in specs]
    if dataset=='planning' and area=='cantoneiras':specs += [('sku_family','Família de SKU','identity',None),('sku_family_status','Estado da família de SKU','identity',None)]
    if dataset=='planning':specs=[(k,{'cut':'Quantidade cortada','boc':'Quantidade abocardada','hours_pct':'Ocupação da máquina/semana (%)'}.get(k,l),g,t) for k,l,g,t in specs]
    if dataset=='planning' and area=='perfis':
        index=next(i for i,s in enumerate(specs) if s[0]=='picking_week')
        specs.insert(index+1,('picking_date','Data de Picking','identity',None))
    if dataset=='planning' and area=='perfis':specs += [('theoretical_hours','Horas previstas de corte','work',None)]
    if dataset=='capacity_items':specs += [('rate_source','Origem da taxa aplicada','work',None),('applied_rate_value','Taxa aplicada','work',None)]
    if dataset in ('planning','orders'):
        specs += [('planning_active','Planeamento ativo','identity',None),('closure_reason','Origem do fecho','identity',None)]
    if area=='cantoneiras' and dataset=='planning':
        # Sem Picking no registo das cantoneiras (06/10/2026): a coluna fica visível, mas só de leitura.
        specs=[(k,l,g,None if k=='picking_week' else t) for k,l,g,t in specs]
        specs=[(k,{'remaining':'Qtd. falta','quantity_required':'QTD','material_type':'Tipo de material','length_mm':'Comprimento (mm)','operation_detail':'2.ª operação','remaining_m':'Metros em falta','machine':'Máquina','ocr_quantity':'OCR · operação principal'}.get(k,l),g,t) for k,l,g,t in specs]
        cat=catalogs.catalog(area)
        codes={x['value']:x['label'] for x in cat['operations']+cat['additional_operations'] if x['countable']}
        specs += [('ocr_op_'+k,'OCR · '+label,'production',None) for k,label in codes.items()]
    return [dict(id=k,label=l,short_label={'length_mm':'Comp. (mm)','operation':'1.ª op.','operation_detail':'2.ª op.'}.get(k) if area=='cantoneiras' and dataset=='planning' else None,group=g,type=t or 'readonly',data_type='number' if k.startswith('ocr_op_') or k in NUMBERS and k!='id' else 'date' if k in DATES else 'boolean' if k in ('planning_active','planning_balance_provisional','abocardar','material_requested','overdue','draft','primary_operation') else 'text',editable=bool(t),unit='un.' if k.startswith('ocr_op_') else UNITS.get(k),pinned=k in ('of','ov','component_ref'),default_visible=(k in CANT_DEFAULT if area=='cantoneiras' and dataset=='planning' else g!='technical')) for k,l,g,t in specs]


def columns(area='perfis'):
    cols=fields(area)
    return {'area':area,'columns':cols,'default_widths':dict(zip(CANT_DEFAULT,[110,110,130,140,220,115,120,60,245,95,82,82,125,75])) if area=='cantoneiras' else {},'default_columns':CANT_DEFAULT if area=='cantoneiras' else list(dict.fromkeys(['of','ov','component_ref']+[f['id'] for f in cols if f['default_visible']])),'groups':GROUPS,'catalog':catalogs.catalog(area),'page_sizes':[25,50,100,250,500],'pinned':['of','ov','component_ref']}


def mapping(area='perfis',dataset='planning'):
    return {f['id']:f for f in fields(area,dataset)}
