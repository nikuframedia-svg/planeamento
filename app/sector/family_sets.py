"""Conjuntos de famílias SKU com máquina pré-definida (pedido do Luís, 05/10/2026).

Um conjunto é um grupo de famílias SKU criado pelo planeador (ex.: «Treliça pesada» = M + M2 + G4) com
uma máquina. As linhas dessas famílias que não têm máquina escolhida na Carteira nem escrita na Tabela
passam a ter essa máquina (ver machine_choice.py). Cada família está num só conjunto ativo por setor.
Gravações com request_id idempotente, revisão esperada e um evento por alteração.
"""
from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from contextlib import nullcontext

from psycopg.types.json import Jsonb

from .. import planning, planning_needs as needs, planning_registration as registration
from . import machine_choice, portfolio

UNIT = {"cantoneiras": "MTG3", "perfis": "MTG2"}


def machines(sector: str, conn=None) -> list[dict]:
    """Máquinas físicas que se podem escolher neste setor (catálogo), com o ID físico."""
    from .occurrences import resources_context
    from .portfolio_kpis import catalog
    with (planning.connect(readonly=True) if conn is None else nullcontext(conn)) as c:
        codes, by_id, _, _, _ = resources_context(c)
        info = catalog(c, sector) if by_id else {}
    used = {x["machine"] for x in portfolio.current(sector)["lines"] if x["machine"]}
    out = []
    for rid, r in by_id.items():
        meta = info.get(r.get("code")) or {}
        if meta.get("unit") == UNIT[sector] and meta.get("type") in ("maquina", "posto") or r.get("name") in used:
            out.append({"id": rid, "name": r.get("name") or rid, "code": r.get("code"), "process": meta.get("process")})
    return sorted(out, key=lambda m: (m.get("process") or "~", m["name"]))


def listing(sector: str) -> dict:
    portfolio.check_sector(sector)
    data = portfolio.current(sector)
    ctx = machine_choice.context(sector)
    by_family = defaultdict(lambda: {"lines": 0, "metres": 0.0, "tabela": Counter(), "machine_sources": Counter()})
    for x in data["lines"]:
        f = by_family[x["sku_family"]]
        f["lines"] += 1
        f["metres"] += x["metres"]
        if x["tabela_machine"]:
            f["tabela"][x["tabela_machine"]] += 1
        f["machine_sources"][x["machine_source"] or "sem"] += 1
    families = [{"code": code, "lines": f["lines"], "metres": round(f["metres"], 1),
                 "set": (ctx["family"].get(code) or {}).get("name"),
                 "usual_machine": f["tabela"].most_common(1)[0][0] if f["tabela"] else None,
                 "usual_share": round(f["tabela"].most_common(1)[0][1] / sum(f["tabela"].values()), 2) if f["tabela"] else None}
                for code, f in sorted(by_family.items()) if code != "Sem família SKU"]
    sets = []
    for s in ctx["sets"]:
        lines = [x for x in data["lines"] if x["sku_family"] in s["families"]]
        sets.append({"id": str(s["id"]), "name": s["name"], "families": list(s["families"]), "resource_id": s["resource_id"],
                     "machine": s["machine_name"], "revision": s["revision"], "lines": len(lines),
                     "metres": round(sum(x["metres"] for x in lines), 1),
                     "lines_with_set_machine": sum(x["machine_source"] == "conjunto" for x in lines)})
    return needs.serial({"sector": sector, "sector_label": portfolio.SECTORS[sector], "sets": sets, "families": families,
                         "machines": machines(sector), "has_families": bool(families)})


def _request(c, request_id, sector, content, actor):
    found = c.execute("SELECT content_hash, result FROM planning_mtg.sector_selection_requests WHERE request_id = %s", (request_id,)).fetchone()
    if found:
        if found["content_hash"] != content:
            raise planning.PlanningError("Este pedido já foi usado com outro conteúdo. Recarrega a página.", 409)
        return {**found["result"], "repeated": True}
    return None


def save(payload: dict, *, conn=None) -> dict:
    sector = portfolio.check_sector(str(payload.get("setor") or ""))
    name = str(payload.get("nome") or "").strip()
    families = payload.get("familias")
    resource_id = str(payload.get("maquina") or "").strip()
    if not name or len(name) > 120:
        raise planning.PlanningError("Dá um nome ao conjunto (até 120 letras).")
    if not isinstance(families, list) or not families or not all(isinstance(f, str) and f.strip() for f in families):
        raise planning.PlanningError("Escolhe pelo menos uma família.")
    families = sorted({f.strip() for f in families})
    try:
        request_id = uuid.UUID(str(payload.get("request_id")))
        set_id = uuid.UUID(str(payload["id"])) if payload.get("id") else None
    except ValueError:
        raise planning.PlanningError("Pedido inválido; recarrega a página.") from None
    options = {m["id"]: m for m in machines(sector)}
    if resource_id not in options:
        raise planning.PlanningError("Escolhe uma máquina deste setor.")
    actor = registration.human_actor(payload)
    content = needs.digest({"a": "save", "setor": sector, "id": str(set_id) if set_id else None, "nome": name,
                            "familias": families, "maquina": resource_id, "rev": payload.get("expected_revision")})
    with (planning.connect() if conn is None else nullcontext(conn)) as c:
        c.execute("SELECT pg_advisory_xact_lock(hashtext('sector_family_sets:' || %s))", (sector,))
        repeated = _request(c, request_id, sector, content, actor)
        if repeated:
            return repeated
        taken = c.execute("SELECT id, name, f FROM planning_mtg.sector_family_sets, unnest(families) f "
                          "WHERE area = %s AND NOT archived AND f = ANY(%s) AND id IS DISTINCT FROM %s", (sector, families, set_id)).fetchall()
        if taken:
            raise planning.PlanningError("Cada família só pode estar num conjunto: " +
                                         ", ".join(f"{t['f']} já está em «{t['name']}»" for t in taken) + ".", 409)
        before = None
        if set_id:
            before = c.execute("SELECT * FROM planning_mtg.sector_family_sets WHERE id = %s AND area = %s", (set_id, sector)).fetchone()
            if not before or before["archived"]:
                raise planning.PlanningError("Esse conjunto já não existe. Recarrega a página.", 409)
            if payload.get("expected_revision") != before["revision"]:
                raise planning.PlanningError("O conjunto foi alterado entretanto. Recarrega a página.", 409)
            c.execute("UPDATE planning_mtg.sector_family_sets SET name=%s, families=%s, resource_id=%s, machine_name=%s, "
                      "revision=revision+1, actor=%s, updated_at=now() WHERE id=%s",
                      (name, families, resource_id, options[resource_id]["name"], actor, set_id))
        else:
            set_id = uuid.uuid4()
            c.execute("INSERT INTO planning_mtg.sector_family_sets (id, area, name, families, resource_id, machine_name, actor) "
                      "VALUES (%s, %s, %s, %s, %s, %s, %s)", (set_id, sector, name, families, resource_id, options[resource_id]["name"], actor))
        result = {"id": str(set_id), "name": name, "families": families, "machine": options[resource_id]["name"], "repeated": False}
        _event(c, sector, set_id, name, "set_saved", actor, request_id,
               {"before": needs.serial(dict(before)) if before else None, "after": result})
        c.execute("INSERT INTO planning_mtg.sector_selection_requests (request_id, area, action, content_hash, actor, result) "
                  "VALUES (%s, %s, 'family_set', %s, %s, %s)", (request_id, sector, content, actor, Jsonb(result)))
    return result


def archive(payload: dict, *, conn=None) -> dict:
    sector = portfolio.check_sector(str(payload.get("setor") or ""))
    try:
        request_id = uuid.UUID(str(payload.get("request_id")))
        set_id = uuid.UUID(str(payload.get("id")))
    except ValueError:
        raise planning.PlanningError("Pedido inválido; recarrega a página.") from None
    actor = registration.human_actor(payload)
    content = needs.digest({"a": "archive", "setor": sector, "id": str(set_id), "rev": payload.get("expected_revision")})
    with (planning.connect() if conn is None else nullcontext(conn)) as c:
        c.execute("SELECT pg_advisory_xact_lock(hashtext('sector_family_sets:' || %s))", (sector,))
        repeated = _request(c, request_id, sector, content, actor)
        if repeated:
            return repeated
        before = c.execute("SELECT * FROM planning_mtg.sector_family_sets WHERE id = %s AND area = %s AND NOT archived", (set_id, sector)).fetchone()
        if not before:
            raise planning.PlanningError("Esse conjunto já não existe. Recarrega a página.", 409)
        if payload.get("expected_revision") != before["revision"]:
            raise planning.PlanningError("O conjunto foi alterado entretanto. Recarrega a página.", 409)
        c.execute("UPDATE planning_mtg.sector_family_sets SET archived=true, revision=revision+1, actor=%s, updated_at=now() WHERE id=%s",
                  (actor, set_id))
        result = {"id": str(set_id), "name": before["name"], "archived": True, "repeated": False}
        _event(c, sector, set_id, before["name"], "set_archived", actor, request_id, {"before": needs.serial(dict(before))})
        c.execute("INSERT INTO planning_mtg.sector_selection_requests (request_id, area, action, content_hash, actor, result) "
                  "VALUES (%s, %s, 'family_set', %s, %s, %s)", (request_id, sector, content, actor, Jsonb(result)))
    return result


def _event(c, sector, set_id, name, action, actor, request_id, detail):
    c.execute("""INSERT INTO planning_mtg.sector_decision_events
                     (area, kind, production_order_no, reference, member_key, action, actor, request_id, detail)
                 VALUES (%s, 'family_set', '', %s, %s, %s, %s, %s, %s)""",
              (sector, name, str(set_id), action, actor, request_id, Jsonb(detail)))
