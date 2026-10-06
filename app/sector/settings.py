"""Definições de cada setor: máquinas, turnos, tempos e capacidades (pedido do Luís, 06/10/2026).

Lê e grava sem criar uma segunda fonte de verdade:
- máquinas = recursos físicos (raw_objects kind='resource'): turnos padrão (`default_shifts`)
  e correção local do intervalo da ficha de capacidades (`capacity_override`, aplicada nas candidatas);
- turnos = calendários semanais (shifts.py) gerados a partir do modelo do setor (horas dos turnos,
  dias de trabalho, feriados) guardado em sector_settings;
- tempos = tabela de velocidades (kind='rate', plano de 06/10, parte 3): uma linha por máquina, operação e
  intervalo (espessura nas cantoneiras, tipo de material e área de secção nos perfis), com arranque por peça;
  margem (%) e tempo fixo por peça (min) do setor em sector_settings (0 = as horas não mudam).
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
METHODS = {"metres_hour": "m/h", "area_hour": "mm²/h", "units_hour": "peças/h", "minutes_unit": "min/peça", "fixed_minutes": "min"}
TIMING = {"margin_pct": ("Margem sobre os tempos estimados (%)", 0, 300), "piece_minutes": ("Tempo fixo por peça (min)", 0, 120)}
STORED = ("template", "workdays", "holidays", *TIMING)  # chaves guardadas em sector_settings.definition
OPERATION_NAMES = {"112": "Punção", "119": "Broca", "corte": "Corte", "abocardar": "Abocardar"}
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def default(today: date | None = None) -> dict:
    year = (today or date.today()).year
    return {"template": [list(x) for x in shifts.DEFAULT_TEMPLATE], "workdays": list(shifts.DEFAULT_WORKDAYS),
            "holidays": shifts.national_holidays(year) + shifts.national_holidays(year + 1), "revision": 0,
            "margin_pct": 0, "piece_minutes": 0}


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


def _operation_code(op) -> str:
    from ..raw.capacity import operation_code
    return operation_code(op)


def rate_operation_codes(sector: str, m: dict) -> list[str]:
    """Operações da máquina que podem ter linhas na tabela. Nas cantoneiras só códigos ('112', '119'): o motor
    procura o código da operação, por isso uma linha 'corte' nunca valeria lá (só nos perfis)."""
    codes = [_operation_code(op) for op in m.get("operations") or []] + [_operation_code(f["operation"]) for f in m.get("ficha") or []]
    return list(dict.fromkeys(c for c in codes if c and (sector != "cantoneiras" or c.isdigit())))


def operation_tabs(machines: list[dict], rates: list[dict]) -> list[dict]:
    """Separadores por operação da tabela de velocidades (ex.: Punção · 112, Broca · 119), com o processo da ficha."""
    from collections import Counter, defaultdict
    processes = defaultdict(Counter)
    for m in machines:
        for cap in m.get("ficha") or []:
            if cap.get("process"):
                processes[_operation_code(cap["operation"])][cap["process"]] += 1
    codes = {code for m in machines for code in m.get("rate_operations_codes") or []}
    codes |= {_operation_code(r.get("operation")) for r in rates if r.get("operation")}
    tabs = []
    for code in sorted(codes, key=lambda c: (not c.isdigit(), int(c) if c.isdigit() else 0, c)):
        name = processes[code].most_common(1)[0][0] if processes[code] else OPERATION_NAMES.get(code)
        tabs.append({"code": code, "label": f"{name} · {code}" if name and code.isdigit() else (name or code),
                     "machines": [m["id"] for m in machines if code in (m.get("rate_operations_codes") or [])]})
    return tabs


def excel_seed(sector: str, machines: list[dict], study: dict | None, excel_area: dict) -> list[dict]:
    """«Preencher com as velocidades atuais do Excel»: uma linha por máquina do setor e operação.

    Cantoneiras: a velocidade mais recente do Excel da máquina (moda das linhas com Data Corte nas últimas
    semanas com dados, `productivity.recent_excel_speeds`), igual em todas as operações da máquina — a mesma que
    a Carteira, a Carga, o motor e o Gantt usam sem tabela, por isso preencher não muda as horas. Perfis: a taxa
    mm²/h da folha CapacidadeMáquinas (coluna C), sem o fator ×3 da Thomas.
    """
    from .throughput import aliases_to_names
    seed = []
    for m in machines:
        if not m.get("has_object"):
            continue  # a taxa pendura-se no recurso gravado (raw/capacity.validate); sem ele não há onde
        if sector == "cantoneiras":
            if not study:
                continue
            names = sorted(n for n in aliases_to_names({m["id"]: {"name": m["name"], "aliases": m.get("aliases")}})[m["id"]] if n)
            recent = next((study.get("recent_speeds", {}).get(n) for n in names if study.get("recent_speeds", {}).get(n)), None)
            if not recent:
                continue
            for code in [c for c in m.get("rate_operations_codes") or [] if c.isdigit()]:
                found = recent
                seed.append({"maquina": m["id"], "nome": m["name"], "operacao": code, "metodo": "metres_hour", "valor": found["value"],
                             "unidade": "m/h", "linhas": found["lines"],
                             "notas": f"Excel: velocidade mais recente ({found['lines']} linhas desde {recent.get('from')})"})
        elif excel_area.get(m.get("code")) and "corte" in (m.get("rate_operations_codes") or []):
            seed.append({"maquina": m["id"], "nome": m["name"], "operacao": "corte", "metodo": "area_hour", "valor": excel_area[m["code"]],
                         "unidade": "mm²/h", "linhas": None, "notas": "Excel: folha CapacidadeMáquinas, coluna C (sem fator ×3)"})
    return seed


def _rate_view(r: dict, today: str) -> dict:
    from ..raw.productivity import rate_tier
    d = r["definition"]
    return {"id": str(r["id"]), "name": r["name"], "revision": r["revision"], **d,
            "operation_code": _operation_code(d.get("operation")), "source": rate_tier(d),
            "in_force": bool(d.get("confirmed")) and str(d.get("valid_from") or "") <= today
                        and (not d.get("valid_until") or today <= str(d["valid_until"]))}


def overview(sector: str) -> dict:
    from . import priority, throughput
    from .estimates import area_rates
    from ..gantt import research
    planning.check_area(sector)
    today = date.today().isoformat()
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
            m["rates"] = [_rate_view(r, today) for r in rates if str(r["definition"].get("resource_id")) == m["id"]
                          and r["definition"].get("area") in (None, sector)]
            m["rate_operations_codes"] = rate_operation_codes(sector, m)
            excel = None
            if study:
                names = [n for n in throughput.aliases_to_names({m["id"]: {"name": m["name"], "aliases": m.get("aliases")}})[m["id"]] if n]
                found = next((study.get("recent_speeds", {}).get(n) for n in sorted(names) if study.get("recent_speeds", {}).get(n)), None)
                if found and found.get("value"):
                    excel = {"value": round(found["value"], 1), "unit": "m/h", "lines": found.get("lines"),
                             "source": f"Velocidade mais recente da coluna Mt\\h do Excel (linhas com Data Corte de {found.get('from')} a {found.get('to')})"}
                recent_profiles = study.get("recent_profile_speeds") or {}
                profiles = sorted(((p, v) for (name, p), v in recent_profiles.items() if name in names and v["lines"] >= 3),
                                  key=lambda kv: -kv[1]["lines"])[:12]
                m["profile_speeds"] = [{"profile": p, "value": round(v["value"], 1), "lines": v["lines"]} for p, v in profiles]
                summary = study["summary"].get(m["name"]) or {}
                m["observed_week_hours"] = summary.get("hours_median")
            elif excel_area.get(m["code"]):
                excel = {"value": excel_area[m["code"]], "unit": "mm²/h", "source": "Folha CapacidadeMáquinas do Excel (coluna C)"}
            m["excel_rate"] = excel
            active = [r for r in m["rates"] if r["in_force"]]
            m["rate_in_use"] = ("Tabela de velocidades (confirmada)" if any(r["source"] == "Confirmada" for r in active) else
                                "Tabela de velocidades (origem Excel)" if active else
                                ("Velocidade mais recente do Excel" if sector == "cantoneiras" else "Taxa mm²/h do Excel (CapacidadeMáquinas)")
                                if excel else "Por definir")
        all_rates = [r for m in machines for r in m["rates"]]
        tabs = operation_tabs(machines, all_rates)
        seed = excel_seed(sector, machines, study, excel_area)
    rules = [
        "Prazo: " + ("Data Corte." if sector == "cantoneiras" else "Picking (semana do Excel; ano deduzido), depois Data Corte."),
        "Máquina de cada linha: escolha da Carteira → coluna Máquina da Tabela → conjunto de famílias.",
        "Estados: Planeado (Planear + máquina) · Planeado para nesting (tem máquina) · Sem máquina atribuída. Sem máquina não se planeia.",
        "Horas: taxa confirmada da tabela de velocidades; senão histórico válido; senão velocidade mais recente do Excel.",
        "Horas = volume ÷ velocidade + peças × (arranque por peça + tempo fixo por peça), depois × (1 + margem). A margem e o tempo fixo não se aplicam ao histórico.",
        ("Se a espessura não estiver na tabela, usa a imediatamente superior." if sector == "cantoneiras" else
         "Tipo de material vazio = todos. Se a área de secção não estiver na tabela, usa a imediatamente superior."),
        "Capacidade de cada semana: os turnos da máquina nessa semana (calendário), sem os feriados.",
        "Fora da ficha de capacidades: a máquina escolhida mantém-se e entra no plano.",
    ]
    speed_table = {"unit": "m/h" if sector == "cantoneiras" else "mm²/h", "method": "metres_hour" if sector == "cantoneiras" else "area_hour",
                   "range": {"cantoneiras": {"field": "thickness", "label": "Esp.", "unit": "mm"},
                             "perfis": {"field": "section", "label": "Área", "unit": "mm²"}}[sector],
                   "rule": rules[5], "operations": tabs, "seed": seed,
                   "timing": {k: settings.get(k, 0) for k in TIMING},
                   "timing_labels": {k: v[0] for k, v in TIMING.items()}}
    return needs.serial({"sector": sector, "settings": settings, "machines": machines, "weeks": weeks, "rules": rules,
                         "policy": policy, "methods": METHODS, "shift_hours": shifts.shift_hours(settings["template"]),
                         "speed_table": speed_table})


def regenerate(c, sector: str, settings: dict, request_id: uuid.UUID, *, machines: list[dict] | None = None,
               reset_base_for: set | None = None) -> int:
    """Reescreve os calendários das próximas 52 semanas com o modelo atual (horas, dias, feriados).

    Semanas mudadas à mão mantêm os seus turnos; `reset_base_for` = máquinas cujos turnos padrão mudaram
    (as semanas não manuais passam a esse número). Semanas em falta são criadas.
    """
    machines = machines if machines is not None else machine_rows(c, sector)
    changed = 0
    for m in machines:
        if not m.get("has_object"):
            continue  # qualquer máquina do setor tem calendário (07/10/2026); sem recurso gravado não há onde o pendurar
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
    """Semanas do horizonte (52 semanas) sem calendário nas máquinas do setor: [(máquina, ano, semana)]. Só leitura."""
    machines = machines if machines is not None else machine_rows(c, sector)
    return [(m["id"], y, w) for m in machines if m.get("has_object")
            for y, w in _weeks(today) if not shifts.calendar_row(c, m["id"], y, w)]


def extend_horizon(sector: str, *, conn=None, today: date | None = None) -> dict:
    """Prolonga os calendários: cria só as semanas em falta das próximas 52, com os turnos padrão (auditoria 06/10, C1-5).

    Sem isto o horizonte encurta uma semana por semana até alguém gravar as Definições (regenerate só corre aí).
    Regras: todas as máquinas do setor com recurso gravado; semanas existentes (manuais, antigas ou não) não se tocam; feriados do modelo
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


def _store(c, sector: str, definition: dict, actor) -> None:
    clean = {k: definition[k] for k in STORED if k in definition}
    c.execute("""INSERT INTO planning_mtg.sector_settings (area, definition, actor) VALUES (%s, %s, %s)
                 ON CONFLICT (area) DO UPDATE SET definition = EXCLUDED.definition, revision = sector_settings.revision + 1,
                 actor = EXCLUDED.actor, updated_at = now()""", (sector, Jsonb(clean), actor))


def _validate_timing(p: dict, current: dict) -> dict:
    """Margem (%) e tempo fixo por peça (min) do setor; campo ausente = mantém o valor atual."""
    out = {}
    for name, (label, low, high) in TIMING.items():
        value = p.get(name, current.get(name, 0))
        try:
            number = float(str(value).replace(",", ".")) if value not in (None, "") else 0.0
        except ValueError:
            raise planning.PlanningError(f"{label}: indica um número.") from None
        if not low <= number <= high or number != number:
            raise planning.PlanningError(f"{label}: entre {low} e {high}.")
        out[name] = int(number) if number.is_integer() else round(number, 3)
    return out


def _seed_now(c, sector: str, machines: list[dict]) -> list[dict]:
    from . import throughput
    from .estimates import area_rates
    from ..gantt import research
    study = throughput.load(c) if research.enabled() and sector == "cantoneiras" else None
    excel_area = area_rates(research.load(c)["metadata"]) if research.enabled() and sector == "perfis" else {}
    for m in machines:
        m["rate_operations_codes"] = rate_operation_codes(sector, m)
    return excel_seed(sector, machines, study, excel_area)


RATE_FIELDS = {  # payload do ecrã → definição da taxa
    "esp_de": "thickness_min", "esp_ate": "thickness_max", "area_de": "section_min", "area_ate": "section_max",
    "arranque_s": "piece_seconds", "notas": "notes"}


def _save_rate(c, sector: str, payload: dict, machines: dict, request_id: uuid.UUID, salt: str) -> None:
    """Grava (ou arquiva) uma linha da tabela de velocidades; a validação é a do motor (raw/capacity.validate)."""
    from ..raw import objects
    existing = payload.get("id")
    row = c.execute("SELECT revision, archived, definition, name FROM planning_mtg.raw_objects WHERE id = %s AND kind = 'rate'",
                    (existing,)).fetchone() if existing else None
    if existing and not row:
        raise planning.PlanningError("Linha da tabela desconhecida. Recarrega a página.", 404)
    if row and payload.get("expected_revision") is not None and payload["expected_revision"] != row["revision"]:
        raise planning.PlanningError("A linha foi alterada entretanto. Recarrega a página.", 409)
    if payload.get("arquivar"):  # apagar linha = arquivar (fica no histórico de versões)
        if not row:
            raise planning.PlanningError("Linha da tabela desconhecida. Recarrega a página.", 404)
        if str(row["definition"].get("resource_id")) not in machines:
            raise planning.PlanningError("Máquina desconhecida neste setor.")
        objects.save({"request_id": str(uuid.uuid5(request_id, salt)), "id": existing, "expected_revision": row["revision"],
                      "name": row["name"], "area": sector, "definition": row["definition"], "archived": True}, "rate", conn=c, signal=False)
        return
    if str(payload.get("maquina")) not in machines:
        raise planning.PlanningError("Máquina desconhecida neste setor.")
    method = payload.get("metodo") or ("metres_hour" if sector == "cantoneiras" else "area_hour")
    if method not in METHODS:
        raise planning.PlanningError("Unidade da taxa inválida.")
    origin = str(payload.get("origem") or "Confirmada")
    if origin not in ("Excel", "Confirmada"):
        raise planning.PlanningError("Origem da taxa desconhecida.")
    operation = _operation_code(str(payload.get("operacao") or "").strip() or ("corte" if sector == "perfis" else ""))
    if sector == "cantoneiras" and not operation.isdigit():
        raise planning.PlanningError("Nas cantoneiras a operação é um código (ex.: 112 ou 119).")
    definition = {"resource_id": str(payload["maquina"]), "area": sector, "operation": operation,
                  "method": method, "value": payload.get("valor"), "setup_minutes": 0,
                  "profile": str(payload.get("perfil") or "").strip(),
                  "material_type": str(payload.get("tipo_material") or "").strip() if sector == "perfis" else "",
                  "valid_from": str(payload.get("desde") or (row["definition"].get("valid_from") if row else None) or date.today().isoformat()),
                  "valid_until": str(payload["ate"]) if payload.get("ate") else None,
                  "confirmed": True, "source": origin}
    for field, name in RATE_FIELDS.items():
        if field in payload:
            definition[name] = payload[field]
    ranges = [definition.get(k) for k in ("thickness_min", "thickness_max", "section_min", "section_max")]
    label = " · ".join(x for x in [
        machines[str(payload["maquina"])]["name"], operation or "operação", definition["material_type"] or None, definition["profile"] or None,
        (f"{ranges[0] if ranges[0] not in (None, '') else '…'}–{ranges[1] if ranges[1] not in (None, '') else '…'} mm" if any(r not in (None, "") for r in ranges[:2]) else None),
        (f"{ranges[2] if ranges[2] not in (None, '') else '…'}–{ranges[3] if ranges[3] not in (None, '') else '…'} mm²" if any(r not in (None, "") for r in ranges[2:]) else None)] if x)
    objects.save({"request_id": str(uuid.uuid5(request_id, salt)), "id": existing, "expected_revision": row["revision"] if row else 0,
                  "name": label, "area": sector, "definition": definition, "archived": False}, "rate", conn=c, signal=False)


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
            new = {**{k: current[k] for k in TIMING if k in current}, **new}  # a margem e o tempo fixo ficam
            _store(c, sector, new, actor)
            settings = {**new, "revision": current["revision"] + 1}
            changed = regenerate(c, sector, settings, request_id)
        elif kind == "tempos":  # margem e tempo fixo por peça: mudam as horas, não os calendários
            if payload.get("expected_revision") != current["revision"]:
                raise planning.PlanningError("As definições mudaram entretanto. Recarrega a página.", 409)
            timing = _validate_timing(payload, current)
            stored = c.execute("SELECT definition FROM planning_mtg.sector_settings WHERE area = %s", (sector,)).fetchone() \
                if c.execute("SELECT to_regclass('planning_mtg.sector_settings') t").fetchone()["t"] else None
            base = dict(stored["definition"]) if stored else {k: current[k] for k in ("template", "workdays", "holidays")}
            _store(c, sector, {**base, **timing}, actor)
            changed = 1
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
            if "confirmada" in payload:  # a caixa saiu das Definições (07/10/2026); fica por compatibilidade
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
            _save_rate(c, sector, payload, machines, request_id, "rate")
            changed = 1
        elif kind == "taxas_lote":  # «Preencher com as velocidades atuais do Excel»
            machines = {m["id"]: m for m in machine_rows(c, sector)}
            lines = payload.get("linhas")
            if lines is None:
                lines = [{**x, "origem": "Excel"} for x in _seed_now(c, sector, list(machines.values()))]
            if not isinstance(lines, list) or len(lines) > 500:
                raise planning.PlanningError("Lista de velocidades inválida.")
            active = c.execute("SELECT definition FROM planning_mtg.raw_objects WHERE kind='rate' AND NOT archived").fetchall()
            taken = {(str(r["definition"].get("resource_id")), r["definition"].get("area"), _operation_code(r["definition"].get("operation")))
                     for r in active}
            changed = 0
            for i, line in enumerate(lines):
                if not isinstance(line, dict):
                    raise planning.PlanningError("Linha de velocidade inválida.")
                ident = (str(line.get("maquina")), sector, _operation_code(line.get("operacao") or ("corte" if sector == "perfis" else "")))
                if ident in taken:
                    continue  # a máquina/operação já tem linhas na tabela: preencher não as substitui
                _save_rate(c, sector, {**line, "id": None, "arquivar": False, "origem": line.get("origem") or "Excel"},
                           machines, request_id, f"rate-batch-{i}")
                taken.add(ident)
                changed += 1
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
