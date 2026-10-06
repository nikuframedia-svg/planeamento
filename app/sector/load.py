"""Carga e turnos por máquina e semana (pedido do Luís, 06/10/2026).

Para cada máquina e semana ISO (a atual e as 12 seguintes):
- capacidade = horas do calendário dessa semana (na semana atual, só as que faltam a partir de agora;
  a semana inteira fica em «full_capacity»);
- no plano = horas das linhas «Planeado» (Planear + máquina) na sua máquina, na semana do prazo;
- a vencer = trabalho aberto não planeado com prazo nessa semana: na máquina efetiva («com máquina») ou
  na sugerida (à parte);
- atrasado = prazo antes da semana atual: fica à parte, por máquina («late_before»), e não entra na carga
  da semana atual (07/10/2026); o que tem prazo entre segunda e ontem fica na semana atual, marcado como
  atrasado (a mesma regra da Carteira e do painel Máquinas);
- linhas excluídas na Carteira não contam (como na lista vermelha do quadro);
- máquinas do setor sem calendário que têm trabalho aparecem com capacidade 0 e «Sem calendário»;
- recomendação de turnos (shifts.advise): na semana atual, atrasado + carga da semana contra as horas que
  faltam; nas outras, a carga da semana. Tirar turnos só nas 3 primeiras semanas (mais à frente a carga ainda
  está a chegar) e nunca numa máquina com trabalho atrasado ou sem prazo;
- cor da célula (status): carga da semana contra a capacidade da semana inteira, os mesmos números que a
  célula mostra; o atrasado não pinta a semana atual (tem a sua coluna);
- ao lado, o que as antigas páginas Capacidades/Disponibilidade mostravam (load_sources.py): horas segundo o
  Excel, peso, horas reais declaradas, calendário do Excel; e totais por máquina (separador Máquinas).
Prazo pela política do setor (MTG3 Data Corte; MTG2 Picking, depois Data Corte). As horas são as mesmas da
Carteira (occurrences + estimates); horas desconhecidas nunca contam como zero — são contadas à parte.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from .. import planning, planning_needs as needs
from . import shifts

WEEKS = 13
REDUCE_WEEKS = 3  # só se propõe tirar turnos na semana atual e nas duas seguintes
PLAN, DUE, SUGGESTED = "plan", "due", "suggested"


def _week_of(day) -> tuple[int, int] | None:
    if not day:
        return None
    d = day if isinstance(day, date) else date.fromisoformat(str(day)[:10])
    y, w, _ = d.isocalendar()
    return y, w


def _today() -> date:
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Europe/Lisbon")).date()


def week_list(today: date | None = None, count: int = WEEKS) -> list[tuple[int, int]]:
    today = today or _today()
    monday = today - timedelta(days=today.weekday())
    return [(monday + timedelta(weeks=i)).isocalendar()[:2] for i in range(count)]


def classify(fact: dict, planned_keys: set, current: tuple[int, int], horizon: set,
             today: date | None = None) -> tuple[str, tuple[int, int] | str, bool] | None:
    """(kind, week | 'sem_data' | 'depois', late) for one occurrence; None when it has no machine at all.

    Atrasado = prazo antes de hoje, como na Carteira e no painel Máquinas (auditoria 06/10/2026, C5-3).
    O que tem prazo entre segunda e ontem fica na célula da semana atual, já como atrasado.
    """
    rid = fact.get("planning_resource_id")
    if not rid:
        return None
    planned = fact.get("line_key") in planned_keys and fact.get("machine_basis") == "atribuída"
    kind = PLAN if planned else DUE if fact.get("machine_basis") == "atribuída" else SUGGESTED
    day = fact.get("priority_day")
    week = _week_of(day)
    if week is None:
        return kind, "sem_data", False
    late = (str(day)[:10] < today.isoformat()) if today else week < current
    if week < current:
        return kind, current, True
    return (kind, week, late) if week in horizon else (kind, "depois", late)


def _empty_cell():
    return {PLAN: 0.0, DUE: 0.0, SUGGESTED: 0.0, "late": 0.0, "unknown": 0, "operations": 0, "excel": 0.0, "excel_unknown": 0}


def _empty_total():
    return {"operations": 0, "unknown": 0, "pieces": 0.0, "metres": 0.0, "area_mm2": 0.0, "weight_kg": 0.0, "weight_unknown": 0,
            "load": 0.0, "late": 0.0, "late_before": 0.0, "after": 0.0, "no_date": 0.0, "excel_hours": 0.0, "excel_unknown": 0}


def _before_week(fact: dict, monday: date) -> bool:
    """Prazo antes da segunda-feira da semana atual: atrasado à parte (coluna Atrasado), fora da semana atual."""
    day = fact.get("priority_day")
    return bool(day) and str(day)[:10] < monday.isoformat()


def advice_text(advice: dict, missing: float, shifts_now: int | None = None) -> dict:
    """Texto simples da recomendação: «faltam 52 h · +1 turno» / «sobram 40 h · −1 turno» (07/10/2026)."""
    delta = advice.get("delta") or 0
    if delta > 0:
        text = f"faltam {missing:.0f} h · +{delta} turno{'s' if delta > 1 else ''}"
    elif delta < 0:
        text = f"sobram {-missing:.0f} h · −{-delta} turno{'s' if delta < -1 else ''}"
    elif missing > 0.05:
        full = shifts_now is not None and shifts_now >= shifts.MAX_SHIFTS
        text = f"faltam {missing:.0f} h · já tem {shifts.MAX_SHIFTS} turnos" if full else f"faltam {missing:.0f} h"
    elif missing < -0.05:
        text = f"sobram {-missing:.0f} h"
    else:
        text = "certo"
    return {**advice, "text": text}


def recommend(load_hours: float, capacity: float, n: int, settings: dict, *, workdays: int, can_reduce: bool) -> dict:
    """Recomendação de turnos (shifts.advise) com o texto simples; −1 só quando `can_reduce`."""
    advice = shifts.advise(load_hours, capacity, n, settings, workdays_in_week=workdays)
    missing = load_hours - capacity
    if advice["delta"] < 0 and not can_reduce:
        advice = {"delta": 0}
    return advice_text(advice, missing, n)


def _add_total(t: dict, f: dict, week, late: bool, excel, weight, applies: bool, before: bool = False) -> None:
    t["operations"] += 1
    if f.get("phase", "principal") == "principal":
        t["pieces"] += f.get("pieces") or 0
        t["metres"] += f.get("metres") or 0
        if f.get("remaining") is not None and f.get("section_unit"):
            t["area_mm2"] += f["remaining"] * f["section_unit"]
        if weight is None:
            t["weight_unknown"] += 1
        else:
            t["weight_kg"] += weight
    if applies:
        if excel is None:
            t["excel_unknown"] += 1
        else:
            t["excel_hours"] += excel
    hours = f.get("load_hours")
    if hours is None:
        t["unknown"] += 1
        return
    t["load"] += hours
    if late:
        t["late"] += hours
    if before:
        t["late_before"] += hours
    if week == "depois":
        t["after"] += hours
    elif week == "sem_data":
        t["no_date"] += hours


def _context(sector: str, today: date | None = None):
    from . import occurrences, portfolio, selection, settings as sector_settings
    data = portfolio.current(sector)
    decisions = selection.current(sector)
    planned = {x["key"] for x in data["lines"] if portfolio.status_of(x, decisions)["planeado"]}
    occ = occurrences.load(sector, allow_stale=True)
    # Linha excluída na Carteira não é trabalho a planear: não conta na Carga, como na lista vermelha (A8-5).
    excluded = {x["key"] for x in data["lines"] if portfolio.decision_of(x, decisions) == "excluded"}
    if excluded:
        occ = {**occ, "facts": [f for f in occ["facts"] if f.get("line_key") not in excluded]}
    return data, planned, occ


def overview(sector: str, *, today: date | None = None, now: datetime | None = None) -> dict:
    from . import load_sources, settings as sector_settings
    planning.check_area(sector)
    today = today or _today()
    now = now or datetime.now(timezone.utc)
    weeks = week_list(today)
    horizon = set(weeks)
    current = weeks[0]
    data, planned, occ = _context(sector, today)
    with planning.connect(readonly=True) as c:
        settings = sector_settings.read(c, sector)
        machines = sector_settings.machine_rows(c, sector)
        ids = [m["id"] for m in machines]
        calendars = c.execute("SELECT definition FROM planning_mtg.raw_objects WHERE kind='calendar' AND NOT archived "
                              "AND definition->>'resource_id' = ANY(%s)", (ids,)).fetchall()
        src = load_sources.context(c, sector)
    cal = {(str(r["definition"]["resource_id"]), int(r["definition"]["year"]), int(r["definition"]["week"])): r["definition"] for r in calendars}
    cells = defaultdict(_empty_cell)
    no_date = defaultdict(_empty_cell)
    late_before = defaultdict(_empty_cell)  # prazo antes da semana atual: coluna Atrasado, fora da semana atual
    monday_now = date.fromisocalendar(*current, 1)
    totals = defaultdict(_empty_total)
    own = set(ids)
    elsewhere = defaultdict(lambda: {"operations": 0, "hours": 0.0, "unknown": 0})
    for f in occ["facts"]:
        found = classify(f, planned, current, horizon, today)
        excel, weight, applies = load_sources.fact_values(f, src["lines"])
        if not found:  # sem máquina: só entra nos totais («Sem máquina»)
            _add_total(totals[None], f, "sem_data" if not f.get("priority_day") else None, False, excel, weight, applies)
            continue
        if f["planning_resource_id"] not in own:  # trabalho do setor numa máquina de outro setor: nota à parte
            e = elsewhere[f["planning_resource_id"]]
            e["operations"] += 1
            e["hours"] += f.get("load_hours") or 0
            e["unknown"] += f.get("load_hours") is None
            continue
        kind, week, late = found
        before = week == current and _before_week(f, monday_now)
        _add_total(totals[f["planning_resource_id"]], f, week, late, excel, weight, applies, before)
        if week == "depois":
            continue
        target = (no_date[f["planning_resource_id"]] if week == "sem_data" else late_before[f["planning_resource_id"]] if before
                  else cells[(f["planning_resource_id"], *week)])
        target["operations"] += 1
        if applies:
            if excel is None:
                target["excel_unknown"] += 1
            else:
                target["excel"] += excel
        if f.get("load_hours") is None:
            target["unknown"] += 1
            continue
        target[kind] += f["load_hours"]
        if late:
            target["late"] += f["load_hours"]
    rows = []
    for m in machines:
        has_load = any(cells.get((m["id"], y, w)) for y, w in weeks)
        has_calendar = any((m["id"], y, w) in cal for y, w in weeks)
        # Máquina do setor sem calendário mas com trabalho (mesmo sem prazo ou sem horas): a linha aparece,
        # com capacidade 0 e «Sem calendário», em vez de o trabalho desaparecer (auditoria 06/10/2026, A7-3).
        has_work = bool((totals.get(m["id"]) or {}).get("operations"))
        if not (has_load or has_calendar or has_work):
            continue
        lb = late_before.get(m["id"]) or _empty_cell()
        lb_hours = lb[PLAN] + lb[DUE] + lb[SUGGESTED]
        nd = no_date.get(m["id"]) or _empty_cell()
        nd_hours = nd[PLAN] + nd[DUE] + nd[SUGGESTED]
        # Nunca propor tirar turnos a uma máquina com trabalho atrasado ou sem prazo (07/10/2026).
        can_reduce = not (lb["operations"] or nd["operations"])
        out = []
        for index, (y, w) in enumerate(weeks):
            d = cal.get((m["id"], y, w))
            cell = cells.get((m["id"], y, w)) or _empty_cell()
            full = shifts.week_hours(d) if d else 0.0
            capacity = shifts.week_hours(d, after=now if (y, w) == current else None) if d else 0.0
            base, days = shifts.decode(d, settings["template"]) if d else ({}, {})
            n = max([base.get(str(x), 0) for x in settings["workdays"]] or [0])
            monday = date.fromisocalendar(y, w, 1)
            workdays = [monday + timedelta(days=x - 1) for x in settings["workdays"]]
            open_days = [x for x in workdays if x.isoformat() not in set(settings["holidays"]) and (x >= today if (y, w) == current else True)]
            load = cell[PLAN] + cell[DUE] + cell[SUGGESTED]
            # Na semana atual a recomendação conta o atrasado + a carga da semana contra as horas que faltam.
            # Mais à frente (index >= REDUCE_WEEKS) a carga ainda está a chegar: mostrar a folga, sem propor cortar.
            need = load + (lb_hours if index == 0 else 0.0)
            advice = (recommend(need, capacity, n, settings, workdays=len(open_days), can_reduce=can_reduce and index < REDUCE_WEEKS)
                      if d else {"delta": 0, "text": "Sem calendário"})
            balance = capacity - need
            # A cor bate com o que a célula mostra («carga / capacidade da semana inteira»): o atrasado tem a sua
            # coluna e não pinta a semana atual; só a recomendação o conta (revisão 07/10/2026).
            room = full - load
            status = "falta" if room < -0.05 else "apertado" if full and room < 0.15 * full else "folga"
            extra = src["actual"].get((m["id"], y, w)) or {}
            out.append({"year": y, "week": w, "monday": monday, "shifts": n, "manual": bool((d or {}).get("manual")),
                        "day_changes": len(days), "capacity": round(capacity, 1), "full_capacity": round(full, 1), "plan": round(cell[PLAN], 1),
                        "due": round(cell[DUE], 1), "suggested": round(cell[SUGGESTED], 1), "late": round(cell["late"], 1),
                        "unknown": cell["unknown"], "operations": cell["operations"], "load": round(load, 1),
                        "balance": round(balance, 1), "status": status if d else "sem_calendario", "advice": advice,
                        "excel_hours": round(cell["excel"], 1), "excel_unknown": cell["excel_unknown"],
                        "actual_hours": extra.get("actual_hours") if (y, w) == current else None,
                        "excel_calendar_hours": extra.get("excel_calendar_hours"),
                        "days": [{"date": monday + timedelta(days=i), "shifts": _day_shifts(base, days, settings, monday + timedelta(days=i))}
                                 for i in range(7)] if d else []})
        after = (totals.get(m["id"]) or {}).get("after", 0.0)
        rows.append({"id": m["id"], "name": m["name"], "code": m["code"], "process": m["process"], "default_shifts": m["default_shifts"],
                     "has_calendar": has_calendar, "weeks": out,
                     "no_date": {"hours": round(nd_hours, 1), "unknown": nd["unknown"], "operations": nd["operations"]},
                     "late_before": {"hours": round(lb_hours, 1), "unknown": lb["unknown"], "operations": lb["operations"]},
                     "after": round(after, 1)})
    names = {rid: (r.get("name") or rid) for rid, r in (occ.get("resources") or {}).items()}
    recent = [(today - timedelta(weeks=i)).isocalendar()[:2] for i in range(4, 0, -1)]  # 4 semanas completas antes desta
    machine_totals = []
    per_shift = shifts.shift_hours(settings["template"])
    for m in machines:
        t = totals.get(m["id"]) or _empty_total()
        # Capacidade de uma semana normal (turnos padrão × horas do turno × dias de trabalho): «Semanas de trabalho».
        normal = sum(per_shift[:int(m.get("default_shifts") or 0)]) * len(settings["workdays"])
        machine_totals.append({"id": m["id"], "name": m["name"], "process": m["process"], **_round_total(t),
                               "week_capacity": round(normal, 1),
                               "actual_recent": [{"year": y, "week": w, "hours": (src["actual"].get((m["id"], y, w)) or {}).get("actual_hours")} for y, w in recent]})
    if totals.get(None):
        machine_totals.append({"id": None, "name": "Sem máquina", "process": None, **_round_total(totals[None]), "actual_recent": []})
    other = [{"id": rid, "name": names.get(rid) or rid, "operations": e["operations"], "hours": round(e["hours"], 1), "unknown": e["unknown"]}
             for rid, e in sorted(elsewhere.items(), key=lambda x: -x[1]["hours"])]
    return needs.serial({"sector": sector, "today": today, "weeks": [{"year": y, "week": w, "monday": date.fromisocalendar(y, w, 1)} for y, w in weeks],
                         "machines": rows, "totals": machine_totals, "elsewhere": {"operations": sum(o["operations"] for o in other), "hours": round(sum(o["hours"] for o in other), 1), "machines": other}, "settings": {k: settings[k] for k in ("template", "workdays", "holidays")},
                         "shift_hours": shifts.shift_hours(settings["template"]), "stale": bool(occ.get("stale")),
                         "rules": __doc__.split("\n\n", 1)[1].strip()})


def _round_total(t: dict) -> dict:
    return {k: round(v, 1) if isinstance(v, float) else v for k, v in t.items()}


def _day_shifts(base: dict, days: dict, settings: dict, day: date) -> int:
    iso = day.isoformat()
    if iso in days:
        return int(days[iso])
    if iso in set(settings["holidays"]):
        return 0
    return int(base.get(str(day.isoweekday()), 0))


def cell(sector: str, machine: str, year: int, week: int, *, today: date | None = None) -> dict:
    """O que está atrás de uma célula: uma linha por OF (horas, horas segundo o Excel, peso, peças, metros, prazo)."""
    from . import load_sources
    planning.check_area(sector)
    today = today or _today()
    weeks = week_list(today)
    horizon, current = set(weeks), weeks[0]
    data, planned, occ = _context(sector, today)
    with planning.connect(readonly=True) as c:
        src = load_sources.context(c, sector)
    lines = {x["key"]: x for x in data["lines"]}
    target = (int(year), int(week))
    groups = {}
    summary = {"plan_principal": 0.0, "excel_hours": 0.0, "excel_unknown": 0, "weight_kg": 0.0}
    for f in _cell_facts(occ, planned, current, horizon, machine, target, today):
        kind, late = f["_kind"], f["_late"]
        excel, weight, applies = load_sources.fact_values(f, src["lines"])
        g = groups.setdefault(f["of"], {"of": f["of"], "customer": f.get("customer"), "work": f.get("work"), "hours": 0.0, "unknown": 0,
                                        "pieces": 0.0, "metres": 0.0, "operations": 0, "references": set(), "kinds": set(),
                                        "priority_day": None, "late_days": 0, "excel_hours": 0.0, "excel_unknown": 0, "weight_kg": 0.0})
        if applies:
            if excel is None:
                g["excel_unknown"] += 1
                summary["excel_unknown"] += 1
            else:
                g["excel_hours"] += excel
                summary["excel_hours"] += excel
        if weight is not None:
            g["weight_kg"] += weight
            summary["weight_kg"] += weight
        if f.get("phase", "principal") == "principal" and f.get("load_hours") is not None:
            summary["plan_principal"] += f["load_hours"]
        g["operations"] += 1
        g["references"].add(f.get("reference"))
        g["kinds"].add(kind)
        if f.get("load_hours") is None:
            g["unknown"] += 1
        else:
            g["hours"] += f["load_hours"]
        line = lines.get(f.get("line_key"))
        if f.get("phase") == "principal" and line:
            g["pieces"] += line["pieces"] or 0
            g["metres"] += line["metres"] or 0
        day = f.get("priority_day")
        if day and (g["priority_day"] is None or str(day) < str(g["priority_day"])):
            g["priority_day"] = day
        g["late_days"] = max(g["late_days"], f.get("late_days") or 0)
    rows = sorted(groups.values(), key=lambda g: (-g["late_days"], str(g["priority_day"] or "9999"), g["of"]))
    for g in rows:
        g["references"] = len(g["references"])
        g["kinds"] = sorted(g["kinds"])
        g["hours"] = round(g["hours"], 2)
        g["metres"] = round(g["metres"], 1)
        g["pieces"] = round(g["pieces"])
        g["excel_hours"] = round(g["excel_hours"], 2)
        g["weight_kg"] = round(g["weight_kg"], 1)
    extra = src["actual"].get((machine, int(year), int(week))) or {}
    return needs.serial({"sector": sector, "machine": machine, "year": int(year), "week": int(week), "orders": rows,
                         "hours": round(sum(g["hours"] for g in rows), 2), "unknown": sum(g["unknown"] for g in rows),
                         **{k: round(v, 2) if isinstance(v, float) else v for k, v in summary.items()},
                         "actual_hours": extra.get("actual_hours"), "excel_calendar_hours": extra.get("excel_calendar_hours")})


def _cell_facts(occ, planned, current, horizon, machine, target, today=None):
    """Ocorrências de uma célula (máquina × semana), com o tipo (no plano / a vencer / sugerida) e o atraso."""
    for f in occ["facts"]:
        if f.get("planning_resource_id") != machine:
            continue
        found = classify(f, planned, current, horizon, today)
        if not found or found[1] != target:
            continue
        yield {**f, "_kind": found[0], "_late": found[2]}


def estimate_calculation(fact: dict) -> dict | None:
    """Cálculo das horas estimadas da Carteira (estimates.estimate) para o «Ver cálculo» (auditoria 06/10, CARGA-OPS-01).

    Quando as horas da linha são estimadas, a prova do motor de capacidade não as explica: a conta mostrada tem de
    ser a da estimativa — MTG3 metros do saldo ÷ velocidade do Excel; MTG2 saldo × área unitária ÷ taxa mm²/h.
    A taxa é a que deu estas horas (volume ÷ horas); a base (mediana, perfil, linhas) vem da origem guardada.
    """
    hours, remaining = fact.get("load_hours"), fact.get("remaining")
    if fact.get("load_basis") != "estimada" or not hours or remaining is None:
        return None
    if fact.get("area") == "cantoneiras":
        length = fact.get("length_mm")
        if not length:
            return None
        volume, unit, rate_unit = remaining * length / 1000, "m", "m/h"
        formula = "metros em falta (peças em falta × comprimento ÷ 1000) ÷ velocidade do Excel"
    else:
        section = fact.get("section_unit")
        if not section:
            return None
        volume, unit, rate_unit = remaining * section, "mm²", "mm²/h"
        formula = "peças em falta × área de corte unitária ÷ taxa mm²/h do Excel (sem fator ×3)"
    return {"formula": formula, "remaining": remaining, "length_mm": fact.get("length_mm"), "section_unit": fact.get("section_unit"),
            "volume": round(volume, 3), "volume_unit": unit, "rate": round(volume / hours, 3), "rate_unit": rate_unit,
            "hours": round(hours, 4), "basis": fact.get("load_origin")}


def operations(sector: str, machine: str, year: int, week: int, of: str, *, today: date | None = None) -> dict:
    """Operações de uma OF numa célula, com o cálculo de cada uma (taxa, fórmula, vigência, Excel)."""
    from . import load_sources
    from .occurrences import _estimate_name
    planning.check_area(sector)
    today = today or _today()
    weeks = week_list(today)
    data, planned, occ = _context(sector, today)
    facts = [f for f in _cell_facts(occ, planned, weeks[0], set(weeks), machine, (int(year), int(week)), today) if f["of"] == of]
    with planning.connect(readonly=True) as c:
        src = load_sources.context(c, sector)
        proofs = load_sources.proofs(c, sector, sorted({f["line_key"] for f in facts if f.get("line_key")}))
    KIND = {PLAN: "no plano", DUE: "a vencer", SUGGESTED: "a vencer, máquina sugerida"}
    out = []
    for f in sorted(facts, key=lambda x: (str(x.get("reference")), x.get("occurrence") or 0)):
        excel, weight, applies = load_sources.fact_values(f, src["lines"])
        name = _estimate_name(f.get("operation"), sector, f.get("phase") == "principal")
        out.append({"reference": f.get("reference"), "operation": f.get("operation_label") or f.get("operation"), "phase": f.get("phase"),
                    "kind": KIND[f["_kind"]], "late": f["_late"], "remaining": f.get("remaining"), "length_mm": f.get("length_mm"),
                    "profile": f.get("profile"), "load_hours": f.get("load_hours"), "hours_origin": f.get("hours_origin"),
                    # Origem das horas previstas (documental ou estimada pelo Excel), para comparar com o Gantt (C3-F5).
                    "load_basis": f.get("load_basis"), "load_origin": f.get("load_origin"),
                    "hours_reason": f.get("hours_reason"), "priority_day": f.get("priority_day"),
                    "priority_source": (f.get("priority") or {}).get("priority_source"),
                    "excel_hours": excel if applies else None, "weight_kg": weight,
                    # Horas estimadas: a conta que as deu; a prova do motor fica marcada como não usada (CARGA-OPS-01).
                    "estimate": estimate_calculation(f), "proof_used": f.get("load_basis") != "estimada",
                    "proof": proofs.get((f.get("line_key"), name))})
    return needs.serial({"sector": sector, "machine": machine, "year": int(year), "week": int(week), "of": of, "operations": out})


def production(sector: str, machine: str, year: int, week: int, page: int = 1) -> dict:
    """Produção registada (folhas OCR validadas) numa máquina e semana ISO, e as horas reais declaradas."""
    from ..raw import query
    from . import load_sources
    from .occurrences import resources_context
    planning.check_area(sector)
    monday = date.fromisocalendar(int(year), int(week), 1)
    with planning.connect(readonly=True) as c:
        codes, by_id, aliases, _, _ = resources_context(c)
        resource = by_id.get(machine) or {}
        names = {resource.get("name")} | {name for (area, name), code in aliases.items() if (codes.get(code) or {}).get("id") == machine}
        names = sorted(n for n in names if n)
        src = load_sources.context(c, sector)
    if not names:
        raise planning.PlanningError("Máquina desconhecida neste setor.", 404)
    listing = query.listing({"area": sector, "dataset": "production", "page": int(page), "page_size": 50,
                             "filters": [{"field": "machine", "op": "in", "values": names},
                                         {"field": "production_date", "op": "between", "min": monday.isoformat(), "max": (monday + timedelta(days=6)).isoformat()}],
                             "order": [{"field": "production_date", "direction": "desc"}]})
    extra = src["actual"].get((machine, int(year), int(week))) or {}
    rows = listing.get("rows", [])
    sheet_hours = _sheet_hours(sector, monday, rows)
    return needs.serial({"sector": sector, "machine": machine, "year": int(year), "week": int(week), "names": names,
                         "rows": rows, "total": listing.get("total", 0), "page": int(page),
                         "actual_hours": extra.get("actual_hours"), "sheet_hours": sheet_hours})


def _sheet_hours(sector: str, monday: date, rows: list[dict]) -> dict[str, float | None]:
    """Horas declaradas de cada folha destas linhas de produção: {sheet_uid: horas} (auditoria 06/10, CARGA-PROD-04).

    As horas são da folha, não da linha (a projeção deixa hours_worked da linha a vazio de propósito): vêm do
    conjunto production_hours, pela folha, e o ecrã mostra-as uma vez por folha. Folha sem horas → None.
    """
    from ..raw import query
    uids = {r.get("sheet_uid") for r in rows if r.get("sheet_uid")}
    if not uids:
        return {}
    found = query.listing({"area": sector, "dataset": "production_hours", "page": 1, "page_size": 500,
                           "filters": [{"field": "production_date", "op": "between", "min": monday.isoformat(),
                                        "max": (monday + timedelta(days=6)).isoformat()}]})
    hours = {r.get("sheet_uid") or r.get("key"): (r.get("values") or {}).get("hours_worked") for r in found.get("rows", [])}
    return {uid: hours.get(uid) for uid in sorted(uids)}
