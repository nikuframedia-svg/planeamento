"""Edição manual do Gantt simples (Etapa 4, 08/10/2026): os ajustes («âncoras») e a sua gravação.

Regras (a primeira vai escrita no ecrã):
- «Uma alteração feita no Gantt fica até a retirares ou até a OF deixar de ter trabalho planeado nessa máquina; o
  cálculo automático nunca a apaga.»
- Um ajuste = setor + OF + máquina + dia, ou dia e hora. Abrange todo o trabalho Planeado aberto da OF nessa máquina:
  as operações ficam seguidas a partir do dia (00:00 → a primeira abertura) ou da hora (dispatch.py). Em hora fechada
  passa para a abertura seguinte, com aviso; por cima de outro ajuste, o mais recente fica logo a seguir, com aviso;
  num dia que já passou, o resto vai à frente da fila, «(já passou)». Os conflitos são avisos, nunca bloqueios.
- Um só estado: ativo. Acaba ao ser retirado ou desfeito, quando outro ajuste da mesma OF e máquina o substitui, ou
  quando a OF deixa de ter trabalho Planeado nessa máquina (concluída, Limpar, mudou de máquina). Este último fim
  deduz-se na leitura, sem gravar, com o motivo; a gravação seguinte do setor regista-o (com as entradas atuais),
  para o ajuste não voltar quando a OF for planeada outra vez.
- Mudar de máquina: só máquinas do setor com calendário e com horas para a operação principal. Grava a escolha da
  Carteira (member_machine.write_choice, origem «gantt»): a Carteira, a Carga e o Gantt ficam iguais. Até as
  ocorrências se refazerem, a previsão põe a OF na máquina nova com as horas da anterior («horas a recalcular»).
  Fora da ficha técnica é aviso.
- Desfazer: acaba o ajuste e repõe a máquina só se a escolha atual da Carteira ainda for a que o ajuste gravou (em
  todas as linhas); senão desfaz só o ajuste e diz porquê. Repõe também o ajuste que este tinha substituído.
- Retirar: acaba o ajuste; a máquina escolhida fica na Carteira.
- O Excel nunca muda: a Data Corte e a Tabela ficam.
- Impacto: a previsão calcula-se antes e depois com as mesmas entradas (forecast.inputs, leituras que aceitam a
  versão anterior): OF que acabam mais tarde (Δ em dias úteis, as 10 maiores), novas «atrasa» e células que passam
  a Completa. A Carga semanal é pelo prazo e não muda com os ajustes.
Sem a migração 053: as leituras devolvem vazio e a gravação responde 503.
"""
from __future__ import annotations

import re
import uuid
from collections import defaultdict
from contextlib import nullcontext
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb

from .. import planning, planning_needs as needs, planning_registration as registration

LISBON = ZoneInfo("Europe/Lisbon")
NOT_INSTALLED = "A edição manual do Gantt ainda não está instalada (migração 053)."
RULE = ("Uma alteração feita no Gantt fica até a retirares ou até a OF deixar de ter trabalho planeado nessa máquina; "
        "o cálculo automático nunca a apaga.")
ACTIONS = ("mover", "retirar", "desfazer")
DAYS_BEFORE, DAYS_AFTER = 31, 730  # dias aceites num ajuste, a contar de hoje (revisão 08/10)
FIELDS = ("setor", "acao", "of", "de", "maquina", "dia", "hora", "turno", "ajuste_id")
ENDED = {"retirada": "Retirada", "desfeita": "Desfeita", "substituida": "Substituída por outra alteração",
         "concluida": "A OF já não tem trabalho em aberto (concluída ou saiu da carteira)",
         "mudou_de_maquina": "A OF mudou de máquina", "sem_planeado": "A OF deixou de estar Planeado nesta máquina"}
RECALCULATING = ("Horas a recalcular: a máquina mudou na Carteira; as horas desta máquina chegam quando a Carga se "
                 "refizer (cerca de 1 minuto).")


# ---------------------------------------------------------------- leitura

def installed(c) -> bool:
    return bool(c.execute("SELECT to_regclass('planning_mtg.sector_plan_adjustments') t").fetchone()["t"])


def _row(r) -> dict:
    return {"id": str(r["id"]), "of": r["production_order_no"], "resource_id": r["resource_id"],
            "machine_name": r["machine_name"], "day": r["day"], "start_at": r["start_at"], "author": r["created_by"],
            "created_at": r["created_at"], "revision": r["revision"], "previous_machine": r["previous_machine"]}


_COLUMNS = "id, production_order_no, resource_id, machine_name, day, start_at, created_by, created_at, revision, previous_machine"


def _active(c, sector: str) -> list[dict]:
    return [_row(r) for r in c.execute(f"SELECT {_COLUMNS} FROM planning_mtg.sector_plan_adjustments "
                                       "WHERE area = %s AND active ORDER BY created_at, id", (sector,)).fetchall()]


def snapshot(c, sector: str) -> tuple[list[dict], int | None]:
    """(ajustes ativos do setor, id do último evento) — o último evento entra na chave da previsão."""
    if not installed(c):
        return [], None
    last = c.execute("SELECT max(id) AS n FROM planning_mtg.sector_plan_adjustment_events WHERE area = %s",
                     (sector,)).fetchone()["n"]
    return _active(c, sector), last


def read(sector: str, *, allow_stale: bool = True) -> list[dict]:
    """Os ajustes do setor como a previsão os vê: «ativa» (com as chaves das operações e os avisos) ou «terminada»
    com o motivo (deduzido na leitura, sem gravar)."""
    from . import forecast
    return forecast.current(sector, allow_stale=allow_stale).get("anchors") or []


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _order(anchor: dict) -> str:
    return f"{_utc(anchor['created_at']).astimezone(timezone.utc).isoformat()}|{anchor['id']}"


def window(anchor: dict, origin: datetime) -> tuple[datetime, datetime | None]:
    """(início pedido, fim do dia ou None). Dia: 00:00 de Lisboa (a previsão passa à primeira abertura); o dia de hoje
    começa no turno em curso (a origem), sem aviso. Hora: o instante gravado."""
    if anchor.get("start_at"):
        return _utc(anchor["start_at"]), None
    day = anchor["day"] if isinstance(anchor["day"], date) else date.fromisoformat(str(anchor["day"])[:10])
    start = datetime.combine(day, time.min, LISBON).astimezone(timezone.utc)
    until = datetime.combine(day + timedelta(days=1), time.min, LISBON).astimezone(timezone.utc)
    if start < origin < until:
        start = origin
    return start, until


def mark(ops: list[dict], meta: dict, anchors: list[dict], origin: datetime, *, pools=None, occ_stamp=None) -> dict:
    """Marca as operações dos ajustes para o despacho (no próprio dicionário de cada operação). Puro.

    Cada ajuste, pela ordem de criação: todas as operações Planeado (âmbito 0) programáveis da OF nessa máquina,
    seguidas (`anchor.id`). Um ajuste que mudou a OF de máquina, enquanto as ocorrências forem as de antes
    (`occ_stamp` igual ao gravado), leva também as operações principais dessas linhas da máquina anterior, com as horas
    de lá («horas a recalcular»). Devolve {"keys": {id: [chaves]}, "moved": [chaves mudadas de máquina]}.
    """
    pool_of = {}
    for post, members in (pools or {}).items():
        for rid in (post, *members):
            pool_of[rid] = post
    info = {"keys": defaultdict(list), "moved": []}
    taken = set()
    for a in sorted(anchors, key=_order):
        previous = a.get("previous_machine") or {}
        source, lines = previous.get("from"), {x["key"] for x in previous.get("lines") or []}
        if source and source != a["resource_id"] and lines and previous.get("occ_stamp") == occ_stamp:
            for op in ops:
                if (op.get("scope") == 0 and not op.get("reason") and op.get("of") == a["of"] and op.get("resource_id") == source
                        and op.get("line_key") in lines and (meta.get(op["key"]) or {}).get("phase", "principal") == "principal"):
                    op["resource_id"], op["pool"] = a["resource_id"], pool_of.get(a["resource_id"])
                    info["moved"].append(op["key"])
        start, until = window(a, origin)
        for op in ops:
            if (op["key"] in taken or op.get("scope") != 0 or op.get("reason") or op.get("of") != a["of"]
                    or op.get("resource_id") != a["resource_id"]):
                continue
            op["anchor"] = {"start": start, "until": until, "id": a["id"], "order": _order(a)}
            taken.add(op["key"])
            info["keys"][a["id"]].append(op["key"])
    return info


def _hour(value) -> str | None:
    return _utc(value).astimezone(LISBON).strftime("%H:%M") if value else None


def evaluate(anchors: list[dict], ops: list[dict], meta: dict, info: dict, placed: dict, names: dict) -> list[dict]:
    """Os ajustes como se mostram: «ativa» com as chaves, o início e o fim previstos e os avisos; ou «terminada» com
    o motivo, quando a OF deixou de ter trabalho Planeado nessa máquina (só na leitura). Puro."""
    present, planned = set(), defaultdict(set)  # OF com alguma operação; máquinas com Planeado de cada OF
    for op in ops:
        present.add(op.get("of"))
        if op.get("scope") == 0:
            planned[op.get("of")].add(op.get("resource_id"))
    out = []
    for a in sorted(anchors, key=_order):
        keys = list(info["keys"].get(a["id"], []))
        item = {"id": a["id"], "of": a["of"], "resource_id": a["resource_id"],
                "machine": names.get(a["resource_id"]) or a["machine_name"],
                "day": (a["day"].isoformat() if isinstance(a["day"], date) else str(a["day"])[:10]),
                "hour": _hour(a.get("start_at")), "author": a["author"], "created_at": a["created_at"], "keys": keys,
                "moved": [k for k in info["moved"] if k in keys], "start": None, "end": None, "warnings": [],
                "state": "ativa", "reason": None, "reason_text": None}
        if keys:
            got = [placed[k] for k in keys if k in placed]
            warnings = []
            for r in got:
                for w in r.get("warnings") or ():
                    if w not in warnings:
                        warnings.append(w)
            starts = [r["start"] for r in got if r.get("start") is not None]
            ends = [r["end"] for r in got if r.get("end") is not None]
            item.update(start=min(starts) if starts else None, end=max(ends) if ends and len(ends) == len(got) else None,
                        warnings=warnings)
        elif a["resource_id"] in planned.get(a["of"], ()):
            item["warnings"] = ["sem_previsao"]  # trabalho Planeado sem horas/saldo: fica ativo, sem caixa
        else:
            reason = ("concluida" if a["of"] not in present else
                      "mudou_de_maquina" if planned.get(a["of"], set()) - {a["resource_id"]} else "sem_planeado")
            item.update(state="terminada", reason=reason, reason_text=ENDED[reason])
        out.append(item)
    return out


def warning_text(code: str, operations: dict | None = None, *, start=None) -> str:
    """Texto de um aviso de ajuste (nunca bloqueia)."""
    if code.startswith("sobreposta:"):
        key = code.split(":", 1)[1]
        of = ((operations or {}).get(key) or {}).get("of")
        return f"Sobrepõe a {of}: fica logo a seguir" if of else "Sobrepõe outra alteração: fica logo a seguir"
    if code == "fora_de_horario":
        when = f" ({_utc(start).astimezone(LISBON).strftime('%d/%m %H:%M')})" if start else ""
        return f"Fora do turno: começa na abertura seguinte{when}"
    return {"ja_passou": "O dia já passou: o que falta vai à frente da fila",
            "horas_a_recalcular": RECALCULATING,
            "sem_previsao": "Sem previsão nesta máquina (sem horas ou saldo por confirmar)"}.get(code, code)


# ---------------------------------------------------------------- máquinas candidatas

class Fit:
    """Horas e ficha técnica de operações noutra máquina, pela regra única da Carteira e da Carga (estimates.hours_on)
    e pelas candidatas da ficha técnica (as mesmas de assignments.alternatives)."""

    def __init__(self, sector: str):
        from . import assignments, occurrences
        self.occ = occurrences.load(sector, allow_stale=True)
        self.facts = {f["key"]: f for f in self.occ["facts"]}
        with planning.connect(readonly=True) as c:
            self.evidence = assignments._evidence(c, self.occ)
        self._spec: dict[str, set | None] = {}
        self._hours: dict[tuple, bool] = {}

    def _in_spec(self, key: str) -> set | None:
        if key not in self._spec:
            row = self.occ["_rows"].get(key) if self.evidence else None
            self._spec[key] = None if not row else {
                c.get("resource_id") for c in self.evidence["index"].candidates(row, self.evidence["codes"])
                if c.get("resource_id") and c.get("eligibility") != "excluded"}
        return self._spec[key]

    def _has_hours(self, key: str, rid: str) -> bool:
        from . import estimates
        if (key, rid) not in self._hours:
            fact = self.facts.get(key)
            if fact is None:
                found = None
            elif self.evidence is None:
                found = fact["hours"] if estimates.documentary_on(fact, rid) else None
            else:
                found = estimates.hours_on(fact, rid, **self.evidence["hours"])[0]
            self._hours[(key, rid)] = found is not None
        return self._hours[(key, rid)]

    def __call__(self, fact_keys, rids) -> dict:
        """{máquina: {"hours": todas as operações têm horas lá, "in_spec": todas estão na ficha técnica}}."""
        out = {}
        for rid in rids:
            hours = bool(fact_keys) and all(self._has_hours(k, rid) for k in fact_keys)
            spec = all(rid in s for s in (self._in_spec(k) for k in fact_keys) if s is not None)
            out[rid] = {"hours": hours, "in_spec": spec}
        return out


def candidates(sector: str, boxes: list[dict], fc: dict, fit: Fit | None = None) -> dict:
    """{(OF, máquina): [{id, name, in_spec}]}: as outras máquinas do setor com calendário e horas para as operações
    principais da caixa. Uma caixa só com operações seguintes não muda de máquina (lista vazia)."""
    meta = fc["meta"]
    machines = sorted((rid for rid, m in fc["machines"].items() if m.get("has_calendar")), key=lambda r: str(fc["machines"][r]["name"]))
    fit = fit or Fit(sector)
    out = {}
    for box in boxes:
        key = (box["of"], box["resource_id"])
        facts = sorted({meta[k]["fact_key"] for k in box.get("keys") or () if k in meta and meta[k].get("phase") == "principal"})
        if key in out or not facts:
            out.setdefault(key, [])
            continue
        found = fit(facts, [rid for rid in machines if rid != box["resource_id"]])
        out[key] = [{"id": rid, "name": fc["machines"][rid]["name"], "in_spec": f["in_spec"]} for rid, f in found.items() if f["hours"]]
    return out


# ---------------------------------------------------------------- impacto

def impact(before: dict, after: dict, count_days, *, limit: int = 10) -> dict:
    """Antes e depois com as mesmas entradas: OF que acabam mais tarde (Δ dias úteis), novas «atrasa» e células que
    passam a Completa. `count_days(a, b)` = dias úteis em (a, b]."""
    from .forecast import LATE
    names = after.get("names") or {}
    later = []
    for of, o in after["orders"].items():
        b = before["orders"].get(of)
        if not b or b.get("end") is None or o.get("end") is None or o["end"] <= b["end"]:
            continue
        days = count_days(b["end"].astimezone(LISBON).date(), o["end"].astimezone(LISBON).date())
        if days > 0:
            later.append({"of": of, "before": b["end"], "after": o["end"], "days": days})
    later.sort(key=lambda x: (-x["days"], str(x["of"])))
    new_late = sorted(({"of": of, "due_day": o.get("due_day")} for of, o in after["orders"].items()
                       if o.get("state") == LATE and not o.get("already_late")
                       and (before["orders"].get(of) or {}).get("state") != LATE), key=lambda x: str(x["of"]))
    old = {(rid, c["date"], c["shift"]): c["state"] for rid, cells in before.get("cells", {}).items() for c in cells}
    complete = [{"machine": names.get(rid) or rid, "resource_id": rid, "date": c["date"], "shift": c["shift"]}
                for rid, cells in sorted(after.get("cells", {}).items(), key=lambda x: str(x[0])) for c in cells
                if c["state"] == "completa" and old.get((rid, c["date"], c["shift"])) != "completa"]
    return {"later": later[:limit], "later_count": len(later), "new_late": new_late[:limit], "new_late_count": len(new_late),
            "complete": complete[:limit], "complete_count": len(complete)}


# ---------------------------------------------------------------- gravação

def _uuid(value, message: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise planning.PlanningError(message) from None


def _day(value) -> date:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        raise planning.PlanningError("Dia inválido.") from None


def _start_hour(payload: dict, template) -> time | None:
    """Hora pedida («HH:MM») ou o início do turno pedido (1.º, 2.º…); nenhuma = o dia."""
    hour, shift = payload.get("hora"), payload.get("turno")
    if hour not in (None, ""):
        found = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", str(hour))
        if not found:
            raise planning.PlanningError("Hora inválida (usa HH:MM).")
        return time(int(found[1]), int(found[2]))
    if shift not in (None, ""):
        try:
            n = int(shift)
        except (TypeError, ValueError):
            raise planning.PlanningError("Turno inválido.") from None
        if not 1 <= n <= len(template):  # turno 0 ou negativo escolhia o último em silêncio (revisão 08/10)
            raise planning.PlanningError("Turno inválido.")
        start = template[n - 1][0]
        return time(int(start[:2]), int(start[3:5]))
    return None


def _event(c, adjustment_id, sector, action, actor, request_id, detail) -> None:
    c.execute("INSERT INTO planning_mtg.sector_plan_adjustment_events (adjustment_id, area, action, actor, request_id, detail) "
              "VALUES (%s, %s, %s, %s, %s, %s)", (adjustment_id, sector, action, actor, request_id, Jsonb(needs.serial(detail))))


def _end(c, sector, row_id, reason, action, actor, request_id) -> bool:
    done = c.execute("UPDATE planning_mtg.sector_plan_adjustments SET active = false, ended_at = now(), ended_reason = %s, "
                     "revision = revision + 1 WHERE id = %s AND area = %s AND active RETURNING id", (reason, row_id, sector)).fetchone()
    if done:
        _event(c, row_id, sector, action, actor, uuid.uuid5(request_id, f"{row_id}:{action}"), {"motivo": reason})
    return bool(done)


def _repeated(c, request_id, action, content):
    found = c.execute("SELECT detail FROM planning_mtg.sector_plan_adjustment_events WHERE request_id = %s AND action = %s",
                      (request_id, action)).fetchone()
    if not found:
        return None
    if found["detail"].get("pedido") != content:
        raise planning.PlanningError("Este pedido já foi usado com outro conteúdo. Recarrega a página.", 409)
    return {**(found["detail"].get("resultado") or {}), "repeated": True}


def _locked(c, sector, payload) -> dict:
    row_id = _uuid(payload.get("ajuste_id"), "Indica a alteração.")
    found = c.execute(f"SELECT {_COLUMNS}, active FROM planning_mtg.sector_plan_adjustments WHERE id = %s AND area = %s FOR UPDATE",
                      (row_id, sector)).fetchone()
    if not found or not found["active"]:
        raise planning.PlanningError("Esta alteração já não está ativa. Recarrega o plano.", 409)
    return _row(found)


def _summary(row: dict, state: str, reason: str | None = None) -> dict:
    return {"id": row["id"], "of": row["of"], "resource_id": row["resource_id"], "machine": row["machine_name"],
            "day": row["day"], "hour": _hour(row.get("start_at")), "author": row["author"], "state": state,
            "reason": reason, "reason_text": ENDED.get(reason) if reason else None}


def _move(c, sector, payload, before, ki, actor, request_id, fit) -> tuple[dict, list[str], list[str]]:
    from . import member_machine
    of = str(payload.get("of") or "").strip()
    if not of:
        raise planning.PlanningError("Indica a OF.")
    machines, ops, meta = before["machines"], before["operations"], before["meta"]
    target = str(payload.get("maquina") or "")
    if target not in machines or not machines[target].get("has_calendar"):
        raise planning.PlanningError("Escolhe uma máquina deste setor com turnos.")
    name = lambda rid: (machines.get(rid) or {}).get("name") or rid  # noqa: E731
    day = _day(payload.get("dia"))
    today = ki.get("today") or date.today()
    if not today - timedelta(days=DAYS_BEFORE) <= day <= today + timedelta(days=DAYS_AFTER):
        raise planning.PlanningError("Dia fora do plano.")
    hour = _start_hour(payload, ki["settings"]["template"])
    source = str(payload.get("de") or "") or None
    if source is None:
        rids = sorted({r["resource_id"] for r in ops.values() if r["scope"] == 0 and r["of"] == of}, key=str)
        source = target if target in rids else rids[0] if len(rids) == 1 else None
        if source is None:
            raise planning.PlanningError(f"Indica de que máquina sai a {of}." if rids else f"A {of} não tem trabalho Planeado no plano.", 409)
    keys = [k for k, r in ops.items() if r["scope"] == 0 and r["of"] == of and r["resource_id"] == source]
    if not keys:
        raise planning.PlanningError(f"A {of} não tem trabalho Planeado na {name(source)}. Recarrega o plano.", 409)
    notes, previous = [], None
    if target != source:
        principal = [k for k in keys if meta[k].get("phase", "principal") == "principal"]
        if not principal:
            raise planning.PlanningError("Esta caixa só tem operações seguintes: só a operação principal muda de máquina. "
                                         "Muda o dia, ou muda a máquina na Carteira.")
        facts = sorted({meta[k]["fact_key"] for k in principal})
        found = (fit or Fit(sector))(facts, [target])[target]
        if not found["hours"]:
            raise planning.PlanningError(f"A {name(target)} não tem horas para esta operação: escolhe outra máquina.", 409)
        if not found["in_spec"]:
            notes.append("Máquina fora da ficha técnica")
        if len(principal) < len(keys):
            rest = len(keys) - len(principal)
            notes.append(f"{rest} {'operação seguinte fica' if rest == 1 else 'operações seguintes ficam'} na {name(source)}")
        wanted = {meta[k]["line_key"] for k in principal}
        lines = [x for x in ki["data"]["lines"] if x["key"] in wanted]
        if not lines:
            raise planning.PlanningError("As linhas desta OF mudaram na importação. Recarrega o plano.", 409)
        written = member_machine.write_choice(c, sector, lines, {"id": target, "name": name(target)}, "gantt", actor=actor,
                                              request_id=uuid.uuid5(request_id, "gantt-maquina"),
                                              detail={"of": of, "de": name(source), "pedido": str(request_id)})
        previous = {"from": source, "from_name": name(source), "to": target, "to_name": name(target),
                    "occ_stamp": (ki.get("occ") or {}).get("stamp"), "lines": written}
    found_rows = c.execute(
        "SELECT id, previous_machine FROM planning_mtg.sector_plan_adjustments WHERE area = %s AND production_order_no = %s "
        "AND resource_id = ANY(%s) AND active ORDER BY created_at FOR UPDATE", (sector, of, sorted({source, target}))).fetchall()
    replaced = [str(r["id"]) for r in found_rows]
    if previous is None:
        # Novo dia na mesma máquina de uma OF que lá chegou por um ajuste: herda a mudança de máquina (as operações
        # continuam a ser levadas da máquina anterior até as ocorrências se refazerem). Herdada = o Desfazer desta não
        # repõe a Carteira; repõe o ajuste substituído, que a repõe no seu próprio Desfazer (revisão 08/10).
        for r in reversed(found_rows):
            prior = r["previous_machine"] or {}
            if prior.get("to") == target and prior.get("lines"):
                previous = {**prior, "inherited": True}
                break
    for row_id in replaced:
        _end(c, sector, row_id, "substituida", "substituir", actor, request_id)
    new_id = uuid.uuid5(request_id, "ajuste")
    start_at = datetime.combine(day, hour, LISBON) if hour else None
    row = c.execute(f"""INSERT INTO planning_mtg.sector_plan_adjustments
                            (id, area, production_order_no, resource_id, machine_name, day, start_at, created_by, previous_machine, request_id,
                             created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, clock_timestamp()) RETURNING {_COLUMNS}""",
                    (new_id, sector, of, target, name(target), day, start_at, actor,
                     Jsonb(needs.serial(previous)) if previous else None, request_id)).fetchone()
    return _row(row), notes, replaced


def _restore_machine(c, sector, row, ki, actor, request_id) -> str | None:
    """Desfazer: repõe a escolha anterior da Carteira só se a atual ainda for a que o ajuste gravou (todas as linhas)."""
    from . import machine_choice, member_machine
    previous = row.get("previous_machine") or {}
    lines = previous.get("lines") or []
    if not lines or previous.get("inherited"):  # herdada: quem repõe a Carteira é o ajuste substituído (reposto)
        return None
    ctx = machine_choice.context(sector, conn=c)

    def still(line):
        return any((ctx["members"].get(k) or {}).get("resource_id") == previous["to"]
                   and (ctx["members"].get(k) or {}).get("revision") == line["revision"] for k in line["keys"])
    if not all(still(x) for x in lines):
        return ("A máquina não foi reposta: a escolha da Carteira mudou depois desta alteração. "
                "Só a fixação foi desfeita.")
    by_key = {x["key"]: x for x in ki["data"]["lines"]}
    groups = defaultdict(list)
    for x in lines:
        line = by_key.get(x["key"])
        if line is None:
            continue
        before = x.get("before")
        groups[(before["resource_id"], before["machine_name"]) if before else None].append(line)
    for machine, group in sorted(groups.items(), key=lambda g: str(g[0])):
        member_machine.write_choice(c, sector, group, {"id": machine[0], "name": machine[1]} if machine else None, "gantt",
                                    actor=actor, request_id=uuid.uuid5(request_id, f"gantt-desfazer:{machine}"),
                                    detail={"of": row["of"], "desfazer": row["id"], "pedido": str(request_id)}, ctx=ctx)
    return f"Máquina reposta: {previous.get('from_name') or previous.get('from')}."


def _undo(c, sector, row, ki, actor, request_id) -> list[str]:
    notes = []
    c.execute("UPDATE planning_mtg.sector_plan_adjustments SET active = false, ended_at = now(), ended_reason = 'desfeita', "
              "revision = revision + 1 WHERE id = %s", (row["id"],))
    told = _restore_machine(c, sector, row, ki, actor, request_id)
    if told:
        notes.append(told)
    moved = c.execute("SELECT detail FROM planning_mtg.sector_plan_adjustment_events WHERE adjustment_id = %s AND action = 'mover'",
                      (row["id"],)).fetchone()
    for old_id in ((moved or {}).get("detail") or {}).get("substituiu") or []:
        old = c.execute(f"SELECT {_COLUMNS}, active, ended_reason FROM planning_mtg.sector_plan_adjustments WHERE id = %s FOR UPDATE",
                        (old_id,)).fetchone()
        if not old or old["active"] or old["ended_reason"] != "substituida":
            continue
        busy = c.execute("SELECT 1 FROM planning_mtg.sector_plan_adjustments WHERE area = %s AND production_order_no = %s "
                         "AND resource_id = %s AND active", (sector, old["production_order_no"], old["resource_id"])).fetchone()
        if busy:
            continue
        c.execute("UPDATE planning_mtg.sector_plan_adjustments SET active = true, ended_at = NULL, ended_reason = NULL, "
                  "revision = revision + 1 WHERE id = %s", (old_id,))
        _event(c, old_id, sector, "repor", actor, uuid.uuid5(request_id, f"{old_id}:repor"), {"desfazer": row["id"]})
        when = old["day"].strftime("%d/%m") + (f" {_hour(old['start_at'])}" if old["start_at"] else "")
        notes.append(f"Volta a alteração anterior: {old['production_order_no']} → {when} ({old['machine_name']}).")
    return notes


def _sweep(c, sector, evaluated, actor, request_id) -> list[str]:
    """Regista o fim dos ajustes que a leitura já dá como terminados (a OF deixou de ter Planeado nessa máquina)."""
    ended = []
    for a in evaluated:
        if a["state"] == "terminada" and _end(c, sector, a["id"], a["reason"], "terminar", actor, request_id):
            ended.append(a["id"])
    return ended


def apply(payload: dict, *, conn=None, inputs=None, fit=None) -> dict:
    """Rota única POST /planeamento/api/setor/quadro/ajustes {setor, acao: mover|retirar|desfazer, of, de?, maquina,
    dia, hora? | turno?, ajuste_id?, request_id} → {ajuste, impacto, avisos, acao, repeated}.

    Uma transação com o bloqueio do setor; o mesmo request_id com a mesma ação devolve o resultado gravado.
    `inputs` = (ki, src) da previsão e `fit` (máquinas candidatas) só para os testes.
    """
    from . import forecast, portfolio
    sector = portfolio.check_sector(str(payload.get("setor") or ""))
    action = str(payload.get("acao") or "")
    if action not in ACTIONS:
        raise planning.PlanningError("Ação inválida.")
    request_id = _uuid(payload.get("request_id"), "Pedido sem identificador; recarrega a página.")
    actor = registration.human_actor(payload)
    content = needs.digest({k: payload.get(k) for k in FIELDS})
    # As entradas da previsão leem-se antes da transação e do bloqueio (ligações próprias, só leitura; a frio podem
    # demorar): dentro ficam só os ajustes ativos, a gravação e as duas previsões (revisão 08/10).
    if inputs is None:
        with (planning.connect(readonly=True) if conn is None else nullcontext(conn)) as c:
            if not installed(c):  # sem a 053 responde logo, sem ler a previsão
                raise planning.PlanningError(NOT_INSTALLED, 503)
        inputs = forecast.inputs(sector)
    ki, src = inputs
    with (planning.connect() if conn is None else nullcontext(conn)) as c:
        if not installed(c):
            raise planning.PlanningError(NOT_INSTALLED, 503)
        c.execute("SELECT pg_advisory_xact_lock(hashtext('sector_plan_adjustments:' || %s))", (sector,))
        repeated = _repeated(c, request_id, action, content)
        if repeated is not None:
            return repeated
        before = forecast.compute(sector, ki, src, anchors=_active(c, sector))
        # Com entradas antigas (a refazer) não se grava o fim de nenhum ajuste: podia ser só atraso das ocorrências.
        swept = [] if ki.get("stale") else _sweep(c, sector, before["anchors"], actor, request_id)
        notes, replaced, detail = [], [], {}
        if action == "mover":
            row, notes, replaced = _move(c, sector, payload, before, ki, actor, request_id, fit)
            detail = {"of": row["of"], "maquina": row["resource_id"], "dia": row["day"], "hora": _hour(row["start_at"]),
                      "substituiu": replaced, "maquina_anterior": row["previous_machine"]}
        else:
            row = _locked(c, sector, payload)
            if action == "retirar":
                c.execute("UPDATE planning_mtg.sector_plan_adjustments SET active = false, ended_at = now(), "
                          "ended_reason = 'retirada', revision = revision + 1 WHERE id = %s", (row["id"],))
                if (row.get("previous_machine") or {}).get("lines") and not row["previous_machine"].get("inherited"):
                    notes.append(f"A máquina fica a {row['machine_name']} na Carteira (usa Desfazer para a repor).")
            else:
                notes = _undo(c, sector, row, ki, actor, request_id)
        after = forecast.compute(sector, ki, src, anchors=_active(c, sector))
        rule = forecast.Rule(ki["settings"].get("workdays") or [], ki["settings"].get("holidays") or ())
        effect = impact(before, after, rule.count)
        warnings = list(notes)
        if action == "mover":
            item = next((a for a in after["anchors"] if a["id"] == row["id"]), None)
            adjustment = item or _summary(row, "ativa")
            for code in (item or {}).get("warnings") or ():
                text = warning_text(code, after["operations"], start=(item or {}).get("start"))
                if text not in warnings:
                    warnings.append(text)
            order = after["orders"].get(row["of"]) or {}
            if order.get("state") == forecast.LATE and (before["orders"].get(row["of"]) or {}).get("state") != forecast.LATE:
                warnings.append(f"Passa a atrasada (prazo {_short(order.get('due_day'))})")
        else:
            adjustment = _summary(row, "terminada", "retirada" if action == "retirar" else "desfeita")
        result = needs.serial({"acao": action, "ajuste": adjustment, "impacto": effect, "avisos": warnings,
                               "terminados": swept, "repeated": False, "regra": RULE})
        _event(c, row["id"], sector, action, actor, request_id, {**detail, "pedido": content, "resultado": result})
    return result


def _short(value) -> str:
    text = str(value or "")[:10]
    return f"{text[8:10]}/{text[5:7]}" if len(text) == 10 else "—"


def save(payload: dict) -> dict:
    """Grava e devolve também o quadro novo (o Gantt já com o ajuste). Se o quadro falhar, a gravação fica e o ecrã
    recarrega-o."""
    import logging
    from . import board
    result = apply(payload)
    try:
        result["quadro"] = needs.serial(board.board(str(payload.get("setor")), allow_stale=True, fresh_plan=True))
    except Exception:
        logging.getLogger(__name__).exception("Quadro depois do ajuste indisponível")
        result["quadro"] = None
    return result
