"""2.ª operação das cantoneiras fora do plano (decisão do Luís, 08/10/2026, opção A). Sem base de dados."""
from contextlib import contextmanager

import pytest

from app import planning
from app.sector import second_operation


def test_machines_of_the_second_operation_are_the_cantoneiras_ones_outside_punch_and_drill():
    for process in ("Corte adicional", "Chanfro", "Forja"):  # Saca bocados / Plasma manual, Fresadora, Prensa
        assert second_operation.machine("cantoneiras", process) is True
    for process in ("Punção", "Broca", None, ""):  # principais, ou sem processo no catálogo: ficam nas listas
        assert second_operation.machine("cantoneiras", process) is False
    assert second_operation.machine("perfis", "Abocardar") is False  # a MTG2 fica igual


def test_operations_of_the_second_operation_are_the_following_ones_of_the_cantoneiras():
    assert second_operation.operation("cantoneiras", {"phase": "seguinte"}) is True
    assert second_operation.operation("cantoneiras", {"phase": "principal"}) is False
    assert second_operation.operation("cantoneiras", {}) is False
    assert second_operation.operation("perfis", {"phase": "seguinte"}) is False
    assert [second_operation.phase(x) for x in (1, 2, 5, None, "x")] == ["principal", "seguinte", "seguinte", "principal", "principal"]


def test_summary_and_label_count_by_machine_and_never_turn_unknown_hours_into_zero():
    facts = [*[{"planning_resource_id": "pl", "planning_machine": "Plasma manual", "load_hours": None}] * 3925,
             *[{"planning_resource_id": "pr", "planning_machine": "Prensa", "load_hours": 0.5}] * 2,
             {"planning_resource_id": None, "planning_machine": "Sem máquina", "load_hours": None}]
    summary = second_operation.summary(facts)
    assert summary == {"operations": 3928, "hours": 1.0, "unknown": 3926,
                       "machines": [{"name": "Plasma manual", "operations": 3925}, {"name": "Prensa", "operations": 2},
                                    {"name": "sem máquina", "operations": 1}]}
    assert second_operation.label(summary) == ("3 928 operações de 2.ª operação fora do plano "
                                               "(Plasma manual 3 925 · Prensa 2 · sem máquina 1). Continuam na Tabela.")
    assert second_operation.label(second_operation.summary([])) == ""
    one = second_operation.summary([{"planning_resource_id": "f", "planning_machine": "Fresadora", "load_hours": None}])
    assert second_operation.label(one) == "1 operação de 2.ª operação fora do plano (Fresadora 1). Continuam na Tabela."


def test_assign_machine_and_family_sets_no_longer_offer_the_second_operation_machines(monkeypatch):
    """Atribuir máquina e Conjuntos usam family_sets.machines(); a validação de member_machine.apply passa por aí."""
    from app.sector import family_sets, member_machine, occurrences, portfolio, portfolio_kpis
    by_id = {"peddi": {"name": "Peddi 8", "code": "PEDDI8"}, "plasma": {"name": "Plasma manual", "code": "PLASMA_MANUAL"},
             "prensa": {"name": "Prensa", "code": "PRENSA"}}
    info = {"PEDDI8": {"process": "Punção", "unit": "MTG3", "type": "maquina"},
            "PLASMA_MANUAL": {"process": "Corte adicional", "unit": "MTG3", "type": "posto"},
            "PRENSA": {"process": "Forja", "unit": "MTG3", "type": "posto"}}

    @contextmanager
    def connect(readonly=True):
        yield None

    monkeypatch.setattr(family_sets.planning, "connect", connect)
    monkeypatch.setattr(occurrences, "resources_context", lambda c: ({}, by_id, {}, [], None))
    monkeypatch.setattr(portfolio_kpis, "catalog", lambda c, sector: info)
    monkeypatch.setattr(portfolio, "current", lambda sector, **k: {"lines": [{"machine": "Prensa"}]})  # escrita na Tabela
    assert [m["name"] for m in family_sets.machines("cantoneiras")] == ["Peddi 8"]
    with pytest.raises(planning.PlanningError, match="Escolhe uma máquina deste setor."):
        member_machine.apply({"setor": "cantoneiras", "maquina": "prensa", "membros": [],
                              "request_id": "8d1f9a0e-0000-4000-8000-000000000001"})
