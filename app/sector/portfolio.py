"""Carteira: todo o trabalho aberto de um setor, agrupado por tema.

Só leitura. Junta três fontes da mesma importação do Excel:
- a projeção RAW da aplicação: linhas ativas, produção MES associada, máquina, prazo e estado CPIS;
- a linha original do Excel (raw_mtg.plan_production_rows.row_data): notas «Descrição» e «P»;
- a cópia do CPIS dentro do Excel (raw_mtg.cpis_rows): família e data de registo da OF.

Saldo de uma linha = pedido − maior(contador do Excel, produção MES associada), nunca abaixo
de zero. É um saldo em papel: produção ainda não registada pode reduzi-lo.
"""
from __future__ import annotations

import re
import threading
from collections import defaultdict
from contextlib import nullcontext
from datetime import date, datetime, timedelta

from .. import planning
from .references import UNRESOLVED, master_reference

SECTORS = {"cantoneiras": "MTG3 Cantoneiras"}  # MTG2 Perfis entra na fase 6 do plano
OPEN_STATES = set(planning.OPEN_STATES)

WINDOWS = {  # ordem = urgência
    "atrasado": "Data Corte já passada",
    "3_semanas": "Até ao fim da semana ISO +2",
    "mais_tarde": "Mais tarde",
    "sem_data": "Sem Data Corte",
}
LEVELS = {
    "master": "Referência mestre",
    "reference": "Referência (SKU)",
    "of": "OF",
    "work": "Obra / OV",
    "profile": "Perfil",
    "family": "Família",
    "customer": "Cliente",
}
VIEWS = {
    "referencia": ("master", "reference", "of"),
    "of": ("work", "of"),
    "perfil": ("profile", "of"),
    "familia": ("family", "of"),
    "cliente": ("customer", "of"),
}
VIEW_LABELS = {
    "referencia": "Referência: modelo → SKU → OF",
    "of": "OF, por obra / OV",
    "perfil": "Perfil → OF",
    "familia": "Família → OF",
    "cliente": "Cliente → OF",
}
SIGNALS = {
    "prioridade": "Prioridade escrita",
    "anulada": "Marcada «anulada» no Excel",
    "eletrofer": "Feita na Eletrofer",
    "validacao": "Fabricar após validação",
    "estado_cpis": "Estado CPIS por confirmar",
}

STATES = {
    "proposta": "Proposta por decidir",
    "selecionado": "Marcado para planear",
    "excluido": "Excluído",
    "por_decidir": "Sem decisão",
}
BLOCKING = ("anulada", "eletrofer", "validacao", "estado_cpis")  # sinais que tiram uma linha da proposta
WHOLE = "*"  # decisão sobre a OF inteira

_PRIORITY = re.compile(r"(\d+)\s*[ªº]?\s*PRIORIDADE", re.I)
_CANCELLED = re.compile(r"anulad", re.I)
_ELETROFER = re.compile(r"ELE[C]?TROFER", re.I)
_VALIDATION = re.compile(r"AP[ÓO]S\s+(A\s+)?VALIDA", re.I)
_WRITTEN_WEEK = re.compile(r"ENTREGA\s*W\s*(\d{1,2})(?:\s*/\s*(\d{4}))?", re.I)

_SQL = """
WITH g AS (
    SELECT id, dataset, metadata->'snapshot'->>'snapshot_id' AS snapshot
    FROM planning_mtg.raw_generations WHERE dataset = %(dataset)s ORDER BY id DESC LIMIT 1
)
SELECT m.row_key, c.values_json AS v, g.id AS generation, g.snapshot,
       p.row_data->>'Descrição' AS notes, p.row_data->>'P' AS p_value,
       p.row_data->>'Observações' AS observations,
       p.row_data->>'Observações Galvanização' AS galvanising_notes,
       cp.work_type_code, cp.work_type_description, cp.record_date
FROM g
JOIN planning_mtg.raw_members m ON m.dataset = g.dataset AND m.first_generation <= g.id
     AND (m.last_generation IS NULL OR m.last_generation > g.id)
JOIN planning_mtg.raw_resolved_contents c ON c.hash = m.content_hash
LEFT JOIN raw_mtg.plan_production_rows p ON p.snapshot_id = g.snapshot AND p.source_line_id = substr(m.row_key, 7)
LEFT JOIN raw_mtg.cpis_rows cp ON cp.snapshot_id = g.snapshot AND cp.production_order_no = c.values_json->>'of'
WHERE (c.values_json->>'planning_active')::boolean
"""

_cache: dict[str, tuple[tuple, dict]] = {}
_lock = threading.Lock()


def check_sector(sector: str) -> str:
    if sector not in SECTORS:
        raise planning.PlanningError("A Carteira está disponível para MTG3 Cantoneiras; MTG2 Perfis vem depois.")
    return sector


def _number(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _day(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def window_of(cut_date: date | None, today: date) -> str:
    if cut_date is None:
        return "sem_data"
    if cut_date < today:
        return "atrasado"
    end = today - timedelta(days=today.weekday()) + timedelta(weeks=2, days=6)  # domingo da semana ISO +2
    return "3_semanas" if cut_date <= end else "mais_tarde"


def signals_of(designation: str, notes: str, observations: str, galvanising_notes: str, status: str | None) -> dict:
    text = " ".join(x for x in (designation, observations) if x)
    priority = _PRIORITY.search(designation or "")
    week = _WRITTEN_WEEK.search(designation or "")
    return {
        "prioridade": int(priority.group(1)) if priority else None,
        "anulada": bool(_CANCELLED.search(notes or "")),
        "eletrofer": bool(_ELETROFER.search(" ".join(x for x in (notes, galvanising_notes) if x))),
        "validacao": bool(_VALIDATION.search(text)),
        "estado_cpis": status not in OPEN_STATES,
        "entrega_escrita": f"W{int(week.group(1))}" + (f"/{week.group(2)}" if week.group(2) else "") if week else None,
    }


def line_from_row(row: dict, today: date) -> dict | None:
    """One open plan line, or None when nothing is left to cut."""
    v = row["v"]
    quantity = _number(v.get("quantity_required"))
    if quantity is None:
        return None
    done = max(_number(v.get("made")) or 0.0, _number(v.get("ocr_quantity")) or 0.0)
    pieces = max(0.0, quantity - done)
    if pieces <= 0:
        return None
    length = _number(v.get("length_mm"))
    reference = (v.get("component_ref") or "").strip()
    cut_date = _day(v.get("cut_date"))
    status = v.get("status")
    designation = (v.get("designation") or "").strip()
    family_code = (row.get("work_type_code") or "").strip() or None
    family_name = (row.get("work_type_description") or "").strip()
    machine = (v.get("machine") or "").strip()
    return {
        "key": row["row_key"],
        "of": v.get("of") or "",
        "ov": v.get("ov") or "",
        "customer": (v.get("customer") or "").strip() or "Sem cliente",
        "designation": designation,
        "work": v.get("ov") or v.get("of") or "",
        "family_code": family_code,
        "family": f"{family_code} {family_name}".strip() if family_code else "Sem família (OF fora do CPIS)",
        "registered": _day(row.get("record_date")),
        "status": status or "Sem estado CPIS",
        "reference": reference or "Sem referência",
        "master": master_reference(reference) or UNRESOLVED,
        "profile": (v.get("profile") or "").strip() or "Sem perfil",
        "length_mm": length,
        "quantity": quantity,
        "done": done,
        "pieces": pieces,
        "metres": pieces * length / 1000 if length else 0.0,
        "machine": machine,
        "week": _number(v.get("imported_week")),
        "p": _number(row.get("p_value")),
        "cut_date": cut_date,
        "delivery_date": _day(v.get("delivery_date")),
        "window": window_of(cut_date, today),
        "signals": (signals := signals_of(designation, row.get("notes"), row.get("observations"), row.get("galvanising_notes"), status)),
        "proposal": proposal_of(signals, window_of(cut_date, today)),
    }


def proposal_of(signals: dict, window: str) -> str | None:
    """Proposed tier: A prioridade escrita, B atrasado, C até ao fim da semana ISO +2; None fora da proposta."""
    if any(signals.get(name) for name in BLOCKING):
        return None
    if signals.get("prioridade") is not None:
        return "A"
    return {"atrasado": "B", "3_semanas": "C"}.get(window)


def decision_of(line: dict, decisions: dict | None) -> str | None:
    """A decisão mais específica ganha: (OF, referência) antes de (OF, '*')."""
    if not decisions:
        return None
    specific = decisions.get((line["of"], line["reference"]))
    if specific:
        return specific["decision"]
    whole = decisions.get((line["of"], WHOLE))
    return whole["decision"] if whole else None


def state_of(line: dict, decisions: dict | None) -> str:
    decision = decision_of(line, decisions)
    if decision == "selected":
        return "selecionado"
    if decision == "excluded":
        return "excluido"
    return "proposta" if line["proposal"] else "por_decidir"


def load(sector: str, *, today: date | None = None, conn=None) -> dict:
    """All open lines of the sector from the latest projection, cached per generation and day."""
    check_sector(sector)
    today = today or date.today()
    dataset = f"planning:{sector}"
    with (planning.connect(readonly=True) if conn is None else nullcontext(conn)) as c:
        c.execute("SET LOCAL jit = off")
        head = c.execute("SELECT id, metadata->'snapshot'->>'snapshot_id' AS snapshot, created_at "
                         "FROM planning_mtg.raw_generations WHERE dataset = %s ORDER BY id DESC LIMIT 1", (dataset,)).fetchone()
        if not head:
            raise planning.PlanningError("A preparar a consulta deste setor. Tenta dentro de alguns segundos.", 503)
        stamp = (head["id"], today)
        with _lock:
            cached = _cache.get(sector)
        if cached and cached[0] == stamp:
            return cached[1]
        rows = c.execute(_SQL, {"dataset": dataset}).fetchall()
    lines = [line for line in (line_from_row(r, today) for r in rows) if line]
    result = {"sector": sector, "generation": head["id"], "snapshot": head["snapshot"],
              "imported_at": head["created_at"], "today": today, "lines": lines}
    with _lock:
        _cache[sector] = (stamp, result)
    return result


def matches(line: dict, filters: dict) -> bool:
    if filters.get("familia") and line["family_code"] != filters["familia"]:
        return False
    if filters.get("janela") and line["window"] != filters["janela"]:
        return False
    machine = filters.get("maquina")
    if machine == "sem" and line["machine"]:
        return False
    if machine == "com" and not line["machine"]:
        return False
    if machine and machine not in ("sem", "com") and line["machine"] != machine:
        return False
    signal = filters.get("sinal")
    if signal and not line["signals"].get(signal):
        return False
    query = (filters.get("q") or "").strip().upper()
    if query:
        haystack = " ".join((line["of"], line["ov"], line["reference"], line["master"], line["customer"], line["designation"])).upper()
        if query not in haystack:
            return False
    return True


def _summary(lines: list[dict], decisions: dict | None = None) -> dict:
    metres = sum(x["metres"] for x in lines)
    by_state = defaultdict(float)
    for x in lines:
        by_state[state_of(x, decisions)] += x["metres"]
    by_machine = defaultdict(float)
    windows = defaultdict(float)
    signals = defaultdict(int)
    for x in lines:
        by_machine[x["machine"] or "Sem máquina"] += x["metres"]
        windows[x["window"]] += x["metres"]
        for name, value in x["signals"].items():
            if value and name != "entrega_escrita":
                signals[name] += 1
    cut_dates = [x["cut_date"] for x in lines if x["cut_date"]]
    priorities = [x["signals"]["prioridade"] for x in lines if x["signals"]["prioridade"] is not None]
    return {
        "lines": len(lines),
        "ofs": len({x["of"] for x in lines}),
        "pieces": round(sum(x["pieces"] for x in lines)),
        "metres": round(metres, 1),
        "metres_without_machine": round(sum(x["metres"] for x in lines if not x["machine"]), 1),
        "earliest_cut_date": min(cut_dates) if cut_dates else None,
        "windows": {k: round(windows.get(k, 0.0), 1) for k in WINDOWS},
        "machines": [{"machine": m, "metres": round(v, 1)} for m, v in sorted(by_machine.items(), key=lambda kv: -kv[1])[:4]],
        "signals": dict(signals),
        "priority": min(priorities) if priorities else None,
        "written_weeks": sorted({x["signals"]["entrega_escrita"] for x in lines if x["signals"]["entrega_escrita"]}),
        "customers": sorted({x["customer"] for x in lines})[:3],
        "designation": next((x["designation"] for x in lines if x["designation"]), ""),
        "states": {k: round(by_state.get(k, 0.0), 1) for k in STATES},
        "proposed_metres": round(sum(x["metres"] for x in lines if x["proposal"]), 1),
    }


def _urgency(group: dict):
    rank = min((list(WINDOWS).index(w) for w, m in group["windows"].items() if m > 0), default=len(WINDOWS))
    priority = group["priority"] if group["priority"] is not None else 99
    return (priority, rank, group["earliest_cut_date"] or date.max, -group["metres"], group["key"])


def groups(sector: str, view: str = "referencia", path: list[str] | None = None, filters: dict | None = None,
           sort: str = "urgencia", limit: int = 500, *, data: dict | None = None, decisions: dict | None = None) -> dict:
    """Groups at the level below `path` for the chosen view, with totals."""
    if view not in VIEWS:
        raise planning.PlanningError("Vista inválida.")
    levels = VIEWS[view]
    path = list(path or [])
    if len(path) >= len(levels):
        raise planning.PlanningError("Não há mais níveis nesta vista.")
    data = data or load(sector)
    filters = filters or {}
    selected = [x for x in data["lines"] if matches(x, filters)]
    if filters.get("estado"):
        if filters["estado"] not in STATES:
            raise planning.PlanningError("Estado inválido.")
        selected = [x for x in selected if state_of(x, decisions) == filters["estado"]]
    for level, key in zip(levels, path):
        selected = [x for x in selected if x[level] == key]
    level = levels[len(path)]
    buckets = defaultdict(list)
    for x in selected:
        buckets[x[level]].append(x)
    result = [{"key": k, **_summary(v, decisions)} for k, v in buckets.items()]
    result.sort(key=_urgency if sort == "urgencia" else (lambda g: (-g["metres"], g["key"])))
    return {
        "sector": sector, "sector_label": SECTORS[sector], "view": view, "levels": [{"id": l, "label": LEVELS[l]} for l in levels],
        "level": {"id": level, "label": LEVELS[level]}, "path": path, "has_children": len(path) + 1 < len(levels),
        "generation": data["generation"], "snapshot": data["snapshot"], "imported_at": data["imported_at"], "today": data["today"],
        "totals": _summary(selected, decisions), "groups": result[:limit], "truncated": len(result) > limit, "group_count": len(result),
        "windows": WINDOWS, "signals": SIGNALS, "states": STATES,
        "rules": {
            "saldo": "Saldo = pedido − maior(contador do Excel, produção MES associada), nunca abaixo de zero; é um saldo em papel.",
            "modelo": "Referência mestre = código do modelo no início da referência (ED4T40 → ED4, DLT319 → DLT, 1283V053 → 1283).",
            "janela": "«Até ao fim da semana ISO +2» conta a partir de hoje; «Data Corte já passada» é anterior a hoje.",
            "proposta": "Proposta = prioridade escrita, depois Data Corte já passada, depois até ao fim da semana ISO +2; ficam fora as linhas anuladas, da Eletrofer, à espera de validação ou com estado CPIS por confirmar. O corte pela capacidade das máquinas entra quando a capacidade estiver confirmada (semana 2).",
        },
    }


def families(sector: str, *, data: dict | None = None) -> list[dict]:
    data = data or load(sector)
    seen = {}
    for x in data["lines"]:
        if x["family_code"]:
            seen[x["family_code"]] = x["family"]
    return [{"code": k, "label": v} for k, v in sorted(seen.items(), key=lambda kv: kv[1])]


def machines(sector: str, *, data: dict | None = None) -> list[str]:
    data = data or load(sector)
    return sorted({x["machine"] for x in data["lines"] if x["machine"]})
