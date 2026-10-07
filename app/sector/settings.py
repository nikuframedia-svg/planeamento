"""Definições de cada setor: máquinas, turnos, tempos e capacidades (pedido do Luís, 06/10/2026).

Lê e grava sem criar uma segunda fonte de verdade:
- máquinas = recursos físicos (raw_objects kind='resource'): turnos padrão (`default_shifts`)
  e correção local do intervalo da ficha de capacidades (`capacity_override`, aplicada nas candidatas);
- turnos = calendários semanais (shifts.py) gerados a partir do modelo do setor (horas dos turnos,
  dias de trabalho, feriados) guardado em sector_settings;
- tempos = tabela de velocidades (kind='rate', plano de 06/10, parte 3): uma linha por máquina, operação e
  intervalo (espessura nas cantoneiras, tipo de material e área de secção nos perfis), com arranque por peça;
  tempo fixo por peça (min) do setor em sector_settings (0 = as horas não mudam);
- eficiência de cada máquina (%, por defeito 100, pressuposto; 08/10) em sector_settings.definition.efficiency:
  o único fator sobre as horas (horas do Excel × 100 / eficiência). Substitui a margem do setor, que deixa de se
  editar. Ao lado mostra-se o «medido» (histórico ÷ Excel), só para comparar.
Cada gravação guarda a definição inteira: chaves que o ecrã não envia ficam como estavam (S01, 08/10).
"""
from __future__ import annotations

import re
import uuid
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone

from psycopg.types.json import Jsonb

from .. import planning, planning_needs as needs, planning_registration as registration
from . import shifts
from .week import lisbon_today

UNIT = {"cantoneiras": "MTG3", "perfis": "MTG2"}
HORIZON_WEEKS = 52
METHODS = {"metres_hour": "m/h", "area_hour": "mm²/h", "units_hour": "peças/h", "minutes_unit": "min/peça", "fixed_minutes": "min"}
TIMING = {"margin_pct": ("Margem (substituída pela eficiência de cada máquina)", 0, 300), "piece_minutes": ("Tempo fixo por peça (min)", 0, 120)}
EFFICIENCY_LABEL = "Eficiência da máquina (% da velocidade do Excel)"
# Campos do payload «maquina» que mudam o recurso físico (raw_objects); a eficiência fica nas Definições do setor.
RESOURCE_FIELDS = {"turnos_padrao", "confirmada", "ficha", "nomes", "operacoes", "janela_historico"}
OPERATION_NAMES = {"112": "Punção", "119": "Broca", "corte": "Corte", "abocardar": "Abocardar"}
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def default(today: date | None = None) -> dict:
    year = (today or date.today()).year
    return {"template": [list(x) for x in shifts.DEFAULT_TEMPLATE], "workdays": list(shifts.DEFAULT_WORKDAYS),
            "holidays": shifts.national_holidays(year) + shifts.national_holidays(year + 1), "revision": 0,
            "margin_pct": 0, "piece_minutes": 0, "efficiency": {}}


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
    """Separadores por operação da tabela de velocidades (ex.: Punção · 112, Broca · 119), com o processo da ficha.

    As operações mais usadas primeiro (mais máquinas, depois mais linhas na tabela), para o 112 e o 119 não ficarem
    atrás das operações de um só posto desde que contam todas as máquinas do setor (07/10/2026); empate pelo código.
    """
    from collections import Counter, defaultdict
    processes = defaultdict(Counter)
    for m in machines:
        for cap in m.get("ficha") or []:
            if cap.get("process"):
                processes[_operation_code(cap["operation"])][cap["process"]] += 1
    codes = {code for m in machines for code in m.get("rate_operations_codes") or []}
    codes |= {_operation_code(r.get("operation")) for r in rates if r.get("operation")}
    used = Counter(code for m in machines for code in set(m.get("rate_operations_codes") or []))
    lines = Counter(_operation_code(r.get("operation")) for r in rates if r.get("operation"))
    tabs = []
    for code in sorted(codes, key=lambda c: (-used[c], -lines[c], not c.isdigit(), int(c) if c.isdigit() else 0, c)):
        name = processes[code].most_common(1)[0][0] if processes[code] else OPERATION_NAMES.get(code)
        tabs.append({"code": code, "label": f"{name} · {code}" if name and code.isdigit() else (name or code),
                     "machines": [m["id"] for m in machines if code in (m.get("rate_operations_codes") or [])]})
    return tabs


def excel_seed(sector: str, machines: list[dict], study: dict | None, excel_area: dict) -> list[dict]:
    """«Preencher com as velocidades atuais do Excel»: uma linha por máquina do setor e operação.

    Cantoneiras: a velocidade mais recente do Excel da máquina (moda das linhas com Data Corte nas últimas
    semanas com dados, `productivity.recent_excel_speeds`), igual em todas as operações da máquina — a mesma que
    a Carteira, a Carga, o motor e o Gantt usam sem tabela, por isso preencher não muda as horas. Perfis: a taxa
    mm²/h da folha CapacidadeMáquinas, colunas E/F (08/10; `excel_area` por ID da máquina, `_excel_area`), sem o
    fator ×3 da Thomas (aplica-se nas contas, QTD > 50).
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
        elif "corte" in (m.get("rate_operations_codes") or []):
            found = excel_area.get(m["id"]) or excel_area.get(m.get("code"))
            if not found:
                continue
            value, cell = (found["value"], found.get("cell")) if isinstance(found, dict) else (found, None)
            seed.append({"maquina": m["id"], "nome": m["name"], "operacao": "corte", "metodo": "area_hour", "valor": value,
                         "unidade": "mm²/h", "linhas": None,
                         "notas": f"Excel: folha CapacidadeMáquinas, {cell or 'coluna E/F'} (sem fator ×3)"})
    return seed


def _excel_area(c, machines: list[dict]) -> dict:
    """{ID da máquina: {value, cell, machine}}: taxa mm²/h E/F do Excel dos perfis em uso (08/10), pelos nomes da
    máquina (nome e aliases), como a Carteira e o motor."""
    from ..raw.productivity import current_excel_area
    from .estimates import machine_names
    sheet = current_excel_area(c)
    out = {}
    for m in machines:
        names = machine_names(m)
        found = sorted((name, e) for name, e in sheet.items() if name in names and e.get("value"))
        if found:
            name, entry = found[0]
            out[m["id"]] = {"value": entry["value"], "cell": entry.get("cell"), "machine": name}
    return out


def _measured(c, sector: str) -> dict:
    """{ID da máquina|operação: histórico} da última revisão de capacidade (08/10): só para mostrar como «medido»."""
    from ..raw import query
    try:
        gen = query.generation(c, sector, dataset="capacity")
    except planning.PlanningError:
        return {}
    return (gen["metadata"] or {}).get("measured_rates") or {}


def measured_view(m: dict, measured: dict) -> list[dict]:
    """O «medido» de uma máquina por operação: velocidade das folhas OCR com horas ÷ velocidade do Excel, com a amostra.

    Só informação (08/10): as horas usam a velocidade do Excel × eficiência. Amostra pequena (abaixo do mínimo do
    histórico) mostra-se com o aviso, nunca escondida.
    """
    from ..raw.productivity import PLAUSIBLE, THOMAS_MIN_QUANTITY, thomas_factor
    excel = m.get("excel_rate") or {}
    names = [m.get("name")] + [a.get("name") for a in m.get("aliases") or []]
    out = []
    for key, h in sorted(measured.items()):
        rid, _, operation = key.partition("|")
        if rid != m["id"] or not h.get("hours") or not h.get("volume"):
            continue
        rate = h["volume"] / h["hours"]
        ratio = rate / excel["value"] * 100 if excel.get("value") and excel.get("unit") == h.get("unit") else None
        # Thomas (achado A-medido-thomas): com QTD > 50 o Excel já conta 3 × a taxa E/F, e o medido não diz quantas linhas
        # foram dessas. Comparar com a taxa base daria ~300 % e, passado à eficiência, contaria o × 3 duas vezes.
        thomas = thomas_factor(m.get("area"), operation, names + [h.get("machine")], THOMAS_MIN_QUANTITY + 1) != 1
        if thomas:
            ratio = None
        out.append({"operation": operation, "value": round(rate, 1), "unit": h.get("unit"), "hours": round(h["hours"], 1),
                    "sheets": h.get("sheet_count"), "events": h.get("event_count"), "window": h.get("window"),
                    "enough": h.get("value") is not None, "reason": h.get("reason"),
                    "ratio_pct": round(ratio) if ratio is not None else None,
                    "plausible": ratio is None or PLAUSIBLE[0] <= ratio / 100 <= PLAUSIBLE[1],
                    **({"note": "O × 3 da Thomas (QTD > 50) já está nas horas: este medido não se compara com a taxa base "
                                "nem deve ir para a eficiência."} if thomas else {})})
    return out


def _rate_view(r: dict, today: str) -> dict:
    from ..raw.productivity import rate_tier
    d = r["definition"]
    return {"id": str(r["id"]), "name": r["name"], "revision": r["revision"], **d,
            "operation_code": _operation_code(d.get("operation")), "source": rate_tier(d),
            "in_force": bool(d.get("confirmed")) and str(d.get("valid_from") or "") <= today
                        and (not d.get("valid_until") or today <= str(d["valid_until"]))}


def overview(sector: str) -> dict:
    from . import priority, throughput
    from ..gantt import research
    from ..raw.productivity import efficiency_of, sector_timing
    planning.check_area(sector)
    today = lisbon_today().isoformat()  # vigência das taxas no dia de Lisboa, como as contas (F24)
    with planning.connect(readonly=True) as c:
        settings = read(c, sector)
        machines = machine_rows(c, sector)
        rates = c.execute("SELECT id, name, revision, definition FROM planning_mtg.raw_objects WHERE kind='rate' AND NOT archived ORDER BY name").fetchall()
        study = throughput.load(c) if research.enabled() and sector == "cantoneiras" else None
        excel_area = _excel_area(c, machines) if sector == "perfis" else {}
        timing = sector_timing(c)[sector]
        measured = _measured(c, sector)
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
            elif excel_area.get(m["id"]):
                found = excel_area[m["id"]]
                excel = {"value": found["value"], "unit": "mm²/h",
                         "source": f"Folha CapacidadeMáquinas do Excel ({found['cell']}, colunas E/F de 29/11/2024; o × 3 da Thomas aplica-se com QTD > 50)"}
            m["excel_rate"] = excel
            active = [r for r in m["rates"] if r["in_force"]]
            m["rate_in_use"] = ("Tabela de velocidades (confirmada)" if any(r["source"] == "Confirmada" for r in active) else
                                "Tabela de velocidades (origem Excel)" if active else
                                ("Velocidade mais recente do Excel" if sector == "cantoneiras" else "Taxa mm²/h do Excel (CapacidadeMáquinas E/F)")
                                if excel else "Por definir")
            # Eficiência (pressuposto, 08/10) e, ao lado, o medido nas folhas OCR com horas (só para comparar).
            m["efficiency_pct"] = round(efficiency_of(timing, m["id"]), 2)
            m["efficiency_default"] = str(m["id"]) not in (timing.get("efficiency") or {}) and "*" not in (timing.get("efficiency") or {})
            m["measured"] = measured_view(m, measured)
        all_rates = [r for m in machines for r in m["rates"]]
        tabs = operation_tabs(machines, all_rates)
        seed = excel_seed(sector, machines, study, excel_area)
    rules = [
        "Prazo: " + ("Data Corte." if sector == "cantoneiras" else "Picking (semana do Excel; ano deduzido), depois Data Corte."),
        "Máquina de cada linha: escolha da Carteira → coluna Máquina da Tabela → conjunto de famílias.",
        "Estados: Planeado (Planear + máquina) · Planeado para nesting (tem máquina) · Sem máquina atribuída. Sem máquina não se planeia.",
        "Horas: taxa confirmada da tabela de velocidades; senão velocidade do Excel da máquina da linha" +
        (" (a mais recente da coluna Mt\\h)." if sector == "cantoneiras" else
         " (CapacidadeMáquinas, colunas E/F; × 3 na Thomas com QTD > 50, como no Excel).") +
        " O histórico medido só se mostra, para comparar.",
        "Horas = (volume ÷ velocidade + peças × (arranque por peça + tempo fixo por peça)) × 100 ÷ eficiência da máquina. "
        "Uma taxa confirmada marcada como medida não leva a eficiência nem o tempo fixo.",
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
                   "timing_labels": {k: v[0] for k, v in TIMING.items()},
                   # 08/10: a margem do setor já não se edita; a eficiência é por máquina (machines[].efficiency_pct).
                   "margin_editable": False, "efficiency_label": EFFICIENCY_LABEL}
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
        weeks = _calendar_weeks(c, m)
        if weeks is None:
            continue
        default_plan = {str(d): (m["default_shifts"] if d in settings["workdays"] else 0) for d in range(1, 8)}
        for (year, week), row in weeks.items():
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


def _calendar_weeks(c, m: dict, today: date | None = None) -> dict | None:
    """{(ano, semana): calendário ou None} do horizonte de uma máquina que tem calendários; None se não tem.

    Qualquer máquina do setor com recurso gravado pode ter calendário (07/10/2026), mas só se criam semanas quando
    tem turnos padrão ou já tem alguma semana gravada: semanas a 0 turnos fariam de uma máquina parada uma
    máquina «com calendário» de 0 h na Carga e nas capacidades.
    """
    if not m.get("has_object"):
        return None  # sem recurso gravado não há onde pendurar o calendário
    weeks = {(y, w): shifts.calendar_row(c, m["id"], y, w) for y, w in _weeks(today)}
    return weeks if m.get("default_shifts", 0) > 0 or any(weeks.values()) else None


def missing_weeks(c, sector: str, *, machines: list[dict] | None = None, today: date | None = None) -> list[tuple[str, int, int]]:
    """Semanas do horizonte (52 semanas) sem calendário nas máquinas do setor que têm calendários
    (`_calendar_weeks`): [(máquina, ano, semana)]. Só leitura."""
    machines = machines if machines is not None else machine_rows(c, sector)
    return [(m["id"], y, w) for m in machines for (y, w), row in (_calendar_weeks(c, m, today) or {}).items() if not row]


def extend_horizon(sector: str, *, conn=None, today: date | None = None) -> dict:
    """Prolonga os calendários: cria só as semanas em falta das próximas 52, com os turnos padrão (auditoria 06/10, C1-5).

    Sem isto o horizonte encurta uma semana por semana até alguém gravar as Definições (regenerate só corre aí).
    Regras: máquinas do setor com recurso gravado e com turnos padrão ou calendário já gravado; semanas existentes (manuais, antigas ou não) não se tocam; feriados do modelo
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


def _stored(c, sector: str) -> dict:
    """A definição gravada do setor, tal como está (sem os valores por defeito de `read`)."""
    if not c.execute("SELECT to_regclass('planning_mtg.sector_settings') t").fetchone()["t"]:
        return {}
    row = c.execute("SELECT definition FROM planning_mtg.sector_settings WHERE area = %s", (sector,)).fetchone()
    return dict(row["definition"]) if row else {}


def _first_store(c, sector: str, current: dict) -> dict:
    """Na primeira gravação do setor, o modelo dos turnos em uso (por defeito) vai junto; depois, nada."""
    return {} if _stored(c, sector) else {k: current[k] for k in ("template", "workdays", "holidays")}


def _store(c, sector: str, definition: dict, actor) -> None:
    """Grava a definição do setor juntando-a à gravada (S01, 08/10).

    Antes só ficavam as chaves de uma lista fixa (STORED): qualquer chave nova (eficiência, folga, clientes
    prioritários, pessoas, política…) desaparecia na gravação seguinte do horário ou dos tempos. Agora todas as
    chaves gravadas ficam; as enviadas substituem as do mesmo nome.
    """
    clean = {**_stored(c, sector), **{k: v for k, v in definition.items() if k != "revision"}}
    c.execute("""INSERT INTO planning_mtg.sector_settings (area, definition, actor) VALUES (%s, %s, %s)
                 ON CONFLICT (area) DO UPDATE SET definition = EXCLUDED.definition, revision = sector_settings.revision + 1,
                 actor = EXCLUDED.actor, updated_at = now()""", (sector, Jsonb(clean), actor))


def _number(value, label: str) -> float:
    try:
        number = float(str(value).replace(",", ".")) if value not in (None, "") else 0.0
    except ValueError:
        raise planning.PlanningError(f"{label}: indica um número.") from None
    if number != number:
        raise planning.PlanningError(f"{label}: indica um número.")
    return number


def _validate_timing(p: dict, current: dict) -> dict:
    """Tempo fixo por peça (min) do setor; campo ausente = mantém o valor atual.

    A margem do setor deixou de se editar (08/10): a eficiência de cada máquina é o único fator sobre as horas.
    Enviar o valor atual (o ecrã antigo envia os dois campos) não muda nada; outro valor é recusado.
    """
    out = {}
    for name, (label, low, high) in TIMING.items():
        number = _number(p.get(name, current.get(name, 0)), label)
        if name == "margin_pct":
            if number != _number(current.get(name, 0), label):
                raise planning.PlanningError("A margem do setor deixou de existir: indica a eficiência de cada máquina.")
            continue
        if not low <= number <= high:
            raise planning.PlanningError(f"{label}: entre {low} e {high}.")
        out[name] = int(number) if number.is_integer() else round(number, 3)
    return out


def _validate_efficiency(value) -> float | None:
    """Eficiência (%) de uma máquina: None (vazio) ou 100 = sem fator; senão entre 10 e 200."""
    from ..raw.productivity import EFFICIENCY_RANGE
    if value in (None, ""):
        return None
    number = _number(value, EFFICIENCY_LABEL)
    low, high = EFFICIENCY_RANGE
    if not low <= number <= high:
        raise planning.PlanningError(f"{EFFICIENCY_LABEL}: entre {low:g} e {high:g} %.")
    number = int(number) if number.is_integer() else round(number, 2)
    return None if number == 100 else number


def _efficiency_store(current: dict, changes: dict, machines: dict) -> dict:
    """Eficiências do setor depois das alterações ({resource_id: % ou None}); só as diferentes de 100 ficam.

    Uma margem antiga ≠ 0 sem eficiências gravadas passa à eficiência equivalente em todas as máquinas do setor
    antes de aplicar a alteração (08/10), para as outras máquinas não mudarem de horas; a margem fica a 0.

    Só máquinas com recurso gravado (has_object): o motor de capacidade conhece a máquina pelo recurso gravado
    (aliases), e numa máquina só do catálogo (ID 'v2:…') a eficiência valeria na Carteira e no Gantt mas não na
    Tabela nem nas horas documentais da Carga (achado A-efic-id, 08/10). Tirar a eficiência (vazio/100) é sempre
    possível.
    """
    stored = {str(k): v for k, v in (current.get("efficiency") or {}).items()}
    margin = float(current.get("margin_pct") or 0)
    if margin and not stored:
        equivalent = round(100 / (1 + margin / 100), 4)
        stored = {rid: equivalent for rid, m in machines.items() if m.get("has_object")}
    for rid, pct in changes.items():
        if str(rid) not in machines:
            raise planning.PlanningError("Máquina desconhecida neste setor.")
        value = _validate_efficiency(pct)
        if value is not None and not machines[str(rid)].get("has_object"):
            raise planning.PlanningError("Esta máquina ainda não tem recurso gravado: a eficiência só se indica em máquinas com recurso.")
        if value is None:
            stored.pop(str(rid), None)
        else:
            stored[str(rid)] = value
    return stored


def _seed_now(c, sector: str, machines: list[dict]) -> list[dict]:
    from . import throughput
    from ..gantt import research
    study = throughput.load(c) if research.enabled() and sector == "cantoneiras" else None
    excel_area = _excel_area(c, machines) if sector == "perfis" else {}
    for m in machines:
        m["rate_operations_codes"] = rate_operation_codes(sector, m)
    return excel_seed(sector, machines, study, excel_area)


RATE_FIELDS = {  # payload do ecrã → definição da taxa
    "esp_de": "thickness_min", "esp_ate": "thickness_max", "area_de": "section_min", "area_ate": "section_max",
    "arranque_s": "piece_seconds", "notas": "notes",
    "medida": "measured"}  # taxa confirmada medida na produção: sem eficiência nem tempo fixo (08/10)


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
                  "valid_from": str(payload.get("desde") or (row["definition"].get("valid_from") if row else None) or lisbon_today().isoformat()),
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


def _save_resource(c, sector: str, m: dict, payload: dict, current: dict, request_id: uuid.UUID) -> int:
    """Grava os campos do recurso físico de uma máquina (turnos padrão, ficha, nomes, operações, janela)."""
    from ..raw import objects
    if not m["has_object"]:
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
    return changed


def save(payload: dict, *, conn=None) -> dict:
    sector = str(payload.get("setor") or "")
    kind = payload.get("tipo")
    try:
        request_id = uuid.UUID(str(payload.get("request_id")))
    except ValueError:
        raise planning.PlanningError("Pedido sem identificador; recarrega a página.") from None
    actor = registration.human_actor(payload)
    with (planning.connect() if conn is None else nullcontext(conn)) as c:
        planning.check_area(sector)
        c.execute("SELECT pg_advisory_xact_lock(hashtext('sector_settings:' || %s))", (sector,))
        current = read(c, sector)
        if kind == "setor":
            new = _validate_settings(payload)
            if payload.get("expected_revision") != current["revision"]:
                raise planning.PlanningError("As definições mudaram entretanto. Recarrega a página.", 409)
            _store(c, sector, new, actor)  # o resto da definição (tempos, eficiências…) fica como está (S01)
            settings = {**current, **new, "revision": current["revision"] + 1}
            changed = regenerate(c, sector, settings, request_id)
        elif kind == "tempos":  # tempo fixo por peça: muda as horas, não os calendários
            if payload.get("expected_revision") != current["revision"]:
                raise planning.PlanningError("As definições mudaram entretanto. Recarrega a página.", 409)
            _store(c, sector, {**_first_store(c, sector, current), **_validate_timing(payload, current)}, actor)
            changed = 1
        elif kind == "eficiencia":  # eficiência por máquina (08/10): muda as horas, não os calendários
            if payload.get("expected_revision") != current["revision"]:
                raise planning.PlanningError("As definições mudaram entretanto. Recarrega a página.", 409)
            machines = {m["id"]: m for m in machine_rows(c, sector)}
            changes = payload.get("eficiencias")
            if changes is None and "maquina" in payload:
                changes = {str(payload["maquina"]): payload.get("eficiencia")}
            if not isinstance(changes, dict) or not changes or len(changes) > 200:
                raise planning.PlanningError("Indica a eficiência de pelo menos uma máquina.")
            _store(c, sector, {**_first_store(c, sector, current), "efficiency": _efficiency_store(current, changes, machines),
                               "margin_pct": 0}, actor)
            changed = 1
        elif kind == "maquina":
            machines = {m["id"]: m for m in machine_rows(c, sector)}
            m = machines.get(str(payload.get("id")))
            if not m:
                raise planning.PlanningError("Máquina desconhecida neste setor.")
            changed = 0
            if "eficiencia" in payload:  # a eficiência vive nas Definições do setor, não no recurso (08/10)
                _store(c, sector, {**_first_store(c, sector, current), "margin_pct": 0,
                                   "efficiency": _efficiency_store(current, {m["id"]: payload["eficiencia"]}, machines)}, actor)
                changed += 1
            if RESOURCE_FIELDS.intersection(payload) or "eficiencia" not in payload:
                changed += _save_resource(c, sector, m, payload, current, request_id)
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
