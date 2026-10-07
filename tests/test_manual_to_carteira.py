"""Registo manual → Tabela (RAW) → Carteira → Planear, numa base PostgreSQL descartável (06/10/2026).

Faz o mesmo que o botão «Guardar» do ecrã /planeamento/manual (POST necessidades/registar → raw.edits.prepare)
com entrada livre ligada, como em produção. Depois lê a geração planning:perfis, a Carteira
(app.sector.portfolio.current) e grava «Planear» (app.sector.selection.apply). Sem camada de pesquisa
(MES_PLANNING_V2_ENABLED desligado): a máquina efetiva é a da Tabela, como nas linhas sem ficha técnica.
"""
import uuid
from datetime import date
from pathlib import Path

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app import planning
from app.raw import query
from app.raw.edits import prepare
from app.raw.registration import iso_date
from app.sector import planning_status, portfolio, scope, selection
from tests.test_raw_workspace import workspace, database, canonical, registry, postgres16  # noqa: F401 (fixtures)

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 10, 6)


@pytest.fixture()
def manual(workspace, monkeypatch):
    monkeypatch.setenv("MES_PLANNING_FREE_ENTRY", "1")
    monkeypatch.delenv("MES_PLANNING_V2_ENABLED", raising=False)
    with psycopg.connect(workspace) as c:
        c.execute((ROOT / "sql" / "042_free_registration.sql").read_text())
        if not c.execute("SELECT to_regclass('planning_mtg.sector_member_machine')").fetchone()[0]:
            for name in ("039_schema_migrations.sql", "040_sector_selection.sql", "046_sector_member_selection.sql",
                         "047_member_selection_no_phase.sql", "048_family_sets_member_machine.sql"):
                c.execute((ROOT / "sql" / name).read_text())
        c.execute("TRUNCATE planning_mtg.sector_selection, planning_mtg.sector_decision_events, planning_mtg.sector_member_selection, "
                  "planning_mtg.sector_selection_requests, planning_mtg.sector_member_machine, planning_mtg.sector_family_sets")
    from app.raw import projection
    projection.rebuild("perfis")  # geração de partida, como em produção
    portfolio._cache.clear()
    portfolio._current_cache.clear()
    return workspace


def register(values, **extra):
    return prepare({"request_id": str(uuid.uuid4()), "actor": "Teste", "area": "perfis", "production_order_no": "OF4200",
                    "catalog_version": "s1", "record_status": "ready", "values": values, "decisions": {}, **extra})


PIECE = {"cut_date": "20/10/2026", "component_ref": "MAN-1", "material_type": "Tubo redondo", "profile": "88.9x3",
         "quantity_required": "12", "outer_diameter_mm": "88.9", "thickness_mm": "3", "length_mm": "1500", "angle_deg": "0",
         "team": "Equipa 5", "pavilion": "1", "machine": "MEBA", "operation": "corte"}


def line_of(reference):
    lines = [x for x in portfolio.current("perfis", today=TODAY)["lines"] if x["reference"] == reference]
    assert len(lines) == 1, lines
    return lines[0]


def test_manual_piece_reaches_raw_carteira_and_can_be_planned(manual):
    saved = register(PIECE)
    assert saved["record_status"] == "ready" and saved["publication"]["areas"].get("perfis")
    # Data dd/mm/aaaa convertida (antes ficava texto e a linha sem prazo); nenhum aviso de data.
    assert not [w for w in saved["registration_warnings"] if w["field"] == "cut_date"]

    with planning.connect(readonly=True) as c:
        gen = query.generation(c, "perfis")
    assert gen["dataset"] == "planning:perfis"
    rows = query.listing({"area": "perfis", "q": "MAN-1"})["rows"]
    assert len(rows) == 1
    row = rows[0]
    # A Tabela mostra o que foi escrito; o valor calculado (Carteira, prazo) é a data ISO.
    assert iso_date(row["values"]["cut_date"]) == "2026-10-20" and row["values"]["machine"] == "MEBA"
    assert row["values"]["team"] == "Equipa 5" and float(row["values"]["quantity_required"]) == 12

    line = line_of("MAN-1")
    assert line["machine"] == "MEBA" and line["pieces"] == 12 and line["cut_date"] == date(2026, 10, 20)
    status = portfolio.status_of(line, selection.current("perfis"))
    assert status["nesting"] and planning_status.STATUS["nesting"] == "Planeado para nesting"

    result = selection.apply({"setor": "perfis", "acao": "selecionar", "request_id": str(uuid.uuid4()),
                              "membros": [{"chave": line["key"], "token": None}]}, data=portfolio.current("perfis", today=TODAY))
    assert result["changed"] == 1 and result["skipped_no_machine"] == 0
    assert portfolio.status_of(line, selection.current("perfis"))["planeado"]

    # A Equipa da linha manual chega ao Gantt (scope.local_rows lê-a para a preferência de posto).
    record = {"values_json": row["values"], "detail": {"calculation": {}}, "area": "perfis", "row_key": line["key"]}
    gantt_rows, _ = scope.local_rows([record], {})
    assert gantt_rows[0]["equipa"] == "Equipa 5"


def test_manual_piece_without_machine_cannot_be_planned(manual):
    register({**PIECE, "component_ref": "MAN-2", "machine": ""})
    line = line_of("MAN-2")
    assert portfolio.status_of(line, selection.current("perfis"))["sem_maquina"]
    with pytest.raises(planning.PlanningError):
        selection.apply({"setor": "perfis", "acao": "selecionar", "request_id": str(uuid.uuid4()),
                         "membros": [{"chave": line["key"], "token": None}]}, data=portfolio.current("perfis", today=TODAY))


def test_registered_excel_line_keeps_the_excel_notes(manual):
    """Peça registada a partir de uma linha do Excel: Descrição/Observações vêm da linha de origem."""
    with psycopg.connect(manual) as c:
        source = c.execute("SELECT source_line_id, row_data FROM raw_mtg.plan_production_rows WHERE snapshot_id='s1' "
                           "ORDER BY excel_row LIMIT 1").fetchone()
        c.execute("UPDATE raw_mtg.plan_production_rows SET row_data=%s WHERE snapshot_id='s1' AND source_line_id=%s",
                  (Jsonb({**source[1], "Observações": "Fabricar após validação do cliente", "Descrição": "anulada"}), source[0]))
    with planning.connect(readonly=True) as c:
        values = __import__("app.planning_needs", fromlist=["x"]).source_data({"kind": "plan_line", "id": source[0]}, "perfis", c)["values"]
    saved = register({**values, "machine": "MEBA", "team": "Equipa 5"}, source={"kind": "plan_line", "id": source[0], "version": "s1"})
    with planning.connect(readonly=True) as c:
        _, head = portfolio._stamp(c, "perfis", date.today())  # a geração que a Carteira lê
        rows = c.execute(portfolio._SQL, {"dataset": "planning:perfis", "generation": head["id"]}).fetchall()
    mine = [r for r in rows if not r["row_key"].startswith("macro:") and str(r["row_key"]) == str(saved["need_id"])]
    assert mine, [r["row_key"] for r in rows]
    assert mine[0]["observations"] == "Fabricar após validação do cliente" and mine[0]["notes"] == "anulada"


def test_only_of_quantity_and_length_save_and_reach_the_carteira(manual, monkeypatch):
    """Só o essencial (07/10/2026): OF + QTD + Comp. grava, sem o interruptor antigo, e a linha entra na Carteira."""
    monkeypatch.delenv("MES_PLANNING_FREE_ENTRY")
    saved = register({"quantity_required": "7", "length_mm": "2500"})
    assert saved["record_status"] == "ready"
    # Avisos discretos, nunca a impedir: sem máquina e sem área de corte (sem horas).
    assert {w["field"] for w in saved["registration_warnings"]} == {"machine", "profile"}
    lines = [x for x in portfolio.current("perfis", today=TODAY)["lines"] if x["key"] == str(saved["need_id"])]
    assert len(lines) == 1 and lines[0]["pieces"] == 7 and lines[0]["metres"] == 17.5 and not lines[0]["machine"]
