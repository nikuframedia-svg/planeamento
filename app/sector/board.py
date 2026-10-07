"""Quadro simples do plano (pedido de 02/10/2026): o Gantt para qualquer pessoa e a lista vermelha.

Só leitura. Duas partes:
- «Por planear»: OF com trabalho aberto no plano do setor e linhas por cortar sem máquina (os campos
  de planeamento do Excel/Tabela). Marcar com Planear não chega para sair da lista, porque sem máquina
  a OF também não entra no Gantt; a lista diz que já está marcada. Linhas excluídas na Carteira não
  contam. As OF que entraram no CPIS nos últimos 3 meses e não aparecem em nenhum plano vêm à parte,
  porque ainda não se sabe o setor.
- Caixas do Gantt: o plano aceite mais recente deste setor; sem plano aceite, a proposta automática e,
  para o que ela não coloca, as previsões do planeamento (máquina e dia/semana). Uma caixa = uma OF numa
  máquina, de um dia a outro, com as peças em falta somadas — nunca uma barra por operação.
- Só as máquinas do setor (members.py). Trabalho do setor em máquinas de outro setor fica numa nota
  (`elsewhere`), nunca como linha (pedido do Luís, 06/10/2026).
- 2.ª operação das cantoneiras (08/10, second_operation.py): as operações seguintes da MTG3 saem da lista das
  que não aparecem no quadro (`source.missing`) e ficam só contadas em `source.second_operation`.
- Turnos e dia (06/10/2026): cada caixa diz as horas por dia e turno; `day()` dá o Gantt de um dia com
  eixo de horas, faixas dos turnos e totais por turno. Previsões sem horas recebem a estimativa da
  Carteira (`hours_estimated`).
"""
from __future__ import annotations

import re
import threading
from collections import defaultdict
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .. import cpis_copies, planning, planning_needs as needs
from . import cache, portfolio, second_operation, selection

LISBON = ZoneInfo("Europe/Lisbon")
RECENT_DAYS = 91  # «Sem peças nos planos»: só as OF registadas há menos de 3 meses (decisão de 28/09)

_cache: dict[tuple, list[dict]] = {}
_lock = threading.Lock()


def _order_no(value) -> str:
    """OF264095, «264095» e 264095.0 são a mesma OF."""
    text = str(value or "").strip().upper()
    text = text[2:] if text.startswith("OF") else text
    return text.split(".")[0].strip()


def short_text(value: str) -> str:
    """Designação do Excel em uma linha legível: sem marcas «=», quebras nem _x000D_."""
    text = re.sub(r"_x000D_", " ", value or "")
    text = re.sub(r"\s*=\s*", " · ", text)
    text = re.sub(r"\s+", " ", text).strip(" ·")
    return re.sub(r"(\s*·\s*)+", " · ", text)


def unplanned(sector: str, *, data: dict | None = None, decisions: dict | None = None) -> dict:
    data = data or portfolio.current(sector)
    decisions = selection.current(sector) if decisions is None else decisions
    today = data["today"]
    by_order: dict[str, list[dict]] = defaultdict(list)
    for line in data["lines"]:
        by_order[line["of"]].append(line)
    orders, planned = [], 0
    for of, lines in by_order.items():
        lines = [x for x in lines if portfolio.decision_of(x, decisions) != "excluded"]
        if not lines:
            continue
        missing = [x for x in lines if not x["machine"]]
        if not missing:
            planned += 1
            continue
        days = [x["priority_day"] for x in missing if x.get("priority_day")]
        due = min(days) if days else None
        known = [x["pieces"] for x in missing if x.get("pieces") is not None]  # saldo por confirmar nunca vira 0 (08/10)
        priorities = [x["signals"]["prioridade"] for x in lines if x["signals"]["prioridade"] is not None]
        first = lines[0]
        orders.append({
            "of": of, "work": first["work"], "customer": first["customer"],
            "designation": short_text(next((x["designation"] for x in lines if x["designation"]), "")),
            "family": first["family"], "registered": first["registered"],
            "waiting_days": (today - first["registered"]).days if first["registered"] else None,
            "due": due, "late_days": (today - due).days if due and due < today else 0,
            "metres": round(sum(x["metres"] for x in missing), 1),
            "metres_unknown": sum(bool(x.get("metres_unknown", x.get("balance_unknown"))) for x in missing),
            "pieces": round(sum(known)) if known else None, "pieces_unknown": len(missing) - len(known),
            "lines": len(missing), "lines_total": len(lines), "partial": len(missing) < len(lines),
            "priority": min(priorities) if priorities else None,
            "marked": all(portfolio.decision_of(x, decisions) == "selected" for x in missing),
            # Linhas desta OF que o botão Planear grava: com máquina e ainda não planeadas, e sem máquina mas por
            # decidir na Tabela (desde 07/10/2026 recebem a máquina sugerida; «Subcontrato» e afins nunca).
            "plannable": sum(1 for x in lines if (portfolio.decision_of(x, decisions) != "selected" if x["machine"]
                                                  else selection.tabela_note(x) is None)),
            "warnings": [label for name, label in (("anulada", "Diz «anulada» no Excel"), ("eletrofer", "Feita na Eletrofer"),
                                                   ("validacao", "Só depois de validação"))
                         if any(x["signals"].get(name) for x in lines)],
        })
    orders.sort(key=lambda o: (o["priority"] is None, o["priority"] or 0, o["due"] is None, o["due"] or date.max, -o["metres"], o["of"]))
    # «orders_with_machine» (08/10): OF com máquina em todas as linhas, não «planeadas» (Planear não conta aqui).
    # «planned_orders» é o nome antigo, com o mesmo valor; fica só até à próxima versão, para quem ainda o lê.
    return {"orders": orders, "orders_with_machine": planned, "planned_orders": planned, "today": today,
            "imported_at": data["imported_at"]}


def not_in_plans(*, today: date | None = None, conn=None) -> list[dict]:
    """OF abertas no CPIS, registadas há menos de 3 meses, sem nenhuma linha em nenhum dos dois Excel de planeamento.

    Depende só das importações do Excel (com a cópia do CPIS), não das gerações RAW, que mudam a cada
    validação MES: assim o cálculo corre uma vez por importação e não dezenas de vezes por dia.
    """
    from .week import lisbon_today
    today = today or lisbon_today()  # dia de Lisboa (08/10)
    with (planning.connect(readonly=True) if conn is None else nullcontext(conn)) as c:
        heads = c.execute("SELECT DISTINCT ON (dataset) dataset, id, metadata->'snapshot'->>'snapshot_id' AS snapshot "
                          "FROM planning_mtg.raw_generations WHERE dataset IN ('planning:cantoneiras', 'planning:perfis') "
                          "ORDER BY dataset, id DESC").fetchall()
        snapshots = [h["snapshot"] for h in heads if h["snapshot"]]
        if not snapshots:
            return []
        stamp = (tuple(sorted(snapshots)), today)
        with _lock:
            if stamp in _cache:
                return _cache[stamp]
        known = {_order_no(r["of"]) for r in c.execute(
            "SELECT DISTINCT row_data->>'OF' AS of FROM raw_mtg.plan_production_rows WHERE snapshot_id = ANY(%s)",
            (snapshots,)).fetchall()}
        since = today - timedelta(days=RECENT_DAYS)
        rows = c.execute(
            "SELECT c.production_order_no AS of, c.customer_name, c.work_type_description, c.record_date, c.status, "
            "c.delivery_date, s.loaded_at AS copy_loaded_at "
            "FROM raw_mtg.cpis_rows c LEFT JOIN audit_mtg.snapshots s USING (snapshot_id) "
            "WHERE c.snapshot_id = ANY(%s) AND c.production_order_no IN ("
            "SELECT production_order_no FROM raw_mtg.cpis_rows WHERE snapshot_id = ANY(%s) AND record_date >= %s) "
            "ORDER BY c.production_order_no, c.record_date DESC",
            (snapshots, snapshots, since)).fetchall()
    # Cópias CPIS em desacordo: manda a mais recente, para todos os campos, e o estado mostra-se como vem
    # (decisão de 06/10/2026, substitui A3-2/C06 «basta uma Fechada»). «Pronta» conta como aberta (A3-7).
    copies: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        copies[_order_no(r["of"])].append(r)
    result = []
    for of, group in copies.items():
        group = cpis_copies.latest_first(group, recorded="record_date")
        first = group[0]

        def latest(field):
            return next((r[field] for r in group if r.get(field) not in (None, "")), None)

        status = (latest("status") or "").strip()
        registered = latest("record_date")
        if of in known or registered is None or registered.date() < since or not portfolio.cpis_open(status):
            continue
        delivery = latest("delivery_date")
        result.append({"of": first["of"], "customer": (latest("customer_name") or "").strip() or "Sem cliente",
                       "family": (latest("work_type_description") or "").strip() or "Sem família",
                       "registered": registered.date(), "waiting_days": (today - registered.date()).days,
                       "status": status, "delivery": delivery.date() if delivery else None})
    result.sort(key=lambda r: (r["registered"], r["of"]))
    with _lock:
        _cache.clear()
        _cache[stamp] = result
    return result


def _merge(items: list[dict], today: date | None = None) -> list[dict]:
    """Uma caixa por OF e máquina enquanto os dias se tocam; peças, linhas e horas por dia somadas.

    Atrasada: acaba depois do prazo ou o prazo já passou (antes de hoje), como na Carga e na Carteira.
    Sem isto, uma previsão da Tabela com data passada (prazo = dia da caixa) nunca ficava atrasada (A8-2).
    """
    boxes: list[dict] = []
    for item in sorted(items, key=lambda x: (x["resource_id"], x["of"], x["start"], x["end"])):
        last = boxes[-1] if boxes else None
        days = dict(item.get("days") or {})
        if last and last["resource_id"] == item["resource_id"] and last["of"] == item["of"] and item["start"] <= last["end"]:
            last["end"] = max(last["end"], item["end"])
            if item["pieces"] is None:
                last["pieces_unknown"] += 1
            else:
                last["pieces"] += item["pieces"]
            last["lines"] += 1
            last["approximate"] = last["approximate"] or item["approximate"]
            last["forecast"] = last.get("forecast", False) or item.get("forecast", False)
            last["hours_unknown"] += item.get("hours") is None
            last["hours_estimated"] += int(bool(item.get("estimated")))
            last["hours"] += item.get("hours") or 0
            last["timed"] = last.get("timed", []) + list(item.get("timed") or [])
            for d, h in days.items():
                last["days"][d] = last["days"].get(d, 0) + h
            if item["due"] and (last["due"] is None or item["due"] < last["due"]):
                last["due"] = item["due"]
        else:
            boxes.append({**item, "pieces": item["pieces"] or 0, "pieces_unknown": int(item["pieces"] is None),
                          "lines": 1, "days": days, "hours": item.get("hours") or 0, "hours_unknown": int(item.get("hours") is None),
                          "hours_estimated": int(bool(item.get("estimated"))), "timed": list(item.get("timed") or [])})
            boxes[-1].pop("estimated", None)
    for box in boxes:
        box["late"] = bool(box["due"] and (box["due"] < box["end"] - timedelta(days=1) or (today and box["due"] < today)))
        # Peças desconhecidas não viram 0 (08/10): só desconhecidas → None; algumas → soma das conhecidas + contagem.
        box["pieces"] = None if box["pieces_unknown"] == box["lines"] else round(box["pieces"])
        box["hours"] = round(box["hours"], 2)
        box["days"] = [{"date": d, "hours": round(h, 2)} for d, h in sorted(box["days"].items())]
    return boxes


def _due(op: dict) -> date | None:
    value = (op.get("priority") or {}).get("priority_day") or (op.get("milestones") or {}).get("priority_day")
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _day(instant: datetime) -> date:
    return instant.astimezone(LISBON).date()


def boxes_from_source_plan(plan: dict, operations: list[dict], *, skip: set | None = None, estimates: dict | None = None,
                           today: date | None = None) -> list[dict]:
    """Previsões do planeamento (máquina e Data Corte da Tabela); as horas ficam todas nesse dia.

    Sem horas na previsão, usa a estimativa da Carteira para a mesma operação (`estimates`: chave → horas).
    """
    ops = {op["key"]: op for op in operations}
    items = []
    for entry in plan.get("entries") or []:
        op = ops.get(entry["key"])
        if not op or (skip and entry["key"] in skip):
            continue
        start = date.fromisoformat(entry["start_date"])
        hours = entry.get("hours")
        estimated = hours is None and (estimates or {}).get(entry["key"]) is not None
        if estimated:
            hours = estimates[entry["key"]]
        items.append({"resource_id": entry["resource_id"], "of": op["of"],
                      "start": start, "end": date.fromisoformat(entry["end_date_exclusive"]),
                      "pieces": op.get("planning_remaining"), "due": _due(op),
                      "approximate": entry.get("precision") == "week", "forecast": True, "hours": hours, "estimated": estimated,
                      "days": {start.isoformat(): hours} if hours and entry.get("precision") != "week" else {}})
    return _merge(items, today)


def forecast_only(plan: dict, operations: list[dict], placed: set) -> list[dict]:
    """Operações que a proposta automática não coloca (bloqueadas) e que só aparecem como previsão da Tabela.

    Ficam na lista das operações sem hora com o motivo do bloqueio (ex.: «Duração admissível por confirmar.»),
    para a caixa de previsão não passar por plano (auditoria 06/10/2026, A8-2).
    """
    shown = {e["key"]: e for e in plan.get("entries") or []}
    out = []
    for op in operations:
        reasons = op.get("blocking_reasons") or []
        entry = shown.get(op["key"])
        if op["key"] in placed or not entry or not reasons:
            continue
        out.append({"of": op["of"], "reference": op.get("reference"), "operation": op.get("operation"), "forecast": True,
                    "forecast_day": entry.get("start_date"), "reasons": list(reasons)})
    return out


def missing_operations(sector: str, plan: dict, operations: list[dict], placed: set) -> tuple[list[dict], int]:
    """Operações escolhidas que não ficam em caixa nenhuma (sem hora na proposta e sem dia/máquina na previsão),
    com o motivo; e quantas delas são 2.ª operação das cantoneiras (08/10), que saem da lista e só se contam.

    A fase de uma operação do Gantt vem da ocorrência (a 1.ª é a principal, second_operation.phase)."""
    seconds = [op for op in operations if second_operation.operation(sector, {"phase": second_operation.phase(op.get("occurrence"))})]
    second = {op["key"] for op in seconds}
    kept = [op for op in operations if op["key"] not in second]
    ops = {op["key"]: op for op in kept}
    pending = [p for p in plan.get("pending") or [] if p["key"] not in placed]
    missing = [{"of": ops[p["key"]]["of"], "reference": ops[p["key"]].get("reference"), "operation": ops[p["key"]].get("operation"),
                "reasons": p.get("reasons") or []} for p in pending if p["key"] in ops]
    missing += forecast_only(plan, kept, placed)
    return missing, sum(p["key"] in second for p in pending) + len(forecast_only(plan, seconds, placed))


def boxes_from_proposal(snapshot: dict, proposal: dict, *, area: str | None = None, today: date | None = None) -> list[dict]:
    """Caixas da proposta (ou do plano aceite); com `area`, só as operações desse setor.

    Cada caixa guarda os segmentos com hora (`timed`, UTC) para os turnos e o Gantt do dia.
    """
    from .week import split_segments
    start = datetime.fromisoformat(snapshot["started_at"])
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    ops = {op["key"]: op for op in snapshot["operations"]}
    items = []
    for key, bar in (proposal.get("bars") or {}).items():
        op = ops.get(key)
        segments = bar.get("segments") or [[bar.get("start_minute"), bar.get("end_minute")]]
        segments = [s for s in segments if s and s[0] is not None and s[1] is not None]
        if not op or not segments or (area and op.get("area") and op["area"] != area):
            continue
        first = _day(start + timedelta(minutes=min(s[0] for s in segments)))
        last = _day(start + timedelta(minutes=max(s[1] for s in segments) - 1))
        days = split_segments(snapshot["started_at"], segments)
        timed = [{"start": start + timedelta(minutes=a), "end": start + timedelta(minutes=b), "key": key,
                  "reference": op.get("reference"), "operation": op.get("operation")} for a, b in segments if b > a]
        items.append({"resource_id": bar["resource_id"], "of": op["of"], "start": first, "end": last + timedelta(days=1),
                      "pieces": op.get("planning_remaining"), "due": _due(op), "approximate": False,
                      "hours": sum(days.values()), "days": days, "timed": timed})
    return _merge(items, today)


def _accepted(sector: str) -> tuple[dict, dict, dict] | None:
    """O plano aceite mais recente que inclui este setor e ainda usa as fontes atuais."""
    from ..gantt import service
    candidates = []
    for scenario in service.scenarios()["scenarios"]:
        accepted = (scenario.get("definition") or {}).get("accepted")
        areas = (scenario.get("definition") or {}).get("areas") or [scenario.get("area")]
        if accepted and sector in areas and not scenario.get("stale"):
            candidates.append((accepted.get("accepted_at") or "", scenario, accepted))
    if not candidates:
        return None
    _, scenario, accepted = max(candidates, key=lambda c: c[0])
    job = service.job(accepted["job_id"])
    snapshot, proposal = (job.get("input") or {}).get("snapshot"), (job.get("result") or {}).get("proposal")
    if not snapshot or not proposal:
        return None
    return scenario, snapshot, proposal


# Por setor: (resposta da semana, pormenores privados por máquina). A chave segue as fontes do Gantt; o que ela
# não segue (estimativas das ocorrências, Definições do setor…) refaz-se ao fim de 10 minutos. Nos dois casos a
# leitura recebe logo o quadro anterior (marcado «stale») e o novo calcula-se uma vez em segundo plano (cache.py).
BOARD_CACHE_SECONDS = 600
_board = cache.Cache("Quadro", mark=lambda value: ({**value[0], "stale": True}, value[1]), max_age=BOARD_CACHE_SECONDS)


def _machine_days(resource_ids, today: date, weeks: int = 14) -> dict[str, dict[str, float]]:
    """Horas de calendário por dia (da semana passada às próximas semanas), por máquina."""
    from .week import calendar_days
    monday = today - timedelta(days=today.weekday())
    keys = [(monday + timedelta(weeks=i)).isocalendar()[:2] for i in range(-1, weeks)]
    with planning.connect(readonly=True) as c:
        rows = c.execute("SELECT definition FROM planning_mtg.raw_objects WHERE kind='calendar' AND NOT archived "
                         "AND definition->>'resource_id' = ANY(%s)", (list(resource_ids),)).fetchall()
    by = defaultdict(list)
    for r in rows:
        d = r["definition"]
        if (int(d["year"]), int(d["week"])) in keys and d.get("confirmed"):
            by[str(d["resource_id"])].append(d)
    return {rid: {k: round(v, 2) for k, v in calendar_days(defs).items()} for rid, defs in by.items()}


def _shift_hours(timed: list[dict], template) -> list[dict]:
    """Horas por dia e turno de uma caixa: [{date, shift, hours}] (turno None = fora dos turnos do setor)."""
    from .week import split_by_shift
    acc: dict[tuple, float] = defaultdict(float)
    for t in timed:
        for piece in split_by_shift(t["start"], t["end"], template):
            acc[(piece["shift_date"], piece["shift"])] += piece["hours"]
    return [{"date": d, "shift": n, "hours": round(h, 2)} for (d, n), h in sorted(acc.items(), key=lambda x: (x[0][0], x[0][1] or 9))]


def _elsewhere(boxes: list[dict], resources: dict) -> dict:
    """Trabalho deste setor em máquinas de outro setor: nota visível em vez de linha no Gantt."""
    by = defaultdict(lambda: {"orders": set(), "hours": 0.0, "operations": 0, "items": []})
    for b in boxes:
        m = by[b["resource_id"]]
        m["orders"].add(b["of"])
        m["hours"] += b["hours"] or 0
        m["operations"] += b["lines"]
        m["items"].append({"of": b["of"], "start": b["start"], "end": b["end"]})
    machines = [{"id": rid, "name": (resources.get(rid) or {}).get("name") or rid, "orders": len(m["orders"]),
                 "hours": round(m["hours"], 1), "operations": m["operations"], "items": m["items"][:50]}
                for rid, m in sorted(by.items(), key=lambda x: -x[1]["hours"])]
    return {"operations": sum(m["operations"] for m in machines), "orders": len({b["of"] for b in boxes}),
            "hours": round(sum(m["hours"] for m in machines), 1), "machines": machines}


def _estimates(sector: str) -> dict:
    """Horas da Carteira por operação (mesma chave do Gantt), para as previsões sem horas."""
    from . import occurrences
    try:
        return {f["key"]: f.get("load_hours") for f in occurrences.load(sector, allow_stale=True)["facts"]
                if f.get("key") and f.get("load_hours") is not None}
    except planning.PlanningError:  # ocorrências ainda em construção: fica sem estimativa
        return {}


def _sources(sector: str) -> str:
    """Fontes do quadro: as referências do Gantt e os cenários com plano aceite.

    As referências têm as gerações dos dois setores de propósito: as taxas históricas que dão as durações
    leem a produção dos dois (productivity.Context) e um plano aceite fica antigo com qualquer fonte. As
    exportações do OCR original (original:*) não entram.
    """
    from ..gantt import integrated
    with planning.connect(readonly=True) as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        refs = integrated.references(c)
        accepted = c.execute("SELECT id, revision FROM planning_mtg.raw_objects WHERE kind = 'gantt' AND NOT archived "
                             "AND definition ? 'accepted' ORDER BY id").fetchall()
    return needs.digest(needs.serial({"references": refs, "accepted": accepted}))


def _built(sector: str, data: dict, *, allow_stale: bool = False) -> tuple[dict, dict]:
    """(resposta da semana, pormenores privados por máquina), em cache pelas fontes e pelo dia (10 minutos no máximo).

    `allow_stale`: com fontes novas ou passados os 10 minutos, devolve logo o quadro anterior do mesmo dia e
    refaz uma vez em segundo plano.
    """
    today = data["today"]
    return _board.get(sector, (_sources(sector), today), lambda: _build(sector), allow_stale=allow_stale,
                      stale_if=lambda old: old[-1] == today, refresh=lambda: _built(sector, {"today": today}))


def _build(sector: str) -> tuple[dict, dict]:
    from ..gantt import service, baseline, source_plan
    from . import settings as sector_settings
    from .members import members
    data = portfolio.current(sector)  # as linhas atuais, nunca as da geração anterior
    customers = {}
    for line in data["lines"]:
        customers.setdefault(line["of"], {"customer": line["customer"], "designation": short_text(line["designation"])})
    accepted = _accepted(sector)
    if accepted:
        scenario, snapshot, proposal = accepted
        resources = snapshot["resources"]
        boxes = boxes_from_proposal(snapshot, proposal, area=sector, today=data["today"])
        source = {"kind": "aceite", "name": scenario.get("name"), "accepted_at": scenario["definition"]["accepted"].get("accepted_at")}
    else:
        snapshot = service.snapshot(area=sector)
        resources = snapshot["resources"]
        plan = source_plan.build(snapshot)
        selected = len({op["of"] for op in snapshot["operations"]})
        estimates = _estimates(sector)
        try:
            proposal = baseline.build(snapshot)
            placed = set(proposal.get("bars") or {})
            boxes = (boxes_from_proposal(snapshot, proposal, area=sector, today=data["today"])
                     + boxes_from_source_plan(plan, snapshot["operations"], skip=placed, estimates=estimates, today=data["today"]))
            source = {"kind": "automatica", "selected_orders": selected, "placed": len(placed),
                      "operations": len(snapshot["operations"])}
        except Exception:  # a proposta falhou a sua validação: fica-se pelas previsões da Tabela
            import logging
            logging.getLogger(__name__).exception("Proposta automática indisponível para o quadro")
            boxes = boxes_from_source_plan(plan, snapshot["operations"], estimates=estimates, today=data["today"])
            source = {"kind": "previsoes", "selected_orders": selected}
            placed = set()
        source["missing"], source["second_operation"] = missing_operations(sector, plan, snapshot["operations"], placed)
    with planning.connect(readonly=True) as c:
        template = sector_settings.read(c, sector)["template"]
        own = set(members(c, sector))
    for box in boxes:
        box.update(customers.get(box["of"], {"customer": "", "designation": ""}))
        box["shifts"] = _shift_hours(box["timed"], template)
        if not box["timed"] and not box["approximate"]:  # previsão com dia mas sem hora: horas «sem hora» nesse dia
            box["shifts"] += [{"date": x["date"], "shift": None, "hours": x["hours"]} for x in box["days"] if x["hours"]]
    private = {"timed": defaultdict(list), "boxes": defaultdict(list), "template": template}
    machines = []
    for rid, resource in resources.items():
        if rid not in own:
            continue
        mine = [b for b in boxes if b["resource_id"] == rid]
        if mine or resource.get("windows"):
            for b in mine:
                private["boxes"][rid].append(b)
                private["timed"][rid].extend((b, t) for t in b["timed"])
            machines.append({"id": rid, "name": resource.get("name") or rid, "member": True,
                             "boxes": [{k: v for k, v in b.items() if k != "timed"} for b in mine]})
    days = _machine_days([m["id"] for m in machines], data["today"])
    for m in machines:
        m["days"] = days.get(m["id"], {})
    machines.sort(key=lambda m: (not m["boxes"], m["name"]))
    result = {"sector": sector, "sector_label": portfolio.SECTORS[sector], "today": data["today"],
              "imported_at": data["imported_at"], "source": source, "machines": machines, "template": template, "day_view": True,
              "elsewhere": _elsewhere([b for b in boxes if b["resource_id"] not in own], resources),
              "not_in_plans": not_in_plans(today=data["today"]), "stale": False}
    return result, private


def board(sector: str, *, allow_stale: bool = False) -> dict:
    """Gantt simples: plano aceite; senão proposta automática (com previsões para o que ela não coloca).

    `allow_stale` (a rota GET): o Gantt e as linhas podem ser os anteriores enquanto se refazem; a lista
    vermelha usa sempre as decisões atuais. `stale` diz se alguma parte é a anterior.
    """
    portfolio.check_sector(sector)
    data = portfolio.current(sector, allow_stale=allow_stale)
    decisions = selection.current(sector)
    result, _ = _built(sector, data, allow_stale=allow_stale)
    from . import drive_notice
    return {**result, "unplanned": unplanned(sector, data=data, decisions=decisions),
            # Excel do setor no Drive mais recente do que o importado (F16, 08/10): uma linha de aviso.
            "source_notice": drive_notice.text(sector),
            "stale": bool(result.get("stale") or data.get("stale"))}


def _merge_pieces(pieces: list[dict]) -> list[dict]:
    """Pedaços seguidos da mesma OF no mesmo turno juntam-se num bloco com as referências todas."""
    out: list[dict] = []
    for p in sorted(pieces, key=lambda x: x["start"]):
        last = out[-1] if out else None
        if last and last["of"] == p["of"] and last["end"] >= p["start"] and (last["shift"], last["shift_date"]) == (p["shift"], p["shift_date"]):
            last["end"] = max(last["end"], p["end"])
            last["to"] = p["to"]
            last["hours"] += p["hours"]
            last["operations"] += 1
            if p["reference"] and p["reference"] not in last["references"]:
                last["references"].append(p["reference"])
            last["late"] = last["late"] or p["late"]
        else:
            out.append({**p, "references": [p["reference"]] if p["reference"] else [], "operations": 1})
    for p in out:
        p.pop("reference", None)
        p["hours"] = round(p["hours"], 2)
    return out


def day(sector: str, day_text: str, machine: str | None = None, *, allow_stale: bool = False) -> dict:
    """Gantt de um dia: por máquina do setor, janelas e trabalho com hora, por turno, e previsões sem hora."""
    from .week import bands, calendar_days, day_bounds, hour_ticks, labelled_windows, split_by_shift
    portfolio.check_sector(sector)
    try:
        the_day = date.fromisoformat(str(day_text))
    except ValueError:
        raise planning.PlanningError("Dia inválido.") from None
    data = portfolio.current(sector, allow_stale=allow_stale)
    result, private = _built(sector, data, allow_stale=allow_stale)
    template = private["template"]
    machines = [m for m in result["machines"] if not machine or m["id"] == machine]
    if machine and not machines:
        raise planning.PlanningError("Máquina desconhecida neste setor.", 404)
    start, end = day_bounds(the_day)
    wide_start, wide_end = start - timedelta(days=1), end + timedelta(days=1)  # turnos inteiros (madrugada)
    weeks = {(the_day + timedelta(days=i)).isocalendar()[:2] for i in (-1, 0, 1)}
    with planning.connect(readonly=True) as c:
        rows = c.execute("SELECT definition FROM planning_mtg.raw_objects WHERE kind='calendar' AND NOT archived "
                         "AND definition->>'resource_id' = ANY(%s)", ([m["id"] for m in machines],)).fetchall()
    calendars = defaultdict(list)
    for r in rows:
        d = r["definition"]
        if d.get("confirmed") and (int(d["year"]), int(d["week"])) in weeks:
            calendars[str(d["resource_id"])].append(d)
    iso = the_day.isoformat()
    out = []
    for m in machines:
        windows = labelled_windows(calendars.get(m["id"], []), template, wide_start, wide_end)
        pieces = []
        for box, t in private["timed"].get(m["id"], []):
            a, b = max(t["start"], wide_start), min(t["end"], wide_end)
            if b <= a:
                continue
            for piece in split_by_shift(a, b, template):
                pieces.append({**piece, "of": box["of"], "customer": box.get("customer") or "", "reference": t.get("reference"),
                               "late": box["late"], "pieces": box["pieces"]})
        shifts_seen = sorted({(w["shift"], w["shift_date"]) for w in windows + pieces
                              if w["shift"] and w["start"] < end and w["end"] > start}, key=lambda x: (x[1], x[0]))
        totals = []
        for n, shift_date in shifts_seen:
            a, b = template[n - 1]
            totals.append({"shift": n, "shift_date": shift_date, "from": a, "to": b,
                           "planned": round(sum(p["hours"] for p in pieces if (p["shift"], p["shift_date"]) == (n, shift_date)), 2),
                           "capacity": round(sum(w["hours"] for w in windows if (w["shift"], w["shift_date"]) == (n, shift_date)), 2)})
        inside = [p for p in pieces if p["end"] > start and p["start"] < end]
        clipped = []
        for p in inside:
            a, b = max(p["start"], start), min(p["end"], end)
            clipped.append({**p, "start": a, "end": b, "hours": (b - a).total_seconds() / 3600,
                            "cut_start": p["start"] < start, "cut_end": p["end"] > end})
        untimed = []
        for box in private["boxes"].get(m["id"], []):
            if box["timed"] or not (box["start"] <= the_day < box["end"]):
                continue
            hours = next((x["hours"] for x in box["days"] if x["date"] == iso), None) if not box["approximate"] else None
            untimed.append({"of": box["of"], "customer": box.get("customer") or "", "pieces": box["pieces"], "hours": hours,
                            "estimated": bool(box.get("hours_estimated")), "precision": "week" if box["approximate"] else "day", "late": box["late"]})
        planned_day = sum(p["hours"] for p in clipped) + sum(u["hours"] or 0 for u in untimed if u["precision"] == "day")
        out.append({"id": m["id"], "name": m["name"],
                    "windows": [{**w, "start": max(w["start"], start), "end": min(w["end"], end)} for w in windows if w["end"] > start and w["start"] < end],
                    "segments": _merge_pieces(clipped), "shifts": totals, "untimed": untimed,
                    "day": {"planned": round(planned_day, 2), "untimed": round(sum(u["hours"] or 0 for u in untimed if u["precision"] == "day"), 2),
                            # fora das 14 semanas do quadro, a capacidade vem dos calendários do próprio dia
                            "capacity": round(m["days"].get(iso, calendar_days(calendars.get(m["id"], [])).get(iso, 0)), 2)}})
    return needs.serial({"sector": sector, "sector_label": result["sector_label"], "day": the_day, "start": start, "end": end,
                         "template": template, "source": result["source"], "bands": bands(the_day, template),
                         "ticks": hour_ticks(the_day), "machines": out, "elsewhere": result["elsewhere"], "today": data["today"],
                         "stale": bool(result.get("stale") or data.get("stale"))})
