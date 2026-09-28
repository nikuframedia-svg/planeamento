#!/usr/bin/env python3
"""Compara uma captura da API de dossiês com a verdade conferida dos PDFs.

O programa é deliberadamente só de leitura. A captura pode ser a resposta de
GET /planeamento/api/dossies ou uma lista de documentos obtidos pelos endpoints
de detalhe. O relatório nunca transforma o plano/macro em verdade de extração.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.dossiers.models import ref_key

DEFAULT_REFERENCE = ROOT / "tests/fixtures/dossier_reference_2026-09.json"
VALUE_FIELDS = ("component_ref", "profile", "material_type", "grade", "quantity_required",
                "length_mm", "outer_diameter_mm", "width_mm", "height_mm", "thickness_mm")


def _profile(value) -> str:
    return re.sub(r"[\sØø⌀]", "", str(value or "")).replace("×", "x").replace("X", "x").upper()


def _number(value):
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _documents(payload) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("documents"), list):
        return payload["documents"]
    if isinstance(payload, dict) and payload.get("pieces") is not None:
        return [payload]
    raise ValueError("A captura deve conter uma lista de documentos com as respetivas pieces.")


def actual_lines(payload) -> tuple[list[dict], list[str]]:
    lines, structural = [], []
    for document in _documents(payload):
        order = str(document.get("production_order") or "")
        for piece in document.get("pieces") or []:
            if piece.get("state") in {"excluded", "duplicate", "superseded"}:
                continue
            literal = piece.get("values") or {}
            match = piece.get("match") or {}
            effective = match.get("effective_values") or literal
            effective_group = match["machine_group"] if "machine_group" in match else piece.get("machine_group")
            pages = piece.get("drawing_pages") or []
            if not order or not effective.get("component_ref"):
                structural.append(f"Peça sem OF/referência no documento {document.get('id') or document.get('filename')}")
                continue
            lines.append({
                "of": order,
                "component_ref": effective.get("component_ref"),
                "literal": {field: _number(literal.get(field)) for field in VALUE_FIELDS},
                "effective": {field: _number(effective.get(field)) for field in VALUE_FIELDS} | {
                    "machine_group": effective_group},
                "drawing_page": pages[0] if len(pages) == 1 else pages,
            })
    return lines, structural


def _key(line):
    return str(line.get("of") or "").upper(), ref_key(line.get("component_ref"))


def evaluate(reference: dict, payload) -> dict:
    actual, structural = actual_lines(payload)
    expected = reference["expected"]
    expected_map, actual_map = {}, {}
    duplicates = []
    for label, lines, target in (("referência", expected, expected_map), ("captura", actual, actual_map)):
        for line in lines:
            key = _key(line)
            if key in target:
                duplicates.append(f"Identidade repetida na {label}: {key[0]}/{key[1]}")
            target[key] = line
    missing = [f"{of}/{ref}" for of, ref in sorted(expected_map.keys() - actual_map.keys())]
    unexpected = [f"{of}/{ref}" for of, ref in sorted(actual_map.keys() - expected_map.keys())]
    mismatches = []
    for key in sorted(expected_map.keys() & actual_map.keys()):
        wanted, seen = expected_map[key], actual_map[key]
        if wanted.get("drawing_page") != seen.get("drawing_page"):
            mismatches.append({"of": key[0], "component_ref": wanted["component_ref"],
                               "field": "drawing_page", "expected": wanted.get("drawing_page"),
                               "actual": seen.get("drawing_page")})
        for scope in ("literal", "effective"):
            for field, left in wanted.get(scope, {}).items():
                right = seen.get(scope, {}).get(field)
                equal = (_profile(left) == _profile(right)
                         if field in {"profile", "grade", "material_type"} else left == right)
                if not equal:
                    mismatches.append({"of": key[0], "component_ref": wanted["component_ref"],
                                       "field": f"{scope}.{field}", "expected": left, "actual": right})
    by_machine = Counter()
    quantity = 0
    for line in actual:
        amount = line.get("effective", {}).get("quantity_required")
        if isinstance(amount, (int, float)) and not isinstance(amount, bool):
            quantity += amount
            group = line.get("effective", {}).get("machine_group")
            by_machine[str(group if group in ("Vanguard", "Serrote") else "por atribuir")] += amount
    totals = {"needs": len(actual), "quantity_required": _number(quantity),
              "resolved_by_machine": {key: value for key, value in sorted(by_machine.items())
                                      if key != "por atribuir"},
              "unresolved_quantity": _number(by_machine.get("por atribuir", 0))}
    expected_totals = reference["totals"]
    totals_match = totals == expected_totals
    errors = structural + duplicates
    passed = not errors and not missing and not unexpected and not mismatches and totals_match
    return {"reference_version": reference["version"], "passed": passed,
            "expected_needs": len(expected), "actual_needs": len(actual),
            "missing": missing, "unexpected": unexpected, "mismatches": mismatches,
            "structural_errors": errors, "totals": totals,
            "expected_totals": expected_totals, "totals_match": totals_match}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actual", required=True, type=Path, help="Captura JSON da API")
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--report", type=Path, help="Guardar também o relatório JSON")
    args = parser.parse_args()
    reference = json.loads(args.reference.read_text(encoding="utf-8"))
    payload = json.loads(args.actual.read_text(encoding="utf-8"))
    report = evaluate(reference, payload)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
