"""Prazo de prioridade por setor (plano de 01/10/2026, secção 7).

Uma só regra para a Carteira, a vista de necessidades, o Gantt, o motor, o verificador e os gráficos:

- MTG3 Cantoneiras: a Data Corte da linha. Avalia a conclusão da operação principal até ao fim do dia
  local indicado. Sem Data Corte fica «prioridade sem data»; não se preenche com o Picking.
- MTG2 Perfis: o Picking utilizável, por continuidade com a regra anterior; sem Picking, Galvanização
  e depois Data Corte, como antes.
- Operações seguintes guardam o seu próprio marco (Galvanização; na MTG2 também o Picking da OF):
  não ficam todas obrigadas a terminar no prazo de corte.

Uma substituição por OF (ou OF × referência) prevalece e fica registada com motivo. A chave inclui o
setor: a mesma OF noutro setor não herda a decisão. As políticas são configuráveis por setor; sem
configuração gravada vale a política por defeito abaixo.
"""
from __future__ import annotations

from contextlib import nullcontext
from datetime import date, datetime, time, timedelta
import uuid
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb

from .. import planning, planning_dates, planning_needs as needs

LISBON = ZoneInfo("Europe/Lisbon")
WHOLE = "*"

FIELDS = {
    "cut_date": "Data Corte",
    "picking": "Picking",
    "galvanizing": "Galvanização",
    "planned_period": "Semana escolhida",
    "planned_finish_date": "Fim previsto da Produção",
    "delivery_date": "Data de entrega",
}
MILESTONES = {
    "conclusao_principal": "Conclusão da operação principal (corte/processamento)",
    "disponibilidade_picking": "Operações da OF disponíveis para o Picking",
    "marco_proprio": "Marco próprio da operação",
    "data_escolhida": "Data escolhida pelo utilizador",
}
# Picking pede a OF inteira pronta; os restantes marcos avaliam cada operação.
ORDER_SCOPED = {"picking"}
# Auditoria 06/10 (S53-1): «2026/53» escrito à mão na coluna W da Tabela MTG3 marca linhas estacionadas
# (sem máquina, Data Corte de março a agosto, fora do Plan_semanal). Não é a semana ISO 53: a linha fica
# sem prazo e numa janela própria, fora do atraso e da carga das semanas.
PARKED_WEEKS = {"2026/53"}
PARKED = "estacionada"


def parked_week(value) -> str | None:
    """O texto da coluna W quando é um marcador de linha estacionada; senão None."""
    text = str(value or "").strip()
    return text if text in PARKED_WEEKS else None

DEFAULTS = {
    "cantoneiras": {
        "version": "mtg3-data-corte-v1",
        "principal": ["cut_date"],
        "following": ["galvanizing"],
        "milestone": "conclusao_principal",
        "missing": "Prioridade sem data: Data Corte por indicar.",
    },
    "perfis": {
        "version": "mtg2-picking-v1",
        "principal": ["picking", "planned_period", "galvanizing", "cut_date"],
        "following": ["picking", "galvanizing"],
        "milestone": "disponibilidade_picking",
        "missing": "Prioridade sem data: Picking, Galvanização e Data Corte por indicar.",
    },
}


def default(area: str) -> dict:
    planning.check_area(area)
    return {**DEFAULTS[area], "principal": list(DEFAULTS[area]["principal"]),
            "following": list(DEFAULTS[area]["following"]), "origin": "Política por defeito"}


def validate_policy(area: str, definition) -> dict:
    """User policy: ordered fields per phase; unknown fields and empty lists are rejected."""
    planning.check_area(area)
    if not isinstance(definition, dict):
        raise planning.PlanningError("Política de prioridade inválida.")
    clean = {}
    for phase in ("principal", "following"):
        value = definition.get(phase)
        if not isinstance(value, list) or not 1 <= len(value) <= len(FIELDS) or any(v not in FIELDS for v in value) or len(set(value)) != len(value):
            raise planning.PlanningError("Escolhe, por ordem, os campos de prazo de cada fase.")
        clean[phase] = list(value)
    milestone = definition.get("milestone", DEFAULTS[area]["milestone"])
    if milestone not in MILESTONES:
        raise planning.PlanningError("Marco avaliado inválido.")
    clean["milestone"] = milestone
    assumed = definition.get("assume_picking_year")
    if assumed is not None and (type(assumed) is not int or not 2000 <= assumed <= 2200):
        raise planning.PlanningError("Ano de Picking assumido inválido.")
    clean["assume_picking_year"] = assumed
    return clean


def _day_end(day: date) -> str:
    # Uma data sem hora conserva a precisão do dia: o prazo é o início do dia seguinte em Lisboa.
    return datetime.combine(day + timedelta(days=1), time.min, LISBON).isoformat()


def _day(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def engine_values(row: dict, values: dict | None) -> dict:
    """Campos de prazo de uma operação do motor (Carga, Gantt), com a mesma origem da Carteira.

    Auditoria 06/10 (A9-1): o Picking vem dos valores atuais da linha (folha Picking importada,
    decisão manual, conflito), como na Carteira; a semana da camada de pesquisa, que pode estar
    parada numa importação antiga, só vale quando a linha não tem valores atuais de Picking.
    """
    values = values or {}
    current = "picking_week" in values
    return {**values,
            "cut_date": row.get("data_corte_prevista") or values.get("cut_date"),
            "picking_week": values.get("picking_week") if current else row.get("semana_picking"),
            "picking_year": values.get("picking_year") if current else row.get("ano_picking"),
            "picking_conflict": values.get("picking_conflict") if current else None,
            "nao_galvaniza_indicado": row.get("nao_galvaniza_indicado")}


def chosen_period_end(values: dict):
    """Fim exclusivo da «Semana escolhida» (ano + semana de planeamento) de uma linha, ou None.

    Auditoria 06/10 (A9-4): a mesma leitura da Tabela e do Gantt antigo (`planning_dates.period`):
    só conta uma decisão local válida; uma data prevista que não coincide com a semana anula-a.
    """
    if all(values.get(k) in (None, "") for k in ("planned_year", "planned_week")):
        return None
    year, week, origin = planning_dates.period(
        {k: values.get(k) for k in ("expected_date", "planned_year", "planned_week")}, area="perfis")
    return planning_dates.period_deadline(year, week) if origin == "Decisão local" else None


def milestones_from_values(values: dict, raw: dict | None = None, *, picking_year=None, picking_at=None,
                           planned_period_end=None, assumed_year=None) -> dict:
    """Normalise the dated fields of one application/Excel line, without inventing a shift.

    A Picking week without year takes the policy's assumed year when one is configured; otherwise the
    year is deduced (regra do Luís, 06/10/2026): the year in which that week is nearest the line's
    Data Corte, or today without it — in December, week 1 is next year. It stays provisional.
    Without an explicit `planned_period_end`, the line's own chosen week (planned_year/planned_week)
    feeds the «Semana escolhida» step.
    """
    raw = raw or {}
    if planned_period_end is None:
        planned_period_end = chosen_period_end(values)
    picking = None
    week = values.get("picking_week")
    year = picking_year or values.get("picking_year")
    if picking_at:
        picking = {"at": picking_at, "provisional": False, "origin": "Prazo de Picking corrigido"}
    elif not values.get("picking_conflict") and week not in (None, ""):
        if year not in (None, ""):
            found = planning_dates.picking_deadline(week, year)
            if found:
                picking = {"at": found["at"], "provisional": False, "origin": found["origin"]}
        elif assumed_year:
            found = planning_dates.picking_deadline(week, None, assumed_year=assumed_year)
            if found:
                picking = {"at": found["at"], "provisional": True, "origin": f"ano {assumed_year} assumido pela política do setor"}
        else:
            found = planning_dates.picking_deadline(week, None, anchor=values.get("cut_date"))
            if found:
                picking = {"at": found["at"], "provisional": True, "origin": f"ano {found['year']} deduzido pela semana"}
    galvanizing = None if values.get("nao_galvaniza_indicado") else raw.get("Data Galvanização")
    return {"cut_date": _day(values.get("cut_date")), "picking": picking, "galvanizing": _day(galvanizing),
            "parked": parked_week(raw.get("W")),
            "picking_week_without_year": planning_dates.positive_week(week) if week not in (None, "") and not picking and not year else None,
            "planned_period": planned_period_end, "planned_finish_date": _day(values.get("planned_finish_date")),
            "delivery_date": _day(values.get("delivery_date"))}


def _candidate(field: str, milestones: dict):
    value = milestones.get(field)
    if not value:
        return None
    if field == "picking":
        at = value["at"]
        local = datetime.fromisoformat(at).astimezone(LISBON)
        return {"priority_date": at, "priority_day": local.date().isoformat(), "precision": "week",
                "provisional": bool(value.get("provisional")), "origin_detail": value.get("origin")}
    if field == "planned_period":
        local = datetime.fromisoformat(value).astimezone(LISBON)
        return {"priority_date": value, "priority_day": (local.date() - timedelta(days=1)).isoformat(),
                "precision": "week", "provisional": False, "origin_detail": "Decisão local"}
    day = _day(value)
    if not day:
        return None
    return {"priority_date": _day_end(day), "priority_day": day.isoformat(), "precision": "day",
            "provisional": False, "origin_detail": None}


def resolve(area: str, phase: str, milestones: dict, *, policy: dict | None = None, override: dict | None = None,
            urgent: bool = False) -> dict:
    """priority_date is an exclusive instant; priority_day is the local day shown to people."""
    policy = policy or default(area)
    principal = phase == "principal"
    result = {"priority_date": None, "priority_day": None, "priority_milestone": None, "priority_source": None,
              "priority_field": None, "priority_scope": None, "policy_version": policy["version"],
              "override_id": None, "precision": None, "provisional": False, "missing_reason": None,
              "urgent": bool(urgent)}
    definition = (override or {}).get("definition") or override or {}
    if override and (principal or definition.get("applies_to") == "all"):
        result["override_id"] = str(override.get("id")) if override.get("id") else None
        if definition.get("due_date"):
            day = _day(definition["due_date"])
            if day:
                return {**result, "priority_date": _day_end(day), "priority_day": day.isoformat(),
                        "priority_milestone": "data_escolhida", "priority_source": "Substituição manual",
                        "priority_field": "override", "priority_scope": "operation", "precision": "day"}
        if definition.get("field") in FIELDS:
            found = _candidate(definition["field"], milestones)
            if found:
                field = definition["field"]
                return {**result, **{k: v for k, v in found.items() if k != "origin_detail"},
                        "priority_milestone": "data_escolhida",
                        "priority_source": FIELDS[field] + " · substituição manual",
                        "priority_field": field, "priority_scope": "order" if field in ORDER_SCOPED else "operation"}
            result["missing_reason"] = f"{FIELDS[definition['field']]} escolhida na substituição, mas sem data."
            return result
    if area == "cantoneiras" and milestones.get("parked"):
        return {**result, "parked": True,
                "missing_reason": f"Estacionada no Excel (W {milestones['parked']}): fora do atraso e da carga das semanas."}
    fields = policy["principal"] if principal else policy["following"]
    for field in fields:
        found = _candidate(field, milestones)
        if found:
            milestone = policy["milestone"] if principal and field == fields[0] else "disponibilidade_picking" if field == "picking" else "marco_proprio"
            source = FIELDS[field] + (f" · {found['origin_detail']}" if found.get("origin_detail") else "")
            return {**result, **{k: v for k, v in found.items() if k != "origin_detail"},
                    "priority_milestone": milestone, "priority_source": source, "priority_field": field,
                    "priority_scope": "order" if field in ORDER_SCOPED else "operation"}
    result["missing_reason"] = policy.get("missing") if principal else "Operação seguinte sem prazo próprio."
    if milestones.get("picking_week_without_year") and "picking" in fields:
        result["missing_reason"] += f" Picking W{milestones['picking_week_without_year']} sem ano confirmado."
    return result


def group(priority: dict) -> int:
    """Engine tiers: 0 urgent, 1 with a dated milestone, 2 without date."""
    if priority.get("urgent"):
        return 0
    return 1 if priority.get("priority_date") else 2


def window(priority: dict, today: date) -> str:
    """Carteira window, now from the sector's own priority date."""
    if priority.get("parked"):
        return PARKED
    day = _day(priority.get("priority_day"))
    if day is None:
        return "sem_data"
    if day < today:
        return "atrasado"
    end = today - timedelta(days=today.weekday()) + timedelta(weeks=2, days=6)
    return "3_semanas" if day <= end else "mais_tarde"


# ---------------------------------------------------------------- persistence


def _exists(c, table: str) -> bool:
    return bool(c.execute("SELECT to_regclass(%s) t", ("planning_mtg." + table,)).fetchone()["t"])


def policies(c) -> dict:
    result = {area: default(area) for area in planning.AREAS}
    if not _exists(c, "sector_priority_policies"):
        return result
    for row in c.execute("SELECT * FROM planning_mtg.sector_priority_policies").fetchall():
        d = row["definition"]
        result[row["area"]] = {**result[row["area"]], **d, "origin": "Política configurada",
                               "version": f"{row['area']}-r{row['revision']}-{needs.digest(d)[:12]}",
                               "revision": row["revision"], "actor": row["actor"], "reason": row["reason"],
                               "updated_at": row["updated_at"]}
    return result


def overrides(c) -> dict:
    if not _exists(c, "sector_priority_overrides"):
        return {}
    rows = c.execute("SELECT * FROM planning_mtg.sector_priority_overrides ORDER BY area,production_order_no,reference").fetchall()
    return {(r["area"], r["production_order_no"], r["reference"]): needs.serial(r) for r in rows}


def override_for(table: dict, area: str, of: str, reference: str):
    return table.get((area, of, reference)) or table.get((area, of, WHOLE))


def digest(c) -> str:
    return needs.digest({"policies": {k: {f: v.get(f) for f in ("version", "principal", "following", "milestone")}
                                      for k, v in policies(c).items()},
                         "overrides": [{k: v for k, v in o.items() if k != "updated_at"} for o in overrides(c).values()]})


def _event(c, kind, area, subject, action, before, after, reason, actor, request_id):
    c.execute("""INSERT INTO planning_mtg.sector_config_events
        (kind,area,subject,action,before,after,reason,actor,request_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (request_id,kind,subject) DO NOTHING""",
              (kind, area, subject, action, Jsonb(needs.serial(before)) if before else None,
               Jsonb(needs.serial(after)) if after else None, reason, actor, request_id))


def _repeated(c, request_id, kind) -> bool:
    return bool(c.execute("SELECT 1 FROM planning_mtg.sector_config_events WHERE request_id=%s AND kind=%s LIMIT 1",
                          (request_id, kind)).fetchone())


def _request(payload) -> uuid.UUID:
    try:
        return uuid.UUID(str(payload.get("request_id")))
    except ValueError:
        raise planning.PlanningError("Pedido sem identificador; recarrega a página.") from None


def save_policy(payload: dict, conn=None) -> dict:
    """New revision of a sector policy; the old one stays in the audit events."""
    from .. import planning_registration as registration
    area = planning.check_area(str(payload.get("setor") or payload.get("area") or ""))
    request_id = _request(payload)
    reason = str(payload.get("motivo") or payload.get("reason") or "").strip()
    if not reason or len(reason) > 1000:
        raise planning.PlanningError("Indica o motivo da mudança de política.")
    actor = registration.human_actor(payload)
    if payload.get("repor"):
        definition = None
    else:
        definition = validate_policy(area, payload.get("definition"))
    with (planning.connect() if conn is None else nullcontext(conn)) as c:
        c.execute("SELECT pg_advisory_xact_lock(hashtext('sector-priority-policy'))")
        if _repeated(c, request_id, "priority_policy"):
            return {"repeated": True, "policies": needs.serial(policies(c))}
        prior = c.execute("SELECT * FROM planning_mtg.sector_priority_policies WHERE area=%s FOR UPDATE", (area,)).fetchone()
        expected = payload.get("expected_revision", 0)
        if (prior["revision"] if prior else 0) != expected:
            raise planning.PlanningError("A política mudou entretanto. Reabre-a antes de gravar.", 409)
        if definition is None:
            c.execute("DELETE FROM planning_mtg.sector_priority_policies WHERE area=%s", (area,))
        else:
            c.execute("""INSERT INTO planning_mtg.sector_priority_policies(area,definition,reason,actor)
                VALUES (%s,%s,%s,%s) ON CONFLICT (area) DO UPDATE SET definition=excluded.definition,
                reason=excluded.reason, actor=excluded.actor, updated_at=now(),
                revision=sector_priority_policies.revision+1""", (area, Jsonb(definition), reason, actor))
        _event(c, "priority_policy", area, area, "reset" if definition is None else "saved",
               prior and prior["definition"], definition, reason, actor, request_id)
        return {"repeated": False, "policies": needs.serial(policies(c))}


def save_override(payload: dict, conn=None) -> dict:
    """Set or clear the priority date of one OF (reference '*') or OF × reference in one sector."""
    from .. import planning_registration as registration
    area = planning.check_area(str(payload.get("setor") or payload.get("area") or ""))
    of = str(payload.get("of") or "").strip()
    reference = str(payload.get("referencia") or payload.get("reference") or WHOLE).strip() or WHOLE
    if not of:
        raise planning.PlanningError("Indica a OF.")
    request_id = _request(payload)
    reason = str(payload.get("motivo") or payload.get("reason") or "").strip()
    actor = registration.human_actor(payload)
    clear = bool(payload.get("limpar"))
    definition = None
    if not clear:
        if not reason or len(reason) > 1000:
            raise planning.PlanningError("Indica o motivo da substituição do prazo.")
        due, field = payload.get("due_date"), payload.get("field")
        if bool(due) == bool(field):
            raise planning.PlanningError("Escolhe uma data ou um campo de prazo, não ambos.")
        if due and _day(due) is None:
            raise planning.PlanningError("Data de prazo inválida.")
        if field and field not in FIELDS:
            raise planning.PlanningError("Campo de prazo inválido.")
        applies = payload.get("applies_to") or "principal"
        if applies not in ("principal", "all"):
            raise planning.PlanningError("Indica se a substituição vale para a operação principal ou para todas.")
        definition = {"due_date": _day(due).isoformat() if due else None, "field": field, "applies_to": applies}
    with (planning.connect() if conn is None else nullcontext(conn)) as c:
        c.execute("SELECT pg_advisory_xact_lock(hashtext('sector-priority-override'))")
        subject = f"{of}|{reference}"
        if _repeated(c, request_id, "priority_override"):
            return {"repeated": True}
        prior = c.execute("""SELECT * FROM planning_mtg.sector_priority_overrides
            WHERE area=%s AND production_order_no=%s AND reference=%s FOR UPDATE""", (area, of, reference)).fetchone()
        if (prior["revision"] if prior else 0) != payload.get("expected_revision", 0):
            raise planning.PlanningError("O prazo desta OF mudou entretanto. Reabre-o antes de gravar.", 409)
        if clear:
            if prior:
                c.execute("DELETE FROM planning_mtg.sector_priority_overrides WHERE area=%s AND production_order_no=%s AND reference=%s",
                          (area, of, reference))
        else:
            c.execute("""INSERT INTO planning_mtg.sector_priority_overrides
                (area,production_order_no,reference,id,definition,reason,actor) VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (area,production_order_no,reference) DO UPDATE SET definition=excluded.definition,
                reason=excluded.reason, actor=excluded.actor, updated_at=now(),
                revision=sector_priority_overrides.revision+1""",
                      (area, of, reference, uuid.uuid5(uuid.NAMESPACE_URL, f"priority-override:{area}:{subject}"),
                       Jsonb(definition), reason, actor))
        _event(c, "priority_override", area, subject, "cleared" if clear else "saved",
               prior and {"definition": prior["definition"], "reason": prior["reason"]},
               definition and {"definition": definition, "reason": reason}, reason or None, actor, request_id)
        return {"repeated": False, "override": needs.serial(overrides(c).get((area, of, reference)))}
