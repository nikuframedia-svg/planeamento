"""Versioned independent workbook catalogues and the common field contract."""
from __future__ import annotations
import re
import hashlib
import zipfile
from pathlib import Path
from functools import lru_cache
from xml.etree import ElementTree as ET
from datetime import date
from decimal import Decimal, InvalidOperation
from . import planning


def clean(value):
    if value is None: return ''
    if isinstance(value, float) and value.is_integer(): value=int(value)
    value=re.sub(r'\s+', ' ', str(value).replace('_x000D_', ' ')).strip()
    return '' if value.startswith(('#', '=')) or value in ('-', '—') else value


def key(value):
    return clean(value).casefold().replace('rectangular','retangular')


def family(material):
    value=key(material)
    return value


# Retained in storage and the legacy API, absent from the current editor.
RETIRED_FIELDS=frozenset(('chanfro','ponteira',
    'finish_week','finish_year','weekly_capacity_hours','material_available_date','material_lot',
    'material_request_date'))


def abocardar_mark(value):
    if value is True or str(value).strip().upper()=='X':return 'X'
    if value is False or value in (None,'','-'):return '-'
    return str(value).strip()


def fields():
    from .raw.registration import enabled as free_entry
    specs=[
        ('component_ref','Referência','text',None,'piece'),('identity_discriminator','Variante','text',None,'piece'),
        ('material_type','Tipo de material','select',None,'piece'),('profile','Perfil normalizado','select',None,'piece'),
        ('custom_profile','Perfil especial','boolean',None,'piece'),('special_profile','Designação do perfil especial','text',None,'piece'),
        ('geometry','Geometria','select',None,'piece'),('grade','Qualidade','text',None,'piece'),
        ('outer_diameter_mm','Diâmetro exterior','number','mm','piece'),('width_mm','Largura / lado','number','mm','piece'),
        ('height_mm','Altura','number','mm','piece'),('thickness_mm','Espessura','number','mm','piece'),
        ('length_mm','Comprimento','number','mm','piece'),('angle_deg','Ângulo','number','°','piece'),
        ('quantity_required','Quantidade necessária','number','un.','piece'),
        ('operation','Operação principal','select',None,'operation'),('operation_detail','Operação adicional / indicação','select',None,'operation'),
        ('machine','Máquina','select',None,'operation'),('team','Equipa','select',None,'operation'),
        ('quantity_to_plan','Quantidade a planear','number','un.','operation'),
        ('abocardar','Abocardar','checkbox',None,'operation'),('chanfro','Chanfro — indicação original','text',None,'operation'),
        ('ponteira','Ponteira — indicação original','text',None,'operation'),('other_operations','Outras operações','text',None,'operation'),
        ('pavilion','Pavilhão','text',None,'operation'),('cut_date','Data Corte','date',None,'operation'),
        ('expected_date','Previsão de execução','date',None,'operation'),('picking_week','Picking — semana','number',None,'operation'),
        ('planned_week','Semana de planeamento','number',None,'operation'),('planned_year','Ano de planeamento','number',None,'operation'),
        ('picking_year','Picking — ano','number',None,'operation'),('finish_week','Finalização — semana','number',None,'operation'),
        ('finish_year','Finalização — ano','number',None,'operation'),('weekly_capacity_hours','Capacidade semanal','number','h','operation'),
        ('material_request_date','Requisição de material','date',None,'operation'),('material_available_date','Disponibilidade prevista de material','date',None,'operation'),
        ('material_requested','Requisitado?','tristate',None,'operation'),('stock_length_mm','Comprimento unitário do perfil','number','mm','operation'),
        ('material_lot','Lote / referência de material','text',None,'operation'),('notes','Observações locais','textarea',None,'operation')]
    main_piece={'component_ref','material_type','profile','custom_profile','special_profile',
                'geometry','outer_diameter_mm','width_mm','height_mm','thickness_mm','length_mm','quantity_required'}
    names={'component_ref':'Referência da peça','identity_discriminator':'O que distingue esta peça?',
           'material_type':'Tipo de perfil nível 1','profile':'Tipo de perfil nível 2','custom_profile':'Outro perfil','special_profile':'Designação do perfil',
           'geometry':'Forma da secção','grade':'Qualidade do material','length_mm':'Comprimento','angle_deg':'Ângulo de corte',
           'quantity_required':'Quantidade total necessária','operation':'Operação',
           'quantity_to_plan':'Quantidade a preparar agora'}
    help_text={'component_ref':'Código que identifica a peça no desenho.',
               'quantity_required':'Total desta peça necessário para a OF.',
               'quantity_to_plan':'Quantidade que pretendes preparar para esta operação.',
               'profile':'Depende do tipo de perfil nível 1.',
               'identity_discriminator':'Por exemplo, revisão do desenho ou variante que distingue peças com a mesma referência.',
               'grade':'Qualidade indicada no desenho, por exemplo S355.',
               'picking_year':'Deixa vazio se o ano ainda não for conhecido.'}
    result=[]
    for index,(i,l,t,u,s) in enumerate(specs):
        result.append(dict(id=i,label=names.get(i,l),type=t,unit=u,scope=s,help=help_text.get(i,''),
            group='cut' if i in ('angle_deg','grade','length_mm') else 'piece' if i in main_piece or i=='identity_discriminator' else 'work' if i in ('operation','machine','operation_detail') else 'extra',
            order={'angle_deg':0,'grade':1,'length_mm':2,'abocardar':0}.get(i,index+10),
            editor_visible=i not in RETIRED_FIELDS and (i!='quantity_to_plan' or free_entry()),
            representation={'checked':'X','unchecked':'-'} if i=='abocardar' else None,
            required_on_ready=i in ('component_ref','material_type','profile','operation','quantity_required','quantity_to_plan'),
            visibility={'special_profile':'custom_profile','geometry':'unresolved_geometry',
                        'outer_diameter_mm':'geometry','width_mm':'geometry','height_mm':'geometry','thickness_mm':'geometry'}.get(i,'always')))
    return result


# Registo manual (pedido do Luís, 06/10/2026, noite): a primeira secção tem SEMPRE todas as colunas do
# Excel de cada setor, pela mesma ordem (Met2_Plan_Perfis a azul; folha das cantoneiras com o X), sem
# esconder nada pelo tipo de material. A Máquina entra porque sem ela a Carteira não deixa planear.
# Perfil especial e geometria são auxiliares e vão para «Mais opções». OF e OV ficam na secção da ordem.
FIRST_SECTION={
    'perfis':['cut_date','component_ref','material_type','profile','quantity_required','outer_diameter_mm',
              'width_mm','height_mm','thickness_mm','length_mm','angle_deg','grade','abocardar',
              'picking_week','picking_year','team','pavilion','machine'],
    'cantoneiras':['cut_date','component_ref','material_type','quantity_required','profile','length_mm',
                   'operation','operation_detail','team','pavilion','machine']}
WORK_SECTION={'perfis':['operation'],'cantoneiras':[]}
HIDDEN_BY_AREA={'perfis':{'operation_detail'},'cantoneiras':{'abocardar','picking_week','picking_year'}}
LABELS_BY_AREA={
    'perfis':{'cut_date':'Data Corte','component_ref':'Referência','material_type':'Tipo de Material',
              'profile':'Designação Perfil','quantity_required':'QTD','outer_diameter_mm':'Ø Externo',
              'width_mm':'Largura','height_mm':'Altura','thickness_mm':'Espessura','length_mm':'Comp.',
              'angle_deg':'Ang.','grade':'Qual.','abocardar':'Abocardar','picking_week':'Picking semana',
              'picking_year':'Picking ano','team':'Equipa','pavilion':'Pav.','machine':'Máquina'},
    'cantoneiras':{'cut_date':'Data Corte','component_ref':'Ref.','material_type':'Tipo de material',
                   'quantity_required':'QTD','profile':'Des. Material','length_mm':'Comp.',
                   'operation':'1.ª Oper.','operation_detail':'2.ª Oper.','team':'Equipa','pavilion':'Pav.',
                   'machine':'Máquina'}}


def arrange(fields_list, area):
    """Groups, order, labels and visibility of the editor fields for one sector.

    Os campos da primeira secção ficam sempre visíveis (visibility='always'): as dimensões deixam de
    depender do tipo de material, como no Excel.
    """
    first,work=FIRST_SECTION.get(area),WORK_SECTION.get(area,[])
    if not first:return fields_list
    for f in fields_list:
        i=f['id']
        if i in first:f.update(group='piece',order=first.index(i),visibility='always')
        elif i in work:f.update(group='work',order=100+work.index(i))
        else:f.update(group='extra',order=200+f['order'])
        if i in HIDDEN_BY_AREA.get(area,()):f['editor_visible']=False
        f['label']=LABELS_BY_AREA.get(area,{}).get(i,f['label'])
    return fields_list


GEOMETRIES={'tubo redondo':['outer_diameter_mm','thickness_mm'],
 'tubo quadrado':['width_mm','thickness_mm'], 'tubo retangular':['width_mm','height_mm','thickness_mm'],
 'varão redondo':['outer_diameter_mm'], 'varão quadrado':['width_mm'],
 'varão retangular':['width_mm','height_mm'], 'barra':['width_mm','height_mm'],
 'chapa':['width_mm','thickness_mm'], 'cantoneira':['width_mm','height_mm','thickness_mm'],
 'perfil normalizado':[], 'outro':['width_mm','height_mm','thickness_mm']}


@lru_cache(maxsize=16)
def workbook_ranges(path,mtime,size,expected_hash):
    source=Path(path)
    with source.open('rb') as stream:
        actual=hashlib.file_digest(stream,'sha256').hexdigest()
    if actual!=expected_hash:raise planning.PlanningError('O ficheiro do catálogo mudou desde a importação.',409)
    with zipfile.ZipFile(source) as z:
        root=ET.fromstring(z.read('xl/workbook.xml'))
        rels=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        sheet=next((s for s in root.findall('.//{*}sheet') if s.get('name')=='Planeamento'),None)
        validations=[]
        if sheet is not None:
            rid=sheet.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
            target=next(r.get('Target') for r in rels if r.get('Id')==rid)
            xml=ET.fromstring(z.read(target.lstrip('/') if target.startswith('/') else 'xl/'+target))
            # Wildcards include x14 extensions that openpyxl drops on reading.
            for validation in xml.findall('.//{*}dataValidation'):
                sqref=validation.get('sqref') or validation.findtext('{*}sqref') or ''
                formula=validation.find('{*}formula1')
                formula=''.join(formula.itertext()).strip() if formula is not None else ''
                if sqref and formula:validations.append({'range':sqref,'formula':formula})
    result={'ranges':{},'names':{},'validations':validations}
    from openpyxl.utils.cell import column_index_from_string
    for entry in root.findall('.//{*}definedName'):
        match=re.fullmatch(r"'?AreaSecaoCorte'?!(?:\$)?([A-Z]+)\$?(\d+):\$?([A-Z]+)\$?(\d+)",entry.text or '')
        if match and match[1]==match[3]:
            column=column_index_from_string(match[1])-1
            result['ranges'][column]=(int(match[2]),int(match[4]))
            result['names'][entry.get('name')]=(column,int(match[2]),int(match[4]))
    return result


def catalog(area, conn=None):
    if conn is None:
        with planning.connect(readonly=True) as connection: return catalog(area,connection)
    info=planning.snapshot(conn,area)
    rows=conn.execute("SELECT sheet_name,excel_row,row_data FROM raw_mtg.other_sheet_rows WHERE snapshot_id=%s AND sheet_name=ANY(%s) ORDER BY sheet_name,excel_row",
                      (info['snapshot_id'],['Dados','AreaSecaoCorte','Tabela pesos','Picking'])).fetchall()
    ranges={}; workbook={'names':{},'validations':[]}
    source=conn.execute('SELECT source_path,source_sha256 FROM audit_mtg.snapshots WHERE snapshot_id=%s',(info['snapshot_id'],)).fetchone()
    if area=='perfis' and source and source.get('source_path') and Path(source['source_path']).is_file():
        stat=Path(source['source_path']).stat()
        workbook=workbook_ranges(source['source_path'],stat.st_mtime_ns,stat.st_size,source['source_sha256']);ranges=workbook['ranges']
    from . import planning_dates
    values={k:{} for k in ('machines','material_types','teams')}; profiles={}; primary=[]; secondary=[]; section=1
    picking,picking_evidence=planning_dates.picking_index([r for r in rows if r['sheet_name']=='Picking'])
    def add(group,v):
        v=clean(v)
        if v and key(v) not in ('máquinas','tipo de material','equipa','rendimento'): values[group].setdefault(key(v),v)
    header=[]
    for row in rows:
        v=row['row_data'].get('values') or []
        def cell(i): return clean(v[i]) if i<len(v) else ''
        sheet=row['sheet_name']; line=row['excel_row']
        if sheet=='Dados' and line>=3:
            add('machines',cell(1));add('teams',cell(6 if area=='perfis' else 10))
            if area=='cantoneiras' and line<=6:add('material_types',cell(4))
            if area=='cantoneiras':
                code,label=cell(7),cell(8)
                if 'operação' in key(code): section=2 if '2' in code else 1
                elif code and label:
                    option={'value':code,'label':f'{code} · {label}','sequence':section,'countable':code.isdigit() and code!='0'}
                    (primary if section==1 else secondary).append(option)
        elif sheet=='AreaSecaoCorte' and area=='perfis':
            if 3<=line<=700:add('material_types',cell(0))
            if line==1: header=v
            elif line>=2:
                for i in (ranges if ranges else range(13,min(33,len(v)))):
                    low,high=ranges.get(i,(2,150))
                    if not low<=line<=high:continue
                    name=clean(header[i]) if i<len(header) else ''
                    if name and cell(i): profiles.setdefault(key(name),set()).add(cell(i))
        elif sheet=='Tabela pesos' and area=='cantoneiras' and line>=3 and cell(1):
            p=cell(1); prefix=p.upper()
            group='cantoneira' if re.match(r'^L\d',prefix) else 'barra' if prefix.startswith('BARRA') else 'perfil' if re.match(r'^(HE|IP|UP|UB|UC|PFC|W)\d*',prefix) else None
            if group: profiles.setdefault(group,set()).add(p)
    # Old snapshots may lack raw Dados. Read only available lists; never invent materials.
    if not values['machines']:
        for row in conn.execute('SELECT row_data,machine_name,material_type FROM raw_mtg.machine_rows WHERE snapshot_id=%s',(info['snapshot_id'],)).fetchall():
            add('machines',row['machine_name'])
    if area=='perfis':
        # AG uses INDIRECT(SUBSTITUTE(AF," ","")), not the old Dados!E list.
        if workbook['names']:
            profiles={}
            cells={r['excel_row']:r['row_data'].get('values',[]) for r in rows if r['sheet_name']=='AreaSecaoCorte'}
            for name in values['material_types'].values():
                bounds=workbook['names'].get(name.replace(' ',''))
                if bounds:
                    col,low,high=bounds
                    profiles[key(name)]={clean(v[col]) for n,v in cells.items() if low<=n<=high and len(v)>col and clean(v[col])}
        primary=[{'value':'corte','label':'Corte','countable':True,'sequence':1}]
    if area=='cantoneiras' and not any(option['value']=='0' for option in secondary):
        secondary.insert(0,{'value':'0','label':'0 · Sem segunda operação','sequence':2,'countable':False,
                            'source':{'kind':'planning_rule','rule':'G03/G09: zero means no additional operation'}})
    result={k:sorted(v.values(),key=key) for k,v in values.items()}
    result.update(area=area,version=info['snapshot_id'],source='macro_'+area,snapshot=planning.serializable(info),
                  profiles={k:sorted(v,key=key) for k,v in profiles.items()},operations=primary,additional_operations=secondary,picking=picking,picking_evidence=picking_evidence,geometries=GEOMETRIES)
    result['profile_modes']={key(name):'select' if result['profiles'].get(key(name)) else 'manual' for name in result['material_types']}
    result['level1_source']='AreaSecaoCorte!A3:A700' if area=='perfis' else 'Dados!E3:E6'
    from .raw.registration import enabled as free_entry
    result['free_entry']=free_entry()
    result['validations']=workbook['validations']
    result['contract_version']=3
    result['fields']=arrange(fields(),area)
    for f in result['fields']:
        f.update(catalog_version=result['version'],catalog_source=result['source'])
        if f['id']=='profile':f['mode_by_family']=result['profile_modes']
        opts={'material_type':result['material_types'],'machine':result['machines'],'team':result['teams'],
              'operation':primary,'operation_detail':secondary,'geometry':list(GEOMETRIES)}
        if f['id'] in opts:f['options']=opts[f['id']]
    return result


def validate(raw, cat, ready=False, previous=None):
    errors={}; data={}; previous=previous or {}
    for f in fields():
        name=f['id']; value=raw.get(name,previous.get(name))
        if name in RETIRED_FIELDS and name not in raw:
            data[name]=previous.get(name);continue
        if f['type']=='tristate':
            if value is not None and type(value) is not bool: errors[name]='Escolhe Sim, Não ou Por confirmar.'
            data[name]=value;continue
        if name=='abocardar':
            data[name]=abocardar_mark(value)
            if data[name] not in ('X','-') and ready:
                errors[name]='Confirma se a peça precisa de abocardar; a indicação antiga é desconhecida.'
            continue
        if f['type']=='boolean': data[name]=value is True;continue
        if f['type']=='number':
            if value in (None,''):data[name]=None;continue
            try:
                d=Decimal(str(value).replace(',','.'))
                if (name=='stock_length_mm' and d<=0) or not d.is_finite() or abs(d)>1_000_000_000 or (d<0 and name!='angle_deg'):raise ValueError()
                if name in ('quantity_required','quantity_to_plan','picking_week','picking_year','finish_week','finish_year','planned_week','planned_year') and d!=d.to_integral_value():raise ValueError()
                data[name]=float(d)
            except (InvalidOperation,ValueError):errors[name]='Indica um número válido.';data[name]=None
        else:
            data[name]=clean(value)
            if len(data[name])>(4000 if name=='notes' else 500):errors[name]='Texto demasiado longo.'
            if f['type']=='date' and data[name]:
                try: date.fromisoformat(data[name])
                except ValueError:errors[name]='Indica uma data válida.'
    options={'material_type':cat['material_types'],'machine':cat['machines'],'team':cat['teams'],
             'operation':[x['value'] for x in cat['operations']+cat['additional_operations']
                          if x['countable'] or (not ready and x['value']=='por_definir')],
             'operation_detail':[x['value'] for x in cat['additional_operations']], 'geometry':list(GEOMETRIES)}
    for name,opts in options.items():
        if data[name] and data[name] not in opts and (ready or data[name]!=previous.get(name)): errors[name]='Seleciona uma opção válida do catálogo desta área.'
    if data['custom_profile']:
        data['profile']=data['special_profile']
    elif data['profile'] and cat['profiles'].get(key(data['material_type'])) and data['profile'] not in cat['profiles'][key(data['material_type'])] and (ready or data['profile']!=previous.get('profile')):
        errors['profile']='Seleciona um perfil desta família ou Perfil especial.'
    if ready:
        for name in ('component_ref','material_type','profile','operation','quantity_required'):
            if not data[name]: errors[name]='Campo obrigatório para concluir.'
        if data['operation']=='corte' or cat['area']=='cantoneiras':
            if not data['length_mm']:errors['length_mm']='Indica o comprimento de corte.'
        geom=data['geometry'] or family(data['material_type'])
        if (data['custom_profile'] or key(data['material_type'])=='varão') and geom not in GEOMETRIES:errors['geometry']='Seleciona a geometria do perfil especial.'
        # A catalogue designation alone is not a safe parser for missing dimensions.
        if data['custom_profile'] or geom.startswith(('tubo','varão')):
            for name in GEOMETRIES.get(geom,[]):
                if not data[name]:errors[name]='Dimensão obrigatória para esta geometria.'
    for name in ('outer_diameter_mm','width_mm','height_mm','thickness_mm','length_mm'):
        if data[name] is not None and data[name]<=0:errors[name]='A dimensão deve ser superior a zero.'
    if data['quantity_required'] is not None and data['quantity_required']<0:errors['quantity_required']='A necessidade não pode ser negativa.'
    if 'quantity_to_plan' in raw and data['quantity_to_plan'] is not None and data['quantity_required'] is not None and data['quantity_to_plan']>data['quantity_required']:errors['quantity_to_plan']='Ultrapassa a necessidade indicada.'
    for prefix in ('picking','finish','planned'):
        if prefix+'_week' not in raw and prefix+'_year' not in raw:continue
        week,year=data[prefix+'_week'],data[prefix+'_year']
        if week is not None:
            try:
                if not 1<=week<=53:raise ValueError()
                if year is not None: date.fromisocalendar(int(year),int(week),1)
            except (ValueError,OverflowError):errors[prefix+'_week']='Semana inválida para o ano indicado.'
        if year is not None and not 2000<=year<=2100:errors[prefix+'_year']='Indica um ano entre 2000 e 2100.'
    if 'weekly_capacity_hours' in raw and data['weekly_capacity_hours'] is not None and data['weekly_capacity_hours']>168:errors['weekly_capacity_hours']='Máximo: 168 horas.'
    if data['angle_deg'] is not None and abs(data['angle_deg'])>360:errors['angle_deg']='Confirma a convenção do ângulo.'
    if errors:
        exc=planning.PlanningError('Corrige os campos assinalados.');exc.fields=errors;raise exc
    return data
