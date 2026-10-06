"""Definições de cada setor: máquinas, turnos, tempos e capacidades (pedido do Luís, 06/10/2026).

Lê e grava sem criar uma segunda fonte de verdade:
- máquinas = recursos físicos (raw_objects kind='resource'): confirmada, turnos padrão (`default_shifts`)
  e correção local do intervalo da ficha de capacidades (`capacity_override`, aplicada nas candidatas);
- turnos = calendários semanais (shifts.py) gerados a partir do modelo do setor (horas dos turnos,
  dias de trabalho, feriados) guardado em sector_settings;
- tempos = taxas confirmadas (kind='rate'), que têm prioridade sobre as velocidades do Excel.
"""
from __future__ import annotations

import re
import uuid
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone

from psycopg.types.json import Jsonb

from .. import planning, planning_needs as needs, planning_registration as registration
from . import shifts

UNIT = {"cantoneiras": "MTG3", "perfis": "MTG2"}
HORIZON_WEEKS = 52
METHODS = {"metres_hour": "m/h", "area_hour": "mm²/h", "units_hour": "peças/h", "minutes_unit": "min/peça"}
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def default(today: date | None = None) -> dict:
    year = (today or date.today()).year
    return {"template": [list(x) for x in shifts.DEFAULT_TEMPLATE], "workdays": list(shifts.DEFAULT_WORKDAYS),
            "holidays": shifts.national_holidays(year) + shifts.national_holidays(year + 1), "revision": 0}


def read(c, sector: str) -> dict:
    planning.check_area(sector)
    if c.execute("SELECT to_regclass('planning_mtg.sector_settings') t").fetchone()["t"]:
        row = c.execute("SELECT definition, revision FROM planning_mtg.sector_settings WHERE area = %s", (sector,)).fetchone()
        if row:
            stored = {**default(), **row["definition"], "revision": row["revision"]}
            year = date.today().year
            covered = {h[:4] for h in stored["holidays"]}
            for y in (year, year + 1):  # anos ainda sem feriados gravados: os nacionais entram sozinhos
                if str(y) not in covered:
                    stored["holidays"] = sorted(set(stored["holidays"]) | set(shifts.national_holidays(y)))
            return stored
    return default()


def _current_week(today: date | None = None) -> tuple[int, int]:
    y, w, _ = (today or date.today()).isocalendar()
    return y, w


def _weeks(today: date | None = None, count: int = HORIZON_WEEKS):
    monday = (today or date.today()) - timedelta(days=(today or date.today()).weekday())
    for i in range(count):
        y, w, _ = (monday + timedelta(weeks=i)).isocalendar()
        yield y, w


def machine_rows(c, sector: str) -> list[dict]:
    """Máquinas do setor pelo catálogo de recursos (members.rule); a área dos calendários não conta."""
    from .members import rule
    from .occurrences import resources_context
    from .portfolio_kpis import catalog
    codes, by_id, _, configs, package = resources_context(c)
    info = catalog(c, sector) if by_id else {}
    own = rule(by_id, info, sector)
    objects = {str(cfg["id"]): cfg for cfg in configs if cfg["kind"] == "resource"}
    capacities = (package or {}).get("metadata", {}).get("capacities", []) if package else []
    y, w = _current_week()
    out = []
    for rid, r in by_id.items():
        meta = info.get(r.get("code")) or {}
        if rid not in own:
            continue
        obj = objects.get(rid)
        d = (obj or {}).get("definition") or {}
        default_shifts = d.get("default_shifts")
        if default_shifts is None:
            row = shifts.calendar_row(c, rid, y, w)
            plan, _ = shifts.decode(row["definition"]) if row else ({}, {})
            default_shifts = max([plan.get(str(day), 0) for day in range(1, 6)] or [0])
        out.append({"id": rid, "code": r.get("code"), "name": r.get("name") or rid, "type": meta.get("type") or r.get("type"), "area": sector,
                    "process": meta.get("process"), "confirmed": bool(d.get("confirmed")), "revision": (obj or {}).get("revision"),
                    "default_shifts": int(default_shifts), "has_object": bool(obj), "override": d.get("capacity_override") or {},
                    "aliases": d.get("aliases") or [], "operations": d.get("operations") or [], "history_window_days": d.get("history_window_days"),
                    "ficha": [{"operation": cap["operacao_codigo"], "process": cap.get("processo_fisico"), "min": cap.get("perfil_minimo"),
                               "max": cap.get("perfil_maximo"), "source": cap.get("fonte")}
                              for cap in capacities if cap["recurso_codigo"] == r.get("code")]})
    return sorted(out, key=lambda m: (m["process"] or "~", m["name"]))


def overview(sector: str) -> dict:
    from . import priority, throughput
    from .estimates import area_rates
    from ..gantt import research
    planning.check_area(sector)
    with planning.connect(readonly=True) as c:
        settings = read(c, sector)
        machines = machine_rows(c, sector)
        rates = c.execute("SELECT id, name, revision, definition FROM planning_mtg.raw_objects WHERE kind='rate' AND NOT archived ORDER BY name").fetchall()
        study = throughput.load(c) if research.enabled() and sector == "cantoneiras" else None
        excel_area = area_rates(research.load(c)["metadata"]) if research.enabled() and sector == "perfis" else {}
        policy = priority.policies(c)[sector]
        y, w = _current_week()
        weeks = []
        for m in machines:
            plan = []
            for year, week in list(_weeks(count=6)):
                row = shifts.calendar_row(c, m["id"], year, week)
                if row:
                    base, days = shifts.decode(row["definition"], settings["template"])
                    plan.append({"year": year, "week": week, "shifts": max(base.get(str(d), 0) for d in settings["workdays"]) if settings["workdays"] else 0,
                                 "hours": round(shifts.week_hours(row["definition"]), 1), "manual": bool(row["definition"].get("manual")),
                                 "day_changes": len(days)})
                else:
                    plan.append({"year": year, "week": week, "shifts": None, "hours": 0, "manual": False, "day_changes": 0})
            weeks.append({"machine": m["id"], "weeks": plan})
            m["rates"] = [{"id": str(r["id"]), "name": r["name"], "revision": r["revision"], **r["definition"]}
                          for r in rates if str(r["definition"].get("resource_id")) == m["id"]]
            excel = None
            if study:
                found = study["speeds"].get(m["name"])
                if found and found.get("value"):
                    excel = {"value": round(found["value"], 1), "unit": "m/h", "lines": found.get("lines"),
                             "source": "Mediana da coluna Mt\\h do Excel (todas as peças desta máquina)"}
                profiles = sorted(((p, v) for (name, p), v in study["profile_speeds"].items() if name == m["name"] and v["lines"] >= 3),
                                  key=lambda kv: -kv[1]["lines"])[:12]
                m["profile_speeds"] = [{"profile": p, "value": round(v["value"], 1), "lines": v["lines"]} for p, v in profiles]
                summary = study["summary"].get(m["name"]) or {}
                m["observed_week_hours"] = summary.get("hours_median")
            elif excel_area.get(m["code"]):
                excel = {"value": excel_area[m["code"]], "unit": "mm²/h", "source": "Folha CapacidadeMáquinas do Excel"}
            m["excel_rate"] = excel
            m["rate_in_use"] = ("Taxa confirmada" if any(r.get("confirmed") for r in m["rates"]) else
                                "Velocidade do Excel" if excel else "Por definir")
    rules = [
        "Prazo: " + ("Data Corte." if sector == "cantoneiras" else "Picking (semana do Excel; ano deduzido), depois Data Corte."),
        "Máquina de cada linha: escolha da Carteira → coluna Máquina da Tabela → conjunto de famílias.",
        "Estados: Planeado (Planear + máquina) · Planeado para nesting (tem máquina) · Sem máquina atribuída. Sem máquina não se planeia.",
        "Horas: taxa confirmada da máquina; senão a velocidade do Excel para a máquina e o perfil.",
        "Capacidade de cada semana: os turnos da máquina nessa semana (calendário), sem os feriados.",
        "Fora da ficha de capacidades: a máquina escolhida mantém-se e entra no plano.",
    ]
    return needs.serial({"sector": sector, "settings": settings, "machines": machines, "weeks": weeks, "rules": rules,
                         "policy": policy, "methods": METHODS, "shift_hours": shifts.shift_hours(settings["template"])})


def regenerate(c, sector: str, settings: dict, request_id: uuid.UUID, *, machines: list[dict] | None = None,
               reset_base_for: set | None = None) -> int:
    """Reescreve os calendários das próximas 52 semanas com o modelo atual (horas, dias, feriados).

    Semanas mudadas à mão mantêm os seus turnos; `reset_base_for` = máquinas cujos turnos padrão mudaram
    (as semanas não manuais passam a esse número). Semanas em falta são criadas.
    """
    machines = machines if machines is not None else machine_rows(c, sector)
    changed = 0
    for m in machines:
        if not m.get("confirmed"):
            continue  # sem identidade física confirmada não há calendário (raw/capacity.py)
        default_plan = {str(d): (m["default_shifts"] if d in settings["workdays"] else 0) for d in range(1, 8)}
        for year, week in _weeks():
            row = shifts.calendar_row(c, m["id"], year, week)
            if row and shifts.is_legacy(row["definition"]):
                continue  # calendário antigo só com turnos: não se reescreve sem horários conhecidos
            manual = bool(row and row["definition"].get("manual"))
            if row:
                base, days = shifts.decode(row["definition"], settings["template"])
                if not manual and reset_base_for and m["id"] in reset_base_for:
                    base = default_plan
            else:
                base, days = default_plan, {}
            changed += shifts.write(c, m, sector, year, week, base, days, settings, manual=manual, request_id=request_id, actor_payload={})
    return changed


def missing_weeks(c, sector: str, *, machines: list[dict] | None = None, today: date | None = None) -> list[tuple[str, int, int]]:
    """Semanas do horizonte (52 semanas) sem calendário nas máquinas confirmadas: [(máquina, ano, semana)]. Só leitura."""
    machines = machines if machines is not None else machine_rows(c, sector)
    return [(m["id"], y, w) for m in machines if m.get("confirmed")
            for y, w in _weeks(today) if not shifts.calendar_row(c, m["id"], y, w)]


def extend_horizon(sector: str, *, conn=None, today: date | None = None) -> dict:
    """Prolonga os calendários: cria só as semanas em falta das próximas 52, com os turnos padrão (auditoria 06/10, C1-5).

    Sem isto o horizonte encurta uma semana por semana até alguém gravar as Definições (regenerate só corre aí).
    Regras: só máquinas confirmadas; semanas existentes (manuais, antigas ou não) não se tocam; feriados do modelo
    do setor; um só lote com um só sinal. Pensado para correr uma vez por semana (tarefa agendada); repetir não grava.
    """
    with (planning.connect() if conn is None else nullcontext(conn)) as c:
        planning.check_area(sector)
        c.execute("SELECT pg_advisory_xact_lock(hashtext('sector_settings:' || %s))", (sector,))  # o mesmo lock de save()
        settings = read(c, sector)
        machines = {m["id"]: m for m in machine_rows(c, sector)}
        missing = missing_weeks(c, sector, machines=list(machines.values()), today=today)
        request_id = uuid.uuid4()
        created = 0
        for rid, year, week in missing:
            m = machines[rid]
            base = {str(d): (m["default_shifts"] if d in settings["workdays"] else 0) for d in range(1, 8)}
            created += shifts.write(c, m, sector, year, week, base, {}, settings, manual=False, request_id=request_id,
                                    actor_payload={})
        if created:
            shifts.finish_batch(c, request_id)
    return {"sector": sector, "created": created, "machines": len({rid for rid, _, _ in missing})}


def _validate_settings(p: dict) -> dict:
    template = p.get("turnos")
    if not isinstance(template, list) or not 1 <= len(template) <= 3:
        raise planning.PlanningError("Indica de 1 a 3 turnos.")
    clean = []
    for pair in template:
        if not isinstance(pair, list) or len(pair) != 2 or not all(isinstance(t, str) and _TIME.match(t) for t in pair) or pair[0] == pair[1]:
            raise planning.PlanningError("Horas dos turnos inválidas (HH:MM).")
        clean.append([pair[0], pair[1]])
    workdays = p.get("dias")
    if not isinstance(workdays, list) or not workdays or not all(isinstance(d, int) and 1 <= d <= 7 for d in workdays):
        raise planning.PlanningError("Escolhe os dias de trabalho.")
    holidays = p.get("feriados") or []
    try:
        holidays = sorted({date.fromisoformat(str(h)).isoformat() for h in holidays})
    except ValueError:
        raise planning.PlanningError("Feriado com data inválida.") from None
    return {"template": clean, "workdays": sorted(set(workdays)), "holidays": holidays}


def save(payload: dict, *, conn=None) -> dict:
    sector = str(payload.get("setor") or "")
    kind = payload.get("tipo")
    try:
        request_id = uuid.UUID(str(payload.get("request_id")))
    except ValueError:
        raise planning.PlanningError("Pedido sem identificador; recarrega a página.") from None
    actor = registration.human_actor(payload)
    from ..raw import objects
    with (planning.connect() if conn is None else nullcontext(conn)) as c:
        planning.check_area(sector)
        c.execute("SELECT pg_advisory_xact_lock(hashtext('sector_settings:' || %s))", (sector,))
        current = read(c, sector)
        if kind == "setor":
            new = _validate_settings(payload)
            if payload.get("expected_revision") != current["revision"]:
                raise planning.PlanningError("As definições mudaram entretanto. Recarrega a página.", 409)
            c.execute("""INSERT INTO planning_mtg.sector_settings (area, definition, actor) VALUES (%s, %s, %s)
                         ON CONFLICT (area) DO UPDATE SET definition = EXCLUDED.definition, revision = sector_settings.revision + 1,
                         actor = EXCLUDED.actor, updated_at = now()""", (sector, Jsonb(new), actor))
            settings = {**new, "revision": current["revision"] + 1}
            changed = regenerate(c, sector, settings, request_id)
        elif kind == "maquina":
            machines = {m["id"]: m for m in machine_rows(c, sector)}
            m = machines.get(str(payload.get("id")))
            if not m or not m["has_object"]:
                raise planning.PlanningError("Máquina desconhecida neste setor.")
            obj = c.execute("SELECT * FROM planning_mtg.raw_objects WHERE id = %s", (m["id"],)).fetchone()
            if payload.get("expected_revision") != obj["revision"]:
                raise planning.PlanningError("A máquina foi alterada entretanto. Recarrega a página.", 409)
            d = dict(obj["definition"])
            if "turnos_padrao" in payload:
                n = int(payload["turnos_padrao"])
                if not 0 <= n <= shifts.MAX_SHIFTS:
                    raise planning.PlanningError(f"Os turnos padrão vão de 0 a {shifts.MAX_SHIFTS}.")
                d["default_shifts"] = n
            if "confirmada" in payload:
                d["confirmed"] = bool(payload["confirmada"])
            if "ficha" in payload:
                override = {}
                for op, limits in (payload.get("ficha") or {}).items():
                    if not isinstance(limits, dict):
                        raise planning.PlanningError("Intervalo da ficha inválido.")
                    lo, hi = str(limits.get("min") or "").strip().upper(), str(limits.get("max") or "").strip().upper()
                    if lo or hi:
                        from ..gantt.machines import dimensions
                        if (lo and not dimensions(lo)) or (hi and not dimensions(hi)):
                            raise planning.PlanningError("Perfil inválido na ficha (ex.: L200X200X24).")
                        override[op] = {"min": lo or None, "max": hi or None}
                d["capacity_override"] = override
            if "nomes" in payload:  # nomes da máquina no Excel e nas folhas OCR, por setor (antes em «Capacidades e horas»)
                aliases = []
                for item in payload.get("nomes") or []:
                    area, name = str((item or {}).get("area") or ""), str((item or {}).get("name") or "").strip()
                    if area not in planning.AREAS or not name:
                        raise planning.PlanningError("Cada nome precisa do setor (MTG2 ou MTG3) e do nome.")
                    if {"area": area, "name": name} not in aliases:
                        aliases.append({"area": area, "name": name})
                d["aliases"] = aliases
            if "operacoes" in payload:
                d["operations"] = [str(x).strip() for x in payload.get("operacoes") or [] if str(x).strip()]
            if "janela_historico" in payload:
                d["history_window_days"] = payload["janela_historico"]
            objects.save({"request_id": str(uuid.uuid5(request_id, "resource")), "id": m["id"], "expected_revision": obj["revision"],
                          "name": obj["name"], "area": obj["area"], "definition": d}, "resource", conn=c, signal=False)
            changed = 1
            if "turnos_padrao" in payload and int(payload["turnos_padrao"]) != m["default_shifts"]:
                changed += regenerate(c, sector, current, request_id, machines=[{**m, "default_shifts": d["default_shifts"]}],
                                      reset_base_for={m["id"]})
        elif kind == "taxa":
            machines = {m["id"]: m for m in machine_rows(c, sector)}
            if str(payload.get("maquina")) not in machines:
                raise planning.PlanningError("Máquina desconhecida neste setor.")
            if payload.get("metodo") not in METHODS:
                raise planning.PlanningError("Unidade da taxa inválida.")
            definition = {"resource_id": str(payload["maquina"]), "area": sector, "operation": str(payload.get("operacao") or "").strip(),
                          "method": payload["metodo"], "value": payload.get("valor"), "setup_minutes": 0,
                          "profile": str(payload.get("perfil") or "").strip(), "material_type": "",
                          "valid_from": str(payload.get("desde") or date.today().isoformat()), "confirmed": True}
            existing = payload.get("id")
            row = c.execute("SELECT revision, archived FROM planning_mtg.raw_objects WHERE id = %s", (existing,)).fetchone() if existing else None
            objects.save({"request_id": str(uuid.uuid5(request_id, "rate")), "id": existing, "expected_revision": row["revision"] if row else 0,
                          "name": f"{machines[str(payload['maquina'])]['name']} · {definition['operation'] or 'operação'}"
                                  + (f" · {definition['profile']}" if definition["profile"] else ""),
                          "area": sector, "definition": definition, "archived": bool(payload.get("arquivar"))}, "rate", conn=c, signal=False)
            changed = 1
        else:
            raise planning.PlanningError("Tipo de definição desconhecido.")
        if changed:
            shifts.finish_batch(c, request_id)
    return {"changed": changed, "tipo": kind}


if __name__ == "__main__":  # tarefa semanal: python -m app.sector.settings prolongar (C1-5)
    import json
    import sys
    if sys.argv[1:] != ["prolongar"]:
        raise SystemExit("Uso: python -m app.sector.settings prolongar")
    print(json.dumps([extend_horizon(sector) for sector in planning.AREAS], ensure_ascii=False))
