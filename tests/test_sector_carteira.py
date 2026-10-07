"""Carteira de 02/10/2026: semanas, vista OF → Perfil, subtotal, estados e KPIs por máquina. Sem base de dados.

Critérios CA01, CA03, CA04, CA08, CA09 e CA10 do plano docs/plano-carteira-perfis-2026-10-02.
"""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.sector import decisions as resolution, portfolio, portfolio_kpis
from tests.test_sector_portfolio import TODAY, data, raw

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
    # A operação seguinte da k1 é 2.ª operação das cantoneiras (08/10): fora do plano, não soma horas nem
    # desconhecidas e não duplica metros; a k2 tem horas desconhecidas.
    assert peddi["base"]["metres"] == 20.0 and peddi["base"]["hours"] == 0.0 and peddi["base"]["hours_unknown"] == 1
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


def test_kpis_follow_only_the_week_filter(client, monkeypatch):
    """P4 (08/10): o Prazo (semanas) é o único filtro que muda os KPIs; os outros continuam ignorados (GD01)."""
    calls = []

    def week_slice(sector, codes, today):
        calls.append(codes)
        return {"today": TODAY, "current": False, "stale": False,
                "machines": {PEDDI: {"id": PEDDI, "name": "Peddi 8", "load": 3.0, "capacity": 60.0, "plan": 0.0, "due": 3.0,
                                     "suggested": 0.0, "unknown": 1, "operations": 2, "metres": 20.0, "metres_unknown": 0,
                                     "status": "folga", "late_before": None}},
                "kinds": {"plan": {"hours": 0.0, "unknown": 0}, "due": {"hours": 3.0, "unknown": 1}, "suggested": {"hours": 0.7, "unknown": 0}},
                "totals": {"capacity": 60.0, "load": 3.0, "late_before": None, "no_date": 0.0}}
    monkeypatch.setattr(portfolio_kpis, "_week_slice", week_slice)
    url, others = "/planeamento/api/carteira/kpis", [("q", "nada"), ("estado", "nesting"), ("maquina", "sem"), ("familia", "9")]
    plain = client.get(url, params={"setor": "cantoneiras"}).json()
    filtered = client.get(url, params=[("setor", "cantoneiras"), *others]).json()
    assert plain == filtered and plain["panels"][0]["label"] == "Punção" and calls == []
    assert plain["scope"] == {"weeks": [], "label": "todas as semanas", "sector_label": "MTG3 Cantoneiras", "current": False}
    assert "week_totals" not in plain and all("week" not in m for p in plain["panels"] for m in p["machines"])
    week = client.get(url, params=[("setor", "cantoneiras"), ("semanas", "2026-W38")]).json()
    assert week == client.get(url, params=[("setor", "cantoneiras"), ("semanas", "2026-W38"), *others]).json()
    assert calls == [["2026-W38"], ["2026-W38"]]
    assert week["scope"] == {"weeks": ["2026-W38"], "label": "Semana 38 (14/09–20/09)", "sector_label": "MTG3 Cantoneiras", "current": False}
    machines = {m["name"]: m for p in week["panels"] for m in p["machines"]}
    assert machines["Peddi 8"]["week"]["load"] == 3.0 and machines["Peddi 8"]["week"]["capacity"] == 60.0
    assert machines["Ficep Rapid 25T"]["week"] is None and machines["Peddi 8"]["base"] == plain["panels"][0]["machines"][0]["base"]
    summary = {s["code"]: s["week"] for s in week["summary"]}  # metros das linhas da semana; horas por tipo da célula
    assert (summary["nesting"]["metres"], summary["nesting"]["hours"], summary["nesting"]["hours_unknown"]) == (30.0, 3.0, 1)
    assert (summary["sem_maquina"]["metres"], summary["sem_maquina"]["hours"], summary["sem_maquina"]["hours_kind"]) == (5.0, 0.7, "suggested")
    assert week["week_totals"]["capacity"] == 60.0
    bad = client.get(url, params={"setor": "cantoneiras", "semanas": "ontem"})
    assert bad.status_code == 422 and bad.json()["error"] == "Prazo inválido."
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


# --- Avisos e desconhecidos (08/10): F06, F07, F09, F16, F26


def _quiet_notice(monkeypatch, text=None):
    from app.sector import drive_notice
    monkeypatch.setattr(drive_notice, "text", lambda sector: text)


def test_repeated_lines_are_marked_and_counted_once_in_the_subtotal_but_never_removed(monkeypatch):
    """F06: linhas iguais em OF, referência, perfil, comprimento, QTD, material e qualidade contam a dobrar."""
    _quiet_notice(monkeypatch)
    rows = [raw("OF1", "A", 10, 1000, key="k1"), raw("OF1", "A", 10, 1000, key="k2"), raw("OF1", "A", 10, 1500, key="k3")]
    for r in rows:
        r["v"].update(material_type="Chapa", grade="S355J2")
    d = data(*rows)
    portfolio.mark_repeated(d["lines"], [portfolio.repeated_identity(x, r["v"]) for x, r in zip(d["lines"], rows)])
    by = {x["key"]: x for x in d["lines"]}
    assert by["k1"]["repeated"] == by["k2"]["repeated"] == 2 and "repeated" not in by["k3"]
    assert not by["k1"].get("repeat_extra") and by["k2"]["repeat_extra"]  # a cópia a mais é a 2.ª pela chave
    totals = portfolio.groups("cantoneiras", "of", data=d)["list_totals"]
    assert totals["repeated"] == {"lines": 1, "metres": 10.0} and totals["lines"] == 3 and totals["metres"] == 35.0
    m = portfolio.members("cantoneiras", "of", ["OV1", "OF1"], data=d)
    assert {i["key"]: i["repeated"] for i in m["items"]} == {"k1": 2, "k2": 2, "k3": None}
    # Outra qualidade já não é a mesma linha.
    other = [raw("OF1", "A", 10, 1000, key="k1"), raw("OF1", "A", 10, 1000, key="k2")]
    other[1]["v"]["grade"] = "S275"
    o = data(*other)
    portfolio.mark_repeated(o["lines"], [portfolio.repeated_identity(x, r["v"]) for x, r in zip(o["lines"], other)])
    assert not any(x.get("repeated") for x in o["lines"])
    assert portfolio.groups("cantoneiras", "of", data=o)["list_totals"]["repeated"] == {"lines": 0, "metres": 0.0}


def test_production_above_quantity_is_a_warning_also_for_lines_that_left_the_carteira(monkeypatch):
    """F07: produção acima da QTD (OCR k × QTD) — a linha sai com saldo 0, mas o aviso conta-a; nada é corrigido."""
    _quiet_notice(monkeypatch)
    gone = raw("OF2", "B", 12, 1000, made=24, key="gone")
    gone["v"].update(planning_remaining=0, production_excess=12)
    assert portfolio.line_from_row(gone, TODAY) is None
    closed = portfolio.line_from_row(gone, TODAY, keep_done=True)
    assert closed["production_excess"] == 12 and closed["pieces"] == 0
    still = raw("OF2", "C", 5, 1000, made=7, key="still")
    still["v"].update(planning_remaining=0, production_excess=2)
    still["detail"] = {"calculation": {"integrated_operations": [{"operation": "LOCAL:ABOCARDAR", "occurrence": 2, "remaining": 5}]}}
    d = {**data(still, raw("OF3", "D", 5, 1000, key="ok")), "excess_done": [closed]}
    totals = portfolio.groups("cantoneiras", "of", data=d)["list_totals"]
    assert totals["production_excess"] == {"lines": 2, "pieces": 14, "closed": 1}
    assert portfolio.groups("cantoneiras", "of", filters={"q": "OF3"}, data=d)["list_totals"]["production_excess"]["lines"] == 0
    [item] = portfolio.members("cantoneiras", "of", ["OV1", "OF2"], data=d)["items"]
    assert item["production_excess"] == 2


def test_only_the_following_operation_left_shows_its_balance_not_zero_pieces():
    """F09: só falta o abocardar ou a 2.ª operação → «Abocardar: 5» / «2.ª op.: N», e 0 kg por cortar."""
    r = raw("OF1", "A", 5, 1000, made=5, key="k")
    r["v"]["planning_remaining"] = 0
    r["detail"] = {"calculation": {"integrated_operations": [
        {"operation": "LOCAL:ABOCARDAR", "occurrence": 2, "remaining": 5}, {"operation": "CPIS:111", "occurrence": 3, "remaining": None}]}}
    line = portfolio.line_from_row(r, TODAY)
    assert line["following"] == [{"label": "Abocardar", "remaining": 5}, {"label": "2.ª op.", "remaining": None}]
    assert line["kg"] == 0.0 and line["metres"] == 0.0 and not line["metres_unknown"]
    view = portfolio.member_view(line, {})
    assert view["following"] == line["following"] and view["pieces"] == 0
    # Linha com corte por fazer: sem «following».
    assert "following" not in portfolio.line_from_row(raw("OF1", "B", 5, 1000), TODAY)


def test_unknown_metres_are_none_on_screen_and_counted_apart(monkeypatch):
    """F09: sem comprimento ou sem saldo, os metros são «—» na lupa e contam à parte no Subtotal."""
    _quiet_notice(monkeypatch)
    d = data(raw("OF1", "A", 10, None, key="nolen"), raw("OF1", "B", 24, 1500, made=4, mes=10, key="nobal"), raw("OF1", "C", 2, 1000, key="ok"))
    by = {x["key"]: x for x in d["lines"]}
    assert by["nolen"]["metres_unknown"] and by["nobal"]["metres_unknown"] and not by["ok"]["metres_unknown"]
    assert portfolio.member_view(by["nolen"], {})["metres"] is None and portfolio.member_view(by["ok"], {})["metres"] == 2.0
    totals = portfolio.groups("cantoneiras", "of", data=d)["list_totals"]
    assert totals["metres"] == 2.0 and totals["metres_unknown"] == 2
    summary = {s["code"]: s for s in portfolio_kpis.overview("cantoneiras", data=d, decisions={},
                                                              occurrences_data={"facts": [], "resources": RESOURCES}, resources_catalog=CATALOG)["summary"]}
    assert summary["sem_maquina"]["metres"] == 2.0 and summary["sem_maquina"]["metres_unknown"] == 2


def test_no_family_has_one_label_in_the_carteira_and_the_occurrences():
    """F26: «Sem família (OF fora do CPIS)» nos dois (antes «Sem família CPIS» nos factos)."""
    from app.sector import occurrences
    line = portfolio.line_from_row(raw("OF1", "A", 1, 1000, family=None), TODAY)
    assert line["family"] == occurrences.NO_CPIS_FAMILY == "Sem família (OF fora do CPIS)"


def test_newer_excel_on_drive_is_one_line_on_top_of_the_carteira(monkeypatch):
    """F16: a Carteira, a Carga e o Gantt simples dizem quando há um Excel mais recente no Drive por importar."""
    from app.sector import drive_notice
    status = {"sources": [
        {"area": "cantoneiras", "newer_available": True, "newer_folder": "SAIDA",
         "drive": {"remote_modified_at": "2026-10-07T12:20:31.123456789Z"}, "imported": {"loaded_at": "2026-10-02T07:15:00+00:00"}},
        {"area": "perfis", "newer_available": False, "newer_folder": None, "drive": {}, "imported": {}}]}
    calls = []
    monkeypatch.setattr(drive_notice, "_status", lambda: calls.append(1) or status)
    drive_notice.clear()
    text = "O Excel de MTG3 Cantoneiras no Drive é mais recente (07/10 13:20, pasta SAIDA) do que o importado (02/10 08:15)."
    assert drive_notice.text("cantoneiras") == text and drive_notice.text("perfis") is None and len(calls) == 1  # 60 s em memória
    d = data(raw("OF1", "A", 1, 1000))
    assert portfolio.groups("cantoneiras", "of", data=d)["source_notice"] == text
    assert portfolio.groups("cantoneiras", "of", ["OV1"], data=d)["source_notice"] is None  # só no nível de cima
    # Sem pasta (a raiz é a mais recente) e sem data importada.
    assert drive_notice.notice_of({"area": "perfis", "newer_available": True, "drive": {}, "imported": {}}) == \
        "O Excel de MTG2 Perfis no Drive é mais recente do que o importado."
    # Uma base indisponível dá None, sem rebentar a página.
    monkeypatch.setattr(drive_notice, "_status", lambda: (_ for _ in ()).throw(RuntimeError("sem base")))
    drive_notice.clear()
    assert drive_notice.text("cantoneiras") is None
    drive_notice.clear()


# --- Ordem por data (P6, 08/10): grupos pela data mais antiga com saldo; a lupa segue a mesma ordem.


def _row(of, ref, *, cut, quantity=10, length=1000, key=None, raw_w=None, galvanizing=None, picking=None, area="cantoneiras", made=0):
    r = raw(of, ref, quantity, length, cut=cut, key=key or f"k-{of}-{ref}", made=made)
    r["detail"] = {"area": area, "raw": {k: v for k, v in (("W", raw_w), ("Data Galvanização", galvanizing)) if v}}
    if picking:
        r["v"]["picking_week"], r["v"]["picking_year"] = picking
    return r


def _sector_data(area, *rows):
    return {**data(*rows), "sector": area}


def test_cut_date_order_puts_the_oldest_late_group_first_then_future_without_date_and_parked(monkeypatch):
    _quiet_notice(monkeypatch)
    closed = _row("OF5", "OLD", cut="2026-01-01", made=10)
    closed["v"]["planning_remaining"] = 0
    closed["detail"]["calculation"] = {"integrated_operations": [{"operation": "CPIS:111", "occurrence": 2, "remaining": 5}]}
    d = data(_row("OF1", "A", cut="2026-07-20"), _row("OF1", "B", cut="2026-10-05"),
             _row("OF2", "A", cut="2026-10-02"), _row("OF3", "A", cut="2026-07-01"),
             _row("OF4", "A", cut=None), _row("OF6", "A", cut="2026-03-02", raw_w="2026/53"),
             closed, _row("OF5", "NEW", cut="2026-10-10"),
             _row("OF7", "P", cut="2026-03-01", raw_w="2026/53"), _row("OF7", "Q", cut="2026-10-20"))
    view = portfolio.groups("cantoneiras", "of_perfil", sort="corte", data=d)
    assert [g["key"] for g in view["groups"]] == ["OF3", "OF1", "OF2", "OF5", "OF7", "OF4", "OF6"]
    assert view["order"] == "corte" and view["capabilities"] == {"ordem_data": True}
    tags = {g["key"]: g["due_tag"] for g in view["groups"]}
    assert tags["OF1"] == {"day": date(2026, 7, 20), "field": "cut_date", "late": True, "late_days": 70, "provisional": False}
    assert tags["OF2"]["late"] is False and tags["OF2"]["late_days"] == 0 and "week" not in tags["OF2"]
    assert tags["OF5"]["day"] == date(2026, 10, 10)    # a linha já cortada (só falta a 2.ª operação) não conta
    assert tags["OF7"]["day"] == date(2026, 10, 20)    # a estacionada não conta; o grupo não é «só estacionadas»
    assert tags["OF4"] == {"none": "sem data"} and tags["OF6"] == {"none": "estacionada"}
    # Grupo já todo cortado (só falta a 2.ª operação): fica pela data das suas linhas, não vai para «sem data».
    only_closed = data(_row("OF1", "A", cut="2026-10-02"), {**closed, "row_key": "k-closed"})
    view = portfolio.groups("cantoneiras", "of_perfil", sort="corte", data=only_closed)
    assert [(g["key"], g["due_tag"]["day"]) for g in view["groups"]] == [("OF5", date(2026, 1, 1)), ("OF1", date(2026, 10, 2))]
    # Data igual: mais metros primeiro, depois a chave.
    tie = data(_row("OF1", "A", cut="2026-10-01"), _row("OF2", "A", cut="2026-10-01", quantity=30), _row("OF3", "A", cut="2026-10-01"))
    assert [g["key"] for g in portfolio.groups("cantoneiras", "of_perfil", sort="corte", data=tie)["groups"]] == ["OF2", "OF1", "OF3"]
    # As outras ordens não trazem etiqueta e a de picking não existe na MTG3.
    assert "due_tag" not in portfolio.groups("cantoneiras", "of_perfil", sort="urgencia", data=d)["groups"][0]
    with pytest.raises(portfolio.planning.PlanningError, match="Ordem inválida"):
        portfolio.groups("cantoneiras", "of_perfil", sort="picking", data=d)
    assert portfolio.orders("cantoneiras") == ("corte", "urgencia", "metros") and portfolio.default_order("cantoneiras") == "corte"
    assert portfolio.orders("perfis")[:2] == ("corte", "picking") and portfolio.default_order("perfis") == "picking"


def test_picking_order_with_deduced_year_and_profiles_without_picking_by_the_policy_deadline(monkeypatch):
    _quiet_notice(monkeypatch)
    rows = [_row("P1", "A", cut="2026-10-20", picking=(41, 2026), area="perfis"),
            _row("P2", "A", cut="2026-09-30", picking=(40, None), area="perfis"),          # ano deduzido
            _row("P3", "A", cut="2026-10-20", picking=(38, 2026), area="perfis"),
            # Sem Picking: o prazo da política (Galvanização 01/10) e não a Data Corte crua (01/09).
            _row("P4", "A", cut="2026-09-01", galvanizing="2026-10-01", area="perfis"),
            _row("P5", "A", cut="2026-09-10", area="perfis"),
            _row("P6", "A", cut=None, area="perfis")]
    d = _sector_data("perfis", *rows)
    line = {x["of"]: x for x in d["lines"]}
    assert line["P2"]["picking_day"] == date(2026, 9, 28) and line["P2"]["picking_provisional"]
    assert line["P1"]["picking_day"] == date(2026, 10, 5) and not line["P1"]["picking_provisional"]
    view = portfolio.groups("perfis", "of_perfil", sort="picking", data=d)
    assert [g["key"] for g in view["groups"]] == ["P3", "P2", "P1", "P5", "P4", "P6"]
    tags = {g["key"]: g["due_tag"] for g in view["groups"]}
    assert tags["P2"] == {"day": date(2026, 9, 28), "field": "picking", "late": False, "late_days": 0, "provisional": True, "week": "2026-W40"}
    assert tags["P3"]["late"] and tags["P3"]["late_days"] == 14 and tags["P3"]["week"] == "2026-W38"
    assert tags["P4"]["field"] == "galvanizing" and tags["P4"]["day"] == date(2026, 10, 1) and "week" not in tags["P4"]
    assert tags["P5"]["field"] == "cut_date" and tags["P6"] == {"none": "sem data"}
    # A data com o ano confirmado numa linha confirma o grupo: deixa de ser «S40?».
    both = _sector_data("perfis", _row("P2", "A", cut="2026-09-30", picking=(40, None), area="perfis"),
                        _row("P2", "B", cut="2026-09-30", picking=(40, 2026), area="perfis"))
    assert portfolio.groups("perfis", "of_perfil", sort="picking", data=both)["groups"][0]["due_tag"]["provisional"] is False
    # Pela data de corte, os perfis seguem a Data Corte.
    assert [g["key"] for g in portfolio.groups("perfis", "of_perfil", sort="corte", data=d)["groups"]][:3] == ["P4", "P5", "P2"]


def test_zero_metre_group_is_ranked_by_its_lines_not_sent_to_the_end(monkeypatch):
    """F10: um grupo de 0 m (sem comprimento) atrasado ia para o fim na «Mais urgente primeiro»."""
    _quiet_notice(monkeypatch)
    d = data(_row("OF1", "A", cut="2026-10-10"), _row("OF2", "A", cut="2026-09-01", length=None), _row("OF3", "A", cut=None))
    urgent = portfolio.groups("cantoneiras", "of_perfil", sort="urgencia", data=d)["groups"]
    assert [g["key"] for g in urgent] == ["OF2", "OF1", "OF3"] and urgent[0]["metres"] == 0
    assert urgent[0]["window_lines"]["atrasado"] == 1
    by_cut = portfolio.groups("cantoneiras", "of_perfil", sort="corte", data=d)["groups"]
    assert [g["key"] for g in by_cut] == ["OF2", "OF1", "OF3"] and by_cut[0]["due_tag"]["late_days"] == 27


def test_lupa_follows_the_date_order_of_the_list():
    d = data(_row("OF1", "C", cut="2026-10-10", key="k-late-2"), _row("OF1", "A", cut=None, key="k-nodate"),
             _row("OF1", "B", cut="2026-08-01", key="k-late-1"), _row("OF1", "D", cut="2026-03-01", raw_w="2026/53", key="k-parked"))
    path = ["OF1", "L45X45X5"]
    by_cut = portfolio.members("cantoneiras", "of_perfil", path, data=d, sort="corte")
    assert [i["key"] for i in by_cut["items"]] == ["k-late-1", "k-late-2", "k-nodate", "k-parked"] and by_cut["order"] == "corte"
    assert by_cut["keys"] == [i["key"] for i in by_cut["items"]]
    assert [i["reference"] for i in portfolio.members("cantoneiras", "of_perfil", path, data=d)["items"]] == ["A", "B", "C", "D"]
    with pytest.raises(portfolio.planning.PlanningError):
        portfolio.members("cantoneiras", "of_perfil", path, data=d, sort="picking")


def test_api_echoes_the_order_and_the_lupa_receives_it(client, monkeypatch):
    _quiet_notice(monkeypatch)
    body = client.get("/planeamento/api/carteira", params={"setor": "cantoneiras", "vista": "of_perfil", "ordem": "corte"}).json()
    assert body["order"] == "corte" and body["capabilities"]["ordem_data"] is True
    assert body["groups"][0]["due_tag"]["field"] == "cut_date" and body["groups"][0]["due_tag"]["day"] == "2026-09-20"
    assert client.get("/planeamento/api/carteira", params={"setor": "cantoneiras"}).json()["order"] == "urgencia"
    wrong = client.get("/planeamento/api/carteira", params={"setor": "cantoneiras", "ordem": "picking"})
    assert wrong.status_code == 422 and wrong.json()["error"] == "Ordem inválida."
    members = client.get("/planeamento/api/carteira/membros", params=[("setor", "cantoneiras"), ("vista", "of_perfil"), ("caminho", "OF1"),
                                                                      ("caminho", "L45X45X5"), ("ordem", "corte")]).json()
    assert members["order"] == "corte" and members["total"] == 2
    page = client.get("/planeamento/carteira").text
    assert "/static/tabela_fixa.js?v=" in page and 'id="cart-table"' in page and "planeamento_ui.css?v=20261008" in page
    assert '<option value="corte">Data de corte mais próxima</option>' in page
