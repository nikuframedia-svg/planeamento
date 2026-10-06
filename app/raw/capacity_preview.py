"""Read-only F12 simulation, using the publication engine and current peer rows."""
from datetime import datetime
from zoneinfo import ZoneInfo
from .. import planning, planning_needs as needs, planning_population as population
from . import query, projection, capacity_revision as capacity, workbooks


def apply(conn,area,row,base,configs):
    rule=row['calculation']['rules']['hours_pct']
    def unavailable(reason):
        row['values']['hours_pct']=None;rule['reason']=reason
        return {'available':False,'reason':reason,'saved':False}
    if not population.includes(row):return unavailable('Peça fechada: excluída da carga do planeamento ativo.')
    from .capacity import physical_ids  # máquinas do setor e confirmadas à mão, como no motor (07/10/2026)
    resources,aliases=capacity.resource_index(configs,physical_ids(conn,[r for r in configs if r['kind']=='resource']))
    primary=aliases.get((area,row['values'].get('machine')))
    if primary is None:return unavailable('Confirma o recurso físico e o seu calendário para calcular a ocupação semanal.')
    names={r['values'].get('machine') for r in (base,row)}
    names.update(p['values_json'].get('machine') for r in (base,row) for p in r.get('preparations',[]))
    machines={aliases[(area,name)] for name in names if (area,name) in aliases}
    related={a['area'] for ident in machines for a in resources[ident]['definition']['aliases']}
    gens={};sources={};keys={}
    for other_area in related:
        try:gen=query.generation(conn,other_area)
        except planning.PlanningError as exc:
            if exc.status!=503:raise
            return unavailable('A população de '+other_area+' ainda não está disponível para simular a máquina partilhada.')
        if gen['metadata'].get('core_source_fingerprint',gen['metadata'].get('source_fingerprint'))!=projection.fingerprint(conn,other_area):
            return unavailable('As fontes de '+other_area+' estão em atualização; a ocupação será calculável quando a população estiver atualizada.')
        gens[other_area]=gen;sources[other_area]=workbooks.source(conn,other_area)
        relevant=[name for (a,name),ident in aliases.items() if a==other_area and ident in machines]
        source,args=query.source(gen)
        # Query current planning, not the possibly older capacity membership:
        # a just-saved peer can already have moved to the proposed resource.
        keys[other_area]={r['row_key'] for r in conn.execute("SELECT m.row_key"+source+' AND ('+population.active_sql()+')'+
            " AND (c.values_json->>'machine'=ANY(%s) OR EXISTS (SELECT 1 FROM jsonb_array_elements(coalesce(c.detail->'preparations','[]')) p WHERE p->'values_json'->>'machine'=ANY(%s)))",
            args+[relevant,relevant])}
    keys.setdefault(area,set()).add(row['key'])
    scope={'machines':machines,'keys':keys}
    result=capacity.calculate(conn,configs,sources,gens,today=datetime.now(ZoneInfo(planning.settings.display_timezone)).date(),
        scope=scope,rows_override={area:[row]},persist=False)
    items=[i for i in result['items'] if i['values']['area']==area and i['planning_key']==row['key']]
    capacity.apply_planning_results(row,items,result['weekly'])
    f12=row['calculation']['rules']['hours_pct'];f12.pop('capacity_fingerprint',None)
    f12['source']='Simulação da carga total da máquina/semana, incluindo as outras peças e áreas partilhadas.'
    return needs.serial({'available':True,'saved':False,'planning_versions':{a:str(g['id']) for a,g in gens.items()},
        'resources':sorted(machines),'weekly':result['weekly'],'items':items})
