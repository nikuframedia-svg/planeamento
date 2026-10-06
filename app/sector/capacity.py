"""Capacidade por setor e família, abaixo do Gantt (plano de 01/10/2026, secções 8, 10 e 11).

Para a máquina física m e o período w:
    C(m,w)   horas do calendário confirmado no período (ou orçamento semanal confirmado)
    H(o,m,w) interseção dos segmentos de ocupação da ocorrência o com o período w
    Ocupação(u,w)             = 100 × H_alocado(u,w) / C(u,w)
    Família na capacidade     = 100 × H(u,f,w) / C(u,w)
    Família na carga          = 100 × H(u,f,w) / H_alocado(u,w)
    Pressão das necessidades  = 100 × H_necessário_conhecido(u,w) / C(u,w)

- A capacidade é o denominador antes da alocação; nunca se divide por uma «capacidade livre».
- Equipamento, posto e operador não somam capacidade: um posto composto por máquinas não conta além
  delas; operadores são horas-pessoa num painel próprio; filas funcionais e destinos não entram.
- Um recurso usado pelos dois setores só divide capacidade com quotas configuradas (soma ≤ 1);
  sem quotas fica numa faixa «Partilhada» e o total de cada setor é identificado como parcial.
- Sem calendário: «capacidade por confirmar», sem percentagem. Calendário fechado: capacidade zero e
  «sem capacidade» quando há procura. Totais usam soma de horas / soma de capacidade.
- Necessidade sem colocação é procura, não ocupação. Só planos aceites em vigor ocupam; uma ocorrência
  conta uma vez mesmo que apareça em dois cenários aceites.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import nullcontext
from datetime import date, datetime, time, timedelta, timezone
import uuid
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb

from .. import planning, planning_needs as needs
from . import tree

LISBON = ZoneInfo("Europe/Lisbon")
MACHINE_TYPES = {"maquina", "equipamento", "posto"}
NOT_CAPACITY = {"fila_funcional": "Fila funcional (trabalho manual; capacidade em horas-pessoa por confirmar)",
                "destino": "Destino de encaminhamento; a máquina concreta está por decidir"}
UNIT_LABELS = {"perfis": "MTG2 Perfis", "cantoneiras": "MTG3 Cantoneiras"}
MIN_DECLARED_WEEKS = 4
BACKLOG_DAYS = 14  # proposta configurável do plano; não é um prazo prometido de recuperação


def _instant(day: str) -> datetime:
    return datetime.combine(date.fromisoformat(day), time.min, LISBON).astimezone(timezone.utc)


def _overlap_hours(windows, start: datetime, end: datetime) -> float:
    total = 0.0
    for w in windows:
        low = max(datetime.fromisoformat(w["start"]).astimezone(timezone.utc), start)
        high = min(datetime.fromisoformat(w["end"]).astimezone(timezone.utc), end)
        if high > low:
            total += (high - low).total_seconds() / 3600
    return total


SCENARIOS = {
    "confirmada": "Só calendários e orçamentos confirmados",
    "mediana": "Confirmada; senão débito observado (mediana) ou disponibilidade declarada",
    "prudente": "Confirmada; senão débito observado (percentil 25) ou disponibilidade declarada",
}


def resource_capacity(resource: dict, budgets: list[dict], slots: list[dict], *, observed=None, declared=None,
                      scenario: str = "mediana") -> dict:
    """Capacity per period, best evidence first and always labelled.

    confirmed hourly calendar → confirmed weekly budget → observed executed throughput (MTG3 Excel,
    theoretical hours/week) → weekly availability declared in the workbook (MTG2, por validar) → unknown.
    Observed and declared values are estimates: they carry their own status, never «confirmada».
    """
    result = {}
    for slot in slots:
        start, end = _instant(slot["start"]), _instant(slot["end"])
        weeks_in_slot = (date.fromisoformat(slot["end"]) - date.fromisoformat(slot["start"])).days / 7
        if resource.get("windows"):
            result[slot["key"]] = {"hours": round(_overlap_hours(resource["windows"], start, end) * (resource.get("capacity") or 1), 4),
                                   "status": "confirmada", "source": "Calendário confirmado"}
            continue
        if resource.get("calendar_status") == "closed":
            result[slot["key"]] = {"hours": 0.0, "status": "fechada", "source": "Calendário confirmado sem janelas"}
            continue
        weeks = [b for b in budgets if b["resource_id"] == resource["id"]
                 and slot["start"] <= date.fromisocalendar(b["year"], b["week"], 1).isoformat() < slot["end"]
                 and b.get("hours") is not None]
        if weeks and slot["kind"] == "week":
            result[slot["key"]] = {"hours": sum(b["hours"] for b in weeks), "status": "confirmada", "source": "Orçamento semanal confirmado"}
        elif scenario != "confirmada" and observed and observed.get("hours_median"):
            weekly = observed["hours_p25"] if scenario == "prudente" else observed["hours_median"]
            result[slot["key"]] = {"hours": round(weekly * weeks_in_slot, 2), "status": "observada",
                                   "source": f"Débito executado {'P25' if scenario == 'prudente' else 'mediana'} de {observed['weeks']} semanas "
                                             f"({observed['hours_p25']}–{observed['hours_p75']} h teóricas/semana)"}
        elif scenario != "confirmada" and declared and declared.get("hours"):
            weekly = declared["p25"] if scenario == "prudente" and declared.get("p25") else declared["hours"]
            result[slot["key"]] = {"hours": round(weekly * weeks_in_slot, 2), "status": "declarada",
                                   "source": f"Disponibilidade declarada no Excel: {declared['label']} (por validar)"}
        else:
            result[slot["key"]] = {"hours": None, "status": "por_confirmar", "source": None}
    return result


def declared_availability(rows) -> dict:
    """Typical weekly availability declared in PlanDisponibilidadeSemanal, per resource.

    The median of every declared week (not the latest one: isolated weeks of one 8 h shift exist),
    with sample size and range. Weeks whose rows disagree stay out. Declared, not validated.
    """
    from . import throughput
    by = defaultdict(list)
    for r in rows:
        if r.get("status") == "imported" and r.get("hours"):
            by[r["resource_id"]].append((r["year"], r["week"], r["hours"]))
    result = {}
    for rid, weeks in by.items():
        if len(weeks) < MIN_DECLARED_WEEKS:
            continue  # one isolated week (e.g. a single 8 h shift) is not a typical availability
        hours = [h for _, _, h in weeks]
        first, last = min(weeks)[:2], max(weeks)[:2]
        result[rid] = {"hours": round(throughput.quantile(hours, .5), 2), "p25": round(throughput.quantile(hours, .25), 2), "weeks": len(weeks),
                       "min": min(hours), "max": max(hours),
                       "label": f"mediana de {len(weeks)} semanas declaradas W{first[1]}/{first[0]}–W{last[1]}/{last[0]}, {min(hours):g}–{max(hours):g} h"}
    return result


def physical(resources: dict, relations: list[dict]) -> dict:
    """Which resources contribute machine-hours (a post made of machines does not)."""
    composed = defaultdict(list)
    for rel in relations:
        if rel["relacao"] == "compoe":
            composed[rel["pai"]].append(rel["filho"])
    by_code = {r["code"]: r for r in resources.values()}
    roles = {}
    for rid, r in resources.items():
        if r["type"] == "grupo_operadores":
            roles[rid] = "operadores"
        elif r["type"] in NOT_CAPACITY:
            roles[rid] = r["type"]
        elif r["type"] == "posto" and composed.get(r["code"]):
            roles[rid] = "posto_composto"
        elif r["type"] in MACHINE_TYPES:
            roles[rid] = "maquina"
        else:
            roles[rid] = "outro"
    members = {by_code[p]["id"]: [by_code[c]["id"] for c in children if c in by_code]
               for p, children in composed.items() if p in by_code}
    return {"roles": roles, "members": members}


def quotas(c) -> list[dict]:
    if not c.execute("SELECT to_regclass('planning_mtg.sector_capacity_quotas') t").fetchone()["t"]:
        return []
    return needs.serial(c.execute("SELECT * FROM planning_mtg.sector_capacity_quotas ORDER BY resource_id,area,valid_from").fetchall())


def _share(quota_rows, rid, area, slot):
    found = [q for q in quota_rows if q["resource_id"] == rid and q["area"] == area
             and q["valid_from"] <= slot["start"] and (not q["valid_until"] or q["valid_until"] >= slot["start"])]
    return float(found[-1]["share"]) if found else None


def accepted_bars(c, areas) -> tuple[dict, list[dict]]:
    """Wall-clock segments of the accepted plans in force; each occurrence counted once."""
    rows = c.execute("SELECT id,name,definition FROM planning_mtg.raw_objects WHERE kind='gantt' AND NOT archived").fetchall()
    accepted = sorted((r for r in rows if (r["definition"].get("accepted") or {}).get("job_id")),
                      key=lambda r: r["definition"]["accepted"].get("accepted_at") or "", reverse=True)
    bars, used = {}, []
    for scenario in accepted:
        job = c.execute("SELECT input,result FROM planning_mtg.raw_jobs WHERE id=%s AND kind='gantt' AND status='done'",
                        (needs.uid(scenario["definition"]["accepted"]["job_id"]),)).fetchone()
        if not job or not (job["result"] or {}).get("proposal"):
            continue
        origin = datetime.fromisoformat(job["input"]["started_at"])
        resources = (job["input"].get("snapshot") or {}).get("resources") or {}
        count = 0
        for key, bar in job["result"]["proposal"].get("bars", {}).items():
            if key in bars:
                continue  # already committed by a more recent accepted plan
            bars[key] = {"resource_id": bar["resource_id"], "resource_name": (resources.get(bar["resource_id"]) or {}).get("name"),
                         "segments": [(origin + timedelta(minutes=a), origin + timedelta(minutes=b)) for a, b in bar["segments"]],
                         "scenario": scenario["name"]}
            count += 1
        used.append({"id": str(scenario["id"]), "name": scenario["name"], "accepted_at": scenario["definition"]["accepted"].get("accepted_at"), "bars": count})
    return bars, used


def proposal_bars(c, scenario_id) -> dict:
    obj = c.execute("SELECT id,revision FROM planning_mtg.raw_objects WHERE id=%s AND kind='gantt'", (needs.uid(scenario_id),)).fetchone()
    if not obj:
        raise planning.PlanningError("Cenário indisponível.", 404)
    job = c.execute("""SELECT input,result FROM planning_mtg.raw_jobs WHERE kind='gantt' AND object_id=%s AND status='done'
        ORDER BY created_at DESC LIMIT 1""", (obj["id"],)).fetchone()
    if not job or not (job["result"] or {}).get("proposal"):
        return {}
    origin = datetime.fromisoformat(job["input"]["started_at"])
    return {key: {"resource_id": bar["resource_id"], "segments": [(origin + timedelta(minutes=a), origin + timedelta(minutes=b)) for a, b in bar["segments"]]}
            for key, bar in job["result"]["proposal"].get("bars", {}).items()}


def _pct(part, whole):
    if part is None or whole is None:
        return None
    if whole == 0:
        return None
    return round(100 * part / whole, 1)


def _res(f):
    return f.get("planning_resource_id", f["assigned_resource_id"])


def _load(f):
    return f.get("load_hours", f["hours"])


def _estimated(f):
    return f.get("load_basis") == "estimada"


def _suggested(f):
    return f.get("machine_basis") == "sugerida"


def build(datasets: dict, resources: dict, relations: list[dict], budgets: list[dict], quota_rows: list[dict],
          bars: dict, *, today: date, horizon_weeks: int = 12, granularity: str = "auto", filters: dict | None = None,
          sets: dict | None = None, observed: dict | None = None, declared: dict | None = None,
          scenario: str = "mediana") -> dict:
    """Pure aggregation. `datasets`: area → facts; `bars`: key → wall-clock segments.

    Load = documentary hours, else estimated hours (counted apart); machine = assigned, else suggested
    (counted apart). Observed/declared capacity is a labelled scenario, never «confirmada».
    """
    if scenario not in SCENARIOS:
        raise planning.PlanningError("Cenário de capacidade inválido.")
    observed, declared = observed or {}, declared or {}
    slots = tree.periods(today, horizon_weeks, granularity)
    shape = physical(resources, relations)
    cell_for = lambda rid, r, s: resource_capacity(r, budgets, s, observed=observed.get(rid), declared=declared.get(rid), scenario=scenario)
    capacity = {rid: cell_for(rid, r, slots) for rid, r in resources.items()}
    facts = {f["key"]: f for area_facts in datasets.values() for f in area_facts}
    highlighted = {k for k, f in facts.items() if tree.matches(f, filters or {}, sets)} if filters else None
    users = defaultdict(set)
    for f in facts.values():
        if _res(f):
            users[_res(f)].add(f["area"])
    for key, bar in bars.items():
        area = (facts.get(key) or {}).get("area")
        if area:
            users[bar["resource_id"]].add(area)
    catalogue_area = {rid: r.get("area") for rid, r in resources.items()}

    def owner(rid, area_slot):
        area, slot = area_slot
        share = _share(quota_rows, rid, area, slot)
        if share is not None:
            return share, "quota"
        sectors = users.get(rid) or ({catalogue_area[rid]} if catalogue_area.get(rid) else set())
        if len(sectors) > 1:
            return None, "partilhada"
        return (1.0, "exclusiva") if sectors == {area} else (0.0, "outro_setor")

    allocated = defaultdict(float)
    for key, bar in bars.items():
        fact = facts.get(key)
        family = fact["sku_family"] if fact else "Fora da carteira atual"
        area = fact["area"] if fact else None
        for left, right in bar["segments"]:
            for slot in slots:
                low, high = max(left, _instant(slot["start"])), min(right, _instant(slot["end"]))
                if high > low:
                    allocated[(bar["resource_id"], slot["key"], area, family, key in (highlighted or ()))] += (high - low).total_seconds() / 3600

    def counted(cells):
        """Machines and composed posts without double counting: a post with its own capacity
        replaces its members; otherwise its members count and the post does not."""
        chosen = {rid for rid in resources if shape["roles"].get(rid) == "maquina"}
        for post, members in shape["members"].items():
            if cells[post]["hours"] is not None:
                chosen -= set(members)
                chosen.add(post)
        return chosen

    member_of = {m: post for post, members in shape["members"].items() for m in members}

    def unit_capacity(area, slot, cells=None):
        """Capacity of the sector's resources whose capacity is known, and which those are.

        Resources without any capacity evidence (posts, queues) are listed apart instead of making
        the whole sector unknown; the pressure is then computed only over the covered demand.
        """
        cells = cells if cells is not None else {rid: capacity[rid][slot["key"]] for rid in resources}
        total, machines_known, machines, partial, statuses = 0.0, 0, 0, False, set()
        known_ids, unknown_names = set(), []
        for rid in counted(cells):
            share, kind = owner(rid, (area, slot))
            if kind == "outro_setor":
                continue
            if kind == "partilhada":
                partial = True
                continue
            machines += 1
            cell = cells[rid]
            statuses.add(cell["status"])
            if cell["hours"] is None:
                unknown_names.append(resources[rid]["name"])
            else:
                machines_known += 1
                total += cell["hours"] * share
                known_ids.add(rid)
        hours = None if not machines_known else 0.0 if statuses == {"fechada"} else total
        basis = sorted(statuses - {"por_confirmar"})
        return {"hours": hours, "known_hours": round(total, 2), "machines": machines, "machines_known": machines_known,
                "partial": partial or bool(unknown_names), "basis": basis, "known_ids": known_ids,
                "without_capacity": sorted(unknown_names), "estimated": bool(set(basis) & {"observada", "declarada"})}

    def covered(rid, known_ids):
        if not rid:
            return False
        if rid in known_ids or member_of.get(rid) in known_ids:
            return True
        members = shape["members"].get(rid)
        return bool(members) and all(m in known_ids for m in members)

    def status_of(cap, unit_cap):
        if cap is None:
            return "por_confirmar"
        if cap == 0:
            return "sem_capacidade"
        return "estimada" if unit_cap["estimated"] else "confirmada"

    units = {}
    shared_lane = {}
    for area, area_facts in datasets.items():
        periods_out = []
        lanes = {}
        for slot in slots:
            unit_cap = unit_capacity(area, slot)
            cap = unit_cap["hours"]
            families_alloc = defaultdict(float)
            highlighted_alloc = 0.0
            for (rid, key, a, family, hit), hours in allocated.items():
                if key == slot["key"] and a == area:
                    families_alloc[family] += hours
                    highlighted_alloc += hours if hit else 0
            alloc = sum(families_alloc.values())
            need_by_family = defaultdict(float)
            unknown = {"no_machine": 0, "no_hours": 0, "unknown_balance": 0}
            estimated = suggested = highlighted_need = need_covered = 0.0
            for f in area_facts:
                if tree.bucket(f["priority_day"], today, slots) != slot["key"]:
                    continue
                load = _load(f)
                if load is None:
                    unknown["no_hours"] += 1
                else:
                    need_by_family[f["sku_family"]] += load
                    need_covered += load if covered(_res(f), unit_cap["known_ids"]) else 0
                    estimated += load if _estimated(f) else 0
                    suggested += load if _suggested(f) else 0
                    highlighted_need += load if highlighted and f["key"] in highlighted else 0
                unknown["no_machine"] += not _res(f)
                unknown["unknown_balance"] += not f["balance_known"]
            need = sum(need_by_family.values())
            families = sorted(set(families_alloc) | set(need_by_family))
            periods_out.append({
                "key": slot["key"], "label": slot["label"], "kind": slot["kind"],
                "capacity_hours": round(cap, 2) if cap is not None else None,
                "capacity_status": status_of(cap, unit_cap), "capacity_basis": unit_cap["basis"],
                "capacity_partial": unit_cap["partial"], "capacity_known_hours": unit_cap["known_hours"],
                "machines": unit_cap["machines"], "machines_known": unit_cap["machines_known"],
                "without_capacity": unit_cap["without_capacity"],
                "allocated_hours": round(alloc, 2), "need_hours": round(need, 2),
                "need_covered_hours": round(need_covered, 2), "need_uncovered_hours": round(need - need_covered, 2),
                "need_estimated_hours": round(estimated, 2), "need_suggested_hours": round(suggested, 2),
                "occupation_pct": _pct(alloc, cap), "pressure_pct": _pct(need_covered, cap),
                "no_capacity_with_demand": cap == 0 and (alloc > 0 or need > 0),
                "highlight": {"allocated_hours": round(highlighted_alloc, 2), "need_hours": round(highlighted_need, 2)} if highlighted is not None else None,
                "families": [{"family": fam, "allocated_hours": round(families_alloc.get(fam, 0), 2),
                              "need_hours": round(need_by_family.get(fam, 0), 2),
                              "pct_capacity": _pct(families_alloc.get(fam, 0), cap),
                              "pct_load": _pct(families_alloc.get(fam, 0), alloc) if alloc else None,
                              "pct_need_capacity": _pct(need_by_family.get(fam, 0), cap)} for fam in families],
                "pending": unknown,
            })
        late = [f for f in area_facts if f["late"]]
        for rid, r in resources.items():
            role = shape["roles"].get(rid)
            lane_facts = [f for f in area_facts if _res(f) == rid]
            lane_bars = [(k, v) for k, v in allocated.items() if k[0] == rid and k[2] == area]
            if not lane_facts and not lane_bars:
                continue
            cells = []
            for slot in slots:
                share, kind = owner(rid, (area, slot))
                cell = capacity[rid][slot["key"]]
                alloc = sum(h for (x, key, a, fam, hit), h in lane_bars if key == slot["key"])
                need = sum(_load(f) for f in lane_facts if _load(f) is not None and tree.bucket(f["priority_day"], today, slots) == slot["key"])
                own = cell["hours"] * share if cell["hours"] is not None and share is not None else None
                cells.append({"key": slot["key"], "capacity_hours": round(own, 2) if own is not None else None,
                              "resource_capacity_hours": cell["hours"], "capacity_status": cell["status"], "capacity_source": cell["source"],
                              "ownership": kind, "allocated_hours": round(alloc, 2), "need_hours": round(need, 2),
                              "occupation_pct": _pct(alloc, own), "pressure_pct": _pct(need, own)})
            families = defaultdict(lambda: {"need_hours": 0.0, "occurrences": 0, "unknown_hours": 0})
            for f in lane_facts:
                fam = families[f["sku_family"]]
                fam["occurrences"] += 1
                if _load(f) is None:
                    fam["unknown_hours"] += 1
                else:
                    fam["need_hours"] += _load(f)
            total_load = sum(_load(f) for f in lane_facts if _load(f) is not None)
            week = next((c for c, s in zip(cells, slots) if s["kind"] == "week" and c["capacity_hours"]), None)
            lane = {"resource_id": rid, "name": r["name"], "code": r.get("code"), "type": r["type"], "role": role,
                    "role_note": NOT_CAPACITY.get(r["type"]) or ("Posto composto: conta o posto quando tem capacidade própria, senão as máquinas que o compõem" if role == "posto_composto" else
                                                                 "Horas-pessoa: não somadas às horas-máquina" if role == "operadores" else None),
                    "members": shape["members"].get(rid, []), "shared": len(users.get(rid, ())) > 1,
                    "periods": cells,
                    "late_need_hours": round(sum(_load(f) for f in lane_facts if f["late"] and _load(f) is not None), 2),
                    "load_hours": round(total_load, 2),
                    "estimated_hours": round(sum(_load(f) for f in lane_facts if _estimated(f) and _load(f) is not None), 2),
                    "suggested_occurrences": sum(_suggested(f) for f in lane_facts),
                    "unknown_occurrences": sum(_load(f) is None for f in lane_facts),
                    "weekly_capacity_hours": week["capacity_hours"] if week else None,
                    "weekly_capacity_status": week["capacity_status"] if week else None,
                    "weeks_to_clear": round(total_load / week["capacity_hours"], 1) if week else None,
                    "families": sorted(({"family": k, **{x: round(y, 2) if isinstance(y, float) else y for x, y in v.items()}} for k, v in families.items()),
                                       key=lambda x: -x["need_hours"])}
            if lane["shared"] and not any(q["resource_id"] == rid for q in quota_rows):
                shared_lane[rid] = {**lane, "areas": sorted(users[rid])}
            lanes[rid] = lane
        no_machine = [f for f in area_facts if not _res(f)]
        units[area] = {
            "label": UNIT_LABELS[area], "periods": periods_out,
            "late": {"occurrences": len(late), "known_hours": round(sum(f["hours"] for f in late if f["hours"] is not None), 2),
                     "load_hours": round(sum(_load(f) for f in late if _load(f) is not None), 2),
                     "estimated_hours": round(sum(_load(f) for f in late if _estimated(f) and _load(f) is not None), 2),
                     "unknown_hours": sum(_load(f) is None for f in late)},
            "after_horizon_hours": round(sum(_load(f) for f in area_facts if _load(f) is not None and tree.bucket(f["priority_day"], today, slots) == tree.AFTER), 2),
            "no_date": {"occurrences": sum(not f["priority_day"] for f in area_facts),
                        "known_hours": round(sum(_load(f) for f in area_facts if not f["priority_day"] and _load(f) is not None), 2)},
            "pending_queue": {"no_machine": {"occurrences": len(no_machine), "known_hours": round(sum(_load(f) for f in no_machine if _load(f) is not None), 2)},
                              "no_hours": sum(_load(f) is None for f in area_facts),
                              "suggested": sum(_suggested(f) for f in area_facts),
                              "estimated": sum(_estimated(f) for f in area_facts),
                              "unknown_balance": sum(not f["balance_known"] for f in area_facts)},
            "resources": sorted(lanes.values(), key=lambda l: (l["role"] != "maquina", -(l["weeks_to_clear"] or 0), l["name"])),
        }
        # The 14-day window is exact (today → today + 14), not the overlapping ISO weeks.
        window = {"key": "janela", "start": today.isoformat(), "end": (today + timedelta(days=BACKLOG_DAYS)).isoformat(), "kind": "window"}
        window_cells = {rid: cell_for(rid, r, [window])["janela"] for rid, r in resources.items()}
        window_cap = unit_capacity(area, window, window_cells)
        units[area]["backlog"] = backlog(area_facts, window_cap, bars, today=today,
                                         is_covered=lambda f: covered(_res(f), window_cap["known_ids"]))
    return {"periods": slots, "units": units, "shared": list(shared_lane.values()), "today": today.isoformat(),
            "commitments": len(bars), "scenario": scenario, "scenarios": SCENARIOS,
            "rules": __doc__.split("\n\n", 1)[1].strip()}


def backlog(facts: list[dict], unit_cap: dict, bars: dict, *, today: date, window_days: int = None, is_covered=None) -> dict:
    """Late work by the sector milestone and a 14-day balance, with estimates and unknowns kept apart."""
    window_days = window_days or BACKLOG_DAYS
    end = today + timedelta(days=window_days)
    late = [f for f in facts if f["late"]]
    due = [f for f in facts if f["priority_day"] and today.isoformat() <= f["priority_day"] < end.isoformat()]
    ages = defaultdict(lambda: {"occurrences": 0, "known_hours": 0.0})
    for f in late:
        label = "1–7 dias" if f["late_days"] <= 7 else "8–30 dias" if f["late_days"] <= 30 else "31–90 dias" if f["late_days"] <= 90 else "mais de 90 dias"
        ages[label]["occurrences"] += 1
        ages[label]["known_hours"] += _load(f) or 0
    load = lambda rows: round(sum(_load(f) for f in rows if _load(f) is not None), 2)
    estimated = lambda rows: round(sum(_load(f) for f in rows if _estimated(f) and _load(f) is not None), 2)
    unknown = lambda rows: sum(_load(f) is None for f in rows)
    initial = load(late) + load(due)
    is_covered = is_covered or (lambda f: True)
    initial_covered = load([f for f in late + due if is_covered(f)])
    late_covered = load([f for f in late if is_covered(f)])
    window_end = _instant(end.isoformat())
    planned = 0.0
    for f in late + due:
        bar = bars.get(f["key"])
        if bar:
            planned += sum(max(0.0, (min(b, window_end) - a).total_seconds() / 3600) for a, b in bar["segments"] if a < window_end)
    capacity_hours = round(unit_cap["hours"], 2) if unit_cap["hours"] is not None else None
    weekly = capacity_hours / (window_days / 7) if capacity_hours else None
    return {
        "window_days": window_days, "until": end.isoformat(),
        "open": {"occurrences": len(facts), "known_hours": load(facts), "estimated_hours": estimated(facts), "unknown_hours": unknown(facts)},
        "late": {"occurrences": len(late), "known_hours": load(late), "estimated_hours": estimated(late), "unknown_hours": unknown(late),
                 "ofs": len({f["of"] for f in late}), "ages": {k: {**v, "known_hours": round(v["known_hours"], 2)} for k, v in ages.items()}},
        "due_in_window": {"occurrences": len(due), "known_hours": load(due), "estimated_hours": estimated(due), "unknown_hours": unknown(due)},
        "blocked": {"no_machine": sum(not _res(f) for f in late + due),
                    "suggested_machine": sum(_suggested(f) for f in late + due),
                    "no_hours": unknown(late + due),
                    "unknown_balance": sum(not f["balance_known"] for f in late + due)},
        "balance": {
            "initial_known_hours": round(initial, 2), "initial_estimated_hours": round(estimated(late) + estimated(due), 2),
            "entries": None, "entries_note": "Sem previsão de entradas: só a carteira atual (não é previsão de procura).",
            "planned_completion_hours": round(planned, 2) if bars else None,
            "planned_note": None if bars else "Sem plano aceite em vigor: conclusão prevista por calcular.",
            "final_known_hours": round(initial - planned, 2) if bars else None,
            "capacity_hours": capacity_hours, "capacity_estimated": unit_cap.get("estimated", False),
            "capacity_basis": unit_cap.get("basis", []),
            "covered_hours": round(initial_covered, 2), "uncovered_hours": round(max(0.0, initial - initial_covered), 2),
            "deficit_hours": round(max(0.0, initial_covered - capacity_hours), 2) if capacity_hours is not None else None,
            "late_weeks_at_capacity": round(late_covered / weekly, 1) if weekly else None,
            "without_capacity": unit_cap.get("without_capacity", []),
            "capacity_known_hours": unit_cap["known_hours"], "capacity_partial": unit_cap["partial"],
            "capacity_note": None if capacity_hours is not None else "Capacidade por confirmar: défice não calculado.",
        },
        "recovery_note": "Semanas de atraso = horas em atraso ÷ capacidade semanal do cenário, sem novas entradas e sem trabalho com prazo dentro da janela; não é uma data prometida.",
    }


def evidence(c, by_id, aliases):
    """Observed (MTG3 Excel throughput) and declared (MTG2 workbook availability) weekly capacity per resource."""
    from . import throughput
    from ..gantt import research, source_plan
    from ..raw import query
    observed, declared = {}, {}
    if not research.enabled():
        return observed, declared
    study = throughput.load(c)
    names = throughput.aliases_to_names(by_id)
    for rid in by_id:
        for name in names[rid]:
            found = study["summary"].get(name)
            if found and found["hours_median"]:
                observed[rid] = found
                break
    try:
        generation = query.generation(c, "perfis")
    except planning.PlanningError:
        return observed, declared
    configs = c.execute("SELECT * FROM planning_mtg.raw_objects WHERE kind='calendar' AND NOT archived").fetchall()
    by_name = {name: by_id[code_id]["id"] for (area, name), code in aliases.items() if area == "perfis"
               for code_id in [next((rid for rid, r in by_id.items() if r["code"] == code), None)] if code_id}
    declared = declared_availability(source_plan.availability(c, generation, configs, by_name))
    return observed, {rid: v for rid, v in declared.items() if rid in by_id and rid not in observed}


def view(areas: list[str], *, horizon_weeks: int = 12, granularity: str = "auto", mode: str = "needs",
         scenario_id: str | None = None, filters: dict | None = None, today: date | None = None,
         scenario: str = "mediana") -> dict:
    from . import occurrences, sets as reference_sets
    from ..gantt import research
    today = today or date.today()
    filters = tree.clean_filters(filters)
    if mode not in ("needs", "proposal", "accepted"):
        raise planning.PlanningError("Escolhe Necessidades, Cenário ou Aceite.")
    with planning.connect(readonly=True) as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        datasets, stamps, memberships = {}, {}, {}
        for area in areas:
            data = occurrences.load(area, conn=c, today=today, allow_stale=True)
            datasets[area] = data["facts"]
            stamps[area] = {"stamp": data["stamp"], "stale": data.get("stale", False)}
            found, _ = reference_sets.memberships(c, area, data["facts"])
            memberships.update(found)
        _, by_id, aliases, _, package = occurrences.resources_context(c)
        observed, declared = evidence(c, by_id, aliases)
        metadata = package["metadata"] if package else {"relations": [], "budgets": [], "resources": []}
        sector_of = {r["codigo"]: research.AREAS.get(r["setor"]) for r in metadata["resources"]}
        resources = {rid: {**r, "area": sector_of.get(r["code"])} for rid, r in by_id.items()}
        budgets = [{"resource_id": by_id_code["id"], "year": date.fromisoformat(b["inicio_semana"]).isocalendar()[0],
                    "week": date.fromisoformat(b["inicio_semana"]).isocalendar()[1], "hours": b["capacidade"] if b["modo"] == "horas" else None}
                   for b in metadata["budgets"] if b["estado"] == "confirmado"
                   for by_id_code in [next((r for r in by_id.values() if r["code"] == b["recurso_codigo"]), None)] if by_id_code]
        accepted, used = accepted_bars(c, areas)
        bars = proposal_bars(c, scenario_id) if mode == "proposal" and scenario_id else accepted if mode in ("accepted", "needs") else {}
        quota_rows = quotas(c)
    result = build(datasets, resources, metadata["relations"], budgets, quota_rows, bars, today=today,
                   horizon_weeks=horizon_weeks, granularity=granularity, filters=filters, sets=memberships,
                   observed=observed, declared=declared, scenario=scenario)
    result.update(mode=mode, stamps=stamps, accepted_plans=used, quotas=quota_rows,
                  capacity_evidence={"observed": {by_id[r]["name"]: v for r, v in observed.items()},
                                     "declared": {by_id[r]["name"]: v for r, v in declared.items()}},
                  filters=filters, horizon_weeks=horizon_weeks)
    return needs.serial(result)


def save_quota(payload: dict, conn=None) -> dict:
    """Share of a shared physical resource for one sector; the shares in force never exceed 1."""
    from .. import planning_registration as registration
    rid = str(payload.get("resource_id") or "").strip()
    area = str(payload.get("area") or payload.get("setor") or "")
    if area not in ("perfis", "cantoneiras", "reserva") or not rid:
        raise planning.PlanningError("Indica o recurso e o setor (ou reserva).")
    try:
        request_id = uuid.UUID(str(payload.get("request_id")))
        valid_from = date.fromisoformat(str(payload.get("valid_from") or date.today().isoformat()))
        valid_until = date.fromisoformat(str(payload["valid_until"])) if payload.get("valid_until") else None
        share = float(payload.get("share"))
    except (ValueError, TypeError, KeyError):
        raise planning.PlanningError("Quota, datas ou pedido inválidos.") from None
    if not 0 <= share <= 1 or (valid_until and valid_until < valid_from):
        raise planning.PlanningError("A quota fica entre 0 e 1 e a vigência não pode terminar antes de começar.")
    reason = str(payload.get("reason") or payload.get("motivo") or "").strip()
    if not reason:
        raise planning.PlanningError("Indica o motivo da quota.")
    actor = registration.human_actor(payload)
    with (planning.connect() if conn is None else nullcontext(conn)) as c:
        c.execute("SELECT pg_advisory_xact_lock(hashtext('sector-capacity-quotas'))")
        if c.execute("SELECT 1 FROM planning_mtg.sector_config_events WHERE request_id=%s AND kind='capacity_quota'", (request_id,)).fetchone():
            return {"repeated": True}
        others = c.execute("""SELECT area,share,valid_from,valid_until FROM planning_mtg.sector_capacity_quotas
            WHERE resource_id=%s AND NOT (area=%s AND valid_from=%s)""", (rid, area, valid_from)).fetchall()
        overlapping = [o for o in others if (o["valid_until"] is None or o["valid_until"] >= valid_from)
                       and (valid_until is None or o["valid_from"] <= valid_until)]
        by_area = defaultdict(float)
        for o in overlapping:
            by_area[o["area"]] = max(by_area[o["area"]], float(o["share"]))
        if sum(by_area.values()) + share > 1 + 1e-9:
            raise planning.PlanningError("A soma das quotas em vigor deste recurso passaria de 100%.", 422)
        prior = c.execute("SELECT * FROM planning_mtg.sector_capacity_quotas WHERE resource_id=%s AND area=%s AND valid_from=%s",
                          (rid, area, valid_from)).fetchone()
        c.execute("""INSERT INTO planning_mtg.sector_capacity_quotas(resource_id,area,valid_from,valid_until,share,reason,actor)
            VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (resource_id,area,valid_from) DO UPDATE SET valid_until=excluded.valid_until,
            share=excluded.share, reason=excluded.reason, actor=excluded.actor, updated_at=now(),
            revision=sector_capacity_quotas.revision+1""", (rid, area, valid_from, valid_until, share, reason, actor))
        c.execute("""INSERT INTO planning_mtg.sector_config_events(kind,area,subject,action,before,after,reason,actor,request_id)
            VALUES ('capacity_quota',%s,%s,'saved',%s,%s,%s,%s,%s)""",
                  (area, f"{rid}|{valid_from.isoformat()}", Jsonb(needs.serial(prior)) if prior else None,
                   Jsonb({"share": share, "valid_until": valid_until.isoformat() if valid_until else None}), reason, actor, request_id))
        return {"repeated": False, "quotas": quotas(c)}
