"""Quadro simples do plano (pedido de 02/10/2026): o Gantt para qualquer pessoa e a lista vermelha.

Só leitura. Duas partes:
- «Por planear»: OF com trabalho aberto no plano do setor e linhas por cortar sem máquina (os campos
  de planeamento do Excel/Tabela). Marcar com Planear não chega para sair da lista, porque sem máquina
  a OF também não entra no Gantt; a lista diz que já está marcada. Linhas excluídas na Carteira não
  contam. As OF que entraram no CPIS nos últimos 3 meses e não aparecem em nenhum plano vêm à parte,
  porque ainda não se sabe o setor.
- Caixas do Gantt: o plano em uso (Etapa 3, 08/10) = as linhas Planeado na previsão com capacidade finita
  (forecast.py, a fila por máquina de dispatch.py), na máquina da Carteira e com as horas da Carga. Uma caixa =
  uma OF numa máquina, de um dia a outro, com as peças em falta somadas — nunca uma barra por operação — e as
  chaves das operações (`keys`), o início e o fim exatos, a conclusão prevista da OF, a margem e o risco. O Gantt
  técnico (plano aceite e proposta automática) é um estudo e já não entra aqui.
- Só as máquinas do setor (members.py). Trabalho do setor em máquinas de outro setor fica numa nota
  (`elsewhere`), nunca como linha (pedido do Luís, 06/10/2026).
- 2.ª operação das cantoneiras (08/10, second_operation.py): as operações seguintes da MTG3 saem da lista das
  que não aparecem no quadro (`source.missing`) e ficam só contadas em `source.second_operation`.
- Turnos e dia (06/10/2026): cada caixa diz as horas por dia e turno; `day()` dá o Gantt de um dia com
  eixo de horas, faixas dos turnos e totais por turno, dos segmentos da previsão.
"""
from __future__ import annotations

import re
import threading
from collections import defaultdict
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .. import cpis_copies, planning, planning_needs as needs
from . import cache, portfolio, selection

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
    """Uma caixa por OF e máquina enquanto os dias se tocam; peças, linhas, horas por dia e chaves somadas.

    Atrasada: acaba depois do prazo (pela previsão, como instante: `late_exact`) ou o prazo já passou (antes de
    hoje), como na Carga e na Carteira. Sem `late_exact`, a regra antiga pelo dia da caixa.
    """
    boxes: list[dict] = []
    for item in sorted(items, key=lambda x: (x["resource_id"], x["of"], x["start"], x["end"], x.get("start_at") or datetime.min.replace(tzinfo=timezone.utc))):
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
            last["hours_unknown"] += item.get("hours") is None
            last["hours_estimated"] += int(bool(item.get("estimated")))
            last["hours"] += item.get("hours") or 0
            last["timed"] = last.get("timed", []) + list(item.get("timed") or [])
            last["keys"] = last.get("keys", []) + list(item.get("keys") or [])
            last["late_exact"] = last.get("late_exact", False) or item.get("late_exact", False)
            for c in item.get("conflicts") or []:
                if c not in last.setdefault("conflicts", []):
                    last["conflicts"].append(c)
            for name, pick in (("start_at", min), ("end_at", max)):
                if item.get(name) is not None:
                    last[name] = item[name] if last.get(name) is None else pick(last[name], item[name])
            for d, h in days.items():
                last["days"][d] = last["days"].get(d, 0) + h
            if item["due"] and (last["due"] is None or item["due"] < last["due"]):
                last["due"] = item["due"]
        else:
            boxes.append({**item, "pieces": item["pieces"] or 0, "pieces_unknown": int(item["pieces"] is None),
                          "lines": 1, "days": days, "hours": item.get("hours") or 0, "hours_unknown": int(item.get("hours") is None),
                          "hours_estimated": int(bool(item.get("estimated"))), "timed": list(item.get("timed") or []),
                          "keys": list(item.get("keys") or []), "conflicts": list(item.get("conflicts") or [])})
            boxes[-1].pop("estimated", None)
    for box in boxes:
        by_day = bool(box["due"] and box["due"] < box["end"] - timedelta(days=1))
        box["late"] = bool(box.pop("late_exact", by_day) or (box["due"] and today and box["due"] < today))
        # Peças desconhecidas não viram 0 (08/10): só desconhecidas → None; algumas → soma das conhecidas + contagem.
        box["pieces"] = None if box["pieces_unknown"] == box["lines"] else round(box["pieces"])
        box["hours"] = round(box["hours"], 2)
        box["days"] = [{"date": d, "hours": round(h, 2)} for d, h in sorted(box["days"].items())]
    return boxes


def _day(instant: datetime) -> date:
    return instant.astimezone(LISBON).date()


def _due_day(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _conflicts(meta: dict, rid: str, names: dict, warnings=()) -> list[str]:
    """Avisos de uma operação no plano em uso (nunca bloqueiam): iniciada noutra máquina e os das âncoras."""
    out = []
    other = meta.get("documentary_resource_id")
    if meta.get("started") and other and other != rid:
        out.append(f"Iniciada na {names.get(other) or meta.get('hours_machine') or 'outra máquina'}")
    for w in warnings or ():
        out.append({"fora_de_horario": "Fixada em hora fechada: passou para a abertura seguinte",
                    "ja_passou": "Ajuste já passou: o resto vai à frente da fila"}.get(w)
                   or (f"Sobrepõe outra âncora ({w.split(':', 1)[1]})" if w.startswith("sobreposta:") else w))
    return out


def boxes_from_forecast(fc: dict, *, today: date | None = None, names: dict | None = None) -> tuple[list[dict], list[dict], dict]:
    """(caixas, operações sem caixa, trabalho noutro setor) do plano em uso: o âmbito 0 da previsão (linhas Planeado).

    Uma caixa = uma OF numa máquina, de um dia a outro (_merge), com as chaves das operações (`keys`), o início e o
    fim exatos, a conclusão prevista da OF, a margem, o risco e os avisos. O que a previsão não coloca fica na lista
    das operações sem caixa, com o motivo; a 2.ª operação das cantoneiras só se conta.
    """
    from .forecast import REASON_TEXT
    from .week import split_interval
    names = names or {}
    meta, orders = fc["meta"], fc.get("orders") or {}
    items, missing = [], []
    for key, r in fc["operations"].items():
        if r["scope"] != 0:
            continue
        m = meta.get(key) or {}
        timed = [{"start": a, "end": b, "key": key, "reference": m.get("reference"), "operation": m.get("operation")}
                 for a, b, *_ in r["segments"] if b > a]
        if r["status"] != "colocada":
            missing.append({"of": r["of"], "reference": m.get("reference"), "operation": m.get("operation"),
                            "reasons": [REASON_TEXT["alem_do_horizonte"]]})
        first = timed[0]["start"] if timed else r["start"]
        if first is None:
            continue
        last = timed[-1]["end"] if timed else r["end"] or first
        days = defaultdict(float)
        for t in timed:
            for d, h in split_interval(t["start"], t["end"]).items():
                days[d] += h
        due = _due_day(m.get("due_day"))
        items.append({"resource_id": r["resource_id"], "of": r["of"], "start": _day(first),
                      "end": _day(last - timedelta(microseconds=1) if last > first else last) + timedelta(days=1),
                      "pieces": m.get("pieces"), "due": due, "approximate": False,
                      "hours": sum((t["end"] - t["start"]).total_seconds() for t in timed) / 3600,
                      "estimated": m.get("load_basis") == "estimada", "days": dict(days), "timed": timed, "keys": [key],
                      "start_at": first, "end_at": last if r["status"] == "colocada" else None,
                      "late_exact": bool(r.get("due") and (r["end"] is None or r["end"] > r["due"])),
                      "conflicts": _conflicts(m, r["resource_id"], names, r.get("warnings"))})
    second, elsewhere = 0, defaultdict(lambda: {"orders": set(), "hours": 0.0, "operations": 0, "items": []})
    for u in fc["unschedulable"]:
        if u["scope"] != 0:
            continue
        m = meta.get(u["key"]) or {}
        if u["reason"] == "segunda_operacao":
            second += 1
        elif u["reason"] == "outro_setor":
            e = elsewhere[u["resource_id"]]
            e["orders"].add(u["of"])
            e["hours"] += (u.get("seconds") or 0) / 3600
            e["operations"] += 1
            e["items"].append({"of": u["of"], "start": None, "end": None})
        else:
            missing.append({"of": u["of"], "reference": m.get("reference"), "operation": m.get("operation"),
                            "reasons": [REASON_TEXT.get(u["reason"], u["reason"])]})
    boxes = _merge(items, today)
    for box in boxes:
        o = orders.get(box["of"]) or {}
        box.update(conclusion=o.get("end"), margin_days=o.get("margin_days"), risk=o.get("state"),
                   already_late=bool(o.get("already_late")))
    machines = [{"id": rid, "name": names.get(rid) or rid, "orders": len(e["orders"]), "hours": round(e["hours"], 1),
                 "operations": e["operations"], "items": e["items"][:50]} for rid, e in sorted(elsewhere.items(), key=lambda x: -x[1]["hours"])]
    note = {"operations": sum(m["operations"] for m in machines), "orders": len({o for e in elsewhere.values() for o in e["orders"]}),
            "hours": round(sum(m["hours"] for m in machines), 1), "machines": machines}
    missing.sort(key=lambda x: (str(x["of"]), str(x["reference"] or ""), str(x["operation"] or "")))
    return boxes, missing, {"elsewhere": note, "second_operation": second}


# Por setor: (resposta da semana, pormenores privados por máquina). A chave é o carimbo da previsão (forecast.stamp:
# ocorrências, linhas, decisões com quantidades, calendários, Definições, origem e dia); 10 minutos no máximo. A
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


def _sources(sector: str) -> str:
    """Fontes do quadro: o carimbo da previsão (o plano em uso vem dela; o Gantt técnico já não entra)."""
    from . import forecast
    return forecast.stamp(sector)


def _built(sector: str, data: dict, *, allow_stale: bool = False) -> tuple[dict, dict]:
    """(resposta da semana, pormenores privados por máquina), em cache pelo carimbo da previsão e pelo dia.

    `allow_stale`: com fontes novas ou passados os 10 minutos, devolve logo o quadro anterior do mesmo dia e
    refaz uma vez em segundo plano.
    """
    today = data["today"]
    return _board.get(sector, (_sources(sector), today), lambda: _build(sector), allow_stale=allow_stale,
                      stale_if=lambda old: old[-1] == today, refresh=lambda: _built(sector, {"today": today}))


def _build(sector: str) -> tuple[dict, dict]:
    """O quadro a partir da previsão atual (nunca a anterior: o resultado fica na cache com a chave nova)."""
    from . import forecast
    fc = forecast.current(sector)
    data = portfolio.current(sector, allow_stale=True)
    customers = {}
    for line in data["lines"]:
        customers.setdefault(line["of"], {"customer": line["customer"], "designation": short_text(line["designation"])})
    names = {rid: m["name"] for rid, m in fc["machines"].items()}
    names.update({u["resource_id"]: u["resource_id"] for u in fc["unschedulable"] if u.get("resource_id") and u["resource_id"] not in names})
    names.update(fc.get("names") or {})
    boxes, missing, extra = boxes_from_forecast(fc, today=fc["today"], names=names)
    template = fc["template"]
    placed = sum(1 for r in fc["operations"].values() if r["scope"] == 0 and r["status"] == "colocada")
    source = {"kind": "plano_em_uso", "origin": fc["origin"], "placed": placed, "missing": missing,
              "second_operation": extra["second_operation"],
              "operations": sum(1 for r in fc["operations"].values() if r["scope"] == 0)
              + sum(1 for u in fc["unschedulable"] if u["scope"] == 0 and u["reason"] != "segunda_operacao"),
              "selected_orders": len({m["of"] for m in fc["meta"].values() if m.get("plan")})}
    for box in boxes:
        box.update(customers.get(box["of"], {"customer": "", "designation": ""}))
        box["shifts"] = _shift_hours(box["timed"], template)
    private = {"timed": defaultdict(list), "boxes": defaultdict(list), "template": template}
    machines = []
    for rid, m in fc["machines"].items():
        mine = [b for b in boxes if b["resource_id"] == rid]
        if not (mine or m.get("has_calendar")):
            continue
        for b in mine:
            private["boxes"][rid].append(b)
            private["timed"][rid].extend((b, t) for t in b["timed"])
        machines.append({"id": rid, "name": m["name"], "member": True,
                         "boxes": [{k: v for k, v in b.items() if k != "timed"} for b in mine]})
    days = _machine_days([m["id"] for m in machines], fc["today"])
    for m in machines:
        m["days"] = days.get(m["id"], {})
    machines.sort(key=lambda m: (not m["boxes"], m["name"]))
    result = {"sector": sector, "sector_label": portfolio.SECTORS[sector], "today": fc["today"],
              "imported_at": data["imported_at"], "source": source, "machines": machines, "template": template, "day_view": True,
              "elsewhere": extra["elsewhere"], "not_in_plans": not_in_plans(today=fc["today"]), "stale": bool(fc.get("stale"))}
    return result, private


def board(sector: str, *, allow_stale: bool = False) -> dict:
    """Gantt simples: o plano em uso (as linhas Planeado na previsão com capacidade finita).

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
