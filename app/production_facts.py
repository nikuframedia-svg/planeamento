"""Materializa uma folha uma vez para todos os consumidores de produção.

O registo pai representa sempre a linha física. Em ``Perf. Comp. = X`` os
filhos preservam todas as referências (incluindo falta zero), enquanto os
factos de exportação incluem apenas filhos com produção positiva. Assim nenhum
consumidor soma simultaneamente o agregado e a decomposição.
"""

from __future__ import annotations

from .matching import carryover, similarity as sim
from .matching.full_profile import plan_identity
from .templates_spec import field_value, is_marked


def _has_content(row: dict) -> bool:
    return any(
        not str(key).startswith("_")
        and value is not None and str(value).strip()
        for key, value in row.items()
    )


def materialize_sheet(sheet: dict) -> list[dict]:
    data = sheet.get("sheet_data") or {}
    rows = data.get("rows") or []
    cross = sheet.get("cross_check") or {}
    cross_rows = {r.get("row_index"): r for r in cross.get("rows", [])}
    identities = carryover.resolve(rows, (), {})
    facts: list[dict] = []
    for row_index, source_row in enumerate(rows):
        if source_row.get("_deleted") is True or not _has_content(source_row):
            continue
        row_cross = cross_rows.get(row_index) or {}
        if row_cross.get("row_kind") in {"activity", "empty"} or row_cross.get("mode") in {"activity", "empty"}:
            continue
        effective = (
            dict(source_row) if cross.get("engine_version") == "cross-v3" or cross.get("version") == "cross-v3"
            else carryover.effective_row(source_row, identities[row_index])
        )
        plan_refs = list(row_cross.get("plan_refs") or []) if is_marked(field_value(source_row, "perf_comp")) else []
        parent_row = dict(effective)
        parent_cross = dict(row_cross)
        export_rows: list[tuple[dict, dict]] = []
        if plan_refs:
            total = sum(
                sim.parse_number(ref.get("assumed_quantity")) or 0.0
                for ref in plan_refs
            )
            meters = round(sum(
                (sim.parse_number(ref.get("assumed_quantity")) or 0.0)
                * (sim.parse_number(ref.get("length_mm")) or 0.0) / 1000.0
                for ref in plan_refs
            ), 3)
            parent_row["modelo"] = None
            parent_row["qtd"] = total
            if any((sim.parse_number(r.get("assumed_quantity")) or 0) > 0 and sim.parse_number(r.get("length_mm")) is None for r in plan_refs):
                meters = None
            parent_cross.update({
                "matched_plan_key": None,
                "plan_length_mm": None,
                "plan_line_meters": meters,
                "line_meters": meters,
            })
            for ref in plan_refs:
                quantity = sim.parse_number(ref.get("assumed_quantity"))
                if quantity is None or quantity <= 0:
                    continue
                child_row = dict(effective)
                child_row["modelo"] = ref.get("component_ref")
                child_row["perfil"] = ref.get("profile_type") or child_row.get("perfil")
                child_row["qtd"] = quantity
                for field, key in (("of", "production_order_no"), ("ov", "sales_order_no"), ("cliente", "customer_name")):
                    if key in ref:
                        child_row[field] = ref[key]
                # O filho é uma referência concreta, não uma nova afirmação
                # agregada de «perfil completo». Só o registo físico pai
                # conserva a marca X.
                child_row["perf_comp"] = None
                child_cross = dict(row_cross)
                length = sim.parse_number(ref.get("length_mm"))
                child_cross.update({
                    "matched_plan_key": ref.get("plan_key"),
                    "plan_identity": plan_identity(ref, ref.get("snapshot_id") or cross.get("snapshot_id")),
                    "plan_length_mm": length,
                    "plan_line_meters": (
                        round(quantity * length / 1000.0, 3)
                        if length is not None else None
                    ),
                })
                child_cross["line_meters"] = child_cross["plan_line_meters"]
                export_rows.append((child_row, child_cross))
        else:
            export_rows.append((dict(effective), dict(row_cross)))
        facts.append({
            "row_index": row_index,
            "source_row": source_row,
            "parent_row": parent_row,
            "parent_cross": parent_cross,
            "plan_refs": plan_refs,
            "export_rows": export_rows,
        })
    return facts
