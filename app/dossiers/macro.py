"""Preencher uma CÓPIA XLSM por edição cirúrgica do OOXML.

Não abrir/gravar a macro com openpyxl: isso perderia extensões, desenhos e
outros elementos. Só se alteram células de entrada na folha Planeamento e
a opção de recálculo. O projeto VBA e os restantes membros ZIP são preservados.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import io
import re
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from openpyxl.formula.translate import Translator
from openpyxl.utils.cell import column_index_from_string

from . import DossierError, cpis, store
from .models import FIELD_LABELS, fingerprint, need_key, specification

S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = {"s": S, "r": R}
HEADER_ROW = 6
INPUT_MAP = {"E": "production_order", "L": "component_ref", "AF": "material_type",
             "AG": "profile", "AH": "quantity_required", "AI": "outer_diameter_mm",
             "AJ": "width_mm", "AK": "height_mm", "AL": "thickness_mm",
             "AM": "length_mm", "AO": "grade",
             "T": "abocardar", "U": "chanfro"}
EXPECTED_HEADERS = {"A": "ID", "E": "OF Nº", "L": "Referência", "AF": "Tipo de Material", "AG": "Designação Perfil",
                    "T": "Aborc.", "U": "Chanf.", "AH": "QTD [un,]",
                    "AI": "Ø Externo [mm]", "AJ": "Largura (w) [mm]",
                    "AK": "Altura (h) [mm]", "AL": "Espessura (t) [mm]",
                    "AM": "Comp, [mm]", "AN": "Ang,", "AO": "Qual.",
                    "AQ": "Máquina Corte", "AT": "Observações"}
# Nenhum campo desta lista representa produção realizada ou uma previsão calculada.
PRESERVED_PRODUCTION = {"I", "V", "W", "X", "Y", "Z", "AA", "AB", "AC", "AD", "AR", "AS",
                        "AU", "AV", "AW", "AZ", "BB", "BC", "BD", "BE", "CL", "CM", "CN", "CO",
                        "CP", "CQ", "CR", "CS", "CT", "CU", "CV", "CW", "CX"}
WRITABLE_COLUMNS = set(INPUT_MAP) | {"A", "AQ", "AT"}
assert WRITABLE_COLUMNS.isdisjoint(PRESERVED_PRODUCTION)


def export_rows(document_ids: list[str] | None = None) -> list:
    ids = document_ids or sorted({p["document_id"] for p in store.plan_rows()})
    if not ids:
        raise DossierError("Ainda não existem linhas preparadas para exportar.", 409)
    from .pipeline import reconcile
    selected, identities = [], {}
    for uid in ids:
        doc = store.get_document(uid)
        if doc["status"] not in ("ready", "review"):
            raise DossierError("Conclui a leitura do dossiê antes de gerar a saída.", 409)
        # A exportação nunca confia num estado CPIS guardado dias antes.
        reconcile(uid)
        doc = store.get_document(uid)
        if doc["status"] != "ready" or not doc["pieces"]:
            raise DossierError("Há dados por confirmar ou o CPIS mudou. Abre o dossiê e resolve as indicações antes de exportar.", 409)
        for piece in doc["pieces"]:
            if piece["state"] == "excluded":
                continue
            if piece["state"] == "superseded":
                raise DossierError("Uma linha deste dossiê foi substituída. Exporta a versão mais recente.", 409)
            if piece["state"] not in ("ready", "existing", "duplicate"):
                raise DossierError("Existem linhas por confirmar. A macro não foi gerada parcialmente.", 409)
            effective_values = piece.get("match", {}).get("effective_values") or piece["values"]
            effective_group = piece.get("match", {}).get("machine_group") or piece["machine_group"]
            key = need_key(doc["production_order"], effective_group, effective_values)
            spec = specification(effective_values)
            if key in identities:
                if identities[key] != spec:
                    raise DossierError("Existem versões incompatíveis da mesma peça na seleção.", 409)
                continue
            identities[key] = spec
            selected.append({**piece, "machine_group": effective_group,
                             "production_order": doc["production_order"], "context": doc["context"],
                             "filename": doc["filename"]})
    snapshots = {r["context"]["snapshot"]["snapshot_id"] for r in selected}
    if len(snapshots) > 1:
        raise DossierError("A importação do CPIS mudou durante a preparação. Tenta novamente.", 409)
    if not selected:
        raise DossierError("Todas as linhas deste dossiê foram excluídas na conferência.", 409)
    return selected


def _safe_csv(value):
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        value = "; ".join(value) if isinstance(value, list) else str(value)
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def csv_bytes(rows) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["OF", "OV", "Cliente", "Designação", "Distribuição", *FIELD_LABELS.values(), "PDF", "Página do índice", "Páginas do desenho"])
    for row in rows:
        context = row["context"]
        writer.writerow([_safe_csv(v) for v in [row["production_order"], context.get("sales_order"),
            context.get("customer"), context.get("designation"), row["machine_group"],
            *(row["values"].get(k) for k in FIELD_LABELS), row["filename"], row["index_page"],
            ", ".join(map(str, row["drawing_pages"]))]])
    return output.getvalue().encode("utf-8-sig")


def _sheet_path(archive):
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    sheet = next((s for s in workbook.findall("s:sheets/s:sheet", NS) if s.get("name") == "Planeamento"), None)
    if sheet is None:
        raise DossierError("A macro não contém a folha Planeamento esperada.", 409)
    rel_id = sheet.get(f"{{{R}}}id")
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    target = next((r.get("Target") for r in rels if r.get("Id") == rel_id), None)
    if not target:
        raise DossierError("A ligação à folha Planeamento é inválida.", 409)
    return target.lstrip("/") if target.startswith("/") else "xl/" + target


def _namespaces(xml):
    start = xml.index(b"<worksheet")
    tag = xml[start:xml.index(b">", start) + 1]
    declarations = b" ".join(re.findall(rb'xmlns(?::[\w]+)?="[^"]+"', tag))
    for prefix, uri in re.findall(rb'xmlns(?::([\w]+))?="([^"]+)"', tag):
        ET.register_namespace(prefix.decode(), uri.decode())
    return declarations


def _row_match(xml, number):
    return re.search(rb'<row\b[^>]*\br="' + str(number).encode() + rb'"[^>]*(?:/>|>.*?</row>)', xml, re.S)


def _parse_row(raw, declarations):
    return list(ET.fromstring(b"<root " + declarations + b">" + raw + b"</root>"))[0]


def _col(cell):
    return re.sub(r"\d", "", cell.get("r", ""))


def _value(cell, shared):
    if cell is None:
        return None
    if cell.get("t") == "inlineStr":
        return "".join(cell.itertext())
    value = cell.findtext(f"{{{S}}}v")
    if cell.get("t") == "s" and value is not None:
        return shared[int(value)]
    return value


def _input_cell(column, row_number, value, original=None):
    cell = ET.Element(f"{{{S}}}c", {"r": f"{column}{row_number}"})
    if original is not None and original.get("s"):
        cell.set("s", original.get("s"))
    if value is None or value == "":
        return cell
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        ET.SubElement(cell, f"{{{S}}}v").text = str(value)
    else:
        # Inline string, jamais une formule provenant du document ou du modèle.
        if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff]", str(value)):
            raise DossierError("Um campo contém caracteres inválidos para Excel. Corrige o texto antes de exportar.", 409)
        cell.set("t", "inlineStr")
        ET.SubElement(ET.SubElement(cell, f"{{{S}}}is"), f"{{{S}}}t").text = str(value)
    return cell


def _same_value(before, after):
    if before in (None, "", " ") and after in (None, ""):
        return True
    if isinstance(after, (int, float)) and not isinstance(after, bool):
        try:
            return float(before) == float(after)
        except (TypeError, ValueError):
            return False
    return str(before) == str(after)


def _technical_note(piece: dict) -> str:
    def clean(value):
        return re.sub(r"\s+", " ", str(value)).strip()

    pages = ",".join(map(str, piece["drawing_pages"]))
    if piece.get("technical_origin") == "manual":
        marker = "planeamento:" + str(piece.get("record_id") or "")[:16]
        parts = [f"Ficha manual · {piece['machine_group']}",
                 f"Responsável: {piece.get('actor') or 'não indicado'}"]
    else:
        marker = "dossier:" + need_key(piece["production_order"], piece["machine_group"], piece["values"])[:16]
        parts = [f"PDF {piece['filename']} · p. {pages} · {piece['machine_group']}"]
    selection = piece.get("selection") or {}
    if selection.get("source"):
        parts.append(f"Seleção: {selection['source']} p. {selection.get('page') or piece['index_page']}")
    plan_sources = {source.get("excel_row") for source in piece.get("match", {}).get("field_sources", {}).values()
                    if source.get("source") == "plan" and source.get("excel_row")}
    if plan_sources:
        parts.append("Campos complementados pelo plano, linha(s) " + ",".join(map(str, sorted(plan_sources))))
    operations = list(piece["values"].get("operations", []))
    if operations:
        parts.append("; ".join(clean(value) for value in operations))
    if piece["values"].get("angle_deg") is not None:
        parts.append(f"Ângulo indicado no desenho: {piece['values']['angle_deg']}° (sem conversão para Ang,)")
    if piece["values"].get("chanfro") is not None and not any("chanfr" in op.casefold() for op in operations):
        parts.append("Indicação de chanfro: " + str(piece["values"]["chanfro"]))
    if piece["values"].get("notes"):
        parts.append(clean(piece["values"]["notes"]))
    if piece["values"].get("drawing_revision"):
        parts.append("Revisão do desenho: " + piece["values"]["drawing_revision"])
    if piece["values"].get("ponteira") is not None:
        parts.append("Ponteira: " + piece["values"]["ponteira"])
    return f"[{marker}] " + " · ".join(clean(value) for value in parts)


def _shared_formulas(xml):
    result = {}
    pattern = re.compile(rb'<c\b[^>]*\br="([A-Z]+\d+)"[^>]*>\s*<f\b([^>]*)>([^<]+)</f>', re.S)
    from html import unescape
    for match in pattern.finditer(xml):
        attributes = match[2]
        si = re.search(rb'\bsi="(\d+)"', attributes)
        if si and b't="shared"' in attributes and match[3]:
            result[si[1].decode()] = (match[1].decode(), unescape(match[3].decode()))
    return result


def _formula_clone(cell, target_row, shared_formulas):
    result = copy.deepcopy(cell)
    origin = cell.get("r")
    target = _col(cell) + str(target_row)
    result.set("r", target)
    formula = result.find(f"{{{S}}}f")
    expression = formula.text
    if formula.get("t") == "shared" and not expression:
        if formula.get("si") not in shared_formulas:
            raise DossierError("Não foi possível prolongar uma fórmula partilhada da macro.", 409)
        origin, expression = shared_formulas[formula.get("si")]
    if not expression:
        raise DossierError("A linha modelo contém uma fórmula sem expressão.", 409)
    try:
        formula.text = Translator("=" + expression, origin=origin).translate_formula(target)[1:]
    except Exception:
        raise DossierError("Não foi possível prolongar uma fórmula da macro com segurança.", 409) from None
    array = formula.get("t") == "array"
    if array and ":" in formula.get("ref", ""):
        raise DossierError("A macro contém uma fórmula matricial que abrange várias células. É necessário adaptar o mapeamento.", 409)
    formula.attrib.clear()
    if array:
        formula.set("t", "array")
        formula.set("ref", target)
    for value in list(result.findall(f"{{{S}}}v")):
        result.remove(value)
    result.attrib.pop("t", None)
    return result


def fill_macro(rows: list[dict], *, source_bytes: bytes | None = None) -> tuple[bytes, dict]:
    if not rows:
        raise DossierError("Não existem linhas a preencher.", 409)
    context = rows[0]["context"]
    source = context["source"]
    path = Path(source["source_path"])
    if source_bytes is None:
        if not path.is_file() or path.suffix.lower() != ".xlsm":
            raise DossierError("A macro de origem não está disponível no servidor.", 409)
        source_bytes = path.read_bytes()
    if hashlib.sha256(source_bytes).hexdigest() != source["source_sha256"]:
        raise DossierError("A macro mudou desde a importação do CPIS. Atualiza a importação antes de gerar a cópia.", 409)
    with ZipFile(io.BytesIO(source_bytes)) as archive:
        sheet_path = _sheet_path(archive)
        xml = archive.read(sheet_path)
        declarations = _namespaces(xml)
        shared = ["".join(e.itertext()) for e in ET.fromstring(archive.read("xl/sharedStrings.xml"))] if "xl/sharedStrings.xml" in archive.namelist() else []
        header_match = _row_match(xml, HEADER_ROW)
        if not header_match:
            raise DossierError("O cabeçalho da macro mudou; é necessário atualizar o mapeamento.", 409)
        header = {_col(c): _value(c, shared) for c in _parse_row(header_match.group(), declarations)}
        if any((header.get(k) or "").strip() != v for k, v in EXPECTED_HEADERS.items()):
            raise DossierError("As colunas da macro diferem do mapeamento validado. A cópia não foi gerada.", 409)
        last_row = int(context["tail"]["last_row"] or HEADER_ROW)
        last_id = int(context["tail"]["last_id"] or 0)
        template_match = _row_match(xml, last_row)
        if not template_match or last_row <= HEADER_ROW:
            raise DossierError("Não existe uma linha modelo para conservar as fórmulas da macro.", 409)
        template = _parse_row(template_match.group(), declarations)
        shared_formulas = _shared_formulas(xml)
        changes, cell_changes, added, updated, unchanged = [], [], 0, 0, 0
        touched = set()
        for piece in rows:
            piece_change_start = len(cell_changes)
            match = piece["match"]
            is_new = match["kind"] == "new"
            if not is_new and match["kind"] not in ("changed", "existing"):
                raise DossierError("Existe uma associação ao planeamento por resolver.", 409)
            if is_new:
                last_row += 1
                last_id += 1
                target_row = last_row
                added += 1
            else:
                target_row = match["excel_row"]
            if target_row in touched:
                raise DossierError("Duas necessidades tentam preencher a mesma linha da macro.", 409)
            touched.add(target_row)
            found = _row_match(xml, target_row)
            if not found:
                raise DossierError("A macro não tem linhas preparadas suficientes. Prolonga a área de entrada no Excel e volta a importar.", 409)
            original = _parse_row(found.group(), declarations)
            cells = {_col(c): c for c in original}
            of_value = _value(cells.get("E"), shared)
            if is_new and of_value not in (None, "", " "):
                raise DossierError("A linha de destino já contém uma OF. Atualiza a importação da macro.", 409)
            if not is_new and of_value != piece["production_order"]:
                raise DossierError("A linha da macro já não corresponde à OF conferida.", 409)
            if is_new:
                for template_cell in template:
                    col = _col(template_cell)
                    if template_cell.find(f"{{{S}}}f") is not None and (col not in cells or cells[col].find(f"{{{S}}}f") is None):
                        if cells.get(col) is not None and _value(cells[col], shared) not in (None, "", " "):
                            continue
                        cells[col] = _formula_clone(template_cell, target_row, shared_formulas)
                cells["A"] = _input_cell("A", target_row, last_id, cells.get("A"))
                cell_changes.append({"row": target_row, "column": "A", "field": "row_id",
                    "before": _value(original.find(f"{{{S}}}c[@r='A{target_row}']"), shared),
                    "after": last_id, "reason": "identificador da nova linha"})
            values = {**piece["values"], **match.get("effective_values", {}),
                      "production_order": piece["production_order"]}
            fields = set(INPUT_MAP) if is_new else {col for col, field in INPUT_MAP.items()
                if field in {d["field"] for d in match["differences"]}}
            if not match.get("chanfro_export", False):
                fields.discard("U")
            for col in sorted(fields, key=column_index_from_string):
                if cells.get(col) is not None and cells[col].find(f"{{{S}}}f") is not None:
                    raise DossierError(f"A coluna {col} passou a ser calculada. Atualiza o mapeamento antes de preencher.", 409)
                before = _value(cells.get(col), shared)
                after = values.get(INPUT_MAP[col])
                if _same_value(before, after):
                    continue
                cells[col] = _input_cell(col, target_row, after, cells.get(col))
                cell_changes.append({"row": target_row, "column": col, "field": INPUT_MAP[col],
                    "before": before, "after": after,
                    "reason": "nova necessidade" if is_new else "diferença conferida ou campo em falta"})
            machines = [m for m in context["machines"] if "vanguard" in m.casefold()]
            machine = (machines[0] if is_new and piece["machine_group"] == "Vanguard" and len(machines) == 1
                       else match.get("machine_update"))
            if machine and not _same_value(_value(cells.get("AQ"), shared), machine):
                before = _value(cells.get("AQ"), shared)
                cells["AQ"] = _input_cell("AQ", target_row, machine, cells.get("AQ"))
                cell_changes.append({"row": target_row, "column": "AQ", "field": "machine",
                    "before": before, "after": machine, "reason": "distribuição Vanguard inequívoca"})
            note = _technical_note(piece)
            existing_note = _value(cells.get("AT"), shared)
            note_lines = str(existing_note or "").splitlines()
            marker = note.partition("]")[0] + "]"
            matching = [index for index, line in enumerate(note_lines) if line.startswith(marker)]
            if not matching:
                after_note = "\n".join(filter(None, [existing_note, note]))
            elif len(matching) > 1 or note_lines[matching[0]] != note:
                first = matching[0]
                note_lines = [line for index, line in enumerate(note_lines) if index not in matching]
                note_lines.insert(first, note)
                after_note = "\n".join(note_lines)
            else:
                after_note = existing_note
            if not _same_value(existing_note, after_note):
                cells["AT"] = _input_cell("AT", target_row, after_note, cells.get("AT"))
                cell_changes.append({"row": target_row, "column": "AT", "field": "notes",
                    "before": existing_note, "after": after_note, "reason": "proveniência técnica do dossiê"})
            if not is_new and len(cell_changes) == piece_change_start:
                unchanged += 1
                continue
            for cell in cells.values():
                if cell.find(f"{{{S}}}f") is not None:
                    # Um cache do lote anterior seria um valor errado no novo PDF.
                    for value in list(cell.findall(f"{{{S}}}v")):
                        cell.remove(value)
                    cell.attrib.pop("t", None)
            output_row = copy.deepcopy(original)
            for child in list(output_row):
                output_row.remove(child)
            for col in sorted(cells, key=column_index_from_string):
                output_row.append(cells[col])
            changes.append((found.start(), found.end(), ET.tostring(output_row, encoding="utf-8")))
            if not is_new:
                updated += 1
        # Não voltar a serializar um milhão de linhas formatadas sem dados.
        for start, end, replacement in sorted(changes, reverse=True):
            xml = xml[:start] + replacement + xml[end:]
        workbook = archive.read("xl/workbook.xml")
        calc = re.search(rb'<calcPr\b[^>]*(?:/>|>.*?</calcPr>)', workbook)
        replacement = b'<calcPr calcMode="auto" fullCalcOnLoad="1" forceFullCalc="1"/>'
        workbook = workbook[:calc.start()] + replacement + workbook[calc.end():] if calc else workbook.replace(b"</workbook>", replacement + b"</workbook>")
        out = io.BytesIO()
        with ZipFile(out, "w") as result:
            for info in archive.infolist():
                content = xml if info.filename == sheet_path else workbook if info.filename == "xl/workbook.xml" else archive.read(info.filename)
                result.writestr(info, content)
    if any(change["column"] not in WRITABLE_COLUMNS for change in cell_changes):
        raise DossierError("A proposta contém uma coluna fora do contrato de escrita.", 409)
    return out.getvalue(), {"added": added, "updated": updated, "unchanged": unchanged,
                            "cells": cell_changes,
                            "source_sha256": hashlib.sha256(source_bytes).hexdigest()}


def preview_macro(rows: list[dict], *, source_bytes: bytes | None = None) -> dict:
    _output, summary = fill_macro(rows, source_bytes=source_bytes)
    return summary
