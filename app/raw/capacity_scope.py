"""Dependency scope between two committed capacity/planning publications.

Use membership epochs, not wall-clock timestamps. A missing cursor or changed
workbook/day falls back to the complete calculation; it never guesses freshness.
"""
from .. import planning, planning_needs as needs
from . import query


def changed_keys(conn,dataset,previous,current):
    if str(previous)==str(current):return set()
    return {r['row_key'] for r in conn.execute('''SELECT DISTINCT row_key FROM planning_mtg.raw_members
        WHERE dataset=%s AND ((first_generation>%s AND first_generation<=%s)
          OR (last_generation>%s AND last_generation<=%s))''',
        (dataset,int(previous),int(current),int(previous),int(current)))}


def rows_at(conn,area,version,keys,dataset='planning'):
    if not keys:return []
    gen=conn.execute('SELECT * FROM planning_mtg.raw_generations WHERE id=%s AND dataset=%s',(int(version),dataset+':'+area)).fetchone()
    if not gen:raise planning.PlanningError('Falta uma versão de origem para o recálculo.',409)
    base,args=query.source(gen)
    return [{**r['detail'],'values':r['values_json']} for r in conn.execute(
        'SELECT c.detail,c.values_json'+base+' AND m.row_key=ANY(%s)',args+[list(keys)])]


def capacity_inputs(row):
    if row is None:return None
    # A core OF refresh removes derived occupancy/rate fields from peer rows.
    # That alone does not invalidate every resource used by those peers.
    derived={'hours_pct','theoretical_hours','rate_source','applied_rate_value','applied_rate_unit','speed_m_h',
             'planning_remaining','planning_balance_origin','planning_balance_provisional'}
    diagnostics={'last_activity','unassigned_records','execution_status'}
    calc=row.get('calculation',{})
    return {'values':{k:v for k,v in row['values'].items() if k not in derived|diagnostics},
        'raw':{k:row.get('raw',{}).get(k) for k in ('Fechado','Horas Consumidas','h teor. Falta','Quantidade Prevista','Qtd em Falta','Mt\\h')},
        'preparations':row.get('preparations',[]),'compatible':calc.get('compatible'),
        'macro_balance_source':{
            'quantity_required':row.get('original',{}).get('quantity_required'),
            'technical_signature':needs.signature(row.get('original',{}))},
        'production_sources':calc.get('production_sources',[]),
        'identity':{k:row.get(k) for k in ('key','revision','need_id','plan_key','selection_aliases','population')}}


def history_inputs(row):
    if row is None:return None
    values=row['values'];calc=row.get('calculation',{})
    return {'values':{k:values.get(k) for k in ('material_type','profile','grade','length_mm',
        'outer_diameter_mm','width_mm','height_mm','thickness_mm','angle_deg','section_unit')},
        'compatible':calc.get('compatible'),'historical_compatible':calc.get('historical_compatible'),
        'identity':{k:row.get(k) for k in ('key','need_id','plan_key','selection_aliases')}}


def identify(conn,previous,gens,versions,snapshots,configs,contract,day,machine_key,reference_inputs=None,*,history_unchanged=False):
    """Return affected physical resources and complete peer keys, or None for full."""
    if not previous:return None
    meta=previous['metadata']
    if meta.get('contract')!=contract or meta.get('day')!=day:return None
    if reference_inputs is not None and meta.get('reference_inputs')!=reference_inputs:return None
    if meta.get('snapshots')!=snapshots:
        # Retained estimates cite their original immutable workbook evidence.
        # Reuse is valid only if every referenced cell/formula is identical and
        # no snapshot-bound interpretation of imported weeks changes.
        if not reference_inputs or meta.get('reference_inputs')!=reference_inputs:return None
        changed_areas={a for a,s in snapshots.items() if meta.get('snapshots',{}).get(a)!=s}
        for obj in [*meta.get('configurations',[]),*configs]:
            if (obj['kind']=='period' and obj['area'] in changed_areas
                    and obj['definition'].get('snapshot') in
                    (meta.get('snapshots',{}).get(obj['area']),snapshots.get(obj['area']))):return None
    cursors=meta.get('applied_planning_versions')
    if cursors is None or set(cursors)!=set(gens):return None
    old_versions=meta.get('planning_versions',{})
    # Dataset addition/removal changes the available production universe.
    if set(old_versions)!=set(versions):return None
    machines=set();estimate_machines=set();changed={};keys={area:set() for area in gens};restored={area:{} for area in gens}
    prior_estimates={}
    old_configs={str(r['id']):r for r in meta.get('configurations',[])}
    new_configs={str(r['id']):r for r in needs.serial(configs)}
    for ident in set(old_configs)|set(new_configs):
        old,new=old_configs.get(ident),new_configs.get(ident)
        if old==new:continue
        for conf in (old,new):
            if not conf:continue
            d=conf['definition']
            if conf['kind']=='period':return None  # Global interpretation of imported weeks.
            if conf['kind']=='resource':
                machines.add(str(conf['id']))
                estimate_machines.add(str(conf['id']))
                for alias in d.get('aliases',[]):
                    machines.add(alias['area']+':'+str(alias['name']))
                    machines.add(machine_key(alias['area'],alias['name']))
                    estimate_machines.add(alias['area']+':'+str(alias['name']))
                    estimate_machines.add(machine_key(alias['area'],alias['name']))
            else:
                machines.add(str(d['resource_id']))
                if conf['kind']!='calendar':estimate_machines.add(str(d['resource_id']))
    configured_estimates=set(estimate_machines)
    for area,gen in gens.items():
        candidates=changed_keys(conn,'planning:'+area,cursors[area],gen['id'])
        old_rows={r['key']:r for r in rows_at(conn,area,cursors[area],candidates)}
        current_rows={r['key']:r for r in rows_at(conn,area,gen['id'],candidates)}
        changed[area]={key for key in candidates if capacity_inputs(old_rows.get(key))!=capacity_inputs(current_rows.get(key))}
        history_changed={key for key in candidates if history_inputs(old_rows.get(key))!=history_inputs(current_rows.get(key))}
        for key in candidates-changed[area]:
            old,current=old_rows.get(key),current_rows.get(key)
            if not old or not current:continue
            from .. import planning_population
            # Closed pieces have no current capacity item. Their estimates were
            # calculated by the core publisher; there is no active aggregate to
            # restore, and an older estimate must not overwrite that calculation.
            if not planning_population.includes(current):continue
            for field in ('hours_pct','theoretical_hours','rate_source','applied_rate_value','applied_rate_unit','speed_m_h',
                          'planning_remaining','planning_balance_origin','planning_balance_provisional'):
                if field in old['values']:current['values'][field]=old['values'][field]
            for field in ('hours_pct','theoretical_hours'):
                old_rule=old.get('calculation',{}).get('rules',{}).get(field)
                if old_rule is not None:current.setdefault('calculation',{}).setdefault('rules',{})[field]=old_rule
            if 'operation_estimates' in old.get('calculation',{}):
                prior_estimates[(area,key)]=old['calculation']['operation_estimates']
            restored[area][key]=current
        keys[area].update(changed[area])
        for row in [r for key,r in current_rows.items() if key in changed[area]]:
            v=row['values'];machines.add(machine_key(area,v.get('machine')))
            for prep in row.get('preparations',[]):machines.add(machine_key(area,prep['values_json'].get('machine')))
            extra='abocardar' if area=='perfis' and v.get('abocardar')=='X' else str(v.get('operation_detail') or '') if area=='cantoneiras' else None
            counted=extra=='abocardar' or (str(extra or '').isdigit() and extra!='0')
            if counted and not any(str(p['values_json'].get('operation'))==extra for p in row.get('preparations',[])):
                machines.add(machine_key(area,None))
        for dataset in ('production','production_hours'):
            name=dataset+':'+area
            if name not in versions:continue
            events=changed_keys(conn,name,old_versions[name],versions[name])
            for version in {str(old_versions[name]),str(versions[name])}:
                for row in rows_at(conn,area,version,events,dataset):
                    if (dataset=='production_hours'
                            and all(row['values'].get(k) is None for k in ('machine','production_date','hours_worked'))
                            and not row.get('original_machines')):
                        # An empty validated sheet has no time/resource input.
                        # Keep its diagnostic, without invalidating every piece
                        # whose machine is still unknown. Old nonempty versions
                        # are still visited when a declaration is cleared.
                        continue
                    machine=machine_key(area,row['values'].get('machine'))
                    machines.add(machine);estimate_machines.add(machine)
            if dataset=='production' and history_changed:
                # A geometry/identity edit can change historical productivity even
                # when the validated event itself has not changed.
                pg=query.generation(conn,area,dataset=dataset);base,args=query.source(pg)
                for r in conn.execute("SELECT DISTINCT c.values_json->>'machine' machine"+base+
                        " AND coalesce(c.detail->'planning_keys','[]') ?| %s",args+[list(history_changed)]):
                    machines.add(machine_key(area,r['machine']))
                    estimate_machines.add(machine_key(area,r['machine']))
    if history_unchanged:
        # The complete production/time inputs prove that rates and exclusions
        # are unchanged. Configuration changes still invalidate their estimates.
        estimate_machines=configured_estimates
    prior_items={}
    for area in gens:
        try:g=query.generation(conn,area,dataset='capacity_items')
        except planning.PlanningError:return None
        base,args=query.source(g)
        # Lightweight adjacency index; complete item JSON is loaded only for the
        # selected resources during calculation/publication.
        prior_items[area]=conn.execute("SELECT m.row_key key,c.values_json->>'area' area,c.values_json->>'machine_key' machine,c.values_json->>'operation' operation,c.detail->>'planning_key' piece"+base,args).fetchall()
        for item in prior_items[area]:
            if item['piece'] in changed.get(item['area'],set()):machines.add(item['machine'])
    for items in prior_items.values():
        for item in items:
            if item['machine'] in machines and item['area'] in keys:keys[item['area']].add(item['piece'])
    represented={}
    for items in prior_items.values():
        for item in items:
            ident=(item['area'],item['piece'])
            if ident in prior_estimates:represented.setdefault(ident,set()).add(item['operation'])
    for (area,key),estimates in prior_estimates.items():
        calculation=restored[area][key].setdefault('calculation',{})
        current={str(e['operation']):e for e in calculation.get('operation_estimates',[])}
        # Only the capacity publisher owns these estimates. Unresolved extra
        # operations have no capacity item; keep their newer core diagnostics.
        for estimate in estimates:
            if str(estimate['operation']) in represented.get((area,key),set()):
                current[str(estimate['operation'])]=estimate
        calculation['operation_estimates']=list(current.values())
    # Closed pieces have no capacity adjacency. Their current estimates still
    # depend on rates, history and resource aliases, while calendars do not
    # create any load for them. Include only these estimation dependencies.
    from .. import planning_population
    for area,gen in gens.items():
        names={m[len(area)+1:] for m in estimate_machines if m.startswith(area+':')}
        if 'None' in names:names.remove('None');names.add('')
        for conf in [*old_configs.values(),*new_configs.values()]:
            if conf['kind']=='resource' and str(conf['id']) in estimate_machines:
                names.update(a['name'] for a in conf['definition'].get('aliases',[]) if a['area']==area)
        if not names:continue
        # gens are the current generations in rebuild's REPEATABLE READ
        # snapshot. This partial index avoids reading every retained content.
        keys[area].update(r['row_key'] for r in conn.execute('''SELECT row_key FROM planning_mtg.raw_members
            WHERE dataset=%s AND last_generation IS NULL AND planning_active=false AND planning_machine=ANY(%s)''',
            ('planning:'+area,sorted(names))))
        base,args=query.source(gen)
        base+=' AND NOT ('+planning_population.active_sql()+')'
        primary="c.values_json->>'machine'=ANY(%s)"
        if '' in names:primary="("+primary+" OR c.values_json->>'machine' IS NULL)"
        legacy=conn.execute('''SELECT 1 FROM planning_mtg.raw_members WHERE dataset=%s
            AND last_generation IS NULL AND planning_active IS NULL LIMIT 1''',('planning:'+area,)).fetchone()
        if legacy:
            keys[area].update(r['row_key'] for r in conn.execute('SELECT m.row_key'+base+' AND m.planning_active IS NULL AND '+primary,args+[sorted(names)]))
        prepared=gen['metadata'].get('preparation_keys')
        # Separate queries matter: PostgreSQL can distribute an OR predicate
        # and evaluate the JSON subquery on every nonmatching primary row.
        if prepared is None or prepared:
            preparation_scope=' AND m.row_key=ANY(%s)' if prepared is not None else ''
            preparation_args=[prepared] if prepared is not None else []
            keys[area].update(r['row_key'] for r in conn.execute('SELECT m.row_key'+base+preparation_scope+
                " AND EXISTS (SELECT 1 FROM jsonb_array_elements(coalesce(c.detail->'preparations','[]')) p WHERE coalesce(p->'values_json'->>'machine','')=ANY(%s))",
                args+preparation_args+[sorted(names)]))
    # Peer estimates remain valid when their inputs and rate/history context
    # did not change. They still contribute to complete aggregate populations.
    from collections import defaultdict
    piece_machines=defaultdict(set)
    for items in prior_items.values():
        for item in items:piece_machines[item['area'],item['piece']].add(item['machine'])
    reusable=machines-estimate_machines;reuse={area:set() for area in gens}
    for area,items in prior_items.items():
        for item in items:
            a,key=item['area'],item['piece']
            if a in keys and key not in changed[a] and item['machine'] in reusable and not (piece_machines[a,key]&machines)-reusable:
                reuse[area].add(item['key'])
    skip={area:set() for area in gens}
    for items in prior_items.values():
        for item in items:
            a,key=item['area'],item['piece']
            if a in skip and key not in changed[a] and piece_machines[a,key]&machines and not (piece_machines[a,key]&machines)-reusable:
                skip[a].add(key)
    return {'machines':machines,'keys':{a:k-skip[a] for a,k in keys.items()},'changed':changed,'restored':restored,'reuse':reuse}


def publish(conn,dataset,fingerprint,rows,metadata,scope):
    from . import projection
    if scope is None:return projection.publish(conn,dataset,fingerprint,rows,metadata)
    kind,area=dataset.split(':',1);gen=query.generation(conn,area,dataset=kind);base,args=query.source(gen)
    old={r['row_key'] for r in conn.execute("SELECT m.row_key"+base+" AND c.values_json->>'machine_key'=ANY(%s)",args+[sorted(scope['machines'])])}
    return projection.publish_delta(conn,dataset,fingerprint,[r for r in rows if not r.get('_retained')],metadata,
        remove=old-{r['key'] for r in rows},expected_generation=gen['id'])
