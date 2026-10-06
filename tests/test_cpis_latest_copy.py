"""Duas cópias do CPIS em desacordo: manda a cópia mais recente.

Decisão do Luís de 06/10/2026, que substitui as regras de 20/09 («não se resolve escolhendo uma cópia»)
e de 23/09 (C06, «basta uma cópia dizer Fechada»): quando as duas cópias do CPIS que vêm nos Excel
discordam, vale a cópia cujo Excel foi carregado mais tarde, para todos os campos. O estado mostra-se
tal como vem, sem avisos de conflito. Em empate de carga, ganha a linha com a data de registo maior.
"""
from datetime import date, datetime, timezone

from app import planning_hub, planning_population
from app.sector import board, portfolio

OLD = datetime(2026, 10, 2, 12, 51, tzinfo=timezone.utc)
NEW = datetime(2026, 10, 2, 12, 53, tzinfo=timezone.utc)


def copy(area, loaded, status, *, finish=None, delivery=None, recorded=None, **extra):
    return {'production_order_no': 'OF4200', 'area': area, 'copy_loaded_at': loaded,
            'copy_record_date': recorded, 'status': status, 'planned_finish_date': finish,
            'delivery_date': delivery, 'customer_name': extra.get('customer', 'Cliente'),
            'responsible_dp': extra.get('responsible'), 'sales_order_no': 'OV21'}


def test_newest_copy_wins_status_and_dates_without_conflict():
    rows = [copy('cantoneiras', OLD, 'Fechada', finish=date(2026, 9, 1), delivery=date(2026, 9, 5), responsible='Ana'),
            copy('perfis', NEW, 'Em Produção', finish=date(2026, 10, 20), delivery=date(2026, 10, 30), responsible='Rui')]
    for order in (rows, rows[::-1]):
        s = planning_hub._order_summary(order)
        assert s['cpis_status'] == 'Em Produção' and s['status_values'] == ['Em Produção']
        assert s['planned_finish_date'] == date(2026, 10, 20) and s['delivery_date'] == date(2026, 10, 30)
        assert s['responsible_dp'] == 'Rui'
        assert s['conflicts'] == [] and s['cpis_latest_copy'] == 'perfis'
        # Uma «Fechada» na cópia antiga já não fecha a OF (substitui C06).
        assert planning_population.classify({'status_values': s['status_values']})['active'] is True


def test_newest_copy_closed_closes_and_empty_field_falls_back_to_older_copy():
    rows = [copy('cantoneiras', NEW, 'Fechada', delivery=None),
            copy('perfis', OLD, 'Em Produção', delivery=date(2026, 10, 30))]
    s = planning_hub._order_summary(rows)
    assert s['cpis_status'] == 'Fechada' and s['status_values'] == ['Fechada']
    assert planning_population.classify({'status_values': s['status_values']})['active'] is False
    # A cópia recente não traz entrega: fica a única data conhecida, sem conflito.
    assert s['delivery_date'] == date(2026, 10, 30)


def test_same_load_time_uses_greater_record_date():
    rows = [copy('perfis', NEW, 'Pronta', recorded=datetime(2026, 9, 30)),
            copy('cantoneiras', NEW, 'Em Aberto', recorded=datetime(2026, 10, 1))]
    assert planning_hub._order_summary(rows)['cpis_status'] == 'Em Aberto'


def test_not_in_plans_shows_the_newest_copy_status():
    board._cache.clear()

    class Rows(list):
        def fetchall(self):
            return self

    class Conn:
        def execute(self, sql, params=None):
            if 'raw_generations' in sql:
                return Rows([{'dataset': 'planning:perfis', 'id': 2, 'snapshot': 'p'},
                             {'dataset': 'planning:cantoneiras', 'id': 1, 'snapshot': 'c'}])
            if 'plan_production_rows' in sql:
                return Rows()
            day = datetime(2026, 9, 20)
            base = {'customer_name': 'Cliente', 'work_type_description': 'Postes', 'record_date': day, 'delivery_date': None}
            return Rows([{**base, 'of': 'OF1', 'status': 'Fechada', 'copy_loaded_at': OLD},
                         {**base, 'of': 'OF1', 'status': 'Em Produção', 'copy_loaded_at': NEW},
                         {**base, 'of': 'OF2', 'status': 'Em Aberto', 'copy_loaded_at': OLD},
                         {**base, 'of': 'OF2', 'status': 'Fechada', 'copy_loaded_at': NEW}])

    result = board.not_in_plans(today=date(2026, 10, 6), conn=Conn())
    assert [(r['of'], r['status']) for r in result] == [('OF1', 'Em Produção')]


def test_portfolio_signal_follows_the_resolved_status():
    assert portfolio.signals_of('', '', '', '', 'Em Produção', ['Em Produção'])['estado_cpis'] is False
    assert portfolio.signals_of('', '', '', '', 'Fechada', ['Fechada'])['estado_cpis'] is True
