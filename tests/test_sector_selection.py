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


@pytest.fixture(autouse=True)
def no_suggestions(monkeypatch):
    """Sem camada de pesquisa nesta base: nenhuma máquina sugerida, salvo quando o teste a dá."""
    monkeypatch.setattr(selection, "suggested_machines", lambda sector, lines, **kw: {})


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


def test_excluding_without_a_reason_keeps_the_author_and_time(conn):
    # Motivo opcional desde 07/10/2026; a base continua a exigir texto numa exclusão, por isso fica «Sem motivo indicado».
    selection.apply(payload(acao="excluir"), data=D, conn=conn)
    rows = conn.execute("SELECT decision, reason, actor, decided_at FROM planning_mtg.sector_member_selection").fetchall()
    assert {(r["decision"], r["reason"]) for r in rows} == {("excluded", resolution.NO_REASON)}
    assert all(r["actor"] and r["decided_at"] for r in rows)
    assert {e["reason"] for e in conn.execute("SELECT reason FROM planning_mtg.sector_decision_events").fetchall()} == {None}
    selection.apply(payload(acao="excluir", motivo="Aguarda validação do EP", caminho=["ED4", "ED4T40"]), data=D, conn=conn)
    assert conn.execute("SELECT reason FROM planning_mtg.sector_member_selection WHERE reference = 'ED4T40'").fetchone()["reason"] \
        == "Aguarda validação do EP"
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


def test_a_changed_member_stays_out_and_the_others_are_planned(conn):
    # Antes de 07/10/2026 um só membro mudado recusava o pedido inteiro (409, nada gravado).
    d = eighteen()
    stale = [{"chave": x["key"], "token": portfolio.member_token(x, 0)} for x in d["lines"][:3]] + [{"chave": "nao-existe"}]
    changed = data(*[raw("OF7", "DLT319", 2 if i else 9, 1000 + i, key=f"macro:s:plan:{i}", machine=P8) for i in range(18)])  # o saldo do 1.º mudou
    request = {"setor": "cantoneiras", "acao": "selecionar", "membros": stale, "request_id": str(uuid.uuid4())}
    result = selection.apply(request, data=changed, conn=conn)
    assert result["changed"] == 2 and sorted(result["keys"]) == ["macro:s:plan:1", "macro:s:plan:2"]
    assert result["skipped_count"] == 2 and {s["key"]: s["reason"] for s in result["skipped"]} == {
        "macro:s:plan:0": selection.CHANGED, "nao-existe": selection.GONE}
    assert sorted(r["member_key"] for r in member_rows(conn)) == ["macro:s:plan:1", "macro:s:plan:2"]
    again = selection.apply(request, data=changed, conn=conn)  # repetição: o resultado gravado, sem nova escrita
    assert again["repeated"] and again["skipped_count"] == 2 and len(member_rows(conn)) == 2
    with pytest.raises(selection.Conflict) as error:  # nada a gravar: só membros mudados ou que já não estão na carteira
        selection.apply({**request, "request_id": str(uuid.uuid4()), "membros": [stale[0], stale[3]]}, data=changed, conn=conn)
    assert error.value.status == 409 and {c["key"] for c in error.value.fields["conflicts"]} == {"macro:s:plan:0", "nao-existe"}


def test_a_member_marked_before_a_new_import_is_found_by_its_old_key(conn):
    old = data(raw("OF1", "R", 10, 1000, key="old:1", machine=P8))
    token = portfolio.member_token(old["lines"][0], 0)
    new = data(raw("OF1", "R", 10, 1000, key="new:1", machine=P8))
    new["lines"][0]["aliases"] = ["old:1"]
    result = selection.apply({"setor": "cantoneiras", "acao": "selecionar", "request_id": str(uuid.uuid4()),
                              "membros": [{"chave": "old:1", "token": token}]}, data=new, conn=conn)
    assert result["changed"] == 1 and result["keys"] == ["new:1"] and result["skipped_count"] == 0


def test_select_all_of_a_large_group_uses_the_frozen_seal(conn):
    d = data(*[raw("OF8", "DLT319", 1, 1000, key=f"big:{i}", machine=P8) for i in range(1200)])
    decisions = selection.current("cantoneiras", conn=conn)
    page = portfolio.members("cantoneiras", "of_perfil", ["OF8", "L45X45X5"], limit=200, data=d, decisions=decisions)
    assert page["total"] == 1200 and len(page["items"]) == 200 and len(page["keys"]) == 1200 and page["next_cursor"] == 200
    result = selection.apply({"setor": "cantoneiras", "acao": "selecionar", "request_id": str(uuid.uuid4()),
                              "grupo": {"vista": "of_perfil", "caminho": ["OF8", "L45X45X5"], "selo": page["seal"], "exceto": ["big:7"]}},
                             data=d, conn=conn)
    assert result["changed"] == 1199 and not result["group_changed"]
    assert conn.execute("SELECT count(*) AS n FROM planning_mtg.sector_member_selection").fetchone()["n"] == 1199


def test_a_group_that_changed_since_it_was_opened_is_planned_as_it_is_now(conn):
    # Antes de 07/10/2026 um selo antigo recusava o grupo inteiro (409); agora conta o grupo atual e diz que mudou.
    d = data(*[raw("OF8", "DLT319", 1, 1000, key=f"g:{i}", machine=P8) for i in range(5)])
    d["lines"][4]["aliases"] = ["antiga:4"]  # exceção marcada antes da última importação
    result = selection.apply({"setor": "cantoneiras", "acao": "selecionar", "request_id": str(uuid.uuid4()),
                              "grupo": {"vista": "of_perfil", "caminho": ["OF8", "L45X45X5"], "selo": "antigo", "exceto": ["antiga:4"]}},
                             data=d, conn=conn)
    assert result["changed"] == 4 and result["group_changed"] and "g:4" not in result["keys"]


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


def test_planear_leaves_out_only_lines_without_any_suggestion_and_refuses_when_none_can_go(conn):
    d = data(raw("OF1", "A", 10, 1000, key="m:1", machine=P8), raw("OF1", "B", 10, 1000, key="m:2"))
    tokens = {x["key"]: portfolio.member_token(x, 0) for x in d["lines"]}
    result = selection.apply({"setor": "cantoneiras", "acao": "selecionar", "request_id": str(uuid.uuid4()),
                              "membros": [{"chave": k, "token": t} for k, t in tokens.items()]}, data=d, conn=conn)
    assert result["changed"] == 1 and result["skipped_no_machine"] == 1 and result["suggested_machine"] == 0
    assert result["skipped"] == [{"key": "m:2", "of": "OF1", "reference": "B", "reason": selection.NO_SUGGESTION}]
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


RAPID25 = {"resource_id": "rid-25", "machine": "Ficep Rapid 25T", "origin": "aprendida",
           "label": "80% de 5 escolhas em ZG L45X45X5"}


def test_planear_without_machine_saves_the_suggested_machine_and_the_line_is_planned(conn, monkeypatch, database):
    from app.sector import machine_choice, planning_status, scope
    d = data(raw("OF1", "A", 10, 1000, key="s:1"), raw("OF1", "B", 10, 1000, key="s:2", machine=P8),
             raw("OF1", "C", 5, 1000, key="s:3"))
    asked, how = [], []

    def suggest(sector, lines, **kw):
        asked.extend(x["key"] for x in lines)
        how.append(kw)
        return {"s:1": RAPID25}
    monkeypatch.setattr(selection, "suggested_machines", suggest)
    tokens = {x["key"]: portfolio.member_token(x, 0) for x in d["lines"]}
    request = {"setor": "cantoneiras", "acao": "selecionar", "request_id": str(uuid.uuid4()),
               "membros": [{"chave": k, "token": t} for k, t in tokens.items()]}
    result = selection.apply(request, data=d, conn=conn)
    assert sorted(asked) == ["s:1", "s:3"]  # só as linhas sem máquina pedem sugestão
    # A mesma sugestão que a lupa mostra (a versão em memória): o Planear não refaz a previsão a cada clique.
    assert how == [{"allow_stale": True}]
    with psycopg.connect(database) as other:  # bloqueios por esta ordem: seleção → conjuntos de famílias → máquina
        held = [other.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s))", (f"{name}:cantoneiras",)).fetchone()[0]
                for name in ("sector_member_selection", "sector_family_sets", "sector_member_machine")]
    assert held == [False, False, False]
    assert selection.apply(request, data=d, conn=conn)["repeated"] and len(how) == 1  # repetição: sem calcular sugestões
    assert result["changed"] == 2 and result["planned"] == 2 and result["suggested_machine"] == 1 and result["skipped_no_machine"] == 1
    assert [s["key"] for s in result["skipped"]] == ["s:3"]
    # A sugerida fica como escolha da Carteira (a mesma de «Atribuir máquina»), com a origem marcada.
    row = conn.execute("SELECT member_key, resource_id, machine_name, actor, seen FROM planning_mtg.sector_member_machine").fetchone()
    assert (row["member_key"], row["resource_id"], row["machine_name"]) == ("s:1", "rid-25", "Ficep Rapid 25T")
    assert row["seen"]["origem"] == "sugerida" and row["actor"] == "Utilizador não identificado"
    event = conn.execute("SELECT action, detail FROM planning_mtg.sector_decision_events WHERE kind = 'machine'").fetchone()
    assert event["action"] == "machine" and event["detail"]["origem"] == "sugerida"
    assert event["detail"]["after"]["carteira"] == "Ficep Rapid 25T"
    # A linha fica «Planeado» e entra no âmbito do Gantt com a máquina da Carteira.
    ctx = machine_choice.context("cantoneiras", conn=conn)
    decisions = selection.current("cantoneiras", conn=conn)
    line = next(x for x in d["lines"] if x["key"] == "s:1")
    machine = machine_choice.effective(ctx, ["s:1"], None, "")
    assert machine == {"machine": "Ficep Rapid 25T", "resource_id": "rid-25", "source": "carteira"}
    assert planning_status.classify(portfolio.effective(line, decisions), machine["machine"])["planeado"]
    assert scope.decision(scope.read(conn), "cantoneiras", "OF1", "A", ["s:1"]) == "selected"
    # Planear outra vez (a Carteira já mostra a máquina escolhida): nada a sugerir nem a gravar.
    now = {**d, "lines": [{**x, "machine": "Ficep Rapid 25T", "machine_source": "carteira"} if x["key"] == "s:1" else x for x in d["lines"]]}
    again = selection.apply({"setor": "cantoneiras", "acao": "selecionar", "request_id": str(uuid.uuid4()),
                             "membros": [{"chave": "s:1"}]}, data=now, conn=conn)
    assert again["changed"] == 0 and again["suggested_machine"] == 0
    assert conn.execute("SELECT count(*) AS n FROM planning_mtg.sector_member_machine").fetchone()["n"] == 1


def test_planear_gives_the_suggested_machine_to_an_already_planned_line_without_machine(conn, monkeypatch):
    d = data(raw("OF1", "A", 10, 1000, key="s:1"))
    conn.execute("INSERT INTO planning_mtg.sector_selection (area, production_order_no, reference, decision, actor) "
                 "VALUES ('cantoneiras', 'OF1', '*', 'selected', 'legado')")
    conn.commit()
    monkeypatch.setattr(selection, "suggested_machines", lambda sector, lines, **kw: {"s:1": RAPID25})
    result = selection.apply({"setor": "cantoneiras", "acao": "selecionar", "request_id": str(uuid.uuid4()),
                              "membros": [{"chave": "s:1"}]}, data=d, conn=conn)
    assert result["changed"] == 0 and result["planned"] == 1 and result["suggested_machine"] == 1  # a linha passa a «Planeado»
    assert conn.execute("SELECT machine_name FROM planning_mtg.sector_member_machine").fetchone()["machine_name"] == "Ficep Rapid 25T"


def test_a_machine_assigned_meanwhile_is_never_overwritten_by_the_suggestion(conn, catalogue, monkeypatch, database):
    """Revisão de 07/10: a Carteira lida antes do «Atribuir máquina» de outra pessoa não apaga essa escolha."""
    from app.sector import member_machine
    stale = data(raw("OF1", "A", 10, 1000, key="r:1"), raw("OF1", "B", 10, 1000, key="r:2"))  # vista antes da escolha
    member_machine.apply({"setor": "cantoneiras", "maquina": "rid-p8", "request_id": str(uuid.uuid4()),
                          "membros": [{"chave": "r:1"}, {"chave": "r:2"}]}, data=stale, conn=conn)
    conn.commit()
    free = []

    def suggest(sector, lines, **kw):
        # A sugestão calcula-se antes de qualquer bloqueio (ligações próprias, só leitura).
        with psycopg.connect(database) as other:
            free.append(other.execute("SELECT pg_try_advisory_xact_lock(hashtext('sector_member_selection:cantoneiras'))").fetchone()[0])
        return {x["key"]: RAPID25 for x in lines}
    monkeypatch.setattr(selection, "suggested_machines", suggest)
    result = selection.apply({"setor": "cantoneiras", "acao": "selecionar", "request_id": str(uuid.uuid4()),
                              "membros": [{"chave": "r:1", "token": portfolio.member_token(stale["lines"][0], 0)}, {"chave": "r:2"}]},
                             data=stale, conn=conn)
    assert free == [True]
    # r:1 foi marcada sem máquina e entretanto ganhou uma: mudou. r:2 (sem token) planeia-se com a máquina escolhida.
    assert result["planned"] == 1 and result["keys"] == ["r:2"] and result["suggested_machine"] == 0
    assert {s["key"]: s["reason"] for s in result["skipped"]} == {"r:1": selection.CHANGED}
    rows = conn.execute("SELECT member_key, resource_id, revision FROM planning_mtg.sector_member_machine ORDER BY member_key").fetchall()
    assert [(r["member_key"], r["resource_id"], r["revision"]) for r in rows] == [("r:1", "rid-p8", 1), ("r:2", "rid-p8", 1)]
    seen = conn.execute("SELECT seen FROM planning_mtg.sector_member_selection WHERE member_key = 'r:2'").fetchone()["seen"]
    assert seen["machine"] == "Peddi 8"


def test_a_whole_group_sent_as_members_keeps_the_exclusions(conn):
    d = data(raw("OF1", "A", 10, 1000, key="w:1", machine=P8), raw("OF1", "B", 10, 1000, key="w:2", machine=P8))
    selection.apply({"setor": "cantoneiras", "acao": "excluir", "request_id": str(uuid.uuid4()), "membros": [{"chave": "w:2"}]}, data=d, conn=conn)
    tokens = {x["key"]: portfolio.member_token(x, 0) for x in d["lines"]}
    result = selection.apply({"setor": "cantoneiras", "acao": "selecionar", "request_id": str(uuid.uuid4()), "todo_o_grupo": True,
                              "membros": [{"chave": k, "token": t} for k, t in tokens.items()]}, data=d, conn=conn)
    assert result["keys"] == ["w:1"] and result["skipped_count"] == 0
    decisions = selection.current("cantoneiras", conn=conn)
    assert {x["key"]: portfolio.decision_of(x, decisions) for x in d["lines"]} == {"w:1": "selected", "w:2": "excluded"}


def test_planear_never_suggests_over_a_tabela_placeholder(conn, monkeypatch):
    # «Subcontrato», «Serrote MTG3»… contam como «sem máquina» mas não são linhas por decidir: nunca se sugere máquina.
    d = data(raw("OF1", "A", 10, 1000, key="p:1", machine="Subcontrato"), raw("OF1", "B", 10, 1000, key="p:2"),
             raw("OF1", "C", 10, 1000, key="p:3", machine="Por definir"), raw("OF1", "D", 10, 1000, key="p:4", machine="Sem máquina"))
    asked = []
    monkeypatch.setattr(selection, "suggested_machines", lambda sector, lines, **kw: asked.extend(x["key"] for x in lines) or {x["key"]: RAPID25 for x in lines})
    result = selection.apply({"setor": "cantoneiras", "acao": "selecionar", "request_id": str(uuid.uuid4()),
                              "membros": [{"chave": "p:1"}, {"chave": "p:2"}, {"chave": "p:3"}, {"chave": "p:4"}]}, data=d, conn=conn)
    assert sorted(asked) == ["p:2", "p:3", "p:4"] and result["planned"] == 3 and result["suggested_machine"] == 3
    assert result["skipped"] == [{"key": "p:1", "of": "OF1", "reference": "A", "reason": "Na Tabela: Subcontrato"}]


def test_the_lupa_shows_the_machine_planear_would_write():
    d = data(raw("OF1", "A", 10, 1000, key="l:1"), raw("OF1", "B", 10, 1000, key="l:2", machine=P8))
    calls = []

    def suggest(lines):
        calls.append([x["key"] for x in lines])
        return {"l:1": RAPID25}
    page = portfolio.members("cantoneiras", "of_perfil", ["OF1"], data=d, decisions={}, suggest=suggest)
    assert {i["key"]: i["suggested"] for i in page["items"]} == {"l:1": RAPID25, "l:2": None} and calls == [["l:1"]]
    assert page["todo_o_grupo"] is True  # a Carteira pode mandar o grupo inteiro como membros com token


def test_a_failing_suggestion_never_stops_planning_the_lines_that_have_a_machine(conn, monkeypatch):
    def broken(sector, lines, **kw):
        raise RuntimeError("camada de pesquisa indisponível")
    monkeypatch.setattr(selection, "suggested_machines", broken)
    d = data(raw("OF1", "A", 10, 1000, key="f:1", machine=P8), raw("OF1", "B", 10, 1000, key="f:2"))
    result = selection.apply({"setor": "cantoneiras", "acao": "selecionar", "request_id": str(uuid.uuid4()),
                              "membros": [{"chave": "f:1"}, {"chave": "f:2"}]}, data=d, conn=conn)
    assert result["changed"] == 1 and result["skipped"][0]["reason"] == selection.SUGGESTION_UNAVAILABLE


def test_suggested_machine_is_the_carteira_suggestion_then_the_estimate_and_only_of_the_sector(monkeypatch):
    from contextlib import nullcontext
    from app.sector import machine_learning, members, occurrences
    monkeypatch.undo()  # a função verdadeira, sem a sugestão vazia dos outros testes
    own = {"rid-25": {"name": "Ficep Rapid 25T"}, "rid-p8": {"name": "Peddi 8"}}
    monkeypatch.setattr(planning, "connect", lambda readonly=False: nullcontext(None))
    monkeypatch.setattr(members, "members", lambda c, sector: own)
    monkeypatch.setattr(machine_learning, "model", lambda sector: {"weighted": {}, "raw": {}})
    loads = []
    # Preferência aprendida já filtrada pela ficha técnica (a «— sugerida» da lupa): A no setor, B noutro setor.
    monkeypatch.setattr(machine_learning, "technical", lambda sector, data=None: {
        "a": {"resource_id": "rid-25", "machine": "Rapid 25T", "label": "4 de 5 escolhas"},
        "b": {"resource_id": "rid-mtg2", "machine": "Vanguard", "label": "noutro setor"},
        "e": {"resource_id": "rid-25", "machine": "Rapid 25T", "label": "4 de 5 escolhas"}} if data is not None else None)
    facts = [{"line_key": "b", "phase": "principal", "machine_basis": "sugerida",
              "suggestion": {"resource_id": "rid-p8", "machine": "Peddi 8", "reason": "Mesma máquina das outras linhas da OF"}},
             {"line_key": "antiga:c", "phase": "principal", "machine_basis": "sugerida",
              "suggestion": {"resource_id": "rid-p8", "machine": "Peddi 8", "reason": "precedente em 2 OF"}},
             {"line_key": "d", "phase": "seguinte", "machine_basis": "sugerida",
              "suggestion": {"resource_id": "rid-p8", "machine": "Peddi 8", "reason": "operação seguinte"}}]
    monkeypatch.setattr(occurrences, "load", lambda sector, **kw: loads.append(kw) or {"facts": facts})
    lines = [{"key": k, "aliases": ["antiga:c"] if k == "c" else [], "sku_family": None, "profile": "L45X45X5", "machine": "",
              "tabela_machine": "Subcontrato" if k == "e" else ""} for k in "abcde"]
    found = selection.suggested_machines("cantoneiras", lines)
    assert loads == [{"allow_stale": False}]  # por omissão lê as ocorrências atuais; o Planear e a lupa pedem a versão em memória
    # «e» diz «Subcontrato» na Tabela: nunca recebe máquina, mesmo com preferência aprendida.
    assert found == {"a": {"resource_id": "rid-25", "machine": "Ficep Rapid 25T", "origin": "aprendida", "label": "4 de 5 escolhas"},
                     "b": {"resource_id": "rid-p8", "machine": "Peddi 8", "origin": "previsao", "label": "Mesma máquina das outras linhas da OF"},
                     "c": {"resource_id": "rid-p8", "machine": "Peddi 8", "origin": "previsao", "label": "precedente em 2 OF"}}
    assert selection.suggested_machines("cantoneiras", lines, allow_stale=True) == found and loads[-1] == {"allow_stale": True}
    monkeypatch.setattr(members, "members", lambda c, sector: {})
    assert selection.suggested_machines("cantoneiras", lines) == {}  # sem máquinas do setor não há sugestão


def test_suggested_machines_do_not_teach_the_learned_preferences(conn, monkeypatch):
    from app.sector import machine_learning
    monkeypatch.setattr(machine_learning, "_names", lambda c: {"ficep rapid 25t": ("rid-25", "Ficep Rapid 25T")})
    monkeypatch.setattr(selection, "suggested_machines", lambda sector, lines, **kw: {x["key"]: RAPID25 for x in lines})
    lines = [raw("OF1", f"R{i}", 10, 1000, key=f"t:{i}") for i in range(4)]
    for r in lines:
        r["v"]["sku_family"] = "ZG"
    machine_learning._cache.clear()
    before = machine_learning.model("cantoneiras", conn=conn, lines=[])
    selection.apply({"setor": "cantoneiras", "acao": "selecionar", "request_id": str(uuid.uuid4()),
                     "grupo": {"vista": "of_perfil", "caminho": ["OF1"]}}, data=data(*lines), conn=conn)
    assert conn.execute("SELECT count(*) AS n FROM planning_mtg.sector_member_machine").fetchone()["n"] == 4
    learned = machine_learning.build(conn, "cantoneiras", [])
    assert learned["weighted"] == {}  # só as escolhas do planeador ensinam; a sugestão não se reforça a si própria
    assert machine_learning.model("cantoneiras", conn=conn, lines=[]) is before  # e não refaz o modelo em memória


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
