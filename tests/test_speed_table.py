"""Tabela de velocidades das máquinas (plano de 06/10/2026, parte 3): uma só regra em todo o lado."""
from datetime import date, timedelta

import pytest

from app import planning
from app.raw import capacity, productivity as p
from app.sector import estimates, throughput
from app.gantt import integrated
from tests.test_raw_workspace import workspace, database, canonical, registry, postgres16  # noqa: F401

TODAY = date.today().isoformat()


def rate(ident, **d):
    base = {'resource_id': 'r1', 'area': 'cantoneiras', 'operation': '112', 'method': 'metres_hour', 'value': 100,
            'valid_from': '2026-01-01', 'confirmed': True, 'source': 'Confirmada'}
    return {'id': ident, 'definition': {**base, **d}}


TABLE = [rate('fino', thickness_min=0, thickness_max=6, value=120),
         rate('medio', thickness_min=6, thickness_max=10, value=100),
         rate('grosso', thickness_min=14, thickness_max=24, value=60)]


def choose(table, profile, **kw):
    return p.match_rate(table, 'r1', 'cantoneiras', kw.pop('operation', 'CPIS:112'), {'profile': profile, **kw})


def test_match_rate_inside_the_range_then_the_next_one_above():
    assert choose(TABLE, 'L50X50X5')['configuration']['id'] == 'fino'
    assert choose(TABLE, 'L80X80X8')['configuration']['id'] == 'medio'
    # Encostadas (0–6 e 6–10): no limite fica a de baixo.
    assert choose(TABLE, 'L60X60X6')['configuration']['id'] == 'fino'
    # 12 mm não está na tabela: usa a imediatamente superior (14–24).
    found = choose(TABLE, 'L120X120X12')
    assert found['configuration']['id'] == 'grosso' and found['basis'] == 'intervalo imediatamente superior'
    # Acima de tudo e sem linha geral: nenhuma (fica o histórico/Excel).
    assert choose(TABLE, 'L300X300X30') is None
    # Espessura desconhecida: só uma linha sem intervalo serve.
    assert choose(TABLE, 'Chapa') is None
    assert choose(TABLE + [rate('geral', operation='CPIS:119')], 'Chapa', operation='119')['configuration']['id'] == 'geral'


def test_match_rate_operation_formats_material_validity_and_tier():
    table = [rate('a', operation='CPIS:112', value=90)]
    assert choose(table, 'L50X50X5', operation='112')['rate']['value'] == 90
    assert choose(table, 'L50X50X5', operation={'CPIS:112', 'corte'})['rate']['value'] == 90
    assert choose(table, 'L50X50X5', operation='119') is None
    perfis = [{'id': 'g', 'definition': {**rate('g')['definition'], 'area': 'perfis', 'operation': 'LOCAL:PRINCIPAL', 'method': 'area_hour', 'value': 9000}},
              {'id': 'tubo', 'definition': {**rate('t')['definition'], 'area': 'perfis', 'operation': 'corte', 'method': 'area_hour',
                                             'value': 5000, 'material_type': 'Tubo redondo'}}]
    assert p.match_rate(perfis, 'r1', 'perfis', 'corte', {'material_type': 'Tubo  Redondo'})['configuration']['id'] == 'tubo'
    assert p.match_rate(perfis, 'r1', 'perfis', 'corte', {'material_type': 'Viga'})['configuration']['id'] == 'g'
    # Vigência pela data de hoje por defeito: uma taxa futura ainda não vale.
    future = [rate('f', valid_from=(date.today() + timedelta(days=3)).isoformat())]
    assert choose(future, 'L50X50X5') is None
    assert p.match_rate(future, 'r1', 'cantoneiras', '112', {}, (date.today() + timedelta(days=5)).isoformat())
    expired = [rate('e', valid_until='2026-01-31')]
    assert choose(expired, 'L50X50X5') is None
    seeded = [rate('s', source='Excel')]
    assert choose(seeded, 'L50X50X5')['configuration']['id'] == 's'
    assert p.match_rate(seeded, 'r1', 'cantoneiras', '112', {'profile': 'L50X50X5'}, tier='Confirmada') is None
    assert not choose([rate('x', confirmed=False)], 'L50X50X5')
    assert choose([rate('a', thickness_min=0, thickness_max=10), rate('b', thickness_min=0, thickness_max=10)], 'L50X50X5')['conflict'] == ['a', 'b']


def test_overlap_only_on_the_same_machine_operation_material_and_range():
    a = rate('a', thickness_min=0, thickness_max=6)['definition']
    assert capacity.rates_conflict(a, {**a, 'thickness_min': 5, 'thickness_max': 8})
    assert not capacity.rates_conflict(a, {**a, 'thickness_min': 6, 'thickness_max': 8})  # encostadas
    assert capacity.rates_conflict(a, {**a, 'thickness_min': 6, 'thickness_max': 6})  # um ponto no limite
    assert capacity.rates_conflict(a, {**a, 'thickness_min': None, 'thickness_max': None})  # linha geral cobre tudo
    assert capacity.rates_conflict(a, {**a, 'operation': 'CPIS:112', 'thickness_min': 2, 'thickness_max': 3})
    assert not capacity.rates_conflict(a, {**a, 'operation': '119'})
    assert not capacity.rates_conflict(a, {**a, 'resource_id': 'r2'})
    assert not capacity.rates_conflict(a, {**a, 'material_type': 'Galvanizado'})
    assert not capacity.rates_conflict(a, {**a, 'source': 'Excel'})  # a semente fica abaixo das confirmadas
    assert not capacity.rates_conflict(a, {**a, 'valid_from': '2025-01-01', 'valid_until': '2025-12-31'})


def test_rate_fields_are_validated():
    base = {'resource_id': 'r1', 'area': 'cantoneiras', 'operation': 'CPIS:112', 'method': 'metres_hour', 'value': '120',
            'valid_from': '2026-10-01', 'confirmed': True}
    clean = capacity.validate_rate_fields({**base, 'thickness_min': '8', 'thickness_max': '12,5', 'piece_seconds': '20', 'notes': ' x '})
    assert clean['operation'] == '112' and clean['thickness_max'] == 12.5 and clean['piece_seconds'] == 20 and clean['notes'] == 'x'
    assert clean['source'] == 'Confirmada'
    with pytest.raises(planning.PlanningError):
        capacity.validate_rate_fields({**base, 'thickness_min': 12, 'thickness_max': 8})
    with pytest.raises(planning.PlanningError):
        capacity.validate_rate_fields({**base, 'section_min': 100})  # área de secção é dos perfis
    with pytest.raises(planning.PlanningError):
        capacity.validate_rate_fields({**base, 'piece_seconds': -1})
    with pytest.raises(planning.PlanningError):
        capacity.validate_rate_fields({**base, 'source': 'Outra'})


def test_hours_add_piece_time_fixed_time_and_machine_efficiency_except_measured():
    # 08/10: a eficiência da máquina é o único fator sobre as horas (horas × 100 / eficiência); a margem do setor saiu.
    values = {'quantity_to_plan': 10, 'length_mm': 2000}
    plain = {'method': 'metres_hour', 'value': 100}
    assert capacity.estimate(values, plain, '112') == (0.2, None)
    with_piece = p.timed({**plain, 'piece_seconds': 36}, 'Manual', {'piece_minutes': 0, 'efficiency': {}}, 'r1')
    assert capacity.estimate(values, with_piece, '112')[0] == pytest.approx(0.2 + 10 * 36 / 3600)
    timing = {'piece_minutes': 1.5, 'efficiency': {'r1': 80}}
    full = p.timed({**plain, 'piece_seconds': 36}, 'Manual', timing, 'r1')
    assert full['piece_seconds'] == 36 + 90 and full['efficiency_pct'] == 80 and full['margin_pct'] == pytest.approx(25)
    assert capacity.estimate(values, full, '112')[0] == pytest.approx((0.2 + 10 * 126 / 3600) * 100 / 80)
    # Aplicar duas vezes não soma outra vez o tempo fixo nem o fator.
    again = p.timed(full, 'Manual', timing, 'r1')
    assert again['piece_seconds'] == 126 and capacity.estimate(values, again, '112')[0] == pytest.approx(capacity.estimate(values, full, '112')[0])
    # A eficiência é da máquina: outra máquina fica a 100 %.
    assert capacity.estimate(values, p.timed(plain, 'Manual', timing, 'r2'), '112')[0] == pytest.approx(0.2 + 10 * 90 / 3600)
    # Excel também leva eficiência e tempo fixo; o Histórico e uma taxa confirmada «medida» não (medem horas reais).
    half = {'piece_minutes': 2, 'efficiency': {'r1': 50}}
    assert capacity.estimate(values, p.timed(plain, 'Excel provisório', {**half, 'piece_minutes': 0}, 'r1'), '112')[0] == pytest.approx(0.4)
    assert p.timed(plain, 'Histórico', half, 'r1') is plain
    measured = {**plain, 'measured': True}
    assert p.timed(measured, 'Manual', half, 'r1') is measured
    # A margem antiga só chega como eficiência equivalente de todas as máquinas ('*', sector_timing).
    assert capacity.estimate(values, p.timed(plain, 'Manual', {'efficiency': {'*': 100 / 1.1}}, 'r9'), '112')[0] == pytest.approx(0.22)
    assert capacity.estimate({**values, 'quantity_to_plan': 0}, full, '112') == (0, None)
    rule = capacity.estimate_rule(values, {'rate': full, 'source': 'Manual', 'hours': 1})
    assert 'eficiência' in rule['formula'] and rule['inputs']['piece_seconds'] == 126 and rule['inputs']['efficiency_pct'] == 80
    # Sem nada disto, as contas e a fórmula ficam iguais às de antes.
    assert p.timed(plain, 'Manual', {'piece_minutes': 0, 'efficiency': {}}, 'r1') is plain
    assert p.timed(plain, 'Manual', {'piece_minutes': 0, 'efficiency': {'r1': 100}}, 'r1') is plain
    assert 'eficiência' not in capacity.estimate_rule(values, {'rate': plain, 'source': 'Manual', 'hours': 0.2})['formula']


def test_select_rate_order_confirmed_excel_table_excel_and_history_only_shown():
    # Decisão do Luís (08/10): Confirmada > Excel; o histórico já não ganha, fica como «medido».
    values = {'profile': 'L50X50X5'}
    args = dict(area='cantoneiras', operation='112', resource_id='r1', excel={'method': 'metres_hour', 'value': 80}, when='2026-08-01')
    history = {'value': 110, 'method': 'metres_hour'}
    seeded = [rate('s', source='Excel', value=120)]
    confirmed = [rate('c', value=150)]
    assert p.select_rate(values, manual=confirmed + seeded, historical_rate=history, **args)['source'] == 'Manual'
    chosen = p.select_rate(values, manual=seeded, historical_rate=history, **args)
    assert chosen['source'] == 'Excel provisório' and chosen['rate']['value'] == 120 and chosen['configuration']['id'] == 's'
    assert chosen['rate_alternatives']['historical']['value'] == 110
    assert p.select_rate(values, manual=seeded, historical_rate={'value': None}, **args)['rate']['value'] == 120
    plain = p.select_rate(values, manual=[], historical_rate=history, **args)
    assert plain['source'] == 'Excel provisório' and plain['rate']['value'] == 80
    assert p.select_rate(values, manual=[], historical_rate={'value': None}, **args)['rate']['value'] == 80
    # Sem Excel nem confirmada não há taxa, mesmo com histórico.
    none = p.select_rate(values, manual=[], historical_rate=history, **{**args, 'excel': None})
    assert none['source'] is None and none['rate'] is None and none['rate_alternatives']['historical']['value'] == 110
    # A vigência é a de rate_day (o motor passa hoje), não a data prevista (when) de uma linha atrasada.
    new = [rate('n', value=150, valid_from='2026-09-01')]
    assert p.select_rate(values, manual=new, historical_rate={'value': None}, rate_day='2026-10-06', **args)['source'] == 'Manual'
    assert p.select_rate(values, manual=new, historical_rate={'value': None}, **args)['source'] == 'Excel provisório'


def test_recent_excel_speed_wins_over_the_whole_history():
    rows = ([{'Máquina Corte': 'XP T4', 'Mt\\h': 80, 'Data Corte': f'2026-02-{d:02d}T00:00:00', 'Tipo de perfil': 'L50X50X5', '1ª Oper.': 112}
             for d in range(1, 28)] * 10
            + [{'Máquina Corte': 'XP T4', 'Mt\\h': 120, 'Data Corte': f'2026-09-{d:02d}', 'Tipo de perfil': 'L50X50X5', '1ª Oper.': 112}
               for d in range(1, 21)]
            + [{'Máquina Corte': 'XP T4', 'Mt\\h': 100, 'Data Corte': '2026-09-02', 'Tipo de perfil': 'L60X60X6', '1ª Oper.': 112}] * 3
            + [{'Máquina Corte': 'XP T4', 'Mt\\h': 60, 'Data Corte': '2027-01-10', 'Tipo de perfil': 'L50X50X5', '1ª Oper.': 112}]  # futura
            + [{'Máquina Corte': 'Peddi 6', 'Mt\\h': 50, 'Data Corte': '1900-01-13T00:00:00'}])  # data zero do Excel
    machine, profile, operation = throughput.recent_speeds(rows, until=date(2026, 10, 6))
    assert machine['XP T4']['value'] == 120 and machine['XP T4']['lines'] == 23
    assert profile[('XP T4', 'L60X60X6')]['value'] == 100 and operation[('XP T4', '112')]['value'] == 120
    assert 'Peddi 6' not in machine
    medians, by_profile = throughput.speeds(rows)
    assert medians['XP T4']['value'] == 80  # a mediana antiga ficava presa nos 80 m/h
    study = {'speeds': medians, 'profile_speeds': by_profile, 'recent_speeds': machine, 'recent_profile_speeds': profile}
    value, _, basis = estimates.speed_for(study, {'XP T4'}, 'L50X50X5')
    assert value == 120 and 'mais recente' in basis
    # A velocidade não depende do perfil: restos da transição (3 linhas a 100 num perfil) não contam.
    assert estimates.speed_for(study, {'XP T4'}, 'L60X60X6')[0] == 120
    assert estimates.speed_for(study, {'XP T4'}, 'L90X90X9')[0] == 120
    assert estimates.speed_for(study, {'Outra'}, 'L50X50X5') is None


def test_the_same_confirmed_rate_gives_the_same_hours_in_carteira_engine_and_gantt():
    timing = {'piece_minutes': 0.5, 'efficiency': {'rid': 100 / 1.1}}  # eficiência da máquina (08/10): × 1,1 nas horas
    table = [rate('c', resource_id='rid', operation='CPIS:112', value=90, thickness_min=6, thickness_max=10, piece_seconds=12)]
    # Carteira e Carga (estimates).
    fact = {'remaining': 10, 'phase': 'principal', 'area': 'cantoneiras', 'length_mm': 1000, 'profile': 'L80X80X8',
            'operation': 'CPIS:112', 'material_type': 'Sem tipo'}
    study = {'speeds': {}, 'profile_speeds': {}, 'recent_speeds': {'XP': {'value': 120, 'lines': 9}}, 'recent_profile_speeds': {}}
    carteira, why = estimates.estimate(fact, {'id': 'rid', 'code': 'XPT6', 'name': 'XP'}, {'XP'}, study, {}, table=table, timing=timing)
    assert 'taxa confirmada' in why
    # Motor de capacidade (select_rate + Context.estimate).
    chosen = p.select_rate({'profile': 'L80X80X8'}, area='cantoneiras', operation='112', resource_id='rid', manual=table,
                           historical_rate={'value': None}, excel={'method': 'metres_hour', 'value': 120}, when='2026-08-01', rate_day=TODAY)
    engine, _ = capacity.estimate({'quantity_to_plan': 10, 'length_mm': 1000}, p.timed(chosen['rate'], chosen['source'], timing, 'rid'), '112')
    # Gantt (_duration), sem a sua antiga filtragem própria.
    configs = [{'kind': 'rate', **table[0]}]
    r = {'setor': 'MTG3', 'ordem_codigo': 'OF1', 'referencia_original': 'P', 'item_id': 'i', 'operacao_id': 'o', 'linha_origem': 'l',
         'ocorrencia': 1, 'operacao_codigo': 'CPIS:112', 'fase': 'principal', 'perfil': 'L80X80X8', 'qualidade': None,
         'quantidade_base': 10, 'saldo_confirmado': None, 'saldo_documental': 10, 'estado_quantidade': 'coerente',
         'comprimento_mm': 1000, 'recurso_atual': None, 'raw': {}}
    found = integrated._duration(r, {'resource_code': 'XPT6', 'proposed_code': 'CPIS:112', 'eligibility': 'admissible'},
                                 {'id': 'rid', 'confirmed': False}, configs, {}, f'{TODAY}T08:00:00+00:00', timing=timing)
    expected = (10 * 1000 / 1000 / 90 + 10 * (12 + 30) / 3600) * 1.1
    assert carteira == pytest.approx(expected) and engine == pytest.approx(expected)
    assert found['duration_hours'] == pytest.approx(expected) and found['rate_source'] == 'Manual'
    # Linha com máquina sugerida e sem taxa: a velocidade mais recente do Excel, com a mesma margem.
    hours, why = estimates.estimate({**fact, 'profile': 'L200X200X20'}, {'id': 'rid', 'code': 'XPT6', 'name': 'XP'}, {'XP'}, study, {},
                                    table=table, timing=timing)
    assert hours == pytest.approx((10 / 120 + 10 * 30 / 3600) * 1.1) and 'mais recente' in why
    # Operação seguinte: só com linha na tabela.
    assert estimates.estimate({**fact, 'phase': 'seguinte'}, {'id': 'rid', 'name': 'XP'}, {'XP'}, study, {}, table=table)[0] == pytest.approx(10 / 90 + 10 * 12 / 3600)
    assert estimates.estimate({**fact, 'phase': 'seguinte', 'operation': 'CPIS:119'}, {'id': 'rid', 'name': 'XP'}, {'XP'}, study, {}, table=table)[0] is None


def test_gantt_refuses_overlapping_confirmed_rates_and_uses_seeded_rows_as_excel():
    r = {'setor': 'MTG3', 'ordem_codigo': 'OF1', 'referencia_original': 'P', 'item_id': 'i', 'operacao_id': 'o', 'linha_origem': 'l',
         'ocorrencia': 1, 'operacao_codigo': 'CPIS:112', 'fase': 'principal', 'perfil': 'L80X80X8', 'qualidade': None,
         'quantidade_base': 10, 'saldo_confirmado': None, 'saldo_documental': 10, 'estado_quantidade': 'coerente',
         'comprimento_mm': 1000, 'recurso_atual': None, 'raw': {}}
    candidate = {'resource_code': 'XPT6', 'proposed_code': 'CPIS:112', 'eligibility': 'admissible'}
    both = [{'kind': 'rate', **rate('a', resource_id='rid')}, {'kind': 'rate', **rate('b', resource_id='rid')}]
    assert integrated._duration(r, dict(candidate), {'id': 'rid', 'confirmed': False}, both, {}, f'{TODAY}T08:00:00+00:00') is None
    seeded = [{'kind': 'rate', **rate('s', resource_id='rid', source='Excel', value=120)}]
    templates = {('XPT6', 'CPIS:112'): [{'method': 'metres_hour', 'value': 70, 'setup_minutes': 0, 'profile': None}]}
    found = integrated._duration(r, dict(candidate), {'id': 'rid', 'confirmed': False}, seeded, templates, f'{TODAY}T08:00:00+00:00')
    assert found['duration_hours'] == pytest.approx(10 / 120) and found['rate_source'] == 'Excel provisório'


def test_settings_save_speed_rows_seed_and_timing_on_a_disposable_database(workspace, monkeypatch):
    """Base descartável: gravar linhas da tabela, preencher pelo Excel, apagar, margem e tempo fixo."""
    import uuid
    from pathlib import Path
    import psycopg
    from app.raw import objects
    from app.sector import settings as sector_settings, shifts
    with psycopg.connect(workspace) as c:
        c.execute((Path(__file__).parents[1] / 'sql/049_sector_settings.sql').read_text())
    resource = objects.save({'request_id': str(uuid.uuid4()), 'name': 'Ficep XP T4', 'area': 'cantoneiras',
                             'definition': {'aliases': [{'area': 'cantoneiras', 'name': 'Ficep XP T4'}], 'operations': ['CPIS:112'],
                                            'confirmed': True}}, 'resource')
    machine = {'id': resource['id'], 'name': 'Ficep XP T4', 'code': 'XPT4', 'confirmed': True, 'has_object': True,
               'aliases': [{'area': 'cantoneiras', 'name': 'Ficep XP T4'}], 'operations': ['CPIS:112'], 'ficha': [], 'default_shifts': 2}
    monkeypatch.setattr(sector_settings, 'machine_rows', lambda c, sector: [dict(machine)])
    monkeypatch.setattr(sector_settings, 'regenerate', lambda *a, **k: 0)
    monkeypatch.setattr(shifts, 'finish_batch', lambda c, request_id: None)

    def save(**payload):
        return sector_settings.save({'setor': 'cantoneiras', 'request_id': str(uuid.uuid4()), **payload})

    def rates():
        with planning.connect(readonly=True) as c:
            return c.execute("SELECT id, revision, archived, definition FROM planning_mtg.raw_objects WHERE kind='rate' ORDER BY name").fetchall()

    save(tipo='taxa', maquina=resource['id'], operacao='CPIS:112', valor='120', esp_de=0, esp_ate=8, arranque_s=15, notas='Punção')
    with pytest.raises(planning.PlanningError) as overlap:
        save(tipo='taxa', maquina=resource['id'], operacao='112', valor=100, esp_de=6, esp_ate=12)
    assert overlap.value.status == 409
    save(tipo='taxa', maquina=resource['id'], operacao='112', valor=100, esp_de=8, esp_ate=12)
    # Nas cantoneiras a operação é um código: uma linha 'corte' nunca valeria no motor.
    with pytest.raises(planning.PlanningError):
        save(tipo='taxa', maquina=resource['id'], operacao='LOCAL:PRINCIPAL', valor=100)
    found = rates()
    assert [r['definition']['thickness_max'] for r in found] == [8, 12]
    assert found[0]['definition']['operation'] == '112' and found[0]['definition']['piece_seconds'] == 15
    assert found[0]['definition']['source'] == 'Confirmada' and found[0]['definition']['notes'] == 'Punção'
    # Preencher pelo Excel não substitui a máquina/operação que já tem linhas; cria as que faltam com origem Excel.
    result = save(tipo='taxas_lote', linhas=[{'maquina': resource['id'], 'operacao': '112', 'metodo': 'metres_hour', 'valor': 120},
                                              {'maquina': resource['id'], 'operacao': '119', 'metodo': 'metres_hour', 'valor': 120}])
    assert result['changed'] == 1
    seeded = [r for r in rates() if r['definition']['operation'] == '119']
    assert seeded[0]['definition']['source'] == 'Excel' and seeded[0]['definition']['confirmed'] is True
    assert save(tipo='taxas_lote', linhas=[{'maquina': resource['id'], 'operacao': '119', 'valor': 130}])['changed'] == 0
    # Editar a linha da semente confirma-a; apagar arquiva.
    save(tipo='taxa', id=str(seeded[0]['id']), maquina=resource['id'], operacao='119', valor=125)
    edited = next(r for r in rates() if r['id'] == seeded[0]['id'])
    assert edited['definition']['source'] == 'Confirmada' and edited['definition']['value'] == 125
    save(tipo='taxa', id=str(seeded[0]['id']), arquivar=True)
    assert next(r for r in rates() if r['id'] == seeded[0]['id'])['archived']
    # Tempo fixo: guardado nas Definições, sem perder o modelo dos turnos e sem regenerar calendários. A margem do
    # setor já não se edita (08/10): enviar o valor atual não muda nada, outro valor é recusado.
    save(tipo='setor', expected_revision=0, turnos=[['06:00', '14:00']], dias=[1, 2, 3, 4, 5], feriados=[])
    with pytest.raises(planning.PlanningError):
        save(tipo='tempos', expected_revision=1, piece_minutes=-5)
    with pytest.raises(planning.PlanningError, match='eficiência'):
        save(tipo='tempos', expected_revision=1, margin_pct='12,5', piece_minutes=1)
    save(tipo='tempos', expected_revision=1, margin_pct=0, piece_minutes=1)
    # Eficiência por máquina (08/10): só as diferentes de 100 ficam; fora de 10–200 % é recusada.
    with pytest.raises(planning.PlanningError):
        save(tipo='eficiencia', expected_revision=2, eficiencias={resource['id']: 5})
    with pytest.raises(planning.PlanningError):
        save(tipo='eficiencia', expected_revision=2, eficiencias={'outra': 80})
    save(tipo='eficiencia', expected_revision=2, eficiencias={resource['id']: '80'})
    with planning.connect(readonly=True) as c:
        stored = sector_settings.read(c, 'cantoneiras')
        assert stored['template'] == [['06:00', '14:00']] and stored['piece_minutes'] == 1
        assert stored['efficiency'] == {resource['id']: 80}
        assert p.sector_timing(c)['cantoneiras'] == {'piece_minutes': 1.0, 'efficiency': {resource['id']: 80.0}}
        assert p.sector_timing(c)['perfis'] == {'piece_minutes': 0.0, 'efficiency': {}}
    # S01: gravar o horário ou os tempos não apaga a eficiência nem outras chaves que o ecrã não envia.
    with psycopg.connect(workspace) as c:
        c.execute("UPDATE planning_mtg.sector_settings SET definition = definition || '{\"folga_dias\": 2}'::jsonb WHERE area='cantoneiras'")
    save(tipo='setor', expected_revision=3, turnos=[['06:00', '14:00'], ['14:00', '22:00']], dias=[1, 2, 3, 4, 5], feriados=[])
    save(tipo='tempos', expected_revision=4, piece_minutes=0.5)
    with planning.connect(readonly=True) as c:
        stored = sector_settings.read(c, 'cantoneiras')
        assert len(stored['template']) == 2 and stored['piece_minutes'] == 0.5
        assert stored['efficiency'] == {resource['id']: 80} and stored['folga_dias'] == 2
    # 100 % (ou vazio) volta ao defeito: a máquina sai da lista.
    save(tipo='maquina', id=resource['id'], eficiencia=100)
    with planning.connect(readonly=True) as c:
        assert sector_settings.read(c, 'cantoneiras')['efficiency'] == {}
        assert p.sector_timing(c)['cantoneiras']['efficiency'] == {}


def test_operation_tabs_and_excel_seed_use_the_most_recent_speed():
    from app.sector import settings as sector_settings
    machines = [{'id': 'xp', 'name': 'Ficep XP T4', 'code': 'XPT4', 'confirmed': True, 'has_object': True, 'aliases': [],
                 'rate_operations_codes': ['112', '119'], 'ficha': [{'operation': 'CPIS:112', 'process': 'Punção'}]},
                {'id': 'r20', 'name': 'Ficep Rapid 20T -1', 'code': 'RAPID20_1', 'confirmed': True, 'has_object': True,
                 'aliases': [{'area': 'cantoneiras', 'name': 'Rapid 20T - 1'}], 'rate_operations_codes': ['119'],
                 'ficha': [{'operation': 'CPIS:119', 'process': 'Broca'}]},
                {'id': 'old', 'name': 'Por confirmar', 'code': 'X', 'confirmed': False, 'has_object': True, 'aliases': [],
                 'rate_operations_codes': ['112'], 'ficha': []}]
    tabs = sector_settings.operation_tabs(machines, [])
    assert [t['label'] for t in tabs] == ['Punção · 112', 'Broca · 119'] and tabs[1]['machines'] == ['xp', 'r20']
    study = {'recent_speeds': {'Ficep XP T4': {'value': 120, 'lines': 40, 'from': '2026-08-10'}, 'Rapid 20T - 1': {'value': 45, 'lines': 9}},
             'recent_operation_speeds': {('Ficep XP T4', '119'): {'value': 100, 'lines': 3}}}
    seed = sector_settings.excel_seed('cantoneiras', machines, study, {})
    # Só a velocidade da máquina (a mesma da Carteira), também numa operação com linhas próprias.
    assert [(s['maquina'], s['operacao'], s['valor']) for s in seed] == [('xp', '112', 120), ('xp', '119', 120), ('r20', '119', 45)]
    perfis = [{'id': 'meba', 'name': 'MEBA', 'code': 'MEBA', 'confirmed': True, 'has_object': True, 'rate_operations_codes': ['corte']}]
    assert sector_settings.excel_seed('perfis', perfis, None, {'MEBA': 48024.0})[0]['valor'] == 48024.0


def test_corte_is_a_rate_name_only_in_perfis():
    assert 'corte' not in p.operation_names('CPIS:112', True, 'cantoneiras')
    assert p.operation_names('CPIS:112', True, 'cantoneiras') == {'CPIS:112', '112'}
    assert 'corte' in p.operation_names('LOCAL:PRINCIPAL', True, 'perfis')
    # Uma linha 'corte' numa máquina de cantoneiras não vale na Carteira (como no motor, que procura '112').
    table = [rate('x', resource_id='rid', operation='corte', value=90)]
    fact = {'remaining': 10, 'phase': 'principal', 'area': 'cantoneiras', 'length_mm': 1000, 'profile': 'L80X80X8',
            'operation': 'CPIS:112', 'material_type': 'Sem tipo'}
    study = {'speeds': {}, 'profile_speeds': {}, 'recent_speeds': {'XP': {'value': 120, 'lines': 9}}}
    hours, why = estimates.estimate(fact, {'id': 'rid', 'name': 'XP'}, {'XP'}, study, {}, table=table)
    assert hours == pytest.approx(10 / 120) and 'mais recente' in why
    assert p.select_rate({}, area='cantoneiras', operation='112', resource_id='rid', manual=table, historical_rate={'value': None},
                         excel={'method': 'metres_hour', 'value': 120}, when=TODAY)['rate']['value'] == 120


def test_conflicting_excel_rows_block_even_with_a_history():
    # 08/10: o histórico já não entra nas horas, por isso também já não desfaz um conflito da tabela.
    values = {'profile': 'L50X50X5'}
    args = dict(area='cantoneiras', operation='112', resource_id='r1', excel={'method': 'metres_hour', 'value': 80}, when=TODAY)
    twins = [rate('s1', source='Excel', value=120), rate('s2', source='Excel', value=110)]
    assert p.select_rate(values, manual=twins, historical_rate={'value': 100, 'method': 'metres_hour'}, **args)['source'] is None
    blocked = p.select_rate(values, manual=twins, historical_rate={'value': None}, **args)
    assert blocked['source'] is None and blocked['candidates'] == ['s1', 's2']
    # Gantt: o conflito bloqueia; com uma taxa confirmada, a confirmada ganha.
    r = {'setor': 'MTG3', 'ordem_codigo': 'OF1', 'referencia_original': 'P', 'item_id': 'i', 'operacao_id': 'o', 'linha_origem': 'l',
         'ocorrencia': 1, 'operacao_codigo': 'CPIS:112', 'fase': 'principal', 'perfil': 'L80X80X8', 'qualidade': None,
         'quantidade_base': 10, 'saldo_confirmado': None, 'saldo_documental': 10, 'estado_quantidade': 'coerente',
         'comprimento_mm': 1000, 'recurso_atual': None, 'raw': {}}
    configs = [{'kind': 'rate', **rate(i, resource_id='rid', source='Excel', value=v)} for i, v in (('s1', 120), ('s2', 110))]
    candidate = {'resource_code': 'XPT6', 'proposed_code': 'CPIS:112', 'eligibility': 'admissible'}
    assert integrated._duration(r, candidate, {'id': 'rid', 'confirmed': False}, configs, {}, f'{TODAY}T08:00:00+00:00') is None
    assert candidate['duration_reason'] == 'Taxas da tabela sobrepostas.'
    configs.append({'kind': 'rate', **rate('c', resource_id='rid', value=90)})
    found = integrated._duration(r, dict(candidate), {'id': 'rid', 'confirmed': False}, configs, {}, f'{TODAY}T08:00:00+00:00')
    assert found['rate_source'] == 'Manual' and found['duration_hours'] == pytest.approx(10 / 90)


def _engine(recent):
    """Um Context do motor sem base de dados (só o que rate/estimate leem)."""
    ctx = p.Context.__new__(p.Context)
    ctx.configs, ctx.manual, ctx.resources, ctx.aliases, ctx.declarations, ctx.observed = [], [], {}, {}, [], []
    ctx.events, ctx.cache, ctx.time_cache, ctx.history_hashes, ctx.scopes = [], {}, {}, {}, {}
    ctx.timing, ctx.recent_excel = {}, recent
    return ctx


def test_without_a_table_carteira_engine_and_gantt_use_the_most_recent_excel_speed():
    recent = {'Ficep XP T6': {'value': 120, 'lines': 40, 'from': '2026-08-01', 'to': '2026-09-30'}}
    # Motor: a linha antiga traz Mt\h = 80; vale a velocidade mais recente da máquina.
    engine = _engine(recent).estimate({'machine': 'Ficep XP T6', 'quantity_to_plan': 10, 'length_mm': 1000}, 'cantoneiras', '112', TODAY,
                                      excel={'method': 'metres_hour', 'value': 80, 'unit': 'm/h', 'source': 'Velocidade da macro'},
                                      as_of=date.today())
    assert engine['hours'] == pytest.approx(10 / 120) and engine['rate']['row_value'] == 80
    assert engine['rate']['source'] == 'Velocidade mais recente do Excel'
    # Máquina sem velocidade recente: fica a da linha.
    other = _engine(recent).estimate({'machine': 'Peddi 6', 'quantity_to_plan': 10, 'length_mm': 1000}, 'cantoneiras', '112', TODAY,
                                     excel={'method': 'metres_hour', 'value': 50}, as_of=date.today())
    assert other['hours'] == pytest.approx(10 / 50)
    # Linhas da tabela e taxas mm²/h não mudam.
    seeded = {'method': 'metres_hour', 'value': 100, 'resource_id': 'rid'}
    assert p.current_excel(seeded, recent, 'Ficep XP T6') is seeded
    assert p.current_excel({'method': 'area_hour', 'value': 9}, recent, 'Ficep XP T6')['value'] == 9
    # Carteira (estimates) com o mesmo estudo.
    fact = {'remaining': 10, 'phase': 'principal', 'area': 'cantoneiras', 'length_mm': 1000, 'profile': 'L80X80X8', 'operation': 'CPIS:112'}
    study = {'speeds': {}, 'profile_speeds': {}, 'recent_speeds': recent,
             'recent_profile_speeds': {('Ficep XP T6', 'L80X80X8'): {'value': 100, 'lines': 6}}}
    carteira, _ = estimates.estimate(fact, {'id': 'rid', 'name': 'Ficep XP T6'}, {'Ficep XP T6'}, study, {})
    # Gantt: a velocidade documental da linha (80) e a mediana de outras máquinas dão lugar à mais recente.
    r = {'setor': 'MTG3', 'ordem_codigo': 'OF1', 'referencia_original': 'P', 'item_id': 'i', 'operacao_id': 'o', 'linha_origem': 'l',
         'ocorrencia': 1, 'operacao_codigo': 'CPIS:112', 'fase': 'principal', 'perfil': 'L80X80X8', 'qualidade': None,
         'quantidade_base': 10, 'saldo_confirmado': None, 'saldo_documental': 10, 'estado_quantidade': 'coerente',
         'comprimento_mm': 1000, 'recurso_atual': 'Ficep XP T6', 'rate_m_per_hour': 80, 'raw': {}}
    templates = {('Ficep XP T6', 'CPIS:112'): [{'method': 'metres_hour', 'value': 80, 'setup_minutes': 0, 'profile': None, 'lines': 9},
                                               {'method': 'metres_hour', 'value': 100, 'setup_minutes': 0, 'profile': None, 'lines': 2}]}
    found = integrated._duration(r, {'resource_code': 'Ficep XP T6', 'proposed_code': 'CPIS:112', 'eligibility': 'admissible'},
                                 {'id': 'rid', 'confirmed': False}, [], templates, f'{TODAY}T08:00:00+00:00', _engine(recent))
    assert carteira == pytest.approx(10 / 120) and found['duration_hours'] == pytest.approx(10 / 120)
    # Outra máquina sem velocidade escrita no Excel para este perfil: a mais recente dela, como na Carteira.
    other = integrated._duration(r, {'resource_code': 'XPT4', 'proposed_code': 'CPIS:112', 'eligibility': 'admissible'},
                                 {'id': 'r4', 'confirmed': False, 'aliases': [{'area': 'cantoneiras', 'name': 'Ficep XP T4'}]}, [], templates,
                                 f'{TODAY}T08:00:00+00:00', _engine({**recent, 'Ficep XP T4': {'value': 100, 'lines': 5}}))
    assert other['duration_hours'] == pytest.approx(10 / 100) and other['rate_source'] == 'Excel provisório'
    # Sem a medida recente (antes) a máquina sem velocidade escrita fica por confirmar.
    assert integrated._duration(r, {'resource_code': 'XPT4', 'proposed_code': 'CPIS:112', 'eligibility': 'admissible'},
                                {'id': 'r4', 'confirmed': False}, [], templates, f'{TODAY}T08:00:00+00:00', _engine({})) is None


def test_carga_calculation_tells_the_rate_origin_and_adds_piece_time_and_efficiency():
    from app.sector import load
    timing = {'piece_minutes': 0.5, 'efficiency': {'rid': 80}}  # 80 % → horas × 1,25, escrito como margem de 25 %
    table = [rate('c', resource_id='rid', value=90, piece_seconds=12)]
    fact = {'remaining': 10, 'phase': 'principal', 'area': 'cantoneiras', 'length_mm': 1000, 'profile': 'L80X80X8',
            'operation': 'CPIS:112', 'material_type': 'Sem tipo'}
    detail = {}
    hours, why = estimates.estimate(fact, {'id': 'rid', 'name': 'XP'}, {'XP'}, {'recent_speeds': {}}, {}, table=table, timing=timing, detail=detail)
    shown = load.estimate_calculation({**fact, 'load_hours': hours, 'load_basis': 'estimada', 'load_origin': why, 'load_estimate': detail})
    assert shown['rate'] == 90 and 'taxa confirmada' in shown['formula'] and 'margem' in shown['formula']
    assert shown['piece_seconds'] == 42 and shown['margin_pct'] == pytest.approx(25) and detail['efficiency_pct'] == 80
    assert (shown['volume_hours'] + shown['pieces_hours']) * 1.25 == pytest.approx(shown['hours'], abs=1e-3)
    # Sem tabela, sem margem: a velocidade mais recente do Excel, e a conta simples de sempre.
    detail = {}
    hours, why = estimates.estimate(fact, {'id': 'rid', 'name': 'XP'}, {'XP'}, {'recent_speeds': {'XP': {'value': 120, 'lines': 4}}}, {}, detail=detail)
    shown = load.estimate_calculation({**fact, 'load_hours': hours, 'load_basis': 'estimada', 'load_origin': why, 'load_estimate': detail})
    assert shown['rate'] == 120 and 'mais recente' in shown['formula'] and 'piece_seconds' not in shown
