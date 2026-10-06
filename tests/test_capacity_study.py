"""Estudo de capacidade (01/10/2026): débito observado, estimativas, sugestões e desempates. Sem base de dados."""
from datetime import date

from app.gantt import integrated, machines
from app.sector import capacity, estimates, throughput
from tests.test_sector_needs import RELATIONS, TODAY, need, resources


def line(machine, day, metres, hours=None, speed=45, of="OF1", profile="L70X70X7"):
    return {"Máquina Corte": machine, "dia": day, "m prod.": metres, "h teor. Trab": hours, "Mt\\h": speed, "OF": of, "Tipo de perfil": profile}


def test_production_day_never_guesses_between_several_days():
    assert throughput.production_day("2026-09-14T00:00:00") == (date(2026, 9, 14), None)
    assert throughput.production_day("31/08/2026") == (date(2026, 8, 31), None)
    assert throughput.production_day("20+21/08/26") == (None, "varias_datas")
    assert throughput.production_day("1900-01-00")[1] in ("data_zero_excel", "data_ilegivel")
    assert throughput.production_day(None) == (None, "sem_data")


def test_weekly_throughput_counts_complete_weeks_and_observed_zeros():
    rows = [line("Rapid", "2026-09-07", 450, 10), line("Rapid", "2026-09-08", 90),  # hours from metres/speed
            line("Rapid", "2026-09-21", 900, 20), line("Rapid", "2026-09-29", 999, 99),  # current week: out
            line("Rapid", "21+22/09/2026", 500, 11)]
    weekly = throughput.weekly_mtg3(rows, until=date(2026, 9, 30), weeks=4)
    series = {w["iso"]: w for w in weekly["series"]["Rapid"]}
    assert series["2026-W37"]["hours"] == 12 and series["2026-W37"]["metres"] == 540
    assert series["2026-W38"]["observed_zero"] and series["2026-W38"]["hours"] == 0
    assert "2026-W40" not in series and weekly["excluded"]["varias_datas"] == 1
    summary = throughput.summarise(weekly["series"])["Rapid"]
    assert summary["weeks"] == 3 and summary["zero_weeks"] == 1 and summary["hours_median"] == 12


def test_speeds_use_weighted_medians_by_machine_and_profile():
    rows = [line("XP", "2026-09-01", 1, speed=120)] * 5 + [line("XP", "2026-09-01", 1, speed=80, profile="L50X50X5")] * 3
    by_machine, by_profile = throughput.speeds(rows)
    assert by_machine["XP"]["value"] == 120 and by_machine["XP"]["lines"] == 8
    assert by_profile[("XP", "L50X50X5")]["value"] == 80


def test_mes_rates_count_each_sheet_once_and_drop_impossible_hours():
    events = [{"folha_uid": "a", "recurso_codigo": "XPT6", "setor": "MTG3", "horas_reportadas": 7.5, "metros_reportados": 1050},
              {"folha_uid": "a", "recurso_codigo": "XPT6", "setor": "MTG3", "horas_reportadas": 7.5, "metros_reportados": 1050},
              {"folha_uid": "b", "recurso_codigo": "XPT6", "setor": "MTG3", "horas_reportadas": 730, "metros_reportados": 900}]
    found = throughput.mes_rates(events)[("MTG3", "XPT6")]
    assert found["sheets"] == 2 and found["sheets_with_hours"] == 1 and found["metres_per_hour_median"] == 140


STUDY = {"speeds": {"Ficep Rapid 25T": {"value": 35, "lines": 100}},
         "profile_speeds": {("Ficep Rapid 25T", "L70X70X7"): {"value": 40, "lines": 12}, ("Ficep Rapid 25T", "L90X90X9"): {"value": 30, "lines": 2}},
         "summary": {}}


def test_estimates_use_profile_speed_then_machine_and_never_invent_following_operations():
    fact = {"remaining": 10, "phase": "principal", "area": "cantoneiras", "length_mm": 2000, "profile": "L70X70X7"}
    hours, why = estimates.estimate(fact, {"code": "RAPID25", "name": "Ficep Rapid 25T"}, {"Ficep Rapid 25T"}, STUDY, {})
    assert hours == 0.5 and "L70X70X7" in why
    hours, why = estimates.estimate({**fact, "profile": "L90X90X9"}, None, {"Ficep Rapid 25T"}, STUDY, {})
    assert round(hours, 4) == round(20 / 35, 4) and "todos os perfis" in why  # 2 lines are not enough for the profile
    assert estimates.estimate({**fact, "phase": "seguinte"}, None, {"Ficep Rapid 25T"}, STUDY, {})[0] is None
    assert estimates.estimate({**fact, "remaining": None}, None, {"Ficep Rapid 25T"}, STUDY, {})[0] is None
    mtg2 = {"remaining": 10, "phase": "principal", "area": "perfis", "section_unit": 500}
    hours, why = estimates.estimate(mtg2, {"code": "MEBA", "name": "MEBA"}, {"MEBA"}, STUDY, {"MEBA": 5000})
    assert hours == 1 and "sem fator ×3" in why


class Index:
    """Candidate machines as the Gantt evidence index would return them."""
    def __init__(self, options):
        self.options = options

    def candidates(self, row, codes):
        return [dict(o) for o in self.options[row["key"]]]


def option(rid, history=0, conditions=()):
    return {"resource_id": rid, "resource_code": rid, "proposed_code": "CPIS:119", "eligibility": "conditional",
            "conditions": list(conditions), "other_orders": history}


def test_suggestions_prefer_history_then_avoid_third_party_conditions_then_balance_load(monkeypatch):
    by_id = {r: {"id": r, "name": r, "code": r, "aliases": []} for r in ("R1", "R2", "P6")}
    facts = []
    for i in range(6):
        f = need(f"k{i}", "cantoneiras", None, None, "2026-09-20", late=True)
        f.update(assigned_resource_id=None, assigned_machine="Sem máquina", hours=None, hours_origin=None, length_mm=4500,
                 remaining=10, profile="L70X70X7", phase="principal", of=f"OF{i}")
        facts.append(f)
    options = {f"k{i}": [option("R1"), option("R2"), option("P6", conditions=["confirmar_cliente_nacional"])] for i in range(5)}
    options["k5"] = [option("R1"), option("R2", history=3)]
    monkeypatch.setattr(machines, "EvidenceIndex", lambda metadata, rows: Index(options))
    study = {"speeds": {"R1": {"value": 45, "lines": 9}, "R2": {"value": 45, "lines": 9}, "P6": {"value": 45, "lines": 9}},
             "profile_speeds": {}, "summary": {"R1": {"hours_median": 10}, "R2": {"hours_median": 10}, "P6": {"hours_median": 100}}}
    result = estimates.apply(facts, {f["key"]: {"key": f["key"]} for f in facts}, codes={}, by_id=by_id,
                             package={"metadata": {"rates": []}, "rows": []}, study=study)
    chosen = {f["key"]: f["planning_resource_id"] for f in facts}
    assert chosen["k5"] == "R2"  # precedent in 3 OF wins over load
    assert "P6" not in chosen.values()  # national-market option never wins a plain tie
    assert sorted(chosen[f"k{i}"] for i in range(5)).count("R1") in (2, 3)  # load balanced between R1 and R2
    assert all(f["machine_basis"] == "sugerida" and f["load_basis"] == "estimada" for f in facts)
    assert round(result["loads"]["R1"] + result["loads"]["R2"], 6) == 6.0


def test_gantt_choice_does_not_pick_a_conditional_third_party_option_by_code():
    options = [{"resource_id": "A", "resource_code": "PEDDI6", "proposed_code": "CPIS:112", "eligibility": "conditional",
                "conditions": ["confirmar_cliente_nacional"], "other_orders": 0},
               {"resource_id": "B", "resource_code": "XPT6", "proposed_code": "CPIS:112", "eligibility": "conditional",
                "conditions": ["revisao_tecnica_por_validar"], "other_orders": 0}]
    assert machines.choose(options, None)[0]["resource_id"] == "B"


def test_divergent_speeds_use_a_stated_weighted_median():
    templates = [{"value": 80, "lines": 3, "source": "Excel"}, {"value": 120, "lines": 5, "source": "Excel"}, {"value": 100, "lines": 1, "source": "Excel"}]
    chosen = integrated.median_template(templates)
    assert chosen["value"] == 120 and "mediana" in chosen["source"] and "120 m/h (5)" in chosen["divergent_values"]


def test_capacity_scenarios_label_observed_and_declared_evidence():
    data = {"cantoneiras": [need("n1", "cantoneiras", "r1", 30, "2026-10-02")], "perfis": [need("p1", "perfis", "r2", 50, "2026-10-02")]}
    observed = {"r1": {"weeks": 16, "hours_p25": 50, "hours_median": 60, "hours_p75": 70}}
    declared = {"r2": {"hours": 75, "p25": 40, "label": "mediana de 26 semanas"}}
    result = capacity.build(data, resources(), RELATIONS, [], [], {}, today=TODAY, horizon_weeks=1, observed=observed, declared=declared)
    week = result["units"]["cantoneiras"]["periods"][0]
    assert week["capacity_hours"] == 60 and week["capacity_status"] == "estimada" and week["pressure_pct"] == 50.0
    assert week["capacity_basis"] == ["observada"]
    perfis = result["units"]["perfis"]["periods"][0]
    assert perfis["capacity_basis"] == ["declarada"] and perfis["capacity_hours"] == 75
    assert "Posto" in perfis["without_capacity"] or perfis["capacity_partial"]
    prudent = capacity.build(data, resources(), RELATIONS, [], [], {}, today=TODAY, horizon_weeks=1, observed=observed, declared=declared, scenario="prudente")
    assert prudent["units"]["cantoneiras"]["periods"][0]["capacity_hours"] == 50
    strict = capacity.build(data, resources(), RELATIONS, [], [], {}, today=TODAY, horizon_weeks=1, observed=observed, declared=declared, scenario="confirmada")
    assert strict["units"]["cantoneiras"]["periods"][0]["capacity_hours"] is None
    lane = next(l for l in result["units"]["cantoneiras"]["resources"] if l["resource_id"] == "r1")
    assert lane["weekly_capacity_hours"] == 60 and lane["weeks_to_clear"] == 0.5


def test_pressure_is_computed_only_over_demand_with_known_capacity():
    """A queue without capacity no longer makes the whole sector unknown; its demand is shown apart."""
    data = {"cantoneiras": [need("a", "cantoneiras", "r1", 30, "2026-10-02"), need("b", "cantoneiras", "plasma", 12, "2026-10-02")]}
    res = resources(); res["plasma"] = {"id": "plasma", "code": "PLASMA", "name": "Plasma manual", "type": "posto", "windows": [], "calendar_status": "unknown", "area": "cantoneiras"}
    result = capacity.build(data, res, RELATIONS, [], [], {}, today=TODAY, horizon_weeks=1,
                            observed={"r1": {"weeks": 16, "hours_p25": 50, "hours_median": 60, "hours_p75": 70}})
    week = result["units"]["cantoneiras"]["periods"][0]
    assert week["need_hours"] == 42 and week["need_covered_hours"] == 30 and week["need_uncovered_hours"] == 12
    assert week["pressure_pct"] == 50.0 and week["without_capacity"] == ["Plasma manual"]


def test_lines_of_the_same_order_and_operation_stay_on_one_machine(monkeypatch):
    by_id = {r: {"id": r, "name": r, "code": r, "aliases": []} for r in ("R1", "R2")}
    facts = []
    for i, assigned in enumerate(("R2", None, None)):
        f = need(f"k{i}", "cantoneiras", assigned, 1.0 if assigned else None, "2026-09-20", late=True)
        f.update(assigned_resource_id=assigned, assigned_machine=assigned or "Sem máquina", hours=1.0 if assigned else None,
                 hours_origin="Excel" if assigned else None, length_mm=4500, remaining=10, profile="L70X70X7",
                 phase="principal", of="OF9", operation="CPIS:119")
        facts.append(f)
    options = {f"k{i}": [option("R1"), option("R2")] for i in range(3)}
    monkeypatch.setattr(machines, "EvidenceIndex", lambda metadata, rows: Index(options))
    study = {"speeds": {"R1": {"value": 45, "lines": 9}, "R2": {"value": 45, "lines": 9}}, "profile_speeds": {},
             "summary": {"R1": {"hours_median": 100}, "R2": {"hours_median": 1}}}  # R2 is far more loaded
    estimates.apply(facts, {f["key"]: {"key": f["key"]} for f in facts}, codes={}, by_id=by_id,
                    package={"metadata": {"rates": []}, "rows": []}, study=study)
    assert [f["planning_resource_id"] for f in facts] == ["R2", "R2", "R2"]
    assert facts[1]["suggestion"]["with_of_peers"] and "mesma máquina" in facts[1]["suggestion"]["reason"].lower()


def test_series_rule_prefers_punching_for_series_and_drilling_otherwise():
    assert estimates.series_process(24, "L70X70X6") == "Punção"
    assert estimates.series_process(3, "L70X70X6") == "Broca"       # low series
    assert estimates.series_process(40, "L100X100X10") == "Broca"   # thick plate
    assert estimates.series_process(40, "L150X150X8") == "Broca"    # leg above the punching limit
    assert estimates.series_process(None, "L70X70X6") is None and estimates.series_process(10, "texto") is None


def test_punching_machines_become_conditional_119_candidates_only_with_observed_practice():
    metadata = {"capacities": [
        {"id": 1, "recurso_codigo": "XPT4", "operacao_codigo": "CPIS:112", "processo_fisico": "Punção", "perfil_minimo": "L40X40X3", "perfil_maximo": "L120X120X12", "fonte": "ficha"},
        {"id": 2, "recurso_codigo": "PEDDI8", "operacao_codigo": "CPIS:112", "processo_fisico": "Punção", "perfil_minimo": "L40X40X4", "perfil_maximo": "L120X120X8", "fonte": "ficha"},
        {"id": 3, "recurso_codigo": "RAPID", "operacao_codigo": "CPIS:119", "processo_fisico": "Broca", "perfil_minimo": "L40X40X3", "perfil_maximo": "L200X200X24", "fonte": "ficha"}],
        "history": [{"variante_id": f"v{i}", "operacao_codigo": "CPIS:119", "recurso_atual": "XPT4", "route": ["CPIS:119"],
                     "segunda_operacao_estado": "ausente", "ordem_codigo": f"OF{i}"} for i in range(25)], "events": []}
    row = {"setor": "MTG3", "fase": "principal", "operacao_codigo": "CPIS:119", "perfil": "L70X70X6", "item_id": "i",
           "ocorrencia": 1, "ordem_codigo": "OF9", "referencia_original": "R", "identidade_tecnica_confirmada": True}
    index = machines.EvidenceIndex(metadata, [row])
    found = {o["resource_code"]: o for o in index.candidates(row, {c: {"id": c, "technical_rules": []} for c in ("XPT4", "PEDDI8", "RAPID")})}
    assert set(found) == {"XPT4", "RAPID"}  # Peddi 8 has no observed 119 practice here
    xp = found["XPT4"]
    assert xp["proposed_code"] == "CPIS:119" and "processo_119_em_puncao_por_confirmar" in xp["conditions"]
    assert "mudanca_112_para_119_requer_decisao" not in xp["conditions"] and xp["origin"] == "pratica_observada"
    assert machines.choose(list(found.values()), None, process="Punção")[0]["resource_code"] == "XPT4"
    assert machines.choose(list(found.values()), None, process="Broca")[0]["resource_code"] == "RAPID"
