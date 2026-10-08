"""Cenários (app/sector/scenarios.py, Etapa 5, 08/10/2026).

Sem base de dados: as entradas do motor são montadas à mão (como em test_sector_forecast_risk). No fim, aplicar e
desfazer num PostgreSQL 16 descartável com a migração 054 (as escritas noutros sítios — calendários, Carteira,
prazos — são substituídas por registos em memória: aqui testa-se a orquestração e a transação)."""
import importlib.util
import shutil
import socket
import subprocess
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import planning
from app.sector import forecast, scenarios, shifts
from tests.test_sector_forecast_risk import SETTINGS, _inputs, fact, lisbon, week_calendar
from tests.test_sector_shifts import _fake_store

UTC = timezone.utc


def change(kind, target=None, params=None, cid=None):
    return {"id": cid or str(uuid.uuid4()), "kind": kind, "target": target or {}, "params": params or {}}


def compare(facts, changes, **kw):
    ki, src = _inputs(facts, {}, **kw)
    return scenarios.compare_inputs("cantoneiras", ki, src, changes)["diff"]


def rows(diff):
    return {r["of"]: r for r in diff["orders"]}


# --- diferença ---------------------------------------------------------------------------------------------------

def test_without_changes_the_difference_is_zero():
    facts = [fact(f"k{i}", f"L{i}", f"OF{i}", ("m1", "m2")[i % 2], 3.0 + i, due=f"2026-10-{13 + i % 5}") for i in range(8)]
    diff = compare(facts, [])
    assert diff["orders"] == [] and diff["machines"] == [] and diff["weeks"] == [] and diff["people"] == []
    assert diff["counters"]["late_new"] == diff["counters"]["late_gone"] == 0
    assert diff["counters"]["over_capacity_before"] == diff["counters"]["over_capacity_after"]
    assert diff["counts_before"] == diff["counts_after"]


def test_cancel_frees_the_machine_and_the_next_order_finishes_earlier():
    facts = [fact("a", "L1", "OF1", "m1", 7.5, due="2026-10-12"), fact("b", "L2", "OF2", "m1", 7.5, due="2026-10-12"),
             fact("c", "L3", "OF3", "m1", 1.0, due="2026-10-30")]
    facts[0]["ov"], facts[1]["ov"] = "OV9, OV10", "OV11"
    diff = compare(facts, [change("cancelar", {"ov": "OV10"})])  # OV dentro de um campo com várias OV
    r = rows(diff)
    assert r["OF1"]["cancelled"] is True and diff["counters"]["cancelled"] == 1
    assert r["OF2"]["delta_days"] == -1 and r["OF2"]["state_before"] == "atrasa" and r["OF2"]["state_after"] != "atrasa"
    assert diff["counters"]["late_gone"] == 1 and "OF2" in diff["late_gone"]
    assert r["OF2"]["why"] == "A fila da M1 ficou mais curta: Cancelar a OV OV10 (alteração 1)"
    assert diff["counters"]["late_new"] == 0


def test_machine_stop_pushes_the_queue_and_says_why():
    facts = [fact("a", "L1", "OF1", "m1", 7.0, due="2026-10-13"), fact("b", "L2", "OF2", "m2", 7.0, due="2026-10-13")]
    stop = change("maquina_parada", {"maquina": "m1"}, {"de": "2026-10-12T00:00", "ate": "2026-10-14T00:00"})
    stop["target"], stop["params"] = scenarios.validate_change("maquina_parada", stop["target"], stop["params"], machines={"m1": {}})
    diff = compare(facts, [stop])
    r = rows(diff)
    assert set(r) == {"OF1"}                                   # a m2 não muda
    assert r["OF1"]["delta_days"] == 2 and r["OF1"]["state_after"] == "atrasa"
    assert diff["counters"]["late_new"] == 1
    assert r["OF1"]["why"].startswith("M1 parada de 12/10 00:00 a 14/10 00:00 (alteração 1)")
    week = next(w for w in diff["weeks"] if w["id"] == "m1" and w["week"] == 42)
    assert week["capacity_after"] == week["capacity_before"] - 15.0  # dois dias de um turno de 7,5 h


def test_shifts_minus_and_plus_move_the_conclusion():
    facts = [fact("a", "L1", "OF1", "m1", 14.0, due="2026-10-20")]
    later = compare(facts, [change("turnos", {"maquina": "m1"}, {"dia": "2026-10-12", "turnos": 0})])
    assert rows(later)["OF1"]["delta_days"] == 1
    earlier = compare(facts, [change("turnos", {"maquina": "m1"}, {"ano": 2026, "semana": 42, "turnos": 2})])
    assert rows(earlier)["OF1"]["delta_days"] == -1           # 14 h num só dia com 2 turnos (15 h)


def test_simulated_shifts_equal_what_apply_writes(monkeypatch):
    """A simulação usa a mesma leitura das mudanças e a mesma definição que a gravação (shifts.apply)."""
    m = {"id": "r1", "name": "Peddi 8", "default_shifts": 1, "confirmed": True}
    store, _, _ = _fake_store(monkeypatch, [m])
    w42 = week_calendar("r1", 2026, 42, per_day=3)
    store[("r1", 2026, 42)] = {"id": 1, "revision": 1, "definition": w42}
    store[("r1", 2026, 43)] = {"id": 2, "revision": 1, "definition": week_calendar("r1", 2026, 43)}
    changes = [{"maquina": "r1", "dia": "2026-10-18", "turnos": 3}, {"maquina": "r1", "ano": 2026, "semana": 44, "turnos": 2}]
    defs = {k: v["definition"] for k, v in store.items()}
    simulated = shifts.simulate(defs, {"r1": m}, dict(SETTINGS), changes)
    shifts.apply({"setor": "cantoneiras", "request_id": str(uuid.uuid4()), "mudancas": changes})
    for key in store:
        assert simulated[key] == store[key]["definition"], key
    assert set(simulated) == set(store)  # semana 44 criada; a 43 recebe a madrugada do domingo da 42


def test_missing_people_stop_the_machine_that_adds_least_delay_and_the_user_can_swap():
    facts = [fact("a", "L1", "OF1", "m1", 7.0, due="2026-10-12"), fact("b", "L2", "OF2", "m2", 7.0, due="2026-10-30")]
    ki, src = _inputs(facts, {})
    chosen = scenarios.choose_stops("cantoneiras", ki, src, datetime(2026, 10, 12).date(), 1, 1, names={"m1": "M1", "m2": "M2"})
    assert chosen["machines"] == ["m2"] and chosen["missing"] == 0
    assert [(x["id"], x["late_orders"]) for x in chosen["ranking"]] == [("m2", 0), ("m1", 1)]
    people = change("pessoas_em_falta", params={"dia": "2026-10-12", "turno": 1, "n": 1})
    diff = compare(facts, [people])
    assert rows(diff)["OF2"]["delta_days"] == 1 and "OF1" not in rows(diff)
    assert diff["stops"][0]["machines"] == ["M2"] and diff["stops"][0]["chosen_by"] == "simulação"
    swapped = change("pessoas_em_falta", params={"dia": "2026-10-12", "turno": 1, "n": 1, "maquinas": ["m1"]})
    diff = compare(facts, [swapped])
    assert diff["counters"]["late_new"] == 1 and rows(diff)["OF1"]["delta_days"] == 1  # acabava no dia do prazo: passa a atrasar
    assert diff["stops"][0]["chosen_by"] == "utilizador"
    # Sem pessoas disponíveis nas Definições não há défice: o contador fica vazio, não 0.
    assert diff["counters"]["people_short_after"] is None
    ki, src = _inputs(facts, {}, settings={"pessoas_por_turno": [2, 1, 1]})
    diff = scenarios.compare_inputs("cantoneiras", ki, src, [people])["diff"]
    assert (diff["counters"]["people_short_before"], diff["counters"]["people_short_after"]) == (0, 0)
    day = next(p for p in diff["people"] if p["date"] == "2026-10-12" and p["shift"] == 1)
    assert (day["need_before"], day["need_after"], day["available_before"], day["available_after"]) == (2, 1, 2, 1)


def test_causes_follow_the_first_change_and_the_chain_of_start_reasons():
    facts = [fact("a", "L1", "OF1", "m1", 7.5, due="2026-10-12"), fact("b", "L2", "OF2", "m1", 7.5, due="2026-10-13"),
             fact("c", "L3", "OF3", "m1", 7.5, due="2026-10-20")]
    diff = compare(facts, [change("urgente", {"of": "OF3"})])
    r = rows(diff)
    assert r["OF3"]["why"] == "OF3 urgente (alteração 1)" and r["OF3"]["delta_days"] == -2
    assert r["OF1"]["why"] == "Começa depois da OF3 na M1, que passou à frente: OF3 urgente (alteração 1)"
    assert diff["counters"]["late_new"] == 2  # OF1 e OF2 passam a acabar depois do prazo
    # Duas alterações: cada mudança vai para a primeira que a provoca; as seguintes ficam ditas.
    diff = compare(facts, [change("cancelar", {"of": "OF2"}), change("urgente", {"of": "OF3"})])
    r = rows(diff)
    assert r["OF3"]["why"] == "A fila da M1 ficou mais curta: Cancelar a OF2 (alteração 1) · também alteração 2"
    assert r["OF1"]["why"].startswith("Começa depois da OF3 na M1, que passou à frente: OF3 urgente (alteração 2)")


def test_due_date_change_moves_the_risk_and_never_the_queue_of_others():
    facts = [fact("a", "L1", "OF1", "m1", 7.0, due="2026-10-20"), fact("b", "L2", "OF2", "m1", 7.0, due="2026-10-30")]
    diff = compare(facts, [change("prazo", {"of": "OF1"}, {"data": "2026-10-12"})])
    r = rows(diff)
    assert r["OF1"]["state_before"] == "ok" and r["OF1"]["due_day"] == "2026-10-12"
    assert r["OF1"]["why"] == "Prazo da OF1 passa a 12/10 (alteração 1)" and "OF2" not in r


def test_urgent_override_is_written_priority_zero_in_the_forecast():
    f = fact("w", "L", "OF9", "m1", 1, priority=1)
    urgent = {**f, "signals": {"prioridade": None}, "priority": {**f["priority"], "urgent": True, "urgent_override": True}}
    assert forecast.priority_key(urgent) < forecast.priority_key(f)
    from app.sector import priority
    r = priority.resolve("cantoneiras", "seguinte", {}, override={"definition": {"urgent": True, "applies_to": "principal"}})
    assert r["urgent"] is True and r["urgent_override"] is True
    plain = priority.resolve("cantoneiras", "principal", {})
    assert "urgent_override" not in plain  # sem substituição urgente o resultado não muda


# --- isolamento da cache e cálculo em segundo plano ----------------------------------------------------------------

def test_scenarios_never_write_in_the_cache_of_the_plan_in_use(monkeypatch):
    facts = [fact("a", "L1", "OF1", "m1", 7.0), fact("b", "L2", "OF2", "m1", 7.0)]
    ki, src = _inputs(facts, {})
    sid = str(uuid.uuid4())
    row = {"id": sid, "area": "cantoneiras", "name": "Teste", "status": "aberto", "revision": 3, "applied_summary": None}
    changes = [change("cancelar", {"of": "OF1"})]
    monkeypatch.setattr(scenarios, "_load", lambda sector, scenario_id: (row, changes))
    monkeypatch.setattr(scenarios, "_sources", lambda sector: src)
    monkeypatch.setattr(forecast, "_key_inputs", lambda sector, now=None: ki)
    monkeypatch.setattr(forecast, "current", lambda *a, **k: pytest.fail("a previsão em uso não pode ser pedida"))
    forecast.invalidate()
    scenarios._results.clear(), scenarios._forecasts.clear()
    first = scenarios.comparison("cantoneiras", sid)
    assert first["pending"] is True
    for t in [t for t in threading.enumerate() if t.name.startswith("cenario-")]:
        t.join(30)
    ready = scenarios.comparison("cantoneiras", sid)
    assert ready["pending"] is False and ready["counters"]["cancelled"] == 1
    fc = scenarios.compute_for("cantoneiras", sid)  # a previsão do cenário (vistas da parte V) vem da memória própria
    assert fc["scenario"]["id"] == sid and "OF1" not in fc["orders"] and "OF2" in fc["orders"]
    assert forecast._cache._entries == {}


# --- paragens gravadas: partidas por semana --------------------------------------------------------------------------

def test_reserve_splits_by_week_and_merges_overlaps(monkeypatch):
    m = {"id": "r1", "name": "Peddi 8", "default_shifts": 1, "area": "cantoneiras"}
    store, saved, _ = _fake_store(monkeypatch, [m])
    for i, w in enumerate((42, 43), 1):
        store[("r1", 2026, w)] = {"id": i, "revision": 1, "definition": week_calendar("r1", 2026, w, per_day=3, days=range(1, 8))}
    start, end = lisbon(2026, 10, 18, 22), lisbon(2026, 10, 19, 5, 30)   # 3.º turno de domingo
    out = shifts.reserve(None, m, "cantoneiras", start, end, "Cenário «X»", request_id=uuid.uuid4())
    assert [(w["year"], w["week"]) for w in out["weeks"]] == [(2026, 42), (2026, 43)] and out["skipped"] == []
    w42 = store[("r1", 2026, 42)]["definition"]["reserved_windows"]
    w43 = store[("r1", 2026, 43)]["definition"]["reserved_windows"]
    assert datetime.fromisoformat(w42[0]["end"]) == lisbon(2026, 10, 19)  # domingo até à meia-noite
    assert datetime.fromisoformat(w43[0]["start"]) == lisbon(2026, 10, 19)
    fresh = week_calendar("r1", 2026, 42, per_day=3, days=range(1, 8))
    assert shifts.week_hours(store[("r1", 2026, 42)]["definition"]) == shifts.week_hours(fresh) - 2  # domingo 22:00–24:00
    out = shifts.reserve(None, m, "cantoneiras", lisbon(2026, 10, 19, 4), lisbon(2026, 10, 27, 8), "Avaria", request_id=uuid.uuid4())
    w43 = store[("r1", 2026, 43)]["definition"]["reserved_windows"]
    assert len(w43) == 1 and w43[0]["area"] == "Cenário «X» + Avaria"           # juntas numa só, sem sobreposição
    assert out["skipped"] == [{"year": 2026, "week": 44, "reason": "sem calendário com horários"}]
    assert all(p["definition"].get("reserved_windows") for p in saved)


def test_stop_in_memory_is_the_same_reservation_that_reserve_writes():
    ki, src = _inputs([fact("a", "L1", "OF1", "m1", 7.0)], {})
    stopped = scenarios.stop_machine(src, "m1", lisbon(2026, 10, 12, 8), lisbon(2026, 10, 12, 10), "X")
    d = next(d for d in stopped["calendars"] if d["resource_id"] == "m1" and d["week"] == 42)
    assert d["reserved_windows"] == shifts.merge_reserved([], lisbon(2026, 10, 12, 8), lisbon(2026, 10, 12, 10), "X")
    assert all(not d.get("reserved_windows") for d in src["calendars"])  # as entradas da referência não mudam


def test_validation_of_changes():
    machines = {"m1": {}}
    with pytest.raises(planning.PlanningError):
        scenarios.validate_change("maquina_parada", {"maquina": "m1"}, {"de": "2026-10-12T10:00", "ate": "2026-10-12T08:00"}, machines=machines)
    with pytest.raises(planning.PlanningError):
        scenarios.validate_change("turnos", {"maquina": "zz"}, {"dia": "2026-10-12", "turnos": 1}, machines=machines)
    with pytest.raises(planning.PlanningError):
        scenarios.validate_change("pessoas_em_falta", {}, {"dia": "2026-10-12", "turno": 4, "n": 1}, machines=machines)
    t, p = scenarios.validate_change("prazo", {"of": " of264095 "}, {"data": "2026-10-20"}, machines=machines)
    assert t == {"of": "OF264095"} and p == {"data": "2026-10-20"}
    t, p = scenarios.validate_change("maquina_parada", {"maquina": "m1"}, {"de": "2026-10-25T01:00", "ate": "2026-10-25T03:00"}, machines=machines)
    assert datetime.fromisoformat(p["ate"]) - datetime.fromisoformat(p["de"]) == timedelta(hours=3)  # muda a hora a 25/10


# --- aplicar e desfazer numa base descartável com a 054 --------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("migrate", ROOT / "scripts/migrate.py")
migrate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migrate)


@pytest.fixture(scope="module")
def database(tmp_path_factory):
    if shutil.which("docker") is None:
        pytest.skip("docker indisponível")
    name, password = f"planning-scenarios-{uuid.uuid4().hex[:10]}", uuid.uuid4().hex
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    subprocess.run(["docker", "run", "-d", "--rm", "--name", name, "-e", f"POSTGRES_PASSWORD={password}",
                    "-e", "POSTGRES_DB=dataresearchmtg", "-p", f"127.0.0.1:{port}:5432", "postgres:16-alpine"],
                   check=True, capture_output=True)
    dsn = f"host=127.0.0.1 port={port} dbname=dataresearchmtg user=postgres password={password}"
    try:
        import psycopg
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
        migrations = tmp_path_factory.mktemp("scenario-migrations")
        names = ["039_schema_migrations.sql", "054_plan_scenarios.sql"]
        for filename in names:
            shutil.copy2(ROOT / "sql" / filename, migrations / filename)
        assert migrate.apply(prefix, migrations) == names
        yield dsn, prefix
    finally:
        subprocess.run(["docker", "stop", name], capture_output=True)


@pytest.fixture()
def world(database, monkeypatch):
    """A base com a 054 e, em memória, os sítios onde «Aplicar» grava (calendários, prazos)."""
    from app.sector import priority, settings as sector_settings
    dsn, _ = database
    monkeypatch.setenv("MES_PG_DSN", dsn)
    import psycopg
    with psycopg.connect(dsn) as c:
        c.execute("TRUNCATE planning_mtg.plan_scenario_requests, planning_mtg.plan_scenario_changes, planning_mtg.plan_scenarios")
    machine = {"id": "m1", "name": "Peddi 8", "default_shifts": 1, "area": "cantoneiras"}
    monkeypatch.setattr(scenarios, "_machines", lambda c, sector: {"m1": machine})
    monkeypatch.setattr(sector_settings, "read", lambda c, sector: dict(SETTINGS))
    calls = {"shifts": [], "reserve": [], "override": [], "finish": []}
    overrides = {}

    def save_override(payload, conn=None):
        calls["override"].append(payload)
        key = ("cantoneiras", payload["of"], "*")
        prior = overrides.get(key)
        assert payload.get("expected_revision", 0) == (prior["revision"] if prior else 0)
        if payload.get("limpar"):
            overrides.pop(key, None)
        else:
            d = {"due_date": payload.get("due_date"), "field": payload.get("field"), "applies_to": payload.get("applies_to")}
            if payload.get("urgente"):
                d["urgent"] = True
            overrides[key] = {"definition": d, "revision": (prior["revision"] if prior else 0) + 1, "reason": payload.get("motivo")}
        return {"repeated": False}
    monkeypatch.setattr(priority, "save_override", save_override)
    monkeypatch.setattr(priority, "overrides", lambda c: dict(overrides))
    calendars = {}
    monkeypatch.setattr(shifts, "calendar_row", lambda c, rid, y, w: calendars.get((rid, y, w)))

    def apply(payload, conn=None):
        calls["shifts"].append(payload)
        for item in payload["mudancas"]:
            calendars[(item["maquina"], 2026, 43)] = {"id": 1, "revision": 2, "definition": {"shift_plan": {"1": item["turnos"]}, "day_shifts": {}}}
        return {"changed": 1, "weeks": 1}
    monkeypatch.setattr(shifts, "apply", apply)

    def reserve(c, resource, area, start, end, reason, *, request_id):
        calls["reserve"].append((resource["id"], start, end, reason))
        return {"weeks": [{"year": 2026, "week": 43, "before": [], "after": [{"start": start.isoformat(), "end": end.isoformat(), "area": reason}]}],
                "skipped": []}
    monkeypatch.setattr(shifts, "reserve", reserve)
    monkeypatch.setattr(shifts, "finish_batch", lambda c, rid: calls["finish"].append(rid))
    return calls, overrides, calendars


def post(**payload):
    return scenarios.save({"setor": "cantoneiras", "request_id": str(uuid.uuid4()), **payload})


def test_create_change_remove_with_revisions_and_idempotent_requests(world):
    created = post(acao="criar", nome="Avaria da Peddi")
    sid = created["id"]
    request = str(uuid.uuid4())
    body = {"setor": "cantoneiras", "request_id": request, "acao": "alterar", "cenario": sid, "expected_revision": 1,
            "tipo": "prazo", "alvo": {"of": "OF1"}, "parametros": {"data": "2026-10-20"}}
    first = scenarios.save(body)
    assert first["revision"] == 2 and first["change"]["label"] == "Prazo da OF1 passa a 20/10"
    again = scenarios.save(body)
    assert again["repeated"] is True and again["change"]["id"] == first["change"]["id"]
    with pytest.raises(planning.PlanningError) as e:
        scenarios.save({**body, "parametros": {"data": "2026-10-21"}})
    assert e.value.status == 409
    with pytest.raises(planning.PlanningError) as e:  # revisão antiga
        post(acao="alterar", cenario=sid, expected_revision=1, tipo="urgente", alvo={"of": "OF2"})
    assert e.value.status == 409
    people = post(acao="alterar", cenario=sid, expected_revision=2, tipo="pessoas_em_falta", parametros={"dia": "2026-10-12", "turno": 1, "n": 2})
    removed = post(acao="retirar_alteracao", cenario=sid, expected_revision=3, alteracao=people["change"]["id"])
    assert removed["revision"] == 4
    listed = scenarios.listing("cantoneiras")
    assert listed["installed"] is True
    [s] = listed["scenarios"]
    assert [c["label"] for c in s["changes"]] == ["Prazo da OF1 passa a 20/10"]  # a retirada fica só no histórico
    assert s["changes"][0]["apply_text"] == "Substituição de prazo: Prazo da OF1 passa a 20/10"


def test_apply_writes_in_one_transaction_and_undo_restores_only_what_is_unchanged(world, database):
    calls, overrides, calendars = world
    sid = post(acao="criar", nome="Semana difícil")["id"]
    post(acao="alterar", cenario=sid, expected_revision=1, tipo="prazo", alvo={"of": "OF1"}, parametros={"data": "2026-10-20"})
    post(acao="alterar", cenario=sid, expected_revision=2, tipo="turnos", alvo={"maquina": "m1"}, parametros={"ano": 2026, "semana": 43, "turnos": 2})
    post(acao="alterar", cenario=sid, expected_revision=3, tipo="maquina_parada", alvo={"maquina": "m1"},
         parametros={"de": "2026-10-20T06:00", "ate": "2026-10-20T13:30"})
    post(acao="alterar", cenario=sid, expected_revision=4, tipo="pessoas_em_falta", parametros={"dia": "2026-10-12", "turno": 1, "n": 1})
    post(acao="alterar", cenario=sid, expected_revision=5, tipo="urgente", alvo={"of": "OF1"})

    # Uma falha a meio desfaz tudo: o cenário fica aberto e nenhum pedido é registado.
    original = shifts.reserve
    shifts.reserve = lambda *a, **k: (_ for _ in ()).throw(planning.PlanningError("Paragem inválida"))
    with pytest.raises(planning.PlanningError):
        post(acao="aplicar", cenario=sid, expected_revision=6)
    shifts.reserve = original
    import psycopg
    with psycopg.connect(database[0]) as c:
        assert c.execute("SELECT status FROM planning_mtg.plan_scenarios WHERE id=%s", (sid,)).fetchone()[0] == "aberto"
    overrides.clear(), calls["override"].clear(), calls["shifts"].clear(), calendars.clear()

    applied = post(acao="aplicar", cenario=sid, expected_revision=6)
    assert applied["status"] == "aplicado" and applied["revision"] == 7
    assert [x["written"] for x in applied["applied"]][3] == "Não se grava (só simulação)"
    assert calls["shifts"][0]["mudancas"] == [{"maquina": "m1", "turnos": 2, "ano": 2026, "semana": 43}]
    assert calls["reserve"][-1][0] == "m1" and calls["reserve"][-1][3].startswith("Peddi 8 parada de 20/10 06:00")
    assert overrides[("cantoneiras", "OF1", "*")]["definition"] == {"due_date": "2026-10-20", "field": None, "applies_to": "principal",
                                                                   "urgent": True}
    with pytest.raises(planning.PlanningError):  # já aplicado
        post(acao="aplicar", cenario=sid, expected_revision=7)

    listed = scenarios.listing("cantoneiras")["scenarios"][0]
    items = {it["kind"]: it for it in listed["applied"]}
    assert listed["status"] == "aplicado" and items["pessoas_em_falta"]["simulation_only"] is True

    # Desfazer o urgente: o prazo continua (revisão igual à gravada pelo cenário → repõe o anterior, a data).
    out = post(acao="desfazer_aplicada", cenario=sid, expected_revision=7, alteracao=items["urgente"]["change_id"])
    assert out["note"] == "Prazo reposto" and "urgent" not in overrides[("cantoneiras", "OF1", "*")]["definition"]
    # Desfazer o prazo agora: a substituição mudou depois (o Desfazer do urgente) → fica como está.
    out = post(acao="desfazer_aplicada", cenario=sid, expected_revision=8, alteracao=items["prazo"]["change_id"])
    assert out["note"] == "O prazo desta OF mudou depois: ficou como está"
    with pytest.raises(planning.PlanningError) as e:
        post(acao="desfazer_aplicada", cenario=sid, expected_revision=9, alteracao=items["prazo"]["change_id"])
    assert e.value.status == 409
    with pytest.raises(planning.PlanningError):  # pessoas em falta: nada a desfazer
        post(acao="desfazer_aplicada", cenario=sid, expected_revision=9, alteracao=items["pessoas_em_falta"]["change_id"])
    gone = post(acao="descartar", cenario=sid, expected_revision=9)
    assert gone["status"] == "arquivado" and scenarios.listing("cantoneiras")["scenarios"] == []


def test_without_the_migration_reads_are_empty_and_writes_say_so(monkeypatch):
    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=None):
            class R:
                def fetchone(self):
                    return {"t": None}
            return R()
    from app.sector import settings as sector_settings
    monkeypatch.setattr(planning, "connect", lambda *a, **k: Conn())
    monkeypatch.setattr(scenarios, "_machines", lambda c, sector: {})
    monkeypatch.setattr(sector_settings, "read", lambda c, sector: dict(SETTINGS))
    assert scenarios.listing("cantoneiras")["scenarios"] == []
    with pytest.raises(planning.PlanningError) as e:
        post(acao="criar", nome="X")
    assert e.value.status == 503 and "migração 054" in str(e.value)
    with pytest.raises(planning.PlanningError) as e:
        scenarios.compute_for("cantoneiras", str(uuid.uuid4()))
    assert e.value.status == 404
