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
    assert calculations.CONTRACT.endswith("-v11")


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


def test_empty_and_non_integer_quantity_have_their_own_warning():
    assert [w["message"] for w in free.normalize({"machine": "M", "length_mm": 1}, {"area": "perfis"})[1]] == ["Sem QTD: não entra na Carteira"]
    assert [w["message"] for w in free.normalize({"machine": "M", "length_mm": 1, "quantity_required": "2,5"}, {"area": "perfis"})[1]] == \
        ["QTD tem de ser um número inteiro (senão não entra na Carteira)"]


def test_sections_are_read_once_per_connection(monkeypatch):
    calls = []
    monkeypatch.setattr(raw_calculations, "_sections_table", lambda conn, snapshot: calls.append(snapshot) or {})

    class Connection:
        pass
    first, second = Connection(), Connection()
    for _ in range(3):
        raw_calculations.sections(first, "s1")
    raw_calculations.sections(second, "s1")
    assert calls == ["s1", "s1"]


def test_declared_remaining_expires_with_production_recorded_after_it():
    piece = {"quantity_required": 12, "length_mm": 1000}
    ocr = lambda quantity: [{"operation": "corte", "ocr_records": [{"record_id": 1, "quantity": quantity, "validated": True}]}]
    local = "Condição inicial local"
    assert calculations.calculate(piece, operations=ocr(5), declared_remaining=5, declared_produced=0, declared_origin=local)["values"]["remaining"] == 0
    assert calculations.calculate(piece, operations=ocr(2), declared_remaining=5, declared_produced=0, declared_origin=local)["values"]["remaining"] == 3
    # Produção desconhecida quando foi escrita: não se desconta nada.
    assert calculations.calculate(piece, operations=ocr(2), declared_remaining=5, declared_origin=local)["values"]["remaining"] == 5
    measured = calculations.calculate(piece, operations=ocr(2), declared_remaining=5, declared_produced=0, declared_origin=local)["operations"][0]
    assert measured["measured"] == 2 and measured["measured_origin"] == "OCR validado" and measured["origin"] == calculations.DECLARED_ORIGIN


def test_declared_remaining_discounts_only_within_the_same_evidence_source():
    piece = {"quantity_required": 100, "length_mm": 1000}
    # Escrita com o OCR a 20; agora conta o contador do Excel (60): outra fonte, não se desconta nada.
    excel = calculations.calculate(piece, raw={"Ser.": 60}, declared_remaining=30, declared_produced=20, declared_origin="OCR validado")
    assert excel["values"]["remaining"] == 30 and excel["operations"][0]["measured_origin"] == "Excel provisório"
    assert excel["operations"][0]["declared_source_changed"]
    # A mesma fonte (Excel 50 → 60) desconta os 10.
    same = calculations.calculate(piece, raw={"Ser.": 60}, declared_remaining=30, declared_produced=50, declared_origin="Excel provisório")
    assert same["values"]["remaining"] == 20 and not same["operations"][0]["declared_source_changed"]


def test_mtg3_w_week_without_year_gets_the_capacity_year():
    from datetime import date
    from app import planning_dates
    result = calculations.calculate({"quantity_required": 5, "length_mm": 100, "operation": "119", "imported_week": 21.0},
                                    area="cantoneiras", today=date(2026, 11, 25))
    year = planning_dates.infer_iso_year(21, date(2026, 11, 25), prefer_past=True)
    assert result["values"]["expected_week"] == f"{year}-W21" and result["values"]["expected_year"] == year == 2026
    assert result["rules"]["expected_week"]["source"] == "Semana W importada — ano deduzido"


def test_hidden_dates_are_read_only_in_the_table():
    from app.raw import contracts
    fields = {f["id"]: f for f in contracts.fields("perfis")}
    for name in free.HIDDEN_DATES:
        assert not fields[name]["editable"], name
    assert fields["cut_date"]["editable"] and fields["machine"]["editable"]


def test_an_unreadable_typed_number_counts_as_a_contradiction():
    from app.raw.edits import agrees
    line = {"component_ref": "REF-A", "quantity_required": 100, "length_mm": 3003}
    assert agrees({"component_ref": "REF-A", "quantity_required": "100"}, line)
    assert not agrees({"component_ref": "REF-A", "quantity_required": "1OO"}, line)
    assert not agrees({"component_ref": "REF-A", "length_mm": "3oo3"}, line)


def test_v2_research_overlay_keeps_the_declared_remaining(monkeypatch):
    from app.gantt import integrated, research
    from tests.test_integrated_gantt import _raw_row, _research_row
    monkeypatch.setattr(research, "enabled", lambda: True)
    monkeypatch.setattr(research, "load", lambda c: {"rows": [_research_row()], "head": {"version_id": "v"}})
    row = _raw_row(3, {"Ser.": None, "Qtd em Falta": 8})
    row["calculation"]["production_sources"][0].update(origin=calculations.DECLARED_ORIGIN, value=5)
    research.overlay_rows(None, "perfis", [row])
    assert row["values"]["remaining"] == 3 and row["values"]["planning_remaining"] == 3
    assert not any(s.get("v2_evidence") for s in row["calculation"]["production_sources"])
    from app.raw import query
    monkeypatch.setattr(query, "generation", lambda c, area: {})
    monkeypatch.setattr(query, "source", lambda g: ("", []))
    record = {"area": "perfis", "row_key": row["key"], "values_json": row["values"],
              "detail": {"selection_aliases": row["selection_aliases"], "raw": row["raw"], "calculation": row["calculation"]}}
    research_row = {**_research_row(), "matched_application_key": row["key"]}
    balances = research.application_balances(None, [research_row], records=[record])
    assert integrated.balance({**research_row, **balances["op1"]})["planning_remaining"] == 3


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
    # O worker continua a parar com o Excel diferente (as horas de turno nunca ficam vazias); quem grava não.
    from app.raw import workbooks
    with planning.connect() as c:
        with pytest.raises(planning.PlanningError) as stopped:
            workbooks.capture(c, "perfis")
        assert stopped.value.status == 409
    with planning.connect() as c, workbooks.interactive():
        assert workbooks.capture(c, "perfis") is None


def test_similar_piece_links_to_the_only_excel_line_and_keeps_its_balance(essential):
    with psycopg.connect(essential) as c:
        c.execute("DELETE FROM raw_mtg.plan_production_rows WHERE source_line_id='s1:11'")
    projection.rebuild("perfis")
    saved = register({"component_ref": "REF-A", "quantity_required": "100", "length_mm": "3003"})
    assert saved["excel_link"] == "s1:10"
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


def sources_of(need_id):
    with planning.connect(readonly=True) as c:
        return [(s["kind"], s["source_id"]) for s in
                c.execute("SELECT kind,source_id FROM planning_mtg.need_sources WHERE need_id=%s ORDER BY source_id", (need_id,)).fetchall()]


def balances(reference):
    return sorted((r.get("plan_key") or "", r["need_id"] or "", r["values"]["remaining"]) for r in rows_of(reference))


def only_line_ref_a(essential):
    with psycopg.connect(essential) as c:
        c.execute("DELETE FROM raw_mtg.plan_production_rows WHERE source_line_id='s1:11'")
    projection.rebuild("perfis")


def from_excel_line(key="s1:10", changed=None, **values):
    return prepare({"request_id": str(uuid.uuid4()), "actor": "Teste", "area": "perfis", "production_order_no": "OF4200",
                    "source": {"kind": "plan_line", "id": key, "version": "s1"}, "record_status": "ready", "decisions": {},
                    **({"changed_fields": changed} if changed is not None else {}),
                    "values": {"component_ref": "REF-A", "quantity_required": 100, "length_mm": 3003, "profile": "88.9x3",
                               "material_type": "Tubo redondo", "operation": "corte", **values}})


def test_a_different_length_does_not_absorb_the_only_excel_line(essential):
    only_line_ref_a(essential)
    saved = register({"component_ref": "REF-A", "quantity_required": "5", "length_mm": "2000"})
    assert sources_of(saved["need_id"]) == []
    assert balances("REF-A") == sorted([("s1:10", "", 36), ("", str(saved["need_id"]), 5)])


def test_b_a_free_line_among_several_is_not_taken(essential):
    first = from_excel_line()
    other = register({"component_ref": "REF-A", "profile": "200x5", "quantity_required": "3", "length_mm": "500"})
    assert sources_of(other["need_id"]) == [] and sources_of(first["need_id"]) == [("plan_line", "s1:10")]
    assert balances("REF-A") == sorted([("s1:10", str(first["need_id"]), 36), ("s1:11", "", 36), ("", str(other["need_id"]), 3)])


def test_c_an_identical_piece_never_puts_two_lines_on_one_need(essential):
    with psycopg.connect(essential) as c:
        c.execute("UPDATE raw_mtg.plan_production_rows SET profile_type='88.9x3' WHERE source_line_id='s1:11'")
        c.execute("UPDATE analytics_mtg.kanban_plan_lines SET profile_type='88.9x3' WHERE plan_key='s1:11'")
    projection.rebuild("perfis")
    first = from_excel_line()
    register({"component_ref": "REF-A", "quantity_required": "100", "length_mm": "3003", "profile": "88.9x3",
              "material_type": "Tubo redondo"})
    assert sources_of(first["need_id"]) == [("plan_line", "s1:10")]
    assert sum(r[2] for r in balances("REF-A")) == 72


def test_d_a_different_quantity_does_not_absorb_the_only_excel_line(essential):
    only_line_ref_a(essential)
    saved = register({"component_ref": "REF-A", "quantity_required": "5", "length_mm": "3003"})
    assert sources_of(saved["need_id"]) == []
    assert balances("REF-A") == sorted([("s1:10", "", 36), ("", str(saved["need_id"]), 5)])


def test_untouched_abocardar_keeps_the_excel_mark_when_linking(essential):
    with psycopg.connect(essential) as c:
        c.execute("DELETE FROM raw_mtg.plan_production_rows WHERE source_line_id='s1:11'")
        c.execute("""UPDATE raw_mtg.plan_production_rows SET row_data=row_data||'{"Aborc.":"X","Aboc.":10}' WHERE source_line_id='s1:10'""")
    projection.rebuild("perfis")
    saved = register({"component_ref": "REF-A", "quantity_required": "100", "length_mm": "3003", "abocardar": False})
    assert sources_of(saved["need_id"]) == [("plan_line", "s1:10")]
    row = next(r for r in rows_of("REF-A") if r["need_id"] == str(saved["need_id"]))
    assert row["values"]["abocardar"] == "X" and row["values"]["boc_remaining"] == 90


def test_new_piece_from_a_vanished_excel_line_keeps_the_form_values(essential):
    saved = register({**PIECE, "component_ref": "MAN-VAN", "machine": "Peddi"},
                     source={"kind": "plan_line", "id": "s1:999", "version": "s0"}, changed_fields=["machine"])
    detail = needs.detail(saved["need_id"])
    spec, record = detail["need"]["specification"], detail["records"][0]["values_json"]
    assert spec["component_ref"] == "MAN-VAN" and spec["quantity_required"] == 12 and spec["length_mm"] == 1500
    assert record["machine"] == "Peddi" and record["profile"] == "88.9x3"


def test_declared_remaining_keeps_the_production_known_when_typed(essential):
    only_line_ref_a(essential)
    linked = from_excel_line()
    typed = from_excel_line(changed=["remaining_declared"], remaining_declared="10")
    assert typed["need_id"] == linked["need_id"]
    with planning.connect(readonly=True) as c:
        values = c.execute("SELECT values_json FROM planning_mtg.records WHERE need_id=%s", (linked["need_id"],)).fetchone()["values_json"]
    assert values["remaining_declared"] == 10 and values["remaining_declared_produced"] == 64
    assert values["remaining_declared_origin"] == "Excel provisório"
    # O Excel regista mais 6 cortadas: a «Qtd em falta» escrita desconta-as.
    with psycopg.connect(essential) as c:
        c.execute("UPDATE raw_mtg.plan_production_rows SET row_data=row_data||'{\"Ser.\":70}' WHERE source_line_id='s1:10'")
    projection.rebuild("perfis", force=True)  # a importação mudada no próprio sítio só se vê com force
    assert next(r for r in rows_of("REF-A") if r["need_id"] == str(typed["need_id"]))["values"]["remaining"] == 4
    # A pré-visualização de um valor escrito de novo já não desconta; sem isso continua a mostrar o saldo atual.
    from app.raw import preview
    form = {"area": "perfis", "need_id": typed["need_id"], "values": {"component_ref": "REF-A", "quantity_required": 100, "length_mm": 3003,
            "profile": "88.9x3", "material_type": "Tubo redondo", "operation": "corte", "remaining_declared": "10"}}
    assert preview.preview(form)["row"]["values"]["remaining"] == 4
    assert preview.preview({**form, "changed_fields": ["remaining_declared"]})["row"]["values"]["remaining"] == 10
    # Voltar a escrever o mesmo valor recomeça a contagem a partir da produção de agora.
    from_excel_line(changed=["remaining_declared"], remaining_declared="10")
    assert next(r for r in rows_of("REF-A") if r["need_id"] == str(typed["need_id"]))["values"]["remaining"] == 10
    # Limpar o campo devolve o saldo calculado.
    from_excel_line(changed=["remaining_declared"], remaining_declared="")
    assert next(r for r in rows_of("REF-A") if r["need_id"] == str(typed["need_id"]))["values"]["remaining"] == 30


def test_hidden_dates_of_registered_pieces_do_not_drive_the_deadline(essential):
    saved = register({**PIECE, "component_ref": "MAN-DATE", "expected_date": "2026-09-23", "planned_week": 39, "planned_year": 2026})
    with planning.connect(readonly=True) as c:
        stored = c.execute("SELECT values_json FROM planning_mtg.records WHERE need_id=%s", (saved["need_id"],)).fetchone()["values_json"]
    assert stored["expected_date"] == "2026-09-23"
    row = next(r for r in rows_of("MAN-DATE"))
    assert row["values"]["expected_week"] == "2026-W43"
    assert all(p["values_json"]["expected_date"] is None and p["values_json"]["planned_week"] is None for p in row["preparations"])


def test_a_typed_value_is_kept_even_when_the_source_passes_through_it(essential, monkeypatch):
    from app.dossiers import store
    piece = {"component_ref": "PDF-K", "material_type": "Tubo redondo", "profile": "88.9x3", "outer_diameter_mm": 88.9,
             "thickness_mm": 3, "length_mm": 1000, "quantity_required": 9, "machine": "MEBA"}
    document = {"id": "doc-k", "revision": 1, "production_order": "OF4200", "status": "ready",
                "pieces": [{"id": "p1", "revision": 1, "state": "ready", "values": piece}]}
    monkeypatch.setattr(store, "get_document", lambda ident: copy.deepcopy(document))
    saved = prepare({"request_id": str(uuid.uuid4()), "actor": "Teste", "area": "perfis", "production_order_no": "OF4200",
                     "source": {"kind": "pdf", "id": "doc-k/p1", "version": "1:1"}, "values": {**piece, "length_mm": 1200},
                     "changed_fields": ["length_mm"], "record_status": "ready"})

    def field(name):
        return next(f for f in needs.detail(saved["need_id"])["fields"] if f["field"] == name and f["scope"] == "piece")
    assert field("length_mm")["human_decision"] == "write" and field("thickness_mm")["human_decision"] in (None, "accept")
    for revision, length, thickness in ((2, 1200, 3), (3, 1500, 4)):
        document["revision"] = revision
        document["pieces"][0]["values"] = {**piece, "length_mm": length, "thickness_mm": thickness}
        assert field("length_mm")["value"] == 1200
    assert field("length_mm")["requires_review"] and field("thickness_mm")["value"] == 4


def test_empty_cantoneiras_operation_keeps_the_excel_operation(essential):
    with psycopg.connect(essential) as c:
        c.execute("""UPDATE raw_mtg.plan_production_rows SET row_data=row_data||'{"1ª Oper.":"112"}' WHERE source_line_id='c1:10'""")
    projection.rebuild("cantoneiras")
    saved = prepare({"request_id": str(uuid.uuid4()), "actor": "Teste", "area": "cantoneiras", "production_order_no": "OF4200",
                     "source": {"kind": "plan_line", "id": "c1:10", "version": "c1"}, "record_status": "ready", "decisions": {},
                     "values": {"component_ref": "REF-A", "quantity_required": 100, "length_mm": 5291, "operation": "", "machine": "Ficep"}})
    assert [o["code"] for o in needs.detail(saved["need_id"])["operations"]] == ["112"]


def test_suggested_values_neither_block_nor_overwrite_the_excel_line(essential):
    from app import planning_suggestions
    only_line_ref_a(essential)
    typed = {"component_ref": "REF-A", "quantity_required": "100"}
    suggested = {k: s["value"] for k, s in planning_suggestions.suggest("perfis", "OF4200", "REF-A", values=typed, learned=False).items()}
    # A Designação 88.9x3 sugere Ø e Espessura que o Excel não tem: antes impediam a ligação e criavam uma peça a mais.
    assert suggested.get("outer_diameter_mm") == 88.9 and suggested.get("thickness_mm") == 3
    form = {**suggested, "team": "Equipa sugerida", "machine": "Máquina sugerida", **typed}
    saved = register(form, changed_fields=list(typed))
    assert saved["excel_link"] == "s1:10" and sources_of(saved["need_id"]) == [("plan_line", "s1:10")]
    detail = needs.detail(saved["need_id"])
    spec, record = detail["need"]["specification"], detail["records"][0]["values_json"]
    assert spec["outer_diameter_mm"] is None and spec["thickness_mm"] is None and spec["profile"] == "88.9x3"
    # A Máquina do Excel ganha à sugerida; a Equipa, que o Excel não tem, fica a sugerida.
    assert record["machine"] == "MEBA" and record["team"] == "Equipa sugerida"
    assert next(r for r in rows_of("REF-A") if r["need_id"] == str(saved["need_id"]))["values"]["remaining"] == 36


def test_an_unreadable_quantity_creates_its_own_piece(essential):
    only_line_ref_a(essential)
    saved = register({"component_ref": "REF-A", "quantity_required": "1OO", "length_mm": "3003"},
                     changed_fields=["component_ref", "quantity_required", "length_mm"])
    assert saved["excel_link"] is None and sources_of(saved["need_id"]) == []


def test_untouched_operation_fields_follow_a_new_excel_import(essential):
    linked = from_excel_line(changed=["machine"], machine="Peddi")
    with psycopg.connect(essential) as c:
        c.execute("INSERT INTO audit_mtg.snapshots SELECT 's2',dataset_id,source_filename,source_path,source_sha256,now()+interval '1 second' FROM audit_mtg.snapshots WHERE snapshot_id='s1'")
        for table in ("raw_mtg.plan_production_rows", "analytics_mtg.kanban_plan_lines", "core_mtg.production_orders", "raw_mtg.cpis_rows",
                      "raw_mtg.other_sheet_rows", "raw_mtg.machine_rows"):
            columns = [r[0] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position", tuple(table.split("."))).fetchall()]
            selected = ["'s2'" if k == "snapshot_id" else "replace(" + k + ",'s1:','s2:')" if k in ("source_line_id", "plan_key") else k for k in columns]
            c.execute("INSERT INTO " + table + " SELECT " + ",".join(selected) + " FROM " + table + " WHERE snapshot_id='s1'")
        c.execute("""UPDATE raw_mtg.plan_production_rows SET cut_date='2026-12-15',team='Equipa 7',row_data=row_data||'{"Máquina Corte":"Ficep"}'
                     WHERE source_line_id='s2:10'""")
    detail = needs.detail(linked["need_id"])  # a importação nova é vista ao abrir (ou pelo worker)
    record = detail["records"][0]
    assert record["values_json"]["cut_date"] == "2026-12-15" and record["values_json"]["team"] == "Equipa 7"
    assert record["values_json"]["machine"] == "Peddi"
    machine = next(f for f in detail["fields"] if f["field"] == "machine" and f["scope"] == str(record["operation_id"]))
    assert machine["requires_review"] and machine["suggestion"] == "Ficep" and machine["human_decision"] in ("write", "select")
    projection.rebuild("perfis")
    row = next(r for r in rows_of("REF-A") if r["need_id"] == str(linked["need_id"]))
    assert row["plan_key"] == "s2:10" and row["values"]["cut_date"] == "2026-12-15" and row["values"]["machine"] == "Peddi"


def new_import_with_the_same_excel(essential):
    with psycopg.connect(essential) as c:
        c.execute("INSERT INTO audit_mtg.snapshots SELECT 's2',dataset_id,source_filename,source_path,source_sha256,now()+interval '1 second' FROM audit_mtg.snapshots WHERE snapshot_id='s1'")
        for table in ("raw_mtg.plan_production_rows", "analytics_mtg.kanban_plan_lines", "core_mtg.production_orders", "raw_mtg.cpis_rows",
                      "raw_mtg.other_sheet_rows", "raw_mtg.machine_rows"):
            columns = [r[0] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position", tuple(table.split("."))).fetchall()]
            selected = ["'s2'" if k == "snapshot_id" else "replace(" + k + ",'s1:','s2:')" if k in ("source_line_id", "plan_key") else k for k in columns]
            c.execute("INSERT INTO " + table + " SELECT " + ",".join(selected) + " FROM " + table + " WHERE snapshot_id='s1'")


def test_a_table_cell_edit_does_not_freeze_the_rest_of_the_line(essential):
    # F20 (08/10): editar uma célula na Tabela grava a linha inteira. O perfil inteiro sugerido (6000/12000) não passa
    # a «manual» e o que ninguém escreveu (Chanfro, Requisição) continua a seguir o Excel.
    from app.raw import edits
    only_line_ref_a(essential)
    listed = query.listing({"area": "perfis", "q": "REF-A"})
    line = next(r for r in listed["rows"] if r["plan_key"] == "s1:10")
    assert line["values"]["stock_length_origin"] == "Sugestão automática"
    edits.update_batch({"request_id": str(uuid.uuid4()), "actor": "Teste", "area": "perfis", "version": listed["version"],
                        "edits": [{"key": line["key"], "expected_revision": line["revision"], "values": {"notes": "Escrito"}}]})
    edited = next(r for r in rows_of("REF-A") if r["need_id"])
    assert edited["values"]["notes"] == "Escrito" and edited["values"]["stock_length_origin"] == "Sugestão automática"
    new_import_with_the_same_excel(essential)
    with psycopg.connect(essential) as c:
        c.execute("""UPDATE raw_mtg.plan_production_rows SET row_data=row_data||'{"Chanf.":"X","Data requisição de material":"2026-10-20","Observações":"Do Excel"}'
                     WHERE source_line_id='s2:10'""")
    detail = needs.detail(edited["need_id"])
    record = detail["records"][0]["values_json"]
    assert record["chanfro"] == "X" and record["material_request_date"] == "2026-10-20" and record["notes"] == "Escrito"
    notes = next(f for f in detail["fields"] if f["field"] == "notes" and f["scope"] != "piece")
    assert notes["requires_review"] and notes["suggestion"] == "Do Excel"
    projection.rebuild("perfis")
    row = next(r for r in rows_of("REF-A") if r["need_id"] == edited["need_id"])
    assert row["plan_key"] == "s2:10" and row["values"]["chanfro"] == "X" and row["values"]["notes"] == "Escrito"


def test_a_following_operation_without_state_does_not_take_the_cut_machine(essential):
    # Achado B-F20 (08/10): os valores da linha do Excel descrevem a operação principal. A ficha de uma operação seguinte
    # gravada sem estado (pela Tabela) não passa a ter a Máquina e a Data Corte do corte numa importação nova.
    linked = from_excel_line(changed=["quantity_required"])
    with psycopg.connect(essential) as c:
        main = c.execute("SELECT id FROM planning_mtg.records WHERE need_id=%s", (linked["need_id"],)).fetchone()[0]
        columns = [r[0] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='planning_mtg' "
                                           "AND table_name='records' ORDER BY ordinal_position").fetchall()]
        op, ident = uuid.uuid4(), uuid.uuid4()
        c.execute("INSERT INTO planning_mtg.need_operations(id,need_id,area,code,sequence) VALUES (%s,%s,'perfis','abocardar',2)",
                  (op, linked["need_id"]))
        selected = ["%s" if k in ("id", "operation_id") else """values_json||'{"machine":null,"cut_date":null}'""" if k == "values_json"
                    else k for k in columns]
        args = [ident if k == "id" else op for k in columns if k in ("id", "operation_id")]
        c.execute("INSERT INTO planning_mtg.records(" + ",".join(columns) + ") SELECT " + ",".join(selected)
                  + " FROM planning_mtg.records WHERE id=%s", (*args, main))
    new_import_with_the_same_excel(essential)
    with psycopg.connect(essential) as c:
        c.execute("""UPDATE raw_mtg.plan_production_rows SET cut_date='2026-12-15',row_data=row_data||'{"Máquina Corte":"Ficep"}'
                     WHERE source_line_id='s2:10'""")
    detail = needs.detail(linked["need_id"])
    records = {str(r["operation_id"]): r["values_json"] for r in detail["records"]}
    assert records[str(op)]["machine"] is None and records[str(op)]["cut_date"] is None
    assert not [f for f in detail["fields"] if f["scope"] == str(op)]
    first = next(v for k, v in records.items() if k != str(op))
    assert first["cut_date"] == "2026-12-15" and first["machine"] == "Ficep"


def test_an_import_with_the_same_excel_keeps_untyped_values(essential):
    # A linha s1:10 não tem Equipa; a peça ficou com a sugerida, sem o utilizador a escrever.
    linked = from_excel_line(changed=["quantity_required"], team="Equipa sugerida")
    new_import_with_the_same_excel(essential)
    detail = needs.detail(linked["need_id"])
    assert detail["sources"][0]["version"] == "s2"
    assert detail["records"][0]["values_json"]["team"] == "Equipa sugerida"


def test_clearing_a_field_with_a_default_saves_the_default(essential):
    projection.rebuild("cantoneiras")
    saved = prepare({"request_id": str(uuid.uuid4()), "actor": "Teste", "area": "cantoneiras", "production_order_no": "OF4200",
                     "source": {"kind": "plan_line", "id": "c1:10", "version": "c1"}, "record_status": "ready",
                     "decisions": {"operation_detail": "clear"}, "changed_fields": ["operation_detail"],
                     "values": {"component_ref": "REF-A", "quantity_required": 100, "length_mm": 5291, "operation": "119", "operation_detail": ""}})
    record = needs.detail(saved["need_id"])["records"][0]
    assert record["values_json"]["operation_detail"] == "0"
    state = next(f for f in needs.detail(saved["need_id"])["fields"] if f["field"] == "operation_detail" and f["scope"] != "piece")
    assert state["human_decision"] is None


def test_pdf_fields_it_does_not_carry_do_not_change_the_technical_revision(essential, monkeypatch):
    from app.dossiers import store
    piece = {"component_ref": "PDF-T", "material_type": "Tubo redondo", "profile": "88.9x3", "length_mm": 1000, "quantity_required": 9}
    document = {"id": "doc-t", "revision": 1, "production_order": "OF4200", "status": "ready",
                "pieces": [{"id": "p1", "revision": 1, "state": "ready", "values": piece}]}
    monkeypatch.setattr(store, "get_document", lambda ident: copy.deepcopy(document))
    saved = prepare({"request_id": str(uuid.uuid4()), "actor": "Teste", "area": "perfis", "production_order_no": "OF4200",
                     "source": {"kind": "pdf", "id": "doc-t/p1", "version": "1:1"}, "values": piece, "changed_fields": [], "record_status": "ready"})
    before = needs.detail(saved["need_id"])["need"]["technical_revision"]
    document["revision"] = 2
    assert needs.detail(saved["need_id"])["need"]["technical_revision"] == before


def test_production_association_ignores_a_changed_excel_on_disk(essential, tmp_path):
    from app import planning_associations as assoc
    saved = register({**PIECE, "component_ref": "MAN-OCR"})
    (tmp_path / "Met2_Plan_Perfis.xlsm").write_bytes(b"ficheiro mudado no disco")
    with psycopg.connect(essential) as c:
        c.execute("INSERT INTO mes_kanban.validated_sheets(sheet_uid,sheet_date,template_name,family,operator_name,image_sha256,raw_extraction,sheet_data,validated_by,source_app) "
                  "VALUES ('wb-sheet','2026-10-01','tpl999','perfis','Teste','hash','{}','{}','Teste','kanban-mes-mtg2')")
        rid = c.execute("INSERT INTO mes_kanban.production_records(sheet_uid,row_index,sheet_date,family,operator_name,production_order,quantity,validated_at) "
                        "VALUES ('wb-sheet',0,'2026-10-01','perfis','Teste','4200',4,now()) RETURNING id").fetchone()[0]
    with planning.connect(readonly=True) as c:
        record = assoc.fact(c, rid)
    result = assoc.save({"request_id": str(uuid.uuid4()), "actor": "Teste", "production_record_id": rid, "expected_revision": 0,
                         "evidence_hash": needs.digest(record), "status": "associated", "reason": "",
                         "allocations": [{"need_id": saved["need_id"], "operation_id": saved["operation_id"],
                                          "expected_need_revision": saved["revision"], "quantity": 4}]})
    assert result["status"] == "associated"


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
    # Separador antigo: envia todos os campos visíveis (Observações vazias) e não diz o que mudou. Recebe o
    # 409 de antes em vez de apagar as Observações de outra pessoa ou repor valores que entretanto mudaram.
    with pytest.raises(planning.PlanningError) as refused:
        register({**PIECE, "component_ref": "MAN-REV", "team": "Equipa 9", "notes": ""}, need_id=first["need_id"],
                 expected_revision=first["revision"])
    assert refused.value.status == 409
    values = needs.detail(stale["need_id"])["records"][0]["values_json"]
    assert values["team"] == "Equipa 5" and values["machine"] == "Peddi" and values["notes"] == "Outra pessoa"


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
