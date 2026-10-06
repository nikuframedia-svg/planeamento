"""One closure rule for planning consumers; never deletes source/history facts.

CPIS states observed in the source inventory: Em Aberto, Em Produção,
Fechada and Pronta. Only Fechada declares closure. Unknown states remain
visible with their diagnostic; production percentage is not a closure source.
When the two imported CPIS copies disagree, the newest copy decides
(decisão de 06/10/2026, ver cpis_copies.latest_first).
"""
from . import planning

CPIS_CLOSED = ('fechada', 'fechado')
CPIS_OPEN = ('em aberto', 'em produção', 'pronta')
MACRO_CLOSED = ('x', 'true', '1')
MACRO_OPEN = ('', '-', 'false', '0')
SCOPES = ('active', 'history', 'all')


def token(value):
    return str(value if value is not None else '').strip().lower()


def scope(value=None):
    value = value or 'active'
    if value not in SCOPES:
        raise planning.PlanningError('População inválida: escolhe ativo, histórico ou todos.')
    return value


def classify(row):
    values = row.get('values') or row.get('values_json') or {}
    statuses = row.get('status_values') or [row.get('status') or values.get('status')]
    macros = row.get('macro_closure_values')
    if macros is None:
        macros = [(row.get('raw') or {}).get('Fechado'), row.get('closed_x'), values.get('macro_closed')]
    closed = []
    if any(token(s) in CPIS_CLOSED for s in statuses):
        closed.append('CPIS')
    if any(token(s) in MACRO_CLOSED for s in macros):
        closed.append('Macro')
    unknown = [{'source': 'CPIS', 'value': s} for s in statuses if token(s) and token(s) not in CPIS_CLOSED + CPIS_OPEN]
    unknown += [{'source': 'Macro', 'value': s} for s in macros if token(s) not in MACRO_CLOSED + MACRO_OPEN]
    return {'active': not closed, 'closed_sources': closed, 'unknown_states': unknown,
            'rule': 'CPIS fechado OU linha fechada na macro', 'contract': 'population-v1'}


def annotate(row):
    population = classify(row)
    row['population'] = population
    row['values'].update(planning_active=population['active'],
                         closure_reason=' + '.join(population['closed_sources']) or None)
    for state in population['unknown_states']:
        warning = f"Estado de fecho desconhecido ({state['source']}): {state['value']}. Não interpretado como fechado."
        if warning not in row.setdefault('warnings', []):
            row['warnings'].append(warning)
    return row


def includes(row, population=None):
    population = scope(population)
    active = (row.get('population') or classify(row))['active']
    return population == 'all' or active == (population == 'active')


def active_sql():
    """Same rule for immutable generations, including those made before v1.

    New generations carry the classification. The fallback lets saved versions
    keep working without making a pre-v1 closed row active by default.
    """
    def literals(items):
        return ','.join("'" + x.replace("'", "''") + "'" for x in items)
    return """CASE WHEN c.values_json->>'planning_active' IN ('true','false')
        THEN (c.values_json->>'planning_active')::boolean
        ELSE NOT (
          EXISTS (SELECT 1 FROM jsonb_array_elements_text(
            CASE WHEN jsonb_array_length(coalesce(c.detail->'status_values','[]'))>0
              THEN c.detail->'status_values'
              ELSE jsonb_build_array(coalesce(c.detail->>'status',c.values_json->>'status')) END
          ) s(value) WHERE lower(btrim(s.value)) IN (""" + literals(CPIS_CLOSED) + """))
          OR EXISTS (SELECT 1 FROM jsonb_array_elements_text(
            coalesce(c.detail->'macro_closure_values',jsonb_build_array(
              c.detail->'raw'->'Fechado',c.detail->'closed_x',c.values_json->'macro_closed'))
          ) s(value) WHERE lower(btrim(s.value)) IN (""" + literals(MACRO_CLOSED) + """))
        ) END"""
