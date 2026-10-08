"""Quadro simples do plano e lista vermelha das OF por planear (02/10/2026). Sem base de dados."""
from datetime import date, timedelta

from app.sector import board

TODAY = date(2026, 10, 2)


def line(of, *, machine="", metres=10.0, pieces=5, due=None, priority=None, reference="R1", registered=date(2026, 9, 1), **signals):
    return {"of": of, "work": "OV" + of, "customer": "Cliente " + of, "designation": "= POSTES =_x000D_\n= 1 PRIORIDADE =",
            "family": "1 Postes", "registered": registered, "reference": reference, "machine": machine,
            "metres": metres, "pieces": pieces, "priority_day": due,
            "signals": {"prioridade": priority, "anulada": False, "eletrofer": False, "validacao": False, **signals}}


def data(*lines):
    return {"lines": list(lines), "today": TODAY, "imported_at": None}


def test_order_without_machine_is_red_and_planned_order_is_not():
    result = board.unplanned("cantoneiras", data=data(line("OF1"), line("OF2", machine="Peddi 8")), decisions={})
    assert [o["of"] for o in result["orders"]] == ["OF1"]
    assert result["planned_orders"] == 1
    assert result["orders"][0]["designation"] == "POSTES · 1 PRIORIDADE"
    assert result["orders"][0]["waiting_days"] == 31


def test_marking_with_planear_keeps_order_red_until_it_has_a_machine():
    decisions = {("OF1", "*"): {"decision": "selected"}}
    result = board.unplanned("cantoneiras", data=data(line("OF1")), decisions=decisions)
    assert result["orders"][0]["marked"] is True


def test_planear_is_offered_for_orders_whose_lines_all_lack_a_machine():
    # Desde 07/10/2026 o Planear dá a máquina sugerida às linhas sem máquina: também contam como por planear.
    result = board.unplanned("cantoneiras", data=data(line("OF1"), line("OF1", reference="R2")), decisions={})
    assert result["orders"][0]["plannable"] == 2
    marked = board.unplanned("cantoneiras", data=data(line("OF1"), line("OF1", reference="R2", machine="Peddi 8")),
                             decisions={("OF1", "*"): {"decision": "selected"}})
    assert marked["orders"][0]["marked"] and marked["orders"][0]["plannable"] == 1  # marcada, falta a máquina sugerida
    # «Subcontrato» na Tabela não recebe máquina sugerida: não conta, e a OF só com estas linhas não mostra Planear.
    sub = board.unplanned("cantoneiras", data=data({**line("OF1"), "tabela_machine": "Subcontrato"}), decisions={})
    assert sub["orders"][0]["plannable"] == 0


def test_excluded_lines_do_not_count_and_partial_orders_show_missing_part():
    decisions = {("OF1", "R2"): {"decision": "excluded"}}
    result = board.unplanned("cantoneiras", data=data(
        line("OF1", reference="R2"), line("OF3", machine="XP T4", reference="A"), line("OF3", reference="B", metres=4)), decisions=decisions)
    assert [o["of"] for o in result["orders"]] == ["OF3"]
    order = result["orders"][0]
    assert order["partial"] and order["lines"] == 1 and order["lines_total"] == 2 and order["metres"] == 4


def test_order_is_priority_then_deadline_then_size():
    result = board.unplanned("cantoneiras", data=data(
        line("OFA", due=date(2026, 9, 1)), line("OFB", due=date(2026, 8, 1)), line("OFC", priority=3, due=date(2026, 12, 1)),
        line("OFD", metres=99), line("OFE", metres=1)), decisions={})
    assert [o["of"] for o in result["orders"]] == ["OFC", "OFB", "OFA", "OFD", "OFE"]
    assert result["orders"][1]["late_days"] == 62


def test_order_numbers_compare_with_or_without_prefix():
    assert board._order_no("OF264095") == board._order_no("264095") == board._order_no("264095.0") == "264095"


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class _CpisConn:
    """Ligação falsa: duas cópias CPIS (perfis e cantoneiras) e as OF que já estão nos planos."""

    def __init__(self, cpis, planned=()):
        self.cpis, self.planned = cpis, planned

    def execute(self, sql, params=None):
        if "raw_generations" in sql:
            return _Rows([{"dataset": "planning:perfis", "id": 2, "snapshot": "p"},
                          {"dataset": "planning:cantoneiras", "id": 1, "snapshot": "c"}])
        if "plan_production_rows" in sql:
            return _Rows([{"of": of} for of in self.planned])
        return _Rows(self.cpis)


def cpis(of, status, *, recorded=date(2026, 9, 20), newer=False):
    from datetime import datetime
    loaded = datetime(2026, 10, 2, 12, 53 if newer else 51)
    return {"of": of, "customer_name": "Cliente", "work_type_description": "Postes", "record_date": datetime.combine(recorded, datetime.min.time()),
            "status": status, "delivery_date": None, "copy_loaded_at": loaded}


def test_not_in_plans_uses_the_newest_cpis_copy_and_treats_pronta_as_open():
    # Decisão de 06/10/2026 (substitui A3-2/C06 «basta uma Fechada»): manda a cópia carregada mais tarde.
    board._cache.clear()
    conn = _CpisConn([
        cpis("OF1", "Em Produção"), cpis("OF1", "Fechada", newer=True),   # a recente fecha: não aparece
        cpis("OF2", "Fechada"), cpis("OF2", "Em Produção", newer=True),   # a antiga fechada já não esconde
        cpis("OF3", "Pronta"),                                            # Pronta: aberta, como na população (A3-7)
        cpis("OF4", "Em Aberto"), cpis("OF4", "Pronta", newer=True),
        cpis("OF5", "Em Aberto"),                                         # já está num plano
        cpis("OF6", "Em Aberto", recorded=date(2026, 5, 1)),              # fora dos 3 meses
    ], planned=["OF5"])
    result = board.not_in_plans(today=TODAY, conn=conn)
    assert [r["of"] for r in result] == ["OF2", "OF3", "OF4"]
    assert [r["status"] for r in result] == ["Em Produção", "Pronta", "Pronta"]


def test_unknown_pieces_never_become_zero_in_the_red_list_or_the_boxes():
    """F09 (08/10): saldo por confirmar → peças None (e a contagem à parte), nunca 0 peças."""
    result = board.unplanned("cantoneiras", data=data(line("OF1", pieces=None), line("OF1", reference="R2", pieces=None)), decisions={})
    assert result["orders"][0]["pieces"] is None and result["orders"][0]["pieces_unknown"] == 2
    mixed = board.unplanned("cantoneiras", data=data(line("OF1", pieces=None), line("OF1", reference="R2", pieces=4)), decisions={})
    assert mixed["orders"][0]["pieces"] == 4 and mixed["orders"][0]["pieces_unknown"] == 1
    items = [{"resource_id": "m1", "of": "OF1", "start": TODAY, "end": TODAY, "pieces": None, "due": None, "approximate": False},
             {"resource_id": "m1", "of": "OF1", "start": TODAY, "end": TODAY, "pieces": 6, "due": None, "approximate": False},
             {"resource_id": "m2", "of": "OF2", "start": TODAY, "end": TODAY, "pieces": None, "due": None, "approximate": False}]
    boxes = board._merge(items)
    assert [(b["of"], b["pieces"], b["pieces_unknown"]) for b in boxes] == [("OF1", 6, 1), ("OF2", None, 1)]


def test_orders_with_machine_keeps_the_old_name_for_one_version():
    """F15 (08/10): «planned_orders» contava OF com máquina, não planeadas; o nome novo é «orders_with_machine»."""
    result = board.unplanned("cantoneiras", data=data(line("OF1"), line("OF2", machine="Peddi 8")), decisions={})
    assert result["orders_with_machine"] == result["planned_orders"] == 1


# --- Plano em uso (Etapa 3, 08/10): o quadro vem da previsão com capacidade finita

def test_board_comes_from_the_forecast_and_each_planned_line_is_on_its_portfolio_machine():
    from tests.test_sector_forecast_risk import _inputs, fact
    from app.sector import forecast
    facts = [fact("a", "L1", "OF1", "m1", 2.0), fact("b", "L2", "OF1", "m2", 1.0), fact("c", "L3", "OF2", "m1", 3.0),
             fact("d", "L4", "OF3", "m2", 1.5, basis="sugerida"), fact("s", "L1", "OF1", "m1", 1.0, phase="seguinte"),
             fact("x", "L5", "OF4", "elsewhere", 2.0), fact("n", "L6", "OF5", "m1", None)]
    ki, src = _inputs(facts, {"L1": None, "L2": None, "L4": None, "L5": None, "L6": None})
    fc = forecast.compute("cantoneiras", ki, src)
    boxes, missing, extra = board.boxes_from_forecast(fc, today=ki["today"], names={"m1": "M1", "m2": "M2"})
    placed = {(b["of"], b["resource_id"]): b for b in boxes}
    assert set(placed) == {("OF1", "m1"), ("OF1", "m2")}       # só as linhas Planeado (a sugerida não é Planeado)
    assert placed[("OF1", "m1")]["keys"] == ["a"] and placed[("OF1", "m2")]["keys"] == ["b"]
    box = placed[("OF1", "m1")]
    assert box["start_at"] == fc["origin"] and box["end_at"] == fc["origin"] + timedelta(hours=2)
    assert box["hours"] == 2.0
    assert box["conclusion"] == fc["orders"]["OF1"]["end"] and box["risk"] == fc["orders"]["OF1"]["state"]
    assert box["margin_days"] == fc["orders"]["OF1"]["margin_days"]
    assert [m["reasons"] for m in missing] == [["Sem horas"]] and missing[0]["of"] == "OF5"
    assert extra["second_operation"] == 1                      # a 2.ª operação da linha Planeado só se conta
    assert extra["elsewhere"]["operations"] == 1 and extra["elsewhere"]["machines"][0]["id"] == "elsewhere"
    for f in facts:  # cada linha Planeado colocada fica na máquina da Carteira (a efetiva)
        for b in boxes:
            if f["key"] in b["keys"]:
                assert b["resource_id"] == f["planning_resource_id"]


def test_partial_plan_shows_only_the_planned_part_in_the_box():
    from tests.test_sector_forecast_risk import _inputs, fact
    from app.sector import forecast
    ki, src = _inputs([fact("a", "L1", "OF1", "m1", 5.0, remaining=10)], {"L1": 4})
    fc = forecast.compute("cantoneiras", ki, src)
    [box] = board.boxes_from_forecast(fc, today=ki["today"])[0]
    assert box["keys"] == ["a"] and box["pieces"] == 4 and box["hours"] == 2.0


def test_box_is_late_when_the_forecast_ends_after_the_due_instant():
    from tests.test_sector_forecast_risk import _inputs, fact, lisbon
    from app.sector import forecast
    f = fact("a", "L1", "OF1", "m1", 10.0)
    f["priority"].update(priority_date=lisbon(2026, 10, 13, 8).isoformat(), priority_day="2026-10-13")
    ki, src = _inputs([f], {"L1": None})
    fc = forecast.compute("perfis", ki, src)
    [box] = board.boxes_from_forecast(fc, today=ki["today"])[0]
    assert box["late"] is True and box["risk"] == "atrasa"   # acaba terça 08:30, Picking terça 08:00


def test_build_uses_the_forecast_and_never_the_technical_gantt(monkeypatch):
    """O quadro deixa de chamar service.snapshot (16,6 s na MTG3): a fonte é «plano_em_uso»."""
    import sys
    from tests.test_sector_forecast_risk import _inputs, fact
    from app.sector import forecast
    ki, src = _inputs([fact("a", "L1", "OF1", "m1", 2.0)], {"L1": None})
    fc = forecast.compute("cantoneiras", ki, src)
    monkeypatch.setattr(forecast, "current", lambda sector, **kw: fc)
    monkeypatch.setattr(board.portfolio, "current", lambda sector, **kw: {"lines": [{"of": "OF1", "customer": "Cliente", "designation": "X"}],
                                                                         "imported_at": None, "today": ki["today"]})
    monkeypatch.setattr(board, "_machine_days", lambda ids, today: {})
    monkeypatch.setattr(board, "not_in_plans", lambda **kw: [])
    service = sys.modules.get("app.gantt.service")
    if service is not None:
        monkeypatch.setattr(service, "snapshot", lambda **kw: (_ for _ in ()).throw(AssertionError("snapshot chamado")))
    result, private = board._build("cantoneiras")
    assert result["source"]["kind"] == "plano_em_uso" and result["source"]["placed"] == 1
    assert result["source"]["origin"] == fc["origin"] and result["source"]["missing"] == []
    [machine] = [m for m in result["machines"] if m["boxes"]]
    assert machine["id"] == "m1" and machine["boxes"][0]["customer"] == "Cliente" and machine["boxes"][0]["keys"] == ["a"]
    assert private["timed"]["m1"] and {m["id"] for m in result["machines"]} == {"m1", "m2"}  # m2: com calendário, sem trabalho
