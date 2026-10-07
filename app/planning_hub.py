"""Consulta consolidada do CPIS, planos, dossiês e produção validada."""
from __future__ import annotations

import hashlib
from collections import OrderedDict
from contextlib import nullcontext
import json
import math
import re
import threading
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import psycopg
from psycopg.types.json import Jsonb

from . import planning
from .config import settings
from .dossiers.models import order_number, ref_key
from . import cpis_copies, planning_production, planning_population
from .matching.geometry import profile_key

OPEN_STATES = ('Em Aberto', 'Em Produção')


def _serial(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=lambda x:
        float(x) if isinstance(x, Decimal) else str(x) if isinstance(x, uuid.UUID) else x.isoformat()))


def _technical_key(value):
    return re.sub(r'\s+', ' ', str(value or '').strip().upper())


def _production_associations(produced, plans):
    current = {row['plan_key']: row for row in plans}
    by_reference = {}
    for line in plans:
        by_reference.setdefault((line.get('source_app'), _technical_key(line.get('component_ref'))), []).append(line)
    for record in produced:
        record['resolved_plan_keys'], record['resolved_plan_refs'] = [], []
        frozen = (record.get('extra') or {}).get('plan_identity') or record.get('frozen_identity') or {}
        if record.get('full_profile') and not record.get('plan_refs'):
            record['association_status'] = 'incomplete'
            continue
        probes = record.get('plan_refs') or [{
            'plan_key': record.get('matched_plan_key'),
            'component_ref': frozen.get('component_ref', record.get('model_ref')),
            'length_mm': frozen.get('length_mm', record.get('length_mm')),
            'profile_type': frozen.get('profile_type', record.get('profile_type')),
            'assumed_quantity': record.get('quantity')}]
        resolved, candidates = [], set()
        explicit_count = 0
        for probe in probes:
            explicit = current.get(probe.get('plan_key'))
            if explicit and explicit.get('source_app') == record.get('source_app'):
                # A stored key refers to this immutable snapshot, not a row number in a new file.
                resolved.append({'plan_key': explicit['plan_key'], 'assumed_quantity': probe.get('assumed_quantity')})
                explicit_count += 1
                continue
            rows = by_reference.get((record.get('source_app'), _technical_key(probe['component_ref'])), []) if probe.get('component_ref') else []
            length = probe.get('length_mm')
            if length is not None:
                rows = [line for line in rows if line.get('length_mm') is not None
                        and abs(float(line['length_mm']) - float(length)) < .001]
            profile = probe.get('profile_type')
            if profile:
                rows = [line for line in rows
                        if profile_key(line.get('profile_type')) == profile_key(profile)]
            candidates.update(line['plan_key'] for line in rows)
            if len(rows) == 1 and length is not None and profile:
                resolved.append({'plan_key': rows[0]['plan_key'],
                                 'assumed_quantity': probe.get('assumed_quantity')})
        unique = list(dict.fromkeys(item['plan_key'] for item in resolved))
        if len(unique) == len(probes) and unique:
            record['association_status'] = 'explicit' if explicit_count == len(probes) else 'technical_unique'
            record['resolved_plan_keys'] = unique
            record['resolved_plan_refs'] = resolved
        elif candidates:
            record['association_status'] = 'ambiguous' if len(candidates) > 1 else 'incomplete'
            record['association_candidates'] = sorted(candidates)
            record['resolved_plan_keys'] = []
        else:
            record['association_status'] = 'unmatched'
            record['resolved_plan_keys'] = []


def _table(conn, schema, table):
    return bool(conn.execute('SELECT to_regclass(%s) AS name', (f'{schema}.{table}',)).fetchone()['name'])


def _latest_snapshots(conn):
    rows = conn.execute('''SELECT DISTINCT ON (dataset_id) dataset_id,snapshot_id,
        source_filename,source_path,source_sha256,loaded_at
        FROM audit_mtg.snapshots WHERE dataset_id=ANY(%s)
        ORDER BY dataset_id,loaded_at DESC,snapshot_id DESC''',
        (['ds-met2-perfis', 'ds-2638099daddc474e'],)).fetchall()
    return {row['dataset_id']: row for row in rows}


def _direct_version(conn, requested=None):
    if not _table(conn, 'cpis_mtg', 'versions'):
        return None
    if requested and not str(requested).startswith('fallback:'):
        try:
            value = uuid.UUID(str(requested))
        except ValueError:
            raise planning.PlanningError('A versão CPIS pedida já não é válida.', 409) from None
        row = conn.execute('SELECT * FROM cpis_mtg.versions WHERE id=%s', (value,)).fetchone()
        if not row:
            raise planning.PlanningError('A versão CPIS pedida já não está disponível.', 409)
        return row
    return conn.execute('SELECT * FROM cpis_mtg.versions ORDER BY last_confirmed_at DESC LIMIT 1').fetchone()


def _fallback_token(snapshots):
    return 'fallback:' + ':'.join(str(snapshots.get(key, {}).get('snapshot_id') or '-')
                                 for key in ('ds-met2-perfis', 'ds-2638099daddc474e'))


def _fresh(confirmed_at):
    if not confirmed_at:
        return False
    current = datetime.now(timezone.utc)
    if confirmed_at.tzinfo is None:
        confirmed_at = confirmed_at.replace(tzinfo=timezone.utc)
    return 0 <= (current - confirmed_at).total_seconds() <= settings.cpis_fresh_seconds


def require_operational_orders(orders, *, expected_version=None, conn=None):
    """One rule for manual/PDF outputs and completion; never trust a pinned old OF."""
    if conn is None:
        with planning.connect(readonly=True) as connection:
            return require_operational_orders(orders, expected_version=expected_version, conn=connection)
    conn.execute("SELECT pg_advisory_xact_lock_shared(hashtextextended('cpis_mtg.sync',0))")
    direct = _direct_version(conn)
    if not direct or not _fresh(direct['last_confirmed_at']):
        raise planning.PlanningError(
            'O CPIS não tem uma confirmação direta com menos de 15 minutos. '
            'Podes consultar e guardar rascunhos; a conclusão e a saída operacional estão bloqueadas.', 409)
    version = str(direct['id'])
    if expected_version and expected_version != version:
        raise planning.PlanningError('O CPIS mudou. Reabre a OF e prepara uma nova comparação.', 409)
    for original in set(orders):
        of = order_number(original)
        rows = conn.execute('SELECT status FROM cpis_mtg.orders WHERE version_id=%s AND production_order_no=%s',
                            (direct['id'], of)).fetchall()
        states = {row['status'] for row in rows}
        if len(states) != 1 or not states.issubset(set(OPEN_STATES)):
            raise planning.PlanningError(f'{of or "A OF"} não está confirmada como aberta na versão atual do CPIS. Reabre a ordem.', 409)
    return version


def source_status():
    with planning.connect(readonly=True) as conn:
        snapshots = _latest_snapshots(conn)
        direct = _direct_version(conn)
        from . import original_ocr
        original_status = original_ocr.status(conn)
        ocr = conn.execute('''SELECT v.source_app,count(DISTINCT v.sheet_uid) AS sheets,
            count(p.id) AS records,max(v.validated_at) AS last_validation,
            max(p.sheet_date) AS last_production_date
            FROM mes_kanban.validated_sheets v
            LEFT JOIN mes_kanban.production_records p USING(sheet_uid)
            WHERE v.source_app=ANY(%s) GROUP BY v.source_app''',
            (['kanban-mes-mtg2', 'kanban-mes'],)).fetchall()
        last_attempt = None
        if _table(conn, 'cpis_mtg', 'sync_attempts'):
            last_attempt = conn.execute(
                'SELECT success,finished_at,error_code,error_message FROM cpis_mtg.sync_attempts '
                'ORDER BY finished_at DESC LIMIT 1').fetchone()
    if direct:
        cpis = {'mode': 'direct', 'label': 'CPIS direto', 'version': str(direct['id']),
                'checked_at': direct['last_confirmed_at'], 'fresh': _fresh(direct['last_confirmed_at']),
                'row_count': direct['row_count'], 'available': True}
    else:
        latest = max((r['loaded_at'] for r in snapshots.values()), default=None)
        cpis = {'mode': 'imported', 'label': 'CPIS importado da macro — sem confirmação direta',
                'version': _fallback_token(snapshots), 'checked_at': None, 'imported_at': latest, 'fresh': False,
                'available': bool(snapshots)}
    return _serial({'cpis': cpis, 'last_attempt': last_attempt, 'ocr_original': original_status,
        'display_timezone': settings.display_timezone,
        'macros': {
            'perfis': snapshots.get('ds-met2-perfis'),
            'cantoneiras': snapshots.get('ds-2638099daddc474e'),
        },
        'ocr': {('perfis' if r['source_app'] == 'kanban-mes-mtg2' else 'cantoneiras'): r
                for r in ocr},
        'completion_allowed': bool(cpis.get('mode') == 'direct' and cpis.get('fresh'))})


def _order_summary(rows):
    fields = ('sales_order_no', 'customer_name', 'observations', 'status', 'factory_unit',
              'work_type_code', 'work_type_description', 'responsible_dp', 'planned_start_date', 'planned_finish_date',
              'delivery_date', 'actual_start_date', 'actual_finish_date')
    result = {'of': rows[0]['production_order_no'], 'sources': [],
              'cpis_copies': sorted({r.get('area') for r in rows if r.get('area')})}
    # Cópias importadas dos Excel trazem a hora de carga: manda a mais recente, campo a campo,
    # sem conflito (decisão de 06/10/2026, substitui 20/09 e C06). Um campo vazio na cópia
    # recente fica com o valor da outra. Sem hora de carga (CPIS direto), a regra antiga mantém-se.
    by_recency = any(r.get('copy_loaded_at') for r in rows)
    if by_recency:
        rows = cpis_copies.latest_first(rows)
        result['cpis_latest_copy'] = rows[0].get('area')
    conflicts = []
    for field in fields:
        values = []
        for row in rows:
            value = row.get(field)
            if value not in (None, '') and value not in values:
                values.append(value)
        if by_recency and field != 'sales_order_no':
            result[field] = values[0] if values else None
            values = values[:1] if field == 'status' else values
        else:
            result[field] = values[0] if len(values) == 1 else None
            if len(values) > 1 and field != 'sales_order_no':
                conflicts.append(field)
        result[field + '_values'] = values
    result['ovs'] = result.pop('sales_order_no_values')
    result.pop('sales_order_no', None)
    result['conflicts'] = conflicts
    result['cpis_status'] = result.pop('status')
    result['status_values'] = result.pop('status_values')
    return result


def _order_rows(conn, version, query, states, extra_ofs=(), *, only_ofs=None):
    literal = str(query or '').strip()[:160]
    pattern = f'%{literal}%'
    if version:
        source = '''SELECT production_order_no,sales_order_no,customer_name,observations,status,
            factory_unit,work_type_code,work_type_description,responsible_dp,planned_start_date,planned_finish_date,
            delivery_date,actual_start_date,actual_finish_date,NULL::text AS area
            FROM cpis_mtg.orders WHERE version_id=%s AND production_order_no IS NOT NULL'''
        params = [version['id']]
    else:
        ids = [r['snapshot_id'] for r in _latest_snapshots(conn).values()]
        if not ids:
            return []
        source = '''SELECT c.production_order_no,c.sales_order_no,c.customer_name,c.observations,c.status,
        c.factory_unit,c.work_type_code,c.work_type_description,c.responsible_dp,c.planned_start_date,c.planned_finish_date,
        c.delivery_date,c.actual_start_date,c.actual_finish_date,
        CASE WHEN s.dataset_id='ds-met2-perfis' THEN 'perfis' ELSE 'cantoneiras' END AS area,
        s.loaded_at AS copy_loaded_at,c.record_date AS copy_record_date
        FROM raw_mtg.cpis_rows c JOIN audit_mtg.snapshots s USING(snapshot_id)
        WHERE c.snapshot_id=ANY(%s) AND c.production_order_no IS NOT NULL'''
        params = [ids]
    if only_ofs is not None:
        # Restrict identities before loading administrative context, retaining
        # every CPIS copy of each requested OF for conflict/closure checks.
        source += " AND regexp_replace(trim(production_order_no),'^OF[ ._-]*','','i')=ANY(%s)"
        params.append([of[2:] for of in only_ofs])
    if not literal and states is None:
        # No identity filter: the source already contains every required copy.
        # A self-join here can become quadratic for a newly imported CPIS cut
        # whose statistics have not yet incorporated its complete population.
        return conn.execute(source,params).fetchall()
    # Filter identities, then return every source row for those identities. A
    # closed copy must not disappear because the other copy is open or matches q.
    sql = 'WITH source AS (' + source + ''') SELECT s.* FROM source s
        JOIN (SELECT DISTINCT production_order_no FROM source
          WHERE (%s::text[] IS NULL OR lower(btrim(status))=ANY(%s))
          AND (%s='' OR production_order_no ILIKE %s OR sales_order_no ILIKE %s
            OR customer_name ILIKE %s OR observations ILIKE %s OR production_order_no=ANY(%s))) found
        USING(production_order_no)'''
    selected_states = [planning_population.token(s) for s in states] if states is not None else None
    return conn.execute(sql, (*params, selected_states, selected_states, literal,
                             pattern, pattern, pattern, pattern, list(extra_ofs))).fetchall()


def _document_context(query=''):
    try:
        from .dossiers import store
        documents = store.list_documents(limit=None)
    except Exception:
        return {}, [], {}
    counts = {}
    areas = {}
    matches = set()
    needle = str(query or '').strip().casefold()
    for document in documents:
        of = order_number(document.get('production_order'))
        if not of:
            continue
        counts[of] = counts.get(of, 0) + 1
        if document.get('perfis_piece_count', 0):
            areas.setdefault(of, set()).add('perfis')
        if not needle:
            continue
        haystack = ' '.join(str(document.get(key) or '') for key in
                            ('production_order', 'filename', 'context')).casefold()
        if needle in haystack:
            matches.add(of)
            continue
        try:
            full = store.get_document(document['id'])
            if any(needle in ' '.join(str((piece.get('values') or {}).get(key) or '')
                   for key in ('component_ref', 'drawing_ref', 'profile')).casefold()
                   for piece in full.get('pieces', [])):
                matches.add(of)
        except Exception:
            continue
    return counts, sorted(matches), areas


class _ImportCache:
    """Values that depend only on immutable imports, kept for the newest `size` keys.

    A macro import or a CPIS version never changes in place (a new file is a new snapshot,
    a new CPIS content is a new version), so a value built for a key stays valid until a
    newer key appears. One build per key at a time: simultaneous first requests wait for
    the same build instead of each reading the imports again.
    """

    def __init__(self, size=2):
        self.size = size
        self._lock = threading.Lock()
        self._values = OrderedDict()
        self._flights = {}

    def get(self, key, build):
        with self._lock:
            if key in self._values:
                self._values.move_to_end(key)
                return self._values[key]
            flight = self._flights.setdefault(key, threading.Lock())
        with flight:
            with self._lock:
                if key in self._values:
                    return self._values[key]
            value = build()
            with self._lock:
                self._values[key] = value
                while len(self._values) > self.size:
                    self._values.popitem(last=False)
                self._flights.pop(key, None)
        return value

    def clear(self):
        with self._lock:
            self._values.clear()


_generations = _ImportCache(size=2)


def clear_cache():
    """Forget the cached imports. Only for tests and trials that edit an import in place."""
    _generations.clear()


def _source_key(conn, direct, snapshots):
    """Identity of what the slow part of the order list reads: one CPIS version and the macro imports."""
    info = conn.info
    return ((info.host, info.port, info.dbname), str(direct['id']) if direct else None,
            tuple(sorted((dataset, row['snapshot_id'], row['loaded_at']) for dataset, row in snapshots.items())))


def _interned(memo, compute, *inputs):
    """One shared result per distinct input (repr keeps 1, 1.0 and True apart)."""
    key = repr(inputs)
    if key not in memo:
        memo[key] = compute()
    return memo[key]


class _Generation:
    """What the order list derives from one CPIS version and one set of macro imports. Read-only.

    Memory (production, 07/10/2026: 70 000 CPIS orders, 87 000 macro lines): the full CPIS summaries
    took 240 MB, so only the fields the list filters on are kept (`cpis`) together with the CPIS
    rows as tuples; `summary(of)` rebuilds the complete summary for the orders actually returned.
    """

    LIGHT = ('of', 'status_values', 'ovs', 'customer_name_values', 'observations_values', 'conflicts')

    def __init__(self, cpis_rows, source):
        from . import planning_order_population as order_population
        self.source = source
        self._keys = next((tuple(group[0]) for group in cpis_rows.values()), ())
        self._rows, self.cpis, self.cpis_closures = {}, {}, {}
        memo = {}
        for of, group in cpis_rows.items():
            summary = _order_summary(group)
            self._rows[of] = tuple(tuple(row.values()) for row in group)
            self.cpis[of] = {key: summary[key] for key in self.LIGHT}
            # A CPIS summary has no macro closure: its classification depends only on its states.
            self.cpis_closures[of] = _interned(memo, lambda: planning_population.classify(summary),
                                               'cpis', summary['status_values'])
        cpis = self.cpis
        # Each macro line on its own, classified as summarize() would with the CPIS states of its OF.
        # A line's classification depends only on its closure values and those states.
        self.line_closures = []
        for member in source.singles:
            context = cpis.get(member['of']) or source.summaries.get(member['of']) or {}
            statuses = context.get('status_values', [])
            self.line_closures.append((statuses, _interned(
                memo, lambda: order_population.classify(member, context),
                'line', member['macro_closure_values'], statuses)))

    def plan_counts(self, members, singles, contexts):
        """summarize() for this request, reusing the classification of lines that did not change."""
        from . import planning_order_population as order_population
        result = {}
        for member, index in zip(members, singles):
            context = contexts.get(member['of'], {})
            closure = None
            if index is not None:
                statuses, closure = self.line_closures[index]
                if context.get('status_values', []) != statuses:
                    closure = None
            if closure is None:
                closure = order_population.classify(member, context)
            order_population.tally(result, member, closure)
        return result

    def closure(self, item):
        cached = self.cpis.get(item['of'])
        return self.cpis_closures[item['of']] if item is cached else planning_population.classify(item)

    def summary(self, of):
        return _order_summary([dict(zip(self._keys, row)) for row in self._rows[of]])

    def complete(self, items):
        """The returned orders with their full CPIS summary (list items carry only LIGHT fields)."""
        return [{**self.summary(item['of']), **item} if item['of'] in self.cpis else item for item in items]


def _shared(pool, value):
    """The same object for equal texts and dates, so repeated states, units and dates are kept once."""
    if isinstance(value, (str, date)):  # datetime is a date; the offset decides how it is written
        return pool.setdefault((type(value), value, getattr(value, 'tzinfo', None) and value.utcoffset()), value)
    return value


def _load_generation(conn, direct, snapshots):
    from . import planning_order_population
    grouped, pool = {}, {}
    for row in _order_rows(conn, direct, '', None):
        of = order_number(row['production_order_no']) or row['production_order_no']
        if of:
            grouped.setdefault(of, []).append(
                {key: _shared(pool, value) for key, value in {**row, 'production_order_no': of}.items()})
    return _Generation(grouped, planning_order_population.Source.load(conn, snapshots))


def list_orders(*, query='', page=1, page_size=50, state='all', version=None,
                pending_only=False, population='active'):
    try:
        page, page_size = max(1, int(page)), min(100, max(1, int(page_size)))
    except (TypeError, ValueError):
        raise planning.PlanningError('A paginação é inválida.') from None
    expected, mode, population, orders, generation = _population_items(
        query=query, state=state, version=version, pending_only=pending_only, population=population)
    total = len(orders)
    start = (page - 1) * page_size
    result = _serial({'version': expected, 'mode': mode, 'population': population,
                      'orders': generation.complete(orders[start:start + page_size])})
    return {**result, 'page': page, 'page_size': page_size, 'total': total,
            'pages': math.ceil(total / page_size) if total else 0}


def _order_population(*, query='', state='all', version=None, pending_only=False,
                      population='active'):
    """Classify the complete result before any count or pagination is applied."""
    expected, mode, population, orders, generation = _population_items(
        query=query, state=state, version=version, pending_only=pending_only, population=population)
    return _serial({'version': expected, 'mode': mode, 'population': population,
                    'orders': generation.complete(orders)})


def _population_items(*, query, state, version, pending_only, population):
    population = planning_population.scope(population)
    states = OPEN_STATES if state == 'open' else ((state,) if state and state != 'all' else None)
    document_counts, document_matches, document_areas = _document_context(query)
    with planning.connect(readonly=True) as conn:
        direct = _direct_version(conn, version)
        snapshots = _latest_snapshots(conn)
        if not direct and not snapshots:
            raise planning.PlanningError(
                'As fontes CPIS e as importações das macros estão indisponíveis. Tenta novamente mais tarde.',
                503)
        reference_matches = set(document_matches)
        if str(query or '').strip():
            for row in conn.execute('''SELECT DISTINCT production_order_no FROM raw_mtg.plan_production_rows
                    WHERE snapshot_id=ANY(%s) AND component_ref ILIKE %s''',
                    ([r['snapshot_id'] for r in snapshots.values()], f'%{str(query).strip()[:160]}%')).fetchall():
                reference_matches.add(row['production_order_no'])
        if str(query or '').strip() and _table(conn, 'planning_mtg', 'records'):
            for row in conn.execute('''SELECT DISTINCT production_order_no
                    FROM planning_mtg.records WHERE component_ref ILIKE %s''',
                    (f'%{str(query).strip()[:160]}%',)).fetchall():
                reference_matches.add(row['production_order_no'])
        expected = str(direct['id']) if direct else _fallback_token(snapshots)
        if version and str(version) != expected:
            raise planning.PlanningError('A origem mudou. Atualiza a lista antes de continuar.', 409)
        from . import planning_order_population
        # The imports are read once per version; the application's own data on every request.
        generation = _generations.get(_source_key(conn, direct, snapshots),
                                      lambda: _load_generation(conn, direct, snapshots))
        members, fallback, singles = planning_order_population.assemble(conn, generation.source)
        contexts = {**fallback, **generation.cpis}
        plan_counts = generation.plan_counts(members, singles, contexts)
        needle = str(query or '').strip().casefold()[:160]
        reference_matches = {order_number(of) for of in reference_matches}
        if needle:
            reference_matches.update(m['of'] for m in members if any(
                needle in str(ref or '').casefold() for ref in m['references']))
        selected_states = {planning_population.token(s) for s in states} if states is not None else None
        summaries = []
        for of, item in contexts.items():
            if selected_states is not None and not any(planning_population.token(status) in selected_states
                                                       for status in item['status_values']):
                continue
            if needle and of not in reference_matches and not any(needle in str(value or '').casefold()
                    for value in [of, *item['ovs'], *item['customer_name_values'], *item['observations_values']]):
                continue
            plan_state = plan_counts.get(item['of'], {})
            closure = generation.closure(item)
            unknown_states = list(closure['unknown_states'])
            plan, population_counts = {}, {'active': 0, 'history': 0}
            for area, value in plan_state.items():
                counts = {'active': value['active'] if closure['active'] else 0,
                          'history': value['history'] if closure['active'] else value['lines']}
                for key, count in counts.items():
                    population_counts[key] += count
                selected = value['lines'] if population == 'all' else counts[population]
                if selected:
                    plan[area] = selected
                for unknown in value['unknown_states']:
                    if unknown not in unknown_states:
                        unknown_states.append(unknown)
            # Orders without imported pieces still have administrative context.
            # A closed CPIS copy applies even when another copy matches the filter.
            if not (population == 'all' or (population_counts[population] > 0 if plan_state else
                                             closure['active'] == (population == 'active'))):
                continue
            # A copy: the cached entries are shared by every request (full CPIS summary: generation.complete).
            summaries.append({**item, 'population_unknown_states': unknown_states, 'plan': plan,
                              'population_counts': population_counts})
        ofs = [row['of'] for row in summaries]
        production_counts, prep_counts, conference_counts = {}, {}, {}
        if ofs:
            for row in conn.execute('''SELECT 'OF'||regexp_replace(p.production_order,'^OF','') AS of,
                    count(*) records FROM mes_kanban.production_records p
                    JOIN mes_kanban.validated_sheets v USING(sheet_uid)
                    WHERE p.production_order IS NOT NULL AND v.source_app=ANY(%s)
                    AND 'OF'||regexp_replace(p.production_order,'^OF','')=ANY(%s) GROUP BY 1''',
                    (['kanban-mes-mtg2', 'kanban-mes'], ofs)).fetchall():
                production_counts[row['of']] = row['records']
            if _table(conn, 'planning_mtg', 'records'):
                for row in conn.execute('''SELECT production_order_no,count(*) records,
                        array_agg(DISTINCT record_status) statuses,array_agg(DISTINCT area) areas FROM planning_mtg.records
                        WHERE production_order_no=ANY(%s) GROUP BY 1''', (ofs,)).fetchall():
                    prep_counts[row['production_order_no']] = row
            if _table(conn, 'planning_mtg', 'reconciliations'):
                for row in conn.execute('''SELECT production_order_no,count(*) records
                        FROM planning_mtg.reconciliations
                        WHERE production_order_no=ANY(%s) GROUP BY 1''', (ofs,)).fetchall():
                    conference_counts[row['production_order_no']] = row['records']
        for item in summaries:
            plan_state = plan_counts.get(item['of'], {})
            # A closed imported plan does not cover additional local/PDF needs.
            item['execution_complete'] = (bool(plan_state) and not item['conflicts']
                and not document_counts.get(item['of']) and not prep_counts.get(item['of']) and all(
                value['complete'] is True for value in plan_state.values()))
            item['sources'] = sorted(set(item['plan']) | document_areas.get(item['of'], set())
                                     | set(prep_counts.get(item['of'], {}).get('areas') or []))
            item['area'] = ('ambas' if len(item['sources']) > 1 else
                            item['sources'][0] if item['sources'] else 'por_identificar')
            item['production_records'] = production_counts.get(item['of'], 0)
            item['preparation'] = prep_counts.get(item['of'])
            item['documents'] = document_counts.get(item['of'], 0)
            item['conferences'] = conference_counts.get(item['of'], 0)
        if pending_only:
            summaries = [item for item in summaries if not item['execution_complete']]
        summaries.sort(key=lambda item: item['of'] or '', reverse=True)
    return expected, 'direct' if direct else 'imported', population, summaries, generation


def _context_for_order(conn, of, version=None):
    direct = _direct_version(conn, version)
    rows = _order_rows(conn, direct, '', None, only_ofs=[of])
    rows = [{**row,'production_order_no':of} for row in rows if order_number(row['production_order_no']) == of]
    if not rows:
        from . import planning_order_population
        _, fallback = planning_order_population.read(conn, _latest_snapshots(conn), orders=[of])
        if of in fallback:
            return fallback[of], direct
        raise planning.PlanningError('A OF não foi encontrada nas fontes de Planeamento disponíveis.', 404)
    return _order_summary(rows), direct


def order_detail(of, *, version=None, conn=None):
    of = order_number(of)
    if not of:
        raise planning.PlanningError('Indica uma OF válida.')
    with (planning.connect(readonly=True) if conn is None else nullcontext(conn)) as conn:
        context, direct = _context_for_order(conn, of, version)
        snapshots = _latest_snapshots(conn)
        token = str(direct['id']) if direct else _fallback_token(snapshots)
        plans = conn.execute('''SELECT l.source_app,l.snapshot_id,l.plan_key,l.excel_row,l.production_order_no,
            l.component_ref,l.profile_type,l.material_type,l.material_description,l.length_mm,
            l.quantity_planned,l.quantity_made,l.remaining_quantity,l.remaining_valid,
            l.remaining_rule,l.closed_x,
            coalesce(nullif(l.cutting_machine,''),r.row_data->>'Máquina Corte') cutting_machine,
            l.planning_week,l.cut_date,
            jsonb_build_object('Ser.',r.row_data->'Ser.','Aboc.',r.row_data->'Aboc.',
                'Aborc.',r.row_data->'Aborc.','1ª Oper.',r.row_data->'1ª Oper.',
                '2ª Oper.',r.row_data->'2ª Oper.') operation_inputs
            FROM analytics_mtg.kanban_plan_lines l
            LEFT JOIN raw_mtg.plan_production_rows r ON r.snapshot_id=l.snapshot_id AND r.source_line_id=l.plan_key
            WHERE l.snapshot_id=ANY(%s) AND regexp_replace(trim(l.production_order_no),'^OF[ ._-]*','','i')=regexp_replace(%s,'^OF','','i') ORDER BY l.source_app,l.excel_row''',
            ([row['snapshot_id'] for row in snapshots.values()], of)).fetchall()
        produced = conn.execute('''SELECT p.id,p.sheet_uid,v.sheet_no,v.source_app,v.source_filename,
            v.source_page,p.row_index,p.sheet_date,p.validated_at,p.machine,p.model_ref,
            p.quantity,p.length_mm,p.profile_type,p.matched_plan_key,p.plan_snapshot_id,
            p.match_confidence,p.extra,p.full_profile,v.cross_check
            FROM mes_kanban.production_records p JOIN mes_kanban.validated_sheets v USING(sheet_uid)
            WHERE 'OF'||regexp_replace(p.production_order,'^OF','')=%s
              AND v.source_app=ANY(%s) ORDER BY p.sheet_date DESC,p.id DESC''',
            (of, ['kanban-mes-mtg2', 'kanban-mes'])).fetchall()
        children = {}
        if produced and _table(conn, 'mes_kanban', 'production_record_plan_refs'):
            for row in conn.execute('''SELECT * FROM mes_kanban.production_record_plan_refs
                    WHERE production_record_id=ANY(%s) ORDER BY production_record_id,plan_key''',
                    ([r['id'] for r in produced],)).fetchall():
                children.setdefault(row['production_record_id'], []).append(row)
        for row in produced:
            row['area'] = 'perfis' if row['source_app'] == 'kanban-mes-mtg2' else 'cantoneiras'
            check = next((check for check in (row.pop('cross_check') or {}).get('rows', [])
                          if check.get('row_index') == row['row_index']), {})
            row['frozen_identity'] = check.get('plan_identity') or {}
            row['plan_refs'] = children.get(row['id']) or check.get('plan_refs') or []
            row['counting_rule'] = 'expanded_refs' if row['plan_refs'] else 'production_record'
        missing_keys = {row['matched_plan_key'] for row in produced if row.get('matched_plan_key')
                        and not row['frozen_identity'] and not (row.get('extra') or {}).get('plan_identity')}
        if missing_keys:
            history = {}
            for line in conn.execute('''SELECT plan_key,source_app,production_order_no,
                    component_ref,profile_type,length_mm FROM analytics_mtg.kanban_plan_lines
                    WHERE plan_key=ANY(%s)''', (sorted(missing_keys),)).fetchall():
                history.setdefault(line['plan_key'], []).append(line)
            for row in produced:
                candidates = history.get(row.get('matched_plan_key'), [])
                if len(candidates) == 1 and candidates[0]['source_app'] == row['source_app']:
                    row['frozen_identity'] = candidates[0]
        from . import planning_original_production
        for area in planning.AREAS:
            produced.extend(planning_original_production.records(conn,area,of))
        _production_associations(produced, plans)
        planning_production.attach_operation_evidence(plans, produced)
        preparations = conn.execute('''SELECT id::text,area,component_ref,record_status,values_json,
                revision,actor,source_kind,source_version,updated_at FROM planning_mtg.records
                WHERE production_order_no=%s ORDER BY updated_at DESC''', (of,)).fetchall()
        reconciliations = conn.execute('''SELECT * FROM planning_mtg.reconciliations
                WHERE production_order_no=%s ORDER BY created_at DESC''', (of,)).fetchall() \
                if _table(conn, 'planning_mtg', 'reconciliations') else []
        need_conferences = conn.execute('''SELECT DISTINCT ON(c.need_id,c.operation_id) c.need_id,o.area,o.code operation,n.component_ref,c.accepted_required,c.accepted_remaining,c.actor,c.reason,c.created_at
            FROM planning_mtg.need_conferences c JOIN planning_mtg.needs n ON n.id=c.need_id JOIN planning_mtg.need_operations o ON o.id=c.operation_id
            WHERE n.production_order_no=%s ORDER BY c.need_id,c.operation_id,c.created_at DESC,c.id DESC''',(of,)).fetchall() if _table(conn,'planning_mtg','need_conferences') else []
    try:
        from .dossiers import store
        documents = [d for d in store.list_documents(limit=None) if order_number(d.get('production_order')) == of]
        pdf_perfis = any(d.get('perfis_piece_count', 0) for d in documents)
        documents = [{'id': d['id'], 'filename': d['filename'], 'status': d['status'],
                      'updated_at': d['updated_at']} for d in documents]
    except Exception:
        documents = []
        pdf_perfis = False
    context['sources'] = sorted({('perfis' if line['source_app'] == 'kanban-mes-mtg2' else 'cantoneiras')
                                for line in plans} | {p['area'] for p in preparations}
                               | ({'perfis'} if pdf_perfis else set()))
    result = _serial({'version': token, 'cpis_mode': 'direct' if direct else 'imported',
        'context': context, 'plan_lines': plans, 'production': produced,
        'preparations': preparations, 'reconciliations': reconciliations, 'need_conferences': need_conferences,
        'documents': documents})
    for line in result['plan_lines']:
        for operation in line['operations']:
            evidence = planning_production.conference_evidence(line, operation['operation'], token)
            if evidence:
                operation['evidence_fingerprint'] = hashlib.sha256(json.dumps(
                    evidence, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    for decision in result['reconciliations']:
        key = (decision.get('evidence_json') or {}).get('plan_line', {}).get('plan_key')
        lines = [line for line in result['plan_lines']
                 if key and line.get('plan_key') == key and line.get('component_ref') == decision['component_ref']
                 and ('perfis' if line.get('source_app') == 'kanban-mes-mtg2' else 'cantoneiras') == decision['area']]
        if len(lines) != 1:
            decision['valid'] = False
            decision['review_reason'] = 'A identidade técnica já não tem uma correspondência única.'
            continue
        line = lines[0]
        evidence = planning_production.conference_evidence(line, decision['operation'], token)
        current = hashlib.sha256(json.dumps(evidence, sort_keys=True,
                                 ensure_ascii=False).encode()).hexdigest()
        decision['valid'] = current == decision['evidence_fingerprint']
        decision['review_reason'] = None if decision['valid'] else 'O plano, a produção ou a versão CPIS mudou.'
    return result


def save_reconciliation(payload):
    if not isinstance(payload, dict):
        raise planning.PlanningError('A conferência é inválida.')
    try:
        request_id = uuid.UUID(str(payload.get('request_id')))
    except ValueError:
        raise planning.PlanningError('A conferência não tem um identificador válido.') from None
    of = order_number(payload.get('of'))
    area = planning.check_area(payload.get('area'))
    component = str(payload.get('component_ref') or '').strip()
    operation = str(payload.get('operation') or '').strip()
    from .planning_registration import human_actor
    actor = human_actor(payload)
    reason = str(payload.get('reason') or '').strip()
    if not all((of, component, operation in ('corte', 'abocardar'), actor, reason)):
        raise planning.PlanningError('Indica a peça, operação, responsável e motivo da conferência.')
    detail = order_detail(of)
    if payload.get('cpis_version') != detail['version']:
        raise planning.PlanningError('A origem mudou. Reabre a OF antes de conferir.', 409)
    line = next((line for line in detail['plan_lines'] if line['plan_key'] == payload.get('plan_key')
                 and line['component_ref'] == component
                 and ('perfis' if line['source_app'] == 'kanban-mes-mtg2' else 'cantoneiras') == area), None)
    if not line:
        raise planning.PlanningError('Seleciona a peça e geometria na lista da OF antes de conferir.', 409)
    evidence = planning_production.conference_evidence(line, operation, detail['version'])
    if not evidence:
        raise planning.PlanningError('A operação ainda precisa de identificação antes da conferência.', 409)
    fingerprint = hashlib.sha256(json.dumps(evidence, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if payload.get('evidence_fingerprint') != fingerprint:
        raise planning.PlanningError('A evidência mudou. Reabre a conferência para comparar os valores atuais.', 409)
    def number(name):
        value = payload.get(name)
        if value in (None, ''):
            return None
        try:
            result = Decimal(str(value).replace(',', '.'))
        except Exception:
            raise planning.PlanningError('As quantidades conferidas têm de ser números válidos.') from None
        if not result.is_finite() or result < 0 or result != result.to_integral_value():
            raise planning.PlanningError('As quantidades conferidas têm de ser inteiros não negativos.')
        return result
    with planning.connect() as conn:
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (str(request_id),))
        old = conn.execute('SELECT * FROM planning_mtg.reconciliations WHERE request_id=%s',
                           (request_id,)).fetchone()
        if old:
            same = (old['production_order_no'] == of and old['area'] == area
                    and old['component_ref'] == component and old['operation'] == operation
                    and old['actor'] == actor and old['reason'] == reason
                    and old['evidence_fingerprint'] == fingerprint
                    and old['accepted_required'] == number('accepted_required')
                    and old['accepted_remaining'] == number('accepted_remaining'))
            if not same:
                raise planning.PlanningError('Este pedido já foi usado para outra conferência.', 409)
            return _serial({'replayed': True, 'reconciliation': old})
        conn.execute('''INSERT INTO planning_mtg.reconciliations
            (request_id,production_order_no,area,component_ref,operation,accepted_required,
             accepted_remaining,macro_snapshot_id,cpis_version,evidence_fingerprint,
             evidence_json,actor,reason) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
            (request_id, of, area, component, operation, number('accepted_required'),
             number('accepted_remaining'), line['snapshot_id'],
             detail['version'], fingerprint, Jsonb(evidence), actor, reason))
    return {'replayed': False, 'request_id': str(request_id)}
