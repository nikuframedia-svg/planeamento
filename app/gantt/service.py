"""Versioned Perfis scenarios, frozen executions and guarded acceptance."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
import logging
import time
import uuid

from psycopg.types.json import Jsonb

from .. import planning, planning_needs as needs
from ..raw import objects, analysis, query
from . import inputs, baseline, solver, validation, source_plan
from .contracts import HORIZON_WEEKS, utc

log = logging.getLogger(__name__)
USER_FIELDS = {'horizon_weeks', 'urgent', 'pins', 'picking_year_by_of',
               'picking_deadline_by_of', 'alternatives'}


@lru_cache(maxsize=1)
def runtime_manifest():
    root = Path(__file__).resolve().parents[1]
    paths = sorted([*root.joinpath('gantt').glob('*.py'),
                    root/'planning_dates.py', root/'planning_estimates.py',
                    root/'planning_calendars.py'])
    digest = sha256(b''.join(path.read_bytes() for path in paths)).hexdigest()
    return {'code_sha256': digest,
            'python_dependencies': {name: version(name) for name in ('ortools', 'psycopg')}}


def validate_definition(value):
    if not isinstance(value, dict) or set(value) - USER_FIELDS - {'accepted', 'pin_bindings'}:
        raise planning.PlanningError('Definição do cenário inválida.', 422)
    weeks = value.get('horizon_weeks', HORIZON_WEEKS)
    if type(weeks) is not int or not 1 <= weeks <= 26:
        raise planning.PlanningError('Escolhe um horizonte entre 1 e 26 semanas.', 422)
    urgent = value.get('urgent', [])
    if not isinstance(urgent, list) or len(urgent) > 5000 or any(not isinstance(x, str) or len(x) > 200 for x in urgent):
        raise planning.PlanningError('Urgências inválidas.', 422)
    pins = value.get('pins', {})
    if not isinstance(pins, dict) or len(pins) > 5000:
        raise planning.PlanningError('Fixações inválidas.', 422)
    clean_pins = {}
    for key, pin in pins.items():
        if not isinstance(key, str) or not isinstance(pin, dict) or set(pin) != {'start', 'resource_id'}:
            raise planning.PlanningError('Fixação inválida.', 422)
        try:
            start = utc(pin['start'])
            rid = str(needs.uid(pin['resource_id']))
        except (KeyError, TypeError, ValueError) as exc:
            raise planning.PlanningError('Início ou máquina da fixação inválidos.', 422) from exc
        if start.second or start.microsecond:
            raise planning.PlanningError('A fixação deve indicar um minuto inteiro.', 422)
        clean_pins[key] = {'start': start.isoformat(), 'resource_id': rid}
    years = value.get('picking_year_by_of', {})
    if not isinstance(years, dict) or any(type(year) is not int or not 2000 <= year <= 2200 for year in years.values()):
        raise planning.PlanningError('Anos de Picking inválidos.', 422)
    deadlines = value.get('picking_deadline_by_of', {})
    if not isinstance(deadlines, dict):
        raise planning.PlanningError('Prazos de Picking inválidos.', 422)
    try:
        deadlines = {str(of): utc(at).isoformat() for of, at in deadlines.items()}
    except (TypeError, ValueError) as exc:
        raise planning.PlanningError('Prazo de Picking com hora ou fuso inválido.', 422) from exc
    alternatives = value.get('alternatives', {})
    if not isinstance(alternatives, dict) or any(not isinstance(v, list) or len(v) > 20 for v in alternatives.values()):
        raise planning.PlanningError('Alternativas de máquina inválidas.', 422)
    try:
        alternatives = {str(k): list(dict.fromkeys(str(needs.uid(r)) for r in v)) for k, v in alternatives.items()}
    except planning.PlanningError as exc:
        raise planning.PlanningError(str(exc), 422) from exc
    result = {'horizon_weeks': weeks, 'urgent': list(dict.fromkeys(urgent)),
              'pins': clean_pins, 'picking_year_by_of': years,
              'picking_deadline_by_of': deadlines, 'alternatives': alternatives}
    if 'accepted' in value:
        result['accepted'] = value['accepted']
    if 'pin_bindings' in value:
        result['pin_bindings'] = value['pin_bindings']
    return result


def _binding(operation):
    return {'of': operation['of'], 'operation': operation['operation'],
            'planning_key': operation['planning_key'],
            'selection_aliases': operation.get('selection_aliases') or [],
            'technical_signature': operation['technical_signature']}


def _current_pin_bindings(conn, pins, inherited=None):
    bindings = {key:value for key,value in (inherited or {}).items() if key in pins}
    if not pins:
        return bindings
    try:
        gen = query.generation(conn, 'perfis')
    except planning.PlanningError as exc:
        if exc.status == 503:
            return bindings
        raise
    base, args = query.source(gen)
    keys = list({key.rsplit(':',1)[0] for key in pins})
    rows = conn.execute('SELECT m.row_key,c.values_json,c.detail' + base + ' AND m.row_key=ANY(%s)',
                        args + [keys]).fetchall()
    for row in rows:
        values = row['values_json']
        for key in pins:
            if key in bindings or not key.startswith(row['row_key'] + ':'):
                continue
            bindings[key] = {'of':values.get('of'), 'operation':key.rsplit(':',1)[1],
                             'planning_key':row['row_key'],
                             'selection_aliases':row['detail'].get('selection_aliases') or [],
                             'technical_signature':needs.signature(values)}
    return bindings


def operations(scenario_id=None):
    with planning.connect(readonly=True) as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        d = {}
        if scenario_id:
            obj = objects.get(scenario_id, c)
            if obj['kind'] != 'gantt' or obj['archived']:
                raise planning.PlanningError('Cenário indisponível.', 404)
            d = obj['definition']
        snapshot = inputs.capture(c, d, datetime.now(timezone.utc) + timedelta(minutes=1))
        return {'operations': snapshot['operations'], 'resources': snapshot['resources'],
                'source_references': snapshot['source_references'],
                'orphaned_pins': snapshot['orphaned_pins'],
                'source_plan': source_plan.build(snapshot)}


def _current(conn, payload, current_refs=None):
    if payload.get('runtime_manifest') != runtime_manifest():
        return False
    refs = current_refs or inputs.references(conn)
    if refs['sources_pending']:
        return False
    if payload['source_references'] == refs:
        return True
    frozen = payload.get('snapshot')
    if not frozen:
        return False
    try:
        now = inputs.capture(conn, payload['definition'], payload['started_at'])
    except planning.PlanningError:
        return False
    return not now['orphaned_pins'] and inputs.effective_digest(now) == inputs.effective_digest(frozen)


def scenarios():
    with planning.connect(readonly=True) as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        rows = c.execute("SELECT * FROM planning_mtg.raw_objects WHERE kind='gantt' AND NOT archived ORDER BY updated_at DESC").fetchall()
        refs = inputs.references(c)
        result = needs.serial(rows)
        for row in result:
            latest = c.execute("SELECT id,status FROM planning_mtg.raw_jobs WHERE kind='gantt' AND object_id=%s AND object_revision=%s ORDER BY created_at DESC LIMIT 1",
                               (needs.uid(row['id']),row['revision'])).fetchone()
            row['latest_job_id'] = str(latest['id']) if latest else None
            row['latest_job_status'] = latest['status'] if latest else None
            accepted = row['definition'].get('accepted') or {}
            if accepted:
                job = c.execute("SELECT input FROM planning_mtg.raw_jobs WHERE id=%s AND kind='gantt'",
                                (needs.uid(accepted['job_id']),)).fetchone()
                row['stale'] = not job or not _current(c, job['input'], refs)
            else:
                row['stale'] = False
        return {'scenarios': result, 'source_references': refs}


def save(p):
    with planning.connect() as c:
        ident = needs.uid(p.get('id') or p.get('request_id'))
        prior = c.execute('SELECT * FROM planning_mtg.raw_objects WHERE id=%s FOR UPDATE', (ident,)).fetchone()
        if prior and prior['kind'] != 'gantt':
            raise planning.PlanningError('Identificador já utilizado por outro registo.', 409)
        if p.get('area', 'perfis') != 'perfis':
            raise planning.PlanningError('O Gantt está disponível apenas para Perfis.', 422)
        incoming = p.get('definition') or {}
        if not isinstance(incoming, dict) or 'accepted' in incoming or 'pin_bindings' in incoming:
            raise planning.PlanningError('A aceitação faz-se na ação própria.', 422)
        d = validate_definition(incoming)
        d['pin_bindings'] = _current_pin_bindings(c, d['pins'],
            (prior['definition'].get('pin_bindings') if prior else None))
        if prior and prior['definition'].get('accepted'):
            d['accepted'] = prior['definition']['accepted']
        return objects.save({**p, 'id': str(ident), 'area': 'perfis', 'definition': d}, 'gantt', conn=c)


def solve(p):
    with planning.connect() as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        _, _, old = needs.command(c, p)
        if old:
            return old
        obj = objects.get(p.get('id'), c)
        if obj['kind'] != 'gantt' or obj['archived']:
            raise planning.PlanningError('Cenário indisponível.', 404)
        if p.get('expected_revision') != obj['revision']:
            raise planning.PlanningError('O cenário mudou. Reabre-o.', 409)
        refs = inputs.references(c)
        if refs['sources_pending']:
            raise planning.PlanningError('Aguarda a publicação dos cálculos.', 409)
        accepted = obj['definition'].get('accepted') or {}
        prior_bars = {}
        started = datetime.now(timezone.utc).replace(second=0, microsecond=0) + timedelta(minutes=1)
        if accepted.get('job_id'):
            prior = c.execute("SELECT input,result FROM planning_mtg.raw_jobs WHERE id=%s AND kind='gantt' AND status='done'",(needs.uid(accepted['job_id']),)).fetchone()
            if prior and prior['result']:
                older = (prior['result'].get('proposal') or {}).get('bars') or {}
                offset = int((utc(prior['input']['started_at'])-started).total_seconds()//60)
                prior_bars = {key: {**bar, 'start_minute': bar['start_minute']+offset,
                                    'end_minute': bar['end_minute']+offset}
                              for key, bar in older.items()}
        payload = {'definition': obj['definition'], 'source_references': refs,
                   'runtime_manifest': runtime_manifest(),
                   'started_at': started.isoformat(), 'accepted_bars': prior_bars}
        job = analysis.queue(c, obj, kind='gantt', input=payload)
        return needs.finish(c, p, {'job_id': str(job['id']), 'status': job['status'],
                                   'object_revision': obj['revision']})


def job(id):
    with planning.connect(readonly=True) as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        row = c.execute("SELECT * FROM planning_mtg.raw_jobs WHERE id=%s AND kind='gantt'", (needs.uid(id),)).fetchone()
        if not row:
            raise planning.PlanningError('Tarefa Gantt não encontrada.', 404)
        result = needs.serial(row)
        result['stale'] = not _current(c, row['input'])
        return result


def _publish(job, update, *, final=False):
    with planning.connect() as c:
        fields = "status='done',finished_at=now(),heartbeat_at=now()" if final else 'heartbeat_at=now()'
        c.execute(f'UPDATE planning_mtg.raw_jobs SET {fields},input=%s,result=%s WHERE id=%s AND status=\'running\' AND attempts=%s',
                  (Jsonb(update['input']), Jsonb(update['result']), job['id'], job['attempts'] + 1))


def run_job(job):
    began = time.perf_counter()
    try:
        payload = dict(job['input'])
        if payload.get('runtime_manifest') != runtime_manifest():
            raise planning.PlanningError('A versão do motor Gantt mudou. Volta a calcular.',409)
        with planning.connect(readonly=True) as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            snapshot = inputs.capture(c, {**payload['definition'], 'accepted_bars': payload.get('accepted_bars') or {}},
                                      payload['started_at'], expected_references=payload['source_references'])
        payload['snapshot'] = snapshot
        preliminary = {'input': payload, 'result': {'phase': 'initial', 'snapshot': snapshot}}
        if snapshot['orphaned_pins']:
            preliminary['result']['diagnostic'] = {'orphaned_pins': snapshot['orphaned_pins']}
        try:
            initial = baseline.build(snapshot)
        except (ValueError, KeyError) as exc:
            preliminary['result'].update(phase='diagnostic', diagnostic={'message': str(exc),
                                        'orphaned_pins': snapshot['orphaned_pins']})
            _publish(job, preliminary, final=True)
            return
        preliminary['result']['initial'] = initial
        preliminary['result']['timings'] = {'initial_seconds': round(time.perf_counter()-began, 3)}
        _publish(job, preliminary)
        if snapshot['orphaned_pins']:
            preliminary['result'].update(phase='diagnostic', proposal=initial)
            _publish(job, preliminary, final=True)
            return
        proposal, technical = solver.optimize(snapshot, initial)
        checked = validation.validate(snapshot, proposal)
        preliminary['result']['timings']['total_seconds'] = round(time.perf_counter()-began, 3)
        preliminary['result'].update(phase='done', proposal=proposal, solver=technical, validation=checked)
        _publish(job, preliminary, final=True)
    except Exception as exc:
        log.exception('Gantt job failed')
        message = str(exc) if isinstance(exc, planning.PlanningError) else 'Falha ao construir ou validar a proposta.'
        with planning.connect() as c:
            c.execute("UPDATE planning_mtg.raw_jobs SET status='failed',error=%s,finished_at=now() WHERE id=%s AND status='running' AND attempts=%s",
                      (message, job['id'], job['attempts'] + 1))


def accept(p):
    with planning.connect() as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        _, _, old = needs.command(c, p)
        if old:
            return old
        row = c.execute("SELECT * FROM planning_mtg.raw_jobs WHERE id=%s AND kind='gantt' FOR UPDATE", (needs.uid(p.get('job_id')),)).fetchone()
        if not row or row['status'] != 'done':
            raise planning.PlanningError('A proposta ainda não terminou.', 409)
        obj = objects.get(row['object_id'], c)
        if obj['revision'] != row['object_revision'] or p.get('expected_revision') != obj['revision']:
            raise planning.PlanningError('O cenário mudou. Reabre a proposta.', 409)
        result = row['result'] or {}
        snapshot = row['input'].get('snapshot')
        proposal = result.get('proposal')
        if not snapshot or not proposal or result.get('phase') != 'done':
            raise planning.PlanningError('A proposta não é aceitável.', 409)
        if not _current(c, row['input']):
            raise planning.PlanningError('As fontes mudaram. Recalcula a proposta.', 409)
        if snapshot.get('orphaned_pins'):
            raise planning.PlanningError('Revê as fixações órfãs ou incompatíveis.', 409)
        checked = validation.validate(snapshot, proposal)
        if not checked['valid']:
            raise planning.PlanningError('A proposta falhou a validação: ' + '; '.join(checked['errors'][:5]), 422)
        accepted = {'job_id': str(row['id']), 'source_references': row['input']['source_references'],
                    'score': checked['score'], 'accepted_at': datetime.now(timezone.utc).isoformat()}
        internal = {'request_id': str(uuid.uuid5(needs.uid(p['request_id']), 'accepted-gantt')),
                    'id': obj['id'], 'expected_revision': obj['revision'],
                    'name': obj['name'], 'area': 'perfis',
                    'definition': {**obj['definition'], 'pins': snapshot['pins'],
                                   'pin_bindings': {op['key']:_binding(op) for op in snapshot['operations']
                                                    if op['key'] in snapshot['pins']},
                                   'accepted': accepted}}
        saved = objects.save(internal, 'gantt', conn=c)
        return needs.finish(c, p, {'id': saved['id'], 'revision': saved['revision'], 'accepted': accepted})
