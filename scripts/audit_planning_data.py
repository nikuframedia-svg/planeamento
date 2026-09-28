"""Read-only audit of imported CPIS, planning and validated OCR evidence.

Run with the project venv from the repository root. It writes a local JSON
report only; PostgreSQL uses one repeatable-read, read-only transaction.
Connection secrets and operator names are not included in the report.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / '.env')
from app import planning, planning_hub
from app.dossiers.models import order_number

LATEST = """WITH latest AS (
 SELECT DISTINCT ON (dataset_id) * FROM audit_mtg.snapshots
 WHERE dataset_id IN ('ds-met2-perfis','ds-2638099daddc474e')
 ORDER BY dataset_id,loaded_at DESC,snapshot_id DESC
), c AS (
 SELECT s.dataset_id,r.* FROM raw_mtg.cpis_rows r JOIN latest s USING(snapshot_id)
), p AS (
 SELECT l.* FROM analytics_mtg.kanban_plan_lines l JOIN latest USING(snapshot_id)
) """
OPEN = {'Em Aberto', 'Em Produção'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    report = {'observed_at_utc': datetime.now(timezone.utc).isoformat(),
              'scope': 'Imported workbook versions and central validated OCR; not a live CPIS query',
              'queries': {}}
    with planning.connect(readonly=True) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        conn.execute("SET LOCAL statement_timeout = '90s'")

        def query(name, sql, params=(), *, latest=True):
            print('Reading', name, flush=True)
            rows = conn.execute((LATEST if latest else '') + sql, params).fetchall()
            report['queries'][name] = rows
            return rows

        snapshots = query('snapshots', 'SELECT * FROM latest ORDER BY dataset_id')
        query('cpis_states', '''SELECT dataset_id,status,count(*) rows,
            count(DISTINCT production_order_no) orders FROM c GROUP BY 1,2 ORDER BY 1,2''')
        query('cpis_duplicate_orders', '''SELECT dataset_id,production_order_no,count(*) rows,
            array_agg(DISTINCT sales_order_no) ovs,array_agg(DISTINCT status) states
            FROM c GROUP BY 1,2 HAVING count(*)>1 ORDER BY 1,2''')
        query('cpis_field_quality_open', '''SELECT dataset_id,count(*) orders,
            count(*) FILTER(WHERE sales_order_no IS NULL OR sales_order_no='') missing_ov,
            count(*) FILTER(WHERE customer_name IS NULL OR customer_name='') missing_customer,
            count(*) FILTER(WHERE observations IS NULL OR observations='') missing_description,
            count(*) FILTER(WHERE planned_finish_date IS NULL) missing_production_finish,
            count(*) FILTER(WHERE delivery_date IS NULL) missing_delivery,
            count(*) FILTER(WHERE planned_finish_date IS DISTINCT FROM delivery_date) finish_delivery_different,
            count(*) FILTER(WHERE planned_finish_date > delivery_date) production_finish_after_delivery,
            count(*) FILTER(WHERE actual_finish_date IS NOT NULL) has_actual_finish,
            count(*) FILTER(WHERE substring(production_order_no FROM '[0-9]+')::bigint<=250000) of_below_old_filter
            FROM c WHERE status IN ('Em Aberto','Em Produção') GROUP BY 1 ORDER BY 1''')
        query('cpis_dates_examples', '''SELECT production_order_no,planned_finish_date,delivery_date,
            actual_finish_date,status FROM c WHERE dataset_id='ds-met2-perfis'
            AND status IN ('Em Aberto','Em Produção') AND planned_finish_date IS DISTINCT FROM delivery_date
            ORDER BY production_order_no DESC LIMIT 8''')
        query('open_plan_coverage', '''SELECT c.dataset_id,count(*) open_orders,
            count(*) FILTER(WHERE EXISTS(SELECT 1 FROM p WHERE p.snapshot_id=c.snapshot_id
              AND p.production_order_no=c.production_order_no)) with_own_plan,
            count(*) FILTER(WHERE EXISTS(SELECT 1 FROM p
              WHERE p.production_order_no=c.production_order_no)) with_any_plan
            FROM c WHERE status IN ('Em Aberto','Em Produção') GROUP BY 1 ORDER BY 1''')
        query('combined_open', '''SELECT count(*) orders,
            count(*) FILTER(WHERE n_open=2) open_in_both,
            count(*) FILTER(WHERE n_open=1 AND n_copies=2) open_in_one_but_not_other,
            count(*) FILTER(WHERE n_copies=1) only_one_copy,
            count(*) FILTER(WHERE NOT EXISTS(SELECT 1 FROM p WHERE p.production_order_no=g.production_order_no)) without_any_plan
            FROM (SELECT production_order_no,count(*) n_copies,
              count(*) FILTER(WHERE status IN ('Em Aberto','Em Produção')) n_open
              FROM c GROUP BY 1) g WHERE n_open>0''')
        query('cpis_status_differences', '''SELECT a.status perfis_status,b.status cantoneiras_status,
            count(*) orders FROM c a JOIN c b USING(production_order_no)
            WHERE a.dataset_id='ds-met2-perfis' AND b.dataset_id='ds-2638099daddc474e'
            AND a.status IS DISTINCT FROM b.status GROUP BY 1,2 ORDER BY 1,2''')
        query('cpis_field_differences', '''SELECT count(*) common_orders,
            count(*) FILTER(WHERE a.sales_order_no IS DISTINCT FROM b.sales_order_no) ov,
            count(*) FILTER(WHERE a.customer_name IS DISTINCT FROM b.customer_name) customer,
            count(*) FILTER(WHERE a.observations IS DISTINCT FROM b.observations) description,
            count(*) FILTER(WHERE a.planned_finish_date IS DISTINCT FROM b.planned_finish_date) production_finish,
            count(*) FILTER(WHERE a.delivery_date IS DISTINCT FROM b.delivery_date) delivery,
            count(*) FILTER(WHERE a.actual_finish_date IS DISTINCT FROM b.actual_finish_date) actual_finish,
            count(*) FILTER(WHERE a.factory_unit IS DISTINCT FROM b.factory_unit) factory_unit
            FROM c a JOIN c b USING(production_order_no)
            WHERE a.dataset_id='ds-met2-perfis' AND b.dataset_id='ds-2638099daddc474e' ''')
        query('cpis_conflict_examples', '''SELECT a.production_order_no,a.status perfis_status,
            b.status cantoneiras_status,a.planned_finish_date perfis_finish,b.planned_finish_date cantoneiras_finish,
            a.delivery_date perfis_delivery,b.delivery_date cantoneiras_delivery
            FROM c a JOIN c b USING(production_order_no)
            WHERE a.dataset_id='ds-met2-perfis' AND b.dataset_id='ds-2638099daddc474e'
            AND a.status IS DISTINCT FROM b.status ORDER BY production_order_no DESC LIMIT 12''')
        query('plan_quality', '''SELECT source_app,count(*) lines,count(DISTINCT production_order_no) orders,
            count(*) FILTER(WHERE component_ref IS NULL OR component_ref='') missing_reference,
            count(*) FILTER(WHERE profile_type IS NULL OR profile_type='') missing_profile,
            count(*) FILTER(WHERE length_mm IS NULL OR length_mm<=0) missing_or_nonpositive_length,
            count(*) FILTER(WHERE quantity_planned IS NULL) unknown_required,
            count(*) FILTER(WHERE quantity_planned<=0) nonpositive_required,
            count(*) FILTER(WHERE quantity_planned<>trunc(quantity_planned)) fractional_required,
            count(*) FILTER(WHERE NOT remaining_valid OR remaining_quantity IS NULL) unknown_remaining,
            count(*) FILTER(WHERE remaining_valid AND remaining_quantity>0) positive_remaining,
            count(*) FILTER(WHERE closed_x AND remaining_valid AND remaining_quantity>0) closed_with_remaining,
            count(*) FILTER(WHERE NOT closed_x AND remaining_valid AND remaining_quantity=0) unclosed_zero_remaining,
            count(*) FILTER(WHERE quantity_made IS NULL) unknown_accumulated,
            count(*) FILTER(WHERE remaining_rule='calculated:qtd_minus_maq_blank_zero') blank_maq_as_zero,
            count(*) FILTER(WHERE cc.known_order IS NULL) missing_in_own_cpis_copy
            FROM p LEFT JOIN (SELECT DISTINCT snapshot_id,production_order_no known_order FROM c) cc
              ON cc.snapshot_id=p.snapshot_id AND cc.known_order=p.production_order_no
            GROUP BY 1 ORDER BY 1''')
        query('plan_on_open_orders', '''SELECT p.source_app,count(*) lines,count(DISTINCT p.production_order_no) orders,
            count(*) FILTER(WHERE NOT remaining_valid OR remaining_quantity IS NULL) unknown_remaining,
            count(*) FILTER(WHERE remaining_valid AND remaining_quantity>0) positive_remaining,
            count(*) FILTER(WHERE closed_x AND remaining_valid AND remaining_quantity>0) closed_with_remaining
            FROM p JOIN (SELECT DISTINCT snapshot_id,production_order_no known_order FROM c
              WHERE c.status IN ('Em Aberto','Em Produção')) cc
              ON cc.snapshot_id=p.snapshot_id AND cc.known_order=p.production_order_no
            GROUP BY 1 ORDER BY 1''')
        query('reused_references_different_geometry', '''SELECT source_app,count(*) groups,
            sum(n) lines FROM (SELECT source_app,production_order_no,component_ref,count(*) n
            FROM p WHERE component_ref IS NOT NULL GROUP BY 1,2,3
            HAVING count(DISTINCT(profile_type,length_mm))>1) x GROUP BY 1 ORDER BY 1''')
        query('geometry_examples', '''SELECT source_app,production_order_no,component_ref,count(*) n,
            array_agg(DISTINCT profile_type) profiles,array_agg(DISTINCT length_mm) lengths,
            array_agg(DISTINCT cutting_machine) machines FROM p WHERE component_ref IS NOT NULL
            GROUP BY 1,2,3 HAVING count(DISTINCT(profile_type,length_mm))>1
            ORDER BY production_order_no DESC LIMIT 12''')
        query('same_geometry_multiple_machines', '''SELECT source_app,count(*) groups,sum(n) lines
            FROM (SELECT source_app,production_order_no,component_ref,profile_type,length_mm,count(*) n
              FROM p WHERE component_ref IS NOT NULL GROUP BY 1,2,3,4,5
              HAVING count(DISTINCT cutting_machine)>1) x GROUP BY 1 ORDER BY 1''')
        query('ocr_summary', '''SELECT v.source_app,count(DISTINCT v.sheet_uid) sheets,count(p.id) records,
            count(DISTINCT p.production_order) written_of_variants,min(p.sheet_date) first_production,
            max(p.sheet_date) last_production,max(v.validated_at) last_validation,
            count(p.id) FILTER(WHERE p.quantity IS NULL) unknown_quantity,
            count(p.id) FILTER(WHERE p.quantity=0) zero_quantity,
            count(p.id) FILTER(WHERE p.quantity<0) negative_quantity,
            count(p.id) FILTER(WHERE p.quantity<>trunc(p.quantity)) fractional_quantity,
            count(p.id) FILTER(WHERE p.length_mm IS NULL) missing_length,
            count(p.id) FILTER(WHERE p.profile_type IS NULL OR p.profile_type='') missing_profile,
            count(p.id) FILTER(WHERE p.matched_plan_key IS NULL) no_parent_key,
            count(p.id) FILTER(WHERE p.full_profile) full_profile,
            count(p.id) FILTER(WHERE p.extra ? 'plan_identity') frozen_identity,
            count(p.id) FILTER(WHERE EXISTS(SELECT 1 FROM analytics_mtg.kanban_plan_lines l
              WHERE l.plan_key=p.matched_plan_key)) parent_key_any_import,
            count(p.id) FILTER(WHERE EXISTS(SELECT 1 FROM analytics_mtg.kanban_plan_lines l JOIN latest USING(snapshot_id)
              WHERE l.plan_key=p.matched_plan_key)) parent_key_current_import
            FROM mes_kanban.validated_sheets v LEFT JOIN mes_kanban.production_records p USING(sheet_uid)
            WHERE v.source_app IN ('kanban-mes-mtg2','kanban-mes') GROUP BY 1 ORDER BY 1''')
        query('ocr_expanded_refs', '''SELECT v.source_app,count(*) child_rows,
            count(DISTINCT r.production_record_id) parent_records,
            count(*) FILTER(WHERE r.assumed_quantity IS NULL) unknown_quantity,
            count(*) FILTER(WHERE r.assumed_quantity=0) zero_quantity,
            count(*) FILTER(WHERE r.assumed_quantity<0) negative_quantity,
            count(*) FILTER(WHERE EXISTS(SELECT 1 FROM p WHERE p.plan_key=r.plan_key)) current_key,
            count(*) FILTER(WHERE EXISTS(SELECT 1 FROM analytics_mtg.kanban_plan_lines l
              WHERE l.plan_key=r.plan_key)) historical_key
            FROM mes_kanban.production_record_plan_refs r JOIN mes_kanban.validated_sheets v USING(sheet_uid)
            GROUP BY 1 ORDER BY 1''')
        query('ocr_possible_repeated_images', '''SELECT source_app,image_sha256,count(*) sheets,
            array_agg(sheet_no ORDER BY sheet_no) sheet_numbers FROM mes_kanban.validated_sheets
            WHERE image_sha256 IS NOT NULL AND image_sha256<>'' GROUP BY 1,2 HAVING count(*)>1''')
        query('cpis_direct_versions', 'SELECT count(*) versions,max(last_confirmed_at) last_confirmation FROM cpis_mtg.versions', latest=False)
        query('preparations', 'SELECT source_kind,record_status,count(*) n FROM planning_mtg.records GROUP BY 1,2', latest=False)

        # Audit historical identity and the current hub classifier without writing anything.
        plans = conn.execute(LATEST + 'SELECT * FROM p').fetchall()
        produced = conn.execute('''SELECT p.id,p.sheet_uid,p.row_index,p.production_order,p.model_ref,
            p.length_mm,p.profile_type,p.quantity,p.matched_plan_key,p.plan_snapshot_id,p.full_profile,
            p.machine,p.extra,v.source_app FROM mes_kanban.production_records p
            JOIN mes_kanban.validated_sheets v USING(sheet_uid)
            WHERE v.source_app IN ('kanban-mes-mtg2','kanban-mes')''').fetchall()
        children = conn.execute('SELECT * FROM mes_kanban.production_record_plan_refs').fetchall()
        sheets = conn.execute('''SELECT source_app,sheet_uid,cross_check,sheet_data FROM mes_kanban.validated_sheets
            WHERE source_app IN ('kanban-mes-mtg2','kanban-mes')''').fetchall()
        perfis_raw = conn.execute(LATEST + '''SELECT r.excel_row,r.production_order_no,r.component_ref,
            r.quantity_planned,r.quantity_remaining_source,r.closed_x,r.row_data->>'Ser.' cut,
            r.row_data->>'Aboc.' aboc,r.row_data->>'Aborc.' aboc_requirement
            FROM raw_mtg.plan_production_rows r JOIN latest s USING(snapshot_id)
            WHERE s.dataset_id='ds-met2-perfis' ''').fetchall()

    for snapshot in snapshots:
        p = Path(snapshot['source_path'])
        snapshot['local_file_present'] = p.is_file()
        if p.is_file():
            snapshot['current_file_sha256'] = hashlib.sha256(p.read_bytes()).hexdigest()
            snapshot['matches_imported_hash'] = snapshot['current_file_sha256'] == snapshot['source_sha256']

    by_of = defaultdict(list)
    for row in plans:
        by_of[order_number(row['production_order_no'])].append(row)
    refs = defaultdict(list)
    for row in children:
        refs[row['production_record_id']].append(row)
    frozen_checks = {}
    for sheet in sheets:
        for check in (sheet['cross_check'] or {}).get('rows', []):
            frozen_checks[sheet['sheet_uid'], check.get('row_index')] = check
    association_counts, association_examples = defaultdict(Counter), defaultdict(list)
    frozen_counts = defaultdict(Counter)
    for row in produced:
        row['plan_refs'] = refs[row['id']]
        area = row['source_app']
        check = frozen_checks.get((row['sheet_uid'], row['row_index']), {})
        frozen_counts[area]['records'] += 1
        for label, value in [('extra_identity', (row.get('extra') or {}).get('plan_identity')),
                             ('cross_identity',check.get('plan_identity')),
                             ('cross_children',check.get('plan_refs')),
                             ('pg_children',row['plan_refs'])]:
            frozen_counts[area][label] += bool(value)
        if row['full_profile'] and not row['plan_refs']:
            frozen_counts[area]['full_without_pg_children'] += 1
            frozen_counts[area]['full_without_pg_but_cross_children'] += bool(check.get('plan_refs'))
        planning_hub._production_associations([row],by_of[order_number(row['production_order'])])
        status = row['association_status']
        association_counts[area][status] += 1
        if len(association_examples[(area,status)]) < 6:
            association_examples[(area,status)].append({k:row.get(k) for k in
              ('id','production_order','model_ref','length_mm','profile_type','machine','matched_plan_key','resolved_plan_keys')})
        if status=='technical_unique' and (row['length_mm'] is None or not row['profile_type']) and not row['plan_refs']:
            association_counts[area]['technical_unique_missing_top_level_geometry'] += 1
    report['current_hub_associations'] = dict(association_counts)
    report['association_examples'] = {':'.join(k):v for k,v in association_examples.items()}
    report['frozen_evidence'] = dict(frozen_counts)
    report['ocr_normalized_orders'] = dict(Counter({area: len({order_number(r['production_order']) for r in produced
        if r['source_app']==area and order_number(r['production_order'])}) for area in {r['source_app'] for r in produced}}))
    report['ocr_machine_counts'] = {area:dict(Counter(r['machine'] for r in produced if r['source_app']==area))
                                  for area in {r['source_app'] for r in produced}}
    report['perfis_accumulated'] = {'cut_value_present':sum(r['cut'] is not None for r in perfis_raw),
        'aboc_value_present':sum(r['aboc'] is not None for r in perfis_raw),
        'aboc_requirement_marks':dict(Counter(str(r['aboc_requirement']) for r in perfis_raw))}
    report['perfis_closed_with_remaining_examples'] = [r for r in perfis_raw
        if r['closed_x'] and r['quantity_remaining_source'] is not None and r['quantity_remaining_source']>0][:12]
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str)+'\n')
    print(str(path))
    for key in ('combined_open','plan_quality','ocr_summary','ocr_expanded_refs'):
        print(key,json.dumps(report['queries'][key],ensure_ascii=False,default=str))
    print('hub_associations',json.dumps(report['current_hub_associations'],ensure_ascii=False))


if __name__ == '__main__':
    main()
