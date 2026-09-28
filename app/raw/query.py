"""Typed filters, facets and stable navigation executed in PostgreSQL."""
from __future__ import annotations
import re
from datetime import datetime,timedelta,timezone
from psycopg import sql
from .. import planning,planning_needs as needs
from . import contracts,expressions
from .. import planning_population as population


def generation(conn,area='perfis',version=None,dataset='planning'):
    planning.check_area(area);name=dataset+':'+area
    if version:
        try:id=int(version)
        except (TypeError,ValueError):raise planning.PlanningError('Esta versão expirou. Atualiza a lista.',409)
        gen=conn.execute('SELECT * FROM planning_mtg.raw_generations WHERE id=%s AND dataset=%s',(id,name)).fetchone()
        if not gen or gen['created_at']<datetime.now(timezone.utc)-timedelta(days=7):raise planning.PlanningError('Esta versão expirou. Guarda as alterações e atualiza a lista.',409)
    else:gen=conn.execute('SELECT * FROM planning_mtg.raw_generations WHERE dataset=%s ORDER BY id DESC LIMIT 1',(name,)).fetchone()
    if not gen:raise planning.PlanningError('A preparar a consulta desta área. Tenta novamente dentro de alguns segundos.',503)
    return gen


def field_expressions(conn,area,dataset='planning',formula_ids=None):
    fields=contracts.mapping(area,dataset);definitions={}
    if dataset=='planning':
        for r in conn.execute("SELECT id,name,definition FROM planning_mtg.raw_objects WHERE kind='formula' AND area=%s AND NOT archived",(area,)).fetchall():
            k='calc_'+str(r['id']).replace('-','')
            if formula_ids is not None and str(r['id']) not in formula_ids:continue
            definitions[k]=r['definition'];fields[k]={'formula_ast':r['definition']['ast'],'id':k,'label':r['name'],'data_type':r['definition']['data_type'],'unit':r['definition'].get('unit'),'group':'calculated','editable':False,'type':'readonly'}
    cache={};visiting=set()
    def resolve(k):
        if k in cache:return cache[k]
        if k in visiting:raise planning.PlanningError('A fórmula contém uma dependência circular.')
        visiting.add(k)
        if k in definitions:expr=expressions.compile_ast(definitions[k]['ast'],fields,resolve)
        else:expr=expressions.compile_ast({'field':k},fields)
        cache[k]=expr;visiting.remove(k);return expr
    for key in fields:resolve(key)
    return fields,cache


def predicates(p,fields,exprs,skip_field=None):
    clauses=[];args=[]
    selected_scope=population.scope(p.get('population'))
    if 'planning_active' in fields and selected_scope!='all':
        clauses.append('('+population.active_sql()+') = '+('true' if selected_scope=='active' else 'false'))
    q=str(p.get('q') or '').strip()
    if len(q)>4000:raise planning.PlanningError('Pesquisa demasiado longa.')
    terms=[t.strip().casefold() for t in re.split('[,;\n]+',q) if t.strip()]
    if terms:
        clauses.append('('+' OR '.join('c.search_text LIKE %s' for _ in terms)+')');args.extend('%'+t.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%' for t in terms)
    filters=list(p.get('filters') or [])
    if not isinstance(p.get('filters',[]),list) or len(filters)>60:raise planning.PlanningError('Filtros inválidos.')
    for name in ('machine','material_type','origin'):
        if p.get(name):
            if name=='origin':clauses.append("c.detail->>'origin'=%s");args.append(p[name])
            else:filters.append({'field':name,'op':'in','values':[p[name]]})
    if p.get('state') and p['state']!='all':filters.append({'field':'status','op':'in','values':['Em Aberto','Em Produção'] if p['state']=='open' else [p['state']]})
    if p.get('pending'):clauses.append("(jsonb_array_length(coalesce(c.detail->'warnings','[]'))>0 OR c.values_json->>'machine' IS NULL OR c.values_json->>'remaining' IS NULL)")
    selected=p.get('selected')
    if selected is not None:
        if not isinstance(selected,list) or len(selected)>100000:raise planning.PlanningError('Seleção inválida.')
        clauses.append("(m.row_key=ANY(%s) OR coalesce(c.detail->'selection_aliases','[]') ?| %s)");args.extend([selected,selected])
    if p.get('planning_keys') is not None:
        keys=p['planning_keys']
        clauses.append("coalesce(c.detail->'planning_keys','[]') ?| %s");args.append(keys)
    for f in filters:
        key=f.get('field');op=f.get('op')
        if key==skip_field:continue
        if key not in fields:raise planning.PlanningError('Coluna de filtro desconhecida.')
        e=exprs[key];values=f.get('values',[])
        if op in ('empty','known'):
            clauses.append('('+e.sql+') IS '+('NOT ' if op=='known' else '')+'NULL');args.extend(e.args);continue
        if op=='in':
            if not isinstance(values,list) or len(values)>1000:raise planning.PlanningError('Seleção de filtro inválida.')
            clauses.append('('+e.sql+')::text=ANY(%s)');args.extend(e.args);args.append([str(x).lower() if isinstance(x,bool) else str(x) for x in values]);continue
        if op in ('contains','starts'):
            if e.kind not in ('text','boolean'):raise planning.PlanningError('Filtro de texto incompatível.')
            text=str(f.get('value') or '').replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
            clauses.append('('+e.sql+') ILIKE %s');args.extend(e.args);args.append(('%' if op=='contains' else '')+text+'%');continue
        if op in ('eq','ne','gt','gte','lt','lte','between'):
            vals=[f.get('min'),f.get('max')] if op=='between' else [f.get('value')]
            if any(v in (None,'') for v in vals):raise planning.PlanningError('Completa os limites do filtro.')
            if e.kind=='number':
                from ..planning_raw import number
                vals=[number(x) for x in vals]
                if None in vals:raise planning.PlanningError('Filtro numérico inválido.')
            if e.kind=='date':
                from datetime import date
                try:vals=[date.fromisoformat(str(x)) for x in vals]
                except ValueError:raise planning.PlanningError('Data de filtro inválida.')
            symbol={'eq':'=','ne':'<>','gt':'>','gte':'>=','lt':'<','lte':'<='}.get(op)
            clauses.append('('+e.sql+') '+('BETWEEN %s AND %s' if op=='between' else symbol+' %s'));args.extend(e.args);args.extend(vals);continue
        raise planning.PlanningError('Operador de filtro desconhecido.')
    return (' AND '.join(clauses) or 'true'),args


def source(gen,*,capacity_inputs=False):
    table='raw_capacity_contents' if capacity_inputs else 'raw_resolved_contents'
    return ' FROM planning_mtg.raw_members m JOIN planning_mtg.'+table+' c ON c.hash=m.content_hash WHERE m.dataset=%s AND m.first_generation<=%s AND (m.last_generation IS NULL OR m.last_generation>%s)',[gen['dataset'],gen['id'],gen['id']]


def listing(p,conn=None):
    from contextlib import nullcontext
    area=planning.check_area(p.get('area','perfis'));dataset=p.get('dataset','planning')
    if dataset not in ('planning','production','production_hours','orders','capacity','capacity_items','capacity_machines','original'):raise planning.PlanningError('Conjunto de dados inválido.')
    try:page=max(1,int(p.get('page',1)));size=int(p.get('page_size',100))
    except (TypeError,ValueError):raise planning.PlanningError('Paginação inválida.')
    if size not in (25,50,100,250,500):raise planning.PlanningError('Escolhe 25, 50, 100, 250 ou 500 linhas.')
    with (planning.connect(readonly=True) if conn is None else nullcontext(conn)) as c:
        # These short interactive queries are frequently repeated. Compiling
        # their JSON predicates costs more than executing them on this volume.
        c.execute('SET LOCAL jit=off')
        gen=generation(c,area,p.get('version'),dataset);fields,exprs=field_expressions(c,area,dataset)
        where,args=predicates(p,fields,exprs);base,params=source(gen);base+=' AND '+where;params+=args
        total=c.execute('SELECT count(*) n'+base,params).fetchone()['n']
        order=p.get('order') or [{'field':p.get('sort','of' if 'of' in fields else 'machine'),'direction':p.get('direction','asc')}]
        if not isinstance(order,list) or len(order)>8:raise planning.PlanningError('Ordenação inválida.')
        sorts=[];sortargs=[]
        for o in order:
            if o.get('field') not in fields or o.get('direction','asc') not in ('asc','desc'):raise planning.PlanningError('Ordenação inválida.')
            e=exprs[o['field']];sorts.append('('+e.sql+') '+o.get('direction','asc')+' NULLS LAST');sortargs+=e.args
        calculated=[k for k in fields if k.startswith('calc_')];selectargs=[];select=''
        for k in calculated:
            e=exprs[k];select+=', '+e.sql+' AS "'+k+'"';selectargs+=e.args
        formats=c.execute("SELECT id,definition FROM planning_mtg.raw_objects WHERE kind='format' AND area=%s AND NOT archived",(area,)).fetchall() if dataset=='planning' else []
        for rule in formats:
            e=expressions.compile_ast(rule['definition']['ast'],fields,exprs.__getitem__)
            select+=', '+e.sql+' AS "fmt_'+str(rule['id']).replace('-','')+'"';selectargs+=e.args
        rows=c.execute('SELECT m.row_key,c.values_json,c.detail'+select+base+' ORDER BY '+','.join(sorts+['m.row_key'])+' LIMIT %s OFFSET %s',selectargs+params+sortargs+[size,(page-1)*size]).fetchall()
        output=[]
        for r in rows:output.append({**r['detail'],'key':r['row_key'],'values':{**r['values_json'],**{k:r[k] for k in calculated}},'formats':[{'id':str(f['id']),'style':f['definition']['style']} for f in formats if r['fmt_'+str(f['id']).replace('-','')] is True]})
        return needs.serial({**gen['metadata'],'version':str(gen['id']),'rows':output,'total':total,'page':page,'page_size':size,'created_at':gen['created_at'],'columns':list(fields.values()),'population':population.scope(p.get('population'))})


def options(p):
    area=planning.check_area(p.get('area','perfis'));key=p.get('field')
    with planning.connect(readonly=True) as c:
        gen=generation(c,area,p.get('version'));fields,exprs=field_expressions(c,area)
        if key not in fields:raise planning.PlanningError('Coluna desconhecida.')
        where,args=predicates(p,fields,exprs,skip_field=key);base,params=source(gen);e=exprs[key]
        search=str(p.get('search') or '')
        outer='SELECT * FROM (SELECT '+e.sql+' value,count(*) n'+base+' AND '+where+' GROUP BY 1) choices'
        params=e.args+params+args
        if search:outer+=' WHERE value::text ILIKE %s';params.append('%'+search+'%')
        count=c.execute('SELECT count(*) n FROM ('+outer+') opts',params).fetchone()['n']
        page=max(int(p.get('page',1)),1)
        rows=c.execute(outer+' ORDER BY value NULLS FIRST LIMIT 100 OFFSET %s',params+[(page-1)*100]).fetchall()
        return needs.serial({'options':rows,'total':count,'page':page,'version':str(gen['id'])})
