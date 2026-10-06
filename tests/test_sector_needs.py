"""Vistas por família e capacidade (plano de 01/10/2026): regras puras, sem base de dados.

Cobre os critérios de aceitação 3, 4, 7–10, 12, 14–16 e 20 do plano com dados sintéticos.
"""
from datetime import date, datetime, timedelta, timezone

import pytest

from app import planning
from app.gantt import validation, weekly
from app.sector import capacity, priority, tree

TODAY = date(2026, 10, 1)  # quinta-feira


def marks(**values):
    return priority.milestones_from_values(values, values.pop("raw", None) if "raw" in values else None)


# ------------------------------------------------------------------ priority


def test_mtg3_is_judged_by_the_cut_date_even_with_a_later_picking():
    """Critério 7: corte a 8/10 e Picking a 20/10 → prioridade e atraso pelo corte."""
    m = priority.milestones_from_values({"cut_date": "2026-10-08", "picking_week": 43, "picking_year": 2026}, {})
    due = priority.resolve("cantoneiras", "principal", m)
    assert due["priority_day"] == "2026-10-08" and due["priority_field"] == "cut_date"
    assert due["priority_scope"] == "operation" and due["precision"] == "day"
    assert due["priority_date"] == "2026-10-09T00:00:00+01:00"  # fim do dia local; sem turno inventado
    assert priority.group(due) == 1
    # A MTG2 com a mesma linha continua a usar o Picking (marco da OF).
    mtg2 = priority.resolve("perfis", "principal", m)
    assert mtg2["priority_field"] == "picking" and mtg2["priority_scope"] == "order"


def test_missing_cut_date_is_not_filled_with_picking_and_overrides_keep_reason():
    """Critério 8."""
    m = priority.milestones_from_values({"picking_week": 43, "picking_year": 2026}, {})
    due = priority.resolve("cantoneiras", "principal", m)
    assert due["priority_date"] is None and "Data Corte" in due["missing_reason"]
    assert priority.group(due) == 2
    override = {"id": "x", "definition": {"due_date": "2026-10-15", "applies_to": "principal"}}
    chosen = priority.resolve("cantoneiras", "principal", m, override=override)
    assert chosen["priority_day"] == "2026-10-15" and chosen["priority_source"] == "Substituição manual"
    assert chosen["override_id"] == "x"
    by_field = priority.resolve("cantoneiras", "principal", m, override={"definition": {"field": "picking", "applies_to": "principal"}})
    assert by_field["priority_field"] == "picking" and "substituição" in by_field["priority_source"]


def test_following_operations_keep_their_own_milestone():
    """Critério 9: operações seguintes não herdam o prazo de corte."""
    m = priority.milestones_from_values({"cut_date": "2026-10-08"}, {"Data Galvanização": "2026-10-20"})
    following = priority.resolve("cantoneiras", "following", m)
    assert following["priority_day"] == "2026-10-20" and following["priority_field"] == "galvanizing"
    none = priority.resolve("cantoneiras", "following", priority.milestones_from_values({"cut_date": "2026-10-08"}, {}))
    assert none["priority_date"] is None and none["missing_reason"] == "Operação seguinte sem prazo próprio."
    # A substituição da OF só chega às operações seguintes quando pedida explicitamente.
    o = {"definition": {"due_date": "2026-10-10", "applies_to": "principal"}}
    assert priority.resolve("cantoneiras", "following", m, override=o)["priority_field"] == "galvanizing"
    o["definition"]["applies_to"] = "all"
    assert priority.resolve("cantoneiras", "following", m, override=o)["priority_day"] == "2026-10-10"


def test_picking_without_year_deduces_the_nearest_year():
    m = priority.milestones_from_values({"picking_week": 43, "cut_date": "2026-10-30"}, {})
    plain = priority.resolve("perfis", "principal", m)
    assert plain["priority_field"] == "picking" and plain["provisional"] is True
    assert plain["priority_day"] == "2026-10-19"
    december = priority.resolve("perfis", "principal", priority.milestones_from_values({"picking_week": 1, "cut_date": "2026-12-14"}, {}))
    assert december["priority_day"] == "2027-01-04"
    assumed = priority.milestones_from_values({"picking_week": 43, "cut_date": "2026-10-30"}, {}, assumed_year=2025)
    policy = {**priority.default("perfis"), "assume_picking_year": 2025}
    chosen = priority.resolve("perfis", "principal", assumed, policy=policy)
    assert chosen["priority_field"] == "picking" and chosen["priority_day"] == "2025-10-20"


def test_overrides_are_keyed_by_sector():
    table = {("cantoneiras", "OF1", "*"): {"definition": {"due_date": "2026-10-02"}}}
    assert priority.override_for(table, "cantoneiras", "OF1", "REF") is not None
    assert priority.override_for(table, "perfis", "OF1", "REF") is None


def test_policy_validation_rejects_unknown_fields():
    with pytest.raises(planning.PlanningError):
        priority.validate_policy("cantoneiras", {"principal": ["inventado"], "following": ["galvanizing"]})
    clean = priority.validate_policy("cantoneiras", {"principal": ["cut_date", "delivery_date"], "following": ["galvanizing"]})
    assert clean["principal"] == ["cut_date", "delivery_date"] and clean["assume_picking_year"] is None


def test_windows_follow_the_priority_day():
    due = lambda day: {"priority_day": day}
    assert priority.window(due(None), TODAY) == "sem_data"
    assert priority.window(due("2026-09-30"), TODAY) == "atrasado"
    assert priority.window(due("2026-10-18"), TODAY) == "3_semanas"
    assert priority.window(due("2026-10-19"), TODAY) == "mais_tarde"


# ------------------------------------------------------------------ engine and verifier


def op(key, area, of, *, group, scope=None, deadline=None, state="ready"):
    return {"key": key, "area": area, "of": of, "state": state, "priority_group": group, "deadline": deadline,
            "priority": {"priority_scope": scope} if scope else None, "options": [], "planning_remaining": 1}


def test_score_uses_order_milestone_only_for_picking_and_never_mixes_sectors():
    start = datetime(2026, 10, 1, 7, tzinfo=timezone.utc)
    due = (start + timedelta(minutes=100)).isoformat()
    snapshot = {"started_at": start.isoformat(), "operations": [
        op("a", "perfis", "OF1", group=1, scope="order", deadline=due),
        op("b", "perfis", "OF1", group=1, scope="order", deadline=due),
        op("c", "cantoneiras", "OF1", group=1, scope="operation", deadline=due)],
        "orders": {"OF1": ["a", "b", "c"]}, "accepted_bars": {}}
    bars = {"a": {"end_minute": 50, "start_minute": 0, "resource_id": "m"},
            "b": {"end_minute": 160, "start_minute": 100, "resource_id": "m"},
            "c": {"end_minute": 130, "start_minute": 80, "resource_id": "m"}}
    score = validation.score(snapshot, {"bars": bars})
    # Picking (MTG2): the OF is late by its last operation (160-100=60).
    # Data Corte (MTG3, same OF number): only its own lateness (130-100=30), never the MTG2 one.
    assert score[3] == 60 + 30
    old = {**snapshot, "operations": [{**o, "priority": None} for o in snapshot["operations"]]}
    # Scenarios captured before the sector policy keep the old OF-wide meaning.
    assert validation.order_scoped(old["operations"][2])


# ------------------------------------------------------------------ tree


def fact(key, *, area="cantoneiras", of="OF1", ref="M201", family="M2", profile="L70X70X7", phase="principal",
         hours=1.0, remaining=4.0, machine="Ficep Rapid 25T", day="2026-09-20", late=True, item=None, length=1000.0):
    return {"key": key, "area": area, "unit": "MTG3" if area == "cantoneiras" else "MTG2", "item": item or key,
            "of": of, "ov": "", "customer": "C", "work": of, "designation": "", "reference": ref, "master": ref[:2],
            "sku_family": family, "sku_family_state": "confirmada_pelo_utilizador", "classification": "Confirmada",
            "cpis_family": "Sem família CPIS", "material_type": "Cantoneira", "profile": profile,
            "profile_group": f"Cantoneira · {profile}", "length_mm": length, "pavilion": "MTG3",
            "operation": "CPIS:112", "operation_label": "112", "occurrence": 1 if phase == "principal" else 2,
            "phase": phase, "quantity_required": remaining, "remaining": remaining, "balance_known": remaining is not None,
            "balance_provisional": True, "balance_origin": "Excel provisório",
            "pieces": remaining if phase == "principal" else None,
            "metres": remaining * length / 1000 if phase == "principal" and remaining is not None else None,
            "machine": machine, "assigned_machine": machine, "assigned_resource_id": "r-" + machine, "resource_id": "r-" + machine,
            "decision": None, "hours": hours, "hours_origin": "Excel" if hours is not None else None, "hours_reason": None,
            "priority": {"priority_day": day}, "priority_day": day, "late": late, "late_days": 11 if late else 0,
            "window": "atrasado" if late else "mais_tarde", "started": False, "selection": None, "signals": {},
            "status": "Em Produção", "identity_source": "v2", "occurrence_key": key, "technical_signature": "sig",
            "line_key": key}


FACTS = [fact("a1", of="OF1", ref="M201"), fact("a2", of="OF1", ref="M202", machine="Sem máquina", hours=None),
         fact("a3", of="OF2", ref="M201"), fact("a3s", of="OF2", ref="M201", phase="seguinte", item="a3", hours=0.5),
         fact("b1", of="OF3", ref="DLT1", family="DLT", day="2026-10-20", late=False),
         fact("p1", area="perfis", of="OF1", ref="7745T002", family="Sem família SKU", profile="60.3x2.9", day=None, late=False)]


def test_expanding_keeps_occurrences_and_measures_at_their_level():
    """Critério 3: abrir/recolher e trocar família por perfil conserva totais."""
    dims = tree.dims_for("familias")
    root = tree.build(FACTS, dims, [], {}, today=TODAY)
    assert root["here"]["occurrences"] == 6
    for path in (["MTG3"], ["MTG3", "M2"]):
        result = tree.build(FACTS, dims, path, {}, today=TODAY)
        assert sum(g["summary"]["occurrences"] for g in result["rows"]) == result["here"]["occurrences"]
        assert round(sum(g["summary"]["hours_known"] for g in result["rows"]), 6) == result["here"]["hours_known"]
    m2 = tree.build(FACTS, dims, ["MTG3", "M2"], {}, today=TODAY)["here"]
    # OF1 appears in two references: the parent recounts distinct OF, never sums the children.
    assert m2["ofs"] == 2 and m2["references"] == 2
    assert m2["pieces"] == 12  # principal only; the following operation does not count pieces again
    assert m2["hours_known"] == 2.5 and m2["pending"]["no_hours"] == 1
    by_profile = tree.build(FACTS, tree.dims_for("perfis"), [], {}, today=TODAY)["here"]
    assert by_profile["occurrences"] == root["here"]["occurrences"] and by_profile["hours_known"] == root["here"]["hours_known"]


def test_filters_are_or_within_and_across_dimensions():
    f = tree.clean_filters({"sku_family": ["M2", "DLT"], "unit": ["MTG3"], "flags": ["no_machine"]})
    hits = [x["key"] for x in FACTS if tree.matches(x, f)]
    assert hits == ["a2"]
    f = tree.clean_filters({"sku_family": ["M2", "DLT"]})
    assert {x["key"] for x in FACTS if tree.matches(x, f)} == {"a1", "a2", "a3", "a3s", "b1"}
    with pytest.raises(planning.PlanningError):
        tree.clean_filters({"campo_inventado": ["x"]})


def test_reference_sets_are_a_union_and_never_duplicate_work():
    """Critério 4: referência em dois conjuntos conta uma vez no total."""
    sets = {"a1": ["S1", "S2"], "a3": ["S2"], "a3s": ["S2"]}
    result = tree.build(FACTS, tree.dims_for("conjuntos"), [], {}, today=TODAY, sets=sets, set_names={"S1": "Um", "S2": "Dois"})
    groups = {g["key"]: g for g in result["rows"]}
    assert groups["S2"]["summary"]["occurrences"] == 3 and groups["S1"]["summary"]["occurrences"] == 1
    filtered = tree.build(FACTS, tree.dims_for("conjuntos"), [], {"set": ["S1", "S2"]}, today=TODAY, sets=sets)
    assert filtered["filtered"]["occurrences"] == 3  # a1 counted once
    assert groups["S1"]["label"] == "Um"


def test_leaves_are_occurrences_with_pagination_over_the_whole_population():
    dims = ["unit", "sku_family"]
    page = tree.build(FACTS, dims, ["MTG3", "M2"], {}, today=TODAY, limit=2)
    assert page["kind"] == "occurrences" and page["count"] == 4 and len(page["rows"]) == 2
    rest = tree.build(FACTS, dims, ["MTG3", "M2"], {}, today=TODAY, offset=2, limit=2)
    assert {r["key"] for r in page["rows"]}.isdisjoint(r["key"] for r in rest["rows"])


def test_periods_cover_52_weeks_with_months_far_away_and_iso_year_turn():
    slots = tree.periods(TODAY, 52)
    assert slots[0]["start"] == "2026-09-28" and slots[0]["kind"] == "week"
    assert sum(s["kind"] == "week" for s in slots) == 26 and slots[-1]["kind"] == "month"
    assert slots[-1]["end"] == (date(2026, 9, 28) + timedelta(weeks=52)).isoformat()
    assert all(a["end"] == b["start"] for a, b in zip(slots, slots[1:]))
    keys = [s["key"] for s in tree.periods(date(2026, 12, 20), 3)]
    assert keys == ["2026-W51", "2026-W52", "2026-W53"]
    with pytest.raises(planning.PlanningError):
        tree.periods(TODAY, 53)


# ------------------------------------------------------------------ capacity


def calendar_windows(first_day, days, hours=8):
    out = []
    for i in range(days):
        day = first_day + timedelta(days=i)
        start = datetime(day.year, day.month, day.day, 7, tzinfo=timezone.utc)
        out.append({"start": start.isoformat(), "end": (start + timedelta(hours=hours)).isoformat()})
    return out


def resources(**overrides):
    base = {
        "r1": {"id": "r1", "code": "RAPID25", "name": "Ficep Rapid 25T", "type": "maquina", "windows": [], "calendar_status": "unknown", "area": "cantoneiras"},
        "r2": {"id": "r2", "code": "VANGUARD", "name": "Vanguard", "type": "maquina", "windows": [], "calendar_status": "unknown", "area": "perfis"},
        "post": {"id": "post", "code": "POSTO", "name": "Posto", "type": "posto", "windows": [], "calendar_status": "unknown", "area": "perfis"},
        "eq": {"id": "eq", "code": "EQ", "name": "Serrote", "type": "maquina", "windows": [], "calendar_status": "unknown", "area": "perfis"},
        "ops": {"id": "ops", "code": "OPS", "name": "Operadores", "type": "grupo_operadores", "windows": [], "calendar_status": "unknown", "capacity": 2, "area": "perfis"},
    }
    for key, value in overrides.items():
        base[key] = {**base[key], **value}
    return base


RELATIONS = [{"relacao": "compoe", "pai": "POSTO", "filho": "EQ"}]


def need(key, area, rid, hours, day, family="F1", late=False):
    f = fact(key, area=area, family=family, hours=hours, day=day, late=late)
    f.update(assigned_resource_id=rid, assigned_machine=rid)
    return f


def test_unknown_calendar_has_no_percentage_and_closed_calendar_is_zero():
    """Critério 10: desconhecido, fechado e disponível dão resultados diferentes."""
    data = {"cantoneiras": [need("n1", "cantoneiras", "r1", 10, "2026-10-02")]}
    unknown = capacity.build(data, resources(), RELATIONS, [], [], {}, today=TODAY, horizon_weeks=2)
    week = unknown["units"]["cantoneiras"]["periods"][0]
    assert week["capacity_status"] == "por_confirmar" and week["capacity_hours"] is None and week["pressure_pct"] is None
    assert week["need_hours"] == 10
    closed = capacity.build(data, resources(r1={"calendar_status": "closed"}), RELATIONS, [], [], {}, today=TODAY, horizon_weeks=2)
    week = closed["units"]["cantoneiras"]["periods"][0]
    assert week["capacity_hours"] == 0 and week["capacity_status"] == "sem_capacidade" and week["no_capacity_with_demand"]
    assert week["pressure_pct"] is None  # never divide by zero
    open_ = capacity.build(data, resources(r1={"windows": calendar_windows(date(2026, 10, 1), 2)}), RELATIONS, [], [], {}, today=TODAY, horizon_weeks=2)
    week = open_["units"]["cantoneiras"]["periods"][0]
    assert week["capacity_hours"] == 16 and week["pressure_pct"] == 62.5


def test_family_shares_reconcile_and_a_filter_keeps_the_denominator():
    """Critérios 12 e 15; o exemplo ilustrativo do plano: 200 h, 80+40+20 h → 70%."""
    start = datetime(2026, 9, 28, 7, tzinfo=timezone.utc)
    windows = [{"start": start.isoformat(), "end": (start + timedelta(hours=200)).isoformat()}]
    data = {"cantoneiras": [need("m1", "cantoneiras", "r1", 80, "2026-10-02", "M1"), need("m2", "cantoneiras", "r1", 40, "2026-10-02", "M2"),
                            need("o", "cantoneiras", "r1", 20, "2026-10-02", "Outras")]}
    bars = {}
    cursor = start
    for key, hours in (("m1", 80), ("m2", 40), ("o", 20)):
        bars[key] = {"resource_id": "r1", "segments": [(cursor, cursor + timedelta(hours=hours))]}
        cursor += timedelta(hours=hours)
    result = capacity.build(data, resources(r1={"windows": windows}), RELATIONS, [], [], bars, today=TODAY, horizon_weeks=2,
                            filters={"sku_family": ["M1"]})
    weeks = result["units"]["cantoneiras"]["periods"]
    total_cap = sum(w["capacity_hours"] for w in weeks)
    total_alloc = sum(w["allocated_hours"] for w in weeks)
    assert round(total_cap, 6) == 200 and round(total_alloc, 6) == 140
    assert round(100 * total_alloc / total_cap, 1) == 70.0
    fam = {}
    for w in weeks:
        for f in w["families"]:
            fam[f["family"]] = fam.get(f["family"], 0) + f["allocated_hours"]
        assert round(sum(f["allocated_hours"] for f in w["families"]), 6) == w["allocated_hours"]
    assert round(100 * fam["M1"] / total_cap, 1) == 40.0 and round(100 * fam["M1"] / total_alloc, 1) == 57.1
    assert sum(w["highlight"]["allocated_hours"] for w in weeks) == pytest.approx(80)
    assert all(w["capacity_hours"] == unfiltered["capacity_hours"] for w, unfiltered in zip(
        weeks, capacity.build(data, resources(r1={"windows": windows}), RELATIONS, [], [], bars, today=TODAY, horizon_weeks=2)["units"]["cantoneiras"]["periods"]))


def test_an_operation_across_weeks_contributes_only_its_segments():
    """Critério 14: a ocupação reconcilia com a duração total e respeita pausas."""
    friday = datetime(2026, 10, 2, 13, tzinfo=timezone.utc)
    monday = datetime(2026, 10, 5, 7, tzinfo=timezone.utc)
    bars = {"x": {"resource_id": "r1", "segments": [(friday, friday + timedelta(hours=3)), (monday, monday + timedelta(hours=5))]}}
    data = {"cantoneiras": [need("x", "cantoneiras", "r1", 8, "2026-10-09")]}
    result = capacity.build(data, resources(), RELATIONS, [], [], bars, today=TODAY, horizon_weeks=3)
    weeks = result["units"]["cantoneiras"]["periods"]
    assert [w["allocated_hours"] for w in weeks] == [3, 5, 0]


def test_shared_resource_without_quota_is_not_counted_twice():
    """Critério 13: uma máquina usada pelos dois setores não dá 100% a cada um."""
    windows = calendar_windows(date(2026, 10, 1), 2)
    data = {"cantoneiras": [need("c", "cantoneiras", "r2", 4, "2026-10-02")], "perfis": [need("p", "perfis", "r2", 4, "2026-10-02")]}
    res = resources(r2={"windows": windows})
    result = capacity.build(data, res, RELATIONS, [], [], {}, today=TODAY, horizon_weeks=1)
    assert [s["name"] for s in result["shared"]] == ["Vanguard"]
    for area in ("perfis", "cantoneiras"):
        week = result["units"][area]["periods"][0]
        assert week["capacity_partial"] is True
    quotas = [{"resource_id": "r2", "area": "perfis", "share": 0.75, "valid_from": "2026-01-01", "valid_until": None},
              {"resource_id": "r2", "area": "cantoneiras", "share": 0.25, "valid_from": "2026-01-01", "valid_until": None}]
    split = capacity.build(data, res, RELATIONS, [], quotas, {}, today=TODAY, horizon_weeks=1)
    lane = lambda area: next(l for l in split["units"][area]["resources"] if l["resource_id"] == "r2")["periods"][0]
    assert lane("perfis")["capacity_hours"] == 12 and lane("cantoneiras")["capacity_hours"] == 4
    assert not split["shared"]


def test_posts_and_operators_never_add_machine_hours():
    shape = capacity.physical(resources(), RELATIONS)
    assert shape["roles"]["post"] == "posto_composto" and shape["roles"]["ops"] == "operadores"
    assert shape["members"]["post"] == ["eq"]


def test_demand_above_capacity_stays_visible_and_backlog_keeps_unknowns():
    """Critério 15: necessidade acima de 100% fica visível; défice só com capacidade conhecida."""
    windows = calendar_windows(date(2026, 10, 1), 1, hours=10)
    data = {"cantoneiras": [need("a", "cantoneiras", "r1", 22, "2026-10-02"), need("late", "cantoneiras", "r1", 5, "2026-09-01", late=True),
                            {**need("u", "cantoneiras", "r1", None, "2026-10-03")}]}
    result = capacity.build(data, resources(r1={"windows": windows}), RELATIONS, [], [], {}, today=TODAY, horizon_weeks=1)
    unit = result["units"]["cantoneiras"]
    assert unit["periods"][0]["pressure_pct"] == 220.0
    balance = unit["backlog"]["balance"]
    assert balance["initial_known_hours"] == 27 and balance["capacity_hours"] == 10 and balance["deficit_hours"] == 17
    assert unit["backlog"]["due_in_window"]["unknown_hours"] == 1
    unknown = capacity.build(data, resources(), RELATIONS, [], [], {}, today=TODAY, horizon_weeks=1)
    assert unknown["units"]["cantoneiras"]["backlog"]["balance"]["deficit_hours"] is None


# ------------------------------------------------------------------ weekly simulation


def test_weekly_simulation_carries_a_long_lot_across_consecutive_weeks():
    """Uma operação longa reserva várias semanas sem declarar conclusão na primeira."""
    start = datetime(2026, 9, 28, 7, tzinfo=timezone.utc)
    snapshot = {"started_at": start.isoformat(), "horizon_minutes": 4 * 7 * 1440,
                "resources": {"m": {"windows": [], "shared_demands": {}}},
                "weekly_availability": [{"resource_id": "m", "year": 2026, "week": w, "hours": 30, "status": "confirmed"} for w in (40, 41, 42, 43)],
                "operations": [{"key": "long", "state": "ready", "priority_group": 1, "deadline": None, "planning_remaining": 10,
                                "assignment": {"resource_id": "m", "conditions": []}, "source_duration": {"hours": 70},
                                "technical": {}, "blocking_reasons": []},
                               {"key": "after", "state": "ready", "priority_group": 1, "deadline": None, "planning_remaining": 1,
                                "assignment": {"resource_id": "m", "conditions": []}, "source_duration": {"hours": 5},
                                "technical": {}, "blocking_reasons": [], "predecessor_keys": ["long"]}]}
    result = weekly.build(snapshot)
    long = [a for a in result["allocations"] if a["key"] == "long"]
    assert [a["charge"] for a in long] == [30, 30, 10] and long[-1]["segments"] == 3
    assert sum(a["charge"] for a in long) == long[0]["lot_charge"] == 70
    after = next(a for a in result["allocations"] if a["key"] == "after")
    assert after["start_date"] == "2026-10-19"  # only after the last week of its predecessor, not in W42's spare 20 h
    snapshot["weekly_availability"] = [b for b in snapshot["weekly_availability"] if b["week"] != 41]
    gap = weekly.build(snapshot)
    assert not any(a["key"] == "long" for a in gap["allocations"])  # never split across a gap week


def test_backlog_evaluation_uses_frozen_reference_hours_and_never_counts_omitted_work():
    from app.gantt import backlog
    start = datetime(2026, 10, 1, 7, tzinfo=timezone.utc)
    option = lambda rid, minutes: {"resource_id": rid, "duration_minutes": minutes, "eligibility": "admissible"}
    ops = [{"key": "late", "area": "cantoneiras", "of": "OF1", "state": "ready", "deadline": (start - timedelta(days=1)).isoformat(),
            "source_resource_id": "slow", "options": [option("fast", 60), option("slow", 120)]},
           {"key": "due", "area": "cantoneiras", "of": "OF1", "state": "ready", "deadline": (start + timedelta(days=3)).isoformat(),
            "source_resource_id": None, "options": [option("fast", 30)]},
           {"key": "blocked", "area": "cantoneiras", "of": "OF2", "state": "blocked", "deadline": (start + timedelta(days=2)).isoformat(), "options": []}]
    snapshot = {"started_at": start.isoformat(), "horizon_minutes": 28 * 1440, "operations": ops}
    proposal = {"bars": {"late": {"end_minute": 100, "resource_id": "fast"}, "due": {"end_minute": 21000, "resource_id": "fast"}}}
    result = backlog.evaluate(snapshot, proposal)
    # The late operation is worth its source machine's 2 h, whichever machine the plan uses.
    assert result["late_reference_hours"] == 2 and result["late_completed_hours"] == 2
    assert result["due_completed_hours"] == 0  # finishes after the 14-day window
    assert result["unknown_reference_hours"] == 1 and result["not_ready"] == 1
    assert result["orders_due"] == 2 and result["orders_completed"] == 0
    assert backlog.compare(snapshot, {"bars": {}}, proposal)["gain_late_hours"] == 2
