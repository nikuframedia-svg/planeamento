"""Check derived explanation operands on the complete isolated population.

This is a metadata audit, not an independent approval of OCR association or
catalogue/source selection. Scalar arithmetic has a separate population auditor.
"""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from scripts.audit_planning_formula_population import positive, normalized, valid

FOLDER = Path('docs/validacao-planeamento-integral/20260923-execucao')
DIMENSIONS = {
    'varão redondo': ('outer_diameter_mm',), 'varão nervurado': ('outer_diameter_mm',),
    'varão quadrado': ('width_mm',), 'varão retangular': ('width_mm', 'height_mm'),
    'barra': ('width_mm', 'height_mm'), 'tubo redondo': ('outer_diameter_mm', 'thickness_mm'),
    'tubo quadrado': ('width_mm', 'thickness_mm'),
    'tubo retangular': ('width_mm', 'height_mm', 'thickness_mm'),
    'calha': ('width_mm', 'height_mm', 'thickness_mm'),
    'cantoneira': ('width_mm', 'height_mm', 'thickness_mm'), 'chapa': ('width_mm', 'thickness_mm'),
}
EVENT_FIELDS = {'source','instance_id','sheet_uid','record_id','row_index','child_key','operation','quantity','validated'}


def main():
    os.environ['MES_PG_DSN'] = json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
    from app import planning
    from app.raw import query
    from scripts.audit_planning_selected_ocr import source_fingerprints
    report = {'at':datetime.now(timezone.utc).isoformat(), 'areas':{}, 'failures':[],
              'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'boundary':__doc__, 'environment':'planning_integral, read-only repeatable read'}
    with planning.connect(readonly=True) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        assert conn.execute('SELECT current_database() n').fetchone()['n'] == 'planning_integral'
        report['sources_before'] = source_fingerprints(conn)
        for area in planning.AREAS:
            gen = query.generation(conn, area); base, args = query.source(gen)
            info = {'generation':gen['id'], 'rows':0, 'checks':0, 'by_field':Counter()}
            with conn.cursor(name='detail_'+area) as cursor:
                cursor.execute("SELECT m.row_key,c.values_json,c.detail->'calculation' calc,c.detail->>'need_id' need_id,c.detail->>'plan_key' plan_key,c.detail->'sources' sources"+base,args)
                for row in cursor:
                    v, calc = row['values_json'], row['calc']; rules = calc['rules']; checks = {}
                    q, length = valid(v.get('quantity_required'),integer=True), positive(v.get('length_mm'))
                    primary = 'corte' if area == 'perfis' else str(v.get('operation') or '').strip()
                    selected = {str(s['operation']):s for s in calc['production_sources']}
                    principal = selected[primary]; produced = principal['value']
                    expected = {
                        'remaining':{'Q':q,'produced':produced},
                        'production_excess':{'Q':q,'produced':produced},
                        'quantity_to_plan':{'Q':q,'produced':produced,'operation':primary},
                        'total_length':{'Q':q,'L':length}, 'total_m':{'Q':q,'L':length},
                        'remaining_m':{'saldo':v.get('remaining'),'L':length},
                        'section_unit':{'material_type':v.get('material_type'),'profile':v.get('profile')},
                        'section_total':{'A':v.get('section_unit'),'Q':q},
                        'section_pending':{'A':v.get('section_unit'),'saldo':v.get('remaining')},
                        'stock_length_mm':{'L':length,'manual_stock_length_mm':v.get('stock_length_mm') if v.get('stock_length_origin')=='Substituição manual/importada' else None},
                        'bars':{'saldo':v.get('remaining'),'S':v.get('stock_length_mm'),'L':length},
                        'weight':{'weight_unit':v.get('weight_unit'),'remaining':v.get('remaining')},
                    }
                    expected['section_unit'].update({k:positive(v.get(k)) for k in DIMENSIONS.get(normalized(v.get('material_type')),())})
                    period = {k:v.get(k) for k in ('expected_date','planned_year','planned_week')}
                    expected['expected_week'] = expected['expected_year'] = period
                    fields = [('corte','cut'),('abocardar','boc')] if area=='perfis' else [(primary,'made')]
                    for code, field in fields:
                        s = selected.get(code) or {}
                        evidence = {'operation':code,'ocr_total':s.get('ocr'),'excel_total':s.get('excel'),
                                    'compatible':calc['compatible'],
                                    'local_initial':bool(row['need_id'] and not row['plan_key'] and not row['sources']),
                                    'ocr_events':[{k:x for k,x in e.items() if k in EVENT_FIELDS} for e in s.get('records',[])],
                                    'coverage_reasons':s.get('coverage_reasons',[])}
                        if code=='abocardar':evidence['abocardar']=v.get('abocardar')
                        expected[field] = evidence
                        expected[field+'_pct'] = {'Q':q,field:s.get('value')}
                        checks[field+'_selected_origin'] = rules.get(field,{}).get('source') == (s['origin'] if s else 'Não aplicável')
                    if area=='perfis':
                        expected['boc_remaining']={'Q':q,'B':selected.get('abocardar',{}).get('value'),'abocardar':v.get('abocardar')}
                        expected['final_pct']={k:v.get(k) for k in ('abocardar','cut_pct','boc_pct')}
                        density=rules['weight_unit'].get('source',{}).get('density_kg_m3')
                        expected['weight_unit']={'A':v.get('section_unit'),'L':length,'density_kg_m3':density}
                    else:
                        secondary=next((s for code,s in selected.items() if code!=primary),{})
                        expected['secondary_remaining']={'Q':q,'produced':secondary.get('value'),'operation_detail':v.get('operation_detail')}
                        expected['ocr_quantity']={k:x for k,x in expected['made'].items() if k not in ('excel_total','local_initial')}
                        candidates=rules['weight_unit'].get('source') or []
                        rates={positive(c.get('kg_m')) for c in candidates}-{None}
                        expected['weight_unit']={'profile':v.get('profile'),'kg_m':next(iter(rates)) if len(rates)==1 else None,'L':length}
                    checks['contract']=calc['contract']=='planning-integral-20260923-v4'
                    for field, inputs in expected.items():
                        rule=rules.get(field,{})
                        checks[field+'_inputs']=rule.get('inputs')==inputs
                        checks[field+'_formula']=bool(rule.get('formula'))
                        checks[field+'_source']=bool(rule.get('source')) if v.get(field) is not None else True
                        checks[field+'_reason']=v.get(field) is not None or bool(rule.get('reason'))
                        checks[field+'_contract']=rule.get('contract')=='planning-integral-20260923-v4'
                        info['by_field'][field]+=1
                    info['rows']+=1;info['checks']+=len(checks)
                    failed=[name for name,ok in checks.items() if not ok]
                    if failed:
                        report['failures'].append({'area':area,'key':row['row_key'],'checks':failed,
                                                   'expected':expected,'observed':rules})
            report['areas'][area]=info
            print(area, info['rows'], info['checks'], 'checks', flush=True)
        report['sources_after']=source_fingerprints(conn)
    assert report['sources_before']==report['sources_after']
    report['checks']=sum(a['checks'] for a in report['areas'].values())
    report['result']='failed' if report['failures'] else 'passed'
    (FOLDER/'c04-derived-details-population.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(report['result'],len(report['failures']),'failures',flush=True)
    assert not report['failures']


if __name__=='__main__':main()
