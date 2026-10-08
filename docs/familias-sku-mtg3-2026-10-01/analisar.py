"""Read-only family candidates. Does not modify classifications or source data."""
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

OUT = Path(__file__).resolve().parent
BASE = Path('/home/luis/projects/kanban-mes-mtg2/docs/reestruturacao-dataresearchmtg-2026-09-30')
backup = json.loads((BASE / 'backup-status.json').read_text())
access = json.loads((Path(backup['backup_directory']) / 'copy-access.json').read_text())


def candidate(ref):
    # Preserve source spelling. Prefix extraction is evidence, not a confirmed taxonomy.
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
    # H92HA corroborates H92; M10 never corroborates M1; DLTN never corroborates DLT.
    continuation = r'(?!\d)' if family[-1].isdigit() else r'(?![A-Z])'
    return bool(re.search(r'(?<![A-Z0-9])' + re.escape(family) + continuation, designation.upper()))


with psycopg.connect(**access, row_factory=dict_row, options='-c default_transaction_read_only=on -c statement_timeout=45000') as c:
    c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
    heads = c.execute("SELECT DISTINCT 'planning:cantoneiras' conjunto,versao,confirmada_em,metadata FROM consulta_v2.planeamento_atual WHERE area='cantoneiras'").fetchall()
    cpis_versions = c.execute('SELECT * FROM origem_v2.versoes_cpis').fetchall()
    rows = c.execute("""SELECT p.chave,p.valores->>'component_ref' ref,p.valores->>'of' of,
           p.valores->>'designation' designation,p.valores->>'planning_active' active,
           p.valores->>'profile' profile,p.valores->>'machine' machine,
           a.codart,a.desart,a.codfam,a.codgamope
        FROM consulta_v2.planeamento_atual p
        LEFT JOIN importacao_mac_20260930.cpis_artigos a ON a.codart=p.valores->>'component_ref'
        WHERE p.area='cantoneiras' AND nullif(trim(p.valores->>'component_ref'),'') IS NOT NULL""").fetchall()

by_family = defaultdict(list); by_sku = defaultdict(list)
for row in rows:
    by_sku[row['ref']].append(row)
    family, rule = candidate(row['ref'])
    row.update(family=family, rule=rule)
    if family:by_family[family].append(row)

# Supported parent families absorb piece suffixes that resemble another model.
# For example CWA01D3913 stays in CWA, while DLTN never falls into DLT.
common_words = {'AS','OS','DA','DE','DO','DAS','DOS','EM','NA','NO','NAS','NOS','UM','UN'}
roots = {'M1'}
for family, records in by_family.items():
    if (len(family)>1 and not family.isdigit() and family not in common_words
        and len({r['ref'] for r in records})>=10
        and any(mentioned(family,r['designation'] or '') for r in records)):
        roots.add(family)


def assign(ref):
    normalized=ref.strip().upper()
    for family in sorted(roots,key=lambda s:(len(s),s)):
        ending=r'(?![0-9])' if family[-1].isdigit() else r'(?=[0-9-]|$)'
        if re.match('^'+re.escape(family)+ending,normalized):
            return family,'familia_mae_corrobora_designacao'
    return candidate(ref)


by_family=defaultdict(list)
for row in rows:
    family,rule=assign(row['ref'])
    row.update(family=family,rule=rule)
    if family:by_family[family].append(row)

families=[]
for family, records in by_family.items():
    refs=sorted({r['ref'] for r in records}); ofs={r['of'] for r in records if r['of']}
    supporting=[r for r in records if mentioned(family,r['designation'] or '')]
    supporting_ofs={r['of'] for r in supporting if r['of']}
    cpis_refs={r['ref'] for r in records if r['codart']}
    active_refs={r['ref'] for r in records if r['active']=='true'}
    if family=='M1':confidence='confirmada_pelo_utilizador'
    elif family.isdigit():confidence='codigo_de_projeto_por_confirmar'
    elif len(family)==1:confidence='prefixo_demasiado_generico'
    elif family not in common_words and len(refs)>=10 and len(supporting_ofs)>=2:confidence='forte_padrao_e_varias_of'
    elif family not in common_words and len(refs)>=10 and supporting_ofs:confidence='forte_padrao_e_uma_of'
    else:confidence='candidata_por_confirmar'
    # Example labels are original evidence; do not invent the meaning of code suffixes.
    labels=list(dict.fromkeys((r['designation'] or '').replace('_x000D_',' ').replace('\n',' ') for r in supporting))[:3]
    examples=refs[:3]
    families.append({'familia':family,'estado':confidence,'skus_distintos':len(refs),'linhas':len(records),
        'ofs':len(ofs),'skus_em_linhas_ativas':len(active_refs),'skus_encontrados_cpis':len(cpis_refs),
        'ofs_com_familia_na_designacao':len(supporting_ofs),
        'codfam_cpis':' | '.join(sorted({str(r['codfam']) for r in records if r['codfam'] is not None})),
        'exemplos_sku':' | '.join(examples),'evidencia_designacoes':' | '.join(labels),
        'regra':records[0]['rule']})
families.sort(key=lambda f:(-f['skus_distintos'],f['familia']))


def save(name,records,fields):
    with (OUT/name).open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(records)

save('familias-candidatas.csv',families,list(families[0]))
strong=[r for r in families if r['estado'].startswith('forte_') or r['estado']=='confirmada_pelo_utilizador']
save('familias-com-evidencia.csv',strong,list(families[0]))
mapping=[]
for ref,records in sorted(by_sku.items()):
    family,rule=assign(ref)
    mapping.append({'sku':ref,'familia_candidata':family or '', 'regra':rule,'linhas':len(records),
        'ofs':len({r['of'] for r in records if r['of']}),
        'designacao_exemplo':next((r['designation'] for r in records if r['designation']),''),
        'descricao_cpis':next((r['desart'] for r in records if r['desart']),''),
        'codfam_cpis':next((r['codfam'] for r in records if r['codfam']),'')})
save('sku-para-familia.csv',mapping,list(mapping[0]))
summary={'gerado_em_utc':datetime.now(timezone.utc).isoformat(),'setor':'MTG3',
    'escopo':'Fotografia atual completa do planeamento: inclui OF históricas e fechadas; não apenas trabalho pendente.',
    'fontes_planeamento':heads,'versoes_cpis':cpis_versions,
    'linhas':len(rows),'skus_distintos':len(by_sku),'familias_candidatas':len(families),
    'familias_com_evidencia':len(strong),'estados':dict(Counter(r['estado'] for r in families)),
    'skus_sem_padrao':sum(not assign(ref)[0] for ref in by_sku),
    'classificacoes_na_base_alteradas':False,
    'regra_anterior_reutilizada':'docs/analise-planeamento-2026-09-25/pedido-2026-09-28/referencias/scripts/modelo_da_referencia.py',
    'limites':['Classificação candidata, exceto M1 confirmada pelo utilizador.',
      'Designações corroboram agrupamentos; não estabelecem intercambiabilidade das peças nem significado de sufixos.',
      'Não une variantes, não elimina SKUs e não soma quantidades de fontes diferentes.',
      'Códigos numéricos e prefixos de uma letra requerem análise adicional.',
      'Famílias-mãe corroboradas têm prioridade sobre sufixos de peças; nos restantes casos a regra pode subdividir um modelo e exige revisão.']}
(OUT/'resumo.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str))
print(json.dumps({k:summary[k] for k in ('linhas','skus_distintos','familias_candidatas','familias_com_evidencia','estados','skus_sem_padrao')},ensure_ascii=False))
print(json.dumps([{k:r[k] for k in ('familia','estado','skus_distintos','ofs','skus_em_linhas_ativas','ofs_com_familia_na_designacao','exemplos_sku')} for r in strong[:32]],ensure_ascii=False,indent=2))
