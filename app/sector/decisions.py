"""Decisão «Planear» efetiva de uma linha (plano de 02/10/2026).

Precedência, da mais específica para a menos específica:
1. decisão do membro (sector_member_selection), procurada pela chave atual da linha e pelos
   selection_aliases que a projeção conserva entre importações; 'cleared' é uma desmarcação explícita;
2. decisão antiga por (OF, referência);
3. decisão antiga por (OF, '*').
Sem decisão de membro, o resultado é exatamente o das regras antigas: a transição não muda o conjunto
selecionado. O estado mostrado (Planeado / nesting / sem máquina) vem de planning_status.py.

As decisões antigas continuam num dicionário por chave; as dos membros ficam em `members`. Na Carteira
(um setor) as chaves são (OF, referência) e chave do membro; no âmbito do Gantt (vários setores) levam o
setor à frente.
"""
from __future__ import annotations

WHOLE = "*"


class Decisions(dict):
    """Decisões antigas (dict) e decisões por membro (`members`)."""

    def __init__(self, legacy=None, members=None):
        super().__init__(legacy or {})
        self.members = dict(members or {})

    def __bool__(self):
        # Só com decisões por membro continua a haver decisões: `x or {}` não as pode deitar fora.
        return bool(len(self) or self.members)


def member_row(members: dict, keys) -> dict | None:
    for key in keys:
        if key in members:
            return members[key]
    return None


def resolve(legacy: dict, members: dict, legacy_keys, member_keys) -> dict:
    """{decision, source, revision, member_key} for one line; decision None = sem decisão."""
    row = member_row(members, member_keys)
    if row:
        return {"decision": None if row["decision"] == "cleared" else row["decision"],
                "source": "membro", "revision": row["revision"], "member_key": row["member_key"]}
    for key, source in zip(legacy_keys, ("of_referencia", "of")):
        found = legacy.get(key)
        if found:
            return {"decision": found["decision"], "source": source, "revision": 0, "member_key": None}
    return {"decision": None, "source": None, "revision": 0, "member_key": None}


def read_members(c, area: str | None = None) -> list[dict]:
    """Member decisions, or [] before migration 046 is applied."""
    if not c.execute("SELECT to_regclass('planning_mtg.sector_member_selection') t").fetchone()["t"]:
        return []
    sql = ("SELECT area, member_key, production_order_no, reference, decision, reason, actor, decided_at, revision "
           "FROM planning_mtg.sector_member_selection")
    if area:
        return c.execute(sql + " WHERE area = %s ORDER BY member_key", (area,)).fetchall()
    return c.execute(sql + " ORDER BY area, member_key").fetchall()
