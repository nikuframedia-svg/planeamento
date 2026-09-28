"""HTTP adapters for common preparation; business rules live in services."""
import json
import hashlib
import os
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from .. import planning, planning_needs as needs, planning_catalogs as catalogs, planning_associations as associations

router=APIRouter()
templates=Jinja2Templates(directory=str(Path(__file__).parent/'templates'))


def enabled():return os.environ.get('MES_PLANNING_NEEDS_ENABLED','0')=='1'


def call(fn,*args,**kwargs):
    from .planning_routes import _call
    return _call(fn,*args,**kwargs)


async def write(request,fn,*,audit=True):
    origin=request.headers.get('origin')
    if origin and (urlsplit(origin).scheme,urlsplit(origin).netloc)!=(request.url.scheme,request.url.netloc):return JSONResponse({'error':'Reabre esta ação a partir da aplicação.'},403)
    if request.headers.get('content-type','').split(';')[0]!='application/json':return JSONResponse({'error':'Envia os dados em JSON.'},415)
    body=await request.body()
    if len(body)>256000:return JSONResponse({'error':'Pedido demasiado grande.'},413)
    try:payload=json.loads(body,parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    except (ValueError,UnicodeDecodeError):return JSONResponse({'error':'JSON inválido.'},400)
    if not isinstance(payload,dict):return JSONResponse({'error':'Pedido inválido.'},422)
    for key,kind in (('values',dict),('source',dict),('decisions',dict),('allocations',list)):
        if payload.get(key) is not None and not isinstance(payload[key],kind):return JSONResponse({'error':'Formato inválido: '+key},422)
    if any(not isinstance(a,dict) for a in payload.get('allocations',[])):return JSONResponse({'error':'Distribuição inválida.'},422)
    response=await run_in_threadpool(call,fn,payload)
    if audit and response.status_code<300:
        try:await run_in_threadpool(needs.deliver_outbox)
        except Exception:
            import logging
            logging.getLogger(__name__).exception('Auditoria documental pendente; decisão central preservada')
    return response


@router.get('/planeamento/preparar',response_class=HTMLResponse)
def editor(request:Request):
    version=hashlib.sha256((Path(__file__).parent/'static/need_editor.js').read_bytes()+(Path(__file__).parent/'static/need_editor.css').read_bytes()).hexdigest()[:12]
    return templates.TemplateResponse(request=request,name='need_editor.html',context={'version':version,'field_contract':catalogs.fields()})


@router.get('/planeamento/api/ordens/{of}/registo')
def order_registration(of:str):
    from .. import planning_registration
    return call(lambda: {'registration':planning_registration.read(of)})


@router.get('/planeamento/api/necessidades/lista')
def listing(of:str|None=None,populacao:str='active',area:str|None=None):
    return call(needs.list_needs,of,population=populacao,area=area)


@router.get('/planeamento/api/necessidades/por-origem')
def by_pdf(document:str,piece:str):return call(needs.need_for_pdf,document,piece)


@router.post('/planeamento/api/necessidades/resolver')
async def resolve(request:Request):return await write(request,needs.resolve)


@router.get('/planeamento/api/necessidades/{need_id}/historico')
def history(need_id:str):return call(needs.history,need_id)


@router.get('/planeamento/api/necessidades/{need_id}/evidencia')
def evidence(need_id:str,operacao:str):return call(associations.get_evidence,need_id,operacao)


@router.get('/planeamento/api/necessidades/{need_id}')
def detail(need_id:str):return call(needs.detail,need_id)


@router.post('/planeamento/api/necessidades/prever')
async def preview_preparation(request:Request):
    from ..raw.preview import preview
    return await write(request,preview,audit=False)


@router.post('/planeamento/api/necessidades/preparacoes')
async def save(request:Request):return await write(request,needs.save)


@router.get('/planeamento/api/producao/pendencias')
def pending(of:str|None=None,area:str|None=None,pagina:int=1,estado:str='pending',motivo:str|None=None,incluir_sem_of:bool=False):return call(associations.pending,of,area,pagina,estado,motivo,incluir_sem_of)


@router.post('/planeamento/api/associacoes')
async def associate(request:Request):return await write(request,associations.save)


@router.get('/planeamento/ocr-original',response_class=HTMLResponse)
def original_page(request:Request):
    return templates.TemplateResponse(request=request,name='ocr_original.html',context={})


@router.get('/planeamento/api/ocr-original/registos')
def original_rows(of:str='',modelo:str='',maquina:str='',data_de:str='',data_ate:str='',pagina:int=1):
    from .. import original_ocr
    return call(original_ocr.query,of=of,model=modelo,machine=maquina,date_from=data_de,date_to=data_ate,page=pagina)


@router.get('/planeamento/api/saida-planeamento.csv')
def output_csv(proposta:str,assinatura:str):
    from fastapi.responses import Response
    from .. import planning_output
    try:return Response(planning_output.generate_csv(proposta,assinatura),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="Planeamento_preenchido.csv"'})
    except planning.PlanningError as exc:return JSONResponse({'error':str(exc)},exc.status)

@router.post('/planeamento/api/necessidades/registar')
async def register_atomic(request:Request):
    from ..raw.edits import prepare
    return await write(request,prepare)
