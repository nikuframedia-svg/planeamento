"""Parte 3 do plano de 07/10/2026: menos confirmações nas Definições, na Tabela e nas Capacidades.

- qualquer máquina do setor (catálogo: máquina/posto) tem calendários, taxas, horários no Gantt, histórico e
  horas reais, sem a caixa «confirmada»;
- horas reais corrigidas à mão: a conferência das folhas OCR faz-se ao gravar, substituir é o defeito e a
  origem por defeito é «Correção manual»;
- o ano da semana W das cantoneiras é deduzido (já não se confirma por importação);
- Tabela: um lote grava as linhas que não mudaram e devolve as outras, em vez de recusar tudo.

Base de dados só descartável (fixtures de tests/test_raw_workspace.py e tests/test_integrated_gantt.py).
"""
import copy
import uuid
from datetime import date, datetime, timedelta, timezone

import psycopg
import pytest
from app import planning
from app.gantt import research, integrated
from app.raw import capacity_revision as calc, objects, productivity, projection, query, edits
from app.sector import settings as sector_settings, shifts
from tests.test_integrated_gantt import integrated_db, package
from tests.test_raw_workspace import workspace
from tests.test_planning_raw import database, canonical, registry, postgres16

WORKDAYS = {str(d): (1 if d <= 5 else 0) for d in range(1, 8)}
CATALOG = [  # Prensa e Thomas: máquinas do setor que ninguém confirmou; Serrote MTG3 é um destino, não uma máquina
    {'codigo': 'PRENSA', 'designacao': 'Prensa', 'setor': 'MTG3', 'tipo': 'posto', 'quantidade_operadores': None},
    {'codigo': 'THOMAS', 'designacao': 'Thomas IS639', 'setor': 'MTG2', 'tipo': 'maquina', 'quantidade_operadores': None},
    {'codigo': 'SERRA_MTG3', 'designacao': 'Serrote MTG3', 'setor': 'MTG3', 'tipo': 'destino', 'quantidade_operadores': None},
]


def command(**kw):
    return {'request_id': str(uuid.uuid4()), **kw}


def calendar(rid, year=2026, week=43):
    return shifts.definition_for(rid, year, week, WORKDAYS, {}, sector_settings.default(date(year, 1, 1)), manual=False)


@pytest.fixture()
def sector_db(integrated_db):
    p = package()
    p['metadata']['resources'] = copy.deepcopy(CATALOG)
    p['metadata']['capacities'] = [{'id': 'prensa', 'recurso_codigo': 'PRENSA', 'operacao_codigo': 'CPIS:1034', 'processo_fisico': 'prensa',
                                    'perfil_minimo': None, 'perfil_maximo': None, 'fonte': 'ficha', 'apenas_cliente_nacional': False,
                                    'numero_diametros': None}]
    with planning.connect() as c:
        research.publish(c, p)  # regista os recursos do catálogo, todos com confirmed=False
    return integrated_db


def resource(code):
    with planning.connect(readonly=True) as c:
        row = c.execute("SELECT * FROM planning_mtg.raw_objects WHERE kind='resource' AND definition->>'research_code'=%s", (code,)).fetchone()
    assert row and not row['definition'].get('confirmed')
    return row


def test_gantt_windows_count_for_every_sector_machine_without_the_confirmed_flag():
    meta = {'resources': copy.deepcopy(CATALOG), 'aliases': [], 'relations': []}
    configs = [{'id': rid, 'kind': 'resource', 'revision': 1, 'definition': {'research_code': code, 'confirmed': False,
                'aliases': [{'area': 'cantoneiras', 'name': name}], 'operations': []}}
               for rid, code, name in (('p', 'PRENSA', 'Prensa'), ('s', 'SERRA_MTG3', 'Serrote MTG3'))]
    configs += [{'id': 'c-' + rid, 'kind': 'calendar', 'revision': 1, 'definition': calendar(rid)} for rid in ('p', 's')]
    start = datetime(2026, 10, 19, tzinfo=timezone.utc)
    _, by_id = integrated._resources(meta, configs, start, start + timedelta(days=7))
    assert by_id['p']['confirmed'] and by_id['p']['windows'] and by_id['p']['calendar_status'] == 'available'
    assert not by_id['s']['confirmed'] and not by_id['s']['windows']


def test_calendar_and_rate_save_on_an_unconfirmed_sector_machine(sector_db, monkeypatch):
    prensa, serra = resource('PRENSA'), resource('SERRA_MTG3')
    objects.save(command(name='Prensa · 2026-W43', area='cantoneiras', definition=calendar(str(prensa['id']))), 'calendar')
    objects.save(command(name='Prensa · 1034', area='cantoneiras', definition={
        'resource_id': str(prensa['id']), 'area': 'cantoneiras', 'operation': '1034', 'method': 'metres_hour', 'value': 50,
        'valid_from': '2026-01-01', 'confirmed': True, 'source': 'Confirmada'}), 'rate')
    # Um destino (não é máquina nem posto) continua a precisar da confirmação antiga.
    with pytest.raises(planning.PlanningError, match='Confirma primeiro'):
        objects.save(command(name='Serrote MTG3 · 2026-W43', area='cantoneiras', definition=calendar(str(serra['id']))), 'calendar')
    # Sem o catálogo (como no MES) só conta a confirmação manual.
    monkeypatch.setenv('MES_PLANNING_V2_ENABLED', '0')
    with pytest.raises(planning.PlanningError, match='Confirma primeiro'):
        objects.save(command(name='Prensa · 2026-W44', area='cantoneiras', definition=calendar(str(prensa['id']), week=44)), 'calendar')


def test_engine_uses_rates_of_sector_machines_and_keeps_hours_without_their_operation_list(sector_db):
    thomas = resource('THOMAS')  # catálogo sem operações: a lista vazia não pode apagar as horas
    objects.save(command(name='Thomas · corte', area='perfis', definition={
        'resource_id': str(thomas['id']), 'area': 'perfis', 'operation': 'corte', 'method': 'area_hour', 'value': 1000,
        'valid_from': '2026-01-01', 'confirmed': True, 'source': 'Confirmada'}), 'rate')
    with planning.connect(readonly=True) as c:
        configs = c.execute("SELECT * FROM planning_mtg.raw_objects WHERE kind IN ('resource','calendar','rate','period','worked_hours') AND NOT archived").fetchall()
        context = productivity.Context(c, configs, timing={}, recent_excel={})
    assert str(thomas['id']) in context.resources and ('perfis', 'Thomas IS639') in context.aliases
    values = {'machine': 'Thomas IS639', 'quantity_to_plan': 10, 'section_unit': 200}
    table = context.estimate(values, 'perfis', 'corte', '2026-10-07', as_of=date(2026, 10, 7))
    assert table['source'] == 'Manual' and table['hours'] == pytest.approx(2.0)
    excel = context.estimate(values, 'perfis', 'abocardar', '2026-10-07', excel={'method': 'units_hour', 'value': 5, 'unit': 'un./h'},
                             as_of=date(2026, 10, 7))
    assert excel['hours'] == pytest.approx(2.0) and excel['reason'] is None


def test_worked_hours_are_checked_when_saved_with_replace_and_origin_by_default(sector_db):
    prensa = resource('PRENSA')
    with planning.connect() as c:
        projection.publish(c, 'production_hours:cantoneiras', 'hours-ocr', [{
            'key': 'sheet', 'sheet_uid': 'sheet',
            'values': {'machine': 'Prensa', 'production_date': '2026-09-23', 'hours_worked': 2, 'sheet': 1}}], {})
    d = {'resource_id': str(prensa['id']), 'mode': 'period', 'start_date': '2026-09-23', 'end_date': '2026-09-23', 'hours': 5, 'confirmed': True}
    # A conferência continua a valer: uma base antiga é recusada e recusar a substituição também.
    with pytest.raises(planning.PlanningError, match='Revê'):
        objects.save(command(name='Prensa · horas', area='cantoneiras', definition={**d, 'basis_hash': 'antiga'}), 'worked_hours')
    with pytest.raises(planning.PlanningError, match='substituição'):
        objects.save(command(name='Prensa · horas', area='cantoneiras', definition={**d, 'replace_ocr': False}), 'worked_hours')
    saved = objects.save(command(name='Prensa · horas', area='cantoneiras', definition=d), 'worked_hours')['definition']
    assert saved['replace_ocr'] is True and saved['source'] == 'Correção manual'
    assert saved['replaces'] == ['cantoneiras:sheet'] and saved['basis_hash']
    with planning.connect(readonly=True) as c:
        configs = c.execute("SELECT * FROM planning_mtg.raw_objects WHERE kind IN ('resource','worked_hours') AND NOT archived").fetchall()
        cohorts = productivity.Context(c, configs, timing={}, recent_excel={}).cohorts('cantoneiras', 'Prensa')[1]
    assert [(x['origin'], x['hours']) for x in cohorts] == [('Manual', 5)]


def test_settings_seed_counts_unconfirmed_machines_with_a_stored_resource():
    machines = [{'id': 't', 'name': 'Thomas IS639', 'code': 'THOMAS', 'confirmed': False, 'has_object': True, 'rate_operations_codes': ['corte']},
                {'id': 'm', 'name': 'Maqfort', 'code': 'MAQFORT', 'confirmed': False, 'has_object': False, 'rate_operations_codes': ['corte']}]
    seed = sector_settings.excel_seed('perfis', machines, None, {'THOMAS': 1000, 'MAQFORT': 900})
    assert [x['maquina'] for x in seed] == ['t']


def test_mtg3_week_year_is_deduced_without_a_confirmation_per_import():
    stale = [{'area': 'cantoneiras', 'definition': {'snapshot': 's', 'week': 39, 'year': 2025}}]
    assert calc.period({'imported_week': 39}, 'cantoneiras', 's', stale, today=date(2026, 10, 7)) == (2026, 39, 'Semana W importada — ano deduzido')
    assert calc.period({'imported_week': 1}, 'cantoneiras', 'novo', [], today=date(2026, 12, 20))[:2] == (2027, 1)
    assert calc.period({'imported_week': 52}, 'cantoneiras', 'novo', [], today=date(2027, 1, 4))[:2] == (2026, 52)
    # Puxado para o passado: uma linha aberta em fim de novembro com W21 está atrasada (deste ano), não é do ano que vem.
    assert calc.period({'imported_week': 21}, 'cantoneiras', 'novo', [], today=date(2026, 11, 25))[:2] == (2026, 21)
    assert calc.period({'imported_week': 50}, 'cantoneiras', 'novo', [], today=date(2026, 10, 7))[:2] == (2026, 50)
    from app import planning_dates  # o Picking continua com o ano mais perto (sem viés)
    assert planning_dates.infer_iso_year(21, date(2026, 11, 25)) == 2027
    assert planning_dates.infer_iso_year(21, date(2026, 11, 25), prefer_past=True) == 2026
    # A Data Corte continua à frente da semana W; sem semana nem data fica por calendarizar.
    assert calc.period({'imported_week': 39, 'cut_date': '2026-10-07'}, 'cantoneiras', 's', [], today=date(2026, 10, 7))[:2] == (2026, 41)
    assert calc.period({}, 'cantoneiras', 's', [], today=date(2026, 10, 7))[:2] == (None, None)


def test_week_year_confirmations_are_no_longer_saved_but_old_ones_can_be_archived(workspace):
    from psycopg.types.json import Jsonb
    with pytest.raises(planning.PlanningError, match='deduzido'):
        objects.save(command(area='cantoneiras', name='W39', definition={'snapshot': 'c1', 'week': 39, 'year': 2026, 'reason': 'Ensaio'}), 'period')
    old = {'snapshot': 'c0', 'week': 39, 'year': 2026, 'reason': 'Confirmação antiga', 'confirmed': True}
    ident = str(uuid.uuid4())
    with psycopg.connect(workspace) as c:
        c.execute("INSERT INTO planning_mtg.raw_objects(id,kind,name,area,definition,actor) VALUES(%s,'period','W39 antiga','cantoneiras',%s,'ensaio')", (ident, Jsonb(old)))
    archived = objects.save(command(id=ident, expected_revision=1, area='cantoneiras', name='W39 antiga', archived=True, definition={}), 'period')
    assert archived['revision'] == 2 and archived['definition'] == old
    assert objects.get(ident)['archived'] is True


def row(key):
    """Linha atual da Tabela pela chave colada (uma linha do Excel passa a ter a chave da peça quando se grava)."""
    found = query.listing({'selected': [key]})['rows']
    assert len(found) == 1
    return found[0]


def test_table_batch_saves_unchanged_rows_after_an_import_and_reports_the_changed_one(workspace):
    projection.rebuild('perfis')
    data = query.listing({})
    first, second = data['rows'][:2]
    # Outra gravação publica uma versão nova: antes o lote seguinte, feito sobre a lista antiga, dava 409 «Existem dados novos».
    edits.update_batch(command(area='perfis', version=data['version'], edits=[{'key': first['key'], 'expected_revision': first['revision'], 'values': {'notes': 'Antes'}}]))
    current = row(first['key'])
    assert current['revision'] != first['revision'] and current['values']['notes'] == 'Antes'
    with planning.connect(readonly=True) as c:
        assert query.generation(c, 'perfis')['id'] != int(data['version'])
    stale = [{'key': first['key'], 'expected_revision': current['revision'], 'values': {'notes': 'Grava'}},
             {'key': second['key'], 'expected_revision': second['revision'] + 7, 'values': {'notes': 'Mudou'}}]
    # Sem `partial` (ecrãs antigos, que não leem `skipped`) fica o tudo-ou-nada de sempre.
    with pytest.raises(planning.PlanningError, match='Existem dados novos'):
        edits.update_batch(command(area='perfis', version=data['version'], edits=stale))
    result = edits.update_batch(command(area='perfis', version=data['version'], partial=True, edits=stale))
    assert len(result['items']) == 1
    assert [(x['key'], x['of'], x['reason']) for x in result['skipped']] == [(second['key'], second['values']['of'], 'A linha mudou entretanto.')]
    assert row(first['key'])['values']['notes'] == 'Grava' and row(second['key'])['values'].get('notes') != 'Mudou'
    # A revisão de cada linha continua a contar; sem nenhuma linha para gravar o pedido é recusado, como antes.
    with pytest.raises(planning.PlanningError, match='Nenhuma linha gravada: A linha mudou entretanto') as refused:
        edits.update_batch(command(area='perfis', version=data['version'], partial=True, edits=[
            {'key': first['key'], 'expected_revision': first['revision'], 'values': {'notes': 'Antiga'}}]))
    assert refused.value.status == 409 and row(first['key'])['values']['notes'] == 'Grava'


def test_table_partial_batch_skips_a_row_whose_excel_changed_with_the_same_revision(workspace):
    projection.rebuild('perfis')
    data = query.listing({})
    first, second = data['rows'][:2]
    # Nova importação: o Excel muda na segunda linha; a revisão local (0, só Excel) não sobe.
    with psycopg.connect(workspace) as c:
        c.execute("UPDATE raw_mtg.plan_production_rows SET length_mm=length_mm+100 WHERE source_line_id=%s", (second['plan_key'],))
    projection.rebuild('perfis', force=True)
    assert row(second['key'])['revision'] == second['revision'] and row(second['key'])['values']['length_mm'] == second['values']['length_mm'] + 100
    result = edits.update_batch(command(area='perfis', version=data['version'], partial=True, edits=[
        {'key': first['key'], 'expected_revision': first['revision'], 'values': {'notes': 'Grava'}},
        {'key': second['key'], 'expected_revision': second['revision'], 'values': {'notes': 'Sobre o Excel antigo'}}]))
    assert len(result['items']) == 1
    assert [(x['key'], x['reason']) for x in result['skipped']] == [(second['key'], 'O Excel mudou nesta linha.')]
    assert row(first['key'])['values']['notes'] == 'Grava' and row(second['key'])['values'].get('notes') != 'Sobre o Excel antigo'
    # Uma versão que já não existe não se pode comparar: a linha fica de fora pelo mesmo motivo.
    with pytest.raises(planning.PlanningError, match='O Excel mudou nesta linha'):
        edits.update_batch(command(area='perfis', version='999999', partial=True, edits=[
            {'key': second['key'], 'expected_revision': second['revision'], 'values': {'notes': 'Versão perdida'}}]))


def test_capacity_engine_counts_an_unconfirmed_sector_machine_end_to_end(sector_db):
    prensa = resource('PRENSA')
    objects.save(command(name='Prensa · 2026-W43', area='cantoneiras', definition=calendar(str(prensa['id']))), 'calendar')
    for area in planning.AREAS:
        projection.rebuild(area)
    calc.rebuild()
    machines = {r['key']: r for r in query.listing({'dataset': 'capacity_machines', 'area': 'cantoneiras', 'population': 'all'})['rows']}
    assert machines[str(prensa['id'])]['physical_status'] == 'Recurso físico confirmado'
    week = next(r for r in query.listing({'dataset': 'capacity', 'area': 'cantoneiras', 'population': 'all', 'page_size': 500})['rows']
                if r['values']['machine_key'] == str(prensa['id']) and (r['values']['year'], r['values']['week']) == (2026, 43))
    assert week['source_calendar']['confirmed'] is True and week['values']['available_hours'] > 0
    assert 'Disponibilidade por confirmar.' not in week['warnings']
    # O contrato da capacidade conta as máquinas do catálogo: um catálogo diferente obriga a um cálculo completo.
    with planning.connect(readonly=True) as c:
        meta = query.generation(c, 'cantoneiras', dataset='capacity')['metadata']
    assert meta['contract'] != calc.CONTRACT and meta['contract'].startswith(calc.CONTRACT + '|')
