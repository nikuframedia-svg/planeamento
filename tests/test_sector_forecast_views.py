"""Vistas da previsão na Carga: «Capacidade e prazos» e «Calendário» (forecast_views.py, Etapa 3, 08/10/2026).
Sem base de dados: a previsão é calculada por forecast.compute com entradas montadas à mão."""
from datetime import date

from app.sector import forecast, forecast_views as fv
from tests.test_sector_forecast_risk import _inputs, fact

TODAY = date(2026, 10, 12)  # segunda; _inputs põe a origem às 06:00 desse dia


def _mtg3():
    """m1: OF2 (já em atraso, 3 h) e OF1 (7,5 h, prazo segunda: acaba terça → atrasa); m2: OF4 (em risco) e OF3 (ok)."""
    facts = [fact("a", "L1", "OF1", "m1", 7.5, due="2026-10-12"), fact("b", "L2", "OF2", "m1", 3.0, due="2026-10-09"),
             fact("c", "L3", "OF3", "m2", 2.0, due="2026-10-30"), fact("d", "L4", "OF4", "m2", 2.0, due="2026-10-13")]
    ki, src = _inputs(facts, {})
    f = forecast.compute("cantoneiras", ki, src)
    return f, fv.build_index(f)


def test_counters_are_the_forecast_counts_and_already_late_is_apart():
    f, index = _mtg3()
    view = fv.capacity_view(f, index, "dia", TODAY)
    counts = f["counts"]
    assert view["counters"] == {"atrasam": counts["atrasa"], "em_risco": counts["em_risco"],
                                "ja_em_atraso": counts["ja_em_atraso"], "sem_previsao": counts["sem_previsao"]}
    assert view["counters"]["atrasam"] == 1 and view["counters"]["em_risco"] == 1 and view["counters"]["ja_em_atraso"] == 1
    # Riscos principais: só os que atrasam ou ficam em risco; os já em atraso contam à parte, nunca na lista.
    assert [(r["of"], r["state"]) for r in view["risks"]] == [("OF1", "atrasa"), ("OF4", "em_risco")]
    late = view["risks"][0]
    assert late["margin_days"] == -1 and late["machine"] == "M1" and late["due_label"] == "Data Corte"
    assert late["reason"] == "Fila na M1"


def test_day_map_has_fifteen_working_days_and_week_map_thirteen_weeks():
    f, index = _mtg3()
    days = fv.capacity_view(f, index, "dia", TODAY)
    assert len(days["periods"]) == 15
    assert all(date.fromisoformat(p["key"]).isoweekday() <= 5 for p in days["periods"])  # sábados e domingos fora
    assert days["periods"][0]["key"] == "2026-10-12"
    weeks = fv.capacity_view(f, index, "semana", TODAY)
    assert len(weeks["periods"]) == 13 and weeks["periods"][0]["key"] == "2026-W42"
    assert all(len(m["periods"]) == 13 for m in weeks["machines"])


def test_cell_states_full_is_complete_never_an_error_and_risk_is_a_separate_mark():
    f, index = _mtg3()
    view = fv.capacity_view(f, index, "dia", TODAY)
    m1, m2 = view["machines"]
    monday, tuesday, wednesday = m1["periods"][:3]
    assert (monday["state"], monday["pct"]) == ("completa", 100)      # 7,5 / 7,5 h: completa, não erro
    assert monday["risk_marks"] == {"ja_em_atraso": 1}                 # OF2 acaba segunda (já estava em atraso)
    assert (tuesday["state"], tuesday["pct"]) == ("parcial", 40)
    assert tuesday["risk_marks"] == {"atrasa": 1}                       # OF1 acaba terça, depois do prazo
    assert wednesday["state"] == "sem_carga" and wednesday["risk_marks"] == {}
    assert m2["periods"][0]["risk_marks"] == {"em_risco": 1}
    assert fv.cell_of(0, 0)["state"] == "fechado"
    assert fv.cell_of(0, 0, has_calendar=False)["state"] == "sem_calendario"
    assert fv.cell_of(7.5 * 3600, 7.5 * 3600 - 10)["pct"] == 100       # a 1 min do fim: completa
    assert fv.cell_of(7.5 * 3600, 7.4 * 3600)["pct"] == 98             # parcial nunca chega a 100 % por arredondar


def test_calendar_keeps_forecast_and_realized_apart():
    f, index = _mtg3()
    realized = {"2026-10-09": {"pieces": 120, "metres": 80.0, "sheets": 3, "records": 9},
                "2026-10-12": {"pieces": 15, "metres": 10.0, "sheets": 1, "records": 2},
                "2026-10-13": {"pieces": 999, "metres": 1.0, "sheets": 1, "records": 1}}  # amanhã: nunca se mostra
    view = fv.calendar_view(f, index, date(2026, 10, 5), date(2026, 10, 18), TODAY, {"2026-10-16": {"OF3"}}, realized)
    days = {d["date"]: d for d in view["days"]}
    friday = days["2026-10-09"]                       # passado: só realizado
    assert friday["past"] and friday["forecast_h"] is None and friday["capacity_h"] is None
    assert friday["realized"]["pieces"] == 120 and friday["due"] == [{"of": "OF2", "field": "cut_date", "label": "Data Corte"}]
    assert days["2026-10-10"]["realized"] == {"pieces": 0, "metres": None, "metres_unknown": 0, "sheets": 0, "records": 0}
    today = days["2026-10-12"]                        # hoje: previsão e realizado, cada um no seu campo
    assert (today["capacity_h"], today["forecast_h"], today["state"]) == (15.0, 11.5, "parcial")
    assert today["realized"]["pieces"] == 15 and today["ofs"] == 4
    assert today["ends"] == ["OF2", "OF3", "OF4"] and today["at_risk"] == 1 and today["already_late"] == 1
    tomorrow = days["2026-10-13"]
    assert tomorrow["realized"] is None and tomorrow["late"] == 1 and tomorrow["ends"] == ["OF1"]
    assert days["2026-10-17"]["closed"] is True and days["2026-10-17"]["state"] == "fechado"
    assert days["2026-10-16"]["deliveries"] == ["OF3"]
    # Sem dados do MES: nada de realizado (nunca zeros inventados).
    none = fv.calendar_view(f, index, date(2026, 10, 9), date(2026, 10, 13), TODAY, {}, None)
    assert all(d["realized"] is None for d in none["days"]) and none["realized_available"] is False


def test_day_detail_has_shifts_and_orders_by_machine_and_realized_apart():
    f, index = _mtg3()
    realized = fv.realized_by_machine(
        [{"machine": "Folha M1", "day": "2026-10-12", "quantity": 4, "length_mm": 2500, "sheet": "s1"},
         {"machine": "Folha M1", "day": "2026-10-12", "quantity": 6, "length_mm": None, "sheet": "s1"},
         {"machine": "Outra", "day": "2026-10-11", "quantity": 50, "length_mm": 1000, "sheet": "s2"}],
        {("2026-10-12", "Folha M1"): 7.0}, {"Folha M1": ("m1", "M1")}, "2026-10-12")
    assert realized == [{"id": "m1", "machine": "M1", "pieces": 10, "metres": 10.0, "metres_unknown": 1, "hours": 7.0, "sheets": 1}]
    day = fv.day_view(f, index, TODAY, TODAY, realized)
    assert day["realized"] == realized and day["total"]["forecast_h"] == 11.5
    m1 = day["machines"][0]
    assert m1["name"] == "M1" and m1["state"] == "completa"
    assert [(s["shift"], s["start"], s["end"], s["capacity_h"]) for s in m1["shifts"]] == [(1, "06:00", "13:30", 7.5)]
    rows = {r["of"]: r for r in m1["ofs"]}
    assert rows["OF1"]["hours"] == 4.5 and rows["OF1"]["ends"] is None          # acaba amanhã
    assert rows["OF2"]["hours"] == 3.0 and rows["OF2"]["ends"] is not None
    assert rows["OF2"]["pieces"] == 10 and rows["OF2"]["metres"] == 10.0 and rows["OF2"]["kind"] == "Resto"
    assert "realized" not in m1                                                  # nunca dentro da previsão
    assert day["people"] is None                                                 # pessoas por turno não definidas
    past = fv.day_view(f, index, date(2026, 10, 9), TODAY, [])
    assert past["past"] and past["machines"] == [] and past["total"] is None


def test_planned_part_shows_as_planned_and_rest_as_rest():
    facts = [fact("a", "L1", "OF1", "m1", 5.0, remaining=10)]
    ki, src = _inputs(facts, {"L1": 4})
    f = forecast.compute("cantoneiras", ki, src)
    day = fv.day_view(f, fv.build_index(f), TODAY, TODAY, None)
    kinds = {r["kind"]: r for r in day["machines"][0]["ofs"]}
    assert kinds["Planeado"]["pieces"] == 4 and kinds["Resto"]["pieces"] == 6
    assert kinds["Planeado"]["hours"] + kinds["Resto"]["hours"] == 5.0


def test_mtg2_sector_capacity_counts_a_shared_post_once():
    """Fita pav.1 (posto) contém o Doall: a capacidade do setor num dia soma o posto e a m1, nunca o Doall também."""
    facts = [fact("a", "L1", "OF1", "post", 2.0), fact("b", "L2", "OF2", "doall", 1.0), fact("c", "L3", "OF3", "m1", 1.0)]
    for x in facts:
        x["priority"].update(priority_field="picking")
    ki, src = _inputs(facts, {}, posts={"post": ["doall"]}, machines=("post", "doall", "m1"))
    f = forecast.compute("perfis", ki, src)
    index = fv.build_index(f)
    assert index["posts"] == {"post": ["doall"]}
    view = fv.calendar_view(f, index, TODAY, TODAY, TODAY, {}, None)
    assert view["days"][0]["capacity_h"] == 15.0                       # 7,5 (posto) + 7,5 (m1), não 22,5
    assert view["days"][0]["forecast_h"] == 4.0                        # as horas não se contam a dobrar
    assert fv.sector_capacity({"post": 10, "doall": 10, "m1": 5}, {"post": ["doall"]}) == 15
    assert fv.sector_capacity({"post": None, "doall": 10, "m1": 5}, {"post": ["doall"]}) == 15  # sem calendário: as máquinas
    # MTG2: as marcas de risco são da OF inteira, na máquina onde acaba.
    risk = fv.capacity_view(f, index, "dia", TODAY)
    assert risk["counters"]["atrasam"] == f["counts"]["atrasa"]


def test_realized_by_day_counts_pieces_metres_and_sheets():
    rows = [{"day": "2026-10-09", "quantity": 4, "length_mm": 2500, "sheet": "s1"},
            {"day": "2026-10-09", "quantity": 2, "length_mm": None, "sheet": "s2"},
            {"day": "2026-10-09", "quantity": None, "length_mm": 1000, "sheet": "s2"}]
    assert fv.realized_by_day(rows) == {"2026-10-09": {"pieces": 6, "metres": 10.0, "metres_unknown": 1, "sheets": 2, "records": 3}}
    # Sem comprimento nas folhas (o normal no MES): metros desconhecidos, nunca 0.
    assert fv.realized_by_day([{"day": "d", "quantity": 3, "length_mm": None, "sheet": "s"}])["d"]["metres"] is None


def test_scenario_uses_compute_for_when_installed_and_the_plan_in_use_otherwise(monkeypatch):
    plan = {"sector": "cantoneiras", "plan": True}
    monkeypatch.setattr(fv.forecast, "current", lambda sector, allow_stale=False: plan)
    monkeypatch.setattr(fv, "_scenario_compute", lambda: None)
    f, scenario = fv.forecast_for("cantoneiras", "7")
    assert f is plan and scenario == {"id": "7", "name": None, "available": False}
    assert fv.forecast_for("cantoneiras", None) == (plan, None)
    asked = []

    def compute_for(sector, cenario_id=None):
        asked.append((sector, cenario_id))
        return {"sector": sector, "scenario": {"id": cenario_id, "name": "Peddi parada"}}
    monkeypatch.setattr(fv, "_scenario_compute", lambda: compute_for)
    f, scenario = fv.forecast_for("cantoneiras", "7")
    assert asked == [("cantoneiras", "7")] and scenario == {"id": "7", "name": "Peddi parada", "available": True}


def test_memos_keep_the_plan_in_use_and_only_the_last_scenarios_and_drop_expired_realized(monkeypatch):
    """Revisão 08/10 (R1): o índice prende a previsão inteira — fica o do plano em uso e os 3 últimos cenários; o
    realizado tira os expirados ao gravar e não passa de REALIZED_KEPT entradas."""
    monkeypatch.setattr(fv, "build_index", lambda f: {"of": id(f)})
    fv.invalidate()
    for slot in (("cantoneiras", None), ("cantoneiras", "a"), ("perfis", None), ("cantoneiras", "b"),
                 ("perfis", "c"), ("cantoneiras", "d")):
        fv._index({}, slot)
    assert list(fv._index_memo) == [("cantoneiras", None), ("perfis", None), ("cantoneiras", "b"), ("perfis", "c"),
                                    ("cantoneiras", "d")]
    now = [1000.0]
    monkeypatch.setattr(fv.clock, "monotonic", lambda: now[0])
    fv._remember_realized(("cantoneiras", 1, 1), ([], {}))
    now[0] += fv.REALIZED_SECONDS
    fv._remember_realized(("cantoneiras", 2, 2), ([], {}))
    assert list(fv._realized_memo) == [("cantoneiras", 2, 2)]                  # o expirado saiu ao gravar
    for i in range(fv.REALIZED_KEPT + 10):
        fv._remember_realized(("perfis", i, i), ([], {}))
    last = fv.REALIZED_KEPT + 9
    assert len(fv._realized_memo) == fv.REALIZED_KEPT and ("perfis", last, last) in fv._realized_memo
    fv.invalidate()
