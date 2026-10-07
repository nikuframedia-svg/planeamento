"""Planear numa linha sem máquina usa a máquina sugerida (plano de 07/10/2026), numa base PostgreSQL descartável.

Registo manual sem máquina → Tabela → Carteira → Planear: a sugerida fica como escolha da Carteira, a linha fica
«Planeado» e entra no âmbito do Gantt (scope.planning_lines) com essa máquina. Sem camada de pesquisa a sugestão
vem do teste; a cadeia real (ficha técnica, previsão, máquinas do setor) está em selection.suggested_machines.
"""
import uuid

from app import planning
from app.sector import machine_choice, portfolio, scope, selection
from tests.test_manual_to_carteira import PIECE, TODAY, line_of, manual, register  # noqa: F401 (fixtures)
from tests.test_raw_workspace import workspace, database, canonical, registry, postgres16  # noqa: F401 (fixtures)


def test_planear_without_machine_saves_the_suggestion_and_the_line_reaches_the_gantt(manual, monkeypatch):
    register({**PIECE, "component_ref": "MAN-3", "machine": ""})
    line = line_of("MAN-3")
    assert not line["machine"] and portfolio.status_of(line, selection.current("perfis"))["sem_maquina"]
    suggestion = {"resource_id": "rid-meba", "machine": "MEBA", "origin": "previsao", "label": "Única candidata"}
    monkeypatch.setattr(selection, "suggested_machines", lambda sector, lines, **kw: {x["key"]: suggestion for x in lines})

    result = selection.apply({"setor": "perfis", "acao": "selecionar", "request_id": str(uuid.uuid4()),
                              "membros": [{"chave": line["key"], "token": portfolio.member_token(line, 0)}]},
                             data=portfolio.current("perfis", today=TODAY))
    assert result["changed"] == 1 and result["suggested_machine"] == 1 and result["skipped_count"] == 0

    # A Carteira mostra a máquina como escolha da Carteira (muda-se com «Atribuir máquina») e a linha fica «Planeado».
    planned = line_of("MAN-3")
    assert planned["machine"] == "MEBA" and planned["machine_source"] == "carteira"
    assert portfolio.status_of(planned, selection.current("perfis"))["planeado"]

    # O Gantt recebe a linha com a máquina efetiva da Carteira.
    with planning.connect(readonly=True) as c:
        records, pending = scope.planning_lines(c, scope.read(c), ["perfis"])
        ctx = machine_choice.context("perfis", conn=c)
    mine = [r for r in records if r["row_key"] == planned["key"]]
    assert len(mine) == 1 and mine[0]["effective_machine"]["source"] == "carteira"
    assert mine[0]["effective_machine"]["machine"] == "MEBA" and not [p for p in pending if "sem máquina" in p["reason"]]
    assert ctx["members"][planned["key"]]["machine_name"] == "MEBA"
