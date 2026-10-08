"""Fila por máquina: o despacho da previsão com capacidade finita (Etapa 3, 08/10/2026).

Função pura, sem base de dados. Cada máquina consome as janelas livres do seu calendário pela ordem da chave de
prioridade, a partir da origem (o início do turno em curso). O trabalho pausa nos fechos do calendário e nos
blocos das âncoras. Uma explicação exata para cada operação: «acaba quando a máquina fizer as X h que tem à frente».

Regras:
- durações em SEGUNDOS INTEIROS (Σ dos segundos colocados = Σ dos segundos de entrada; a soma das horas bate com
  a da Carga sem arredondamentos por operação);
- ordem em cada máquina: âmbito (0 Planeado, 1 o resto) → `priority_key` → chave. O resto nunca passa à frente do
  Planeado na mesma máquina; só as âncoras saem desta regra;
- posto partilhado (`pool`, ex.: Fita pav.1 com o Doall e a Thomas): é UM recurso. Em cada momento corre, no posto,
  a operação de maior prioridade cuja máquina está aberta; uma operação começada continua até acabar ou até a sua
  máquina fechar (sem preempção a meio de uma janela);
- âncoras (Etapa 4, `anchor: {start, id?, order?, until?}`): colocadas primeiro, pela ordem de criação (`order`). Nunca
  começam em hora fechada: passam para a abertura seguinte, com o aviso «fora_de_horario» (numa âncora de dia,
  `until` = fim desse dia, só quando a abertura já fica depois do dia). Duas âncoras sobrepostas:
  a mais recente fica logo a seguir, com o aviso «sobreposta:<chave>». No passado: começa na origem, aviso
  «ja_passou». As operações da mesma âncora (`id`) ficam seguidas, sem aviso entre elas;
- não programáveis, com o motivo: o que vem em `reason` (estacionada, saldo_desconhecido, outro_setor,
  segunda_operacao…), sem máquina (`sem_maquina`), sem horas (`sem_horas`) e máquina sem janelas depois da origem
  (`sem_calendario`);
- o que não acaba dentro das janelas fica «alem_do_horizonte», com os segundos que faltam (`unplaced_seconds`).
Determinístico: a mesma entrada dá o mesmo resultado, seja qual for a ordem da lista (tudo se ordena por chaves
completas; nada depende da ordem de um set).
"""
from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict, deque
from datetime import datetime, timedelta

PLACED, BEYOND = "colocada", "alem_do_horizonte"
UNSCHEDULABLE = ("sem_maquina", "sem_horas", "sem_calendario", "estacionada", "saldo_desconhecido", "outro_setor",
                 "segunda_operacao")


def _order(op: dict) -> tuple:
    return (int(op.get("scope") or 0), tuple(op.get("priority_key") or ()), str(op["key"]))


def _label(label) -> tuple:
    if isinstance(label, (tuple, list)):
        return (label[0] if len(label) > 0 else None, label[1] if len(label) > 1 else None)
    return (label, None)


def _intervals(windows, origin: datetime) -> list[tuple[int, int, tuple]]:
    """Janelas em segundos desde a origem, cortadas na origem, ordenadas e sem sobreposições."""
    out = []
    for w in windows or ():
        start, end, label = w[0], w[1], (w[2] if len(w) > 2 else None)
        a, b = int((start - origin).total_seconds()), int((end - origin).total_seconds())
        a = max(a, 0)
        if b > a:
            out.append((a, b, _label(label)))
    out.sort(key=lambda x: (x[0], x[1]))
    clean = []
    for a, b, label in out:
        if clean and a < clean[-1][1]:
            a = clean[-1][1]
        if b > a:
            clean.append((a, b, label))
    return clean


def _subtract(intervals, blocks) -> list[tuple[int, int, tuple]]:
    """Intervalos livres = janelas menos blocos ocupados (lista ordenada de (a, b))."""
    if not blocks:
        return list(intervals)
    blocks = sorted(blocks)
    out, j = [], 0
    for a, b, label in intervals:
        cursor = a
        while j < len(blocks) and blocks[j][1] <= cursor:
            j += 1
        k = j
        while k < len(blocks) and blocks[k][0] < b:
            x, y = blocks[k]
            if x > cursor:
                out.append((cursor, min(x, b), label))
            cursor = max(cursor, y)
            if cursor >= b:
                break
            k += 1
        if cursor < b:
            out.append((cursor, b, label))
    return out


def _consume(free, start: int, seconds: int) -> tuple[list, int]:
    """Consome `seconds` dos intervalos livres a partir de `start`: (segmentos, segundos que faltam)."""
    segments, remaining = [], seconds
    i = bisect_right([iv[1] for iv in free], start)
    while remaining > 0 and i < len(free):
        a, b, label = free[i]
        a = max(a, start)
        if a < b:
            take = min(remaining, b - a)
            segments.append((a, a + take, label))
            remaining -= take
            start = a + take
        i += 1
    return segments, remaining


def _merge_segments(segments) -> list:
    out = []
    for a, b, label in segments:
        if out and out[-1][1] == a and out[-1][2] == label:
            out[-1] = (out[-1][0], b, label)
        else:
            out.append((a, b, label))
    return out


def dispatch(operations: list[dict], windows: dict, origin: datetime) -> dict:
    """Despacha as operações. `windows` = {resource_id: [(início UTC, fim UTC, (dia, turno))]}.

    Cada operação: {key, resource_id, seconds (int), priority_key (tupla), scope (0|1), of, line_key, due, due_field,
    pool (posto partilhado ou None), anchor ({start, id?, order?, until?} ou None), reason (não programável, opcional)}.
    """
    ops = sorted(operations, key=_order)
    result_ops: dict[str, dict] = {}
    unschedulable: list[dict] = []
    free_base = {rid: _intervals(w, origin) for rid, w in sorted((windows or {}).items(), key=lambda x: str(x[0]))}
    slot_of: dict[str, tuple] = {}
    schedulable = []
    for op in ops:
        reason = op.get("reason")
        rid = op.get("resource_id")
        if not reason:
            if not rid:
                reason = "sem_maquina"
            elif op.get("seconds") is None:
                reason = "sem_horas"
            elif not free_base.get(rid):
                reason = "sem_calendario"
        if reason:
            unschedulable.append({"key": op["key"], "reason": reason, "resource_id": rid, "of": op.get("of"),
                                  "line_key": op.get("line_key"), "scope": int(op.get("scope") or 0),
                                  "seconds": op.get("seconds")})
            continue
        slot_of.setdefault(rid, ("pool", op["pool"]) if op.get("pool") else ("res", rid))
        schedulable.append(op)

    blocks: dict[tuple, list] = defaultdict(list)          # slot → [(a, b)] ocupados pelas âncoras
    occupants: dict[tuple, list] = defaultdict(list)       # slot → [(fim, início, chave, máquina)]
    placed: dict[str, dict] = {}

    def record(op, segments, remaining, *, anchored=False, warnings=(), at=None):
        """Guarda a colocação; `at` = o instante de uma operação de 0 segundos (começa e acaba aí)."""
        segments = _merge_segments(segments)
        rid = op["resource_id"]
        start = segments[0][0] if segments else at
        end = segments[-1][1] if segments and not remaining else at
        placed[op["key"]] = {"op": op, "segments": segments, "remaining": remaining, "start": start, "end": end,
                             "anchored": anchored, "warnings": list(warnings)}
        for a, b, _ in segments:
            occupants[slot_of[rid]].append((b, a, op["key"], rid))

    # 1. Âncoras: pela ordem de criação; as da mesma âncora seguidas.
    anchors = [op for op in schedulable if op.get("anchor")]
    anchors.sort(key=lambda op: (str((op["anchor"] or {}).get("order") or ""), str((op["anchor"] or {}).get("id") or ""),
                                 _order(op)))
    group_end: dict[str, int] = {}
    for op in anchors:
        a = op["anchor"]
        rid, slot = op["resource_id"], slot_of[op["resource_id"]]
        warnings = []
        wanted = int((a["start"] - origin).total_seconds())
        group = str(a.get("id") or op["key"])
        if group in group_end:
            wanted = max(wanted, group_end[group])
        elif wanted < 0:
            wanted = 0
            warnings.append("ja_passou")
        free = _subtract(free_base[rid], blocks[slot])
        i = bisect_right([iv[1] for iv in free], wanted)
        first = max(free[i][0], wanted) if i < len(free) else None
        if group not in group_end and first is not None and first > wanted:
            # Porque não começou à hora: outra âncora ocupa a primeira abertura da máquina, ou a máquina está fechada.
            # `until` (âncora de dia, Etapa 4): começar mais tarde dentro desse dia não é aviso.
            base = free_base[rid]
            j = bisect_right([iv[1] for iv in base], wanted)
            opening = max(base[j][0], wanted) if j < len(base) else None
            until = a.get("until")
            until = int((until - origin).total_seconds()) if until is not None else None
            if opening is not None and first > opening:
                other = next((o for o in sorted(occupants[slot]) if o[1] <= opening < o[0]), None)
                warnings.append(f"sobreposta:{other[2]}" if other else "fora_de_horario")
            elif until is None or first >= until:
                warnings.append("fora_de_horario")
        segments, remaining = _consume(free, wanted, int(op["seconds"]))
        record(op, segments, remaining, anchored=True, warnings=warnings,
               at=(first if first is not None else wanted) if int(op["seconds"]) == 0 else None)
        blocks[slot].extend((s, e) for s, e, _ in placed[op["key"]]["segments"])
        group_end[group] = placed[op["key"]]["end"] if placed[op["key"]]["end"] is not None else wanted

    # 2. Filas: cada posto (ou máquina sozinha) consome as janelas livres pela ordem de prioridade.
    by_slot: dict[tuple, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for op in schedulable:
        if not op.get("anchor"):
            by_slot[slot_of[op["resource_id"]]][op["resource_id"]].append(op)
    for slot in sorted(by_slot, key=lambda s: (s[0], str(s[1]))):
        queues = by_slot[slot]
        free = {rid: _subtract(free_base[rid], blocks[slot]) for rid in queues}
        if len(queues) == 1:
            [(rid, queue)] = queues.items()
            _run_single(queue, free[rid], record)
        else:
            _run_pool(queues, free, record)

    # 3. Motivo do início de cada operação (pelo que ocupava a máquina ou o posto antes dela).
    ends = {slot: sorted(items) for slot, items in occupants.items()}
    end_keys = {slot: [x[0] for x in items] for slot, items in ends.items()}
    by_resource = defaultdict(list)
    for key, p in placed.items():
        if p["start"] is not None:
            by_resource[p["op"]["resource_id"]].append((p["start"], key))
    previous: dict[str, str | None] = {}
    for rid, items in by_resource.items():
        items.sort()
        for (_, before), (_, key) in zip([(None, None)] + items, items):
            previous[key] = before
    of_by_key = {op["key"]: op.get("of") for op in schedulable}
    for key, p in placed.items():
        op = p["op"]
        rid, start = op["resource_id"], p["start"]
        if p["anchored"]:
            reason = "ancora"
        elif start is None:
            reason = None
        else:
            prev = previous.get(key)
            ready = placed[prev]["end"] if prev and placed[prev]["end"] is not None else 0
            reason = None
            if start > ready:
                slot = slot_of[rid]
                idx = bisect_right(end_keys.get(slot, []), start) - 1
                while idx >= 0:
                    end, _, other, other_rid = ends[slot][idx]
                    if end <= ready:
                        break
                    if other != key:
                        reason = f"ocupada:{other}" if other_rid == rid else f"posto:{other_rid}"
                        break
                    idx -= 1
            if reason is None:
                reason = (f"ocupada:{prev}" if prev else "origem" if start == 0 else "calendario")
        after = reason.split(":", 1)[1] if reason and reason.startswith("ocupada:") else None
        segments = [(origin + timedelta(seconds=a), origin + timedelta(seconds=b), label[0], label[1])
                    for a, b, label in p["segments"]]
        result_ops[key] = {
            "key": key, "resource_id": rid, "of": op.get("of"), "line_key": op.get("line_key"),
            "scope": int(op.get("scope") or 0), "seconds": int(op["seconds"]), "due": op.get("due"),
            "due_field": op.get("due_field"), "pool": op.get("pool"),
            "start": origin + timedelta(seconds=start) if start is not None else None,
            "end": origin + timedelta(seconds=p["end"]) if p["end"] is not None else None,
            "segments": segments, "start_reason": reason, "after_of": of_by_key.get(after) if after else None,
            "status": PLACED if not p["remaining"] else BEYOND, "unplaced_seconds": int(p["remaining"]),
            "anchored": p["anchored"], "warnings": p["warnings"]}
    resources = {}
    for key, r in result_ops.items():
        x = resources.setdefault(r["resource_id"], {"queue_end": None, "placed": 0, "beyond": 0, "seconds": 0,
                                                    "placed_seconds": 0})
        x["seconds"] += r["seconds"]
        x["placed_seconds"] += r["seconds"] - r["unplaced_seconds"]
        if r["status"] == PLACED:
            x["placed"] += 1
            if r["end"] is not None and (x["queue_end"] is None or r["end"] > x["queue_end"]):
                x["queue_end"] = r["end"]
        else:
            x["beyond"] += 1
    horizon = {rid: origin + timedelta(seconds=iv[-1][1]) for rid, iv in free_base.items() if iv}
    return {"origin": origin, "operations": result_ops, "unschedulable": unschedulable, "resources": resources,
            "horizon_end": horizon}


def _run_single(queue: list[dict], free: list, record) -> None:
    """Uma máquina sozinha: as operações seguidas pelas janelas livres."""
    i, t, n = 0, 0, len(free)
    for op in queue:
        remaining, segments = int(op["seconds"]), []
        if remaining == 0:
            while i < n and free[i][1] <= t:
                i += 1
            record(op, [], 0, at=max(t, free[i][0]) if i < n else t)
            continue
        while remaining > 0 and i < n:
            a, b, label = free[i]
            a = max(a, t)
            if a >= b:
                i += 1
                continue
            take = min(remaining, b - a)
            segments.append((a, a + take, label))
            remaining -= take
            t = a + take
            if t >= b:
                i += 1
        record(op, segments, remaining)


def _run_pool(queues: dict[str, list], free: dict[str, list], record) -> None:
    """Posto partilhado: um só recurso; em cada momento corre a operação mais prioritária cuja máquina está aberta."""
    rids = sorted(queues, key=str)
    q = {rid: deque(queues[rid]) for rid in rids}
    ptr = {rid: 0 for rid in rids}
    remaining = {}
    segments = defaultdict(list)
    t = 0
    while True:
        best = None
        for rid in rids:
            if not q[rid]:
                continue
            iv, p = free[rid], ptr[rid]
            while p < len(iv) and iv[p][1] <= t:
                p += 1
            ptr[rid] = p
            if p < len(iv) and iv[p][0] <= t:
                candidate = (_order(q[rid][0]), str(rid))
                if best is None or candidate < best[0]:
                    best = (candidate, rid)
        if best is not None:
            rid = best[1]
            op = q[rid][0]
            left = remaining.get(op["key"], int(op["seconds"]))
            if left == 0:
                q[rid].popleft()
                record(op, [], 0, at=t)
                continue
            a, b, label = free[rid][ptr[rid]]
            stop = min(t + left, b)
            segments[op["key"]].append((t, stop, label))
            left -= stop - t
            remaining[op["key"]] = left
            t = stop
            if left == 0:
                q[rid].popleft()
                record(op, segments.pop(op["key"]), 0)
            continue
        waiting = [free[rid][ptr[rid]][0] for rid in rids if q[rid] and ptr[rid] < len(free[rid])]
        if not waiting:
            break
        t = max(t, min(waiting))
    for rid in rids:
        for op in q[rid]:
            record(op, segments.pop(op["key"], []), remaining.get(op["key"], int(op["seconds"])))


def check(result: dict, operations: list[dict], windows: dict) -> list[str]:
    """Verificador do despacho: lista de problemas (vazia = certo).

    - nada se sobrepõe na mesma máquina nem no mesmo posto;
    - todos os segmentos ficam dentro das janelas da máquina;
    - Σ dos segundos colocados + os que ficaram além do horizonte = Σ dos segundos de entrada programáveis
      (e o mesmo em cada operação);
    - em cada máquina, o Planeado (âmbito 0) começa antes do resto, salvo âncoras.
    """
    problems = []
    origin = result["origin"]
    ops = result["operations"]
    gone = {u["key"] for u in result["unschedulable"]}
    given = {op["key"]: op for op in operations}
    expected = sum(int(op["seconds"]) for op in operations if op["key"] not in gone)
    got = 0
    slots = defaultdict(list)
    per_resource = defaultdict(list)
    for key, r in ops.items():
        placed = sum(int((b - a).total_seconds()) for a, b, *_ in r["segments"])
        got += placed + r["unplaced_seconds"]
        if placed + r["unplaced_seconds"] != int(given[key]["seconds"]):
            problems.append(f"{key}: {placed} + {r['unplaced_seconds']} s ≠ {given[key]['seconds']} s")
        slot = ("pool", r["pool"]) if r.get("pool") else ("res", r["resource_id"])
        for a, b, *_ in r["segments"]:
            slots[slot].append((a, b, key))
        if r["start"] is not None and not r["anchored"]:
            per_resource[r["resource_id"]].append(r)
    if got != expected:
        problems.append(f"segundos: colocados {got} ≠ entrada {expected}")
    for slot, items in slots.items():
        items.sort()
        for (a1, b1, k1), (a2, b2, k2) in zip(items, items[1:]):
            if a2 < b1:
                problems.append(f"sobreposição em {slot[1]}: {k1} e {k2}")
    clean = {}
    for rid, w in (windows or {}).items():  # janelas seguidas juntam-se (um segmento pode atravessar a meia-noite)
        joined = []
        for a, b, _ in _intervals(w, origin):
            if joined and a <= joined[-1][1]:
                joined[-1] = (joined[-1][0], max(b, joined[-1][1]))
            else:
                joined.append((a, b))
        clean[rid] = joined
    for key, r in ops.items():
        iv = clean.get(r["resource_id"]) or []
        starts = [x[0] for x in iv]
        for a, b, *_ in r["segments"]:
            sa, sb = int((a - origin).total_seconds()), int((b - origin).total_seconds())
            i = bisect_right(starts, sa) - 1
            if i < 0 or not (iv[i][0] <= sa and sb <= iv[i][1]):
                problems.append(f"{key}: segmento fora das janelas de {r['resource_id']}")
    for rid, items in per_resource.items():
        planned = [r["start"] for r in items if r["scope"] == 0]
        rest = [r["start"] for r in items if r["scope"] != 0]
        if planned and rest and max(planned) > min(rest):
            problems.append(f"{rid}: trabalho do resto antes do Planeado")
    return problems
