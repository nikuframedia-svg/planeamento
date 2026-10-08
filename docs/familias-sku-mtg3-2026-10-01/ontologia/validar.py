"""Audit live family ontology in one read-only snapshot and export its catalogue."""
import csv
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE=Path(__file__).resolve().parent
BASE=Path('/home/luis/projects/kanban-mes-mtg2/docs/reestruturacao-dataresearchmtg-2026-09-30')
sys.path.insert(0,str(BASE))
from db import connect

report={'verificado_em_utc':datetime.now(timezone.utc).isoformat(),'verificacoes':[]}
def check(name,ok,**details):
    result={'nome':name,'ok':bool(ok),**details};report['verificacoes'].append(result)
    (HERE/'validacao.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n')
    print(json.dumps(result,ensure_ascii=False,default=str),flush=True)
    assert ok,name

def export(name,rows):
    with (HERE/name).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

with connect() as c:
    c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
    c.execute("SET LOCAL statement_timeout='90s'")
    c.execute("SET LOCAL enable_nestloop=off")
    c.execute("SET LOCAL jit=off")
    start=time.monotonic()
    maps=c.execute('SELECT * FROM consulta_v2.kg_familias_mapa ORDER BY area,sku').fetchall()
    catalog=c.execute('SELECT * FROM consulta_v2.kg_familias_catalogo ORDER BY area,familia').fetchall()
    check('catalogo_sem_duplicados',len(maps)==len({(r['area'],r['sku']) for r in maps})
          and len(catalog)==len({(r['area'],r['familia']) for r in catalog}),
          skus=len(maps),agrupamentos=len(catalog))
    mapped={(r['area'],r['sku']) for r in maps}
    sources=c.execute('''WITH d AS MATERIALIZED (SELECT conjunto,dados FROM consulta_v2.dados_aplicacao_atuais
        WHERE conjunto IN ('excel:cantoneiras','mes:production_records','mes:validated_sheets','application:records')),
        refs AS (
         SELECT dados->>'component_ref' sku FROM d WHERE conjunto='excel:cantoneiras'
         UNION SELECT dados->>'component_ref' FROM d WHERE conjunto='application:records' AND dados->>'area'='cantoneiras'
         UNION SELECT p.dados->>'model_ref' FROM d p JOIN d s ON s.conjunto='mes:validated_sheets'
          AND s.dados->>'source_app'='kanban-mes' AND s.dados->>'sheet_uid'=p.dados->>'sheet_uid'
          WHERE p.conjunto='mes:production_records'
         UNION SELECT p.dados->'extra'->'plan_identity'->>'component_ref' FROM d p JOIN d s ON s.conjunto='mes:validated_sheets'
          AND s.dados->>'source_app'='kanban-mes' AND s.dados->>'sheet_uid'=p.dados->>'sheet_uid'
          WHERE p.conjunto='mes:production_records')
        SELECT sku FROM refs WHERE nullif(btrim(sku),'') IS NOT NULL''').fetchall()
    missing=[r['sku'] for r in sources if ('cantoneiras',r['sku']) not in mapped]
    check('todas_referencias_excel_mes_manual_catalogadas',not missing,
          referencias_atuais=len(sources),referencias_em_falta=missing)
    heads={r['dados']['area']:r['dados']['rules_id'] for r in c.execute(
        "SELECT dados FROM consulta_v2.dados_aplicacao_atuais WHERE conjunto='application:sku_family_heads'")}
    check('mapeamentos_na_versao_atual',all(r['versao_regras']==heads.get(r['area']) for r in maps))
    supported=[r for r in catalog if r['estado_classificacao'].startswith('forte_') or r['estado_classificacao']=='confirmada_pelo_utilizador']
    baseline=list(csv.DictReader((HERE.parent/'sku-para-familia.csv').open(encoding='utf-8-sig')))
    by_sku={r['sku']:r for r in maps if r['area']=='cantoneiras'}
    confirmed=json.loads((HERE/'m2-confirmacao.json').read_text())
    explicit=set(confirmed['skus'])
    check('classificacoes_originais_preservadas',all(r['sku'] in by_sku and
          by_sku[r['sku']]['familia']==('M2' if r['sku'] in explicit else r['familia_candidata'] or None)
          for r in baseline),referencias_originais=len(baseline))
    report['pendencias']={'agrupamentos_por_confirmar':len(catalog)-len(supported),
        'referencias_sem_familia':sum(r['familia'] is None for r in maps),
        'familias_confirmadas_ou_inferidas_com_evidencia':len(supported)}
    check('m2_confirmacao_limitada_a_lista',explicit=={r['sku'] for r in maps
          if r['familia']=='M2' and r['estado']=='confirmada_pelo_utilizador'},skus_m2_confirmados=len(explicit))
    check('m1_preservada',all(by_sku[r['sku']]['familia']=='M1' for r in baseline if r['familia_candidata']=='M1'),
          skus_atuais=sum(r['familia']=='M1' for r in maps))
    check('m2011_separada',all(r['familia']!='M2' for r in maps if r['sku'].startswith('M2011')))
    sums=c.execute('SELECT * FROM consulta_v2.kg_familias_resumo ORDER BY area,familia').fetchall()
    m2=next(r for r in sums if r['familia']=='M2');report['m2']=m2
    evidence=c.execute('SELECT * FROM consulta_v2.kg_familias_evidencias').fetchall()
    check('perfis_completos_separados_da_producao_individual',
          all(not r['evidencia']['perfil_completo'] for r in evidence if r['tipo']=='registo_mes')
          and all(r['evidencia']['perfil_completo'] for r in evidence if r['tipo']=='associacao_indireta_mes')
          and m2['registos_mes']==sum(r['tipo']=='registo_mes' and r['familia']=='M2' for r in evidence))
    report['evidencias_por_fonte']=dict(Counter(r['tipo'] for r in evidence))
    coverage=c.execute('SELECT * FROM consulta_v2.kg_familias_cobertura').fetchall()
    report['cobertura_por_fonte']=[{'fonte':source,'estado':state,'linhas':n}
        for (source,state),n in sorted(Counter((r['conjunto'],r['estado_cobertura']) for r in coverage).items())]
    source_sizes={r['conjunto']:r['n'] for r in c.execute('''WITH d AS MATERIALIZED (
        SELECT conjunto,dados FROM consulta_v2.dados_aplicacao_atuais WHERE conjunto IN
        ('excel:cantoneiras','application:records','mes:production_records','mes:validated_sheets'))
        SELECT conjunto,count(*) n FROM d WHERE conjunto='excel:cantoneiras'
         OR (conjunto='application:records' AND dados->>'area'='cantoneiras') GROUP BY conjunto
        UNION ALL SELECT 'mes:production_records',count(*) FROM d p JOIN d s
         ON s.conjunto='mes:validated_sheets' AND s.dados->>'source_app'='kanban-mes'
         AND s.dados->>'sheet_uid'=p.dados->>'sheet_uid' WHERE p.conjunto='mes:production_records' ''')}
    check('cobertura_explica_todas_linhas',dict(Counter(r['conjunto'] for r in coverage))==source_sizes
          and len(coverage)==len({r['id'] for r in coverage})
          and not any(r['estado_cobertura'] in ('referencia_por_catalogar','por_investigar') for r in coverage),
          linhas_por_fonte=source_sizes)
    check('evidencias_sem_duplicados',len(evidence)==len({r['id'] for r in evidence}))
    check('evidencias_coerentes_com_cobertura',{r['id'] for r in evidence}==
          {r['id'] for r in coverage if r['estado_cobertura'].startswith('integrada')})
    export('cobertura-fontes.csv',coverage)
    nodes=set();dups=0;types=Counter()
    with c.cursor(name='sku_ontology_nodes') as cur:
        cur.execute('SELECT id,tipo FROM consulta_v2.kg_nos')
        while batch:=cur.fetchmany(10000):
            for r in batch:
                dups+=r['id'] in nodes;nodes.add(r['id']);types[r['tipo']]+=1
    check('nos_unicos_grafo_completo',dups==0 and None not in nodes,nos=len(nodes),tipos=dict(types))
    edges=set();missing=set();dups=0
    with c.cursor(name='sku_ontology_edges') as cur:
        cur.execute('SELECT id,origem,destino FROM consulta_v2.kg_familias_relacoes')
        while batch:=cur.fetchmany(10000):
            for r in batch:
                dups+=r['id'] in edges;edges.add(r['id'])
                missing.update(x for x in (r['origem'],r['destino']) if x not in nodes)
    check('relacoes_familias_unicas_e_sem_orfaos',dups==0 and not missing and None not in edges,
          relacoes=len(edges),referencias_ausentes=sorted(missing,key=str)[:10])
    expected_of={'kgf:evidencia_of:'+r['id'] for r in evidence if r['ordem_codigo']}
    check('todas_evidencias_com_of_ligadas',expected_of<=(edges),ligacoes_esperadas=len(expected_of))
    report['ofs_acrescentadas']=c.execute('SELECT * FROM consulta_v2.kg_familias_ordens ORDER BY codigo').fetchall()
    check('referencias_of_ambiguas_nao_promovidas',all(
          o['tipo_no']=='of' if o['codigo'].removeprefix('OF').isdigit()
          else o['tipo_no']=='referencia_of_por_confirmar' for o in report['ofs_acrescentadas']))
    heads=c.execute('SELECT * FROM consulta_v2.kg_familias_fontes ORDER BY conjunto').fetchall()
    report['fontes']=heads
    counts=c.execute('''SELECT (SELECT count(*) FROM consulta_v2.planeamento_atual WHERE area='cantoneiras') original,
        (SELECT count(*) FROM consulta_v2.planeamento_com_familias_sku WHERE area='cantoneiras') com_familia''').fetchone()
    check('planeamento_sem_multiplicacao',counts['original']==counts['com_familia'],**counts)
    history=c.execute("SELECT dados FROM consulta_v2.dados_aplicacao_atuais WHERE conjunto='application:sku_family_history'").fetchall()
    history_keys={(r['dados']['area'],r['dados']['sku'],r['dados']['revision']) for r in history}
    check('historico_completo_e_sem_repeticoes',len(history_keys)==len(history)
          and len(history)>=62826 and all((r['area'],r['sku'],revision) in history_keys
          for r in maps for revision in range(1,r['revisao']+1)),registos=len(history))
    export('catalogo-familias.csv',[{k:v for k,v in r.items() if k not in ('evidencia_classificacao','familia_no')} for r in sums])
    export('sku-familia.csv',[{k:r[k] for k in ('area','setor','sku','familia','estado','regra','versao_regras','revisao')} for r in maps])
    report['segundos']=round(time.monotonic()-start,3)
report['ok']=all(r['ok'] for r in report['verificacoes'])
(HERE/'validacao.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n')
print(json.dumps({'ok':report['ok'],'segundos':report['segundos']},ensure_ascii=False))
