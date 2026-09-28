"""Resolve C00 inventory anchors against actual XLSX/XML, VBA and SQL schema.

This is a source/contract inventory, not a numerical acceptance of all 43 rules.
Run after inventory_planning_contract.py --output c00-traceability-base.json.
"""
from __future__ import annotations
import ast,hashlib,json,os,re,sys
from collections import defaultdict
from datetime import datetime,timezone
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile
from openpyxl.formula.translate import Translator
from openpyxl.utils.cell import range_boundaries,column_index_from_string
from scripts.inventory_planning_contract import PERFIS,CANT

FOLDER=Path('docs/validacao-planeamento-integral/20260923-execucao')
NS='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
REL='{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
BOOKS={'Layout':'LayoutPlaneamentoPerfis.xlsx','Perfis':'Met2_Plan_Perfis.xlsm','Cantoneiras':'Met3_Plan_Cantoneiras.xlsm'}
DATASETS=('planning','production','production_hours','orders','capacity','capacity_items','capacity_machines','original')
UNITS={'bars':'un.','unassigned_records':'registos','picking_week':'semana ISO','planned_week':'semana ISO',
       'imported_week':'semana (ano importado pode ser desconhecido)','planned_year':'ano ISO',
       'applied_rate_value':'unidade do método da taxa aplicada','capacity_total':'unidade do método da taxa aplicada',
       'capacity_free':'unidade do método da taxa aplicada','unknown_load':'operações','lines_total':'linhas/ operações conforme a vista',
       'draft_unknown':'operações','remaining_known_lines':'peças','year':'ano ISO','week':'semana ISO',
       'reference_shifts':'turnos','reference_hours_per_shift':'h/turno','draft_hours':'h'}
UNITS.update(reference_equivalent_shifts='turnos',picking_year='ano ISO',finish_week='semana ISO',finish_year='ano ISO',weekly_capacity_hours='h')

def rule_implementation(rule):
    if rule=='H03':return [('app/raw/worked_hours.py','resolve'),('app/raw/projection.py','publish_hours')]
    if rule=='H09':return [('app/raw/productivity.py','historical')]
    if rule=='H10' or rule=='G06':return [('app/raw/productivity.py','select_rate')]
    if rule.startswith('H'):return [('app/raw/capacity_revision.py','summary'),('app/raw/capacity_revision.py','calculate')]
    if rule=='F12':return [('app/raw/capacity_revision.py','summary'),('app/raw/capacity_revision.py','apply_planning_results')]
    if rule in ('F20','G07'):return [('app/raw/capacity.py','estimate'),('app/raw/productivity.py','estimate')]
    if rule in ('F02','F03','G01'):return [('app/planning_calculations.py','production_source'),('app/planning_production.py','attach_operation_evidence')]
    if rule=='F09':return [('app/planning_calculations.py','section')]
    return [('app/planning_calculations.py','calculate')]

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def coordinates(reference):
    bounds=range_boundaries(reference)
    if None in bounds or bounds[0]>bounds[2] or bounds[1]>bounds[3]:raise ValueError('Invalid cell/range: '+reference)
    return bounds

def in_range(cell,bounds):
    match=re.fullmatch(r'([A-Z]+)(\d+)',cell)
    col,row=column_index_from_string(match[1]),int(match[2])
    a,b,c,d=bounds
    return a<=col<=c and b<=row<=d

def source_cells(path,requested,direct_columns):
    """Read original XML, including shared formulas and string/text rules."""
    cells={};samples={};names=[]
    with ZipFile(path) as z:
        strings=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            with z.open('xl/sharedStrings.xml') as s:
                for _,node in ET.iterparse(s,events=('end',)):
                    if node.tag==NS+'si':strings.append(''.join(x.text or '' for x in node.iter(NS+'t')));node.clear()
        book=ET.fromstring(z.read('xl/workbook.xml'))
        names=[dict(n.attrib,value=n.text) for n in book.iter(NS+'definedName')]
        rels={r.get('Id'):r.get('Target') for r in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
        for sheet in book.find(NS+'sheets'):
            name=sheet.get('name')
            if name not in requested and name not in direct_columns:continue
            bounds=requested.get(name,[]);columns=set(direct_columns.get(name,[]));shared={}
            target=rels[sheet.get(REL+'id')];target=target.lstrip('/') if target.startswith('/') else 'xl/'+target
            with z.open(target) as s:
                for _,node in ET.iterparse(s,events=('end',)):
                    if node.tag!=NS+'row':continue
                    for cell in node:
                        coord=cell.get('r');kind=cell.get('t');f=cell.find(NS+'f');formula=f.text if f is not None else None
                        if f is not None and f.get('t')=='shared':
                            if formula:shared[f.get('si')]=(formula,coord)
                        col=re.match('[A-Z]+',coord)[0];row=int(coord[len(col):])
                        index=column_index_from_string(col)
                        wanted=any(a<=index<=c and b<=row<=d for a,b,c,d in bounds)
                        sample=col in columns and row>=7 and (name,col) not in samples
                        if not wanted and not sample:continue
                        if f is not None and not formula and f.get('t')=='shared' and f.get('si') in shared:
                            expression,origin=shared[f.get('si')];formula=Translator('='+expression,origin=origin).translate_formula(coord)[1:]
                        value=cell.findtext(NS+'v')
                        if kind=='s' and value is not None:value=strings[int(value)]
                        elif kind=='inlineStr':value=''.join(x.text or '' for x in cell.iter(NS+'t'))
                        elif value is not None and kind not in ('str','e'):
                            try:
                                value=float(value)
                                if value.is_integer():value=int(value)
                            except ValueError:pass
                        if value is None and f is None:continue
                        item={'sheet':name,'cell':coord,'value':value,'formula':formula,'type':kind,'xml_part':target}
                        if wanted:cells[(name,coord)]=item
                        if sample and value not in (None,'',' '):samples[(name,col)]=item
                    node.clear()
    return cells,samples,names

@lru_cache(maxsize=None)
def code_anchor(path,function):
    p=Path(path);source=p.read_text();tree=ast.parse(source)
    found=[n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==function]
    assert len(found)==1,(path,function)
    n=found[0]
    return {'file':path,'function':function,'line':n.lineno,'end_line':n.end_lineno,'sha256':sha(p)}

def main():
    base=json.loads((FOLDER/'c00-traceability-base.json').read_text())
    books={Path(b['file']).name:b for b in json.loads((FOLDER/'workbook-inventory.json').read_text())}
    wanted={name:defaultdict(list) for name in BOOKS};direct={name:defaultdict(list) for name in BOOKS}
    for rule in base['formulas']:
        for origin in rule['origins']:
            kind,*rest=origin.split(':',2)
            if kind in BOOKS:
                assert len(rest)==2,origin
                wanted[kind][rest[0]].append(coordinates(rest[1]))
    for book,sheet,columns in [('Perfis','Planeamento',PERFIS),('Cantoneiras','Plan_ produção',CANT)]:
        direct[book][sheet]=sorted(set(columns.values()))
        for col in direct[book][sheet]:wanted[book][sheet].append(coordinates(col+'6'))
    # Complete exact property tables and family/name lists, not just a sample.
    wanted['Perfis']['AreaSecaoCorte'].append(coordinates('A1:AG700'))
    wanted['Cantoneiras']['Tabela pesos'].append(coordinates('B1:C462'))
    loaded={};source_proofs=[]
    for name,filename in BOOKS.items():
        book=books[filename];assert sha(book['file'])==book['sha256']
        cells,samples,names=source_cells(book['file'],wanted[name],direct[name])
        assert sha(book['file'])==book['sha256']
        loaded[name]=(cells,samples)
        source_proofs.append({'name':name,'file':book['file'],'sha256':book['sha256'],'defined_names':names,
                             'selected_populated_cells':len(cells),'input_samples':len(samples)})
        print(filename,len(cells),'cells verified directly',flush=True)
    os.environ['MES_PG_DSN']=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
    from app import planning,planning_local_orders
    from app.raw import contracts
    with planning.connect(readonly=True) as c:
        assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
        schema={(r['table_schema']+'.'+r['table_name'],r['column_name']):r['data_type'] for r in c.execute("SELECT table_schema,table_name,column_name,data_type FROM information_schema.columns WHERE table_schema IN ('planning_mtg','mes_kanban')").fetchall()}
        formulas=planning.serializable(c.execute("SELECT id,area,name,revision,definition FROM planning_mtg.raw_objects WHERE kind='formula' AND NOT archived ORDER BY area,id").fetchall())
    # Re-extract source VBA with the same isolated dependency directory used for baseline.
    sys.path.insert(0,'/tmp/planning-vba-tools')
    from oletools.olevba import VBA_Parser
    vba={};source=books[BOOKS['Perfis']]
    parser=VBA_Parser(source['file'])
    try:
        for _,_,module,text in parser.extract_macros():
            if module=='FuncAreaPerf.bas':vba[module]=text
    finally:parser.close()
    assert 'FuncAreaPerf.bas' in vba
    with ZipFile(source['file']) as z:assert hashlib.sha256(z.read('xl/vbaProject.bin')).hexdigest()==source['vba_sha256']
    modules={k:{'file':source['file'],'workbook_sha256':source['sha256'],'vba_sha256':source['vba_sha256'],
                'module_sha256':hashlib.sha256(v.encode()).hexdigest(),'code':v} for k,v in vba.items()}
    (FOLDER/'c00-verified-vba.json').write_text(json.dumps(modules,ensure_ascii=False,indent=2)+'\n')
    for rule in base['formulas']:
        rule['verified_origins']=[]
        for origin in rule['origins']:
            kind,location,*rest=origin.split(':',2)
            if kind in BOOKS:
                bounds=coordinates(rest[0]);cells=[r for (sheet,cell),r in loaded[kind][0].items() if sheet==location and in_range(cell,bounds)]
                assert cells,origin
                proof={'kind':'workbook','file':books[BOOKS[kind]]['file'],'sha256':books[BOOKS[kind]]['sha256'],
                       'sheet':location,'reference':rest[0],'cells':cells}
            elif kind=='SQL':
                column=re.split(r'[.\[]',rest[0])[0]
                assert (location,column) in schema,origin
                proof={'kind':'sql_schema','table':location,'column':column,'path':rest[0],'data_type':schema[(location,column)]}
            elif kind=='VBA':
                assert location in modules;proof={'kind':'vba_module','module':location,'artifact':'c00-verified-vba.json',
                    'module_sha256':modules[location]['module_sha256']}
            else:raise ValueError('Unresolved anchor '+origin)
            rule['verified_origins'].append(proof)
        rule['implementation']=[code_anchor(*target) for target in rule_implementation(rule['id'])]
        rule['validation_status']='independent_arithmetic_population_proof' if rule['population_validation'] else 'full_rule_validation_pending_C04_C10'
    rule_map={r['id']:r for r in base['formulas']}
    for area,info in base['fields'].items():
        book='Perfis' if area=='perfis' else 'Cantoneiras';sheet='Planeamento' if area=='perfis' else 'Plan_ produção'
        for field in info['fields']:
            field['dependencies']=[]
            for origin in field['origins']:
                if origin['kind']=='macro_cell':
                    origin['header']=loaded[book][0].get((sheet,origin['header_cell']))
                    origin['input_example']=loaded[book][1].get((sheet,origin['data_column']))
                    if not origin['input_example']:origin['input_note']='A coluna foi percorrida integralmente e não contém nenhum valor de entrada preenchido.'
                    origin['sha256']=books[BOOKS[book]]['sha256']
                    if not origin['header']:origin['header_note']='Cabeçalho sem célula preenchida; verificar cabeçalho agrupado/linha original.'
                if origin['kind']=='derived':
                    field['dependencies'] += [{'rule':rid,'inputs':rule_map[rid]['inputs']} for rid in origin['formula_ids']]
            if not field['dependencies']:field['dependencies']=[{'source':'Entrada manual ou facto importado; origens e exemplo acima. Não deriva de outra coluna de apresentação.'}]
            field['input_unit']=(field['raw'] or field['form_catalog']).get('unit') or UNITS.get(field['id']) or (' / '.join(dict.fromkeys(rule_map[r['rule']]['unit'] for r in field['dependencies'] if 'rule' in r))) or 'sem unidade física (texto, data ou estado)'
            field['runtime_unit_metadata_absent']=bool(field['raw'] and field['raw']['data_type']=='number' and field['raw']['unit'] is None)
            field['unavailable_policy']='Conservar ausência/erro de origem; resultados derivados exigem motivo específico do motor. Zero desconhecido não é inventado.'
    # All eight RAW datasets, including facts, summaries and resource/period fields.
    producers={'production':('app/raw/projection.py','enrich'),'original':('app/raw/projection.py','rebuild_original'),
               'production_hours':('app/raw/projection.py','publish_hours'),'orders':('app/raw/projection.py','order_rows'),
               'capacity':('app/raw/capacity_revision.py','rebuild'),'capacity_items':('app/raw/capacity_revision.py','rebuild'),
               'capacity_machines':('app/raw/capacity_revision.py','rebuild')}
    capacity_rules={'available_hours':'H01','planned_hours':'H02','actual_hours':'H03','free_hours':'H04','occupancy':'H05',
                    'equivalent_shifts':'H06','capacity_total':'H07','capacity_free':'H08','rate_source':'H10','applied_rate_value':'H10'}
    datasets={}
    for area in planning.AREAS:
        datasets[area]={}
        for dataset in DATASETS:
            fields=contracts.fields(area,dataset);assert len(fields)==len({f['id'] for f in fields})
            entries=[]
            for field in fields:
                if dataset=='planning':
                    entry=next(r for r in base['fields'][area]['fields'] if r['id']==field['id'])
                    entries.append({'field':field,'inventory_reference':f"fields.{area}.{entry['id']}"});continue
                rid=capacity_rules.get(field['id']) if dataset.startswith('capacity') else None
                entries.append({'field':field,'producer':code_anchor(*producers[dataset]),'rules':[rid] if rid else [],
                    'source_kind':'validated_source_fact' if dataset in ('production','production_hours','original') else 'population_aggregate_or_dimension',
                    'dependencies':rule_map[rid]['inputs'] if rid else 'Identidade/dimensões e campos da população de origem desta vista; função produtora indicada.',
                    'unit':field['unit'] or UNITS.get(field['id'],'sem unidade física'),
                    'unknown_policy':'Ausência e cobertura parcial preservadas pelo produtor; horas da folha não repartidas automaticamente por linha.'})
            datasets[area][dataset]={'count':len(fields),'fields':entries}
    families=[]
    for family in base['profile_families']:
        item={k:v for k,v in family.items() if k!='entries'};item['verified_entries']=[]
        if family['method'].startswith('Exact'):
            for entry in family['entries']:
                row=loaded['Perfis'][0][('AreaSecaoCorte',entry['cell'])]
                assert row['value']==entry['area']
                item['verified_entries'].append({'designation':entry['designation'],'source':row})
            assert item['verified_entries'] or item['missing_reason']
        else:
            pattern=r'(?im)^Function '+re.escape(family['method'])+r'\([^\n]*\).*?^End Function'
            match=re.search(pattern,vba['FuncAreaPerf.bas'],re.S)
            assert match,family['method']
            item['vba_function']=match.group();item['module']='FuncAreaPerf.bas'
        families.append(item)
    # Numerical catalogue acceptance is an existing independently evaluated proof.
    acceptance=json.loads((FOLDER/'c02-abocardar-population.json').read_text())
    assert len(acceptance['catalogue_acceptance'])==493 and not acceptance['failures']
    assert {x['family'] for x in acceptance['catalogue_acceptance']}=={x['family'] for x in families}
    base.update(at=datetime.now(timezone.utc).isoformat(),script_sha256=sha(__file__),
        base_script_sha256=sha('scripts/inventory_planning_contract.py'),source_verification=source_proofs,
        profile_families=families,raw_datasets=datasets,
        administrative_form={'fields':['of']+sorted(planning_local_orders.FIELDS),'storage':'planning_mtg.local_orders / local_order_history',
                             'validation':code_anchor('app/planning_local_orders.py','save'),'browser_evidence':'c03-complete-results-final.json'},
        local_formula_columns=formulas,
        catalogue_validation={'artifact':'c02-abocardar-population.json','sha256':sha(FOLDER/'c02-abocardar-population.json'),'cases':493,'families':20},
        scope='Complete current RAW dataset and piece-form field inventory, 43 rules with actual cell/VBA/SQL anchors. Metadata completeness is separate from numerical acceptance and real OCR ingestion.',
        result='all_rule_origins_and_raw_contracts_resolved')
    base['counts']={'rules':len(base['formulas']),'rule_origins':sum(len(r['verified_origins']) for r in base['formulas']),
                    'planning_fields':sum(v['raw_count'] for v in base['fields'].values()),'form_catalog_fields':sum(v['form_catalog_count'] for v in base['fields'].values()),
                    'raw_dataset_fields':sum(v['count'] for area in datasets.values() for v in area.values()),'profile_families':len(families)}
    (FOLDER/'c00-complete-traceability.json').write_text(json.dumps(base,ensure_ascii=False,indent=2,default=str)+'\n')
    print(json.dumps(base['counts']),flush=True)

if __name__=='__main__':main()
