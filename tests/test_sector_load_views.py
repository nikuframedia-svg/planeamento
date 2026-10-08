"""Vistas da Carga por setor, perfil e família (P10, 08/10/2026): somam o mesmo que as máquinas. Sem base de dados."""
from contextlib import contextmanager
from datetime import date, datetime, timezone

import pytest

from app.sector import load, load_views, settings as sector_settings

TODAY = date(2026, 10, 6)  # terça-feira; a semana ISO 41 começa a 05/10 (feriado)
NOW = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
MACHINES = [{"id": "m1", "name": "Peddi 8", "code": "P8", "process": "Punção", "default_shifts": 2},
            {"id": "m2", "name": "XP T4", "code": "XP4", "process": "Punção", "default_shifts": 2},
            {"id": "m3", "name": "Sem turnos", "code": "ST", "process": "Broca", "default_shifts": 0}]


def fact(key, rid, day, hours, *, profile="Cantoneira · L45X45X5", family="1 Postes Treliçados", sku="DLT",
         phase="principal", metres=10.0, pieces=4, basis="atribuída", of="OF1"):
    return {"key": key, "line_key": "L" + key, "of": of, "customer": "Cliente", "planning_resource_id": rid,
            "planning_machine": rid, "machine_basis": basis, "priority_day": day, "load_hours": hours, "phase": phase,
            "profile": profile.split(" · ")[-1], "material_type": profile.split(" · ")[0], "profile_group": profile,
            "cpis_family": family, "sku_family": sku, "section_unit": None,
            "metres": metres if phase == "principal" else None, "pieces": pieces if phase == "principal" else None,
            "remaining": pieces, "late_days": 0}


WORLD = [
    fact("old", "m1", "2026-09-30", 30.0, profile="Cantoneira · L60X60X6", family="6.2 Tel Treliçados Cant", sku="M"),
    fact("old2", "m2", "2026-09-21", None, sku="M"),                      # atrasado sem horas
    fact("mon", "m1", "2026-10-05", 4.0),                                 # segunda (ontem): semana atual, atrasado
    fact("now", "m2", "2026-10-08", 6.0, profile="Cantoneira · L60X60X6"),
    fact("now2", "m2", "2026-10-09", 2.5, phase="seguinte", sku="ED4"),
    fact("next", "m1", "2026-10-14", 5.0, family="Sem família (OF fora do CPIS)", basis="sugerida"),
    fact("next2", "m1", "2026-10-15", None, metres=None, pieces=None),    # sem horas nem saldo
    fact("w44", "m3", "2026-10-28", 7.0, sku="ZD"),                        # máquina sem calendário: entra na soma
    fact("nodate", "m1", None, 3.0, profile="Cantoneira · L70X70X7"),
    fact("far", "m2", "2027-06-01", 7.0, family="6.2 Tel Treliçados Cant"),
    fact("nomachine", None, "2026-10-08", 9.0),                           # sem máquina: fora, como na grelha
    fact("other", "x9", "2026-10-08", 11.0),                              # máquina de outro setor: fora
]


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


@pytest.fixture
def world(monkeypatch):
    """overview() e as vistas sobre o mesmo mundo: m1 e m2 com calendário (2 turnos seg–sex), m3 sem calendário."""
    from app.sector import drive_notice, load_sources, shifts
    settings = sector_settings.default(TODAY)
    plan = {str(d): (2 if d <= 5 else 0) for d in range(1, 8)}
    calendars = [{"definition": shifts.definition_for(m["id"], y, w, plan, {}, settings, manual=False)}
                 for m in MACHINES[:2] for y, w in load.week_list(TODAY)]
    state = {"facts": list(WORLD), "posts": {}, "lines": [{"key": "L" + f["key"], "weight_unit": 2.0} for f in WORLD],
             "overviews": 0}

    class Conn:
        def execute(self, sql, params=None):
            return _Rows(calendars if "kind='calendar'" in sql else [])

    @contextmanager
    def connect(readonly=True):
        yield Conn()

    real_overview = load.overview

    def overview(sector, **kw):
        state["overviews"] += 1
        return real_overview(sector, **kw)

    monkeypatch.setattr(load.planning, "connect", connect)
    monkeypatch.setattr(load, "_context", lambda sector, today=None: (
        {"lines": state["lines"]}, {"Lnow"}, {"facts": state["facts"], "stamp": state.get("stamp")}))
    monkeypatch.setattr(load, "overview", overview)
    monkeypatch.setattr(sector_settings, "read", lambda c, sector: settings)
    monkeypatch.setattr(sector_settings, "machine_rows", lambda c, sector: MACHINES)
    monkeypatch.setattr(load_sources, "context", lambda c, sector: {"lines": {}, "actual": {}, "posts": state["posts"],
                                                                    "names": {m["id"]: m["name"] for m in MACHINES}})
    monkeypatch.setattr(load_sources, "fact_values", lambda f, lines: (None, None, False))
    monkeypatch.setattr(drive_notice, "text", lambda sector: None)
    # Mundo sem a 2.ª operação, nas vistas e na grelha (a junção com P3 pôs a grelha a tirá-la; as duas iguais).
    from app.sector import second_operation
    monkeypatch.setattr(load_views, "_second", None)
    monkeypatch.setattr(second_operation, "operation", lambda sector, fact: False)
    load_views._cache.clear()
    yield state
    load_views._cache.clear()


def _view(por, unit="h", sector="cantoneiras"):
    return load_views.view(sector, por, unit, today=TODAY, now=NOW)


def _columns(view):
    """Somas por coluna das linhas de uma vista: Atrasado, 13 semanas, Sem prazo, Mais tarde (valor e desconhecidas)."""
    cols = [[r["late_before"]] + r["weeks"] + [r["no_date"], r["after"]] for r in view["rows"]]
    return [(round(sum(c[i]["value"] for c in cols), 1), sum(c[i]["unknown"] for c in cols)) for i in range(16)]


def test_every_view_sums_week_by_week_to_the_machines_of_the_load(world):
    """Σ por perfil = Σ por família = Σ por família SKU = Σ por setor = Σ por máquina, semana a semana, e = load.overview."""
    over = load.overview("cantoneiras", today=TODAY, now=NOW)
    rows = over["machines"]
    machines = [(round(sum(m["late_before"]["hours"] for m in rows), 1), sum(m["late_before"]["unknown"] for m in rows))]
    machines += [(round(sum(m["weeks"][i]["load"] for m in rows), 1), sum(m["weeks"][i]["unknown"] for m in rows)) for i in range(13)]
    machines += [(round(sum(m["no_date"]["hours"] for m in rows), 1), sum(m["no_date"]["unknown"] for m in rows)),
                 (round(sum(m["after"] for m in rows), 1), None)]
    views = {por: _view(por) for por in ("perfil", "familia", "familia_sku")}
    setor = _view("setor")
    views["setor"] = {**setor, "rows": [r for r in setor["rows"] if r["key"] == "cantoneiras"]}
    for por, v in views.items():
        cols = _columns(v)
        assert [c[0] for c in cols] == [c[0] for c in machines], por
        assert [c[1] for c in cols[:-1]] == [c[1] for c in machines[:-1]], por  # «Mais tarde» das máquinas não traz as desconhecidas
        total = v["total"] if por != "setor" else None
        if total:
            assert [total["late_before"]["value"], *[w["value"] for w in total["weeks"]], total["no_date"]["value"],
                    total["after"]["value"]] == [c[0] for c in cols], por
    # Os totais de load.overview (máquinas do setor): horas e desconhecidas.
    totals = [t for t in over["totals"] if t["id"]]
    assert views["perfil"]["total"]["total"]["value"] == round(sum(t["load"] for t in totals), 1) == 64.5
    assert views["perfil"]["total"]["total"]["unknown"] == sum(t["unknown"] for t in totals) == 2
    assert views["perfil"]["outside"] == 2  # sem máquina e máquina de outro setor
    assert [w["value"] for w in views["perfil"]["total"]["weeks"][:3]] == [12.5, 5.0, 0.0]
    assert views["perfil"]["total"]["late_before"] == {"value": 30.0, "unknown": 1, "operations": 2}


def test_rows_are_sorted_by_total_with_a_dimension_for_profiles(world):
    v = _view("perfil")
    assert [r["key"] for r in v["rows"]] == ["Cantoneira · L60X60X6", "Cantoneira · L45X45X5", "Cantoneira · L70X70X7"]
    assert [r["total"]["value"] for r in v["rows"]] == [36.0, 25.5, 3.0]
    assert v["rows"][0]["dimension"] == {"aba": 60.0, "aba2": 60.0, "esp": 6.0}
    assert v["text"] == "Horas do trabalho aberto na semana do prazo (como na Carteira)." and v["note"] is None
    fam = _view("familia")
    assert fam["note"] == load_views.FAMILY_NOTE and [r["key"] for r in fam["rows"]] == ["6.2 Tel Treliçados Cant", "1 Postes Treliçados", "Sem família (OF fora do CPIS)"]


def test_metres_and_pieces_only_from_the_main_operation_and_unknowns_apart(world):
    v = _view("perfil", "m")
    assert v["unit"] == "m" and v["text"].startswith("Metros do trabalho aberto")
    l45 = next(r for r in v["rows"] if r["key"] == "Cantoneira · L45X45X5")
    # old2, mon, next, w44 e far (10 m cada) + next2 (metros por saber); now2 é seguinte: não conta nem é desconhecida.
    assert l45["total"] == {"value": 50.0, "unknown": 1, "operations": 7}
    pieces = _view("perfil", "pecas")
    assert next(r for r in pieces["rows"] if r["key"] == "Cantoneira · L45X45X5")["total"]["value"] == 20.0
    # Setores fica só em horas (P4: sem alternador): um pedido de metros ou kg devolve horas.
    setor = _view("setor", "m")
    assert setor["unit"] == "h" and setor["units"] == ["h"] and _view("setor", "kg")["unit"] == "h"
    with pytest.raises(load.planning.PlanningError):
        _view("perfil", "toneladas")
    with pytest.raises(load.planning.PlanningError):
        _view("maquina")


def test_sectors_have_capacity_counted_once_for_a_post(world):
    """Setores: capacidade da semana inteira das máquinas com calendário; % = carga ÷ capacidade."""
    v = _view("setor")
    assert {r["key"] for r in v["rows"]} == {"perfis", "cantoneiras"}
    row = next(r for r in v["rows"] if r["key"] == "cantoneiras")
    over = load.overview("cantoneiras", today=TODAY, now=NOW)
    caps = [round(sum(m["weeks"][i]["full_capacity"] for m in over["machines"] if m["has_calendar"]), 1) for i in range(13)]
    assert [w["capacity"] for w in row["weeks"]] == caps and caps[0] == 120.0
    assert row["weeks"][0]["pct"] == round(100 * 12.5 / 120.0)
    assert "capacity" not in row["late_before"] and v["total"]["label"] == "Total"
    # Com o posto: m1 é um posto que contém m2 → a capacidade de m2 não se soma (capacity.counted).
    load_views._cache.clear()
    world["posts"] = {"m1": ["m2"]}
    v = _view("setor")
    row = next(r for r in v["rows"] if r["key"] == "cantoneiras")
    assert row["weeks"][1]["capacity"] == 75.0
    assert v["note"] == "Peddi 8 é um posto com XP T4: conta uma vez."


def test_sector_capacity_is_a_pure_sum_without_double_counting():
    def row(rid, caps, calendar=True):
        return {"id": rid, "has_calendar": calendar, "weeks": [{"full_capacity": c, "status": "folga"} for c in caps]}
    rows = [row("fita", [60.0, 75.0]), row("doall", [30.0, 37.5]), row("vanguard", [90.0, 112.5]), row("abocardar", [0.0, 0.0], False)]
    caps, merged = load_views.sector_capacity(rows, {"fita": ["doall", "thomas"], "disco": ["a", "b"]})
    assert caps == [150.0, 187.5] and merged == ["fita"]
    assert load_views.sector_capacity(rows, {}) == ([180.0, 225.0], [])
    assert load_views.sector_capacity([row("x", [None], False)], {}) == ([None], [])


def test_second_operation_leaves_the_views_like_the_load(world, monkeypatch):
    class Second:
        @staticmethod
        def operation(sector, fact):
            return sector == "cantoneiras" and fact.get("phase") == "seguinte"
    monkeypatch.setattr(load_views, "_second", Second)
    v = _view("perfil")
    assert v["total"]["total"]["value"] == 62.0 and v["total"]["total"]["operations"] == 9
    assert v["outside"] == 2  # a 2.ª operação não conta como «fora»: tem a sua linha na Carga


def test_mtg2_has_no_sku_families_yet(world):
    v = _view("familia_sku", sector="perfis")
    assert v["empty"] == "A MTG2 ainda não tem famílias SKU." and v["rows"] == [] and v["note"] is None
    assert v["units"] == []  # P5: sem alternador de unidade numa vista vazia


def test_cell_shows_machines_and_orders_that_add_up_to_the_cell(world):
    v = _view("perfil")
    l45 = next(r for r in v["rows"] if r["key"] == "Cantoneira · L45X45X5")
    d = load_views.cell("cantoneiras", "perfil", "Cantoneira · L45X45X5", 2026, 41, today=TODAY, now=NOW)
    assert d["hours"] == l45["weeks"][0]["value"] == 6.5 and d["slot"] == "semana" and (d["year"], d["week"]) == (2026, 41)
    assert [(m["name"], m["hours"]) for m in d["machines"]] == [("Peddi 8", 4.0), ("XP T4", 2.5)] and d["orders"][0]["of"] == "OF1"
    late = load_views.cell("cantoneiras", "perfil", "Cantoneira · L45X45X5", None, "atrasado", today=TODAY, now=NOW)
    assert late["hours_unknown"] == l45["late_before"]["unknown"] == 1 and late["slot"] == "atrasado"
    nxt = load_views.cell("cantoneiras", "perfil", "Cantoneira · L45X45X5", 2026, 42, today=TODAY, now=NOW)
    assert nxt["hours"] == 5.0 and nxt["hours_unknown"] == 1 and nxt["metres"] == 10.0 and nxt["metres_unknown"] == 1
    assert nxt["orders"][0]["kinds"] == ["due", "suggested"] and nxt["kg"] == 8.0  # peso unitário 2 × 4 peças
    sector = load_views.cell("cantoneiras", "setor", "cantoneiras", 2026, 41, today=TODAY, now=NOW)
    assert sector["hours"] == 12.5 and {m["name"] for m in sector["machines"]} == {"Peddi 8", "XP T4"}
    with pytest.raises(load.planning.PlanningError):
        load_views.cell("cantoneiras", "perfil", "x", 2027, 30, today=TODAY, now=NOW)


def test_views_are_kept_per_sector_and_view_until_the_occurrences_change(world, monkeypatch):
    builds = []
    real = load_views._population
    monkeypatch.setattr(load_views, "_population", lambda *a, **k: builds.append(a[0]) or real(*a, **k))
    _view("perfil")
    _view("perfil", "m")  # outra unidade: as mesmas células guardadas
    _view("perfil")
    assert len(builds) == 1
    world["stamp"] = "nova geração"
    _view("perfil")
    assert len(builds) == 2
    for por in ("familia", "familia_sku", "setor"):
        _view(por)
    assert len([slot for slot in load_views._cache._entries if slot[0] == "cantoneiras"]) == 4


def test_views_follow_the_machines_of_the_grid_even_with_the_same_occurrences(world, monkeypatch):
    """E2-04: uma máquina que sai do setor (catálogo ou recursos) sai logo das vistas, como da grelha, sem esperar
    que as ocorrências sejam refeitas: as máquinas da grelha fazem parte da chave."""
    before = _view("perfil")
    assert before["total"]["total"]["value"] == 64.5 and before["outside"] == 2
    monkeypatch.setattr(sector_settings, "machine_rows", lambda c, sector: [m for m in MACHINES if m["id"] != "m2"])
    after = _view("perfil")
    over = load.overview("cantoneiras", today=TODAY, now=NOW)
    assert "m2" not in {m["id"] for m in over["machines"]}
    assert after["total"]["total"]["value"] == round(sum(t["load"] for t in over["totals"] if t["id"]), 1) < 64.5
    assert after["outside"] > before["outside"]
    # As decisões (exclusões) também: o mesmo número de ocorrências com outro digest refaz as células.
    builds = []
    real = load_views._population
    monkeypatch.setattr(load_views, "_population", lambda *a, **k: builds.append(1) or real(*a, **k))
    context = load._context
    monkeypatch.setattr(load, "_context", lambda sector, today=None: (lambda d, p, o: (d, p, {**o, "decisions": "outro"}))(*context(sector, today)))
    _view("perfil")
    assert builds == [1]


def test_views_use_the_load_memory_when_the_day_is_not_fixed(world, monkeypatch):
    """E2-05/P2: sem dia fixado, as vistas pedem load.overview(setor) sem today/now (a memória de 120 s da Carga);
    a vista Setores faz um só overview por setor e por pedido."""
    calls = []
    grid = {s: load.overview(s, today=TODAY, now=NOW) for s in ("perfis", "cantoneiras")}

    def overview(sector, **kw):
        calls.append((sector, kw))
        return grid[sector]
    monkeypatch.setattr(load, "overview", overview)
    monkeypatch.setattr(load, "_today", lambda: TODAY)
    v = load_views.view("cantoneiras", "setor")
    assert calls == [("perfis", {}), ("cantoneiras", {})] and {r["key"] for r in v["rows"]} == {"perfis", "cantoneiras"}
    calls.clear()
    load_views.cell("cantoneiras", "perfil", "Cantoneira · L45X45X5", 2026, 41)
    assert calls == [("cantoneiras", {})]
    calls.clear()
    load_views.view("cantoneiras", "perfil", today=TODAY, now=NOW)  # dia fixado (testes): sem memória
    assert calls == [("cantoneiras", {"today": TODAY, "now": NOW})]
