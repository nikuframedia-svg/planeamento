"""Candidatas a famílias de SKU da MTG2 Perfis. Só leitura: não altera classificações nem fontes.

Mesmo contrato de evidência da MTG3 (docs/familias-sku-mtg3-2026-10-01/analisar.py), sem copiar
as famílias da MTG3: as raízes só são aceites quando o próprio planeamento MTG2 as corrobora
(10 ou mais SKUs e o código citado nas designações das OF). Nenhuma família MTG2 é confirmada
pelo utilizador nesta análise; todas ficam inferidas ou candidatas.

Uso (raiz do projeto): .venv/bin/python docs/familias-sku-mtg2-2026-10-01/analisar.py
"""
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / '.env')
from app import planning
from app.raw import query

OUT = Path(__file__).resolve().parent
COMMON_WORDS = {'AS','OS','DA','DE','DO','DAS','DOS','EM','NA','NO','NAS','NOS','UM','UN'}


def candidate(ref):
    normalized = ref.strip().upper()
    if re.search(r'\s', normalized):
        return None, 'codigo_com_espacos'
    if m := re.match(r'^([A-Z]+\d+)[A-Z]+\d', normalized):
        return m[1], 'letras_numero_letras_numero'
    if m := re.match(r'^(\d+)[A-Z]+\d', normalized):
        return m[1], 'codigo_numerico_candidato_a_projeto'
    if m := re.match(r'^([A-Z]+)-?\d', normalized):
        return m[1], 'prefixo_alfabetico'
    return None, 'sem_padrao'


def mentioned(family, designation):
    continuation = r'(?!\d)' if family[-1].isdigit() else r'(?![A-Z])'
    return bool(re.search(r'(?<![A-Z0-9])' + re.escape(family) + continuation, designation.upper()))


with planning.connect(readonly=True) as c:
    c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
    g = query.generation(c, 'perfis')
    base, args = query.source(g)
    # The whole current snapshot, including closed/historical orders, as for MTG3.
    rows = c.execute("""SELECT m.row_key chave,c.values_json->>'component_ref' ref,c.values_json->>'of' of,
        c.values_json->>'designation' designation,c.values_json->>'planning_active' active,
        c.values_json->>'profile' profile,c.values_json->>'machine' machine,
        c.values_json->>'material_type' material""" + base + " AND nullif(trim(c.values_json->>'component_ref'),'') IS NOT NULL", args).fetchall()
    cpis = c.execute("""SELECT DISTINCT ON (production_order_no) production_order_no,work_type_code,work_type_description
        FROM raw_mtg.cpis_rows WHERE snapshot_id=%s ORDER BY production_order_no""",
                     ((g['metadata'].get('snapshot') or {}).get('snapshot_id'),)).fetchall()
    head = {'conjunto': 'planning:perfis', 'geracao': g['id'], 'publicada_em': str(g['created_at']),
            'snapshot': g['metadata'].get('snapshot')}
cpis = {r['production_order_no']: r for r in cpis}

by_family = defaultdict(list); by_sku = defaultdict(list)
for row in rows:
    by_sku[row['ref']].append(row)
    family, rule = candidate(row['ref'])
    row.update(family=family, rule=rule)
    if family:
        by_family[family].append(row)
roots = set()
for family, records in by_family.items():
    if (len(family) > 1 and not family.isdigit() and family not in COMMON_WORDS
            and len({r['ref'] for r in records}) >= 10
            and any(mentioned(family, r['designation'] or '') for r in records)):
        roots.add(family)


def assign(ref):
    normalized = ref.strip().upper()
    for family in sorted(roots, key=lambda s: (len(s), s)):
        ending = r'(?![0-9])' if family[-1].isdigit() else r'(?=[0-9-]|$)'
        if re.match('^' + re.escape(family) + ending, normalized):
            return family, 'familia_mae_corrobora_designacao'
    return candidate(ref)


by_family = defaultdict(list)
for row in rows:
    family, rule = assign(row['ref'])
    row.update(family=family, rule=rule)
    if family:
        by_family[family].append(row)

families = []
for family, records in by_family.items():
    refs = sorted({r['ref'] for r in records}); ofs = {r['of'] for r in records if r['of']}
    supporting = [r for r in records if mentioned(family, r['designation'] or '')]
    supporting_ofs = {r['of'] for r in supporting if r['of']}
    active_refs = {r['ref'] for r in records if r['active'] == 'true'}
    if family.isdigit():
        confidence = 'codigo_de_projeto_por_confirmar'
    elif len(family) == 1:
        confidence = 'prefixo_demasiado_generico'
    elif family not in COMMON_WORDS and len(refs) >= 10 and len(supporting_ofs) >= 2:
        confidence = 'forte_padrao_e_varias_of'
    elif family not in COMMON_WORDS and len(refs) >= 10 and supporting_ofs:
        confidence = 'forte_padrao_e_uma_of'
    else:
        confidence = 'candidata_por_confirmar'
    labels = list(dict.fromkeys((r['designation'] or '').replace('\n', ' ') for r in supporting))[:3]
    families.append({'familia': family, 'estado': confidence, 'skus_distintos': len(refs), 'linhas': len(records),
        'ofs': len(ofs), 'skus_em_linhas_ativas': len(active_refs),
        'ofs_com_familia_na_designacao': len(supporting_ofs),
        'tipos_material': ' | '.join(sorted({r['material'] or 'Sem tipo' for r in records}))[:200],
        'familias_encomenda_cpis': ' | '.join(sorted({str((cpis.get(r['of']) or {}).get('work_type_code') or '-') for r in records}))[:200],
        'exemplos_sku': ' | '.join(refs[:3]), 'evidencia_designacoes': ' | '.join(labels),
        'regra': records[0]['rule']})
families.sort(key=lambda f: (-f['skus_distintos'], f['familia']))


def save(name, records, fields):
    with (OUT / name).open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader(); writer.writerows(records)


save('familias-candidatas.csv', families, list(families[0]))
strong = [r for r in families if r['estado'].startswith('forte_')]
save('familias-com-evidencia.csv', strong or [{k: '' for k in families[0]}], list(families[0]))
mapping = []
for ref, records in sorted(by_sku.items()):
    family, rule = assign(ref)
    mapping.append({'sku': ref, 'familia_candidata': family or '', 'regra': rule, 'linhas': len(records),
        'ofs': len({r['of'] for r in records if r['of']}),
        'designacao_exemplo': next((r['designation'] for r in records if r['designation']), ''),
        'perfil_exemplo': next((r['profile'] for r in records if r['profile']), ''),
        'tipo_material': next((r['material'] for r in records if r['material']), '')})
save('sku-para-familia.csv', mapping, list(mapping[0]))
summary = {'gerado_em_utc': datetime.now(timezone.utc).isoformat(), 'setor': 'MTG2',
    'escopo': 'Fotografia atual completa do planeamento MTG2 na aplicação: inclui OF históricas e fechadas.',
    'fontes_planeamento': [head], 'versoes_cpis': [{'origem': 'CPIS importado do Excel (raw_mtg.cpis_rows)',
                                                    'snapshot': (head['snapshot'] or {}).get('snapshot_id')}],
    'linhas': len(rows), 'skus_distintos': len(by_sku), 'familias_candidatas': len(families),
    'familias_com_evidencia': len(strong), 'estados': dict(Counter(r['estado'] for r in families)),
    'skus_sem_padrao': sum(not assign(ref)[0] for ref in by_sku),
    'raizes_corroboradas': sorted(roots),
    'classificacoes_na_base_alteradas': False,
    'limites': ['Nenhuma família MTG2 confirmada pelo utilizador; as famílias da MTG3 não foram copiadas.',
      'Designações corroboram agrupamentos; não estabelecem intercambiabilidade das peças.',
      'Não une variantes, não elimina SKUs e não soma quantidades.',
      'Códigos numéricos (modelo/projeto) e prefixos de uma letra exigem confirmação do planeador.',
      'Grupos de perfis (tipo de material + perfil) continuam disponíveis como dimensão independente.']}
(OUT / 'resumo.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
print(json.dumps({k: summary[k] for k in ('linhas', 'skus_distintos', 'familias_candidatas', 'familias_com_evidencia', 'estados', 'skus_sem_padrao', 'raizes_corroboradas')}, ensure_ascii=False))
print(json.dumps([{k: r[k] for k in ('familia', 'estado', 'skus_distintos', 'ofs', 'skus_em_linhas_ativas', 'ofs_com_familia_na_designacao', 'exemplos_sku')} for r in families[:15]], ensure_ascii=False, indent=1))
