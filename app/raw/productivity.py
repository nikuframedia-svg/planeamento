"""Weighted, traceable productivity from complete matching time/production cohorts.

A cohort's numerator and denominator are accepted or rejected together. No
allocation of sheet time to a subset of its pieces or operations is inferred.
"""
from collections import defaultdict
from datetime import date, timedelta
from itertools import groupby
from psycopg.types.json import Jsonb

from .. import planning, planning_needs as needs
from ..planning_calculations import number, quantity, positive, key
from . import query, worked_hours

UNITS={'area_hour':'mm²/h','metres_hour':'m/h','units_hour':'un./h','minutes_unit':'min/un.','fixed_minutes':'min'}
SCOPE_FIELDS=('material_type','profile','grade')


def ordered_records(rows):
    """Stable evidence order, including conflicting versions of the same ID."""
    result=[]
    for _,group in groupby(sorted(rows,key=lambda r:r['key']),key=lambda r:r['key']):
        versions=list(group)
        result.extend(sorted(versions,key=needs.digest) if len(versions)>1 else versions)
    return result


def historical(events, cohorts, *, area, operation, method, values, as_of, days=90):
    start=as_of-timedelta(days=days-1)
    by_sheet=defaultdict(list)
    for e in ordered_records(events):by_sheet[e['sheet_key']].append(e)
    expanded=[]
    for c in cohorts:
        allocations=(c.get('definition') or {}).get('operation_hours') or []
        if not allocations:expanded.append(c);continue
        assigned={(a['area'],a['operation']) for a in allocations}
        covered=[e for sheet in c.get('sheets',[]) for e in by_sheet[sheet]]
        complete=all((e.get('area'),str(e.get('operation'))) in assigned for e in covered)
        for a in allocations:
            expanded.append({**c,'key':c['key']+':'+a['area']+':'+a['operation'],
                'parent_key':c['key'],'allocation':a,'operation':a['operation'],
                'hours':a['hours'] if c.get('hours') is not None and complete else None,
                'reason':c.get('reason') or ('Repartição não abrange todas as operações dos eventos.' if not complete else None)})
    cohorts=ordered_records(expanded)
    def records_for(c):
        records=[r for sheet in sorted(c.get('sheets',[])) for r in by_sheet[sheet]]
        allocation=c.get('allocation')
        return [r for r in records if r.get('area')==allocation['area'] and str(r.get('operation'))==allocation['operation']] if allocation else records
    owners=defaultdict(set);versions=defaultdict(set)
    for cohort in cohorts:
        versions[cohort['key']].add(needs.digest(cohort))
        for e in records_for(cohort):owners[e['key']].add(cohort['key'])
    used=[];excluded=[];seen_cohorts=set();seen_events=set()
    for cohort in cohorts:
        ident=cohort['key'];reasons=[]
        if ident in seen_cohorts:continue
        seen_cohorts.add(ident)
        if len(versions[ident])>1:reasons.append('Declaração de horas repetida com conteúdo divergente.')
        try:
            first=date.fromisoformat(cohort['start_date']);last=date.fromisoformat(cohort['end_date'])
        except (ValueError,TypeError,KeyError):
            first=last=None;reasons.append('Data das horas desconhecida.')
        if first is not None and (first<start or last>as_of or first>last):
            reasons.append('Período fora da janela histórica.')
        h=positive(cohort.get('hours'))
        if h is None:reasons.append(cohort.get('reason') or 'Horas positivas desconhecidas; zero horas não define produtividade.')
        records=records_for(cohort)
        if not records:reasons.append('Sem produção correspondente às horas.')
        if cohort.get('operation') and str(cohort['operation'])!=str(operation):reasons.append('Horas de outra operação.')
        distinct={};volume=0
        for e in records:
            prior=distinct.get(e['key'])
            if prior is not None:
                if prior!=e:reasons.append('Evento repetido com conteúdo divergente.')
                continue
            distinct[e['key']]=e
            if len(owners[e['key']])>1:reasons.append('Evento abrangido por mais de uma declaração de horas.')
            if e.get('area')!=area or str(e.get('operation'))!=str(operation):
                reasons.append('Tempo partilhado por operações/áreas sem repartição comprovada.')
            if not e.get('identity_valid'):reasons.append('Associação técnica ou operação do evento por confirmar.')
            try:
                produced_on=date.fromisoformat(e['date'])
                if first is None or not first<=produced_on<=last:reasons.append('Data do evento incompatível com o período de horas.')
            except (ValueError,TypeError,KeyError):reasons.append('Data de produção desconhecida.')
            if method=='units_hour' and any(key(e.get(k))!=key(values.get(k)) for k in SCOPE_FIELDS):
                reasons.append('Família, perfil ou qualidade incompatíveis com esta estimativa.')
            q=quantity(e.get('quantity'))
            if q is None:reasons.append('Quantidade de produção desconhecida ou inválida.');continue
            if method=='units_hour':
                if any(number(e.get(k))!=number(values.get(k)) for k in ('length_mm','outer_diameter_mm','width_mm','height_mm','thickness_mm','angle_deg')):
                    reasons.append('Dimensões incompatíveis para produtividade em unidades/h.')
                volume+=q
            elif method in ('area_hour','metres_hour'):
                unit=positive(e.get('section_unit' if method=='area_hour' else 'length_mm'))
                if unit is None and q:reasons.append('Volume do evento sem dimensão comprovada.')
                else:volume+=q*(unit or 0)/(1000 if method=='metres_hour' else 1)
            else:reasons.append('Método histórico desconhecido.')
        if reasons:
            excluded.append({'key':ident,'sheets':sorted(cohort.get('sheets',[])),'events':sorted(distinct),
                             'reasons':sorted(set(reasons))})
            continue
        used.append({'key':ident,'sheets':sorted(cohort.get('sheets',[])),'events':sorted(distinct),'hours':h,'volume':volume,
                     'orders':sorted({e['of'] for e in distinct.values() if e.get('of')}),
                     'start_date':str(first),'end_date':str(last),'hours_origin':cohort.get('origin'),
                     'hours_revision':cohort.get('revision'),'allocation':cohort.get('allocation')})
        seen_events.update(distinct)
    volume=sum(r['volume'] for r in used);hours=sum(r['hours'] for r in used)
    value=volume/hours if hours>0 and volume>0 else None
    # Amostra mínima (06/10/2026): uma taxa histórica precisa de pelo menos MIN_SHIFTS turnos em MIN_DAYS dias e
    # MIN_HOURS horas; uma página com 2 linhas não chega para mudar as horas de centenas de linhas.
    days_used={r['start_date'] for r in used}
    small=value is not None and (len(used)<MIN_SHIFTS or len(days_used)<MIN_DAYS or hours<MIN_HOURS)
    if small:value=None
    return {'source':'Histórico','method':method,'unit':UNITS.get(method),'value':value,
            'window':{'start':str(start),'end':str(as_of),'days':days},'volume':volume,'hours':hours,
            'sheet_count':len({s for r in used for s in r['sheets']}),'event_count':len(seen_events),
            'cohorts':used,'excluded':excluded,'scope':{k:values.get(k) for k in SCOPE_FIELDS} if method=='units_hour' else {'area':area,'operation':operation,'unit':UNITS.get(method),'compatibility':'Volume integral normalizado pela dimensão comprovada de cada peça.'},
            'reason':None if value is not None else (f'Amostra histórica insuficiente ({len(used)} turnos em {len(days_used)} dias, {hours:.1f} h); usa-se o Excel.' if small
                     else 'Sem coorte compatível com volume e horas positivos.')}


MIN_SHIFTS, MIN_DAYS, MIN_HOURS = 3, 2, 15.0
PLAUSIBLE = (0.25, 4.0)  # taxa histórica aceite entre ¼ e 4 vezes a velocidade do Excel


# ---------------------------------------------------------------- tabela de velocidades (07/10/2026)
# Uma só regra para Carteira, Carga, Gantt e motor de capacidade (plano de 06/10, parte 3):
#   1. taxa confirmada da tabela (origem «Confirmada»);
#   2. histórico válido (só no motor e no Gantt, com máquina confirmada);
#   3. linha da tabela com origem «Excel» (semente «velocidades atuais do Excel»), tratada como Excel;
#   4. velocidade do Excel da própria linha / da máquina.
# Dentro da tabela: máquina, área e operação (nos dois formatos, 'CPIS:112' = '112', 'LOCAL:PRINCIPAL' =
# 'corte'); tipo de material e perfil quando a linha os indica (a linha específica ganha à geral); a
# espessura (cantoneiras, tirada da designação) ou a área de secção (perfis) dentro do intervalo, senão o
# intervalo imediatamente superior. Vigência pela data de hoje (as linhas atrasadas usam a taxa de hoje).
RANGE_FIELDS={'cantoneiras':('thickness_min','thickness_max'),'perfis':('section_min','section_max')}
TIMING_FIELDS=('margin_pct','piece_minutes')


def _code(operation):
    from .capacity import operation_code
    return operation_code(operation)


def rate_tier(definition):
    """'Excel' para as linhas criadas pela semente do Excel (até alguém as editar), senão 'Confirmada'."""
    return 'Excel' if str((definition or {}).get('source') or '')=='Excel' else 'Confirmada'


def operation_names(operation, principal, area=None):
    """Nomes de taxa aceites para uma ocorrência (os mesmos no Gantt, na Carteira e no motor).

    'corte' só nos perfis (é o nome da operação principal do motor de perfis); nas cantoneiras o motor procura
    só o código da operação ('112', '119'), e a Carteira e o Gantt fazem o mesmo.
    """
    op=str(operation or '')
    names={op,op.removeprefix('CPIS:')}
    if principal and area!='cantoneiras':names.add('corte')
    if op=='LOCAL:ABOCARDAR':names.add('abocardar')
    return names


def rate_dimension(area, values):
    """Espessura (mm) nas cantoneiras, área de secção unitária (mm²) nos perfis; None se desconhecida."""
    if area=='cantoneiras':
        n=positive(values.get('thickness_mm'))
        if n is not None:return n
        try:from ..gantt.machines import dimensions
        except ImportError:dimensions=_angle_dimensions  # o MES partilha app/raw sem app/gantt
        for text in (values.get('profile'),values.get('designation')):
            found=dimensions(text)
            if found:return found[2]
        return None
    return positive(values.get('section_unit'))


def _angle_dimensions(profile):
    import re
    found=re.fullmatch(r'L([0-9.]+)[X×*]+([0-9.]+)[X×*]+([0-9.]+)',re.sub(r'\s','',str(profile or '').upper()).replace(',','.'))
    try:return tuple(float(v) for v in found.groups()) if found else None
    except ValueError:return None


def interval(definition, area):
    lo,hi=RANGE_FIELDS.get(area,(None,None))
    a=number(definition.get(lo)) if lo else None;b=number(definition.get(hi)) if hi else None
    return (float('-inf') if a is None else a, float('inf') if b is None else b)


def intervals_overlap(a, b):
    """[de, até] fechados. Linhas encostadas (5–8 e 8–12) não se sobrepõem; um ponto num limite sobrepõe-se."""
    lo,hi=max(a[0],b[0]),min(a[1],b[1])
    if lo>hi:return False
    if lo<hi:return True
    return a[0]==a[1] or b[0]==b[1]


def _valid_on(d, day):
    start=str(d.get('valid_from') or '');end=str(d.get('valid_until') or '')
    return (not start or start<=day) and (not end or day<=end)


def match_rate(rates, resource_id, area, operation, values, when=None, *, tier=None):
    """A linha da tabela de velocidades que vale para esta ocorrência, ou None.

    `rates`: objetos raw_objects kind='rate' (com 'definition') ou definições soltas. `operation`: um código
    ou um conjunto de nomes aceites. `when`: dia da vigência (por defeito hoje). `tier`: 'Confirmada' ou
    'Excel' para escolher só essa origem. Devolve {'rate', 'configuration', 'basis'} ou, quando duas linhas
    valem por igual, {'rate': None, 'conflict': [ids], 'reason'}.
    """
    day=str(when or date.today())[:10]
    wanted={_code(x) for x in ([operation] if isinstance(operation,str) or operation is None else operation)}
    pool=[]
    for r in rates or ():
        d=r.get('definition',r) if isinstance(r,dict) else {}
        if not d.get('confirmed') or (isinstance(r,dict) and r.get('archived')):continue
        if str(d.get('resource_id'))!=str(resource_id) or d.get('area')!=area or _code(d.get('operation')) not in wanted:continue
        if tier and rate_tier(d)!=tier:continue
        if not _valid_on(d,day):continue
        if any(d.get(k) and key(d[k])!=key(values.get(k)) for k in ('material_type','profile','grade')):continue
        pool.append((r,d))
    if not pool:return None
    dimension=rate_dimension(area,values)
    # A linha que indica material/perfil ganha à geral; dentro de cada grupo, intervalo e depois o superior.
    groups=defaultdict(list)
    for r,d in pool:groups[tuple(bool(d.get(k)) for k in ('material_type','profile','grade'))].append((r,d))
    for _,group in sorted(groups.items(),key=lambda kv:(-sum(kv[0]),kv[0])):
        found=[];basis=None
        if dimension is not None:
            inside=[(interval(d,area),r,d) for r,d in group if interval(d,area)[0]<=dimension<=interval(d,area)[1]]
            if inside:
                best=min(i[0][1] for i in inside)
                found=[(r,d) for i,r,d in inside if i[1]==best];basis='dentro do intervalo'
            else:
                above=[(interval(d,area),r,d) for r,d in group if interval(d,area)[0]>dimension]
                if above:
                    best=min(i[0][0] for i in above)
                    found=[(r,d) for i,r,d in above if i[0]==best];basis='intervalo imediatamente superior'
        else:
            found=[(r,d) for r,d in group if interval(d,area)==(float('-inf'),float('inf'))];basis='sem intervalo'
        if len(found)>1:
            return {'rate':None,'conflict':sorted(str(r.get('id','')) for r,_ in found),'reason':'Taxas da tabela aplicáveis em conflito.'}
        if found:
            r,d=found[0]
            return {'rate':d,'configuration':r if r is not d else None,'basis':basis,'dimension':dimension}
    return None


def _production_day(value):
    """Um dia de produção explícito (Data Corte), ou None. Nunca escolhe entre vários dias («20+21/08»)."""
    import re
    text=str(value or '')[:10].strip()  # como o estudo da Carteira: os 10 primeiros caracteres
    if not text or '+' in text:return None
    try:day=date.fromisoformat(text[:10])
    except ValueError:
        found=re.match(r'^(\d{1,2})/(\d{1,2})/(\d{2,4})$',text)
        if not found:return None
        d,m,y=(int(x) for x in found.groups())
        try:day=date(y+2000 if y<100 else y,m,d)
        except ValueError:return None
    return day if day.year>=2000 else None


RECENT_WEEKS=8


def recent_excel_speeds(rows, *, until, weeks=RECENT_WEEKS):
    """Velocidade do Excel (m/h) em vigor por máquina: a moda das linhas com a Data Corte mais recente.

    Medido a 06/10/2026: a velocidade `Mt\\h` não depende da espessura nem do perfil; é constante por máquina
    (Rapid 20T 45, Rapid 25T 35, Peddi 6 50) ou mudou no tempo (XP T4/XP T6/Peddi 8: 80 → 100 → 120 m/h).
    Conta só a janela das últimas `weeks` semanas com dados de cada máquina, pela Data Corte (até `until`; uma
    máquina só com datas futuras usa as suas mais antigas). É a regra única da Carteira, da Carga, do motor de
    capacidade e do Gantt quando não há taxa confirmada. Devolve ({máquina: {...}}, {(máquina, perfil): {...}},
    {(máquina, operação): {...}}); os dois últimos só para consulta.
    """
    import re
    from collections import Counter
    lines=defaultdict(list)
    for r in rows:
        machine=str(r.get('Máquina Corte') or '').strip()
        speed=number(r.get('Mt\\h'))
        day=_production_day(r.get('Data Corte'))
        if not machine or not speed or speed<=0 or day is None:continue
        profile=re.sub(r'\s','',str(r.get('Tipo de perfil') or '').upper())
        operation=str(r.get('1ª Oper.') or '').strip().removesuffix('.0')
        lines[machine].append((day,speed,profile,operation))
    by_machine,by_profile,by_operation={},{},{}

    def mode(values):
        counts=Counter(v for _,v in values)
        latest={v:d for d,v in sorted(values)}  # empate: a velocidade da linha mais recente
        return max(counts,key=lambda v:(counts[v],latest[v]))

    for machine,items in lines.items():
        past=[x for x in items if x[0]<=until]
        pool=past or items
        last=max(x[0] for x in pool) if past else min(x[0] for x in pool)
        start=last-timedelta(weeks=weeks)
        window=[x for x in items if start<x[0]<=last] if past else [x for x in items if x[0]<last+timedelta(weeks=weeks)]
        by_machine[machine]={'value':mode([(d,s) for d,s,_,_ in window]),'lines':len(window),'from':start.isoformat(),'to':last.isoformat(),
                             'values':dict(Counter(s for _,s,_,_ in window).most_common(4))}
        for index,target in ((2,by_profile),(3,by_operation)):
            groups=defaultdict(list)
            for x in window:
                if x[index]:groups[x[index]].append((x[0],x[1]))
            for k,values in groups.items():target[(machine,k)]={'value':mode(values),'lines':len(values)}
    return by_machine,by_profile,by_operation


def current_excel_speeds(conn):
    """{máquina: velocidade mais recente} do ficheiro de cantoneiras mais recente (o mesmo do estudo da Carteira)."""
    found=conn.execute("SELECT to_regclass('raw_mtg.plan_production_rows') r, to_regclass('audit_mtg.snapshots') s").fetchone()
    if not found['r'] or not found['s']:return {}  # base sem o Excel das cantoneiras (MES, testes)
    try:snap=planning.snapshot(conn,'cantoneiras')
    except planning.PlanningError:return {}
    rows=conn.execute("SELECT row_data->>'Máquina Corte' m, row_data->>%s s, row_data->>'Data Corte' d "
                      "FROM raw_mtg.plan_production_rows WHERE snapshot_id=%s",('Mt\\h',snap['snapshot_id'])).fetchall()
    loaded=snap.get('loaded_at')
    until=date.fromisoformat(str(loaded)[:10]) if loaded else date.today()
    return recent_excel_speeds([{'Máquina Corte':r['m'],'Mt\\h':r['s'],'Data Corte':r['d']} for r in rows],until=until)[0]


def current_excel(excel, recent, machine):
    """Velocidade do Excel de uma linha de cantoneiras substituída pela mais recente da máquina (quando existe).

    As linhas da tabela de velocidades (têm 'resource_id') e as taxas mm²/h ficam como estão.
    """
    if not excel or excel.get('method')!='metres_hour' or excel.get('resource_id'):return excel
    found=(recent or {}).get(str(machine or '').strip())
    if not found or not positive(found.get('value')):return excel
    return {**excel,'value':found['value'],'unit':'m/h','source':'Velocidade mais recente do Excel',
            'row_value':excel.get('value'),'excel_window':{'from':found.get('from'),'to':found.get('to'),'lines':found.get('lines')}}


def sector_timing(conn):
    """{área: {'margin_pct', 'piece_minutes'}} gravados nas Definições do setor (por defeito 0 = nada muda)."""
    result={area:{'margin_pct':0.0,'piece_minutes':0.0} for area in planning.AREAS}
    if not conn.execute("SELECT to_regclass('planning_mtg.sector_settings') t").fetchone()['t']:return result  # base sem Definições
    rows=conn.execute("SELECT area,definition->'margin_pct' m,definition->'piece_minutes' p FROM planning_mtg.sector_settings").fetchall()
    for r in rows:
        if r['area'] in result:
            result[r['area']]={'margin_pct':max(number(r['m']) or 0.0,0.0),'piece_minutes':max(number(r['p']) or 0.0,0.0)}
    return result


def timed(rate, source, timing):
    """A taxa com o arranque por peça (da linha) mais o tempo fixo do setor e a margem, prontos para as contas.

    O Histórico mede horas reais (já com arranques, manuseamento e perdas): nem margem nem tempo fixo.
    """
    if not rate:return rate
    own=number(rate.get('rate_piece_seconds',rate.get('piece_seconds'))) or 0.0
    timing=timing or {}
    historical=source=='Histórico'
    fixed=0.0 if historical else (number(timing.get('piece_minutes')) or 0.0)*60
    margin=0.0 if historical else number(timing.get('margin_pct')) or 0.0
    if not own and not fixed and not margin:return rate
    return {**rate,'rate_piece_seconds':own,'fixed_piece_seconds':fixed,'piece_seconds':own+fixed,'margin_pct':margin}


def select_rate(values, *, area, operation, resource_id, manual, historical_rate, excel, when, rate_day=None):
    """H10 selection, before calculating hours. A conflict cannot fall through.

    `rate_day` é o dia da vigência das taxas da tabela (o motor passa hoje); sem ele usa-se `when`.
    """
    day=str(rate_day or when)[:10]
    found=match_rate(manual,resource_id,area,operation,values,day,tier='Confirmada')
    if found and found.get('conflict'):return {'source':None,'rate':None,'reason':'Taxas manuais aplicáveis em conflito.','candidates':found['conflict'],'factor':1}
    if found:
        return {'source':'Manual','rate':found['rate'],'configuration':found['configuration'],'reason':None,'factor':1,'basis':found['basis']}
    table=match_rate(manual,resource_id,area,operation,values,day,tier='Excel')
    # Duas linhas com origem Excel em conflito só bloqueiam quando o histórico não vale (o histórico ganha-lhes).
    conflict=table if table and table.get('conflict') else None
    if conflict:table=None
    if table:excel={**table['rate'],'source':'Excel','basis':table['basis']}
    historical_value=positive(historical_rate.get('value'))
    plausible=True
    if historical_value and excel and positive(excel.get('value')) and excel.get('method')==historical_rate.get('method'):
        ratio=historical_value/excel['value']
        plausible=PLAUSIBLE[0]<=ratio<=PLAUSIBLE[1]  # longe demais da velocidade do Excel: amostra suspeita, fica o Excel
    if historical_value and plausible:
        return {'source':'Histórico','rate':{k:historical_rate[k] for k in ('method','value','unit','window') if k in historical_rate},'reason':None,'factor':1}
    if conflict:return {'source':None,'rate':None,'reason':'Taxas da tabela aplicáveis em conflito.','candidates':conflict['conflict'],'factor':1}
    if excel and positive(excel.get('value')):
        factor=3 if area=='perfis' and operation=='corte' and values.get('machine')=='Serrote Fita Thomas IS639 Pav.1' and (quantity(values.get('quantity_required')) or 0)>50 else 1
        result={'source':'Excel provisório','rate':{**excel,'value':excel['value']*factor},'reason':None,'factor':factor}
        if table:result['configuration']=table['configuration']
        return result
    return {'source':None,'rate':None,'reason':historical_rate.get('reason') or 'Sem taxa manual, histórica ou Excel válida.','factor':1}


class Context:
    """One database snapshot and memoized rates for a whole planning calculation."""
    def __init__(self, conn, configs, *, rows_override=None, events_override=None, timing=None, recent_excel=None):
        self.configs=needs.serial(configs);self.manual=[r for r in self.configs if r['kind']=='rate']
        # Velocidade mais recente do Excel por máquina (cantoneiras): substitui o Mt\\h de cada linha.
        self.recent_excel=recent_excel if recent_excel is not None else current_excel_speeds(conn)
        # Margem e tempo fixo por peça das Definições de cada setor (0 = as horas não mudam).
        self.timing=timing if timing is not None else sector_timing(conn)
        # Máquinas físicas (capacity.physical_ids): as do setor no catálogo e as confirmadas à mão (07/10/2026).
        from .capacity import physical_ids
        stored=[r for r in self.configs if r['kind']=='resource'];physical=physical_ids(conn,stored)
        self.resources={r['id']:r for r in stored if str(r['id']) in physical}
        self.aliases={(a['area'],a['name']):r for r in self.resources.values() for a in r['definition']['aliases']}
        self.observed=worked_hours.observations(conn);self.events=[];self.cache={};self.time_cache={};self.history_hashes={}
        self.scopes={}  # cache_key → máquina e operação da taxa histórica (insights do Gantt, auditoria GT-08)
        declarations=[r for r in self.configs if r['kind']=='worked_hours']
        self.declarations=declarations
        for area in planning.AREAS:
            try:
                if events_override and area in events_override:events=events_override[area]
                else:
                    gen=query.generation(conn,area,dataset='production');base,args=query.source(gen)
                    events=[{**r['detail'],'values':r['values_json']} for r in conn.execute('SELECT c.detail,c.values_json'+base,args)]
            except planning.PlanningError as exc:
                if exc.status==503:continue
                raise
            ids=list({k for e in events for k in e.get('planning_keys',[])})
            lines={}
            try:
                gen=query.generation(conn,area);base,args=query.source(gen)
                for r in conn.execute("SELECT m.row_key,c.values_json,jsonb_build_object('compatible',c.detail->'calculation'->'compatible','historical_compatible',c.detail->'calculation'->'historical_compatible') calculation"+base+' AND m.row_key=ANY(%s)',args+[ids]):
                    lines[r['row_key']]={'values':r['values_json'],'calculation':r['calculation'] or {}}
            except planning.PlanningError as exc:
                if exc.status!=503:raise
            for row in (rows_override or {}).get(area,[]):
                for ident in [row['key']]+row.get('selection_aliases',[]):lines[ident]=row
            for e in events:
                v=e['values'];linked=e.get('planning_keys',[]);piece=lines.get(linked[0]) if len(linked)==1 else None
                self.events.append({**(piece['values'] if piece else {}),'key':area+':'+e['key'],
                    'sheet_key':('' if v.get('source')=='ocr_original' else area+':')+str(e.get('sheet_uid') or 'unknown:'+e['key']),'area':area,'operation':v.get('operation'),
                    'machine':v.get('machine'),'date':v.get('production_date'),'quantity':v.get('quantity'),
                    'identity_valid':bool(piece and piece.get('calculation',{}).get('compatible') is not False and piece.get('calculation',{}).get('historical_compatible') is not False
                        and v.get('association_status') in ('associated','explicit','technical_unique'))})

    def history_inputs_hash(self):
        """Inputs consumed by historical(), independent of planning import IDs.

        Closing/reopening an OF or rebinding an unchanged macro row must not
        invalidate the historical rates of every other piece on its machines.
        Production identity, dimensions, coverage and all time evidence remain
        dependencies. Duplicate keys retain their entire conflicting payloads.
        """
        fields=('key','sheet_key','area','operation','machine','date','quantity','identity_valid',
                *SCOPE_FIELDS,'length_mm','section_unit','outer_diameter_mm','width_mm',
                'height_mm','thickness_mm','angle_deg')
        groups=defaultdict(list)
        for event in self.events:groups[event['key']].append(event)
        events=[]
        for ident,rows in sorted(groups.items()):
            events.extend(sorted(rows,key=needs.digest) if len(rows)>1 else [{k:rows[0].get(k) for k in fields}])
        return needs.digest(['historical-inputs-v1',events,sorted(self.observed,key=needs.digest),
                             sorted(self.declarations,key=needs.digest)])

    def cohorts(self, area, machine):
        resource=self.aliases.get((area,machine))
        if resource is None:
            resource={'id':area+':'+str(machine),'definition':{'aliases':[{'area':area,'name':machine}]}}
        if resource['id'] not in self.time_cache:
            self.time_cache[resource['id']]=worked_hours.resolve(resource,self.declarations,self.observed) if machine else []
        return resource,self.time_cache[resource['id']]

    def rate(self, values, area, operation, when, *, excel=None, as_of=None):
        resource,cohorts=self.cohorts(area,values.get('machine'))
        days=resource['definition'].get('history_window_days',90)
        as_of=as_of or date.fromisoformat(when)
        method='area_hour' if area=='perfis' and operation=='corte' else 'metres_hour' if area=='cantoneiras' else 'units_hour'
        scope={k:values.get(k) for k in SCOPE_FIELDS+('length_mm','outer_diameter_mm','width_mm','height_mm','thickness_mm','angle_deg')} if method=='units_hour' else {}
        cache_key=needs.digest([resource['id'],area,operation,method,scope,str(as_of),days])
        if cache_key not in self.cache:
            self.cache[cache_key]=historical(self.events,cohorts,area=area,operation=operation,method=method,values=values,as_of=as_of,days=days)
            self.history_hashes[cache_key]=needs.digest({'productivity':self.cache[cache_key]})
            self.scopes[cache_key]={'resource_id':resource['id'] if resource['id'] in self.resources else None,
                                    'machine':values.get('machine'),'area':area,'operation':str(operation)}
        history=self.cache[cache_key]
        if area=='cantoneiras':excel=current_excel(excel,getattr(self,'recent_excel',None),values.get('machine'))
        # Vigência das taxas da tabela pela data de hoje (as_of), não pela data prevista (plano de 06/10, parte 3).
        chosen=select_rate(values,area=area,operation=operation,resource_id=resource['id'],manual=self.manual,historical_rate=history,excel=excel,when=when,rate_day=str(as_of))
        digest=self.history_hashes[cache_key]
        return {**chosen,'history_hash':digest,'history':{k:v for k,v in history.items() if k not in ('cohorts','excluded')},
                'excluded_cohorts':len(history['excluded'])}

    def persist(self, conn):
        # Immutable evidence is shared by content hash, rather than repeated for
        # tens of thousands of pieces with the same productivity scope.
        for cache_key,history in self.cache.items():
            digest=self.history_hashes[cache_key]
            conn.execute("INSERT INTO planning_mtg.raw_contents(hash,values_json,detail,search_text) VALUES(%s,'{}',%s,'') ON CONFLICT DO NOTHING",
                         (digest,Jsonb({'productivity':needs.serial(history)})))

    def estimate(self, values, area, operation, when, *, excel=None, as_of=None):
        from .capacity import estimate,estimate_rule
        applied=self.rate(values,area,operation,when,excel=excel,as_of=as_of)
        resource=self.aliases.get((area,values.get('machine')))
        allowed=operation in ('corte','abocardar') if area=='perfis' else str(operation).isdigit() and str(operation)!='0'
        from .capacity import supports
        # A lista de operações só limita as máquinas confirmadas à mão: numa máquina do setor com a lista do catálogo
        # (às vezes vazia) as horas não desaparecem por isso (07/10/2026).
        if not allowed or resource and resource['definition'].get('confirmed') and not supports(resource,operation):
            result={**applied,'source':None,'rate':None,'hours':None,'reason':'Operação por confirmar para este recurso.'}
            return {**result,'calculation':estimate_rule(values,result)}
        effective=timed(applied['rate'],applied['source'],getattr(self,'timing',{}).get(area))
        h,reason=estimate(values,effective,operation) if applied['rate'] else (None,applied['reason'])
        if quantity(values.get('quantity_to_plan'))==0:h,reason=0,None
        result={**applied,'hours':h,'reason':reason}
        return {**result,'calculation':estimate_rule(values,{**result,'rate':effective})}


def apply_rows(conn, area, rows, configs, *, persist=True, context=None, source=None, today=None):
    if not rows:return
    from zoneinfo import ZoneInfo
    from datetime import datetime
    from . import workbooks, capacity_revision
    from .. import planning_estimates
    from ..gantt.research import overlay_rows
    overlay_rows(conn,area,rows)
    context=context or Context(conn,configs,rows_override={area:rows})
    if source is None and persist:workbooks.capture(conn,area)
    src=source or workbooks.source(conn,area)
    _,excel_rates,_=capacity_revision.workbook_index({area:src})
    periods=[r for r in configs if r['kind']=='period']
    today=today or datetime.now(ZoneInfo(planning.settings.display_timezone)).date()
    for row in rows:
        row.setdefault('calculation',{}).setdefault('rules',{})
        v=row['values'];primary='corte' if area=='perfis' else str(v.get('operation') or '')
        if area=='cantoneiras':
            row.setdefault('original',{}).setdefault('speed_m_h',number(row['raw'].get('Mt\\h')))
            row['original'].setdefault('theoretical_hours',number(row['raw'].get('h teor. Falta')))
        preparations={r['values_json'].get('operation'):r['values_json'] for r in row.get('preparations',[])}
        estimates=[]
        for source in row.get('calculation',{}).get('production_sources',[]):
            op=source['operation'];main=op==primary
            balance=planning_estimates.select_balance(row,op) if area=='perfis' else {
                'planning_remaining':source['remaining'],'reconciled_remaining':source['remaining'],
                'balance_origin':source['origin'],'provisional':source['origin']=='Excel provisório',
                'evidence':source.get('records') or [],'reasons':source.get('coverage_reasons') or []}
            operation_values=preparations.get(op) or ({} if main else {'machine':None,'expected_date':None,'planned_week':None,'planned_year':None})
            vals={**v,**{k:x for k,x in operation_values.items() if k not in needs.PIECE_FIELDS}}
            vals['quantity_to_plan']=balance['planning_remaining'];vals['quantity_required']=v.get('quantity_required')
            # Operação seguinte MTG3 não herda a Data Corte (mesma regra de capacity_revision.period).
            y,w,_=capacity_revision.period({**vals,'cut_date':None} if area=='cantoneiras' and not main else vals,area,src['snapshot_id'],periods,today=today)
            when=str(vals.get('expected_date') or (date.fromisocalendar(y,w,1) if y and w else today))[:10]
            excel=None
            if main:
                imported=excel_rates.get((area,vals.get('machine')))
                excel={**imported,'method':'area_hour'} if area=='perfis' and imported else {'method':'metres_hour','value':number(row['raw'].get('Mt\\h')),'unit':'m/h','source':'Macro · Mt\\h'} if area=='cantoneiras' else None
            # A janela histórica acaba hoje (auditoria 06/10, C3-F6), igual para todas as linhas e para o Gantt;
            # a data prevista (when) só escolhe a vigência das taxas manuais.
            result=context.estimate(vals,area,op,when,excel=excel,as_of=today)
            estimates.append({'operation':op,'machine':vals.get('machine'),'quantity':balance['planning_remaining'],
                              'balance':balance,**result})
            if main:
                v['planning_remaining']=balance['planning_remaining']
                v['planning_balance_origin']=balance['balance_origin']
                v['planning_balance_provisional']=balance['provisional']
                v['theoretical_hours']=result['hours'];v['rate_source']=result['source']
                v['applied_rate_value']=(result['rate'] or {}).get('value')
                v['speed_m_h']=v['applied_rate_value'] if (result['rate'] or {}).get('method')=='metres_hour' else None
                v['applied_rate_unit']=UNITS.get((result['rate'] or {}).get('method')) or (result['rate'] or {}).get('method')
                row['calculation']['rules']['theoretical_hours']=result['calculation']
        row['calculation']['operation_estimates']=estimates
        # The old Excel percentage is not the recalculated weekly occupancy.
        v['hours_pct']=None
        from .. import planning_population
        row['calculation']['rules']['hours_pct']={'formula':'100 × carga da máquina/semana / disponibilidade',
            'reason':'Ocupação agregada aguarda publicação conjunta com a capacidade.' if planning_population.includes(row)
                else 'Peça fechada: excluída da carga do planeamento ativo.'}
    if persist:context.persist(conn)


def evidence(digest):
    with planning.connect(readonly=True) as conn:
        row=conn.execute("SELECT detail->'productivity' evidence FROM planning_mtg.raw_contents WHERE hash=%s AND detail ? 'productivity'",(digest,)).fetchone()
        if not row:raise planning.PlanningError('Evidência de produtividade não encontrada.',404)
        return {'hash':digest,**row['evidence']}
