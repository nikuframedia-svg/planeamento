"""Retenção do histórico RAW (scripts/raw_retention.py), 06/10/2026."""
import hashlib
import json
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from scripts import raw_retention as retention
from tests.test_raw_workspace import workspace, database, canonical, registry, postgres16  # noqa: F401
from app.raw import projection, query

ROOT = __import__('pathlib').Path(__file__).resolve().parents[1]
SQL050 = ROOT / 'sql/050_raw_retention_indexes.sql'


NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)


def gen(gid, dataset, days, **metadata):
    return retention.Generation(gid, dataset, NOW - timedelta(days=days), metadata)


# ---------------------------------------------------------------- regras puras

def test_rules_keep_current_previous_recent_objects_and_metadata_closure():
    generations = [
        gen(1, 'planning:perfis', 20), gen(2, 'planning:perfis', 19), gen(3, 'planning:perfis', 18),
        gen(4, 'production:perfis', 18), gen(5, 'production:perfis', 17),
        gen(6, 'planning:perfis', 16, core_generation='2'),
        # Capacidade antiga referida por uma referência semanal: puxa os cursores e os itens irmãos.
        gen(7, 'capacity_items:perfis', 15, source_fingerprint='fp-a'),
        gen(8, 'capacity:perfis', 15, source_fingerprint='fp-a', planning_versions={'perfis': '6', 'production:perfis': '4'},
            applied_planning_versions={'perfis': '3'}),
        gen(9, 'planning:perfis', 14), gen(10, 'planning:perfis', 13),
        gen(11, 'capacity_items:perfis', 12, source_fingerprint='fp-b'),
        gen(12, 'capacity:perfis', 12, source_fingerprint='fp-b'),
        gen(13, 'planning:perfis', 3),
        gen(14, 'planning:perfis', 1), gen(15, 'production:perfis', 1),
        gen(16, 'capacity_items:perfis', 1, source_fingerprint='fp-c'),
        gen(17, 'capacity:perfis', 1, source_fingerprint='fp-c'),
        gen(18, 'planning:perfis', 0),
    ]
    plan = retention.plan_generations(generations, keep_days=7, now=NOW, object_generation_refs={8, 999})
    assert plan.keep[18] == {'atual', 'recente'} and 'anterior' in plan.keep[14]
    assert 'recente' in plan.keep[13]
    assert plan.keep[8] == {'objeto'}
    # Fecho: 8 → planning 6, 3 e production 4; 6 → core 2; 8 → itens 7 pelo fingerprint.
    assert {2, 3, 4, 6, 7} <= set(plan.keep)
    assert plan.keep[7] == {'itens_capacidade'} and plan.keep[2] == {'metadados'}
    # 11 e 12 são as anteriores de capacity_items/capacity; só 1, 9 e 10 perdem os membros.
    assert plan.drop == [1, 9, 10]
    assert plan.keep[11] == {'anterior', 'itens_capacidade'} and plan.keep[12] == {'anterior'}
    # production 4 e 5: 5 é a anterior de production (15 é a atual), 4 vem da capacidade.
    assert {4, 5, 15} <= set(plan.keep)
    assert plan.kept_by_dataset['planning:perfis'] == [2, 3, 6, 13, 14, 18]
    assert plan.gaps('planning:perfis') == [(0, 2), (3, 6), (6, 13), (14, 18)]
    with pytest.raises(ValueError):
        retention.plan_generations(generations, keep_days=3, now=NOW)


def test_reference_extraction_is_deep_and_typed():
    h = hashlib.sha256(b'x').hexdigest()
    value = {'rows': [{'applied_rate': {'history_hash': h}}], 'sources': {'planning_versions': {'perfis': '12'}},
             'capacity_generation': 7, 'application_generations': [['perfis', 'planning', 31]],
             'flag': True, 'other': 55, h.upper(): 1, 'historical_evidence': {h: {}}}
    assert retention.generation_refs(value) == {7, 12, 31}
    assert retention.hash_refs(value) == {h}


# ---------------------------------------------------------------- PostgreSQL descartável

def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def row(key, n, **detail):
    return {'key': key, 'values': {'of': '4200', 'machine': 'MEBA', 'planning_active': True, 'n': n}, **detail}


def backdate(c, gid, days):
    c.execute('UPDATE planning_mtg.raw_generations SET created_at=now()-%s::interval WHERE id=%s', (f'{days} days', gid))


def evidence(c, digest, label):
    c.execute("INSERT INTO planning_mtg.raw_contents(hash,values_json,detail,search_text) VALUES(%s,'{}',%s,'')",
              (digest, Jsonb({'productivity': {'label': label}})))


@pytest.fixture()
def history(workspace):  # noqa: F811
    """Histórico realista: 7 gerações de planeamento, 3 de encomendas, evidência e uma referência semanal."""
    h_old, h_new, h_week = sha('evidencia-antiga'), sha('evidencia-atual'), sha('evidencia-referencia')
    m_old, m_keep = sha('manifesto-antigo'), sha('manifesto-mantido')
    ids = {}
    with psycopg.connect(workspace, row_factory=dict_row) as c:
        for digest, label in ((h_old, 'old'), (h_new, 'new'), (h_week, 'week')):
            evidence(c, digest, label)
        for digest, kind in ((m_old, 'ocr_manifest'), (m_keep, 'ocr_manifest')):
            c.execute("INSERT INTO planning_mtg.raw_contents(hash,values_json,detail,search_text) VALUES(%s,'{}',%s,'')",
                      (digest, Jsonb({kind: {'contract': 'ocr-scope-v1'}})))
        c.execute("INSERT INTO planning_mtg.raw_contents(hash,values_json,detail,search_text) VALUES(%s,'{}',%s,'')",
                  (sha('cache-macro'), Jsonb({'macro_inputs': {'orders': {}}})))
        p = 'planning:perfis'
        steps = [
            ('g1', 20, [row('A', 1), row('B', 1)], {}),
            ('g2', 15, [row('A', 2), row('B', 1)], {'ocr_manifest': m_old}),
            ('g3', 12, [row('A', 3), row('B', 1)], {'ocr_manifest': m_keep}),
            ('g4', 10, [row('A', 4), row('B', 2)], {}),
            ('g5', 9, [row('A', 5, calculation={'operation_estimates': [{'operation': 'corte', 'history_hash': h_old}]}),
                       row('B', 2)], {}),
            # Conteúdo partilhado: A volta exatamente ao conteúdo de g1.
            ('g6', 2, [row('A', 1), row('B', 2)], {}),
        ]
        for name, days, rows, meta in steps:
            ids[name] = projection.publish(c, p, 'fp-' + name, rows, {'area': 'perfis', **meta})['id']
            if name == 'g2':
                for o, odays in (('o1', 20), ('o2', 19), ('o3', 18)):
                    ids[o] = projection.publish(c, 'orders:perfis', 'fp-' + o,
                                                [{'key': '4200', 'values': {'of': '4200', 'v': o}}], {'area': 'perfis'})['id']
                    backdate(c, ids[o], odays)
            backdate(c, ids[name], days)
        patch = {'values': {'n': 100}, 'original': {}, 'rules': {},
                 'operation_estimates': [{'operation': 'corte', 'history_hash': h_new}], 'search_text': '4200 meba'}
        ids['g7'] = projection.publish_delta(c, p, 'fp-g7', [row('B', 3)], {'area': 'perfis'},
                                             estimate_patches={'A': patch})['id']
        # Referência semanal antiga: congela linhas com history_hash e cita a geração g3.
        c.execute("""INSERT INTO planning_mtg.raw_objects(id,kind,name,area,definition,actor)
            VALUES(%s,'week_reference','Plano W39/2026','perfis',%s,'teste')""",
                  (uuid.uuid4(), Jsonb({'area': 'perfis', 'year': 2026, 'week': 39,
                                        'sources': {'planning_versions': {'perfis': str(ids['g3'])}},
                                        'rows': [{'values': {'quantity': 1}, 'applied_rate': {'history_hash': h_week}}]})))
        # Tudo o que existe é antigo, exceto um conteúdo solto acabado de criar (protegido pela data).
        c.execute("UPDATE planning_mtg.raw_contents SET created_at=now()-interval '30 days'")
        c.execute("INSERT INTO planning_mtg.raw_contents(hash,values_json,detail,search_text) VALUES(%s,'{\"x\":1}','{}','x')",
                  (sha('recente-solto'),))
    return {'dsn': workspace, 'ids': ids, 'h_old': h_old, 'h_new': h_new, 'h_week': h_week,
            'm_old': m_old, 'm_keep': m_keep}


def snapshot(dsn):
    with psycopg.connect(dsn, row_factory=dict_row) as c:
        members = {(r['dataset'], r['row_key'], r['first_generation']): r['content_hash'] for r in
                   c.execute('SELECT * FROM planning_mtg.raw_members')}
        contents = {r['hash'] for r in c.execute('SELECT hash FROM planning_mtg.raw_contents')}
        generations = {r['id'] for r in c.execute('SELECT id FROM planning_mtg.raw_generations')}
    return members, contents, generations


def drop_indexes(dsn):
    with psycopg.connect(dsn, autocommit=True) as c:
        for name in retention.INDEXES:
            c.execute(f'DROP INDEX IF EXISTS planning_mtg.{name}')


def apply_050(dsn):
    with psycopg.connect(dsn) as c:  # uma só transação, como scripts/migrate.py (psql -1)
        c.execute(SQL050.read_text())


def index_oids(dsn):
    with psycopg.connect(dsn, row_factory=dict_row) as c:
        return {r['relname']: r['oid'] for r in c.execute(
            "SELECT relname, oid FROM pg_class WHERE relname = ANY(%s)", (list(retention.INDEXES),))}


def ready(dsn):
    """Índices válidos, como em produção depois de --create-indexes."""
    assert retention.main(['--create-indexes', '--dsn', dsn], log=lambda *_: None) == {
        retention.MEMBER_INDEX: True, retention.SOURCE_INDEX: True}


def run(dsn, tmp_path, *extra, log=None, progress=None):
    return retention.main(['--execute', '--dsn', dsn, '--batch-size', '100', '--log-dir', str(tmp_path), *extra],
                          log=log or (lambda *_: None), progress=progress)


def try_guard(dsn):
    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as c:
        ok = c.execute("SELECT pg_try_advisory_lock(hashtextextended('planning-raw-retention',0)) ok").fetchone()['ok']
        if ok:
            c.execute("SELECT pg_advisory_unlock(hashtextextended('planning-raw-retention',0))")
        return ok


def assert_expected_cleanup(history, contents_before):
    ids = history['ids']
    members, contents, _ = snapshot(history['dsn'])
    planning_members = {(k[1], k[2]) for k in members if k[0] == 'planning:perfis'}
    assert planning_members == {('A', ids['g3']), ('A', ids['g6']), ('A', ids['g7']),
                                ('B', ids['g1']), ('B', ids['g4']), ('B', ids['g7'])}
    removed = contents_before - contents
    assert len(removed) == 6 and history['h_old'] in removed and history['m_old'] in removed
    return members, contents


def test_dry_run_counts_and_execute_deletes_only_unreachable_history(history, tmp_path):
    ids, dsn = history['ids'], history['dsn']
    members_before, contents_before, generations_before = snapshot(dsn)
    logs = []
    summary = retention.main(['--dsn', dsn], log=logs.append)
    # O modo só contar não muda nada.
    assert snapshot(dsn) == (members_before, contents_before, generations_before)
    assert any('VACUUM (FULL' in line for line in logs)
    # A: membros de g1, g2, g4, g5 saem; g3 (referência), g6 (anterior), g7 (atual) ficam. Encomendas: o1 sai.
    assert summary['members']['por_dataset']['planning:perfis']['apagar'] == 4
    assert summary['members']['por_dataset']['orders:perfis']['apagar'] == 1
    assert summary['generations']['razoes']['objeto'] == 1
    # A2, A4, A5, o1 + evidência antiga + manifesto antigo.
    assert summary['contents']['apagar'] == 6

    # Sem índices o --execute recusa; --create-indexes cria-os e a sql/050 só os regista.
    drop_indexes(dsn)
    ready(dsn)
    oids = index_oids(dsn)
    apply_050(dsn)
    assert index_oids(dsn) == oids

    record = retention.main(['--execute', '--dsn', dsn, '--batch-size', '100',
                             '--log-dir', str(tmp_path)], log=logs.append)
    assert record['members_deleted'] == 5 and record['estado'] == 'concluido'
    assert record['lotes_ignorados'] == 0 and record['cedencias'] == 0
    saved = json.loads(next(tmp_path.glob('raw-retention-*.json')).read_text())
    assert saved['estado'] == 'concluido' and saved['members_deleted'] == 5
    members, contents, generations = snapshot(dsn)
    assert generations == generations_before  # as gerações ficam para auditoria
    planning_members = {(k[1], k[2]) for k in members if k[0] == 'planning:perfis'}
    assert planning_members == {('A', ids['g3']), ('A', ids['g6']), ('A', ids['g7']),
                                ('B', ids['g1']), ('B', ids['g4']), ('B', ids['g7'])}
    assert {k[2] for k in members if k[0] == 'orders:perfis'} == {ids['o2'], ids['o3']}
    removed = contents_before - contents
    assert len(removed) == 6
    assert history['h_old'] in removed and history['m_old'] in removed
    for kept in (history['h_new'], history['h_week'], history['m_keep'], sha('cache-macro'), sha('recente-solto')):
        assert kept in contents
    # Os membros restantes apontam todos para conteúdos existentes (a FK garante-o, confirmo à mesma).
    assert set(members.values()) <= contents

    # A app continua a ler a geração atual (conteúdo derivado resolvido sobre o pai partilhado) e uma versão mantida.
    with psycopg.connect(dsn, row_factory=dict_row) as c:
        current = query.generation(c, 'perfis')
        assert current['id'] == ids['g7']
        base, args = query.source(current)
        rows = {r['row_key']: r for r in c.execute('SELECT m.row_key,c.values_json,c.detail' + base, args)}
        assert rows['A']['values_json']['n'] == 100 and rows['B']['values_json']['n'] == 3
        assert rows['A']['detail']['calculation']['operation_estimates'][0]['history_hash'] == history['h_new']
        kept = query.generation(c, 'perfis', str(ids['g6']))
        base, args = query.source(kept)
        rows = {r['row_key']: r['values_json']['n'] for r in c.execute('SELECT m.row_key,c.values_json' + base, args)}
        assert rows == {'A': 1, 'B': 2}
        reference = query.generation(c, 'perfis', dataset='planning')
        assert reference['id'] == ids['g7']
    from app.raw import productivity
    assert productivity.evidence(history['h_new'])['label'] == 'new'

    # Repetir não apaga mais nada.
    again = retention.main(['--execute', '--dsn', dsn, '--log-dir', str(tmp_path)],
                           log=logs.append)
    assert again['members_deleted'] == 0 and sum(again['contents_deleted'].values()) == 0
    assert snapshot(dsn)[1] == contents


# ---------------------------------------------------------------- corrida com publicações

def test_publishers_waiting_detects_a_blocked_publisher(workspace):  # noqa: F811
    keys = ['capacity-revision', 'raw-build:perfis']
    with psycopg.connect(workspace, row_factory=dict_row) as c:
        c.execute("SELECT pg_advisory_xact_lock(hashtextextended('raw-build:perfis',0))")
        assert not retention._publishers_waiting(c, keys)

        def publisher():
            with psycopg.connect(workspace) as p:
                p.execute("SELECT pg_advisory_xact_lock(hashtextextended('raw-build:perfis',0))")

        thread = threading.Thread(target=publisher)
        thread.start()
        deadline = time.monotonic() + 10
        while not retention._publishers_waiting(c, keys):
            assert time.monotonic() < deadline, 'o publicador bloqueado não apareceu em pg_locks'
            time.sleep(0.05)
        assert not retention._publishers_waiting(c, ['raw-build:cantoneiras', 'raw:planning:perfis'])
        c.rollback()
    thread.join(10)
    assert not thread.is_alive()


def test_busy_publisher_lock_leaves_run_incomplete_and_a_later_run_finishes(history, tmp_path):
    dsn = history['dsn']
    ready(dsn)
    _, contents_before, _ = snapshot(dsn)
    with psycopg.connect(dsn) as holder:
        holder.execute("SELECT pg_advisory_xact_lock(hashtextextended('raw-build:perfis',0))")
        record = run(dsn, tmp_path, '--max-wait-s', '1')
        assert retention.cli(['--execute', '--dsn', dsn, '--max-wait-s', '0', '--log-dir', str(tmp_path)],
                             log=lambda *_: None) == 2
        holder.rollback()
    # Membros não precisam dos locks; nenhum conteúdo foi apagado.
    assert record['estado'] == 'incompleto' and record['members_deleted'] == 5
    assert record['lotes_ignorados'] == 1 and record['esperas_lock'] >= 1
    assert record['por_terminar'][0]['fase'].startswith('conteúdos ')
    assert snapshot(dsn)[1] == contents_before
    saved = [json.loads(p.read_text()) for p in tmp_path.glob('raw-retention-*.json')]
    assert saved and all(r['estado'] == 'incompleto' for r in saved)
    again = run(dsn, tmp_path)
    assert again['estado'] == 'concluido' and again['members_deleted'] == 0
    assert_expected_cleanup(history, contents_before)


def test_waiting_publisher_makes_the_batch_roll_back_and_retry(history, tmp_path, monkeypatch):
    dsn = history['dsn']
    ready(dsn)
    _, contents_before, _ = snapshot(dsn)
    answers = iter([True])
    seen = []

    def waiting(c, keys):
        assert 'capacity-revision' in keys and 'raw-build:perfis' in keys and 'raw:planning:perfis' in keys
        seen.append(keys)
        return next(answers, False)

    monkeypatch.setattr(retention, '_publishers_waiting', waiting)
    monkeypatch.setattr(retention.Options, 'retry_s', 0.01)
    record = run(dsn, tmp_path)
    assert record['cedencias'] == 1 and record['estado'] == 'concluido'
    assert len(seen) >= 3  # o lote cedido repetiu-se
    assert_expected_cleanup(history, contents_before)


def test_exclusive_lock_is_held_between_phases_and_a_second_run_refuses(history, tmp_path):
    dsn = history['dsn']
    ready(dsn)
    checks = {}

    def hook(record):
        if record['fase'] in ('membros', 'keep_ready'):
            checks[record['fase']] = try_guard(dsn)
        if record['fase'] == 'membros':
            with pytest.raises(retention.RetentionRefused, match='em curso'):
                retention.execute(dsn, keep_days=7, log=lambda *_: None)

    record = run(dsn, tmp_path, progress=hook)
    assert checks == {'membros': False, 'keep_ready': False}
    assert record['estado'] == 'concluido' and record['members_deleted'] == 5
    assert try_guard(dsn)  # libertado no fim


def test_execute_without_indexes_refuses_and_create_indexes_builds_valid_ones(history, tmp_path):
    dsn = history['dsn']
    drop_indexes(dsn)
    before = snapshot(dsn)
    with pytest.raises(retention.RetentionRefused, match='--create-indexes'):
        run(dsn, tmp_path)
    assert retention.cli(['--execute', '--dsn', dsn, '--log-dir', str(tmp_path)], log=lambda *_: None) == 1
    assert snapshot(dsn) == before
    # A sql/050 recusaria uma tabela grande; aqui (tabela pequena) não chega a ser preciso.
    ready(dsn)
    with psycopg.connect(dsn, row_factory=dict_row) as c:
        assert retention.index_state(c) == {retention.MEMBER_INDEX: True, retention.SOURCE_INDEX: True}
        defs = {r['indexname']: r['indexdef'] for r in c.execute(
            "SELECT indexname, indexdef FROM pg_indexes WHERE indexname = ANY(%s)", (list(retention.INDEXES),))}
    assert '(content_hash)' in defs[retention.MEMBER_INDEX]
    assert 'WHERE (detail_source_hash IS NOT NULL)' in defs[retention.SOURCE_INDEX]
    oids = index_oids(dsn)
    apply_050(dsn)
    assert index_oids(dsn) == oids  # sem efeito
    ready(dsn)  # repetir não faz nada


def test_sql050_creates_the_indexes_on_an_empty_database_and_refuses_invalid_ones(workspace):  # noqa: F811
    drop_indexes(workspace)
    apply_050(workspace)
    with psycopg.connect(workspace, row_factory=dict_row) as c:
        assert retention.index_state(c) == {retention.MEMBER_INDEX: True, retention.SOURCE_INDEX: True}
        c.execute("UPDATE pg_index SET indisvalid = false WHERE indexrelid = 'planning_mtg.raw_member_content_hash'::regclass")
    with pytest.raises(psycopg.errors.RaiseException, match='DROP INDEX CONCURRENTLY'):
        apply_050(workspace)
    drop_indexes(workspace)


def test_publication_during_cleanup_keeps_the_new_references(history, tmp_path):
    dsn, ids = history['dsn'], history['ids']
    ready(dsn)
    _, contents_before, _ = snapshot(dsn)
    published = {}

    def hook(record):
        # Depois da fotografia: uma geração volta a citar o manifesto antigo nos metadados.
        if record['fase'] == 'keep_ready' and 'a' not in published:
            with psycopg.connect(dsn, row_factory=dict_row) as c:
                published['a'] = projection.publish(c, 'planning:perfis', 'fp-mid-a', [row('A', 7), row('B', 3)],
                                                    {'area': 'perfis', 'ocr_manifest': history['m_old']})['id']
        # Já depois da atualização: um membro novo volta a citar a evidência antiga (detetado dentro dos locks).
        if record['fase'] == 'atualizado' and 'b' not in published:
            with psycopg.connect(dsn, row_factory=dict_row) as c:
                estimate = {'operation_estimates': [{'operation': 'corte', 'history_hash': history['h_old']}]}
                published['b'] = projection.publish(c, 'planning:perfis', 'fp-mid-b',
                                                    [row('A', 8, calculation=estimate), row('B', 3)],
                                                    {'area': 'perfis'})['id']

    record = run(dsn, tmp_path, progress=hook)
    assert set(published) == {'a', 'b'} and record['estado'] == 'concluido'
    assert record['atualizacoes'] >= 2
    members, contents, _ = snapshot(dsn)
    assert history['m_old'] in contents and history['h_old'] in contents
    removed = contents_before - contents
    assert len(removed) == 4  # A2, A4, A5 e o1; a evidência e o manifesto antigos ficaram
    assert set(members.values()) <= contents
    with psycopg.connect(dsn, row_factory=dict_row) as c:
        assert query.generation(c, 'perfis')['id'] == published['b']


def test_member_cursor_is_exact_and_a_failed_batch_is_finished_later(workspace, monkeypatch):  # noqa: F811
    with psycopg.connect(workspace, row_factory=dict_row, autocommit=True) as c:
        digest = sha('conteudo-membros')
        c.execute("INSERT INTO planning_mtg.raw_contents(hash,values_json,detail,search_text) VALUES(%s,'{\"x\":1}','{}','x')",
                  (digest,))
        g = [c.execute("INSERT INTO planning_mtg.raw_generations(dataset,fingerprint,metadata,row_count) "
                       "VALUES('t:perfis',%s,'{}',0) RETURNING id", (f'f{i}',)).fetchone()['id'] for i in range(7)]
        members = [  # (row_key, first, last): mantida só g[5]; sobreviventes intercalados
            ('k1', 0, 2), ('k2', 0, 2), ('k3', 0, 3), ('s1', 0, None), ('k4', 0, 1),
            ('k5', 1, 5), ('s2', 1, 6), ('k6', 1, 4),
            ('k7', 2, 3), ('s3', 2, 6), ('k8', 3, 5), ('s4', 4, 6), ('s5', 5, None)]
        for key, first, last in members:
            c.execute('INSERT INTO planning_mtg.raw_members(dataset,row_key,first_generation,last_generation,content_hash) '
                      'VALUES(%s,%s,%s,%s,%s)', ('t:perfis', key, g[first], g[last] if last is not None else None, digest))
    plan = retention.Plan(kept_by_dataset={'t:perfis': [g[5], g[6]]})
    opts = retention.Options(batch=2, retry_s=0.01)

    def remaining():
        with psycopg.connect(workspace, row_factory=dict_row) as c:
            return {r['row_key'] for r in c.execute("SELECT row_key FROM planning_mtg.raw_members WHERE dataset='t:perfis'")}

    real = retention._run_batch
    calls = {'n': 0}

    def flaky(*args, **kwargs):
        calls['n'] += 1
        return None if calls['n'] == 2 else real(*args, **kwargs)

    monkeypatch.setattr(retention, '_run_batch', flaky)
    stats = retention.new_record(7)
    with psycopg.connect(workspace, row_factory=dict_row, autocommit=True) as c:
        first = retention.delete_members(c, plan, opts=opts, stats=stats, log=lambda *_: None)
    assert first == 2 and stats['lotes_ignorados'] == 1
    assert stats['por_terminar'] == [{'fase': 'membros', 'dataset': 't:perfis', 'desde_geracao': g[0],
                                      'ate_geracao': g[5]}]
    monkeypatch.setattr(retention, '_run_batch', real)
    stats = retention.new_record(7)
    with psycopg.connect(workspace, row_factory=dict_row, autocommit=True) as c:
        second = retention.delete_members(c, plan, opts=opts, stats=stats, log=lambda *_: None)
    assert first + second == 8 and stats['lotes_ignorados'] == 0
    assert remaining() == {'s1', 's2', 's3', 's4', 's5'}


def test_record_is_saved_as_interrupted_when_the_run_fails_midway(history, tmp_path):
    dsn = history['dsn']
    ready(dsn)

    def hook(record):
        if record['fase'] == 'membros':
            raise RuntimeError('falha simulada depois dos membros')

    with pytest.raises(RuntimeError, match='falha simulada'):
        run(dsn, tmp_path, progress=hook)
    saved = json.loads(next(tmp_path.glob('raw-retention-*.json')).read_text())
    assert saved['estado'] == 'interrompido' and 'falha simulada' in saved['erro']
    assert saved['members_deleted'] == 5 and saved['finished_at']
    members, _, _ = snapshot(dsn)
    assert len([k for k in members if k[0] == 'planning:perfis']) == 6
    assert try_guard(dsn)
