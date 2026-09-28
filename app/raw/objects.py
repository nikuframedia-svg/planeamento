"""Revisioned shared views, formulas, presentation and machine configuration."""
from contextlib import nullcontext
import uuid
from psycopg.types.json import Jsonb
from .. import planning,planning_needs as needs,planning_registration as registration
from . import contracts,expressions,projection

KINDS={'view','formula','format','resource','calendar','rate','conversation','analysis','period','week_reference','worked_hours','gantt'}


def get(id,conn=None):
    with (planning.connect(readonly=True) if conn is None else nullcontext(conn)) as c:
        row=c.execute('SELECT * FROM planning_mtg.raw_objects WHERE id=%s',(needs.uid(id),)).fetchone()
        if not row:raise planning.PlanningError('Registo não encontrado.',404)
        return needs.serial(row)


def listing(kind,area=None):
    if kind not in KINDS:raise planning.PlanningError('Tipo de registo desconhecido.')
    with planning.connect(readonly=True) as c:
        result=needs.serial({'items':c.execute('SELECT * FROM planning_mtg.raw_objects WHERE kind=%s AND NOT archived AND (%s::text IS NULL OR area=%s OR area IS NULL) ORDER BY name',(kind,area,area)).fetchall()})
        if kind=='view':
            for row in result['items']:row['definition']=normalize_view(row['definition'],row['area'] or area or 'perfis')
        return result


def normalize_view(d,area):
    from .. import planning_population
    d=dict(d);known=contracts.mapping(area)
    d['population']=planning_population.scope(d.get('population'))
    if 'hidden' in d or 'hidden_groups' in d:
        hidden=d.pop('hidden',d.pop('hidden_groups',[]));d.setdefault('columns',[k for k,v in known.items() if v['group'] not in hidden])
    if isinstance(d.get('filters'),dict):
        legacy=d.pop('filters');d.update({k:v for k,v in legacy.items() if k not in d});d['filters']=[]
    if d.get('sort') and not d.get('order'):d['order']=[{'field':d['sort'],'direction':d.get('direction','asc')}]
    d.setdefault('columns',contracts.CANT_DEFAULT if area=='cantoneiras' else [k for k,v in known.items() if v['default_visible']])
    d.setdefault('filters',[])
    for key in ('machine','material_type'):
        if d.get(key):d['filters'].append({'field':key,'op':'in','values':[d.pop(key)]})
    if d.get('state') and d['state']!='all':
        state=d.pop('state');d['filters'].append({'field':'status','op':'in','values':['Em Aberto','Em Produção'] if state=='open' else [state]})
    d['columns']=list(dict.fromkeys(d['columns']))
    if any(k not in known and not k.startswith('calc_') for k in d['columns']):raise planning.PlanningError('A vista contém colunas desconhecidas.')
    d.setdefault('pinned',[k for k in ('of','ov','component_ref') if k in d['columns']])
    d.setdefault('column_order',list(dict.fromkeys(d['columns']+list(known))))
    d.setdefault('column_groups',{})
    for name in ('pinned','column_order'):
        if not isinstance(d[name],list) or any(not isinstance(k,str) or k not in known and not k.startswith('calc_') for k in d[name]):
            raise planning.PlanningError('Disposição de colunas inválida.')
        d[name]=list(dict.fromkeys(d[name]))
    if not isinstance(d['column_groups'],dict) or any(k not in known and not k.startswith('calc_') or v not in contracts.GROUPS for k,v in d['column_groups'].items()):
        raise planning.PlanningError('Grupo de apresentação inválido.')
    if d.get('page_size',100) not in (25,50,100,250,500):raise planning.PlanningError('Tamanho de página inválido.')
    if d.get('density','compact') not in ('compact','comfortable'):raise planning.PlanningError('Densidade inválida.')
    widths=d.get('widths',{})
    if any(not isinstance(v,(int,float)) or not 50<=v<=600 for v in widths.values()):raise planning.PlanningError('Largura de coluna inválida.')
    return d


def save(p,kind,conn=None):
    if kind not in KINDS:raise planning.PlanningError('Tipo desconhecido.')
    with (planning.connect() if conn is None else nullcontext(conn)) as c:
        _,actor,old=needs.command(c,p)
        if old:return old
        id=needs.uid(p.get('id') or p['request_id']);prior=c.execute('SELECT * FROM planning_mtg.raw_objects WHERE id=%s FOR UPDATE',(id,)).fetchone()
        if prior and (prior['kind']!=kind or p.get('expected_revision')!=prior['revision']):raise planning.PlanningError('O registo mudou. Reabre-o antes de guardar.',409)
        if not prior and p.get('expected_revision',0)!=0:raise planning.PlanningError('O registo já não existe.',409)
        area=p.get('area') or (prior['area'] if prior else 'perfis');planning.check_area(area)
        name=str(p.get('name') or '').strip();d=dict(p.get('definition') or {})
        if not name or len(name)>160:raise planning.PlanningError('Indica um nome até 160 caracteres.')
        if kind=='view':
            d=normalize_view(d,area)
            from .query import field_expressions,predicates
            vf,ve=field_expressions(c,area)
            predicates(d,vf,ve)
            if any(x.get('field') not in vf or x.get('direction') not in ('asc','desc') for x in d.get('order',[])):raise planning.PlanningError('Ordenação de vista inválida.')
        if kind in ('formula','format'):
            from .query import field_expressions
            fields,compiled=field_expressions(c,area)
            key='calc_'+str(id).replace('-','')
            fields[key]={'id':key,'label':name,'data_type':'number','unit':None}
            ast=d.get('ast') or expressions.parse(str(d.get('expression') or ''),fields)
            graph={}
            for row in c.execute("SELECT id,definition FROM planning_mtg.raw_objects WHERE kind='formula' AND NOT archived").fetchall():graph['calc_'+str(row['id']).replace('-','')]=row['definition'].get('ast',{})
            graph[key]=ast
            def dependencies(node):
                return {node['field']} if 'field' in node else set().union(*(dependencies(x) for x in node.get('args',[]))) if node.get('args') else set()
            def visit(k,path):
                if k in path:raise planning.PlanningError('Dependência circular entre colunas.')
                for other in dependencies(graph.get(k,{})):
                    if other in graph:visit(other,path|{k})
            visit(key,set())
            def resolve(k):
                if k==key:raise planning.PlanningError('A fórmula não pode depender de si própria.')
                return compiled[k]
            expr=expressions.compile_ast(ast,fields,resolve)
            if kind=='format' and expr.kind!='boolean':raise planning.PlanningError('A formatação exige uma condição lógica.')
            if kind=='formula' and expr.aggregate:raise planning.PlanningError('Uma coluna calcula cada linha; usa uma análise para agregações.')
            if not p.get('confirmed'):raise planning.PlanningError('Confirma a fórmula com Guardar e ativar.')
            requested=d.get('unit') or expr.unit
            if requested!=expr.unit and expressions.DIM.get(requested,requested)!=expressions.DIM.get(expr.unit,expr.unit):raise planning.PlanningError('A unidade apresentada não corresponde à dimensão da fórmula.')
            d.update(ast=ast,data_type=expr.kind,unit=requested)
            if kind=='format' and d.get('style') not in ('warning','success','danger','accent'):raise planning.PlanningError('Estilo de formatação inválido.')
        if kind in ('resource','calendar','rate'):
            from .capacity import validate
            d=validate(c,kind,id,d)
        if kind=='gantt':
            from ..gantt.service import validate_definition
            d=validate_definition(d)
        if kind=='worked_hours':
            from .worked_hours import validate
            d=prior['definition'] if prior and p.get('archived') else validate(c,id,d)
        if kind=='period':
            from .capacity_revision import validate_period
            d=validate_period(c,area,id,d)
        revision=prior['revision']+1 if prior else 1;archived=bool(p.get('archived',False))
        c.execute('''INSERT INTO planning_mtg.raw_objects(id,kind,name,area,revision,definition,archived,actor) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(id) DO UPDATE SET name=excluded.name,area=excluded.area,revision=excluded.revision,definition=excluded.definition,archived=excluded.archived,actor=excluded.actor,updated_at=now()''',(id,kind,name,area,revision,Jsonb(d),archived,actor))
        c.execute('INSERT INTO planning_mtg.raw_object_versions(object_id,revision,definition,name,archived,actor) VALUES(%s,%s,%s,%s,%s,%s)',(id,revision,Jsonb(d),name,archived,actor))
        projection.signal(c,kind)
        if kind in ('resource','calendar','rate','period','worked_hours'):projection.mark_aggregates_pending(c,p['request_id'])
        return needs.finish(c,p,{'id':str(id),'revision':revision,'definition':d})


def history(id):
    with planning.connect(readonly=True) as c:return needs.serial({'versions':c.execute('SELECT * FROM planning_mtg.raw_object_versions WHERE object_id=%s ORDER BY revision DESC',(needs.uid(id),)).fetchall()})


def preview_formula(p):
    """Compute a proposal against the entire filter before the user activates it."""
    from . import query
    with planning.connect(readonly=True) as c:
        area=planning.check_area(p.get('area','perfis'));fields,compiled=query.field_expressions(c,area)
        expression=str(p.get('expression') or '');ast=expressions.parse(expression,fields)
        e=expressions.compile_ast(ast,fields,compiled.__getitem__)
        unit=p.get('unit') or e.unit
        if expressions.DIM.get(unit,unit)!=expressions.DIM.get(e.unit,e.unit):raise planning.PlanningError('Unidade incompatível com a fórmula.')
        gen=query.generation(c,area,p.get('version'));base,args=query.source(gen);where,params=query.predicates(p,fields,compiled);base+=' AND '+where;args+=params
        count=c.execute('SELECT count(*) total,count('+e.sql+') known'+base,e.args+args).fetchone()
        examples=c.execute("SELECT c.values_json->>'of' of,c.values_json->>'component_ref' reference,"+e.sql+' value'+base+' ORDER BY m.row_key LIMIT 20',e.args+args).fetchall()
        return needs.serial({'ast':ast,'data_type':e.kind,'unit':unit,'coverage':count,'examples':examples,'sources':gen['metadata'],'version':str(gen['id']),'unknowns':'Entradas desconhecidas e divisão por zero permanecem desconhecidas.'})
