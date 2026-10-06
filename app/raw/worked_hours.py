"""Audited manual time declarations, separate from availability and OCR facts.

Time is attached to a sheet or an explicitly bounded period of one resource.
Overlapping OCR declarations must be replaced as a reviewed set, never added.
An edited source invalidates that review until the planner reviews it again.
"""
from datetime import date

from .. import planning, planning_needs as needs
from . import objects, query


def observations(conn):
    from ..planning_calculations import number
    result = []
    originals = {}
    for area in planning.AREAS:
        try:
            gen = query.generation(conn, area, dataset='production_hours')
        except planning.PlanningError as exc:
            if exc.status == 503:
                continue
            raise
        base, args = query.source(gen)
        for row in conn.execute('SELECT m.row_key,c.values_json,c.detail'+base, args):
            v, d = row['values_json'], row['detail']
            result.append({'key': area+':'+row['row_key'], 'area': area,
                'sheet_uid': d.get('sheet_uid') or row['row_key'], 'sheet': v.get('sheet'),
                'date': v.get('production_date'), 'machine': v.get('machine'),
                'hours': v.get('hours_worked'), 'origin': 'OCR',
                'machines': d.get('original_machines') or [v.get('machine')],
                'original_hours': d.get('original_hours', [v.get('hours_worked')])})
            value=number(v.get('hours_worked'))
            if v.get('hours_worked') is not None and (value is None or not 0<=value<=24):
                result[-1]['hours']=None
                result[-1]['hours_reason']='Horas da folha inválidas: exige um valor entre 0 e 24 h.'
            if v.get('source')=='ocr_original':
                observed=result.pop();areas=d.get('areas') or [area]
                observed.update(key=str(observed['sheet_uid']),area=areas[0] if len(areas)==1 else None,
                    areas=areas,origin='OCR original',revision=d.get('source_revision'),
                    source_content_hash=d.get('source_content_hash'),instance_id=d.get('instance_id'))
                prior=originals.get(observed['key'])
                if prior and prior!=observed:
                    observed['hours']=None;observed['hours_reason']='Revisões de horas originais divergentes; aguarda atualização das áreas.'
                originals[observed['key']]=observed
    result.extend(originals.values())
    # Operador de cada folha MES: as páginas do mesmo turno repetem no rodapé as horas do turno inteiro (06/10/2026).
    uids = [o['sheet_uid'] for o in result if o.get('origin') == 'OCR' and o.get('sheet_uid')]
    if uids:
        operators = {r['sheet_uid']: r['operator_name'] for r in conn.execute(
            'SELECT sheet_uid, operator_name FROM mes_kanban.validated_sheets WHERE sheet_uid = ANY(%s)', (uids,)).fetchall()}
        for o in result:
            if o.get('origin') == 'OCR':
                o['operator'] = (operators.get(o.get('sheet_uid')) or '').strip() or None
    return result


def observation_aliases(row):
    return {(area,m) for area in row.get('areas',[row['area']]) for m in row.get('machines',[row.get('machine')])}


def observation_origin(row):
    return ('original',row.get('instance_id')) if row.get('origin')=='OCR original' else ('mes',None)


def matching(d, resource, observed):
    aliases = {(a['area'], a['name']) for a in resource['definition']['aliases']}
    rows=[o for o in observed if (
        d['mode'] == 'sheet' and o['key'] == d['sheet_key'] or
        d['mode'] == 'period' and o.get('date') and d['start_date'] <= o['date'] <= d['end_date']
        and bool(observation_aliases(o)&aliases))]
    if d['mode']=='sheet' and rows and rows[0].get('date'):
        peers=[o for o in observed if o.get('date')==rows[0]['date'] and observation_aliases(o)&aliases]
        if any(observation_origin(o)!=observation_origin(rows[0]) for o in peers):return peers
    return rows


def sheet_conflict(definition,rows):
    return definition['mode']=='sheet' and any(o['key']!=definition['sheet_key'] for o in rows)


def basis(rows):
    return needs.digest(sorted(rows, key=lambda r: r['key']))


def normalize(conn, d):
    from .capacity import positive
    resource = objects.get(d.get('resource_id'), conn)
    if resource['kind'] != 'resource' or resource['archived'] or not resource['definition'].get('confirmed'):
        raise planning.PlanningError('Seleciona uma máquina física confirmada.')
    mode = d.get('mode', 'period')
    if mode not in ('sheet', 'period'):
        raise planning.PlanningError('Escolhe uma folha ou um período para as horas reais.')
    observed = observations(conn)
    d = {**d, 'mode': mode}
    if mode == 'sheet':
        rows = [o for o in observed if o['key'] == d.get('sheet_key')]
        if len(rows) != 1:
            raise planning.PlanningError('Seleciona uma folha publicada com identificação estável.')
        row = rows[0]
        if not set(row.get('areas',[row['area']])) & {a['area'] for a in resource['definition']['aliases']}:
            raise planning.PlanningError('A folha pertence a outra área da máquina.')
        if row['machine'] and not observation_aliases(row) & {(a['area'], a['name']) for a in resource['definition']['aliases']}:
            raise planning.PlanningError('A máquina da folha não corresponde ao recurso selecionado.')
        d['start_date'] = d['end_date'] = row['date']
    try:
        start, end = date.fromisoformat(d['start_date']), date.fromisoformat(d['end_date'])
    except (KeyError, TypeError, ValueError):
        raise planning.PlanningError('Indica datas válidas para as horas reais.') from None
    if end < start or start.isocalendar()[:2] != end.isocalendar()[:2]:
        raise planning.PlanningError('O período deve estar contido numa semana ISO. Regista separadamente cada semana.')
    hours = positive(d.get('hours'), zero=True)
    if hours > ((end-start).days+1)*24:
        raise planning.PlanningError('As horas reais excedem a duração do período da máquina.')
    operation = str(d.get('operation') or '').strip()
    from .capacity import supports
    if operation and not supports(resource, operation):
        raise planning.PlanningError('A operação não pertence à máquina. Deixa por repartir se abranger várias operações.')
    allocations=d.get('operation_hours') or []
    if not isinstance(allocations,list) or len(allocations)>40:
        raise planning.PlanningError('A repartição deve listar as operações e as respetivas horas.')
    normalized=[];seen=set()
    for allocation in allocations:
        if not isinstance(allocation,dict):raise planning.PlanningError('Repartição de horas inválida.')
        area=allocation.get('area');code=str(allocation.get('operation') or '').strip()
        if area not in {a['area'] for a in resource['definition']['aliases']} or not supports(resource, code):
            raise planning.PlanningError('Área ou operação da repartição não pertence à máquina.')
        if (area,code) in seen:raise planning.PlanningError('A repartição repete a mesma área/operação.')
        seen.add((area,code));normalized.append({'area':area,'operation':code,'hours':positive(allocation.get('hours'),zero=True)})
    if normalized and (abs(sum(a['hours'] for a in normalized)-hours)>.000001 or operation):
        raise planning.PlanningError('A repartição deve somar as horas reais; deixa a operação única vazia quando repartires o período.')
    reason = str(d.get('source') or '').strip()
    if not reason:
        raise planning.PlanningError('Regista a origem ou justificação das horas reais.')
    d.update(hours=hours, operation=operation or None, operation_hours=normalized, source=reason, origin='Manual',
             year=start.isocalendar().year, week=start.isocalendar().week,
             start_date=str(start), end_date=str(end), confirmed=bool(d.get('confirmed')))
    return d, resource, matching(d, resource, observed)


def overlaps(a, b):
    if a['resource_id'] != b['resource_id']:
        return False
    if a['mode'] == b['mode'] == 'sheet':
        return a['sheet_key'] == b['sheet_key']
    return a['start_date'] <= b['end_date'] and b['start_date'] <= a['end_date']


def preview(p):
    with planning.connect(readonly=True) as conn:
        d, resource, rows = normalize(conn, p.get('definition') or {})
        manual = [needs.serial(r) for r in conn.execute("SELECT id,name,revision,definition FROM planning_mtg.raw_objects WHERE kind='worked_hours' AND NOT archived")
                  if str(r['id']) != str(p.get('id')) and r['definition'].get('confirmed') and overlaps(d, r['definition'])]
        return {'definition': d, 'observations': rows, 'manual_overlaps': manual,
                'basis_hash': basis(rows), 'replacement_required': any(o['hours'] is not None for o in rows),
                'scope_conflict':'Existem folhas de outras origens neste recurso e dia. Revê o conjunto numa declaração por período.' if sheet_conflict(d,rows) else None}


def validate(conn, id, d):
    # Serialize competing declarations on this physical resource. Object revision
    # checks alone cannot protect two different new records from overlapping.
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ('worked-hours:'+str(d.get('resource_id')),))
    d, resource, rows = normalize(conn, d)
    if d['confirmed'] and sheet_conflict(d,rows):
        raise planning.PlanningError('Existem horas sobrepostas de outras origens. Revê o conjunto numa declaração por período.',409)
    for r in conn.execute("SELECT id,definition FROM planning_mtg.raw_objects WHERE kind='worked_hours' AND NOT archived AND id<>%s", (id,)):
        if d['confirmed'] and r['definition'].get('confirmed') and overlaps(d, r['definition']):
            raise planning.PlanningError('O período sobrepõe outra declaração manual. Corrige ou arquiva essa declaração primeiro.', 409)
    if d.get('basis_hash') != basis(rows):
        raise planning.PlanningError('Revê as declarações OCR antes de guardar: as fontes podem ter mudado.', 409)
    if any(o['hours'] is not None for o in rows) and not d.get('replace_ocr'):
        raise planning.PlanningError('Há horas OCR neste âmbito. Confirma a substituição integral para não as duplicar.')
    d['replaces'] = [r['key'] for r in rows]
    return d


def resolve(resource, declarations, observed):
    """Return unique usable time cohorts and conflicts for one physical resource."""
    selected = [r for r in declarations if r['definition'].get('confirmed')
                and r['definition']['resource_id'] == resource['id']]
    aliases = {(a['area'], a['name']) for a in resource['definition']['aliases']}
    used = set()
    cohorts = []
    for record in selected:
        d = record['definition'];rows = matching(d, resource, observed)
        valid = basis(rows) == d['basis_hash']
        partial=sheet_conflict(d,rows)
        conflict = partial or any(other['id'] != record['id'] and overlaps(d, other['definition']) for other in selected)
        used.update(r['key'] for r in rows)
        cohorts.append({'key': 'manual:'+record['id'], 'hours': d['hours'] if valid and not conflict else None,
            'origin': 'Manual', 'revision': record['revision'], 'operation': d.get('operation'),
            'start_date': d['start_date'], 'end_date': d['end_date'], 'sheets': [r['key'] for r in rows],
            'sheet_evidence': rows, 'definition': d,
            'reason': 'Sobreposição entre origens: revê o conjunto numa declaração por período.' if partial else
                'As declarações de origem mudaram; rever substituição.' if not valid else 'Declarações manuais sobrepostas.' if conflict else None})
    relevant=[o for o in observed if observation_aliases(o)&aliases]
    origins_by_date={}
    for o in relevant:
        if o.get('date'):origins_by_date.setdefault(o['date'],set()).add(observation_origin(o))
    candidates=[o for o in relevant if o['key'] not in used]
    # Um turno = uma declaração de horas: páginas da mesma máquina, dia e operador com as mesmas horas no rodapé
    # contam uma vez, com o volume de todas as páginas (antes cada página contava o turno inteiro outra vez).
    shifts_seen={}
    grouped=[]
    for o in candidates:
        same=(o.get('origin')=='OCR' and o.get('operator') and o.get('hours') is not None and o['machine'] is not None)
        k=(o['machine'],o.get('date'),o.get('operator'),o.get('hours')) if same else None
        if k and k in shifts_seen:
            shifts_seen[k]['pages'].append(o)
            continue
        entry={'first':o,'pages':[o]}
        if k:shifts_seen[k]=entry
        grouped.append(entry)
    for entry in grouped:
        o=entry['first'];pages=entry['pages']
        if o['machine'] is None:
            continue
        unresolved_resource=(o.get('origin')=='OCR original' and o.get('area') is None
            and not observation_aliases(o).issubset(aliases))
        overlap=len(origins_by_date.get(o.get('date'),()))>1
        cohorts.append({'key': o['key'] if len(pages)==1 else 'turno:'+'+'.join(sorted(p['key'] for p in pages)),
            'hours': None if overlap or unresolved_resource else o['hours'], 'origin': o['origin'],
            **({'revision':o['revision']} if 'revision' in o else {}),
            'start_date': o['date'], 'end_date': o['date'], 'operation': None,
            'sheets': sorted(p['key'] for p in pages), 'sheet_evidence': pages,
            'reason': 'Sobreposição entre origens de horas por resolver.' if overlap else
                'Área da folha original por confirmar; a máquina pode corresponder a recursos físicos distintos.' if unresolved_resource else
                o.get('hours_reason') or ('Horas da folha desconhecidas.' if o['hours'] is None else None)})
    return cohorts
