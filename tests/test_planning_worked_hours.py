import uuid

import pytest
from app import planning
from app.raw import worked_hours as hours, objects, projection, capacity, query
from app.raw import capacity_revision
from tests.test_raw_workspace import workspace, database, canonical, registry, postgres16


def command(**kw):
    return {'request_id': str(uuid.uuid4()), **kw}


def setup(workspace):
    resource = objects.save(command(name='Recurso partilhado', area='perfis', definition={
        'aliases': [{'area': 'perfis', 'name': 'MEBA'}, {'area': 'cantoneiras', 'name': 'Ficep'}],
        'operations': ['corte', '112'], 'confirmed': True}), 'resource')
    with planning.connect() as c:
        for area, machine in [('perfis', 'MEBA'), ('cantoneiras', 'Ficep')]:
            projection.publish(c, 'planning:'+area, 'hours-planning', [], {'core_source_fingerprint':projection.fingerprint(c,area)})
            projection.publish(c, 'production_hours:'+area, 'hours-original', [{
                'key': area+'-sheet', 'sheet_uid': area+'-sheet',
                'values': {'machine': machine, 'production_date': '2026-09-23', 'hours_worked': 2 if area == 'perfis' else None, 'sheet': 1},
            }], {})
    return resource


def definition(resource, **kw):
    return {'resource_id': resource['id'], 'mode': 'period', 'start_date': '2026-09-23',
            'end_date': '2026-09-23', 'hours': 5, 'source': 'Relógio de produção conferido',
            'confirmed': True, **kw}


def save(d, **kw):
    preview = hours.preview({'definition': d, 'id': kw.get('id')})
    p = command(name='Horas reais', area='perfis', definition={**d, 'basis_hash': preview['basis_hash']}, **kw)
    return objects.save(p, 'worked_hours'), p


def weekly(area='perfis'):
    return next(r for r in query.listing({'area': area, 'dataset': 'capacity'})['rows'] if r['values']['week'] == 39)


def test_audited_replacement_shared_resource_zero_correction_and_no_calendar_mutation(workspace):
    resource = setup(workspace)
    calendar = objects.save(command(name='Disponibilidade', definition={
        'resource_id': resource['id'], 'year': 2026, 'week': 39, 'shifts': 3,
        'hours_per_shift': 8, 'exception_hours': 4, 'confirmed': True}), 'calendar')
    d = definition(resource)
    preview = hours.preview({'definition': d})
    assert preview['replacement_required'] and len(preview['observations']) == 2
    with pytest.raises(planning.PlanningError, match='substituição'): save({**d, 'replace_ocr': False})
    result, p = save({**d, 'replace_ocr': True})
    assert objects.save(p, 'worked_hours') == result
    assert len(objects.history(result['id'])['versions']) == 1
    capacity.rebuild()
    for area in ('perfis', 'cantoneiras'):
        row = weekly(area)
        assert row['values']['actual_hours'] == 5  # not 2 + 5, not duplicated by two aliases
        assert row['values']['available_hours'] == 20
        assert row['actual_coverage']['total'] == 1
        assert row['actual_evidence'][0]['origin'] == 'Manual'
        assert len(row['actual_evidence'][0]['sheets']) == 2
    with pytest.raises(planning.PlanningError, match='sobrepõe'): save({**d, 'replace_ocr': True})
    corrected, _ = save({**d, 'hours': 0, 'replace_ocr': True}, id=result['id'], expected_revision=1)
    assert corrected['revision'] == 2
    with pytest.raises(planning.PlanningError, match='mudou'):
        save({**d, 'hours': 8, 'replace_ocr': True}, id=result['id'], expected_revision=1)
    capacity.rebuild()
    assert weekly()['values']['actual_hours'] == 0
    assert weekly()['values']['available_hours'] == 20
    assert objects.get(calendar['id'])['revision'] == 1
    assert [v['definition']['hours'] for v in objects.history(result['id'])['versions']] == [0, 5]
    assert query.listing({'dataset': 'production_hours'})['rows'][0]['values']['hours_worked'] == 2


def test_sheet_scope_missing_hours_and_source_revision_invalidate_review(workspace):
    resource = setup(workspace)
    d = definition(resource, mode='sheet', sheet_key='cantoneiras:cantoneiras-sheet', operation='112', hours=3)
    result, _ = save(d)
    capacity.rebuild()
    assert weekly()['values']['actual_hours'] == 5  # Perfis 2 plus a distinct Cantoneiras sheet 3.
    assert weekly()['actual_coverage']['total'] == 2
    with planning.connect() as c:
        projection.publish(c, 'production_hours:cantoneiras', 'corrected-ocr', [{
            'key': 'cantoneiras-sheet', 'sheet_uid': 'cantoneiras-sheet',
            'values': {'machine': 'Ficep', 'production_date': '2026-09-23', 'hours_worked': 4, 'sheet': 1},
        }], {})
    capacity.rebuild()
    assert weekly()['values']['actual_hours'] is None
    assert any('mudaram' in x for x in weekly()['warnings'])
    assert weekly()['actual_coverage']['sum_known'] == 2
    with pytest.raises(planning.PlanningError, match='substituição'):
        save({**d, 'replace_ocr': False}, id=result['id'], expected_revision=1)
    save({**d, 'replace_ocr': True}, id=result['id'], expected_revision=1)
    capacity.rebuild()
    assert weekly()['values']['actual_hours'] == 5


@pytest.mark.parametrize('change,match', [
    ({'hours': -1}, 'não negativo'), ({'hours': 25}, 'duração'),
    ({'end_date': '2026-09-28'}, 'semana ISO'),
    ({'start_date': '2026-09-24'}, 'semana ISO'),
    ({'operation': 'inventada'}, 'operação'),
])
def test_invalid_declarations_do_not_persist(workspace, change, match):
    resource = setup(workspace)
    with pytest.raises(planning.PlanningError, match=match): save(definition(resource, **change))
    assert objects.listing('worked_hours')['items'] == []


def test_empty_origin_becomes_manual_correction(workspace):
    # 07/10/2026: a origem deixou de ser obrigatória; vazia fica «Correção manual».
    resource = setup(workspace)
    result, _ = save(definition(resource, source='', replace_ocr=True))
    assert result['definition']['source'] == 'Correção manual'


def test_stale_review_rejected_and_archive_preserves_history(workspace):
    resource = setup(workspace)
    d = definition(resource, replace_ocr=True)
    with pytest.raises(planning.PlanningError, match='Revê'):
        objects.save(command(name='Invalid', definition={**d, 'basis_hash': 'stale'}), 'worked_hours')
    result, _ = save(d)
    archived = objects.save(command(id=result['id'], expected_revision=1, name='Horas reais', archived=True, definition={}), 'worked_hours')
    assert archived['revision'] == 2
    capacity.rebuild()
    assert weekly()['values']['actual_hours'] is None  # Cantoneiras still unknown, no invented zero.
    assert weekly()['actual_coverage']['sum_known'] == 2
    assert len(objects.history(result['id'])['versions']) == 2


def test_physical_capacity_minutes_units_fractional_shifts_and_zero_availability():
    from tests.test_capacity_revision import item
    rate={'definition':{'operation':'112','method':'minutes_unit','value':.5,'confirmed':True}}
    calendar=[{'local':True,'confirmed':True,'hours':8,'hours_per_shift':8}]
    draft=item(q=10,h=2);draft['values']['draft']=True
    result=capacity_revision.summary([draft],calendar,None,2026,39,[rate])
    assert result['values']['planned_hours']==2
    assert result['values']['equivalent_shifts']==.25
    assert result['values']['capacity_total']==960
    assert result['values']['capacity_free']==720
    assert result['capacity_unit']=='un.'
    calendar[0]['hours']=0
    result=capacity_revision.summary([draft],calendar,None,2026,39,[rate])
    assert result['values']['free_hours']==-2
    assert result['values']['occupancy'] is None
    assert result['values']['capacity_free']==-240
    assert 'Sobrecarga' in result['warnings']
    incompatible={'definition':{'operation':'corte','method':'metres_hour','value':120,'confirmed':True}}
    result=capacity_revision.summary([draft],calendar,None,2026,39,[rate,incompatible])
    assert result['values']['capacity_total'] is None


def test_draft_local_piece_uses_recalculated_balance_without_cpis(workspace):
    resource=setup(workspace)
    objects.save(command(name='Taxa manual',definition={'resource_id':resource['id'],'area':'perfis',
        'operation':'corte','method':'units_hour','value':10,'valid_from':'2026-01-01','confirmed':True}), 'rate')
    row={'key':'new-local','values':{'of':'OF990000','machine':'MEBA','operation':'corte',
        'status':None,'expected_date':'2026-09-23','quantity_required':120,'quantity_to_plan':56},
        'calculation':{'compatible':True,'production_sources':[{'operation':'corte','remaining':56,'origin':'OCR validado'}]},
        'preparations':[{'values_json':{'operation':'corte','quantity_to_plan':36},
            'capacity_compatible':False,'record_status':'draft','operation_id':'corte'}]}
    with planning.connect() as c:projection.publish(c,'planning:perfis','quantity-edit',[row],{'core_source_fingerprint':projection.fingerprint(c,'perfis')})
    capacity.rebuild()
    piece=query.listing({'dataset':'capacity_items'})['rows'][0]
    assert piece['values']['quantity']==56
    assert piece['values']['planned_hours']==5.6
    assert piece['inputs']['quantity_source']=='OCR validado'
    assert weekly()['values']['planned_hours']==5.6
    assert weekly()['values']['draft_hours']==5.6


def test_invalid_ocr_hours_are_unknown_and_the_source_is_preserved(workspace):
    setup(workspace)
    for value in (-1, 25, 'erro'):
        with planning.connect() as c:
            projection.publish(c,'production_hours:perfis','invalid-hours-'+str(value),[{
                'key':'invalid','sheet_uid':'invalid','values':{'machine':'MEBA',
                    'production_date':'2026-09-23','hours_worked':value}}],{})
            observed=next(o for o in hours.observations(c) if o['key']=='perfis:invalid')
        assert observed['hours'] is None and observed['hours_reason']
        capacity.rebuild()
        assert weekly()['values']['actual_hours'] is None
        assert query.listing({'dataset':'production_hours'})['rows'][0]['values']['hours_worked']==value


def test_time_allocation_validates_total_and_retains_one_actual_time_declaration(workspace):
    resource=setup(workspace)
    allocation=[{'area':'perfis','operation':'corte','hours':2},{'area':'cantoneiras','operation':'112','hours':3}]
    d=definition(resource,replace_ocr=True,operation_hours=allocation)
    result,_=save(d)
    assert result['definition']['operation_hours']==allocation
    capacity.rebuild()
    assert weekly()['values']['actual_hours']==5 and weekly()['actual_coverage']['total']==1
    with pytest.raises(planning.PlanningError,match='somar'):
        save({**d,'hours':6},id=result['id'],expected_revision=1)
    with pytest.raises(planning.PlanningError,match='repete'):
        save({**d,'operation_hours':[allocation[0],allocation[0]]},id=result['id'],expected_revision=1)
    with pytest.raises(planning.PlanningError,match='não pertence'):
        save({**d,'operation_hours':[{'area':'perfis','operation':'unknown','hours':5}]},id=result['id'],expected_revision=1)
