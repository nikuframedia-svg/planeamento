"""Read the separate research database in one consistent, read-only transaction.

The cache is published atomically in the application's database. Neither request
handlers nor the optimizer connect to the factory or rebuild its schema.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
import argparse
import json
import os
from pathlib import Path
import uuid
from threading import Lock
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .. import planning, planning_needs as needs
from ..planning_calculations import DECLARED_ORIGIN

PROVIDER = 'research-v2'
BALANCE_CONTRACT = 'research-balance-v3'  # v3 (06/10): contador Excel mais recente ganha; derivados refeitos
AREAS = {'MTG2': 'perfis', 'MTG3': 'cantoneiras'}
_cache = {}
_lock = Lock()


def enabled():
    return os.getenv('MES_PLANNING_V2_ENABLED', '0') == '1'


def resource_id(code):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'planeamento:v2:resource:' + code))


def normalize_operation(row):
    if not row.get('operacao_codigo'):
        row['documentary_operation_code']=row.get('operacao_codigo')
        row['operacao_codigo']='por_definir'
        row['route_review_required']=True
    return row


def connect():
    dsn = os.getenv('MES_PLANNING_V2_DSN')
    access = os.getenv('MES_PLANNING_V2_ACCESS_FILE')
    if not dsn and not access:
        raise planning.PlanningError('Ligação à camada v2 por configurar.', 503)
    credentials = json.loads(Path(access).read_text()) if not dsn else {}
    c = psycopg.connect(dsn or '', **credentials, row_factory=dict_row,
                         connect_timeout=10, application_name='planning_v2_readonly')
    c.read_only = True
    c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
    c.execute("SET LOCAL statement_timeout = '120s'")
    expected = os.getenv('MES_PLANNING_V2_DATABASE', 'dataresearchmtg_planeamento_20260930')
    if c.execute('SELECT current_database() db').fetchone()['db'] != expected:
        c.close()
        raise planning.PlanningError('Destino da camada v2 diferente do configurado.', 503)
    return c


def read_source(c, *, as_of=None, orders=None, include_closed=False):
    """A bounded number of set queries, including all positive documentary history."""
    # Dia de exibição (Lisboa), não o fuso do servidor (Berlim), como projection.fingerprint.
    as_of = as_of or datetime.now(ZoneInfo(planning.settings.display_timezone)).date()
    sources = {
        'excel': c.execute('SELECT * FROM consulta_v2.fontes_selecionadas ORDER BY setor,dataset_id').fetchall(),
        'cpis': c.execute('SELECT * FROM origem_v2.versoes_cpis ORDER BY id').fetchall(),
    }
    # Preserve documentary and reconciled balances separately, plus the actual
    # original fields (including geometry, quality, rates and galvanizing dates).
    rows = c.execute("""
        SELECT d.*, i.variante_id, v.assinatura, v.especificacao,
               v.revisao_desenho, v.identidade_tecnica_confirmada,
               r.row_data raw, r.rate_m_per_hour,
               i.gama_aplicada_id, i.segunda_operacao_original
        FROM consulta_v2.kg_diagnostico_operacoes d
        JOIN producao_v2.itens i ON i.id=d.item_id
        LEFT JOIN cadastro_v2.variantes_artigo v ON v.id=i.variante_id
        LEFT JOIN raw_mtg.plan_production_rows r
          ON r.snapshot_id=i.snapshot_id AND r.source_line_id=i.linha_origem
        WHERE (%s OR d.estado_documental <> 'fechada')
          AND (%s::text[] IS NULL OR d.ordem_codigo=ANY(%s))
          AND (%s OR d.saldo_documental IS DISTINCT FROM 0 OR EXISTS (
            SELECT 1 FROM producao_v2.operacoes_itens pending
            WHERE pending.item_id=d.item_id AND pending.fase<>'principal'
              AND pending.saldo_excel IS DISTINCT FROM 0))
        ORDER BY d.setor,d.item_id,d.ocorrencia
    """, (include_closed,list(orders) if orders is not None else None,list(orders) if orders is not None else None,include_closed)).fetchall()
    history = c.execute("""
        WITH routes AS (
          SELECT item_id,array_agg(operacao_codigo ORDER BY ocorrencia) route
          FROM producao_v2.operacoes_itens GROUP BY item_id
        ) SELECT i.variante_id,i.ordem_codigo,i.recurso_atual,
                 i.segunda_operacao_estado,o.operacao_codigo,r.route
          FROM producao_v2.itens i
          JOIN producao_v2.operacoes_itens o ON o.item_id=i.id
          JOIN routes r ON r.item_id=i.id
          WHERE o.fase='principal' AND o.contador_excel>0
            AND i.recurso_atual IS NOT NULL
          ORDER BY i.variante_id,i.ordem_codigo
    """).fetchall()
    events = c.execute('SELECT * FROM producao_v2.eventos WHERE quantidade_reportada>0 AND data_producao<=%s ORDER BY id', (as_of,)).fetchall()
    raw_by_item = {}
    for row in rows:
        normalize_operation(row)
        raw_by_item[str(row['item_id'])] = row.pop('raw') or {}
    metadata = {
        'raw_by_item': raw_by_item,
        'resources': c.execute('SELECT * FROM cadastro_v2.recursos ORDER BY codigo').fetchall(),
        'aliases': c.execute('SELECT * FROM cadastro_v2.alias_recursos ORDER BY nome_origem').fetchall(),
        'relations': c.execute('SELECT * FROM cadastro_v2.relacoes_recursos ORDER BY pai,filho').fetchall(),
        'capacities': c.execute('SELECT * FROM cadastro_v2.capacidades_maquina ORDER BY id').fetchall(),
        'rates': c.execute('SELECT * FROM planeamento_v2.taxas ORDER BY id').fetchall(),
        'availability': c.execute('SELECT * FROM planeamento_v2.disponibilidades_fonte ORDER BY id').fetchall(),
        'budgets': c.execute('SELECT * FROM planeamento_v2.orcamentos_semanais ORDER BY id').fetchall(),
        'rules': c.execute('SELECT * FROM planeamento_v2.regras_conhecimento ORDER BY codigo').fetchall(),
        'dependencies': c.execute('SELECT * FROM producao_v2.dependencias ORDER BY predecessora,sucessora').fetchall(),
        'possible_duplicates': c.execute('SELECT * FROM consulta_v2.possiveis_duplicados_setores ORDER BY ordem_codigo,referencia_original').fetchall(),
        'history': history, 'events': events, 'as_of': str(as_of),
    }
    return needs.serial({'sources': sources, 'metadata': metadata, 'rows': rows})


def version_digest(package):
    """Assinatura da versão só com o conteúdo lido (auditoria 06/10, A14-F2).

    O 'as_of' é só o dia da leitura: se entrasse na assinatura, cada meia-noite
    criava uma versão nova igual à anterior e obrigava a recalcular tudo. Os
    eventos que o 'as_of' filtra já fazem parte do pacote, por isso uma mudança
    real continua a dar versão nova.
    """
    metadata = {k: v for k, v in (package.get('metadata') or {}).items() if k != 'as_of'}
    return needs.digest({**package, 'metadata': metadata})


def publish(c, package):
    """Idempotent immutable versions and one atomic head switch (caller's transaction)."""
    digest = version_digest(package)
    provider = PROVIDER
    c.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ('gantt-research-publish',))
    prior = c.execute('SELECT version_id FROM planning_mtg.gantt_source_heads WHERE provider=%s', (provider,)).fetchone()
    exists = c.execute('SELECT id FROM planning_mtg.gantt_source_versions WHERE id=%s', (digest,)).fetchone()
    if not exists:
        c.execute('INSERT INTO planning_mtg.gantt_source_versions(id,provider,sources,metadata) VALUES(%s,%s,%s,%s)',
                  (digest, provider, Jsonb(package['sources']), Jsonb(package['metadata'])))
        with c.cursor() as cursor:
            cursor.executemany('INSERT INTO planning_mtg.gantt_source_rows(version_id,key,payload) VALUES(%s,%s,%s)',
                               [(digest, row['operacao_id'], Jsonb(row)) for row in package['rows']])
    c.execute("""INSERT INTO planning_mtg.gantt_source_heads(provider,version_id,checked_at,last_error)
                 VALUES(%s,%s,now(),NULL) ON CONFLICT(provider) DO UPDATE
                 SET version_id=excluded.version_id,checked_at=excluded.checked_at,last_error=NULL""", (provider, digest))
    # Register unconfirmed resource identities for the existing capacity editor.
    # Code-to-ID bindings are explicit and shared across both areas.
    aliases = defaultdict(list)
    for row in package['metadata']['aliases']:
        aliases[row['recurso_codigo']].append(row['nome_origem'])
    for resource in package['metadata']['resources']:
        code = resource['codigo']; rid = resource_id(code)
        d = {'confirmed': False, 'research_code': code, 'resource_type': resource['tipo'],
             'operations': sorted({r['operacao_codigo'] for r in package['metadata']['capacities'] if r['recurso_codigo'] == code and r.get('operacao_codigo')}
                 | {r['operacao_codigo'] for r in package['rows'] if r.get('recurso_atual') == code and r.get('operacao_codigo')}), 'aliases': [{'area': area, 'name': name}
               for area in planning.AREAS for name in sorted(set(aliases[code] + [resource['designacao']]))],
             'technical_rules': [], 'operators': resource.get('quantidade_operadores')}
        # Do not replace an explicit existing resource binding.
        names = set(aliases[code] + [resource['designacao']])
        existing = c.execute("SELECT id,definition FROM planning_mtg.raw_objects WHERE kind='resource' AND NOT archived").fetchall()
        match = [r for r in existing if r['definition'].get('research_code') == code or
                 any(a.get('name') in names for a in r['definition'].get('aliases', []))]
        if match:
            continue
        inserted = c.execute("""INSERT INTO planning_mtg.raw_objects(id,kind,name,area,definition,actor)
          VALUES(%s,'resource',%s,%s,%s,'Importação documental v2') ON CONFLICT(id) DO NOTHING RETURNING id""",
          (rid, resource['designacao'], AREAS.get(resource['setor'], 'perfis'), Jsonb(d))).fetchone()
        if inserted:
            c.execute("INSERT INTO planning_mtg.raw_object_versions(object_id,revision,definition,name,archived,actor) VALUES(%s,1,%s,%s,false,'Importação documental v2')", (rid, Jsonb(d), resource['designacao']))
    if not prior or prior['version_id'] != digest:
        from ..raw import projection
        projection.signal(c,'research-v2')
    return {'version': digest, 'changed': not prior or prior['version_id'] != digest, 'operations': len(package['rows'])}


def head(c):
    row = c.execute("""SELECT h.*,v.sources,v.created_at FROM planning_mtg.gantt_source_heads h
      LEFT JOIN planning_mtg.gantt_source_versions v ON v.id=h.version_id WHERE h.provider=%s""", (PROVIDER,)).fetchone()
    if not row or not row['version_id']:
        raise planning.PlanningError('A camada v2 ainda não tem uma importação utilizável.', 503)
    return needs.serial(row)


def load(c, version=None):
    current = head(c)
    ident = version or current['version_id']
    with _lock:
        cached = _cache.get(ident)
    if cached:
        return {**cached, 'head': current}
    v = c.execute('SELECT * FROM planning_mtg.gantt_source_versions WHERE id=%s', (ident,)).fetchone()
    if not v:
        raise planning.PlanningError('Versão de dados v2 indisponível.', 409)
    rows = c.execute('SELECT payload FROM planning_mtg.gantt_source_rows WHERE version_id=%s ORDER BY key', (ident,)).fetchall()
    payload = [r['payload'] for r in rows]
    for row in payload:
        normalize_operation(row)
        row['raw'] = v['metadata'].get('raw_by_item', {}).get(row['item_id'], row.get('raw', {}))
    result = {'sources': v['sources'], 'metadata': v['metadata'], 'rows': payload}
    with _lock:
        if len(_cache) > 1:
            _cache.clear()
        _cache[ident] = result
    return {**result, 'head': current}


def refresh():
    try:
        from . import cpis_tables
        cpis_tables.refresh()
        with connect() as source:
            package = read_source(source)
        with planning.connect() as target:
            return publish(target, package)
    except Exception:
        with planning.connect() as target:
            target.execute("""INSERT INTO planning_mtg.gantt_source_heads(provider,last_error)
              VALUES(%s,'Origem indisponível ou importação rejeitada') ON CONFLICT(provider)
              DO UPDATE SET last_error=excluded.last_error""", (PROVIDER,))
        raise


EXCEL_COUNTERS = {'perfis': ('Ser.', 'Qtd em Falta'), 'cantoneiras': ('Maq.', 'Qtd falta')}


def excel_counters_changed(area, research_raw, current_raw):
    """O Excel atual registou produção depois do retrato da pesquisa (auditoria 06/10).

    Compara o contador e a coluna de falta da operação principal. Só decide quando
    as duas linhas trazem a coluna de falta; sem ela fica a regra anterior.
    """
    from ..planning_calculations import quantity
    counter, remaining = EXCEL_COUNTERS[area]
    old, new = research_raw or {}, current_raw or {}
    if remaining not in old or remaining not in new:
        return False
    return any(quantity(old.get(k)) != quantity(new.get(k)) for k in (counter, remaining))


def _rederive(row, origin):
    """Campos que dependem do saldo, refeitos depois de a pesquisa o substituir.

    Mesmas fórmulas de planning_calculations.calculate; sem isto ficavam calculados
    com o saldo anterior (muitas vezes desconhecido).
    """
    import math
    from ..planning_calculations import positive, CONTRACT
    v = row['values']; rules = row.setdefault('calculation', {}).setdefault('rules', {})
    rem = v.get('remaining'); length = positive(v.get('length_mm'))
    unit = positive(v.get('section_unit')); stock = positive(v.get('stock_length_mm'))
    weight_unit = positive(v.get('weight_unit'))
    pieces = math.floor(stock/length) if stock and length else 0
    derived = {
        'remaining_m': (0 if rem == 0 else rem*length/1000 if rem is not None and length else None, 'saldo × L / 1000', 'm'),
        'section_pending': (0 if rem == 0 else unit*rem if unit is not None and rem is not None else None, 'A × saldo', 'mm²'),
        'bars': (0 if rem == 0 else math.ceil(rem/pieces) if rem is not None and pieces else None, 'ceil(saldo / floor(S / L))', 'un.'),
        'weight': (weight_unit*rem if weight_unit is not None and rem is not None else None, 'peso unitário × saldo principal', 'kg')}
    if 'quantity_to_plan' not in (row.get('input_values') or {}):
        derived['quantity_to_plan'] = (rem, 'Saldo da operação planeada', 'un.')
    for field, (value, formula, unit_name) in derived.items():
        v[field] = value
        rules[field] = {**(rules.get(field) or {}), 'formula': formula, 'unit': unit_name, 'source': origin,
                        'inputs': {'saldo': rem, 'L': length, 'A': unit, 'S': stock, 'weight_unit': weight_unit},
                        'contract': CONTRACT, 'reason': None if value is not None else 'Saldo ou dados da peça desconhecidos.'}


def overlay_rows(c, area, rows):
    """One balance policy for projections, their tables and portfolio views.

    Explicitly reconciled application production takes precedence. Documentary
    v2 balances never increment a counter or reconcile an unassociated event.
    """
    if not enabled() or not rows:
        return
    package = load(c)
    from ..sector import scope
    matched,_ = scope.research_rows(package['rows'],[
        {'area':area,'row_key':r['key'],'values_json':r['values'],'detail':r} for r in rows])
    index = {}; following=defaultdict(list)
    for r in matched:
        key=r['matched_application_key']
        if r['fase']=='principal':
            index[key]=r
        else:
            following[key].append(r)
    from .integrated import balance
    for row in rows:
        key = row['key']
        r = index.get(key)
        if r is None:
            continue
        v = row['values']; calc = row.setdefault('calculation', {})
        calc['integrated_operations']=[{'operation':x['operacao_codigo'],'occurrence':x['ocorrencia'],
            'remaining':balance(x)['planning_remaining'],'origin':balance(x)['balance_origin']}
            for x in following.get(key,[])]
        sources = calc.setdefault('production_sources', [])
        operation = 'corte' if area == 'perfis' else str(v.get('operation') or r['codigo_original'] or '')
        source = next((s for s in sources if str(s.get('operation')) == operation), None)
        # A «Qtd em falta» escrita pelo planeador (07/10/2026) vale como produção conciliada: a fotografia v2 não a substitui.
        if source and (source.get('records') or source.get('origin') == DECLARED_ORIGIN) and source.get('origin') not in ('Excel provisório', 'Excel documental'):
            v.update(planning_remaining=source.get('remaining'),remaining=source.get('remaining'),
                planning_balance_origin=source.get('origin'),planning_balance_provisional=False)
            continue
        if excel_counters_changed(area, r.get('raw'), row.get('raw')):
            # Produção registada no Excel depois do retrato da pesquisa: o saldo RAW ganha.
            continue
        b = balance(r)
        from ..sector.scope import matches_current
        if calc.get('compatible') is False or not matches_current(r,v):
            b.update(planning_remaining=None, reasons=['Identidade/quantidade difere da fotografia v2.'])
        replacement = {'operation': operation, 'remaining': b['planning_remaining'],
                       'origin': b['balance_origin'],
                       'records': [], 'coverage_reasons': b['reasons'],
                       'v2_evidence': {'version': package['head']['version_id'], 'operation_id': r['operacao_id'], 'snapshot': r['snapshot_id']}}
        sources[:] = [s for s in sources if str(s.get('operation')) != operation] + [replacement]
        changed = v.get('remaining') != b['planning_remaining']
        v.update(planning_remaining=b['planning_remaining'], remaining=b['planning_remaining'], planning_balance_origin=replacement['origin'],
                 planning_balance_provisional=b['balance_provisional'])
        if changed:
            _rederive(row, replacement['origin'])


def application_balances(c, source_rows, *, records=None):
    """Reuse proven per-operation reconciliation from the application's ledger.

    An operation code repeated in a route cannot inherit an aggregate counter.
    Its occurrence needs explicit evidence, otherwise the original balance stays.
    """
    from ..raw import query
    grouped = defaultdict(list)
    for row in source_rows:
        grouped[(AREAS[row['setor']],row['linha_origem'])].append(row)
        if row.get('matched_application_key'):
            grouped[(AREAS[row['setor']],str(row['matched_application_key']).removeprefix('macro:'))].append(row)
    result = {}
    for area in planning.AREAS:
        try:
            g = query.generation(c,area); base,args = query.source(g)
        except planning.PlanningError as exc:
            if exc.status == 503:
                continue
            raise
        application_records = records if records is not None else c.execute('SELECT m.row_key,c.values_json,c.detail' + base, args).fetchall()
        for record in application_records:
            if record.get('area') not in (None,area):
                continue
            v = record['values_json']; detail = record['detail']
            aliases = {record['row_key'],*(detail.get('selection_aliases') or [])}
            candidates = {r['operacao_id']:r for alias in aliases for r in grouped.get((area,str(alias).removeprefix('macro:')),[])}
            for r in candidates.values():
                if any(v.get(k) != r.get(column) for k,column in [('of','ordem_codigo'),('component_ref','referencia_original'),('quantity_required','quantidade_base'),('length_mm','comprimento_mm'),('profile','perfil')]):
                    continue
                operation = 'corte' if area=='perfis' and r['fase']=='principal' else 'abocardar' if r['operacao_codigo']=='LOCAL:ABOCARDAR' else r['operacao_codigo'].removeprefix('CPIS:')
                if sum(x['operacao_codigo']==r['operacao_codigo'] for x in candidates.values()) != 1:
                    continue
                source = next((s for s in detail.get('calculation',{}).get('production_sources',[]) if str(s.get('operation'))==operation),None)
                if source and (source.get('records') or source.get('origin')==DECLARED_ORIGIN) and source.get('origin') not in ('Excel provisório','Excel documental'):
                    result[r['operacao_id']] = {'saldo_confirmado':source.get('remaining'),
                        'saldo_documental':None if source.get('remaining') is None else r.get('saldo_documental'),
                        'application_balance_evidence':source, 'execution_started':bool(source.get('made') or source.get('records'))}
                elif (r['fase']=='principal' and source and not source.get('v2_evidence') and source.get('remaining') is not None
                      and excel_counters_changed(area, r.get('raw'), detail.get('raw'))):
                    # O Excel atual tem produção posterior ao retrato da pesquisa: o mesmo saldo RAW da Carteira.
                    result[r['operacao_id']] = {'saldo_confirmado':None,'saldo_documental':source.get('remaining'),
                        'application_balance_evidence':source,'execution_started':bool(source.get('value'))}
    return result


def main():
    from dotenv import load_dotenv
    from psycopg.conninfo import make_conninfo
    load_dotenv('.env')
    if not os.getenv('MES_PG_DSN'):
        os.environ['MES_PG_DSN']=make_conninfo(host=os.getenv('MES_PG_HOST','127.0.0.1'),port=os.getenv('MES_PG_PORT','5432'),
            dbname=os.getenv('MES_PG_DB','dataresearchmtg'),user=os.getenv('MES_PG_USER','mes_kanban_app'),password=os.getenv('MES_PG_PASSWORD',''))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Read source only, without publishing')
    args = parser.parse_args()
    if args.check:
        with connect() as c:
            p = read_source(c)
        result = {'operations': len(p['rows']), 'digest': needs.digest(p)}
    else:
        result = refresh()
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
