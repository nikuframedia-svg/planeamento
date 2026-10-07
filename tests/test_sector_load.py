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
    monkeypatch.setattr(portfolio, "current", lambda sector: {"lines": lines})
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


def _overview_with_calendar(monkeypatch, facts, shifts_per_day=2):
    """overview() com uma máquina «m1» com calendário em todas as semanas (turnos seg–sex) e os factos dados."""
    from app.sector import load_sources, shifts
    settings = sector_settings.default(TODAY)
    machines = [{"id": "m1", "name": "Peddi 8", "code": "P8", "process": "Corte", "default_shifts": 2}]
    plan = {str(d): (shifts_per_day if d <= 5 else 0) for d in range(1, 8)}
    calendars = [{"definition": shifts.definition_for("m1", y, w, plan, {}, settings, manual=False)} for y, w in load.week_list(TODAY)]

    class Conn:
        def execute(self, sql, params=None):
            return _Rows(calendars if "kind='calendar'" in sql else [])

    @contextmanager
    def connect(readonly=True):
        yield Conn()

    monkeypatch.setattr(load.planning, "check_area", lambda sector: None)
    monkeypatch.setattr(load.planning, "connect", connect)
    monkeypatch.setattr(load, "_context", lambda sector, today=None: ({"lines": []}, set(), {"facts": facts}))
    monkeypatch.setattr(sector_settings, "read", lambda c, sector: settings)
    monkeypatch.setattr(sector_settings, "machine_rows", lambda c, sector: machines)
    monkeypatch.setattr(load_sources, "context", lambda c, sector: {"lines": {}, "actual": {}})
    monkeypatch.setattr(load_sources, "fact_values", lambda f, lines: (None, None, False))
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
    assert row["late_before"] == {"hours": 30.0, "unknown": 0, "operations": 1}
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
    assert current["advice"]["delta"] == 1 and current["advice"]["text"] == f"faltam {missing:.0f} h · +1 turno"
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
