"""Contexto CPIS completo, incluindo OF ainda ausentes da folha Planeamento."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

import psycopg

from .. import planning, planning_hub, planning_population, planning_order_population
from . import DossierError
from . import material
from .models import (REQUIRED_FIELDS, FIELD_LABELS, difference_decision_fingerprint,
                     fingerprint, order_number, reading_decision_fingerprint, ref_key)

def issue(code, message, *, field=None, blocking=False, **metadata):
    return {"code": code, "message": message, "field": field, "blocking": blocking, **metadata}


def _source_freshness(source) -> dict:
    checked = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path = Path(str(source.get("source_path") or ""))
    if not path.is_file():
        return {"checked_at": checked, "available": False, "matches_import": False}
    stat = path.stat()
    # A exportação é uma operação pouco frequente e o XLSM é pequeno face às
    # imagens do dossiê. Calcular sempre evita confiar em metadados de ficheiro
    # que podem manter tamanho e timestamp numa substituição rápida.
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    digest = hasher.hexdigest()
    return {"checked_at": checked, "available": True,
            "matches_import": digest == source.get("source_sha256"),
            "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds")}


def read_context(of: str, references=()) -> dict:
    of = order_number(of)
    if not of:
        raise DossierError("Confirma o número da OF do dossiê.")
    try:
        with planning.connect(readonly=True) as conn:
            snapshot = planning.snapshot(conn, "perfis")
            sid = snapshot["snapshot_id"]
            direct = planning_hub._direct_version(conn)
            snapshots = planning_hub._latest_snapshots(conn)
            cpis = planning_hub._order_rows(conn, direct, '', None, only_ofs=[of])
            summary = planning_hub._order_summary(cpis) if cpis else {}
            source = conn.execute("SELECT source_path,source_sha256 FROM audit_mtg.snapshots WHERE snapshot_id=%s", (sid,)).fetchone()
            rows = conn.execute("""SELECT source_line_id,excel_row,external_row_number,component_ref,
                material_type,profile_type,length_mm,quantity_planned,closed_x,row_data,
                sales_order_no,customer_name,designation
                FROM raw_mtg.plan_production_rows WHERE snapshot_id=%s
                AND regexp_replace(trim(production_order_no),'^OF[ ._-]*','','i')=%s
                ORDER BY excel_row""", (sid, of[2:])).fetchall()
            members, _ = planning_order_population.read(conn, snapshots, orders=[of])
            planning_order_population.summarize(members, {of: summary})
            by_source = {key: m for m in members if m['area']=='perfis' for key in m['source_keys']}
            for row in rows:
                member = by_source.get(row['source_line_id'])
                row['planning_key'] = member['key'] if member else 'macro:'+row['source_line_id']
                row['population'] = member['population'] if member else planning_population.classify({
                    'status_values':summary.get('status_values',[]), 'closed_x':row['closed_x'], 'raw':row['row_data']})
            reference_keys = sorted({ref_key(value) for value in references if ref_key(value)})
            history = []
            if reference_keys:
                history = conn.execute("""SELECT source_line_id,excel_row,external_row_number,
                    production_order_no,component_ref,material_type,profile_type,length_mm,
                    quantity_planned,closed_x,row_data,sales_order_no,customer_name,designation
                    FROM raw_mtg.plan_production_rows
                    WHERE snapshot_id=%s AND regexp_replace(trim(production_order_no),'^OF[ ._-]*','','i')<>%s
                    AND regexp_replace(upper(coalesce(component_ref,'')),'[^A-Z0-9]','','g')=ANY(%s)
                    ORDER BY excel_row DESC LIMIT 200""", (sid, of[2:], reference_keys)).fetchall()
            tail = conn.execute("""SELECT max(excel_row) AS last_row, max(external_row_number) AS last_id
                FROM raw_mtg.plan_production_rows WHERE snapshot_id=%s""", (sid,)).fetchone()
            machines = planning._catalogs(conn, "perfis", sid)["machines"]
            catalog_rows = conn.execute("""SELECT excel_row,row_data
                FROM raw_mtg.other_sheet_rows WHERE snapshot_id=%s AND sheet_name='AreaSecaoCorte'
                ORDER BY excel_row""", (sid,)).fetchall()
    except (psycopg.Error, planning.PlanningError):
        raise DossierError("Não foi possível consultar o CPIS. Os dados do PDF foram guardados; tenta cruzar novamente.", 503) from None
    problems = []
    if not cpis:
        problems.append(issue("of_missing", "Esta OF não foi encontrada nas fontes CPIS disponíveis.", blocking=True))
    if summary.get('conflicts'):
        problems.append(issue("cpis_ambiguous", "Existem registos CPIS incompatíveis para esta OF.", blocking=True))
    population = planning_population.classify({'status_values':summary.get('status_values',[])})
    if not population['active']:
        problems.append(issue("of_closed", "A OF está fechada numa das fontes CPIS e não pode originar novas linhas.", blocking=True))
    elif cpis and (len(summary['status_values'])!=1 or summary['cpis_status'] not in planning.OPEN_STATES):
        problems.append(issue("of_not_operational", "O estado CPIS não confirma autorização para concluir ou exportar. A OF não foi interpretada como fechada.", blocking=True))
    for unknown in population['unknown_states']:
        problems.append(issue('cpis_state_unknown',f"Estado CPIS desconhecido: {unknown['value']}. Não interpretado como fechado."))
    catalog = []
    for row in catalog_rows:
        values = row["row_data"].get("values", [])
        if len(values) >= 2 and values[0] and values[1] and row["excel_row"] > 1:
            catalog.append({"row": row["excel_row"], "family": planning._text(values[0]),
                            "profile": planning._text(values[1]),
                            "area": planning._number(values[2]) if len(values) > 2 else None,
                            "rule": planning._text(values[3]) if len(values) > 3 else ""})
    source = planning.serializable(source)
    freshness = _source_freshness(source)
    if not freshness["available"]:
        problems.append(issue("source_unavailable", "A macro de origem da importação já não está disponível no servidor.", blocking=True))
    elif not freshness["matches_import"]:
        problems.append(issue("source_changed", "A macro de origem mudou desde a importação. Atualiza a importação antes de exportar.", blocking=True))
    return planning.serializable({"production_order": of, "snapshot": snapshot,
        "sales_order": (summary.get('ovs') or [None])[0] if len(summary.get('ovs',[]))<=1 else None,
        "sales_orders":summary.get('ovs',[]), "customer": summary.get("customer_name"),
        "designation": planning._text(summary.get("observations")), "status": summary.get("cpis_status"),
        "status_values":summary.get('status_values',[]), "population":population,
        "cpis_mode":'direct' if direct else 'imported',
        "cpis_version":str(direct['id']) if direct else planning_hub._fallback_token(snapshots),
        "delivery_date": summary.get("delivery_date"), "planned_finish_date": summary.get("planned_finish_date"),
        "actual_finish_date": summary.get("actual_finish_date"), "source": source,
        "source_freshness": freshness, "tail": tail,
        "machines": machines, "material_catalog": catalog,
        "material_catalog_version": fingerprint(catalog), "plan_rows": rows,
        "planning_members":[{k:m[k] for k in ('key','need_id','population','source_keys')}
                            for m in members if m['of']==of and m['area']=='perfis'],
        "reference_history": history, "issues": problems})


def _numeric(value):
    return planning._number(value)


def _profile(value):
    return re.sub(r"\s+", "", str(value or "")).upper().replace("×", "X").replace(",", ".")


def _input(raw: dict, header: str, fallback=None):
    """Read the writable macro input, preserving a deliberate blank cell."""
    return raw[header] if header in raw else fallback


def _contains_replacement_character(value) -> bool:
    if isinstance(value, str):
        return "\ufffd" in value
    if isinstance(value, dict):
        return any(_contains_replacement_character(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_replacement_character(item) for item in value)
    return False


def _warning_needs_review(warning: str, values: dict, resolution: dict,
                          required_geometry: tuple[str, ...]) -> bool:
    text = str(warning).casefold()
    absence = any(word in text for word in ("vazi", "ausent", "não cot", "nao cot", "sem cota"))
    if (absence and "índice" in text and any(word in text for word in ("qtd", "quantidade"))
            and values.get("quantity_required") is not None
            and values.get("evidence", {}).get("quantity_required")):
        return False
    dimensions = any(word in text for word in ("largura", "altura", "espessura", "dimens"))
    if (absence and dimensions and not required_geometry
            and resolution.get("status") in ("catalog_exact", "catalog_alias")):
        return False
    return True


def _reading_confirmed(piece, field, values) -> bool:
    decision = piece.get("reviewed", {}).get("decisions", {}).get(field, {})
    return decision.get("reading") == reading_decision_fingerprint(field, values, piece.get("raw"))


def _difference_confirmed(piece, field, values, plan_value, source_plan_key) -> bool:
    decision = piece.get("reviewed", {}).get("decisions", {}).get(field, {})
    return decision.get("difference") == difference_decision_fingerprint(
        field, values, plan_value, source_plan_key)


def _plan_values(row: dict) -> dict:
    raw = row.get("row_data") or {}
    profile = _input(raw, "Designação Perfil", row.get("profile_type"))
    # profile_type is assembled by the importer from the structured input
    # columns and remains useful when the free-text designation is blank.
    if profile in (None, ""):
        profile = row.get("profile_type")
    material_type = _input(raw, "Tipo de Material", row.get("material_type"))
    if material_type in (None, ""):
        material_type = row.get("material_type")
    return {
        "quantity_required": _numeric(_input(raw, "QTD [un,]", row.get("quantity_planned"))),
        "length_mm": _numeric(_input(raw, "Comp, [mm]", row.get("length_mm"))),
        "profile": profile,
        "grade": _input(raw, "Qual.", raw.get("Qual.__2")),
        "material_type": material_type,
        "outer_diameter_mm": _numeric(raw.get("Ø Externo [mm]")),
        "width_mm": _numeric(raw.get("Largura (w) [mm]")),
        "height_mm": _numeric(raw.get("Altura (h) [mm]")),
        "thickness_mm": _numeric(raw.get("Espessura (t) [mm]")),
        "angle_deg": _numeric(raw.get("Ang,")),
        "abocardar": raw.get("Aborc."),
        "chanfro": raw.get("Chanf."),
    }


def _candidate_rows(values: dict, rows, extra_references=()) -> list:
    keys = {ref_key(value) for value in (values.get("component_ref"), values.get("drawing_ref"),
                                         *extra_references) if ref_key(value)}
    candidates = [row for row in rows if ref_key(row.get("component_ref")) in keys]
    if len(candidates) > 1:
        exact = []
        for row in candidates:
            row_values = _plan_values(row)
            comparable = [("length_mm", False), ("profile", True)]
            known = [(field, normalize) for field, normalize in comparable
                     if values.get(field) not in (None, "") and row_values.get(field) not in (None, "")]
            if known and all((_profile(values[field]) == _profile(row_values[field]) if normalize
                              else values[field] == row_values[field]) for field, normalize in known):
                exact.append(row)
        if len(exact) == 1:
            candidates = exact
    return candidates


def _nominal_inch_profile(value) -> bool:
    text = str(value or "").casefold()
    return any(marker in text for marker in ('"', "″", "“", "”", "poleg"))


def _nominal_tube_profile(value, description, plan_value) -> bool:
    current_numbers = re.findall(r"\d+(?:[.,]\d+)?", str(value or ""))
    plan_numbers = re.findall(r"\d+(?:[.,]\d+)?", str(plan_value or ""))
    return (_nominal_inch_profile(value) or _nominal_inch_profile(description)
            or (len(current_numbers) < 2 and len(plan_numbers) >= 2))


def _machine_group(value) -> str | None:
    text = str(value or "").casefold()
    if "vanguard" in text:
        return "Vanguard"
    if "serrote" in text:
        return "Serrote"
    return None


def _history_compatible(row: dict, effective: dict) -> bool:
    candidate = _plan_values(row)
    compared = 0
    for field in ("profile", "material_type", "grade", "length_mm", "outer_diameter_mm",
                  "width_mm", "height_mm", "thickness_mm"):
        current, old = effective.get(field), candidate.get(field)
        if current in (None, "") or old in (None, ""):
            continue
        compared += 1
        if field in ("profile", "material_type", "grade"):
            if _profile(current) != _profile(old):
                return False
        elif current != old:
            return False
    return compared > 0


def assess(piece: dict, context: dict, page_count: int) -> tuple[list, dict]:
    values = piece["values"]
    reviewed = piece.get("reviewed", {})
    issues = list(context.get("issues", []))
    damaged = sorted({field for field in FIELD_LABELS
                      if _contains_replacement_character(values.get(field))}
                     | {field for field, evidence in values.get("evidence", {}).items()
                        if _contains_replacement_character(evidence)}
                     | ({"warnings"} if _contains_replacement_character(values.get("warnings", [])) else set()))
    if damaged:
        issues.append(issue("damaged_text_encoding",
            "A resposta contém texto ilegível (�). Relê a peça antes de a exportar.",
            field=damaged[0] if damaged[0] in FIELD_LABELS else None,
            blocking=True, damaged_fields=damaged))

    candidates = _candidate_rows(values, context.get("plan_rows", []), (piece.get("index_ref"),))
    enriched = dict(values)
    field_sources = {}
    for field in FIELD_LABELS:
        if values.get(field) not in (None, ""):
            evidence = values.get("evidence", {}).get(field) or {}
            field_sources[field] = {"source": "pdf", "page": evidence.get("page")}
    if len(candidates) == 1:
        row = candidates[0]
        source = {"source": "plan", "snapshot_id": context.get("snapshot", {}).get("snapshot_id"),
                  "source_line_id": row.get("source_line_id"), "excel_row": row.get("excel_row")}
        for field, plan_value in _plan_values(row).items():
            missing = enriched.get(field) in (None, "")
            nominal_tube = (field == "profile"
                            and "tubo" in str(enriched.get("material_type") or "").casefold()
                            and _nominal_tube_profile(enriched.get(field),
                                enriched.get("material_description"), plan_value))
            if plan_value not in (None, "") and (missing or nominal_tube):
                enriched[field] = plan_value
                field_sources[field] = dict(source)

    resolution = material.resolve(enriched, context)
    effective = {**enriched, **resolution["export"]}
    for field in ("material_type", "profile", "outer_diameter_mm", "width_mm",
                  "height_mm", "thickness_mm"):
        if effective.get(field) in (None, "") or effective.get(field) == enriched.get(field):
            continue
        if field in resolution.get("derived", {}):
            basis = field_sources.get("profile", {"source": "pdf"})
            field_sources[field] = {**basis, "source": "calculation", "basis": "profile",
                                    "basis_source": basis.get("source")}
        else:
            field_sources[field] = {"source": "catalog",
                "catalog_version": context.get("material_catalog_version"),
                "resolution": resolution.get("status")}
    if resolution["status"] in ("ambiguous", "unresolved", "catalog_unavailable"):
        label = "tem várias correspondências" if resolution["status"] == "ambiguous" else "não foi encontrado"
        issues.append(issue("material_catalog_" + resolution["status"],
            f"O perfil {values.get('profile') or 'sem designação'} {label} no catálogo validado da macro.",
            field="profile", blocking=True, candidates=resolution["candidates"]))
    for field in REQUIRED_FIELDS:
        if effective.get(field) in (None, ""):
            issues.append(issue("missing_" + field, f"Falta confirmar: {FIELD_LABELS[field]}.", field=field))
    family = str(effective.get("material_type") or "").casefold()
    required_geometry = ()
    if "tubo" in family and "redond" in family:
        required_geometry = ("outer_diameter_mm", "thickness_mm")
    elif "tubo" in family and ("retang" in family or "quadr" in family):
        required_geometry = ("width_mm", "height_mm", "thickness_mm")
    elif ("varão" in family or "varao" in family or "barra" in family) and "redond" in family:
        required_geometry = ("outer_diameter_mm",)
    for field in required_geometry:
        if effective.get(field) in (None, ""):
            issues.append(issue("missing_" + field, f"Falta confirmar: {FIELD_LABELS[field]}.", field=field))
    diameter, thickness = effective.get("outer_diameter_mm"), effective.get("thickness_mm")
    if diameter and thickness and thickness >= diameter / 2:
        issues.append(issue("invalid_wall_thickness", "A espessura do tubo não pode atingir o raio exterior.",
                            field="thickness_mm", blocking=True))
    if required_geometry == ("width_mm", "height_mm", "thickness_mm") and thickness:
        if effective.get("width_mm") and effective.get("height_mm") and thickness * 2 >= min(effective["width_mm"], effective["height_mm"]):
            issues.append(issue("invalid_wall_thickness", "A espessura do tubo é incompatível com as dimensões exteriores.",
                                field="thickness_mm", blocking=True))
    for field in (*REQUIRED_FIELDS, "outer_diameter_mm", "width_mm", "height_mm", "thickness_mm",
                  "angle_deg", "abocardar", "chanfro", "ponteira"):
        evidence = values.get("evidence", {}).get(field)
        non_document_source = field_sources.get(field, {}).get("source") in ("plan", "catalog", "calculation")
        if effective.get(field) not in (None, "") and not _reading_confirmed(piece, field, values):
            if (not evidence or not 1 <= evidence.get("page", 0) <= page_count) and not non_document_source:
                issues.append(issue("evidence_" + field, f"Confirma a origem de {FIELD_LABELS[field].lower()} no PDF.", field=field))
    for field, evidence in values.get("evidence", {}).items():
        if not 1 <= evidence.get("page", 0) <= page_count:
            issues.append(issue("invalid_page_" + field, "A evidência aponta para uma página inexistente.", field=field))
    warning_signature = fingerprint(values.get("warnings", []))
    for i, warning in enumerate(values.get("warnings", [])):
        if (_warning_needs_review(warning, values, resolution, required_geometry)
                and reviewed.get("warning_fingerprint") != warning_signature):
            issues.append(issue(f"reading_{i}", warning))
    cut_angles = re.search(
        r"cortes?(?:\s+(?:das?\s+)?extremidades?|\s+extremos?)?\s*(?:a|:)?\s*"
        r"(-?\d+(?:[.,]\d+)?)\s*°?\s*(?:e|/)\s*(-?\d+(?:[.,]\d+)?)\s*°",
        str(values.get("notes") or ""), re.I)
    if (cut_angles and cut_angles.group(1).replace(",", ".") != cut_angles.group(2).replace(",", ".")
            and not _reading_confirmed(piece, "notes", values)):
        issues.append(issue("conflicting_cut_angles",
            "Foram transcritos ângulos diferentes para as extremidades. Confirma as duas cotas no desenho.",
            field="notes"))
    chanfro_export = values.get("chanfro") in (None, "")
    if values.get("chanfro") not in (None, ""):
        mapping = reviewed.get("mappings", {}).get("chanfro")
        expected = fingerprint({"field": "chanfro", "value": values.get("chanfro"),
                                "operations": values.get("operations", []),
                                "evidence": values.get("evidence", {}).get("chanfro")})
        if mapping != expected:
            issues.append(issue("chanfro_mapping", "Confirma que a indicação técnica corresponde à operação Chanf. da macro.", field="chanfro"))
        else:
            chanfro_export = True
    history = [row for row in context.get("reference_history", [])
               if ref_key(row.get("component_ref")) == ref_key(effective.get("component_ref"))
               and _history_compatible(row, effective)]
    machine_suggestions = []
    for row in history:
        machine = (row.get("row_data") or {}).get("Máquina Corte")
        if machine and not any(item["machine"] == machine for item in machine_suggestions):
            machine_suggestions.append({"machine": machine, "machine_group": _machine_group(machine),
                "production_order": row.get("production_order_no"), "excel_row": row.get("excel_row"),
                "profile": _plan_values(row).get("profile")})

    requested_group = piece.get("machine_group")
    effective_group = requested_group
    assigned_machine = ((candidates[0].get("row_data") or {}).get("Máquina Corte")
                        if len(candidates) == 1 else None)
    assigned_group = _machine_group(assigned_machine)
    if requested_group not in ("Vanguard", "Serrote") and assigned_group:
        effective_group = assigned_group
        field_sources["machine_group"] = {"source": "plan",
            "snapshot_id": context.get("snapshot", {}).get("snapshot_id"),
            "source_line_id": candidates[0].get("source_line_id"),
            "excel_row": candidates[0].get("excel_row")}
        machine_status = "resolved_from_plan"
    elif requested_group in ("Vanguard", "Serrote"):
        field_sources["machine_group"] = {"source": "document_or_user"}
        machine_status = "resolved"
    else:
        machine_status = "unresolved"
        issues.append(issue("machine_unresolved",
            "Não foi possível resolver o grupo de máquina no documento nem numa linha compatível da mesma OF.",
            field="machine_group", blocking=True, suggestions=machine_suggestions))
    if assigned_machine and effective_group in ("Vanguard", "Serrote") and assigned_group != effective_group:
        issues.append(issue("machine_conflict",
            f"A macro atribui {assigned_machine}, mas a seleção atual indica {effective_group}.",
            blocking=True, field="machine_group"))
        machine_status = "conflict"
    vanguard = [m for m in context.get("machines", []) if "vanguard" in m.casefold()]
    machine_update = (vanguard[0] if effective_group == "Vanguard" and not assigned_machine
                      and len(vanguard) == 1 else None)
    machine_resolution = {"status": machine_status, "machine_group": effective_group,
                          "assigned_machine": assigned_machine,
                          "suggestions": machine_suggestions}

    if len(candidates) > 1:
        issues.append(issue("plan_ambiguous", "Há várias linhas no planeamento para esta referência. A associação precisa de conferência.", blocking=True))
        return issues, {"kind": "ambiguous", "candidate_rows": [r["excel_row"] for r in candidates],
                        "material_resolution": resolution, "effective_values": effective,
                        "field_sources": field_sources, "machine_group": effective_group,
                        "machine_resolution": machine_resolution, "chanfro_export": chanfro_export}
    if not candidates:
        return issues, {"kind": "new", "quantity_completed": None, "quantity_to_plan": None,
                        "material_resolution": resolution, "effective_values": effective,
                        "field_sources": field_sources, "machine_group": effective_group,
                        "machine_resolution": machine_resolution,
                        "machine_update": machine_update, "chanfro_export": chanfro_export}
    row = candidates[0]
    raw = row["row_data"]
    row_population = row.get('population') or planning_population.classify({'closed_x':row.get('closed_x'),'raw':raw})
    if 'Macro' in row_population['closed_sources']:
        issues.append(issue("plan_row_closed", "A linha correspondente está fechada na macro e não pode ser alterada automaticamente.",
                            blocking=True))
    for unknown in row_population['unknown_states']:
        if unknown['source']=='Macro':
            issues.append(issue('closure_state_unknown',f"Estado de fecho desconhecido na macro: {unknown['value']}. Não interpretado como fechado."))
    completed = _numeric(raw.get("Ser."))
    comparison = _plan_values(row)
    # A comparação de escrita respeita o branco deliberado da célula AG; o
    # valor estruturado acima serve para cálculo/proveniência, não finge que a
    # célula já estava preenchida.
    comparison["profile"] = _input(raw, "Designação Perfil", row.get("profile_type"))
    differences = []
    for field, old in comparison.items():
        current = effective.get(field)
        equal = _profile(current) == _profile(old) if field in ("profile", "grade", "material_type") else current == old
        if current is not None and not equal:
            differences.append({"field": field, "pdf": values.get(field), "resolved": current,
                                "plan": old, "kind": "fill" if old in (None, "") else "change"})
            if old not in (None, "") and not _difference_confirmed(piece, field, effective, old, row["source_line_id"]):
                issues.append(issue("different_" + field,
                    f"{FIELD_LABELS[field]} difere do planeamento: PDF {current}; plano {old or 'vazio'}.", field=field))
    if completed is not None and effective.get("quantity_required") is not None and completed > effective["quantity_required"]:
        issues.append(issue("below_completed", "A quantidade do PDF é inferior à produção já registada. É necessário reconciliar a revisão.", blocking=True))
    geometry_changed = any(d["kind"] == "change" and d["field"] in (
        "length_mm", "profile", "grade", "material_type", "outer_diameter_mm", "width_mm", "height_mm", "thickness_mm", "angle_deg"
    ) for d in differences)
    if geometry_changed and completed and completed > 0:
        issues.append(issue("changed_after_production", "A especificação mudou e já existe produção registada. A revisão requer reconciliação antes de preencher a macro.", blocking=True))
    return issues, {"kind": "changed" if differences else "existing", "excel_row": row["excel_row"],
        "source_plan_key": row["source_line_id"], "differences": differences,
        "material_resolution": resolution, "effective_values": effective,
        "field_sources": field_sources, "machine_group": effective_group,
        "machine_resolution": machine_resolution,
        "machine_update": machine_update, "assigned_machine": assigned_machine,
        "chanfro_export": chanfro_export,
        "quantity_completed": completed, "aboc_completed": _numeric(raw.get("Aboc.")),
        "closed_x": row["closed_x"], "population":row_population, "quantity_to_plan": (
            max(0, comparison["quantity_required"] - completed)
            if completed is not None and comparison["quantity_required"] is not None else None)}
