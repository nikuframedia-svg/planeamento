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
    assert calculations.calculate(piece, operations=ocr(5), declared_remaining=5, declared_produced=0)["values"]["remaining"] == 0
    assert calculations.calculate(piece, operations=ocr(2), declared_remaining=5, declared_produced=0)["values"]["remaining"] == 3
    # Produção desconhecida quando foi escrita: não se desconta nada.
    assert calculations.calculate(piece, operations=ocr(2), declared_remaining=5)["values"]["remaining"] == 5
    measured = calculations.calculate(piece, operations=ocr(2), declared_remaining=5, declared_produced=0)["operations"][0]
    assert measured["measured"] == 2 and measured["origin"] == calculations.DECLARED_ORIGIN


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
    # O Excel regista mais 6 cortadas: a «Qtd em falta» escrita desconta-as.
    with psycopg.connect(essential) as c:
        c.execute("UPDATE raw_mtg.plan_production_rows SET row_data=row_data||'{\"Ser.\":70}' WHERE source_line_id='s1:10'")
    projection.rebuild("perfis", force=True)  # a importação mudada no próprio sítio só se vê com force
    assert next(r for r in rows_of("REF-A") if r["need_id"] == str(typed["need_id"]))["values"]["remaining"] == 4
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
