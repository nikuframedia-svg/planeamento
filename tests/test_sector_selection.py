"""«Planear» (app/sector/selection.py) against a disposable PostgreSQL 16 with migrations 039–040."""
import importlib.util
import shutil
import socket
import subprocess
import time
import uuid
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app import planning
from app.sector import portfolio, selection
from tests.test_sector_portfolio import TODAY, data, raw

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("migrate", ROOT / "scripts/migrate.py")
migrate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migrate)


@pytest.fixture(scope="module")
def database():
    if shutil.which("docker") is None:
        pytest.skip("docker indisponível")
    name, password = f"planning-selection-{uuid.uuid4().hex[:10]}", uuid.uuid4().hex
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    subprocess.run(["docker", "run", "-d", "--rm", "--name", name, "-e", f"POSTGRES_PASSWORD={password}",
                    "-e", "POSTGRES_DB=dataresearchmtg", "-p", f"127.0.0.1:{port}:5432", "postgres:16-alpine"],
                   check=True, capture_output=True)
    dsn = f"host=127.0.0.1 port={port} dbname=dataresearchmtg user=postgres password={password}"
    try:
        deadline = time.monotonic() + 60
        while True:
            try:
                with psycopg.connect(dsn, connect_timeout=1):
                    break
            except psycopg.OperationalError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.5)
        prefix = ["docker", "exec", "-i", name, "psql", "-U", "postgres", "-d", "dataresearchmtg"]
        assert migrate.apply(prefix, ROOT / "sql")[:2] == ["039_schema_migrations.sql", "040_sector_selection.sql"]
        yield dsn
    finally:
        subprocess.run(["docker", "stop", name], capture_output=True)


@pytest.fixture()
def conn(database):
    with psycopg.connect(database, row_factory=dict_row) as c:
        c.execute("TRUNCATE planning_mtg.sector_selection, planning_mtg.sector_decision_events")
        c.commit()
        yield c


D = data(raw("OF1", "DLT319", 10, 1000), raw("OF1", "DLT20", 5, 2000), raw("OF2", "DLT319", 4, 1000),
         raw("OF3", "ED4T40", 8, 500, cut="2026-11-30"))


def payload(**kw):
    return {"setor": "cantoneiras", "vista": "referencia", "caminho": ["DLT", "DLT319"], "acao": "selecionar",
            "request_id": str(uuid.uuid4()), **kw}


def test_planear_a_sku_records_each_of_reference_pair_and_its_event(conn):
    result = selection.apply(payload(), data=D, conn=conn)
    assert result["changed"] == 2 and result["metres"] == pytest.approx(14.0)
    rows = conn.execute("SELECT production_order_no, reference, decision, revision, seen FROM planning_mtg.sector_selection ORDER BY 1").fetchall()
    assert [(r["production_order_no"], r["reference"], r["decision"], r["revision"]) for r in rows] == [
        ("OF1", "DLT319", "selected", 1), ("OF2", "DLT319", "selected", 1)]
    assert rows[0]["seen"]["metres"] == 10.0
    events = conn.execute("SELECT action, actor, detail FROM planning_mtg.sector_decision_events").fetchall()
    assert len(events) == 2 and {e["action"] for e in events} == {"selected"}
    assert events[0]["actor"] == "Utilizador não identificado" and events[0]["detail"]["caminho"] == ["DLT", "DLT319"]


def test_the_same_request_is_not_saved_twice(conn):
    request = payload()
    selection.apply(request, data=D, conn=conn)
    again = selection.apply(request, data=D, conn=conn)
    assert again["repeated"] and again["changed"] == 0
    assert conn.execute("SELECT count(*) AS n FROM planning_mtg.sector_decision_events").fetchone()["n"] == 2


def test_excluding_needs_a_reason_in_the_app_and_in_the_database(conn):
    with pytest.raises(planning.PlanningError, match="motivo"):
        selection.apply(payload(acao="excluir"), data=D, conn=conn)
    selection.apply(payload(acao="excluir", motivo="Aguarda validação do EP"), data=D, conn=conn)
    assert {r["decision"] for r in conn.execute("SELECT decision FROM planning_mtg.sector_selection").fetchall()} == {"excluded"}
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO planning_mtg.sector_selection (area, production_order_no, reference, decision, actor) "
                     "VALUES ('cantoneiras', 'OF9', 'X', 'excluded', 'teste')")
    conn.rollback()


def test_most_specific_decision_wins_and_clear_removes_it(conn):
    selection.apply(payload(vista="of", caminho=["OV1", "OF1"]), data=D, conn=conn)
    selection.apply(payload(caminho=["DLT", "DLT20"], acao="excluir", motivo="Material em falta"), data=D, conn=conn)
    decisions = selection.current("cantoneiras", conn=conn)
    assert ("OF1", "*") in decisions and decisions[("OF1", "DLT20")]["decision"] == "excluded"
    states = portfolio.groups("cantoneiras", "referencia", ["DLT"], data=D, decisions=decisions)
    by_ref = {g["key"]: g["states"] for g in states["groups"]}
    assert by_ref["DLT319"]["selecionado"] == pytest.approx(10.0) and by_ref["DLT20"]["excluido"] == pytest.approx(10.0)
    selection.apply(payload(caminho=["DLT", "DLT20"], acao="limpar"), data=D, conn=conn)
    assert ("OF1", "DLT20") not in selection.current("cantoneiras", conn=conn)
    actions = [e["action"] for e in conn.execute("SELECT action FROM planning_mtg.sector_decision_events ORDER BY id").fetchall()]
    assert actions == ["selected", "excluded", "cleared"]


def test_proposal_leaves_out_blocking_signals_and_is_filterable():
    d = data(raw("OF1", "DLT319", 10, 1000, cut="2026-09-01"), raw("OF2", "DLT20", 10, 1000, cut="2026-09-01", notes="ANULADA"),
             raw("OF3", "ED4T40", 10, 1000, cut="2026-12-01"))
    top = portfolio.groups("cantoneiras", "referencia", data=d)
    assert top["totals"]["states"]["proposta"] == pytest.approx(10.0) and top["totals"]["proposed_metres"] == pytest.approx(10.0)
    only = portfolio.groups("cantoneiras", "referencia", filters={"estado": "proposta"}, data=d)
    assert only["totals"]["ofs"] == 1


def test_web_save_checks_json_and_same_origin(monkeypatch):
    from app.web.planning_app import app
    monkeypatch.setenv("MES_PLANNING_SELECTION_ENABLED", "1")
    monkeypatch.setattr(selection, "apply", lambda p: {"changed": 1, "echo": p["acao"]})
    client = TestClient(app)
    url = "/planeamento/api/carteira/selecao"
    assert client.post(url, content="acao=selecionar", headers={"Content-Type": "text/plain"}).status_code == 415
    assert client.post(url, json=payload(), headers={"Origin": "https://outro.exemplo"}).status_code == 403
    assert client.post(url, json=payload()).json() == {"changed": 1, "echo": "selecionar"}
