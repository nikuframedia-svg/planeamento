"""Versioned SKU family classifications; original references remain identities."""
import argparse
from copy import deepcopy
import csv
import json
from pathlib import Path
import re

from psycopg.types.json import Jsonb

# The command-line entry point must load settings before importing planning.
if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv('.env')

from .. import planning, planning_needs as needs

LABELS = {
    'confirmada_pelo_utilizador': 'Família confirmada pelo utilizador',
    'forte_padrao_e_varias_of': 'Inferida — várias OF',
    'forte_padrao_e_uma_of': 'Inferida — uma OF',
    'candidata_por_confirmar': 'Por confirmar',
    'prefixo_demasiado_generico': 'Prefixo genérico — por confirmar',
    'codigo_de_projeto_por_confirmar': 'Possível projeto — por confirmar',
    'sem_familia': 'Sem família identificada',
}


def head(c, area):
    if not c.execute("SELECT to_regclass('planning_mtg.sku_family_heads') t").fetchone()['t']:
        return None
    return c.execute('''SELECT r.* FROM planning_mtg.sku_family_heads h
        JOIN planning_mtg.sku_family_rules r ON r.id=h.rules_id WHERE h.area=%s''',(area,)).fetchone()


def token(c, area):
    rule = head(c,area)
    return rule['id'] if rule else None


def classify(sku, config):
    override = config.get('sku_overrides', {}).get(str(sku or ''))
    if override:
        return {'family':override['family'],'status':'confirmada_pelo_utilizador',
                'rule':'sku_confirmado_pelo_utilizador'}
    normalized = str(sku or '').strip().upper()
    family = None; rule = 'sem_padrao'
    for root in sorted(config['roots'],key=lambda s:(len(s),s)):
        boundary = r'(?![0-9])' if root[-1].isdigit() else r'(?=[0-9-]|$)'
        if re.match('^'+re.escape(root)+boundary,normalized):
            family,rule = root,'familia_mae_corrobora_designacao';break
    if family is None and not re.search(r'\s',normalized):
        for pattern,method in (
            (r'^([A-Z]+\d+)[A-Z]+\d','letras_numero_letras_numero'),
            (r'^(\d+)[A-Z]+\d','codigo_numerico_candidato_a_projeto'),
            (r'^([A-Z]+)-?\d','prefixo_alfabetico')):
            match = re.match(pattern,normalized)
            if match:family,rule = match[1],method;break
    elif family is None and re.search(r'\s',normalized):
        rule = 'codigo_com_espacos'
    definition = config['families'].get(family) or {}
    state = definition.get('estado')
    if definition.get('ambito')=='lista_explicita_de_skus':
        state = 'candidata_por_confirmar'
    if not state:
        state = ('sem_familia' if family is None else 'codigo_de_projeto_por_confirmar' if family.isdigit()
                 else 'prefixo_demasiado_generico' if len(family)==1 else 'candidata_por_confirmar')
    return {'family':family,'status':state,'rule':rule}


def ensure(c, area, skus, *, source='automatic', evidence=None):
    """Idempotent current map and append-only history, in caller's transaction."""
    current = head(c,area)
    if not current:return {'mapped':0,'changed':0}
    refs = sorted({str(s) for s in skus if s is not None and str(s).strip()})
    if not refs:return {'mapped':0,'changed':0}
    c.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',('sku-family-map:'+area,))
    current = head(c,area)
    if not current:return {'mapped':0,'changed':0}
    existing = {r['sku']:r for r in c.execute('SELECT * FROM planning_mtg.sku_family_mappings WHERE area=%s AND sku=ANY(%s)',(area,refs)).fetchall()}
    changes=[]
    for sku in refs:
        old=existing.get(sku)
        if old and old['rules_id']==current['id']:continue
        mapped=classify(sku,current['config'])
        detail=dict((evidence or {}).get(sku) or (old or {}).get('evidence') or
                    {'source':source,'matched_rule':mapped['rule']})
        if sku in current['config'].get('sku_overrides',{}):
            detail['confirmation']=current['config']['sku_overrides'][sku]
        changes.append((area,sku,mapped['family'],mapped['status'],mapped['rule'],current['id'],
                        old['revision']+1 if old else 1,Jsonb(detail)))
    if changes:
        with c.cursor() as cursor:
            cursor.executemany('''INSERT INTO planning_mtg.sku_family_mappings
                (area,sku,family,status,rule,rules_id,revision,evidence) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(area,sku) DO UPDATE SET family=excluded.family,status=excluded.status,
                rule=excluded.rule,rules_id=excluded.rules_id,revision=excluded.revision,
                evidence=excluded.evidence,updated_at=now()''',changes)
            cursor.executemany('''INSERT INTO planning_mtg.sku_family_history
                (area,sku,family,status,rule,rules_id,revision,evidence) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)''',changes)
    return {'mapped':len(refs),'changed':len(changes),'rules_id':current['id']}


def annotate(c, area, rows):
    """Read-only projection; works in preview and preserves all row identities."""
    current=head(c,area)
    if not current:return
    cache={}
    for row in rows:
        sku=row['values'].get('component_ref')
        if sku not in cache:cache[sku]=classify(sku,current['config'])
        mapping=cache[sku]
        row['values'].update(sku_family=mapping['family'],sku_family_status=LABELS[mapping['status']])
        row['sku_family_mapping']={**mapping,'rules_id':current['id'],'sku':sku}


def source_references(c, area):
    """Keep literal references from every identified source, including MES-only codes."""
    snapshot=planning.snapshot(c,area)['snapshot_id']
    app={'cantoneiras':'kanban-mes','perfis':'kanban-mes-mtg2'}[area]
    return c.execute('''WITH refs AS (
        SELECT component_ref sku,'excel' source FROM raw_mtg.plan_production_rows WHERE snapshot_id=%s
        UNION ALL SELECT component_ref,'manual_registration' FROM planning_mtg.records WHERE area=%s
        UNION ALL SELECT p.model_ref,'mes_model_ref' FROM mes_kanban.production_records p
            JOIN mes_kanban.validated_sheets s USING(sheet_uid) WHERE s.source_app=%s
        UNION ALL SELECT p.extra->'plan_identity'->>'component_ref','mes_plan_identity'
            FROM mes_kanban.production_records p JOIN mes_kanban.validated_sheets s USING(sheet_uid)
            WHERE s.source_app=%s
        ) SELECT sku,array_agg(DISTINCT source ORDER BY source) sources FROM refs
          WHERE nullif(btrim(sku),'') IS NOT NULL GROUP BY sku''',(snapshot,area,app,app)).fetchall()


def refresh():
    """Register Excel, manual and MES references without merging literal identities."""
    with planning.connect() as c:
        if not c.execute("SELECT to_regclass('planning_mtg.sku_family_heads') t").fetchone()['t']:
            return {}
        result={}
        for area in planning.AREAS:
            if not head(c,area):continue
            refs=source_references(c,area)
            result[area]=ensure(c,area,[r['sku'] for r in refs],
                evidence={r['sku']:{'source':'source_catalogue','sources':r['sources']} for r in refs})
        return result


def load_analysis(path):
    path=Path(path)
    def read(name):
        with (path/name).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
    families=read('familias-candidatas.csv');mappings=read('sku-para-familia.csv')
    summary=json.loads((path/'resumo.json').read_text())
    roots=[r['familia'] for r in families if r['estado'].startswith('forte_') or r['estado']=='confirmada_pelo_utilizador']
    config={'contract':'sku-families-v1','roots':sorted(roots),
        'families':{r['familia']:r for r in families},
        'evidence':{'analysis_sha256':needs.digest([families,mappings,summary]),
                    'sources':summary['fontes_planeamento'],'cpis_versions':summary['versoes_cpis']}}
    if len(mappings)!=len({r['sku'] for r in mappings}):raise ValueError('duplicate_sku_in_analysis')
    if len(mappings)!=summary['skus_distintos']:raise ValueError('incomplete_analysis')
    for row in mappings:
        result=classify(row['sku'],config)
        if (result['family'] or '')!=row['familia_candidata']:
            raise ValueError('analysis_rule_disagreement:'+row['sku'])
    return config,mappings


def install(c, area, config, mappings):
    c.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',('sku-family-map:'+area,))
    # Rebuilding an analysis must not erase a later human confirmation or leave
    # automatically discovered/retired references on an obsolete rule version.
    current=head(c,area)
    config=deepcopy(config)
    config['roots']=sorted(set(config['roots']))
    if current:
        for family,definition in current['config']['families'].items():
            if (definition.get('estado')=='confirmada_pelo_utilizador'
                    and config['families'].get(family,{}).get('estado')!='confirmada_pelo_utilizador'):
                config['families'][family]=deepcopy(definition)
        config['sku_overrides']={**current['config'].get('sku_overrides',{}),**config.get('sku_overrides',{})}
        if not config['sku_overrides']:config.pop('sku_overrides')
        if config.get('sku_overrides'):config['contract']='sku-families-v2-explicit-membership'
        config['roots']=sorted(set(config['roots'])|{root for root in current['config']['roots']
            if current['config']['families'].get(root,{}).get('estado')=='confirmada_pelo_utilizador'})
    version=needs.digest([area,config])
    c.execute('INSERT INTO planning_mtg.sku_family_rules(id,area,config) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',(version,area,Jsonb(config)))
    c.execute('''INSERT INTO planning_mtg.sku_family_heads(area,rules_id) VALUES(%s,%s)
        ON CONFLICT(area) DO UPDATE SET rules_id=excluded.rules_id''',(area,version))
    refs={r['sku'] for r in mappings}
    refs.update(config.get('sku_overrides',{}))
    refs.update(r['sku'] for r in c.execute('SELECT sku FROM planning_mtg.sku_family_mappings WHERE area=%s',(area,)))
    result=ensure(c,area,refs,evidence={r['sku']:r for r in mappings})
    from .projection import signal
    if result['changed']:signal(c,'sku_families:'+area)
    return result


def with_confirmation(config, confirmation):
    """Explicit SKU membership never broadens a numeric prefix to other models."""
    family=confirmation['family'];refs=confirmation['skus']
    if not family or not refs or len(refs)!=len(set(refs)) or any(not s.strip() for s in refs):
        raise ValueError('invalid_family_confirmation')
    updated=deepcopy(config)
    updated['contract']='sku-families-v2-explicit-membership'
    evidence={k:v for k,v in confirmation.items() if k!='skus'}
    updated['families'][family]={'familia':family,'estado':'confirmada_pelo_utilizador',
        'ambito':'lista_explicita_de_skus','skus_confirmados':len(refs),'evidencia':evidence}
    for sku in refs:
        updated.setdefault('sku_overrides',{})[sku]={'family':family,'evidence':evidence}
    return updated


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--analysis',type=Path,required=True)
    parser.add_argument('--confirmation',type=Path)
    parser.add_argument('--area',choices=sorted(planning.AREAS),default='cantoneiras')
    args=parser.parse_args()
    config,mappings=load_analysis(args.analysis)
    if args.confirmation:
        confirmation=json.loads(args.confirmation.read_text())
        if set(confirmation['skus'])-set(r['sku'] for r in mappings):
            raise ValueError('confirmed_sku_missing_from_analysis')
        config=with_confirmation(config,confirmation)
    with planning.connect() as c:result=install(c,args.area,config,mappings)
    print(json.dumps(result))


if __name__=='__main__':main()
