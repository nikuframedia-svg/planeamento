"""Planning-only balances. An estimate never updates a production counter."""
from __future__ import annotations

from .planning_calculations import quantity
from .planning_needs import signature


def select_balance(row, operation):
    values = row.get('values') or {}
    calculation = row.get('calculation') or {}
    source = next((item for item in calculation.get('production_sources') or []
                   if str(item.get('operation')) == str(operation)), None)
    reconciled = quantity(source.get('remaining')) if source else None
    if reconciled is not None:
        origin = source.get('origin') or 'Saldo da operação'
        return {'reconciled_remaining': reconciled, 'planning_remaining': reconciled,
                'balance_origin': origin, 'provisional': origin == 'Excel provisório',
                'evidence': source.get('records') or [], 'reasons': source.get('coverage_reasons') or []}
    reasons = list((source or {}).get('coverage_reasons') or [])
    if calculation.get('compatible') is False:
        reasons.append('Identidade técnica alterada; conferir associação.')
    elif row.get('area') == 'perfis' and operation == 'corte':
        macro = quantity((row.get('raw') or {}).get('Qtd em Falta'))
        required = quantity(values.get('quantity_required'))
        original = row.get('original') or {}
        original_required = quantity(original.get('quantity_required'))
        if original and signature(values) != signature(original):
            reasons.append('Identidade técnica alterada; conferir associação.')
        elif original_required is None or required != original_required:
            reasons.append('Quantidade necessária alterada ou não comprovada na origem do saldo da macro.')
        elif macro is not None and macro <= required:
            return {'reconciled_remaining': None, 'planning_remaining': macro,
                    'balance_origin': 'Saldo da macro provisório · Qtd em Falta',
                    'provisional': True, 'evidence': [{'field': 'Qtd em Falta',
                    'snapshot': calculation.get('macro_snapshot'), 'plan_key': row.get('plan_key'),
                    'quantity_required': original_required}],
                    'reasons': reasons}
        else:
            reasons.append('Saldo provisório ausente, inválido ou superior à necessidade.')
    else:
        reasons.append('Saldo da operação por confirmar.')
    return {'reconciled_remaining': None, 'planning_remaining': None,
            'balance_origin': None, 'provisional': False, 'evidence': [],
            'reasons': list(dict.fromkeys(reasons))}
