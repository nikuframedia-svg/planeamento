"""Coherent CPIS planning tables, read-only at source and atomically versioned.

The scope consists of chosen orders with published planning information. Raw
machine codes, units and counters stay documentary evidence, not MES events.
"""
from collections import defaultdict
from datetime import datetime, timezone
import os

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from .. import planning, planning_needs as needs

PROVIDER='cpis-planning-tables'
KEYS={'cpis_artigos':('codart',),'cpis_operacoes':('codope',),'cpis_gamasoperatorias':('codgamope',),
    'cpis_gamasoperatoriaslin':('codgamope','posicao'),'cpis_ordensfabrico':('id',),
    'cpis_ordensfabricolin':('id',),'cpis_ordensfabricolinexp':('id',),'cpis_ordensfabricolinope':('id',),
    'cpis_ordensfabricolin_pecas':('id',),'cpis_planeamentoprod':('id',)}


def read(c,orders, references, *, schema='dados'):
    """Ten set queries in the same repeatable-read transaction, without N+1."""
    def fetch(table,where='',args=()):
        return c.execute(sql.SQL('SELECT * FROM {}.{} '+where+' ORDER BY '+','.join(KEYS[table])).format(sql.Identifier(schema),sql.Identifier(table)),args).fetchall()
    tables={}
    tables['cpis_ordensfabrico']=fetch('cpis_ordensfabrico',"WHERE regexp_replace(upper(trim(ficof)), '^OF[ ._-]*', '')=ANY(%s)",([of.removeprefix('OF') for of in orders],))
    ids=[r['id'] for r in tables['cpis_ordensfabrico']]
    tables['cpis_ordensfabricolin']=fetch('cpis_ordensfabricolin','WHERE idpai=ANY(%s)',(ids,))
    line_ids=[r['id'] for r in tables['cpis_ordensfabricolin']]
    tables['cpis_ordensfabricolinexp']=fetch('cpis_ordensfabricolinexp','WHERE idpai=ANY(%s)',(line_ids,))
    exp_ids=[r['id'] for r in tables['cpis_ordensfabricolinexp']]
    tables['cpis_ordensfabricolinope']=fetch('cpis_ordensfabricolinope','WHERE idpai=ANY(%s)',(exp_ids,))
    tables['cpis_ordensfabricolin_pecas']=fetch('cpis_ordensfabricolin_pecas','WHERE idof=ANY(%s)',(ids,))
    refs=sorted(set(references)|{r['codart'] for r in tables['cpis_ordensfabricolinexp'] if r.get('codart')})
    tables['cpis_artigos']=fetch('cpis_artigos','WHERE codart=ANY(%s)',(refs,))
    gamas=sorted({r['codgamope'] for r in tables['cpis_artigos']+tables['cpis_ordensfabricolinexp'] if r.get('codgamope')})
    tables['cpis_gamasoperatorias']=fetch('cpis_gamasoperatorias','WHERE codgamope=ANY(%s)',(gamas,))
    tables['cpis_gamasoperatoriaslin']=fetch('cpis_gamasoperatoriaslin','WHERE codgamope=ANY(%s)',(gamas,))
    operations=sorted({r['codope'] for r in tables['cpis_gamasoperatoriaslin']+tables['cpis_ordensfabricolinope'] if r.get('codope')})
    tables['cpis_operacoes']=fetch('cpis_operacoes','WHERE codope=ANY(%s)',(operations,))
    tables['cpis_planeamentoprod']=fetch('cpis_planeamentoprod',"WHERE regexp_replace(upper(trim(ficof)), '^OF[ ._-]*', '')=ANY(%s)",([of.removeprefix('OF') for of in orders],))
    validate(tables)
    return needs.serial({'orders':sorted(orders),'references':refs,'tables':tables,'schema':schema})


def validate(tables):
    for table,fields in KEYS.items():
        seen=set()
        for r in tables[table]:
            key=tuple(r.get(k) for k in fields)
            if None in key or key in seen:
                raise planning.PlanningError('Chave CPIS ausente ou duplicada: '+table,422)
            seen.add(key)
    for child,parent,parent_column in [('cpis_ordensfabricolin','cpis_ordensfabrico','idpai'),
        ('cpis_ordensfabricolinexp','cpis_ordensfabricolin','idpai'),('cpis_ordensfabricolinope','cpis_ordensfabricolinexp','idpai')]:
        ids={r['id'] for r in tables[parent]}
        if any(r[parent_column] not in ids for r in tables[child]):
            raise planning.PlanningError('Conjunto CPIS incoerente: '+child,422)


def publish(c,package):
    digest=needs.digest(package)
    c.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',(PROVIDER,))
    prior=c.execute('SELECT version_id FROM planning_mtg.gantt_source_heads WHERE provider=%s',(PROVIDER,)).fetchone()
    c.execute('INSERT INTO planning_mtg.gantt_source_versions(id,provider,sources,metadata) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING',
        (digest,PROVIDER,Jsonb({'schema':package['schema']}),Jsonb({k:v for k,v in package.items() if k!='tables'})))
    for table,rows in package['tables'].items():
        with c.cursor() as cursor:
            cursor.executemany('INSERT INTO planning_mtg.gantt_source_rows(version_id,key,payload) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',
                [(digest,table+':'+needs.digest([r[k] for k in KEYS[table]]),Jsonb({'table':table,'row':r})) for r in rows])
    c.execute('INSERT INTO planning_mtg.gantt_source_heads(provider,version_id,checked_at,last_error) VALUES(%s,%s,now(),NULL) ON CONFLICT(provider) DO UPDATE SET version_id=excluded.version_id,checked_at=excluded.checked_at,last_error=NULL',(PROVIDER,digest))
    if not prior or prior['version_id']!=digest:
        from ..raw import projection
        projection.signal(c,PROVIDER)
    return {'version':digest,'tables':{t:len(r) for t,r in package['tables'].items()}}


def refresh():
    from ..sector import scope
    dsn=os.getenv('MES_PLANNING_CPIS_DSN')
    if not dsn:
        return None
    try:
        with planning.connect(readonly=True) as target:
            selected=scope.read(target);selected={} if selected is None else selected;records,_=scope.planning_lines(target,selected,planning.AREAS)
            orders={r['values_json']['of'] for r in records};refs={r['values_json']['component_ref'] for r in records if r['values_json'].get('component_ref')}
        with psycopg.connect(dsn,row_factory=dict_row,connect_timeout=10) as source:
            source.read_only=True
            source.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            source.execute("SET LOCAL statement_timeout='120s'")
            package=read(source,orders,refs,schema=os.getenv('MES_PLANNING_CPIS_SCHEMA','dados'))
        with planning.connect() as target:
            return publish(target,package)
    except Exception as exc:
        with planning.connect() as target:
            target.execute('INSERT INTO planning_mtg.gantt_source_heads(provider,last_error) VALUES(%s,%s) ON CONFLICT(provider) DO UPDATE SET last_error=excluded.last_error',(PROVIDER,'Origem CPIS indisponível ou conjunto incoerente; versão anterior conservada.'))
        raise planning.PlanningError('Atualização das tabelas CPIS falhou; versão anterior conservada.',503) from exc


def load(c):
    head=c.execute('SELECT * FROM planning_mtg.gantt_source_heads WHERE provider=%s',(PROVIDER,)).fetchone()
    if not head or not head['version_id']:
        return None
    rows=c.execute('SELECT payload FROM planning_mtg.gantt_source_rows WHERE version_id=%s ORDER BY key',(head['version_id'],)).fetchall()
    tables=defaultdict(list)
    for r in rows:
        tables[r['payload']['table']].append(r['payload']['row'])
    return {'head':needs.serial(head),'tables':dict(tables)}


def evidence(package,rows):
    """Documentary changes are review items, not automatic geometry/route edits."""
    if not package:
        return {}
    from ..dossiers.models import order_number
    t=package['tables'];of_by_id={r['id']:order_number(r['ficof']) for r in t.get('cpis_ordensfabrico',[])}
    line_of={r['id']:of_by_id.get(r['idpai']) for r in t.get('cpis_ordensfabricolin',[])}
    articles={r['codart']:r for r in t.get('cpis_artigos',[])};components=defaultdict(list);routes=defaultdict(list)
    for r in t.get('cpis_ordensfabricolinope',[]):routes[r['idpai']].append(r)
    for r in t.get('cpis_ordensfabricolinexp',[]):components[(line_of.get(r['idpai']),r['codart'])].append(r)
    result={}
    for row in rows:
        found=components.get((row['ordem_codigo'],row['referencia_original']),[])
        matches=[]
        for r in found:
            unit=articles.get(r['codart'],{}).get('coduniper')
            length=r.get('qtdper') if unit=='MM' else r.get('qtdper')*1000 if unit=='M' and r.get('qtdper') is not None else None
            if length==row.get('comprimento_mm') and r.get('qtd')==row.get('quantidade_base'):
                matches.append(r)
        if len(matches)==1:
            component=matches[0];route=sorted(routes[component['id']],key=lambda r:(r['posicao'],r['id']))
            result[row['operacao_id']]={'component':component,'route':route,'article':articles.get(component['codart']),
                'version':package['head']['version_id'],'status':'correspondencia_documental_unica',
                'limitation':'Unidades dos tempos e correspondência das máquinas continuam por validar.'}
        else:
            result[row['operacao_id']]={'version':package['head']['version_id'],'status':'sem_correspondencia_unica','candidates':len(found)}
    return result
