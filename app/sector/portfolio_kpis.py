"""KPIs da Carteira: carga por máquina, acréscimo da seleção e resumo por estado (plano de 02/10/2026).

Três conjuntos separados (GD01): F, a lista filtrada (portfolio.groups); S, os membros marcados no
rascunho; B, a carga já planeada do setor. O único filtro da lista aceite é o Prazo (semanas, P4 08/10): com
semanas escolhidas cada máquina mostra a carga e a capacidade dessas semanas, lidas das mesmas células da Carga
e turnos (load.week_slice), e o Resumo dá metros e toneladas das linhas dessas semanas e horas pela semana da
operação principal (Planeado ← no plano, nesting ← a vencer, sem máquina ← na sugerida). Os outros filtros
continuam sem mexer nos KPIs.

- B (carga atual de cada máquina): linhas «Planeado» (Planear e Máquina) — o trabalho que o Gantt
  recebe. Uma máquina sugerida nunca entra em B.
- Acréscimo de S: linhas marcadas «Planeado para nesting» (com Máquina, ainda sem Planear), na sua
  máquina. Marcar uma linha já planeada acrescenta zero; as sem máquina contam à parte (ao Planear recebem a
  máquina sugerida, que só se conhece quando é gravada).
- Resumo: Planeado / Planeado para nesting / Sem máquina atribuída — uma partição de todo o setor, em
  metros, horas e toneladas (saldo de peças × peso unitário; sem peso conta à parte).
- Metros e peças contam uma vez por linha (operação principal); horas somam-se por ocorrência e só com a
  duração calculada para a máquina atribuída e o saldo atual. Desconhecido nunca vira zero: conta-se à
  parte.
- Máquinas agrupadas pelo ID físico do catálogo (aliases incluídos); nomes fora do catálogo (por
  exemplo Ficep XP T7) aparecem com o nome, sem serem classificados.
- 2.ª operação das cantoneiras (08/10, second_operation.py): fora do plano; não soma horas nem «horas
  desconhecidas» (como na Carga, que a tira das células e dos totais).
- Linha planeada em parte (08/10): B leva só a parte planeada (horas e metros na proporção das peças, exato
  porque as horas são lineares nas peças); no Resumo a parte fica em Planeado e o resto em nesting, e a linha
  conta uma vez, em Planeado. Na pré-visualização o resto entra no acréscimo.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from .. import planning, planning_needs as needs
from . import planning_status, portfolio, second_operation

PANELS = {
    "cantoneiras": [("puncao", "Punção", {"Punção"}), ("broca", "Broca", {"Broca"})],
    "perfis": [("mtg2", "Máquinas da MTG2", None)],
}
UNIT = {"cantoneiras": "MTG3", "perfis": "MTG2"}
NO_MACHINE = "Sem máquina"


def _empty():
    return {"metres": 0.0, "hours": 0.0, "hours_unknown": 0, "metres_unknown": 0, "lines": set()}


def _add(target, fact, line, sector=None):
    """Horas por ocorrência; metros da linha (os mesmos da lista) só na ocorrência principal."""
    target["lines"].add(line["key"])
    if fact.get("phase", "principal") == "principal":
        if _metres_unknown(line):
            target["metres_unknown"] += 1
        else:
            target["metres"] += line["metres"]
    hours = fact.get("load_hours") if fact.get("machine_basis") == "atribuída" else None
    if not fact.get("hours_counted", True):
        return  # linha sem ocorrência principal: as horas estão nas ocorrências seguintes
    if second_operation.operation(sector, fact):
        return  # 2.ª operação das cantoneiras: fora do plano, não soma horas nem desconhecidas (08/10)
    if hours is None:
        target["hours_unknown"] += 1
    else:
        target["hours"] += hours


def _parts(facts, line, split) -> tuple[list, list]:
    """([(ocorrência, linha)] da parte planeada, [(ocorrência, linha)] do resto) de uma linha (08/10).

    Linha inteira: tudo de um lado. Parcial: cada ocorrência dividida por portfolio.split_fact e os metros da
    linha na mesma proporção das peças da operação principal.
    """
    if not split["partial"]:
        both = [(f, line) for f in facts]
        return (both, []) if split["status"]["planeado"] else ([], both)
    share = split["share"]
    planned_line = {**line, "metres": line["metres"] * share, "key": line["key"]}
    rest_line = {**line, "metres": line["metres"] * (1 - share)}
    plan, rest = [], []
    for f in facts:
        a, b = portfolio.split_fact(f, split["planned_pieces"], line["pieces"])
        if a is not None:
            plan.append((a, planned_line))
        if b is not None:
            rest.append((b, rest_line))
    return plan, rest


def _metres_unknown(line) -> bool:
    """Sem saldo ou sem comprimento (08/10): os metros não se sabem e contam à parte, nunca como 0."""
    return bool(line.get("metres_unknown", line["balance_unknown"]))


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


def context(sector: str, *, data=None, decisions=None, occurrences_data=None, resources_catalog=None,
            allow_stale: bool = False) -> dict:
    """Everything the KPIs read, loaded once; tests pass synthetic parts.

    `allow_stale` (consultas): as linhas podem ser as da geração anterior enquanto a nova se calcula; as
    decisões são sempre as atuais e as ocorrências já aceitavam a versão anterior.
    """
    from . import selection
    portfolio.check_sector(sector)
    data = data or portfolio.current(sector, allow_stale=allow_stale)
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


# Resumo da semana: as horas de cada estado vêm do tipo da célula da Carga com o mesmo significado.
WEEK_KIND = {"planeado": "plan", "nesting": "due", "sem_maquina": "suggested"}


def week_label(codes: list[str], today: date) -> str:
    """«Semana 41 (05/10–11/10)», «Semanas 41 e 42 (05/10–18/10)», «Sem semana definida»… (códigos do filtro Prazo)."""
    weeks = [(int(c[:4]), int(c[6:])) for c in codes if c not in (portfolio.NO_WEEK, portfolio.PARKED_WEEK)]
    parts = []
    if weeks:
        year = today.isocalendar()[0]
        mondays = [date.fromisocalendar(y, w, 1) for y, w in weeks]
        names = [str(w) if y == year else f"{w} de {y}" for y, w in weeks]
        text = f"Semana {names[0]}" if len(names) == 1 else "Semanas " + ", ".join(names[:-1]) + " e " + names[-1]
        if all((b - a).days == 7 for a, b in zip(mondays, mondays[1:])):  # semanas seguidas: o intervalo de datas
            text += f" ({mondays[0]:%d/%m}–{mondays[-1] + timedelta(days=6):%d/%m})"
        parts.append(text)
    if portfolio.NO_WEEK in codes:
        parts.append("Sem semana definida")
    if portfolio.PARKED_WEEK in codes:
        parts.append(portfolio.WINDOWS["estacionada"])
    return " + ".join(parts)


def _week_slice(sector: str, codes: list[str], today: date | None) -> dict:
    from . import load
    return load.week_slice(sector, codes, today=today)


def overview(sector: str, weeks: list[str] | None = None, *, today: date | None = None, **kw) -> dict:
    """Carga por máquina e resumo por estado. Só o filtro Prazo (`weeks`, códigos do filtro) muda os números.

    Sem semanas: B (a carga do que está Planeado), como antes. Com semanas: cada máquina leva `week`, as horas e a
    capacidade dessas semanas lidas das células da Carga (load.week_slice), e o Resumo leva `week` (metros e
    toneladas das linhas dessas semanas; horas pela semana da operação principal). `scope` diz o âmbito.
    """
    from . import load
    codes = load.week_codes(weeks or [])
    ctx = context(sector, **kw)
    data, decisions = ctx["data"], ctx["decisions"]
    sliced = _week_slice(sector, codes, today) if codes else None
    machines = _machines(ctx)
    base = defaultdict(_empty)
    summary = {code: {**_empty(), "pieces": 0.0, "ofs": set(), "kg": 0.0, "kg_unknown": 0} for code in planning_status.STATUS}
    in_week = {code: {"metres": 0.0, "metres_unknown": 0, "kg": 0.0, "kg_unknown": 0, "lines": 0} for code in planning_status.STATUS}
    for line in data["lines"]:
        split = portfolio.plan_split(line, decisions)
        status = split["status"]
        facts = ctx["facts"].get(line["key"], [])
        plan, rest = _parts(facts, line, split)
        for f in facts:
            b = bucket(f, ctx["names"])
            if b and b not in machines:
                machines[b] = {"id": b, "name": b.removeprefix("nome:"), "code": None, "process": None, "unit": None,
                               "type": None, "in_catalog": False}
        for f, part_line in plan:  # B: só a parte planeada (a linha inteira quando não é parcial)
            b = bucket(f, ctx["names"])
            if b:
                _add(base[b], f, part_line, sector)
        code = next((c for c, value in status.items() if value), None)
        if code is None:  # linha excluída: fora do Resumo (planning_status, A8-5)
            continue
        shares = ((code, 1.0, plan or rest),) if not split["partial"] else (("planeado", split["share"], plan),
                                                                              ("nesting", 1 - split["share"], rest))
        for part_code, share, pairs in shares:
            s = summary[part_code]
            s["pieces"] += (line["pieces"] or 0) * share
            s["ofs"].add(line["of"])
            if line.get("kg") is None:
                s["kg_unknown"] += part_code == code  # sem peso unitário: não conta como zero (uma vez por linha)
            else:
                s["kg"] += line["kg"] * share
            for f, part_line in pairs:
                _add(s, f, part_line, sector)
            if part_code != code:
                s["lines"].discard(line["key"])  # a linha parcial conta uma vez, em Planeado
            if codes and portfolio.matches(line, {"semanas": codes}):  # a semana da linha = a da operação principal
                w = in_week[part_code]
                w["lines"] += part_code == code
                if _metres_unknown(line):
                    w["metres_unknown"] += part_code == code
                else:
                    w["metres"] += line["metres"] * share
                if line.get("kg") is None:
                    w["kg_unknown"] += part_code == code
                else:
                    w["kg"] += line["kg"] * share
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
        row = {**{k: m[k] for k in ("id", "name", "code", "process", "in_catalog")},
               "base": _out(base[rid]) if rid in base else _out(_empty())}
        if sliced is not None:  # sem célula na Carga (máquina fora das Definições do setor): sem números da semana
            found = sliced["machines"].get(rid)
            row["week"] = {k: found[k] for k in WEEK_FIELDS} if found else None
        panels[panel]["machines"].append(row)
    for p in panels.values():
        p["machines"].sort(key=lambda m: m["name"])
    rows = []
    for code, label in planning_status.STATUS.items():
        row = {"code": code, "label": label, "origin": planning_status.ORIGINS[code],
               **_out(summary[code]), "pieces": round(summary[code]["pieces"]), "ofs": len(summary[code]["ofs"]),
               "tonnes": round(summary[code]["kg"] / 1000, 2), "weight_unknown": summary[code]["kg_unknown"]}
        if sliced is not None:
            w, kind = in_week[code], sliced["kinds"][WEEK_KIND[code]]
            row["week"] = {"lines": w["lines"], "metres": round(w["metres"], 1), "metres_unknown": w["metres_unknown"],
                           "tonnes": round(w["kg"] / 1000, 2), "weight_unknown": w["kg_unknown"],
                           "hours": kind["hours"], "hours_unknown": kind["unknown"], "hours_kind": WEEK_KIND[code]}
        rows.append(row)
    out = {
        "sector": sector, "sector_label": portfolio.SECTORS[sector], "version": version(ctx),
        "generation": data["generation"], "imported_at": data["imported_at"],
        "stale": bool(ctx["occ"].get("stale") or data.get("stale") or (sliced or {}).get("stale")),
        "panels": list(panels.values()), "other_machines": sorted(others, key=lambda m: m["name"]),
        "summary": rows,
        # Âmbito dos números (P4, 08/10): sem semanas, a carga do que está Planeado; com semanas, a Carga dessas semanas.
        "scope": {"weeks": codes, "label": week_label(codes, sliced["today"]) if sliced else "todas as semanas",
                  "sector_label": portfolio.SECTORS[sector], "current": bool(sliced and sliced["current"])},
        "rules": __doc__.split("\n\n", 1)[1].strip(),
    }
    if sliced is not None:
        out["week_totals"] = sliced["totals"]
    return out


WEEK_FIELDS = ("load", "capacity", "plan", "due", "suggested", "unknown", "metres", "metres_unknown", "status", "late_before")


def preview(payload: dict, **kw) -> dict:
    """Acréscimo dos membros marcados (S) por máquina. Só consulta: nada é gravado.

    Só as linhas em «Planeado para nesting» acrescentam (na sua máquina). As já planeadas acrescentam
    zero; as sem máquina contam à parte, uma vez por linha (ao Planear recebem a máquina sugerida).
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
            if _metres_unknown(line):
                no_machine["metres_unknown"] += 1
            else:
                no_machine["metres"] += line["metres"]
            continue
        split = portfolio.plan_split(line, decisions)
        status = split["status"]
        if status["nesting"]:
            to_plan["lines"] += 1
            if line.get("kg") is None:
                to_plan["kg_unknown"] += 1
            else:
                to_plan["kg"] += line["kg"]
        plan, rest = _parts(ctx["facts"].get(key, []), line, split)
        for pairs, planned in ((plan, True), (rest, False)):
            for f, part_line in pairs:
                b = bucket(f, ctx["names"])
                if b:  # uma operação seguinte ainda sem máquina não tem destino: não acrescenta a nenhuma
                    _add(already if planned else delta[b], f, part_line, sector)
    return {
        "sector": sector, "version": version(ctx), "stale": bool(ctx["occ"].get("stale") or data.get("stale")),
        "members": len(dict.fromkeys(keys)) - len(unknown), "unknown_keys": unknown[:50], "unknown_count": len(unknown),
        "delta": {b: {"name": (machines.get(b) or {}).get("name") or b.removeprefix("nome:"), **_out(v)} for b, v in delta.items()},
        "already_planned": _out(already),
        "no_machine": {**no_machine, "metres": round(no_machine["metres"], 1)},
        "to_plan": {"lines": to_plan["lines"], "tonnes": round(to_plan["kg"] / 1000, 2), "weight_unknown": to_plan["kg_unknown"]},
    }
