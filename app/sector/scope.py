"""The user's Planear decision gates the published planning information.

CPIS orders, open balances and documentary recommendations never authorize
work on their own. A scenario may further restrict this selection.
"""
from .. import planning, planning_needs as needs, planning_population
from ..raw import query


def matches_current(row, values):
    """A changed technical preparation cannot reuse the old variant's rules."""
    import re
    from ..planning_calculations import key
    if any(row.get(source) != values.get(current) for source,current in [
        ('ordem_codigo','of'),('referencia_original','component_ref'),('perfil','profile'),
        ('comprimento_mm','length_mm'),('quantidade_base','quantity_required')]):
        return False
    written = re.search(r'\bS\d{3}(?:\s?J[012R])?(?:\s?H)?\b',
        str((row.get('raw') or {}).get('Des. Material') or ''),re.I)
    grade = row.get('qualidade') or (written.group(0) if written else None)
    if values.get('grade') and re.sub(r'\s','',key(grade)) != re.sub(r'\s','',key(values['grade'])):
        return False
    if 'drawing_revision' in values and key(row.get('revisao_desenho')) != key(values['drawing_revision']):
        return False
    if row['setor']=='MTG3' and row['fase']=='principal' and values.get('operation') is not None:
        if str(values['operation']) != str(row.get('operacao_codigo') or 'por_definir').removeprefix('CPIS:'):
            return False
    return True


def current_preparation(row, record):
    """Main-machine edits do not replace a following operation's machine."""
    values = record['values_json']
    current = {k:values[k] for k in ('designation','notes','grade','material_type','picking_week','picking_year') if k in values}
    if row['fase']=='principal':
        current.update({k:values[k] for k in ('machine','cut_date') if k in values})
    else:
        operation = 'abocardar' if row['operacao_codigo']=='LOCAL:ABOCARDAR' else row['operacao_codigo'].removeprefix('CPIS:')
        prepared = [p['values_json'] for p in record['detail'].get('preparations',[])
                    if str(p['values_json'].get('operation'))==operation]
        if len(prepared)==1:
            current.update({k:prepared[0][k] for k in ('machine',) if k in prepared[0]})
    return current


def read(c):
    """Legacy (area, OF, reference) decisions, with the member decisions in `.members` (plano de 02/10/2026)."""
    from .decisions import Decisions, read_members
    exists = c.execute("SELECT to_regclass('planning_mtg.sector_selection') t").fetchone()['t']
    if not exists:
        return None
    rows = c.execute('SELECT * FROM planning_mtg.sector_selection ORDER BY area,production_order_no,reference').fetchall()
    return Decisions({(r['area'],r['production_order_no'],r['reference']):r for r in rows},
                     {(r['area'],r['member_key']):r for r in read_members(c)})


def decision(selection, area, of, reference, keys=()):
    """Member (current key or selection aliases) → (OF, reference) → (OF, '*')."""
    if selection is None:
        return None
    from .decisions import resolve
    members = _area_members(selection, area)
    # As decisões antigas por referência foram gravadas com a referência sem espaços (como a Carteira a mostra).
    reference = str(reference or '').strip() or 'Sem referência'
    return resolve(selection, members, [(area,of,reference),(area,of,'*')], list(keys))['decision']


def resolved(selection, area, of, reference, keys=()):
    """A decisão completa (resolve), com a quantidade parcial quando a há (08/10)."""
    if selection is None:
        return {'decision': None}
    from .decisions import resolve
    reference = str(reference or '').strip() or 'Sem referência'
    return resolve(selection, _area_members(selection, area), [(area,of,reference),(area,of,'*')], list(keys))


def planned_part(selection, area, record):
    """(planeada agora?, {'part', 'principal'} ou None) de uma linha ativa (quantidade parcial, 08/10).

    A parte por fazer vem da regra única decisions.planned_open, com o saldo e o feito da Carteira
    (portfolio.balance_of). Parte 0 = já feita: a linha deixa de estar planeada (volta a nesting pelo resto).
    None = a linha inteira.
    """
    from .decisions import planned_open
    v = record['values_json']
    decided = resolved(selection, area, v.get('of'), v.get('component_ref'), member_keys(record))
    if decided.get('decision') != 'selected':
        return False, None
    if decided.get('planned_quantity') is None:
        return True, None
    from .portfolio import balance_of
    _, pieces, done, _ = balance_of(v, record.get('detail') or {}, area)
    part = planned_open(decided, pieces, done)
    if part == 0:
        return False, None
    if part is None or pieces is None or part >= pieces:
        return True, None
    return True, {'part': part, 'principal': pieces}


def _area_members(selection, area):
    members = getattr(selection,'members',None)
    if not members:
        return {}
    cache = selection.__dict__.setdefault('_by_area',{})
    if area not in cache:
        cache[area] = {k[1]:r for k,r in members.items() if k[0]==area}
    return cache[area]


def member_keys(record):
    """Current row key and the earlier keys of the same physical line."""
    return [record['row_key'],*((record.get('detail') or {}).get('selection_aliases') or [])]


def digest(selection):
    """Unchanged for the legacy decisions alone, so existing scenarios keep their references."""
    legacy = [dict(r) for r in (selection or {}).values()]
    members = getattr(selection,'members',None)
    if not members:
        return needs.digest(legacy)
    return needs.digest({'legacy':legacy,'members':[dict(r) for _,r in sorted(members.items())]})


def area_digest(selection, area):
    """Decisões de um só setor, para as caches desse setor: uma decisão no outro setor não as refaz."""
    legacy = [dict(r) for k,r in (selection or {}).items() if k[0]==area]
    members = [dict(r) for k,r in sorted(getattr(selection,'members',{}).items()) if k[0]==area]
    return needs.digest({'legacy':legacy,'members':members})


def planning_lines(c, selection, areas):
    """Current active app rows, bounded by the user's chosen orders."""
    records = []; missing = []
    for area in areas:
        orders = sorted({of for (a,of,_),r in (selection or {}).items() if a==area and r['decision']=='selected'} |
                        {r['production_order_no'] for (a,_),r in getattr(selection,'members',{}).items()
                         if a==area and r['decision']=='selected'})
        if not orders:
            continue
        try:
            g = query.generation(c,area); base,args = query.source(g)
        except planning.PlanningError as exc:
            if exc.status != 503:
                raise
            missing += [{'area':area,'of':of,'reason':'Informação de planeamento ainda não publicada.'} for of in orders]
            continue
        rows = c.execute('SELECT m.row_key,c.values_json,c.detail'+base+' AND '+planning_population.active_sql()+" AND c.values_json->>'of'=ANY(%s)",args+[orders]).fetchall()
        from .machine_choice import context as machine_context, effective as effective_machine
        mctx = machine_context(area, conn=c)
        seen_keys = set(); active_orders = set(); no_machine = 0
        for row in rows:
            v = row['values_json']
            seen_keys.update(member_keys(row)); active_orders.add(v.get('of'))
            chosen, part = planned_part(selection, area, row)
            if chosen:
                # O Gantt só recebe linhas com máquina. Desde 07/10/2026 o Planear dá a máquina sugerida a uma linha
                # sem máquina; aqui ficam de fora só as decisões antigas e as linhas a que tiraram a máquina depois.
                found = effective_machine(mctx, member_keys(row), v.get('sku_family'), v.get('machine'))
                if not found['machine']:
                    no_machine += 1
                    continue
                records.append({**row,'area':area,'effective_machine':found,
                                **({'planned_part':part} if part else {})})
        if no_machine:
            missing.append({'area':area,'reason':f'{no_machine} linha(s) escolhida(s) sem máquina: entram quando tiverem máquina.'})
        # Membros de linhas já concluídas não são pendentes; só os de OF ainda ativas sem correspondência.
        missing += [{'area':area,'of':r['production_order_no'],'reference':r['reference'],'member':key,
                     'reason':'Membro escolhido sem correspondência inequívoca na informação ativa; rever na Carteira.'}
                    for (a,key),r in getattr(selection,'members',{}).items()
                    if a==area and r['decision']=='selected' and key not in seen_keys and r['production_order_no'] in active_orders]
        found = {r['values_json'].get('of') for r in records if r['area']==area}
        legacy_orders = {of for (a,of,_),r in (selection or {}).items() if a==area and r['decision']=='selected'}
        missing += [{'area':area,'of':of,'reason':'Sem informação de planeamento ativa para a seleção.'}
                    for of in orders if of not in found and of in legacy_orders and of not in active_orders]
        present = {(r['values_json'].get('of'),r['values_json'].get('component_ref')) for r in records if r['area']==area}
        missing += [{'area':area,'of':of,'reference':ref,'reason':'Referência escolhida sem informação de planeamento ativa.'}
            for (a,of,ref),r in (selection or {}).items() if a==area and r['decision']=='selected'
            and ref!='*' and of in found and (of,ref) not in present]
    return records,missing


def research_rows(source_rows, records):
    """Exact origins first; cross-version correspondence only when unique."""
    from collections import defaultdict
    aliases = defaultdict(list); technical = defaultdict(list)
    fields = ('ordem_codigo','referencia_original','perfil','comprimento_mm','quantidade_base')
    for r in source_rows:
        aliases[(r['setor'],r['linha_origem'])].append(r)
        technical[(r['setor'],*(r.get(k) for k in fields))].append(r)
    matched = {}; unmatched = []
    for record in records:
        v = record['values_json']; d = record['detail']; sector = 'MTG2' if record['area']=='perfis' else 'MTG3'
        if d.get('calculation',{}).get('compatible') is False:
            unmatched.append(record)
            continue
        current = {record['row_key'],*(d.get('selection_aliases') or [])}
        found = {r['operacao_id']:r for key in current for r in aliases.get((sector,str(key).removeprefix('macro:')),[])
                 if all(r.get(k)==v.get(col) for k,col in [('ordem_codigo','of'),('referencia_original','component_ref'),
                     ('perfil','profile'),('comprimento_mm','length_mm'),('quantidade_base','quantity_required')])}
        if found and any(not matches_current(r,v) for r in found.values()):
            unmatched.append(record)
            continue
        if not found:
            candidates = technical.get((sector,v.get('of'),v.get('component_ref'),v.get('profile'),v.get('length_mm'),v.get('quantity_required')),[])
            if len({r['item_id'] for r in candidates})==1 and all(matches_current(r,v) for r in candidates):
                found = {r['operacao_id']:r for r in candidates}
        if found:
            if len({r['item_id'] for r in found.values()})==1:
                matched.update({key:{**r,'matched_application_key':record['row_key'],
                    'current_planning':current_preparation(r,record)} for key,r in found.items()})
            else:
                unmatched.append({**record,'source_ambiguity':sorted(found)})
        else:
            unmatched.append(record)
    return list(matched.values()),unmatched


def local_rows(records, resource_codes):
    """New or revised app preparations keep working before the next factory import."""
    from ..planning_estimates import select_balance
    from ..planning_calculations import abocardar
    rows = []; dependencies = []
    for record in records:
        v = record['values_json']; detail = record['detail']; area = record['area']; key = record['row_key']
        sources = detail.get('calculation',{}).get('production_sources') or []
        main = 'corte' if area=='perfis' else str(v.get('operation') or '')
        operations = [main]
        # Abocardar desconhecido ou vazio = «-» (plano de 07/10/2026, também nos registos antigos): só «X»/«sim»
        # acrescenta a operação, sem rota por confirmar. O cálculo publicado ainda traz uma fonte «abocardar»
        # quando a marca é desconhecida: essa fonte não cria a operação.
        boc = area=='perfis' and abocardar(v.get('abocardar')) is True
        if boc:
            operations.append('abocardar')
        whole = {}  # operação → código composto de origem («111-1034»), que é a única fonte de saldo
        for s in sources:
            code = str(s['operation'])
            if area=='perfis' and code=='abocardar' and not boc:
                continue
            # 2.ª Oper. composta da MTG3 (ex. «111-1034»): uma ocorrência por operação, como na pesquisa
            # (auditoria 06/10, ORF-2). O saldo e a preparação continuam a ser os da operação composta.
            parts = [p.strip() for p in code.split('-') if p.strip()] if area=='cantoneiras' and code!=main else [code]
            for part in parts:
                if part not in operations:
                    operations.append(part)
                    whole[part] = code
        estimates = {str(e['operation']):e for e in detail.get('calculation',{}).get('operation_estimates',[])}
        preparations = {str(p['values_json'].get('operation')):p['values_json'] for p in detail.get('preparations',[])}
        prior = None
        for occurrence, operation in enumerate(operations,1):
            code = 'LOCAL:PRINCIPAL' if area=='perfis' and operation=='corte' else 'LOCAL:ABOCARDAR' if operation=='abocardar' else 'CPIS:'+operation
            source = whole.get(operation,operation)
            b = select_balance({**detail,'area':area,'values':v},source)
            if b['planning_remaining'] is None and operation==main and v.get('planning_balance_origin') \
                    and isinstance(v.get('planning_remaining'),(int,float)):
                # Mesmo saldo que a Carteira (auditoria 06/10, A8-1): o saldo provisório escolhido na
                # projeção (ex. «Qtd em Falta») vale também para a Carga e o Gantt.
                b = {'reconciled_remaining':None,'planning_remaining':v['planning_remaining'],
                     'balance_origin':v['planning_balance_origin'],'provisional':True,'evidence':[],'reasons':[]}
            prepared = preparations.get(operation) or preparations.get(source,{})
            machine = (prepared.get('machine') if operation!=main else v.get('machine'))
            origin = b['balance_origin'] or ''
            reconciled = b['planning_remaining'] if b['evidence'] and not b['provisional'] else None
            r = {'setor':'MTG2' if area=='perfis' else 'MTG3','ordem_codigo':v.get('of'),
                'referencia_original':v.get('component_ref'), 'item_id':'app:'+key,'operacao_id':f'app:{key}:{occurrence}',
                'linha_origem':key,'ocorrencia':occurrence,'operacao_codigo':code,'codigo_original':operation,
                'snapshot_id':'app-published','excel_linha':detail.get('line'), 'fase':'principal' if occurrence==1 else 'complementar',
                'perfil':v.get('profile'),'qualidade':v.get('grade'),'material_type':v.get('material_type'),
                'assinatura':needs.signature(v),'revisao_desenho':v.get('drawing_revision'),
                'identidade_tecnica_confirmada':False,'variante_id':None,'segunda_operacao_estado':'aplicavel' if len(operations)>1 else 'ausente',
                'quantidade_base':v.get('quantity_required'),'saldo_confirmado':reconciled,'saldo_documental':b['planning_remaining'],
                'estado_quantidade':'fonte_unica' if v.get('quantity_required') is not None else 'por_confirmar',
                'estado_documental':'aberta','comprimento_mm':v.get('length_mm'),'recurso_atual':resource_codes.get((area,machine)),
                'section_unit':v.get('section_unit'),
                'maquina_original':machine,'equipa':v.get('team'),'contador_excel':None,'semana_picking':v.get('picking_week'),'ano_picking':v.get('picking_year'),
                'data_corte_prevista':prepared.get('expected_date') or v.get('cut_date'), 'raw':detail.get('raw') or {},
                'execution_started':bool(reconciled is not None and b['evidence']),
                'application_balance_evidence':b,'application_row_key':key,'application_revision':detail.get('revision'),
                'source_ambiguity':record.get('source_ambiguity'),
                'route_review_required':not operation or operation=='por_definir',
                'documentary_rate':estimates.get(operation)}
            rows.append(r)
            if prior:
                dependencies.append({'predecessora':prior,'sucessora':r['operacao_id'],'validada':not r['route_review_required']})
            prior = r['operacao_id']
    return rows,dependencies
