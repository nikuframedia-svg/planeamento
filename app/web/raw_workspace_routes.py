"""HTTP boundary for the versioned RAW workspace."""
from fastapi import APIRouter,Request,Depends,HTTPException
from fastapi.responses import Response
from .need_routes import call,write
from .. import planning,planning_needs as needs
from ..raw import query,contracts,objects,edits,analysis,capacity,exports,capacity_views,workbooks
import os

def enabled():
    if os.getenv('MES_RAW_WORKSPACE_ENABLED')!='1':raise HTTPException(404,'Workspace RAW desativado.')
router=APIRouter(dependencies=[Depends(enabled)])

@router.post('/planeamento/api/raw/consultas')
async def rows(request:Request):return await write(request,query.listing)
@router.post('/planeamento/api/raw/opcoes')
async def options(request:Request):return await write(request,query.options)
@router.post('/planeamento/api/raw/lotes')
async def batch(request:Request):return await write(request,edits.update_batch)
@router.get('/planeamento/api/raw/objects/{kind}')
def objects_list(kind:str,area:str|None=None):return call(objects.listing,kind,area)
@router.post('/planeamento/api/raw/objects/{kind}')
async def object_save(kind:str,request:Request):
    if kind not in ('view','formula','format','resource','calendar','rate','period','worked_hours'):raise HTTPException(422,'Usa o percurso de proposta e confirmação para as análises.')
    return await write(request,lambda p:objects.save(p,kind))
@router.get('/planeamento/api/raw/objects/{id}/historico')
def object_history(id:str):return call(objects.history,id)
@router.get('/planeamento/api/raw/capacidade/fontes')
def capacity_sources():return call(capacity.sources)
@router.post('/planeamento/api/raw/capacidade/copiar')
async def capacity_copy(request:Request):return await write(request,capacity.copy_calendar)

@router.post('/planeamento/api/raw/capacidade/calendario/preview')
async def calendar_preview(request:Request):
    def preview(payload):
        from .. import planning_calendars
        try:
            definition=planning_calendars.validate(payload.get('definition') or {})
            if 'weekly_windows' not in definition:raise ValueError('Indica horários por dia.')
            return {'available_hours':planning_calendars.available_hours(definition),
                    'timezone':definition['timezone']}
        except (TypeError,ValueError,KeyError) as exc:
            raise planning.PlanningError(str(exc),422) from exc
    return await write(request,preview,audit=False)
@router.post('/planeamento/api/raw/chat')
async def talk(request:Request):return await write(request,analysis.talk)
@router.get('/planeamento/api/raw/conversas/{id}')
def messages(id:str):return call(analysis.messages,id)
@router.post('/planeamento/api/raw/analises/preview')
async def preview(request:Request):return await write(request,analysis.preview)
@router.post('/planeamento/api/raw/analises/confirmar')
async def confirm(request:Request):return await write(request,analysis.confirm)
@router.get('/planeamento/api/raw/jobs/{id}')
def job(id:str):return call(analysis.get_job,id)
@router.get('/planeamento/api/raw/execucoes/{id}')
def runs(id:str):return call(analysis.runs,id)
@router.post('/planeamento/api/raw/jobs/{id}/evidencia')
async def evidence(id:str,request:Request):return await write(request,lambda p:analysis.evidence(id,p))
@router.get('/planeamento/api/raw/jobs/{id}/exportar/{format}')
def export_report(id:str,format:str):
    try:
        data,mime=exports.report(id,format)
        return Response(data,media_type=mime,headers={'Content-Disposition':f'attachment; filename="analise-raw.{format}"'})
    except planning.PlanningError as exc:raise HTTPException(exc.status,str(exc))
@router.post('/planeamento/api/raw/exportar/{format}')
async def export_table(format:str,request:Request):
    # Reuse the same origin/content-type checks as all JSON operations.
    result={}
    def make(p):result['data'],result['mime']=exports.table(p,format);return {'ok':True}
    checked=await write(request,make)
    if checked.status_code>=300:return checked
    return Response(result['data'],media_type=result['mime'],headers={'Content-Disposition':f'attachment; filename="raw.{format}"'})
@router.get('/planeamento/api/raw/workspace/atualizacao')
def available(area:str,version:str,dataset:str='planning'):
    def run():
        if dataset not in ('planning','capacity','capacity_machines'):raise planning.PlanningError('Consulta de versão desconhecida.')
        with planning.connect(readonly=True) as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            g=query.generation(c,area,dataset=dataset)
            source=g if dataset=='planning' else query.generation(c,area)
        pending=bool(source['metadata'].get('aggregates_pending') or source['metadata'].get('source_refresh_pending'))
        return {'available':str(g['id'])!=version,'version':str(g['id']),'pending':pending}
    return call(run)

@router.post('/planeamento/api/raw/jobs/repetir')
async def retry_job(request:Request):return await write(request,analysis.retry)

@router.get('/planeamento/api/raw/capacidade/propostas')
def capacity_proposals():return call(capacity_views.proposals)

@router.post('/planeamento/api/raw/formulas/preview')
async def formula_preview(request:Request):return await write(request,objects.preview_formula)


@router.get('/planeamento/api/raw/workspace/fontes')
def workspace_sources():
    def run():
        with planning.connect(readonly=True) as c:
            return needs.serial({'sources':c.execute("SELECT *, confirmed_at IS NULL OR confirmed_at<now()-interval '3 minutes' AS stale FROM planning_mtg.raw_worker_state ORDER BY source").fetchall()})
    return call(run)

@router.post('/planeamento/api/raw/analises/estado')
async def analysis_state(request:Request):return await write(request,analysis.set_active)


@router.post('/planeamento/api/raw/capacidade/consulta')
async def capacity_query(request:Request):return await write(request,capacity_views.overview)
@router.post('/planeamento/api/raw/capacidade/pecas')
async def capacity_pieces(request:Request):return await write(request,capacity_views.pieces)
@router.post('/planeamento/api/raw/capacidade/excel')
async def capacity_excel(request:Request):return await write(request,capacity_views.evidence)
@router.get('/planeamento/api/raw/ficheiros')
def workbook_status():return call(workbooks.status)
@router.post('/planeamento/api/raw/capacidade/referencia/preview')
async def capacity_reference_preview(request:Request):return await write(request,capacity_views.reference_preview)
@router.post('/planeamento/api/raw/capacidade/referencia')
async def capacity_reference_save(request:Request):return await write(request,capacity_views.save_reference)
@router.get('/planeamento/api/raw/capacidade/referencias')
def capacity_references(area:str='perfis'):return call(capacity_views.references,area)
@router.post('/planeamento/api/raw/capacidade/cumprimento')
async def capacity_compliance(request:Request):return await write(request,capacity_views.compliance)


@router.post('/planeamento/api/raw/horas/prever')
async def worked_hours_preview(request:Request):
    from ..raw.worked_hours import preview
    return await write(request,preview)

@router.get('/planeamento/api/raw/horas/folhas')
def worked_hours_sheets():
    from ..raw.worked_hours import observations
    with planning.connect(readonly=True) as c:
        return needs.serial({'sheets':observations(c)})


@router.get('/planeamento/api/raw/produtividade/{digest}')
def productivity_evidence(digest:str):
    from ..raw.productivity import evidence
    return call(evidence,digest)


def gantt_enabled():
    if os.getenv('MES_PLANNING_GANTT_ENABLED', '0') != '1':
        raise HTTPException(404, 'Gantt desativado.')


@router.get('/planeamento/api/raw/gantt/operations')
def gantt_operations(scenario_id:str|None=None, area:str|None=None):
    gantt_enabled()
    from ..gantt import service
    return call(service.operations,scenario_id,area)


@router.get('/planeamento/api/raw/gantt/options')
def gantt_options(key:str, scenario_id:str|None=None):
    gantt_enabled()
    from ..gantt import service
    return call(service.options,key,scenario_id)


@router.get('/planeamento/api/raw/gantt/scenarios')
def gantt_scenarios():
    gantt_enabled()
    from ..gantt import service
    return call(service.scenarios)


@router.post('/planeamento/api/raw/gantt/rules')
async def gantt_rule(request:Request):
    gantt_enabled()
    from ..gantt import service
    return await write(request,service.confirm_rule)


@router.post('/planeamento/api/raw/gantt/scenarios')
async def gantt_save(request:Request):
    gantt_enabled()
    from ..gantt import service
    return await write(request,service.save)


@router.post('/planeamento/api/raw/gantt/solve')
async def gantt_solve(request:Request):
    gantt_enabled()
    from ..gantt import service
    return await write(request,service.solve)


@router.get('/planeamento/api/raw/gantt/jobs/{id}')
def gantt_job(id:str):
    gantt_enabled()
    from ..gantt import service
    return call(service.job,id)


@router.post('/planeamento/api/raw/gantt/accept')
async def gantt_accept(request:Request):
    gantt_enabled()
    from ..gantt import service
    return await write(request,service.accept)
