"""Read-only evidence of SKU families produced at MTG3; never sums sources."""
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / '.env')
from app import planning
from app.raw import sku_families

OUT = Path(__file__).resolve().parent / 'producao'
OUT.mkdir(exist_ok=True)
today = date.today()
with planning.connect(readonly=True) as c:
    c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
    c.execute("SET LOCAL statement_timeout='30s'")
    snapshot = planning.snapshot(c, 'cantoneiras')
    rules = sku_families.head(c, 'cantoneiras')
    mappings = {r['sku']: r for r in c.execute(
        "SELECT sku,family,status FROM planning_mtg.sku_family_mappings WHERE area='cantoneiras'").fetchall()}
    plan = c.execute('''SELECT source_line_id,component_ref,production_order_no,
        pavilion,quantity_made,metres_produced,cutting_machine
        FROM raw_mtg.plan_production_rows WHERE snapshot_id=%s''', (snapshot['snapshot_id'],)).fetchall()
    mes = c.execute('''SELECT p.id,p.model_ref,p.production_order,p.sheet_date,
        p.quantity,p.full_profile,p.machine,p.extra->'plan_identity'->>'component_ref' frozen_ref
        FROM mes_kanban.production_records p JOIN mes_kanban.validated_sheets v USING(sheet_uid)
        WHERE v.source_app='kanban-mes' ORDER BY p.id''').fetchall()
    ocr = c.execute('''SELECT s.current_version,s.confirmed_at,v.row_count
        FROM ocr_original.export_sources s JOIN ocr_original.export_versions v
        ON v.id=s.current_version''').fetchall()
    ocr_machines = c.execute('''SELECT DISTINCT r.payload->>'machine' machine
        FROM ocr_original.export_sources s JOIN ocr_original.export_rows r
        ON r.version_id=s.current_version''').fetchall()

supported = set(rules['config']['roots'])
by_mes = defaultdict(list)
by_excel = defaultdict(list)
excluded = Counter()
details = []
for row in mes:
    if not row['quantity'] or row['quantity'] <= 0:
        excluded['sem_quantidade_positiva'] += 1
        continue
    if not row['sheet_date'] or row['sheet_date'] > today:
        excluded['data_ausente_ou_futura'] += 1
        continue
    if row['full_profile']:
        excluded['perfil_completo_sem_atribuicao_individual_nesta_analise'] += 1
        continue
    mapping = mappings.get(row['model_ref'])
    if not mapping or not mapping['family']:
        excluded['referencia_sem_familia_mapeada_exatamente'] += 1
        continue
    frozen = mappings.get(row['frozen_ref'])
    if frozen and frozen['family'] != mapping['family']:
        excluded['familia_divergente_da_identidade_congelada'] += 1
        continue
    by_mes[mapping['family']].append(row)
    details.append({'fonte': 'MES validado', 'id': str(row['id']), 'familia': mapping['family'],
        'sku': row['model_ref'], 'of': row['production_order'], 'data_producao': row['sheet_date'],
        'maquina': row['machine'], 'setor': 'MTG3 (source_app=kanban-mes)'})

for row in plan:
    # Numeric/empty pavilions are left unresolved, not silently interpreted.
    if str(row['pavilion'] or '').strip().upper() != 'MTG3':
        continue
    if not ((row['quantity_made'] or 0) > 0 or (row['metres_produced'] or 0) > 0):
        continue
    mapping = mappings.get(row['component_ref'])
    if not mapping or not mapping['family']:
        continue
    by_excel[mapping['family']].append(row)
    details.append({'fonte': 'Acumulado Excel', 'id': row['source_line_id'],
        'familia': mapping['family'], 'sku': row['component_ref'], 'of': row['production_order_no'],
        'data_producao': None, 'maquina': row['cutting_machine'], 'setor': row['pavilion']})

rows = []
for family in sorted(by_mes.keys() | by_excel.keys()):
    m = by_mes[family]; x = by_excel[family]
    dates = [r['sheet_date'] for r in m]
    rows.append({'familia': family, 'familia_com_evidencia_de_classificacao': family in supported,
        'estado_classificacao': rules['config']['families'][family]['estado'],
        'evidencia_producao': 'MES validado + acumulado Excel' if m and x else 'MES validado' if m else 'Acumulado Excel',
        'mes_registos': len(m), 'mes_skus_distintos': len({r['model_ref'] for r in m}),
        'mes_primeira_data': min(dates) if dates else None, 'mes_ultima_data': max(dates) if dates else None,
        'mes_maquinas': ' | '.join(sorted({r['machine'] for r in m if r['machine']})),
        'excel_skus_distintos_com_acumulado': len({r['component_ref'] for r in x}),
        'excel_linhas_com_acumulado': len(x)})

def write(name, values):
    with (OUT / name).open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(values[0])); w.writeheader(); w.writerows(values)

primary = [r for r in rows if r['familia_com_evidencia_de_classificacao']]
write('familias-identificadas.csv', primary)
write('todos-agrupamentos-com-evidencia.csv', rows)
write('evidencias-por-fonte.csv', details)
assert len({r['familia'] for r in rows}) == len(rows)
assert len({(r['fonte'], r['id']) for r in details}) == len(details)
assert sum(r['mes_registos'] for r in rows) + sum(excluded.values()) == len(mes)
assert all(r['familia'] in supported for r in primary)
summary = {
    'gerado_em_utc': datetime.now(timezone.utc).isoformat(), 'snapshot_excel': snapshot,
    'versao_regras': rules['id'], 'leituras_base': 'dataresearchmtg, transacao repeatable read, read_only=true',
    'familias_identificadas': [r['familia'] for r in primary],
    'familias_com_mes': [r['familia'] for r in primary if r['mes_registos']],
    'familias_apenas_acumulado_excel': [r['familia'] for r in primary if not r['mes_registos']],
    'familias_do_catalogo_sem_evidencia_mtg3': sorted(supported - {r['familia'] for r in primary}),
    'agrupamentos_candidatos_com_mes': [r['familia'] for r in rows if r['mes_registos'] and not r['familia_com_evidencia_de_classificacao']],
    'mes_registos_lidos': len(mes), 'mes_registos_excluidos': dict(excluded),
    'mes_periodo_lido': {'inicio': min(r['sheet_date'] for r in mes if r['sheet_date']), 'fim': max(r['sheet_date'] for r in mes if r['sheet_date'])},
    'ocr_exportacao': ocr, 'ocr_maquinas_lidas': [r['machine'] for r in ocr_machines],
    'ocr_usado_para_atribuir_mtg3': False,
    'limites': [
        'MES: quantidade positiva, folha datada, aplicação MTG3 e correspondência exata entre referência registada e catálogo.',
        'Perfis completos, referências ausentes/não mapeadas e divergências ficam excluídos desta prova por SKU; não demonstram ausência de produção.',
        'Excel: Pav. explicitamente MTG3 e acumulado positivo. Evidência documental, sem confirmar evento ou data real de produção.',
        'Data Corte não foi utilizada como data real de produção.',
        'OCR HTTP sem identificação inequívoca MTG3 nas máquinas consultadas; não usado para atribuir produção ao setor.',
        'Cada SKU é distinto dentro de cada fonte. Fontes e operações não são somadas nem usadas para estimar volume fabricado.',
        'Presença de produção não transforma automaticamente um agrupamento candidato numa família confirmada.',
        'CA63: pavilhão 1. PA3: sem acumulado MTG3 explícito. Não se afirma que nunca foram produzidas na MTG3.'
    ]}
(OUT / 'resumo.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + '\n')
print(json.dumps({k: summary[k] for k in ('familias_identificadas','familias_com_mes',
    'familias_apenas_acumulado_excel','familias_do_catalogo_sem_evidencia_mtg3',
    'agrupamentos_candidatos_com_mes','mes_registos_lidos','mes_registos_excluidos')}, ensure_ascii=False, indent=2))
