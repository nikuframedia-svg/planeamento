"""Seleção do trabalho a planear («Planear», «Limpar»), por membro (plano de 02/10/2026).

Um membro é uma linha técnica da Carteira (row_key da projeção, reencontrada entre importações pelos
selection_aliases). A ação grava exatamente os membros pedidos — nunca reconstrói a intenção a partir
dos filtros da lista. Antes de gravar, o servidor confere cada membro: ainda existe, a mesma variante
técnica, o mesmo saldo, a mesma máquina e a mesma revisão da decisão (o `token` da pré-visualização).
Qualquer diferença devolve 409 com os membros afetados e nada é gravado.

Planear só grava membros com Máquina (regra do Luís, 02/10/2026): os outros ficam de fora e são contados
em `skipped_no_machine`; se nenhum tiver máquina, a ação é recusada.

Precedência na leitura: membro → (OF, referência) → (OF, '*') (ver decisions.py). As decisões antigas
por OF/referência continuam a valer; novas ações só escrevem decisões por membro. Limpar um membro
coberto por uma decisão herdada grava uma desmarcação explícita ('cleared'), que vence a herança.

Cada ação fica numa transação: decisões, um evento por membro (antes/depois) em
planning_mtg.sector_decision_events e o pedido em sector_selection_requests. O mesmo request_id com o
mesmo conteúdo devolve o resultado já gravado; com outro conteúdo é recusado (409).
"""
from __future__ import annotations

import uuid
from contextlib import nullcontext

import psycopg
from psycopg.types.json import Jsonb

from .. import planning, planning_needs as needs, planning_registration as registration
from . import decisions as resolution, portfolio

WHOLE = portfolio.WHOLE
ACTIONS = {"selecionar": "selected", "excluir": "excluded", "limpar": "cleared"}
MAX_MEMBERS = 50000


def current(sector: str, conn=None) -> resolution.Decisions:
    """Decisões do setor: antigas por (OF, referência) e por membro em `.members`."""
    portfolio.check_sector(sector)
    with (planning.connect(readonly=True) if conn is None else nullcontext(conn)) as c:
        rows = c.execute("SELECT production_order_no, reference, decision, reason, actor, decided_at, revision "
                         "FROM planning_mtg.sector_selection WHERE area = %s", (sector,)).fetchall()
        members = resolution.read_members(c, sector)
    return resolution.Decisions({(r["production_order_no"], r["reference"]): r for r in rows},
                                {r["member_key"]: r for r in members})


decision_for = portfolio.decision_of


def _seen(line: dict) -> dict:
    return {"of": line["of"], "reference": line["reference"], "profile": line["profile"], "length_mm": line["length_mm"],
            "pieces": line["pieces"], "metres": round(line["metres"], 1), "machine": line["machine"],
            "cut_date": line["cut_date"].isoformat() if line["cut_date"] else None, "signature": line["signature"]}


class Conflict(planning.PlanningError):
    def __init__(self, message: str, conflicts: list[dict]):
        super().__init__(message, 409)
        self.fields = {"conflicts": conflicts[:200], "conflict_count": len(conflicts)}


def _requested(payload: dict, data: dict, decisions) -> tuple[list[tuple[dict, str | None]], dict]:
    """[(line, token sent)] for the exact members of the request, and what the request referred to."""
    by_key = {}
    for line in data["lines"]:
        by_key[line["key"]] = line
    if payload.get("membros") is not None:
        members = payload["membros"]
        if not isinstance(members, list) or not members or len(members) > MAX_MEMBERS:
            raise planning.PlanningError("Escolhe pelo menos um membro.")
        result, missing = [], []
        for item in members:
            if not isinstance(item, dict) or not isinstance(item.get("chave"), str):
                raise planning.PlanningError("Membro inválido.")
            line = by_key.get(item["chave"])
            if line is None:
                missing.append({"key": item["chave"], "reason": "Já não está na carteira aberta (concluído ou mudou na importação)."})
            else:
                result.append((line, item.get("token")))
        if missing:
            raise Conflict("Alguns membros já não estão na carteira. Atualiza a seleção.", missing)
        if len({line["key"] for line, _ in result}) != len(result):
            raise planning.PlanningError("Membro repetido no pedido.")
        return result, {"membros": len(result)}
    group = payload.get("grupo")
    if isinstance(group, dict):
        view, path = str(group.get("vista") or ""), group.get("caminho")
        exceto = group.get("exceto") or []
        if not isinstance(exceto, list) or not all(isinstance(k, str) for k in exceto):
            raise planning.PlanningError("Exceções inválidas.")
        portfolio.check_path(view, path if isinstance(path, list) else None)
        if not path:
            raise planning.PlanningError("Escolhe um grupo da Carteira.")
        lines = portfolio.group_lines(data, view, path)
        if not lines:
            raise planning.PlanningError("Esse grupo já não tem trabalho aberto. Atualiza a Carteira.", 409)
        if group.get("selo") and group["selo"] != portfolio.group_seal(lines, decisions):
            raise Conflict("O grupo mudou desde que foi aberto. Abre a lupa outra vez.", [{"group": path, "reason": "Membros, saldos ou decisões mudaram."}])
        excluded = set(exceto)
        chosen = [(x, None) for x in lines if x["key"] not in excluded]
        if not chosen:
            raise planning.PlanningError("Escolhe pelo menos um membro.")
        return chosen, {"vista": view, "caminho": path, "exceto": len(excluded)}
    return _legacy(payload, data), {"contrato": "antigo"}


def _legacy(payload: dict, data: dict) -> list[tuple[dict, None]]:
    """Contrato anterior (vista + caminho, por exemplo o botão Planear do quadro do plano).

    Resolve os membros exatos do grupo e grava-os um a um: já não grava (OF, '*'), que alargava a ação a
    linhas escondidas e a trabalho que chegue depois.
    """
    view = str(payload.get("vista") or "referencia")
    path = payload.get("caminho") or []
    filters = payload.get("filtros") or {}
    if view not in portfolio.VIEWS or not isinstance(path, list) or not path or not all(isinstance(p, str) for p in path):
        raise planning.PlanningError("Escolhe um grupo da Carteira.")
    if not isinstance(filters, dict):
        raise planning.PlanningError("Filtros inválidos.")
    if any(v for k, v in filters.items() if k != "estado"):
        raise planning.PlanningError("Escolhe os membros na lupa: a ação já não usa os filtros da lista.")
    portfolio.check_path(view, path)
    chosen = portfolio.group_lines(data, view, path)
    if not chosen:
        raise planning.PlanningError("Esse grupo já não tem trabalho aberto. Atualiza a Carteira.", 409)
    return [(x, None) for x in chosen]


def request_hash(payload: dict, action: str) -> str:
    """O pedido tal como foi enviado (não o grupo recalculado): uma repetição devolve o resultado gravado."""
    keep = ("setor", "acao", "motivo", "membros", "grupo", "vista", "caminho", "filtros", "maquina")
    return needs.digest({"action": action, **{k: payload.get(k) for k in keep}})


def previous_request(c, request_id, content):
    found = c.execute("SELECT content_hash, result FROM planning_mtg.sector_selection_requests WHERE request_id = %s",
                      (request_id,)).fetchone()
    if not found:
        return None
    if found["content_hash"] != content:
        raise planning.PlanningError("Este pedido já foi usado com outro conteúdo. Recarrega a página.", 409)
    return {**found["result"], "repeated": True, "changed": 0}


def apply(payload: dict, *, data: dict | None = None, conn=None) -> dict:
    sector = portfolio.check_sector(str(payload.get("setor") or "cantoneiras"))
    action = ACTIONS.get(str(payload.get("acao")))
    reason = str(payload.get("motivo") or "").strip() or None
    if not action:
        raise planning.PlanningError("Ação inválida: usa selecionar, excluir ou limpar.")
    if action == "excluded" and not reason:
        raise planning.PlanningError("Para excluir, indica o motivo.")
    try:
        request_id = uuid.UUID(str(payload.get("request_id")))
    except ValueError:
        raise planning.PlanningError("Pedido sem identificador; recarrega a página.") from None

    data = data or portfolio.current(sector)
    actor = registration.human_actor(payload)
    with (planning.connect() if conn is None else nullcontext(conn)) as c:
        if not c.execute("SELECT to_regclass('planning_mtg.sector_member_selection') t").fetchone()["t"]:
            raise planning.PlanningError("A gravação por membro ainda não está instalada (migração 046).", 503)
        c.execute("SELECT pg_advisory_xact_lock(hashtext('sector_member_selection:' || %s))", (sector,))
        content = request_hash(payload, action)
        repeated = previous_request(c, request_id, content)
        if repeated:
            return repeated
        decisions = current(sector, conn=c)
        chosen, scope = _requested(payload, data, decisions)
        skipped = 0
        if action == "selected":
            if payload.get("membros") is None:
                # Planear um grupo não anula exclusões: um membro excluído só volta se for escolhido um a um.
                chosen = [(line, token) for line, token in chosen if portfolio.effective(line, decisions)["decision"] != "excluded"]
            if not chosen:
                raise planning.PlanningError("Todas estas linhas estão excluídas; escolhe-as uma a uma na lupa para as planear.")
            with_machine = [(line, token) for line, token in chosen if line["machine"]]
            skipped = len(chosen) - len(with_machine)
            if not with_machine:
                raise planning.PlanningError("Nenhum destes membros tem máquina. Dá-lhes máquina antes de Planear.")
            chosen = with_machine
        conflicts, changes = [], []
        for line, token in chosen:
            before = portfolio.effective(line, decisions)
            if token is not None and token != portfolio.member_token(line, before["revision"]):
                conflicts.append({"key": line["key"], "of": line["of"], "reference": line["reference"],
                                  "reason": "Mudou desde a pré-visualização (saldo, máquina, variante ou decisão)."})
                continue
            after = _after(action, line, decisions)
            if after["decision"] == before["decision"]:
                continue  # a decisão efetiva já é esta: nada a gravar neste membro
            changes.append((line, before, after))
        if conflicts:
            raise Conflict("Alguns membros mudaram entretanto. Nada foi gravado; revê a seleção.", conflicts)
        detail = {"ambito": scope, "geracao": data["generation"], "importacao": data["snapshot"]}
        result = {"changed": len(changes), "members": len(chosen), "skipped_no_machine": skipped, "action": action, "actor": actor,
                  "metres": round(sum(line["metres"] for line, _, _ in changes), 1), "repeated": False,
                  "keys": [line["key"] for line, _, _ in changes]}
        _write(c, sector, action, reason, actor, request_id, detail, changes, content, result)
    return result


def _after(action, line, decisions) -> dict:
    """Decisão gravada: selected/excluded; Limpar = sem decisão do membro, ou desmarcação explícita se herdar."""
    if action != "cleared":
        return {"decision": action}
    inherited = resolution.resolve(decisions, {}, [(line["of"], line["reference"]), (line["of"], WHOLE)], [])
    return {"decision": None, "explicit": inherited["decision"] is not None}


def _write(c, sector, action, reason, actor, request_id, detail, changes, content, result) -> None:
    """Uma transação: decisões, eventos e pedido gravados juntos ou nada."""
    with c.cursor() as cur:
        try:
            cur.execute("INSERT INTO planning_mtg.sector_selection_requests (request_id, area, action, content_hash, actor, result) "
                        "VALUES (%s, %s, %s, %s, %s, %s)", (request_id, sector, action, content, actor, Jsonb(result)))
        except psycopg.errors.UniqueViolation:
            raise planning.PlanningError("O mesmo pedido foi gravado entretanto. Atualiza a Carteira.", 409) from None
        for line, before, after in changes:
            keys = [line["key"], *line.get("aliases", ())]
            old = cur.execute("DELETE FROM planning_mtg.sector_member_selection WHERE area = %s AND member_key = ANY(%s) "
                              "RETURNING revision", (sector, keys)).fetchall()
            revision = max((r["revision"] for r in old), default=0) + 1
            stored = after["decision"] if after["decision"] else ("cleared" if after.get("explicit") else None)
            if stored:
                cur.execute(
                    """INSERT INTO planning_mtg.sector_member_selection
                           (area, member_key, production_order_no, reference, decision, reason, actor, revision, request_id, seen)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (sector, line["key"], line["of"], line["reference"], stored,
                     reason if stored == "excluded" else None, actor, revision, request_id, Jsonb(_seen(line))))
            cur.execute(
                """INSERT INTO planning_mtg.sector_decision_events
                       (area, kind, production_order_no, reference, member_key, action, reason, actor, request_id, detail)
                   VALUES (%s, 'member', %s, %s, %s, %s, %s, %s, %s, %s)""",
                (sector, line["of"], line["reference"], line["key"], action, reason, actor, request_id,
                 Jsonb({**detail, "seen": _seen(line), "revision": revision,
                        "before": {k: before[k] for k in ("decision", "source", "revision")},
                        "after": {"decision": after["decision"], "stored": stored}})))
