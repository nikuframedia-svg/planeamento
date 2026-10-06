"""Lossless manual registration; applicability warnings never reject the input.

The normalized projection is used by calculations. Original entered values are
kept for editing, audit and synchronization even when no calculation is possible.
Database identities, command idempotency and optimistic locking remain intact.
"""
import math
import os
from datetime import date


def enabled():
    return os.getenv('MES_PLANNING_FREE_ENTRY', '0') == '1'


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


def normalize(raw, cat, previous=None):
    from .. import planning_catalogs as catalogs
    previous = previous or {}
    data = {}
    warnings = []
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
                if name in ('quantity_required', 'quantity_to_plan', 'picking_week', 'picking_year',
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
                warnings.append({'field': name, 'message': 'Valor guardado; sem número utilizável para cálculo.'})
        elif kind == 'date':
            data[name] = iso_date(value)
            if data[name] is None and value not in (None, ''):
                warnings.append({'field': name, 'message': 'Valor guardado; data por interpretar.'})
        elif name == 'abocardar':
            data[name] = catalogs.abocardar_mark(value)
        elif kind in ('boolean', 'tristate'):
            data[name] = value if isinstance(value, bool) else None if kind == 'tristate' else False
        else:
            data[name] = '' if value is None else str(value).strip()
    if data.get('custom_profile'):
        data['profile'] = data.get('special_profile') or data.get('profile') or ''
    # Catalogue and completeness checks describe applicability, not permission to save.
    # As datas dd/mm/aaaa já convertidas não geram o aviso «data inválida» da validação do catálogo.
    checked = {**raw, **{f['id']: data[f['id']] for f in catalogs.fields()
                         if f['type'] == 'date' and f['id'] in raw and data.get(f['id'])}}
    try:
        catalogs.validate(checked, cat, ready=True, previous=previous)
    except Exception as exc:
        from ..planning import PlanningError
        if not isinstance(exc, PlanningError):
            raise
        warnings.extend({'field': name, 'message': message} for name, message in getattr(exc, 'fields', {}).items())
    unique = {(w['field'], w['message']): w for w in warnings}
    return data, list(unique.values())


def display_values(record, need):
    return {**(record.get('input_values') or {}), **(need.get('input_values') or {})}


def annotate(row, record, need):
    if not record or not need:
        return
    row['input_values'] = display_values(record, need)
    row['registration_warnings'] = record.get('registration_warnings') or []
    row['identity_pending'] = bool(need.get('identity_pending'))
    row['identity_candidates'] = need.get('identity_candidates') or []
    row['warnings'].extend(w['message'] for w in row['registration_warnings'])
    if row['identity_pending']:
        row['warnings'].append('Registo guardado; possível duplicação por associar. Excluído dos totais automáticos.')
        for preparation in row.get('preparations', []):
            preparation['capacity_compatible'] = False
        row['values']['planning_remaining'] = None


def display(row):
    """Display the entered text without changing numeric filtering/calculation."""
    result = dict(row)
    result['values'] = {**row.get('values', {}), **row.get('input_values', {})}
    return result
