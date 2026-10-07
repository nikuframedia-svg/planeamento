"""Máquina sugerida e horas estimadas para a carteira (estudo de capacidade de 01/10/2026).

Nada aqui é uma decisão: são estimativas identificadas, que a vista mostra separadas das horas
documentais e das máquinas atribuídas.

Máquina sugerida (só para ocorrências sem máquina):
1. candidatas técnicas da ficha e do histórico (as mesmas do Gantt), sem as excluídas;
2. a máquina das outras linhas da mesma OF, operação e perfil (atribuídas ou já sugeridas), quando é
   candidata: o mesmo perfil partilha preparação. Na validação coincide com o planeador em 98% das
   linhas, com e sem precedente (contra 56% e 89% sem este critério; 80%/96% agrupando só por OF).
   Perfis diferentes da mesma OF podem ir para máquinas diferentes, o que permite equilibrar a carga;
3. o processo da regra das séries (ver `series_process`): punção para séries, broca para séries baixas,
   chapa grossa ou abas acima de 120 — é o que decide na prática, não o código 112/119;
4. precedente da mesma variante em 2 ou mais OF anteriores, depois 1 OF;
5. sem condições que dependam de terceiros (mercado nacional da Peddi 6, mudança 112 → 119);
6. menor carga em semanas de débito observado depois de somar esta ocorrência (equilíbrio);
7. menos horas na própria máquina; código do recurso como desempate estável.
As ocorrências são tratadas por urgência (atraso, prazo), para que o trabalho mais urgente escolha
primeiro. Uma sugestão nunca tira trabalho a uma máquina atribuída.

Horas (F01, 08/10): as documentais do motor de capacidade só valem na máquina para que foram calculadas; noutra
máquina (escolhida na Carteira, sugerida, alternativa) estima-se com a regra única (Confirmada > Excel):
- primeiro a taxa confirmada da tabela de velocidades das Definições (`productivity.match_rate`), em qualquer
  operação;
- depois a velocidade do Excel que o motor de capacidade publicou para essa máquina e operação
  (`published_rates`): a mesma da Carga e do Gantt;
- sem ela, a linha da tabela com origem Excel e, na operação principal, a velocidade **mais recente** do Excel
  (`Mt\\h`) da máquina (MTG3) ou a taxa mm²/h da `CapacidadeMáquinas`, colunas E/F (MTG2);
- o ×3 da Thomas (QTD > 50) aplica-se uma vez às taxas do Excel (`productivity.thomas_factor`);
- operações seguintes sem linha na tabela: continuam desconhecidas;
- no fim, peças × tempo por peça (arranque da linha + tempo fixo do setor) e a eficiência da máquina.
"""
from __future__ import annotations

from collections import defaultdict
import re

from . import throughput

PENALISED = {"confirmar_cliente_nacional", "mudanca_112_para_119_requer_decisao"}
MIN_PROFILE_LINES = 3


def _profile(value) -> str:
    return re.sub(r"\s", "", str(value or "").upper())


def speed_for(study, names, profile):
    """Excel speed for one machine (any of its names) and profile, with the basis used.

    Plano de 06/10 (parte 3): a velocidade do Excel em vigor é a **mais recente** da máquina (moda das linhas
    com Data Corte nas últimas semanas com dados, `productivity.recent_excel_speeds`), a mesma do motor de
    capacidade e do Gantt. Não depende do perfil (medido a 06/10: a `Mt\\h` é constante por máquina), por isso
    restos da transição num perfil (ex.: 6 linhas a 100 m/h numa máquina a 120) não contam. A mediana de todo o
    histórico fica apenas como último recurso (estudos antigos sem a medida recente).
    """
    recent = study.get("recent_speeds") or {}
    recent_profiles = study.get("recent_profile_speeds") or {}
    best = None
    for name in sorted(n for n in names if n):
        found = recent.get(name)
        if found and found.get("value"):
            return found["value"], found["lines"], f"velocidade mais recente do Excel de {name} ({found['lines']} linhas desde {found.get('from', '?')})"
    if recent or recent_profiles:
        return None  # a máquina não tem linhas com Data Corte: não se usa a mediana antiga de outra época
    for name in names:
        found = study["profile_speeds"].get((name, _profile(profile)))
        if found and found["lines"] >= MIN_PROFILE_LINES and (not best or found["lines"] > best[1]):
            best = (found["value"], found["lines"], f"mediana Excel de {name} para {_profile(profile)} ({found['lines']} linhas)")
    if best:
        return best
    for name in names:
        found = study["speeds"].get(name)
        if found and found["value"]:
            return found["value"], found["lines"], f"mediana Excel de {name} ({found['lines']} linhas, todos os perfis)"
    return None


def weekly_capacity(study, names):
    """Median and quartiles of executed theoretical hours per week (MTG3 Excel)."""
    for name in names:
        found = study["summary"].get(name)
        if found and found["hours_median"]:
            return found
    return None


def calendar_capacity(c, resource_ids, today=None, weeks: int = 13) -> dict:
    """{resource_id: {"hours_median", "basis"}} com as horas dos calendários do setor nas próximas semanas.

    Auditoria 06/10 (PROP-7): a MTG2 não tem débito observado no Excel; sem isto o critério de equilíbrio
    (6) nunca atuava nos perfis. Semanas sem calendário não entram na mediana.
    """
    from datetime import date, timedelta
    from statistics import median
    from . import shifts
    ids = [str(r) for r in resource_ids if r]
    if not ids:
        return {}
    today = today or date.today()
    monday = today - timedelta(days=today.weekday())
    horizon = {(monday + timedelta(weeks=i)).isocalendar()[:2] for i in range(weeks)}
    hours = defaultdict(list)
    for r in c.execute("SELECT definition FROM planning_mtg.raw_objects WHERE kind='calendar' AND NOT archived "
                       "AND definition->>'resource_id' = ANY(%s)", (ids,)).fetchall():
        d = r["definition"]
        if (int(d["year"]), int(d["week"])) in horizon:
            hours[str(d["resource_id"])].append(shifts.week_hours(d))
    return {rid: {"hours_median": median(v), "basis": "calendário"} for rid, v in hours.items() if v and median(v) > 0}


def documentary_on(fact, rid) -> bool:
    """As horas documentais da ocorrência valem nesta máquina? (F01, 08/10)

    Só na máquina para que o motor de capacidade as calculou (`documentary_resource_id`); sem máquina (rid
    vazio) valem as que houver. Nunca passam para outra máquina.
    """
    if fact["hours"] is None:
        return False
    return not rid or rid == fact.get("documentary_resource_id", fact.get("resource_id"))


def hours_on(fact, rid, *, by_id, names, study, rates, table=None, timing=None, detail=None, published=None):
    """(horas, base, origem) de uma ocorrência numa máquina: a regra única da Carteira, da Carga e da previsão.

    Horas documentais do saldo só na máquina para que foram calculadas (`documentary_on`); noutra máquina a
    estimativa (`estimate`) dessa máquina: taxa confirmada da tabela de velocidades (`table`), senão a velocidade
    do Excel publicada pelo motor (`published`, de `published_rates`), com o tempo fixo do setor e a eficiência
    da máquina (`timing`).
    """
    if documentary_on(fact, rid):
        return fact["hours"], "documental", fact["hours_origin"]
    if not rid:
        return None, None, None
    if not study and not table and not published:
        return None, None, None
    hours, why = estimate(fact, by_id.get(rid), names.get(rid, set()), study, rates, table=table, timing=timing, detail=detail,
                          published=published)
    return (hours, "estimada", why) if hours is not None else (None, None, why)


def _hours(fact, rate, source, timing, detail=None, origin=None, resource_id=None):
    """Horas pela conta única do motor (capacity.estimate): volume ÷ velocidade + peças × tempo por peça, × 100 /
    eficiência da máquina (`resource_id`).

    `detail` (opcional) recebe a conta usada, para o «Ver cálculo» da Carga dizer a verdade (origem da taxa,
    velocidade usada, tempo por peça e o fator da eficiência escrito como margem).
    """
    from ..raw.capacity import estimate as engine
    from ..raw.productivity import timed
    values = {"quantity_to_plan": fact["remaining"], "length_mm": fact.get("length_mm"), "section_unit": fact.get("section_unit")}
    effective = timed(rate, source, timing, resource_id)
    hours, reason = engine(values, effective, fact.get("operation"))
    if detail is not None and hours is not None:
        detail.clear()
        detail.update(origin=origin, method=rate.get("method"), rate=rate.get("value"),
                      rate_piece_seconds=effective.get("rate_piece_seconds", effective.get("piece_seconds") or 0) or 0,
                      fixed_piece_seconds=effective.get("fixed_piece_seconds") or 0,
                      piece_seconds=effective.get("piece_seconds") or 0, margin_pct=effective.get("margin_pct") or 0)
        if effective.get("efficiency_pct"):
            detail["efficiency_pct"] = effective["efficiency_pct"]
    return hours, reason


def _operation(fact) -> str:
    """Nome da operação no motor de capacidade: 'corte' na principal dos perfis, '112'/'119', 'abocardar'."""
    from .occurrences import _estimate_name
    return _estimate_name(fact.get("operation"), fact["area"], fact["phase"] == "principal")


def machine_names(resource, names=()) -> set:
    """Nomes de uma máquina: os dados, o do catálogo e os aliases (todos os setores)."""
    found = {n for n in names or () if n}
    if resource:
        found.add(resource.get("name"))
        found.update(a.get("name") for a in resource.get("aliases") or [] if a.get("name"))
    found.discard(None)
    return found


def _positive(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 and number != float("inf") else None


def published_rates(records, resolve=None, *, excel_area=None) -> dict:
    """Velocidade do Excel publicada pelo motor de capacidade por (máquina, operação) (F01, 08/10).

    `records`: linhas da geração (values_json e detail.calculation.operation_estimates, como em
    occurrences._records); `resolve(área, nome)` dá o ID do recurso de um nome de máquina. Só as estimativas
    «Excel provisório»: guarda a taxa base, sem o ×3 da Thomas (valor ÷ fator), para o fator se aplicar uma só vez
    na ocorrência (`productivity.thomas_factor`). Um par com taxas base diferentes (ex.: intervalos da tabela) fica
    de fora: aí vale a linha da tabela de cada ocorrência. `excel_area` ({nome: taxa} de
    productivity.current_excel_area) junta a taxa mm²/h E/F de cada serrote do Excel dos perfis em uso, para as
    máquinas sem linhas publicadas.

    Devolve {"rates": {"rid|operação": {origin, method, value, unit, lines}}, "area": {rid: {value, cell, machine}}}.
    """
    found = defaultdict(lambda: defaultdict(int))
    units = {}
    for record in records or ():
        area = record.get("area")
        for e in (((record.get("detail") or {}).get("calculation") or {}).get("operation_estimates")) or []:
            rate = e.get("rate") or {}
            value = _positive(rate.get("value"))
            if e.get("source") != "Excel provisório" or value is None or not e.get("machine") or not resolve:
                continue
            rid = resolve(area, e["machine"])
            if not rid:
                continue
            key = f"{rid}|{e.get('operation')}"
            found[key][(rate.get("method"), round(value / (_positive(e.get("factor")) or 1), 6))] += 1
            units[key] = rate.get("unit")
    rates = {}
    for key, values in found.items():
        if len(values) != 1:
            continue  # taxas base diferentes na mesma máquina e operação: nenhuma é «a» taxa publicada
        (method, value), lines = next(iter(values.items()))
        rates[key] = {"origin": "Excel provisório", "method": method, "value": value, "unit": units.get(key), "lines": lines}
    area = {}
    for name, entry in sorted((excel_area or {}).items()):
        rid = resolve("perfis", name) if resolve else None
        if rid and _positive(entry.get("value")) and rid not in area:
            area[rid] = {"value": float(entry["value"]), "cell": entry.get("cell"), "machine": name}
    return {"rates": rates, "area": area}


def table_rate(fact, resource, table, *, tier):
    """Linha da tabela de velocidades que vale para esta ocorrência nesta máquina (productivity.match_rate)."""
    if not table or not resource or not resource.get("id"):
        return None
    from ..raw.productivity import match_rate, operation_names
    values = {"profile": fact.get("profile"), "designation": fact.get("designation"), "section_unit": fact.get("section_unit"),
              "material_type": None if fact.get("material_type") in (None, "Sem tipo") else fact.get("material_type")}
    return match_rate(table, resource["id"], fact["area"], operation_names(fact.get("operation"), fact["phase"] == "principal", fact["area"]), values,
                      tier=tier)


UNITS = {"metres_hour": "m/h", "area_hour": "mm²/h"}


def estimate(fact, resource, names, study, area_rates, *, table=None, timing=None, detail=None, published=None):
    """Hours for one occurrence on one machine, or (None, reason).

    Ordem (a mesma do motor e do Gantt, sem o histórico; 08/10): taxa confirmada da tabela de velocidades;
    velocidade do Excel publicada pelo motor para esta máquina e operação (`published`); linha da tabela com
    origem Excel; velocidade mais recente do Excel (cantoneiras) ou taxa mm²/h E/F da CapacidadeMáquinas (perfis;
    `area_rates` antigas só sem ela). O ×3 da Thomas aplica-se uma vez às taxas do Excel; o tempo fixo por peça do
    setor e a eficiência da máquina no fim.
    """
    from ..raw.productivity import thomas_factor
    remaining = fact["remaining"]
    if remaining is None:
        return None, "Saldo por confirmar."
    rid = (resource or {}).get("id")

    def result(rate, source, origin, label, basis=None):
        hours, reason = _hours(fact, rate, source, timing, detail, origin, resource_id=rid)
        if hours is None:
            return None, reason
        unit = UNITS.get(rate.get("method"), rate.get("method"))
        thomas = " (× 3 da Thomas, QTD > 50)" if factor > 1 and source != "Manual" else ""
        return hours, f"Estimativa: {label}, {rate['value']:g} {unit}{thomas}" + (f" ({basis})" if basis else "")

    factor = 1
    found = table_rate(fact, resource, table, tier="Confirmada")
    if found and found.get("conflict"):
        return None, "Taxas da tabela de velocidades em conflito."
    if found:
        return result(found["rate"], "Manual", "taxa confirmada da tabela de velocidades",
                      f"taxa confirmada de {resource['name']}", found["basis"])
    operation = _operation(fact)
    factor = thomas_factor(fact["area"], operation, machine_names(resource, names), fact.get("quantity_required"))
    entry = ((published or {}).get("rates") or {}).get(f"{rid}|{operation}") if rid else None
    if entry:
        rate = {"method": entry["method"], "value": entry["value"] * factor}
        return result(rate, "Excel provisório", "velocidade do Excel (a do motor de capacidade)",
                      f"velocidade do Excel de {resource['name']}")
    found = table_rate(fact, resource, table, tier="Excel")
    if found and found.get("conflict"):
        return None, "Taxas da tabela de velocidades em conflito."
    if found:
        rate = {**found["rate"], "value": found["rate"]["value"] * factor}
        return result(rate, "Excel provisório", "velocidade da tabela de velocidades (origem Excel)",
                      f"tabela de velocidades (origem Excel) de {resource['name']}", found["basis"])
    if fact["phase"] != "principal":
        return None, "Operação seguinte sem taxa conhecida."
    if fact["area"] == "cantoneiras":
        length = fact.get("length_mm")
        if not length:
            return None, "Comprimento desconhecido."
        found = speed_for(study or {"speeds": {}, "profile_speeds": {}}, names, fact["profile"])
        if not found:
            return None, "Velocidade da máquina desconhecida no Excel."
        value, _, basis = found
        return result({"method": "metres_hour", "value": value * factor}, "Excel provisório", "velocidade mais recente do Excel", basis)
    section = fact.get("section_unit")
    sheet = ((published or {}).get("area") or {}).get(rid) if rid else None
    value = sheet["value"] if sheet else (area_rates or {}).get(resource.get("code")) if resource else None
    if not section:
        return None, "Área de corte unitária por confirmar."
    if not value:
        return None, "Taxa mm²/h da máquina desconhecida no Excel."
    where = f"CapacidadeMáquinas!{sheet['cell']}" if sheet and sheet.get("cell") else "CapacidadeMáquinas"
    return result({"method": "area_hour", "value": value * factor}, "Excel provisório",
                  f"taxa mm²/h da folha {where} do Excel", f"taxa Excel de {resource['name']} ({where})")


SERIES_PIECES = 8      # «factor de selecção maq» of the workbook (Analise maq!Q1), confirmed by the data
DRILL_THICKNESS = 9.5  # mm; thicker angles were drilled in 94–100% of the executed lines
PUNCH_MAX_LEG = 120    # mm; the punching machines' sheet limit


def series_process(mean_quantity, profile):
    """Observed process rule for an OF × operation × profile group (MTG3 angles).

    Average pieces per line ≥ 8, thickness ≤ 9.5 mm and leg ≤ 120 mm → punching; otherwise drilling.
    On 7 858 executed groups of 2026 it matches the process used for 88–89% of the metres (validated
    by OF), against 47% for the 112/119 code. Unknown quantity or geometry → no preference.
    """
    from ..gantt.machines import dimensions
    found = dimensions(profile)
    if mean_quantity is None or not found:
        return None
    leg, thickness = max(found[0], found[1]), found[2]
    return "Punção" if mean_quantity >= SERIES_PIECES and thickness <= DRILL_THICKNESS and leg <= PUNCH_MAX_LEG else "Broca"


def group_processes(facts):
    """Preferred process per set-up group, from the mean quantity per line of its principal lines."""
    quantities = defaultdict(list)
    for f in facts:
        if f["area"] == "cantoneiras" and f["phase"] == "principal" and f.get("quantity_required"):
            quantities[group_key(f)].append(f["quantity_required"])
    return {key: series_process(sum(q) / len(q), key[2]) for key, q in quantities.items()}


def score(option, *, peer=None, process=None, hours=None, weeks=None, learned=None):
    """Ordering of the candidate machines of one occurrence (lower is better).

    A preferência aprendida com as escolhas dos planeadores (machine_learning.py) vem primeiro.
    """
    history = option.get("other_orders") or 0
    return (bool(learned) and option.get("resource_id") != learned,
            option.get("resource_id") != peer if peer else True,
            bool(process) and option.get("process") not in (None, process),
            0 if history >= 2 else 1 if history == 1 else 2,
            bool(PENALISED.intersection(option.get("conditions", []))),
            weeks if weeks is not None else float("inf"), hours if hours is not None else float("inf"),
            option.get("resource_code") or "", option.get("proposed_code") or "")


def group_key(fact):
    """Lines that share a set-up: same OF, operation and profile."""
    return (fact["of"], fact["operation"], re.sub(r"\s", "", str(fact.get("profile") or "").upper()))


def peer_machine(peers, candidates):
    """Most used machine among the OF's other lines of the same operation, if it is a candidate."""
    usable = [(n, rid) for rid, n in peers.items() if n > 0 and rid in candidates]
    return max(usable)[1] if usable else None


def area_rates(metadata):
    """Unique mm²/h rate per resource code from the workbook capacity sheet (conflicts → none)."""
    found = defaultdict(set)
    for r in metadata.get("rates", []):
        if r.get("unidade") in ("mm2/h", "mm²/h") and r.get("valor"):
            found[r["recurso_codigo"]].add(float(r["valor"]))
    return {code: next(iter(v)) for code, v in found.items() if len(v) == 1}


def apply(facts, rows, *, codes, by_id, package, study, learned=None, calendar=None, table=None, timing=None, published=None,
          excluded=None):
    """Add suggested machine, planning machine and load hours to every occurrence (in place).

    `calendar` ({resource_id: {"hours_median"}}, de `calendar_capacity`) é a capacidade semanal das máquinas
    sem débito observado no Excel (MTG2). `published` (de `published_rates`): velocidades do Excel do motor por
    máquina e operação. `excluded`: chaves das ocorrências de linhas excluídas na Carteira (F25, 08/10); recebem
    horas e sugestão como as outras, mas não contam na carga do equilíbrio nem como «outras linhas da OF».
    """
    from ..gantt import machines
    names = throughput.aliases_to_names(by_id)
    rates = area_rates(package["metadata"]) if package else {}
    index = machines.EvidenceIndex(package["metadata"], package["rows"] + [r for r in rows.values() if r.get("application_row_key")]) if package else None
    capacity = {rid: weekly_capacity(study, names[rid]) for rid in by_id} if study else {}
    for rid, found in (calendar or {}).items():
        if not capacity.get(rid):
            capacity[rid] = found
    load = defaultdict(float)
    processes = group_processes(facts)
    peers = defaultdict(lambda: defaultdict(int))  # (OF, operation, profile) → machine → lines
    excluded = excluded or set()

    def own_hours(fact, rid, detail=None):
        return hours_on(fact, rid, by_id=by_id, names=names, study=study, rates=rates, table=table, timing=timing, detail=detail,
                        published=published)

    for fact in facts:
        rid = fact["assigned_resource_id"]
        detail = {}
        hours, basis, why = own_hours(fact, rid, detail)
        fact.update(planning_resource_id=rid, planning_machine=fact["assigned_machine"] if rid else "Sem máquina",
                    machine_basis="atribuída" if rid else None, suggestion=None,
                    load_hours=hours, load_basis=basis, load_origin=why,
                    load_estimate=detail if basis == "estimada" and detail else None)
        if fact["key"] in excluded:
            continue  # trabalho fora do plano: não pesa nas sugestões das outras linhas
        if rid and hours:
            load[rid] += hours
        if rid:
            peers[group_key(fact)][rid] += 1
    pending = sorted((f for f in facts if not f["assigned_resource_id"]),
                     key=lambda f: (-f["late_days"], f["priority_day"] or "9999", f["of"], f["reference"], f["occurrence"]))
    for fact in pending:
        row = rows.get(fact["key"])
        if not index or not row:
            continue
        candidates = [c for c in index.candidates(row, codes) if c.get("resource_id") and c["eligibility"] != "excluded"]
        peer = peer_machine(peers[group_key(fact)], {c["resource_id"] for c in candidates})
        from .machine_learning import suggest
        preference = suggest(learned, fact.get("sku_family"), fact.get("profile")) if learned else None
        if preference and preference["resource_id"] not in {c["resource_id"] for c in candidates}:
            preference = None
        # A preferência já filtrada pela ficha técnica: a mesma que a Carteira pré-escolhe (auditoria 06/10, PROP-2).
        fact["learned_preference"] = preference
        options = []
        for c in candidates:
            rid = c["resource_id"]
            detail = {}
            hours, _, why = own_hours(fact, rid, detail)
            cap = (capacity.get(rid) or {}).get("hours_median")
            weeks = (load[rid] + (hours or 0)) / cap if cap else None
            options.append((score(c, peer=peer, process=processes.get(group_key(fact)), hours=hours, weeks=weeks,
                                  learned=(preference or {}).get("resource_id")), c, hours, why, weeks, detail))
        if not options:
            fact["load_origin"] = fact["load_origin"] or "Sem máquina candidata na ficha nem no histórico."
            continue
        _, chosen, hours, why, weeks, detail = min(options, key=lambda o: o[0])
        rid = chosen["resource_id"]
        counted = fact["key"] not in excluded
        if counted:
            peers[group_key(fact)][rid] += 1
        process = processes.get(group_key(fact))
        reason = (f"Preferência aprendida: {preference['label']}; " if preference and rid == preference["resource_id"] else "") + \
                 ("Mesma máquina das outras linhas da OF com este perfil e operação; " if rid == peer else "") + \
                 (f"{process.lower()} pela regra das séries ({'≥' if process == 'Punção' else '<'} {SERIES_PIECES} peças/linha ou geometria); " if process and chosen.get("process") == process else "") + \
                 (f"precedente em {chosen['other_orders']} OF" if chosen.get("other_orders") else "sem precedente da peça") + \
                 (f"; carga prevista {weeks:.1f} semanas de {'calendário' if (capacity.get(rid) or {}).get('basis') == 'calendário' else 'débito observado'}"
                  if weeks is not None else "; débito da máquina desconhecido") + \
                 (f"; {len(options)} candidatas" if len(options) > 1 else "; única candidata")
        fact.update(planning_resource_id=rid, planning_machine=by_id[rid]["name"], machine_basis="sugerida",
                    suggestion={"resource_id": rid, "machine": by_id[rid]["name"], "proposed_code": chosen["proposed_code"],
                                "eligibility": chosen["eligibility"], "conditions": chosen["conditions"], "reason": reason,
                                "alternatives": len(options), "history_orders": chosen.get("other_orders") or 0,
                                "with_of_peers": rid == peer, "process": chosen.get("process"), "preferred_process": process,
                                "learned": preference if preference and rid == preference["resource_id"] else None})
        # Horas da máquina sugerida pela mesma regra (F01, 08/10): as documentais só se forem dessa máquina; sem
        # taxa nela, ficam as documentais que houver (calculadas sem máquina).
        if hours is not None or fact["hours"] is None:
            basis = "documental" if documentary_on(fact, rid) else "estimada" if hours is not None else None
            fact.update(load_hours=hours, load_basis=basis, load_origin=why,
                        load_estimate=detail if basis == "estimada" and detail else None)
        if hours and counted:
            load[rid] += hours
    return {"loads": dict(load), "capacity": {rid: c for rid, c in capacity.items() if c}}
