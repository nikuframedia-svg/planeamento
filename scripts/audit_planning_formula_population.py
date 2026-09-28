"""Independent C04 arithmetic/property audit on every isolated planning row.

Reads exact workbook ledgers and checks their current source hashes. Application
formula/rule outputs are never used as expected results. The section resolver is
called only as the observed result in additional catalogue acceptance cases.
Production-source association is deliberately a separate C01/C02 gate: this audit
uses the selected counters and records that boundary explicitly.
"""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
from datetime import date,datetime,timezone
import gzip,hashlib,json,math,os,re
from pathlib import Path
from zoneinfo import ZoneInfo

FOLDER=Path('docs/validacao-planeamento-integral/20260923-execucao')

def normalized(x):return ' '.join(str(x or '').strip().casefold().split()).replace('rectangular','retangular')
def number(x):
    if isinstance(x,bool):return None
    try:
        v=float(str(x).replace(',','.'))
        return v if math.isfinite(v) else None
    except (ValueError,TypeError):return None

def valid(x,integer=False):
    n=number(x)
    return n if n is not None and n>=0 and (not integer or n.is_integer()) else None

def positive(x):
    n=number(x);return n if n is not None and n>0 else None

def equal(a,b):
    if a is None or b is None:return a is b
    if isinstance(a,bool) or isinstance(b,bool):return a is b
    if isinstance(a,(int,float)) and isinstance(b,(int,float)):
        return abs(a-b)<=max(1e-6,abs(a)*1e-8)
    return a==b

def sheets(stem,wanted):
    result={s:defaultdict(dict) for s in wanted}
    with gzip.open(FOLDER/(stem+'-cells.jsonl.gz'),'rt') as stream:
        for line in stream:
            item=json.loads(line)
            if item['sheet'] not in result:continue
            column,row=re.fullmatch(r'([A-Z]+)(\d+)',item['cell']).groups()
            result[item['sheet']][int(row)][column]=item
    return result

def area_expected(v,table):
    family=normalized(v.get('material_type'))
    dims={k:positive(v.get(k)) for k in ['outer_diameter_mm','width_mm','height_mm','thickness_mm']}
    d,w,h,t=[dims[k] for k in dims]
    # Formulas transcribed from FuncAreaPerf.bas, not the application module.
    formulas={
      'varão redondo':(lambda:math.pi*d**2/4, bool(d),'AreaVaraoRedondo'),
      'varão nervurado':(lambda:math.pi*d**2/4, bool(d),'AreaVaraoNervurado'),
      'varão quadrado':(lambda:w**2,bool(w),'AreaVaraoQuadrado'),
      'varão retangular':(lambda:w*h,bool(w and h),'AreaVaraoRetangular'),
      'barra':(lambda:w*h,bool(w and h),'AreaBarra'),
      'tubo redondo':(lambda:math.pi*(d**2-(d-2*t)**2)/4,bool(d and t and d>2*t),'AreaTuboRedondo'),
      'tubo quadrado':(lambda:w**2-(w-2*t)**2,bool(w and t and w>2*t),'AreaTuboQuadrado'),
      'tubo retangular':(lambda:w*h-(w-2*t)*(h-2*t),bool(w and h and t and min(w,h)>2*t),'AreaTuboRetangular'),
      'calha':(lambda:h*t+2*w*t-2*t*t,bool(w and h and t and h>2*t and w>t),'AreaCalha'),
      'cantoneira':(lambda:h*t+w*t-t*t,bool(w and h and t and min(w,h)>t),'AreaCantoneira'),
      'chapa':(lambda:w*t,bool(w and t),'AreaChapa')}
    if family in formulas:
        formula,ready,name=formulas[family]
        return (formula() if ready else None),{'kind':'VBA','module':'FuncAreaPerf.bas','function':name,'inputs':dims,'reason':None if ready else 'Dimensões ausentes ou inválidas'}
    entries=table.get((family,normalized(v.get('profile'))),[])
    values={x['value'] for x in entries}
    return (next(iter(values)) if len(values)==1 else None),{'kind':'exact_lookup','sheet':'AreaSecaoCorte','entries':entries,'reason':None if len(values)==1 else 'Correspondência ausente ou divergente'}

def row_expected(v,detail,area,sections,weights,today):
    q=valid(v.get('quantity_required'),True);length=positive(v.get('length_mm'))
    cut=valid(v.get('cut' if area=='perfis' else 'made'),True);boc=valid(v.get('boc'),True)
    mark=v.get('abocardar');yes=mark is True or normalized(mark).lstrip("'") in ('x','sim');no=mark is False or normalized(mark) in ('-','não','nao')
    remaining=max(q-cut,0) if q is not None and cut is not None else None
    boc_remaining=0 if no else max(q-boc,0) if q is not None and boc is not None else None
    prop,property_source=area_expected(v,sections)
    expected={};evidence={}
    def put(rule,field,value,inputs,origin):
        expected[field]=(rule,value);evidence[field]={'inputs':inputs,'origin':origin}
    put('F07' if area=='perfis' else 'G03','remaining',remaining,{'Q':q,'produced':cut},'max(Q - P, 0)')
    put('F07' if area=='perfis' else 'G03','production_excess',max(cut-q,0) if q is not None and cut is not None else None,{'Q':q,'produced':cut},'max(P - Q, 0)')
    put('F11' if area=='perfis' else 'G10','quantity_to_plan',remaining,{'Q':q,'produced':cut},'Saldo principal')
    put('F04' if area=='perfis' else 'G02','cut_pct' if area=='perfis' else 'made_pct',100*cut/q if q and cut is not None else None,{'Q':q,'produced':cut},'100 * P / Q')
    if area=='perfis':
        put('F05','boc_pct',100*boc/q if not no and q and boc is not None else None,{'Q':q,'B':boc,'abocardar':mark},'Layout S / operação aplicável')
        put('F06','final_pct',100*(boc if yes else cut)/q if q and ((yes and boc is not None) or (no and cut is not None)) else None,{'Q':q,'C':cut,'B':boc,'abocardar':mark},'Layout T / operação final')
        put('F08','boc_remaining',boc_remaining,{'Q':q,'B':boc,'abocardar':mark},'Layout V')
        put('F09','section_unit',prop,v,property_source)
        put('F10','section_total',prop*q if prop is not None and q is not None else None,{'Q':q,'unit_area':prop},property_source)
        put('F10','section_pending',0 if remaining==0 else prop*remaining if prop is not None and remaining is not None else None,{'remaining':remaining,'unit_area':prop},property_source)
    else:
        secondary=str(v.get('operation_detail') or '').strip()
        primary=str(v.get('operation') or '').strip()
        produced=next((valid(op.get('value'),True) for op in detail.get('selected_operations',[]) if str(op.get('operation'))==secondary),None)
        secondary_balance=0 if secondary in ('','0',primary) else max(q-produced,0) if q is not None and produced is not None else None
        put('G03','secondary_remaining',secondary_balance,{'Q':q,'operation':secondary,'primary':primary,'produced':produced},'max(Q - P_secondary, 0); no secondary load for code 0 or absent operation')
    put('F16' if area=='perfis' else 'G04','total_length',q*length if q is not None and length else None,{'Q':q,'L':length},'Q * L; mm')
    put('F16' if area=='perfis' else 'G04','total_m',q*length/1000 if q is not None and length else None,{'Q':q,'L':length},'Q * L / 1000; m')
    put('F19' if area=='perfis' else 'G05','remaining_m',0 if remaining==0 else remaining*length/1000 if remaining is not None and length else None,{'remaining':remaining,'L':length},'saldo * L / 1000; m')
    stock=positive(v.get('stock_length_mm'))
    if area=='perfis':
        if not detail.get('need_id'):
            imported=positive(detail.get('imported_stock'))
            expected_stock=imported if imported is not None else 12000 if length and length>6000 else 6000 if length else None
            put('F17','stock_length_mm',expected_stock,{'L':length,'imported_BS':detail.get('imported_stock')},'Planeamento BS ou sugestão textual Layout AO2; preparação local excluída deste confronto')
        elif v.get('stock_length_origin')=='Sugestão automática':
            put('F17','stock_length_mm',12000 if length and length>6000 else 6000 if length else None,{'L':length},'Layout AO2 textual')
        fit=math.floor(stock/length) if stock and length else 0
        put('F18','bars',0 if remaining==0 else math.ceil(remaining/fit) if fit and remaining is not None else None,{'remaining':remaining,'stock':stock,'L':length},'Layout AP2 textual: ceil(saldo / floor(S / L))')
        density=7850 if detail.get('plan_key') or re.match(r'^(S\d|C\d|B\d|DX\d)',str(v.get('grade') or '').upper()) else None
        unit_weight=prop/1e6*length/1000*density if prop is not None and length and density else None
        source={'rule':'Planeamento DB/DC; aço da macro ou qualidade compatível','density':density,'area':prop,'L':length}
    else:
        entries=weights.get(normalized(v.get('profile')),[]);rates={x['value'] for x in entries}
        kg_m=next(iter(rates)) if len(rates)==1 else None
        unit_weight=kg_m*length/1000 if kg_m is not None and length else None
        source={'rule':'Tabela pesos B:C exata; corrigir VLOOKUP aproximado de AP','profile':v.get('profile'),'entries':entries,'L':length}
    put('F14' if area=='perfis' else 'G08','weight_unit',unit_weight,source,source['rule'])
    put('F15' if area=='perfis' else 'G09','weight',unit_weight*remaining if unit_weight is not None and remaining is not None else None,{'unit_weight':unit_weight,'remaining':remaining},source)
    year=week=None
    try:
        if v.get('expected_date'):year,week,_=date.fromisoformat(str(v['expected_date'])[:10]).isocalendar()
        if v.get('planned_year') is not None or v.get('planned_week') is not None:
            yr,wk=int(v['planned_year']),int(v['planned_week']);date.fromisocalendar(yr,wk,1)
            if year is not None and (yr,wk)!=(year,week):raise ValueError
            year,week=yr,wk
    except (ValueError,TypeError):year=week=None
    put('F13' if area=='perfis' else 'G11','expected_week',f'{year}-W{week:02}' if year is not None else None,{k:v.get(k) for k in ['expected_date','planned_year','planned_week']},'ISO; ano da semana, não YEAR(data)')
    # C01/C02 resolve the counters and are not silently approved by arithmetic.
    return expected,evidence

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='c04-formula-population');parser.add_argument('--workbook-root',type=Path);args=parser.parse_args()
    if not re.fullmatch('[a-z0-9-]+',args.output):parser.error('Use a simple proof prefix')
    os.environ['MES_PG_DSN']=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
    from app import planning
    from app.raw import query
    out={'at':datetime.now(timezone.utc).isoformat(),'environment':'isolated full copy localhost44164; readonly transaction','boundary':'Independent arithmetic for selected counters and typed inputs. C01/C02 source selection, local-source field parity, F01/F02/F03/F12/F20/F21/G01/G06/G07/G12/H01-H10 are separate gates, not claimed here.','sources':[],'areas':{},'failures':[]}
    for entry in json.loads((FOLDER/'workbook-inventory.json').read_text()):
        path=args.workbook_root/Path(entry['file']).name if args.workbook_root else Path(entry['file'])
        actual=hashlib.sha256(path.read_bytes()).hexdigest();assert actual==entry['sha256'],str(path)
        out['sources'].append({'file':str(path),'sha256':actual,'inventory_file':entry['file']})
    section_sheet=sheets('Met2_Plan_Perfis',{'AreaSecaoCorte'})['AreaSecaoCorte']
    weight_sheet=sheets('Met3_Plan_Cantoneiras',{'Tabela pesos'})['Tabela pesos']
    sections=defaultdict(list);weights=defaultdict(list)
    for row,cells in section_sheet.items():
        if row<3:continue
        area_value=positive(cells.get('C',{}).get('value'))
        if area_value:sections[(normalized(cells.get('A',{}).get('value')),normalized(cells.get('B',{}).get('value')))].append({'cell':f'C{row}','value':area_value})
    for row,cells in weight_sheet.items():
        if row<3:continue
        value=positive(cells.get('C',{}).get('value'))
        if value:weights[normalized(cells.get('B',{}).get('value'))].append({'cell':f'C{row}','value':value})
    print('Exact workbook property tables loaded',len(sections),len(weights),flush=True)
    from app.planning_calculations import section as observed_section
    actual_table={key:[{'area':item['value'],'cell':item['cell']} for item in entries] for key,entries in sections.items()}
    out['catalogue_acceptance']=[]
    for family in json.loads((FOLDER/'field-formula-inventory.json').read_text())['profile_families']:
        name=family['family'];profiles=[key[1] for key in sections if key[0]==normalized(name)] if family['method'].startswith('Exact') else [None]
        for profile in profiles or [None]:
            inputs={'material_type':name,'profile':profile,'outer_diameter_mm':20,'width_mm':10,'height_mm':20,'thickness_mm':1}
            expected,source=area_expected(inputs,sections);actual,_=observed_section(inputs,actual_table)
            item={'family':name,'profile':profile,'inputs':inputs,'source':source,'expected':expected,'observed':actual,'equal':equal(expected,actual)}
            out['catalogue_acceptance'].append(item)
            if not item['equal']:out['failures'].append({'check':'catalogue_acceptance',**item})
    assert len({r['family'] for r in out['catalogue_acceptance']})==20
    today=datetime.now(ZoneInfo(planning.settings.display_timezone)).date();out['application_day']=today.isoformat()
    with gzip.open(FOLDER/(args.output+'-rows.jsonl.gz'),'wt',encoding='utf8') as ledger,planning.connect(readonly=True) as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
        for area in planning.AREAS:
            gen=query.generation(c,area);base,params=query.source(gen)
            info={'version':gen['id'],'snapshot':gen['metadata']['snapshot']['snapshot_id'],'rows':0,'checks':0,'known':0,'unavailable':0,'by_rule':{},'families':{}}
            rules=defaultdict(Counter);families=defaultdict(Counter)
            with c.cursor(name='formula_'+area) as cursor:
                cursor.execute("SELECT m.row_key,c.values_json,c.detail->>'plan_key' plan_key,c.detail->>'need_id' need_id,c.detail->'raw'->'comp.per. utilizar (mm)' imported_stock,c.detail->'calculation'->'production_sources' selected_operations"+base,params)
                for row in cursor:
                    v=row['values_json'];expected,evidence=row_expected(v,row,area,sections,weights,today);checks=[]
                    for field,(rule,value) in expected.items():
                        observed=v.get(field);ok=equal(value,observed)
                        rules[rule]['checked']+=1;rules[rule]['passed' if ok else 'failed']+=1;rules[rule]['known' if value is not None else 'unavailable']+=1
                        if field=='section_unit':families[str(v.get('material_type'))]['known' if value is not None else 'unavailable']+=1
                        check={'rule':rule,'field':field,'expected':value,'observed':observed,'equal':ok,**evidence[field]};checks.append(check)
                        if not ok:out['failures'].append({'area':area,'key':row['row_key'],**check})
                    info['rows']+=1;info['checks']+=len(checks);info['known']+=sum(x['expected'] is not None for x in checks);info['unavailable']+=sum(x['expected'] is None for x in checks)
                    ledger.write(json.dumps({'area':area,'key':row['row_key'],'of':v.get('of'),'reference':v.get('component_ref'),'checks':checks},ensure_ascii=False,default=str)+'\n')
                    if info['rows']%20000==0:print(area,info['rows'],'rows',flush=True)
            info['by_rule']={k:dict(v) for k,v in rules.items()};info['families']={k:dict(v) for k,v in families.items()};out['areas'][area]=info;print(area,info['rows'],info['checks'],'checks',flush=True)
    out['result']='passed_in_stated_scope' if not out['failures'] else 'failed'
    out['ledger']={'file':args.output+'-rows.jsonl.gz','sha256':hashlib.sha256((FOLDER/(args.output+'-rows.jsonl.gz')).read_bytes()).hexdigest()}
    (FOLDER/(args.output+'.json')).write_text(json.dumps(out,ensure_ascii=False,indent=2,default=str)+'\n')
    print('Failures',len(out['failures']),flush=True)
    if out['failures']:raise SystemExit(1)

if __name__=='__main__':main()
