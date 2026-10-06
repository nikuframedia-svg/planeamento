"""RAW HTTP adapters. Existing JSON-origin checks also protect local decisions."""
import os
import json
from pathlib import Path
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from .templates_env import install
from psycopg.types.json import Jsonb
from .. import planning, planning_raw as raw, planning_raw_analysis as analysis, planning_needs as needs
from .need_routes import write, call


def enabled():
    if os.getenv('MES_PLANNING_RAW_ENABLED','0')!='1':raise HTTPException(404,'Vista RAW desativada.')
router=APIRouter(dependencies=[Depends(enabled)])
templates=install(Jinja2Templates(directory=str(Path(__file__).parent/'templates')))

@router.get('/planeamento/raw',response_class=HTMLResponse)
def page(request:Request):return templates.TemplateResponse(request=request,name='raw_workspace.html' if os.getenv('MES_RAW_WORKSPACE_ENABLED')=='1' else 'planning_raw.html',context={})

@router.get('/planeamento/api/raw/colunas')
def columns(area:str='perfis'):
    if os.getenv('MES_RAW_WORKSPACE_ENABLED')=='1':
        from ..raw.contracts import columns as contract
        return call(contract,area)
    return call(raw.columns)

@router.get('/planeamento/api/raw/linhas')
def rows(request:Request):
    if os.getenv('MES_RAW_WORKSPACE_ENABLED')=='1':
        from ..raw.query import listing
        return call(listing,dict(request.query_params))
    return call(raw.listing,dict(request.query_params))

@router.patch('/planeamento/api/raw/linhas/{key:path}')
async def update(key:str,request:Request):return await write(request,lambda payload:raw.update(key,payload))

@router.get('/planeamento/api/raw/vistas')
def views():
    def query():
        with planning.connect(readonly=True) as conn:return needs.serial({'views':conn.execute('SELECT * FROM planning_mtg.raw_views ORDER BY name').fetchall()})
    return call(query)

@router.post('/planeamento/api/raw/vistas')
async def save_view(request:Request):
    def save(p):
        name=str(p.get('name') or '').strip();settings=p.get('settings')
        if not name or len(name)>100 or not isinstance(settings,dict):raise planning.PlanningError('Indica um nome e as opções da vista.')
        if len(json.dumps(settings))>16000:raise planning.PlanningError('Vista demasiado grande.')
        with planning.connect() as conn:
            _,_,old=needs.command(conn,p)
            if old:return old
            id=needs.uid(p.get('id') or p['request_id']);prior=conn.execute('SELECT revision FROM planning_mtg.raw_views WHERE id=%s',(id,)).fetchone()
            if prior and p.get('expected_revision')!=prior['revision']:raise planning.PlanningError('A vista mudou. Reabre-a.',409)
            conn.execute('INSERT INTO planning_mtg.raw_views(id,name,settings) VALUES(%s,%s,%s) ON CONFLICT(id) DO UPDATE SET name=excluded.name,settings=excluded.settings,revision=raw_views.revision+1,updated_at=now()',(id,name,Jsonb(settings)))
            return needs.finish(conn,p,{'id':str(id)})
    return await write(request,save)

@router.post('/planeamento/api/raw/analises')
async def start(request:Request):return await write(request,analysis.create)

@router.get('/planeamento/api/raw/analises')
def saved():return call(lambda:{'analyses':analysis.saved()})

@router.post('/planeamento/api/raw/analises/guardar')
async def save_analysis(request:Request):return await write(request,analysis.save)

@router.get('/planeamento/api/raw/analises/{id}')
def report(id:str):return call(lambda:analysis.public_report(analysis.get(id)))

@router.get('/planeamento/api/raw/analises/{id}/html')
def report_html(id:str,download:bool=False):
    try:
        content=analysis.render(analysis.get(id))
        return HTMLResponse(content,headers={'Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; sandbox",**({'Content-Disposition':'attachment; filename="analise-raw.html"'} if download else {})})
    except planning.PlanningError as exc:raise HTTPException(exc.status,str(exc))

@router.get('/planeamento/api/raw/analises/{id}/json')
def report_json(id:str):
    data=analysis.get(id)
    if data['status']!='done':raise HTTPException(409,'Aguarda a conclusão.')
    return Response(json.dumps(data,ensure_ascii=False),media_type='application/json',headers={'Content-Disposition':'attachment; filename="analise-raw.json"'})

@router.get('/planeamento/api/raw/atualizacao')
def update_available(version:str):
    return call(lambda:{'available':raw.dataset(force=True)['version']!=version})


def _load_page(request:Request,view:str|None):
    """Capacidades e Disponibilidade estão na Carga e turnos (06/10/2026). O MES partilha este ficheiro mas não
    tem o pacote sector: aí as páginas antigas continuam como estavam."""
    import importlib.util
    if importlib.util.find_spec(__package__.rsplit('.',1)[0]+'.sector') is None:return None
    from fastapi.responses import RedirectResponse
    area=request.query_params.get('area') or request.query_params.get('setor')
    area=area if area in ('perfis','cantoneiras') else 'cantoneiras'
    return RedirectResponse('/planeamento/setor/carga?setor='+area+('&vista='+view if view else ''),status_code=302)

@router.get('/planeamento/capacidades',response_class=HTMLResponse)
def machine_capacity_page(request:Request):
    moved=_load_page(request,'maquinas')
    if moved:return moved
    if os.getenv('MES_RAW_WORKSPACE_ENABLED')!='1':raise HTTPException(404,'Página desativada.')
    return templates.TemplateResponse(request=request,name='capacity.html',context={'mode':'machines','title':'Capacidades das máquinas'})

@router.get('/planeamento/disponibilidade',response_class=HTMLResponse)
def weekly_capacity_page(request:Request):
    moved=_load_page(request,None)
    if moved:return moved
    if os.getenv('MES_RAW_WORKSPACE_ENABLED')!='1':raise HTTPException(404,'Página desativada.')
    return templates.TemplateResponse(request=request,name='capacity.html',context={'mode':'weekly','title':'Disponibilidade semanal'})


def _gantt_enabled():
    if os.getenv('MES_PLANNING_GANTT_ENABLED','0')!='1' or os.getenv('MES_RAW_WORKSPACE_ENABLED')!='1':
        raise HTTPException(404,'Gantt desativado.')


@router.get('/planeamento/gantt',response_class=HTMLResponse)
def gantt_page(request:Request):
    """Quadro simples: uma linha por máquina, uma caixa por OF, e a lista vermelha das OF por planear."""
    _gantt_enabled()
    return templates.TemplateResponse(request=request,name='plano.html',context={})


@router.get('/planeamento/gantt/detalhe',response_class=HTMLResponse)
def gantt_detail_page(request:Request):
    """Ferramentas do planeador: cenários, propostas, aceitação e ajustes por operação."""
    _gantt_enabled()
    return templates.TemplateResponse(request=request,name='gantt.html',context={})
