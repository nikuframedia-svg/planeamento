"""Quadro simples do plano e lista vermelha das OF por planear (02/10/2026). Sem base de dados."""
from datetime import date

from app.sector import board

TODAY = date(2026, 10, 2)


def line(of, *, machine="", metres=10.0, pieces=5, due=None, priority=None, reference="R1", registered=date(2026, 9, 1), **signals):
    return {"of": of, "work": "OV" + of, "customer": "Cliente " + of, "designation": "= POSTES =_x000D_\n= 1 PRIORIDADE =",
            "family": "1 Postes", "registered": registered, "reference": reference, "machine": machine,
            "metres": metres, "pieces": pieces, "priority_day": due,
            "signals": {"prioridade": priority, "anulada": False, "eletrofer": False, "validacao": False, **signals}}


def data(*lines):
    return {"lines": list(lines), "today": TODAY, "imported_at": None}


def test_order_without_machine_is_red_and_planned_order_is_not():
    result = board.unplanned("cantoneiras", data=data(line("OF1"), line("OF2", machine="Peddi 8")), decisions={})
    assert [o["of"] for o in result["orders"]] == ["OF1"]
    assert result["planned_orders"] == 1
    assert result["orders"][0]["designation"] == "POSTES · 1 PRIORIDADE"
    assert result["orders"][0]["waiting_days"] == 31


def test_marking_with_planear_keeps_order_red_until_it_has_a_machine():
    decisions = {("OF1", "*"): {"decision": "selected"}}
    result = board.unplanned("cantoneiras", data=data(line("OF1")), decisions=decisions)
    assert result["orders"][0]["marked"] is True


def test_excluded_lines_do_not_count_and_partial_orders_show_missing_part():
    decisions = {("OF1", "R2"): {"decision": "excluded"}}
    result = board.unplanned("cantoneiras", data=data(
        line("OF1", reference="R2"), line("OF3", machine="XP T4", reference="A"), line("OF3", reference="B", metres=4)), decisions=decisions)
    assert [o["of"] for o in result["orders"]] == ["OF3"]
    order = result["orders"][0]
    assert order["partial"] and order["lines"] == 1 and order["lines_total"] == 2 and order["metres"] == 4


def test_order_is_priority_then_deadline_then_size():
    result = board.unplanned("cantoneiras", data=data(
        line("OFA", due=date(2026, 9, 1)), line("OFB", due=date(2026, 8, 1)), line("OFC", priority=3, due=date(2026, 12, 1)),
        line("OFD", metres=99), line("OFE", metres=1)), decisions={})
    assert [o["of"] for o in result["orders"]] == ["OFC", "OFB", "OFA", "OFD", "OFE"]
    assert result["orders"][1]["late_days"] == 62


def op(key, of, remaining, due=None):
    return {"key": key, "of": of, "planning_remaining": remaining, "priority": {"priority_day": due}}


def test_source_plan_boxes_merge_one_order_per_machine_and_mark_late():
    plan = {"entries": [
        {"key": "a", "resource_id": "m1", "start_date": "2026-10-01", "end_date_exclusive": "2026-10-02", "precision": "day"},
        {"key": "b", "resource_id": "m1", "start_date": "2026-10-02", "end_date_exclusive": "2026-10-03", "precision": "day"},
        {"key": "c", "resource_id": "m1", "start_date": "2026-10-10", "end_date_exclusive": "2026-10-11", "precision": "day"},
        {"key": "d", "resource_id": "m2", "start_date": "2026-10-05", "end_date_exclusive": "2026-10-12", "precision": "week"}]}
    boxes = board.boxes_from_source_plan(plan, [op("a", "OF1", 10, "2026-10-01"), op("b", "OF1", 5), op("c", "OF1", 1), op("d", "OF2", 7)])
    assert [(b["resource_id"], b["of"], str(b["start"]), str(b["end"]), b["pieces"], b["lines"]) for b in boxes] == [
        ("m1", "OF1", "2026-10-01", "2026-10-03", 15, 2), ("m1", "OF1", "2026-10-10", "2026-10-11", 1, 1),
        ("m2", "OF2", "2026-10-05", "2026-10-12", 7, 1)]
    assert boxes[0]["late"] and not boxes[2]["late"]
    assert boxes[2]["approximate"]


def test_proposal_boxes_use_lisbon_days_of_segments():
    snapshot = {"started_at": "2026-10-01T22:30:00+00:00", "operations": [op("a", "OF1", 3, "2026-10-05")]}
    proposal = {"bars": {"a": {"resource_id": "m1", "segments": [[0, 60], [1440, 1500]]}}}
    [box] = board.boxes_from_proposal(snapshot, proposal)
    assert (str(box["start"]), str(box["end"]), box["late"]) == ("2026-10-01", "2026-10-04", False)


def test_order_numbers_compare_with_or_without_prefix():
    assert board._order_no("OF264095") == board._order_no("264095") == board._order_no("264095.0") == "264095"
