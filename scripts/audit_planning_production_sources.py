"""F02/F03/G01: independently select counters for every current piece/operation.

The inputs are resolved operation evidence plus original macro cells. Association
and central revisions have a separate current OCR audit; live original ingestion
and the complete human/cross-origin decision matrix remain C01/C02 gates.
"""
from __future__ import annotations
import argparse,gzip,hashlib,json,math,os,re
from collections import defaultdict,Counter
from datetime import datetime,timezone
from pathlib import Path
from scripts.audit_planning_formula_population import FOLDER,equal


def count(value):
    try:n=float(str(value).replace(',','.'))
    except (ValueError,TypeError):return None
    return n if math.isfinite(n) and n>=0 and n.is_integer() else None


def normalized(value):
    return ' '.join(str(value).strip().casefold().split()).replace('rectangular','retangular')


def identity(values):
    fields=('component_ref','identity_discriminator','material_type','profile','grade','length_mm',
            'outer_diameter_mm','width_mm','height_mm','thickness_mm','angle_deg')
    result={}
    for field in fields:
        value=values.get(field)
        if value in (None,''):value=None
        elif field.endswith('_mm') or field=='angle_deg':
            text=str(value).strip()
            if re.fullmatch(r'[+-]?\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d+)?',text):text=re.sub(r'\s+','',text)
            try:
                value=float(text.replace(',','.'))
                if not math.isfinite(value):value=None
            except (TypeError,ValueError):value=None
        elif isinstance(value,str):
            value=normalized(value.replace('_x000D_',' '))
            if value.startswith(('#','=')) or value in ('-','—'):value=''
        result[field]=value
    return result


def select_counter(operation,macro,*,compatible=True,local_initial=False):
    records=operation.get('ocr_records') or [];reasons=list(operation.get('coverage_reasons') or [])
    if operation.get('ocr_partial'):reasons.append('Produção OCR com quantidades em falta.')
    if operation.get('requires_operation_review'):reasons.append('Operação por confirmar.')
    if not compatible:reasons.append('Identidade técnica alterada; associação por rever.')
    grouped=defaultdict(list);origins=set()
    for record in records:
        if record.get('operation') not in (None,operation['operation']):
            reasons.append('Evento de outra operação.');continue
        ident=(record.get('source','mes'),record.get('instance_id'),record.get('sheet_uid'),record.get('record_id'),record.get('row_index'),record.get('child_key'))
        grouped[ident].append(count(record.get('quantity')))
        origins.add(ident[:2])
        if count(record.get('quantity')) is None:reasons.append('Quantidade OCR desconhecida ou inválida.')
        if record.get('validated') is False:reasons.append('Revisão OCR não validada.')
    if any(len(set(v))>1 for v in grouped.values()):reasons.append('Revisões ou quantidades em conflito para o mesmo evento.')
    if len(origins)>1 and not operation.get('cross_source_reconciled'):reasons.append('Sobreposição entre origens OCR por resolver.')
    usable=bool(grouped) and not reasons
    ocr=sum(v[0] for v in grouped.values()) if usable else None
    excel=count(macro)
    if usable:value,source=ocr,'OCR validado'
    elif compatible and excel is not None:value,source=excel,'Excel provisório'
    elif local_initial and not records and not reasons:value,source=0,'Condição inicial local'
    else:value,source=None,'Indisponível'
    return {'value':value,'origin':source,'ocr':ocr,'excel':excel,
            'difference':ocr-excel if ocr is not None and excel is not None else None,
            'coverage_reasons':sorted(set(reasons))}


def codes(values,area):
    primary='corte' if area=='perfis' else str(values.get('operation') or '').strip()
    result=[primary]
    if area=='perfis':
        mark=values.get('abocardar')
        if mark is not False and normalized(mark) not in ('-','não','nao'):result.append('abocardar')
    else:
        secondary=str(values.get('operation_detail') or '').strip()
        if secondary not in ('','0',primary):result.append(secondary)
    return primary,result


def macro_for(code,primary,area,raw,operation):
    if area=='perfis':return raw.get('Ser.' if code=='corte' else 'Aboc.')
    explicit=operation.get('macro_quantity')
    if explicit is not None:return explicit
    # The original workbook primary owns Maq.; sequence edits do not transfer it.
    owner=str(raw.get('1ª Oper.') or '').strip()
    return raw.get('Maq.') if code==primary and (not owner or owner==code) else None


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='c02-source-policy');args=parser.parse_args()
    assert args.output.replace('-','').isalnum()
    os.environ['MES_PG_DSN']=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
    from app import planning
    from app.raw import query
    from scripts.audit_planning_selected_ocr import source_fingerprints
    report={'at':datetime.now(timezone.utc).isoformat(),'rules':['F02','F03','G01'],'boundary':__doc__,
            'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'areas':{},'checks':0,'failures':[],
            'environment':'planning_integral clone, read-only repeatable read'}
    ledger=FOLDER/(args.output+'-rows.jsonl.gz')
    def check(name,actual,expected,**context):
        report['checks']+=1
        if not equal(actual,expected):report['failures'].append({'check':name,'actual':actual,'expected':expected,**context})
    with planning.connect(readonly=True) as conn,gzip.open(ledger,'wt',encoding='utf8') as out:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        assert conn.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
        report['sources_before']=source_fingerprints(conn)
        for area in planning.AREAS:
            gen=query.generation(conn,area);base,params=query.source(gen);snapshot=gen['metadata']['snapshot']['snapshot_id']
            originals={r['source_line_id']:r['cells'] for r in conn.execute("SELECT source_line_id,jsonb_build_object('Ser.',row_data->'Ser.','Aboc.',row_data->'Aboc.','Maq.',row_data->'Maq.','1ª Oper.',row_data->'1ª Oper.') cells FROM raw_mtg.plan_production_rows WHERE snapshot_id=%s",(snapshot,))}
            totals=Counter();states=Counter();examples={}
            with conn.cursor(name='counter_policy_'+area) as cursor:
                cursor.execute("SELECT m.row_key,c.values_json,c.detail->'operations' operations,c.detail->'original' original,c.detail->'raw' raw,c.detail->'calculation' calc,c.detail->>'need_id' need_id,c.detail->>'plan_key' plan_key,c.detail->'sources' sources"+base,params)
                for row in cursor:
                    v=row['values_json'];raw=row['raw'] or {};calc=row['calc'];q=count(v.get('quantity_required'))
                    primary,applicable=codes(v,area);ops={str(o['operation']):o for o in row['operations'] or []}
                    observed={str(s['operation']):s for s in calc['production_sources']};key=row['row_key'];totals['pieces']+=1
                    compatible=not row['plan_key'] or identity(v)==identity(row['original'] or {})
                    initial=bool(row['need_id'] and not row['plan_key'] and not row['sources'])
                    check('compatible',calc['compatible'],compatible,area=area,key=key)
                    check('operation_population',sorted(observed),sorted(applicable),area=area,key=key)
                    if row['plan_key'] in originals:
                        wanted=originals[row['plan_key']]
                        check('original_macro_cells',{k:raw.get(k) for k in wanted},wanted,area=area,key=key)
                        totals['original_macro_rows']+=1
                    wanted_operations=[]
                    for code in applicable:
                        operation=ops.get(code,{'operation':code});macro=macro_for(code,primary,area,raw,operation)
                        wanted=select_counter(operation,macro,compatible=compatible,local_initial=initial)
                        wanted.update(operation=code,remaining=max(q-wanted['value'],0) if q is not None and wanted['value'] is not None else None,
                                      excess=max(wanted['value']-q,0) if q is not None and wanted['value'] is not None else None,
                                      percent=100*wanted['value']/q if q and wanted['value'] is not None else None)
                        actual=observed.get(code,{})
                        for field,expected in wanted.items():
                            actual_value=sorted(actual.get(field,[])) if field=='coverage_reasons' else actual.get(field)
                            check(field,actual_value,expected,area=area,key=key,operation=code)
                        check('records_preserved',actual.get('records'),operation.get('ocr_records') or [],area=area,key=key,operation=code)
                        check('unavailable_reason',bool(actual.get('reason')) if wanted['value'] is None else actual.get('reason') is None,True,area=area,key=key,operation=code)
                        target=('cut' if code=='corte' else 'boc') if area=='perfis' else 'made' if code==primary else None
                        if target:check(target,v.get(target),wanted['value'],area=area,key=key,operation=code)
                        if area=='cantoneiras':
                            check('ocr_op_'+code,v.get('ocr_op_'+code),wanted['ocr'],area=area,key=key)
                            if code==primary:check('ocr_quantity',v.get('ocr_quantity'),wanted['ocr'],area=area,key=key)
                        state=wanted['origin'];states[state]+=1;totals['operations']+=1
                        if wanted['coverage_reasons']:totals['operations_with_coverage_reasons']+=1
                        if wanted['difference'] is not None and wanted['difference']!=0:totals['ocr_excel_differences']+=1
                        if wanted['excess']:totals['production_excess']+=1
                        if state not in examples:examples[state]={'key':key,'of':v.get('of'),'reference':v.get('component_ref'),'operation':code,'expected':wanted}
                        wanted_operations.append({'expected':wanted,'observed':actual,'original_macro':macro,'operation_inputs':operation})
                    out.write(json.dumps({'area':area,'key':key,'compatible':compatible,'local_initial':initial,'operations':wanted_operations},ensure_ascii=False)+'\n')
            report['areas'][area]={'generation':gen['id'],'totals':dict(totals),'states':dict(states),'examples':examples}
            print(area,dict(totals),dict(states),flush=True)
        report['sources_after']=source_fingerprints(conn)
    assert report['sources_before']==report['sources_after']
    report['ledger']={'file':ledger.name,'sha256':hashlib.sha256(ledger.read_bytes()).hexdigest()}
    report['result']='failed' if report['failures'] else 'passed'
    (FOLDER/(args.output+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(report['result'],report['checks'],'checks',len(report['failures']),'failures',flush=True)
    assert not report['failures'],report['failures'][:1]


if __name__=='__main__':main()
