"""Fichas de planeamento. Fontes importadas só de leitura; escrita própria.

Uma ficha guarda valores absolutos declarados, nunca incrementa Ser./Aboc.
Assim, reabrir ou corrigir uma ficha não representa uma nova produção.
"""
from __future__ import annotations

import json
import hashlib
import os
import uuid
from datetime import date, datetime
from decimal import Decimal

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .config import settings
from .dossiers.models import order_number

AREAS = {
    "perfis": ("ds-met2-perfis", "MTG2 Perfis"),
    "cantoneiras": ("ds-2638099daddc474e", "MTG3 Cantoneiras"),
}
OPEN_STATES = ("Em Aberto", "Em Produção")


class PlanningError(Exception):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def connect(*, readonly=False):
    conn = psycopg.connect(os.environ.get("MES_PG_DSN") or settings.pg_dsn,
                          row_factory=dict_row, connect_timeout=5)
    conn.read_only = readonly
    return conn


def serializable(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=lambda x:
        float(x) if isinstance(x, Decimal) else str(x) if isinstance(x, uuid.UUID) else x.isoformat()))


def check_area(area):
    if not isinstance(area, str) or area not in AREAS:
        raise PlanningError("Seleciona Perfis ou Cantoneiras.")
    return area


def snapshot(conn, area):
    check_area(area)
    row = conn.execute(
        "SELECT snapshot_id, source_filename, loaded_at FROM audit_mtg.snapshots "
        "WHERE dataset_id = %s ORDER BY loaded_at DESC, snapshot_id DESC LIMIT 1",
        (AREAS[area][0],),
    ).fetchone()
    if not row:
        raise PlanningError("Ainda não existe um ficheiro importado para esta área.", 503)
    return row


def _text(value):
    return str(value or "").replace("_x000D_", "").strip()


def _number(value):
    # Excel sources contain text such as "1 543" in Cantoneiras!Comp. One reader for the whole app (08/10, F19).
    from .planning_calculations import number
    return number(value)


def _date(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    text = _text(value)
    try:
        return date.fromisoformat(text[:10]).isoformat() if text else ""
    except ValueError:
        return ""


def _pick(d, *names):
    for name in names:
        if d.get(name) not in (None, ""):
            return d[name]
    return None


def _catalogs(conn, area, snapshot_id):
    aux = conn.execute(
        "SELECT sheet_name, excel_row, row_data FROM raw_mtg.other_sheet_rows "
        "WHERE snapshot_id=%s AND sheet_name IN ('Dados','Picking') ORDER BY excel_row",
        (snapshot_id,),
    ).fetchall()
    from . import planning_dates
    picking_rows = [r for r in aux if r['sheet_name'] == 'Picking']
    picking, picking_evidence = planning_dates.picking_index(picking_rows)
    machines, types, teams, operations = set(), set(), set(), set()
    profiles = {}
    for row in aux:
        v = row["row_data"].get("values", [])
        if area == "perfis" and row["sheet_name"] == "Dados" and row["excel_row"] >= 3:
            if len(v) > 1 and v[1]: machines.add(_text(v[1]))
            if len(v) > 4 and v[4]: types.add(_text(v[4]))
            if len(v) > 6 and v[6]: teams.add(_text(v[6]))
        if area == "cantoneiras" and row["sheet_name"] == "Dados" and row["excel_row"] >= 3:
            if len(v) > 1 and v[1] and _text(v[1]) != "Rendimento": machines.add(_text(v[1]))
            if len(v) > 4 and v[4]: types.add(_text(v[4]))
            if len(v) > 10 and v[10] and _text(v[10]).casefold() != "equipa": teams.add(_text(v[10]))
            if len(v) > 7 or len(v) > 8:
                operation = " · ".join(_text(v[i]) for i in (7, 8) if i < len(v) and v[i])
                if operation: operations.add(operation)
    if area == "cantoneiras":
        machines = {r["display_name"] for r in conn.execute(
            "SELECT display_name FROM core_mtg.machines WHERE snapshot_id=%s",
            (snapshot_id,),
        ).fetchall() if r["display_name"] != "Rendimento"}
        types = {"Cantoneira", "Perfil U", "Perfil I", "Perfil H", "Chapa", "Tubo", "Outro"}
        for row in conn.execute(
            "SELECT operation_code,operation_description,material_type,row_data "
            "FROM raw_mtg.machine_rows WHERE snapshot_id=%s", (snapshot_id,),
        ).fetchall():
            raw = row.get("row_data") or {}
            if row.get("material_type"): types.add(_text(row["material_type"]))
            team = raw.get("column_11") or raw.get("Equipa")
            if team and _text(team).casefold() != "equipa": teams.add(_text(team))
            code, description = row.get("operation_code"), row.get("operation_description")
            if code or description:
                operations.add(" · ".join(v for v in (_text(code), _text(description)) if v))
    else:
        # O importador guarda Dados!B e os catálogos paralelos nesta tabela.
        # As colunas são listas independentes, não relações máquina/material/equipa.
        for row in conn.execute(
            "SELECT machine_name, material_type, row_data FROM raw_mtg.machine_rows WHERE snapshot_id=%s",
            (snapshot_id,),
        ).fetchall():
            if row["machine_name"]: machines.add(_text(row["machine_name"]))
            if row["material_type"]: types.add(_text(row["material_type"]))
            if row["row_data"].get("Equipa"): teams.add(_text(row["row_data"]["Equipa"]))
        catalog_rows = conn.execute("""SELECT excel_row,row_data FROM raw_mtg.other_sheet_rows
            WHERE snapshot_id=%s AND sheet_name='AreaSecaoCorte'
            ORDER BY excel_row""", (snapshot_id,)).fetchall()
        header = ((catalog_rows[0].get("row_data") or {}).get("values") or []) if catalog_rows else []
        for row in catalog_rows[1:]:
            values = (row.get("row_data") or {}).get("values") or []
            for column, family in enumerate(values[13:33], start=13):
                if family not in (None, "", "-"):
                    name = _text(header[column]) if column < len(header) else ""
                    if name:
                        profiles.setdefault(name, set()).add(_text(family))
    types |= {"Tubo redondo", "Tubo quadrado", "Tubo retangular", "Varão redondo",
              "Varão quadrado", "Barra", "Cantoneira", "Calha", "Chapa", "Outro"}
    return {"machines": sorted(machines), "material_types": sorted(types),
            "teams": sorted(teams), "operations": sorted(operations),
            "profiles": {key: sorted(values) for key, values in sorted(profiles.items())},
            "picking": picking, "picking_evidence": picking_evidence}


def bootstrap(area):
    with connect(readonly=True) as conn:
        info = snapshot(conn, area)
        catalogs = _catalogs(conn, area, info["snapshot_id"])
        catalogs.pop("picking")
    return serializable({"area": area, "snapshot": info, **catalogs,
                         "fields": field_contract(area, catalogs, info["snapshot_id"])})


def field_contract(area, catalogs, catalog_version):
    """Contrato comum do formulário; a validação efetiva continua no servidor."""
    specs = [
        ("component_ref", "Referência", "text", None, True, None),
        ("identity_discriminator", "Discriminador / variante", "text", None, False, None),
        ("material_type", "Tipo de material", "select", None, True, catalogs["material_types"]),
        ("profile", "Perfil normalizado", "select", None, True, sorted({v for rows in catalogs["profiles"].values() for v in rows})),
        ("custom_profile", "Perfil especial", "select", None, False, [False, True]),
        ("grade", "Qualidade", "text", None, False, None),
        ("outer_diameter_mm", "Diâmetro exterior", "number", "mm", False, None),
        ("width_mm", "Largura / lado", "number", "mm", False, None),
        ("height_mm", "Altura", "number", "mm", False, None),
        ("thickness_mm", "Espessura", "number", "mm", False, None),
        ("length_mm", "Comprimento", "number", "mm", True, None),
        ("angle_deg", "Ângulo", "number", "graus", False, None),
        ("quantity_required", "Quantidade necessária", "number", "un.", True, None),
        ("quantity_to_plan", "Quantidade a planear", "number", "un.", False, None),
        ("operation", "Operação principal", "select", None, True, ["corte", "abocardar"]),
        ("operation_detail", "Operação do catálogo", "select", None, False, catalogs["operations"]),
        ("machine", "Máquina", "select", None, False, catalogs["machines"]),
        ("team", "Equipa", "select", None, False, catalogs["teams"]),
        ("pavilion", "Pavilhão", "text", None, False, None),
        ("cut_date", "Data Corte", "date", None, False, None),
        ("expected_date", "Previsão de execução", "date", None, False, None),
        ("notes", "Observações locais", "text", None, False, None),
    ]
    conditional = {
        "outer_diameter_mm": ["tubo redondo", "varão redondo"],
        "width_mm": ["tubo quadrado", "tubo retangular", "varão quadrado", "barra", "chapa"],
        "height_mm": ["tubo retangular", "barra", "chapa"],
        "thickness_mm": ["tubo redondo", "tubo quadrado", "tubo retangular", "chapa", "cantoneira", "calha"],
    }
    return [{"id": key, "label": label, "type": kind, "unit": unit,
             "required_when_ready": required,
             "visible_for_materials": conditional.get(key),
             "options": options, "catalog_source": "macro_" + area,
             "catalog_version": catalog_version,
             "current_value": None, "suggested_value": None}
            for key, label, kind, unit, required, options in specs]


def search_orders(area, query=""):
    from . import planning_hub
    result = planning_hub.list_orders(query=query, page=1, page_size=40)
    info = bootstrap(area)["snapshot"]
    orders = [{"of": row["of"], "ov": ", ".join(row.get("ovs") or []),
               "customer": row.get("customer_name"), "designation": row.get("observations"),
               "cpis_status": row.get("cpis_status"), "line_count": row.get("plan", {}).get(area, 0),
               "cpis_version": result["version"]} for row in result["orders"] if row['of'] is not None]
    return {"snapshot": info, "cpis_version": result["version"], "orders": orders}


def _source_rows(conn, snapshot_id, production_order=None, plan_key=None):
    return conn.execute(
        """SELECT r.*, p.remaining_quantity AS canonical_remaining, p.remaining_valid,
                  o.cpis_status, o.cpis_delivery_date, o.cpis_planned_finish_date
             FROM raw_mtg.plan_production_rows r
             JOIN analytics_mtg.kanban_plan_lines p
               ON p.snapshot_id=r.snapshot_id AND p.plan_key=r.source_line_id
             LEFT JOIN core_mtg.production_orders o
               ON o.snapshot_id=r.snapshot_id AND o.production_order_no=r.production_order_no
            WHERE r.snapshot_id=%s AND (%s::text IS NULL OR
              regexp_replace(trim(r.production_order_no),'^OF[ ._-]*','','i')=regexp_replace(%s,'^OF[ ._-]*','','i'))
              AND (%s::text IS NULL OR r.source_line_id=%s)
            ORDER BY r.excel_row""",
        (snapshot_id, production_order, production_order, plan_key, plan_key),
    ).fetchall()


def line_data(row, area, picking):
    d = row["row_data"]
    raw_cut = _number(d.get("Ser.")) if area == "perfis" else _number(row.get("quantity_made"))
    length = _number(row.get("length_mm"))
    if length is None and area == "cantoneiras":
        # The legacy importer leaves grouped numeric text NULL. Read the
        # original cell without rewriting that imported projection.
        length = _number(d.get("Comp."))
    values = {
        "component_ref": _text(row["component_ref"]),
        "cut_date": _date(row.get("cut_date")),
        "expected_date": _date(d.get("Data prevista")),
        "operation": "corte", "abocardar": _text(d.get("Aborc.")),
        "chanfro": _text(_pick(d, "Chanf.", "Chanfro")), "ponteira": _text(d.get("Ponteira")),
        "other_operations": "; ".join(f"{k}: {d[k]}" for k in ("1ª Oper.", "2ª Oper.", "Forja", "Alar. Furos", "Serr./Sold.") if d.get(k) not in (None, "", 0)),
        "material_type": _text(row.get("material_type")),
        "material_description": _text(row.get("material_description")),
        "profile": _text(row.get("profile_type")), "custom_profile": False,
        "outer_diameter_mm": _number(d.get("Ø Externo [mm]")),
        "width_mm": _number(d.get("Largura (w) [mm]")),
        "height_mm": _number(d.get("Altura (h) [mm]")),
        "thickness_mm": _number(d.get("Espessura (t) [mm]")),
        "length_mm": length, "angle_deg": _number(_pick(d,"Ang,","Ang.")),
        # Perfis AH is the writable planning quantity used by AP's area
        # formula and by the PDF comparison. N belongs to the older source
        # projection; retain it in row_data instead of substituting it for AH.
        # A present but blank/invalid AH must remain unknown.
        "quantity_required": _number(d.get("QTD [un,]", row.get("quantity_planned"))
                                     if area == "perfis" else row.get("quantity_planned")),
        "quantity_to_plan": _number(row["canonical_remaining"]) if row["remaining_valid"] else None,
        "quantity_completed": raw_cut,
        "grade": _text(_pick(d,"Qual.","Qual.__2")),
        "material_request_date": _date(d.get("Data requisição de material")),
        "material_available_date": _date(d.get("Data Material")),
        "material_lot": _text(d.get("Nº lote")),
        "team": _text(row.get("team") or d.get("Equipa")),
        "pavilion": _text(row.get("pavilion") or d.get("Pav.")),
        "machine": _text(d.get("Máquina Corte") or row.get("cutting_machine")),
        "picking_week": picking.get(row["production_order_no"]), "picking_year": None,
        "weekly_capacity_hours": None, "finish_week": None, "finish_year": None,
        "notes": _text(_pick(d,"Observações","OBSERVAÇÕES")),
    }
    # Não reinterpretar valores de tempo/semana antigos ou erros Excel como previsões.
    return serializable({
        "plan_key": row["source_line_id"], "excel_row": row["excel_row"],
        "external_id": row.get("external_row_number"), "of": row["production_order_no"],
        "ov": row.get("sales_order_no"), "customer": row.get("customer_name"),
        "designation": _text(row.get("designation")), "cpis_status": row["cpis_status"],
        "cpis_delivery_date": _date(row["cpis_delivery_date"]),
        "cpis_planned_finish_date": _date(row.get("cpis_planned_finish_date")),
        "source_cut_completed": raw_cut, "source_aboc_completed": _number(d.get("Aboc.")),
        "source_remaining": row["canonical_remaining"], "remaining_valid": row["remaining_valid"],
        "source_quantity_aux": _number(d.get("QTD [un,]")), "closed_x": row["closed_x"],
        "values": values,
    })


def order_lines(area, production_order, *, population='active'):
    from . import planning_hub, planning_population, planning_order_population
    population = planning_population.scope(population)
    detail = planning_hub.order_detail(production_order)
    production_order = detail['context']['of']
    with connect(readonly=True) as conn:
        info = snapshot(conn, area)
        rows = _source_rows(conn, info["snapshot_id"], production_order=production_order)
        members, _ = planning_order_population.read(conn, planning_hub._latest_snapshots(conn), orders=[production_order])
        planning_order_population.summarize(members, {production_order:detail['context']})
        by_source = {key:member for member in members if member['area']==area for key in member['source_keys']}
        catalogs = _catalogs(conn, area, info["snapshot_id"])
        lines = []
        for row in rows:
            line = line_data(row, area, catalogs['picking'])
            line['cpis_status'] = detail['context'].get('cpis_status')
            line['status_values'] = detail['context'].get('status_values', [])
            line['population'] = planning_population.classify({
                'status_values': detail['context'].get('status_values'),
                'closed_x': row['closed_x'], 'raw': row['row_data']})
            member = by_source.get(row['source_line_id'])
            if member:
                line['planning_key'] = member['key']
                line['population'] = member['population']
            if planning_population.includes(line, population):
                lines.append(line)
    return {"snapshot": serializable(info), "cpis_version": detail["version"],
            "order": detail["context"], "lines": lines, "population": population}


TEXT_LIMITS = {
    "component_ref": 160, "identity_discriminator": 160,
    "material_type": 100, "material_description": 1000,
    "profile": 200, "grade": 100, "team": 120, "pavilion": 80, "machine": 160,
    "material_lot": 160, "other_operations": 500, "notes": 4000,
    "abocardar": 40, "chanfro": 40, "ponteira": 40, "operation_detail": 240,
}
DATE_FIELDS = ("cut_date", "expected_date", "material_request_date", "material_available_date")
NUMBER_FIELDS = ("outer_diameter_mm", "width_mm", "height_mm", "thickness_mm", "length_mm", "angle_deg",
                 "quantity_required", "quantity_to_plan", "quantity_completed", "picking_week", "picking_year",
                 "weekly_capacity_hours", "finish_week", "finish_year")


def validate_values(raw, catalogs, *, record_status="ready"):
    if not isinstance(raw, dict):
        raise PlanningError("Os dados da ficha estão incompletos.")
    data = {}
    for key, maximum in TEXT_LIMITS.items():
        value = _text(raw.get(key))
        if len(value) > maximum:
            raise PlanningError(f"O campo {key} é demasiado longo.")
        data[key] = value
    for key in DATE_FIELDS:
        value = _text(raw.get(key))
        if value and not _date(value):
            raise PlanningError("Existe uma data inválida na ficha.")
        data[key] = _date(value)
    for key in NUMBER_FIELDS:
        raw_value = raw.get(key)
        value = None if raw_value in (None, "") else _number(raw_value)
        if raw_value not in (None, "") and value is None:
            raise PlanningError("Usa apenas números válidos nas quantidades, dimensões e capacidade.")
        if value is not None and ((value < 0 and key != "angle_deg") or abs(value) > 1_000_000_000):
            raise PlanningError("As quantidades e dimensões têm de ser positivas ou zero.")
        data[key] = value
    data["operation"] = raw.get("operation", "corte")
    if data["operation"] not in ("corte", "abocardar"):
        raise PlanningError("Seleciona a operação da ficha.")
    data["custom_profile"] = raw.get("custom_profile") is True
    ready = record_status == "ready"
    if ready and (not data["component_ref"] or not data["material_type"]):
        raise PlanningError("Preenche a referência e o tipo de material.")
    if ready and (not data["quantity_required"] or data["quantity_required"] <= 0):
        raise PlanningError("A quantidade necessária tem de ser superior a zero.")
    if (data["quantity_to_plan"] is not None and data["quantity_required"] is not None
            and data["quantity_to_plan"] > data["quantity_required"]):
        raise PlanningError("A quantidade a planear não pode ultrapassar a quantidade necessária.")
    for key in ("quantity_required", "quantity_to_plan", "quantity_completed"):
        if data[key] is not None and not data[key].is_integer():
            raise PlanningError("Indica quantidades em unidades inteiras.")
    if isinstance(catalogs, dict):
        machines = catalogs.get("machines", [])
        material_types = catalogs.get("material_types", [])
        teams = catalogs.get("teams", [])
        operations = catalogs.get("operations", [])
        profile_options = {item for values in catalogs.get("profiles", {}).values() for item in values}
    else:
        machines, material_types, teams, operations, profile_options = catalogs, [], [], [], set()
    if data["machine"] and data["machine"] not in machines:
        raise PlanningError("Seleciona uma máquina da lista do ficheiro.")
    if data["material_type"] and material_types and data["material_type"] not in material_types:
        raise PlanningError("Seleciona um tipo de material disponível para esta área.")
    if data["team"] and teams and data["team"] not in teams:
        raise PlanningError("Seleciona uma equipa disponível para esta área.")
    if data["operation_detail"] and operations and data["operation_detail"] not in operations:
        raise PlanningError("Seleciona uma operação disponível para esta área.")
    if (ready and not data["custom_profile"] and profile_options
            and data["profile"] not in profile_options):
        raise PlanningError("Seleciona um perfil normalizado ou ativa Perfil especial.")
    if data["machine"] and ((data["machine"] == "Abocardar") != (data["operation"] == "abocardar")):
        raise PlanningError("A operação e a máquina Abocardar têm de corresponder.")
    for key in ("picking_week", "finish_week"):
        if data[key] is not None and (not data[key].is_integer() or not 1 <= data[key] <= 53):
            raise PlanningError("A semana tem de ser um número de 1 a 53.")
    for key in ("picking_year", "finish_year"):
        if data[key] is not None and (not data[key].is_integer() or not 2000 <= data[key] <= 2100):
            raise PlanningError("Indica um ano entre 2000 e 2100.")
    if data["weekly_capacity_hours"] is not None and data["weekly_capacity_hours"] > 168:
        raise PlanningError("A capacidade de uma máquina não pode ultrapassar 168 horas por semana.")
    if data["angle_deg"] is not None and abs(data["angle_deg"]) > 360:
        raise PlanningError("O ângulo não pode ultrapassar 360 graus; confirma os campos do perfil.")
    if ready and data["custom_profile"]:
        if not data["length_mm"]:
            raise PlanningError("Indica o comprimento do perfil especial.")
        kind = data["material_type"].casefold()
        if "redondo" in kind:
            required = ["outer_diameter_mm"]
        elif "quadrado" in kind:
            required = ["width_mm"]
        elif "chapa" in kind:
            required = ["width_mm", "thickness_mm"]
        else:
            required = ["width_mm", "height_mm"]
        if "tubo" in kind or "cantoneira" in kind or "calha" in kind:
            required.append("thickness_mm")
        if any(not data[k] for k in required):
            raise PlanningError("Completa as dimensões necessárias para este tipo de perfil especial.")
    if ready and (data["length_mm"] is None or data["length_mm"] <= 0):
        raise PlanningError("Indica o comprimento de corte em milímetros.")
    return data


def same_identity(a, b):
    return all(a.get(key) == b.get(key) for key in ("of", "external_id")) and all(
        a["values"].get(key) == b["values"].get(key) for key in ("component_ref", "profile", "length_mm"))


def refresh_source(record_id):
    old = get_record(record_id)["record"]
    if old.get("source_kind") != "plan_line":
        from . import planning_hub
        detail = planning_hub.order_detail(old["production_order_no"])
        source = dict(old.get("source_payload") or {})
        context = detail["context"]
        source.update(ov=", ".join(context.get("ovs") or []),
                      customer=context.get("customer_name"),
                      designation=context.get("observations"),
                      cpis_status=context.get("cpis_status"),
                      cpis_planned_finish_date=_date(context.get("planned_finish_date")),
                      cpis_delivery_date=_date(context.get("delivery_date")))
        return {"snapshot": bootstrap(old["area"])["snapshot"],
                "cpis_version": detail["version"], "source": source}
    current = order_lines(old["area"], old["production_order_no"], population='all')
    matches = [row for row in current["lines"] if same_identity(old["source_payload"], row)]
    if len(matches) != 1:
        raise PlanningError("A linha mudou no ficheiro e não pode ser associada automaticamente. Seleciona a origem numa nova ficha.", 409)
    return {"snapshot": current["snapshot"], "source": matches[0]}


def _record(conn, record_id):
    row = conn.execute("SELECT * FROM planning_mtg.records WHERE id=%s", (record_id,)).fetchone()
    if not row:
        raise PlanningError("A ficha não foi encontrada.", 404)
    return row


def get_record(record_id):
    try:
        uid = uuid.UUID(str(record_id))
    except ValueError:
        raise PlanningError("A ficha não foi encontrada.", 404) from None
    with connect(readonly=True) as conn:
        row = _record(conn, uid)
        versions = conn.execute(
            "SELECT revision, actor, created_at FROM planning_mtg.record_versions "
            "WHERE record_id=%s ORDER BY revision DESC", (uid,),
        ).fetchall()
    row["id"] = str(row["id"])
    return serializable({"record": row, "versions": versions})


def list_records(area):
    check_area(area)
    with connect(readonly=True) as conn:
        rows = conn.execute(
            "SELECT id::text,production_order_no,component_ref,values_json,revision,actor,"
            "record_status,source_kind,updated_at "
            "FROM planning_mtg.records WHERE area=%s ORDER BY updated_at DESC LIMIT 100", (area,),
        ).fetchall()
    return serializable(rows)


def save_record(payload):
    if not isinstance(payload, dict):
        raise PlanningError("O pedido não contém uma ficha válida.")
    area = check_area(payload.get("area"))
    record_status = _text(payload.get("record_status") or "draft").lower()
    if record_status not in ("draft", "ready"):
        raise PlanningError("O estado da preparação é inválido.")
    from .planning_registration import human_actor, register
    actor = human_actor(payload)
    try:
        request_id = uuid.UUID(str(payload.get("request_id")))
        record_id = uuid.UUID(str(payload["record_id"])) if payload.get("record_id") else uuid.uuid4()
        expected_revision = int(payload.get("revision", 0))
    except (TypeError, ValueError):
        raise PlanningError("A sessão de edição é inválida. Volta a abrir a ficha.") from None
    with connect() as conn:
        # Idempotência de retries/clique duplo; serializar a mesma chave entre pedidos.
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (str(request_id),))
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        previous = conn.execute(
            "SELECT record_id::text, revision, request_hash FROM planning_mtg.record_versions WHERE request_id=%s",
            (request_id,),
        ).fetchone()
        if previous:
            if previous["request_hash"] != fingerprint:
                raise PlanningError("Este pedido já foi usado para guardar outros valores. Reabre a ficha.", 409)
            return {"id": previous["record_id"], "revision": previous["revision"], "replayed": True}
        from . import planning_hub
        info = snapshot(conn, area)
        plan_key = _text(payload.get("plan_key"))
        source_kind = "plan_line" if plan_key else _text(payload.get("source_kind") or "cpis_manual")
        if source_kind not in ("plan_line", "cpis_manual", "pdf"):
            raise PlanningError("A origem da preparação é inválida.")
        if plan_key and payload.get("snapshot_id") != info["snapshot_id"]:
            raise PlanningError("O ficheiro de planeamento mudou. Atualiza a origem antes de guardar.", 409)
        rows = _source_rows(conn, info["snapshot_id"], plan_key=plan_key) if plan_key else []
        if plan_key and len(rows) != 1:
            raise PlanningError("A linha de origem mudou. Volta a selecionar a referência.", 409)
        of = rows[0]["production_order_no"] if rows else order_number(payload.get("production_order_no"))
        if not of:
            raise PlanningError("Seleciona uma OF antes de guardar.")
        detail = planning_hub.order_detail(of, version=payload.get("cpis_version"))
        if detail["context"].get("cpis_status") not in OPEN_STATES:
            raise PlanningError("A OF já não está aberta no CPIS disponível.", 409)
        if record_status == "ready":
            planning_hub.require_operational_orders([of], expected_version=detail['version'], conn=conn)
        catalogs = _catalogs(conn, area, info["snapshot_id"])
        values = validate_values(payload.get("values"), catalogs, record_status=record_status)
        if record_status == "ready" and rows:
            evidence_line = next((line for line in detail['plan_lines'] if line['plan_key'] == plan_key), {})
            evidence_operation = next((item for item in evidence_line.get('operations', [])
                                       if item['operation'] == values['operation']), {})
            source_remaining = _number(evidence_operation.get('macro_remaining'))
            proposed = values.get("quantity_to_plan")
            if proposed is not None and (source_remaining is None or proposed != source_remaining):
                decisions = [item for item in detail.get("reconciliations", [])
                    if item.get("valid") and item.get("area") == area
                    and item.get("component_ref") == values["component_ref"]
                    and item.get('evidence_json', {}).get('plan_line', {}).get('plan_key') == plan_key
                    and item.get("operation") == values["operation"]
                    and _number(item.get("accepted_remaining")) == proposed]
                if not decisions:
                    raise PlanningError(
                        "A quantidade a planear difere do saldo confirmado na macro. Confere a divergência na página da OF.",
                        409)
        if rows:
            source = line_data(rows[0], area, catalogs["picking"])
            source_id = source["plan_key"]
            source_snapshot_id = info["snapshot_id"]
            source_excel_row = source["excel_row"]
            source_filename = info["source_filename"]
        else:
            context = detail["context"]
            source_id = _text(payload.get("source_id")) or str(uuid.uuid4())
            source_snapshot_id = None
            source_excel_row = None
            source_filename = None
            source = {"of": of, "ov": ", ".join(context.get("ovs") or []),
                      "customer": context.get("customer_name"),
                      "designation": context.get("observations"),
                      "cpis_status": context.get("cpis_status"),
                      "cpis_planned_finish_date": _date(context.get("planned_finish_date")),
                      "cpis_delivery_date": _date(context.get("delivery_date")),
                      "plan_key": None, "excel_row": None, "external_id": None,
                      "values": values}
        provenance = payload.get("provenance") if isinstance(payload.get("provenance"), dict) else {}
        source_version = detail["version"]
        if payload.get("record_id"):
            old = conn.execute("SELECT * FROM planning_mtg.records WHERE id=%s FOR UPDATE", (record_id,)).fetchone()
            if not old or old["area"] != area:
                raise PlanningError("A ficha não foi encontrada.", 404)
            if old["revision"] != expected_revision:
                raise PlanningError("Esta ficha foi alterada noutra sessão. Reabre-a para ver a revisão mais recente.", 409)
            if old["production_order_no"] != of:
                raise PlanningError("Não é possível trocar a OF de uma ficha existente.", 409)
            if old["source_kind"] == "plan_line" and not same_identity(old["source_payload"], source):
                raise PlanningError("Não é possível trocar a linha de origem de uma ficha existente.", 409)
            revision = expected_revision + 1
            conn.execute(
                "UPDATE planning_mtg.records SET values_json=%s,component_ref=%s,actor=%s,revision=%s,updated_at=now(), "
                "source_snapshot_id=%s,source_plan_key=%s,source_excel_row=%s,source_filename=%s,source_payload=%s,"
                "source_kind=%s,source_id=%s,source_version=%s,record_status=%s,provenance_json=%s WHERE id=%s",
                (Jsonb(values), values["component_ref"], actor, revision, source_snapshot_id, plan_key or None,
                 source_excel_row, source_filename, Jsonb(source), source_kind, source_id, source_version,
                 record_status, Jsonb(provenance), record_id),
            )
        else:
            revision = 1
            conn.execute(
                """INSERT INTO planning_mtg.records
                   (id,area,production_order_no,component_ref,source_snapshot_id,source_plan_key,
                    source_excel_row,source_filename,source_payload,values_json,actor,source_kind,
                    source_id,source_version,record_status,provenance_json)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (record_id, area, of, values["component_ref"], source_snapshot_id, plan_key or None,
                 source_excel_row, source_filename, Jsonb(source), Jsonb(values), actor, source_kind,
                 source_id, source_version, record_status, Jsonb(provenance)),
            )
        conn.execute(
            "INSERT INTO planning_mtg.record_versions(request_id,request_hash,record_id,revision,source_snapshot_id,"
            "source_payload,values_json,actor,source_kind,source_id,source_version,record_status,provenance_json) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (request_id, fingerprint, record_id, revision, source_snapshot_id, Jsonb(source), Jsonb(values),
             actor, source_kind, source_id, source_version, record_status, Jsonb(provenance)),
        )
        register(conn,of)
    return {"id": str(record_id), "revision": revision, "record_status": record_status,
            "replayed": False}
