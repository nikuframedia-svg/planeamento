"""Atomic common registration and table batches; only local preparation is written."""
from contextlib import nullcontext
import uuid
from .. import planning,planning_needs as needs,planning_catalogs as catalogs
from ..dossiers.models import order_number
from . import query,projection,incremental,workbooks,registration as free


class Candidates(Exception):
    def __init__(self,result):self.result=result


def macro_candidates(conn,area,of,values):
    if not values.get('component_ref'):return []
    snap=planning.snapshot(conn,area)
    rows=conn.execute('''SELECT r.*,p.remaining_quantity canonical_remaining,p.remaining_valid,
      NULL::text cpis_status,NULL::date cpis_delivery_date,NULL::date cpis_planned_finish_date
      FROM raw_mtg.plan_production_rows r LEFT JOIN analytics_mtg.kanban_plan_lines p ON p.snapshot_id=r.snapshot_id AND p.plan_key=r.source_line_id
      WHERE r.snapshot_id=%s AND regexp_replace(trim(r.production_order_no),'^OF[ ._-]*','','i')=%s
      AND lower(trim(r.component_ref))=lower(trim(%s))''',(snap['snapshot_id'],of[2:],values['component_ref'])).fetchall()
    result=[]
    for r in rows:
        v=planning.line_data(r,area,{})['values'];complete=needs.complete(v) and needs.complete(values)
        exact=complete and needs.signature(v)==needs.signature(values)
        result.append({'plan_key':r['source_line_id'],'source_version':snap['snapshot_id'],'component_ref':v['component_ref'],'specification':v,'quantity_required':v.get('quantity_required'),'exact':exact,'same_quantity':planning._number(v.get('quantity_required'))==planning._number(values.get('quantity_required'))})
    return result


def editor_fields(area):
    """Campos que o formulário de registo mostra e envia para este setor."""
    return {f['id'] for f in catalogs.arrange(catalogs.fields(),area) if f['editor_visible']}


def linked_plan_lines(conn,area,of):
    """Linhas do Excel desta OF já ligadas a uma peça, pelo identificador da importação atual."""
    linked=set()
    for s in conn.execute("""SELECT s.source_id FROM planning_mtg.need_sources s JOIN planning_mtg.needs n ON n.id=s.need_id
        WHERE s.kind='plan_line' AND n.production_order_no=%s""",(of,)).fetchall():
        try:linked.add(needs.source_data({'kind':'plan_line','id':s['source_id']},area,conn)['id'])
        except planning.PlanningError:continue
    return linked


def current_source(conn,source,area):
    """A origem na versão atual (07/10/2026: uma importação com o formulário aberto já não dá 409).

    Uma linha do Excel que deixou de existir na importação atual conta como registo manual.
    """
    if not source:return None
    try:return needs.source_data({k:v for k,v in source.items() if k!='version'},area,conn)
    except planning.PlanningError:
        if source.get('kind')=='plan_line':return None
        raise


def agrees(typed,line):
    """A peça escrita não contradiz a linha do Excel: os campos técnicos escritos coincidem e a QTD é igual ou vazia."""
    mine,theirs=needs.signature(typed),needs.signature(line)
    if any(value is not None and value!=theirs[key] for key,value in mine.items()):return False
    quantity=planning._number(typed.get('quantity_required'))
    return quantity is None or quantity==planning._number(line.get('quantity_required'))


@incremental.retry_serialization
def prepare(p):
    """Gravar do formulário de registo: grava sempre (07/10/2026).

    Se a peça ou a origem mudaram entretanto (importação do Excel, outra pessoa), só os campos que o
    formulário mudou (changed_fields) vão por cima da versão atual. Um pedido sem essa lista (separador
    antigo) recebe o 409 de antes, para não repor valores que entretanto mudaram.
    """
    try:
        with planning.connect() as c,workbooks.interactive():
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            _,_,old=needs.command(c,p)
            if old:return old
            before=incremental.baseline(c)
            area=planning.check_area(p.get('area'));source=p.get('source') or None
            src=current_source(c,source,area)
            # Um PDF de outra OF usa a OF do PDF; o formulário avisa e não bloqueia.
            of=order_number(src['of'] if src else p.get('production_order_no'))
            nid=p.get('need_id');revision=None;chosen=None
            changed=p['changed_fields'] if isinstance(p.get('changed_fields'),list) else None
            entered=dict(p.get('values') or {});decisions=dict(p.get('decisions') or {})
            typed=set(decisions)|set(changed or [])
            source_changed=bool(source) and (src is None or (source.get('version') is not None and str(source['version'])!=str(src['version'])))
            if nid:
                revision=needs.refresh(c,needs.load(c,nid))['revision']
                stale=source_changed or p.get('expected_revision')!=revision
            else:
                # Peça nova cuja linha do Excel desapareceu: os valores do formulário são a base.
                stale=source_changed and src is not None
            if stale:
                if changed is None:raise planning.PlanningError('A peça mudou entretanto. Reabre a ficha para ver a versão atual.',409)
                keep=set(changed)|({'operation'} if nid else set())
                entered={k:v for k,v in entered.items() if k in keep}
                decisions={k:v for k,v in decisions.items() if k in keep}
                if src and not nid:entered={**{k:v for k,v in src['values'].items() if k in editor_fields(area)},**entered}
            # A 1.ª Oper. vazia no formulário não apaga a da origem (o valor por defeito só entra sem nenhuma).
            if src and entered.get('operation') in (None,'') and src['values'].get('operation'):
                entered['operation']=src['values']['operation']
            values={**(src['values'] if src else {}),**entered}
            if nid and src:
                linked=needs.resolve({'request_id':str(uuid.uuid5(needs.uid(p['request_id']),'link')),'area':area,'source':{k:v for k,v in source.items() if k!='version'},'need_id':nid,'expected_revision':revision,'reason':p.get('reason') or 'Reabertura da origem já associada.'},conn=c)
                if linked.get('needs_decision'):raise Candidates(linked)
                if str(linked['need_id'])!=str(nid):raise planning.PlanningError('O documento já está associado a outra peça. Reabre a origem.',409)
                revision=linked['revision']
            if not nid:
                if not of:raise planning.PlanningError('Seleciona uma OF válida.')
                possible=macro_candidates(c,area,of,values) if not src or src['kind']!='plan_line' else []
                # Abocardar só conta como escrito quando o utilizador lhe mexeu (o formulário envia sempre falso).
                mine={k:v for k,v in entered.items() if v not in (None,'') and (k!='abocardar' or k in typed)}
                chosen=next((r for r in possible if r['plan_key']==p.get('selected_plan_key')),None)
                if not chosen and len(possible)==1 and not p.get('create_distinct'):
                    # Peça possivelmente repetida (07/10/2026): liga-se à linha do Excel só quando é a única com a
                    # mesma OF e Referência, ninguém a tem e nada do que foi escrito a contradiz; senão é peça própria.
                    candidate=possible[0]
                    line=needs.source_data({'kind':'plan_line','id':candidate['plan_key']},area,c)['values']
                    if agrees(mine,line) and candidate['plan_key'] not in linked_plan_lines(c,area,of):chosen=candidate
                if chosen:
                    line=needs.source_data({'kind':'plan_line','id':chosen['plan_key']},area,c)['values']
                    entered={**{k:v for k,v in line.items() if k in editor_fields(area)},**mine}
                    values={**values,**entered}
                resolution={k:p[k] for k in ('area','production_order_no','reason','create_distinct') if k in p}
                if src:resolution['source']={k:v for k,v in source.items() if k!='version'}
                resolution.update(_allow_unresolved=True,values=values,request_id=str(uuid.uuid5(needs.uid(p['request_id']),'resolve')))
                result=needs.resolve(resolution,conn=c)
                if result.get('needs_decision'):raise Candidates(result)
                nid=result['need_id'];revision=result['revision']
                # Nunca duas linhas do Excel na mesma peça: a peça reaproveitada que já tem uma fica como está.
                if chosen and any(s['kind']=='plan_line' for s in needs.linked_sources(c,nid)):chosen=None
            if chosen:
                result=needs.resolve({'request_id':str(uuid.uuid5(needs.uid(p['request_id']),'macro')),'area':area,'source':{'kind':'plan_line','id':chosen['plan_key'],'version':chosen['source_version']},'need_id':nid,'expected_revision':revision,'reason':p.get('reason') or 'Única linha do Excel com a mesma OF e Referência.'},conn=c)
                revision=result['revision']
            save_values=dict(entered)
            if src:
                for f in c.execute('SELECT * FROM planning_mtg.field_state WHERE need_id=%s',(nid,)).fetchall():
                    if f['field'] in save_values and f['field'] not in typed and f.get('human_decision'):save_values[f['field']]=f['value']
            result=needs.save({**p,'values':save_values,'decisions':decisions,'request_id':str(uuid.uuid5(needs.uid(p['request_id']),'save')),'need_id':nid,'expected_revision':revision},conn=c)
            if p.get('local_order') is not None:
                from .. import planning_local_orders
                need=needs.load(c,nid)
                context=planning_local_orders.save(c,need['production_order_no'],p['local_order'],needs.registration.human_actor(p),
                                                 merge=True,changed_fields=p.get('local_order_changed_fields'))
                result['local_order']=needs.serial(context)
            projection.signal(c,'planning:'+area)
            published=incremental.publish(c,before,[needs.load(c,nid)['production_order_no']],[nid],p['request_id'])
            return needs.finish(c,p,{**result,'publication':published,'raw_url':'/planeamento/raw?area='+area+'&need='+str(nid),
                                     'excel_link':chosen['plan_key'] if chosen else None})
    except Candidates as exc:return exc.result


@incremental.retry_serialization
def update_batch(p):
    edits=p.get('edits')
    if not isinstance(edits,list) or not 1<=len(edits)<=500 or any(not isinstance(e,dict) for e in edits):raise planning.PlanningError('O lote deve conter entre 1 e 500 linhas.')
    area=planning.check_area(p.get('area','perfis'))
    with planning.connect() as c,workbooks.interactive():
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        _,_,old=needs.command(c,p)
        if old:return old
        before=incremental.baseline(c)
        gen=query.generation(c,area,p.get('version'));current=query.generation(c,area)
        if gen['id']!=current['id']:raise planning.PlanningError('Existem dados novos. Atualiza a lista e compara as alterações.',409)
        source_fingerprint=projection.fingerprint(c,area)
        cat=catalogs.catalog(area,c);allowed={f['id'] for f in contracts_for(area) if f['editable']}|{'picking_year','custom_profile','special_profile','geometry','identity_discriminator'}
        results=[];seen=set();orders=set();local_revisions={}
        for i,e in enumerate(edits):
            key=e.get('key');changes=e.get('values') or {}
            if key in seen:raise planning.PlanningError('Agrupa as alterações da mesma linha num único pedido.')
            seen.add(key)
            if not changes or not isinstance(changes,dict) or set(changes)-allowed:raise planning.PlanningError('Só podes alterar campos locais de preparação.')
            found=query.listing({'area':area,'version':str(gen['id']),'selected':[key]},conn=c)['rows']
            if len(found)!=1:raise planning.PlanningError('Linha não encontrada.',409)
            row=found[0]
            if not incremental.can_edit_orders(gen,source_fingerprint,[row['values']['of']]):raise planning.PlanningError('As fontes mudaram. Atualiza a lista antes de guardar.',409)
            orders.add(row['values']['of'])
            if e.get('expected_revision')!=row['revision']:raise planning.PlanningError('A linha mudou. Reabre-a para comparar.',409)
            nid=row['need_id'];revision=row['revision']
            if not nid:
                resolution=needs.resolve({'request_id':str(uuid.uuid5(needs.uid(p['request_id']),str(i)+'resolve')),'area':area,'source':{'kind':'plan_line','id':row['plan_key'],'version':row.get('calculation',{}).get('macro_snapshot') or gen['metadata']['snapshot']['snapshot_id']},'_allow_unresolved':free.enabled()},conn=c)
                if resolution.get('needs_decision'):raise planning.PlanningError('Existem peças semelhantes. Abre o formulário e escolhe a associação.',409)
                nid=resolution['need_id'];revision=resolution['revision']
            if free.enabled():
                from .. import planning_local_orders
                administrative={k:v for k,v in changes.items() if k in planning_local_orders.FIELDS}
                if administrative:
                    of=row['values']['of']
                    saved_context=planning_local_orders.save(c,of,{'values':administrative,'expected_revision':local_revisions.get(of,row.get('local_order_revision',0))},needs.registration.human_actor(p))
                    local_revisions[of]=saved_context['revision']
            defaults={k:v for k,v in row['values'].items() if k in {f['id'] for f in cat['fields']}}
            result=needs.save({'request_id':str(uuid.uuid5(needs.uid(p['request_id']),str(i)+'save')),'area':area,'need_id':nid,'expected_revision':revision,'catalog_version':cat['version'],'record_status':'draft','values':changes,
                'decisions':{'picking_week':'clear'} if 'picking_week' in changes and changes['picking_week'] in (None,'') else {}},conn=c,source_defaults=defaults)
            results.append(result)
        projection.signal(c,'planning:'+area)
        published=incremental.publish(c,before,orders,[r['need_id'] for r in results],p['request_id'])
        return needs.finish(c,p,{'items':results,'publication':published})


def contracts_for(area):
    from .contracts import fields
    return fields(area)
