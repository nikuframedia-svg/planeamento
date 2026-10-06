"""Read-only what-if calculation from server facts, never client production totals."""
from copy import deepcopy
from datetime import datetime, timezone
from .. import planning, planning_needs as needs, planning_catalogs as catalogs
from .. import planning_associations as associations, planning_dates
from ..dossiers.models import order_number
from . import projection, calculations, productivity, contracts, capacity_preview


def preview(payload):
    allowed={'area','production_order_no','need_id','expected_revision','source','values','catalog_version','local_order','decisions'}
    if set(payload)-allowed:raise planning.PlanningError('A pré-visualização aceita apenas os dados de preparação e a identidade da origem.')
    area=planning.check_area(payload.get('area'))
    raw=dict(payload.get('values') or {})
    if set(raw)-{f['id'] for f in catalogs.fields()}:raise planning.PlanningError('A produção e os resultados calculados são obtidos pelo servidor.')
    from . import registration as free
    if not free.enabled():raw.pop('quantity_to_plan',None)
    decisions=payload.get('decisions') or {}
    if not isinstance(decisions,dict) or any(v not in ('write','select','accept','clear') for v in decisions.values()):
        raise planning.PlanningError('Decisões de preparação inválidas.')
    with planning.connect(readonly=True) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        cat=catalogs.catalog(area,conn)
        if payload.get('catalog_version')!=cat['version']:raise planning.PlanningError('O catálogo mudou. Atualiza as opções antes de calcular.',409)
        src=needs.source_data(payload.get('source'),area,conn) if payload.get('source') else None
        need=needs.load(conn,payload['need_id'],payload.get('expected_revision')) if payload.get('need_id') else None
        of=need['production_order_no'] if need else order_number(src['of'] if src else payload.get('production_order_no'))
        if not of:raise planning.PlanningError('Indica uma OF válida para calcular a peça.')
        if src and order_number(src['of'])!=of:raise planning.PlanningError('A origem pertence a outra OF.',409)
        rows,_,meta=projection.build_rows(conn,area,orders=[of])
        base=next((r for r in rows if need and r['need_id']==str(need['id'])),None)
        if base is None and src and src['kind']=='plan_line':base=next((r for r in rows if r['plan_key']==src['id']),None)
        if need is None and base is None and not src:
            proposed={**raw}
            matches=[r for r in rows if needs.complete(proposed) and needs.signature(r['values'])==needs.signature(proposed)
                and planning._number(r['values'].get('quantity_required'))==planning._number(proposed.get('quantity_required'))]
            if len(matches)==1:base=matches[0]
            else:
                similar=[r for r in rows if catalogs.key(r['values'].get('component_ref'))==catalogs.key(proposed.get('component_ref')) and proposed.get('component_ref')]
                if similar:return needs.serial({'needs_decision':True,'reason':'Existem peças semelhantes. Escolhe a associação ao guardar antes de usar os saldos.',
                    'candidates':[{'key':r['key'],'values':r['values']} for r in similar],'preview':True})
        if base and base.get('need_id') and need is None:need=needs.load(conn,base['need_id'])
        if base is None:
            base={'key':str(need['id']) if need else 'preview','need_id':str(need['id']) if need else 'preview',
                'area':area,'revision':need['revision'] if need else 0,'plan_key':None,
                'values':{**(src['values'] if src else {}),**(need['specification'] if need else {}),'of':of},
                'original':{},'raw':{},'operations':[],'preparations':[],
                'sources':needs.linked_sources(conn,need['id']) if need else ([{'kind':src['kind'],'payload':src}] if src else []),
                'warnings':[],'calculation':{'rules':{}}}
            from .. import planning_hub, planning_population
            try:context,_=planning_hub._context_for_order(conn,of)
            except planning.PlanningError as exc:
                if exc.status!=404:raise
                context={}
            base['status']=context.get('cpis_status');base['status_values']=context.get('status_values',[])
            base['values']['status']=base['status'];planning_population.annotate(base)
        row=deepcopy(base)
        if free.enabled():row['input_values']={**row.get('input_values',{}),**raw}
        op=str(raw.get('operation') or row['values'].get('operation') or ('corte' if area=='perfis' else 'por_definir'))
        previous_preparation=next((r for r in row['preparations'] if r['values_json'].get('operation')==op),None)
        previous={**row['values'],**(previous_preparation['values_json'] if previous_preparation else {}),**(need['specification'] if need else {})}
        if op=='por_definir':cat['operations'].append({'value':op,'label':'Por definir','countable':False,'sequence':1})
        if op=='abocardar' and previous_preparation:cat['operations'].append({'value':op,'label':'Abocardar','countable':True,'sequence':2})
        vals=(free.normalize({**raw,'operation':op},cat,previous)[0] if free.enabled() else catalogs.validate({**raw,'operation':op},cat,previous=previous))
        technical_changed=bool(need and any(need['specification'].get(k)!=vals.get(k) for k in needs.TECH_FIELDS))
        if need and technical_changed:
            hypothetical={**need,'specification':{k:vals.get(k) for k in needs.PIECE_FIELDS},
                'quantity_required':vals.get('quantity_required'),'technical_revision':need['technical_revision']+1}
            # Associations are checked against the proposed technical revision.
            row['operations']=[]
            for operation in conn.execute('SELECT * FROM planning_mtg.need_operations WHERE need_id=%s AND area=%s',(need['id'],area)):
                proof=associations.evidence(conn,hypothetical,operation)
                evidence={'operation':operation['code'],'ocr_records':proof['ocr_records'],
                    'ocr_quantity':proof['ocr_quantity'],'coverage_reasons':proof['warnings']}
                # Some imported counters are normalized in the source table
                # rather than stored in the display cell. Preserve that same
                # scoped fact when simulating a technical revision.
                if len(proof['macro'])==1:evidence['macro_quantity']=proof['macro'][0]['quantity']
                row['operations'].append(evidence)
            row['calculation']['historical_compatible']=False
        preparation={**(previous_preparation or {}),'values_json':vals,'record_status':'draft',
            'operation_id':previous_preparation['operation_id'] if previous_preparation else 'preview:'+op}
        row['preparations']=[r for r in row['preparations'] if r['values_json'].get('operation')!=op]+[preparation]
        # Same common fields for every operation; the selected operation keeps its own scheduling.
        primary='corte' if area=='perfis' else base['values'].get('operation')
        if primary and op!=primary and base['preparations']:
            row['values'].update({k:vals.get(k) for k in needs.PIECE_FIELDS})
        else:row['values'].update(vals)
        if area=='perfis':
            override=None
            if 'picking_week' in raw and (decisions.get('picking_week') or planning_dates.positive_week(raw['picking_week'])):
                override=(raw['picking_week'],decisions.get('picking_week'))
            row['values'].update(planning_dates.picking_values(of,row['raw'].get('Picking'),
                cat['picking'],cat.get('picking_evidence') or {},record=previous_preparation,override=override))
        local=(payload.get('local_order') or {}).get('values') or {}
        if not row['values'].get('delivery_date'):row['values']['delivery_date']=local.get('delivery_date')
        snap=meta['snapshot']['snapshot_id']
        calculations.recalculate(row,calculations.sections(conn,snap),calculations.weights(conn,snap))
        configs=conn.execute("SELECT * FROM planning_mtg.raw_objects WHERE kind IN ('resource','calendar','rate','period','worked_hours') AND NOT archived").fetchall()
        productivity.apply_rows(conn,area,[row],configs,persist=False)
        simulated=capacity_preview.apply(conn,area,row,base,configs)
        for item in simulated.get('items',[]):item['applied_rate'].pop('history_hash',None)
        # Only committed evidence has a retrievable content hash. The preview is not published.
        for estimate in row['calculation'].get('operation_estimates',[]):estimate.pop('history_hash',None)
        if 'theoretical_hours' in row['calculation']['rules']:row['calculation']['rules']['theoretical_hours'].pop('history_hash',None)
        fields=contracts.mapping(area)
        results=[{'field':name,'label':fields[name]['label'],'unit':fields[name].get('unit'),
            'value':row['values'].get(name),'source':rule.get('source'),'reason':rule.get('reason')}
            for name,rule in row['calculation']['rules'].items() if name in fields]
        return needs.serial({'preview':True,'saved':False,'results':results,'need_revision':need['revision'] if need else None,
            'calculated_at':datetime.now(timezone.utc),'source':meta,'row':row,'capacity_preview':simulated})
