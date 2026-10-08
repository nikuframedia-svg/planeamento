"""Definições: secção «Planeamento» e 2.ª operação fora da lista (plano de 08/10/2026, Etapa 2, P9 parte 1 e P3-A).

- Um só dicionário, settings.PLANNING, diz que parâmetros há, a unidade, os limites, a origem, onde se aplicam e o
  que recalculam; o ecrã desenha-se a partir dele e a gravação `tipo='planeamento'` valida por ele.
- Nenhuma gravação das Definições apaga chaves que não enviou (S01): setor, tempos, eficiência, máquina e planeamento.
- Limites, parâmetros desconhecidos ou ainda inativos (Etapa 3) e revisão desatualizada (409).
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
    kinds = {"por_maquina", "numero", "lista", "por_turno", "politica", "postos"}
    for key, p in settings.PLANNING.items():
        assert {"label", "kind", "unit", "default", "limits", "origin", "stored", "active", "applies_in", "recalcula"} <= set(p), key
        assert p["kind"] in kinds and p["origin"] in settings.ORIGINS and p["applies_in"], key
    active = [k for k, p in settings.PLANNING.items() if p["active"]]
    assert active == ["efficiency", "piece_minutes", "deadline_policy", "posts"]
    # Etapa 3: já descritos, ainda escondidos (basta ativá-los).
    assert {"folga_dias", "clientes_prioritarios", "pessoas_por_maquina", "pessoas_por_turno"} <= set(settings.PLANNING)
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
    assert [r["key"] for r in rows] == ["efficiency", "piece_minutes", "deadline_policy", "posts"]
    eff, fixed, deadline, post = rows
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
    refused({"folga_dias": 2}, "desconhecido")  # Etapa 3: ainda inativo
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


def _overview(monkeypatch, sector="cantoneiras"):
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
    import app.sector
    monkeypatch.setitem(sys.modules, "app.sector.second_operation", None)  # import falha: código antigo
    monkeypatch.delattr(app.sector, "second_operation", raising=False)  # o «from . import» também olha para o pacote
    result, _, _ = _overview(monkeypatch)
    assert [m["id"] for m in result["machines"]] == [P8, XP4, PRENSA, PLASMA] and result["second_operation"] == []
    perfis, _, _ = _overview(monkeypatch, "perfis")
    assert perfis["rules"][0] == "Prazo: Picking → Semana escolhida → Galvanização → Data Corte (o primeiro que a linha tiver)."


def test_the_second_operation_rule_never_touches_the_profiles(monkeypatch):
    _fake_second_operation(monkeypatch)
    keep, out = settings.split_second_operation("perfis", [{"id": "a", "process": "Abocardar"}, {"id": "b", "process": None}])
    assert [m["id"] for m in keep] == ["a", "b"] and out == []
