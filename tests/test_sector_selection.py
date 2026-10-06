"""«Planear»/«Limpar» por membro (app/sector/selection.py) num PostgreSQL 16 descartável com as migrações 039, 040, 046 e 047.

Critérios CA05, CA06, CA07, CA10–CA12 e CA14 do plano de 02/10/2026."""
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
from app.sector import decisions as resolution, portfolio, selection
from tests.test_sector_portfolio import data, raw

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("migrate", ROOT / "scripts/migrate.py")
migrate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migrate)


@pytest.fixture(scope="module")
def database(tmp_path_factory):
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
        # This fixture deliberately has no legacy application tables. Limit it
        # to the independent selection migrations rather than later features.
        migrations = tmp_path_factory.mktemp('selection-migrations')
        names = ["039_schema_migrations.sql", "040_sector_selection.sql", "046_sector_member_selection.sql",
                 "047_member_selection_no_phase.sql", "048_family_sets_member_machine.sql"]
        for filename in names:
            shutil.copy2(ROOT / 'sql' / filename,migrations / filename)
        assert migrate.apply(prefix, migrations) == names
        yield dsn
    finally:
        subprocess.run(["docker", "stop", name], capture_output=True)


@pytest.fixture()
def conn(database):
    with psycopg.connect(database, row_factory=dict_row) as c:
        c.execute("TRUNCATE planning_mtg.sector_selection, planning_mtg.sector_decision_events, "
                  "planning_mtg.sector_member_selection, planning_mtg.sector_selection_requests, "
                  "planning_mtg.sector_member_machine, planning_mtg.sector_family_sets")
        c.commit()
        yield c


P8 = "Peddi 8"  # Planear só grava linhas com máquina
D = data(raw("OF1", "DLT319", 10, 1000, machine=P8), raw("OF1", "DLT20", 5, 2000, machine=P8), raw("OF2", "DLT319", 4, 1000, machine=P8),
         raw("OF3", "ED4T40", 8, 500, cut="2026-11-30", machine=P8))


def payload(**kw):
    return {"setor": "cantoneiras", "vista": "referencia", "caminho": ["DLT", "DLT319"], "acao": "selecionar",
            "request_id": str(uuid.uuid4()), **kw}


def keys(d, **where):
    return [x["key"] for x in d["lines"] if all(x[k] == v for k, v in where.items())]


def member_rows(conn):
    return conn.execute("SELECT member_key, decision, revision FROM planning_mtg.sector_member_selection ORDER BY member_key").fetchall()


def test_planear_a_group_records_each_member_and_its_event(conn):
    result = selection.apply(payload(), data=D, conn=conn)
    assert result["changed"] == 2 and result["metres"] == pytest.approx(14.0) and result["skipped_no_machine"] == 0
    rows = member_rows(conn)
    assert [(r["member_key"], r["decision"], r["revision"]) for r in rows] == [
        ("macro:s:plan:OF1:DLT319", "selected", 1), ("macro:s:plan:OF2:DLT319", "selected", 1)]
    # Nada é gravado por (OF, referência) nem por OF inteira.
    assert conn.execute("SELECT count(*) AS n FROM planning_mtg.sector_selection").fetchone()["n"] == 0
    events = conn.execute("SELECT kind, member_key, action, actor, detail FROM planning_mtg.sector_decision_events ORDER BY id").fetchall()
    assert len(events) == 2 and {e["kind"] for e in events} == {"member"}
    assert events[0]["actor"] == "Utilizador não identificado"
    assert events[0]["detail"]["before"]["decision"] is None and events[0]["detail"]["after"]["decision"] == "selected"


def test_the_same_request_is_not_saved_twice_and_a_reused_id_is_refused(conn):
    request = payload()
    selection.apply(request, data=D, conn=conn)
    again = selection.apply(request, data=D, conn=conn)
    assert again["repeated"] and again["changed"] == 0
    assert conn.execute("SELECT count(*) AS n FROM planning_mtg.sector_decision_events").fetchone()["n"] == 2
    with pytest.raises(planning.PlanningError, match="outro conteúdo") as error:
        selection.apply({**request, "acao": "limpar"}, data=D, conn=conn)
    assert error.value.status == 409


def test_excluding_needs_a_reason_in_the_app_and_in_the_database(conn):
    with pytest.raises(planning.PlanningError, match="motivo"):
        selection.apply(payload(acao="excluir"), data=D, conn=conn)
    selection.apply(payload(acao="excluir", motivo="Aguarda validação do EP"), data=D, conn=conn)
    assert {r["decision"] for r in member_rows(conn)} == {"excluded"}
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO planning_mtg.sector_member_selection (area, member_key, production_order_no, reference, decision, actor, request_id) "
                     "VALUES ('cantoneiras', 'k', 'OF9', 'X', 'excluded', 'teste', gen_random_uuid())")
    conn.rollback()


def eighteen():
    return data(*[raw("OF7", "DLT319", 2, 1000 + i, key=f"macro:s:plan:{i}", machine=P8) for i in range(18)])


def test_17_of_18_are_planned_exactly_and_reach_the_gantt_scope(conn):
    from app.sector import scope
    d = eighteen()
    members = portfolio.members("cantoneiras", "of_perfil", ["OF7", "L45X45X5"], data=d, decisions=selection.current("cantoneiras", conn=conn))
    assert members["total"] == 18 and len(members["keys"]) == 18
    chosen = [{"chave": k, "token": t} for k, t in zip(members["keys"][:17], members["tokens"][:17])]
    result = selection.apply({"setor": "cantoneiras", "acao": "selecionar", "membros": chosen, "request_id": str(uuid.uuid4())}, data=d, conn=conn)
    assert result["changed"] == 17 and sorted(result["keys"]) == sorted(members["keys"][:17])
    assert sorted(r["member_key"] for r in member_rows(conn)) == sorted(members["keys"][:17])
    decisions = selection.current("cantoneiras", conn=conn)
    states = [portfolio.decision_of(x, decisions) for x in d["lines"]]
    assert states.count("selected") == 17 and states.count(None) == 1
    selected = scope.read(conn)  # o mesmo resolver do Gantt
    gantt = [x["key"] for x in d["lines"] if scope.decision(selected, "cantoneiras", x["of"], x["reference"], [x["key"]]) == "selected"]
    assert sorted(gantt) == sorted(members["keys"][:17])
    counts = portfolio.counts("cantoneiras", "of_perfil", [], members["keys"][:17], data=d, decisions=decisions)
    assert counts["groups"]["OF7"] == {"selected": 17, "total": 18, "hidden_selected": 0}


def test_same_of_reference_with_two_profiles_and_an_inherited_whole_order_decision(conn):
    d = data(raw("OF1", "R", 10, 1000, key="k:a", machine=P8),
             {**raw("OF1", "R", 5, 2000, key="k:b"), "v": {**raw("OF1", "R", 5, 2000, machine=P8)["v"], "profile": "L60X60X6"}})
    conn.execute("INSERT INTO planning_mtg.sector_selection (area, production_order_no, reference, decision, actor) "
                 "VALUES ('cantoneiras', 'OF1', '*', 'selected', 'legado')")
    conn.commit()
    decisions = selection.current("cantoneiras", conn=conn)
    assert [portfolio.decision_of(x, decisions) for x in d["lines"]] == ["selected", "selected"]  # transição: nada muda
    line = next(x for x in d["lines"] if x["key"] == "k:b")
    token = portfolio.member_token(line, 0)
    selection.apply({"setor": "cantoneiras", "acao": "limpar", "membros": [{"chave": "k:b", "token": token}], "request_id": str(uuid.uuid4())}, data=d, conn=conn)
    assert [(r["member_key"], r["decision"]) for r in member_rows(conn)] == [("k:b", "cleared")]  # desmarcação explícita
    decisions = selection.current("cantoneiras", conn=conn)
    assert {x["key"]: portfolio.decision_of(x, decisions) for x in d["lines"]} == {"k:a": "selected", "k:b": None}
    # Planear outra vez o membro limpo: só esse.
    line_b = next(x for x in d["lines"] if x["key"] == "k:b")
    selection.apply({"setor": "cantoneiras", "acao": "selecionar", "request_id": str(uuid.uuid4()),
                     "membros": [{"chave": "k:b", "token": portfolio.member_token(line_b, 1)}]}, data=d, conn=conn)
    assert [(r["member_key"], r["decision"], r["revision"]) for r in member_rows(conn)] == [("k:b", "selected", 2)]


def test_a_changed_member_is_a_conflict_and_nothing_is_written(conn):
    d = eighteen()
    stale = [{"chave": x["key"], "token": portfolio.member_token(x, 0)} for x in d["lines"][:3]]
    changed = data(*[raw("OF7", "DLT319", 2 if i else 9, 1000 + i, key=f"macro:s:plan:{i}", machine=P8) for i in range(18)])  # o saldo do 1.º mudou
    with pytest.raises(selection.Conflict) as error:
        selection.apply({"setor": "cantoneiras", "acao": "selecionar", "membros": stale, "request_id": str(uuid.uuid4())}, data=changed, conn=conn)
    assert error.value.status == 409 and error.value.fields["conflicts"][0]["key"] == "macro:s:plan:0"
    assert member_rows(conn) == [] and conn.execute("SELECT count(*) AS n FROM planning_mtg.sector_decision_events").fetchone()["n"] == 0
    with pytest.raises(selection.Conflict):  # membro que já não está na carteira
        selection.apply({"setor": "cantoneiras", "acao": "selecionar", "membros": [{"chave": "nao-existe"}], "request_id": str(uuid.uuid4())}, data=d, conn=conn)


def test_select_all_of_a_large_group_uses_the_frozen_seal(conn):
    d = data(*[raw("OF8", "DLT319", 1, 1000, key=f"big:{i}", machine=P8) for i in range(1200)])
    decisions = selection.current("cantoneiras", conn=conn)
    page = portfolio.members("cantoneiras", "of_perfil", ["OF8", "L45X45X5"], limit=200, data=d, decisions=decisions)
    assert page["total"] == 1200 and len(page["items"]) == 200 and len(page["keys"]) == 1200 and page["next_cursor"] == 200
    with pytest.raises(selection.Conflict):
        selection.apply({"setor": "cantoneiras", "acao": "selecionar", "request_id": str(uuid.uuid4()),
                         "grupo": {"vista": "of_perfil", "caminho": ["OF8", "L45X45X5"], "selo": "antigo"}}, data=d, conn=conn)
    result = selection.apply({"setor": "cantoneiras", "acao": "selecionar", "request_id": str(uuid.uuid4()),
                              "grupo": {"vista": "of_perfil", "caminho": ["OF8", "L45X45X5"], "selo": page["seal"], "exceto": ["big:7"]}},
                             data=d, conn=conn)
    assert result["changed"] == 1199
    assert conn.execute("SELECT count(*) AS n FROM planning_mtg.sector_member_selection").fetchone()["n"] == 1199


def test_old_contract_resolves_exact_members_and_refuses_list_filters(conn):
    # O botão Planear do quadro (plano.js) usa vista OF sem filtros: grava os membros, não «*».
    result = selection.apply(payload(vista="of", caminho=["OV1", "OF1"]), data=D, conn=conn)
    assert result["changed"] == 2 and conn.execute("SELECT count(*) AS n FROM planning_mtg.sector_selection").fetchone()["n"] == 0
    with pytest.raises(planning.PlanningError, match="lupa"):
        selection.apply(payload(vista="of", caminho=["OV1", "OF1"], filtros={"q": "DLT20"}), data=D, conn=conn)


def test_a_new_import_finds_the_member_by_alias_and_new_lines_stay_out(conn):
    first = data(raw("OF1", "R", 10, 1000, key="old:1", machine=P8))
    selection.apply({"setor": "cantoneiras", "acao": "selecionar", "request_id": str(uuid.uuid4()),
                     "membros": [{"chave": "old:1", "token": portfolio.member_token(first["lines"][0], 0)}]}, data=first, conn=conn)
    second = data(raw("OF1", "R", 10, 1000, key="new:1", machine=P8), raw("OF1", "R2", 3, 500, key="new:2", machine=P8))
    second["lines"][0]["aliases"] = ["old:1"]  # a projeção conserva a identidade física única
    decisions = selection.current("cantoneiras", conn=conn)
    assert {x["key"]: portfolio.decision_of(x, decisions) for x in second["lines"]} == {"new:1": "selected", "new:2": None}
    status = portfolio.status_of(second["lines"][0], decisions)
    assert status == {"planeado": True, "nesting": False, "sem_maquina": False}
    assert portfolio.status_of(second["lines"][1], decisions) == {"planeado": False, "nesting": True, "sem_maquina": False}
    # Limpar pela chave nova apaga a decisão gravada com a chave antiga.
    token = portfolio.member_token(second["lines"][0], 1)
    selection.apply({"setor": "cantoneiras", "acao": "limpar", "membros": [{"chave": "new:1", "token": token}],
                     "request_id": str(uuid.uuid4())}, data=second, conn=conn)
    assert member_rows(conn) == []


def test_planear_skips_members_without_machine_and_refuses_when_none_has_one(conn):
    d = data(raw("OF1", "A", 10, 1000, key="m:1", machine=P8), raw("OF1", "B", 10, 1000, key="m:2"))
    tokens = {x["key"]: portfolio.member_token(x, 0) for x in d["lines"]}
    result = selection.apply({"setor": "cantoneiras", "acao": "selecionar", "request_id": str(uuid.uuid4()),
                              "membros": [{"chave": k, "token": t} for k, t in tokens.items()]}, data=d, conn=conn)
    assert result["changed"] == 1 and result["skipped_no_machine"] == 1
    assert [r["member_key"] for r in member_rows(conn)] == ["m:1"]
    decisions = selection.current("cantoneiras", conn=conn)
    assert {x["key"]: portfolio.status_of(x, decisions) for x in d["lines"]} == {
        "m:1": {"planeado": True, "nesting": False, "sem_maquina": False},
        "m:2": {"planeado": False, "nesting": False, "sem_maquina": True}}
    assert portfolio.groups("cantoneiras", "referencia", filters={"estado": "planeado"}, data=d, decisions=decisions)["list_totals"]["lines"] == 1
    with pytest.raises(planning.PlanningError, match="máquina") as error:
        selection.apply({"setor": "cantoneiras", "acao": "selecionar", "request_id": str(uuid.uuid4()),
                         "membros": [{"chave": "m:2", "token": tokens["m:2"]}]}, data=d, conn=conn)
    assert error.value.status == 422
    # Uma decisão antiga numa linha sem máquina não a faz «Planeado».
    legacy = resolution.Decisions({("OF1", "*"): {"decision": "selected"}})
    assert portfolio.status_of(d["lines"][1], legacy) == {"planeado": False, "nesting": False, "sem_maquina": True}


def test_the_authenticated_user_is_recorded_as_author(conn):
    from app import planning_registration as registration
    token = registration.ACTOR.set("planeador")
    try:
        result = selection.apply(payload(), data=D, conn=conn)
    finally:
        registration.ACTOR.reset(token)
    assert result["actor"] == "planeador"
    assert {r["actor"] for r in conn.execute("SELECT actor FROM planning_mtg.sector_member_selection").fetchall()} == {"planeador"}
    assert {r["actor"] for r in conn.execute("SELECT actor FROM planning_mtg.sector_decision_events").fetchall()} == {"planeador"}


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


def test_web_conflict_lists_the_affected_members(monkeypatch):
    from app.web.planning_app import app
    monkeypatch.setenv("MES_PLANNING_SELECTION_ENABLED", "1")

    def conflict(p):
        raise selection.Conflict("Alguns membros mudaram entretanto.", [{"key": "k1", "of": "OF1", "reference": "R"}])
    monkeypatch.setattr(selection, "apply", conflict)
    response = TestClient(app).post("/planeamento/api/carteira/selecao", json=payload())
    assert response.status_code == 409
    assert response.json()["fields"] == {"conflicts": [{"key": "k1", "of": "OF1", "reference": "R"}], "conflict_count": 1}


MACHINES = [{"id": "rid-25", "name": "Ficep Rapid 25T", "code": "RAPID25", "process": "Broca"},
            {"id": "rid-p8", "name": "Peddi 8", "code": "PEDDI8", "process": "Punção"}]


@pytest.fixture()
def catalogue(monkeypatch):
    from app.sector import family_sets
    monkeypatch.setattr(family_sets, "machines", lambda sector, conn=None: MACHINES)


def test_assign_machine_to_marked_lines_is_exact_idempotent_and_wins_over_the_tabela(conn, catalogue):
    from app.sector import machine_choice, member_machine
    d = data(raw("OF1", "A", 10, 1000, key="m:1", machine="Peddi 8"), raw("OF2", "B", 10, 1000, key="m:2"), raw("OF3", "C", 5, 1000, key="m:3"))
    tokens = {x["key"]: portfolio.member_token(x, 0) for x in d["lines"]}
    request = {"setor": "cantoneiras", "maquina": "rid-25", "request_id": str(uuid.uuid4()),
               "membros": [{"chave": k, "token": tokens[k]} for k in ("m:1", "m:2")]}
    result = member_machine.apply(request, data=d, conn=conn)
    assert result["changed"] == 2 and result["machine"] == "Ficep Rapid 25T"
    again = member_machine.apply(request, data=d, conn=conn)
    assert again["repeated"] and again["changed"] == 0
    ctx = machine_choice.context("cantoneiras", conn=conn)
    assert machine_choice.effective(ctx, ["m:1"], None, "Peddi 8")["machine"] == "Ficep Rapid 25T"  # Carteira vence a Tabela
    assert machine_choice.effective(ctx, ["m:3"], None, "")["machine"] == ""  # não marcada: nada muda
    events = conn.execute("SELECT kind, action, detail FROM planning_mtg.sector_decision_events WHERE kind = 'machine'").fetchall()
    assert len(events) == 2 and events[0]["detail"]["before"]["tabela"] in ("Peddi 8", "")
    # Tirar a escolha da Carteira devolve a máquina da Tabela.
    member_machine.apply({"setor": "cantoneiras", "maquina": None, "request_id": str(uuid.uuid4()),
                          "membros": [{"chave": "m:1"}]}, data=d, conn=conn)
    ctx = machine_choice.context("cantoneiras", conn=conn)
    assert machine_choice.effective(ctx, ["m:1"], None, "Peddi 8") == {"machine": "Peddi 8", "resource_id": None, "source": "tabela"}
    with pytest.raises(planning.PlanningError, match="máquina deste setor"):
        member_machine.apply({**request, "maquina": "outra", "request_id": str(uuid.uuid4())}, data=d, conn=conn)


def test_family_set_machine_and_one_set_per_family(conn, catalogue):
    from app.sector import family_sets, machine_choice
    first = family_sets.save({"setor": "cantoneiras", "nome": "Treliça", "familias": ["ZG", "M2"], "maquina": "rid-25",
                              "request_id": str(uuid.uuid4())}, conn=conn)
    ctx = machine_choice.context("cantoneiras", conn=conn)
    assert machine_choice.effective(ctx, ["x"], "ZG", "") == {"machine": "Ficep Rapid 25T", "resource_id": "rid-25", "source": "conjunto", "set": "Treliça"}
    assert machine_choice.effective(ctx, ["x"], "ZG", "Peddi 8")["source"] == "tabela"  # a Tabela vence o conjunto
    with pytest.raises(planning.PlanningError, match="ZG já está em «Treliça»") as error:
        family_sets.save({"setor": "cantoneiras", "nome": "Outro", "familias": ["ZG"], "maquina": "rid-p8", "request_id": str(uuid.uuid4())}, conn=conn)
    assert error.value.status == 409
    row = conn.execute("SELECT revision FROM planning_mtg.sector_family_sets").fetchone()
    family_sets.archive({"setor": "cantoneiras", "id": first["id"], "expected_revision": row["revision"], "request_id": str(uuid.uuid4())}, conn=conn)
    assert machine_choice.context("cantoneiras", conn=conn)["family"] == {}


def test_planear_on_a_group_keeps_earlier_exclusions(conn):
    d = data(raw("OF1", "A", 10, 1000, key="e:1", machine=P8), raw("OF1", "B", 10, 1000, key="e:2", machine=P8))
    line = next(x for x in d["lines"] if x["key"] == "e:2")
    selection.apply({"setor": "cantoneiras", "acao": "excluir", "motivo": "Anulada", "request_id": str(uuid.uuid4()),
                     "membros": [{"chave": "e:2", "token": portfolio.member_token(line, 0)}]}, data=d, conn=conn)
    result = selection.apply({"setor": "cantoneiras", "acao": "selecionar", "request_id": str(uuid.uuid4()),
                              "grupo": {"vista": "of_perfil", "caminho": ["OF1"]}}, data=d, conn=conn)
    assert result["changed"] == 1
    decisions = selection.current("cantoneiras", conn=conn)
    assert {x["key"]: portfolio.decision_of(x, decisions) for x in d["lines"]} == {"e:1": "selected", "e:2": "excluded"}


def test_a_repeated_group_request_returns_the_saved_result_even_after_the_group_changed(conn):
    d = eighteen()
    page = portfolio.members("cantoneiras", "of_perfil", ["OF7", "L45X45X5"], data=d, decisions=selection.current("cantoneiras", conn=conn))
    request = {"setor": "cantoneiras", "acao": "selecionar", "request_id": str(uuid.uuid4()),
               "grupo": {"vista": "of_perfil", "caminho": ["OF7", "L45X45X5"], "selo": page["seal"]}}
    first = selection.apply(request, data=d, conn=conn)
    again = selection.apply(request, data=d, conn=conn)  # o selo já mudou (revisões), mas é o mesmo pedido
    assert first["changed"] == 18 and again["repeated"] and again["changed"] == 0
