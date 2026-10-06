"""Quadro simples do plano (pedido de 02/10/2026): o Gantt para qualquer pessoa e a lista vermelha.

Só leitura. Duas partes:
- «Por planear»: OF com trabalho aberto no plano do setor e linhas por cortar sem máquina (os campos
  de planeamento do Excel/Tabela). Marcar com Planear não chega para sair da lista, porque sem máquina
  a OF também não entra no Gantt; a lista diz que já está marcada. Linhas excluídas na Carteira não
  contam. As OF que entraram no CPIS nos últimos 3 meses e não aparecem em nenhum plano vêm à parte,
  porque ainda não se sabe o setor.
- Caixas do Gantt: o plano aceite mais recente deste setor; sem plano aceite, as previsões do
  planeamento (máquina e dia/semana) do trabalho escolhido. Uma caixa = uma OF numa máquina, de um
  dia a outro, com as peças em falta somadas — nunca uma barra por operação.
"""
from __future__ import annotations

import re
import threading
from collections import defaultdict
from contextlib import nullcontext
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .. import planning, planning_needs as needs
from . import portfolio, selection

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
        priorities = [x["signals"]["prioridade"] for x in lines if x["signals"]["prioridade"] is not None]
        first = lines[0]
        orders.append({
            "of": of, "work": first["work"], "customer": first["customer"],
            "designation": short_text(next((x["designation"] for x in lines if x["designation"]), "")),
            "family": first["family"], "registered": first["registered"],
            "waiting_days": (today - first["registered"]).days if first["registered"] else None,
            "due": due, "late_days": (today - due).days if due and due < today else 0,
            "metres": round(sum(x["metres"] for x in missing), 1),
            "pieces": round(sum(x["pieces"] or 0 for x in missing)),
            "lines": len(missing), "lines_total": len(lines), "partial": len(missing) < len(lines),
            "priority": min(priorities) if priorities else None,
            "marked": all(portfolio.decision_of(x, decisions) == "selected" for x in missing),
            # Linhas desta OF que já têm máquina e ainda não estão planeadas: só estas o botão Planear grava.
            "plannable": sum(1 for x in lines if x["machine"] and portfolio.decision_of(x, decisions) != "selected"),
            "warnings": [label for name, label in (("anulada", "Diz «anulada» no Excel"), ("eletrofer", "Feita na Eletrofer"),
                                                   ("validacao", "Só depois de validação"))
                         if any(x["signals"].get(name) for x in lines)],
        })
    orders.sort(key=lambda o: (o["priority"] is None, o["priority"] or 0, o["due"] is None, o["due"] or date.max, -o["metres"], o["of"]))
    return {"orders": orders, "planned_orders": planned, "today": today, "imported_at": data["imported_at"]}


def not_in_plans(*, today: date | None = None, conn=None) -> list[dict]:
    """OF abertas no CPIS, registadas há menos de 3 meses, sem nenhuma linha em nenhum dos dois Excel de planeamento.

    Depende só das importações do Excel (com a cópia do CPIS), não das gerações RAW, que mudam a cada
    validação MES: assim o cálculo corre uma vez por importação e não dezenas de vezes por dia.
    """
    today = today or date.today()
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
        rows = c.execute(
            "SELECT DISTINCT ON (production_order_no) production_order_no AS of, customer_name, work_type_description, "
            "record_date, status, delivery_date FROM raw_mtg.cpis_rows "
            "WHERE snapshot_id = ANY(%s) AND status = ANY(%s) AND record_date >= %s "
            "ORDER BY production_order_no, record_date DESC",
            (snapshots, list(planning.OPEN_STATES), today - timedelta(days=RECENT_DAYS))).fetchall()
    result = [{"of": r["of"], "customer": (r["customer_name"] or "").strip() or "Sem cliente",
               "family": (r["work_type_description"] or "").strip() or "Sem família",
               "registered": r["record_date"].date(), "waiting_days": (today - r["record_date"].date()).days,
               "status": r["status"], "delivery": r["delivery_date"].date() if r["delivery_date"] else None}
              for r in rows if _order_no(r["of"]) not in known]
    result.sort(key=lambda r: (r["registered"], r["of"]))
    with _lock:
        _cache.clear()
        _cache[stamp] = result
    return result


def _merge(items: list[dict]) -> list[dict]:
    """Uma caixa por OF e máquina enquanto os dias se tocam; peças, linhas e horas por dia somadas."""
    boxes: list[dict] = []
    for item in sorted(items, key=lambda x: (x["resource_id"], x["of"], x["start"], x["end"])):
        last = boxes[-1] if boxes else None
        days = dict(item.get("days") or {})
        if last and last["resource_id"] == item["resource_id"] and last["of"] == item["of"] and item["start"] <= last["end"]:
            last["end"] = max(last["end"], item["end"])
            last["pieces"] += item["pieces"]
            last["lines"] += 1
            last["approximate"] = last["approximate"] or item["approximate"]
            last["forecast"] = last.get("forecast", False) or item.get("forecast", False)
            last["hours_unknown"] += item.get("hours") is None
            last["hours"] += item.get("hours") or 0
            for d, h in days.items():
                last["days"][d] = last["days"].get(d, 0) + h
            if item["due"] and (last["due"] is None or item["due"] < last["due"]):
                last["due"] = item["due"]
        else:
            boxes.append({**item, "lines": 1, "days": days, "hours": item.get("hours") or 0, "hours_unknown": int(item.get("hours") is None)})
    for box in boxes:
        box["late"] = bool(box["due"] and box["due"] < box["end"] - timedelta(days=1))
        box["pieces"] = round(box["pieces"])
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


def boxes_from_source_plan(plan: dict, operations: list[dict], *, skip: set | None = None) -> list[dict]:
    """Previsões do planeamento (máquina e Data Corte da Tabela); as horas ficam todas nesse dia."""
    ops = {op["key"]: op for op in operations}
    items = []
    for entry in plan.get("entries") or []:
        op = ops.get(entry["key"])
        if not op or (skip and entry["key"] in skip):
            continue
        start = date.fromisoformat(entry["start_date"])
        hours = entry.get("hours")
        items.append({"resource_id": entry["resource_id"], "of": op["of"],
                      "start": start, "end": date.fromisoformat(entry["end_date_exclusive"]),
                      "pieces": op.get("planning_remaining") or 0, "due": _due(op),
                      "approximate": entry.get("precision") == "week", "forecast": True, "hours": hours,
                      "days": {start.isoformat(): hours} if hours and entry.get("precision") != "week" else {}})
    return _merge(items)


def boxes_from_proposal(snapshot: dict, proposal: dict) -> list[dict]:
    from .week import split_segments
    start = datetime.fromisoformat(snapshot["started_at"])
    ops = {op["key"]: op for op in snapshot["operations"]}
    items = []
    for key, bar in (proposal.get("bars") or {}).items():
        op = ops.get(key)
        segments = bar.get("segments") or [[bar.get("start_minute"), bar.get("end_minute")]]
        segments = [s for s in segments if s and s[0] is not None and s[1] is not None]
        if not op or not segments:
            continue
        first = _day(start + timedelta(minutes=min(s[0] for s in segments)))
        last = _day(start + timedelta(minutes=max(s[1] for s in segments) - 1))
        days = split_segments(snapshot["started_at"], segments)
        items.append({"resource_id": bar["resource_id"], "of": op["of"], "start": first, "end": last + timedelta(days=1),
                      "pieces": op.get("planning_remaining") or 0, "due": _due(op), "approximate": False,
                      "hours": sum(days.values()), "days": days})
    return _merge(items)


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


_board_cache: dict[str, tuple[tuple, float, dict]] = {}
BOARD_CACHE_SECONDS = 600


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


def board(sector: str) -> dict:
    """Gantt simples: plano aceite; senão proposta automática (com previsões para o que ela não coloca)."""
    import time as clock
    portfolio.check_sector(sector)
    from ..gantt import service, baseline, source_plan, integrated
    data = portfolio.current(sector)
    decisions = selection.current(sector)
    with planning.connect(readonly=True) as c:
        refs = needs.digest(needs.serial(integrated.references(c)))
    cached = _board_cache.get(sector)
    key = (refs, data["generation"], data.get("machine_digest"), data["today"])
    if cached and cached[0] == key and clock.monotonic() - cached[1] < BOARD_CACHE_SECONDS:
        result = dict(cached[2])
        result["unplanned"] = unplanned(sector, data=data, decisions=decisions)
        return result
    customers = {}
    for line in data["lines"]:
        customers.setdefault(line["of"], {"customer": line["customer"], "designation": short_text(line["designation"])})
    accepted = _accepted(sector)
    if accepted:
        scenario, snapshot, proposal = accepted
        resources = snapshot["resources"]
        boxes = boxes_from_proposal(snapshot, proposal)
        source = {"kind": "aceite", "name": scenario.get("name"), "accepted_at": scenario["definition"]["accepted"].get("accepted_at")}
    else:
        snapshot = service.snapshot(area=sector)
        resources = snapshot["resources"]
        plan = source_plan.build(snapshot)
        selected = len({op["of"] for op in snapshot["operations"]})
        try:
            proposal = baseline.build(snapshot)
            placed = set(proposal.get("bars") or {})
            boxes = boxes_from_proposal(snapshot, proposal) + boxes_from_source_plan(plan, snapshot["operations"], skip=placed)
            source = {"kind": "automatica", "selected_orders": selected, "placed": len(placed),
                      "operations": len(snapshot["operations"])}
        except Exception:  # a proposta falhou a sua validação: fica-se pelas previsões da Tabela
            import logging
            logging.getLogger(__name__).exception("Proposta automática indisponível para o quadro")
            boxes = boxes_from_source_plan(plan, snapshot["operations"])
            source = {"kind": "previsoes", "selected_orders": selected}
    for box in boxes:
        box.update(customers.get(box["of"], {"customer": "", "designation": ""}))
    from . import settings as sector_settings
    with planning.connect(readonly=True) as c:
        own = {m["id"] for m in sector_settings.machine_rows(c, sector)}
    machines = []
    for rid, resource in resources.items():
        mine = [b for b in boxes if b["resource_id"] == rid]
        if mine or (rid in own and resource.get("windows")):
            machines.append({"id": rid, "name": resource.get("name") or rid, "boxes": mine})
    days = _machine_days([m["id"] for m in machines], data["today"])
    for m in machines:
        m["days"] = days.get(m["id"], {})
    machines.sort(key=lambda m: (not m["boxes"], m["name"]))
    result = {"sector": sector, "sector_label": portfolio.SECTORS[sector], "today": data["today"],
              "imported_at": data["imported_at"], "source": source, "machines": machines,
              "unplanned": unplanned(sector, data=data, decisions=decisions), "not_in_plans": not_in_plans(today=data["today"])}
    _board_cache[sector] = (key, clock.monotonic(), result)
    return result
