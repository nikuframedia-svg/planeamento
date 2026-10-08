"""Definições: secção «Planeamento» e 2.ª operação fora da lista (plano de 08/10/2026, Etapa 2, P9 parte 1 e P3-A).

- Um só dicionário, settings.PLANNING, diz que parâmetros há, a unidade, os limites, a origem, onde se aplicam e o
  que recalculam; o ecrã desenha-se a partir dele e a gravação `tipo='planeamento'` valida por ele.
- Nenhuma gravação das Definições apaga chaves que não enviou (S01): setor, tempos, eficiência, máquina e planeamento.
- Limites, parâmetros desconhecidos e revisão desatualizada (409).
- Etapa 3 (ponto 9): folga_dias, clientes_prioritarios, pessoas_por_maquina e pessoas_por_turno ativos, nos formatos
  que forecast.py lê; gravá-los não marca agregados (só a previsão); «Medido» das pessoas nas folhas MES; sugestão
  dos grupos de operadores do catálogo; a ordem do plano só como texto.
- A política de prazo deixa de estar atrás do interruptor das vistas por família.
- As máquinas da 2.ª operação saem da lista das Definições (second_operation.machine), não de machine_rows.
Sem base de dados: ligação falsa só com sector_settings.
"""
import sys
import types
import uuid

import pytest

from app import planning
from app.raw import productivity
from app.sector import settings, shifts

P8, XP4, PRENSA, PLASMA = "p8", "xp4", "prensa", "plasma"
MACHINES = [
    {"id": P8, "name": "Peddi 8", "code": "PEDDI8", "type": "maquina", "process": "Punção", "has_object": True, "default_shifts": 2,
     "aliases": [], "operations": [], "ficha": [], "override": {}, "revision": 1},
    {"id": XP4, "name": "Ficep XP T4", "code": "XPT4", "type": "maquina", "process": "Punção", "has_object": True, "default_shifts": 2,
     "aliases": [], "operations": [], "ficha": [], "override": {}, "revision": 1},
    {"id": PRENSA, "name": "Prensa", "code": "PRENSA", "type": "posto", "process": "Forja", "has_object": True, "default_shifts": 0,
     "aliases": [], "operations": [], "ficha": [], "override": {}, "revision": 1},
    {"id": PLASMA, "name": "Plasma manual", "code": "PLASMA", "type": "posto", "process": "Corte adicional", "has_object": True,
     "default_shifts": 0, "aliases": [], "operations": [], "ficha": [], "override": {}, "revision": 1},
]
# Chaves que o ecrã de cada gravação não envia: têm de sobreviver a todas (S01).
EXTRA = {"folga_dias": 2, "clientes_prioritarios": ["Cliente X"], "pessoas_por_turno": [3, 2, None], "chave_futura": {"a": 1}}


class Conn:
    """Ligação falsa: só sector_settings (definição e revisão), como na base."""

    def __init__(self, definition, revision=5):
        self.definition, self.revision = definition, revision

    def execute(self, sql, params=None):
        conn = self

        class Result:
            def fetchone(self):
                if "to_regclass" in sql:
                    return {"t": "planning_mtg.sector_settings"}
                if "FROM planning_mtg.sector_settings" in sql:
                    return {"definition": dict(conn.definition), "revision": conn.revision} if conn.definition is not None else None
                return None

            def fetchall(self):
                return []
        if sql.lstrip().startswith("INSERT INTO planning_mtg.sector_settings"):
            conn.definition, conn.revision = params[1].obj, conn.revision + 1
        return Result()


@pytest.fixture()
def conn(monkeypatch):
    monkeypatch.setattr(settings, "machine_rows", lambda c, sector, context=None: [dict(m) for m in MACHINES])
    monkeypatch.setattr(settings, "regenerate", lambda *a, **k: 0)
    monkeypatch.setattr(shifts, "finish_batch", lambda c, request_id: None)
    stored = {"template": [["06:00", "14:00"]], "workdays": [1, 2, 3, 4, 5], "holidays": ["2026-12-25"],
              "margin_pct": 0, "piece_minutes": 0, "efficiency": {P8: 85}, **EXTRA}
    return Conn(stored)


def save(c, **payload):
    return settings.save({"setor": "cantoneiras", "request_id": str(uuid.uuid4()), **payload}, conn=c)


# ---------------------------------------------------------------- dicionário único


def test_planning_dictionary_is_the_single_description_of_the_parameters():
    kinds = {"por_maquina", "numero", "lista", "por_turno", "politica", "postos", "regra"}
    for key, p in settings.PLANNING.items():
        assert {"label", "kind", "unit", "default", "limits", "origin", "stored", "active", "applies_in", "recalcula"} <= set(p), key
        assert p["kind"] in kinds and p["origin"] in settings.ORIGINS and p["applies_in"], key
    active = [k for k, p in settings.PLANNING.items() if p["active"]]
    assert active == ["efficiency", "piece_minutes", "deadline_policy", "posts", "folga_dias", "clientes_prioritarios",
                      "ordem_plano", "pessoas_por_maquina", "pessoas_por_turno"]
    # Etapa 3: só a previsão os lê.
    assert settings.FORECAST_ONLY == {"folga_dias", "clientes_prioritarios", "pessoas_por_maquina", "pessoas_por_turno"}
    for key in settings.FORECAST_ONLY:
        assert settings.PLANNING[key]["recalcula"] == settings.RECALC_FORECAST, key
    assert settings.PLANNING["folga_dias"]["default"] == 2 and settings.PLANNING["folga_dias"]["origin"] == "pressuposto"
    assert "as datas mostradas não mudam" in settings.PLANNING["folga_dias"]["applies_in"]
    assert "depois da prioridade escrita" in settings.PLANNING["clientes_prioritarios"]["applies_in"]
    assert settings.PLANNING["pessoas_por_maquina"]["kind"] == "por_maquina" and settings.PLANNING["pessoas_por_maquina"]["default"] == 1
    assert settings.PLANNING["ordem_plano"]["text"] == "Planeado (com ajustes) → prioridade escrita → clientes prioritários → prazo → OF"
    assert settings.PLANNING["ordem_plano"]["stored"] is False
    # Os mesmos limites que o motor e a gravação antiga usam: uma só fonte.
    assert tuple(settings.PLANNING["efficiency"]["limits"]) == tuple(int(x) for x in productivity.EFFICIENCY_RANGE)
    assert settings.TIMING["piece_minutes"][1:] == tuple(settings.PLANNING["piece_minutes"]["limits"])
    assert settings.PLANNING["efficiency"]["recalcula"] == "Vai recalcular as horas (2–3 min)."
    assert settings.PLANNING["efficiency"]["origin"] == "pressuposto" and settings.PLANNING["deadline_policy"]["origin"] == "regra"


def test_planning_view_lists_only_active_parameters_with_their_values():
    machines = [{"id": P8, "name": "Peddi 8", "efficiency_pct": 85}, {"id": XP4, "name": "Ficep XP T4", "efficiency_pct": 100}]
    policy = {"principal": ["picking", "planned_period", "galvanizing", "cut_date"], "following": ["picking", "galvanizing"],
              "milestone": "disponibilidade_picking", "assume_picking_year": None, "origin": "Política por defeito"}
    posts = [{"post": "fita", "name": "Serrote Fita pav.1", "members": ["Serrote Doall Pav.1"], "text": "…"}]
    rows = settings.planning_view({"piece_minutes": 0.5}, machines, policy, posts)
    assert [r["key"] for r in rows] == ["efficiency", "piece_minutes", "deadline_policy", "posts", "folga_dias",
                                        "clientes_prioritarios", "ordem_plano", "pessoas_por_maquina", "pessoas_por_turno"]
    eff, fixed, deadline, post = rows[:4]
    assert eff["value"] == {P8: 85, XP4: 100} and (eff["min"], eff["max"], eff["unit"]) == (10, 200, "%")
    assert eff["origin_label"] == "Pressuposto" and eff["editable"] and eff["recalcula"] == settings.RECALC_HOURS
    assert fixed["value"] == 0.5 and fixed["unit"] == "min"
    assert deadline["value"]["principal"] == policy["principal"] and deadline["value"]["revision"] == 0
    assert [c["key"] for c in deadline["choices"]][:4] == ["cut_date", "picking", "galvanizing", "planned_period"]
    assert post["editable"] is False and post["origin_label"] == "Declarado"
    # Sem postos no setor (cantoneiras), a linha não aparece.
    assert "posts" not in [r["key"] for r in settings.planning_view({}, machines, policy, [])]


def test_posts_view_shows_the_post_and_its_machines_as_one_capacity():
    by_id = {"fita": {"id": "fita", "code": "POSTO_FITA", "name": "Serrote Fita pav.1", "type": "posto"},
             "doall": {"id": "doall", "code": "DOALL", "name": "Serrote Doall Pav.1", "type": "maquina"},
             "thomas": {"id": "thomas", "code": "THOMAS", "name": "Thomas IS639", "type": "maquina"},
             "p8": {"id": "p8", "code": "PEDDI8", "name": "Peddi 8", "type": "maquina"}}
    package = {"metadata": {"relations": [{"relacao": "compoe", "pai": "POSTO_FITA", "filho": "DOALL"},
                                          {"relacao": "compoe", "pai": "POSTO_FITA", "filho": "THOMAS"},
                                          {"relacao": "partilha_operadores", "pai": "PEDDI8", "filho": "DOALL"}]}}
    [post] = settings.posts_view(by_id, package, {"fita", "doall", "thomas"})
    assert post["text"] == "Serrote Fita pav.1 (posto) = Serrote Fita pav.1 + Serrote Doall Pav.1 + Thomas IS639: uma só capacidade"
    assert settings.posts_view(by_id, package, {"p8"}) == []  # posto de outro setor
    assert settings.posts_view(by_id, None, {"fita"}) == []  # sem catálogo


# ---------------------------------------------------------------- chaves preservadas (S01)


def test_every_save_keeps_every_key_it_did_not_send(conn):
    def kept():
        for key, value in EXTRA.items():
            assert conn.definition[key] == value, key
    save(conn, tipo="setor", expected_revision=5, turnos=[["06:00", "14:00"], ["14:00", "22:00"]], dias=[1, 2, 3, 4], feriados=["2026-12-08"])
    kept()
    assert conn.definition["efficiency"] == {P8: 85} and conn.definition["workdays"] == [1, 2, 3, 4]
    save(conn, tipo="tempos", expected_revision=6, piece_minutes=1)
    kept()
    assert conn.definition["piece_minutes"] == 1 and conn.definition["template"] == [["06:00", "14:00"], ["14:00", "22:00"]]
    save(conn, tipo="eficiencia", expected_revision=7, eficiencias={XP4: 90})
    kept()
    assert conn.definition["efficiency"] == {P8: 85, XP4: 90} and conn.definition["piece_minutes"] == 1
    save(conn, tipo="maquina", id=P8, eficiencia=80)
    kept()
    assert conn.definition["efficiency"] == {P8: 80, XP4: 90}
    save(conn, tipo="planeamento", expected_revision=9, valores={"piece_minutes": "0,5", "efficiency": {XP4: None}})
    kept()
    assert conn.definition["piece_minutes"] == 0.5 and conn.definition["efficiency"] == {P8: 80}
    assert conn.definition["template"] == [["06:00", "14:00"], ["14:00", "22:00"]] and conn.definition["holidays"] == ["2026-12-08"]
    assert "revision" not in conn.definition and conn.revision == 10


def test_planning_save_validates_by_the_dictionary(conn):
    def refused(valores, match):
        with pytest.raises(planning.PlanningError, match=match):
            save(conn, tipo="planeamento", expected_revision=5, valores=valores)
    refused({"piece_minutes": 121}, "entre 0 e 120 min")
    refused({"piece_minutes": -1}, "entre 0 e 120 min")
    refused({"piece_minutes": "abc"}, "indica um número")
    refused({"efficiency": {P8: 250}}, "entre 10 e 200")
    refused({"efficiency": {P8: 5}}, "entre 10 e 200")
    refused({"efficiency": {"outra": 90}}, "Máquina desconhecida")
    refused({"efficiency": {}}, "pelo menos uma máquina")
    refused({"ordem_plano": "x"}, "desconhecido")  # só texto
    refused({"deadline_policy": ["cut_date"]}, "desconhecido")  # tem a sua gravação
    refused({"posts": []}, "desconhecido")  # só leitura
    refused({"margin_pct": 10}, "desconhecido")
    refused({}, "pelo menos um valor")
    refused(None, "pelo menos um valor")
    assert conn.revision == 5, "nada gravado"
    # A máquina da 2.ª operação continua a existir para as gravações (machine_rows fica igual).
    save(conn, tipo="planeamento", expected_revision=5, valores={"efficiency": {P8: "92,5", PRENSA: 100}, "piece_minutes": 2})
    assert conn.definition["efficiency"] == {P8: 92.5} and conn.definition["piece_minutes"] == 2 and conn.definition["margin_pct"] == 0


def test_old_margin_turns_into_efficiency_once_when_saving_from_the_new_section(conn):
    conn.definition.update({"margin_pct": 25, "efficiency": {}})
    save(conn, tipo="planeamento", expected_revision=5, valores={"efficiency": {XP4: 90}})
    assert conn.definition["margin_pct"] == 0
    assert conn.definition["efficiency"] == {P8: 80.0, XP4: 90, PRENSA: 80.0, PLASMA: 80.0}


@pytest.mark.parametrize("payload", [
    {"tipo": "planeamento", "valores": {"piece_minutes": 1}},
    {"tipo": "tempos", "piece_minutes": 1},
    {"tipo": "eficiencia", "eficiencias": {P8: 90}},
    {"tipo": "setor", "turnos": [["06:00", "14:00"]], "dias": [1], "feriados": []},
])
def test_a_stale_revision_is_refused_with_409(conn, payload):
    with pytest.raises(planning.PlanningError) as stale:
        save(conn, expected_revision=4, **payload)
    assert stale.value.status == 409 and conn.revision == 5


# ---------------------------------------------------------------- política fora do interruptor


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient
    from app.sector import priority
    from app.web.planning_app import app

    class Readonly:
        def __enter__(self):
            return object()

        def __exit__(self, *exc):
            return False
    monkeypatch.setattr(planning, "connect", lambda **kw: Readonly())
    monkeypatch.setattr(priority, "policies", lambda c: {a: priority.default(a) for a in planning.AREAS})
    monkeypatch.setattr(priority, "overrides", lambda c: {})
    monkeypatch.setattr(priority, "save_policy", lambda p: {"repeated": False, "saved": p["definition"]})
    monkeypatch.setattr(priority, "save_override", lambda p: {"repeated": False})
    return TestClient(app)


def test_deadline_policy_routes_follow_the_carteira_switch_not_the_family_views(client, monkeypatch):
    monkeypatch.setenv("MES_PLANNING_SELECTION_ENABLED", "1")
    monkeypatch.setenv("MES_PLANNING_FAMILY_VIEWS_ENABLED", "0")
    got = client.get("/planeamento/api/setor/prioridades")
    assert got.status_code == 200 and got.json()["policies"]["cantoneiras"]["principal"] == ["cut_date"]
    body = {"setor": "cantoneiras", "request_id": str(uuid.uuid4()), "expected_revision": 0,
            "definition": {"principal": ["cut_date"], "following": ["galvanizing"]}}
    posted = client.post("/planeamento/api/setor/prioridades/politica", json=body)
    assert posted.status_code == 200 and posted.json()["saved"]["principal"] == ["cut_date"]
    # O prazo por OF continua atrás do interruptor das vistas (sem ecrã nesta etapa).
    assert client.post("/planeamento/api/setor/prioridades/of", json={"setor": "cantoneiras"}).status_code == 404
    # Sem nenhum dos interruptores, nada responde.
    monkeypatch.setenv("MES_PLANNING_SELECTION_ENABLED", "0")
    assert client.get("/planeamento/api/setor/prioridades").status_code == 404
    assert client.post("/planeamento/api/setor/prioridades/politica", json=body).status_code == 404
    # Só com as vistas por família (configuração antiga) continua a responder.
    monkeypatch.setenv("MES_PLANNING_FAMILY_VIEWS_ENABLED", "1")
    assert client.get("/planeamento/api/setor/prioridades").status_code == 200


# ---------------------------------------------------------------- 2.ª operação fora das Definições


def _fake_second_operation(monkeypatch):
    module = types.ModuleType("app.sector.second_operation")
    module.machine = lambda sector, process: sector == "cantoneiras" and process not in (None, "Punção", "Broca")
    monkeypatch.setitem(sys.modules, "app.sector.second_operation", module)
    import app.sector
    monkeypatch.setattr(app.sector, "second_operation", module, raising=False)


def _overview(monkeypatch, sector="cantoneiras", clients=()):
    from app.gantt import research
    from app.sector import priority
    every = [dict(m) for m in MACHINES]
    calls = {}

    class Readonly(Conn):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def rows(c, s, context=None):
        calls["context"] = context
        return every
    monkeypatch.setattr(planning, "connect", lambda **kw: Readonly({"template": [["06:00", "14:00"]], "workdays": [1, 2, 3, 4, 5], "holidays": []}))
    monkeypatch.setattr(settings, "_resources", lambda c: ({}, {}, {}, [], None))
    monkeypatch.setattr(settings, "machine_rows", rows)
    monkeypatch.setattr(settings, "_measured", lambda c, s: {})
    monkeypatch.setattr(settings, "_excel_area", lambda c, machines: {})
    monkeypatch.setattr(research, "enabled", lambda: False)
    monkeypatch.setattr(productivity, "sector_timing", lambda c: {a: {"piece_minutes": 0.0, "efficiency": {P8: 85.0}} for a in planning.AREAS})
    monkeypatch.setattr(priority, "policies", lambda c: {a: priority.default(a) for a in planning.AREAS})
    monkeypatch.setattr(shifts, "calendar_row", lambda c, rid, y, w: None)
    monkeypatch.setattr(settings, "carteira_clients", lambda s: list(clients))  # sem Carteira nos testes
    result = settings.overview(sector)
    return result, every, calls


def test_overview_leaves_the_second_operation_machines_out_of_the_list(monkeypatch):
    _fake_second_operation(monkeypatch)
    result, every, calls = _overview(monkeypatch)
    assert [m["id"] for m in result["machines"]] == [P8, XP4]
    assert [m["machine"] for m in result["weeks"]] == [P8, XP4]
    assert [m["name"] for m in result["second_operation"]] == ["Prensa", "Plasma manual"]
    assert len(every) == 4, "machine_rows fica igual: calendários e turnos usam-no"
    assert calls["context"] == ({}, {}, {}, [], None), "o catálogo lê-se uma vez por pedido"
    # A secção Planeamento: eficiência só das máquinas do plano, com o valor gravado.
    [eff] = [r for r in result["planning"] if r["key"] == "efficiency"]
    assert eff["value"] == {P8: 85.0, XP4: 100.0}
    assert result["rules"][0] == "Prazo: Data Corte."


def test_without_the_second_operation_module_the_list_stays_as_it_was(monkeypatch):
    monkeypatch.setitem(sys.modules, "app.sector.second_operation", None)  # import falha: código antigo
    result, _, _ = _overview(monkeypatch)
    assert [m["id"] for m in result["machines"]] == [P8, XP4, PRENSA, PLASMA] and result["second_operation"] == []
    perfis, _, _ = _overview(monkeypatch, "perfis")
    assert perfis["rules"][0] == "Prazo: Picking → Semana escolhida → Galvanização → Data Corte (o primeiro que a linha tiver)."


def test_the_second_operation_rule_never_touches_the_profiles(monkeypatch):
    _fake_second_operation(monkeypatch)
    keep, out = settings.split_second_operation("perfis", [{"id": "a", "process": "Abocardar"}, {"id": "b", "process": None}])
    assert [m["id"] for m in keep] == ["a", "b"] and out == []


# ---------------------------------------------------------------- Etapa 3 (ponto 9): parâmetros da previsão


def test_planning_view_shows_the_forecast_parameters_in_the_formats_forecast_reads():
    machines = [{"id": P8, "name": "Peddi 8", "efficiency_pct": 100}, {"id": XP4, "name": "Ficep XP T4", "efficiency_pct": 100}]
    stored = {"folga_dias": 3, "clientes_prioritarios": ["Cliente B", "Cliente A"], "pessoas_por_maquina": {XP4: 2},
              "pessoas_por_turno": [3, None, None]}
    people = {"median": 15, "text": "15 por dia útil", "note": "Indicativo"}
    groups = [{"code": "OPERADORES_PAV1", "name": "Operadores dos quatro serrotes pav.1", "people": 2, "members": ["Posto Disco"]}]
    rows = {r["key"]: r for r in settings.planning_view(stored, machines, {}, [], {"clients": ["Cliente A", "Cliente B", "Cliente C"],
                                                                                  "people": people, "groups": groups})}
    assert rows["folga_dias"]["value"] == 3 and rows["folga_dias"]["unit"] == "dias úteis"
    assert rows["clientes_prioritarios"]["value"] == ["Cliente B", "Cliente A"]
    assert rows["clientes_prioritarios"]["choices"] == ["Cliente A", "Cliente B", "Cliente C"]
    assert rows["pessoas_por_maquina"]["value"] == {P8: 1, XP4: 2}
    assert rows["pessoas_por_turno"]["value"] == [3, None, None]
    assert rows["pessoas_por_turno"]["measured"] == people and rows["pessoas_por_turno"]["suggestions"] == groups
    assert rows["ordem_plano"]["value"].startswith("Planeado (com ajustes)") and rows["ordem_plano"]["editable"] is False
    # Sem nada gravado: os defeitos (folga 2, 1 pessoa por máquina, sem pessoas por turno).
    empty = {r["key"]: r for r in settings.planning_view({}, machines, {}, [])}
    assert empty["folga_dias"]["value"] == 2 and empty["clientes_prioritarios"]["value"] == []
    assert empty["pessoas_por_maquina"]["value"] == {P8: 1, XP4: 1} and empty["pessoas_por_turno"]["value"] is None
    assert empty["clientes_prioritarios"]["choices"] == [] and empty["pessoas_por_turno"]["measured"] is None
    # Um número para todas as máquinas (o outro formato que forecast.persons_of lê).
    both = {r["key"]: r for r in settings.planning_view({"pessoas_por_maquina": 2}, machines, {}, [])}
    assert both["pessoas_por_maquina"]["value"] == {P8: 2, XP4: 2}


def test_forecast_parameters_are_saved_in_the_formats_forecast_reads_without_marking_aggregates(conn, monkeypatch):
    from app.sector import forecast
    signals = []
    monkeypatch.setattr(shifts, "finish_batch", lambda c, request_id: signals.append(request_id))
    save(conn, tipo="planeamento", expected_revision=5, valores={
        "folga_dias": "4", "clientes_prioritarios": ["  Cliente   B ", "Cliente A", "Cliente B", ""],
        "pessoas_por_maquina": {XP4: 2, P8: ""}, "pessoas_por_turno": [2, "", None]})
    d = conn.definition
    assert d["folga_dias"] == 4 and isinstance(d["folga_dias"], int)
    assert d["clientes_prioritarios"] == ["Cliente B", "Cliente A"]
    assert d["pessoas_por_maquina"] == {XP4: 2}
    assert d["pessoas_por_turno"] == [2, None, None]
    assert signals == [], "só a previsão: nada de agregados nem calendários"
    assert conn.revision == 6, "a revisão sobe: a previsão segue-a"
    # forecast lê exatamente estes nomes e formatos.
    assert forecast._count(d["folga_dias"], forecast.FOLGA_DEFAULT) == 4
    assert forecast.persons_of(d["pessoas_por_maquina"], [P8, XP4]) == {P8: 1, XP4: 2}
    assert forecast.client_position("CLIENTE A, LDA", d["clientes_prioritarios"]) == 1
    # A pessoa por máquina de volta ao defeito sai; um número antigo para todas passa a valer em cada uma.
    save(conn, tipo="planeamento", expected_revision=6, valores={"pessoas_por_maquina": {XP4: 1}})
    assert conn.definition["pessoas_por_maquina"] == {}
    conn.definition["pessoas_por_maquina"] = 3
    save(conn, tipo="planeamento", expected_revision=7, valores={"pessoas_por_maquina": {P8: 0}})
    assert conn.definition["pessoas_por_maquina"] == {P8: 0, XP4: 3, PRENSA: 3, PLASMA: 3}
    # Com a eficiência no mesmo pedido, marca os agregados (as horas mudam).
    save(conn, tipo="planeamento", expected_revision=8, valores={"folga_dias": 1, "efficiency": {P8: 90}})
    assert len(signals) == 1
    assert conn.definition["chave_futura"] == {"a": 1}, "chaves que não se enviaram ficam (S01)"


def test_forecast_parameters_are_validated(conn):
    def refused(valores, match):
        with pytest.raises(planning.PlanningError, match=match):
            save(conn, tipo="planeamento", expected_revision=5, valores=valores)
    refused({"folga_dias": 21}, "entre 0 e 20 dias úteis")
    refused({"folga_dias": -1}, "entre 0 e 20")
    refused({"folga_dias": "1,5"}, "inteiro")
    refused({"folga_dias": ""}, "indica um número")
    refused({"clientes_prioritarios": [f"C{i}" for i in range(51)]}, "no máximo 50")
    refused({"clientes_prioritarios": ["x" * 121]}, "120 caracteres")
    refused({"pessoas_por_maquina": {P8: 11}}, "entre 0 e 10")
    refused({"pessoas_por_maquina": {P8: 1.5}}, "inteiro")
    refused({"pessoas_por_maquina": {"outra": 1}}, "Máquina desconhecida")
    refused({"pessoas_por_maquina": {}}, "pelo menos uma máquina")
    refused({"pessoas_por_turno": [1, 2, 3, 4]}, "um valor por turno")
    refused({"pessoas_por_turno": 3}, "um valor por turno")
    refused({"pessoas_por_turno": [201]}, "entre 0 e 200")
    refused({"pessoas_por_turno": [1.5]}, "inteiros")
    assert conn.revision == 5, "nada gravado"
    save(conn, tipo="planeamento", expected_revision=5, valores={"pessoas_por_turno": [4], "clientes_prioritarios": []})
    assert conn.definition["pessoas_por_turno"] == [4, None, None] and conn.definition["clientes_prioritarios"] == []


@pytest.mark.parametrize("valores", [{"folga_dias": 1}, {"clientes_prioritarios": ["A"]}, {"pessoas_por_maquina": {P8: 2}},
                                     {"pessoas_por_turno": [1, 1, 1]}])
def test_forecast_parameters_with_a_stale_revision_are_refused_with_409(conn, valores):
    with pytest.raises(planning.PlanningError) as stale:
        save(conn, tipo="planeamento", expected_revision=4, valores=valores)
    assert stale.value.status == 409 and conn.revision == 5 and conn.definition["folga_dias"] == 2


def test_load_memory_ignores_the_forecast_only_keys():
    base = {"template": [["06:00", "14:00"]], "workdays": [1, 2, 3, 4, 5], "piece_minutes": 0, "revision": 3}
    stamp = settings.load_stamp(base)
    assert settings.load_stamp({**base, "revision": 4, "folga_dias": 5, "clientes_prioritarios": ["A"],
                                "pessoas_por_maquina": {P8: 2}, "pessoas_por_turno": [1, None, None]}) == stamp
    assert settings.load_stamp({**base, "piece_minutes": 1}) != stamp


class SheetsConn:
    """Só leitura: to_regclass e a contagem por dia das folhas validadas."""

    def __init__(self, rows, present=True):
        self.rows, self.present, self.queries = rows, present, []

    def execute(self, sql, params=None):
        self.queries.append((sql, params))
        conn = self

        class Result:
            def fetchone(self):
                return {"t": "mes_kanban.validated_sheets" if conn.present else None}

            def fetchall(self):
                return conn.rows
        return Result()


def test_people_measured_counts_distinct_operators_per_workday_with_a_long_cache():
    from datetime import date
    settings._people_cache.clear()
    rows = [{"sheet_date": date(2026, 10, 5), "people": 14, "sheets": 20, "no_shift": 19},   # segunda
            {"sheet_date": date(2026, 10, 6), "people": 16, "sheets": 22, "no_shift": 20},   # terça
            {"sheet_date": date(2026, 10, 7), "people": 15, "sheets": 18, "no_shift": 18},   # quarta
            {"sheet_date": date(2026, 10, 3), "people": 5, "sheets": 5, "no_shift": 5},      # sábado: fora
            {"sheet_date": date(2026, 10, 8), "people": 2, "sheets": 2, "no_shift": 2}]      # feriado gravado: fora
    c = SheetsConn(rows)
    st = {"workdays": [1, 2, 3, 4, 5], "holidays": ["2026-10-08"]}
    got = settings.people_measured(c, "perfis", st, today=date(2026, 10, 8))
    assert (got["median"], got["min"], got["max"], got["days"]) == (15, 14, 16, 3)
    assert got["no_shift_pct"] == round(100 * 64 / 67)
    assert got["text"] == "15 por dia útil (mediana de 3 dias, 14–16; folhas MES dos últimos 28 dias)"
    assert "turno vem vazio em 96 %" in got["note"]
    sql, params = c.queries[-1]
    assert sql.lstrip().startswith("SELECT") and "mes_kanban.validated_sheets" in sql and params[0] == "kanban-mes-mtg2"
    # Cache longa: a segunda leitura não vai à base.
    count = len(c.queries)
    assert settings.people_measured(c, "perfis", st, today=date(2026, 10, 8)) == got and len(c.queries) == count
    # Sem a tabela (base de ensaio) ou sem folhas: nada medido.
    settings._people_cache.clear()
    assert settings.people_measured(SheetsConn([], present=False), "cantoneiras", st, today=date(2026, 10, 8)) is None
    assert settings.people_measured(SheetsConn([]), "perfis", st, today=date(2026, 10, 8)) is None
    settings._people_cache.clear()


def test_operator_groups_of_the_catalogue_are_only_a_suggestion():
    package = {"metadata": {
        "resources": [{"codigo": "OPERADORES_PAV1", "designacao": "Operadores dos quatro serrotes pav.1", "setor": "MTG2",
                       "tipo": "grupo_operadores", "quantidade_operadores": 2},
                      {"codigo": "POSTO_DISCO", "designacao": "Serrote Disco pav.1 (posto)", "tipo": "posto", "setor": "MTG2"},
                      {"codigo": "POSTO_FITA", "designacao": "Serrote Fita pav.1 (posto)", "tipo": "posto", "setor": "MTG2"}],
        "relations": [{"relacao": "partilha_operadores", "pai": "OPERADORES_PAV1", "filho": "POSTO_DISCO"},
                      {"relacao": "partilha_operadores", "pai": "OPERADORES_PAV1", "filho": "POSTO_FITA"}]}}
    [group] = settings.operator_groups(package, "perfis")
    assert group == {"code": "OPERADORES_PAV1", "name": "Operadores dos quatro serrotes pav.1", "people": 2,
                     "members": ["Serrote Disco pav.1 (posto)", "Serrote Fita pav.1 (posto)"]}
    assert settings.operator_groups(package, "cantoneiras") == []
    assert settings.operator_groups(None, "perfis") == []


def test_overview_brings_the_clients_of_the_carteira_and_the_people(monkeypatch):
    monkeypatch.setattr(settings, "people_measured", lambda c, sector, st: {"median": 7, "text": "7 por dia útil"})
    result, _, _ = _overview(monkeypatch, "perfis", clients=["Cliente A", "Cliente B"])
    rows = {r["key"]: r for r in result["planning"]}
    assert rows["clientes_prioritarios"]["choices"] == ["Cliente A", "Cliente B"]
    assert rows["pessoas_por_turno"]["measured"]["median"] == 7 and rows["pessoas_por_turno"]["suggestions"] == []


def test_carteira_clients_are_the_distinct_names_of_the_carteira_in_memory_and_never_compute_it(monkeypatch):
    from app.sector import cache, portfolio
    memory = cache.Cache("teste")
    monkeypatch.setattr(portfolio, "_cache", memory)
    monkeypatch.setattr(portfolio, "load", lambda *a, **k: pytest.fail("as Definições nunca calculam a Carteira"))
    assert settings.carteira_clients("perfis") == [], "Carteira ainda não calculada: escreve-se à mão"
    memory.get("perfis", ("g1", None), lambda: {"lines": [
        {"customer": "beta"}, {"customer": "Alfa"}, {"customer": "Sem cliente"}, {"customer": "Alfa"}, {"customer": ""}]})
    assert settings.carteira_clients("perfis") == ["Alfa", "beta"]
    assert settings.carteira_clients("cantoneiras") == []
