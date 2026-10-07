"""Lista de ordens do hub (/planeamento/api/ordens): resultado igual e cache por importação (07/10/2026).

A resposta de referência (tests/fixtures/order_list_golden.json) foi gravada com o código de 248c7c0,
antes da cache, sobre a mesma base descartável. Gravar outra vez só se a regra mudar de propósito:
    UPDATE_ORDER_LIST_GOLDEN=1 RUN_PG_INTEGRATION=1 pytest tests/test_planning_order_list_cache.py -k golden

Base PostgreSQL 16 descartável (Docker), nunca a base operacional.
"""
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app import cpis_sync, planning, planning_hub as hub, planning_local_orders, planning_needs as needs
from tests.test_planning_needs import canonical, registry, postgres16, request, vals, save  # noqa: F401 (fixtures)
from tests.test_planning_registry import direct_row, payload

needs_pg = pytest.mark.skipif(os.environ.get('RUN_PG_INTEGRATION') != '1', reason='PostgreSQL descartável opt-in')

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / 'tests/fixtures/order_list_golden.json'
UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
INSTANT = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}')


def _plan_row(conn, snap, key, of, ref, *, closed=False, row_data=None, line=True, remaining=36, valid=True):
    excel = int(key.split(':')[1])
    conn.execute('''INSERT INTO raw_mtg.plan_production_rows
        (snapshot_id,source_line_id,excel_row,external_row_number,production_order_no,sales_order_no,
         customer_name,designation,component_ref,material_type,profile_type,length_mm,quantity_planned,
         quantity_made,closed_x,row_data) VALUES (%s,%s,%s,%s,%s,'OV-'||%s,'Cliente '||%s,'Obra '||%s,%s,
         'Tubo redondo','88.9x3',3003,100,64,%s,%s)''',
        (snap, key, excel, excel, of, ref, ref, ref, ref, closed,
         Jsonb({'Ser.': 64, 'Máquina Corte': 'MEBA', 'Picking': None, **(row_data or {})})))
    if line:
        conn.execute('''INSERT INTO analytics_mtg.kanban_plan_lines
            (snapshot_id,plan_key,remaining_quantity,remaining_valid,source_app,excel_row,
             production_order_no,component_ref,profile_type,material_type,length_mm,
             quantity_planned,quantity_made,remaining_rule,closed_x)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'88.9x3','Tubo redondo',3003,100,64,'source:test',%s)''',
            (snap, key, remaining, valid, 'kanban-mes-mtg2' if snap.startswith('s') else 'kanban-mes', excel,
             of, ref, closed))


def _cpis_row(conn, snap, n, of, status, *, ov=None, customer=None, record_date=None):
    conn.execute('''INSERT INTO raw_mtg.cpis_rows(snapshot_id,source_line_id,excel_row,production_order_no,
        sales_order_no,customer_name,planned_finish_date,observations,status,delivery_date,factory_unit,
        record_date,row_data) VALUES (%s,%s,%s,%s,%s,%s,'2026-10-20',%s,%s,'2026-10-30','MTG II',%s,'{}')''',
        (snap, f'{snap}:cpis:{n}', n, of, ov or 'OV-' + of, customer or 'Cliente ' + of, 'Obra ' + of,
         status, record_date))


def _sheet(conn, sheet, app):
    conn.execute("""INSERT INTO mes_kanban.validated_sheets(sheet_uid,sheet_date,template_name,family,operator_name,
        image_sha256,raw_extraction,sheet_data,validated_by,validated_at,source_app,sheet_no,source_filename,source_page)
        VALUES (%s,'2026-10-01','kanban','cantoneiras','Operador','x','{}','{}','Teste','2026-10-01T08:00:00Z',%s,1,%s,1)""",
        (sheet, app, sheet + '.pdf'))


def _production(conn, sheet, row, of):
    conn.execute("""INSERT INTO mes_kanban.production_records(sheet_uid,row_index,sheet_date,family,operator_name,
        production_order,quantity,validated_at) VALUES (%s,%s,'2026-10-01','cantoneiras','Operador',%s,1,
        '2026-10-01T08:00:00Z')""", (sheet, row, of))


@pytest.fixture()
def orders(canonical):
    """Uma OF de cada caso que a lista distingue, mais trabalho local da aplicação."""
    with psycopg.connect(canonical, autocommit=True) as conn:
        conn.execute((ROOT / 'sql/027_planning_local_orders.sql').read_text())
        conn.execute('TRUNCATE planning_mtg.local_orders, planning_mtg.local_order_history')
        conn.execute('TRUNCATE mes_kanban.production_records, mes_kanban.validated_sheets CASCADE')
        # Perfis (s1)
        _plan_row(conn, 's1', 's1:20', 'OF4300', 'REF-B')
        _plan_row(conn, 's1', 's1:21', 'OF4300', 'REF-C')
        _plan_row(conn, 's1', 's1:22', 'OF4400', 'REF-D', closed=True, row_data={'Fechado': 'X'})
        _plan_row(conn, 's1', 's1:23', 'OF4500', 'REF-E')
        _plan_row(conn, 's1', 's1:24', 'OF4600', 'REF-F', row_data={'Fechado': '#VALUE!'})
        _plan_row(conn, 's1', 's1:25', 'OF4900', 'REF-G', closed=True, remaining=0)
        _plan_row(conn, 's1', 's1:26', 'OF 4950', 'REF-H', line=False)
        _plan_row(conn, 's1', 's1:27', 'OF4910', 'REF-I', closed=True, remaining=0, valid=False)
        _plan_row(conn, 's1', 's1:28', 'OF4990', 'REF-J')
        # Cantoneiras (c1)
        _plan_row(conn, 'c1', 'c1:20', 'P', 'REF-X')
        _plan_row(conn, 'c1', 'c1:21', 'OF4300', 'REF-B2', closed=True, remaining=0, row_data={'2ª Oper.': 'Furar'})
        _plan_row(conn, 'c1', 'c1:22', 'OF4900', 'REF-G2', closed=True, remaining=0, row_data={'2ª Oper.': ''})
        _plan_row(conn, 'c1', 'c1:23', 'OF4500', 'REF-E2')
        # CPIS copiado nos dois Excel: a cópia mais recente decide (aqui pela data de registo).
        _cpis_row(conn, 's1', 2, 'OF4300', 'Em Aberto', customer='Cliente B', record_date='2026-09-01')
        _cpis_row(conn, 'c1', 2, 'OF4300', 'Fechada', customer='Cliente B2', record_date='2026-09-15')
        _cpis_row(conn, 's1', 3, 'OF4400', 'Em Produção')
        _cpis_row(conn, 's1', 4, 'OF4600', 'Estado novo')
        _cpis_row(conn, 's1', 5, 'OF4700', 'Em Aberto', ov='OV47', customer='Cliente sete')
        _cpis_row(conn, 'c1', 5, 'OF4800', 'Fechada')
        _cpis_row(conn, 's1', 6, 'OF4900', 'Em Produção')
        _cpis_row(conn, 's1', 7, 'OF4950', 'Pronta')
        _cpis_row(conn, 'c1', 7, 'OF4950', None)
        _cpis_row(conn, 's1', 8, 'OF4910', 'Em Produção')
        for sheet, app in [('f1', 'kanban-mes-mtg2'), ('f2', 'kanban-mes')]:
            _sheet(conn, sheet, app)
        for sheet, row, of in [('f1', 0, 'OF4300'), ('f1', 1, '4300'), ('f2', 0, 'OF4900')]:
            _production(conn, sheet, row, of)
    linked = needs.resolve(request(area='perfis', source={'kind': 'plan_line', 'id': 's1:20'}))
    with planning.connect() as conn:
        second = needs.source_data({'kind': 'plan_line', 'id': 's1:21'}, 'perfis', conn)
        conn.execute('INSERT INTO planning_mtg.need_sources(kind,source_id,need_id,version,payload) VALUES(%s,%s,%s,%s,%s)',
                     ('plan_line', 's1:21', linked['need_id'], 's1', Jsonb({**second, 'area': 'perfis'})))
        planning_local_orders.save(conn, 'OF5555', {'values': {'ov': 'OV-L', 'customer': 'Cliente local',
                                                               'designation': 'Obra local'}}, 'Teste')
        planning_local_orders.save(conn, 'OF4700', {'values': {'ov': 'OV-L7', 'customer': 'Outro cliente'}}, 'Teste')
        planning_local_orders.save(conn, 'OF4500', {'values': {'customer': 'Cliente da macro'}}, 'Teste')
    # Peça ligada a uma linha da macro mas que pertence a outra OF: a linha deixa de contar na OF de origem.
    moved = needs.resolve(request(area='perfis', source={'kind': 'plan_line', 'id': 's1:28'}))
    with psycopg.connect(canonical, autocommit=True) as conn:
        conn.execute("UPDATE planning_mtg.needs SET production_order_no='OF4995' WHERE id=%s", (moved['need_id'],))
    save(needs.resolve(request(area='perfis', production_order_no='OF998877', values=vals())))
    planning.save_record(payload())
    with psycopg.connect(canonical, autocommit=True) as conn:
        conn.execute("""INSERT INTO planning_mtg.reconciliations(request_id,production_order_no,area,component_ref,operation,
            evidence_fingerprint,evidence_json,actor,reason) VALUES (%s,'OF4200','perfis','REF-A','corte',%s,'{}','Teste','Conferência')""",
            (uuid.uuid4(), 'f' * 64))
    hub.clear_cache()
    yield canonical
    hub.clear_cache()


def _normal(value):
    """Tira o que muda de execução para execução (identificadores e instantes gerados agora)."""
    if isinstance(value, dict):
        return {key: _normal(item) for key, item in value.items()
                if key not in ('created_at', 'updated_at', 'changed_at')}
    if isinstance(value, list):
        return [_normal(item) for item in value]
    if isinstance(value, str):
        value = UUID.sub('<uuid>', value)
        return '<instante>' if INSTANT.match(value) else value
    return value


CASES = [dict(), dict(population='history'), dict(population='all'), dict(state='open'),
         dict(state='Fechada', population='all'), dict(state='Estado novo'), dict(pending_only=True),
         dict(pending_only=True, population='all'), dict(query='REF-B'), dict(query='ref-c', population='all'),
         dict(query='OV47'), dict(query='Cliente B'), dict(query='NEW-A'), dict(query='4950'),
         dict(query='REF-X', population='all'), dict(query='inexistente'), dict(page=2, page_size=3),
         dict(page=3, page_size=3, population='all'), dict(page=9, page_size=3)]
DETAILS = ['OF4300', 'OF4500', 'OF4950', 'OF998877', 'OF5555', 'OF4700', 'OF4990', 'OF4995']


def _observed():
    result = {'list': [], 'detail': {}, 'lines': {}, 'needs': {}}
    for case in CASES:
        result['list'].append({'case': case, 'result': _normal(hub.list_orders(**case))})
    for of in DETAILS:
        result['detail'][of] = _normal(hub.order_detail(of)['context'])
    for area, of in [('perfis', 'OF4300'), ('cantoneiras', 'OF4300'), ('perfis', 'OF4500')]:
        for scope in ('active', 'history', 'all'):
            lines = planning.order_lines(area, of, population=scope)['lines']
            result['lines'][f'{area}:{of}:{scope}'] = _normal(
                [[line['plan_key'], line.get('planning_key'), line['population']['active']] for line in lines])
    for scope in ('active', 'history', 'all'):
        result['needs'][scope] = _normal([[n['production_order_no'], n['component_ref']]
                                          for n in needs.list_needs(population=scope)['needs']])
    return result


@pytest.mark.pg_integration
@needs_pg
def test_golden_same_answer_cold_and_warm(orders):
    observed = _observed()
    if os.environ.get('UPDATE_ORDER_LIST_GOLDEN') == '1':
        GOLDEN.write_text(json.dumps(observed, ensure_ascii=False, indent=1, sort_keys=True) + '\n')
    expected = json.loads(GOLDEN.read_text())
    assert json.loads(json.dumps(observed)) == expected
    # Segunda volta: tudo a partir da cache; a resposta não muda.
    assert json.loads(json.dumps(_observed())) == expected


def _loads(monkeypatch, delay=0):
    """Conta as leituras completas das importações (a parte cara da lista)."""
    calls = []
    original = hub._load_generation

    def counted(*args, **kwargs):
        calls.append(threading.get_ident())
        time.sleep(delay)
        return original(*args, **kwargs)
    monkeypatch.setattr(hub, '_load_generation', counted)
    return calls


def _by_of(result):
    return {order['of']: order for order in result['orders']}


@pytest.mark.pg_integration
@needs_pg
def test_imports_are_read_once_while_they_do_not_change(orders, monkeypatch):
    calls = _loads(monkeypatch)
    first = hub.list_orders(population='all', page_size=100)
    assert hub.list_orders(population='all', page_size=100) == first
    hub.list_orders(query='REF', pending_only=True)
    hub.list_orders(population='history', state='Fechada')
    assert len(calls) == 1


@pytest.mark.pg_integration
@needs_pg
def test_a_new_import_or_cpis_version_is_seen_on_the_next_request(orders, monkeypatch):
    calls = _loads(monkeypatch)
    assert 'OF6000' not in _by_of(hub.list_orders(population='all', page_size=100))
    with psycopg.connect(orders, autocommit=True) as conn:
        conn.execute("""INSERT INTO audit_mtg.snapshots(snapshot_id,dataset_id,source_filename,source_path,source_sha256,loaded_at)
            VALUES ('s2','ds-met2-perfis','Met2_Plan_Perfis.xlsm','/tmp/perfis','novo',now()+interval '1 minute')""")
        _plan_row(conn, 's2', 's2:10', 'OF6000', 'REF-NOVA')
        _cpis_row(conn, 's2', 1, 'OF6000', 'Em Aberto')
    after = _by_of(hub.list_orders(population='all', page_size=100))
    assert after['OF6000']['plan'] == {'perfis': 1} and after['OF6000']['cpis_status'] == 'Em Aberto'
    assert after['OF4200']['plan'] == {'cantoneiras': 1}  # as linhas de Perfis do Excel antigo saem
    assert len(calls) == 2
    cpis_sync.publish([{**direct_row('OF4200'), 'status': 'Fechada'}], datetime.now(timezone.utc), central_dsn=orders)
    direct = hub.list_orders(population='all', page_size=100)
    assert direct['mode'] == 'direct' and _by_of(direct)['OF4200']['cpis_status'] == 'Fechada'
    assert len(calls) == 3
    # The same request again reads nothing new.
    assert hub.list_orders(population='all', page_size=100) == direct and len(calls) == 3


@pytest.mark.pg_integration
@needs_pg
def test_work_saved_in_the_application_is_seen_without_a_new_import(orders, monkeypatch):
    calls = _loads(monkeypatch)
    before = _by_of(hub.list_orders(population='all', page_size=100))
    assert before['OF4500']['plan'] == {'perfis': 1, 'cantoneiras': 1} and before['OF4500']['production_records'] == 0
    # Peça nova registada à mão, produção validada, conferência e OF local.
    save(needs.resolve(request(area='perfis', production_order_no='OF4500', values=vals())))
    with psycopg.connect(orders, autocommit=True) as conn:
        _production(conn, 'f1', 7, 'OF4500')
        conn.execute("""INSERT INTO planning_mtg.reconciliations(request_id,production_order_no,area,component_ref,operation,
            evidence_fingerprint,evidence_json,actor,reason) VALUES (%s,'OF4500','perfis','REF-E','corte',%s,'{}','Teste','x')""",
            (uuid.uuid4(), 'e' * 64))
    with planning.connect() as conn:
        planning_local_orders.save(conn, 'OF7777', {'values': {'customer': 'Cliente novo'}}, 'Teste')
    # Uma linha da macro passa a pertencer a uma peça: conta uma vez, na peça.
    needs.resolve(request(area='cantoneiras', source={'kind': 'plan_line', 'id': 'c1:23'}))
    after = _by_of(hub.list_orders(population='all', page_size=100))
    assert after['OF4500']['plan'] == {'perfis': 2, 'cantoneiras': 1}
    assert after['OF4500']['production_records'] == 1 and after['OF4500']['conferences'] == 1
    assert after['OF4500']['preparation']['records'] == 1
    assert after['OF7777']['customer_name'] == 'Cliente novo'
    assert len(calls) == 1


@pytest.mark.pg_integration
@needs_pg
def test_simultaneous_first_requests_read_the_imports_once(orders, monkeypatch):
    calls = _loads(monkeypatch, delay=0.5)
    results, errors = [], []

    def run():
        try:
            results.append(hub.list_orders(population='all', page_size=100))
        except Exception as exc:  # pragma: no cover - surfaced by the assertion below
            errors.append(exc)
    threads = [threading.Thread(target=run) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors and len(results) == 4 and all(r == results[0] for r in results)
    assert len(calls) == 1


def test_import_cache_keeps_the_newest_versions_and_retries_after_a_failure():
    cache = hub._ImportCache(size=2)
    built = []

    def build(value):
        def run():
            built.append(value)
            return value
        return run
    assert cache.get('a', build('A')) == 'A' and cache.get('a', build('X')) == 'A'
    cache.get('b', build('B'))
    cache.get('c', build('C'))  # 'a' sai: só ficam as duas versões mais recentes
    assert cache.get('a', build('A2')) == 'A2'
    assert built == ['A', 'B', 'C', 'A2']

    def broken():
        raise RuntimeError('base indisponível')
    with pytest.raises(RuntimeError):
        cache.get('d', broken)
    assert cache.get('d', build('D')) == 'D'
    cache.clear()
    assert cache.get('b', build('B2')) == 'B2'
