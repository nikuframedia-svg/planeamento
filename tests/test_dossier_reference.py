"""Regressão da conferência independente dos três PDFs iniciais."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.evaluate_dossier_reference import evaluate

REFERENCE = Path(__file__).parent / "fixtures/dossier_reference_2026-09.json"


def _payload(reference):
    documents = {}
    for line in reference["expected"]:
        document = documents.setdefault(line["of"], {"production_order": line["of"], "pieces": []})
        values = dict(line["literal"])
        effective = dict(line["effective"])
        machine_group = effective.pop("machine_group")
        document["pieces"].append({"machine_group": machine_group or "Por atribuir", "state": "ready",
            "drawing_pages": [line["drawing_page"]], "values": values,
            "match": {"effective_values": effective, "machine_group": machine_group}})
    return {"documents": list(documents.values())}


def test_reference_fixture_has_the_independently_verified_scope():
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    assert len(reference["expected"]) == 12
    assert sum(line["effective"]["quantity_required"] for line in reference["expected"]) == 323
    assert {line["of"] for line in reference["expected"]} == {
        "OF260221", "OF263785", "OF265931", "OF265941", "OF266229"}
    assert reference["totals"]["resolved_by_machine"] == {"Vanguard": 212, "Serrote": 69}
    assert reference["totals"]["unresolved_quantity"] == 42
    assert evaluate(reference, _payload(reference))["passed"] is True


def test_reference_evaluator_reports_a_silent_critical_change():
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    payload = _payload(reference)
    payload["documents"][0]["pieces"][0]["match"]["effective_values"]["quantity_required"] = 35
    report = evaluate(reference, payload)
    assert report["passed"] is False
    assert report["mismatches"] == [{"of": "OF263785", "component_ref": "1234.T.120",
        "field": "effective.quantity_required", "expected": 36, "actual": 35}]
    assert report["totals_match"] is False


def test_reference_evaluator_ignores_archived_piece_versions():
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    payload = _payload(reference)
    old = json.loads(json.dumps(payload["documents"][0]["pieces"][0]))
    old["state"] = "superseded"
    old["values"]["quantity_required"] = 999
    payload["documents"][0]["pieces"].append(old)
    assert evaluate(reference, payload)["passed"] is True
