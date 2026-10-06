"""Decisões das vistas por família contra um PostgreSQL 16 descartável com as migrações 039, 040 e 045.

Critérios 5, 17 e 18 do plano: ação em grupo com exceções e regresso ao automático; repetir uma
gravação não duplica; edição concorrente não apaga decisões; nenhuma transferência por semelhança.
A base de operações é sintética (monkeypatch) para isolar a lógica transacional.
"""
import importlib.util
import shutil
import socket
import subprocess
import time
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from app import planning
from app.sector import assignments, capacity, occurrences, priority, sets
from tests.test_sector_needs import fact

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("migrate", ROOT / "scripts/migrate.py")
migrate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migrate)


@pytest.fixture(scope="module")
def database(tmp_path_factory):
    if shutil.which("docker") is None:
        pytest.skip("docker indisponível")
    name, password = f"planning-needs-{uuid.uuid4().hex[:10]}", uuid.uuid4().hex
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
        migrations = tmp_path_factory.mktemp("needs-migrations")
        names = ["039_schema_migrations.sql", "040_sector_selection.sql", "045_sector_needs_views.sql"]
        for filename in names:
            shutil.copy2(ROOT / "sql" / filename, migrations / filename)
        assert migrate.apply(prefix, migrations) == names
        # Re-applying is refused by the registry, never executed twice.
        assert migrate.apply(prefix, migrations) == []
        yield dsn
    finally:
        subprocess.run(["docker", "stop", name], capture_output=True)


@pytest.fixture()
def db(database, monkeypatch):
    monkeypatch.setenv("MES_PG_DSN", database)
    with psycopg.connect(database) as c:
        c.execute("""TRUNCATE planning_mtg.sector_machine_decision_history, planning_mtg.sector_machine_decisions,
            planning_mtg.sector_machine_preferences, planning_mtg.sector_machine_actions, planning_mtg.sector_reference_set_members,
            planning_mtg.sector_reference_sets, planning_mtg.sector_priority_policies, planning_mtg.sector_priority_overrides,
            planning_mtg.sector_capacity_quotas, planning_mtg.sector_config_events CASCADE""")
    return database


RAPID20, RAPID25 = "r-rapid20", "r-rapid25"


def synthetic(stamp="s1"):
    facts = [fact(f"k{i}", of="OF264186", ref=f"M2{i:02d}", hours=0.2) for i in range(4)]
    for i, f in enumerate(facts):
        f["occurrence_key"] = f"OF264186|M2{i:02d}|CPIS:112|1"
        f["technical_signature"] = f"sig{i}"
        f["resource_id"] = RAPID20 if i < 2 else None
    facts[3]["started"] = True
    facts[3]["resource_id"] = RAPID20
    rows = {f["key"]: {"ordem_codigo": f["of"], "referencia_original": f["reference"]} for f in facts}
    return {"area": "cantoneiras", "facts": facts, "_rows": rows, "stamp": stamp,
            "resources": {RAPID20: {"id": RAPID20, "name": "Ficep Rapid 20T -1"}, RAPID25: {"id": RAPID25, "name": "Ficep Rapid 25T"}}}


@pytest.fixture()
def world(db, monkeypatch):
    state = {"data": synthetic()}
    monkeypatch.setattr(occurrences, "load", lambda area, **kw: state["data"])
    monkeypatch.setattr(assignments, "_evidence", lambda c, data: {"ok": True})

    def alternatives(c, data, f, evidence=None):
        # k2 has no documentary alternative on the 25T; k1 is conditional there.
        out = [{"resource_id": RAPID20, "eligibility": "admissible", "conditions": [], "hours": 0.2, "reason": None}]
        if f["key"] != "k2":
            out.append({"resource_id": RAPID25, "eligibility": "conditional" if f["key"] == "k1" else "admissible",
                        "conditions": ["confirmar_graminho_ferramentas_e_desenho"] if f["key"] == "k1" else [], "hours": 0.3, "reason": None})
        return out
    monkeypatch.setattr(assignments, "alternatives", alternatives)
    return state


def group(**kw):
    return {"setor": "cantoneiras", "request_id": str(uuid.uuid4()), "scope": {"preset": "familias", "path": ["MTG3", "M2"]}, **kw}


def current(db):
    with psycopg.connect(db, row_factory=dict_row) as c:
        return {r["occurrence_key"].split("|")[1]: r for r in c.execute("SELECT * FROM planning_mtg.sector_machine_decisions").fetchall()}


def test_group_assignment_resolves_each_occurrence_and_is_idempotent(world, db):
    preview = assignments.preview(group(mode="assign", resource_id=RAPID25))
    statuses = {s: v["count"] for s, v in preview["statuses"].items()}
    assert statuses["admissivel"] == 1 and statuses["condicional"] == 1 and statuses["incompativel"] == 1 and statuses["iniciada"] == 1
    payload = group(mode="assign", resource_id=RAPID25, reason="Rapid 25T livre esta semana", stamp="s1")
    first = assignments.apply(payload)
    assert first["changed"] == 2 and first["kept"] == {"incompativel": 1, "iniciada": 1}
    assert assignments.apply(payload)["repeated"] is True  # critério 17: o mesmo pedido não grava duas vezes
    decisions = current(db)
    assert set(decisions) == {"M200", "M201"} and decisions["M200"]["scope_level"] == 2
    with pytest.raises(planning.PlanningError, match="outros valores"):
        assignments.apply({**payload, "reason": "outro"})


def test_stale_preview_is_rejected_and_nothing_is_written(world, db):
    with pytest.raises(planning.PlanningError) as error:
        assignments.apply(group(mode="assign", resource_id=RAPID25, reason="x", stamp="antigo"))
    assert error.value.status == 409 and not current(db)


def test_family_action_preserves_individual_decisions_and_automatic_removes_only_its_level(world, db):
    single = assignments.apply({**group(mode="assign", resource_id=RAPID20, reason="Exceção da peça", stamp="s1"),
                                "scope": {"keys": ["k0"]}})
    assert single["changed"] == 1 and current(db)["M200"]["scope_level"] == 9
    family = assignments.apply(group(mode="prefer", resource_id=RAPID25, reason="Família na 25T", stamp="s1", include="all"))
    assert family["kept"].get("excecao") == 1 and current(db)["M200"]["resource_id"] == RAPID20
    assert current(db)["M202"]["mode"] == "prefer"  # incompatible kept as intention when asked
    automatic = assignments.apply(group(mode="automatic", stamp="s1"))
    assert automatic["changed"] == 2 and set(current(db)) == {"M200"}  # critério 5


def test_undo_restores_previous_state_except_later_changes(world, db):
    assignments.apply(group(mode="assign", resource_id=RAPID20, reason="Base", stamp="s1", include="eligible"))
    second = assignments.apply(group(mode="assign", resource_id=RAPID25, reason="Mudança", stamp="s1"))
    assignments.apply({**group(mode="assign", resource_id=RAPID20, reason="Mexida depois", stamp="s1"), "scope": {"keys": ["k1"]}})
    undo = assignments.undo({"setor": "cantoneiras", "request_id": str(uuid.uuid4()), "action_id": second["action_id"]})
    assert undo["restored"] == 1 and undo["skipped_changed_later"] == 1
    decisions = current(db)
    assert decisions["M200"]["resource_id"] == RAPID20 and decisions["M200"]["reason"] == "Base"
    assert decisions["M201"]["reason"] == "Mexida depois"
    with pytest.raises(planning.PlanningError, match="já foi desfeita"):
        assignments.undo({"setor": "cantoneiras", "request_id": str(uuid.uuid4()), "action_id": second["action_id"]})


def test_resolver_never_transfers_a_decision_to_another_technical_variant(world, db):
    """Critério 18."""
    assignments.apply({**group(mode="assign", resource_id=RAPID25, reason="x", stamp="s1"), "scope": {"keys": ["k0"]}})
    with psycopg.connect(db, row_factory=dict_row) as c:
        resolver = assignments.resolver(c)
    row = {"ordem_codigo": "OF264186", "referencia_original": "M200", "operacao_codigo": "CPIS:112", "ocorrencia": 1}
    assert resolver.lookup("cantoneiras", row, "sig0")["mode"] == "assign"
    stale = resolver.lookup("cantoneiras", row, "other-signature")
    assert stale["mode"] == "stale" and stale["conflict"]
    assert resolver.lookup("perfis", row, "sig0") is None  # setor faz parte da chave


def test_future_preferences_follow_specificity_and_expose_conflicts(world, db):
    for kind, value, rid in (("sku_family", "M2", RAPID20), ("reference", "M200", RAPID25)):
        assignments.apply({"setor": "cantoneiras", "request_id": str(uuid.uuid4()), "mode": "future_preference",
                           "resource_id": rid, "reason": "Regra do planeador", "selector": {"kind": kind, "value": value}})
    with psycopg.connect(db, row_factory=dict_row) as c:
        c.execute("CREATE TABLE IF NOT EXISTS planning_mtg.sku_family_mappings(area text,sku text,family text)")
        c.execute("INSERT INTO planning_mtg.sku_family_mappings VALUES ('cantoneiras','M200','M2'),('cantoneiras','M201','M2')")
        c.commit()
        resolver = assignments.resolver(c)
        row = lambda ref: {"ordem_codigo": "OF9", "referencia_original": ref, "operacao_codigo": "CPIS:112", "ocorrencia": 1}
        assert resolver.lookup("cantoneiras", row("M200"), "x")["resource_id"] == RAPID25  # referência > família
        assert resolver.lookup("cantoneiras", row("M201"), "x")["resource_id"] == RAPID20
        assignments.apply({"setor": "cantoneiras", "request_id": str(uuid.uuid4()), "mode": "future_preference",
                           "resource_id": RAPID25, "reason": "Outra regra", "selector": {"kind": "sku_family", "value": "M2"}})
        conflict = assignments.resolver(c).lookup("cantoneiras", row("M201"), "x")
        assert conflict["mode"] == "conflict" and "mesma especificidade" in conflict["note"]
        c.execute("DROP TABLE planning_mtg.sku_family_mappings")
        c.commit()


def test_priority_policy_and_override_are_revisioned_and_idempotent(db):
    payload = {"setor": "perfis", "request_id": str(uuid.uuid4()), "reason": "Aceitar ano 2026 do Picking",
               "definition": {"principal": ["picking", "cut_date"], "following": ["picking"], "assume_picking_year": 2026}}
    saved = priority.save_policy(payload)
    assert saved["policies"]["perfis"]["revision"] == 1 and saved["policies"]["perfis"]["assume_picking_year"] == 2026
    assert priority.save_policy(payload)["repeated"] is True
    with pytest.raises(planning.PlanningError) as error:
        priority.save_policy({**payload, "request_id": str(uuid.uuid4())})  # expected_revision 0 is stale now
    assert error.value.status == 409
    override = {"setor": "cantoneiras", "of": "OF1", "request_id": str(uuid.uuid4()), "due_date": "2026-10-10",
                "reason": "Cliente pediu antecipação"}
    assert priority.save_override(override)["override"]["definition"]["due_date"] == "2026-10-10"
    with psycopg.connect(db, row_factory=dict_row) as c:
        assert set(priority.overrides(c)) == {("cantoneiras", "OF1", "*")}
        before = priority.digest(c)
    priority.save_override({"setor": "cantoneiras", "of": "OF1", "request_id": str(uuid.uuid4()), "limpar": True, "expected_revision": 1})
    with psycopg.connect(db, row_factory=dict_row) as c:
        assert not priority.overrides(c) and priority.digest(c) != before
        events = c.execute("SELECT kind,action FROM planning_mtg.sector_config_events ORDER BY id").fetchall()
    assert [(e["kind"], e["action"]) for e in events] == [("priority_policy", "saved"), ("priority_override", "saved"), ("priority_override", "cleared")]


def test_reference_sets_keep_literal_members_and_unknowns(world, db):
    saved = sets.save({"setor": "cantoneiras", "request_id": str(uuid.uuid4()), "name": "Piloto M2", "mode": "frozen",
                       "members": "M200\nM201; M201,  M999 \n m200"})
    assert saved["members"] == 4 and saved["repeated_in_list"] == 1  # m200 ≠ M200: no merging by resemblance
    with psycopg.connect(db, row_factory=dict_row) as c:
        found, names = sets.memberships(c, "cantoneiras", world["data"]["facts"])
    assert found == {"k0": [saved["set"]["id"]], "k1": [saved["set"]["id"]]} and names[saved["set"]["id"]] == "Piloto M2"
    revised = sets.save({"setor": "cantoneiras", "request_id": str(uuid.uuid4()), "id": saved["set"]["id"], "expected_revision": 1,
                         "name": "Piloto M2", "mode": "frozen", "members": ["M202"]})
    assert revised["set"]["revision"] == 2
    with psycopg.connect(db, row_factory=dict_row) as c:
        found, _ = sets.memberships(c, "cantoneiras", world["data"]["facts"])
        assert list(found) == ["k2"]  # the current revision only; revision 1 stays in history
        assert c.execute("SELECT count(*) n FROM planning_mtg.sector_reference_set_members").fetchone()["n"] == 5
    dynamic = sets.save({"setor": "cantoneiras", "request_id": str(uuid.uuid4()), "name": "Atrasadas M2", "mode": "dynamic",
                         "filters": {"sku_family": ["M2"], "flags": ["late"]}})
    with psycopg.connect(db, row_factory=dict_row) as c:
        found, _ = sets.memberships(c, "cantoneiras", world["data"]["facts"])
    assert sum(dynamic["set"]["id"] in v for v in found.values()) == 4
    with pytest.raises(planning.PlanningError):
        sets.save({"setor": "cantoneiras", "request_id": str(uuid.uuid4()), "name": "Vazio", "mode": "dynamic", "filters": {}})


def test_capacity_quotas_never_exceed_the_resource(db):
    base = {"resource_id": "r-vanguard", "valid_from": "2026-10-01", "reason": "Acordo entre setores"}
    capacity.save_quota({**base, "area": "perfis", "share": 0.6, "request_id": str(uuid.uuid4())})
    with pytest.raises(planning.PlanningError, match="100%"):
        capacity.save_quota({**base, "area": "cantoneiras", "share": 0.5, "request_id": str(uuid.uuid4())})
    saved = capacity.save_quota({**base, "area": "cantoneiras", "share": 0.4, "request_id": str(uuid.uuid4())})
    assert {(q["area"], float(q["share"])) for q in saved["quotas"]} == {("perfis", 0.6), ("cantoneiras", 0.4)}


def test_accepting_suggestions_assigns_each_occurrence_its_own_machine(world, db):
    facts = world["data"]["facts"]
    for key, rid in (("k1", RAPID25), ("k2", RAPID20)):
        fact = next(f for f in facts if f["key"] == key)
        fact.update(machine_basis="sugerida", suggestion={"resource_id": rid})
    preview = assignments.preview(group(mode="accept_suggestions"))
    assert preview["statuses"]["sem_sugestao"]["count"] == 2  # k0 and k3 are not suggestions
    saved = assignments.apply(group(mode="accept_suggestions", reason="Aceitar sugestões da OF", stamp="s1"))
    assert saved["changed"] == 2
    decisions = current(db)
    assert decisions["M201"]["resource_id"] == RAPID25 and decisions["M202"]["resource_id"] == RAPID20
    assert {d["mode"] for d in decisions.values()} == {"assign"}


def test_occurrence_keys_with_a_bar_in_the_reference_round_trip():
    assert assignments.split_key("OF1|A|B 12|CPIS:112|2") == ("OF1", "A|B 12", "CPIS:112", "2")


def test_one_action_can_give_each_occurrence_its_own_machine_and_be_undone_at_once(world, db):
    saved = assignments.apply({"setor": "cantoneiras", "request_id": str(uuid.uuid4()), "mode": "assign_each",
                               "targets": {"k0": RAPID25, "k1": RAPID20}, "reason": "Equilíbrio de carga", "stamp": "s1"})
    assert saved["changed"] == 2
    decisions = current(db)
    assert decisions["M200"]["resource_id"] == RAPID25 and decisions["M201"]["resource_id"] == RAPID20
    undone = assignments.undo({"setor": "cantoneiras", "request_id": str(uuid.uuid4()), "action_id": saved["action_id"]})
    assert undone["restored"] == 2 and not current(db)
    with pytest.raises(planning.PlanningError):
        assignments.apply({"setor": "cantoneiras", "request_id": str(uuid.uuid4()), "mode": "assign_each",
                           "targets": {"k0": "maquina-inexistente"}, "reason": "x", "stamp": "s1"})
