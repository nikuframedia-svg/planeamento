"""Máquina efetiva de uma linha (operação principal), igual em todo o sistema (05/10/2026).

Ordem (decisão do Luís):
1. máquina escolhida na Carteira («Atribuir máquina»), procurada pela chave atual da linha e pelos
   selection_aliases que a projeção conserva entre importações;
2. coluna Máquina da Tabela/Excel;
3. máquina pré-definida do conjunto de famílias SKU a que a família da linha pertence.
A Carteira (estado, Planear, lista vermelha, números das máquinas), as ocorrências e o Gantt leem todos
daqui. Uma sugestão aprendida nunca é máquina efetiva.
"""
from __future__ import annotations

from contextlib import nullcontext

from .. import planning, planning_needs as needs

# Textos que na coluna Máquina querem dizer «sem máquina física» (os mesmos da revisão de capacidades).
PLACEHOLDERS = {"", "por definir", "sem máquina", "sem maquina", "mtg3", "subcontrato", "abocardar",
                "serrote mtg2", "serrote mtg3"}
SOURCES = {"carteira": "Escolhida na Carteira", "tabela": "Coluna Máquina da Tabela", "conjunto": "Conjunto de famílias"}


def normalize(name) -> str:
    text = str(name or "").strip()
    return "" if text.casefold() in PLACEHOLDERS else text


def _exists(c, table: str) -> bool:
    return bool(c.execute("SELECT to_regclass(%s) t", ("planning_mtg." + table,)).fetchone()["t"])


def empty(area: str) -> dict:
    return {"area": area, "members": {}, "sets": [], "family": {}, "digest": needs.digest(needs.serial({"m": [], "s": []}))}


def context(area: str, conn=None) -> dict:
    """Escolhas da Carteira e conjuntos ativos de um setor, com um digest para as caches."""
    planning.check_area(area)
    with (planning.connect(readonly=True) if conn is None else nullcontext(conn)) as c:
        members, sets = [], []
        if _exists(c, "sector_member_machine"):
            members = c.execute("SELECT member_key, production_order_no, reference, resource_id, machine_name, revision, actor, decided_at "
                                "FROM planning_mtg.sector_member_machine WHERE area = %s ORDER BY member_key", (area,)).fetchall()
        if _exists(c, "sector_family_sets"):
            sets = c.execute("SELECT id, name, families, resource_id, machine_name, revision FROM planning_mtg.sector_family_sets "
                             "WHERE area = %s AND NOT archived ORDER BY lower(name)", (area,)).fetchall()
    family = {}
    for s in sets:
        for f in s["families"]:
            family.setdefault(f, s)
    digest = needs.digest(needs.serial({"m": [(m["member_key"], m["resource_id"], m["revision"]) for m in members],
                                        "s": [(str(s["id"]), s["families"], s["resource_id"], s["revision"]) for s in sets]}))
    return {"area": area, "members": {m["member_key"]: m for m in members}, "sets": sets, "family": family, "digest": digest}


def effective(ctx: dict | None, keys, sku_family, tabela) -> dict:
    """{machine, resource_id, source}; machine '' quando a linha não tem máquina."""
    if ctx:
        for key in keys:
            row = ctx["members"].get(key)
            if row:
                return {"machine": row["machine_name"], "resource_id": row["resource_id"], "source": "carteira"}
    machine = normalize(tabela)
    if machine:
        return {"machine": machine, "resource_id": None, "source": "tabela"}
    found = (ctx or {}).get("family", {}).get(sku_family) if sku_family else None
    if found:
        return {"machine": found["machine_name"], "resource_id": found["resource_id"], "source": "conjunto", "set": found["name"]}
    return {"machine": "", "resource_id": None, "source": None}


def digests(conn=None) -> str:
    """Digest dos dois setores (para o carimbo das ocorrências e as referências do Gantt)."""
    with (planning.connect(readonly=True) if conn is None else nullcontext(conn)) as c:
        return needs.digest([context(area, conn=c)["digest"] for area in planning.AREAS])
