"""Estudo de capacidade das máquinas MTG2/MTG3 e validação do algoritmo. Só leitura.

Uso (raiz do projeto): .venv/bin/python docs/capacidade-maquinas-2026-10-01/analisar.py
Escreve CSV e resumo.json nesta pasta; não altera dados da aplicação.
"""
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / '.env')
os.environ.setdefault('MES_PLANNING_V2_ENABLED', '1')
from app import planning
from app.gantt import machines
from app.sector import capacity, estimates, occurrences, throughput

OUT = Path(__file__).resolve().parent
TODAY = date.fromisoformat(os.environ.get('ESTUDO_HOJE', date.today().isoformat()))


def save(name, rows):
    if not rows:
        return
    with (OUT / name).open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def backtest(series, train=8):
    """Predict each week with the median of the previous `train` weeks; whole weeks, not lines."""
    result = []
    for machine, weeks in series.items():
        hours = [w['hours'] for w in weeks]
        for i in range(train, len(hours)):
            past = hours[i - train:i]
            p25, p50, p75 = (throughput.quantile(past, q) for q in (.25, .5, .75))
            result.append({'maquina': machine, 'semana': weeks[i]['iso'], 'horas_observadas': round(hours[i], 2),
                           'previsao_mediana': round(p50, 2), 'p25': round(p25, 2), 'p75': round(p75, 2),
                           'erro_absoluto': round(abs(hours[i] - p50), 2), 'dentro_p25_p75': p25 <= hours[i] <= p75})
    return result


with planning.connect(readonly=True) as c:
    c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
    snap = planning.snapshot(c, 'cantoneiras')
    rows = [r['row_data'] for r in c.execute('SELECT row_data FROM raw_mtg.plan_production_rows WHERE snapshot_id=%s', (snap['snapshot_id'],)).fetchall()]
    until = date.fromisoformat(str(snap['loaded_at'])[:10])
    study = throughput.load(c)
    long = throughput.weekly_mtg3(rows, until=until, weeks=32)
    data = occurrences.build(c, 'cantoneiras', TODAY)
    perfis = occurrences.build(c, 'perfis', TODAY)
    codes, by_id, aliases, configs, package = occurrences.resources_context(c)
    observed, declared = capacity.evidence(c, by_id, aliases)
    cap = capacity.view(['perfis', 'cantoneiras'], horizon_weeks=12, today=TODAY)

# 1. Weekly executed theoretical hours (16 complete weeks) and their predictability (32 weeks, 8 to learn).
save('debito-semanal-mtg3.csv', [{'maquina': m, **{k: w[k] for k in ('iso', 'week', 'hours', 'metres', 'lines', 'orders', 'observed_zero')}}
                                 for m, weeks in study['weekly']['series'].items() for w in weeks])
tests = backtest(long['series'])
save('validacao-previsao-semanal.csv', tests)
quality = {}
for machine in sorted({t['maquina'] for t in tests}):
    mine = [t for t in tests if t['maquina'] == machine]
    observed_total = sum(t['horas_observadas'] for t in mine)
    quality[machine] = {'semanas_testadas': len(mine),
                        'erro_ponderado_pct': round(100 * sum(t['erro_absoluto'] for t in mine) / observed_total, 1) if observed_total else None,
                        'cobertura_p25_p75_pct': round(100 * sum(t['dentro_p25_p75'] for t in mine) / len(mine), 1)}

# 2. Suggestion check: hide the machine of lines that have one and see what the rule proposes.
names = throughput.aliases_to_names(by_id)
index = machines.EvidenceIndex(package['metadata'], package['rows'] + [r for r in data['_rows'].values() if r.get('application_row_key')])
checks = []
processes = estimates.group_processes(data['facts'])
peers = defaultdict(Counter)
for fact in data['facts']:
    if fact['phase'] == 'principal' and fact['machine_basis'] == 'atribuída':
        peers[estimates.group_key(fact)][fact['assigned_resource_id']] += 1
for fact in data['facts']:
    if fact['phase'] != 'principal' or fact['machine_basis'] != 'atribuída' or fact['decision']:
        continue
    row = data['_rows'].get(fact['key'])
    candidates = [o for o in index.candidates(row, codes) if o.get('resource_id') and o['eligibility'] != 'excluded']
    if not candidates:
        continue
    others = Counter(peers[estimates.group_key(fact)]); others[fact['assigned_resource_id']] -= 1  # never the line itself
    peer = estimates.peer_machine(others, {o['resource_id'] for o in candidates})
    options = [(estimates.score(o, peer=peer, process=processes.get(estimates.group_key(fact))), o) for o in candidates]
    best = min(options, key=lambda x: x[0])[1]
    actual = fact['assigned_resource_id']
    family = lambda rid: (by_id.get(rid) or {}).get('code', '')[:5]
    checks.append({'of': fact['of'], 'referencia': fact['reference'], 'maquina_excel': fact['assigned_machine'],
                   'sugerida_sem_carga': by_id[best['resource_id']]['name'], 'precedente_of': best.get('other_orders') or 0,
                   'com_linhas_da_mesma_of': peer is not None,
                   'candidatas': len(options), 'excel_entre_candidatas': any(o['resource_id'] == actual for _, o in options),
                   'acerto': best['resource_id'] == actual, 'acerto_mesma_familia': family(best['resource_id']) == family(actual)})
save('validacao-sugestoes.csv', checks)
by_bucket = defaultdict(list)
for x in checks:
    by_bucket['2+ OF' if x['precedente_of'] >= 2 else '1 OF' if x['precedente_of'] == 1 else 'sem precedente'].append(x)
suggestions = {k: {'linhas': len(v), 'acerto_pct': round(100 * sum(x['acerto'] for x in v) / len(v), 1),
                   'acerto_familia_pct': round(100 * sum(x['acerto_mesma_familia'] for x in v) / len(v), 1),
                   'excel_entre_candidatas_pct': round(100 * sum(x['excel_entre_candidatas'] for x in v) / len(v), 1)}
               for k, v in by_bucket.items()}
# Honest split: with neighbours already decided by the planner the rule follows them almost by construction.
for label, flag in (('com linhas vizinhas já decididas', True), ('grupo novo, sem vizinhas', False)):
    v = [x for x in checks if x['com_linhas_da_mesma_of'] == flag]
    if v:
        suggestions[label] = {'linhas': len(v), 'acerto_pct': round(100 * sum(x['acerto'] for x in v) / len(v), 1),
                              'acerto_familia_pct': round(100 * sum(x['acerto_mesma_familia'] for x in v) / len(v), 1)}

# 3. Current load per machine: documentary vs estimated hours, suggested work and weeks at observed throughput.
loads = []
for area, unit in cap['units'].items():
    for lane in unit['resources']:
        loads.append({'setor': unit['label'], 'recurso': lane['name'], 'papel': lane['role'], 'carga_h': lane['load_hours'],
                      'das_quais_estimadas_h': lane['estimated_hours'], 'ocorrencias_sugeridas': lane['suggested_occurrences'],
                      'ocorrencias_sem_horas': lane['unknown_occurrences'], 'atraso_h': lane['late_need_hours'],
                      'capacidade_semanal_h': lane['weekly_capacity_hours'], 'origem_capacidade': lane['weekly_capacity_status'],
                      'semanas_de_carga': lane['weeks_to_clear']})
save('carga-por-maquina.csv', loads)
save('velocidades-excel.csv', [{'maquina': m, 'velocidade_mediana_m_h': v['value'], 'linhas': v['lines'],
                                'valores_mais_frequentes': json.dumps(v['values'])} for m, v in study['speeds'].items()])
save('mes-horas-e-rendimento.csv', [{'setor': k[0], 'recurso': k[1], **v} for k, v in study['mes'].items()])

facts = data['facts'] + perfis['facts']
summary = {
    'gerado_em': date.today().isoformat(), 'hoje_do_estudo': TODAY.isoformat(), 'fontes': study['source'],
    'janela_debito': study['weekly']['window'], 'linhas_excluidas_do_debito': study['weekly']['excluded'],
    'debito_semanal_horas_teoricas': study['summary'], 'previsibilidade_semanal': quality,
    'disponibilidade_declarada_mtg2': {by_id[r]['name']: v for r, v in declared.items()},
    'sugestoes_validacao': suggestions,
    'carteira': {area: {'ocorrencias': len(d['facts']),
                        'maquina': dict(Counter(f['machine_basis'] or 'sem' for f in d['facts'])),
                        'horas': dict(Counter(f['load_basis'] or 'sem' for f in d['facts'])),
                        'horas_documentais': round(sum(f['load_hours'] for f in d['facts'] if f['load_basis'] == 'documental'), 1),
                        'horas_estimadas': round(sum(f['load_hours'] for f in d['facts'] if f['load_basis'] == 'estimada'), 1)}
                 for area, d in (('cantoneiras', data), ('perfis', perfis))},
    'atraso_14_dias': {u['label']: u['backlog']['balance'] for u in cap['units'].values()},
}
(OUT / 'resumo.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + '\n')
print(json.dumps({k: summary[k] for k in ('previsibilidade_semanal', 'sugestoes_validacao', 'carteira')}, ensure_ascii=False, indent=1))
