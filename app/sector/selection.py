"""Seleção do trabalho a planear («Planear»), por OF × referência (Passo 6 do plano de 28/09/2026).

A decisão mais específica ganha: (OF, referência) sobrepõe-se a (OF, '*'). Cada mudança fica em
planning_mtg.sector_decision_events, onde só se acrescenta; é daí que o painel vermelho sabe
«planeada há X dias». O mesmo pedido repetido (mesmo request_id) não grava duas vezes.
"""
from __future__ import annotations

import uuid
from contextlib import nullcontext

import psycopg
from psycopg.types.json import Jsonb

from .. import planning, planning_registration as registration
from . import portfolio

WHOLE = portfolio.WHOLE
ACTIONS = {"selecionar": "selected", "excluir": "excluded", "limpar": "cleared"}


def current(sector: str, conn=None) -> dict[tuple[str, str], dict]:
    portfolio.check_sector(sector)
    with (planning.connect(readonly=True) if conn is None else nullcontext(conn)) as c:
        rows = c.execute("SELECT production_order_no, reference, decision, reason, actor, decided_at, revision "
                         "FROM planning_mtg.sector_selection WHERE area = %s", (sector,)).fetchall()
    return {(r["production_order_no"], r["reference"]): r for r in rows}


decision_for = portfolio.decision_of


def pairs_for(lines: list[dict], view: str) -> dict[tuple[str, str], dict]:
    """(OF, referência) pairs covered by the chosen lines, with what was seen at decision time."""
    pairs: dict[tuple[str, str], dict] = {}
    for line in lines:
        key = (line["of"], WHOLE if view == "of" else line["reference"])
        seen = pairs.setdefault(key, {"lines": 0, "pieces": 0.0, "metres": 0.0, "cut_date": None})
        seen["lines"] += 1
        seen["pieces"] += line["pieces"]
        seen["metres"] += line["metres"]
        if line["cut_date"] and (seen["cut_date"] is None or line["cut_date"] < seen["cut_date"]):
            seen["cut_date"] = line["cut_date"]
    for seen in pairs.values():
        seen["pieces"] = round(seen["pieces"])
        seen["metres"] = round(seen["metres"], 1)
        seen["cut_date"] = seen["cut_date"].isoformat() if seen["cut_date"] else None
    return pairs


def apply(payload: dict, *, data: dict | None = None, conn=None) -> dict:
    sector = portfolio.check_sector(str(payload.get("setor") or "cantoneiras"))
    view = str(payload.get("vista") or "referencia")
    path = payload.get("caminho") or []
    filters = payload.get("filtros") or {}
    action = ACTIONS.get(str(payload.get("acao")))
    reason = str(payload.get("motivo") or "").strip() or None
    if not action:
        raise planning.PlanningError("Ação inválida: usa selecionar, excluir ou limpar.")
    if view not in portfolio.VIEWS or not isinstance(path, list) or not path or not all(isinstance(p, str) for p in path):
        raise planning.PlanningError("Escolhe um grupo da Carteira.")
    if not isinstance(filters, dict):
        raise planning.PlanningError("Filtros inválidos.")
    if action == "excluded" and not reason:
        raise planning.PlanningError("Para excluir, indica o motivo.")
    try:
        request_id = uuid.UUID(str(payload.get("request_id")))
    except ValueError:
        raise planning.PlanningError("Pedido sem identificador; recarrega a página.") from None

    data = data or portfolio.load(sector)
    levels = portfolio.VIEWS[view]
    if len(path) > len(levels):
        raise planning.PlanningError("Grupo inválido.")
    chosen = [x for x in data["lines"] if portfolio.matches(x, filters)]
    for level, key in zip(levels, path):
        chosen = [x for x in chosen if x[level] == key]
    if not chosen:
        raise planning.PlanningError("Esse grupo já não tem trabalho aberto. Atualiza a Carteira.", 409)
    pairs = pairs_for(chosen, view)
    actor = registration.human_actor(payload)
    detail = {"vista": view, "caminho": path, "filtros": {k: v for k, v in filters.items() if v},
              "geracao": data["generation"], "importacao": data["snapshot"]}

    try:
        _write(sector, action, reason, actor, request_id, detail, pairs, conn)
    except _Repeated:
        return {"changed": 0, "pairs": len(pairs), "repeated": True, "action": action}
    metres = round(sum(s["metres"] for s in pairs.values()), 1)
    return {"changed": len(pairs), "pairs": len(pairs), "metres": metres, "repeated": False, "action": action, "actor": actor}


class _Repeated(Exception):
    pass


def _write(sector, action, reason, actor, request_id, detail, pairs, conn) -> None:
    """One transaction: the decisions and their events are saved together or not at all."""
    with (planning.connect() if conn is None else nullcontext(conn)) as c:
        repeated = c.execute("SELECT count(*) AS n FROM planning_mtg.sector_decision_events WHERE request_id = %s",
                             (request_id,)).fetchone()["n"]
        if repeated:
            raise _Repeated()
        with c.cursor() as cur:
            if action == "cleared":
                cur.executemany("DELETE FROM planning_mtg.sector_selection WHERE area = %s AND production_order_no = %s AND reference = %s",
                                [(sector, of, ref) for of, ref in pairs])
            else:
                cur.executemany(
                    """INSERT INTO planning_mtg.sector_selection
                           (area, production_order_no, reference, decision, reason, actor, seen)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (area, production_order_no, reference) DO UPDATE
                       SET decision = EXCLUDED.decision, reason = EXCLUDED.reason, actor = EXCLUDED.actor,
                           decided_at = now(), seen = EXCLUDED.seen, revision = sector_selection.revision + 1""",
                    [(sector, of, ref, action, reason, actor, Jsonb(seen)) for (of, ref), seen in pairs.items()])
            try:
                cur.executemany(
                    """INSERT INTO planning_mtg.sector_decision_events
                           (area, kind, production_order_no, reference, action, reason, actor, request_id, detail)
                       VALUES (%s, 'selection', %s, %s, %s, %s, %s, %s, %s)""",
                    [(sector, of, ref, action, reason, actor, request_id, Jsonb({**detail, "seen": seen}))
                     for (of, ref), seen in pairs.items()])
            except psycopg.errors.UniqueViolation:
                raise _Repeated() from None  # o mesmo pedido gravado entretanto por outro clique
