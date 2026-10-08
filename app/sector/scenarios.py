"""Cenários e replaneamento (Etapa 5, ponto 8, 08/10/2026).

Um cenário é uma lista ordenada de alterações simuladas sobre o plano em uso. Simular nunca muda o plano em uso:
as alterações são funções puras sobre as entradas do motor de previsão (forecast._key_inputs/_sources), com a
MESMA origem e as MESMAS entradas da referência.

Alterações (kind → efeito na simulação → o que «Aplicar» grava):
- cancelar OF / OV (obra; o campo ov pode ter várias OV separadas por vírgula) / linha → tira as operações
  → Excluir na Carteira (selection.apply, motivo «Cenário «…»: cancelada»);
- maquina_parada [de, até) → subtrai às janelas (reservas horárias em memória, partidas por semana) →
  shifts.reserve (reserved_windows nos calendários das semanas afetadas);
- turnos (máquina, dia ou semana, n.º de turnos) → shifts.simulate (definition_for + expand, só em memória) →
  shifts.apply (semana marcada «manual»);
- pessoas_em_falta (dia, turno, n.º) → simula parar cada máquina com trabalho nesse turno e escolhe as que
  acrescentam menos atraso (OF que passam a atrasar, depois horas de atraso, depois o nome) até libertar as
  pessoas em falta; o utilizador pode trocar (params.maquinas) → NUNCA se aplica (só simulação);
- urgente (OF) → 0.ª PRIORIDADE na fila da máquina, dentro do seu âmbito (o resto nunca passa à frente do Planeado)
  → substituição de prazo com «urgente» (priority.save_override);
- prazo (OF, data) → muda o prazo da operação principal → substituição de prazo (priority.save_override).
As máquinas sugeridas ficam as de agora (o cenário nunca muda a máquina de uma linha).

Comparação (compare): referência e cenário calculados com as mesmas entradas, em segundo plano (cache.BACKGROUND),
isolados da cache do plano em uso (nunca escrevem em forecast._cache). Diferença: OF que passam a atrasar / deixam
de atrasar, Δ da conclusão por OF em dias úteis, máquinas (fila e recuperação antes → depois), máquina × semana,
pessoas por dia × turno. «Porquê»: uma corrida por alteração, cumulativas, só nos grupos de máquinas (máquina ou
posto partilhado) que a alteração mexe; cada mudança atribui-se à primeira alteração que a provoca e a cadeia de
causas segue o motivo do início (start_reason: começa depois da OF X).

Aplicar: confirmação no ecrã com as mudanças reais, request_id, uma só transação. Depois, a lista «Aplicado» com
Desfazer por alteração (só repõe o que ainda está como o cenário o deixou) e a previsão nova comparada com a
simulada.
"""
from __future__ import annotations

import logging
import threading
import uuid
from collections import OrderedDict, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb

from .. import planning, planning_needs as needs
from . import cache, dispatch, forecast, shifts

log = logging.getLogger(__name__)
LISBON = ZoneInfo("Europe/Lisbon")
KINDS = ("cancelar", "maquina_parada", "turnos", "pessoas_em_falta", "urgente", "prazo")
KIND_TEXT = {"cancelar": "Cancelar", "maquina_parada": "Máquina parada", "turnos": "Turnos", "pessoas_em_falta": "Pessoas em falta",
             "urgente": "Urgente", "prazo": "Prazo"}
ACTIONS = ("criar", "alterar", "retirar_alteracao", "aplicar", "desfazer_aplicada", "descartar")
NOT_INSTALLED = "Os cenários ainda não estão instalados (migração 054)."
NOT_FOUND = "Cenário não encontrado."
CHANGED = "O cenário mudou entretanto. Recarrega a página."
MOVED_SECONDS = 15 * 60          # uma conclusão que muda menos do que isto não conta como mudança
MAX_CHANGES = 40
MAX_STOP_DAYS = 120
SUGGESTED_TEXT = "As máquinas sugeridas ficam as de agora; a atribuição das causas segue a ordem das alterações."


# ================================================================ alterações: validação e texto (puro)

def _text(value, limit=200) -> str:
    return " ".join(str(value or "").split())[:limit]


def _local(value) -> datetime:
    """'AAAA-MM-DDTHH:MM' (hora de Lisboa) ou ISO com fuso → instante UTC."""
    try:
        found = datetime.fromisoformat(str(value))
    except ValueError:
        raise planning.PlanningError("Data e hora inválidas.") from None
    if found.tzinfo is None:
        found = found.replace(tzinfo=LISBON)
    return found.astimezone(timezone.utc)


def _day(value) -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise planning.PlanningError("Dia inválido.") from None


def split_ov(value) -> list[str]:
    return [x.strip() for x in str(value or "").replace(";", ",").split(",") if x.strip()]


def validate_change(kind: str, target, params, *, machines: dict, shifts_count: int = 3) -> tuple[dict, dict]:
    """(alvo, parâmetros) normalizados de uma alteração; recusa o que não se entende."""
    target = target if isinstance(target, dict) else {}
    params = params if isinstance(params, dict) else {}
    if kind not in KINDS:
        raise planning.PlanningError("Tipo de alteração inválido.")

    def machine():
        rid = str(target.get("maquina") or "")
        if rid not in machines:
            raise planning.PlanningError("Escolhe uma máquina do setor.")
        return rid

    def order():
        of = _text(target.get("of"), 40).upper()
        if not of:
            raise planning.PlanningError("Indica a OF.")
        return of
    if kind == "cancelar":
        if target.get("linha"):
            return {"linha": _text(target["linha"], 300), "of": _text(target.get("of"), 40).upper() or None,
                    "referencia": _text(target.get("referencia"), 80) or None}, {}
        if target.get("ov"):
            return {"ov": _text(target["ov"], 40)}, {}
        if target.get("referencia"):
            return {"of": order(), "referencia": _text(target["referencia"], 80)}, {}
        return {"of": order()}, {}
    if kind == "maquina_parada":
        rid = machine()
        start, end = _local(params.get("de")), _local(params.get("ate"))
        if end <= start:
            raise planning.PlanningError("O fim da paragem tem de ser depois do início.")
        if end - start > timedelta(days=MAX_STOP_DAYS):
            raise planning.PlanningError(f"Uma paragem tem no máximo {MAX_STOP_DAYS} dias.")
        return {"maquina": rid}, {"de": start.isoformat(), "ate": end.isoformat()}
    if kind == "turnos":
        rid = machine()
        try:
            n = int(params.get("turnos"))
        except (TypeError, ValueError):
            raise planning.PlanningError("Número de turnos inválido.") from None
        if not 0 <= n <= shifts.MAX_SHIFTS:
            raise planning.PlanningError(f"Os turnos vão de 0 a {shifts.MAX_SHIFTS}.")
        if params.get("dia"):
            return {"maquina": rid}, {"dia": _day(params["dia"]).isoformat(), "turnos": n}
        try:
            y, w = int(params.get("ano")), int(params.get("semana"))
            date.fromisocalendar(y, w, 1)
        except (TypeError, ValueError):
            raise planning.PlanningError("Indica o dia ou a semana.") from None
        return {"maquina": rid}, {"ano": y, "semana": w, "turnos": n}
    if kind == "pessoas_em_falta":
        try:
            shift, n = int(params.get("turno")), int(params.get("n"))
        except (TypeError, ValueError):
            raise planning.PlanningError("Indica o turno e quantas pessoas faltam.") from None
        if not 1 <= shift <= shifts_count:
            raise planning.PlanningError("Turno inválido.")
        if not 1 <= n <= 50:
            raise planning.PlanningError("Indica quantas pessoas faltam (1 a 50).")
        out = {"dia": _day(params.get("dia")).isoformat(), "turno": shift, "n": n}
        chosen = params.get("maquinas")
        if chosen:
            if not isinstance(chosen, list) or any(str(x) not in machines for x in chosen):
                raise planning.PlanningError("Escolhe máquinas do setor.")
            out["maquinas"] = sorted({str(x) for x in chosen})
        return {}, out
    if kind == "urgente":
        return {"of": order()}, {}
    of = order()  # prazo
    return {"of": of}, {"data": _day(params.get("data")).isoformat()}


def _dm(day) -> str:
    d = _day(day)
    return f"{d.day:02}/{d.month:02}"


def _dmh(instant) -> str:
    local = datetime.fromisoformat(instant).astimezone(LISBON) if isinstance(instant, str) else instant.astimezone(LISBON)
    return f"{local.day:02}/{local.month:02} {local.hour:02}:{local.minute:02}"


def label(change: dict, names: dict | None = None) -> str:
    """Texto curto de uma alteração (o que o ecrã mostra e o «porquê» cita)."""
    names = names or {}
    kind, t, p = change["kind"], change.get("target") or {}, change.get("params") or {}
    machine = names.get(t.get("maquina")) or t.get("maquina")
    if kind == "cancelar":
        if t.get("linha"):
            return f"Cancelar a linha {t.get('of') or ''} {t.get('referencia') or ''}".replace("  ", " ").strip()
        if t.get("referencia"):
            return f"Cancelar a {t['of']} · {t['referencia']}"
        return f"Cancelar a OV {t['ov']}" if t.get("ov") else f"Cancelar a {t['of']}"
    if kind == "maquina_parada":
        return f"{machine} parada de {_dmh(p['de'])} a {_dmh(p['ate'])}"
    if kind == "turnos":
        n = p["turnos"]
        what = f"{n} turno{'s' if n != 1 else ''}"
        return f"{machine}: {what} em {_dm(p['dia'])}" if p.get("dia") else f"{machine}: {what} na semana {p['semana']}"
    if kind == "pessoas_em_falta":
        n = p["n"]
        return f"Falta{'m' if n != 1 else ''} {n} pessoa{'s' if n != 1 else ''} no {p['turno']}.º turno de {_dm(p['dia'])}"
    if kind == "urgente":
        return f"{t['of']} urgente"
    return f"Prazo da {t['of']} passa a {_dm(p['data'])}"


# ================================================================ efeito nas entradas do motor (puro)

def _calendar_map(calendars: list[dict]) -> tuple[dict, list]:
    keyed, other = {}, []
    for d in calendars:
        try:
            keyed[(str(d["resource_id"]), int(d["year"]), int(d["week"]))] = d
        except (KeyError, TypeError, ValueError):
            other.append(d)
    return keyed, other


def _with_calendars(src: dict, keyed: dict, other: list) -> dict:
    return {**src, "calendars": other + [keyed[k] for k in sorted(keyed, key=lambda k: (k[0], k[1], k[2]))]}


def _with_facts(ki: dict, facts: list) -> dict:
    return {**ki, "occ": {**ki["occ"], "facts": facts}}


def matches(fact_or_line: dict, target: dict) -> bool:
    """A linha/ocorrência é do alvo de um «cancelar»: OF, OV (uma das OV do campo) ou linha."""
    if target.get("linha"):
        return (fact_or_line.get("line_key") or fact_or_line.get("key")) == target["linha"] or target["linha"] in (fact_or_line.get("aliases") or ())
    if target.get("ov"):
        wanted = target["ov"].casefold()
        return any(x.casefold() == wanted for x in split_ov(fact_or_line.get("ov")))
    if str(fact_or_line.get("of") or "").upper() != target.get("of"):
        return False
    return not target.get("referencia") or str(fact_or_line.get("reference") or "").casefold() == target["referencia"].casefold()


def shift_interval(day: date, shift: int, template) -> tuple[datetime, datetime]:
    """[início, fim) do turno n.º `shift` do dia (hora de Lisboa; o 3.º turno acaba no dia seguinte)."""
    start, end = template[shift - 1]
    a = datetime.combine(day, time(int(start[:2]), int(start[3:5])), LISBON)
    stop = (0, 0) if end == "24:00" else (int(end[:2]), int(end[3:5]))
    b = datetime.combine(day, time(*stop), LISBON)
    if b <= a:
        b = datetime.combine(day + timedelta(days=1), time(*stop), LISBON)
    return a.astimezone(timezone.utc), b.astimezone(timezone.utc)


def stop_machine(src: dict, rid: str, start: datetime, end: datetime, reason: str) -> dict:
    """As janelas da máquina sem [início, fim): a mesma reserva horária que shifts.reserve grava, só em memória."""
    keyed, other = _calendar_map(src["calendars"])
    for year, week, a, b in shifts.week_pieces(start, end):
        d = keyed.get((rid, year, week))
        if d and not shifts.is_legacy(d):
            keyed[(rid, year, week)] = shifts.with_reservation(d, a, b, reason)
    return _with_calendars(src, keyed, other)


def apply_change(sector: str, ki: dict, src: dict, change: dict, *, names: dict | None = None) -> tuple[dict, dict, dict]:
    """(entradas, fontes, informação) depois de UMA alteração. Puro: nada é gravado nem lido da base."""
    kind, t, p = change["kind"], change.get("target") or {}, change.get("params") or {}
    text = label(change, names)
    info = {"machines": set(), "orders": set(), "label": text}
    if kind == "cancelar":
        facts = ki["occ"]["facts"]
        gone = [f for f in facts if matches(f, t)]
        info["orders"] = {str(f.get("of") or "") for f in gone}
        info["cancelled"] = len(gone)
        return _with_facts(ki, [f for f in facts if not matches(f, t)]), src, info
    if kind in ("urgente", "prazo"):
        out = []
        for f in ki["occ"]["facts"]:
            if str(f.get("of") or "").upper() != t["of"]:
                out.append(f)
                continue
            pr = dict(f.get("priority") or {})
            if kind == "urgente":
                pr.update(urgent=True, urgent_override=True)
            elif f.get("phase", "principal") == "principal":  # como a substituição (applies_to principal)
                day = _day(p["data"])
                pr.update(priority_date=datetime.combine(day + timedelta(days=1), time.min, LISBON).isoformat(),
                          priority_day=day.isoformat(), priority_field="override", parked=False)
            out.append({**f, "priority": pr})
        info["orders"] = {t["of"]}
        return _with_facts(ki, out), src, info
    if kind == "maquina_parada":
        info["machines"] = {t["maquina"]}
        return ki, stop_machine(src, t["maquina"], _local(p["de"]), _local(p["ate"]), text), info
    if kind == "turnos":
        keyed, other = _calendar_map(src["calendars"])
        machines = {m["id"]: m for m in src["machines"]}
        item = {"maquina": t["maquina"], "turnos": p["turnos"], **({"dia": p["dia"]} if p.get("dia") else {"ano": p["ano"], "semana": p["semana"]})}
        keyed = shifts.simulate(keyed, machines, ki["settings"], [item])
        info["machines"] = {t["maquina"]}
        return ki, _with_calendars(src, keyed, other), info
    if kind == "pessoas_em_falta":
        day, shift = _day(p["dia"]), int(p["turno"])
        if p.get("maquinas"):
            chosen = {"machines": list(p["maquinas"]), "ranking": [], "missing": 0, "chosen_by": "utilizador"}
        else:
            chosen = choose_stops(sector, ki, src, day, shift, int(p["n"]), names=names)
        start, end = shift_interval(day, shift, ki["settings"]["template"])
        for rid in chosen["machines"]:
            src = stop_machine(src, rid, start, end, text)
        info.update(machines=set(chosen["machines"]), people=chosen, shift_key=(day.isoformat(), shift), missing_people=int(p["n"]))
        return ki, src, info
    raise planning.PlanningError("Tipo de alteração inválido.")


# ================================================================ motor por grupos de máquinas (puro)

def prepare(sector: str, ki: dict, src: dict) -> tuple[list, dict, dict]:
    """(operações, meta, janelas): a primeira parte de forecast.compute, com as mesmas regras."""
    settings = ki["settings"]
    clients = [c for c in (settings.get("clientes_prioritarios") or []) if str(c or "").strip()]
    own = {m["id"] for m in src["machines"]}
    ops, meta = forecast.operations_from(ki["occ"]["facts"], sector=sector, planned=ki["planned"], own=own,
                                         pools=src["posts"], clients=clients)
    windows = forecast.label_windows([d for d in src["calendars"] if str(d.get("resource_id")) in own], settings["template"],
                                     ki["origin"])
    return ops, meta, windows


def _slot_groups(ops: list[dict], windows: dict, posts: dict) -> dict:
    """{grupo: (operações, janelas das máquinas do grupo)}: uma máquina sozinha ou um posto partilhado. O despacho
    de cada grupo não depende dos outros (dispatch.py)."""
    pool_of = {}
    for post, members in (posts or {}).items():
        for rid in (post, *members):
            pool_of[rid] = post
    groups = defaultdict(lambda: ([], {}))
    for op in ops:
        rid = op.get("resource_id")
        if op.get("reason") or not rid:
            continue
        slot = op.get("pool") or rid
        groups[slot][0].append(op)
    for rid, w in windows.items():
        slot = pool_of.get(rid, rid)
        if slot in groups:
            groups[slot][1][rid] = w
    return dict(groups)


def _signature(group) -> tuple:
    ops, wins = group
    return (tuple(sorted((op["key"], op.get("resource_id"), op.get("seconds"), op.get("scope"), tuple(op.get("priority_key") or ()),
                          str((op.get("anchor") or {}).get("start"))) for op in ops)),
            tuple(sorted((rid, tuple(w)) for rid, w in wins.items())))


def run_groups(groups: dict, origin: datetime, previous: dict | None = None) -> tuple[dict, dict, set]:
    """Despacha só os grupos que mudaram desde `previous` ({grupo: (assinatura, resultado por chave)}).
    Devolve (estado por grupo, resultado por chave, grupos recalculados)."""
    previous = previous or {}
    state, results, redone = {}, {}, set()
    for slot, group in groups.items():
        sig = _signature(group)
        old = previous.get(slot)
        if old is not None and old[0] == sig:
            state[slot] = old
        else:
            out = dispatch.dispatch(group[0], group[1], origin)["operations"]
            state[slot] = (sig, {k: {"end": r["end"], "status": r["status"], "start_reason": r["start_reason"],
                                     "resource_id": r["resource_id"], "of": r["of"], "due": r["due"],
                                     "unplaced": r["unplaced_seconds"], "segments": r["segments"]} for k, r in out.items()})
            redone.add(slot)
        results.update(state[slot][1])
    return state, results, redone


def _lateness(r: dict) -> float:
    """Segundos de atraso de uma operação (as que ficam além do horizonte contam com o que falta)."""
    due = r.get("due")
    if due is None:
        return 0.0
    if r.get("end") is None:
        return float(r.get("unplaced") or 0) + 1.0
    return max(0.0, (r["end"] - due).total_seconds())


def choose_stops(sector: str, ki: dict, src: dict, day: date, shift: int, n: int, *, names: dict | None = None) -> dict:
    """Pessoas em falta: que máquinas parar nesse turno. Simula parar cada máquina com trabalho previsto nesse
    turno e escolhe as que acrescentam menos atraso (OF que passam a atrasar, depois horas de atraso acrescentadas,
    depois o nome), até libertar `n` pessoas (Definições: pessoas por máquina, defeito 1)."""
    names = names or {}
    ops, _, windows = prepare(sector, ki, src)
    origin = ki["origin"]
    groups = _slot_groups(ops, windows, src["posts"])
    _, base, _ = run_groups(groups, origin)
    label_key = (day.isoformat(), shift)
    working = sorted({r["resource_id"] for r in base.values() for s in r["segments"] if (s[2], s[3]) == label_key})
    persons = forecast.persons_of(ki["settings"].get("pessoas_por_maquina"), working)
    start, end = shift_interval(day, shift, ki["settings"]["template"])
    pool_of = {}
    for post, members in (src.get("posts") or {}).items():
        for m in (post, *members):
            pool_of[m] = post
    ranking = []
    for rid in working:
        stopped = stop_machine(src, rid, start, end, "simulação")
        wins = forecast.label_windows([d for d in stopped["calendars"] if str(d.get("resource_id")) == rid],
                                      ki["settings"]["template"], origin)
        g_ops, g_wins = groups.get(pool_of.get(rid, rid), ([], {}))
        out = dispatch.dispatch(g_ops, {**g_wins, rid: wins.get(rid, [])}, origin)["operations"]
        before, after = defaultdict(float), defaultdict(float)  # atraso de cada OF (a sua operação mais atrasada)
        for k, r in out.items():
            if k in base:
                before[r["of"]] = max(before[r["of"]], _lateness(base[k]))
                after[r["of"]] = max(after[r["of"]], _lateness({**r, "unplaced": r["unplaced_seconds"]}))
        late_before = {of for of, v in before.items() if v > 0}
        late_after = {of for of, v in after.items() if v > 0}
        added = sum(after[of] - before[of] for of in after)
        ranking.append({"id": rid, "name": names.get(rid) or rid, "persons": persons.get(rid, 1),
                        "late_orders": len(late_after - late_before), "late_hours": round(max(added, 0) / 3600, 1)})
    ranking.sort(key=lambda x: (x["late_orders"], x["late_hours"], str(x["name"]), x["id"]))
    chosen, freed = [], 0
    for item in ranking:
        if freed >= n:
            break
        if item["persons"] <= 0:
            continue
        chosen.append(item["id"])
        freed += item["persons"]
    return {"machines": chosen, "ranking": ranking, "missing": max(0, n - freed), "chosen_by": "simulação"}


# ================================================================ diferença e «porquê» (puro)

def _late_day(end: datetime) -> date:
    return (end - timedelta(seconds=1)).astimezone(LISBON).date()


def workday_delta(before: datetime | None, after: datetime | None, cal: forecast.Calendar) -> int | None:
    """Δ da conclusão em dias úteis (dias com turnos no setor; fora dos calendários, a regra do setor)."""
    if before is None or after is None:
        return None
    a, b = _late_day(before), _late_day(after)
    if a == b:
        return 0
    if b > a:
        return cal.workdays(a.isoformat(), b.isoformat())
    return -cal.workdays(b.isoformat(), a.isoformat())


def _order_states(results: dict) -> dict:
    """{OF: (fim mais tarde, alguma além do horizonte, n.º de operações)} de um resultado por chave."""
    out = {}
    for r in results.values():
        of = r.get("of")
        end, beyond, n = out.get(of, (None, False, 0))
        if r["status"] == dispatch.BEYOND:
            beyond = True
        elif r["end"] is not None and (end is None or r["end"] > end):
            end = r["end"]
        out[of] = (end, beyond, n + 1)
    return out


def _differs(a, b) -> bool:
    if a is None or b is None:
        return a is not b
    if a[1] != b[1] or a[2] != b[2] or (a[0] is None) != (b[0] is None):
        return True
    return a[0] is not None and abs((a[0] - b[0]).total_seconds()) >= MOVED_SECONDS


def attribute(stages: list[dict], infos: list[dict], names: dict) -> dict:
    """{OF: texto do porquê}: a primeira alteração (corridas cumulativas) que muda a conclusão da OF, com a cadeia
    de causas pelo motivo do início (começa depois da OF X na máquina Y)."""
    states = [_order_states(s) for s in stages]
    whys = {}
    targeted = set().union(*[info["orders"] for info in infos]) if infos else set()
    for of in sorted(set().union(*[set(s) for s in states]) | targeted, key=str):
        hits = [k for k in range(1, len(stages)) if _differs(states[k - 1].get(of), states[k].get(of))]
        # Uma alteração que visa a própria OF (prazo, urgente, cancelar) conta mesmo sem mudar a conclusão.
        hits = sorted(set(hits) | {k for k, info in enumerate(infos, 1) if of in info["orders"]})
        if not hits:
            continue
        k = hits[0]
        info = infos[k - 1]
        tag = f"alteração {k}"
        text = f"{info['label']} ({tag})"
        if of in info["orders"]:
            why = text
        else:
            mine = [r for r in stages[k].values() if r.get("of") == of]
            last = max(mine, key=lambda r: (r["end"] is None, r["end"] or datetime.min.replace(tzinfo=timezone.utc)), default=None)
            rid = last["resource_id"] if last else None
            machine = names.get(rid) or rid
            reason = (last or {}).get("start_reason") or ""
            other = None
            if reason.startswith("ocupada:"):
                other = stages[k].get(reason.split(":", 1)[1], {}).get("of")
            a, b = states[k - 1].get(of), states[k].get(of)
            earlier = bool(a and b and a[0] and b[0] and not b[1] and b[0] < a[0])
            if rid and rid in info["machines"]:
                why = text
            elif earlier:
                why = f"A fila da {machine} ficou mais curta: {text}"
            elif other and other != of and other in info["orders"]:
                why = f"Começa depois da {other} na {machine}, que passou à frente: {text}"
            elif other and other != of:
                why = f"Começa depois da {other} na {machine}: {text}"
            elif machine:
                why = f"A fila da {machine} mudou: {text}"
            else:
                why = text
        if len(hits) > 1:
            why += " · também " + ", ".join(f"alteração {j}" for j in hits[1:])
        whys[of] = why
    return whys


def _week_of(day_iso: str) -> tuple[int, int]:
    y, w, _ = date.fromisoformat(day_iso).isocalendar()
    return y, w


def _weeks(cells: dict) -> dict:
    out = defaultdict(lambda: [0.0, 0.0])
    for rid, items in (cells or {}).items():
        for c in items:
            x = out[(rid, *_week_of(c["date"]))]
            x[0] += c["load"] or 0
            x[1] += c["capacity"] or 0
    return out


def _tag(o: dict | None) -> str | None:
    return None if o is None else o.get("state")


def difference(ref: dict, scen: dict, *, whys: dict, sector_days: forecast.Calendar, infos: list[dict]) -> dict:
    """O que muda do plano em uso para o cenário (puro: recebe os dois resultados de forecast.compute)."""
    names = {**ref.get("names", {}), **scen.get("names", {})}
    rows, late_new, late_gone, cancelled = [], [], [], []
    for of in sorted(set(ref["orders"]) | set(scen["orders"]), key=str):
        r, s = ref["orders"].get(of), scen["orders"].get(of)
        if s is None:
            cancelled.append(of)
            rows.append({"of": of, "customer": r["customer"], "due_day": r.get("due_day"), "before": r.get("end"), "after": None,
                         "state_before": r["state"], "state_after": None, "delta_days": None, "cancelled": True,
                         "why": whys.get(of) or "Cancelada no cenário"})
            continue
        if r is None:
            continue
        moved = _differs((r.get("end"), bool(r.get("beyond")), 0), (s.get("end"), bool(s.get("beyond")), 0))
        if not moved and r["state"] == s["state"] and r.get("due_day") == s.get("due_day"):
            continue
        if s["state"] == forecast.LATE and r["state"] != forecast.LATE:
            late_new.append(of)
        if r["state"] == forecast.LATE and s["state"] != forecast.LATE:
            late_gone.append(of)
        rows.append({"of": of, "customer": s["customer"], "due_day": s.get("due_day"), "due_day_before": r.get("due_day"),
                     "before": r.get("end"), "after": s.get("end"), "beyond_before": bool(r.get("beyond")),
                     "beyond_after": bool(s.get("beyond")), "state_before": r["state"], "state_after": s["state"],
                     "already_late": bool(s.get("already_late")),
                     "delta_days": workday_delta(r.get("end"), s.get("end"), sector_days),
                     "delta_hours": round((s["end"] - r["end"]).total_seconds() / 3600, 1) if r.get("end") and s.get("end") else None,
                     "cancelled": False, "why": whys.get(of) or "Sem mudança atribuída a uma alteração"})
    order = {forecast.LATE: 0, forecast.AT_RISK: 1, forecast.NO_FORECAST: 2, forecast.OK: 3, None: 4}
    rows.sort(key=lambda x: (x["cancelled"], 0 if x["of"] in late_new else 1, order.get(x["state_after"], 4),
                             -(x["delta_days"] or 0), str(x["due_day"] or "9999"), x["of"]))
    machines = []
    for rid in sorted(set(ref["machines"]) | set(scen["machines"]), key=lambda r: str(names.get(r) or r)):
        a, b = ref["machines"].get(rid) or {}, scen["machines"].get(rid) or {}
        keys = ("queue_end", "recovery", "recovers", "overloaded", "late_hours", "hours")
        if all(a.get(k) == b.get(k) for k in keys):
            continue
        machines.append({"id": rid, "name": names.get(rid) or rid, **{f"{k}_before": a.get(k) for k in keys},
                         **{f"{k}_after": b.get(k) for k in keys}})
    wa, wb = _weeks(ref.get("cells")), _weeks(scen.get("cells"))
    weeks = []
    for key in sorted(set(wa) | set(wb), key=lambda k: (str(names.get(k[0]) or k[0]), k[1], k[2])):
        x, y = wa.get(key, [0.0, 0.0]), wb.get(key, [0.0, 0.0])
        if abs(x[0] - y[0]) < 0.05 and abs(x[1] - y[1]) < 0.05:
            continue
        weeks.append({"id": key[0], "name": names.get(key[0]) or key[0], "year": key[1], "week": key[2],
                      "load_before": round(x[0], 1), "load_after": round(y[0], 1),
                      "capacity_before": round(x[1], 1), "capacity_after": round(y[1], 1)})
    pa = {(p["date"], p["shift"]): p for p in ref.get("people") or []}
    pb = {(p["date"], p["shift"]): p for p in scen.get("people") or []}
    people = []
    for key in sorted(set(pa) | set(pb), key=lambda k: (k[0], k[1] or 9)):
        x, y = pa.get(key) or {}, pb.get(key) or {}
        if all(x.get(k) == y.get(k) for k in ("machines", "need", "available", "deficit")):
            continue
        people.append({"date": key[0], "shift": key[1], **{f"{k}_before": x.get(k) for k in ("machines", "need", "available", "deficit")},
                       **{f"{k}_after": y.get(k) for k in ("machines", "need", "available", "deficit")}})
    deficit = lambda items: sum(1 for p in items or [] if (p.get("deficit") or 0) > 0)
    has_people = any(p.get("available") is not None for p in (ref.get("people") or []) + (scen.get("people") or []))
    over = lambda fc: sum(1 for s in fc.get("slots") or [] if s.get("overloaded"))
    stops = []
    for i, info in enumerate(infos, 1):
        if info.get("people"):
            pp = info["people"]
            stops.append({"change": i, "label": info["label"], "machines": [names.get(r) or r for r in pp["machines"]],
                          "chosen_by": pp.get("chosen_by"), "missing": pp.get("missing", 0),
                          "ranking": [{**x, "chosen": x["id"] in pp["machines"]} for x in pp.get("ranking", [])]})
    return {"counters": {"late_new": len(late_new), "late_gone": len(late_gone),
                         "over_capacity_before": over(ref), "over_capacity_after": over(scen),
                         "people_short_before": deficit(ref.get("people")) if has_people else None,
                         "people_short_after": deficit(scen.get("people")) if has_people else None,
                         "cancelled": len(cancelled)},
            "orders": rows, "orders_total": len(rows), "machines": machines, "weeks": weeks, "people": people,
            "people_defined": has_people, "stops": stops, "late_new": late_new, "late_gone": late_gone}


def _people_after(scen: dict, infos: list[dict]) -> None:
    """Pessoas em falta: menos pessoas disponíveis nesse turno (só quando estão definidas nas Definições)."""
    for info in infos:
        if not info.get("shift_key"):
            continue
        for p in scen.get("people") or []:
            if (p["date"], p["shift"]) == info["shift_key"] and p.get("available") is not None:
                p["available"] = max(0, p["available"] - info["missing_people"])
                p["deficit"] = max(0, p["need"] - p["available"])


def simulate(sector: str, ki: dict, src: dict, changes: list[dict], *, names: dict | None = None,
             explain: bool = True) -> dict:
    """Referência e cenário com as MESMAS entradas e a mesma origem; com `explain`, as corridas cumulativas
    (uma por alteração, só nos grupos de máquinas que mudam) para o «porquê». Puro."""
    names = {**(src.get("names") or {}), **{m["id"]: m["name"] for m in src["machines"]}, **(names or {})}
    ref = forecast.compute(sector, ki, src)
    cur_ki, cur_src, infos = ki, src, []
    stages, state = [], None
    if explain:
        ops, _, windows = prepare(sector, ki, src)
        state, results, _ = run_groups(_slot_groups(ops, windows, src["posts"]), ki["origin"])
        stages.append(results)
    for change in changes:
        cur_ki, cur_src, info = apply_change(sector, cur_ki, cur_src, change, names=names)
        infos.append(info)
        if explain:
            ops, _, windows = prepare(sector, cur_ki, cur_src)
            state, results, _ = run_groups(_slot_groups(ops, windows, cur_src["posts"]), ki["origin"], state)
            stages.append(results)
    scen = forecast.compute(sector, cur_ki, cur_src)
    _people_after(scen, infos)
    return {"reference": ref, "scenario": scen, "infos": infos, "stages": stages, "names": names, "ki": cur_ki, "src": cur_src}


def compare_inputs(sector: str, ki: dict, src: dict, changes: list[dict]) -> dict:
    """A comparação inteira (puro): o que o ecrã mostra."""
    sim = simulate(sector, ki, src, changes)
    ref, scen, infos = sim["reference"], sim["scenario"], sim["infos"]
    whys = attribute(sim["stages"], infos, sim["names"]) if changes else {}
    settings = ki["settings"]
    fallback = forecast.Rule(settings.get("workdays") or [], settings.get("holidays") or ())
    _, _, windows = prepare(sector, ki, src)
    sector_days = forecast.Calendar([w for ws in windows.values() for w in ws], fallback)
    diff = difference(ref, scen, whys=whys, sector_days=sector_days, infos=infos)
    diff.update(origin=ki["origin"], today=ki["today"], reference_stamp=ref.get("stamp"), suggested_text=SUGGESTED_TEXT,
                counts_before=ref["counts"], counts_after=scen["counts"],
                changes=[{"label": i["label"], "cancelled": i.get("cancelled")} for i in infos])
    return {"diff": diff, "scenario": scen}


# ================================================================ base de dados

def installed(c) -> bool:
    return bool(c.execute("SELECT to_regclass('planning_mtg.plan_scenarios') t").fetchone()["t"])


def _change_row(r: dict) -> dict:
    return {"id": str(r["id"]), "kind": r["kind"], "target": r["target"] or {}, "params": r["params"] or {}, "reason": r["reason"],
            "position": r["position"], "created_by": r["created_by"], "created_at": r["created_at"]}


def read(c, sector: str, scenario_id) -> tuple[dict, list[dict]]:
    """(cenário, alterações ativas pela ordem). 404 se não existir neste setor."""
    sid = needs.uid(scenario_id)
    row = c.execute("SELECT * FROM planning_mtg.plan_scenarios WHERE id=%s", (sid,)).fetchone()
    if not row or (sector and row["area"] != sector):
        raise planning.PlanningError(NOT_FOUND, 404)
    changes = c.execute("SELECT * FROM planning_mtg.plan_scenario_changes WHERE scenario_id=%s AND removed_at IS NULL "
                        "ORDER BY position", (sid,)).fetchall()
    return dict(row), [_change_row(r) for r in changes]


def _machines(c, sector: str) -> dict:
    from . import second_operation, settings as sector_settings
    return {m["id"]: m for m in sector_settings.machine_rows(c, sector) if not second_operation.machine(sector, m.get("process"))}


def listing(sector: str) -> dict:
    """GET dos cenários do setor (abertos e aplicados; os descartados ficam de fora). Sem a 054: vazio."""
    from . import settings as sector_settings
    planning.check_area(sector)
    with planning.connect(readonly=True) as c:
        machines = _machines(c, sector)
        settings = sector_settings.read(c, sector)
        base = {"sector": sector, "installed": False, "scenarios": [],
                "machines": sorted(({"id": m["id"], "name": m["name"], "default_shifts": m.get("default_shifts")}
                                    for m in machines.values()), key=lambda m: str(m["name"])),
                "shifts": len(settings["template"]), "people_defined": bool([x for x in settings.get("pessoas_por_turno") or [] if x not in (None, "")]),
                "kinds": KIND_TEXT, "suggested_text": SUGGESTED_TEXT}
        if not installed(c):
            return needs.serial(base)
        rows = c.execute("SELECT * FROM planning_mtg.plan_scenarios WHERE area=%s AND status <> 'arquivado' "
                         "ORDER BY created_at DESC LIMIT 50", (sector,)).fetchall()
        ids = [r["id"] for r in rows]
        changes = defaultdict(list)
        if ids:
            for r in c.execute("SELECT * FROM planning_mtg.plan_scenario_changes WHERE scenario_id = ANY(%s) AND removed_at IS NULL "
                               "ORDER BY position", (ids,)).fetchall():
                changes[r["scenario_id"]].append(_change_row(r))
    names = {m["id"]: m["name"] for m in machines.values()}
    out = []
    for r in rows:
        items = [{**ch, "label": label(ch, names), "kind_text": KIND_TEXT[ch["kind"]], "apply_text": apply_text(ch, names)}
                 for ch in changes[r["id"]]]
        summary = r["applied_summary"] or {}
        out.append({"id": str(r["id"]), "name": r["name"], "status": r["status"], "revision": r["revision"],
                    "created_by": r["created_by"], "created_at": r["created_at"], "applied_at": r["applied_at"],
                    "applied_by": r["applied_by"], "changes": items,
                    "applied": [{k: v for k, v in it.items() if k not in ("weeks", "members", "before", "after")}
                                for it in summary.get("items", [])]})
    return needs.serial({**base, "installed": True, "scenarios": out})


def apply_text(change: dict, names: dict) -> str:
    """O que «Aplicar» grava por esta alteração (a confirmação lista estas frases)."""
    kind = change["kind"]
    text = label(change, names)
    return {"cancelar": f"Excluir na Carteira as linhas de {text.replace('Cancelar a ', '').replace('Cancelar ', '')}",
            "maquina_parada": f"Calendário: reserva horária — {text}",
            "turnos": f"Calendário: {text}",
            "pessoas_em_falta": f"Não se grava (só simulação): {text}",
            "urgente": f"Substituição de prazo: {text}",
            "prazo": f"Substituição de prazo: {text}"}[kind]


# ---------------------------------------------------------------- gravações

def _request(payload) -> uuid.UUID:
    try:
        return uuid.UUID(str(payload.get("request_id")))
    except ValueError:
        raise planning.PlanningError("Pedido sem identificador; recarrega a página.") from None


def save(payload: dict, *, conn=None) -> dict:
    """POST dos cenários: {acao: criar|alterar|retirar_alteracao|aplicar|desfazer_aplicada|descartar, setor,
    request_id, expected_revision, …}. Repetir o mesmo request_id com o mesmo conteúdo devolve o mesmo resultado."""
    from contextlib import nullcontext
    from . import portfolio
    from .. import planning_registration as registration
    sector = portfolio.check_sector(str(payload.get("setor") or ""))
    action = str(payload.get("acao") or "")
    if action not in ACTIONS:
        raise planning.PlanningError("Ação inválida.")
    request_id = _request(payload)
    actor = registration.human_actor(payload)
    content = needs.digest({k: v for k, v in payload.items() if k != "request_id"})
    with (planning.connect() if conn is None else nullcontext(conn)) as c:
        if not installed(c):
            raise planning.PlanningError(NOT_INSTALLED, 503)
        c.execute("SELECT pg_advisory_xact_lock(hashtext('plan_scenarios:' || %s))", (sector,))
        found = c.execute("SELECT content_hash, result FROM planning_mtg.plan_scenario_requests WHERE request_id=%s",
                          (request_id,)).fetchone()
        if found:
            if found["content_hash"] != content:
                raise planning.PlanningError("Este pedido já foi usado com outro conteúdo. Recarrega a página.", 409)
            return {**found["result"], "repeated": True}
        handler = {"criar": _create, "alterar": _add_change, "retirar_alteracao": _remove_change, "aplicar": _apply,
                   "desfazer_aplicada": _undo, "descartar": _discard}[action]
        result = needs.serial(handler(c, sector, payload, actor, request_id))
        c.execute("INSERT INTO planning_mtg.plan_scenario_requests (request_id, area, scenario_id, action, content_hash, actor, result) "
                  "VALUES (%s,%s,%s,%s,%s,%s,%s)", (request_id, sector, result.get("id"), action, content, actor, Jsonb(result)))
    return {**result, "repeated": False}


def _locked(c, sector, payload, *, statuses=("aberto",)) -> tuple[dict, list[dict]]:
    row, changes = read(c, sector, payload.get("cenario"))
    c.execute("SELECT 1 FROM planning_mtg.plan_scenarios WHERE id=%s FOR UPDATE", (row["id"],))
    if payload.get("expected_revision") != row["revision"]:
        raise planning.PlanningError(CHANGED, 409)
    if row["status"] not in statuses:
        raise planning.PlanningError({"aplicado": "Este cenário já foi aplicado.", "arquivado": "Este cenário foi descartado.",
                                      "aberto": "Este cenário ainda não foi aplicado."}[row["status"]], 409)
    return row, changes


def _bump(c, row) -> int:
    return c.execute("UPDATE planning_mtg.plan_scenarios SET revision=revision+1, updated_at=now() WHERE id=%s RETURNING revision",
                     (row["id"],)).fetchone()["revision"]


def _create(c, sector, payload, actor, request_id) -> dict:
    name = _text(payload.get("nome"), 120)
    if not name:
        raise planning.PlanningError("Dá um nome ao cenário.")
    sid = uuid.uuid5(request_id, "cenario")
    c.execute("INSERT INTO planning_mtg.plan_scenarios (id, area, name, created_by) VALUES (%s,%s,%s,%s)", (sid, sector, name, actor))
    return {"id": str(sid), "revision": 1, "name": name}


def _add_change(c, sector, payload, actor, request_id) -> dict:
    from . import settings as sector_settings
    row, changes = _locked(c, sector, payload)
    if len(changes) >= MAX_CHANGES:
        raise planning.PlanningError(f"Um cenário tem no máximo {MAX_CHANGES} alterações.")
    machines = _machines(c, sector)
    template = sector_settings.read(c, sector)["template"]
    kind = str(payload.get("tipo") or "")
    target, params = validate_change(kind, payload.get("alvo"), payload.get("parametros"), machines=machines,
                                     shifts_count=len(template))
    position = c.execute("SELECT coalesce(max(position), 0) + 1 p FROM planning_mtg.plan_scenario_changes WHERE scenario_id=%s",
                         (row["id"],)).fetchone()["p"]
    cid = uuid.uuid5(request_id, "alteracao")
    c.execute("INSERT INTO planning_mtg.plan_scenario_changes (id, scenario_id, kind, target, params, reason, position, created_by) "
              "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", (cid, row["id"], kind, Jsonb(target), Jsonb(params),
                                                   _text(payload.get("motivo"), 500) or None, position, actor))
    names = {m["id"]: m["name"] for m in machines.values()}
    return {"id": str(row["id"]), "revision": _bump(c, row), "change": {"id": str(cid), "kind": kind, "target": target, "params": params,
                                                                         "label": label({"kind": kind, "target": target, "params": params}, names)}}


def _remove_change(c, sector, payload, actor, request_id) -> dict:
    row, changes = _locked(c, sector, payload)
    cid = needs.uid(payload.get("alteracao"))
    if not any(ch["id"] == str(cid) for ch in changes):
        raise planning.PlanningError("Esta alteração já não está no cenário.", 409)
    c.execute("UPDATE planning_mtg.plan_scenario_changes SET removed_at=now(), removed_by=%s WHERE id=%s AND removed_at IS NULL",
              (actor, cid))
    return {"id": str(row["id"]), "revision": _bump(c, row)}


def _discard(c, sector, payload, actor, request_id) -> dict:
    row, _ = _locked(c, sector, payload, statuses=("aberto", "aplicado"))
    c.execute("UPDATE planning_mtg.plan_scenarios SET status='arquivado' WHERE id=%s", (row["id"],))
    return {"id": str(row["id"]), "revision": _bump(c, row), "status": "arquivado"}


# ---------------------------------------------------------------- aplicar e desfazer

def _sub(request_id: uuid.UUID, change_id: str, what: str) -> str:
    return str(uuid.uuid5(request_id, f"{what}:{change_id}"))


def _week_state(c, rid, year, week) -> dict:
    row = shifts.calendar_row(c, rid, year, week)
    d = (row or {}).get("definition") or {}
    return {"exists": bool(row), "shift_plan": d.get("shift_plan"), "day_shifts": d.get("day_shifts") or {},
            "manual": bool(d.get("manual")), "reserved_windows": d.get("reserved_windows") or []}


def _apply_shifts(c, sector, ch, settings, machines, request_id, names) -> dict:
    t, p = ch["target"], ch["params"]
    item = {"maquina": t["maquina"], "turnos": p["turnos"], **({"dia": p["dia"]} if p.get("dia") else {"ano": p["ano"], "semana": p["semana"]})}

    def lookup(rid, y, w):
        row = shifts.calendar_row(c, rid, y, w)
        return ((row or {}).get("definition") or {}) if row else None
    keys = set(shifts.parse_changes([item], machines, settings, lookup))
    keys |= {(rid, *shifts._following(y, w)) for rid, y, w in keys}
    before = {k: _week_state(c, *k) for k in sorted(keys)}
    out = shifts.apply({"setor": sector, "mudancas": [item], "request_id": _sub(request_id, ch["id"], "turnos")}, conn=c)
    weeks = [{"maquina": k[0], "year": k[1], "week": k[2], "before": before[k], "after": _week_state(c, *k)} for k in sorted(keys)]
    return {"weeks": [w for w in weeks if w["before"] != w["after"]], "written": f"{out['changed']} semana(s) do calendário"}


def _apply_stop(c, sector, ch, machines, request_id, names) -> dict:
    t, p = ch["target"], ch["params"]
    out = shifts.reserve(c, machines[t["maquina"]], sector, _local(p["de"]), _local(p["ate"]), label(ch, names),
                         request_id=uuid.UUID(_sub(request_id, ch["id"], "paragem")))
    weeks = [{"maquina": t["maquina"], **w} for w in out["weeks"]]
    note = f"{len(weeks)} semana(s) do calendário"
    if out["skipped"]:
        note += f"; {len(out['skipped'])} semana(s) sem calendário ficaram de fora"
    return {"weeks": weeks, "written": note, "calendar": bool(weeks)}


def _apply_cancel(c, sector, ch, scenario_name, request_id) -> dict:
    from . import portfolio, selection
    data = portfolio.current(sector)
    decisions = selection.current(sector, conn=c)
    members = []
    for line in data["lines"]:
        if not matches(line, ch["target"]):
            continue
        found = portfolio.open_effective(line, decisions)
        if found["decision"] == "excluded":
            continue
        members.append({"key": line["key"], "of": line["of"], "reference": line["reference"], "before": found["decision"],
                        "quantity": found.get("planned_open") if found.get("planned_quantity") is not None else None})
    if not members:
        return {"members": [], "written": "Nada a excluir: as linhas já estavam excluídas ou fora da Carteira"}
    out = selection.apply({"setor": sector, "acao": "excluir", "motivo": f"Cenário «{scenario_name}»: cancelada",
                           "membros": [{"chave": m["key"]} for m in members], "request_id": _sub(request_id, ch["id"], "cancelar")},
                          data=data, conn=c)
    return {"members": members, "written": f"{out.get('changed', 0)} linha(s) excluídas na Carteira"}


def _override(c, sector, of):
    from . import priority
    found = priority.overrides(c).get((sector, of, priority.WHOLE))
    if not found:
        return None
    return {"definition": found["definition"], "revision": found["revision"], "reason": found.get("reason")}


def _apply_priority(c, sector, ch, scenario_name, request_id) -> dict:
    from . import priority
    of = ch["target"]["of"]
    prior = _override(c, sector, of)
    d = (prior or {}).get("definition") or {}
    payload = {"setor": sector, "of": of, "request_id": _sub(request_id, ch["id"], ch["kind"]),
               "expected_revision": (prior or {}).get("revision", 0), "motivo": f"Cenário «{scenario_name}»",
               "applies_to": d.get("applies_to") or "principal"}
    if ch["kind"] == "prazo":
        payload.update(due_date=ch["params"]["data"], urgente=bool(d.get("urgent")))
    else:
        payload.update(due_date=d.get("due_date"), field=None if d.get("due_date") else d.get("field"), urgente=True)
    priority.save_override(payload, conn=c)
    after = _override(c, sector, of)
    return {"of": of, "before": prior, "after": after, "written": "Substituição de prazo gravada"}


def _simulated_snapshot(sector: str, sid: str, revision: int) -> dict | None:
    """A previsão simulada (OF → fim e estado) da última comparação desta revisão, para comparar depois de aplicar."""
    with _lock:
        found = _results.get((sector, sid))
    if not found or found[0][1] != revision or found[1].get("error"):
        return None
    with _lock:
        fc = None
        for (s, i), (key, value) in _forecasts.items():
            if (s, i) == (sector, sid) and key[1] == revision:
                fc = value
    if fc is None:
        return None
    return {"at": datetime.now(timezone.utc).isoformat(),
            "orders": {of: {"end": o.get("end"), "state": o.get("state")} for of, o in fc["orders"].items()}}


def _apply(c, sector, payload, actor, request_id) -> dict:
    from . import settings as sector_settings
    row, changes = _locked(c, sector, payload)
    real = [ch for ch in changes if ch["kind"] != "pessoas_em_falta"]
    if not real:
        raise planning.PlanningError("Nada para aplicar: as pessoas em falta são só simulação.")
    machines = _machines(c, sector)
    names = {m["id"]: m["name"] for m in machines.values()}
    settings = sector_settings.read(c, sector)
    items, calendar = [], False
    for i, ch in enumerate(changes, 1):
        base = {"change_id": ch["id"], "position": i, "kind": ch["kind"], "label": label(ch, names), "undone_at": None}
        if ch["kind"] == "pessoas_em_falta":
            items.append({**base, "written": "Não se grava (só simulação)", "simulation_only": True})
            continue
        if ch["kind"] == "turnos":
            out = _apply_shifts(c, sector, ch, settings, machines, request_id, names)
        elif ch["kind"] == "maquina_parada":
            out = _apply_stop(c, sector, ch, machines, request_id, names)
            calendar = calendar or out.pop("calendar")
        elif ch["kind"] == "cancelar":
            out = _apply_cancel(c, sector, ch, row["name"], request_id)
        else:
            out = _apply_priority(c, sector, ch, row["name"], request_id)
        items.append({**base, **out})
    if calendar:
        shifts.finish_batch(c, request_id)
    summary = {"items": items, "simulated": _simulated_snapshot(sector, str(row["id"]), row["revision"])}
    c.execute("UPDATE planning_mtg.plan_scenarios SET status='aplicado', applied_at=now(), applied_by=%s, applied_summary=%s "
              "WHERE id=%s", (actor, Jsonb(needs.serial(summary)), row["id"]))
    return {"id": str(row["id"]), "revision": _bump(c, row), "status": "aplicado",
            "applied": [{k: it.get(k) for k in ("change_id", "label", "written")} for it in items]}


def _undo(c, sector, payload, actor, request_id) -> dict:
    from . import settings as sector_settings
    row, _ = _locked(c, sector, payload, statuses=("aplicado",))
    summary = row["applied_summary"] or {}
    cid = str(needs.uid(payload.get("alteracao")))
    item = next((it for it in summary.get("items", []) if it["change_id"] == cid), None)
    if item is None or item.get("simulation_only"):
        raise planning.PlanningError("Esta alteração não foi gravada por este cenário.", 409)
    if item.get("undone_at"):
        raise planning.PlanningError("Esta alteração já foi desfeita.", 409)
    machines = _machines(c, sector)
    settings = sector_settings.read(c, sector)
    sub = uuid.UUID(_sub(request_id, cid, "desfazer"))
    kept = []
    if item["kind"] in ("turnos", "maquina_parada"):
        changed = 0
        for w in sorted(item.get("weeks") or [], key=lambda w: (w["maquina"], w["year"], w["week"])):
            rid, y, wk = w["maquina"], w["year"], w["week"]
            now = shifts.calendar_row(c, rid, y, wk)
            d = (now or {}).get("definition") or {}
            if item["kind"] == "turnos":
                after = w["after"]
                if not now or d.get("shift_plan") != after["shift_plan"] or (d.get("day_shifts") or {}) != after["day_shifts"]:
                    kept.append(f"{y}-W{wk:02}")
                    continue
                b = w["before"]
                if b["exists"] and b["shift_plan"] is not None:
                    plan, days, manual = b["shift_plan"], b["day_shifts"], b["manual"]
                else:  # a semana foi criada pelo cenário: fica com os turnos padrão da máquina
                    n = machines[rid]["default_shifts"]
                    plan, days, manual = {str(x): (n if x in settings["workdays"] else 0) for x in range(1, 8)}, {}, False
                changed += shifts.write(c, machines[rid], sector, y, wk, plan, days, settings, manual=manual, request_id=sub,
                                        actor_payload={})
            else:
                if not now or (d.get("reserved_windows") or []) != w["after"]:
                    kept.append(f"{y}-W{wk:02}")
                    continue
                shifts.save_definition(c, machines[rid], sector, now, shifts.planning_calendars.validate({**d, "reserved_windows": w["before"]}),
                                       sub, "desfazer")
                changed += 1
        if changed:
            shifts.finish_batch(c, sub)
        note = f"{changed} semana(s) repostas"
        if kept:
            note += f"; ficaram como estão (mudaram depois): {', '.join(kept)}"
    elif item["kind"] == "cancelar":
        note = _undo_cancel(c, sector, item, sub)
    else:
        note = _undo_priority(c, sector, item, sub)
    item.update(undone_at=datetime.now(timezone.utc).isoformat(), undone_by=actor, undo_note=note)
    c.execute("UPDATE planning_mtg.plan_scenarios SET applied_summary=%s WHERE id=%s", (Jsonb(needs.serial(summary)), row["id"]))
    return {"id": str(row["id"]), "revision": _bump(c, row), "undone": cid, "note": note}


def _undo_cancel(c, sector, item, sub) -> str:
    from . import portfolio, selection
    data = portfolio.current(sector)
    decisions = selection.current(sector, conn=c)
    by_key = {}
    for line in data["lines"]:
        for k in (line["key"], *line.get("aliases", ())):
            by_key[k] = line
    clear, plan, kept = [], [], 0
    for m in item.get("members") or []:
        line = by_key.get(m["key"])
        if line is None or portfolio.decision_of(line, decisions) != "excluded":
            kept += 1  # já não está excluída (ou saiu da Carteira): nada a repor
            continue
        if m["before"] == "selected":
            plan.append({"chave": line["key"], **({"quantidade": m["quantity"]} if m.get("quantity") else {})})
        else:
            clear.append({"chave": line["key"]})
    done = 0
    if clear:
        done += selection.apply({"setor": sector, "acao": "limpar", "membros": clear, "request_id": str(uuid.uuid5(sub, "limpar"))},
                                data=data, conn=c).get("changed", 0)
    if plan:
        done += selection.apply({"setor": sector, "acao": "selecionar", "membros": plan, "request_id": str(uuid.uuid5(sub, "planear"))},
                                data=data, conn=c).get("changed", 0)
    note = f"{done} linha(s) repostas na Carteira"
    if kept:
        note += f"; {kept} já tinham mudado depois e ficaram como estão"
    return note


def _undo_priority(c, sector, item, sub) -> str:
    from . import priority
    of = item["of"]
    now = _override(c, sector, of)
    after = item.get("after")
    if not now or not after or now["revision"] != after["revision"]:
        return "O prazo desta OF mudou depois: ficou como está"
    before = item.get("before")
    payload = {"setor": sector, "of": of, "request_id": str(uuid.uuid5(sub, "prazo")), "expected_revision": now["revision"]}
    if not before:
        payload["limpar"] = True
    else:
        d = before["definition"] or {}
        payload.update(due_date=d.get("due_date"), field=None if d.get("due_date") else d.get("field"),
                       applies_to=d.get("applies_to") or "principal", urgente=bool(d.get("urgent")), motivo=before.get("reason") or "")
    priority.save_override(payload, conn=c)
    return "Prazo reposto"


# ================================================================ cálculo em segundo plano e leituras

_lock = threading.Lock()
_results: OrderedDict = OrderedDict()     # (setor, id) → ((chave das entradas, revisão, digest), diferença)
_forecasts: OrderedDict = OrderedDict()   # (setor, id) → ((chave das entradas, revisão, digest), previsão do cenário)
_running: dict = {}                        # (setor, id) → chave em cálculo
_compute_lock = threading.Lock()          # um cálculo de cenário de cada vez neste processo
KEEP_RESULTS, KEEP_FORECASTS = 12, 3


def _remember(store: OrderedDict, slot, key, value, keep: int) -> None:
    store[slot] = (key, value)
    store.move_to_end(slot)
    while len(store) > keep:
        store.popitem(last=False)


def _scenario_key(ki: dict, row: dict, changes: list[dict]) -> tuple:
    return (needs.digest(needs.serial(ki["key"])), row["revision"], needs.digest(needs.serial(changes)))


def _load(sector: str, scenario_id) -> tuple[dict, list]:
    with planning.connect(readonly=True) as c:
        if not installed(c):
            raise planning.PlanningError(NOT_FOUND, 404)
        return read(c, sector, scenario_id)


def _sources(sector: str) -> dict:
    with planning.connect(readonly=True) as c:
        return forecast._sources(c, sector)


def compute_for(setor: str, cenario_id=None) -> dict:
    """O resultado do motor (a mesma forma de forecast.current) com o cenário aplicado; sem cenário, a previsão em
    uso. Para as vistas Calendário e Capacidade e prazos (contrato com a parte V). Nunca escreve na cache da
    previsão em uso; guarda as últimas previsões de cenários numa memória própria e pequena."""
    planning.check_area(setor)
    if not cenario_id:
        return forecast.current(setor, allow_stale=True)
    row, changes = _load(setor, cenario_id)
    if row["status"] != "aberto":  # aplicado: o plano em uso já tem as alterações (não se aplicam duas vezes)
        return forecast.current(setor, allow_stale=True)
    ki = forecast._key_inputs(setor)
    key = _scenario_key(ki, row, changes)
    slot = (setor, str(row["id"]))
    with _lock:
        found = _forecasts.get(slot)
        if found and found[0] == key:
            return found[1]
    with _compute_lock:
        with _lock:
            found = _forecasts.get(slot)
            if found and found[0] == key:
                return found[1]
        src = _sources(setor)
        cur_ki, cur_src = ki, src
        names = {**(src.get("names") or {}), **{m["id"]: m["name"] for m in src["machines"]}}
        infos = []
        for ch in changes:
            cur_ki, cur_src, info = apply_change(setor, cur_ki, cur_src, ch, names=names)
            infos.append(info)
        result = forecast.compute(setor, cur_ki, cur_src)
        _people_after(result, infos)
        result = {**result, "scenario": {"id": str(row["id"]), "name": row["name"], "status": row["status"]}}
        with _lock:
            _remember(_forecasts, slot, key, result, KEEP_FORECASTS)
    return result


def _run(sector: str, row: dict, changes: list, ki: dict, key: tuple) -> None:
    slot = (sector, str(row["id"]))
    try:
        with cache.BACKGROUND.hold(cache.NORMAL), _compute_lock:
            src = _sources(sector)
            out = compare_inputs(sector, ki, src, changes)
        scen = {**out["scenario"], "scenario": {"id": str(row["id"]), "name": row["name"], "status": row["status"]}}
        value = needs.serial(out["diff"])
        with _lock:
            _remember(_results, slot, key, value, KEEP_RESULTS)
            _remember(_forecasts, slot, key, scen, KEEP_FORECASTS)
    except Exception as exc:  # o ecrã mostra o erro; o pedido seguinte volta a tentar
        log.exception("Cenário %s: a comparação falhou", slot)
        message = str(exc) if isinstance(exc, planning.PlanningError) else "A comparação falhou. Tenta outra vez."
        with _lock:
            _remember(_results, slot, key, {"error": message}, KEEP_RESULTS)
    finally:
        with _lock:
            if _running.get(slot) == key:
                del _running[slot]


def comparison(sector: str, scenario_id) -> dict:
    """GET da comparação: pronta, ou «a calcular» (o ecrã volta a pedir) enquanto corre em segundo plano.

    Cenário aplicado: a previsão em uso agora comparada com a que foi simulada antes de aplicar."""
    if sector:
        planning.check_area(sector)
    row, changes = _load(sector, scenario_id)
    sector = row["area"]
    if row["status"] == "aplicado":
        return _after_apply(sector, row)
    if row["status"] != "aberto":
        raise planning.PlanningError(NOT_FOUND, 404)
    ki = forecast._key_inputs(sector)
    key = _scenario_key(ki, row, changes)
    slot = (sector, str(row["id"]))
    with _lock:
        found = _results.get(slot)
        if found and found[0] == key:
            if found[1].get("error"):
                del _results[slot]  # mostra o erro uma vez; o pedido seguinte volta a calcular
                raise planning.PlanningError(found[1]["error"], 503)
            return {"pending": False, "revision": row["revision"], **found[1]}
        if slot not in _running:  # outra revisão ainda a calcular: o pedido seguinte começa esta
            _running[slot] = key
            threading.Thread(target=_run, args=(sector, row, changes, ki, key), name=f"cenario-{slot[1][:8]}", daemon=True).start()
        previous = found[1] if found and found[0][1] == row["revision"] and not found[1].get("error") else None
    return needs.serial({"pending": True, "revision": row["revision"], "previous": previous})


def _after_apply(sector: str, row: dict) -> dict:
    summary = row["applied_summary"] or {}
    simulated = (summary.get("simulated") or {}).get("orders")
    items = [{k: v for k, v in it.items() if k not in ("weeks", "members", "before", "after")} for it in summary.get("items", [])]
    out = {"pending": False, "applied": True, "revision": row["revision"], "items": items, "applied_at": row["applied_at"],
           "applied_by": row["applied_by"], "simulated": simulated is not None}
    if simulated is None:
        return needs.serial(out)
    fc = forecast.current(sector, allow_stale=True)
    diffs = []
    for of, s in simulated.items():
        o = fc["orders"].get(of)
        now_end = o.get("end") if o else None
        sim_end = datetime.fromisoformat(s["end"]) if s.get("end") else None
        if o is None:
            continue
        moved = (now_end is None) != (sim_end is None) or (now_end and sim_end and abs((now_end - sim_end).total_seconds()) >= MOVED_SECONDS)
        if moved or o.get("state") != s.get("state"):
            diffs.append({"of": of, "customer": o.get("customer"), "simulated": s.get("end"), "now": now_end,
                          "state_simulated": s.get("state"), "state_now": o.get("state")})
    diffs.sort(key=lambda x: x["of"])
    out.update(differences=diffs[:200], differences_total=len(diffs), stale=bool(fc.get("stale")), origin=fc.get("origin"))
    return needs.serial(out)


def compare(setor: str, cenario_id) -> dict:
    """Nome do plano para a comparação (referência e cenário em segundo plano): o mesmo que `comparison`."""
    return comparison(setor, cenario_id)
