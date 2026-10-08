"""Fila por máquina da previsão (dispatch.py, Etapa 3, 08/10/2026). Sem base de dados."""
import hashlib
import json
import os
import random
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from app.sector import dispatch, forecast, shifts

UTC = timezone.utc
LISBON = ZoneInfo("Europe/Lisbon")
ROOT = Path(__file__).resolve().parents[1]
O = datetime(2026, 10, 12, 5, 0, tzinfo=UTC)  # segunda 12/10, 06:00 de Lisboa


def h(x):
    return timedelta(hours=x)


def win(a, b, label=("2026-10-12", 1)):
    return (O + h(a), O + h(b), label)


def op(key, rid="m1", hours=1.0, scope=1, pk=(1,), **extra):
    return {"key": key, "resource_id": rid, "seconds": int(round(hours * 3600)), "priority_key": pk, "scope": scope,
            "of": "OF" + key, "line_key": "L" + key, **extra}


def spans(result, key):
    return [((a - O).total_seconds() / 3600, (b - O).total_seconds() / 3600) for a, b, *_ in result["operations"][key]["segments"]]


def test_work_pauses_at_closures_and_keeps_day_and_shift_labels():
    windows = {"m1": [win(0, 7.5, ("2026-10-12", 1)), win(8, 15.5, ("2026-10-12", 2))]}
    r = dispatch.dispatch([op("a", hours=7), op("b", hours=2, pk=(2,))], windows, O)
    assert spans(r, "a") == [(0, 7)]
    assert spans(r, "b") == [(7, 7.5), (8, 9.5)]  # pausa no fecho das 13:30 às 14:00
    assert [s[2:] for s in r["operations"]["b"]["segments"]] == [("2026-10-12", 1), ("2026-10-12", 2)]
    assert r["operations"]["a"]["start_reason"] == "origem"
    assert r["operations"]["b"]["start_reason"] == "ocupada:a" and r["operations"]["b"]["after_of"] == "OFa"
    assert dispatch.check(r, [op("a", hours=7), op("b", hours=2, pk=(2,))], windows) == []


def test_daylight_saving_change_on_25_october_counts_real_hours():
    """25/10/2026: o 3.º turno de sábado para domingo (00:00–05:30 de Lisboa) tem 6,5 horas reais."""
    settings = {"template": shifts.DEFAULT_TEMPLATE, "holidays": []}
    d = shifts.definition_for("m1", 2026, 43, {"6": 3, "7": 0}, {}, settings, manual=False)
    origin = datetime(2026, 10, 24, 21, 0, tzinfo=UTC)  # sábado 22:00 de Lisboa (ainda +01:00)
    windows = forecast.label_windows([d], shifts.DEFAULT_TEMPLATE, origin)
    total = sum((b - a).total_seconds() for a, b, _ in windows["m1"])
    assert total == 2 * 3600 + 6.5 * 3600  # 22:00–24:00 de sábado e 00:00–05:30 de domingo (com a hora repetida)
    ops = [op("a", hours=8.5)]
    r = dispatch.dispatch(ops, windows, origin)
    end = r["operations"]["a"]["end"].astimezone(LISBON)
    assert (end.date(), end.strftime("%H:%M")) == (date(2026, 10, 25), "05:30")
    assert {s[2:] for s in r["operations"]["a"]["segments"]} == {("2026-10-24", 3)}  # tudo no 3.º turno de sábado
    assert dispatch.check(r, ops, windows) == []


def test_planned_goes_before_the_rest_and_then_the_priority_key():
    windows = {"m1": [win(0, 24)]}
    ops = [op("rest-urgent", scope=1, pk=(0,)), op("plan-late", scope=0, pk=(9,)), op("plan-first", scope=0, pk=(1,))]
    r = dispatch.dispatch(ops, windows, O)
    order = sorted(r["operations"], key=lambda k: r["operations"][k]["start"])
    assert order == ["plan-first", "plan-late", "rest-urgent"]
    assert dispatch.check(r, ops, windows) == []


def _digest(result):
    out = {k: [v["start"].isoformat() if v["start"] else None, v["end"].isoformat() if v["end"] else None, v["start_reason"],
               [[a.isoformat(), b.isoformat(), d, s] for a, b, d, s in v["segments"]]] for k, v in result["operations"].items()}
    return hashlib.sha256(json.dumps(out, sort_keys=True).encode()).hexdigest()


def _sample():
    windows = {"m1": [win(i * 24, i * 24 + 7.5, (f"d{i}", 1)) for i in range(5)],
               "p": [win(i * 24, i * 24 + 15.5, (f"d{i}", 1)) for i in range(5)],
               "d": [win(i * 24 + 2, i * 24 + 6, (f"d{i}", 1)) for i in range(5)]}
    ops = []
    for i in range(60):
        rid = ("m1", "p", "d")[i % 3]
        ops.append(op(f"k{i:02d}", rid=rid, hours=0.3 + (i % 7) * 0.45, scope=i % 2, pk=(i % 5, f"OF{i % 4}"),
                      pool="p" if rid in ("p", "d") else None))
    return ops, windows


def test_same_input_gives_the_same_result_in_any_order():
    ops, windows = _sample()
    first = dispatch.dispatch(ops, windows, O)
    for seed in range(5):
        shuffled = list(ops)
        random.Random(seed).shuffle(shuffled)
        assert _digest(dispatch.dispatch(shuffled, windows, O)) == _digest(first)
    assert dispatch.check(first, ops, windows) == []


def test_same_result_with_another_hash_seed():
    code = ("import sys; sys.path.insert(0, %r); from tests.test_sector_dispatch import _sample, _digest, O; "
            "from app.sector import dispatch; ops, w = _sample(); print(_digest(dispatch.dispatch(ops, w, O)))") % str(ROOT)
    out = set()
    for seed in ("1", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        out.add(subprocess.run([sys.executable, "-c", code], env=env, cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip())
    ops, windows = _sample()
    assert out == {_digest(dispatch.dispatch(ops, windows, O))}


def test_shared_post_runs_one_operation_at_a_time_the_most_urgent_open_machine():
    """Fita pav.1 (posto) com o Doall: um só recurso. Às 06:00 só o posto está aberto e começa o seu mais urgente;
    às 06:30 abre o Doall com trabalho ainda mais urgente, mas o que já começou continua até acabar."""
    windows = {"post": [win(0, 7.5)], "doall": [win(0.5, 5)]}
    ops = [op("x", rid="post", hours=1.5, pk=(5,), pool="post"), op("y", rid="doall", hours=2, pk=(1,), pool="post"),
           op("z", rid="post", hours=1, pk=(3,), pool="post")]
    r = dispatch.dispatch(ops, windows, O)
    assert spans(r, "z") == [(0, 1)]
    assert spans(r, "y") == [(1, 3)] and r["operations"]["y"]["start_reason"] == "posto:post"
    assert spans(r, "x") == [(3, 4.5)] and r["operations"]["x"]["start_reason"] == "posto:doall"
    assert dispatch.check(r, ops, windows) == []


def test_anchors_first_never_in_closed_hours_and_the_most_recent_goes_right_after():
    windows = {"m1": [win(0, 7.5), win(8, 15.5)]}
    ops = [op("q1", hours=3, pk=(1,)), op("q2", hours=6, pk=(2,)),
           op("a1", hours=1, anchor={"start": O + h(7.6), "order": "1"}),             # 13:36: fechado → 14:00
           op("a2", hours=1, anchor={"start": O + h(8.5), "order": "2"}),             # sobrepõe a1 → logo a seguir
           op("a3", hours=0.5, anchor={"start": O - h(30), "order": "3"})]            # já passou → na origem
    r = dispatch.dispatch(ops, windows, O)
    a1, a2, a3 = (r["operations"][k] for k in ("a1", "a2", "a3"))
    assert spans(r, "a1") == [(8, 9)] and a1["warnings"] == ["fora_de_horario"] and a1["start_reason"] == "ancora"
    assert spans(r, "a2") == [(9, 10)] and a2["warnings"] == ["sobreposta:a1"]
    assert spans(r, "a3") == [(0, 0.5)] and a3["warnings"] == ["ja_passou"]
    # A fila pausa nos blocos das âncoras: q1 depois de a3, q2 até ao fecho, pausa em a1+a2 e acaba às 15:30.
    assert spans(r, "q1") == [(0.5, 3.5)]
    assert spans(r, "q2") == [(3.5, 7.5), (10, 12)]
    assert dispatch.check(r, ops, windows) == []


def test_operations_of_the_same_anchor_stay_together_without_warnings():
    windows = {"m1": [win(0, 15.5)]}
    ops = [op("b1", hours=1, pk=(1,), anchor={"start": O + h(2), "id": "A"}),
           op("b2", hours=1, pk=(2,), anchor={"start": O + h(2), "id": "A"})]
    r = dispatch.dispatch(ops, windows, O)
    assert spans(r, "b1") == [(2, 3)] and spans(r, "b2") == [(3, 4)]
    assert r["operations"]["b2"]["warnings"] == []


def test_unschedulable_operations_keep_their_reason():
    windows = {"m1": [win(0, 8)], "closed": []}
    ops = [op("a", rid=None), {**op("b"), "seconds": None}, op("c", rid="closed"), op("d", rid="nowhere"),
           {**op("e"), "reason": "estacionada"}, op("ok")]
    r = dispatch.dispatch(ops, windows, O)
    assert {u["key"]: u["reason"] for u in r["unschedulable"]} == {
        "a": "sem_maquina", "b": "sem_horas", "c": "sem_calendario", "d": "sem_calendario", "e": "estacionada"}
    assert set(r["operations"]) == {"ok"}
    assert dispatch.check(r, ops, windows) == []


def test_whole_seconds_and_work_beyond_the_horizon_are_accounted_for():
    windows = {"m1": [win(0, 1)]}
    ops = [op("a", hours=0), {**op("b"), "seconds": 1801}, {**op("c", pk=(2,)), "seconds": 3000}]
    r = dispatch.dispatch(ops, windows, O)
    a, b, c = (r["operations"][k] for k in "abc")
    assert a["start"] == a["end"] == O and a["segments"] == []
    assert b["end"] == O + timedelta(seconds=1801)
    assert c["status"] == dispatch.BEYOND and c["end"] is None and c["unplaced_seconds"] == 3000 - 1799
    assert all(isinstance((y - x).total_seconds(), float) and (y - x).total_seconds() == int((y - x).total_seconds())
               for v in r["operations"].values() for x, y, *_ in v["segments"])
    assert r["resources"]["m1"]["placed_seconds"] == 3600
    assert dispatch.check(r, ops, windows) == []


def test_check_finds_overlaps_closed_hours_and_lost_seconds():
    windows = {"m1": [win(0, 2)]}
    ops = [op("a"), op("b", pk=(2,))]
    r = dispatch.dispatch(ops, windows, O)
    r["operations"]["b"]["segments"] = [(O + h(0.5), O + h(1.5), "d", 1)]
    r["operations"]["a"]["segments"] = [(O + h(3), O + h(4), "d", 1)]
    problems = dispatch.check(r, ops, windows)
    assert any("sobreposição" not in p and "fora das janelas" in p for p in problems)
    r["operations"]["a"]["segments"] = [(O + h(0), O + h(1), "d", 1)]
    assert any("sobreposição" in p for p in dispatch.check(r, ops, windows))
    r["operations"]["b"]["segments"] = []
    assert any("segundos" in p for p in dispatch.check(r, ops, windows))
