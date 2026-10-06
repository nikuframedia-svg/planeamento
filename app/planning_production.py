"""Operation-specific evidence. Never changes validated OCR or macro counters."""
from __future__ import annotations

import math


def number(value):
    try:
        result = float(str(value).replace(',', '.'))
        return result if math.isfinite(result) and result >= 0 else None
    except (TypeError, ValueError):
        return None


def operation_for_record(record, plans=None):
    record.pop('operation_by_plan_key', None)
    if record.get('source')=='ocr_original':
        explicit=str((record.get('extra') or {}).get('operation_code') or '').strip()
        if not explicit:return 'operacao_por_confirmar'
        codes={op['operation'] for line in (plans or []) if line.get('source_app')==record.get('source_app') for op in operations_for_line(line)}
        if explicit in codes:
            record['operation_basis']={'kind':'recorded_code','value':explicit}
            return explicit
        # Original templates cover other factory operations as well: a machine
        # name alone cannot authorize a planning operation.
        return 'operacao_por_confirmar'
    if record.get('source_app') != 'kanban-mes-mtg2':
        # A machine is never operation evidence. An explicitly recorded code or
        # the sole applicable operation of an unambiguously identified piece is.
        extra=record.get('extra') or {}
        explicit=extra.get('operation_code') or extra.get('operacao')
        if explicit is not None:
            codes={op['operation'] for line in (plans or []) for op in operations_for_line(line)}
            if str(explicit).strip() in codes:
                record['operation_basis']={'kind':'recorded_code','value':str(explicit).strip()}
                return str(explicit).strip()
        if plans is not None and record.get('association_status') in ('explicit','technical_unique'):
            matched=[line for line in plans if line['plan_key'] in record.get('resolved_plan_keys',[])]
            sequences=[operations_for_line(line) for line in matched]
            unique={ops[0]['operation'] for ops in sequences if len(ops)==1}
            if sequences and all(len(ops)==1 and not ops[0].get('requires_operation_review') for ops in sequences) and len(unique)==1:
                code=next(iter(unique))
                record['operation_basis']={'kind':'sole_piece_operation','plan_keys':[line['plan_key'] for line in matched],'code':code}
                return code
            # Barra com vários filhos: a regra é por peça. Cada filho com uma só
            # operação recebe essa operação; os filhos com 2.ª operação ficam por
            # confirmar sem anular a produção dos irmãos.
            per_child={line['plan_key']:ops[0]['operation'] for line,ops in zip(matched,sequences)
                       if len(ops)==1 and not ops[0].get('requires_operation_review')}
            if len(matched)>1 and per_child:
                record['operation_by_plan_key']=per_child
                record['operation_basis']={'kind':'sole_piece_operation_per_child','codes':per_child}
        return 'operacao_por_confirmar'
    machine = ' '.join(str(record.get('machine') or '').split()).casefold()
    if machine in ('abocardar', 'maq. abocardar'):
        return 'abocardar'
    # Os modelos de 22/09 usam nomes curtos ('DISCO PAV1', 'FITA PAV1'): são as
    # mesmas serras de disco e de fita, logo também corte.
    if any(word in machine for word in ('serrote', 'vanguard', 'meba', 'doall', 'corte', 'disco', 'fita')):
        return 'corte'
    return 'operacao_por_confirmar'


def record_operation(record, plan_key):
    """Operação do registo para uma linha concreta (filho de barra incluído)."""
    return (record.get('operation_by_plan_key') or {}).get(plan_key, record.get('operation'))


def operations_for_line(line):
    raw = line.get('operation_inputs') or {}
    required = number(line.get('quantity_planned'))
    if line.get('source_app') == 'kanban-mes-mtg2':
        result = [{'operation': 'corte', 'label': 'Corte',
                   'macro_quantity': number(raw.get('Ser.')),
                   'macro_remaining': number(line.get('remaining_quantity')) if line.get('remaining_valid') else None,
                   'remaining_origin': 'Qtd em Falta'}]
        mark = str(raw.get('Aborc.') or '').strip().upper().lstrip("'")
        if mark not in ('', '-', 'NÃO', 'NAO'):
            accumulated = number(raw.get('Aboc.'))
            recognized = mark == 'X'
            result.append({'operation': 'abocardar',
                           'label': 'Abocardar' if recognized else 'Abocardar — indicação por confirmar',
                           'macro_quantity': accumulated,
                           'macro_remaining': max(required - accumulated, 0) if recognized and required is not None and accumulated is not None else None,
                           'remaining_origin': 'QTD − Aboc.' if recognized else 'Indicação desconhecida'})
        return result
    codes = [str(raw.get(key) or '').strip() for key in ('1ª Oper.', '2ª Oper.')]
    codes = list(dict.fromkeys(code for code in codes if code.isdigit() and code != '0'))
    if codes:
        return [{'operation':code,'label':'Operação '+code,
                 'macro_quantity':number(line.get('quantity_made')) if i==0 else None,
                 'macro_remaining':number(line.get('remaining_quantity')) if i==0 and line.get('remaining_valid') else None,
                 'remaining_origin':line.get('remaining_rule') if i==0 else 'Acumulado próprio da segunda operação desconhecido'} for i,code in enumerate(codes)]
    return [{'operation': 'operacao_por_confirmar',
             'label': 'Operações ' + ' / '.join(codes) if codes else 'Operação por confirmar',
             'macro_quantity': number(line.get('quantity_made')),
             'macro_remaining': number(line.get('remaining_quantity')) if line.get('remaining_valid') else None,
             'remaining_origin': line.get('remaining_rule'),
             'requires_operation_review': True}]


def attach_operation_evidence(plans, produced):
    for record in produced:
        record['operation'] = operation_for_record(record, plans)
    for line in plans:
        operations = operations_for_line(line)
        related = [record for record in produced
                   if record.get('association_status') in ('explicit', 'technical_unique')
                   and line['plan_key'] in record.get('resolved_plan_keys', [])]
        known_operations = {item['operation'] for item in operations}
        if 'abocardar' not in known_operations and any(r['operation'] == 'abocardar' for r in related):
            operations.append({'operation': 'abocardar', 'label': 'Abocardar — não indicado no plano',
                               'macro_quantity': number((line.get('operation_inputs') or {}).get('Aboc.')),
                               'macro_remaining': None, 'remaining_origin': 'Necessidade por confirmar',
                               'requires_need_review': True})
        for operation in operations:
            records = [record for record in related if record_operation(record, line['plan_key']) == operation['operation']]
            facts = []
            for record in records:
                refs = record.get('resolved_plan_refs') or []
                quantity = next((ref.get('assumed_quantity') for ref in refs
                                 if ref['plan_key'] == line['plan_key']), None)
                facts.append({'record_id': record['id'], 'sheet_uid': record['sheet_uid'],
                              'row_index': record['row_index'], 'quantity': number(quantity),
                              'operation': record_operation(record, line['plan_key']),
                              'validated_at': record.get('validated_at'),
                              **({k:record[k] for k in ('source','instance_id','source_revision','source_content_hash')} if record.get('source')=='ocr_original' else {})})
            unresolved = [record for record in produced if
                (line['plan_key'] in record.get('association_candidates',[]) or
                 line['plan_key'] in record.get('resolved_plan_keys',[]) and record_operation(record, line['plan_key'])=='operacao_por_confirmar')
                and record_operation(record, line['plan_key']) in (operation['operation'],'operacao_por_confirmar')
                and record.get('association_status') not in ('unrelated',)]
            reasons = ['Registo '+str(record['id'])+': identidade ou operação por confirmar.' for record in unresolved]
            origins={(f.get('source','mes'),f.get('instance_id')) for f in facts}
            if len(origins)>1:reasons.append('Sobreposição entre origens OCR por resolver.')
            complete = bool(facts) and not reasons and all(fact['quantity'] is not None for fact in facts)
            operation.update(ocr_quantity=sum(f['quantity'] for f in facts) if complete else None,
                             ocr_partial=bool(facts) and not complete,
                             coverage_reasons=reasons,
                             ocr_records=facts,
                             conference_allowed=operation['operation'] in ('corte', 'abocardar'))
        # Unknown operations stay in the evidence list and never join cut totals.
        line['operations'] = operations


def conference_evidence(line, operation, cpis_version):
    selected = next((item for item in line.get('operations', []) if item['operation'] == operation), None)
    if not selected or not selected.get('conference_allowed'):
        return None
    return {'contract': 'operation-evidence-v1', 'cpis_version': cpis_version,
            'plan_line': {key: line.get(key) for key in (
                'plan_key', 'snapshot_id', 'source_app', 'component_ref', 'profile_type',
                'material_type', 'length_mm', 'quantity_planned')},
            'operation': operation, 'operation_label': selected['label'],
            'macro_quantity': selected['macro_quantity'],
            'macro_remaining': selected['macro_remaining'], 'ocr_records': selected['ocr_records']}
