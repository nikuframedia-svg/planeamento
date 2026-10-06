"""Conjuntos de referências (plano de 01/10/2026, secção 5).

Criados colando uma lista, a partir das linhas escolhidas ou guardando um filtro:
- congelado: lista literal por revisão (a referência introduzida é a identidade; grafias parecidas
  não se fundem; desconhecidas ficam guardadas como pendentes);
- dinâmico: guarda o filtro e recalcula os membros na população atual.

Uma referência em dois conjuntos continua a ser uma só ocorrência de trabalho: a pertença é um
metadado e a união nunca duplica horas ou peças. O mesmo SKU em duas OF continua a ser duas
necessidades distintas.
"""
from __future__ import annotations

from contextlib import nullcontext
import re
import uuid

from psycopg.types.json import Jsonb

from .. import planning, planning_needs as needs

MAX_MEMBERS = 20000
_SEPARATORS = re.compile(r"[\n\r\t;,]+")


def _exists(c) -> bool:
    return bool(c.execute("SELECT to_regclass('planning_mtg.sector_reference_sets') t").fetchone()["t"])


def parse(text_or_list) -> tuple[list[str], int]:
    """Literal references in order; returns (unique, repeated count). Spaces inside a code are kept."""
    if isinstance(text_or_list, list):
        items = [str(x) for x in text_or_list]
    else:
        items = _SEPARATORS.split(str(text_or_list or ""))
    clean = [x.strip() for x in items if x and x.strip()]
    unique = list(dict.fromkeys(clean))
    if len(unique) > MAX_MEMBERS or any(len(x) > 200 for x in unique):
        raise planning.PlanningError(f"Lista demasiado grande (máximo {MAX_MEMBERS} referências de até 200 caracteres).")
    return unique, len(clean) - len(unique)


def _sets(c, area):
    if not _exists(c):
        return []
    return c.execute("SELECT * FROM planning_mtg.sector_reference_sets WHERE area=%s AND NOT archived ORDER BY name",
                     (area,)).fetchall()


def _members(c, set_ids):
    rows = c.execute("""SELECT m.set_id,m.sku_literal FROM planning_mtg.sector_reference_set_members m
        JOIN planning_mtg.sector_reference_sets s ON s.id=m.set_id AND s.revision=m.revision
        WHERE m.set_id=ANY(%s)""", (list(set_ids),)).fetchall() if set_ids else []
    result = {}
    for r in rows:
        result.setdefault(str(r["set_id"]), set()).add(r["sku_literal"])
    return result


def memberships(c, area, facts):
    """key → [set ids] and set id → name, over the given occurrences (union semantics)."""
    from . import tree
    found = _sets(c, area)
    if not found:
        return {}, {}
    frozen = _members(c, [s["id"] for s in found if s["mode"] == "frozen"])
    result = {}
    for s in found:
        sid = str(s["id"])
        if s["mode"] == "frozen":
            members = frozen.get(sid, set())
            hits = [f for f in facts if f["reference"] in members]
        else:
            filters = tree.clean_filters((s["selector"] or {}).get("filters"))
            hits = [f for f in facts if tree.matches(f, filters)]
        for f in hits:
            result.setdefault(f["key"], []).append(sid)
    return result, {str(s["id"]): s["name"] for s in found}


def listing(area: str) -> dict:
    area = planning.check_area(area)
    with planning.connect(readonly=True) as c:
        found = _sets(c, area)
        counts = {}
        if found:
            for r in c.execute("""SELECT m.set_id,count(*) n FROM planning_mtg.sector_reference_set_members m
                    JOIN planning_mtg.sector_reference_sets s ON s.id=m.set_id AND s.revision=m.revision
                    WHERE s.area=%s GROUP BY m.set_id""", (area,)).fetchall():
                counts[str(r["set_id"])] = r["n"]
        return needs.serial({"sets": [{**s, "members": counts.get(str(s["id"]), 0)} for s in found]})


def detail(area: str, set_id: str) -> dict:
    """Members with their status in the current population; nothing is merged by resemblance."""
    from . import occurrences, tree
    area = planning.check_area(area)
    with planning.connect(readonly=True) as c:
        s = c.execute("SELECT * FROM planning_mtg.sector_reference_sets WHERE id=%s AND area=%s",
                      (needs.uid(set_id), area)).fetchone()
        if not s:
            raise planning.PlanningError("Conjunto não encontrado.", 404)
        data = occurrences.load(area, conn=c, allow_stale=True)
        if s["mode"] == "frozen":
            literals = sorted(_members(c, [s["id"]]).get(str(s["id"]), set()))
        else:
            filters = tree.clean_filters((s["selector"] or {}).get("filters"))
            literals = sorted({f["reference"] for f in data["facts"] if tree.matches(f, filters)})
        catalogue = {r["sku"]: r for r in c.execute(
            "SELECT sku,family,status FROM planning_mtg.sku_family_mappings WHERE area=%s AND sku=ANY(%s)",
            (area, literals)).fetchall()} if c.execute("SELECT to_regclass('planning_mtg.sku_family_mappings') t").fetchone()["t"] else {}
    active = {}
    for f in data["facts"]:
        if f["reference"] in literals:
            a = active.setdefault(f["reference"], {"occurrences": 0, "ofs": set()})
            a["occurrences"] += 1
            a["ofs"].add(f["of"])
    members = [{"reference": ref, "active_occurrences": active.get(ref, {}).get("occurrences", 0),
                "ofs": sorted(active.get(ref, {}).get("ofs", ())),
                "catalogue_family": (catalogue.get(ref) or {}).get("family"),
                "state": "ativa" if ref in active else "no catálogo, sem trabalho ativo" if ref in catalogue else "desconhecida — guardada como pendente"}
               for ref in literals]
    return needs.serial({"set": s, "members": members, "active": sum(m["active_occurrences"] > 0 for m in members),
                         "unknown": sum(m["state"].startswith("desconhecida") for m in members)})


def save(payload: dict, conn=None) -> dict:
    """Create or revise a set. Frozen sets store the literal list of this revision."""
    from .. import planning_registration as registration
    from . import tree
    area = planning.check_area(str(payload.get("setor") or ""))
    try:
        request_id = uuid.UUID(str(payload.get("request_id")))
    except ValueError:
        raise planning.PlanningError("Pedido sem identificador; recarrega a página.") from None
    name = str(payload.get("name") or "").strip()
    if not 1 <= len(name) <= 160:
        raise planning.PlanningError("Indica um nome até 160 caracteres.")
    mode = payload.get("mode")
    if mode not in ("frozen", "dynamic"):
        raise planning.PlanningError("Indica se o conjunto é congelado ou dinâmico.")
    actor = registration.human_actor(payload)
    selector, literals, repeated = {}, [], 0
    if mode == "dynamic":
        filters = tree.clean_filters(payload.get("filters"))
        if not filters:
            raise planning.PlanningError("Um conjunto dinâmico precisa de pelo menos um filtro.")
        selector = {"filters": filters}
    with (planning.connect() if conn is None else nullcontext(conn)) as c:
        c.execute("SELECT pg_advisory_xact_lock(hashtext('sector-reference-sets'))")
        if c.execute("SELECT 1 FROM planning_mtg.sector_config_events WHERE request_id=%s AND kind='reference_set'", (request_id,)).fetchone():
            row = c.execute("""SELECT s.* FROM planning_mtg.sector_config_events e JOIN planning_mtg.sector_reference_sets s
                ON s.id::text=e.subject WHERE e.request_id=%s AND e.kind='reference_set'""", (request_id,)).fetchone()
            return {"repeated": True, "set": needs.serial(row)}
        if mode == "frozen":
            source = payload.get("from")
            if source:
                # Freeze the references of a group or filter as the user sees it now.
                from . import occurrences
                data = occurrences.load(area, conn=c)
                current_sets, _ = memberships(c, area, data["facts"])
                dims = tree.dims_for(source.get("preset"), source.get("dims"))
                chosen = tree.select(data["facts"], dims, [str(p) for p in source.get("path") or []],
                                     tree.clean_filters(source.get("filters")), current_sets)
                literals = sorted({f["reference"] for f in chosen if f["reference"] != "Sem referência"})
                selector = {"frozen_from": {"dims": dims, "path": source.get("path") or [],
                                            "filters": tree.clean_filters(source.get("filters")), "stamp": data["stamp"]}}
            else:
                literals, repeated = parse(payload.get("members"))
            if not literals:
                raise planning.PlanningError("O conjunto não tem referências.")
        ident = needs.uid(payload["id"]) if payload.get("id") else uuid.uuid4()
        prior = c.execute("SELECT * FROM planning_mtg.sector_reference_sets WHERE id=%s FOR UPDATE", (ident,)).fetchone()
        expected = payload.get("expected_revision", 0)
        if (prior["revision"] if prior else 0) != expected or prior and prior["area"] != area:
            raise planning.PlanningError("O conjunto mudou entretanto. Reabre-o antes de gravar.", 409)
        revision = prior["revision"] + 1 if prior else 1
        if prior:
            c.execute("""UPDATE planning_mtg.sector_reference_sets SET name=%s,mode=%s,selector=%s,revision=%s,
                actor=%s,updated_at=now() WHERE id=%s""", (name, mode, Jsonb(selector), revision, actor, ident))
        else:
            c.execute("""INSERT INTO planning_mtg.sector_reference_sets(id,area,name,mode,selector,actor)
                VALUES (%s,%s,%s,%s,%s,%s)""", (ident, area, name, mode, Jsonb(selector), actor))
        if literals:
            with c.cursor() as cursor:
                cursor.executemany("""INSERT INTO planning_mtg.sector_reference_set_members(set_id,revision,area,sku_literal)
                    VALUES (%s,%s,%s,%s)""", [(ident, revision, area, ref) for ref in literals])
        c.execute("""INSERT INTO planning_mtg.sector_config_events(kind,area,subject,action,before,after,reason,actor,request_id)
            VALUES ('reference_set',%s,%s,%s,%s,%s,NULL,%s,%s)""",
                  (area, str(ident), "revised" if prior else "created",
                   Jsonb(needs.serial({"name": prior["name"], "mode": prior["mode"], "revision": prior["revision"]})) if prior else None,
                   Jsonb({"name": name, "mode": mode, "revision": revision, "members": len(literals), "selector": selector}),
                   actor, request_id))
        row = c.execute("SELECT * FROM planning_mtg.sector_reference_sets WHERE id=%s", (ident,)).fetchone()
        return {"repeated": False, "set": needs.serial(row), "members": len(literals), "repeated_in_list": repeated}


def archive(payload: dict, conn=None) -> dict:
    from .. import planning_registration as registration
    area = planning.check_area(str(payload.get("setor") or ""))
    try:
        request_id = uuid.UUID(str(payload.get("request_id")))
    except ValueError:
        raise planning.PlanningError("Pedido sem identificador; recarrega a página.") from None
    actor = registration.human_actor(payload)
    with (planning.connect() if conn is None else nullcontext(conn)) as c:
        ident = needs.uid(payload.get("id"))
        prior = c.execute("SELECT * FROM planning_mtg.sector_reference_sets WHERE id=%s AND area=%s FOR UPDATE", (ident, area)).fetchone()
        if not prior:
            raise planning.PlanningError("Conjunto não encontrado.", 404)
        if prior["revision"] != payload.get("expected_revision"):
            raise planning.PlanningError("O conjunto mudou entretanto. Reabre-o.", 409)
        c.execute("UPDATE planning_mtg.sector_reference_sets SET archived=true,revision=revision+1,actor=%s,updated_at=now() WHERE id=%s",
                  (actor, ident))
        c.execute("""INSERT INTO planning_mtg.sector_config_events(kind,area,subject,action,before,after,reason,actor,request_id)
            VALUES ('reference_set',%s,%s,'archived',%s,NULL,NULL,%s,%s) ON CONFLICT DO NOTHING""",
                  (area, str(ident), Jsonb({"name": prior["name"], "revision": prior["revision"]}), actor, request_id))
        return {"archived": True, "id": str(ident)}
