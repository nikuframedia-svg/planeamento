"""Leitura direta do CPIS e publicação atómica no PostgreSQL central.

O conector deve correr no PC da fábrica. A origem é sempre read-only; o DSN
CPIS é deliberadamente diferente de MES_PG_DSN.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import uuid
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .config import settings
from .dossiers.models import order_number

VIEW = 'public.ordensfabrico_listagem_excel_vw'
VERSION = 'cpis-direct-v1'
REQUIRED_COLUMNS = {'of', 'ov', 'cliente', 'status'}
FIELDS = {
    'ov': 'sales_order_no', 'cliente': 'customer_name',
    'responsaveldp': 'responsible_dp', 'datainireal': 'actual_start_date',
    'datafimprevdp': 'planned_finish_date', 'datafimreal': 'actual_finish_date',
    'observacoes': 'observations', 'codtipobr': 'work_type_code',
    'destipobr': 'work_type_description', 'pesoof': 'production_order_weight_kg',
    'data': 'record_date', 'datarecdp': 'received_dp_date', 'status': 'status',
    'dataentregadl': 'delivery_date', 'datarecdl': 'received_dl_date',
    'datainiprev': 'planned_start_date', 'ordemsap': 'sap_order',
    'codunifab': 'factory_unit',
}


class SyncError(RuntimeError):
    def __init__(self, message: str, code: str = 'sync_failed'):
        super().__init__(message)
        self.code = code


def _json(value):
    if isinstance(value, (date, datetime, Decimal)):
        return value.isoformat() if isinstance(value, (date, datetime)) else str(value)
    raise TypeError(type(value).__name__)


def _clean(value):
    return str(value).strip() if value not in (None, '') else None


def read_source(dsn: str) -> tuple[list[dict], datetime]:
    if not dsn:
        raise SyncError('Falta CPIS_DSN no ambiente.', 'missing_dsn')
    queried_at = datetime.now(timezone.utc)
    try:
        with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=10) as conn:
            conn.read_only = True
            conn.execute('SET LOCAL statement_timeout = 120000')
            cursor = conn.execute(f'SELECT * FROM {VIEW}')
            columns = {str(item.name).lower() for item in cursor.description}
            rows = cursor.fetchall()
    except psycopg.Error as exc:
        raise SyncError('Não foi possível consultar o CPIS.', 'source_unavailable') from exc
    missing = REQUIRED_COLUMNS - columns
    if missing:
        raise SyncError('A vista CPIS não contém os campos obrigatórios: ' + ', '.join(sorted(missing)),
                        'invalid_structure')
    if not rows:
        raise SyncError('A vista CPIS devolveu zero linhas; a versão anterior foi conservada.',
                        'empty_result')
    normalized = []
    for index, original in enumerate(rows, 1):
        row = {str(k).lower(): v for k, v in original.items()}
        raw_of = _clean(row.get('of'))
        canonical = order_number(raw_of)
        normalized.append({
            'source_row_no': index,
            'production_order_no': canonical,
            'production_order_original': raw_of,
            **{target: row.get(source) for source, target in FIELDS.items()},
            'row_data': json.loads(json.dumps(row, ensure_ascii=False, default=_json)),
        })
    usable = sum(bool(row['production_order_no']) for row in normalized)
    if normalized and usable < len(normalized) * .95:
        raise SyncError('Mais de 5% das linhas CPIS não têm uma OF reconhecível.', 'invalid_orders')
    return normalized, queried_at


def _digest(rows: list[dict]) -> str:
    payload = json.dumps(rows, sort_keys=True, ensure_ascii=False, separators=(',', ':'), default=_json)
    return hashlib.sha256(payload.encode()).hexdigest()


def publish(rows: list[dict], queried_at: datetime, *, central_dsn: str | None = None) -> dict:
    central_dsn = central_dsn or os.environ.get('MES_PG_DSN') or settings.pg_dsn
    attempt_id, version_id = uuid.uuid4(), uuid.uuid4()
    digest = _digest(rows)
    state_counts = Counter(_clean(row.get('status')) or '(sem estado)' for row in rows)
    grouped = {}
    for row in rows:
        if row.get('production_order_no'):
            grouped.setdefault(row['production_order_no'], []).append(row)
    duplicate_orders = {key: values for key, values in grouped.items() if len(values) > 1}
    identity_fields = ('sales_order_no', 'customer_name', 'status', 'planned_finish_date', 'delivery_date')
    conflicting_orders = [key for key, values in duplicate_orders.items()
                          if any(len({str(row.get(field) or '') for row in values}) > 1
                                 for field in identity_fields)]
    validation = {'changed': None, 'duplicate_order_count': len(duplicate_orders),
                  'conflicting_order_count': len(conflicting_orders),
                  'conflicting_orders_sample': conflicting_orders[:50],
                  'unusable_order_rows': sum(not row.get('production_order_no') for row in rows)}
    started = datetime.now(timezone.utc)
    try:
        with psycopg.connect(central_dsn, row_factory=dict_row) as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('cpis_mtg.sync', 0))")
            existing = conn.execute(
                'SELECT id FROM cpis_mtg.versions WHERE content_sha256=%s FOR UPDATE', (digest,)
            ).fetchone()
            if existing:
                version_id = existing['id']
                conn.execute('UPDATE cpis_mtg.versions SET last_confirmed_at=%s WHERE id=%s',
                             (queried_at, version_id))
                changed = False
            else:
                conn.execute('''INSERT INTO cpis_mtg.versions
                    (id,source_view,content_sha256,row_count,state_counts,queried_at,last_confirmed_at,connector_version)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)''',
                    (version_id, VIEW, digest, len(rows), Jsonb(dict(state_counts)), queried_at,
                     queried_at, VERSION))
                insert = '''INSERT INTO cpis_mtg.orders
                    (version_id,source_row_no,production_order_no,production_order_original,
                     sales_order_no,customer_name,responsible_dp,actual_start_date,planned_finish_date,
                     actual_finish_date,observations,work_type_code,work_type_description,
                     production_order_weight_kg,record_date,received_dp_date,status,delivery_date,
                     received_dl_date,planned_start_date,sap_order,factory_unit,row_data)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)'''
                for row in rows:
                    conn.execute(insert, (version_id, *(row.get(key) for key in (
                        'source_row_no','production_order_no','production_order_original','sales_order_no',
                        'customer_name','responsible_dp','actual_start_date','planned_finish_date',
                        'actual_finish_date','observations','work_type_code','work_type_description',
                        'production_order_weight_kg','record_date','received_dp_date','status','delivery_date',
                        'received_dl_date','planned_start_date','sap_order','factory_unit')),
                        Jsonb(json.loads(json.dumps(row['row_data'], ensure_ascii=False, default=_json)))))
                published = conn.execute('SELECT count(*) AS value FROM cpis_mtg.orders WHERE version_id=%s',
                                         (version_id,)).fetchone()['value']
                if published != len(rows):
                    raise SyncError('A contagem publicada não corresponde à leitura CPIS.',
                                    'publication_count_mismatch')
                changed = True
            validation['changed'] = changed
            finished = datetime.now(timezone.utc)
            conn.execute('''INSERT INTO cpis_mtg.sync_attempts
                (id,started_at,finished_at,success,version_id,row_count,details)
                VALUES (%s,%s,%s,true,%s,%s,%s)''',
                (attempt_id, started, finished, version_id, len(rows), Jsonb(validation)))
        return {'ok': True, 'changed': changed, 'version_id': str(version_id),
                'row_count': len(rows), 'queried_at': queried_at.isoformat()}
    except psycopg.Error as exc:
        raise SyncError('Não foi possível publicar a versão CPIS no servidor central.',
                        'central_unavailable') from exc


def record_failure(error: SyncError, *, central_dsn: str | None = None,
                   started_at: datetime | None = None) -> None:
    """Regista uma falha de origem quando o servidor central ainda está acessível."""
    dsn = central_dsn or os.environ.get('MES_PG_DSN') or settings.pg_dsn
    try:
        with psycopg.connect(dsn) as conn:
            conn.execute('''INSERT INTO cpis_mtg.sync_attempts
                (id,started_at,finished_at,success,error_code,error_message,details)
                VALUES (%s,%s,%s,false,%s,%s,%s)''',
                (uuid.uuid4(), started_at or datetime.now(timezone.utc), datetime.now(timezone.utc),
                 error.code, str(error)[:500], Jsonb({})))
    except psycopg.Error:
        # A ausência de confirmações recentes permite à aplicação detetar também
        # a situação em que nem o PostgreSQL central está alcançável.
        return


def sync_once(*, source_dsn: str | None = None, central_dsn: str | None = None) -> dict:
    started = datetime.now(timezone.utc)
    try:
        rows, queried_at = read_source(source_dsn or os.environ.get('CPIS_DSN') or settings.cpis_dsn)
    except SyncError as exc:
        record_failure(exc, central_dsn=central_dsn, started_at=started)
        raise
    try:
        return publish(rows, queried_at, central_dsn=central_dsn)
    except SyncError as exc:
        record_failure(exc, central_dsn=central_dsn, started_at=started)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description='Sincroniza o CPIS para o planeamento central.')
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--interval', type=int, default=int(os.environ.get('CPIS_SYNC_INTERVAL_SECONDS', '300')))
    args = parser.parse_args(argv)
    while True:
        try:
            print(json.dumps(sync_once(), ensure_ascii=False), flush=True)
        except SyncError as exc:
            print(json.dumps({'ok': False, 'code': exc.code, 'error': str(exc)}, ensure_ascii=False), flush=True)
            if not args.watch:
                raise SystemExit(1)
        if not args.watch:
            break
        time.sleep(max(30, args.interval))


if __name__ == '__main__':
    main()
