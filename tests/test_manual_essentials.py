"""Registo manual só com o essencial (plano de 07/10/2026, Parte 1).

Campos visíveis por setor, valores por defeito, avisos essenciais, «Qtd em falta», peça repetida
sem «por associar» e gravar sempre (sem 409 quando a peça, a origem ou a OF mudaram entretanto).
Os testes com base usam o PostgreSQL descartável de tests/test_manual_to_carteira.py.
"""
import copy
import math
import uuid
from pathlib import Path

import psycopg
import pytest

from app import planning, planning_calculations as calculations, planning_catalogs as catalogs, planning_needs as needs
from app import planning_suggestions as suggestions
from app.raw import calculations as raw_calculations, projection, query, registration as free
from app.raw.edits import prepare
from app.sector import portfolio
from tests.test_manual_to_carteira import (PIECE, TODAY, manual, register, workspace, database, canonical,  # noqa: F401
                                           registry, postgres16)

ROOT = Path(__file__).resolve().parents[1]


def visible(area, group=None):
    fields = sorted(catalogs.arrange(catalogs.fields(), area), key=lambda f: f["order"])
    return [f["id"] for f in fields if f["editor_visible"] and (group is None or f["group"] == group)]


def test_more_options_keeps_only_notes_and_unused_fields_leave_the_editor():
    for area in ("perfis", "cantoneiras"):
        assert visible(area, "extra") == ["notes"]
        assert "remaining_declared" in visible(area, "work")
        assert not set(visible(area)) & catalogs.UNUSED_FIELDS
    assert "picking_year" not in visible("perfis") and "picking_week" in visible("perfis", "piece")
    # Nas cantoneiras também saem Qual., Ø, Largura, Altura, Espessura e Ang. («Tirar todos menos Observações»).
    assert not set(visible("cantoneiras")) & {"grade", "outer_diameter_mm", "width_mm", "height_mm", "thickness_mm", "angle_deg"}
    # O contrato continua com todos os campos: o que já está gravado fica.
    assert catalogs.UNUSED_FIELDS <= {f["id"] for f in catalogs.fields()}
    assert all("required_on_ready" not in f for f in catalogs.fields())
    labels = {f["id"]: f["label"] for f in catalogs.arrange(catalogs.fields(), "cantoneiras")}
    assert labels["notes"] == "Observações" and labels["remaining_declared"] == "Qtd em falta"


def test_defaults_operations_and_two_state_abocardar():
    values, _ = free.normalize({"operation": "", "operation_detail": None}, {"area": "cantoneiras"})
    assert values["operation"] == "119" and values["operation_detail"] == "0"
    values, _ = free.normalize({"operation": "112", "operation_detail": "111"}, {"area": "cantoneiras"})
    assert values["operation"] == "112" and values["operation_detail"] == "111"
    assert free.normalize({}, {"area": "perfis"})[0]["operation"] == "corte"
    for unknown in (None, "", "???", "talvez", False, "-"):
        assert catalogs.abocardar_mark(unknown) == "-"
        assert free.normalize({"abocardar": unknown}, {"area": "perfis"})[0]["abocardar"] == "-"
    for yes in ("X", "x", True, "'X", "Sim"):
        assert catalogs.abocardar_mark(yes) == "X"


def test_cantoneiras_form_suggests_the_default_operations():
    index = suggestions.Index("cantoneiras", [])
    found = suggestions.suggest("cantoneiras", "OF1", idx=index, learned=False)
    assert found["operation"]["value"] == "119" and found["operation_detail"]["value"] == "0"
    assert "operation" not in suggestions.suggest("perfis", "OF1", idx=suggestions.Index("perfis", []), learned=False)


def test_steel_density_when_grade_is_empty_only_for_the_weight():
    piece = {"material_type": "Tubo redondo", "outer_diameter_mm": 88.9, "thickness_mm": 3, "length_mm": 1000,
             "quantity_required": 10}
    expected = math.pi * (88.9 ** 2 - 82.9 ** 2) / 4 / 1e6 * 7850
    empty = calculations.calculate(piece)
    assert empty["values"]["weight_unit"] == pytest.approx(expected)
    assert empty["rules"]["weight_unit"]["source"]["density_kg_m3"] == 7850
    assert calculations.calculate({**piece, "grade": "S355"})["values"]["weight_unit"] == pytest.approx(expected)
    assert calculations.calculate({**piece, "grade": "AISI 304"})["values"]["weight_unit"] is None
    assert calculations.CONTRACT.endswith("-v10")


def test_only_the_essential_warnings_never_blocking():
    values, warnings = free.normalize({"machine": "Inventada", "material_type": "Coisa", "angle_deg": 999,
                                       "abocardar": "???", "quantity_required": "12,5", "cut_date": "amanhã"},
                                      {"area": "perfis"}, sections={})
    assert {(w["field"], w["message"]) for w in warnings} == {
        ("quantity_required", "QTD tem de ser um número inteiro (senão não entra na Carteira)"),
        ("length_mm", "Sem comprimento: sem metros nem horas"),
        ("profile", "Sem área de corte: sem horas")}
    assert values["machine"] == "Inventada" and values["angle_deg"] == 999
    _, none = free.normalize({"machine": "MEBA", "material_type": "Tubo redondo", "outer_diameter_mm": 88.9,
                              "thickness_mm": 3, "length_mm": 1000, "quantity_required": 12}, {"area": "perfis"}, sections={})
    assert none == []
    _, angles = free.normalize({"machine": "", "operation": "Corte", "length_mm": 900, "quantity_required": 3},
                               {"area": "cantoneiras"})
    assert {(w["field"], w["message"]) for w in angles} == {
        ("machine", "Sem máquina: será usada a sugerida ao planear"),
        ("operation", "Operação não numérica: sem horas")}
    # «Por definir» conta como sem máquina, como na Carteira.
    assert [w["field"] for w in free.warnings_for({"machine": "Por definir", "quantity_required": 1, "length_mm": 1}, "perfis")] == ["machine"]
    assert free.ESSENTIAL == set(free.WARNINGS.values())


def test_declared_remaining_is_the_balance_capped_at_the_quantity():
    piece = {"quantity_required": 12, "length_mm": 1000}
    result = calculations.calculate(piece, local_initial=True, declared_remaining=5)
    assert result["values"]["remaining"] == 5 and result["values"]["remaining_m"] == 5
    assert result["operations"][0]["origin"] == "Qtd em falta (registo manual)"
    assert calculations.calculate(piece, local_initial=True, declared_remaining=20)["values"]["remaining"] == 12
    assert calculations.calculate(piece, local_initial=True, declared_remaining="abc")["values"]["remaining"] == 12
    assert calculations.calculate(piece, local_initial=True)["values"]["remaining"] == 12


def test_pdf_piece_without_excel_line_starts_with_nothing_produced():
    def row(sources):
        return {"area": "cantoneiras", "need_id": "n1", "plan_key": None, "sources": sources,
                "values": {"quantity_required": 8, "length_mm": 500, "operation": "119"}, "original": {}, "raw": {},
                "operations": [], "calculation": {}, "warnings": []}
    assert raw_calculations.recalculate(row([{"kind": "pdf"}]), {}, {})["values"]["remaining"] == 8
    assert raw_calculations.recalculate(row([]), {}, {})["values"]["remaining"] == 8
    # Ligada ao Excel mas sem a linha na importação atual: a produção continua desconhecida.
    assert raw_calculations.recalculate(row([{"kind": "plan_line"}]), {}, {})["values"]["remaining"] is None


def test_registered_rows_show_only_essential_warnings_and_are_never_pending():
    row = {"warnings": [], "values": {"remaining": 4, "planning_remaining": 4}, "preparations": [{}]}
    record = {"input_values": {}, "registration_warnings": [
        {"field": "machine", "message": free.WARNINGS["machine"]},
        {"field": "machine", "message": "Seleciona uma opção válida do catálogo desta área."}]}
    free.annotate(row, record, {"identity_pending": True, "identity_candidates": [{"kind": "need", "id": "x"}],
                                "input_values": {}})
    assert row["warnings"] == [free.WARNINGS["machine"]]
    assert row["identity_pending"] is False and row["values"]["planning_remaining"] == 4


def test_changed_workbook_falls_back_to_the_imported_rows(tmp_path):
    path = tmp_path / "Met2_Plan_Perfis.xlsm"
    path.write_bytes(b"ficheiro mudado depois da importacao")
    stat = path.stat()
    assert catalogs.workbook_ranges(str(path), stat.st_mtime_ns, stat.st_size, "hash-da-importacao") == \
        {"ranges": {}, "names": {}, "validations": []}


# Base descartável ------------------------------------------------------------------------------------------


@pytest.fixture()
def essential(manual, monkeypatch):
    # Gravar já não depende do interruptor antigo MES_PLANNING_FREE_ENTRY.
    monkeypatch.delenv("MES_PLANNING_FREE_ENTRY", raising=False)
    with psycopg.connect(manual) as c:
        c.execute((ROOT / "sql" / "027_planning_local_orders.sql").read_text())
        c.execute("TRUNCATE planning_mtg.local_orders CASCADE")
    return manual


def rows_of(reference):
    return query.listing({"area": "perfis", "q": reference, "population": "all"})["rows"]


def test_excel_file_changed_on_disk_does_not_block_saving(essential, tmp_path):
    path = tmp_path / "Met2_Plan_Perfis.xlsm"
    path.write_bytes(b"outro ficheiro")
    with psycopg.connect(essential) as c:
        c.execute("UPDATE audit_mtg.snapshots SET source_path=%s,source_sha256='hash-antigo' WHERE snapshot_id='s1'", (str(path),))
    assert catalogs.catalog("perfis")["version"] == "s1"
    saved = register({**PIECE, "component_ref": "MAN-WB"}, catalog_version="catalogo-antigo")
    assert saved["record_status"] == "ready"


def test_similar_piece_links_to_the_only_excel_line_and_keeps_its_balance(essential):
    with psycopg.connect(essential) as c:
        c.execute("DELETE FROM raw_mtg.plan_production_rows WHERE source_line_id='s1:11'")
    projection.rebuild("perfis")
    saved = register({"component_ref": "REF-A", "quantity_required": "100", "length_mm": "3003"})
    with planning.connect(readonly=True) as c:
        sources = c.execute("SELECT kind,source_id FROM planning_mtg.need_sources WHERE need_id=%s", (saved["need_id"],)).fetchall()
        need = c.execute("SELECT identity_pending,specification FROM planning_mtg.needs WHERE id=%s", (saved["need_id"],)).fetchone()
    assert [(s["kind"], s["source_id"]) for s in sources] == [("plan_line", "s1:10")]
    assert not need["identity_pending"] and need["specification"]["profile"] == "88.9x3"
    rows = rows_of("REF-A")
    assert len(rows) == 1 and rows[0]["need_id"] == str(saved["need_id"])
    assert rows[0]["values"]["remaining"] == 36 and not rows[0]["identity_pending"]


def test_similar_piece_with_several_excel_lines_counts_as_its_own_piece(essential):
    saved = register({"component_ref": "REF-A", "quantity_required": "5", "length_mm": "1200"})
    with planning.connect(readonly=True) as c:
        assert not c.execute("SELECT 1 FROM planning_mtg.need_sources WHERE need_id=%s", (saved["need_id"],)).fetchone()
        assert not c.execute("SELECT bool_or(identity_pending) p FROM planning_mtg.needs").fetchone()["p"]
    mine = next(r for r in rows_of("REF-A") if r["need_id"] == str(saved["need_id"]))
    assert mine["values"]["remaining"] == 5 and mine["values"]["planning_remaining"] == 5


def test_declared_remaining_feeds_the_carteira(essential):
    saved = register({**PIECE, "component_ref": "MAN-QF", "remaining_declared": "4"})
    line = next(x for x in portfolio.current("perfis", today=TODAY)["lines"] if x["key"] == str(saved["need_id"]))
    assert line["quantity"] == 12 and line["pieces"] == 4


def test_changed_revision_saves_only_the_changed_fields_on_top(essential):
    first = register({**PIECE, "component_ref": "MAN-REV"})
    # Outra pessoa (ou uma importação) grava entretanto.
    register({**PIECE, "component_ref": "MAN-REV", "notes": "Outra pessoa"}, need_id=first["need_id"],
             expected_revision=first["revision"])
    stale = register({**PIECE, "component_ref": "MAN-REV", "machine": "Peddi"}, need_id=first["need_id"],
                     expected_revision=first["revision"], changed_fields=["machine"])
    values = needs.detail(stale["need_id"])["records"][0]["values_json"]
    assert values["machine"] == "Peddi" and values["notes"] == "Outra pessoa"
    # Sem a lista de campos mudados (cliente antigo): grava tudo o que trouxe, sem 409.
    old_client = register({**PIECE, "component_ref": "MAN-REV", "team": "Equipa 9"}, need_id=first["need_id"],
                          expected_revision=first["revision"])
    values = needs.detail(old_client["need_id"])["records"][0]["values_json"]
    assert values["team"] == "Equipa 9" and values["machine"] == "MEBA" and values["notes"] == "Outra pessoa"


def test_pdf_from_another_order_uses_the_pdf_order_and_starts_with_nothing_produced(essential, monkeypatch):
    from app.dossiers import store
    piece = {"component_ref": "PDF-1", "material_type": "Tubo redondo", "profile": "88.9x3", "outer_diameter_mm": 88.9,
             "thickness_mm": 3, "length_mm": 1500, "quantity_required": 9, "machine": "MEBA"}
    document = {"id": "doc-of", "revision": 1, "production_order": "OF4200", "status": "ready",
                "pieces": [{"id": "p1", "revision": 1, "state": "ready", "values": piece}]}
    monkeypatch.setattr(store, "get_document", lambda ident: copy.deepcopy(document))
    saved = prepare({"request_id": str(uuid.uuid4()), "actor": "Teste", "area": "perfis", "production_order_no": "OF999999",
                     "source": {"kind": "pdf", "id": "doc-of/p1", "version": "1:1"}, "values": piece, "record_status": "ready"})
    assert needs.detail(saved["need_id"])["need"]["production_order_no"] == "OF4200"
    row = next(r for r in rows_of("PDF-1") if r["need_id"] == str(saved["need_id"]))
    assert row["values"]["remaining"] == 9
    # A origem mudou com o formulário aberto: grava na mesma, por cima da versão atual.
    document["revision"] = 2
    again = prepare({"request_id": str(uuid.uuid4()), "actor": "Teste", "area": "perfis", "production_order_no": "OF4200",
                     "source": {"kind": "pdf", "id": "doc-of/p1", "version": "1:1"}, "need_id": saved["need_id"],
                     "expected_revision": saved["revision"], "values": {**piece, "team": "Equipa 5"},
                     "changed_fields": ["team"], "record_status": "ready"})
    assert needs.detail(again["need_id"])["records"][0]["values_json"]["team"] == "Equipa 5"
