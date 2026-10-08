"""Carga e turnos por máquina e semana (pedido do Luís, 06/10/2026).

Para cada máquina e semana ISO (a atual e as 12 seguintes):
- capacidade = horas do calendário dessa semana (na semana atual, só as que faltam a partir de agora;
  a semana inteira fica em «full_capacity»);
- no plano = horas das linhas «Planeado» (Planear + máquina) na sua máquina, na semana do prazo;
- a vencer = trabalho aberto não planeado com prazo nessa semana: na máquina efetiva («com máquina») ou
  na sugerida (à parte);
- atrasado = prazo antes da semana atual: fica à parte, por máquina («late_before», separado em no plano, a vencer
  e sugerida desde 08/10), e não entra na carga da semana atual (07/10/2026); o que tem prazo entre segunda e
  ontem fica na semana atual, marcado como atrasado (a mesma regra da Carteira e do painel Máquinas);
- linhas excluídas na Carteira não contam (como na lista vermelha do quadro);
- linha planeada em parte (08/10): cada ocorrência divide-se na parte planeada («no plano») e no resto («a vencer»),
  pela regra única decisions.planned_open (a operação principal leva min(parte, saldo); as seguintes as peças já
  cortadas que lhes faltam mais a parte). Parte + resto = saldo; a operação conta uma vez;
- máquinas do setor sem calendário que têm trabalho aparecem com capacidade 0 e «Sem calendário»;
- recomendação de turnos (shifts.advise): na semana atual, atrasado + carga da semana contra as horas que
  faltam, e o texto diz «inclui N h atrasadas» (08/10); nas outras, a carga da semana. Tirar turnos só nas 3
  primeiras semanas (mais à frente a carga ainda está a chegar) e nunca numa máquina com trabalho atrasado ou
  sem prazo;
- cor da célula (status): carga da semana contra a capacidade da semana inteira, os mesmos números que a
  célula mostra; o atrasado não pinta a semana atual (tem a sua coluna);
- ao lado, o que as antigas páginas Capacidades/Disponibilidade mostravam (load_sources.py): horas segundo o
  Excel, horas reais declaradas, calendário do Excel; e totais por máquina (separador Máquinas);
- peso = peso unitário da linha da Carteira × saldo, como na Carteira (08/10); sem peso conta à parte, nunca 0 kg;
- máquinas de um posto (ex.: Fita pav.1 com o Doall e a Thomas) continuam em linhas próprias, com a nota da
  capacidade conjunta do posto (capacity.counted, 08/10);
- 2.ª operação das cantoneiras (08/10, second_operation.py): as máquinas da 2.ª operação (Saca bocados, Plasma
  manual, Fresadora, Prensa) saem das linhas e as operações seguintes saem das células, dos totais e de «noutro
  setor»; ficam só contadas à parte («N operações de 2.ª operação fora do plano»). Na MTG2 nada muda;
- os KPIs da semana da Carteira leem estas mesmas células (week_slice, 08/10): os números são iguais por construção.
Prazo pela política do setor (MTG3 Data Corte; MTG2 Picking, depois Data Corte). As horas são as mesmas da
Carteira (occurrences + estimates); horas desconhecidas nunca contam como zero — são contadas à parte.
"""
from __future__ import annotations

import re
import threading
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from .. import planning, planning_needs as needs
from . import shifts

WEEKS = 13
REDUCE_WEEKS = 3  # só se propõe tirar turnos na semana atual e nas duas seguintes
PLAN, DUE, SUGGESTED = "plan", "due", "suggested"


def _week_of(day) -> tuple[int, int] | None:
    """Semana ISO do prazo pela mesma função da linha da Carteira (portfolio.iso_week, P4 08/10): a semana de uma
    ocorrência principal é a da sua linha no filtro Prazo."""
    from .portfolio import iso_week
    if not day:
        return None
    code = iso_week(day if isinstance(day, date) else date.fromisoformat(str(day)[:10]))
    return int(code[:4]), int(code[6:])


def _today() -> date:
    from .week import lisbon_today
    return lisbon_today()


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
    planned = fact.get("line_key") in planned_keys and fact.get("machine_basis") == "atribuída" and fact.get("_part") != "rest"
    kind = PLAN if planned else DUE if fact.get("machine_basis") == "atribuída" else SUGGESTED
    day = fact.get("priority_day")
    week = _week_of(day)
    if week is None:
        return kind, "sem_data", False
    late = (str(day)[:10] < today.isoformat()) if today else week < current
    if week < current:
        return kind, current, True
    return (kind, week, late) if week in horizon else (kind, "depois", late)


def split_facts(facts, planned, lines) -> list[dict]:
    """As ocorrências com as das linhas planeadas em parte divididas em parte planeada e resto (08/10).

    `planned` = load._context()[1]: {chave: peças planeadas por fazer ou None}; None (ou um conjunto, contrato
    antigo) = a linha inteira, sem divisão. A parte leva `_part: "plan"`; o resto `_part: "rest"` (fica «a vencer»)
    e, quando a mesma operação também tem parte, `_extra` (não conta outra vez a operação nem os desconhecidos).
    """
    if not isinstance(planned, dict) or not any(v is not None for v in planned.values()):
        return facts
    from .portfolio import split_fact
    pieces = {x["key"]: x["pieces"] for x in lines}
    out = []
    for f in facts:
        part = planned.get(f.get("line_key"))
        if part is None or f.get("machine_basis") != "atribuída":
            out.append(f)
            continue
        out.extend(x for x in split_fact(f, part, pieces.get(f.get("line_key"))) if x is not None)
    return out


def _empty_cell():
    return {PLAN: 0.0, DUE: 0.0, SUGGESTED: 0.0, "late": 0.0, "unknown": 0, "operations": 0, "excel": 0.0, "excel_unknown": 0,
            "metres": 0.0, "metres_unknown": 0, "unknown_" + PLAN: 0, "unknown_" + DUE: 0, "unknown_" + SUGGESTED: 0}


def _empty_total():
    return {"operations": 0, "unknown": 0, "pieces": 0.0, "pieces_unknown": 0, "metres": 0.0, "metres_unknown": 0, "area_mm2": 0.0,
            "weight_kg": 0.0, "weight_unknown": 0,
            "load": 0.0, "late": 0.0, "late_before": 0.0, "after": 0.0, "no_date": 0.0, "excel_hours": 0.0, "excel_unknown": 0}


def _before_week(fact: dict, monday: date) -> bool:
    """Prazo antes da segunda-feira da semana atual: atrasado à parte (coluna Atrasado), fora da semana atual."""
    day = fact.get("priority_day")
    return bool(day) and str(day)[:10] < monday.isoformat()


def advice_text(advice: dict, missing: float, shifts_now: int | None = None, late: float = 0.0) -> dict:
    """Texto simples da recomendação: «faltam 52 h · +1 turno» / «sobram 40 h · −1 turno» (07/10/2026).

    Na semana atual a recomendação conta o atrasado, que a cor não conta (decisão de 07/10): o texto diz
    «inclui N h atrasadas», para não parecer que contradiz a cor (08/10).
    """
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
    if late > 0.05:
        text += f" · inclui {late:.0f} h atrasadas"
    return {**advice, "text": text}


def recommend(load_hours: float, capacity: float, n: int, settings: dict, *, workdays: int, can_reduce: bool,
              late: float = 0.0) -> dict:
    """Recomendação de turnos (shifts.advise) com o texto simples; −1 só quando `can_reduce`.

    `late`: horas atrasadas já incluídas em `load_hours` (só na semana atual), ditas no texto."""
    advice = shifts.advise(load_hours, capacity, n, settings, workdays_in_week=workdays)
    missing = load_hours - capacity
    if advice["delta"] < 0 and not can_reduce:
        advice = {"delta": 0}
    return advice_text(advice, missing, n, late)


def _add_total(t: dict, f: dict, week, late: bool, excel, weight, applies: bool, before: bool = False) -> None:
    extra = bool(f.get("_extra"))  # resto de uma operação planeada em parte: a operação e os desconhecidos já contaram
    t["operations"] += not extra
    if f.get("phase", "principal") == "principal":
        # Desconhecido ≠ 0 (F09): saldo ou comprimento em falta conta-se à parte, como na Carteira (achado C-carga-totais-zero).
        for name in ("pieces", "metres"):
            if f.get(name) is None:
                t[name + "_unknown"] += not extra
            else:
                t[name] += f[name]
        if f.get("remaining") is not None and f.get("section_unit"):
            t["area_mm2"] += f["remaining"] * f["section_unit"]
        if weight is None:
            t["weight_unknown"] += not extra
        else:
            t["weight_kg"] += weight
    if applies:
        if excel is None:
            t["excel_unknown"] += not extra
        else:
            t["excel_hours"] += excel
    hours = f.get("load_hours")
    if hours is None:
        t["unknown"] += not extra
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


def weights_of(lines: list[dict]) -> dict:
    """Peso unitário de cada linha da Carteira (values.weight_unit), pela chave da linha."""
    return {x["key"]: x.get("weight_unit") for x in lines if x.get("key")}


def fact_weight(fact: dict, weights: dict) -> float | None:
    """Peso por cortar de uma ocorrência (F21, 08/10): o mesmo da Carteira, peso unitário da linha × saldo.

    Uma só fonte para os kg da Carteira e da Carga (antes a Carga lia o peso de outra geração, capacity_items).
    Só a operação principal tem peso; sem peso unitário ou sem saldo → None, contado à parte.
    """
    if fact.get("phase", "principal") != "principal":
        return None
    unit, remaining = weights.get(fact.get("line_key")), fact.get("remaining")
    return unit * remaining if unit is not None and remaining is not None else None


def shared_posts(rows: list[dict], posts: dict, names: dict) -> None:
    """Nota das máquinas de um posto (F18, 08/10): «partilha o posto … com …: juntas têm X h».

    O Fita pav.1 é um posto que contém o Doall e a Thomas: juntos têm uma só capacidade. As linhas continuam por
    máquina; cada uma do posto (o posto incluído) recebe `shared` com a capacidade conjunta de cada semana, contada
    por capacity.counted() (o posto com calendário substitui as máquinas; sem ele, somam-se as máquinas).
    """
    from .capacity import counted
    by_id = {r["id"]: r for r in rows}
    for post, members in posts.items():
        group = [post, *members]
        shown = [rid for rid in group if rid in by_id]
        if not shown or len(group) < 2:
            continue
        resources = {rid: {"id": rid} for rid in group}
        shape = {"roles": {m: "maquina" for m in members}, "members": {post: list(members)}}
        weeks = []
        for i in range(max(len(by_id[rid]["weeks"]) for rid in shown)):
            caps = {rid: (by_id[rid]["weeks"][i]["full_capacity"] if rid in by_id and by_id[rid]["has_calendar"]
                          and by_id[rid]["weeks"][i]["status"] != "sem_calendario" else None) for rid in group}
            chosen = counted(resources, caps, shape=shape)
            known = [caps[rid] for rid in chosen if caps[rid] is not None]
            weeks.append(round(sum(known), 1) if known else None)
        for rid in shown:
            others = [names.get(x) or (by_id.get(x) or {}).get("name") or x for x in group if x not in (rid, post)]
            by_id[rid]["shared"] = {"post": names.get(post) or (by_id.get(post) or {}).get("name") or post, "is_post": rid == post,
                                    "with": others, "hours": weeks[0] if weeks else None, "weeks": weeks}


def _context(sector: str, today: date | None = None):
    """Linhas, decisões e ocorrências da Carga (só leituras: as linhas e as ocorrências podem ser as anteriores
    enquanto se refazem em segundo plano; as decisões são sempre as atuais).

    As ocorrências devolvidas levam `decisions`, o digest das decisões atuais (chave da memória de _aggregate): as
    ocorrências anteriores podem vir com o carimbo antigo enquanto se refazem, o plano e as exclusões não."""
    from . import occurrences, portfolio, scope, selection
    data = portfolio.current(sector, allow_stale=True)
    decisions = selection.current(sector)
    # {chave: peças planeadas por fazer ou None = a linha inteira} (quantidade parcial, 08/10); `in` continua a valer.
    planned = portfolio.planned_parts(data["lines"], decisions)
    occ = occurrences.load(sector, allow_stale=True)
    # Linha excluída na Carteira não é trabalho a planear: não conta na Carga, como na lista vermelha (A8-5).
    excluded = {x["key"] for x in data["lines"] if portfolio.decision_of(x, decisions) == "excluded"}
    facts = [f for f in occ["facts"] if f.get("line_key") not in excluded] if excluded else occ["facts"]
    return data, planned, {**occ, "facts": facts, "decisions": scope.digest(decisions)}


# Memória curta das células (P4, 08/10): a Carga e os KPIs da semana da Carteira leem as mesmas células, por isso
# os números são iguais por construção. Uma entrada por setor; a chave segue o dia de Lisboa, as ocorrências, a
# geração das linhas, as decisões, os calendários/recursos e as Definições do setor. O resto (horas reais
# declaradas, catálogo) fica no máximo MEMORY_SECONDS atrasado. A capacidade da semana atual (que depende da hora)
# calcula-se sempre fora da memória.
MEMORY_SECONDS = 120
_memory: dict[str, tuple] = {}
_memory_lock = threading.Lock()


def _calendar_stamp(c) -> tuple:
    row = c.execute("SELECT count(*) n, max(updated_at) m FROM planning_mtg.raw_objects WHERE kind = ANY(%s) AND NOT archived",
                    (["calendar", "resource"],)).fetchone()
    return row["n"], row["m"]


def _remembered(key: tuple):
    with _memory_lock:
        found = _memory.get(key[0])
        if found and found[0] == key and time.monotonic() - found[1] < MEMORY_SECONDS:
            return found[2]
    return None


def _remember(key: tuple, value: dict) -> None:
    with _memory_lock:
        _memory[key[0]] = (key, time.monotonic(), value)


def forget() -> None:
    with _memory_lock:
        _memory.clear()


def status_of(load_hours: float, full: float) -> str:
    """Cor da célula da Carga: carga da semana contra a capacidade da semana inteira, os números que a célula mostra
    (revisão 07/10/2026); a mesma regra nos KPIs da semana da Carteira."""
    room = full - load_hours
    return "falta" if room < -0.05 else "apertado" if full and room < 0.15 * full else "folga"


def _parked(fact: dict) -> bool:
    return bool((fact.get("priority") or {}).get("parked"))


def _add_cell(target: dict, f: dict, kind: str, late: bool, excel, applies: bool) -> None:
    extra = bool(f.get("_extra"))  # resto de uma operação planeada em parte: não conta outra vez (08/10)
    target["operations"] += not extra
    if applies:
        if excel is None:
            target["excel_unknown"] += not extra
        else:
            target["excel"] += excel
    if f.get("phase", "principal") == "principal":  # metros só na operação principal, como na Carteira
        if f.get("metres") is None:
            target["metres_unknown"] += not extra
        else:
            target["metres"] += f["metres"]
    if f.get("load_hours") is None:
        target["unknown"] += not extra
        target["unknown_" + kind] += not extra
        return
    target[kind] += f["load_hours"]
    if late:
        target["late"] += f["load_hours"]


def _merge_cell(target: dict, cell: dict | None) -> dict:
    for k, v in (cell or {}).items():
        target[k] += v
    return target


def _aggregate(sector: str, today: date | None = None, *, memo: bool = False) -> dict:
    """As células da Carga (máquina × semana) e o resto do que a Carga e os KPIs da semana leem.

    - cells[(máquina, ano, semana)]: as 13 semanas (a atual sem o atrasado); later: semanas depois das 13;
    - past[(máquina, ano, semana)]: o atrasado de cada semana passada; a soma por máquina é late_before;
    - undated/parked: sem prazo e estacionadas no Excel (no_date = as duas, como antes);
    - cada célula tem horas por tipo (no plano / a vencer / sugerida), as desconhecidas por tipo, metros (só a
      operação principal) e as horas segundo o Excel;
    - 2.ª operação das cantoneiras (second_operation.operation): fora das células, dos totais e de «noutro setor»,
      só contada em `second_operation`; as máquinas da 2.ª operação saem das linhas (MTG2 igual).
    `memo`: usa a memória curta (pedidos sem dia nem hora fixos); os testes passam o dia e calculam sempre.
    """
    from . import load_sources, second_operation, settings as sector_settings
    planning.check_area(sector)
    today = today or _today()
    weeks = week_list(today)
    horizon = set(weeks)
    current = weeks[0]
    data, planned, occ = _context(sector, today)
    with planning.connect(readonly=True) as c:
        settings = sector_settings.read(c, sector)
        key = None
        if memo:
            key = (sector, today, occ.get("stamp"), data.get("generation"), occ.get("decisions"), _calendar_stamp(c),
                   sector_settings.load_stamp(settings), bool(occ.get("stale") or data.get("stale")))
            found = _remembered(key)
            if found is not None:
                return found
        machines = [m for m in sector_settings.machine_rows(c, sector) if not second_operation.machine(sector, m.get("process"))]
        ids = [m["id"] for m in machines]
        calendars = c.execute("SELECT definition FROM planning_mtg.raw_objects WHERE kind='calendar' AND NOT archived "
                              "AND definition->>'resource_id' = ANY(%s)", (ids,)).fetchall()
        src = load_sources.context(c, sector)
    cal = {(str(r["definition"]["resource_id"]), int(r["definition"]["year"]), int(r["definition"]["week"])): r["definition"] for r in calendars}
    cells, later, past = defaultdict(_empty_cell), defaultdict(_empty_cell), defaultdict(_empty_cell)
    undated, parked = defaultdict(_empty_cell), defaultdict(_empty_cell)
    monday_now = date.fromisocalendar(*current, 1)
    totals = defaultdict(_empty_total)
    own = set(ids)
    elsewhere = defaultdict(lambda: {"operations": 0, "hours": 0.0, "unknown": 0})
    elsewhere_work = _empty_total()  # peças, metros e kg dessas operações: para o fecho com a Carteira (08/10)
    second = []
    weights = weights_of(data["lines"])
    for f in split_facts(occ["facts"], planned, data["lines"]):
        if second_operation.operation(sector, f):  # 2.ª operação das cantoneiras: fora do plano (08/10)
            second.append(f)
            continue
        found = classify(f, planned, current, horizon, today)
        excel, _, applies = load_sources.fact_values(f, src["lines"])
        weight = fact_weight(f, weights)
        if not found:  # sem máquina: só entra nos totais («Sem máquina»)
            _add_total(totals[None], f, "sem_data" if not f.get("priority_day") else None, False, excel, weight, applies)
            continue
        rid = f["planning_resource_id"]
        if rid not in own:  # trabalho do setor numa máquina de outro setor: nota à parte
            e = elsewhere[rid]
            e["operations"] += not f.get("_extra")
            e["hours"] += f.get("load_hours") or 0
            e["unknown"] += f.get("load_hours") is None and not f.get("_extra")
            _add_total(elsewhere_work, f, None, False, excel, weight, applies)
            continue
        kind, week, late = found
        before = week == current and _before_week(f, monday_now)
        _add_total(totals[rid], f, week, late, excel, weight, applies, before)
        if week == "sem_data":
            target = (parked if _parked(f) else undated)[rid]
        elif week == "depois":
            target = later[(rid, *_week_of(f["priority_day"]))]
        elif before:
            target = past[(rid, *_week_of(f["priority_day"]))]
        else:
            target = cells[(rid, *week)]
        _add_cell(target, f, kind, late, excel, applies)
    late_before, no_date = defaultdict(_empty_cell), defaultdict(_empty_cell)
    for (rid, _, _), cell in past.items():
        _merge_cell(late_before[rid], cell)
    for part in (undated, parked):
        for rid, cell in part.items():
            _merge_cell(no_date[rid], cell)
    result = {"sector": sector, "today": today, "weeks": weeks, "current": current, "machines": machines, "settings": settings,
              "cal": cal, "src": src, "cells": dict(cells), "later": dict(later), "past": dict(past), "late_before": dict(late_before),
              "undated": dict(undated), "parked": dict(parked), "no_date": dict(no_date), "totals": dict(totals),
              "elsewhere": dict(elsewhere), "elsewhere_work": elsewhere_work, "second_operation": second_operation.summary(second),
              "names": {rid: (r.get("name") or rid) for rid, r in (occ.get("resources") or {}).items()},
              "stale": bool(occ.get("stale") or data.get("stale"))}
    if key is not None:
        _remember(key, result)
    return result


def overview(sector: str, *, today: date | None = None, now: datetime | None = None) -> dict:
    """A grelha da Carga, formatada a partir de _aggregate (a mesma memória que os KPIs da semana da Carteira)."""
    from . import drive_notice, second_operation
    agg = _aggregate(sector, today, memo=today is None and now is None)
    today, settings, src, cal = agg["today"], agg["settings"], agg["src"], agg["cal"]
    now = now or datetime.now(timezone.utc)
    weeks, current, machines = agg["weeks"], agg["current"], agg["machines"]
    cells, totals, late_before, no_date = agg["cells"], agg["totals"], agg["late_before"], agg["no_date"]
    rows = []
    for m in machines:
        has_load = any(cells.get((m["id"], y, w)) for y, w in weeks)
        # Semanas gravadas a 0 turnos não são calendário: a máquina continua «sem calendário» (07/10/2026).
        has_calendar = any(shifts.week_hours(cal[(m["id"], y, w)]) > 0 for y, w in weeks if (m["id"], y, w) in cal)
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
            advice = (recommend(need, capacity, n, settings, workdays=len(open_days), can_reduce=can_reduce and index < REDUCE_WEEKS,
                                late=lb_hours if index == 0 else 0.0)
                      if d else {"delta": 0, "text": "Sem calendário"})
            balance = capacity - need
            # A cor bate com o que a célula mostra («carga / capacidade da semana inteira»): o atrasado tem a sua
            # coluna e não pinta a semana atual; só a recomendação o conta (revisão 07/10/2026).
            extra = src["actual"].get((m["id"], y, w)) or {}
            out.append({"year": y, "week": w, "monday": monday, "shifts": n, "manual": bool((d or {}).get("manual")),
                        "day_changes": len(days), "capacity": round(capacity, 1), "full_capacity": round(full, 1), "plan": round(cell[PLAN], 1),
                        "due": round(cell[DUE], 1), "suggested": round(cell[SUGGESTED], 1), "late": round(cell["late"], 1),
                        "unknown": cell["unknown"], "operations": cell["operations"], "load": round(load, 1),
                        "balance": round(balance, 1), "status": status_of(load, full) if d else "sem_calendario", "advice": advice,
                        "excel_hours": round(cell["excel"], 1), "excel_unknown": cell["excel_unknown"],
                        "actual_hours": extra.get("actual_hours") if (y, w) == current else None,
                        "excel_calendar_hours": extra.get("excel_calendar_hours"),
                        "days": [{"date": monday + timedelta(days=i), "shifts": _day_shifts(base, days, settings, monday + timedelta(days=i))}
                                 for i in range(7)] if d else []})
        after = (totals.get(m["id"]) or {}).get("after", 0.0)
        rows.append({"id": m["id"], "name": m["name"], "code": m["code"], "process": m["process"], "default_shifts": m["default_shifts"],
                     "has_calendar": has_calendar, "weeks": out,
                     "no_date": {"hours": round(nd_hours, 1), "unknown": nd["unknown"], "operations": nd["operations"]},
                     # Atrasado por tipo (F12, 08/10): no plano / a vencer / máquina sugerida, além do total.
                     "late_before": {"hours": round(lb_hours, 1), "unknown": lb["unknown"], "operations": lb["operations"],
                                     PLAN: round(lb[PLAN], 1), DUE: round(lb[DUE], 1), SUGGESTED: round(lb[SUGGESTED], 1)},
                     "after": round(after, 1)})
    names = agg["names"]
    shared_posts(rows, src.get("posts") or {}, {**names, **(src.get("names") or {})})
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
             for rid, e in sorted(agg["elsewhere"].items(), key=lambda x: -x[1]["hours"])]
    work = _round_total(agg["elsewhere_work"])
    second = agg["second_operation"]
    return needs.serial({"sector": sector, "today": today, "weeks": [{"year": y, "week": w, "monday": date.fromisocalendar(y, w, 1)} for y, w in weeks],
                         "machines": rows, "totals": machine_totals,
                         "elsewhere": {"operations": sum(o["operations"] for o in other), "hours": round(sum(o["hours"] for o in other), 1),
                                       "unknown": sum(o["unknown"] for o in other), "machines": other,
                                       **{k: work[k] for k in ("pieces", "pieces_unknown", "metres", "metres_unknown", "weight_kg", "weight_unknown")}},
                         # 2.ª operação das cantoneiras fora do plano (08/10): só a contagem, para uma linha discreta.
                         "second_operation": {**second, "text": second_operation.label(second)},
                         # Excel do setor no Drive mais recente do que o importado (F16, 08/10): uma linha de aviso.
                         "source_notice": drive_notice.text(sector),
                         "settings": {k: settings[k] for k in ("template", "workdays", "holidays")},
                         "shift_hours": shifts.shift_hours(settings["template"]), "stale": agg["stale"],
                         "rules": __doc__.split("\n\n", 1)[1].strip()})


_CODE = re.compile(r"^(\d{4})-W(\d{2})$")


def week_codes(codes) -> list[str]:
    """Códigos do filtro Prazo da Carteira (portfolio.week_code): «2026-W41», «sem», «estacionada». Semanas por ordem,
    depois «sem» e «estacionada»; repetidos uma vez. Outro valor → erro «Prazo inválido.»."""
    from .portfolio import NO_WEEK, PARKED_WEEK
    weeks, special = set(), set()
    for code in codes or []:
        found = _CODE.match(code) if isinstance(code, str) else None
        if found:
            try:
                date.fromisocalendar(int(found[1]), int(found[2]), 1)
            except ValueError:
                raise planning.PlanningError("Prazo inválido.") from None
            weeks.add(code)
        elif code in (NO_WEEK, PARKED_WEEK):
            special.add(code)
        else:
            raise planning.PlanningError("Prazo inválido.")
    return sorted(weeks) + [c for c in (NO_WEEK, PARKED_WEEK) if c in special]


def week_slice(sector: str, codes, *, today: date | None = None) -> dict:
    """Carga das semanas do filtro Prazo da Carteira, por máquina e por tipo, das mesmas células da Carga (P4, 08/10).

    Por máquina: load = no plano + a vencer + sugerida (na semana atual sem o atrasado, como a célula); capacidade =
    a da semana inteira (full_capacity, o número que a célula mostra), somada com várias semanas; cor pela mesma
    regra (status_of). Semanas passadas: as horas atrasadas dessa semana, sem capacidade (None, «—»); «sem» e
    «estacionada»: sem prazo e estacionadas, sem capacidade. Na semana atual, `late_before` = o atrasado de semanas
    anteriores (a coluna Atrasado). Os totais somam a capacidade sem contar a dobrar os postos (capacity.counted).
    """
    from .capacity import counted
    from .portfolio import NO_WEEK
    codes = week_codes(codes)
    agg = _aggregate(sector, today, memo=today is None)
    current, horizon = agg["current"], set(agg["weeks"])
    chosen = [(int(c[:4]), int(c[6:])) for c in codes if _CODE.match(c)]
    special = [c for c in codes if not _CODE.match(c)]
    machines, kinds = {}, {k: {"hours": 0.0, "unknown": 0} for k in (PLAN, DUE, SUGGESTED)}
    caps = {}
    for m in agg["machines"]:
        rid = m["id"]
        acc, full, with_calendar, timeless = _empty_cell(), 0.0, False, bool(special)
        # Calendário como na Carga (E2-07): semanas gravadas a 0 turnos não contam; sem nenhuma semana com horas no
        # horizonte, a máquina fica «sem calendário» e a capacidade não entra (nem troca as máquinas de um posto).
        has_calendar = any(shifts.week_hours(agg["cal"][(rid, y, w)]) > 0 for y, w in agg["weeks"] if (rid, y, w) in agg["cal"])
        for y, w in chosen:
            if (y, w) < current:
                # Com a semana atual escolhida, o atrasado das semanas passadas já vem em late_before (a coluna
                # Atrasado): não se soma à carga, para não contar duas vezes nem misturar com a célula (E2-06).
                if current not in chosen:
                    _merge_cell(acc, agg["past"].get((rid, y, w)))
                    timeless = True
                continue
            _merge_cell(acc, (agg["cells"] if (y, w) in horizon else agg["later"]).get((rid, y, w)))
            d = agg["cal"].get((rid, y, w))
            if d:
                with_calendar = True
                full += shifts.week_hours(d)
        for code in special:
            _merge_cell(acc, (agg["undated"] if code == NO_WEEK else agg["parked"]).get(rid))
        load = acc[PLAN] + acc[DUE] + acc[SUGGESTED]
        dated = any((y, w) >= current for y, w in chosen)
        status = None if not dated else "sem_calendario" if not (with_calendar and has_calendar) else None if timeless else status_of(load, full)
        lb = agg["late_before"].get(rid) or _empty_cell()
        machines[rid] = {"id": rid, "name": m["name"], "load": round(load, 1), "capacity": round(full, 1) if dated else None,
                         PLAN: round(acc[PLAN], 1), DUE: round(acc[DUE], 1), SUGGESTED: round(acc[SUGGESTED], 1),
                         "unknown": acc["unknown"], "operations": acc["operations"], "metres": round(acc["metres"], 1),
                         "metres_unknown": acc["metres_unknown"], "status": status,
                         "late_before": round(lb[PLAN] + lb[DUE] + lb[SUGGESTED], 1) if current in chosen else None}
        caps[rid] = full if dated and with_calendar and has_calendar else None
        for k in (PLAN, DUE, SUGGESTED):
            kinds[k]["hours"] += acc[k]
            kinds[k]["unknown"] += acc["unknown_" + k]
    posts = agg["src"].get("posts") or {}
    members = {x for ms in posts.values() for x in ms}
    shape = {"roles": {rid: "maquina" for rid in caps if rid not in posts or rid in members},
             "members": {post: list(ms) for post, ms in posts.items()}}
    resources = {rid: {"id": rid} for rid in {*caps, *posts, *members}}
    known = [caps[rid] for rid in counted(resources, caps, shape=shape) if caps.get(rid) is not None]
    any_dated = any((y, w) >= current for y, w in chosen)
    return {"sector": sector, "codes": codes, "today": agg["today"], "current": current in chosen,
            "current_week": f"{current[0]}-W{current[1]:02d}", "machines": machines,
            "kinds": {k: {"hours": round(v["hours"], 1), "unknown": v["unknown"]} for k, v in kinds.items()},
            "totals": {"capacity": round(sum(known), 1) if any_dated and known else None,
                       "load": round(sum(x["load"] for x in machines.values()), 1),
                       "late_before": round(sum(x["late_before"] or 0 for x in machines.values()), 1) if current in chosen else None,
                       "no_date": round(sum(c[PLAN] + c[DUE] + c[SUGGESTED] for c in agg["undated"].values()), 1)},
            "stale": agg["stale"]}


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
    """O que está atrás de uma célula: uma linha por OF (horas, horas segundo o Excel, peso, peças, metros, prazo).

    Na semana atual entram também as OF com prazo antes desta semana (coluna Atrasado). Desde 08/10 (F12) as horas
    vêm separadas: `week_hours` são as da grelha (a carga da semana) e `late_before` as atrasadas, por tipo; `hours`
    continua a ser o total, como antes. Peso, peças e metros desconhecidos contam-se à parte, nunca como 0 (F09).
    """
    from . import load_sources
    planning.check_area(sector)
    today = today or _today()
    weeks = week_list(today)
    horizon, current = set(weeks), weeks[0]
    data, planned, occ = _context(sector, today)
    with planning.connect(readonly=True) as c:
        src = load_sources.context(c, sector)
    lines = {x["key"]: x for x in data["lines"]}
    weights = weights_of(data["lines"])
    target = (int(year), int(week))
    monday_now = date.fromisocalendar(*current, 1)
    groups = {}
    summary = {"plan_principal": 0.0, "excel_hours": 0.0, "excel_unknown": 0, "weight_kg": 0.0, "weight_unknown": 0}
    late = {"hours": 0.0, "unknown": 0, "operations": 0, PLAN: 0.0, DUE: 0.0, SUGGESTED: 0.0}
    for f in _cell_facts(occ, planned, current, horizon, machine, target, today, data["lines"], sector):
        kind = f["_kind"]
        extra = bool(f.get("_extra"))
        before = target == current and _before_week(f, monday_now)
        excel, _, applies = load_sources.fact_values(f, src["lines"])
        weight = fact_weight(f, weights)
        principal = f.get("phase", "principal") == "principal"
        g = groups.setdefault(f["of"], {"of": f["of"], "customer": f.get("customer"), "work": f.get("work"), "hours": 0.0, "unknown": 0,
                                        "week_hours": 0.0, "late_before_hours": 0.0, "late_before_operations": 0,
                                        "pieces": 0.0, "pieces_unknown": 0, "metres": 0.0, "metres_unknown": 0, "operations": 0,
                                        "references": set(), "kinds": set(), "priority_day": None, "late_days": 0,
                                        "excel_hours": 0.0, "excel_unknown": 0, "weight_kg": 0.0, "weight_unknown": 0, "_weights": 0})
        if principal and f.get("_part") == "plan":  # «planeado X de Y» (quantidade parcial, 08/10)
            g.setdefault("planned_part", {"pieces": 0.0, "of": 0.0})
            g["planned_part"]["pieces"] += f["remaining"]
            g["planned_part"]["of"] += f["planned_of"]
        if applies:
            if excel is None:
                g["excel_unknown"] += not extra
                summary["excel_unknown"] += not extra
            else:
                g["excel_hours"] += excel
                summary["excel_hours"] += excel
        if principal:
            if weight is None:
                g["weight_unknown"] += not extra
                summary["weight_unknown"] += not extra
            else:
                g["weight_kg"] += weight
                g["_weights"] += 1
                summary["weight_kg"] += weight
        if principal and f.get("load_hours") is not None:
            summary["plan_principal"] += f["load_hours"]
        g["operations"] += not extra
        g["references"].add(f.get("reference"))
        g["kinds"].add(kind)
        hours = f.get("load_hours")
        if hours is None:
            g["unknown"] += not extra
        else:
            g["hours"] += hours
            g["late_before_hours" if before else "week_hours"] += hours
        if before:
            g["late_before_operations"] += not extra
            late["operations"] += not extra
            if hours is None:
                late["unknown"] += not extra
            else:
                late["hours"] += hours
                late[kind] += hours
        line = lines.get(f.get("line_key"))
        if f.get("phase") == "principal" and line:
            # Linha dividida (parte + resto, 08/10): peças e metros pela proporção desta ocorrência.
            share = f["remaining"] / f["planned_of"] if f.get("_part") and f.get("planned_of") else 1.0
            if line["pieces"] is None:
                g["pieces_unknown"] += not extra
            else:
                g["pieces"] += line["pieces"] * share
            if line.get("metres_unknown", line.get("balance_unknown")):
                g["metres_unknown"] += not extra
            else:
                g["metres"] += (line["metres"] or 0) * share
        day = f.get("priority_day")
        if day and (g["priority_day"] is None or str(day) < str(g["priority_day"])):
            g["priority_day"] = day
        g["late_days"] = max(g["late_days"], f.get("late_days") or 0)
    rows = sorted(groups.values(), key=lambda g: (-g["late_days"], str(g["priority_day"] or "9999"), g["of"]))
    for g in rows:
        g["references"] = len(g["references"])
        g["kinds"] = sorted(g["kinds"])
        for k in ("hours", "week_hours", "late_before_hours", "excel_hours"):
            g[k] = round(g[k], 2)
        g["metres"] = round(g["metres"], 1)
        g["pieces"] = round(g["pieces"])
        if g.get("planned_part"):
            part = g["planned_part"]
            g["planned_part"] = {"pieces": round(part["pieces"]), "of": round(part["of"])}
            g["planned_text"] = f"planeado {pieces_text(part['pieces'])} de {pieces_text(part['of'])}"
        # Só operações sem peso → peso desconhecido («—»), nunca 0,0 kg (F09).
        g["weight_kg"] = round(g["weight_kg"], 1) if g.pop("_weights") or not g["weight_unknown"] else None
    extra = src["actual"].get((machine, int(year), int(week))) or {}
    hours = round(sum(g["hours"] for g in rows), 2)
    return needs.serial({"sector": sector, "machine": machine, "year": int(year), "week": int(week), "orders": rows,
                         "hours": hours, "unknown": sum(g["unknown"] for g in rows),
                         "week_hours": round(hours - late["hours"], 2), "week_unknown": sum(g["unknown"] for g in rows) - late["unknown"],
                         "late_before": {k: round(v, 2) if isinstance(v, float) else v for k, v in late.items()},
                         **{k: round(v, 2) if isinstance(v, float) else v for k, v in summary.items()},
                         "actual_hours": extra.get("actual_hours"), "excel_calendar_hours": extra.get("excel_calendar_hours")})


def pieces_text(value) -> str:
    """3139 → «3 139» (peças, como no ecrã)."""
    return f"{round(value):,}".replace(",", "\u00a0")


def _cell_facts(occ, planned, current, horizon, machine, target, today=None, lines=None, sector=None):
    """Ocorrências de uma célula (máquina × semana), com o tipo (no plano / a vencer / sugerida) e o atraso.
    Com as linhas, as ocorrências das linhas planeadas em parte vêm divididas (split_facts).
    Sem a 2.ª operação das cantoneiras, como as células de _aggregate (P3, 08/10): o detalhe soma o que a célula mostra."""
    from . import second_operation
    facts = split_facts(occ["facts"], planned, lines) if lines is not None else occ["facts"]
    for f in facts:
        if f.get("planning_resource_id") != machine:
            continue
        if sector and second_operation.operation(sector, f):
            continue
        found = classify(f, planned, current, horizon, today)
        if not found or found[1] != target:
            continue
        yield {**f, "_kind": found[0], "_late": found[2]}


def estimate_calculation(fact: dict) -> dict | None:
    """Cálculo das horas estimadas da Carteira (estimates.estimate) para o «Ver cálculo» (auditoria 06/10, CARGA-OPS-01).

    Quando as horas da linha são estimadas, a prova do motor de capacidade não as explica: a conta mostrada tem de
    ser a da estimativa, com a origem verdadeira da taxa (plano de 06/10, parte 3): taxa confirmada da tabela de
    velocidades, linha da tabela com origem Excel, velocidade mais recente do Excel (MTG3) ou taxa mm²/h da folha
    CapacidadeMáquinas (MTG2). A taxa mostrada é a da tabela/Excel; o tempo por peça e a margem aparecem à parte,
    para a conta bater certo. Sem o detalhe guardado (Carteira antiga), a taxa é volume ÷ horas.
    """
    hours, remaining = fact.get("load_hours"), fact.get("remaining")
    if fact.get("load_basis") != "estimada" or not hours or remaining is None:
        return None
    detail = fact.get("load_estimate") or {}
    if fact.get("area") == "cantoneiras":
        length = fact.get("length_mm")
        if not length:
            return None
        volume, unit, rate_unit, what = remaining * length / 1000, "m", "m/h", "metros em falta (peças em falta × comprimento ÷ 1000)"
    else:
        section = fact.get("section_unit")
        if not section:
            return None
        volume, unit, rate_unit, what = remaining * section, "mm²", "mm²/h", "peças em falta × área de corte unitária"
    origin = detail.get("origin") or ("velocidade do Excel" if fact.get("area") == "cantoneiras" else "taxa mm²/h do Excel (sem fator ×3)")
    rate = detail.get("rate") if detail.get("rate") else volume / hours
    piece_seconds, margin = detail.get("piece_seconds") or 0, detail.get("margin_pct") or 0
    formula = f"{what} ÷ {origin}"
    if piece_seconds:
        formula += f" + peças em falta × {piece_seconds:g} s por peça ÷ 3600"
    if margin:
        formula = f"({formula}) × (1 + {margin:g} % de margem)"
    out = {"formula": formula, "remaining": remaining, "length_mm": fact.get("length_mm"), "section_unit": fact.get("section_unit"),
           "volume": round(volume, 3), "volume_unit": unit, "rate": round(rate, 3), "rate_unit": rate_unit,
           "hours": round(hours, 4), "basis": fact.get("load_origin"), "rate_origin": origin}
    if piece_seconds or margin:
        out.update(piece_seconds=piece_seconds, rate_piece_seconds=detail.get("rate_piece_seconds") or 0,
                   fixed_piece_seconds=detail.get("fixed_piece_seconds") or 0, margin_pct=margin,
                   volume_hours=round(volume / rate, 4), pieces_hours=round(remaining * piece_seconds / 3600, 4))
    return out


def operations(sector: str, machine: str, year: int, week: int, of: str, *, today: date | None = None) -> dict:
    """Operações de uma OF numa célula, com o cálculo de cada uma (taxa, fórmula, vigência, Excel)."""
    from . import load_sources
    from .occurrences import _estimate_name
    planning.check_area(sector)
    today = today or _today()
    weeks = week_list(today)
    data, planned, occ = _context(sector, today)
    facts = [f for f in _cell_facts(occ, planned, weeks[0], set(weeks), machine, (int(year), int(week)), today, data["lines"], sector)
             if f["of"] == of]
    with planning.connect(readonly=True) as c:
        src = load_sources.context(c, sector)
        proofs = load_sources.proofs(c, sector, sorted({f["line_key"] for f in facts if f.get("line_key")}))
    KIND = {PLAN: "no plano", DUE: "a vencer", SUGGESTED: "a vencer, máquina sugerida"}
    weights = weights_of(data["lines"])
    out = []
    for f in sorted(facts, key=lambda x: (str(x.get("reference")), x.get("occurrence") or 0)):
        excel, _, applies = load_sources.fact_values(f, src["lines"])
        weight = fact_weight(f, weights)  # o peso da Carteira (F21, 08/10)
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
                    "proof": proofs.get((f.get("line_key"), name)),
                    # Quantidade parcial (08/10): a parte planeada desta operação e o saldo todo.
                    **({"planned_of": f["planned_of"], "part": f["_part"]} if f.get("_part") and f.get("planned_of") else {}),
                    **({"planned_text": f"planeado {pieces_text(f['remaining'])} de {pieces_text(f['planned_of'])}"}
                       if f.get("_part") == "plan" else {})})
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
