"""Página HTML de preparação de planeamento e API com persistência PostgreSQL."""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates

from .. import planning, planning_hub

router = APIRouter()
_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(_DIR / "templates"))
templates.env.globals['raw_enabled'] = lambda: os.getenv('MES_PLANNING_RAW_ENABLED','0') == '1'
log = logging.getLogger(__name__)


@router.get("/planeamento", response_class=HTMLResponse)
def hub_page(request: Request):
    version = hashlib.sha256((_DIR / "static" / "planning_hub.js").read_bytes()
                             + (_DIR / "static" / "planning_hub.css").read_bytes()).hexdigest()[:10]
    return templates.TemplateResponse(request=request, name="planning_hub.html",
        context={"version": version, "population_contract": 1})


def _call(function, *args, **kwargs):
    try:
        return JSONResponse(function(*args, **kwargs), headers={"Cache-Control": "no-store"})
    except planning.PlanningError as exc:
        return JSONResponse({"error": str(exc), "fields": getattr(exc, "fields", {})}, status_code=exc.status)
    except psycopg.Error:
        log.exception("Ligação de planeamento indisponível")
        return JSONResponse({"error": "Não foi possível aceder aos dados de planeamento. Tenta novamente."}, status_code=503)


@router.get("/planeamento/manual", response_class=HTMLResponse)
def page(request: Request):
    from .need_routes import enabled, editor
    if enabled():
        return editor(request)
    version = hashlib.sha256((_DIR / "static" / "planning.js").read_bytes()
                             + (_DIR / "static" / "planning.css").read_bytes()).hexdigest()[:10]
    return templates.TemplateResponse(request=request, name="planning.html", context={"version": version})


@router.get("/planeamento/api/contexto")
def context(area: str = "perfis"):
    return _call(planning.bootstrap, area)


@router.get("/planeamento/api/fontes")
def sources():
    return _call(planning_hub.source_status)


@router.get("/planeamento/api/ordens")
def hub_orders(q: str = "", pagina: int = 1, tamanho: int = 50,
               estado: str = "all", versao: str | None = None,
               por_fazer: bool = False, populacao: str = "active"):
    return _call(planning_hub.list_orders, query=q, page=pagina, page_size=tamanho,
                 state=estado, version=versao, pending_only=por_fazer, population=populacao)


@router.get("/planeamento/api/ordens/{of}")
def hub_order(of: str, versao: str | None = None):
    return _call(planning_hub.order_detail, of, version=versao)


@router.get("/planeamento/api/catalogos")
def catalogs(area: str = "perfis", contrato: int = 1):
    from .need_routes import enabled
    from ..planning_catalogs import catalog
    return _call(catalog if contrato >= 2 or enabled() else planning.bootstrap, area)


@router.post("/planeamento/api/conferencias")
async def reconcile_production(request: Request):
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        return JSONResponse({"error": "Formato de conferência inválido."}, status_code=415)
    try:
        data = json.loads(await request.body())
    except (ValueError, UnicodeDecodeError):
        return JSONResponse({"error": "A conferência não contém dados válidos."}, status_code=400)
    from starlette.concurrency import run_in_threadpool
    from .. import planning_associations
    handler = planning_associations.confer if data.get("need_id") else planning_hub.save_reconciliation
    return await run_in_threadpool(_call, handler, data)


@router.post("/planeamento/api/saida-propostas")
async def output_proposal(request: Request):
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        return JSONResponse({"error": "Formato de proposta inválido."}, status_code=415)
    try:
        data = json.loads(await request.body())
    except (ValueError, UnicodeDecodeError):
        return JSONResponse({"error": "A proposta não contém dados válidos."}, status_code=400)
    from .. import planning_output
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(_call, planning_output.create_proposal, data)


@router.get("/planeamento/api/saida-planeamento.xlsm")
def output_download(proposta: str, assinatura: str):
    from .. import planning_output
    try:
        data = planning_output.generate(proposta, assinatura)
        return Response(data,
            media_type="application/vnd.ms-excel.sheet.macroEnabled.12",
            headers={"Content-Disposition": 'attachment; filename="Planeamento_preenchido.xlsm"',
                     "Cache-Control": "no-store"})
    except planning.PlanningError as exc:
        return JSONResponse({"error": str(exc), "fields": getattr(exc, "fields", {})}, status_code=exc.status)
    except psycopg.Error:
        log.exception("Ligação de planeamento indisponível")
        return JSONResponse({"error": "Não foi possível aceder aos dados de planeamento. Tenta novamente."}, status_code=503)


@router.get("/planeamento/api/ofs")
def orders(area: str = "perfis", q: str = ""):
    return _call(planning.search_orders, area, q)


@router.get("/planeamento/api/linhas")
def lines(area: str, of: str, populacao: str = "active"):
    return _call(planning.order_lines, area, of, population=populacao)


@router.get("/planeamento/api/registos")
def records(area: str = "perfis"):
    return _call(planning.list_records, area)


@router.get("/planeamento/api/registos/{record_id}")
def record(record_id: str):
    return _call(planning.get_record, record_id)


@router.get("/planeamento/api/registos/{record_id}/origem")
def source(record_id: str):
    return _call(planning.refresh_source, record_id)


@router.post("/planeamento/api/registos")
async def save(request: Request):
    # JSON e origem igual impedem posts de formulários de outro site.
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        return JSONResponse({"error": "Formato de registo inválido."}, status_code=415)
    origin = request.headers.get("origin")
    if origin and (urlsplit(origin).scheme, urlsplit(origin).netloc) != (request.url.scheme, request.url.netloc):
        return JSONResponse({"error": "Reabre o formulário a partir desta aplicação."}, status_code=403)
    body = await request.body()
    if len(body) > 64_000:
        return JSONResponse({"error": "A ficha ultrapassa o tamanho permitido."}, status_code=413)
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return JSONResponse({"error": "O pedido não contém uma ficha válida."}, status_code=400)
    # O código PostgreSQL síncrono corre numa thread, sem bloquear o servidor.
    from starlette.concurrency import run_in_threadpool
    from .need_routes import enabled
    from ..planning_needs import save_legacy_payload
    return await run_in_threadpool(_call, save_legacy_payload if enabled() else planning.save_record, payload)


from .dossier_routes import router as dossier_router
router.include_router(dossier_router)

from .need_routes import router as need_router
router.include_router(need_router)

from .raw_routes import router as raw_router
router.include_router(raw_router)
