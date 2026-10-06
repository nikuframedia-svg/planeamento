"""KPIs da Carteira: carga por máquina, acréscimo da seleção e resumo por estado (plano de 02/10/2026).

Três conjuntos separados (GD01): F, a lista filtrada (portfolio.groups); S, os membros marcados no
rascunho; B, a carga já planeada do setor. Nada aqui aceita filtros da lista: o resumo depende só do
setor, das fontes e das decisões gravadas.

- B (carga atual de cada máquina): linhas «Planeado» (Planear e Máquina) — o trabalho que o Gantt
  recebe. Uma máquina sugerida nunca entra em B.
- Acréscimo de S: linhas marcadas «Planeado para nesting» (com Máquina, ainda sem Planear), na sua
  máquina. Marcar uma linha já planeada acrescenta zero; sem máquina não se planeia (fica à parte).
- Resumo: Planeado / Planeado para nesting / Sem máquina atribuída — uma partição de todo o setor, em
  metros, horas e toneladas (saldo de peças × peso unitário; sem peso conta à parte).
- Metros e peças contam uma vez por linha (operação principal); horas somam-se por ocorrência e só com a
  duração calculada para a máquina atribuída e o saldo atual. Desconhecido nunca vira zero: conta-se à
  parte.
- Máquinas agrupadas pelo ID físico do catálogo (aliases incluídos); nomes fora do catálogo (por
  exemplo Ficep XP T7) aparecem com o nome, sem serem classificados.
"""
from __future__ import annotations

from collections import defaultdict

from .. import planning, planning_needs as needs
from . import planning_status, portfolio

PANELS = {
    "cantoneiras": [("puncao", "Punção", {"Punção"}), ("broca", "Broca", {"Broca"})],
    "perfis": [("mtg2", "Máquinas da MTG2", None)],
}
UNIT = {"cantoneiras": "MTG3", "perfis": "MTG2"}
NO_MACHINE = "Sem máquina"


def _empty():
    return {"metres": 0.0, "hours": 0.0, "hours_unknown": 0, "metres_unknown": 0, "lines": set()}


def _add(target, fact, line):
    """Horas por ocorrência; metros da linha (os mesmos da lista) só na ocorrência principal."""
    target["lines"].add(line["key"])
    if fact.get("phase", "principal") == "principal":
        if line["balance_unknown"]:
            target["metres_unknown"] += 1
        else:
            target["metres"] += line["metres"]
    hours = fact.get("load_hours") if fact.get("machine_basis") == "atribuída" else None
    if not fact.get("hours_counted", True):
        return  # linha sem ocorrência principal: as horas estão nas ocorrências seguintes
    if hours is None:
        target["hours_unknown"] += 1
    else:
        target["hours"] += hours


def _out(value):
    return {"metres": round(value["metres"], 1), "hours": round(value["hours"], 1), "hours_unknown": value["hours_unknown"],
            "metres_unknown": value["metres_unknown"], "lines": len(value["lines"])}


def bucket(fact, names: dict | None = None) -> str | None:
    """ID físico da máquina atribuída (pelo ID, ou pelo nome do catálogo); o nome quando a máquina não
    está no catálogo; None sem máquina."""
    if fact.get("assigned_resource_id"):
        return fact["assigned_resource_id"]
    machine = (fact.get("machine") or NO_MACHINE).strip()
    if machine == NO_MACHINE or not machine:
        return None
    return (names or {}).get(machine.casefold()) or "nome:" + machine


def _facts_by_line(data: dict, facts: list[dict]) -> dict[str, list[dict]]:
    """Ocorrências de cada linha; sem a camada de ocorrências, uma ocorrência principal pela linha."""
    by_line = defaultdict(list)
    for f in facts:
        by_line[f["line_key"]].append(f)
    for line in data["lines"]:
        facts = by_line[line["key"]]
        if not any(f.get("phase", "principal") == "principal" for f in facts):
            # Sem ocorrência principal em aberto (ou sem a camada de ocorrências): os metros da linha
            # contam uma vez, na máquina da linha, com horas desconhecidas.
            facts.insert(0, {"line_key": line["key"], "phase": "principal", "assigned_resource_id": None,
                             "machine": line["machine"] or NO_MACHINE, "machine_basis": None,
                             "load_hours": None, "suggestion": None, "hours_counted": not facts})
    return by_line


def catalog(c, sector: str) -> dict:
    """Processo físico e setor de cada recurso, do catálogo da base de pesquisa."""
    from ..gantt import research
    if not research.enabled():
        return {}
    metadata = research.load(c)["metadata"]
    processes = defaultdict(set)
    for cap in metadata.get("capacities", []):
        if cap.get("processo_fisico"):
            processes[cap["recurso_codigo"]].add(cap["processo_fisico"])
    return {r["codigo"]: {"process": next(iter(processes[r["codigo"]])) if len(processes[r["codigo"]]) == 1 else None,
                          "unit": r.get("setor"), "type": r.get("tipo")} for r in metadata.get("resources", [])}


def context(sector: str, *, data=None, decisions=None, occurrences_data=None, resources_catalog=None) -> dict:
    """Everything the KPIs read, loaded once; tests pass synthetic parts."""
    from . import selection
    portfolio.check_sector(sector)
    data = data or portfolio.current(sector)
    decisions = selection.current(sector) if decisions is None else decisions
    if occurrences_data is None:
        from . import occurrences
        try:
            occurrences_data = occurrences.load(sector, allow_stale=True)
        except planning.PlanningError as exc:
            if exc.status != 503:
                raise
            occurrences_data = {"facts": [], "resources": {}, "stale": True, "stamp": None}
    if resources_catalog is None:
        with planning.connect(readonly=True) as c:
            resources_catalog = catalog(c, sector)
    names = {str(r.get("name") or "").strip().casefold(): rid for rid, r in (occurrences_data.get("resources") or {}).items()}
    return {"sector": sector, "data": data, "decisions": decisions, "occ": occurrences_data, "catalog": resources_catalog, "names": names,
            "facts": _facts_by_line(data, [f for f in occurrences_data.get("facts", []) if f.get("line_key")])}


def _machines(ctx) -> dict[str, dict]:
    """Máquinas do painel: todas as do catálogo com processo do setor, e as que têm carga."""
    resources = ctx["occ"].get("resources") or {}
    out = {}
    for rid, r in resources.items():
        info = ctx["catalog"].get(r.get("code")) or {}
        out[rid] = {"id": rid, "name": r.get("name") or rid, "code": r.get("code"), "process": info.get("process"),
                    "unit": info.get("unit"), "type": info.get("type") or r.get("type"), "in_catalog": True}
    return out


def _panel_of(sector, machine) -> str:
    for code, _, processes in PANELS[sector]:
        if processes is None:
            if machine["in_catalog"] and machine.get("unit") == UNIT[sector]:
                return code
        elif machine.get("process") in processes:
            return code
    return "outras"


def version(ctx) -> str:
    from .scope import digest
    return needs.digest([ctx["data"]["generation"], ctx["occ"].get("stamp"), digest(ctx["decisions"])])[:24]


def overview(sector: str, **kw) -> dict:
    """Carga atual por máquina e resumo por estado. Não depende dos filtros da lista."""
    ctx = context(sector, **kw)
    data, decisions = ctx["data"], ctx["decisions"]
    machines = _machines(ctx)
    base = defaultdict(_empty)
    summary = {code: {**_empty(), "pieces": 0.0, "ofs": set(), "kg": 0.0, "kg_unknown": 0} for code in planning_status.STATUS}
    for line in data["lines"]:
        found = portfolio.effective(line, decisions)
        status = planning_status.classify(found, line["machine"])
        facts = ctx["facts"].get(line["key"], [])
        for f in facts:
            b = bucket(f, ctx["names"])
            if b and b not in machines:
                machines[b] = {"id": b, "name": b.removeprefix("nome:"), "code": None, "process": None, "unit": None,
                               "type": None, "in_catalog": False}
            if b and status["planeado"]:
                _add(base[b], f, line)
        code = next(c for c, value in status.items() if value)
        s = summary[code]
        s["pieces"] += line["pieces"] or 0
        s["ofs"].add(line["of"])
        if line.get("kg") is None:
            s["kg_unknown"] += 1  # sem peso unitário: não conta como zero
        else:
            s["kg"] += line["kg"]
        for f in facts:
            _add(s, f, line)
    panels = {code: {"id": code, "label": label, "machines": []} for code, label, _ in PANELS[sector]}
    others = []
    for rid, m in machines.items():
        panel = _panel_of(sector, m)
        if panel == "outras":
            if base[rid]["metres"] > 0 or base[rid]["hours"] > 0:
                others.append({"id": rid, "name": m["name"], "base": _out(base[rid])})
            continue
        if PANELS[sector][0][2] is None and rid not in base and m.get("type") != "maquina":
            continue  # MTG2: postos sem carga não ocupam o painel
        panels[panel]["machines"].append({**{k: m[k] for k in ("id", "name", "code", "process", "in_catalog")},
                                          "base": _out(base[rid]) if rid in base else _out(_empty())})
    for p in panels.values():
        p["machines"].sort(key=lambda m: m["name"])
    return {
        "sector": sector, "sector_label": portfolio.SECTORS[sector], "version": version(ctx),
        "generation": data["generation"], "imported_at": data["imported_at"], "stale": bool(ctx["occ"].get("stale")),
        "panels": list(panels.values()), "other_machines": sorted(others, key=lambda m: m["name"]),
        "summary": [{"code": code, "label": label, "origin": planning_status.ORIGINS[code],
                     **_out(summary[code]), "pieces": round(summary[code]["pieces"]), "ofs": len(summary[code]["ofs"]),
                     "tonnes": round(summary[code]["kg"] / 1000, 2), "weight_unknown": summary[code]["kg_unknown"]}
                    for code, label in planning_status.STATUS.items()],
        "rules": __doc__.split("\n\n", 1)[1].strip(),
    }


def preview(payload: dict, **kw) -> dict:
    """Acréscimo dos membros marcados (S) por máquina. Só consulta: nada é gravado.

    Só as linhas em «Planeado para nesting» acrescentam (na sua máquina). As já planeadas acrescentam
    zero; as sem máquina não podem ser planeadas e contam à parte, uma vez por linha.
    """
    sector = portfolio.check_sector(str(payload.get("setor") or ""))
    keys = portfolio.keys_from(payload)
    ctx = context(sector, **kw)
    data, decisions = ctx["data"], ctx["decisions"]
    by_key = {x["key"]: x for x in data["lines"]}
    machines = _machines(ctx)
    delta = defaultdict(_empty)
    already = _empty()
    to_plan = {"lines": 0, "kg": 0.0, "kg_unknown": 0}  # linhas marcadas em nesting: passam a Planeado
    no_machine = {"lines": 0, "metres": 0.0, "metres_unknown": 0}
    unknown = []
    for key in dict.fromkeys(keys):
        line = by_key.get(key)
        if line is None:
            unknown.append(key)
            continue
        if not line["machine"]:
            no_machine["lines"] += 1
            if line["balance_unknown"]:
                no_machine["metres_unknown"] += 1
            else:
                no_machine["metres"] += line["metres"]
            continue
        status = planning_status.classify(portfolio.effective(line, decisions), line["machine"])
        if status["nesting"]:
            to_plan["lines"] += 1
            if line.get("kg") is None:
                to_plan["kg_unknown"] += 1
            else:
                to_plan["kg"] += line["kg"]
        for f in ctx["facts"].get(key, []):
            b = bucket(f, ctx["names"])
            if b:  # uma operação seguinte ainda sem máquina não tem destino: não acrescenta a nenhuma
                _add(already if status["planeado"] else delta[b], f, line)
    return {
        "sector": sector, "version": version(ctx), "stale": bool(ctx["occ"].get("stale")),
        "members": len(dict.fromkeys(keys)) - len(unknown), "unknown_keys": unknown[:50], "unknown_count": len(unknown),
        "delta": {b: {"name": (machines.get(b) or {}).get("name") or b.removeprefix("nome:"), **_out(v)} for b, v in delta.items()},
        "already_planned": _out(already),
        "no_machine": {**no_machine, "metres": round(no_machine["metres"], 1)},
        "to_plan": {"lines": to_plan["lines"], "tonnes": round(to_plan["kg"] / 1000, 2), "weight_unknown": to_plan["kg_unknown"]},
    }
