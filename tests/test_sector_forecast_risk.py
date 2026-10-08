"""Previsão: margem, risco, falta acumulada, recurso limitante, células e pessoas (forecast.py, Etapa 3, 08/10).
Sem base de dados: as entradas são montadas à mão, com a mesma forma das ocorrências da Carga."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.sector import forecast, shifts

UTC = timezone.utc
LISBON = ZoneInfo("Europe/Lisbon")
SETTINGS = {"template": shifts.DEFAULT_TEMPLATE, "workdays": [1, 2, 3, 4, 5], "holidays": [], "revision": 1}


def lisbon(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=LISBON).astimezone(UTC)


def week_calendar(rid, year, week, per_day=1, days=(1, 2, 3, 4, 5)):
    return shifts.definition_for(rid, year, week, {str(d): (per_day if d in days else 0) for d in range(1, 8)}, {},
                                 SETTINGS, manual=False)


def calendar_of(rid, weeks=((2026, 42), (2026, 43), (2026, 44)), per_day=1):
    origin = lisbon(2026, 10, 12, 6)
    defs = [week_calendar(rid, y, w, per_day) for y, w in weeks]
    windows = forecast.label_windows(defs, shifts.DEFAULT_TEMPLATE, origin)
    return forecast.Calendar(windows.get(rid, []))


# --- margem e risco

def test_margin_is_zero_on_the_due_day_one_from_friday_to_monday_and_negative_when_late():
    cal = calendar_of("m1")
    friday = lisbon(2026, 10, 16, 12)
    assert forecast.margin_days(friday, "2026-10-16", cal) == 0           # acaba no dia do prazo
    assert forecast.margin_days(friday, "2026-10-19", cal) == 1           # sexta → segunda (sábado e domingo sem turnos)
    assert forecast.margin_days(lisbon(2026, 10, 21, 10), "2026-10-19", cal) == -2  # acaba quarta, prazo segunda
    assert forecast.margin_days(lisbon(2026, 10, 17, 0, 0), "2026-10-16", cal) == 0  # acaba à meia-noite = ainda sexta


def test_margin_of_work_already_late_counts_the_past_working_days_by_the_sector_rule():
    """Prazo de agosto e conclusão depois da origem: os dias antes do calendário contam pela regra do setor (dias da
    semana e feriados), nunca só os dias com calendário (um defeito visto com dados reais a 08/10)."""
    rule = forecast.Rule([1, 2, 3, 4, 5], ["2026-10-05", "2026-08-15"])  # 15/08/2026 é sábado: não conta
    windows = forecast.label_windows([week_calendar("m1", 2026, 42)], shifts.DEFAULT_TEMPLATE, lisbon(2026, 10, 12, 6))
    cal = forecast.Calendar(windows["m1"], rule)  # calendário só de 12 a 16/10
    expected = sum(1 for i in range(1, (date(2026, 10, 11) - date(2026, 8, 7)).days + 1)
                   if (date(2026, 8, 7) + timedelta(days=i)).isoweekday() <= 5) - 1  # menos o feriado de 05/10
    assert forecast.margin_days(lisbon(2026, 10, 12, 9), "2026-08-07", cal) == -(expected + 1)  # + segunda 12/10
    assert rule.count(date(2026, 10, 2), date(2026, 10, 9)) == 4                     # sex → sex, sem o feriado
    assert rule.count(date(2026, 10, 9), date(2026, 10, 2)) == 0
    assert forecast.margin_days(lisbon(2026, 10, 16, 9), "2026-11-02", cal) == 11    # depois do calendário: pela regra


def test_picking_is_an_instant_finishing_monday_at_ten_is_late_even_with_margin_zero():
    cal = calendar_of("m1")
    due = lisbon(2026, 10, 19, 8)  # Picking: segunda às 08:00
    end = lisbon(2026, 10, 19, 10)
    margin = forecast.margin_days(end, "2026-10-19", cal)
    assert margin == 0
    assert forecast.state_of(end=end, due=due, margin=margin, folga=2, beyond=False, horizon_end=None, missing=[]) == ("atrasa", None)
    early = lisbon(2026, 10, 19, 7)
    assert forecast.state_of(end=early, due=due, margin=0, folga=2, beyond=False, horizon_end=None, missing=[]) == ("em_risco", None)
    assert forecast.state_of(end=early, due=due, margin=2, folga=2, beyond=False, horizon_end=None, missing=[]) == ("ok", None)


def test_no_forecast_has_a_reason_and_beyond_the_horizon_is_late_when_the_due_date_is_inside():
    due = lisbon(2026, 10, 30, 0)
    assert forecast.state_of(end=None, due=due, margin=None, folga=2, beyond=False, horizon_end=None, missing=["sem_horas"]) == ("sem_previsao", "sem_horas")
    assert forecast.state_of(end=None, due=due, margin=None, folga=2, beyond=True, horizon_end=lisbon(2027, 1, 1), missing=[]) == ("atrasa", None)
    assert forecast.state_of(end=None, due=lisbon(2028, 1, 1), margin=None, folga=2, beyond=True, horizon_end=lisbon(2027, 1, 1),
                             missing=[]) == ("sem_previsao", "alem_do_horizonte")
    assert forecast.state_of(end=lisbon(2026, 10, 20), due=None, margin=None, folga=2, beyond=False, horizon_end=None, missing=[]) == (None, "sem_prazo")


def test_already_late_is_counted_apart():
    cal = calendar_of("m1")
    line = {"end": lisbon(2026, 10, 13, 9), "due": lisbon(2026, 10, 10), "due_day": "2026-10-09", "beyond": False, "missing": []}
    forecast._evaluate(line, cal, 2, None, "2026-10-12")
    assert line["state"] == "atrasa" and line["already_late"] is True and line["margin_days"] == -2


# --- falta acumulada, recuperação e recurso limitante

def test_shortage_by_due_date_recovers_when_capacity_catches_up():
    cal = calendar_of("m1")  # 7,5 h por dia útil
    origin = lisbon(2026, 10, 12, 6)
    ops = [{"due": lisbon(2026, 10, 13), "seconds": 20 * 3600}]  # 20 h com prazo no fim de segunda
    found = forecast.shortage(ops, cal, origin, date(2026, 10, 30))
    assert found["overloaded"] and found["recovers"]
    assert found["peak_hours"] == 12.5                       # 20 h − 7,5 h de segunda
    assert found["recovery"] == date(2026, 10, 14)           # terça faltam 5 h; na quarta já não falta
    late = forecast.shortage([{"due": lisbon(2026, 10, 13), "seconds": 500 * 3600}], cal, origin, date(2026, 10, 30))
    assert late["overloaded"] and not late["recovers"] and late["recovery"] is None
    none = forecast.shortage([{"due": lisbon(2026, 10, 20), "seconds": 3600}, {"due": None, "seconds": 999 * 3600}], cal, origin, date(2026, 10, 30))
    assert not none["overloaded"] and none["recovery"] is None


def test_limiting_resource_is_the_one_that_recovers_last_not_recovering_first_and_ties_shown():
    def slot(i, recovers, recovery, peak=1.0, late=0.0):
        return {"id": i, "overloaded": True, "recovers": recovers, "recovery": recovery, "peak_weeks": peak, "late_hours": late}
    a, b = slot("A", True, date(2026, 11, 20), peak=9), slot("B", True, date(2026, 12, 1), peak=1)
    assert [s["id"] for s in forecast.limiting([a, b])] == ["B"]            # recupera mais tarde, mesmo com pico menor
    c = slot("C", False, None, peak=0.5)
    assert [s["id"] for s in forecast.limiting([a, b, c])] == ["C"]         # «não recupera» primeiro
    d = slot("D", True, date(2026, 12, 1), peak=3)
    assert [s["id"] for s in forecast.limiting([b, d])] == ["D"]            # desempate: pico em semanas
    e = slot("E", True, date(2026, 12, 1), peak=1, late=5)
    assert [s["id"] for s in forecast.limiting([b, e])] == ["E"]            # depois: horas atrasadas
    f = slot("F", True, date(2026, 12, 1), peak=1)
    assert [s["id"] for s in forecast.limiting([f, b])] == ["B", "F"]       # empate verdadeiro: os dois
    assert forecast.limiting([{"id": "x", "overloaded": False}]) == []


def test_full_cell_is_complete_never_an_error():
    assert forecast.cell_state(7.5 * 3600, 7.5 * 3600) == "completa"
    assert forecast.cell_state(7.5 * 3600, 7.5 * 3600 - 30) == "completa"
    assert forecast.cell_state(7.5 * 3600, 3600) == "parcial"
    assert forecast.cell_state(7.5 * 3600, 0) == "sem_carga"
    assert forecast.cell_state(0, 0) == "fechado"


def test_people_needed_is_the_peak_of_machines_working_times_people_per_machine():
    t = lisbon(2026, 10, 12, 6)
    segs = {"m1": [(t, t + timedelta(hours=2))], "m2": [(t + timedelta(hours=1), t + timedelta(hours=3))],
            "m3": [(t + timedelta(hours=2), t + timedelta(hours=4))]}  # m1 acaba quando m3 começa
    assert forecast.people_needed(segs, {"m1": 1, "m2": 1, "m3": 1}) == 2
    assert forecast.people_needed(segs, forecast.persons_of({"m2": 3}, ["m1", "m2", "m3"])) == 4
    assert forecast.persons_of(None, ["m1"]) == {"m1": 1} and forecast.persons_of(2, ["m1"]) == {"m1": 2}


def test_origin_is_the_start_of_the_current_shift_in_lisbon():
    tpl = shifts.DEFAULT_TEMPLATE
    assert forecast.origin_at(lisbon(2026, 10, 12, 9, 17), tpl) == lisbon(2026, 10, 12, 6)
    assert forecast.origin_at(lisbon(2026, 10, 12, 13, 45), tpl) == lisbon(2026, 10, 12, 6)    # entre turnos: o último
    assert forecast.origin_at(lisbon(2026, 10, 13, 1, 30), tpl) == lisbon(2026, 10, 12, 22)    # 3.º turno da véspera
    assert forecast.origin_at(lisbon(2026, 10, 25, 1, 30), tpl) == lisbon(2026, 10, 24, 22)    # noite da mudança da hora


# --- montagem da entrada e invariante das horas

def fact(key, line, of, rid, hours, *, remaining=10, phase="principal", basis="atribuída", due="2026-10-16", pieces=None,
         parked=False, priority=None, customer="Cliente"):
    return {"key": key, "line_key": line, "of": of, "phase": phase, "remaining": remaining, "pieces": remaining if phase == "principal" else None,
            "planning_resource_id": rid, "planning_machine": rid, "machine_basis": basis if rid else None, "load_hours": hours,
            "load_basis": "estimada", "reference": "R" + key, "operation": "Corte", "customer": customer, "profile": "L50",
            "length_mm": 1000, "signals": {"prioridade": priority},
            "priority": {"priority_date": (lisbon(*map(int, due.split("-"))) + timedelta(days=1)).isoformat() if due else None,
                         "priority_day": due, "priority_field": "cut_date", "parked": parked, "provisional": False}}


def test_planned_part_and_rest_split_the_seconds_without_losing_any():
    facts = [fact("a", "L1", "OF1", "m1", 3.0, remaining=10), fact("b", "L1", "OF1", "m1", 1.0, remaining=10, phase="seguinte"),
             fact("c", "L2", "OF2", "m1", 2.0)]
    ops, meta = forecast.operations_from(facts, sector="perfis", planned={"L1": 4}, own={"m1"}, pools={})
    by = {o["key"]: o for o in ops}
    assert by["a"]["scope"] == 0 and by["a"]["seconds"] == int(3 * 3600 * 4 / 10)
    assert by["a#resto"]["scope"] == 1 and by["a"]["seconds"] + by["a#resto"]["seconds"] == 3 * 3600
    assert meta["a"]["pieces"] == 4 and meta["a#resto"]["pieces"] == 6
    # Seguinte (MTG2 Abocardar): saldo próprio 10, principal 10 → nada cortado à espera: só a parte planeada (4).
    assert by["b"]["seconds"] == int(3600 * 4 / 10)
    assert by["c"]["scope"] == 1 and "c#resto" not in by
    # Um set (código antigo) = linhas inteiras.
    ops, _ = forecast.operations_from(facts, sector="perfis", planned={"L1"}, own={"m1"}, pools={})
    assert {o["key"]: o["scope"] for o in ops} == {"a": 0, "b": 0, "c": 1}
    assert forecast.planned_pieces({"remaining": 10, "phase": "seguinte"}, 4, principal_remaining=3) == 10  # 7 cortadas + 4 → saldo
    assert forecast.planned_pieces({"remaining": 10, "phase": "seguinte"}, 2, principal_remaining=9) == 3
    assert forecast.planned_pieces({"remaining": 10}, 0, None) == 0


def test_priority_key_follows_written_priority_then_priority_clients_then_due_date():
    clients = ["acme"]
    keys = {name: forecast.priority_key(f, clients) for name, f in {
        "written": fact("w", "L", "OF9", "m1", 1, priority=2, due="2026-12-01"),
        "client": fact("c", "L", "OF8", "m1", 1, customer="ACME Lda", due="2026-11-01"),
        "early": fact("e", "L", "OF7", "m1", 1, due="2026-10-13"),
        "undated": fact("u", "L", "OF1", "m1", 1, due=None)}.items()}
    assert sorted(keys, key=keys.get) == ["written", "client", "early", "undated"]


def _inputs(facts, planned, *, posts=None, machines=("m1", "m2"), now=None, settings=None):
    now = now or lisbon(2026, 10, 12, 6, 30)
    settings = {**SETTINGS, **(settings or {})}
    origin = forecast.origin_at(now, settings["template"])
    ki = {"settings": settings, "origin": origin, "today": now.astimezone(LISBON).date(), "now": now,
          "data": {"imported_at": None}, "occ": {"facts": facts}, "planned": planned, "stale": False, "key": ("k",)}
    calendars = [week_calendar(rid, y, w) for rid in machines for y, w in ((2026, 42), (2026, 43), (2026, 44))]
    src = {"machines": [{"id": rid, "name": rid.upper()} for rid in machines], "calendars": calendars,
           "posts": posts or {}, "names": {}, "v2_at": None}
    return ki, src


def test_forecast_hours_per_machine_equal_the_load_totals_and_the_check_passes():
    """Invariante: Σ horas previstas por máquina (colocáveis + estacionadas/sem calendário) = Σ horas da Carga."""
    facts = [fact(f"k{i}", f"L{i}", f"OF{i % 4}", ("m1", "m2")[i % 2], 0.37 * (i + 1), basis="sugerida" if i % 3 else "atribuída")
             for i in range(30)]
    facts.append(fact("park", "LP", "OFP", "m1", 4.2, parked=True))
    facts.append(fact("other", "LO", "OFO", "elsewhere", 1.0))
    facts.append(fact("second", "LS", "OFS", "m2", 2.0, phase="seguinte"))
    ki, src = _inputs(facts, {"L0": 3, "L3": None})
    result = forecast.compute("cantoneiras", ki, src)
    assert result["check"] == []
    expected = {}
    for f in facts:  # a regra da Carga: máquinas do setor, sem a 2.ª operação das cantoneiras
        if f["planning_resource_id"] in ("m1", "m2") and f["phase"] == "principal":
            expected[f["planning_resource_id"]] = expected.get(f["planning_resource_id"], 0) + f["load_hours"]
    assert {rid: h["total"] for rid, h in result["machine_hours"].items()} == {rid: round(v, 2) for rid, v in expected.items()}
    assert result["machine_hours"]["m1"]["excluded"] == 4.2
    reasons = {u["key"]: u["reason"] for u in result["unschedulable"]}
    assert reasons == {"park": "estacionada", "other": "outro_setor", "second": "segunda_operacao"}
    assert "OFP" not in result["orders"]  # estacionadas fora das listas de risco
    assert "OFS" not in result["orders"]  # só 2.ª operação: fora da conclusão (não é «sem previsão»)


def test_mtg2_order_is_judged_whole_against_the_picking_instant():
    facts = [fact("a", "L1", "OF1", "m1", 7.0), fact("b", "L2", "OF1", "m2", 10.0)]  # m2 acaba terça às 08:30
    for f in facts:
        f["priority"].update(priority_date=lisbon(2026, 10, 13, 8).isoformat(), priority_day="2026-10-13", priority_field="picking")
    ki, src = _inputs(facts, {})
    fc = forecast.compute("perfis", ki, src)
    order = fc["orders"]["OF1"]
    assert order["end"] == max(r["end"] for r in fc["operations"].values())  # a OF inteira
    assert order["state"] == "atrasa" and order["margin_days"] == 0        # acaba terça depois das 08:00
    assert fc["counts"]["atrasa"] == 1


def test_people_per_shift_use_the_settings_and_never_count_a_deficit_without_availability():
    facts = [fact("a", "L1", "OF1", "m1", 7.0), fact("b", "L2", "OF2", "m2", 7.0)]
    ki, src = _inputs(facts, {})
    first = forecast.compute("perfis", ki, src)["people"][0]
    assert (first["machines"], first["need"], first["available"], first["deficit"]) == (2, 2, None, None)
    ki, src = _inputs(facts, {}, settings={"pessoas_por_maquina": {"m1": 2}, "pessoas_por_turno": [2, 1, 1]})
    first = forecast.compute("perfis", ki, src)["people"][0]
    assert (first["need"], first["available"], first["deficit"]) == (3, 2, 1)


def test_shared_post_in_the_forecast_is_one_resource_and_one_shortage():
    facts = [fact("a", "L1", "OF1", "post", 5.0), fact("b", "L2", "OF2", "doall", 5.0)]
    ki, src = _inputs(facts, {}, posts={"post": ["doall"]}, machines=("post", "doall"))
    fc = forecast.compute("perfis", ki, src)
    assert fc["check"] == []
    a, b = fc["operations"]["a"], fc["operations"]["b"]
    assert a["end"] <= b["start"] or b["end"] <= a["start"]   # nunca ao mesmo tempo
    assert [s["id"] for s in fc["slots"]] == ["post"] and fc["machines"]["doall"]["slot"] == "post"
