"""Atomic common registration and table batches; only local preparation is written."""
from contextlib import nullcontext
import uuid
from .. import planning,planning_needs as needs,planning_catalogs as catalogs
from ..dossiers.models import order_number
from . import query,projection,incremental,registration as free


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


@incremental.retry_serialization
def prepare(p):
    try:
        with planning.connect() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            _,_,old=needs.command(c,p)
            if old:return old
            before=incremental.baseline(c)
            area=planning.check_area(p.get('area'));src=needs.source_data(p.get('source'),area,c) if p.get('source') else None
            values={**(src['values'] if src else {}),**(p.get('values') or {})};of=order_number(src['of'] if src else p.get('production_order_no'))
            nid=p.get('need_id');revision=p.get('expected_revision');chosen=None
            if src and p.get('production_order_no') and order_number(p['production_order_no'])!=of:raise planning.PlanningError('A OF do documento difere da OF selecionada. Confirma qual a ordem a utilizar.',409)
            if nid and src:
                linked=needs.resolve({'request_id':str(uuid.uuid5(needs.uid(p['request_id']),'link')),'area':area,'source':p['source'],'need_id':nid,'expected_revision':revision,'reason':p.get('reason') or 'Reabertura da origem já associada.'},conn=c)
                if linked.get('needs_decision'):raise Candidates(linked)
                if str(linked['need_id'])!=str(nid):raise planning.PlanningError('O documento já está associado a outra peça. Reabre a origem.',409)
                revision=linked['revision']
            if not nid:
                if not of:raise planning.PlanningError('Seleciona uma OF válida.')
                possible=macro_candidates(c,area,of,values) if not src or src['kind']!='plan_line' else []
                matches=[r for r in possible if r['exact'] and r['same_quantity']]
                chosen=next((r for r in possible if r['plan_key']==p.get('selected_plan_key')),None)
                if p.get('selected_plan_key') and not chosen:raise planning.PlanningError('A linha escolhida mudou. Atualiza as candidatas.',409)
                if chosen and not free.enabled() and not str(p.get('reason') or '').strip():raise planning.PlanningError('Justifica a associação à linha escolhida.')
                if not chosen and len(matches)==1:chosen=matches[0]
                elif not chosen and possible and not p.get('create_distinct') and not free.enabled():
                    raise Candidates({'needs_decision':True,'candidates':possible,'suggestion':values,'production_order_no':of})
                if not free.enabled() and p.get('create_distinct') and possible and (not values.get('identity_discriminator') or not p.get('reason')):raise planning.PlanningError('Identifica o que distingue a peça e justifica a necessidade adicional.')
                resolution={k:p[k] for k in ('area','production_order_no','source','reason','create_distinct') if k in p}
                resolution.update(_allow_unresolved=free.enabled(),values=values,request_id=str(uuid.uuid5(needs.uid(p['request_id']),'resolve')))
                result=needs.resolve(resolution,conn=c)
                if result.get('needs_decision'):raise Candidates(result)
                nid=result['need_id'];revision=result['revision']
                if free.enabled() and possible and not chosen:
                    from psycopg.types.json import Jsonb
                    c.execute('UPDATE planning_mtg.needs SET identity_pending=true,identity_candidates=identity_candidates || %s WHERE id=%s',
                        (Jsonb([{'kind':'plan_line','id':r['plan_key'],'version':r['source_version']} for r in possible]),nid))
            if chosen:
                result=needs.resolve({'request_id':str(uuid.uuid5(needs.uid(p['request_id']),'macro')),'area':area,'source':{'kind':'plan_line','id':chosen['plan_key'],'version':chosen['source_version']},'need_id':nid,'expected_revision':revision,'reason':p.get('reason') or 'Correspondência técnica completa, única e com a mesma quantidade.'},conn=c)
                revision=result['revision']
            save_values=dict(p.get('values') or {})
            if src:
                for f in c.execute('SELECT * FROM planning_mtg.field_state WHERE need_id=%s',(nid,)).fetchall():
                    if f['field'] in save_values and f['field'] not in (p.get('decisions') or {}) and f.get('human_decision'):save_values[f['field']]=f['value']
            result=needs.save({**p,'values':save_values,'request_id':str(uuid.uuid5(needs.uid(p['request_id']),'save')),'need_id':nid,'expected_revision':revision},conn=c)
            if p.get('local_order') is not None:
                from .. import planning_local_orders
                need=needs.load(c,nid)
                context=planning_local_orders.save(c,need['production_order_no'],p['local_order'],needs.registration.human_actor(p))
                result['local_order']=needs.serial(context)
            projection.signal(c,'planning:'+area)
            published=incremental.publish(c,before,[needs.load(c,nid)['production_order_no']],[nid],p['request_id'])
            return needs.finish(c,p,{**result,'publication':published,'raw_url':'/planeamento/raw?area='+area+'&need='+str(nid)})
    except Candidates as exc:return exc.result


@incremental.retry_serialization
def update_batch(p):
    """Grava um lote da Tabela. Uma importação entretanto já não recusa o lote (07/10/2026): cada linha é procurada
    na versão atual e grava-se se a sua revisão não mudou; as outras ficam de fora e voltam em `skipped`.
    Só quando nenhuma linha se pode gravar é que o pedido é recusado (409)."""
    edits=p.get('edits')
    if not isinstance(edits,list) or not 1<=len(edits)<=500 or any(not isinstance(e,dict) for e in edits):raise planning.PlanningError('O lote deve conter entre 1 e 500 linhas.')
    area=planning.check_area(p.get('area','perfis'))
    with planning.connect() as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        _,_,old=needs.command(c,p)
        if old:return old
        before=incremental.baseline(c)
        gen=query.generation(c,area)
        source_fingerprint=projection.fingerprint(c,area)
        cat=catalogs.catalog(area,c);allowed={f['id'] for f in contracts_for(area) if f['editable']}|{'picking_year','custom_profile','special_profile','geometry','identity_discriminator'}
        results=[];skipped=[];seen=set();orders=set();local_revisions={}
        def skip(key,row,reason):
            values=(row or {}).get('values') or {}
            skipped.append({'key':key,'of':values.get('of'),'component_ref':values.get('component_ref'),'reason':reason})
        for i,e in enumerate(edits):
            key=e.get('key');changes=e.get('values') or {}
            if key in seen:raise planning.PlanningError('Agrupa as alterações da mesma linha num único pedido.')
            seen.add(key)
            if not changes or not isinstance(changes,dict) or set(changes)-allowed:raise planning.PlanningError('Só podes alterar campos locais de preparação.')
            found=query.listing({'area':area,'version':str(gen['id']),'selected':[key]},conn=c)['rows']
            if len(found)!=1:
                skip(key,None,'Linha não encontrada.');continue
            row=found[0]
            if not incremental.can_edit_orders(gen,source_fingerprint,[row['values']['of']]):
                skip(key,row,'As fontes mudaram.');continue
            if e.get('expected_revision')!=row['revision']:
                skip(key,row,'A linha mudou entretanto.');continue
            nid=row['need_id'];revision=row['revision']
            if not nid:
                resolution=needs.resolve({'request_id':str(uuid.uuid5(needs.uid(p['request_id']),str(i)+'resolve')),'area':area,'source':{'kind':'plan_line','id':row['plan_key'],'version':row.get('calculation',{}).get('macro_snapshot') or gen['metadata']['snapshot']['snapshot_id']},'_allow_unresolved':free.enabled()},conn=c)
                if resolution.get('needs_decision'):raise planning.PlanningError('Existem peças semelhantes. Abre o formulário e escolhe a associação.',409)
                nid=resolution['need_id'];revision=resolution['revision']
            orders.add(row['values']['of'])
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
        if not results:  # nada a gravar: erro como antes (também para os ecrãs que ainda não leem `skipped`)
            raise planning.PlanningError('Nenhuma linha gravada: '+' '.join(dict.fromkeys(x['reason'] for x in skipped))+' Atualiza a lista e cola outra vez.',409)
        projection.signal(c,'planning:'+area)
        published=incremental.publish(c,before,orders,[r['need_id'] for r in results],p['request_id'])
        return needs.finish(c,p,{'items':results,'skipped':skipped,'publication':published})


def contracts_for(area):
    from .contracts import fields
    return fields(area)
