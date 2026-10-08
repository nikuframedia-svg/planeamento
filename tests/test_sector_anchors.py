"""Edição manual do Gantt (anchors.py, Etapa 4, 08/10/2026).

Parte pura: o despacho com âncoras de OF (dia ou hora), o fim deduzido na leitura, a máquina mudada à espera das
ocorrências, o impacto e o texto dos avisos. Parte com base: PostgreSQL 16 descartável com as migrações 039, 040, 046,
047, 048, 052 e 053 — mover, retirar, desfazer, idempotência, fim sozinho registado na gravação seguinte e Desfazer
com a escolha da Carteira mudada entretanto.
"""
import importlib.util
import shutil
import socket
import subprocess
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg
import pytest
from psycopg.rows import dict_row

from app import planning
from app.sector import anchors, dispatch, forecast, machine_choice, member_machine
from tests.test_sector_forecast_risk import SETTINGS, fact, lisbon, week_calendar
from tests.test_sector_portfolio import data, raw

UTC = timezone.utc
LISBON = ZoneInfo("Europe/Lisbon")
ROOT = Path(__file__).resolve().parents[1]
NOW = lisbon(2026, 10, 12, 6, 30)  # segunda 12/10, 1.º turno (06:00–14:00)
CREATED = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)


def inputs(facts, planned, *, machines=("m1", "m2"), data_lines=None, occ_stamp="occ-1", now=NOW):
    origin = forecast.origin_at(now, SETTINGS["template"])
    ki = {"settings": SETTINGS, "origin": origin, "today": now.astimezone(LISBON).date(), "now": now,
          "data": {"imported_at": None, "lines": data_lines or []}, "occ": {"facts": facts, "stamp": occ_stamp},
          "planned": planned, "stale": False, "key": ("k",), "anchors": []}
    calendars = [week_calendar(rid, y, w) for rid in machines for y, w in ((2026, 42), (2026, 43), (2026, 44))]
    src = {"machines": [{"id": rid, "name": rid.upper()} for rid in machines], "calendars": calendars,
           "posts": {}, "names": {}, "v2_at": None}
    return ki, src


def anchor(of, rid, day, *, hour=None, created=CREATED, previous=None, aid=None):
    start = datetime.combine(date.fromisoformat(day), datetime.strptime(hour, "%H:%M").time(), LISBON) if hour else None
    return {"id": aid or str(uuid.uuid4()), "of": of, "resource_id": rid, "machine_name": rid.upper(),
            "day": date.fromisoformat(day), "start_at": start, "author": "luis", "created_at": created, "revision": 1,
            "previous_machine": previous}


def local(value):
    return value.astimezone(LISBON).strftime("%d/%m %H:%M")


# --- despacho com âncoras de OF

FACTS = [fact("a1", "L1", "OF1", "m1", 3.0), fact("a2", "L2", "OF1", "m1", 2.0),     # OF1: 5 h na m1
         fact("b1", "L3", "OF2", "m1", 4.0, due="2026-10-13"),                      # OF2: 4 h, mais urgente
         fact("c1", "L4", "OF3", "m2", 2.0)]
PLANNED = {"L1": None, "L2": None, "L3": None, "L4": None}


def test_a_day_anchor_keeps_every_planned_operation_of_the_order_together_from_the_first_opening_of_that_day():
    ki, src = inputs(FACTS, PLANNED)
    plain = forecast.compute("cantoneiras", ki, src)
    assert plain["operations"]["b1"]["start"] < plain["operations"]["a1"]["start"]  # sem ajuste: OF2 primeiro (prazo)
    a = anchor("OF1", "m1", "2026-10-14")
    fc = forecast.compute("cantoneiras", ki, src, anchors=[a])
    a1, a2 = fc["operations"]["a1"], fc["operations"]["a2"]
    assert local(a1["start"]) == "14/10 06:00" and a2["start"] == a1["end"]      # seguidas, sem buracos
    assert a1["anchored"] and a1["warnings"] == [] and a2["warnings"] == []        # começar às 06:00 do dia não é aviso
    assert local(fc["operations"]["b1"]["start"]) == "12/10 06:00"                 # o resto arruma-se à volta
    assert fc["check"] == []
    [item] = fc["anchors"]
    assert item["state"] == "ativa" and sorted(item["keys"]) == ["a1", "a2"] and item["hour"] is None
    assert local(item["start"]) == "14/10 06:00" and item["end"] == a2["end"]


def test_today_starts_at_the_current_shift_without_saying_it_already_passed():
    ki, src = inputs(FACTS, PLANNED)
    fc = forecast.compute("cantoneiras", ki, src, anchors=[anchor("OF1", "m1", "2026-10-12")])
    assert local(fc["operations"]["a1"]["start"]) == "12/10 06:00" and fc["operations"]["a1"]["warnings"] == []


def test_closed_hour_moves_to_the_next_opening_with_a_warning_and_a_past_day_goes_to_the_front():
    ki, src = inputs(FACTS, PLANNED)
    closed = anchor("OF1", "m1", "2026-10-13", hour="20:00")                       # calendário: 1 turno por dia
    fc = forecast.compute("cantoneiras", ki, src, anchors=[closed])
    a1 = fc["operations"]["a1"]
    assert local(a1["start"]) == "14/10 06:00" and a1["warnings"] == ["fora_de_horario"]
    assert anchors.warning_text("fora_de_horario", fc["operations"], start=a1["start"]) == \
        "Fora do turno: começa na abertura seguinte (14/10 06:00)"
    past = anchor("OF1", "m1", "2026-10-09")
    fc = forecast.compute("cantoneiras", ki, src, anchors=[past])
    assert local(fc["operations"]["a1"]["start"]) == "12/10 06:00" and fc["operations"]["a1"]["warnings"] == ["ja_passou"]
    assert fc["operations"]["b1"]["start"] >= fc["operations"]["a2"]["end"]       # o resto vai à frente da fila
    # Um dia sem turnos (sábado): passa para a abertura seguinte, com aviso.
    weekend = forecast.compute("cantoneiras", ki, src, anchors=[anchor("OF1", "m1", "2026-10-17")])
    assert local(weekend["operations"]["a1"]["start"]) == "19/10 06:00"
    assert weekend["operations"]["a1"]["warnings"] == ["fora_de_horario"]


def test_overlapping_anchors_the_most_recent_goes_right_after_and_names_the_order():
    ki, src = inputs(FACTS, PLANNED)
    first = anchor("OF2", "m1", "2026-10-14", created=CREATED)
    second = anchor("OF1", "m1", "2026-10-14", created=CREATED + timedelta(minutes=5))
    fc = forecast.compute("cantoneiras", ki, src, anchors=[second, first])
    b1, a1 = fc["operations"]["b1"], fc["operations"]["a1"]
    assert local(b1["start"]) == "14/10 06:00" and a1["start"] == b1["end"]
    assert a1["warnings"] == ["sobreposta:b1"] and b1["warnings"] == []
    assert anchors.warning_text("sobreposta:b1", fc["operations"]) == "Sobrepõe a OF2: fica logo a seguir"
    assert fc["check"] == []


def test_dispatch_day_anchor_without_until_keeps_the_old_closed_hours_warning():
    o = datetime(2026, 10, 12, 5, 0, tzinfo=UTC)
    windows = {"m1": [(o + timedelta(hours=2), o + timedelta(hours=8), ("2026-10-12", 1))]}
    ops = [{"key": "x", "resource_id": "m1", "seconds": 3600, "priority_key": (1,), "scope": 0, "of": "OFX",
            "anchor": {"start": o - timedelta(hours=5) + timedelta(hours=5), "until": o + timedelta(hours=19)}}]
    r = dispatch.dispatch(ops, windows, o)
    assert r["operations"]["x"]["warnings"] == []                    # abre mais tarde no mesmo dia: sem aviso
    ops[0]["anchor"] = {"start": o}
    assert dispatch.dispatch(ops, windows, o)["operations"]["x"]["warnings"] == ["fora_de_horario"]


# --- fim sozinho (só na leitura) e máquina à espera das ocorrências

def test_an_anchor_ends_by_itself_on_read_with_the_reason():
    ki, src = inputs(FACTS, {"L4": None, "L3": None})                              # OF1 deixou de estar Planeado
    fc = forecast.compute("cantoneiras", ki, src, anchors=[anchor("OF1", "m1", "2026-10-14")])
    [item] = fc["anchors"]
    assert item["state"] == "terminada" and item["reason"] == "sem_planeado"
    assert item["reason_text"] == "A OF deixou de estar Planeado nesta máquina"
    gone = [f for f in FACTS if f["of"] != "OF1"]
    fc = forecast.compute("cantoneiras", *inputs(gone, PLANNED), anchors=[anchor("OF1", "m1", "2026-10-14")])
    assert fc["anchors"][0]["reason"] == "concluida"
    elsewhere = [fact("a1", "L1", "OF1", "m2", 3.0), *FACTS[2:]]
    fc = forecast.compute("cantoneiras", *inputs(elsewhere, PLANNED), anchors=[anchor("OF1", "m1", "2026-10-14")])
    assert fc["anchors"][0]["reason"] == "mudou_de_maquina"


def test_a_machine_change_uses_the_old_hours_until_the_occurrences_are_rebuilt():
    moved = anchor("OF1", "m2", "2026-10-14", previous={"from": "m1", "to": "m2", "occ_stamp": "occ-1",
                                                         "lines": [{"key": "L1", "keys": ["L1"], "revision": 1, "before": None}]})
    ki, src = inputs(FACTS, PLANNED)
    fc = forecast.compute("cantoneiras", ki, src, anchors=[moved])
    a1 = fc["operations"]["a1"]
    assert a1["resource_id"] == "m2" and a1["seconds"] == 3 * 3600 and "horas_a_recalcular" in a1["warnings"]
    assert fc["operations"]["a2"]["resource_id"] == "m1"                         # outra linha da OF fica onde estava
    assert fc["anchors"][0]["keys"] == ["a1"] and fc["anchors"][0]["moved"] == ["a1"]
    assert fc["machine_hours"]["m2"]["total"] == 5.0                              # 2 h da OF3 + 3 h vindas da m1
    # Ocorrências refeitas (outro carimbo): a linha já vem da Carteira na máquina nova; nada é mudado à força.
    ki, src = inputs(FACTS, PLANNED, occ_stamp="occ-2")
    fc = forecast.compute("cantoneiras", ki, src, anchors=[moved])
    assert fc["operations"]["a1"]["resource_id"] == "m1" and fc["anchors"][0]["state"] == "terminada"


def test_impact_lists_orders_finishing_later_new_late_and_cells_that_become_complete():
    facts = [*FACTS[:2], fact("b1", "L3", "OF2", "m1", 4.0, due="2026-10-12"), fact("x1", "L5", "OF5", "m2", 8.0)]
    ki, src = inputs(facts, {**PLANNED, "L5": None})
    before = forecast.compute("cantoneiras", ki, src)
    after = forecast.compute("cantoneiras", ki, src, anchors=[anchor("OF1", "m1", "2026-10-12"), anchor("OF5", "m2", "2026-10-14")])
    rule = forecast.Rule(SETTINGS["workdays"], SETTINGS["holidays"])
    effect = anchors.impact(before, after, rule.count)
    assert [(x["of"], x["days"]) for x in effect["later"]] == [("OF5", 2), ("OF2", 1)]
    assert [x["of"] for x in effect["new_late"]] == ["OF2"] and effect["new_late_count"] == 1   # acaba terça, prazo segunda
    assert [(x["machine"], x["date"], x["shift"]) for x in effect["complete"]] == [("M2", "2026-10-14", 1)]
    assert anchors.impact(before, before, rule.count) == {"later": [], "later_count": 0, "new_late": [], "new_late_count": 0,
                                                          "complete": [], "complete_count": 0}


def test_start_hour_from_hour_or_shift_and_bad_values_are_refused():
    template = SETTINGS["template"]
    assert anchors._start_hour({"hora": "14:30"}, template).strftime("%H:%M") == "14:30"
    assert anchors._start_hour({"turno": 2}, template).strftime("%H:%M") == template[1][0]
    assert anchors._start_hour({}, template) is None
    for bad in ({"hora": "25:00"}, {"turno": 9}, {"turno": 0}, {"turno": -1}, {"turno": "x"}):  # 0/-1: revisão 08/10 (R5)
        with pytest.raises(planning.PlanningError, match="(Turno|Hora) inválid"):
            anchors._start_hour(bad, template)


def test_forecast_inputs_are_read_before_the_write_transaction_and_the_lock(monkeypatch):
    """Revisão 08/10 (R2): forecast.inputs (pode demorar a frio) corre antes de abrir a ligação de escrita."""
    order = []
    monkeypatch.setattr(forecast, "inputs", lambda sector: order.append("inputs") or ({}, {}))

    class Conn(_NoTable):
        def __init__(self, readonly):
            self.readonly = readonly

        def execute(self, sql, *a, **k):
            order.append(("ro " if self.readonly else "rw ") + sql.split()[0] + (" lock" if "advisory" in sql else ""))
            if "advisory" in sql:
                raise RuntimeError("parar aqui")

            class R:
                @staticmethod
                def fetchone():
                    return {"t": "planning_mtg.sector_plan_adjustments"}
            return R()
    monkeypatch.setattr(planning, "connect", lambda readonly=False, **kw: Conn(readonly))
    with pytest.raises(RuntimeError, match="parar aqui"):
        anchors.apply({"setor": "cantoneiras", "acao": "mover", "request_id": str(uuid.uuid4())})
    assert order == ["ro SELECT", "inputs", "rw SELECT", "rw SELECT lock"]


class _NoTable:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a, **k):
        class R:
            @staticmethod
            def fetchone():
                return {"t": None}
        return R()


def test_without_migration_053_reads_are_empty_and_writes_answer_503():
    assert anchors.snapshot(_NoTable(), "cantoneiras") == ([], None)
    with pytest.raises(planning.PlanningError, match="migração 053") as error:
        anchors.apply({"setor": "cantoneiras", "acao": "mover", "request_id": str(uuid.uuid4())}, conn=_NoTable())
    assert error.value.status == 503


def test_cache_key_follows_the_last_anchor_event_and_keeps_the_day_last(monkeypatch):
    from app.sector import load, settings as sector_settings

    class Conn(_NoTable):
        pass
    monkeypatch.setattr(load, "_context", lambda sector, today: ({"generation": 1}, {}, {"stamp": "s", "decisions": "d"}))
    monkeypatch.setattr(sector_settings, "read", lambda c, sector: SETTINGS)
    monkeypatch.setattr(load, "_calendar_stamp", lambda c: (1, None))
    monkeypatch.setattr(planning, "connect", lambda **kw: Conn())
    monkeypatch.setattr(anchors, "snapshot", lambda c, sector: ([], 7))
    first = forecast._key_inputs("cantoneiras", NOW)
    monkeypatch.setattr(anchors, "snapshot", lambda c, sector: ([], 8))
    second = forecast._key_inputs("cantoneiras", NOW)
    assert first["key"] != second["key"] and first["key"][-1] == second["key"][-1] == NOW.astimezone(LISBON).date()


# --- base descartável com a 053

spec = importlib.util.spec_from_file_location("migrate", ROOT / "scripts/migrate.py")
migrate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migrate)


@pytest.fixture(scope="module")
def database(tmp_path_factory):
    if shutil.which("docker") is None:
        pytest.skip("docker indisponível")
    name, password = f"planning-anchors-{uuid.uuid4().hex[:10]}", uuid.uuid4().hex
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
        migrations = tmp_path_factory.mktemp("anchors-migrations")
        names = ["039_schema_migrations.sql", "040_sector_selection.sql", "046_sector_member_selection.sql",
                 "047_member_selection_no_phase.sql", "048_family_sets_member_machine.sql",
                 "052_member_planned_quantity.sql", "053_sector_plan_adjustments.sql"]
        for filename in names:
            shutil.copy2(ROOT / "sql" / filename, migrations / filename)
        assert migrate.apply(prefix, migrations) == names
        yield {"dsn": dsn, "prefix": prefix}
    finally:
        subprocess.run(["docker", "stop", name], capture_output=True)


@pytest.fixture()
def conn(database):
    with psycopg.connect(database["dsn"], row_factory=dict_row) as c:
        c.execute("TRUNCATE planning_mtg.sector_plan_adjustment_events, planning_mtg.sector_plan_adjustments, "
                  "planning_mtg.sector_decision_events, planning_mtg.sector_member_machine")
        c.commit()
        yield c


D = data(raw("OF1", "DLT319", 10, 1000, machine="Peddi 8"), raw("OF1", "DLT20", 5, 2000, machine="Peddi 8"),
         raw("OF2", "DLT319", 4, 1000, machine="Peddi 8"))
K1, K2, K3 = (x["key"] for x in D["lines"])
DB_FACTS = [fact("a1", K1, "OF1", "m1", 3.0), fact("a2", K2, "OF1", "m1", 2.0), fact("b1", K3, "OF2", "m1", 4.0, due="2026-10-13")]
DB_PLANNED = {K1: None, K2: None, K3: None}
OK_FIT = lambda facts, rids: {rid: {"hours": True, "in_spec": True} for rid in rids}  # noqa: E731


def move(c, *, inputs_=None, fit=OK_FIT, **kw):
    payload = {"setor": "cantoneiras", "acao": "mover", "of": "OF1", "de": "m1", "maquina": "m1", "dia": "2026-10-14",
               "request_id": str(uuid.uuid4()), **kw}
    return anchors.apply(payload, conn=c, inputs=inputs_ or inputs(DB_FACTS, DB_PLANNED, data_lines=D["lines"]), fit=fit), payload


def act(c, action, adjustment_id, *, inputs_=None):
    return anchors.apply({"setor": "cantoneiras", "acao": action, "ajuste_id": adjustment_id, "request_id": str(uuid.uuid4())},
                         conn=c, inputs=inputs_ or inputs(DB_FACTS, DB_PLANNED, data_lines=D["lines"]))


def rows(c):
    return c.execute("SELECT production_order_no AS of, resource_id, day, start_at, active, ended_reason "
                     "FROM planning_mtg.sector_plan_adjustments ORDER BY created_at, id").fetchall()


def events(c):
    return [r["action"] for r in c.execute("SELECT action FROM planning_mtg.sector_plan_adjustment_events ORDER BY id").fetchall()]


def test_move_to_a_day_records_the_adjustment_with_its_event_impact_and_is_idempotent(conn):
    result, payload = move(conn)
    assert result["ajuste"]["state"] == "ativa" and sorted(result["ajuste"]["keys"]) == ["a1", "a2"]
    assert [x["of"] for x in result["impacto"]["later"]] == ["OF1"] and result["regra"] == anchors.RULE
    assert [(r["of"], r["resource_id"], r["day"], r["active"]) for r in rows(conn)] == [("OF1", "m1", date(2026, 10, 14), True)]
    assert events(conn) == ["mover"]
    again = anchors.apply(payload, conn=conn, inputs=inputs(DB_FACTS, DB_PLANNED, data_lines=D["lines"]), fit=OK_FIT)
    assert again["repeated"] and again["ajuste"]["id"] == result["ajuste"]["id"] and len(rows(conn)) == 1
    with pytest.raises(planning.PlanningError, match="outro conteúdo") as error:
        anchors.apply({**payload, "dia": "2026-10-15"}, conn=conn, inputs=inputs(DB_FACTS, DB_PLANNED), fit=OK_FIT)
    assert error.value.status == 409
    # O Excel não muda: nenhuma decisão nem máquina da Carteira foi gravada por mudar só o dia.
    assert conn.execute("SELECT count(*) n FROM planning_mtg.sector_member_machine").fetchone()["n"] == 0


def test_a_new_move_of_the_same_box_replaces_the_old_one_and_undo_brings_it_back(conn):
    first, _ = move(conn)
    second, _ = move(conn, dia="2026-10-15", hora="10:00")
    assert [(r["day"], r["active"], r["ended_reason"]) for r in rows(conn)] == [
        (date(2026, 10, 14), False, "substituida"), (date(2026, 10, 15), True, None)]
    assert second["ajuste"]["hour"] == "10:00"
    undone = act(conn, "desfazer", second["ajuste"]["id"])
    assert [(r["day"], r["active"], r["ended_reason"]) for r in rows(conn)] == [
        (date(2026, 10, 14), True, None), (date(2026, 10, 15), False, "desfeita")]
    assert any("Volta a alteração anterior: OF1 → 14/10 (M1)" in w for w in undone["avisos"])
    assert events(conn) == ["mover", "substituir", "mover", "repor", "desfazer"]


def test_withdraw_ends_the_adjustment_and_an_inactive_one_cannot_be_withdrawn_again(conn):
    result, _ = move(conn)
    out = act(conn, "retirar", result["ajuste"]["id"])
    assert out["ajuste"]["state"] == "terminada" and out["ajuste"]["reason_text"] == "Retirada"
    assert [(r["active"], r["ended_reason"]) for r in rows(conn)] == [(False, "retirada")]
    with pytest.raises(planning.PlanningError, match="já não está ativa") as error:
        act(conn, "retirar", result["ajuste"]["id"])
    assert error.value.status == 409


def test_changing_machine_writes_the_carteira_choice_and_undo_restores_it(conn):
    result, _ = move(conn, maquina="m2")
    choice = conn.execute("SELECT member_key, resource_id, seen FROM planning_mtg.sector_member_machine ORDER BY member_key").fetchall()
    assert {(r["member_key"], r["resource_id"]) for r in choice} == {(K1, "m2"), (K2, "m2")}
    assert {r["seen"]["origem"] for r in choice} == {"gantt"}
    machine_events = conn.execute("SELECT action, detail FROM planning_mtg.sector_decision_events").fetchall()
    assert {e["action"] for e in machine_events} == {"machine"} and {e["detail"]["origem"] for e in machine_events} == {"gantt"}
    # Até as ocorrências se refazerem, a previsão já põe a OF na m2 com as horas de antes.
    assert result["ajuste"]["resource_id"] == "m2" and sorted(result["ajuste"]["moved"]) == ["a1", "a2"]
    assert anchors.RECALCULATING in result["avisos"]
    undone = act(conn, "desfazer", result["ajuste"]["id"])
    assert "Máquina reposta: M1." in undone["avisos"]
    assert conn.execute("SELECT count(*) n FROM planning_mtg.sector_member_machine").fetchone()["n"] == 0
    assert rows(conn)[0]["ended_reason"] == "desfeita"


def test_a_new_day_on_the_new_machine_keeps_the_machine_change_until_the_occurrences_are_rebuilt(conn):
    """Revisão 08/10 (A1): mudar para a m2 e, logo a seguir (ocorrências ainda as de antes), mudar o dia na m2: a OF
    continua na m2; o Desfazer repõe o ajuste anterior e só o Desfazer desse repõe a Carteira."""
    first, _ = move(conn, maquina="m2")
    second, _ = move(conn, de="m2", maquina="m2", dia="2026-10-15")
    assert second["ajuste"]["state"] == "ativa" and second["ajuste"]["resource_id"] == "m2"
    assert sorted(second["ajuste"]["moved"]) == ["a1", "a2"]                   # não volta à m1
    undone = act(conn, "desfazer", second["ajuste"]["id"])
    assert not any(w.startswith("Máquina reposta") for w in undone["avisos"])
    assert any(w.startswith("Volta a alteração anterior") for w in undone["avisos"])
    assert {r["resource_id"] for r in conn.execute("SELECT resource_id FROM planning_mtg.sector_member_machine")} == {"m2"}
    again = act(conn, "desfazer", first["ajuste"]["id"])
    assert "Máquina reposta: M1." in again["avisos"]


def test_a_day_outside_the_plan_is_refused(conn):
    """Revisão 08/10 (R5): dia muito no passado ou no futuro (9999-12-31 dava um 500) é recusado sem gravar."""
    for bad in ("9999-12-31", "2100-01-01", "2026-08-01"):
        with pytest.raises(planning.PlanningError, match="Dia fora do plano"):
            move(conn, dia=bad)
        conn.rollback()
    assert rows(conn) == []


def test_undo_keeps_the_machine_when_the_carteira_choice_changed_in_between(conn):
    result, _ = move(conn, maquina="m2")
    lines = [x for x in D["lines"] if x["key"] == K1]
    member_machine.write_choice(conn, "cantoneiras", lines, {"id": "m3", "name": "M3"}, "carteira", actor="ana",
                                request_id=uuid.uuid4())                     # alguém mudou na Carteira depois
    undone = act(conn, "desfazer", result["ajuste"]["id"])
    assert any(w.startswith("A máquina não foi reposta") for w in undone["avisos"])
    ctx = machine_choice.context("cantoneiras", conn=conn)
    assert ctx["members"][K1]["resource_id"] == "m3" and ctx["members"][K2]["resource_id"] == "m2"
    assert rows(conn)[0]["ended_reason"] == "desfeita"


def test_a_machine_without_hours_for_the_operation_is_refused_and_nothing_is_written(conn):
    no_hours = lambda facts, rids: {rid: {"hours": False, "in_spec": True} for rid in rids}  # noqa: E731
    with pytest.raises(planning.PlanningError, match="não tem horas"):
        move(conn, maquina="m2", fit=no_hours)
    conn.rollback()
    assert rows(conn) == [] and conn.execute("SELECT count(*) n FROM planning_mtg.sector_member_machine").fetchone()["n"] == 0
    out_of_spec = lambda facts, rids: {rid: {"hours": True, "in_spec": False} for rid in rids}  # noqa: E731
    result, _ = move(conn, maquina="m2", fit=out_of_spec)
    assert "Máquina fora da ficha técnica" in result["avisos"]


def test_an_adjustment_whose_order_left_the_plan_ends_on_read_and_is_recorded_on_the_next_write(conn):
    result, _ = move(conn, of="OF2", dia="2026-10-14")
    conn.commit()
    without_of2 = inputs(DB_FACTS, {K1: None, K2: None}, data_lines=D["lines"])   # Limpar na OF2
    rows_now = anchors._active(conn, "cantoneiras")
    fc = forecast.compute("cantoneiras", *without_of2, anchors=rows_now)
    assert fc["anchors"][0]["state"] == "terminada" and rows(conn)[0]["active"]    # só na leitura: nada gravado
    out, _ = move(conn, inputs_=without_of2)                                       # gravação seguinte do setor
    assert out["terminados"] == [result["ajuste"]["id"]]
    assert [(r["of"], r["active"], r["ended_reason"]) for r in rows(conn)] == [("OF2", False, "sem_planeado"), ("OF1", True, None)]
    assert "terminar" in events(conn)
