"""Lossless manual registration; applicability warnings never reject the input.

The normalized projection is used by calculations. Original entered values are
kept for editing, audit and synchronization even when no calculation is possible.
Database identities and command idempotency remain intact.

Desde 07/10/2026 gravar é sempre livre (o que era MES_PLANNING_FREE_ENTRY=1): só os
avisos essenciais, como texto ao lado do campo, e nunca a impedir a gravação.
"""
import math
import os
from datetime import date


def enabled():
    """Interruptor antigo; o registo manual já não depende dele (07/10/2026)."""
    return os.getenv('MES_PLANNING_FREE_ENTRY', '0') == '1'


# Valores por defeito quando o campo fica vazio (07/10/2026). Nas cantoneiras a 1.ª Oper. 119 é a
# habitual em todas as máquinas (83% das linhas importadas a 07/10) e a 2.ª Oper. 0 é «sem segunda operação».
DEFAULTS = {'perfis': {'operation': 'corte'},
            'cantoneiras': {'operation': '119', 'operation_detail': '0'}}

# Os únicos avisos do registo (07/10/2026): dizem o que fica sem cálculo e nunca bloqueiam.
WARNINGS = {
    'quantity_required': 'QTD tem de ser um número inteiro (senão não entra na Carteira)',
    'length_mm': 'Sem comprimento: sem metros nem horas',
    'machine': 'Sem máquina: será usada a sugerida ao planear',
    'section': 'Sem área de corte: sem horas',
    'operation': 'Operação não numérica: sem horas',
}
ESSENTIAL = frozenset(WARNINGS.values())


def iso_date(value):
    """AAAA-MM-DD, também a partir de dd/mm/aaaa ou dd-mm-aaaa (como se escreve na fábrica); None se não for data."""
    if value in (None, ''):
        return None
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10] if len(text) > 10 and text[10] in 'T ' else text).isoformat()
    except ValueError:
        pass
    parts = text.replace('-', '/').replace('.', '/').split('/')
    if len(parts) == 3 and all(p.strip().isdigit() for p in parts) and len(parts[2].strip()) == 4:
        try:
            return date(int(parts[2]), int(parts[1]), int(parts[0])).isoformat()
        except ValueError:
            return None
    return None


def normalize(raw, cat, previous=None, *, sections=None):
    """(valores para cálculo, avisos essenciais). `sections` é a tabela AreaSecaoCorte dos perfis."""
    from .. import planning_catalogs as catalogs
    previous = previous or {}
    data = {}
    for field in catalogs.fields():
        name, kind = field['id'], field['type']
        value = raw.get(name, previous.get(name))
        if kind == 'number':
            if value in (None, ''):
                data[name] = None
                continue
            try:
                number = float(str(value).replace(',', '.'))
                if isinstance(value, bool) or not math.isfinite(number) or abs(number) > 1e9:
                    raise ValueError()
                if number < 0 and name != 'angle_deg':
                    raise ValueError()
                if name in ('quantity_required', 'quantity_to_plan', 'remaining_declared', 'picking_week', 'picking_year',
                            'planned_week', 'planned_year', 'finish_week', 'finish_year') and not number.is_integer():
                    raise ValueError()
                if name.endswith('_mm') and number <= 0:
                    raise ValueError()
                if name.endswith('_week') and not 1 <= number <= 53:
                    raise ValueError()
                if name.endswith('_year') and not 2000 <= number <= 2100:
                    raise ValueError()
                data[name] = number
            except (ValueError, TypeError, OverflowError):
                data[name] = None
        elif kind == 'date':
            data[name] = iso_date(value)
        elif name == 'abocardar':
            data[name] = catalogs.abocardar_mark(value)
        elif kind in ('boolean', 'tristate'):
            data[name] = value if isinstance(value, bool) else None if kind == 'tristate' else False
        else:
            data[name] = '' if value is None else str(value).strip()
    if data.get('custom_profile'):
        data['profile'] = data.get('special_profile') or data.get('profile') or ''
    area = cat.get('area')
    for name, value in DEFAULTS.get(area, {}).items():
        if data.get(name) in (None, ''):
            data[name] = value
    return data, warnings_for(data, area, sections)


def machine(value):
    """A máquina como a Carteira a lê: «Por definir», «Sem máquina»… contam como sem máquina."""
    try:
        from ..sector.machine_choice import normalize
    except ImportError:  # o MES partilha este módulo sem a Carteira
        return str(value or '').strip()
    return normalize(value)


def warnings_for(data, area, sections=None):
    """Avisos essenciais, por campo. A área de corte só é verificada quando há tabela de secções."""
    found = []
    if data.get('quantity_required') is None:
        found.append(('quantity_required', WARNINGS['quantity_required']))
    if data.get('length_mm') is None:
        found.append(('length_mm', WARNINGS['length_mm']))
    if not machine(data.get('machine')):
        found.append(('machine', WARNINGS['machine']))
    if area == 'perfis' and sections is not None:
        from ..planning_calculations import section
        if section(data, sections)[0] is None:
            found.append(('profile', WARNINGS['section']))
    if area == 'cantoneiras' and not str(data.get('operation') or '').strip().isdigit():
        found.append(('operation', WARNINGS['operation']))
    return [{'field': field, 'message': message} for field, message in found]


def display_values(record, need):
    return {**(record.get('input_values') or {}), **(need.get('input_values') or {})}


def annotate(row, record, need):
    if not record or not need:
        return
    row['input_values'] = display_values(record, need)
    # Só os avisos essenciais; os avisos antigos guardados (catálogo, geometria…) deixam de aparecer.
    row['registration_warnings'] = [w for w in record.get('registration_warnings') or []
                                    if w.get('message') in ESSENTIAL]
    # A peça possivelmente repetida já não fica «por associar» nem perde o saldo (07/10/2026).
    # As chaves ficam por compatibilidade com quem as lê (Gantt, sincronização da pesquisa).
    row['identity_pending'] = False
    row['identity_candidates'] = []
    row['warnings'].extend(w['message'] for w in row['registration_warnings'])


def display(row):
    """Display the entered text without changing numeric filtering/calculation."""
    result = dict(row)
    result['values'] = {**row.get('values', {}), **row.get('input_values', {})}
    return result
