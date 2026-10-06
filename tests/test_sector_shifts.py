"""Turnos, feriados, recomendação, horas por dia, ano do Picking e campos do registo por setor (06/10/2026).

Sem base de dados: só as regras puras.
"""
from datetime import datetime, timezone

from app import planning_catalogs, planning_dates
from app.sector import shifts, week

SETTINGS = {"template": shifts.DEFAULT_TEMPLATE, "workdays": [1, 2, 3, 4, 5], "holidays": []}
WEEKDAYS = lambda n: {str(d): (n if d <= 5 else 0) for d in range(1, 8)}  # noqa: E731


def definition(base, days=None, holidays=(), year=2026, week_no=42):
    return shifts.definition_for("r1", year, week_no, base, days or {}, {**SETTINGS, "holidays": list(holidays)}, manual=False)


def test_third_shift_crosses_midnight_into_the_next_day():
    weekly, overrides = shifts.build(WEEKDAYS(3), {}, [], shifts.DEFAULT_TEMPLATE, 2026, 42)
    assert weekly["1"] == [{"start": "06:00", "end": "13:30"}, {"start": "14:00", "end": "21:30"}, {"start": "22:00", "end": "24:00"}]
    assert weekly["2"][0] == {"start": "00:00", "end": "05:30"}
    assert weekly["6"] == [{"start": "00:00", "end": "05:30"}]  # sexta à noite acaba no sábado
    assert overrides == {}


def test_hours_per_day_for_one_two_and_three_shifts():
    assert shifts.shift_hours(shifts.DEFAULT_TEMPLATE) == [7.5, 7.5, 7.5]
    for n in (1, 2, 3):
        assert round(shifts.week_hours(definition(WEEKDAYS(n))), 2) == 37.5 * n


def test_encode_decode_round_trip_and_legacy_windows():
    d = definition(WEEKDAYS(2), {"2026-10-14": 3})
    assert shifts.decode(d) == (WEEKDAYS(2), {"2026-10-14": 3})
    legacy = {k: v for k, v in d.items() if k not in ("shift_plan", "day_shifts")}
    assert shifts.decode(legacy)[0] == WEEKDAYS(2)


def test_holiday_is_a_day_without_shifts_and_a_day_change_wins():
    holiday = definition(WEEKDAYS(2), holidays=["2026-10-12"])
    assert holiday["date_overrides"]["2026-10-12"] == []
    assert round(shifts.week_hours(holiday), 2) == 60.0
    worked = definition(WEEKDAYS(2), {"2026-10-12": 1}, holidays=["2026-10-12"])
    assert round(shifts.week_hours(worked), 2) == 67.5
    night = definition(WEEKDAYS(1), {"2026-10-16": 3})  # 3.º turno de sexta passa para sábado
    assert night["date_overrides"]["2026-10-17"] == [{"start": "00:00", "end": "05:30"}]


def test_national_holidays_include_moving_feasts():
    days = shifts.national_holidays(2026)
    assert {"2026-04-03", "2026-04-05", "2026-06-04", "2026-10-05", "2026-12-25"} <= set(days)
    assert shifts.easter(2027).isoformat() == "2027-03-28"


def test_advice_adds_removes_and_explains_the_limit():
    s = SETTINGS
    assert shifts.advise(93.0, 75.0, 2, s)["delta"] == 1
    assert shifts.advise(93.0, 75.0, 2, s)["text"].startswith("+1 turno · faltam 18 h")
    assert shifts.advise(30.0, 75.0, 2, s)["delta"] == -1
    assert shifts.advise(0.0, 37.5, 1, s)["delta"] == 0  # nunca abaixo de 1 turno
    full = shifts.advise(200.0, 112.5, 3, s)
    assert full["delta"] == 0 and "máximo de 3 turnos" in full["text"]
    short = shifts.advise(200.0, 75.0, 2, s)
    assert short["delta"] == 1 and short["still_missing"] == 87.5 and "ficam a faltar" in short["text"]
    assert shifts.advise(75.0, 75.0, 2, s)["text"] == "Certo"


def test_split_by_lisbon_days_across_the_dst_change():
    # 25/10/2026: o dia de Lisboa tem 25 horas. Das 22:00 de sábado (21:00 UTC) às 06:00 de domingo (07:00 UTC).
    start = datetime(2026, 10, 24, 21, 0, tzinfo=timezone.utc)
    end = datetime(2026, 10, 25, 7, 0, tzinfo=timezone.utc)
    assert week.split_interval(start, end) == {"2026-10-24": 2.0, "2026-10-25": 8.0}
    assert sum(week.split_segments("2026-10-24T21:00:00+00:00", [(0, 120), (120, 600)]).values()) == 10.0


def test_calendar_days_of_a_three_shift_machine():
    days = week.calendar_days([definition(WEEKDAYS(3))])
    assert days["2026-10-12"] == 17.0  # 6:00–13:30, 14:00–21:30, 22:00–24:00
    assert days["2026-10-13"] == 22.5  # mais 00:00–05:30 do turno da noite anterior
    assert days["2026-10-17"] == 5.5


def test_picking_year_is_the_nearest_to_the_reference_date():
    assert planning_dates.infer_iso_year(1, "2026-12-14") == 2027
    assert planning_dates.infer_iso_year(52, "2027-01-10") == 2026
    assert planning_dates.infer_iso_year(36, "2026-10-06") == 2026
    assert planning_dates.infer_iso_year(53, "2026-12-30") == 2026
    assert planning_dates.infer_iso_year(54, "2026-10-06") is None
    due = planning_dates.picking_deadline(1, anchor="2026-12-20")
    assert due["at"] == "2027-01-04T08:00:00+00:00" and due["provisional"] and due["origin"] == "Picking · ano deduzido"
    assert planning_dates.picking_deadline(1, 2026)["year"] == 2026


def test_first_section_follows_the_excel_columns_of_each_sector():
    def first(area):
        fields = planning_catalogs.arrange(planning_catalogs.fields(), area)
        return [f["id"] for f in sorted(fields, key=lambda f: f["order"]) if f["group"] == "piece" and f["editor_visible"]]
    perfis = first("perfis")
    assert perfis[:4] == ["component_ref", "cut_date", "material_type", "profile"]
    assert perfis[-3:] == ["abocardar", "picking_week", "picking_year"]
    cantoneiras = first("cantoneiras")
    assert cantoneiras[:2] == ["cut_date", "component_ref"]
    assert cantoneiras[-4:] == ["operation", "operation_detail", "team", "pavilion"]
    hidden = {f["id"] for f in planning_catalogs.arrange(planning_catalogs.fields(), "cantoneiras") if not f["editor_visible"]}
    assert {"abocardar", "picking_week", "picking_year"} <= hidden
    labels = {f["id"]: f["label"] for f in planning_catalogs.arrange(planning_catalogs.fields(), "cantoneiras")}
    assert labels["operation"] == "1.ª Operação" and labels["operation_detail"] == "2.ª Operação"


class _Conn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_store(monkeypatch, machines):
    """Calendários em memória; conta gravações e sinais de agregados."""
    from app.raw import objects
    from app.sector import settings as sector_settings
    store, saved, signals = {}, [], []
    monkeypatch.setattr(shifts, "calendar_row", lambda c, rid, y, w: store.get((rid, y, w)))
    def save(payload, kind, conn=None, *, signal=True):
        assert kind == "calendar" and signal is False
        d = payload["definition"]
        store[(d["resource_id"], d["year"], d["week"])] = {"id": len(saved) + 1, "revision": 1, "definition": d}
        saved.append(payload)
    monkeypatch.setattr(objects, "save", save)
    monkeypatch.setattr(shifts, "finish_batch", lambda c, rid: signals.append(rid))
    monkeypatch.setattr(sector_settings, "read", lambda c, s: dict(SETTINGS))
    monkeypatch.setattr(sector_settings, "machine_rows", lambda c, s: machines)
    monkeypatch.setattr(shifts.planning, "connect", lambda *a, **k: _Conn())
    return store, saved, signals


def test_batch_of_shift_changes_is_one_signal_and_day_change_survives_only_inside_its_week(monkeypatch):
    import uuid
    m = {"id": "r1", "name": "Peddi 8", "default_shifts": 1, "confirmed": True}
    store, saved, signals = _fake_store(monkeypatch, [m])
    request = str(uuid.uuid4())
    out = shifts.apply({"setor": "cantoneiras", "request_id": request, "mudancas": [
        {"maquina": "r1", "ano": 2026, "semana": 43, "turnos": 2},
        {"maquina": "r1", "dia": "2026-10-23", "turnos": 3},
        {"maquina": "r1", "ano": 2026, "semana": 44, "turnos": 3}]})
    assert out == {"changed": 2, "weeks": 2} and signals == [uuid.UUID(request)]
    w43 = store[("r1", 2026, 43)]["definition"]
    assert w43["manual"] and w43["shift_plan"]["1"] == 2 and w43["day_shifts"] == {"2026-10-23": 3}
    assert round(shifts.week_hours(w43), 2) == 4 * 15 + 22.5
    # A semana inteira manda: repor 2 turnos nessa semana apaga a exceção do dia.
    shifts.apply({"setor": "cantoneiras", "request_id": str(uuid.uuid4()), "mudancas": [{"maquina": "r1", "ano": 2026, "semana": 43, "turnos": 2}]})
    assert store[("r1", 2026, 43)]["definition"]["day_shifts"] == {}
    # Repetir o mesmo pedido não grava nada nem volta a sinalizar.
    before = (len(saved), len(signals))
    shifts.apply({"setor": "cantoneiras", "request_id": str(uuid.uuid4()), "mudancas": [{"maquina": "r1", "ano": 2026, "semana": 43, "turnos": 2}]})
    assert (len(saved), len(signals)) == before


def test_regenerate_skips_unconfirmed_machines_and_keeps_manual_weeks(monkeypatch):
    import uuid
    from app.sector import settings as sector_settings
    confirmed = {"id": "r1", "name": "Peddi 8", "default_shifts": 2, "confirmed": True}
    unconfirmed = {"id": "r2", "name": "Prensa", "default_shifts": 1, "confirmed": False}
    store, saved, _ = _fake_store(monkeypatch, [confirmed, unconfirmed])
    y, w = sector_settings._current_week()
    store[("r1", y, w)] = {"id": 99, "revision": 3, "definition": shifts.definition_for("r1", y, w, WEEKDAYS(3), {}, SETTINGS, manual=True)}
    changed = sector_settings.regenerate(None, "cantoneiras", {**SETTINGS, "holidays": ["2026-12-25"]}, uuid.uuid4())
    assert changed == sector_settings.HORIZON_WEEKS - 1  # a semana manual já estava certa
    assert all(k[0] == "r1" for k in store)
    assert store[("r1", y, w)]["definition"]["shift_plan"]["1"] == 3
    christmas = store[("r1", 2026, 52)]["definition"]
    assert christmas["date_overrides"]["2026-12-25"] == []
