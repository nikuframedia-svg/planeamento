"""O que as antigas páginas «Capacidades das máquinas» e «Disponibilidade semanal» mostravam, ligado à
Carga e turnos (pedido do Luís, 06/10/2026: ver tudo na Carga; configurar nas Definições).

Uma só definição de carga continua a ser a da Carga (factos da Carteira, máquina efetiva, semana do
prazo). Daqui só vêm valores por linha e as horas reais, que se juntam a esses factos:
- Horas segundo o Excel: a regra do próprio Excel para a operação principal (MTG3 metros em falta ÷
  velocidade Mt\\h da linha; MTG2 área ÷ taxa da folha CapacidadeMáquinas, ×3 no Thomas acima de 50 peças),
  calculada pelo motor de capacidade (raw/capacity_revision.py) e escalada ao saldo atual da linha
  (a regra é proporcional às peças).
- Peso: já não vem daqui (08/10, F21): a Carga usa o peso da Carteira (load.fact_weight); o daqui fica nas provas.
- Horas reais declaradas: folhas OCR validadas e horas corrigidas à mão, por máquina e semana ISO
  (pela data de produção; não depende da regra de semana do planeamento).
- Cálculo de cada operação: taxa, fórmula, vigência e origem, tal como o motor as usou.
Os conjuntos capacity_items/capacity juntam os dois setores; filtra-se sempre pelo setor de cada linha.
"""
from __future__ import annotations

import threading

from .. import planning

_cache: dict[tuple, object] = {}
_lock = threading.Lock()


def _generation(c, sector: str, dataset: str):
    from ..raw import query
    return query.generation(c, sector, None, dataset)


def _cached(key, build):
    with _lock:
        if key in _cache:
            return _cache[key]
    value = build()
    with _lock:
        for old in [k for k in _cache if k[:2] == key[:2] and k != key]:
            del _cache[old]
        _cache[key] = value
    return value


def machine_index(codes: dict, by_id: dict, aliases: dict) -> dict[str, str]:
    """Chave de máquina do motor de capacidade → máquina da Carga.

    O motor usa o ID do recurso confirmado ou «área:nome do Excel»; a Carga usa o ID do recurso.
    """
    index = {rid: rid for rid in by_id}
    for (area, name), code in aliases.items():
        rid = (codes.get(code) or {}).get("id")
        if rid:
            index.setdefault(f"{area}:{name}", rid)
    return index


def excel_lines(c, sector: str) -> dict[str, dict]:
    """Por linha da Carteira (line_key): horas segundo o Excel e peso por peça da operação principal."""
    from ..raw import query
    gen = _generation(c, sector, "capacity_items")

    def build():
        base, params = query.source(gen)
        rows = c.execute(
            "SELECT c.values_json v, c.detail->>'planning_key' k, c.detail->'reference_rate' rr, "
            "c.detail->>'reference_factor' rf, c.detail->>'reference_reason' rreason, c.detail->'inputs' inputs"
            + base + " AND c.values_json->>'area' = %s AND c.values_json->>'primary_operation' = 'true'",
            params + [sector]).fetchall()
        out = {}
        for r in rows:
            v, q = r["v"], r["v"].get("quantity")
            ref, weight = v.get("reference_hours"), v.get("weight")
            out[r["k"]] = {
                "quantity": q,
                "excel_per_unit": ref / q if ref is not None and q else None,
                "weight_per_unit": weight / q if weight is not None and q else None,
                "macro_hours": v.get("macro_hours"), "excel_machine": v.get("machine"),
                "excel_rate": r["rr"], "excel_factor": float(r["rf"]) if r["rf"] not in (None, "") else None,
                "excel_reason": r["rreason"], "inputs": r["inputs"] or {}}
        return out
    return _cached(("items", sector, gen["id"]), build)


def fact_values(fact: dict, lines: dict) -> tuple[float | None, float | None, bool]:
    """(horas segundo o Excel, peso kg, aplica-se) de uma ocorrência da Carga.

    Só a operação principal tem regra no Excel; as seguintes não contam como desconhecidas.
    """
    if fact.get("phase", "principal") != "principal":
        return None, None, False
    line = lines.get(fact.get("line_key"))
    remaining = fact.get("remaining")
    if not line or remaining is None:
        return None, None, True
    excel = line["excel_per_unit"] * remaining if line["excel_per_unit"] is not None else None
    weight = line["weight_per_unit"] * remaining if line["weight_per_unit"] is not None else None
    return excel, weight, True


def actual_hours(c, sector: str, index: dict) -> dict[tuple[str, int, int], dict]:
    """Horas reais declaradas por (máquina da Carga, ano, semana): OCR validado + correções manuais."""
    from ..raw import query
    gen = _generation(c, sector, "capacity")

    def build():
        base, params = query.source(gen)
        rows = c.execute(
            "SELECT c.values_json->>'machine_key' mk, (c.values_json->>'year')::int y, (c.values_json->>'week')::int w, "
            "(c.values_json->>'actual_hours')::float h, c.values_json->>'reference_available_hours' cal"
            + base + " AND c.values_json->>'year' IS NOT NULL AND (c.values_json->>'actual_hours' IS NOT NULL "
            "OR c.values_json->>'reference_available_hours' IS NOT NULL)", params).fetchall()
        out: dict[tuple, dict] = {}
        for r in rows:
            rid = index.get(r["mk"])
            if not rid:
                continue
            cell = out.setdefault((rid, r["y"], r["w"]), {"actual_hours": None, "excel_calendar_hours": None})
            if r["h"] is not None:
                cell["actual_hours"] = (cell["actual_hours"] or 0) + r["h"]
            if r["cal"] not in (None, ""):
                cell["excel_calendar_hours"] = (cell["excel_calendar_hours"] or 0) + float(r["cal"])
        return out
    return _cached(("capacity", sector, gen["id"], hash(frozenset(index.items()))), build)


def proofs(c, sector: str, line_keys: list[str]) -> dict[tuple[str, str], dict]:
    """Cálculo de cada operação de umas linhas: {(line_key, operação): prova} como o motor o fez."""
    from ..raw import query
    if not line_keys:
        return {}
    gen = _generation(c, sector, "capacity_items")
    base, params = query.source(gen)
    rows = c.execute(
        "SELECT c.values_json v, c.detail->>'planning_key' k, (c.detail->'applied_rate') - 'history'::text ar, c.detail->'reference_rate' rr, "
        "c.detail->>'reference_factor' rf, c.detail->>'reference_reason' rreason, c.detail->>'rate_date' rd, "
        "c.detail->>'rate_date_source' rds, c.detail->'inputs' inputs, c.detail->>'reason' reason"
        + base + " AND c.values_json->>'area' = %s AND c.detail->>'planning_key' = ANY(%s)",
        params + [sector, list(line_keys)]).fetchall()
    out = {}
    for r in rows:
        v, applied = r["v"], r["ar"] or {}
        calc = applied.get("calculation") or {}
        out[(r["k"], str(v.get("operation")))] = {
            "planned_hours": v.get("planned_hours"), "rate_source": v.get("rate_source") or applied.get("source"),
            "rate": calc.get("inputs", {}).get("rate"), "method": calc.get("inputs", {}).get("method"),
            "formula": calc.get("formula"), "volume": calc.get("inputs", {}).get("volume"),
            "volume_unit": calc.get("inputs", {}).get("volume_unit"), "setup_minutes": calc.get("inputs", {}).get("setup_minutes"),
            "history_hash": calc.get("history_hash"), "rate_date": r["rd"], "rate_date_source": r["rds"],
            "reason": r["reason"] or applied.get("reason"),
            "excel_hours": v.get("reference_hours"), "excel_rate": r["rr"], "excel_factor": r["rf"], "excel_reason": r["rreason"],
            "macro_hours": v.get("macro_hours"), "macro_column": "Horas Consumidas" if sector == "perfis" else "h teor. Falta",
            "inputs": r["inputs"] or {}, "quantity": v.get("quantity")}
    return out


def posts(by_id: dict, package) -> dict[str, list[str]]:
    """Postos compostos por máquinas, {posto: [máquinas]} pelos IDs da Carga (relação «compoe» do catálogo)."""
    if not package:
        return {}
    from .capacity import physical
    return physical(by_id, (package.get("metadata") or {}).get("relations") or [])["members"]


def context(c, sector: str) -> dict:
    """Tudo o que a Carga precisa destas fontes, numa ligação."""
    from .occurrences import resources_context
    codes, by_id, aliases, _, package = resources_context(c)
    index = machine_index(codes, by_id, aliases)
    try:
        lines = excel_lines(c, sector)
        actual = actual_hours(c, sector, index)
    except planning.PlanningError:  # motor de capacidade ainda sem geração: a Carga funciona sem estes valores
        lines, actual = {}, {}
    # Postos e nomes (08/10, F18): a nota «partilha o posto com …» das máquinas de um posto.
    return {"lines": lines, "actual": actual, "index": index, "posts": posts(by_id, package),
            "names": {rid: r.get("name") or rid for rid, r in by_id.items()}}
