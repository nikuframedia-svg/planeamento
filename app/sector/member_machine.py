"""«Atribuir máquina» na Carteira: as linhas marcadas vão todas para a máquina escolhida (05/10/2026).

A escolha fica na aplicação (sector_member_machine), por membro, e vence a coluna Máquina da Tabela e o
conjunto de famílias (machine_choice.py). O Excel não muda. `maquina: null` tira a escolha da Carteira.
A escrita está em `write_choice`, também usada pelo Gantt (origem «gantt», Etapa 4).
Mesmo contrato do Planear: membros exatos com token (ou grupo com selo), 409 sem escrita parcial se algo
mudou, request_id idempotente, uma transação com um evento por membro. Pode misturar conjuntos.
"""
from __future__ import annotations

import uuid
from contextlib import nullcontext

from psycopg.types.json import Jsonb

from .. import planning, planning_registration as registration
from . import family_sets, machine_choice, portfolio, selection


def apply(payload: dict, *, data: dict | None = None, conn=None) -> dict:
    sector = portfolio.check_sector(str(payload.get("setor") or ""))
    resource_id = payload.get("maquina")
    if resource_id is not None and not isinstance(resource_id, str):
        raise planning.PlanningError("Máquina inválida.")
    if payload.get("membros") is None and not isinstance(payload.get("grupo"), dict):
        raise planning.PlanningError("Marca as linhas a que queres dar a máquina.")
    try:
        request_id = uuid.UUID(str(payload.get("request_id")))
    except ValueError:
        raise planning.PlanningError("Pedido sem identificador; recarrega a página.") from None
    machine = None
    if resource_id:
        machine = next((m for m in family_sets.machines(sector, conn=conn) if m["id"] == resource_id), None)
        if not machine:
            raise planning.PlanningError("Escolhe uma máquina deste setor.")
    data = data or portfolio.current(sector)
    actor = registration.human_actor(payload)
    with (planning.connect() if conn is None else nullcontext(conn)) as c:
        if not c.execute("SELECT to_regclass('planning_mtg.sector_member_machine') t").fetchone()["t"]:
            raise planning.PlanningError("A máquina por linha ainda não está instalada (migração 048).", 503)
        c.execute("SELECT pg_advisory_xact_lock(hashtext('sector_member_machine:' || %s))", (sector,))
        content = selection.request_hash(payload, "machine")
        repeated = selection.previous_request(c, request_id, content)
        if repeated:
            return repeated
        decisions = selection.current(sector, conn=c)
        chosen, scope, _ = selection._requested(payload, data, decisions)
        ctx = machine_choice.context(sector, conn=c)
        conflicts, changes = [], []
        for line, token in chosen:
            before = portfolio.effective(line, decisions)
            if token is not None and token != portfolio.member_token(line, before["revision"]):
                conflicts.append({"key": line["key"], "of": line["of"], "reference": line["reference"],
                                  "reason": "Mudou desde que foi marcada (saldo, máquina, variante ou decisão)."})
                continue
            keys = [line["key"], *line.get("aliases", ())]
            current = next((ctx["members"][k] for k in keys if k in ctx["members"]), None)
            if (current or {}).get("resource_id") == resource_id or (current is None and resource_id is None):
                continue  # já é esta a escolha da Carteira
            changes.append((line, keys, current))
        if conflicts:
            raise selection.Conflict("Algumas linhas mudaram entretanto. Nada foi gravado; revê a seleção.", conflicts)
        result = {"changed": len(changes), "members": len(chosen), "machine": machine["name"] if machine else None,
                  "action": "machine", "actor": actor, "repeated": False, "keys": [line["key"] for line, _, _ in changes],
                  "metres": round(sum(line["metres"] for line, _, _ in changes), 1)}
        detail = {"ambito": scope, "geracao": data["generation"], "importacao": data["snapshot"]}
        c.execute("INSERT INTO planning_mtg.sector_selection_requests (request_id, area, action, content_hash, actor, result) "
                  "VALUES (%s, %s, 'machine', %s, %s, %s)", (request_id, sector, content, actor, Jsonb(result)))
        write_choice(c, sector, [line for line, _, _ in changes], machine, "carteira", actor=actor, request_id=request_id,
                     detail=detail, ctx=ctx)
    return result


def write_choice(conn, sector: str, lines: list[dict], machine: dict | None, origem: str, *, actor: str, request_id,
                 detail: dict | None = None, ctx: dict | None = None) -> list[dict]:
    """Grava a escolha da Carteira de cada linha (`machine` {id, name}; None tira a escolha), um evento por linha.

    A mesma escrita de «Atribuir máquina» (origem «carteira») e do Gantt (origem «gantt», Etapa 4): a Carteira, a
    Carga e o Gantt leem todos a mesma escolha (machine_choice.py). Sem verificação de tokens nem pedido gravado:
    quem chama decide o que muda e guarda o pedido. Outra origem fica em `seen` e no evento.

    Devolve, por linha: {key, keys, before ({resource_id, machine_name, revision} da escolha anterior ou None),
    revision (a gravada)} — o que o Desfazer do Gantt precisa para só repor se a escolha atual ainda for esta.
    """
    ctx = ctx if ctx is not None else machine_choice.context(sector, conn=conn)
    extra = {} if origem == "carteira" else {"origem": origem}
    written = []
    with conn.cursor() as cur:
        for line in lines:
            keys = [line["key"], *line.get("aliases", ())]
            current = next((ctx["members"][k] for k in keys if k in ctx["members"]), None)
            old = cur.execute("DELETE FROM planning_mtg.sector_member_machine WHERE area = %s AND member_key = ANY(%s) RETURNING revision",
                              (sector, keys)).fetchall()
            revision = max((r["revision"] for r in old), default=0) + 1
            seen = selection._seen(line)
            if machine:
                cur.execute("""INSERT INTO planning_mtg.sector_member_machine
                                   (area, member_key, production_order_no, reference, resource_id, machine_name, actor, revision, request_id, seen)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                            (sector, line["key"], line["of"], line["reference"], machine["id"], machine["name"], actor, revision,
                             request_id, Jsonb({**seen, **extra})))
            cur.execute("""INSERT INTO planning_mtg.sector_decision_events
                               (area, kind, production_order_no, reference, member_key, action, actor, request_id, detail)
                           VALUES (%s, 'machine', %s, %s, %s, %s, %s, %s, %s)""",
                        (sector, line["of"], line["reference"], line["key"], "machine" if machine else "machine_cleared", actor, request_id,
                         Jsonb({**(detail or {}), **extra, "seen": seen, "revision": revision,
                                "before": {"carteira": (current or {}).get("machine_name"), "tabela": line.get("tabela_machine"),
                                           "efetiva": line["machine"], "origem": line.get("machine_source"),
                                           "familia": line.get("sku_family"), "perfil": line.get("profile")},
                                "after": {"carteira": machine["name"] if machine else None}})))
            written.append({"key": line["key"], "keys": keys, "revision": revision,
                            "before": {"resource_id": current["resource_id"], "machine_name": current["machine_name"],
                                       "revision": current["revision"]} if current else None})
    return written
