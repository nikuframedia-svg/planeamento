"""Carga e turnos (app/sector/load.py) e estado das linhas: regras da auditoria de 06/10/2026. Sem base de dados."""
from contextlib import contextmanager
from datetime import date, datetime, timezone

from app.sector import load, planning_status, portfolio, settings as sector_settings

TODAY = date(2026, 10, 6)  # terça-feira; a semana ISO 41 começa a 05/10


def fact(key, rid, day, hours, *, basis="atribuída", line_key=None, phase="principal"):
    return {"key": key, "line_key": line_key or key, "of": "OF1", "planning_resource_id": rid, "machine_basis": basis,
            "priority_day": day, "load_hours": hours, "phase": phase, "pieces": 1, "metres": 1.0}


def test_late_is_a_deadline_before_today_like_the_carteira_and_the_panel():
    """C5-3: prazo na segunda desta semana (ontem) é atrasado; conta na semana atual."""
    weeks = load.week_list(TODAY)
    found = load.classify(fact("a", "m1", "2026-10-05", 2.0), set(), weeks[0], set(weeks), TODAY)
    assert found == (load.DUE, (2026, 41), True)
    assert load.classify(fact("b", "m1", "2026-10-06", 2.0), set(), weeks[0], set(weeks), TODAY) == (load.DUE, (2026, 41), False)
    assert load.classify(fact("c", "m1", "2026-09-30", 2.0), set(), weeks[0], set(weeks), TODAY)[2] is True


def test_excluded_line_is_outside_the_three_states():
    """A8-5: uma linha excluída com máquina não é «Planeado para nesting»."""
    assert planning_status.classify({"decision": "excluded"}, "Peddi 8") == {"planeado": False, "nesting": False, "sem_maquina": False}
    assert planning_status.classify({"decision": None}, "Peddi 8")["nesting"] is True
    assert planning_status.classify({"decision": "selected"}, "Peddi 8")["planeado"] is True


def test_excluded_line_does_not_count_in_the_load(monkeypatch):
    """A8-5: a Carga não conta as ocorrências de uma linha excluída na Carteira (como a lista vermelha)."""
    from app.sector import occurrences, selection
    lines = [{"key": "L1", "of": "OF1", "reference": "R1", "machine": "M"}, {"key": "L2", "of": "OF1", "reference": "R2", "machine": "M"}]
    monkeypatch.setattr(portfolio, "current", lambda sector, **kw: {"lines": lines})
    monkeypatch.setattr(selection, "current", lambda sector: {("OF1", "R2"): {"decision": "excluded"}})
    monkeypatch.setattr(occurrences, "load", lambda sector, allow_stale=True: {"facts": [fact("o1", "m1", "2026-10-07", 1.0, line_key="L1"),
                                                                                        fact("o2", "m1", "2026-10-07", 1.0, line_key="L2")]})
    _, planned, occ = load._context("perfis", TODAY)
    assert planned == set() and [f["key"] for f in occ["facts"]] == ["o1"]


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class _Conn:
    def execute(self, sql, params=None):
        return _Rows([])


def test_sector_machine_without_calendar_but_with_work_shows_with_zero_capacity(monkeypatch):
    """A7-3: Plasma manual (sem calendário, operações sem prazo nem horas) aparece como linha «Sem calendário»."""
    from app.sector import load_sources
    machines = [{"id": "plasma", "name": "Plasma manual", "code": "PLASMA", "process": "Corte", "default_shifts": 1},
                {"id": "idle", "name": "Saca bocados", "code": "SACA", "process": "Corte", "default_shifts": 1}]

    @contextmanager
    def connect(readonly=True):
        yield _Conn()

    monkeypatch.setattr(load.planning, "check_area", lambda sector: None)
    monkeypatch.setattr(load.planning, "connect", connect)
    monkeypatch.setattr(load, "_context", lambda sector, today=None: ({"lines": []}, set(), {"facts": [
        fact("p1", "plasma", None, None, basis="sugerida", phase="seguinte"), fact("p2", "plasma", None, None, basis="sugerida", phase="seguinte")]}))
    monkeypatch.setattr(sector_settings, "read", lambda c, sector: sector_settings.default(TODAY))
    monkeypatch.setattr(sector_settings, "machine_rows", lambda c, sector: machines)
    monkeypatch.setattr(load_sources, "context", lambda c, sector: {"lines": {}, "actual": {}})
    monkeypatch.setattr(load_sources, "fact_values", lambda f, lines: (None, None, False))
    result = load.overview("cantoneiras", today=TODAY, now=datetime(2026, 10, 6, 12, tzinfo=timezone.utc))
    [row] = result["machines"]  # a máquina sem trabalho e sem calendário continua escondida
    assert row["id"] == "plasma" and row["no_date"] == {"hours": 0.0, "unknown": 2, "operations": 2}
    assert all(w["capacity"] == 0 and w["status"] == "sem_calendario" and w["advice"]["text"] == "Sem calendário" for w in row["weeks"])


def test_estimated_hours_show_the_estimate_calculation_not_the_engine_proof():
    """CARGA-OPS-01: horas estimadas explicadas pela conta da estimativa (saldo, comprimento ou área, taxa e origem)."""
    angle = {"area": "cantoneiras", "load_basis": "estimada", "load_hours": 1.5, "remaining": 10, "length_mm": 6000,
             "load_origin": "Estimativa: mediana Excel de Peddi 8 para L45X45X5 (12 linhas), 40 m/h"}
    calc = load.estimate_calculation(angle)
    assert calc["volume"] == 60 and calc["volume_unit"] == "m" and calc["rate"] == 40 and calc["rate_unit"] == "m/h"
    assert calc["basis"] == angle["load_origin"] and "velocidade do Excel" in calc["formula"]
    profile = {"area": "perfis", "load_basis": "estimada", "load_hours": 2.0, "remaining": 4, "section_unit": 5000.0,
               "load_origin": "Estimativa: taxa Excel 10000 mm²/h de Vanguard (sem fator ×3)"}
    calc = load.estimate_calculation(profile)
    assert calc["volume"] == 20000 and calc["rate"] == 10000 and calc["rate_unit"] == "mm²/h"
    assert load.estimate_calculation({**angle, "load_basis": "documental"}) is None
    assert load.estimate_calculation({**angle, "load_hours": None}) is None


def test_operations_return_the_estimate_and_mark_the_engine_proof_as_unused(monkeypatch):
    from app.sector import load_sources

    @contextmanager
    def connect(readonly=True):
        yield _Conn()

    estimated = {**fact("e", "m1", "2026-10-07", 1.5, line_key="L1"), "area": "cantoneiras", "load_basis": "estimada",
                 "remaining": 10, "length_mm": 6000, "load_origin": "Estimativa: x, 40 m/h", "operation": "1"}
    documental = {**fact("d", "m1", "2026-10-07", 2.0, line_key="L2"), "area": "cantoneiras", "load_basis": "documental", "operation": "1"}
    monkeypatch.setattr(load.planning, "check_area", lambda sector: None)
    monkeypatch.setattr(load.planning, "connect", connect)
    monkeypatch.setattr(load, "_context", lambda sector, today=None: ({"lines": []}, set(), {"facts": [estimated, documental]}))
    monkeypatch.setattr(load_sources, "context", lambda c, sector: {"lines": {}, "actual": {}})
    monkeypatch.setattr(load_sources, "proofs", lambda c, sector, keys: {(k, "Corte"): {"formula": "Taxa e método por confirmar"} for k in keys})
    import app.sector.occurrences as occurrences
    monkeypatch.setattr(occurrences, "_estimate_name", lambda op, sector, principal: "Corte")
    ops = {o["load_basis"]: o for o in load.operations("cantoneiras", "m1", 2026, 41, "OF1", today=TODAY)["operations"]}
    assert ops["estimada"]["estimate"]["rate"] == 40 and ops["estimada"]["proof_used"] is False
    assert ops["documental"]["estimate"] is None and ops["documental"]["proof_used"] is True


def test_production_rows_get_the_hours_of_their_sheet_once(monkeypatch):
    """CARGA-PROD-04: hours_worked da linha é sempre vazio; as horas vêm da folha (production_hours)."""
    from app.raw import query
    calls = []

    def listing(p, conn=None):
        calls.append(p)
        assert p["dataset"] == "production_hours"
        return {"rows": [{"key": "s1", "sheet_uid": "s1", "values": {"hours_worked": 7.5}},
                         {"key": "s2", "sheet_uid": "s2", "values": {"hours_worked": None}},
                         {"key": "s9", "sheet_uid": "s9", "values": {"hours_worked": 3.0}}]}
    monkeypatch.setattr(query, "listing", listing)
    rows = [{"sheet_uid": "s1", "values": {"hours_worked": None}}, {"sheet_uid": "s1", "values": {}}, {"sheet_uid": "s2", "values": {}}]
    assert load._sheet_hours("cantoneiras", date(2026, 9, 28), rows) == {"s1": 7.5, "s2": None}
    assert calls[0]["filters"][0]["min"] == "2026-09-28" and calls[0]["filters"][0]["max"] == "2026-10-04"
    assert load._sheet_hours("cantoneiras", date(2026, 9, 28), []) == {} and len(calls) == 1


def _overview_with_calendar(monkeypatch, facts, shifts_per_day=2, *, planned=(), lines=(), machines=None, src=None):
    """overview() com uma máquina «m1» com calendário em todas as semanas (turnos seg–sex) e os factos dados."""
    from app.sector import drive_notice, load_sources, shifts
    settings = sector_settings.default(TODAY)
    machines = machines or [{"id": "m1", "name": "Peddi 8", "code": "P8", "process": "Corte", "default_shifts": 2}]
    plan = {str(d): (shifts_per_day if d <= 5 else 0) for d in range(1, 8)}
    calendars = [{"definition": shifts.definition_for(m["id"], y, w, plan, {}, settings, manual=False)}
                 for m in machines for y, w in load.week_list(TODAY)]

    class Conn:
        def execute(self, sql, params=None):
            return _Rows(calendars if "kind='calendar'" in sql else [])

    @contextmanager
    def connect(readonly=True):
        yield Conn()

    monkeypatch.setattr(load.planning, "check_area", lambda sector: None)
    monkeypatch.setattr(load.planning, "connect", connect)
    monkeypatch.setattr(load, "_context", lambda sector, today=None: ({"lines": list(lines)}, set(planned), {"facts": facts}))
    monkeypatch.setattr(sector_settings, "read", lambda c, sector: settings)
    monkeypatch.setattr(sector_settings, "machine_rows", lambda c, sector: machines)
    monkeypatch.setattr(load_sources, "context", lambda c, sector: src or {"lines": {}, "actual": {}})
    monkeypatch.setattr(load_sources, "fact_values", lambda f, lines: (None, None, False))
    monkeypatch.setattr(drive_notice, "text", lambda sector: None)
    return load.overview("cantoneiras", today=TODAY, now=datetime(2026, 10, 6, 12, tzinfo=timezone.utc))


def test_zero_shift_weeks_are_not_a_calendar(monkeypatch):
    """07/10: semanas gravadas a 0 turnos não contam como calendário (a máquina continua «sem calendário»)."""
    [row] = _overview_with_calendar(monkeypatch, [fact("now", "m1", "2026-10-08", 6.0)], shifts_per_day=0)["machines"]
    assert row["has_calendar"] is False


def test_late_before_the_current_week_is_apart_from_the_current_week_load(monkeypatch):
    """07/10: o atrasado (prazo antes de segunda) sai da carga da semana atual e vai para «late_before»."""
    facts = [fact("old", "m1", "2026-09-30", 30.0), fact("mon", "m1", "2026-10-05", 4.0), fact("now", "m1", "2026-10-08", 6.0),
             fact("next", "m1", "2026-10-14", 5.0), fact("nodate", "m1", None, 3.0), fact("far", "m1", "2027-06-01", 7.0)]
    result = _overview_with_calendar(monkeypatch, facts)
    [row] = result["machines"]
    assert row["late_before"] == {"hours": 30.0, "unknown": 0, "operations": 1, "plan": 0.0, "due": 30.0, "suggested": 0.0}
    current, nxt = row["weeks"][0], row["weeks"][1]
    assert current["load"] == 10.0 and current["late"] == 4.0  # segunda (ontem) fica na semana, marcada como atrasada
    assert nxt["load"] == 5.0 and row["no_date"]["hours"] == 3.0 and row["after"] == 7.0 and row["has_calendar"] is True
    # Semana inteira: 2 turnos × 7,5 h × 4 dias (05/10 é feriado); a que falta é menor (já passou meio dia de terça).
    assert current["full_capacity"] == 60.0 and current["capacity"] < current["full_capacity"] and nxt["full_capacity"] == nxt["capacity"] == 75.0
    [total] = result["totals"]
    assert total["late_before"] == 30.0 and total["late"] == 34.0 and total["week_capacity"] == 75.0


def test_current_week_advice_counts_the_late_work_against_the_hours_left(monkeypatch):
    facts = [fact("old", "m1", "2026-09-30", 80.0), fact("now", "m1", "2026-10-08", 6.0)]
    [row] = _overview_with_calendar(monkeypatch, facts)["machines"]
    current = row["weeks"][0]
    missing = 86.0 - current["capacity"]
    # 08/10: a recomendação diz que inclui o atrasado, que a cor não conta (para não parecer contraditória).
    assert current["advice"]["delta"] == 1 and current["advice"]["text"] == f"faltam {missing:.0f} h · +1 turno · inclui 80 h atrasadas"
    assert "atrasadas" not in row["weeks"][1]["advice"]["text"]  # só a semana atual conta o atrasado
    # A cor bate com o que a célula mostra («6 / 60 h»): o atrasado tem a sua coluna e não pinta a semana atual.
    assert current["load"] == 6.0 and current["full_capacity"] == 60.0 and current["status"] == "folga"


def test_week_colour_matches_the_numbers_in_the_cell(monkeypatch):
    """Revisão 07/10: cor = carga da semana contra a capacidade da semana inteira (os números escritos)."""
    for hours, status in ((50.0, "folga"), (55.0, "apertado"), (61.0, "falta")):
        [row] = _overview_with_calendar(monkeypatch, [fact("now", "m1", "2026-10-08", hours)])["machines"]
        current = row["weeks"][0]
        assert current["full_capacity"] == 60.0 and current["status"] == status, (hours, current["status"])
    # Mesmo com a semana quase vazia e muito atrasado, a célula não fica vermelha.
    [row] = _overview_with_calendar(monkeypatch, [fact("old", "m1", "2026-09-30", 500.0)])["machines"]
    assert row["weeks"][0]["load"] == 0 and row["weeks"][0]["status"] == "folga"


def test_never_minus_one_shift_with_late_or_undated_work(monkeypatch):
    """07/10: nunca «−1 turno» numa máquina com atrasado ou sem prazo, mesmo com a semana quase vazia."""
    for extra in ([fact("old", "m1", "2026-09-30", 1.0)], [fact("nodate", "m1", None, 1.0)], [fact("nodate", "m1", None, None)]):
        [row] = _overview_with_calendar(monkeypatch, [fact("next", "m1", "2026-10-14", 1.0), *extra])["machines"]
        assert all(w["advice"]["delta"] >= 0 for w in row["weeks"]), extra
        assert row["weeks"][1]["advice"]["text"] == "sobram 74 h"
    # Sem atrasado nem sem prazo, a semana seguinte quase vazia com 2 turnos: −1 turno, com o texto simples.
    [row] = _overview_with_calendar(monkeypatch, [fact("next", "m1", "2026-10-14", 1.0)])["machines"]
    assert row["weeks"][1]["advice"]["delta"] == -1 and row["weeks"][1]["advice"]["text"] == "sobram 74 h · −1 turno"
    assert all(w["advice"]["delta"] == 0 for w in row["weeks"][load.REDUCE_WEEKS:])  # mais à frente a carga ainda está a chegar


def test_advice_text_is_short():
    assert load.advice_text({"delta": 2}, 52.4)["text"] == "faltam 52 h · +2 turnos"
    assert load.advice_text({"delta": -1}, -40.0)["text"] == "sobram 40 h · −1 turno"
    assert load.advice_text({"delta": 0}, 20.0, 3)["text"] == "faltam 20 h · já tem 3 turnos"
    assert load.advice_text({"delta": 0}, 20.0, 1)["text"] == "faltam 20 h"
    assert load.advice_text({"delta": 0}, 0.0)["text"] == "certo"
    assert load.advice_text({"delta": 0}, -3.0, late=12.4)["text"] == "sobram 3 h · inclui 12 h atrasadas"
    assert load.advice_text({"delta": 1}, 30.0, late=0.01)["text"] == "faltam 30 h · +1 turno"


def test_late_before_is_split_by_kind_planned_due_and_suggested(monkeypatch):
    """F12 (08/10): a coluna Atrasado separa «no plano», «a vencer» e «sugerida» (o Planeado atrasado já não some)."""
    facts = [fact("p", "m1", "2026-09-28", 3.0, line_key="LP"), fact("d", "m1", "2026-09-29", 5.0),
             fact("s", "m1", "2026-09-30", 7.0, basis="sugerida"), fact("u", "m1", "2026-09-30", None)]
    [row] = _overview_with_calendar(monkeypatch, facts, planned={"LP"})["machines"]
    assert row["late_before"] == {"hours": 15.0, "unknown": 1, "operations": 4, "plan": 3.0, "due": 5.0, "suggested": 7.0}
    assert row["weeks"][0]["load"] == 0 and row["weeks"][0]["status"] == "folga"  # a cor mantém a decisão de 07/10


def _cell(monkeypatch, facts, lines=(), year=2026, week=41, planned=()):
    from app.sector import load_sources

    @contextmanager
    def connect(readonly=True):
        yield _Conn()

    monkeypatch.setattr(load.planning, "check_area", lambda sector: None)
    monkeypatch.setattr(load.planning, "connect", connect)
    monkeypatch.setattr(load, "_context", lambda sector, today=None: ({"lines": list(lines)}, set(planned), {"facts": facts}))
    monkeypatch.setattr(load_sources, "context", lambda c, sector: {"lines": {}, "actual": {}})
    monkeypatch.setattr(load_sources, "fact_values", lambda f, lines: (None, None, False))
    return load.cell("cantoneiras", "m1", year, week, today=TODAY)


def test_current_week_cell_separates_the_week_hours_from_the_late_ones(monkeypatch):
    """F12 (08/10): o detalhe da semana atual dizia 243,4 h contra 30,2 h na grelha (somava o atrasado)."""
    facts = [{**fact("old", "m1", "2026-09-30", 30.0), "of": "OF1"}, {**fact("old2", "m1", "2026-09-29", 4.0, line_key="LP"), "of": "OF2"},
             {**fact("now", "m1", "2026-10-08", 6.0), "of": "OF2"}, {**fact("mon", "m1", "2026-10-05", 2.0), "of": "OF3"}]
    d = _cell(monkeypatch, facts, planned={"LP"})
    assert d["hours"] == 42.0 and d["week_hours"] == 8.0  # 6 + 2: os mesmos da célula da grelha
    assert d["late_before"] == {"hours": 34.0, "unknown": 0, "operations": 2, "plan": 4.0, "due": 30.0, "suggested": 0.0}
    by = {o["of"]: o for o in d["orders"]}
    assert (by["OF1"]["week_hours"], by["OF1"]["late_before_hours"]) == (0.0, 30.0)
    assert (by["OF2"]["week_hours"], by["OF2"]["late_before_hours"]) == (6.0, 4.0)
    # Noutra semana não há atrasado à parte.
    later = _cell(monkeypatch, [fact("next", "m1", "2026-10-14", 5.0)], week=42)
    assert later["week_hours"] == later["hours"] == 5.0 and later["late_before"]["operations"] == 0


def test_cell_weight_pieces_and_metres_unknown_are_never_zero(monkeypatch):
    """F09/F21 (08/10): peso da Carteira (peso unitário × saldo); sem peso, «—» (None), nunca 0,0 kg."""
    lines = [{"key": "L1", "pieces": 10, "metres": 20.0, "weight_unit": 2.5, "metres_unknown": False},
             {"key": "L2", "pieces": None, "metres": 0.0, "weight_unit": None, "metres_unknown": True, "balance_unknown": True}]
    facts = [{**fact("a", "m1", "2026-10-08", 1.0, line_key="L1"), "of": "OF1", "remaining": 10},
             {**fact("b", "m1", "2026-10-08", 1.0, line_key="L2"), "of": "OF2", "remaining": None}]
    d = _cell(monkeypatch, facts, lines=lines)
    by = {o["of"]: o for o in d["orders"]}
    assert by["OF1"]["weight_kg"] == 25.0 and by["OF1"]["weight_unknown"] == 0 and by["OF1"]["pieces"] == 10
    assert by["OF2"]["weight_kg"] is None and by["OF2"]["weight_unknown"] == 1
    assert by["OF2"]["pieces_unknown"] == 1 and by["OF2"]["metres_unknown"] == 1
    assert d["weight_kg"] == 25.0 and d["weight_unknown"] == 1


def test_load_and_portfolio_weights_come_from_one_source_and_count_the_same_unknowns(monkeypatch):
    """F21 (08/10): kg da Carga = peso unitário da Carteira × saldo; o «sem peso» conta a mesma população.

    Uma linha sem saldo no corte (só falta a 2.ª operação) tem 0 kg por cortar nos dois lados, com ou sem peso.
    """
    from app.sector import drive_notice
    from tests.test_sector_portfolio import data as portfolio_data, raw
    heavy = raw("OF1", "A", 10, 1000, key="L1")
    heavy["v"]["weight_unit"] = 2.0
    light = raw("OF1", "B", 5, 1000, key="L2")
    done = raw("OF1", "C", 4, 1000, key="L3")
    done["v"]["planning_remaining"] = 0
    done["detail"] = {"calculation": {"integrated_operations": [{"operation": "CPIS:111", "occurrence": 2, "remaining": 4}]}}
    d = portfolio_data(heavy, light, done)
    monkeypatch.setattr(drive_notice, "text", lambda sector: None)
    totals = portfolio.groups("cantoneiras", "of", data=d)["list_totals"]
    assert totals["tonnes"] == 0.02 and totals["weight_unknown"] == 1
    facts = [{**fact("a", "m1", "2026-10-08", 1.0, line_key="L1"), "remaining": 10},
             {**fact("b", "m1", "2026-10-08", 1.0, line_key="L2"), "remaining": 5},
             {**fact("c", "m1", "2026-10-08", 1.0, line_key="L3", phase="seguinte"), "remaining": 4}]
    [total] = _overview_with_calendar(monkeypatch, facts, lines=d["lines"])["totals"]
    assert total["weight_kg"] == 20.0 and total["weight_unknown"] == totals["weight_unknown"] == 1


def test_machines_of_a_post_show_the_shared_capacity_and_stay_as_rows(monkeypatch):
    """F18 (08/10): o Fita pav.1 contém o Doall e a Thomas; as linhas continuam por máquina, com a nota do posto."""
    machines = [{"id": "fita", "name": "Serrote Fita pav.1", "code": "POSTO_FITA", "process": None, "default_shifts": 2},
                {"id": "doall", "name": "Serrote Doall Pav.1", "code": "DOALL", "process": None, "default_shifts": 1},
                {"id": "meba", "name": "Serrote MEBA", "code": "MEBA", "process": None, "default_shifts": 1}]
    src = {"lines": {}, "actual": {}, "posts": {"fita": ["doall", "thomas"]}, "names": {"thomas": "Serrote Thomas"}}
    result = _overview_with_calendar(monkeypatch, [fact("x", "doall", "2026-10-08", 1.0)], machines=machines, src=src)
    rows = {r["id"]: r for r in result["machines"]}
    assert set(rows) == {"fita", "doall", "meba"} and "shared" not in rows["meba"]
    fita, doall = rows["fita"]["shared"], rows["doall"]["shared"]
    # O posto tem calendário próprio: substitui as máquinas (não 60 + 60), como capacity.counted().
    assert doall["hours"] == fita["hours"] == rows["fita"]["weeks"][0]["full_capacity"] == 60.0
    assert doall == {"post": "Serrote Fita pav.1", "is_post": False, "with": ["Serrote Thomas"], "hours": 60.0, "weeks": doall["weeks"]}
    assert fita["is_post"] and fita["with"] == ["Serrote Doall Pav.1", "Serrote Thomas"]


def test_work_on_other_sector_machines_is_counted_even_without_hours(monkeypatch):
    """F14 (08/10): as operações noutro setor aparecem na nota mesmo sem horas (antes a nota ficava escondida)."""
    facts = [fact("x", "outra", None, None, phase="seguinte"), fact("y", "outra", None, None, phase="seguinte")]
    result = _overview_with_calendar(monkeypatch, facts)
    assert result["elsewhere"]["operations"] == 2 and result["elsewhere"]["hours"] == 0 and result["elsewhere"]["unknown"] == 2


def test_lisbon_day_between_23_and_midnight(monkeypatch):
    """F24 (08/10): às 23:30 de Lisboa já é meia-noite e meia em Berlim (o fuso do servidor); o dia é o de Lisboa."""
    from zoneinfo import ZoneInfo
    from app.sector import board, occurrences, warmup, week
    instant = datetime(2026, 10, 7, 22, 30, tzinfo=timezone.utc)  # 23:30 Lisboa, 00:30 Berlim
    assert instant.astimezone(ZoneInfo("Europe/Berlin")).date() == date(2026, 10, 8)
    assert week.lisbon_today(instant) == date(2026, 10, 7)

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)
    monkeypatch.setattr(week, "datetime", Frozen)
    assert load._today() == warmup._today() == week.lisbon_today() == date(2026, 10, 7)
    # Carteira e ocorrências usam o mesmo dia por omissão (as chaves das caches batem com a Carga).
    assert portfolio.lisbon_today is occurrences.lisbon_today is week.lisbon_today
    assert "lisbon_today" in board.not_in_plans.__code__.co_names
