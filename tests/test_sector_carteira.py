"""Carteira de 02/10/2026: semanas, vista OF → Perfil, subtotal, estados e KPIs por máquina. Sem base de dados.

Critérios CA01, CA03, CA04, CA08, CA09 e CA10 do plano docs/plano-carteira-perfis-2026-10-02.
"""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.sector import decisions as resolution, portfolio, portfolio_kpis
from tests.test_sector_portfolio import data, raw

RAPID, PEDDI = "rid-rapid", "rid-peddi"
RESOURCES = {RAPID: {"id": RAPID, "code": "RAPID25", "name": "Ficep Rapid 25T", "type": "maquina"},
             PEDDI: {"id": PEDDI, "code": "PEDDI8", "name": "Peddi 8", "type": "maquina"}}
CATALOG = {"RAPID25": {"process": "Broca", "unit": "MTG3", "type": "maquina"},
           "PEDDI8": {"process": "Punção", "unit": "MTG3", "type": "maquina"}}


def member(key, decision="selected", revision=1):
    return {"member_key": key, "decision": decision, "revision": revision}


def test_weeks_follow_the_iso_year_across_new_year_and_never_invent_dates():
    d = data(raw("OF1", "A", 1, 1000, cut="2026-12-28", key="a"), raw("OF2", "B", 1, 1000, cut="2027-01-04", key="b"),
             raw("OF3", "C", 1, 1000, cut="2027-01-01", key="c"), raw("OF4", "D", 1, 1000, cut=None, key="d"))
    weeks = portfolio.weeks("cantoneiras", data=d)
    assert [w["code"] for w in weeks] == ["2026-W53", "2027-W01", "sem"]  # 01/01/2027 ainda é da S53 de 2026
    assert weeks[0]["label"] == "2026 · S53 · 28/12–03/01" and weeks[-1]["label"] == "Sem semana definida"
    chosen = portfolio.groups("cantoneiras", "of", filters={"semanas": ["2026-W53", "2027-W01"]}, data=d)
    assert chosen["list_totals"]["ofs"] == 3
    assert portfolio.groups("cantoneiras", "of", filters={"semanas": ["sem"]}, data=d)["list_totals"]["ofs"] == 1


def test_of_then_profile_view_reconciles_with_members_and_counts_distinct_orders():
    l60 = {**raw("OF1", "B", 5, 2000, key="k2"), "v": {**raw("OF1", "B", 5, 2000)["v"], "profile": "L60X60X6"}}
    d = data(raw("OF1", "A", 10, 1000, key="k1"), l60, raw("OF2", "A", 4, 1000, key="k3"))
    top = portfolio.groups("cantoneiras", "of_perfil", data=d)
    assert [g["key"] for g in top["groups"]] == ["OF1", "OF2"] and top["level"]["id"] == "of"
    assert top["list_totals"]["ofs"] == 2 and top["list_totals"]["metres"] == pytest.approx(24.0)
    inner = portfolio.groups("cantoneiras", "of_perfil", ["OF1"], data=d)
    assert {g["key"]: g["metres"] for g in inner["groups"]} == {"L45X45X5": 10.0, "L60X60X6": 10.0}
    assert inner["list_totals"]["ofs"] == 1  # subtotal conta OF distintas, não a soma dos grupos
    m = portfolio.members("cantoneiras", "of_perfil", ["OF1", "L60X60X6"], data=d)
    assert m["total"] == 1 and m["keys"] == ["k2"] and m["items"][0]["metres"] == pytest.approx(10.0)


def test_filters_choose_groups_but_the_member_total_is_the_whole_group():
    d = data(raw("OF1", "A", 10, 1000, key="k1"), raw("OF1", "B", 10, 1000, key="k2", machine="Peddi 8"))
    view = portfolio.groups("cantoneiras", "of_perfil", filters={"maquina": "sem"}, data=d)
    assert view["groups"][0]["lines"] == 1 and view["groups"][0]["member_total"] == 2
    m = portfolio.members("cantoneiras", "of_perfil", ["OF1", "L45X45X5"], filters={"maquina": "sem"}, data=d)
    assert m["total"] == 2 and m["hidden_by_filters"] == 1
    counts = portfolio.counts("cantoneiras", "of_perfil", [], ["k2"], {"maquina": "sem"}, data=d)
    assert counts["groups"]["OF1"] == {"selected": 1, "total": 2, "hidden_selected": 1}


def test_three_states_are_a_partition_and_the_filter_uses_saved_decisions_only():
    d = data(raw("OF1", "A", 10, 1000, key="k1"), raw("OF1", "B", 10, 1000, key="k2", machine="Peddi 8"),
             raw("OF2", "C", 10, 1000, key="k3", machine="Peddi 8"), raw("OF3", "D", 10, 1000, key="k4"))
    decided = resolution.Decisions({("OF2", "*"): {"decision": "selected"}, ("OF3", "*"): {"decision": "selected"}})
    by = lambda estado: sorted(x["key"] for x in d["lines"] if portfolio.matches(x, {"estado": estado}, decided))
    assert by("planeado") == ["k3"]            # Planear + Máquina
    assert by("nesting") == ["k2"]             # Máquina, sem Planear
    assert by("sem_maquina") == ["k1", "k4"]   # sem máquina, mesmo com uma decisão antiga (k4)
    totals = portfolio.groups("cantoneiras", "of", data=d, decisions=decided)["list_totals"]
    assert sum(totals["status"][c]["lines"] for c in portfolio.STATUS) == totals["lines"] == 4
    g = portfolio.groups("cantoneiras", "of", ["OV1"], data=d, decisions=decided)
    of1 = next(x for x in g["groups"] if x["key"] == "OF1")
    assert of1["status"]["nesting"]["lines"] == 1 and of1["lines"] == 2  # grupo misto: não fica todo a verde


def occurrence(key, rid, metres, hours, *, phase="principal", basis="atribuída", machine=None):
    return {"line_key": key, "phase": phase, "metres": metres, "assigned_resource_id": rid,
            "machine": machine or ("Sem máquina" if not rid else RESOURCES[rid]["name"]),
            "machine_basis": basis if rid else "sugerida", "load_hours": hours,
            "suggestion": None if rid else {"machine": "Peddi 8"}}


def world():
    d = data(raw("OF1", "A", 10, 1000, key="k1", machine="Ficep Rapid 25T"),
             raw("OF1", "B", 20, 1000, key="k2", machine="Peddi 8"),
             raw("OF2", "C", 5, 1000, key="k3"))
    facts = [occurrence("k1", RAPID, 10.0, 2.0), occurrence("k1", PEDDI, None, 1.5, phase="seguinte"),
             occurrence("k2", PEDDI, 20.0, None), occurrence("k3", None, 5.0, 0.7)]
    return d, {"facts": facts, "resources": RESOURCES, "stamp": "s1", "stale": False}


def kw(d, occ, decided):
    return {"data": d, "decisions": decided, "occurrences_data": occ, "resources_catalog": CATALOG}


def test_base_counts_planned_work_with_a_machine_once_per_line_and_hours_per_occurrence():
    d, occ = world()
    decided = resolution.Decisions({("OF1", "*"): {"decision": "selected"}})
    k = portfolio_kpis.overview("cantoneiras", **kw(d, occ, decided))
    panels = {p["id"]: {m["name"]: m for m in p["machines"]} for p in k["panels"]}
    assert [p["label"] for p in k["panels"]] == ["Punção", "Broca"] and k["other_machines"] == []
    rapid, peddi = panels["broca"]["Ficep Rapid 25T"], panels["puncao"]["Peddi 8"]
    assert rapid["base"]["metres"] == 10.0 and rapid["base"]["hours"] == 2.0
    # A operação seguinte da k1 dá horas à Peddi 8 sem duplicar metros; a k2 tem horas desconhecidas.
    assert peddi["base"]["metres"] == 20.0 and peddi["base"]["hours"] == 1.5 and peddi["base"]["hours_unknown"] == 1
    summary = {s["code"]: s for s in k["summary"]}
    assert [s["code"] for s in k["summary"]] == ["planeado", "nesting", "sem_maquina"]
    assert summary["planeado"]["metres"] == 30.0 and summary["planeado"]["ofs"] == 1
    assert summary["nesting"]["metres"] == 0
    assert summary["sem_maquina"]["metres"] == 5.0 and summary["sem_maquina"]["hours_unknown"] == 1
    nothing = portfolio_kpis.overview("cantoneiras", **kw(d, occ, resolution.Decisions()))
    assert {s["code"]: s["metres"] for s in nothing["summary"]} == {"planeado": 0, "nesting": 30.0, "sem_maquina": 5.0}


def test_delta_appears_once_is_zero_for_planned_items_and_moves_to_the_base_after_planear():
    d, occ = world()
    nothing = resolution.Decisions()
    preview = portfolio_kpis.preview({"setor": "cantoneiras", "chaves": ["k2", "k2", "k3"]}, **kw(d, occ, nothing))
    assert preview["members"] == 2 and preview["delta"] == {PEDDI: {"name": "Peddi 8", "metres": 20.0, "hours": 0.0,
                                                                     "hours_unknown": 1, "metres_unknown": 0, "lines": 1}}
    assert preview["no_machine"] == {"lines": 1, "metres": 5.0, "metres_unknown": 0}
    before = portfolio_kpis.overview("cantoneiras", **kw(d, occ, nothing))
    planned = resolution.Decisions({}, {"k2": member("k2")})
    after = portfolio_kpis.overview("cantoneiras", **kw(d, occ, planned))
    peddi = lambda k: next(m for p in k["panels"] for m in p["machines"] if m["name"] == "Peddi 8")
    assert peddi(before)["base"]["metres"] == 0 and peddi(after)["base"]["metres"] == 20.0
    again = portfolio_kpis.preview({"setor": "cantoneiras", "chaves": ["k2"]}, **kw(d, occ, planned))
    assert again["delta"] == {} and again["already_planned"]["metres"] == 20.0


def test_machines_outside_the_catalogue_are_shown_by_name_not_classified():
    d = data(raw("OF1", "A", 10, 1000, key="k1", machine="Ficep XP T7"))
    occ = {"facts": [occurrence("k1", None, 10.0, None, machine="Ficep XP T7")], "resources": RESOURCES, "stamp": "s", "stale": False}
    k = portfolio_kpis.overview("cantoneiras", **kw(d, occ, resolution.Decisions({("OF1", "*"): {"decision": "selected"}})))
    assert [(m["name"], m["base"]["metres"]) for m in k["other_machines"]] == [("Ficep XP T7", 10.0)]
    assert {m["name"] for m in next(p for p in k["panels"] if p["id"] == "puncao")["machines"]} == {"Peddi 8"}


@pytest.fixture()
def client(monkeypatch):
    from app.web.planning_app import app
    from app.sector import selection
    monkeypatch.setenv("MES_PLANNING_SELECTION_ENABLED", "1")
    d, occ = world()
    monkeypatch.setattr(portfolio, "load", lambda sector, **k: d)
    from app.sector import machine_choice, machine_learning
    monkeypatch.setattr(machine_choice, "context", lambda area, conn=None: machine_choice.empty(area))
    monkeypatch.setattr(machine_learning, "model", lambda area, **k: None)
    monkeypatch.setattr(selection, "current", lambda sector, conn=None: resolution.Decisions())
    real = portfolio_kpis.context
    monkeypatch.setattr(portfolio_kpis, "context", lambda sector, **k: real(sector, data=d, decisions=resolution.Decisions(),
                                                                            occurrences_data=occ, resources_catalog=CATALOG))
    return TestClient(app)


def test_kpis_ignore_list_filters_and_the_page_has_the_new_controls(client):
    plain = client.get("/planeamento/api/carteira/kpis", params={"setor": "cantoneiras"}).json()
    filtered = client.get("/planeamento/api/carteira/kpis", params={"setor": "cantoneiras", "q": "nada", "estado": "nesting",
                                                                    "maquina": "sem", "semanas": "2026-W40"}).json()
    assert plain == filtered and plain["panels"][0]["label"] == "Punção"
    empty = client.get("/planeamento/api/carteira", params={"setor": "cantoneiras", "q": "não existe"}).json()
    assert empty["list_totals"]["lines"] == 0  # a lista fica vazia; os KPIs acima não mudam
    page = client.get("/planeamento/carteira").text
    for text in ("Família de Produto", "Família SKU", "Limpar filtros", "OF → Perfil", "Prazo", "Ordem", "Planeado",
                 "Planeado para nesting", "Sem máquina atribuída", "Em nesting"):
        assert text in page
    for gone in ("Família da encomenda", ">Sinal", "Planear para", "produção", "Excluir", "Como ler"):
        assert gone not in page
    assert page.index('value="perfil"') < page.index('value="referencia"')  # Perfil é a vista por defeito
    options = client.get("/planeamento/api/carteira/opcoes", params={"setor": "cantoneiras"}).json()
    assert [w["code"] for w in options["weeks"]] == ["2026-W38"]
    members = client.get("/planeamento/api/carteira/membros", params=[("setor", "cantoneiras"), ("vista", "of_perfil"), ("caminho", "OF1"),
                                                                      ("caminho", "L45X45X5")]).json()
    assert members["total"] == 2 and len(members["tokens"]) == 2
    preview = client.post("/planeamento/api/carteira/previsao", json={"setor": "cantoneiras", "chaves_compactas": {"k": ["2"]}}).json()
    assert preview["members"] == 1 and preview["delta"][PEDDI]["metres"] == 20.0
    counts = client.post("/planeamento/api/carteira/contagens", json={"setor": "cantoneiras", "vista": "of", "caminho": [],
                                                                      "chaves": ["k1", "k3"], "filtros": {"q": "OF2"}}).json()
    assert counts["groups"]["OV1"] == {"selected": 2, "total": 3, "hidden_selected": 1}
    assert date.fromisoformat(options["weeks"][0]["start"]) == date(2026, 9, 14)


def test_lupa_and_assign_machine_show_the_machine_planear_writes(client, monkeypatch):
    """Revisão de 07/10: uma só fonte — a «— sugerida» da lupa e a pré-escolha de «Atribuir máquina» são o que o Planear grava."""
    from app.sector import family_sets, selection
    calls = []

    def suggest(sector, lines, allow_stale=False):
        calls.append((sorted(x["key"] for x in lines), allow_stale))
        return {x["key"]: {"resource_id": PEDDI, "machine": "Peddi 8", "origin": "previsao", "label": "Única candidata"}
                for x in lines if not x["machine"]}
    monkeypatch.setattr(selection, "suggested_machines", suggest)
    monkeypatch.setattr(family_sets, "machines", lambda sector, conn=None: [{"id": PEDDI, "name": "Peddi 8"}, {"id": RAPID, "name": "Ficep Rapid 25T"}])
    members = client.get("/planeamento/api/carteira/membros", params=[("setor", "cantoneiras"), ("vista", "of"), ("caminho", "OV1"),
                                                                      ("caminho", "OF2")]).json()
    assert [(i["key"], i["suggested"]["machine"], i["suggested"]["label"]) for i in members["items"]] == [("k3", "Peddi 8", "Única candidata")]
    assert calls == [(["k3"], True)]  # a lupa é uma leitura: pode mostrar a versão anterior enquanto se refaz
    suggestion = client.post("/planeamento/api/carteira/sugestao", json={"setor": "cantoneiras", "chaves": ["k3", "k1"]}).json()
    assert suggestion["suggestion"]["resource_id"] == PEDDI and suggestion["suggestion"]["lines"] == 1 and suggestion["suggestion"]["marked"] == 2


def test_tonnes_use_open_pieces_times_unit_weight_and_unknown_weight_is_not_zero():
    heavy = raw("OF1", "A", 10, 1000, key="k1", machine="Peddi 8", made=4)
    heavy["v"]["weight_unit"] = 25.0  # kg por peça
    d = data(heavy, raw("OF1", "B", 5, 1000, key="k2", machine="Peddi 8"))
    occ = {"facts": [], "resources": RESOURCES, "stamp": "s", "stale": False}
    k = portfolio_kpis.overview("cantoneiras", **kw(d, occ, resolution.Decisions()))
    nesting = next(s for s in k["summary"] if s["code"] == "nesting")
    assert nesting["tonnes"] == pytest.approx(0.15) and nesting["weight_unknown"] == 1  # 6 peças em falta × 25 kg
    totals = portfolio.groups("cantoneiras", "of", data=d)["list_totals"]
    assert totals["tonnes"] == pytest.approx(0.15) and totals["weight_unknown"] == 1
    preview = portfolio_kpis.preview({"setor": "cantoneiras", "chaves": ["k1", "k2"]}, **kw(d, occ, resolution.Decisions()))
    assert preview["to_plan"] == {"lines": 2, "tonnes": 0.15, "weight_unknown": 1}


def machine_ctx(members=None, sets=None):
    from app.sector import machine_choice
    ctx = machine_choice.empty("cantoneiras")
    ctx["members"] = {m["member_key"]: m for m in members or []}
    ctx["sets"] = sets or []
    ctx["family"] = {f: s for s in ctx["sets"] for f in s["families"]}
    ctx["digest"] = repr((members, sets))
    return ctx


def test_effective_machine_order_is_carteira_then_tabela_then_family_set(monkeypatch):
    from app.sector import machine_choice
    rows = [raw("OF1", "ZG-1", 10, 1000, key="k1", machine="Peddi 8"), raw("OF1", "ZG-2", 10, 1000, key="k2"),
            raw("OF1", "DLT9", 10, 1000, key="k3"), raw("OF1", "ZG-3", 10, 1000, key="k4", machine="Por definir")]
    for r, fam in zip(rows, ("ZG", "ZG", "DLT", "ZG")):
        r["v"]["sku_family"] = fam
    d = data(*rows)
    zg = {"id": "s1", "name": "Treliça", "families": ["ZG"], "resource_id": "rid-20t1", "machine_name": "Ficep Rapid 20T -1", "revision": 1}
    ctx = machine_ctx([{"member_key": "k1", "resource_id": "rid-25", "machine_name": "Ficep Rapid 25T", "revision": 1}], [zg])
    monkeypatch.setattr(portfolio, "load", lambda sector, **k: d)
    monkeypatch.setattr(machine_choice, "context", lambda area, conn=None: ctx)
    portfolio._current_cache.clear()
    lines = {x["key"]: x for x in portfolio.current("cantoneiras")["lines"]}
    assert (lines["k1"]["machine"], lines["k1"]["machine_source"]) == ("Ficep Rapid 25T", "carteira")  # Carteira vence a Tabela
    assert (lines["k2"]["machine"], lines["k2"]["machine_source"]) == ("Ficep Rapid 20T -1", "conjunto")
    assert (lines["k3"]["machine"], lines["k3"]["machine_source"]) == ("", None)  # DLT fora do conjunto
    assert (lines["k4"]["machine"], lines["k4"]["machine_source"]) == ("Ficep Rapid 20T -1", "conjunto")  # «Por definir» = sem máquina
    assert lines["k1"]["tabela_machine"] == "Peddi 8"
    # A máquina do conjunto conta: a linha fica em nesting e pode ser planeada.
    assert portfolio.status_of(lines["k2"], resolution.Decisions()) == {"planeado": False, "nesting": True, "sem_maquina": False}
    planned = resolution.Decisions({("OF1", "*"): {"decision": "selected"}})
    assert portfolio.status_of(lines["k2"], planned)["planeado"] and portfolio.status_of(lines["k3"], planned)["sem_maquina"]


def test_learned_preference_uses_the_most_specific_context_with_enough_choices():
    from app.sector import machine_learning
    ident_a, ident_b = ("rid-a", "Ficep Rapid 20T -1"), ("rid-b", "Peddi 8")
    from collections import Counter
    learned = {"weighted": {("familia_perfil", ("ZG", "L100X100X10")): Counter({ident_a: 9, ident_b: 1}),
                            ("familia", ("ZG",)): Counter({ident_b: 50}),
                            ("familia_perfil", ("DLT", "L45X45X4")): Counter({ident_a: 2})},
               "raw": {("familia_perfil", ("ZG", "L100X100X10")): Counter({ident_a: 9, ident_b: 1}),
                       ("familia", ("ZG",)): Counter({ident_b: 50}),
                       ("familia_perfil", ("DLT", "L45X45X4")): Counter({ident_a: 2})}}
    s = machine_learning.suggest(learned, "ZG", "L100x100x10")
    assert s["machine"] == "Ficep Rapid 20T -1" and s["share"] == 0.9 and s["choices"] == 10 and "ZG L100X100X10" in s["label"]
    assert machine_learning.suggest(learned, "ZG", "L200X200X20")["machine"] == "Peddi 8"  # cai para a família
    assert machine_learning.suggest(learned, "DLT", "L45X45X4") is None  # só 2 escolhas: não chega
    assert machine_learning.suggest(None, "ZG", "L100X100X10") is None


def test_sem_perfil_marker_is_not_a_profile_for_learning():
    # Auditoria 06/10 (PROP-8): «Sem perfil» é o marcador de perfil vazio; não pode criar contextos de perfil.
    from app.sector import machine_learning
    assert machine_learning.contexts("D13", "Sem perfil") == [("familia", ("D13",))]
    assert machine_learning.contexts("Sem família SKU", "Sem perfil") == []
    assert ("perfil", ("L45X45X5",)) in machine_learning.contexts("D13", "L45X45X5")


def _apply_world(monkeypatch, candidates):
    """Uma ocorrência sem máquina e uma ficha técnica falsa com as candidatas dadas."""
    from app.gantt import machines
    from app.sector import estimates

    class Index:
        def __init__(self, metadata, rows):
            pass

        def candidates(self, row, codes):
            return [dict(c) for c in candidates]
    monkeypatch.setattr(machines, "EvidenceIndex", Index)
    fact = {"key": "v2:a", "line_key": "k1", "area": "perfis", "phase": "principal", "of": "OF1", "reference": "R1",
            "occurrence": 1, "operation": "LOCAL:PRINCIPAL", "profile": "HEA200", "sku_family": "VIGA",
            "resource_id": None, "assigned_resource_id": None, "assigned_machine": "Sem máquina", "hours": None, "hours_origin": None,
            "late_days": 0, "priority_day": "2026-10-10", "remaining": 10, "length_mm": 1000, "section_unit": 100.0,
            "quantity_required": 10}
    by_id = {"rid-v": {"id": "rid-v", "name": "Vanguard", "code": "VANGUARD"},
             "rid-d": {"id": "rid-d", "name": "Disco", "code": "POSTO_DISCO"}}
    package = {"metadata": {"rates": [{"unidade": "mm2/h", "valor": 100, "recurso_codigo": "VANGUARD"},
                                      {"unidade": "mm2/h", "valor": 100, "recurso_codigo": "POSTO_DISCO"}]}, "rows": []}
    study = {"summary": {}, "speeds": {}, "profile_speeds": {}}
    return estimates, fact, by_id, package, study


def _candidate(rid, code, eligibility="admissible"):
    return {"resource_id": rid, "resource_code": code, "eligibility": eligibility, "proposed_code": "corte",
            "conditions": [], "other_orders": 0, "process": None}


def test_learned_machine_that_the_technical_sheet_excludes_is_not_proposed(monkeypatch):
    # Auditoria 06/10 (PROP-2): a Carteira pré-escolhia a máquina aprendida mesmo excluída pela ficha técnica.
    from app.sector import machine_learning
    from collections import Counter
    estimates, fact, by_id, package, study = _apply_world(monkeypatch, [_candidate("rid-d", "POSTO_DISCO"),
                                                                       _candidate("rid-v", "VANGUARD", "excluded")])
    ident = ("rid-v", "Vanguard")
    learned = {"weighted": {("familia", ("VIGA",)): Counter({ident: 10})}, "raw": {("familia", ("VIGA",)): Counter({ident: 10})}}
    estimates.apply([fact], {"v2:a": {"perfil": "HEA200"}}, codes={}, by_id=by_id, package=package, study=study, learned=learned)
    assert fact["learned_preference"] is None and fact["planning_machine"] == "Disco"
    line = {"key": "k1", "sku_family": "VIGA", "profile": "HEA200"}
    assert machine_learning.for_line(learned, None, line)["machine"] == "Vanguard"  # sem ficha: como antes
    assert machine_learning.for_line(learned, {"k1": fact["learned_preference"]}, line) is None
    assert machine_learning.for_line(learned, {}, line) is None  # linha sem ocorrência principal verificada


def test_profiles_balance_load_with_calendar_hours_when_there_is_no_observed_throughput(monkeypatch):
    # Auditoria 06/10 (PROP-7): a MTG2 não tem débito observado; o equilíbrio usa as horas do calendário.
    estimates, fact, by_id, package, study = _apply_world(monkeypatch, [_candidate("rid-d", "POSTO_DISCO"),
                                                                       _candidate("rid-v", "VANGUARD")])
    busy = {**fact, "key": "v2:b", "line_key": "k2", "of": "OF0", "assigned_resource_id": "rid-d",
            "assigned_machine": "Disco", "hours": 80.0, "hours_origin": "documental"}
    no_calendar = [dict(busy), dict(fact)]
    estimates.apply(no_calendar, {"v2:a": {"perfil": "HEA200"}}, codes={}, by_id=by_id, package=package, study=study)
    assert no_calendar[1]["planning_machine"] == "Disco" and "débito da máquina desconhecido" in no_calendar[1]["suggestion"]["reason"]
    calendar = {"rid-d": {"hours_median": 40.0, "basis": "calendário"}, "rid-v": {"hours_median": 40.0, "basis": "calendário"}}
    balanced = [dict(busy), dict(fact)]
    estimates.apply(balanced, {"v2:a": {"perfil": "HEA200"}}, codes={}, by_id=by_id, package=package, study=study, calendar=calendar)
    assert balanced[1]["planning_machine"] == "Vanguard"  # o Disco já tem 2 semanas de carga
    assert "semanas de calendário" in balanced[1]["suggestion"]["reason"]


def test_preview_alternatives_use_the_same_hours_as_the_portfolio_and_load(monkeypatch):
    # Auditoria 06/10 (PROP-4): a previsão de máquinas mostrava horas do motor do Gantt, diferentes da Carteira.
    from app.sector import assignments
    estimates, fact, by_id, package, study = _apply_world(monkeypatch, [_candidate("rid-d", "POSTO_DISCO"),
                                                                       _candidate("rid-v", "VANGUARD", "excluded")])
    estimates.apply([fact], {"v2:a": {"perfil": "HEA200"}}, codes={}, by_id=by_id, package=package, study=study)
    from app.gantt import machines
    evidence = {"codes": {}, "by_id": by_id, "index": machines.EvidenceIndex(None, None),
                "hours": {"by_id": by_id, "names": {r: {v["name"]} for r, v in by_id.items()}, "study": study,
                          "rates": estimates.area_rates(package["metadata"])}}
    options = {o["name"]: o for o in assignments.alternatives(None, {"_rows": {"v2:a": {"perfil": "HEA200"}}}, fact, evidence)}
    assert options["Disco"]["hours"] == fact["load_hours"] == 10.0  # 10 peças × 100 mm² ÷ 100 mm²/h
    assert options["Vanguard"]["hours"] is None  # excluída pela ficha
