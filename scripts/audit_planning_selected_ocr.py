"""Independent central OCR-to-piece reconciliation in the isolated full copy.

Uses raw imported identities and central validated records, never calls the
application association or production selection functions. Does not prove live
source ingestion or the inaccessible original OCR Windows publisher.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re

from scripts.audit_planning_formula_population import FOLDER, equal, number


def text(value):
    return re.sub(r'\s+', ' ', str(value or '').strip().upper())


def order(value):
    match = re.fullmatch(r'(?:OF[ ._-]*)?(\d{4,10})', text(value))
    return 'OF'+match[1] if match else None


def profile(value):
    # Presentation-only normalization: keep every dimension and profile family.
    return re.sub(r'\s+', '', text(value)).replace('×','X').replace(',','.').removeprefix('Ø')


PERFIS_OPERATIONS = {
    'ABOCARDAR':'abocardar', 'MAQ. ABOCARDAR':'abocardar',
    'DOALL PAV1':'corte', 'MEBA':'corte', 'SERROTE DISCO PAV 1':'corte',
    'SERROTE DOALL PAV.1':'corte', 'SERROTE FITA THOMAS IS639 PAV.1':'corte',
    'SERROTE MEBA IS381 PAV 3':'corte', 'VANGUARD':'corte',
}


def source_fingerprints(conn):
    """Bind a source proof to complete central tables, including new events."""
    tables=[('mes_kanban.validated_sheets','sheet_uid'),
                              ('mes_kanban.production_records','id'),
                              ('mes_kanban.production_record_plan_refs','id'),
                              ('raw_mtg.plan_production_rows','source_line_id'),
                              ('planning_mtg.association_decisions','id'),
            ('planning_mtg.needs','id'),('planning_mtg.need_operations','id'),
            ('planning_mtg.need_sources','need_id,kind,source_id'),('planning_mtg.records','id'),
            ('planning_mtg.raw_objects','id'),('planning_mtg.need_conferences','id'),
            ('raw_mtg.cpis_rows','snapshot_id,excel_row'),('cpis_mtg.versions','id'),
            ('cpis_mtg.orders','version_id,source_row_no'),('raw_mtg.other_sheet_rows','snapshot_id,sheet_name,excel_row'),
            ('raw_mtg.machine_rows','snapshot_id,excel_row'),('planning_mtg.raw_workbook_evidence','snapshot_id'),
            ('ocr_original.instances','id'),('ocr_original.snapshots','id'),
            ('ocr_original.sheets','instance_id,sheet_id,content_hash'),
            ('ocr_original.snapshot_sheets','snapshot_id,sheet_id'),
            ('planning_mtg.original_association_decisions','id')]
    result={}
    for table,key in tables:
        if conn.execute('SELECT to_regclass(%s) t',(table,)).fetchone()['t']:
            # Fold fixed-size row digests so retained import history cannot
            # exceed PostgreSQL's single-value limit during an audit.
            result[table]=conn.execute('SELECT count(*) n,md5(string_agg(md5(t::text),\'\' ORDER BY '+key+')) hash FROM '+table+' t').fetchone()
    return result


def piece_codes(plan):
    if plan['area']=='perfis':
        return ['corte','abocardar']
    return list(dict.fromkeys(str(plan['raw'].get(k) or '').strip()
                             for k in ('1ª Oper.','2ª Oper.')
                             if str(plan['raw'].get(k) or '').strip().isdigit()
                             and str(plan['raw'].get(k) or '').strip() != '0'))


def record_operation(record, targets):
    if record['source_app']=='kanban-mes-mtg2':
        code = PERFIS_OPERATIONS.get(text(record.get('machine')))
        return code, {'kind':'explicit_machine_operation_name','machine':record.get('machine')}
    explicit = (record.get('extra') or {}).get('operation_code') or (record.get('extra') or {}).get('operacao')
    if explicit is not None:
        code=str(explicit).strip()
        if all(code in piece_codes(p) for p in targets):
            return code, {'kind':'recorded_operation_code','code':code}
        return None, {'kind':'recorded_code_not_applicable','code':code}
    sequences=[piece_codes(p) for p in targets]
    unique={codes[0] for codes in sequences if len(codes)==1}
    if sequences and all(len(codes)==1 for codes in sequences) and len(unique)==1:
        code=next(iter(unique))
        return code, {'kind':'only_same_operation_on_every_resolved_child','code':code,
                      'piece_operations':{p['key']:piece_codes(p) for p in targets}}
    return None, {'kind':'operation_requires_human_resolution'}


def resolve_probe(record, probe, plans, by_ref):
    of=order(record.get('production_order')) or order((record.get('frozen') or {}).get('production_order_no'))
    explicit=plans.get(probe.get('plan_key'))
    if explicit and explicit['of']==of and explicit['source_app']==record['source_app']:
        return explicit, [explicit], 'immutable_snapshot_key'
    candidates=by_ref.get((record['source_app'],of,text(probe.get('component_ref'))),[])
    length=number(probe.get('length_mm')); designation=profile(probe.get('profile_type'))
    matches=[p for p in candidates if (length is None or equal(length,p['length']))
             and (not designation or profile(p['profile'])==designation)]
    if length is not None and designation and len(matches)==1:
        return matches[0], matches, 'unique_full_technical_identity'
    return None, matches, 'ambiguous_or_incomplete_identity' if matches else 'no_current_matching_piece'


def reconcile(records, plans):
    by_ref=defaultdict(list)
    for p in plans.values():by_ref[p['source_app'],p['of'],text(p['reference'])].append(p)
    accepted=defaultdict(list); uncertain=defaultdict(list); resolution=[]
    for record in records:
        frozen=record.get('frozen') or {}
        probes=record.get('children') or ([] if record.get('full_profile') else [{
            'plan_key':record.get('matched_plan_key'),
            'component_ref':frozen.get('component_ref',record.get('model_ref')),
            'profile_type':frozen.get('profile_type',record.get('profile_type')),
            'length_mm':frozen.get('length_mm',record.get('length_mm')),
            'assumed_quantity':record.get('quantity')}])
        resolved=[resolve_probe(record,p,plans,by_ref) for p in probes]
        targets=[r[0] for r in resolved if r[0]]
        complete=bool(probes) and len(targets)==len(probes) and len({p['key'] for p in targets})==len(probes)
        code,basis=record_operation(record,targets) if complete else (None,{'kind':'unresolved_identity'})
        details={'record_id':record['id'],'sheet_uid':record['sheet_uid'],'row_index':record['row_index'],
                 'source_app':record['source_app'],'validated_at':record['validated_at'],
                 'operation':code,'operation_basis':basis,'complete_identity':complete,
                 'probes':[], 'status':'accepted' if complete and code else 'unresolved'}
        for probe,(target,candidates,method) in zip(probes,resolved):
            quantity=number(probe.get('assumed_quantity'))
            if quantity is not None and (quantity<0 or not quantity.is_integer()):quantity=None
            item={'child_key':probe.get('plan_key') if record.get('children') else None,
                  'original_probe':{k:probe.get(k) for k in ('plan_key','component_ref','profile_type','length_mm','assumed_quantity')},
                  'planning_key':target['key'] if target else None,'quantity':quantity,'method':method,
                  'candidates':[p['key'] for p in candidates]}
            details['probes'].append(item)
            if complete and code:
                accepted[target['key'],code].append({**{k:details[k] for k in ('record_id','sheet_uid','row_index','source_app','validated_at','operation','operation_basis')},**item})
            else:
                for p in candidates:uncertain[p['key']].append(record['id'])
        resolution.append(details)
    return accepted,uncertain,resolution


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='c02-selected-ocr');args=parser.parse_args()
    if not re.fullmatch(r'[a-z0-9-]+',args.output):parser.error('Use a simple proof prefix')
    os.environ['MES_PG_DSN']=json.loads(Path('/home/luis/.local/state/planning-backups/integral-20260923/isolated.json').read_text())['dsn']
    from app import planning
    from app.raw import query
    report={'at':datetime.now(timezone.utc).isoformat(),'environment':'planning_integral readonly repeatable read',
        'command':f'PYTHONPATH=. .venv/bin/python scripts/audit_planning_selected_ocr.py --output {args.output}',
        'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'boundary':'Central validated MES Perfis/Cantoneiras only. No live ingestion or Windows original OCR approval; no human decisions present in this fixture. Fallback and cross-origin conflict matrix remain separate gates.',
        'areas':{},'failures':[],'selected':[]}
    plans={};published={};counts=Counter()
    with planning.connect(readonly=True) as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        assert c.execute('SELECT current_database() n').fetchone()['n']=='planning_integral'
        assert c.execute('SELECT count(*) n FROM planning_mtg.association_decisions').fetchone()['n']==0,'Human-decision audit required for this population'
        for area in ('perfis','cantoneiras'):
            gen=query.generation(c,area);snapshot=gen['metadata']['snapshot']['snapshot_id']
            source_app='kanban-mes-mtg2' if area=='perfis' else 'kanban-mes'
            for p in c.execute('SELECT source_line_id,production_order_no,component_ref,profile_type,length_mm,row_data FROM raw_mtg.plan_production_rows WHERE snapshot_id=%s',(snapshot,)):
                length=number(p['length_mm'])
                if length is None and area=='cantoneiras':
                    raw=str(p['row_data'].get('Comp.') or '').strip()
                    if re.fullmatch(r'\d{1,3}(?:[ \u00a0\u202f]\d{3})+',raw):length=number(re.sub(r'\s+','',raw))
                plans[p['source_line_id']]={'key':'macro:'+p['source_line_id'],'area':area,'source_app':source_app,
                    'of':order(p['production_order_no']),'reference':p['component_ref'],'profile':p['profile_type'],
                    'length':length,'raw':{k:p['row_data'].get(k) for k in ('1ª Oper.','2ª Oper.')}}
            base,params=query.source(gen)
            rows=c.execute("SELECT m.row_key,c.values_json->'cut' cut,c.values_json->'made' made,c.detail->'calculation'->'production_sources' sources"+base,params).fetchall()
            for row in rows:published[row['row_key']]={'area':area,**row}
            report['areas'][area]={'generation':gen['id'],'snapshot':snapshot,'pieces':len(rows)}
        records=c.execute('''SELECT p.id,p.sheet_uid,p.row_index,p.quantity,p.production_order,p.model_ref,p.profile_type,
            p.length_mm,p.machine,p.matched_plan_key,p.full_profile,p.validated_at,
            jsonb_build_object('operation_code',p.extra->'operation_code','operacao',p.extra->'operacao') extra,
            coalesce(p.extra->'plan_identity',jsonb_path_query_first(v.cross_check,
            'strict $.rows[*] ? (@.row_index == $row)',jsonb_build_object('row',p.row_index),true)->'plan_identity') frozen,
            jsonb_path_query_first(v.cross_check,'strict $.rows[*] ? (@.row_index == $row)',jsonb_build_object('row',p.row_index),true)->'plan_refs' frozen_children,
            v.source_app FROM mes_kanban.production_records p JOIN mes_kanban.validated_sheets v USING(sheet_uid)
            WHERE v.source_app IN ('kanban-mes-mtg2','kanban-mes') ORDER BY p.id''').fetchall()
        children=defaultdict(list)
        for child in c.execute('SELECT production_record_id,plan_key,component_ref,profile_type,length_mm,assumed_quantity FROM mes_kanban.production_record_plan_refs ORDER BY production_record_id,plan_key'):
            children[child['production_record_id']].append(child)
        for r in records:r['children']=children[r['id']] or r.pop('frozen_children') or []
        report['source_fingerprints']=source_fingerprints(c)
    report['central_inputs_sha256']=hashlib.sha256(json.dumps(records,sort_keys=True,default=str).encode()).hexdigest()
    report['current_piece_identities_sha256']=hashlib.sha256(json.dumps(plans,sort_keys=True,default=str).encode()).hexdigest()
    accepted,uncertain,resolution=reconcile(records,plans)
    for key,row in published.items():
        for selected in row['sources'] or []:
            code=selected['operation'];expected=accepted.get((key,code),[])
            unique={(e['record_id'],e['child_key']):e for e in expected}
            ready=bool(expected) and not uncertain.get(key) and all(e['quantity'] is not None for e in expected)
            total=sum(e['quantity'] for e in unique.values()) if ready else None
            if selected['origin']!='OCR validado':
                if ready:
                    report['failures'].append({'check':'usable_central_events_not_selected','area':row['area'],'key':key,'operation':code,'expected':total,'observed':selected['value'],'origin':selected['origin'],'event_ids':[e['record_id'] for e in expected]})
                continue
            observed_records=selected['records'];observed_ids=Counter((e['record_id'],e['sheet_uid'],e.get('row_index'),number(e.get('quantity'))) for e in observed_records)
            expected_ids=Counter((e['record_id'],e['sheet_uid'],e['row_index'],e['quantity']) for e in unique.values())
            issues=[]
            if not ready:issues.append('independent_identity_operation_or_coverage_unresolved')
            if observed_ids!=expected_ids:issues.append('selected_event_population_differs')
            revisions={(e['record_id'],e['sheet_uid']):str(e['validated_at']).replace(' ','T') for e in expected}
            if any(str(e.get('validated_at')).replace(' ','T') != revisions.get((e['record_id'],e['sheet_uid'])) for e in observed_records):
                issues.append('selected_validation_revision_differs')
            if not equal(selected['value'],total):issues.append('selected_total_differs')
            if selected.get('coverage_reasons'):issues.append('selected_with_coverage_warning')
            proof={'area':row['area'],'key':key,'operation':code,'expected':total,'observed':selected['value'],
                   'events':list(unique.values()),'uncertain_records':uncertain.get(key,[]),'issues':issues,'result':'failed' if issues else 'passed'}
            report['selected'].append(proof);counts[row['area']]+=1
            if issues:report['failures'].append({'check':'selected_ocr_not_independently_proven',**proof})
    report['central_records']=len(records);report['record_resolution_counts']=dict(Counter(r['status'] for r in resolution))
    report['selected_counts']=dict(counts)
    ledger=FOLDER/(args.output+'-records.jsonl.gz')
    with gzip.open(ledger,'wt') as f:
        for r in resolution:f.write(json.dumps(r,ensure_ascii=False,default=str)+'\n')
    report['record_ledger']={'file':ledger.name,'sha256':hashlib.sha256(ledger.read_bytes()).hexdigest()}
    report['result']='failed' if report['failures'] else 'passed_in_stated_scope'
    (FOLDER/(args.output+'.json')).write_text(json.dumps(report,ensure_ascii=False,default=str,indent=2)+'\n')
    print('Central records',len(records),'selected',dict(counts),'failures',len(report['failures']),flush=True)
    if report['failures']:raise SystemExit(1)


if __name__=='__main__':main()
