"""Version 2 immutable scheduling inputs for both sectors, with automatic assignments."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
import math
import re
import uuid

from .. import planning, planning_needs as needs, planning_calendars
from ..raw.capacity import estimate
from . import research, machines
from .calendar import option_fit
from .contracts import utc, minute


def identity(row):
    # Includes the occurrence, so repeated operation codes never share a decision.
    signature = needs.digest([row.get('assinatura'), row.get('revisao_desenho'), row['referencia_original']])
    ident = str(uuid.uuid5(uuid.NAMESPACE_URL, needs.digest([
        'planning-occurrence-v2', row['setor'], row['ordem_codigo'], row['linha_origem'],
        row['ocorrencia'], row['operacao_codigo'], signature])))
    return ident, signature


def balance(row):
    confirmed, documented = row.get('saldo_confirmado'), row.get('saldo_documental')
    value = confirmed if confirmed is not None else documented
    coherent = row.get('estado_quantidade') in ('coerente', 'fonte_unica')
    reasons = []
    if not coherent:
        reasons.append('Quantidade autorizada por confirmar.')
    if value is None or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        reasons.append('Saldo da operação por confirmar.'); value = None
    application=row.get('application_balance_evidence') or {}
    if application:
        reasons += application.get('coverage_reasons') or application.get('reasons') or []
    return {'planning_remaining': value if coherent else None, 'reconciled_remaining': confirmed,
            'balance_provisional': confirmed is None,
            'balance_origin': application.get('origin') or application.get('balance_origin') or ('Reconciliado' if confirmed is not None else 'Excel provisório'), 'reasons': reasons}


def _resources(metadata, configs, start, end):
    by_code = {}; by_id = {}
    objects = [r for r in configs if r['kind'] == 'resource']
    for r in metadata['resources']:
        explicit = [o for o in objects if o['definition'].get('research_code') == r['codigo']]
        # Old resources may already identify this exact physical machine by alias.
        aliases = {a['nome_origem'] for a in metadata['aliases'] if a['recurso_codigo'] == r['codigo']} | {r['designacao']}
        matched = explicit or [o for o in objects if any(a.get('name') in aliases for a in o['definition'].get('aliases', []))]
        obj = matched[0] if len(matched) == 1 else None
        d = obj['definition'] if obj else {}
        rid = str(obj['id']) if obj else research.resource_id(r['codigo'])
        resource = {'id': rid, 'code': r['codigo'], 'name': r['designacao'], 'type': r['tipo'],
                    'operations': d.get('operations', []), 'revision': obj.get('revision') if obj else None,
                    'confirmed': bool(d.get('confirmed')), 'technical_rules': d.get('technical_rules', []),
                    'capacity_override': d.get('capacity_override') or {},
                    'windows': [], 'calendar_status': 'unknown', 'aliases': d.get('aliases', []),
                    'capacity': (r.get('quantidade_operadores') or 0) if r['tipo'] == 'grupo_operadores' else 1,
                    'mapping_conflict': len(matched) > 1}
        by_code[r['codigo']] = resource; by_id[rid] = resource
    for config in configs:
        d = config['definition']; rid = str(d.get('resource_id'))
        if config['kind'] == 'calendar' and d.get('confirmed') and rid in by_id and by_id[rid]['confirmed'] and 'weekly_windows' in d:
            by_id[rid]['windows'].extend(planning_calendars.expand(d))
            by_id[rid]['calendar_status'] = 'closed'
    for resource in by_id.values():
        resource['windows'] = [{'start': a, 'end': b} for a,b in sorted({(w['start'],w['end']) for w in resource['windows'] if utc(w['end']) > start and utc(w['start']) < end})]
        if resource['windows']:
            resource['calendar_status'] = 'available'
    # A single post budget, never the sum of its component saws.
    for rel in metadata['relations']:
        if rel['relacao'] == 'partilha_operadores' and rel['pai'] in by_code and rel['filho'] in by_code:
            pool, member = by_code[rel['pai']], by_code[rel['filho']]
            if pool['type'] != 'grupo_operadores':
                pool, member = member, pool
            if pool['type'] == 'grupo_operadores':
                member.setdefault('shared_demands', {})[pool['id']] = 1
    for rel in metadata['relations']:
        if rel['relacao'] == 'compoe' and rel['pai'] in by_code and rel['filho'] in by_code:
            post, equipment = by_code[rel['pai']], by_code[rel['filho']]
            if post['type'] != 'posto':
                post, equipment = equipment, post
            if post['type'] == 'posto':
                # A job selected at post level also occupies this same pool.
                post.setdefault('shared_demands', {})[post['id']] = 1
                equipment.setdefault('shared_demands', {}).update(post.get('shared_demands', {}))
    return by_code, by_id


def _templates(package):
    rates = defaultdict(list)
    for r in package['metadata']['rates']:
        rates[(r['recurso_codigo'], r['operacao_codigo'])].append({
            'method': {'mm2/h':'area_hour','mm²/h':'area_hour','m/h':'metres_hour','un./h':'units_hour','min/un.':'minutes_unit'}.get(r['unidade']),
            'value': r['valor'], 'setup_minutes': 0, 'source': r['fonte'],
            'valid_from': None, 'valid_until': None, 'profile': None})
    # Keep all different documented rates/scopes, with how many lines wrote each one; the
    # duration chooses explicitly between them (current machine's own rate, else the weighted median).
    for row in package['rows']:
        rate = row.get('rate_m_per_hour')
        if row['setor'] == 'MTG3' and row['fase'] == 'principal' and row.get('recurso_atual') and rate and rate > 0:
            template = {'method': 'metres_hour', 'value': rate, 'setup_minutes': 0,
                        'source': 'Excel MTG3 · ' + row['snapshot_id'],
                        'profile': row.get('perfil'), 'valid_from': None, 'valid_until': None}
            key = (row['recurso_atual'], row['operacao_codigo'])
            found = next((t for t in rates[key] if {k: v for k, v in t.items() if k != 'lines'} == template), None)
            if found:
                found['lines'] = found.get('lines', 1) + 1
            else:
                rates[key].append({**template, 'lines': 1})
    return rates


def median_template(templates):
    """Weighted median of divergent documentary speeds; a stated estimate, never a confirmed rate."""
    ordered = sorted(templates, key=lambda t: t['value'])
    total = sum(t.get('lines', 1) for t in ordered)
    seen = 0
    for template in ordered:
        seen += template.get('lines', 1)
        if seen * 2 >= total:
            values = ', '.join(f"{t['value']:g} m/h ({t.get('lines', 1)})" for t in ordered)
            return {**template, 'source': template['source'] + ' · mediana de velocidades divergentes',
                    'divergent_values': values}
    return ordered[-1]


def _duration(row, candidate, resource, configs, templates, started_at, context=None, *, rate_day=None):
    from .inputs import _option
    q = balance(row)['planning_remaining']
    if q is None or q <= 0:
        return None
    raw = row.get('raw') or {}
    area = research.AREAS[row['setor']]
    op = row['operacao_codigo']
    section = next((planning._number(raw.get(k)) for k in ('Área de Seção de Corte Unit. [mm2]', 'Área de Seção de Corte Unit. [mm²]') if planning._number(raw.get(k)) is not None), None)
    if row.get('application_row_key'):
        section = row.get('section_unit')
    values = {'quantity_to_plan':q, 'length_mm':row.get('comprimento_mm'), 'section_unit':section,
              'profile':row.get('perfil'), 'grade':row.get('qualidade'), 'material_type':row.get('material_type')}
    names = {op, op.removeprefix('CPIS:'), 'corte' if row['fase'] == 'principal' else op,
             'abocardar' if op == 'LOCAL:ABOCARDAR' else op}
    rates = [c['definition'] for c in configs if c['kind'] == 'rate' and c['definition'].get('confirmed')
             and str(c['definition'].get('resource_id')) == resource['id']
             and c['definition'].get('area') == area and str(c['definition'].get('operation')) in names
             and all(not c['definition'].get(k) or c['definition'][k] == row.get(column)
                     for k, column in [('profile', 'perfil'), ('material_type', 'material_type'), ('grade','qualidade')])]
    day = rate_day or str(started_at)[:10]
    rates = [r for r in rates if (not r.get('valid_from') or r['valid_from'] <= day) and (not r.get('valid_until') or r['valid_until'] >= day)]
    source = 'Manual'
    if len(rates) > 1:
        candidate['duration_reason'] = 'Taxas confirmadas sobrepostas.'; return None
    history = None
    if not rates and context and resource['confirmed']:
        alias = next((a['name'] for a in resource.get('aliases',[]) if a['area']==area and (area,a['name']) in context.aliases),None)
        historical_op = ('corte' if row['fase']=='principal' else 'abocardar') if area=='perfis' and op.startswith('LOCAL:') else candidate['proposed_code'].removeprefix('CPIS:')
        if alias:
            history = context.rate({**values,'machine':alias},area,historical_op,day,as_of=min(date.fromisoformat(day),date.fromisoformat(str(started_at)[:10])))
            if history.get('source')=='Histórico':
                rates = [history['rate']]; source = 'Histórico'
    if not rates:
        own_estimate=row.get('documentary_rate') or {}
        if row.get('application_row_key') and candidate['resource_code']==row.get('recurso_atual') and own_estimate.get('source')=='Excel provisório' and own_estimate.get('rate'):
            own_rate=dict(own_estimate['rate'])
            if own_estimate.get('factor',1)>1:
                own_rate['value']/=own_estimate['factor']
            rates=[own_rate]
            source='Excel provisório'
    if not rates:
        rates = [r for r in templates.get((candidate['resource_code'], candidate['proposed_code']), [])
                 if not r.get('profile') or str(r['profile']).strip() == str(row.get('perfil') or '').strip()]
        if len({r['value'] for r in rates}) > 1:
            # The current row's rate describes its current machine only; for another machine the
            # weighted median of what the workbook wrote for this profile is a stated estimate.
            own = row.get('rate_m_per_hour') if candidate['resource_code'] == row.get('recurso_atual') else None
            rates = [r for r in rates if r['value'] == own][:1] if own else [median_template(rates)]
            if not own:
                candidate['duration_note'] = 'Velocidades divergentes no Excel para esta máquina e perfil: ' + rates[0]['divergent_values'] + '; usada a mediana.'
        source = 'Excel provisório'
    if not rates:
        candidate['duration_reason'] = 'Taxa da máquina/operação por confirmar.'; return None
    rate = rates[0]
    if row['fase'] == 'principal' and row['setor'] == 'MTG2' and op != 'LOCAL:PRINCIPAL' and rate['method'] == 'area_hour':
        candidate['duration_reason'] = 'Taxa de corte não abrange toda a rota.'; return None
    hours, reason = estimate(values, rate, op)
    if reason:
        candidate['duration_reason'] = reason; return None
    result = _option(resource['id'], {'hours': hours, 'quantity': q, 'source': source, 'rate': rate}, source, started_at)
    if result:
        result['option_id'] = needs.digest([result['option_id'],candidate['proposed_code']])
        result.update(eligibility=candidate['eligibility'], resource_code=candidate['resource_code'],
                      proposed_code=candidate['proposed_code'], shared_demands=resource.get('shared_demands', {}))
        if source == 'Histórico':
            result.update(history_hash=history['history_hash'], history=history['history'], excluded_cohorts=history['excluded_cohorts'])
        elif source != 'Manual':
            result['assumptions'] = ['Taxa documental; preparação e movimentação por confirmar.'] + \
                ([candidate['duration_note']] if candidate.get('duration_note') else [])
    return result


def member_selection_digest(c):
    """Member decisions of the Carteira (plano de 02/10/2026); absent while there are none, so the
    references of existing scenarios stay identical until the first member decision."""
    from ..sector.decisions import read_members
    rows = [{k: r[k] for k in ('area', 'member_key', 'decision', 'revision')} for r in read_members(c)]
    return {'member_selection_digest': needs.digest(needs.serial(rows))} if rows else {}


def machine_choice_digest(c):
    """Máquinas escolhidas na Carteira e conjuntos de famílias; ausente enquanto não houver nenhum."""
    from ..sector import machine_choice
    contexts = [machine_choice.context(area, conn=c) for area in planning.AREAS]
    if not any(ctx['members'] or ctx['sets'] for ctx in contexts):
        return {}
    return {'machine_choice_digest': needs.digest([ctx['digest'] for ctx in contexts])}


def references(c):
    h = research.head(c)
    configs = c.execute("SELECT id,kind,revision,definition,name,area FROM planning_mtg.raw_objects WHERE kind=ANY(%s) AND NOT archived ORDER BY id", (['resource', 'calendar', 'rate', 'worked_hours'],)).fetchall()
    selection = c.execute('SELECT area,production_order_no,reference,decision,revision FROM planning_mtg.sector_selection ORDER BY area,production_order_no,reference').fetchall()
    from . import cpis_tables
    cp=c.execute('SELECT version_id FROM planning_mtg.gantt_source_heads WHERE provider=%s',(cpis_tables.PROVIDER,)).fetchone()
    from ..raw import query
    generations = []; pending = False
    for area in planning.AREAS:
        for dataset in ('planning', 'production'):
            try:
                g = query.generation(c, area, dataset=dataset)
                generations.append([area,dataset,g['id']])
                # Production publications carry the core planning metadata;
                # their inherited aggregate flag is not a second pending job.
                pending |= bool(g['metadata'].get('source_refresh_pending') or
                    dataset=='planning' and g['metadata'].get('aggregates_pending'))
            except planning.PlanningError as exc:
                if exc.status != 503:
                    raise
    from ..sector import priority, assignments
    return {'schema_version': 2, 'provider': research.PROVIDER, 'research_version': h['version_id'],
            'configuration_digest': needs.digest(needs.serial(configs)),
            'selection_digest': needs.digest(needs.serial(selection)), 'application_generations': generations,
            **member_selection_digest(c), **machine_choice_digest(c),
            'cpis_tables_version':cp['version_id'] if cp else None,'sources_pending': pending,
            'priority_digest': priority.digest(c), 'machine_decisions_digest': assignments.digest(c)}


def capture(c, definition, started_at, *, expected_references=None):
    from .inputs import reconcile_pins, reconcile_decisions
    refs = references(c)
    if expected_references and refs != expected_references:
        raise planning.PlanningError('As fontes ou decisões mudaram antes do cálculo.', 409)
    if expected_references and refs['sources_pending']:
        raise planning.PlanningError('Aguarda a publicação dos cálculos e saldos.', 409)
    package = research.load(c, refs['research_version'])
    metadata = package['metadata']
    start = utc(started_at).replace(second=0, microsecond=0)
    horizon = definition.get('horizon_weeks', 12) * 7 * 1440
    end = start + timedelta(minutes=horizon)
    areas = definition.get('areas') or ['perfis', 'cantoneiras']
    from ..sector import scope
    selection = scope.read(c)
    if selection is None:  # um Decisions só com decisões por membro é «vazio»: não o trocar por {}
        from ..sector.decisions import Decisions
        selection = Decisions()
    planning_lines, selection_pending = scope.planning_lines(c,selection,areas)
    # Chaves de cada linha (atual + importações anteriores) e máquina efetiva (Carteira → Tabela → conjunto).
    record_info = {r['row_key']: (scope.member_keys(r), r.get('effective_machine') or {}) for r in planning_lines}
    selected_rows, unmatched_lines = scope.research_rows(package['rows'],planning_lines)
    balances = research.application_balances(c,selected_rows, records=planning_lines)
    rows = [{**row,**balances.get(row['operacao_id'],{})} for row in selected_rows]
    configs = c.execute("SELECT * FROM planning_mtg.raw_objects WHERE kind=ANY(%s) AND NOT archived ORDER BY id", (['resource', 'calendar', 'rate', 'worked_hours'],)).fetchall()
    codes, resources = _resources(metadata, configs, start, end)
    aliases = {(area,a['nome_origem']):a['recurso_codigo'] for a in metadata['aliases'] for area in planning.AREAS}
    for code,resource in codes.items():
        for alias in resource.get('aliases',[]):
            aliases[(alias['area'],alias['name'])]=code
        for area in planning.AREAS:
            aliases.setdefault((area,resource['name']),code)
    new_rows,new_dependencies = scope.local_rows(unmatched_lines,aliases)
    rows += new_rows
    rows=[{**r,'documentary_source_machine':r.get('maquina_original'),'documentary_source_resource':r.get('recurso_atual'),
        **({'material_type':r['current_planning']['material_type']} if r.get('current_planning',{}).get('material_type') else {}),
        **({'maquina_original':r['current_planning']['machine'],'recurso_atual':aliases.get((research.AREAS[r['setor']],r['current_planning']['machine']))} if 'machine' in r.get('current_planning',{}) else {}),
        **({'data_corte_prevista':r['current_planning']['cut_date']} if r.get('current_planning',{}).get('cut_date') else {})} for r in rows]
    for i, r in enumerate(rows):
        info = record_info.get(r.get('matched_application_key') or r.get('application_row_key'))
        if r['fase'] == 'principal' and info and info[1].get('source') in ('carteira', 'conjunto'):
            code = next((k for k, res in codes.items() if res.get('id') == info[1].get('resource_id')), None)
            rows[i] = {**r, 'maquina_original': info[1]['machine'], 'recurso_atual': code}
    from . import cpis_tables
    cpis_package=cpis_tables.load(c)
    cpis_evidence=cpis_tables.evidence(cpis_package,rows)
    raw_rows = {row['operacao_id']: row for row in rows}
    from ..raw.productivity import Context
    context = Context(c,configs)
    index = machines.EvidenceIndex(metadata, package['rows'] + new_rows); templates = _templates(package)
    identities = []
    for row in rows:
        if research.AREAS[row['setor']] in areas:
            uid, signature = identity(row)
            identities.append({'key':'v2:'+uid, 'of':row['ordem_codigo'], 'operation':row['operacao_codigo'],
                'area':research.AREAS[row['setor']], 'occurrence':row['ocorrencia'], 'technical_signature':signature,
                'planning_key':'v2-item:'+row['item_id'], 'selection_aliases':[row['linha_origem']]})
    overrides, override_transfers, override_orphans = reconcile_decisions(identities,
        definition.get('machine_overrides', {}), definition.get('override_bindings', {}))
    from ..sector import priority, assignments
    sector_policies = priority.policies(c); sector_overrides = priority.overrides(c)
    sector_decisions = assignments.resolver(c)
    raw_to_key = {}; operations = []; orders = defaultdict(list)
    # Machine of the OF's other lines with the same operation and profile (shared set-up), when a line has none.
    peers = defaultdict(lambda: defaultdict(int))
    from ..sector.estimates import series_process
    group_quantities = defaultdict(list)
    for r in rows:
        if r['setor'] == 'MTG3' and r['fase'] == 'principal' and r.get('quantidade_base'):
            group_quantities[(r['ordem_codigo'], r['operacao_codigo'], re.sub(r'\s', '', str(r.get('perfil') or '').upper()))].append(r['quantidade_base'])
    processes = {k: series_process(sum(v) / len(v), k[2]) for k, v in group_quantities.items()}
    for r in rows:
        if r.get('recurso_atual') in codes:
            peers[(r['ordem_codigo'], r['operacao_codigo'], re.sub(r'\s', '', str(r.get('perfil') or '').upper()))][codes[r['recurso_atual']]['id']] += 1
    for row in rows:
        area = research.AREAS[row['setor']]
        if area not in areas:
            continue
        uid, signature = identity(row); key = 'v2:' + uid
        raw_to_key[row['operacao_id']] = key
        b = balance(row); remaining = b['planning_remaining']
        started = bool((row.get('contador_excel') or 0) > 0 or row.get('execution_started')) and remaining != 0
        execution_conflict = started and row.get('documentary_source_resource') and row.get('recurso_atual') != row['documentary_source_resource']
        if execution_conflict:
            row={**row,'recurso_atual':row['documentary_source_resource'],'maquina_original':row['documentary_source_machine']}
        raw = row.get('raw') or {}
        # Extract a grade only when the original text explicitly contains it.
        grade = re.search(r'\bS\d{3}(?:\s?J[012R])?(?:\s?H)?\b', str(raw.get('Des. Material') or ''), re.I)
        row = {**row, 'qualidade': row.get('qualidade') or (grade.group(0).upper() if grade else None)}
        candidates = index.candidates(row, codes)
        source_rid = codes.get(row.get('recurso_atual'), {}).get('id')
        # One sector policy for every engine: MTG3 by Data Corte, MTG2 by usable Picking.
        # An unconfirmed Picking year stays out unless the scenario confirms it.
        year = definition.get('picking_year_by_of', {}).get(row['ordem_codigo']) or row.get('ano_picking')
        marks = priority.milestones_from_values(
            {'cut_date': row.get('data_corte_prevista'), 'picking_week': row.get('semana_picking'),
             'nao_galvaniza_indicado': row.get('nao_galvaniza_indicado')}, raw, picking_year=year,
            picking_at=definition.get('picking_deadline_by_of', {}).get(row['ordem_codigo']),
            assumed_year=sector_policies[area].get('assume_picking_year'))
        principal = row['fase'] == 'principal'
        from ..sector.portfolio import signals_of
        signals=signals_of(row.get('current_planning',{}).get('designation') or raw.get('Designação') or '',
            row.get('current_planning',{}).get('notes') or raw.get('Descrição') or '', '', '', None)
        urgent = key in definition.get('urgent', []) or row['ordem_codigo'] in definition.get('urgent', []) or signals['prioridade'] is not None
        due = priority.resolve(area, 'principal' if principal else 'following', marks, policy=sector_policies[area],
            override=priority.override_for(sector_overrides, area, row['ordem_codigo'], row['referencia_original']), urgent=urgent)
        picking = (marks['picking'] or {}).get('at')
        galv = marks['galvanizing'].isoformat() if marks['galvanizing'] else None
        forecast = row.get('data_corte_prevista') if principal else None
        deadline = due['priority_date']
        all_options = []
        for candidate in candidates:
            resource = resources.get(candidate.get('resource_id'))
            # A máquina do planeador conta mesmo fora da ficha: precisa também de duração.
            if not resource or (candidate['eligibility'] == 'excluded' and candidate.get('resource_id') != source_rid):
                continue
            if resource['mapping_conflict']:
                candidate.update(eligibility='excluded', reasons=['Correspondência de recurso ambígua.']); continue
            days = {start.date().isoformat()} | {cfg['definition']['valid_from'] for cfg in configs if cfg['kind']=='rate'
                and str(cfg['definition'].get('resource_id'))==resource['id'] and cfg['definition'].get('valid_from')
                and start.date().isoformat()<cfg['definition']['valid_from']<end.date().isoformat()}
            durations = {}
            for day in sorted(days):
                duration = _duration(row,candidate,resource,configs,templates,start.isoformat(),context,rate_day=day)
                if duration:
                    durations[duration['option_id']] = duration
            candidate['durations'] = list(durations.values())
            option = min(durations.values(),key=lambda o:(o.get('earliest_minute',0)+o['duration_minutes'],o['option_id'])) if durations else None
            candidate['duration'] = option
            if option:
                all_options.extend(durations.values())
                found = option_fit({'started_at':start.isoformat(),'horizon_minutes':horizon,'resources':resources},option,option['earliest_minute'],[],{})
                if found:
                    candidate['finish_minute'] = found['end']
                    candidate['predicted_finish_without_queue'] = (start+timedelta(minutes=found['end'])).isoformat()
                    candidate['lateness_minutes'] = max(0, found['end'] - minute(deadline, start.isoformat())) if deadline else 0
        override = overrides.get(key)
        override_rid = override.get('resource_id') if isinstance(override, dict) else override
        # Scenario choice first; then the sector's group decisions and saved preferences.
        scenario_rid = override_rid
        sector = None if override_rid else sector_decisions.lookup(area, row, signature, candidates)
        if sector and sector['mode'] == 'assign':
            override_rid = sector['resource_id']
        from ..sector.estimates import peer_machine
        own = dict(peers[(row['ordem_codigo'], row['operacao_codigo'], re.sub(r'\s', '', str(row.get('perfil') or '').upper()))])
        if source_rid in own:
            own[source_rid] -= 1
        peer = None if source_rid else peer_machine(own, {o.get('resource_id') for o in candidates if o['eligibility'] != 'excluded'})
        group = (row['ordem_codigo'], row['operacao_codigo'], re.sub(r'\s', '', str(row.get('perfil') or '').upper()))
        selected, reason = machines.choose(candidates, source_rid, override=override_rid, peer=peer,
                                           process=None if source_rid else processes.get(group))
        if sector and sector['mode'] == 'prefer':
            preferred = next((o for o in candidates if o.get('resource_id') == sector['resource_id'] and o['eligibility'] != 'excluded'), None)
            if preferred:
                selected, reason = preferred, 'Preferência do setor: ' + sector['origin']
            else:
                reason += ' · preferência do setor não aplicável a esta ocorrência'
        elif sector and sector['mode'] == 'assign':
            reason = ('Decisão do setor: ' + sector['origin']) if selected else 'Decisão do setor incompatível ou sem correspondência'
        if started:
            selected = next((o for o in sorted(candidates, key=lambda o: o['eligibility'] == 'excluded') if o.get('resource_id') == source_rid), None)
            reason = 'Trabalho iniciado conserva a máquina documentada'
        # A máquina escolhida pelo planeador vale como confirmação técnica para esta ocorrência.
        planner = bool(selected) and bool(source_rid) and selected.get('resource_id') == source_rid and (not override_rid or override_rid == source_rid)
        info = record_info.get(row.get('matched_application_key') or row.get('application_row_key'))
        decision = scope.decision(selection,area,row['ordem_codigo'],row['referencia_original'],
                                  info[0] if info else [k for k in (row.get('matched_application_key'),row.get('application_row_key'),row.get('linha_origem')) if k])
        reasons = list(b['reasons'])
        if execution_conflict:
            reasons.append('A máquina no registo diverge do trabalho iniciado; conferir execução.')
        if row.get('source_ambiguity'):
            reasons.append('Correspondência a várias linhas documentais por rever.')
        if row.get('route_review_required'):
            reasons.append('Operação ou aplicabilidade da rota por confirmar.')
        cp=cpis_evidence.get(row['operacao_id'])
        if cp and cp['status']=='correspondencia_documental_unica':
            route=[str(r['codope']) for r in cp['route']]
            expected=[code.removeprefix('CPIS:') for code in index.routes[row['item_id']]]
            if row['setor']=='MTG3' and route!=expected:
                reasons.append('Rota CPIS atual difere da informação de planeamento.')
        if started and override_rid and override_rid != source_rid:
            reasons.append('Escolha manual contradiz trabalho iniciado.')
        if sector and sector.get('conflict'):
            reasons.append(sector['conflict'])
        if row['estado_documental'] != 'aberta':
            reasons.append('Estado da OF por confirmar.')
        if decision != 'selected':
            continue
        included = definition.get('included_operations')
        if included is not None and key not in included:
            reasons.append('Operação fora da seleção do cenário.')
        if override_rid and not selected:
            reasons.append(reason)
            if scenario_rid:
                override_orphans.append(key)
        if started and scenario_rid and scenario_rid != source_rid:
            override_orphans.append(key)
        if selected and selected['eligibility'] != 'admissible' and not planner:
            reasons.append('Compatibilidade técnica por confirmar.')
        if not selected:
            reasons.append('Máquina da operação por indicar.')
        if planner:
            options = [{**o, 'eligibility': 'admissible', 'eligibility_basis': 'escolha_do_planeador',
                        'open_conditions': selected.get('conditions', [])} for o in (selected.get('durations') or [])]
        else:
            options = [o for o in all_options if o['eligibility'] == 'admissible' and (not override_rid or o['resource_id'] == override_rid)
                       and (not started or o['resource_id'] == source_rid)]
        if remaining and not options:
            reasons.append('Duração admissível por confirmar.')
        if options and not any(resources[o['resource_id']]['windows'] for o in options):
            reasons.append('Calendário horário por confirmar.')
        # Shared operators require their own confirmed availability.
        for option in options:
            if any(not resources[p]['windows'] for p in option.get('shared_demands', {})):
                reasons.append('Calendário dos operadores partilhados por confirmar.')
            if any(resources[p].get('capacity',1)<=0 for p in option.get('shared_demands',{})):
                reasons.append('Capacidade dos operadores partilhados por confirmar.')
        op = {'key': key, 'operation_uid': uid, 'planning_key': 'v2-item:' + row['item_id'],
              'area': area, 'sector': row['setor'], 'operation_id': row['operacao_codigo'],
              'operation': row['operacao_codigo'], 'occurrence': row['ocorrencia'], 'of': row['ordem_codigo'],
              'reference': row['referencia_original'], 'line': row['excel_linha'], 'technical_signature': signature,
              'technical': {'profile': row.get('perfil'), 'grade': row.get('qualidade'), 'material_type':row.get('material_type'), 'length_mm': row.get('comprimento_mm'), 'revision': row.get('revisao_desenho')},
              'quantity_required': row['quantidade_base'], **{k: v for k, v in b.items() if k != 'reasons'},
              'source_machine': row.get('maquina_original'), 'source_resource_id': source_rid, 'started': started,
              'source_duration': {'hours': (selected or {}).get('duration', {}).get('duration_hours') if (selected or {}).get('duration') else None, 'quantity': remaining, 'origin': ((selected or {}).get('duration') or {}).get('duration_origin')},
              'assignment': {'mode': 'manual' if override_rid else 'preference' if sector and sector['mode']=='prefer' and selected and selected.get('resource_id')==sector['resource_id'] else 'automatic',
                             'resource_id': (selected or {}).get('resource_id'),
                             'proposed_code':(selected or {}).get('proposed_code'),
                             'eligibility': (selected or {}).get('eligibility'), 'reason': reason,
                             'basis': 'escolha_do_planeador' if planner else None,
                             'conditions': (selected or {}).get('conditions', []), 'override': override,
                             'sector_decision': sector},
              'candidates': candidates, 'options': options, 'selection_aliases': [row['linha_origem']],
              'state': 'complete' if remaining == 0 else 'blocked' if reasons else 'ready',
              'blocking_reasons': sorted(set(reasons)), 'provisional': b['balance_provisional'] or any(o['provisional'] for o in options),
              'priority_group': priority.group(due), 'priority': due,
              'deadline': deadline, 'predecessor_keys': [], 'predecessor_key': None,
              'evidence': {'snapshot': row['snapshot_id'], 'row': row['excel_linha'], 'operation_id': row['operacao_id'], 'raw': raw,
                           'variant_signature':row.get('assinatura'), 'drawing_revision':row.get('revisao_desenho'),
                           'application_balance':row.get('application_balance_evidence')},
              'cpis_evidence':cp,
              'observations': [], 'milestones': {'operation_forecast': forecast, 'cut_date': row.get('data_corte_prevista'),
                'picking': picking, 'galvanizing': galv, 'period_origin': 'Excel documental', 'period_year': None, 'period_week': None,
                'priority_day': due['priority_day'], 'priority_source': due['priority_source']}}
        operations.append(op); orders[op['of']].append(key)
    by_key = {o['key']: o for o in operations}
    for dep in metadata['dependencies'] + new_dependencies:
        before = raw_to_key.get(dep['predecessora']); after = raw_to_key.get(dep['sucessora'])
        if after:
            by_key[after]['predecessor_keys'].append(before or 'missing:' + dep['predecessora'])
            selected_id = by_key[after]['assignment']['resource_id']
            original = raw_rows.get(dep['sucessora']) if selected_id else None
            if original:
                original = {**original,'qualidade':by_key[after]['technical']['grade']}
            validated = bool(original and any('rota_por_validar' in r.get('resolved_conditions', [])
                             for r in machines.matching_rules(original, resources[selected_id])))
            if not dep['validada'] and not validated and by_key[after]['state'] != 'complete':
                by_key[after]['blocking_reasons'].append('Sequência operacional por validar.')
                by_key[after]['state'] = 'blocked'
    for op in operations:
        op['predecessor_key'] = next(iter(op['predecessor_keys']), None)
    pins, transfers, orphans = reconcile_pins(operations, definition.get('pins', {}), definition.get('pin_bindings', {}))
    availability = []
    for d in metadata['budgets']:
        if d['estado'] != 'confirmado' or d['recurso_codigo'] not in codes:
            continue
        day = date.fromisoformat(d['inicio_semana']); y, w, _ = day.isocalendar()
        availability.append({'resource_id': codes[d['recurso_codigo']]['id'], 'year': y, 'week': w,
                            'hours': d['capacidade'] if d['modo'] == 'horas' else None,
                            'capacity': d['capacidade'], 'unit': d['modo'], 'status': 'confirmed', 'evidence': [{'budget': d['id'], 'source': d['fonte']}]})
    for cfg in configs:
        d = cfg['definition']
        if cfg['kind'] == 'calendar' and d.get('confirmed') and str(d['resource_id']) in resources:
            availability = [a for a in availability if (a['resource_id'], a['year'], a['week']) != (str(d['resource_id']), d['year'], d['week'])]
            availability.append({'resource_id': str(d['resource_id']), 'year': d['year'], 'week': d['week'], 'hours': planning_calendars.available_hours(d), 'unit': 'hours', 'status': 'confirmed', 'alternatives': [], 'evidence': [{'object_id': str(cfg['id']), 'revision': cfg['revision']}]})
    return needs.serial({'schema_version': 2, 'area': areas[0], 'areas': areas, 'started_at': start.isoformat(),
        'horizon_minutes': horizon, 'source_references': refs, 'source_status':{**package['head'],'calculations_pending':refs['sources_pending'],
            'cpis_tables':cpis_package['head'] if cpis_package else None},
        'resources': resources, 'operations': operations, 'orders': dict(orders),
        'selection_summary':{'selected_orders':len({(r['area'],r['values_json'].get('of')) for r in planning_lines}),
            'orders_with_planning':len(orders),'pending':selection_pending,
            'rule':'Planear na Carteira → informação ativa de planeamento → escolha de máquina → proposta → aceitação.'},
        'pins': pins, 'pin_transfers': transfers, 'orphaned_pins': orphans,
        'machine_overrides': overrides, 'override_transfers': override_transfers,
        'orphaned_overrides': override_orphans, 'weekly_availability': availability,
        'accepted_bars': definition.get('accepted_bars', {}), 'possible_duplicates': metadata['possible_duplicates'],
        'historical_evidence': {context.history_hashes[k]:v for k,v in context.cache.items()}})
