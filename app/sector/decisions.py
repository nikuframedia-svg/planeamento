"""Decisão «Planear» efetiva de uma linha (plano de 02/10/2026).

Precedência, da mais específica para a menos específica:
1. decisão do membro (sector_member_selection), procurada pela chave atual da linha e pelos
   selection_aliases que a projeção conserva entre importações; 'cleared' é uma desmarcação explícita;
2. decisão antiga por (OF, referência);
3. decisão antiga por (OF, '*').
Sem decisão de membro, o resultado é exatamente o das regras antigas: a transição não muda o conjunto
selecionado. O estado mostrado (Planeado / nesting / sem máquina) vem de planning_status.py.

Quantidade parcial (migração 052, 08/10/2026): uma decisão Planear de um membro pode levar `planned_quantity`
(peças da operação principal; NULL = a linha inteira) e `made_at_plan` (produção já feita quando se planeou).
Regra única, `planned_open`: a produção registada depois de planear consome primeiro a parte planeada. Quando a
parte chega a 0 a linha volta a «Planeado para nesting» pelo resto, sem gravar nada. Planear não é produzir:
a quantidade nunca muda o saldo nem a produção da linha.

As decisões antigas continuam num dicionário por chave; as dos membros ficam em `members`. Na Carteira
(um setor) as chaves são (OF, referência) e chave do membro; no âmbito do Gantt (vários setores) levam o
setor à frente.
"""
from __future__ import annotations

WHOLE = "*"
# Motivos opcionais desde 07/10/2026 (Excluir, prazos, política, máquina por grupo): o autor e a hora ficam
# sempre registados. As tabelas que exigem texto no motivo recebem esta frase quando ninguém escreveu nada.
NO_REASON = "Sem motivo indicado"


def reason_or_default(value) -> str:
    """O motivo escrito, ou NO_REASON quando vem vazio."""
    return str(value or "").strip() or NO_REASON


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
        found = {"decision": None if row["decision"] == "cleared" else row["decision"],
                 "source": "membro", "revision": row["revision"], "member_key": row["member_key"]}
        if row.get("planned_quantity") is not None:  # só com a 052 e numa decisão parcial
            found.update(planned_quantity=row["planned_quantity"], made_at_plan=row.get("made_at_plan"))
        return found
    for key, source in zip(legacy_keys, ("of_referencia", "of")):
        found = legacy.get(key)
        if found:
            return {"decision": found["decision"], "source": source, "revision": 0, "member_key": None}
    return {"decision": None, "source": None, "revision": 0, "member_key": None}


def _whole(value):
    """Peças como int quando são inteiras (3139.0 → 3139)."""
    return int(value) if isinstance(value, float) and value.is_integer() else value


def planned_open(decision_row: dict | None, pieces, done):
    """Peças planeadas ainda por fazer na operação principal de uma linha; None = a linha inteira.

    - sem decisão Planear → 0 (nada planeado);
    - Planear sem quantidade (NULL, as decisões antigas e as da linha inteira) → None;
    - saldo por confirmar (`pieces` None) → None: sem saldo não se sabe a parte, fica a linha inteira;
    - senão: consumida = max(done − made_at_plan, 0) — a produção depois de planear consome primeiro a parte
      planeada — e a parte é clamp(planned_quantity − consumida, 0, pieces).
    Uma parte igual ao saldo é a linha inteira na prática; quem chama decide se a mostra como parcial.
    """
    if not decision_row or decision_row.get("decision") != "selected":
        return 0
    quantity = decision_row.get("planned_quantity")
    if quantity is None or pieces is None:
        return None
    made = decision_row.get("made_at_plan")
    consumed = max(float(done or 0) - float(made if made is not None else (done or 0)), 0.0)
    value = min(float(quantity) - consumed, float(pieces))
    return _whole(max(value, 0.0))


def operation_part(remaining, part, principal_remaining, principal: bool = True):
    """Parte planeada de uma operação, a partir da parte da operação principal (`part`, de planned_open).

    - principal: min(parte, saldo);
    - seguintes (abocardar, 2.ª operação): as peças já cortadas que lhes faltam mais a parte planeada,
      min(saldo próprio, parte + max(saldo próprio − saldo da principal, 0)).
    `part` None (linha inteira) → o saldo todo; saldo desconhecido → None (fica inteiro, por saber).
    """
    if remaining is None or part is None:
        return remaining
    if principal:
        return _whole(max(min(float(part), float(remaining)), 0.0))
    already_cut = max(float(remaining) - float(principal_remaining or 0), 0.0)
    return _whole(max(min(float(remaining), float(part) + already_cut), 0.0))


_QUANTITY_COLUMNS: set = set()  # bases (host, porta, nome) onde a 052 já está aplicada: não volta a perguntar


def has_quantity(c) -> bool:
    """A migração 052 (planned_quantity, made_at_plan) está aplicada nesta base? Guarda só a resposta «sim»."""
    info = getattr(c, "info", None)
    where = (getattr(info, "host", None), getattr(info, "port", None), getattr(info, "dbname", None)) if info else None
    if where is not None and where in _QUANTITY_COLUMNS:
        return True
    found = c.execute("SELECT count(*) AS n FROM pg_attribute WHERE attrelid = to_regclass('planning_mtg.sector_member_selection') "
                      "AND attname IN ('planned_quantity', 'made_at_plan') AND NOT attisdropped").fetchone()["n"] == 2
    if found and where is not None:
        _QUANTITY_COLUMNS.add(where)
    return found


def _quantity_fields(row: dict) -> dict:
    """Sem quantidade, a linha fica exatamente como antes da 052 (os digests das decisões inteiras não mudam)."""
    quantity, made = row.pop("planned_quantity", None), row.pop("made_at_plan", None)
    if quantity is not None:
        row["planned_quantity"] = int(quantity)
        row["made_at_plan"] = _whole(float(made)) if made is not None else None
    return row


def read_members(c, area: str | None = None) -> list[dict]:
    """Member decisions, or [] before migration 046 is applied; with the planned quantity after 052."""
    if not c.execute("SELECT to_regclass('planning_mtg.sector_member_selection') t").fetchone()["t"]:
        return []
    extra = ", planned_quantity, made_at_plan" if has_quantity(c) else ""
    sql = ("SELECT area, member_key, production_order_no, reference, decision, reason, actor, decided_at, revision" + extra +
           " FROM planning_mtg.sector_member_selection")
    if area:
        rows = c.execute(sql + " WHERE area = %s ORDER BY member_key", (area,)).fetchall()
    else:
        rows = c.execute(sql + " ORDER BY area, member_key").fetchall()
    return [_quantity_fields(dict(r)) for r in rows] if extra else rows
