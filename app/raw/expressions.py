"""Small typed expression language. Compiles a validated AST; never evaluates code."""
from __future__ import annotations
from dataclasses import dataclass
import re
from ..planning import PlanningError

@dataclass
class Expr:
    sql: str
    args: list
    kind: str='number'
    unit: str|None=None
    aggregate: bool=False

DIM={'mm':'length','m':'length','mm²':'area','m²':'area','kg':'mass','h':'time','min':'time','un.':'count','%':'ratio','°':'angle','m/h':'speed'}
OPS={'+','-','*','/','>','<','>=','<=','=','!=','and','or'}
FUNCTIONS={'if','round','floor','ceil','min','max','abs','concat','lower','upper','length','year','week','date','days','coalesce','sum','count','count_distinct','average','minimum','maximum'}
TOKEN=re.compile(r'\s*(\[[^\]]+\]|\d+(?:\.\d+)?|"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|>=|<=|!=|[+*/=<>(),;\-]|[A-Za-z_][A-Za-z_0-9]*)')


def parse(text,fields):
    """Human labels resolve once to permanent IDs. Semicolons delimit arguments."""
    aliases={f['label'].casefold():k for k,f in fields.items()};aliases.update({k.casefold():k for k in fields})
    if text.strip().casefold() in aliases:return {'field':aliases[text.strip().casefold()]}
    tokens=[];pos=0
    while pos<len(text.rstrip()):
        m=TOKEN.match(text,pos)
        if not m:raise PlanningError('Fórmula inválida junto de '+text[pos:pos+20]+'.')
        tokens.append(m[1]);pos=m.end()
    index=0
    def expression(level=0):
        nonlocal index
        if index>=len(tokens):raise PlanningError('Fórmula incompleta.')
        t=tokens[index];index+=1
        if t=='-':left={'op':'-','args':[{'literal':0},expression(6)]}
        elif t=='(':
            left=expression()
            if index>=len(tokens) or tokens[index]!=')':raise PlanningError('Falta fechar parêntesis.')
            index+=1
        elif t.startswith('['):
            key=aliases.get(t[1:-1].casefold())
            if key is None:raise PlanningError('Campo inexistente: '+t)
            left={'field':key}
        elif t[0] in ('"',"'"):left={'literal':t[1:-1].replace('\\'+t[0],t[0])}
        elif re.fullmatch(r'\d+(\.\d+)?',t):left={'literal':float(t)}
        elif t.lower() in ('true','false','null'):left={'literal':{'true':True,'false':False,'null':None}[t.lower()]}
        elif t.lower() in FUNCTIONS:
            if index>=len(tokens) or tokens[index]!='(':raise PlanningError('Falta abrir os argumentos da função.')
            index+=1;args=[]
            if index<len(tokens) and tokens[index]!=')':
                while True:
                    args.append(expression())
                    if index<len(tokens) and tokens[index] in (',',';'):index+=1;continue
                    break
            if index>=len(tokens) or tokens[index]!=')':raise PlanningError('Falta fechar os argumentos.')
            index+=1;left={'op':t.lower(),'args':args}
        else:raise PlanningError('Usa um campo entre [ ] ou uma função permitida.')
        precedence={'or':1,'and':2,'=':3,'!=':3,'>':3,'<':3,'>=':3,'<=':3,'+':4,'-':4,'*':5,'/':5}
        while index<len(tokens) and precedence.get(tokens[index].lower(),0)>level:
            op=tokens[index].lower();p=precedence[op];index+=1;left={'op':op,'args':[left,expression(p)]}
        return left
    if len(tokens)>500:raise PlanningError('Fórmula demasiado extensa.')
    ast=expression()
    if index!=len(tokens):raise PlanningError('Elementos inesperados no fim da fórmula.')
    return ast


def same(a,b):
    return a.kind==b.kind and (a.unit==b.unit or (not a.unit and not b.unit))


def compile_ast(node,fields,resolve=None,depth=0,allow_aggregate=False):
    if depth>30 or not isinstance(node,dict):raise PlanningError('Expressão inválida ou demasiado profunda.')
    if set(node)=={'field'}:
        key=node['field']
        if key not in fields:raise PlanningError('Campo inexistente: '+str(key))
        if resolve:return resolve(key)
        f=fields[key];kind=f['data_type'];unit=f.get('unit')
        # Identifiers come solely from the server contract, never from expression text.
        if not re.fullmatch('[a-zA-Z_][a-zA-Z_0-9]*',key):raise PlanningError('Identificador de campo inválido.')
        value="c.values_json->>'"+key+"'"
        sql=f"NULLIF({value},'')"
        if kind=='number':sql=f'({sql})::numeric'
        elif kind=='date':sql=f'({sql})::date'
        elif kind=='boolean':sql=f"CASE WHEN {value} IN ('true','X') THEN true WHEN {value} IN ('false','-') THEN false ELSE NULL END"
        return Expr(sql,[],kind,unit)
    if set(node)=={'literal'}:
        v=node['literal']
        if v is None:return Expr('NULL',[],'null')
        if type(v) not in (str,int,float,bool):raise PlanningError('Constante inválida.')
        if isinstance(v,str) and len(v)>4000:raise PlanningError('Texto demasiado longo.')
        kind='boolean' if type(v) is bool else 'number' if type(v) in (int,float) else 'text'
        return Expr('%s::numeric' if kind=='number' else '%s',[v],kind)
    if set(node)!={'op','args'} or node['op'] not in OPS|FUNCTIONS or not isinstance(node['args'],list):raise PlanningError('Operação não permitida.')
    if node['op']=='round' and len(node['args'])==1:node={**node,'args':node['args']+[{'literal':0}]}
    op=node['op'];args=[compile_ast(x,fields,resolve,depth+1,allow_aggregate) for x in node['args']]
    expected={'if':3,'round':2,'floor':1,'ceil':1,'abs':1,'lower':1,'upper':1,'length':1,'year':1,'week':1,'date':1,'days':2,'sum':1,'count':1,'count_distinct':1,'average':1,'minimum':1,'maximum':1}
    if op in OPS and len(args)!=2 or op in expected and len(args)!=expected[op] or not args:raise PlanningError('Número de argumentos inválido em '+op+'.')
    params=[x for a in args for x in a.args];s=[a.sql for a in args];kind=args[0].kind;unit=args[0].unit;agg=any(a.aggregate for a in args)
    aggregates={'sum':'sum','count':'count','count_distinct':'count','average':'avg','minimum':'min','maximum':'max'}
    if op in aggregates:
        if not allow_aggregate or agg:raise PlanningError('Agregação não permitida neste contexto.')
        if op in ('sum','average') and kind!='number':raise PlanningError('A agregação exige números.')
        return Expr(aggregates[op]+'('+('DISTINCT ' if op=='count_distinct' else '')+s[0]+')',params,'number' if op.startswith('count') else kind,'registos' if op.startswith('count') else unit,True)
    if op in ('+','-','*','/'):
        if any(a.kind not in ('number','null') for a in args):raise PlanningError('A operação aritmética exige números.')
        if op in ('+','-') and args[0].unit!=args[1].unit:raise PlanningError('Unidades incompatíveis. Converte os valores antes de somar ou subtrair.')
        if op=='*':
            units=[a.unit for a in args if a.unit and a.unit!='un.']
            unit='·'.join(units) if units else ('un.' if any(a.unit for a in args) else None)
            unit={'mm·mm':'mm²','m·m':'m²'}.get(unit,unit)
        if op=='/':unit=None if args[0].unit==args[1].unit else args[0].unit if not args[1].unit else (args[0].unit or '1')+'/'+args[1].unit
        return Expr('('+s[0]+op+('NULLIF('+s[1]+',0)' if op=='/' else s[1])+')',params,'number',unit,agg)
    if op in ('>','<','>=','<=','=','!='):
        if not same(*args) and not (args[0].kind==args[1].kind=='number' and (not args[0].unit or not args[1].unit)) and all(a.kind!='null' for a in args):raise PlanningError('Comparação entre tipos ou unidades incompatíveis.')
        return Expr('('+s[0]+op+s[1]+')',params,'boolean',None,agg)
    if op in ('and','or'):
        if any(a.kind!='boolean' for a in args):raise PlanningError('A condição exige valores lógicos.')
        return Expr('('+(' '+op.upper()+' ').join(s)+')',params,'boolean',None,agg)
    if op=='if':
        zero_branch=any(n.get('literal')==0 and a.kind=='number' for n,a in zip(node['args'][1:],args[1:])) and args[1].kind==args[2].kind=='number'
        if args[0].kind!='boolean' or not same(args[1],args[2]) and not zero_branch and all(a.kind!='null' for a in args[1:]):raise PlanningError('Condição ou resultados incompatíveis.')
        return Expr('CASE WHEN ('+s[0]+') IS NULL THEN NULL WHEN '+s[0]+' THEN '+s[1]+' ELSE '+s[2]+' END',args[0].args+params,args[1].kind if args[1].kind!='null' else args[2].kind,args[1].unit or args[2].unit,agg)
    if op=='coalesce':
        if any(not same(args[0],a) and a.kind!='null' for a in args[1:]):raise PlanningError('Valores alternativos incompatíveis.')
        return Expr('coalesce('+','.join(s)+')',params,kind,unit,agg)
    if op in ('min','max','round','floor','ceil','abs'):
        if any(a.kind!='number' for a in args):raise PlanningError('A função exige números.')
        if op in ('min','max') and any(not same(args[0],a) for a in args):raise PlanningError('Unidades incompatíveis.')
        fn={'min':'least','max':'greatest'}.get(op,op)
        # PostgreSQL least/greatest ignore NULL; our contract propagates unknowns.
        if op in ('min','max'):
            return Expr('CASE WHEN '+' OR '.join(x+' IS NULL' for x in s)+' THEN NULL ELSE '+fn+'('+','.join(s)+') END',params+params,kind,unit,agg)
        if op=='round':s[1]='('+s[1]+')::integer'
        return Expr(fn+'('+','.join(s)+')',params,kind,unit,agg)
    if op in ('concat','lower','upper','length'):
        if any(a.kind!='text' for a in args):raise PlanningError('A função exige texto.')
        sql='('+'||'.join(s)+')' if op=='concat' else op+'('+s[0]+')'
        return Expr(sql,params,'number' if op=='length' else 'text',None,agg)
    if op=='date':
        if kind!='text':raise PlanningError('A data exige texto ISO (aaaa-mm-dd).')
        literal=node['args'][0].get('literal')
        if not isinstance(literal,str):raise PlanningError('Usa um campo de data ou uma data ISO literal.')
        from datetime import date
        try:date.fromisoformat(literal)
        except ValueError:raise PlanningError('Data ISO inválida.')
        return Expr('('+s[0]+')::date',params,'date',None,agg)
    if op in ('year','week'):
        if kind!='date':raise PlanningError('A função exige uma data.')
        return Expr('extract('+('isoyear' if op=='year' else 'week')+' FROM '+s[0]+')',params,'number',None,agg)
    if op=='days':
        if any(a.kind!='date' for a in args):raise PlanningError('O intervalo exige duas datas.')
        return Expr('('+s[0]+'-'+s[1]+')',params,'number','dias',agg)
    raise PlanningError('Função não implementada.')
