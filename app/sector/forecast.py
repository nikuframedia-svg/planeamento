"""Previsão com capacidade finita (Etapa 3, 08/10/2026): conclusão prevista, margem, risco e recurso limitante.

Monta a entrada do despacho (dispatch.py) a partir da MESMA população e das MESMAS horas da Carga (load._context):
linhas da Carteira, decisões Planear (com a parte planeada, contrato 3A/3B) e ocorrências sem as excluídas.

- Máquina de cada operação: a efetiva, senão a sugerida (`planning_resource_id`); horas = `load_hours` (as da
  Carga), em segundos inteiros. Prazo = `priority.resolve` (MTG3 Data Corte até ao fim do dia; MTG2 Picking como
  instante, segunda às 08:00).
- Âmbito 0 = a parte planeada das linhas Planeado (Planear + máquina atribuída, como na Carga): min(parte, saldo)
  na operação principal; nas seguintes, as peças já cortadas que faltam mais a parte planeada. O resto da linha
  entra no âmbito 1, com o resto das horas (a soma dos segundos não muda).
- Ordem em cada máquina: âmbito → «N.ª PRIORIDADE» escrita → clientes prioritários (Definições, lista) → com prazo
  antes de sem prazo → prazo → OF → perfil → comprimento → chave.
- Fora da previsão, com o motivo: 2.ª operação das cantoneiras, estacionadas, saldo por confirmar, sem máquina,
  máquina de outro setor, sem horas e máquina sem calendário. A 2.ª operação e as operações sem calendário ficam
  fora da conclusão e da fiabilidade das linhas.
- Origem = início do turno em curso (hora de Lisboa; entre turnos, o último que começou); dia = dia de Lisboa.
- Risco (3 estados): «atrasa» (fim previsto depois do instante do prazo), «em_risco» (0 ≤ margem < folga, dias
  úteis, Definições «folga_dias», defeito 2) e «sem_previsao» (com o motivo). À parte, «já em atraso» (prazo antes
  de hoje). A folga nunca muda as datas mostradas. 100 % ocupada = «Completa», nunca erro.
- Margem = dias com turnos na máquina entre o dia da conclusão (exclusive) e o dia do prazo (inclusive); negativa
  quando acaba depois. MTG3 por linha (Data Corte); MTG2 pela OF inteira (Picking) com os dias de trabalho do setor.
- Falta acumulada pelo prazo, por máquina (ou posto): horas com prazo ≤ t (incluindo o já atrasado) − capacidade
  da origem a t; recuperação = o dia a partir do qual a falta fica ≤ 0. Recurso limitante = o que recupera mais
  tarde («não recupera no horizonte» primeiro; desempates: pico de falta em semanas de turnos, depois horas que
  acabam depois do prazo), com a parte das horas que vem de máquinas sugeridas.
- Pessoas por dia e turno = pico de máquinas a trabalhar × pessoas por máquina (defeito 1) contra as pessoas
  disponíveis por turno (vazio = sem défice).
Invariante: Σ horas previstas por máquina (colocáveis + não colocáveis com horas) = totais da Carga.
"""
from __future__ import annotations

import logging
import statistics
import time as clock
from bisect import bisect_right
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .. import planning, planning_needs as needs
from . import cache, dispatch

log = logging.getLogger(__name__)
LISBON = ZoneInfo("Europe/Lisbon")
FOLGA_DEFAULT = 2
CELL_WEEKS = 13
LATE, AT_RISK, NO_FORECAST, OK = "atrasa", "em_risco", "sem_previsao", "ok"
STATES = (LATE, AT_RISK, NO_FORECAST, OK)
IGNORED = {"segunda_operacao", "sem_calendario"}  # fora da conclusão e da fiabilidade das linhas
REASON_TEXT = {
    "sem_maquina": "Sem máquina nem sugestão", "sem_horas": "Sem horas", "sem_calendario": "Máquina sem calendário",
    "estacionada": "Estacionada no Excel", "saldo_desconhecido": "Saldo por confirmar",
    "outro_setor": "Máquina de outro setor", "segunda_operacao": "2.ª operação (fora do plano)",
    "alem_do_horizonte": "Acaba depois do fim dos calendários", "sem_prazo": "Sem prazo",
}

_cache = cache.Cache("Previsão", mark=lambda value: {**value, "stale": True})


# ---------------------------------------------------------------- funções puras

def origin_at(now: datetime, template) -> datetime:
    """Início do turno em curso (Lisboa): o último início de turno do horário que já passou."""
    local = now.astimezone(LISBON)
    best = None
    for back in (0, 1, 2):
        day = local.date() - timedelta(days=back)
        for start, _ in template:
            hour, minute = int(start[:2]), int(start[3:5])
            at = datetime.combine(day, time(hour, minute), LISBON)
            if at <= local and (best is None or at > best):
                best = at
    return (best or local.replace(second=0, microsecond=0)).astimezone(timezone.utc)


def _norm(text) -> str:
    return " ".join(str(text or "").split()).casefold()


def client_position(customer, clients) -> int:
    """Posição do cliente na lista dos prioritários (o nome escrito contido no do cliente); fora da lista = len."""
    name = _norm(customer)
    for i, wanted in enumerate(clients or ()):
        w = _norm(wanted)
        if w and w in name:
            return i
    return len(clients or ())


def _instant(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        found = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return found if found.tzinfo else found.replace(tzinfo=timezone.utc)


def priority_key(fact: dict, clients=()) -> tuple:
    """Chave de prioridade (sem o âmbito, que o despacho põe à frente). Sem None: comparável sempre."""
    signals = fact.get("signals") or {}
    written = signals.get("prioridade")
    priority = fact.get("priority") or {}
    due = priority.get("priority_date")
    length = fact.get("length_mm")
    return ((0, int(written)) if written is not None else (1, 0),
            client_position(fact.get("customer"), clients),
            0 if due else 1, str(due or ""), str(fact.get("of") or ""),
            str(fact.get("profile") or ""), float(length) if length is not None else float("inf"),
            str(fact.get("key")))


def planned_pieces(fact: dict, open_pieces, principal_remaining) -> int | float:
    """Peças da parte planeada de uma ocorrência (contrato 3A/3B, regra do desenho P5).

    `open_pieces` = parte planeada ainda aberta da linha (None = a linha inteira). Principal: min(parte, saldo).
    Seguintes: as peças já cortadas que faltam mais a parte planeada, sem passar do saldo próprio."""
    remaining = fact.get("remaining") or 0
    if open_pieces is None:
        return remaining
    if fact.get("phase", "principal") == "principal":
        return max(0, min(open_pieces, remaining))
    cut_waiting = max(remaining - (principal_remaining or 0), 0)
    return max(0, min(remaining, open_pieces + cut_waiting))


def _planned_map(planned) -> dict:
    """Contrato: dict {chave da linha: peças planeadas abertas ou None}; um set (código antigo) = tudo inteiro."""
    if isinstance(planned, dict):
        return planned
    return {key: None for key in planned or ()}


def operations_from(facts: list[dict], *, sector: str, planned, own: set, pools: dict, clients=()) -> tuple[list, dict]:
    """(operações do despacho, meta por chave) a partir das ocorrências da Carga."""
    from . import second_operation
    planned = _planned_map(planned)
    principal_left = {}
    for f in facts:
        if f.get("phase", "principal") == "principal" and f.get("line_key"):
            principal_left[f["line_key"]] = f.get("remaining")
    pool_of = {}
    for post, members in (pools or {}).items():
        for rid in (post, *members):
            pool_of[rid] = post
    ops, meta = [], {}
    for f in facts:
        rid = f.get("planning_resource_id")
        priority = f.get("priority") or {}
        hours = f.get("load_hours")
        reason = None
        if second_operation.operation(sector, f):
            reason = "segunda_operacao"
        elif priority.get("parked"):
            reason = "estacionada"
        elif f.get("remaining") is None:
            reason = "saldo_desconhecido"
        elif not rid:
            reason = "sem_maquina"
        elif rid not in own:
            reason = "outro_setor"
        elif hours is None:
            reason = "sem_horas"
        seconds = int(round(hours * 3600)) if hours is not None else None
        in_plan = f.get("line_key") in planned  # linha Planeado (Planear); o âmbito 0 pede também a máquina atribuída
        is_plan = in_plan and f.get("machine_basis") == "atribuída"
        part = 0
        if is_plan and not reason:
            part = planned_pieces(f, planned.get(f["line_key"]), principal_left.get(f.get("line_key")))
        remaining = f.get("remaining") or 0
        base = {"resource_id": rid, "priority_key": priority_key(f, clients), "of": f.get("of"),
                "line_key": f.get("line_key"), "due": _instant(priority.get("priority_date")),
                "due_field": priority.get("priority_field"), "pool": pool_of.get(rid) if rid else None}
        info = {"of": f.get("of"), "line_key": f.get("line_key"), "reference": f.get("reference"),
                "operation": f.get("operation_label") or f.get("operation"), "phase": f.get("phase", "principal"),
                "customer": f.get("customer"), "machine_basis": f.get("machine_basis"), "load_basis": f.get("load_basis"),
                "provisional": bool(priority.get("provisional")), "due_day": priority.get("priority_day"),
                "resource_id": rid, "machine": f.get("planning_machine"), "fact_key": f.get("key"),
                "started": bool(f.get("started")), "documentary_resource_id": f.get("documentary_resource_id"),
                "hours_machine": f.get("hours_machine"), "parked": bool(priority.get("parked")),
                "length_mm": f.get("length_mm")}
        if reason:  # fora da previsão; uma linha Planeado guarda o âmbito 0 (o Gantt diz porque não aparece)
            ops.append({**base, "key": f["key"], "seconds": seconds, "scope": 0 if in_plan else 1, "reason": reason})
            meta[f["key"]] = {**info, "pieces": f.get("pieces"), "hours": hours, "scope": 0 if in_plan else 1, "plan": in_plan}
            continue
        if not is_plan or part <= 0 or remaining <= 0:
            ops.append({**base, "key": f["key"], "seconds": seconds, "scope": 1})
            meta[f["key"]] = {**info, "pieces": f.get("pieces"), "hours": hours, "scope": 1, "plan": False}
            continue
        whole = part >= remaining
        plan_seconds = seconds if whole else int(round(seconds * part / remaining))
        principal = f.get("phase", "principal") == "principal"
        ops.append({**base, "key": f["key"], "seconds": plan_seconds, "scope": 0})
        meta[f["key"]] = {**info, "pieces": part if principal else None, "hours": plan_seconds / 3600, "scope": 0, "plan": True,
                          "partial": not whole}
        if not whole:
            rest_key = f["key"] + "#resto"
            ops.append({**base, "key": rest_key, "seconds": seconds - plan_seconds, "scope": 1})
            meta[rest_key] = {**info, "pieces": remaining - part if principal else None,
                              "hours": (seconds - plan_seconds) / 3600, "scope": 1, "plan": False, "rest_of": f["key"]}
    return ops, meta


def label_windows(calendars: list[dict], template, origin: datetime) -> dict:
    """{máquina: [(início, fim, (dia ISO do turno, turno))]} a partir da origem, cortadas pelos turnos do setor."""
    from .. import planning_calendars
    from .week import split_by_shift
    out = defaultdict(list)
    for d in calendars:
        rid = str(d.get("resource_id"))
        for r in planning_calendars.expand(d) or []:
            a, b = datetime.fromisoformat(r["start"]), datetime.fromisoformat(r["end"])
            if b <= origin:
                continue
            a = max(a, origin)
            for piece in split_by_shift(a, b, template):
                out[rid].append((piece["start"], piece["end"], (piece["shift_date"].isoformat(), piece["shift"])))
    return {rid: sorted(set(items)) for rid, items in out.items()}


class Rule:
    """Dias de trabalho do setor (Definições: dias da semana e feriados), para os dias sem calendário: antes da
    origem (prazos já passados) e depois do último calendário. Conta por aritmética, sem percorrer os dias."""

    def __init__(self, workdays=(1, 2, 3, 4, 5), holidays=()):
        self.workdays = {int(d) for d in workdays}
        self.holidays = sorted(h for h in {str(x)[:10] for x in holidays} if date.fromisoformat(h).isoweekday() in self.workdays)

    def count(self, after: date, until: date) -> int:
        """Dias de trabalho em (after, until]."""
        if until <= after:
            return 0
        span = (until - after).days
        weeks, rest = divmod(span, 7)
        n = weeks * len(self.workdays)
        day = after + timedelta(days=weeks * 7)
        for _ in range(rest):
            day += timedelta(days=1)
            n += day.isoweekday() in self.workdays
        return n - (bisect_right(self.holidays, until.isoformat()) - bisect_right(self.holidays, after.isoformat()))


class Calendar:
    """Janelas de uma máquina (ou de um posto, a união): horas acumuladas e dias com turnos. Fora do período com
    calendário (antes do primeiro dia, depois do último) os dias contam pela regra do setor (`rule`)."""

    def __init__(self, windows, rule: Rule | None = None):
        merged = []
        for a, b, *_ in sorted(windows):
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        self.starts = [a for a, _ in merged]
        self.ends = [b for _, b in merged]
        self.cum = [0.0]
        for a, b in merged:
            self.cum.append(self.cum[-1] + (b - a).total_seconds())
        self.days = sorted({w[2][0] if len(w) > 2 and w[2] else w[0].astimezone(LISBON).date().isoformat() for w in windows})
        self.first_day = self.days[0] if self.days else None
        self.last_day = self.days[-1] if self.days else None
        self.rule = rule

    def seconds_before(self, t: datetime) -> float:
        i = bisect_right(self.starts, t)
        if i == 0:
            return 0.0
        done = self.cum[i - 1]
        a, b = self.starts[i - 1], self.ends[i - 1]
        return done + (min(t, b) - a).total_seconds()

    def hours_between(self, a: datetime, b: datetime) -> float:
        return (self.seconds_before(b) - self.seconds_before(a)) / 3600

    def workdays(self, after: str, until: str) -> int:
        """Dias com turnos em (after, until] (datas ISO)."""
        if not self.days:
            return self.rule.count(date.fromisoformat(after), date.fromisoformat(until)) if self.rule else 0
        n = bisect_right(self.days, until) - bisect_right(self.days, after)
        if self.rule:
            first = date.fromisoformat(self.first_day) - timedelta(days=1)  # antes do calendário: (after, véspera]
            n += self.rule.count(date.fromisoformat(after), min(date.fromisoformat(until), first))
            last = date.fromisoformat(self.last_day)                       # depois: (último, until]
            n += self.rule.count(max(date.fromisoformat(after), last), date.fromisoformat(until))
        return n


def margin_days(end: datetime, due_day: str, calendar: Calendar) -> int:
    """Margem em dias úteis: dias com turnos depois do dia da conclusão até ao dia do prazo (inclusive);
    negativa quando acaba depois do prazo (dias com turnos depois do prazo até ao dia da conclusão)."""
    done = (end - timedelta(seconds=1)).astimezone(LISBON).date().isoformat()
    if done <= due_day:
        return calendar.workdays(done, due_day)
    return -calendar.workdays(due_day, done)


def state_of(*, end, due, margin, folga, beyond, horizon_end, missing) -> tuple[str | None, str | None]:
    """(estado, motivo) de uma linha ou OF. Sem prazo → (None, 'sem_prazo')."""
    if due is None:
        return None, "sem_prazo"
    if end is not None and end > due:
        return LATE, None
    if beyond:
        if horizon_end is not None and due <= horizon_end:
            return LATE, None
        return NO_FORECAST, "alem_do_horizonte"
    if missing:
        return NO_FORECAST, missing[0]
    if end is None:
        return NO_FORECAST, "sem_previsao"
    if margin is not None and margin < folga:
        return AT_RISK, None
    return OK, None


def _rank(state):
    return {LATE: 0, AT_RISK: 1, NO_FORECAST: 2, OK: 3, None: 4}[state]


def shortage(ops: list[dict], calendar: Calendar, origin: datetime, last_day: date | None) -> dict:
    """Falta acumulada pelo prazo de um recurso: pico (h), recuperação (data) e se recupera no horizonte.

    `ops` = [{due (instante), seconds}] das operações colocáveis com prazo."""
    if not last_day:
        return {"peak_hours": 0.0, "recovery": None, "recovers": True, "overloaded": False}
    dues = sorted((op["due"], op["seconds"]) for op in ops if op.get("due") is not None)
    day = origin.astimezone(LISBON).date()
    i, demand, peak, last_over, last_seen = 0, 0.0, 0.0, None, None
    while day <= last_day:
        end = datetime.combine(day + timedelta(days=1), time.min, LISBON).astimezone(timezone.utc)
        while i < len(dues) and dues[i][0] <= end:
            demand += dues[i][1]
            i += 1
        missing = (demand - (calendar.seconds_before(end) - calendar.seconds_before(origin))) / 3600
        if missing > 0.05:
            last_over = day
            peak = max(peak, missing)
        last_seen = day
        day += timedelta(days=1)
    recovers = last_over is None or last_over < last_seen
    return {"peak_hours": round(peak, 1), "overloaded": last_over is not None, "recovers": recovers,
            "recovery": (last_over + timedelta(days=1)) if last_over is not None and recovers else None}


def limiting(slots: list[dict]) -> list[dict]:
    """O recurso que recupera mais tarde («não recupera» primeiro; desempates: pico em semanas, horas atrasadas).
    Empates verdadeiros vêm todos."""
    over = [s for s in slots if s.get("overloaded")]
    if not over:
        return []

    def key(s):
        recovery = s["recovery"].toordinal() if s.get("recovery") else 0
        return (s["recovers"], -recovery, -round(s.get("peak_weeks") or 0, 2), -round(s.get("late_hours") or 0, 1))
    over.sort(key=lambda s: (key(s), str(s["id"])))
    first = key(over[0])
    return [s for s in over if key(s) == first]


def cell_state(capacity: float, load: float) -> str:
    """Fechado | Sem carga | parcial (%) | Completa 100 % — nunca vermelho."""
    if capacity <= 0:
        return "fechado" if load <= 0 else "completa"
    if load <= 0:
        return "sem_carga"
    return "completa" if load >= capacity - 60 else "parcial"


def people_needed(segments_by_machine: dict, persons: dict) -> int:
    """Pico de pessoas ao mesmo tempo: Σ pessoas das máquinas a trabalhar (varrimento dos segmentos)."""
    events = []
    for rid, items in segments_by_machine.items():
        n = persons.get(rid, 1)
        for a, b in items:
            events.append((b, 0, -n))  # quem acaba sai antes de quem entra no mesmo instante
            events.append((a, 1, n))
    events.sort(key=lambda x: (x[0], x[1]))
    now = peak = 0
    for _, _, delta in events:
        now += delta
        peak = max(peak, now)
    return peak


def persons_of(setting, rids) -> dict:
    """Pessoas por máquina a trabalhar (Definições): número para todas ou {máquina: n}; defeito 1."""
    if isinstance(setting, dict):
        return {rid: _count(setting.get(rid), 1) for rid in rids}
    value = _count(setting, 1)
    return {rid: value for rid in rids}


def _count(value, default):
    try:
        return max(0, int(value)) if value is not None and value != "" else default
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- cálculo

def _key_inputs(sector: str, now: datetime | None = None) -> dict:
    """O que a chave da previsão segue: a população da Carga (carimbos efetivamente devolvidos), as decisões
    com quantidades, os calendários, as Definições, a origem e o dia de Lisboa."""
    from . import load, settings as sector_settings
    from .week import lisbon_today
    now = now or datetime.now(timezone.utc)
    today = lisbon_today(now)
    data, planned, occ = load._context(sector, today)
    with planning.connect(readonly=True) as c:
        settings = sector_settings.read(c, sector)
        calendars = load._calendar_stamp(c)
    origin = origin_at(now, settings["template"])
    planned_map = _planned_map(planned)
    key = (occ.get("stamp"), data.get("generation"), occ.get("decisions"),
           needs.digest(needs.serial(sorted(planned_map.items(), key=lambda x: str(x[0])))), calendars,
           settings.get("revision"), origin.isoformat(), today)
    return {"data": data, "planned": planned_map, "occ": occ, "settings": settings, "origin": origin, "today": today,
            "now": now, "key": key, "stale": bool(occ.get("stale") or data.get("stale"))}


def _sources(c, sector: str) -> dict:
    """Máquinas do setor (as da Carga), calendários, postos partilhados e a idade da camada v2."""
    from . import load_sources, second_operation, settings as sector_settings
    from .occurrences import resources_context
    context = resources_context(c)
    codes, by_id, _, _, package = context
    machines = [m for m in sector_settings.machine_rows(c, sector, context=context)
                if not second_operation.machine(sector, m.get("process"))]
    ids = [m["id"] for m in machines]
    calendars = [r["definition"] for r in c.execute(
        "SELECT definition FROM planning_mtg.raw_objects WHERE kind='calendar' AND NOT archived "
        "AND definition->>'resource_id' = ANY(%s)", (ids,)).fetchall()]
    v2 = None
    if package and (package.get("head") or {}).get("created_at"):
        v2 = package["head"]["created_at"]
    posts = load_sources.posts(by_id, package)
    own = set(ids)
    posts = {p: [m for m in ms] for p, ms in posts.items() if p in own or any(m in own for m in ms)}
    names = {rid: r.get("name") or rid for rid, r in by_id.items()}
    return {"machines": machines, "calendars": calendars, "posts": posts, "names": names, "v2_at": v2}


def compute(sector: str, ki: dict, src: dict) -> dict:
    """A previsão inteira de um setor (puro: recebe as entradas já lidas)."""
    started = clock.monotonic()
    settings, origin, today = ki["settings"], ki["origin"], ki["today"]
    data, occ = ki["data"], ki["occ"]
    template = settings["template"]
    folga = _count(settings.get("folga_dias"), FOLGA_DEFAULT)
    clients = [c for c in (settings.get("clientes_prioritarios") or []) if str(c or "").strip()]
    machines = src["machines"]
    own = {m["id"] for m in machines}
    names = {**src.get("names", {}), **{m["id"]: m["name"] for m in machines}}
    ops, meta = operations_from(occ["facts"], sector=sector, planned=ki["planned"], own=own, pools=src["posts"],
                                clients=clients)
    windows = label_windows([d for d in src["calendars"] if str(d.get("resource_id")) in own], template, origin)
    result = dispatch.dispatch(ops, windows, origin)
    problems = dispatch.check(result, ops, windows)
    if problems:
        log.error("Previsão %s: o verificador encontrou %d problemas (ex.: %s)", sector, len(problems), problems[:3])
    placed = result["operations"]
    gone = {u["key"]: u for u in result["unschedulable"]}
    fallback = Rule(settings.get("workdays") or [], settings.get("holidays") or ())
    calendars = {rid: Calendar(w, fallback) for rid, w in windows.items()}
    sector_days = Calendar([w for ws in windows.values() for w in ws], fallback)
    empty = Calendar([], fallback)
    horizon_end = max(result["horizon_end"].values()) if result["horizon_end"] else None

    # --- horas por máquina (invariante com a Carga)
    hours = defaultdict(lambda: {"placeable": 0, "excluded": 0, "unknown": 0})
    for op in ops:
        rid = op.get("resource_id")
        if rid not in own:
            continue
        reason = gone.get(op["key"], {}).get("reason")
        if reason == "segunda_operacao":
            continue
        if op.get("seconds") is None:
            hours[rid]["unknown"] += 1
        elif reason:
            hours[rid]["excluded"] += op["seconds"]
        else:
            hours[rid]["placeable"] += op["seconds"]
    machine_hours = {rid: {"placeable": round(h["placeable"] / 3600, 2), "excluded": round(h["excluded"] / 3600, 2),
                           "total": round((h["placeable"] + h["excluded"]) / 3600, 2), "unknown": h["unknown"]}
                     for rid, h in hours.items()}

    # --- linhas e OF
    lines, by_order = {}, defaultdict(list)
    for key, m in meta.items():
        lk = m["line_key"] or key
        line = lines.get(lk)
        if line is None:
            line = lines[lk] = {"line_key": lk, "of": m["of"], "reference": None, "customer": m["customer"], "end": None,
                                "beyond": False, "missing": [], "due": None, "due_day": None, "machine": None,
                                "resource_id": None, "approximate": set(), "planned": False, "parked": False, "ops": 0}
            by_order[m["of"]].append(lk)
        g = gone.get(key)
        if m["phase"] == "principal" or line["reference"] is None:
            line["reference"] = m["reference"]
        line["planned"] = line["planned"] or m["plan"]
        line["parked"] = line["parked"] or m["parked"]
        if g:
            if g["reason"] not in IGNORED:
                line["missing"].append(g["reason"])
            continue
        r = placed[key]
        line["ops"] += 1
        if m["phase"] == "principal":
            line["resource_id"], line["machine"] = r["resource_id"], names.get(r["resource_id"]) or m["machine"]
        if r["status"] == dispatch.BEYOND:
            line["beyond"] = True
        elif r["end"] is not None and (line["end"] is None or r["end"] > line["end"]):
            line["end"] = r["end"]
        if m["load_basis"] == "estimada":
            line["approximate"].add("horas estimadas")
        if m["machine_basis"] == "sugerida":
            line["approximate"].add("máquina sugerida")
        if m["provisional"]:
            line["approximate"].add("ano do Picking deduzido")
    # Prazo da linha: o da operação principal; sem ela, o mais cedo das outras (fora a 2.ª operação).
    due_of, other_due = {}, {}
    for op in ops:
        m = meta[op["key"]]
        if op.get("due") is None or gone.get(op["key"], {}).get("reason") == "segunda_operacao":
            continue
        lk = m["line_key"] or op["key"]
        target = due_of if m["phase"] == "principal" else other_due
        if lk not in target or op["due"] < target[lk][0]:
            target[lk] = (op["due"], m["due_day"])
    for lk, line in lines.items():
        found = due_of.get(lk) or other_due.get(lk)
        if found:
            line["due"], line["due_day"] = found
    today_iso = today.isoformat()
    for lk, line in lines.items():
        cal = calendars.get(line["resource_id"]) or empty
        _evaluate(line, cal, folga, horizon_end, today_iso)
    orders = {}
    for of, keys in by_order.items():
        # Fora das listas: linhas estacionadas e as que só têm trabalho ignorado (2.ª operação, sem calendário).
        group = [x for x in (lines[k] for k in keys) if not x["parked"] and (x["ops"] or x["missing"])]
        if not group:
            continue
        o = {"of": of, "customer": group[0]["customer"], "lines": len(group), "planned_lines": sum(x["planned"] for x in group),
             "machines": sorted({x["machine"] for x in group if x["machine"]}),
             "approximate": sorted(set().union(*[x["approximate"] for x in group]))}
        if sector == "perfis":  # a OF inteira contra o Picking (o prazo mais cedo das linhas), dias do setor
            ends = [x["end"] for x in group if x["end"] is not None]
            dues = [(x["due"], x["due_day"]) for x in group if x["due"] is not None]
            o.update(end=max(ends) if ends else None, beyond=any(x["beyond"] for x in group),
                     missing=sorted({r for x in group for r in x["missing"]}),
                     due=min(dues)[0] if dues else None, due_day=min(dues)[1] if dues else None,
                     resource_id=max(((x["end"], x["resource_id"]) for x in group if x["end"]), default=(None, None))[1])
            _evaluate(o, sector_days, folga, horizon_end, today_iso)
        else:  # MTG3: cada linha contra a sua Data Corte; a OF fica com a pior linha
            worst = min(group, key=lambda x: (_rank(x["state"]), x["margin_days"] if x["margin_days"] is not None else 10 ** 6))
            ends = [x["end"] for x in group if x["end"] is not None]
            dues = [x for x in group if x["due"] is not None]
            o.update(end=max(ends) if ends else None, beyond=any(x["beyond"] for x in group),
                     due=min(x["due"] for x in dues) if dues else None, due_day=min(x["due_day"] for x in dues) if dues else None,
                     state=worst["state"], reason=worst["reason"], margin_days=worst["margin_days"],
                     shift_hours=worst["shift_hours"], already_late=any(x["already_late"] for x in group))
        orders[of] = o

    # --- por máquina / posto: fila, falta acumulada, recuperação
    slot_of = {}
    for post, members in src["posts"].items():
        for rid in (post, *members):
            slot_of[rid] = post
    slot_ops = defaultdict(list)
    for key, r in placed.items():
        slot_ops[slot_of.get(r["resource_id"], r["resource_id"])].append((key, r))
    by_machine = {}
    slots = []
    for slot in sorted(set(slot_ops) | {slot_of.get(rid, rid) for rid in own}, key=str):
        members = [rid for rid in own if slot_of.get(rid, rid) == slot] or [slot]
        wins = [w for rid in members for w in windows.get(rid, [])]
        cal = Calendar(wins, fallback)
        last = date.fromisoformat(cal.last_day) if cal.last_day else None
        items = slot_ops.get(slot, [])
        total = sum(r["seconds"] for _, r in items)
        suggested = sum(r["seconds"] for k, r in items if meta[k]["machine_basis"] == "sugerida")
        late = sum(r["seconds"] for _, r in items if r["due"] is not None and (r["end"] is None or r["end"] > r["due"]))
        found = shortage([{"due": r["due"], "seconds": r["seconds"]} for _, r in items], cal, origin, last)
        weeks = defaultdict(float)
        for a, b, *_ in wins:
            weeks[a.astimezone(LISBON).isocalendar()[:2]] += (b - a).total_seconds() / 3600
        normal = statistics.median([h for h in weeks.values() if h > 0]) if any(h > 0 for h in weeks.values()) else None
        entry = {"id": slot, "name": names.get(slot) or slot, "machines": [names.get(r) or r for r in sorted(members, key=str)],
                 "pool": len(members) > 1 or slot in src["posts"], "hours": round(total / 3600, 1),
                 "suggested_hours": round(suggested / 3600, 1), "late_hours": round(late / 3600, 1),
                 "week_capacity": round(normal, 1) if normal else None,
                 "peak_weeks": round(found["peak_hours"] / normal, 2) if normal else None, **found}
        slots.append(entry)
        for rid in members:
            res = result["resources"].get(rid) or {}
            by_machine[rid] = {"id": rid, "name": names.get(rid) or rid, "queue_end": res.get("queue_end"),
                               "operations": res.get("placed", 0) + res.get("beyond", 0), "beyond": res.get("beyond", 0),
                               "hours": round((res.get("seconds") or 0) / 3600, 1), "slot": slot,
                               "recovery": found["recovery"], "recovers": found["recovers"],
                               "overloaded": found["overloaded"], "peak_hours": found["peak_hours"],
                               "late_hours": round(sum(r["seconds"] for _, r in items if r["resource_id"] == rid and r["due"] is not None
                                                       and (r["end"] is None or r["end"] > r["due"])) / 3600, 1),
                               "has_calendar": bool(windows.get(rid)), "excel_hours": machine_hours.get(rid)}

    # --- células máquina × dia × turno e pessoas (13 semanas a partir da origem)
    cell_end = origin + timedelta(weeks=CELL_WEEKS)
    capacity, loaded, running = defaultdict(float), defaultdict(float), defaultdict(lambda: defaultdict(list))
    for rid, wins in windows.items():
        for a, b, label in wins:
            if a < cell_end:
                capacity[(rid, *label)] += (b - a).total_seconds()
    for r in placed.values():
        for a, b, day, shift in r["segments"]:
            if a < cell_end:
                loaded[(r["resource_id"], day, shift)] += (b - a).total_seconds()
                running[(day, shift)][r["resource_id"]].append((a, b))
    cells = defaultdict(list)
    for key in sorted(set(capacity) | set(loaded), key=lambda k: (str(k[0]), str(k[1]), k[2] or 9)):
        rid, day, shift = key
        cap, used = capacity.get(key, 0.0), loaded.get(key, 0.0)
        cells[rid].append({"date": day, "shift": shift, "capacity": round(cap / 3600, 2), "load": round(used / 3600, 2),
                           "pct": round(100 * used / cap) if cap else None, "state": cell_state(cap, used)})
    persons = persons_of(settings.get("pessoas_por_maquina"), own)
    available = [x for x in (settings.get("pessoas_por_turno") or []) if x not in (None, "")]
    people = []
    for (day, shift), by_rid in sorted(running.items(), key=lambda x: (x[0][0], x[0][1] or 9)):
        need = people_needed(by_rid, persons)
        have = _count(available[shift - 1], None) if shift and available and shift - 1 < len(available) else None
        people.append({"date": day, "shift": shift, "machines": len(by_rid), "need": need, "available": have,
                       "deficit": max(0, need - have) if have is not None else None})

    # --- resumo de risco e fiabilidade
    counts = {LATE: 0, AT_RISK: 0, NO_FORECAST: 0, OK: 0, "ja_em_atraso": 0, "sem_prazo": 0}
    for o in orders.values():
        if o.get("already_late"):
            counts["ja_em_atraso"] += 1
        elif o["state"] is None:
            counts["sem_prazo"] += 1
        else:
            counts[o["state"]] += 1
    reasons = defaultdict(int)
    for u in result["unschedulable"]:
        reasons[u["reason"]] += 1
    approx = defaultdict(int)
    for line in lines.values():
        for why in line["approximate"]:
            approx[why] += 1
    reliability = {"approximate_lines": sum(1 for x in lines.values() if x["approximate"] and not x["parked"]),
                   "reasons": dict(sorted(approx.items())), "unschedulable": dict(sorted(reasons.items())),
                   "excel_imported_at": data.get("imported_at"), "v2_at": src.get("v2_at")}
    for line in lines.values():
        line["approximate"] = sorted(line["approximate"])
    elapsed = clock.monotonic() - started
    log.info("Previsão %s: %d operações em %.2f s", sector, len(ops), elapsed)
    return {"sector": sector, "today": today, "origin": origin, "horizon_end": horizon_end, "folga": folga, "template": template,
            "clients": clients, "operations": placed, "unschedulable": result["unschedulable"], "meta": meta,
            "lines": lines, "orders": orders, "machines": by_machine, "slots": slots, "limiting": limiting(slots),
            "cells": dict(cells), "people": people, "counts": counts, "reliability": reliability,
            "machine_hours": machine_hours, "check": problems, "names": names, "elapsed": round(elapsed, 2),
            "imported_at": data.get("imported_at"), "stale": ki["stale"], "stamp": needs.digest(needs.serial(ki["key"])),
            # Para as vistas da Carga (forecast_views): quando foi calculada e os dias de trabalho do setor.
            "computed_at": datetime.now(timezone.utc), "workdays": list(settings.get("workdays") or []),
            "holidays": sorted({str(h)[:10] for h in settings.get("holidays") or ()})}


def _evaluate(x: dict, cal: Calendar, folga: int, horizon_end, today_iso: str) -> None:
    """Margem, horas de turno até ao prazo, estado e «já em atraso» de uma linha ou OF (no próprio dicionário)."""
    end, due, due_day = x.get("end"), x.get("due"), x.get("due_day")
    complete = end is not None and not x.get("beyond") and not x.get("missing")
    margin = hours = None
    if due is not None and end is not None and due_day:
        margin = margin_days(end, str(due_day)[:10], cal)
        hours = round(cal.hours_between(end, due), 1) if end <= due else -round(cal.hours_between(due, end), 1)
    state, reason = state_of(end=end, due=due, margin=margin, folga=folga, beyond=x.get("beyond"), horizon_end=horizon_end,
                             missing=x.get("missing") or [])
    x.update(margin_days=margin if complete or state == LATE else None, shift_hours=hours if complete or state == LATE else None,
             state=state, reason=reason, complete=complete,
             already_late=bool(due_day and str(due_day)[:10] < today_iso))


# ---------------------------------------------------------------- cache e leituras

def current(sector: str, *, allow_stale: bool = False, now: datetime | None = None) -> dict:
    """A previsão do setor. Uma entrada por setor; as leituras (`allow_stale`) recebem a anterior enquanto a nova
    se calcula uma vez em segundo plano (cache.py, vez única)."""
    planning.check_area(sector)
    ki = _key_inputs(sector, now)

    def build():
        with planning.connect(readonly=True) as c:
            src = _sources(c, sector)
        return compute(sector, ki, src)
    today = ki["today"]
    return _cache.get(sector, ki["key"], build, allow_stale=allow_stale, stale_if=lambda old: old[-1] == today,
                      refresh=lambda: current(sector))


def stamp(sector: str) -> str:
    """O carimbo da previsão atual (chave do quadro): o que a previsão segue, sem a calcular."""
    return needs.digest(needs.serial(_key_inputs(sector)["key"]))


def _when(value):
    return value.isoformat() if isinstance(value, (datetime, date)) else value


def summary(sector: str) -> dict:
    """Resumo: recurso limitante, contagens de risco, por máquina (fim da fila, recuperação, horas atrasadas) e
    fiabilidade."""
    f = current(sector, allow_stale=True)
    machines = sorted(f["machines"].values(), key=lambda m: str(m["name"]))
    return needs.serial({
        "sector": sector, "today": f["today"], "origin": f["origin"], "horizon_end": f["horizon_end"], "folga": f["folga"],
        "limiting": [{k: s[k] for k in ("id", "name", "machines", "recovery", "recovers", "peak_hours", "peak_weeks", "late_hours",
                                        "hours", "suggested_hours")} for s in f["limiting"]],
        "counts": f["counts"], "reliability": f["reliability"],
        "machines": [{k: m[k] for k in ("id", "name", "queue_end", "operations", "beyond", "hours", "recovery", "recovers",
                                        "overloaded", "peak_hours", "late_hours", "has_calendar", "slot")} for m in machines],
        "slots": f["slots"], "unschedulable": f["reliability"]["unschedulable"], "check": len(f["check"]),
        "elapsed": f["elapsed"], "stale": f["stale"], "rules": __doc__.split("\n\n", 1)[1].strip()})


ESTADOS = ("todas", LATE, AT_RISK, NO_FORECAST, OK, "ja_em_atraso", "sem_prazo")


def orders(sector: str, estado: str = "todas") -> dict:
    """Lista de OF com a conclusão prevista, a margem, o estado e o motivo; `estado` filtra («todas» por defeito)."""
    estado = estado or "todas"
    if estado not in ESTADOS:
        raise planning.PlanningError("Estado inválido.")
    f = current(sector, allow_stale=True)
    out = []
    for o in f["orders"].values():
        tag = "ja_em_atraso" if o.get("already_late") else (o["state"] or "sem_prazo")
        if estado != "todas" and tag != estado:  # «atrasa» sem as que já estavam em atraso (contadas à parte)
            continue
        out.append({"of": o["of"], "customer": o["customer"], "conclusion": o.get("end"), "beyond": o.get("beyond"),
                    "due": o.get("due"), "due_day": o.get("due_day"), "margin_days": o.get("margin_days"),
                    "shift_hours": o.get("shift_hours"), "state": o["state"], "already_late": o.get("already_late"),
                    "reason": REASON_TEXT.get(o.get("reason"), o.get("reason")), "approximate": o["approximate"],
                    "machines": o["machines"], "lines": o["lines"], "planned_lines": o["planned_lines"]})
    out.sort(key=lambda o: (_rank(o["state"]), str(o["due_day"] or "9999"), o["margin_days"] if o["margin_days"] is not None else 10 ** 6, o["of"]))
    return needs.serial({"sector": sector, "estado": estado, "today": f["today"], "origin": f["origin"],
                         "orders": out, "total": len(out), "stale": f["stale"]})


def invalidate() -> None:
    _cache.clear()
