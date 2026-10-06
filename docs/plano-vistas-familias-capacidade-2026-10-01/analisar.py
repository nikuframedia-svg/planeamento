"""Read-only planning inventory. Writes evidence files only, never application data."""
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
import csv
import json
import math
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT/'.env')
from app import planning, planning_population
from app.raw import query

HERE=Path(__file__).resolve().parent
TODAY=date(2026,10,1)


def number(v):
    try:
        n=float(v)
        return n if math.isfinite(n) else None
    except (ValueError,TypeError):return None


def day(v):
    try:return date.fromisoformat(str(v)[:10])
    except (ValueError,TypeError):return None


def count(rows):
    backlog=[v for v in rows if number(v.get('planning_remaining')) is not None and number(v['planning_remaining'])>0]
    hours=[number(v.get('theoretical_hours')) for v in backlog]
    dated=[day(v.get('cut_date')) for v in backlog]
    return {
        'linhas_ativas':len(rows), 'ofs_ativas':len({v['of'] for v in rows}),
        'referencias_ativas':len({v['component_ref'] for v in rows}),
        'linhas_com_saldo_principal_positivo':len(backlog),
        'linhas_com_saldo_principal_desconhecido':sum(number(v.get('planning_remaining')) is None for v in rows),
        'linhas_com_saldo_principal_zero':sum(number(v.get('planning_remaining'))==0 for v in rows),
        'horas_principais_documentais_conhecidas':round(sum(h for h in hours if h is not None and h>=0),4),
        'linhas_positivas_com_horas':sum(h is not None and h>=0 for h in hours),
        'linhas_positivas_sem_horas':sum(h is None or h<0 for h in hours),
        'linhas_positivas_com_corte_passado':sum(d is not None and d<TODAY for d in dated),
        'linhas_positivas_sem_data_corte':sum(d is None for d in dated),
        'linhas_positivas_com_corte_ate_14_dias':sum(d is not None and 0<=(d-TODAY).days<=14 for d in dated),
        'linhas_positivas_sem_maquina':sum(not str(v.get('machine') or '').strip() for v in backlog),
        'linhas_positivas_com_saldo_provisorio':sum(bool(v.get('planning_balance_provisional')) for v in backlog),
        'linhas_positivas_com_picking':sum(bool(v.get('picking_deadline')) for v in backlog),
        'linhas_positivas_com_ano_picking':sum(bool(v.get('picking_year')) for v in backlog),
        'fontes_taxa_nas_linhas_com_horas':dict(Counter(v.get('rate_source') or 'sem_origem' for v in backlog if number(v.get('theoretical_hours')) is not None)),
        'pavilhoes_nas_linhas_positivas':dict(Counter(str(v.get('pavilion') or 'sem_pavilhao') for v in backlog)),
    }


def export(name,rows):
    if not rows:return
    with (HERE/name).open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)


report={'consultado_em_utc':datetime.now(timezone.utc).isoformat(),'data_corte_analise':str(TODAY),
        'escopo':'Linhas ativas da RAW por area documental; saldos/horas principais, nao carga integral nem producao fisica exclusiva da unidade.',
        'areas':{},'casos_m1_m2':{},'limitacoes':['Horas documentais conhecidas nao medem capacidade disponivel.',
          'Familia SKU, familia CPIS e perfil sao dimensoes distintas.',
          'Linhas principais nao incluem necessariamente todas as operacoes seguintes.',
          'Possiveis duplicados nao sao somados entre areas para afirmar trabalho fisico total.']}
families=[];profiles=[];machines=[]
with planning.connect(readonly=True) as c:
    c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
    c.execute("SET LOCAL statement_timeout='60s'")
    maps={(r['area'],r['sku']):r for r in c.execute('SELECT area,sku,family,status,rules_id FROM planning_mtg.sku_family_mappings')}
    report['catalogo']={'referencias':len(maps),'por_area':dict(Counter(k[0] for k in maps)),
        'agrupamentos':len({(r['area'],r['family']) for r in maps.values() if r['family']}),
        'sem_familia':sum(r['family'] is None for r in maps.values()),
        'versoes':sorted({r['rules_id'] for r in maps.values()})}
    columns=['of','component_ref','profile','material_type','machine','pavilion','cut_date',
        'picking_deadline','picking_year','planning_remaining','planning_balance_provisional',
        'theoretical_hours','rate_source','quantity_required','length_mm']
    projection=','.join("'%s',c.values_json->'%s'"%(f,f) for f in columns)
    for area in planning.AREAS:
        g=query.generation(c,area);base,args=query.source(g)
        records=c.execute('SELECT m.row_key,jsonb_build_object('+projection+') v'+base+' AND '+planning_population.active_sql(),args).fetchall()
        rows=[r['v'] for r in records]
        report['areas'][area]={'geracao':g['id'],'fontes':g['metadata'].get('snapshot'),**count(rows)}
        by_family=defaultdict(list);by_profile=defaultdict(list);by_machine=defaultdict(list)
        for v in rows:
            mapping=maps.get((area,v['component_ref']),{})
            by_family[(mapping.get('family') or 'Sem familia SKU',mapping.get('status') or 'sem_catalogo')].append(v)
            by_profile[(v.get('material_type') or 'Sem tipo',v.get('profile') or 'Sem perfil')].append(v)
            by_machine[v.get('machine') or 'Sem maquina'].append(v)
        for (family,status),group in sorted(by_family.items()):
            stats=count(group)
            families.append({'area':area,'familia_sku':family,'estado':status,**{k:v for k,v in stats.items() if not isinstance(v,dict)}})
        for (kind,profile),group in sorted(by_profile.items()):
            stats=count(group)
            profiles.append({'area':area,'tipo_material':kind,'perfil':profile,**{k:v for k,v in stats.items() if not isinstance(v,dict)}})
        for machine,group in sorted(by_machine.items()):
            stats=count(group)
            machines.append({'area':area,'maquina_indicada':machine,**{k:v for k,v in stats.items() if not isinstance(v,dict)}})
        if area=='cantoneiras':
            cases=c.execute("SELECT c.values_json->>'sku_family' family,c.values_json->>'machine' machine,"
                "c.values_json->>'cut_date' cut_date,c.values_json->>'status' status,"
                "c.values_json->>'closure_reason' closure_reason,"+planning_population.active_sql()+" active"+base+
                " AND c.values_json->>'sku_family' IN ('M1','M2')",args).fetchall()
            for family in ('M1','M2'):
                vals=[r for r in cases if r['family']==family]
                dates=sorted(r['cut_date'] for r in vals if r['cut_date'])
                report['casos_m1_m2'][family]={'linhas_todas':len(vals),'linhas_ativas':sum(r['active'] for r in vals),
                    'maquinas_documentais':dict(Counter(r['machine'] or 'Sem maquina' for r in vals)),
                    'estados_documentais':dict(Counter(r['status'] or 'Sem estado' for r in vals)),
                    'motivos_fecho':dict(Counter(r['closure_reason'] or 'sem_fecho' for r in vals)),
                    'menor_data_corte':dates[0] if dates else None,'maior_data_corte':dates[-1] if dates else None}
    configs=c.execute('SELECT kind,definition FROM planning_mtg.raw_objects WHERE NOT archived').fetchall()
    report['configuracao']={
        'objetos_por_tipo':dict(Counter(o['kind'] for o in configs)),
        'confirmados_por_tipo':dict(Counter(o['kind'] for o in configs if o['definition'].get('confirmed'))),
        'selecoes_para_planear':c.execute("SELECT count(*) n FROM planning_mtg.sector_selection WHERE decision='selected'").fetchone()['n'],
        'cenarios_com_plano_aceite':sum(o['kind']=='gantt' and bool(o['definition'].get('accepted')) for o in configs)}
    source=c.execute('SELECT v.*,h.checked_at,h.last_error FROM planning_mtg.gantt_source_heads h JOIN planning_mtg.gantt_source_versions v ON v.id=h.version_id WHERE h.provider=%s',('research-v2',)).fetchone()
    meta=source['metadata']
    report['fonte_documental_gantt']={k:source[k] for k in ['id','created_at','checked_at','last_error','sources']}
    report['fonte_documental_gantt'].update(
        contagens={k:len(v) for k,v in meta.items() if isinstance(v,(list,dict))},
        recursos_por_tipo=dict(Counter(r['tipo'] for r in meta['resources'])),
        disponibilidades_por_estado=dict(Counter(r.get('estado') or 'sem_estado' for r in meta['availability'])),
        amostra_disponibilidades=meta['availability'][:3],taxas=meta['rates'],
        relacoes_recursos=meta['relations'])
    report['fonte_documental_gantt']['operacoes_por_setor_fase']=c.execute('''SELECT payload->>'setor' setor,payload->>'fase' fase,
        count(*) ocorrencias,count(DISTINCT payload->>'item_id') itens,
        count(*) FILTER(WHERE payload->>'saldo_confirmado' IS NOT NULL) com_saldo_reconciliado
        FROM planning_mtg.gantt_source_rows WHERE version_id=%s GROUP BY 1,2 ORDER BY 1,2''',(source['id'],)).fetchall()

export('familias.csv',families);export('perfis.csv',profiles);export('maquinas.csv',machines)
(HERE/'diagnostico.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n')
print(json.dumps({k:report[k] for k in ['catalogo','areas','configuracao']},ensure_ascii=False,indent=2,default=str))
