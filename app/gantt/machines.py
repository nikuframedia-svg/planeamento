"""Technical eligibility, documentary evidence and deterministic machine choices."""
from __future__ import annotations

from collections import defaultdict
import re

from .. import planning, planning_needs as needs

CONDITIONS = {
    'confirmar_cliente_nacional', 'confirmar_graminho_ferramentas_e_desenho',
    'confirmar_numero_de_diametros_da_peca', 'mudanca_112_para_119_requer_decisao',
    'revisao_tecnica_por_validar', 'confirmar_geometria_furacao_e_revisao',
    'limites_por_validar', 'perfil_por_interpretar', 'abas_desiguais_por_validar',
    'rota_por_validar', 'recurso_da_operacao_por_validar', 'processo_119_em_puncao_por_confirmar',
}
# A punching machine becomes a (conditional) candidate for code 119 only when the workbook
# history shows that practice on it; the capacity sheet itself lists only 112 for these machines.
OBSERVED_PRACTICE_LINES = 20
SECONDARY_RESOURCES = {'CPIS:1410': 'SOLDADURA', 'CPIS:1003': 'FURACAO_MANUAL',
                       'CPIS:209': 'FURACAO_MANUAL', 'CPIS:98': 'QUINADORA_MTG2',
                       'CPIS:99': 'QUINADORA_MTG2', 'LOCAL:ABOCARDAR': 'ABOCARDAR'}


def dimensions(profile):
    text = re.sub(r'\s', '', str(profile or '').upper()).replace(',', '.')
    # The capacity sheet itself writes «L40xx40x3»: a repeated separator is still one separator.
    found = re.fullmatch(r'L([0-9.]+)[X×*]+([0-9.]+)[X×*]+([0-9.]+)', text)
    try:
        return tuple(float(v) for v in found.groups()) if found else None
    except ValueError:
        return None


def screening(row, capacity):
    if not capacity.get('perfil_minimo') or not capacity.get('perfil_maximo'):
        return 'limites_por_validar'
    value, low, high = map(dimensions, (row.get('perfil'), capacity['perfil_minimo'], capacity['perfil_maximo']))
    if not value or not low or not high:
        return 'perfil_por_interpretar'
    if value[0] != value[1]:
        return 'abas_desiguais_por_validar'
    return 'dentro_intervalo_documental' if all(a <= b <= c for a, b, c in zip(low, value, high)) else 'fora_intervalo_documental'


def validate_rules(rules):
    if not isinstance(rules, list) or len(rules) > 1000:
        raise planning.PlanningError('Regras técnicas inválidas.')
    for rule in rules:
        if (not isinstance(rule, dict) or not rule.get('operation_code')
            or not rule.get('reason') or not rule.get('confirmed')
            or not (rule.get('signature') or (rule.get('profile') and rule.get('grade')))
            or not isinstance(rule.get('resolved_conditions', []), list)
            or set(rule.get('resolved_conditions', [])) - CONDITIONS):
            raise planning.PlanningError('Cada regra exige operação, âmbito técnico, confirmação e motivo.')
        if 'confirmar_cliente_nacional' in rule.get('resolved_conditions',[]) and not rule.get('order_code'):
            raise planning.PlanningError('A condição de mercado nacional exige a OF; não se transfere entre clientes.')
    return rules


def matching_rules(row, resource):
    result = []
    for rule in resource.get('technical_rules', []):
        if not rule.get('confirmed') or rule.get('operation_code') != row['operacao_codigo']:
            continue
        if rule.get('signature'):
            matches = rule['signature'] == row.get('assinatura')
        else:
            matches = rule.get('profile') == row.get('perfil') and rule.get('grade') == row.get('qualidade')
        if matches and ('revision' not in rule or rule['revision'] == row.get('revisao_desenho')) and (not rule.get('order_code') or rule['order_code']==row['ordem_codigo']):
            result.append(rule)
    return result


class EvidenceIndex:
    def __init__(self, metadata, rows):
        self.capacities = defaultdict(list)
        for capacity in metadata['capacities']:
            self.capacities[capacity['operacao_codigo']].append(capacity)
        self.history = defaultdict(set)
        self.variant_resources = defaultdict(set)
        self.practice = defaultdict(int)  # (operation code, resource) → executed lines
        for h in metadata['history']:
            self.practice[(h['operacao_codigo'], h['recurso_atual'])] += 1
            key = (h['variante_id'], h['operacao_codigo'], h['recurso_atual'],
                   tuple(h['route'][1:]), h['segunda_operacao_estado'])
            self.history[key].add(h['ordem_codigo'])
            self.variant_resources[h['variante_id']].add(h['recurso_atual'])
        self.events = defaultdict(set)
        self.mes_resources = defaultdict(set)
        for e in metadata['events']:
            of = str(e.get('ordem_original') or '').strip().upper()
            of = 'OF' + re.sub(r'^OF[ ._-]*', '', of) if of else None
            key = (e['setor'], e['referencia_original'], e['comprimento_mm'],
                   str(e.get('perfil_original') or '').strip().upper(), e['recurso_codigo'])
            if of:
                self.events[key].add(of)
                self.mes_resources[key[:4]].add(key[4])
        self.routes = defaultdict(list)
        for row in sorted(rows, key=lambda r: (r['item_id'], r['ocorrencia'])):
            self.routes[row['item_id']].append(row['operacao_codigo'])

    def candidates(self, row, resources_by_code):
        code = row['operacao_codigo']; base = list(self.capacities.get(code, []))
        if row['setor'] == 'MTG3' and row['fase'] == 'principal' and code == 'CPIS:112':
            base += self.capacities.get('CPIS:119', [])
        practice = set()
        if row['setor'] == 'MTG3' and row['fase'] == 'principal' and code == 'CPIS:119':
            listed = {c['recurso_codigo'] for c in base}
            for capacity in self.capacities.get('CPIS:112', []):
                if capacity['recurso_codigo'] not in listed and self.practice[(code, capacity['recurso_codigo'])] >= OBSERVED_PRACTICE_LINES:
                    base.append(capacity)
                    practice.add(capacity['recurso_codigo'])
        result = []
        for capacity in base:
            # Correção local da ficha de capacidades (Definições do setor, 06/10/2026): substitui o intervalo.
            override = ((resources_by_code.get(capacity['recurso_codigo']) or {}).get('capacity_override') or {})
            local = override.get(capacity['operacao_codigo']) or override.get('*')
            if local:
                capacity = {**capacity, 'perfil_minimo': local.get('min') or capacity.get('perfil_minimo'),
                            'perfil_maximo': local.get('max') or capacity.get('perfil_maximo'), 'fonte_local': True}
            observed = capacity['recurso_codigo'] in practice
            triage = screening(row, capacity)
            conditions = []
            if capacity.get('apenas_cliente_nacional'):
                conditions.append('confirmar_cliente_nacional')
            if row['setor'] == 'MTG3' and row['fase'] == 'principal':
                conditions.append('confirmar_graminho_ferramentas_e_desenho')
            if capacity.get('numero_diametros'):
                conditions.append('confirmar_numero_de_diametros_da_peca')
            if observed:
                conditions.append('processo_119_em_puncao_por_confirmar')
            elif capacity['operacao_codigo'] != code:
                conditions.append('mudanca_112_para_119_requer_decisao')
            if not row.get('identidade_tecnica_confirmada'):
                conditions.append('revisao_tecnica_por_validar')
            if triage not in ('dentro_intervalo_documental', 'fora_intervalo_documental'):
                conditions.append(triage)
            result.append({'resource_code': capacity['recurso_codigo'],
                           'proposed_code': code if observed else capacity['operacao_codigo'], 'process': capacity['processo_fisico'],
                           'triage': triage, 'conditions': conditions,
                           'origin': 'pratica_observada' if observed else 'ficha_capacidade',
                           'evidence': [{'capacity_id': capacity['id'], 'source': capacity['fonte']}] +
                                       ([{'observed_lines': self.practice[(code, capacity['recurso_codigo'])],
                                          'source': 'Histórico do Excel: linhas 119 executadas nesta máquina'}] if observed else [])})
        extras = set()
        if row['fase'] == 'principal':
            if row.get('recurso_atual'):
                extras.add(row['recurso_atual'])
            if row['setor'] == 'MTG2':
                extras.update(self.variant_resources.get(row.get('variante_id'), set()))
                mes_key = (row['setor'], row['referencia_original'], row.get('comprimento_mm'), str(row.get('perfil') or '').strip().upper())
                extras.update(self.mes_resources.get(mes_key, set()) & {'POSTO_DISCO', 'POSTO_FITA', 'MEBA', 'MAQFORT', 'VANGUARD', 'LASER_TUBO', 'PLASMA_TUBO'})
                if row.get('application_row_key'):
                    extras.update(code for code,r in resources_by_code.items() if code in {'POSTO_DISCO','POSTO_FITA','MEBA','MAQFORT','VANGUARD','LASER_TUBO','PLASMA_TUBO'}
                        and ('corte' in r.get('operations',[]) or 'LOCAL:PRINCIPAL' in r.get('operations',[])))
        else:
            if code in SECONDARY_RESOURCES:
                extras.add(SECONDARY_RESOURCES[code])
            if row.get('recurso_atual'):
                # A máquina do planeamento/Excel de uma operação seguinte também fica, mesmo fora da ficha de
                # capacidades, como na operação principal (plano de 07/10/2026; antes só no segundo programa).
                extras.add(row['recurso_atual'])
        for resource in sorted(extras):
            if any(x['resource_code'] == resource and x['proposed_code'] == code for x in result):
                continue
            result.append({'resource_code': resource, 'proposed_code': code, 'process': None,
                           'triage': 'compatibilidade_tecnica_por_validar',
                           'conditions': ['confirmar_geometria_furacao_e_revisao'],
                           'origin': 'atribuicao_atual' if resource == row.get('recurso_atual') else 'encaminhamento_documental',
                           'evidence': []})
        for option in result:
            resource = resources_by_code.get(option['resource_code'])
            if not resource:
                option.update(eligibility='excluded', reasons=['Recurso sem identidade no Gantt.'])
                continue
            option['resource_id'] = resource['id']
            key = (row.get('variante_id'), option['proposed_code'], option['resource_code'],
                   tuple(self.routes[row['item_id']][1:]), row.get('segunda_operacao_estado'))
            option['other_orders'] = len(self.history.get(key, set()) - {row['ordem_codigo']}) if row['ocorrencia'] == 1 else 0
            mes_key = (row['setor'], row['referencia_original'], row.get('comprimento_mm'),
                       str(row.get('perfil') or '').strip().upper(), option['resource_code'])
            option['mes_orders'] = len(self.events.get(mes_key, set()) - {row['ordem_codigo']}) if row['ocorrencia'] == 1 else 0
            option['historical_limitations'] = 'Contadores documentais sem anterioridade demonstrada; MES sem código de operação. Fontes separadas.'
            rules = matching_rules(row, resource)
            resolved = {c for rule in rules for c in rule.get('resolved_conditions', [])}
            option['conditions'] = sorted(set(option['conditions']) - resolved)
            option['evidence'] += [{'rule': r, 'resource_revision': resource.get('revision')} for r in rules]
            excluded = option['triage'] == 'fora_intervalo_documental' and not any(r.get('allow_documental_exception') for r in rules)
            option['eligibility'] = 'excluded' if excluded else 'conditional' if option['conditions'] else 'admissible'
            option['reasons'] = ['Perfil fora do intervalo documental.'] if excluded else list(option['conditions'])
            team = re.sub(r'\D', '', str(row.get('equipa') or (row.get('raw') or {}).get('Equipa') or ''))
            option['team_preference'] = (team == '5' and option['resource_code'] == 'POSTO_DISCO') or (team == '6' and option['resource_code'] == 'POSTO_FITA')
            option['code_change'] = option['proposed_code'] != code
        return result


def choose(candidates, source_resource, *, override=None, peer=None, process=None):
    usable = [o for o in candidates if o['eligibility'] != 'excluded']
    if override:
        selected = next((o for o in usable if o.get('resource_id') == override), None)
        return selected, 'Escolha manual' if selected else 'Escolha manual incompatível ou sem correspondência'
    if source_resource:
        # A máquina do planeador (Carteira, Tabela ou conjunto de famílias) fica sempre, mesmo fora da ficha
        # de capacidades (decisão do Luís, 05/10/2026: o Excel é o oficial; sem avisos).
        own = [o for o in candidates if o.get('resource_id') == source_resource]
        if own:
            return min(own, key=lambda o: (o['eligibility'] == 'excluded', o['eligibility'] != 'admissible')), 'Mantém atribuição documentada'
    if not usable:
        return None, 'Sem candidata documental utilizável'
    comparable=all(o.get('duration') and 'finish_minute' in o for o in usable)
    def rank(option):
        # Without calendars, an option that depends on a third party (national market, the
        # 112 → 119 change) must not win a tie only because of its resource code.
        return (option['eligibility'] != 'admissible',
                option.get('lateness_minutes', 0) if comparable else 0,
                option.get('resource_id') != source_resource,
                bool(peer) and option.get('resource_id') != peer,
                bool(process) and option.get('process') not in (None, process),
                bool({'confirmar_cliente_nacional', 'mudanca_112_para_119_requer_decisao'}.intersection(option.get('conditions', []))),
                not option.get('team_preference'),
                option.get('code_change', False),
                -option.get('other_orders', 0),
                option.get('finish_minute', float('inf')) if comparable else 0,
                option.get('resource_code', ''), option.get('proposed_code', ''))
    selected = min(usable, key=rank)
    reason = ('Mantém atribuição documentada' if selected.get('resource_id') == source_resource else
              'Mesma máquina das outras linhas da OF com este perfil e operação' if peer and selected.get('resource_id') == peer else
              'Evita atraso previsto' if comparable and any(o.get('lateness_minutes', 0) > selected.get('lateness_minutes', 0) for o in usable) else
              'Preferência de equipa' if selected.get('team_preference') else
              'Compatibilidade e evidência documental')
    if not comparable:
        reason += ' · tempos/calendários sem comparação suficiente'
    if sum(rank(o)[:-2]==rank(selected)[:-2] for o in usable)>1:
        reason += ' · empate documental resolvido pelo código do recurso'
    return selected, reason
