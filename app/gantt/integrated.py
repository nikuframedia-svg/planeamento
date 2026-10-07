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
from .calendar import option_fit, limits_hours
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
    from ..sector.members import is_machine
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
                    # Máquina do setor no catálogo ou confirmada à mão: tem horários e histórico (07/10/2026).
                    'confirmed': bool(d.get('confirmed')) or is_machine(r.get('setor'), r.get('tipo')),
                    'technical_rules': d.get('technical_rules', []),
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


def section_unit(row):
    """Área de corte unitária (mm²) da operação, a mesma que a Carteira e a Carga usam.

    Auditoria 06/10 (GT-01, A7-4): primeiro a área da linha da aplicação (`section_unit` publicada);
    nas linhas só da camada de pesquisa, a unitária do Excel e, se vier vazia, a área total ÷ quantidade.
    Uma linha da aplicação sem área fica sem área (a aplicação anula-a de propósito quando a peça mudou).
    """
    if row.get('section_unit') is not None or row.get('application_row_key'):
        return row.get('section_unit')
    raw = row.get('raw') or {}
    unit = next((planning._number(raw.get(k)) for k in ('Área de Seção de Corte Unit. [mm2]', 'Área de Seção de Corte Unit. [mm²]') if planning._number(raw.get(k)) is not None), None)
    if unit is not None and unit > 0:
        return unit
    total, q = planning._number(raw.get('Área de Seção de Corte [mm2]')), planning._number(row.get('quantidade_base'))
    return total / q if total and total > 0 and q and q > 0 else None


def _documentary(row, candidate, templates):
    """Taxa documental (Excel) para esta máquina: a da própria linha publicada pela aplicação, senão a da folha.

    Auditoria 06/10 (GT-05): na máquina da estimativa publicada (a mesma que a Carga mostra) usa-se essa
    taxa do Excel, sem o fator ×3 da Thomas (decisão de 01/10: o Gantt não o aplica).
    """
    own_estimate = row.get('documentary_rate') or {}
    machine = row.get('documentary_rate_resource', row.get('recurso_atual'))
    if candidate['resource_code'] == machine and own_estimate.get('source') == 'Excel provisório' and (own_estimate.get('rate') or {}).get('value'):
        own_rate = dict(own_estimate['rate'])
        if own_estimate.get('factor', 1) > 1:
            own_rate['value'] /= own_estimate['factor']
        return [own_rate], None
    rates = [r for r in templates.get((candidate['resource_code'], candidate['proposed_code']), [])
             if not r.get('profile') or str(r['profile']).strip() == str(row.get('perfil') or '').strip()]
    if len({r['value'] for r in rates}) > 1:
        # The current row's rate describes its current machine only; for another machine the
        # weighted median of what the workbook wrote for this profile is a stated estimate.
        own = row.get('rate_m_per_hour') if candidate['resource_code'] == row.get('recurso_atual') else None
        rates = [r for r in rates if r['value'] == own][:1] if own else [median_template(rates)]
        if not own:
            return rates, 'Velocidades divergentes no Excel para esta máquina e perfil: ' + rates[0]['divergent_values'] + '; usada a mediana.'
    return rates, None


def _history_note(history):
    """Porque é que uma taxa histórica existente não foi usada (amostra pequena ou longe do Excel)."""
    found = (history or {}).get('history') or {}
    if found.get('value') is not None:
        return [f"Taxa histórica {found['value']:.6g} {found.get('unit') or ''} fora do intervalo plausível face ao Excel; usada a taxa do Excel."]
    return [found['reason']] if str(found.get('reason') or '').startswith('Amostra') else []


def _duration(row, candidate, resource, configs, templates, started_at, context=None, *, rate_day=None, timing=None):
    from .inputs import _option
    q = balance(row)['planning_remaining']
    if q is None or q <= 0:
        return None
    area = research.AREAS[row['setor']]
    op = row['operacao_codigo']
    section = section_unit(row)
    values = {'quantity_to_plan':q, 'length_mm':row.get('comprimento_mm'), 'section_unit':section,
              'profile':row.get('perfil'), 'grade':row.get('qualidade'), 'material_type':row.get('material_type')}
    from ..raw.productivity import match_rate, operation_names, timed
    names = operation_names(op, row['fase'] == 'principal', area)
    table = [c for c in configs if c['kind'] == 'rate']
    # A mesma escolha da Carteira, da Carga e do motor (productivity.match_rate): tabela de velocidades com
    # intervalo de espessura/área e «imediatamente superior», vigência pela data de hoje.
    day = rate_day or str(started_at)[:10]
    found = match_rate(table, resource['id'], area, names, {**values, 'grade': row.get('qualidade')}, day, tier='Confirmada')
    if found and found.get('conflict'):
        candidate['duration_reason'] = 'Taxas confirmadas sobrepostas.'; return None
    rates = [found['rate']] if found else []
    source = 'Manual'
    history = None
    documentary, note = _documentary(row, candidate, templates)
    if area == 'cantoneiras' and context is not None and (documentary or row['fase'] == 'principal'):
        # Velocidade do Excel em vigor = a mais recente da máquina (a mesma da Carteira, da Carga e do motor),
        # não a Mt\h de cada linha nem a mediana de velocidades antigas; na operação principal vale também numa
        # máquina sem velocidade escrita para este perfil/operação (como a Carteira, estimates.speed_for).
        from ..raw.productivity import current_excel
        recent = getattr(context, 'recent_excel', None) or {}
        machine = next((n for n in [candidate.get('resource_code')] + [a['name'] for a in resource.get('aliases', []) if a.get('area') == area]
                        if n and str(n).strip() in recent), None)
        if machine:
            base = documentary[0] if documentary else {'method': 'metres_hour', 'value': None, 'unit': 'm/h', 'setup_minutes': 0}
            documentary, note = [current_excel(base, recent, machine)], None
    excel_table = None if rates else match_rate(table, resource['id'], area, names, {**values, 'grade': row.get('qualidade')}, day, tier='Excel')
    table_conflict = bool(excel_table and excel_table.get('conflict'))
    if table_conflict:
        excel_table = None  # só bloqueia se o histórico não valer (o histórico ganha às linhas com origem Excel)
    if excel_table:
        # Linha da tabela com origem Excel (semente): vale como a velocidade do Excel, abaixo do histórico.
        documentary, note = [{**excel_table['rate'], 'source': 'Excel'}], None
    if not rates and context and resource['confirmed']:
        alias = next((a['name'] for a in resource.get('aliases',[]) if a['area']==area and (area,a['name']) in context.aliases),None)
        historical_op = ('corte' if row['fase']=='principal' else 'abocardar') if area=='perfis' and op.startswith('LOCAL:') else candidate['proposed_code'].removeprefix('CPIS:')
        if alias:
            # Mesma regra H10 da Carga (auditoria 06/10, GT-04): janela até hoje, amostra mínima e taxa
            # plausível face ao Excel desta máquina; fora disso fica a taxa do Excel.
            from zoneinfo import ZoneInfo
            today = utc(started_at).astimezone(ZoneInfo(planning.settings.display_timezone)).date()
            history = context.rate({**values,'machine':alias},area,historical_op,day,excel=documentary[0] if documentary else None,
                                   as_of=min(date.fromisoformat(day),today))
            if history.get('source')=='Histórico':
                rates = [history['rate']]; source = 'Histórico'
    if not rates and table_conflict:
        candidate['duration_reason'] = 'Taxas da tabela sobrepostas.'; return None
    if not rates:
        rates = documentary
        if note:
            candidate['duration_note'] = note
        source = 'Excel provisório'
    if not rates:
        candidate['duration_reason'] = 'Taxa da máquina/operação por confirmar.'; return None
    rate = rates[0]
    if row['fase'] == 'principal' and row['setor'] == 'MTG2' and op != 'LOCAL:PRINCIPAL' and rate['method'] == 'area_hour':
        candidate['duration_reason'] = 'Taxa de corte não abrange toda a rota.'; return None
    if timing is None:
        timing = (getattr(context, 'timing', None) or {}).get(area) if context else None
    hours, reason = estimate(values, timed(rate, source, timing), op)
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
                ([candidate['duration_note']] if candidate.get('duration_note') else []) + _history_note(history)
    return result


def _application_inputs(row, record, aliases):
    """Área de corte e taxa do Excel publicadas pela aplicação para esta operação (as da Carga).

    Auditoria 06/10 (GT-01, GT-05): as linhas da camada de pesquisa (Excel de 29/09) recebem a área
    unitária e a estimativa publicada da linha atual da aplicação; a máquina dessa estimativa fica
    explícita, para a taxa do Excel nunca passar para outra máquina (ex. escolhida na Carteira).
    """
    area = research.AREAS[row['setor']]
    if record is not None:
        from ..sector.occurrences import _estimate_name
        v = record.get('values_json') or {}
        name = _estimate_name(row['operacao_codigo'], area, row['fase'] == 'principal')
        found = [e for e in ((record.get('detail') or {}).get('calculation') or {}).get('operation_estimates') or []
                 if str(e.get('operation')) == name]
        row = {**row, 'section_unit': v.get('section_unit') if row.get('section_unit') is None else row['section_unit'],
               'documentary_rate': found[0] if len(found) == 1 else None}
    estimate = row.get('documentary_rate')
    if estimate:
        row = {**row, 'documentary_rate_resource': aliases.get((area, estimate.get('machine')))}
    return row


ROUTE_REVIEW = 'Operação ou aplicabilidade da rota por confirmar.'
CPIS_ROUTE = 'Rota CPIS atual difere da informação de planeamento.'
SEQUENCE = 'Sequência operacional por validar.'


def chosen_by_planner(selected, source_rid, override_rid, sector):
    """A máquina da ocorrência foi escolhida por uma pessoa (plano de 07/10/2026).

    Conta a escolha manual no Gantt; sem ela, a máquina do planeamento (Carteira, Tabela/Excel ou conjunto de
    famílias); e a preferência do setor quando foi aplicada. Com essa máquina a rota e a compatibilidade do
    planeador/Excel contam como validadas. A escolha automática (sem nenhuma destas) continua por confirmar.
    """
    if not selected:
        return False
    human = {override_rid} if override_rid else {source_rid}
    if sector and sector.get('mode') == 'prefer':
        human.add(sector.get('resource_id'))
    human.discard(None)
    return selected.get('resource_id') in human


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


def sector_timing_digest(c):
    """Margem e tempo fixo por peça das Definições (mudam todas as durações); ausente enquanto forem 0, para as
    referências dos cenários existentes ficarem iguais."""
    from ..raw.productivity import sector_timing
    timing = sector_timing(c)
    return {'sector_timing_digest': needs.digest(timing)} if any(v for t in timing.values() for v in t.values()) else {}


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
            **member_selection_digest(c), **machine_choice_digest(c), **sector_timing_digest(c),
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
    record_values = {r['row_key']: r.get('values_json') or {} for r in planning_lines}
    records_by_key = {r['row_key']: r for r in planning_lines}
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
    rows = [_application_inputs(r, records_by_key.get(r.get('matched_application_key')), aliases) for r in rows]
    rows += [_application_inputs(r, None, aliases) for r in new_rows]
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
        year = definition.get('picking_year_by_of', {}).get(row['ordem_codigo'])
        # Auditoria 06/10 (A9-1, A9-4): o Picking e a Semana escolhida vêm dos valores atuais da linha,
        # como na Carteira e na Carga, e não só da camada de pesquisa (que pode estar parada).
        values = record_values.get(row.get('matched_application_key') or row.get('application_row_key'))
        marks = priority.milestones_from_values(priority.engine_values(row, values), raw, picking_year=year,
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
            # Vigência das taxas pela data de hoje (início do cenário), igual à Carteira, à Carga e ao motor
            # (plano de 06/10, parte 3): uma taxa futura só vale quando chegar o seu dia.
            days = {start.date().isoformat()}
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
        # A máquina escolhida por uma pessoa vale como confirmação técnica para esta ocorrência, e a rota do
        # planeador/Excel também (07/10/2026): rota, compatibilidade e sequência ficam como avisos.
        planner = chosen_by_planner(selected, source_rid, override_rid, sector)
        info = record_info.get(row.get('matched_application_key') or row.get('application_row_key'))
        decision = scope.decision(selection,area,row['ordem_codigo'],row['referencia_original'],
                                  info[0] if info else [k for k in (row.get('matched_application_key'),row.get('application_row_key'),row.get('linha_origem')) if k])
        reasons = list(b['reasons'])
        warnings = []  # por confirmar sem bloquear: a máquina e a rota do planeador contam como validadas
        if execution_conflict:
            reasons.append('A máquina no registo diverge do trabalho iniciado; conferir execução.')
        if row.get('source_ambiguity'):
            reasons.append('Correspondência a várias linhas documentais por rever.')
        if row.get('route_review_required'):
            (warnings if planner else reasons).append(ROUTE_REVIEW)
        cp=cpis_evidence.get(row['operacao_id'])
        if cp and cp['status']=='correspondencia_documental_unica':
            route=[str(r['codope']) for r in cp['route']]
            expected=[code.removeprefix('CPIS:') for code in index.routes[row['item_id']]]
            if row['setor']=='MTG3' and route!=expected:
                (warnings if planner else reasons).append(CPIS_ROUTE)
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
        # Shared operators require their own confirmed availability. Um grupo sem calendário só limita
        # quantos trabalham ao mesmo tempo (08/10): OPERADORES_PAV1 deixava os serrotes do pav.1 sem horário.
        for option in options:
            if any(not resources[p]['windows'] and limits_hours(resources[p]) for p in option.get('shared_demands', {})):
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
              'blocking_reasons': sorted(set(reasons)), 'warnings': sorted(set(warnings)),
              'provisional': b['balance_provisional'] or any(o['provisional'] for o in options),
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
                if by_key[after]['assignment']['basis'] == 'escolha_do_planeador':
                    # Rota do planeador/Excel com a máquina escolhida: validada, fica como aviso (07/10/2026).
                    if SEQUENCE not in by_key[after]['warnings']:
                        by_key[after]['warnings'].append(SEQUENCE)
                else:
                    by_key[after]['blocking_reasons'].append(SEQUENCE)
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
        # Máquina e operação de cada evidência histórica (auditoria 06/10, GT-08), para os insights.
        'historical_evidence': {context.history_hashes[k]:{**v,**{f'scope_{n}':x for n,x in getattr(context,'scopes',{}).get(k,{}).items()}}
                                for k,v in context.cache.items()}})
