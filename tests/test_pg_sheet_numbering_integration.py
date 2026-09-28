"""Integração da numeração com um PostgreSQL 16 descartável.

Executar explicitamente:
    RUN_PG_INTEGRATION=1 .venv/bin/python -m pytest -q \
        -m pg_integration tests/test_pg_sheet_numbering_integration.py
"""

from __future__ import annotations

import concurrent.futures
import os
import socket
import subprocess
import time
import uuid
from pathlib import Path

import psycopg
import pytest

from app import pg_store
from app.templates_spec import get_template


pytestmark = [
    pytest.mark.pg_integration,
    pytest.mark.skipif(
        os.environ.get("RUN_PG_INTEGRATION") != "1",
        reason="define RUN_PG_INTEGRATION=1 para criar o PostgreSQL descartável",
    ),
]


ROOT = Path(__file__).resolve().parents[1]


def _run(*args, input_text=None):
    return subprocess.run(
        args,
        input=input_text,
        text=True,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


@pytest.fixture(scope="module")
def postgres16():
    name = f"kanban-numbering-{uuid.uuid4().hex[:10]}"
    password = uuid.uuid4().hex
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    _run(
        "docker",
        "run",
        "-d",
        "--rm",
        "--name",
        name,
        "-e",
        f"POSTGRES_PASSWORD={password}",
        "-e",
        "POSTGRES_DB=dataresearchmtg",
        "-p",
        f"127.0.0.1:{port}:5432",
        "postgres:16-alpine",
    )
    admin_dsn = (
        f"host=127.0.0.1 port={port} dbname=dataresearchmtg "
        f"user=postgres password={password}"
    )
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                with psycopg.connect(admin_dsn, connect_timeout=1):
                    break
            except psycopg.OperationalError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("PostgreSQL de teste não arrancou")
                time.sleep(0.1)
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(
                "CREATE SCHEMA core_mtg; CREATE SCHEMA analytics_mtg; "
                "CREATE SCHEMA raw_mtg; CREATE SCHEMA audit_mtg"
            )
        for number in range(10, 18):
            path = next((ROOT / "sql").glob(f"{number:03d}_*.sql"))
            _run(
                "docker",
                "exec",
                "-i",
                name,
                "psql",
                "-v",
                "ON_ERROR_STOP=1",
                "-U",
                "postgres",
                "-d",
                "dataresearchmtg",
                input_text=path.read_text(),
            )
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f"ALTER ROLE mes_kanban_app PASSWORD '{password}'")
        app_dsn = (
            f"host=127.0.0.1 port={port} dbname=dataresearchmtg "
            f"user=mes_kanban_app password={password}"
        )
        yield admin_dsn, app_dsn
    finally:
        subprocess.run(
            ["docker", "stop", "-t", "2", name],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )


@pytest.fixture()
def clean_history(postgres16, monkeypatch):
    admin_dsn, app_dsn = postgres16
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute("TRUNCATE mes_kanban.validated_sheets CASCADE")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS "
            "validated_sheets_source_app_sheet_no_uidx "
            "ON mes_kanban.validated_sheets(source_app, sheet_no) "
            "WHERE source_app IS NOT NULL AND sheet_no IS NOT NULL"
        )
    monkeypatch.setenv("MES_PG_DSN", app_dsn)
    return admin_dsn


def sheet(uid: str, number: int, *, with_row: bool = False):
    row = {"of": "256000", "qtd": "1"} if with_row else {}
    return {
        "uid": uid,
        "sheet_no": number,
        "image_sha256": uid.ljust(64, "0"),
        "raw_extraction": {},
        "sheet_data": {
            "header": {"data": "09/09/2026", "operador": "TESTE"},
            "rows": [row] if with_row else [],
            "footer": {},
        },
        "cross_check": {"rows": ([{"row_index": 0, "cells": []}] if with_row else [])},
    }


def store(payload, minimum=1):
    return pg_store.store_validated_sheet(
        payload,
        get_template("serrote_kanban"),
        0,
        "teste",
        minimum_sheet_no=minimum,
    )


def insert_header(dsn: str, uid: str, source_app: str, number: int):
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO mes_kanban.validated_sheets "
            "(sheet_uid, sheet_date, template_name, family, operator_name, "
            "image_sha256, raw_extraction, sheet_data, edit_count, "
            "validated_by, source_app, sheet_no) "
            "VALUES (%s, DATE '2026-09-09', 'serrote_kanban', 'perfis', "
            "'TESTE', %s, '{}'::jsonb, '{}'::jsonb, 0, 'teste', %s, %s)",
            (uid, uid.ljust(64, "0"), source_app, number),
        )


def test_colisoes_concorrentes_e_retry_por_uid(clean_history):
    first = sheet("first", 1)
    second = sheet("second", 1)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(store, (first, second)))
    assert {result.sheet_no for result in results} == {1, 2}

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        same = list(pool.map(store, (sheet("same", 3), sheet("same", 3))))
    assert [result.sheet_no for result in same] == [3, 3]
    assert sum(not result.already_stored for result in same) == 1
    recovered = store(sheet("same", 99), minimum=100)
    assert recovered.sheet_no == 3
    assert recovered.next_sheet_no >= 100
    assert recovered.already_stored
    with psycopg.connect(clean_history) as conn:
        assert (
            conn.execute("SELECT count(*) FROM mes_kanban.validated_sheets").fetchone()[
                0
            ]
            == 3
        )


def test_source_app_isolada_e_folha_sem_factos(clean_history):
    insert_header(clean_history, "legacy", "kanban-mes", 10)
    result = store(sheet("mtg2", 10))
    assert result.sheet_no == 10
    assert result.row_count == 0

    stoppage = sheet("stoppage", 11)
    stoppage["sheet_data"]["rows"] = [
        {"motivo": "Avaria", "inicio": "08:00", "fim": "09:00",
         "duracao": "1", "resolvido": "Sim"}
    ]
    stopped = pg_store.store_validated_sheet(
        stoppage, get_template("perfis_paragens"), 0, "teste")
    assert stopped.row_count == 1
    recovered = pg_store.store_validated_sheet(
        stoppage, get_template("perfis_paragens"), 0, "teste")
    assert recovered.row_count == 1
    assert recovered.already_stored


@pytest.mark.parametrize("code", range(290, 295))
def test_new_stoppage_faces_never_become_production_records(clean_history, code):
    payload = sheet(f"tpl{code}-verso", 1)
    payload["sheet_data"]["rows"] = [{"motivo": "Avaria", "duracao": "1H"}]
    template = get_template(f"tpl{code}_paragens")
    result = pg_store.store_validated_sheet(payload, template, 0, "teste")
    assert result.row_count == 1
    with psycopg.connect(clean_history) as conn:
        assert conn.execute("SELECT count(*) FROM mes_kanban.stoppage_records WHERE sheet_uid=%s",
                            (payload["uid"],)).fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM mes_kanban.production_records WHERE sheet_uid=%s",
                            (payload["uid"],)).fetchone()[0] == 0


def test_escritor_antigo_forca_retry_da_transacao(clean_history):
    trigger_lock = 91028743
    with psycopg.connect(clean_history, autocommit=True) as setup:
        setup.execute(
            f"""
            CREATE OR REPLACE FUNCTION mes_kanban.block_new_writer()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF NEW.sheet_uid = 'new-writer' THEN
                PERFORM pg_advisory_xact_lock({trigger_lock});
              END IF;
              RETURN NEW;
            END $$;
            CREATE TRIGGER block_new_writer
            BEFORE INSERT ON mes_kanban.validated_sheets
            FOR EACH ROW EXECUTE FUNCTION mes_kanban.block_new_writer();
            """
        )
    blocker = psycopg.connect(clean_history, autocommit=True)
    blocker.execute("SELECT pg_advisory_lock(%s)", (trigger_lock,))
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(store, sheet("new-writer", 5))
            deadline = time.monotonic() + 5
            while True:
                with psycopg.connect(clean_history) as observer:
                    waiting = observer.execute(
                        "SELECT 1 FROM pg_stat_activity "
                        "WHERE wait_event_type = 'Lock' AND wait_event = 'advisory' "
                        "AND query LIKE 'INSERT INTO mes_kanban.validated_sheets%'"
                    ).fetchone()
                if waiting:
                    break
                if time.monotonic() >= deadline:
                    raise AssertionError("o novo escritor não chegou ao trigger")
                time.sleep(0.02)
            insert_header(clean_history, "old-writer", pg_store.SOURCE_APP, 5)
            blocker.execute("SELECT pg_advisory_unlock(%s)", (trigger_lock,))
            result = future.result(timeout=10)
    finally:
        blocker.close()
        with psycopg.connect(clean_history, autocommit=True) as setup:
            setup.execute(
                "DROP TRIGGER IF EXISTS block_new_writer "
                "ON mes_kanban.validated_sheets; "
                "DROP FUNCTION IF EXISTS mes_kanban.block_new_writer()"
            )
    assert result.sheet_no == 6


def test_erro_nas_linhas_reverte_cabecalho(clean_history):
    with psycopg.connect(clean_history, autocommit=True) as setup:
        setup.execute(
            """
            CREATE OR REPLACE FUNCTION mes_kanban.fail_rollback_row()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF NEW.sheet_uid = 'rollback' THEN
                RAISE EXCEPTION 'falha injetada após o cabeçalho';
              END IF;
              RETURN NEW;
            END $$;
            CREATE TRIGGER fail_rollback_row
            BEFORE INSERT ON mes_kanban.production_records
            FOR EACH ROW EXECUTE FUNCTION mes_kanban.fail_rollback_row();
            """
        )
    with pytest.raises(psycopg.errors.RaiseException, match="falha injetada"):
        store(sheet("rollback", 7, with_row=True))
    with psycopg.connect(clean_history) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM mes_kanban.validated_sheets "
                "WHERE sheet_uid = 'rollback'"
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM mes_kanban.production_records "
                "WHERE sheet_uid = 'rollback'"
            ).fetchone()[0]
            == 0
        )


def test_schema_sem_indice_bloqueia_antes_do_insert(clean_history):
    with psycopg.connect(clean_history, autocommit=True) as conn:
        conn.execute("DROP INDEX mes_kanban.validated_sheets_source_app_sheet_no_uidx")
    with pytest.raises(pg_store.SheetNumberingConfigurationError):
        store(sheet("no-index", 1))
    with psycopg.connect(clean_history) as conn:
        assert (
            conn.execute("SELECT count(*) FROM mes_kanban.validated_sheets").fetchone()[
                0
            ]
            == 0
        )
