"""Planear parte de uma OF (Etapa 3, P5, migração 052, 08/10/2026). Sem base de dados.

Regra única decisions.planned_open (a produção registada depois de planear consome primeiro a parte planeada),
a regra das operações seguintes, e a propagação: Carteira (_summary, filtro Estado, lupa), KPIs (B só a parte),
Carga (cada ocorrência dividida em «no plano» e «a vencer») e Gantt técnico (o saldo limitado à parte).
Invariante: parte planeada + resto = saldo, nos KPIs e na Carga.
"""
import pytest

from app.gantt import integrated
from app.sector import decisions as resolution, load, portfolio, portfolio_kpis, scope
from tests.test_sector_load import TODAY, NOW, _install_world
from tests.test_sector_portfolio import data, raw

P8 = "Peddi 8"


@pytest.fixture(autouse=True)
def following_counts(monkeypatch):
    """A operação seguinte destes testes conta (na MTG3 a 2.ª operação sai do plano; aqui testa-se a regra)."""
    from app.sector import second_operation
    monkeypatch.setattr(second_operation, "operation", lambda sector, fact: False)


def _decisions(**members):
    """Decisões por membro: chave → (quantidade planeada, feito ao planear) ou None (linha inteira)."""
    rows = {}
    for key, quantity in members.items():
        row = {"member_key": key, "decision": "selected", "revision": 1}
        if quantity is not None:
            row.update(planned_quantity=quantity[0], made_at_plan=quantity[1])
        rows[key] = row
    return resolution.Decisions({}, rows)


# --- regra única --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("row,pieces,done,expected", [
    (None, 100, 0, 0),                                                       # sem Planear: nada planeado
    ({"decision": "excluded"}, 100, 0, 0),
    ({"decision": "selected"}, 100, 0, None),                                # linha inteira
    ({"decision": "selected", "planned_quantity": 40, "made_at_plan": 10}, None, None, None),  # saldo por confirmar
    ({"decision": "selected", "planned_quantity": 40, "made_at_plan": 10}, 90, 10, 40),
    ({"decision": "selected", "planned_quantity": 40, "made_at_plan": 10}, 75, 25, 25),         # 15 feitas depois
    ({"decision": "selected", "planned_quantity": 40, "made_at_plan": 10}, 50, 50, 0),          # parte feita
    ({"decision": "selected", "planned_quantity": 40, "made_at_plan": 10}, 30, 70, 0),
    ({"decision": "selected", "planned_quantity": 40, "made_at_plan": 10}, 20, 10, 20),         # QTD baixou: no máximo o saldo
    ({"decision": "selected", "planned_quantity": 40, "made_at_plan": 30}, 90, 10, 40),         # produção corrigida para baixo
])
def test_planned_open_consumes_the_planned_part_first(row, pieces, done, expected):
    assert resolution.planned_open(row, pieces, done) == expected


def test_following_operations_take_the_cut_pieces_still_missing_plus_the_part():
    # principal: min(parte, saldo)
    assert resolution.operation_part(100, 40, 100, True) == 40
    assert resolution.operation_part(30, 40, 30, True) == 30
    # seguinte: já cortadas que lhe faltam (120 − 100 = 20) mais a parte (40) → 60, no máximo o saldo próprio
    assert resolution.operation_part(120, 40, 100, False) == 60
    assert resolution.operation_part(50, 40, 100, False) == 40
    assert resolution.operation_part(30, 40, 100, False) == 30
    # linha inteira ou saldo desconhecido: o saldo todo
    assert resolution.operation_part(120, None, 100, False) == 120
    assert resolution.operation_part(None, 40, 100, False) is None


# --- Carteira ------------------------------------------------------------------------------------------------------

D = data(raw("OF5", "DLT319", 3139, 1660, key="p:1", machine=P8), raw("OF5", "DLT20", 10, 1000, key="p:2", machine=P8),
         raw("OF6", "DLT20", 8, 1000, key="p:3", machine=P8))
PART = _decisions(**{"p:1": (1200, 0), "p:2": None})


def test_summary_splits_the_metres_planned_part_to_planeado_and_the_rest_to_nesting():
    s = portfolio._summary(D["lines"], PART)
    planeado, nesting = s["status"]["planeado"], s["status"]["nesting"]
    assert planeado["lines"] == 2 and planeado["partial_lines"] == 1 and nesting["lines"] == 1  # a parcial conta uma vez
    assert planeado["metres"] == pytest.approx(1200 * 1.66 + 10.0, abs=0.1)
    assert nesting["metres"] == pytest.approx(1939 * 1.66 + 8.0, abs=0.1)
    assert planeado["metres"] + nesting["metres"] == pytest.approx(s["metres"], abs=0.1)
    assert planeado["pieces"] + nesting["pieces"] == s["pieces"] == 3139 + 10 + 8
    assert planeado["pieces"] == 1210 and planeado["ofs"] == 1 and nesting["ofs"] == 2


def test_state_filter_shows_a_partial_line_in_planeado_and_in_its_rest_state():
    planned = portfolio.groups("cantoneiras", "of_perfil", filters={"estado": "planeado"}, data=D, decisions=PART)
    nesting = portfolio.groups("cantoneiras", "of_perfil", filters={"estado": "nesting"}, data=D, decisions=PART)
    assert planned["list_totals"]["lines"] == 2 and nesting["list_totals"]["lines"] == 2  # p:1 nas duas
    assert planned["capabilities"]["parcial"] is True


def test_lupa_shows_planned_and_rest_pieces():
    members = portfolio.members("cantoneiras", "of_perfil", ["OF5", "L45X45X5"], data=D, decisions=PART)
    item = next(x for x in members["items"] if x["key"] == "p:1")
    assert (item["planned_pieces"], item["planned_quantity"], item["rest_pieces"], item["partial"]) == (1200, 1200, 1939, True)
    whole = next(x for x in members["items"] if x["key"] == "p:2")
    assert (whole["planned_pieces"], whole["rest_pieces"], whole["partial"]) == (10, 0, False)
    assert members["parcial"] is True and members["planeado"] == 2


def test_planned_parts_is_the_load_contract():
    assert portfolio.planned_parts(D["lines"], PART) == {"p:1": 1200, "p:2": None}
    assert "p:1" in portfolio.planned_parts(D["lines"], PART)  # `key in ctx['planned']` continua a valer


# --- KPIs ----------------------------------------------------------------------------------------------------------

def _fact(key, line_key, hours, remaining, *, phase="principal", rid="m1", day="2026-10-08"):
    return {"key": key, "line_key": line_key, "of": "OF5", "planning_resource_id": rid, "assigned_resource_id": rid,
            "machine": P8, "machine_basis": "atribuída", "priority_day": day, "load_hours": hours, "phase": phase,
            "remaining": remaining, "pieces": remaining if phase == "principal" else None,
            "metres": remaining * 1.66 if phase == "principal" else None}


FACTS = [_fact("f1", "p:1", 31.39, 3139), _fact("f1b", "p:1", 10.0, 3200, phase="seguinte"),
         _fact("f2", "p:2", 1.0, 10), _fact("f3", "p:3", 0.8, 8)]


def _kpis(decisions):
    occ = {"facts": FACTS, "resources": {"m1": {"id": "m1", "name": P8, "code": "P8"}}, "stamp": "s"}
    return portfolio_kpis.overview("cantoneiras", data=D, decisions=decisions, occurrences_data=occ,
                                   resources_catalog={"P8": {"process": "Punção", "unit": "MTG3", "type": "maquina"}})


def test_kpis_b_takes_only_the_planned_part_and_part_plus_rest_is_the_balance():
    whole = _kpis(_decisions(**{"p:1": None, "p:2": None}))
    part = _kpis(PART)
    machine = lambda result: next(m for p in result["panels"] for m in p["machines"] if m["id"] == "m1")["base"]
    # Parte: 1200 de 3139 na principal (12 h); a seguinte leva 61 já cortadas + 1200 = 1261 de 3200 → 3,94 h; mais p:2.
    assert machine(part)["hours"] == pytest.approx(12.0 + 10.0 * 1261 / 3200 + 1.0, abs=0.1)
    assert machine(part)["metres"] == pytest.approx(1200 * 1.66 + 10.0, abs=0.1)
    assert machine(whole)["hours"] == pytest.approx(31.39 + 10.0 + 1.0, abs=0.1)
    rows = {r["code"]: r for r in part["summary"]}
    total = sum(r["hours"] for r in rows.values())
    assert total == pytest.approx(31.39 + 10.0 + 1.0 + 0.8, abs=0.1)  # Σ parte + resto = saldo (horas)
    assert rows["planeado"]["hours"] == pytest.approx(machine(part)["hours"], abs=0.1)
    assert rows["planeado"]["lines"] == 2 and rows["nesting"]["lines"] == 1
    assert rows["planeado"]["pieces"] + rows["nesting"]["pieces"] == 3139 + 10 + 8


def test_preview_puts_the_rest_of_a_partial_line_in_the_delta():
    occ = {"facts": FACTS, "resources": {"m1": {"id": "m1", "name": P8, "code": "P8"}}, "stamp": "s"}
    result = portfolio_kpis.preview({"setor": "cantoneiras", "chaves": ["p:1"]}, data=D, decisions=PART, occurrences_data=occ,
                                    resources_catalog={})
    assert result["already_planned"]["hours"] + result["delta"]["m1"]["hours"] == pytest.approx(41.39, abs=0.1)
    assert result["already_planned"]["hours"] == pytest.approx(12.0 + 10.0 * 1261 / 3200, abs=0.1)


# --- Carga ---------------------------------------------------------------------------------------------------------

def _carga(monkeypatch, planned):
    lines = [{"key": x["key"], "pieces": x["pieces"], "metres": x["metres"], "weight_unit": None} for x in D["lines"]]
    _install_world(monkeypatch, FACTS, lines=lines)
    monkeypatch.setattr(load, "_context", lambda sector, today=None: ({"lines": lines}, planned, {"facts": FACTS}))
    return load._aggregate("cantoneiras", TODAY)


def test_load_splits_each_planned_fact_into_plan_and_due(monkeypatch):
    agg = _carga(monkeypatch, {"p:1": 1200, "p:2": None})
    cell = agg["cells"][("m1", 2026, 41)]
    principal, following = 31.39 * 1200 / 3139, 10.0 * 1261 / 3200
    assert cell["plan"] == pytest.approx(principal + following + 1.0, abs=0.01)
    assert cell["due"] == pytest.approx(31.39 - principal + 10.0 - following + 0.8, abs=0.01)
    assert cell["plan"] + cell["due"] == pytest.approx(31.39 + 10.0 + 1.0 + 0.8, abs=0.01)  # Σ parte + resto = saldo
    assert cell["operations"] == 4  # a operação dividida conta uma vez
    assert cell["metres"] == pytest.approx((3139 + 10 + 8) * 1.66, abs=0.1)
    total = agg["totals"]["m1"]
    assert total["operations"] == 4 and total["pieces"] == pytest.approx(3139 + 10 + 8)


def test_load_with_a_set_is_the_old_contract_whole_lines(monkeypatch):
    agg = _carga(monkeypatch, {"p:1", "p:2"})
    cell = agg["cells"][("m1", 2026, 41)]
    assert cell["plan"] == pytest.approx(31.39 + 10.0 + 1.0) and cell["due"] == pytest.approx(0.8)


def test_cell_and_operations_say_planned_x_of_y(monkeypatch):
    from app.sector import load_sources
    _carga(monkeypatch, {"p:1": 1200, "p:2": None})
    monkeypatch.setattr(load_sources, "proofs", lambda c, sector, keys: {})
    detail = load.cell("cantoneiras", "m1", 2026, 41, today=TODAY)
    order = next(o for o in detail["orders"] if o["of"] == "OF5")
    assert order["planned_text"] == "planeado 1 200 de 3 139"
    assert order["operations"] == 4 and order["pieces"] == 3139 + 10 + 8
    ops = load.operations("cantoneiras", "m1", 2026, 41, "OF5", today=TODAY)["operations"]
    planned = [o for o in ops if o.get("planned_text")]
    assert [o["planned_text"] for o in planned if o["phase"] == "principal"] == ["planeado 1 200 de 3 139"]
    assert {o["kind"] for o in ops if o.get("part") == "rest"} == {"a vencer"}


def test_consumed_part_brings_the_line_back_to_nesting_without_writing():
    later = data(raw("OF5", "DLT319", 3139, 1660, key="p:1", machine=P8, made=1200))
    assert portfolio.planned_parts(later["lines"], PART) == {}
    assert portfolio.status_of(later["lines"][0], PART) == {"planeado": False, "nesting": True, "sem_maquina": False}


# --- Gantt técnico ---------------------------------------------------------------------------------------------------

def test_technical_gantt_plans_only_the_planned_part():
    base = {"saldo_confirmado": None, "saldo_documental": 3139, "estado_quantidade": "fonte_unica", "fase": "principal"}
    assert integrated.balance(base)["planning_remaining"] == 3139
    part = {"part": 1200, "principal": 3139}
    assert integrated.balance({**base, "planned_part": part})["planning_remaining"] == 1200
    following = {**base, "fase": "complementar", "saldo_documental": 3200, "planned_part": part}
    assert integrated.balance(following)["planning_remaining"] == 1261


def test_scope_planned_part_uses_the_same_rule():
    record = {"row_key": "p:1", "values_json": {"of": "OF5", "component_ref": "DLT319", "quantity_required": 3139,
                                                 "planning_remaining": 2939}, "detail": {}}
    selection = resolution.Decisions({}, {("cantoneiras", "p:1"): {"member_key": "p:1", "decision": "selected", "revision": 1,
                                                                    "planned_quantity": 1200, "made_at_plan": 0}})
    assert scope.planned_part(selection, "cantoneiras", record) == (True, {"part": 1000, "principal": 2939})
    done = {**record, "values_json": {**record["values_json"], "planning_remaining": 1939}}
    assert scope.planned_part(selection, "cantoneiras", done) == (False, None)  # parte feita: fora do Gantt
    whole = resolution.Decisions({}, {("cantoneiras", "p:1"): {"member_key": "p:1", "decision": "selected", "revision": 1}})
    assert scope.planned_part(whole, "cantoneiras", record) == (True, None)
