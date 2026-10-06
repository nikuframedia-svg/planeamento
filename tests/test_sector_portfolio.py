"""Carteira (app/sector): pure rules with synthetic rows, and the HTTP guard. No database."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.sector import portfolio

TODAY = date(2026, 9, 28)  # segunda-feira; fim da semana ISO +2 = domingo 18/10


def raw(of, ref, quantity, length, *, made=0, mes=None, machine="", cut="2026-09-20", status="Em Produção",
        designation="", notes="", family=("1", "Postes Treliçados"), key=None):
    return {"row_key": key or f"macro:s:plan:{of}:{ref}", "notes": notes, "p_value": "12", "observations": None,
            "galvanising_notes": None, "work_type_code": family[0] if family else None,
            "work_type_description": family[1] if family else None, "record_date": "2026-06-12",
            "v": {"of": of, "ov": "OV1", "customer": "PAINHAS, SA", "designation": designation, "component_ref": ref,
                  "profile": "L45X45X5", "length_mm": length, "quantity_required": quantity, "made": made,
                  "ocr_quantity": mes, "machine": machine, "imported_week": 40, "cut_date": cut,
                  "delivery_date": "2026-10-01T00:00:00", "status": status}}


def data(*rows):
    lines = [x for x in (portfolio.line_from_row(r, TODAY) for r in rows) if x]
    return {"sector": "cantoneiras", "generation": 1, "snapshot": "s", "imported_at": "2026-09-28T12:19:54+00:00",
            "today": TODAY, "lines": lines}


@pytest.mark.parametrize("cut,expected", [
    (None, "sem_data"), (date(2026, 9, 27), "atrasado"), (date(2026, 9, 28), "3_semanas"),
    (date(2026, 10, 18), "3_semanas"), (date(2026, 10, 19), "mais_tarde"),
])
def test_deadline_windows_count_from_today_to_end_of_iso_week_plus_two(cut, expected):
    assert portfolio.window_of(cut, TODAY) == expected


def test_occurrence_detail_carries_every_cpis_status_to_the_signals():
    # occurrences.py passa detail["status_values"] a signals_of; sem isto no _DETAIL chegava sempre None (auditoria A8-3).
    from app.sector import occurrences
    assert "'status_values',coalesce(c.detail->'status_values'" in occurrences._DETAIL


def test_signals_read_the_written_text():
    s = portfolio.signals_of("= POSTES YDT = 1 PRIORIDADE = ENTREGA W48/2026", "Anulada 28-01-2026",
                             "FAB. APÓS VALIDAÇÃO DO EP2633", "fabricado na Electrofer", "Em Produção")
    assert s == {"prioridade": 1, "anulada": True, "eletrofer": True, "validacao": True, "estado_cpis": False,
                 "entrega_escrita": "W48/2026"}
    # «Pronta» não fecha a OF na população, por isso também não fica «por confirmar» na Carteira (A3-7).
    assert portfolio.signals_of("", "", "", "", "Pronta")["estado_cpis"] is False
    assert portfolio.signals_of("", "", "", "", None)["estado_cpis"] is True
    # Gerações gravadas antes de 06/10/2026, sem estado único: só abertas nas duas é que contam como abertas (A8-3).
    # As novas já trazem o estado da cópia CPIS mais recente (ver tests/test_cpis_latest_copy.py).
    assert portfolio.signals_of("", "", "", "", None, ["Em Aberto", "Em Produção"])["estado_cpis"] is False
    assert portfolio.signals_of("", "", "", "", None, ["Fechada", "Em Produção"])["estado_cpis"] is True
    assert portfolio.signals_of("", "", "", "", None, ["Estranho", "Em Produção"])["estado_cpis"] is True


def test_open_conflict_between_cpis_copies_stays_in_the_proposal_and_says_conflict():
    r = raw("OF1", "DLT319", 24, 1500, status=None, cut="2026-10-10")
    r["detail"] = {"status_values": ["Em Aberto", "Em Produção"]}
    line = portfolio.line_from_row(r, TODAY)
    assert line["status"] == "Estado em conflito" and line["proposal"] == "C"
    r["detail"] = {"status_values": ["Fechada", "Em Produção"]}
    assert portfolio.line_from_row(r, TODAY)["proposal"] is None


def test_unreconciled_excel_and_mes_counters_leave_an_unknown_balance():
    line = portfolio.line_from_row(raw("OF1", "DLT319", 24, 1500, made=4, mes=10), TODAY)
    assert line["pieces"] is None and line['balance_unknown'] and line["master"] == "DLT"
    assert portfolio.line_from_row(raw("OF1", "DLT319", 24, 1500, mes=24), TODAY)['pieces'] is None
    assert portfolio.line_from_row(raw("OF1", "DLT319", 24, 1500, made=24), TODAY) is None
    assert portfolio.line_from_row(raw("OF1", "DLT319", None, 1500), TODAY) is None
    r=raw('OF1','DLT319',24,1500,made=4,mes=10)
    r['v'].update(planning_remaining=14,planning_balance_origin='Reconciliado')
    assert portfolio.line_from_row(r,TODAY)['pieces']==14


def test_default_view_goes_model_then_sku_then_of_with_priority_first():
    d = data(raw("OF1", "DLT319", 10, 1000, machine="Peddi 8"),
             raw("OF2", "DLT319", 10, 1000),
             raw("OF3", "DLR9312D", 10, 3000, cut="2026-10-30"),
             raw("OF4", "ED4T40", 5, 1000, designation="POSTES CWR 3 PRIORIDADE", cut="2026-10-10"))
    top = portfolio.groups("cantoneiras", "referencia", data=d)
    assert [g["key"] for g in top["groups"]] == ["ED4", "DLT", "DLR"]
    assert top["totals"]["metres"] == pytest.approx(55.0) and top["totals"]["metres_without_machine"] == pytest.approx(45.0)
    skus = portfolio.groups("cantoneiras", "referencia", ["DLT"], data=d)
    assert [g["key"] for g in skus["groups"]] == ["DLT319"] and skus["has_children"]
    ofs = portfolio.groups("cantoneiras", "referencia", ["DLT", "DLT319"], data=d)
    assert sorted(g["key"] for g in ofs["groups"]) == ["OF1", "OF2"] and not ofs["has_children"]
    with pytest.raises(portfolio.planning.PlanningError):
        portfolio.groups("cantoneiras", "referencia", ["DLT", "DLT319", "OF1"], data=d)


def test_filters_family_machine_window_signal_and_search():
    d = data(raw("OF1", "DLT319", 10, 1000, machine="Peddi 8"),
             raw("OF2", "DLR1", 10, 1000, family=None, status=None),
             raw("OF3", "ED4T40", 10, 1000, notes="ANULADA", cut=None))
    names = lambda f: sorted(g["key"] for g in portfolio.groups("cantoneiras", "of", filters=f, data=d)["groups"])
    assert names({"maquina": "sem"}) == ["OV1"]
    assert portfolio.groups("cantoneiras", "cliente", filters={"familia": "1"}, data=d)["totals"]["ofs"] == 2
    assert portfolio.groups("cantoneiras", "referencia", filters={"janela": "sem_data"}, data=d)["totals"]["ofs"] == 1
    assert portfolio.groups("cantoneiras", "referencia", filters={"sinal": "anulada"}, data=d)["groups"][0]["key"] == "ED4"
    assert portfolio.groups("cantoneiras", "referencia", filters={"sinal": "estado_cpis"}, data=d)["totals"]["ofs"] == 1
    assert portfolio.groups("cantoneiras", "referencia", filters={"q": "dlr"}, data=d)["totals"]["ofs"] == 1


def test_both_sectors_share_the_portfolio_policy():
    assert portfolio.check_sector('perfis')=='perfis'
    assert portfolio.check_sector('cantoneiras')=='cantoneiras'


def test_finishing_primary_keeps_the_following_operation_selectable():
    r=raw('OF1','PART',10,1000,made=10)
    r['v']['planning_remaining']=0
    r['detail']={'calculation':{'integrated_operations':[{'operation':'CPIS:111','occurrence':2,'remaining':None}]}}
    line=portfolio.line_from_row(r,TODAY)
    assert line['pieces']==0 and line['pending_following_operations']==1
    result=portfolio.groups('cantoneiras','of',data=data(r),decisions={('OF1','*'):{'decision':'selected'}})
    assert result['totals']['state_counts']['selecionado']==1


@pytest.fixture()
def client(monkeypatch):
    from app.web.planning_app import app
    from app.sector import selection
    monkeypatch.setattr(portfolio, "load", lambda sector, **kw: data(raw("OF1", "DLT319", 10, 1000)))
    from app.sector import machine_choice
    monkeypatch.setattr(machine_choice, "context", lambda area, conn=None: machine_choice.empty(area))
    monkeypatch.setattr(selection, "current", lambda sector, conn=None: {})
    return TestClient(app)


def test_pages_are_hidden_while_the_switch_is_off(client, monkeypatch):
    monkeypatch.delenv("MES_PLANNING_SELECTION_ENABLED", raising=False)
    assert client.get("/planeamento/carteira").status_code == 404
    assert client.get("/planeamento/api/carteira").status_code == 404


def test_pages_work_with_the_switch_on(client, monkeypatch):
    monkeypatch.setenv("MES_PLANNING_SELECTION_ENABLED", "1")
    page = client.get("/planeamento/carteira")
    assert page.status_code == 200 and "Carteira" in page.text and "MTG3 Cantoneiras" in page.text
    body = client.get("/planeamento/api/carteira", params={"vista": "referencia"}).json()
    assert body["groups"][0]["key"] == "DLT" and body["level"]["id"] == "master"
    child = client.get("/planeamento/api/carteira", params=[("vista", "referencia"), ("caminho", "DLT")]).json()
    assert child["groups"][0]["key"] == "DLT319"
    assert client.get("/planeamento/api/carteira", params={"vista": "x"}).status_code == 422
    assert client.get("/planeamento/api/carteira/opcoes").json()["families"] == [{"code": "1", "label": "1 Postes Treliçados"}]


def test_week_2026_53_text_marks_parked_lines_out_of_late_and_weekly_load():
    # Auditoria 06/10 (S53-1): «2026/53» escrito à mão na coluna W marca linhas estacionadas no Excel.
    from app.sector import priority
    parked = raw("OF9", "ZD-1", 10, 1000, cut="2026-03-02", key="macro:s:plan:p")
    parked["detail"] = {"raw": {"W": "2026/53"}}
    undated = raw("OF9", "ZD-2", 10, 1000, cut=None, key="macro:s:plan:u")
    undated["detail"] = {"raw": {"W": "2026/53"}}
    normal = raw("OF8", "ZD-3", 10, 1000, cut="2026-09-20", key="macro:s:plan:n")
    normal["detail"] = {"raw": {"W": 41}}
    d = data(parked, undated, normal)
    lines = {x["key"]: x for x in d["lines"]}
    for key in ("macro:s:plan:p", "macro:s:plan:u"):
        x = lines[key]
        assert x["window"] == "estacionada" and x["parked"] and x["priority_day"] is None and x["proposal"] is None
        assert "Estacionada no Excel" in x["priority_source"]
    assert lines["macro:s:plan:n"]["window"] == "atrasado" and not lines["macro:s:plan:n"]["parked"]
    weeks = {w["code"]: w["lines"] for w in portfolio.weeks("cantoneiras", data=d)}
    assert weeks == {"2026-W38": 1, "estacionada": 2}
    assert [x["key"] for x in d["lines"] if portfolio.matches(x, {"semanas": ["sem"]})] == []
    assert len([x for x in d["lines"] if portfolio.matches(x, {"semanas": ["estacionada"]})]) == 2
    # A Carga classifica pela data: sem prazo, nunca atrasado da semana atual.
    marks = priority.milestones_from_values({"cut_date": "2026-03-02"}, {"W": "2026/53"})
    due = priority.resolve("cantoneiras", "principal", marks)
    assert due["priority_day"] is None and due["parked"] and priority.window(due, TODAY) == "estacionada"
    # Só na MTG3, e só o marcador: a semana numérica e os perfis seguem a regra normal.
    assert priority.resolve("perfis", "principal", priority.milestones_from_values({"cut_date": "2026-03-02"}, {"W": "2026/53"}))["priority_day"] == "2026-03-02"
    assert priority.resolve("cantoneiras", "principal", priority.milestones_from_values({"cut_date": "2026-03-02"}, {"W": 53}))["priority_day"] == "2026-03-02"
