"""Entrada por PDF e revisão pontual de necessidades MTG2."""
from __future__ import annotations

import hashlib
import hmac
import io
import json
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from .templates_env import install
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ..config import settings
from .. import planning, planning_hub
import psycopg
from ..dossiers import DossierError, macro, pdf, pipeline, provider, store, inbox

router = APIRouter()
DIR = Path(__file__).parent
templates = install(Jinja2Templates(directory=str(DIR / "templates")))


def _result(function, *args, **kwargs):
    try:
        return JSONResponse(function(*args, **kwargs), headers={"Cache-Control": "no-store"})
    except DossierError as exc:
        return JSONResponse({"error": str(exc)}, status_code=exc.status)


def _origin(request):
    origin = request.headers.get("origin")
    if origin and (urlsplit(origin).scheme, urlsplit(origin).netloc) != (request.url.scheme, request.url.netloc):
        raise DossierError("Abre esta ação a partir da aplicação de planeamento.", 403)
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise DossierError("Pedido de outra origem recusado.", 403)


def _can_configure(request):
    local = request.client and request.client.host in ("127.0.0.1", "::1", "testclient") and request.url.hostname in ("localhost", "127.0.0.1", "::1", "testserver")
    supplied = request.headers.get("x-planning-admin", "")
    return bool(local or (settings.admin_token and hmac.compare_digest(supplied, settings.admin_token)))


async def _body(request, *, admin=False):
    _origin(request)
    if admin and not _can_configure(request):
        raise DossierError("Para alterar a API, abre a aplicação neste computador ou indica o código administrativo definido no servidor.", 403)
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise DossierError("Este pedido deve conter JSON.", 415)
    data = await request.body()
    if len(data) > 64000:
        raise DossierError("O pedido é demasiado grande.", 413)
    try:
        value = json.loads(data)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, UnicodeDecodeError):
        raise DossierError("O pedido não contém dados válidos.", 400) from None


def _error(exc):
    return JSONResponse({"error": str(exc)}, status_code=exc.status)


def _public(document):
    # As credenciais nunca fazem parte do documento. O caminho do servidor é interno.
    context = document.get("context", {})
    context.pop("source", None)
    context.pop("plan_rows", None)
    context.pop("tail", None)
    context.pop("material_catalog", None)
    context.pop("reference_history", None)
    from .need_routes import enabled
    document["common_preparation"] = enabled()
    return document


@router.get("/planeamento/dossies", response_class=HTMLResponse)
def page(request: Request):
    version = hashlib.sha256((DIR / "static" / "dossiers.js").read_bytes() + (DIR / "static" / "dossiers.css").read_bytes()).hexdigest()[:10]
    return templates.TemplateResponse(request=request, name="dossiers.html", context={"version": version})


@router.get("/planeamento/api/dossies")
def documents():
    return _result(lambda: {"documents": [_public(d) for d in store.list_documents()], "model": provider.public_config(), "inbox": inbox.status()})


@router.post("/planeamento/api/dossies")
async def upload(request: Request, file: UploadFile):
    try:
        _origin(request)
        data = await file.read(pdf.MAX_BYTES + 1)
        return await run_in_threadpool(_result, store.ingest, data, file.filename, configured=provider.configured())
    except DossierError as exc:
        return _error(exc)
    finally:
        await file.close()


@router.get("/planeamento/api/dossies/{uid}")
def document(uid: str):
    return _result(lambda: _public(store.get_document(uid)))


@router.get("/planeamento/api/dossies/{uid}/pdf")
def original(uid: str):
    try:
        doc = store.get_document(uid)
        return FileResponse(store.file_path(uid), media_type="application/pdf", filename=doc["filename"],
                            content_disposition_type="inline", headers={"Cache-Control": "private, no-cache"})
    except DossierError as exc:
        return _error(exc)


@router.get("/planeamento/api/dossies/{uid}/pagina/{number}")
def image_page(uid: str, number: int):
    try:
        image, _ = pdf.page_data(store.file_path(uid), number)
        return Response(image, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})
    except DossierError as exc:
        return _error(exc)


@router.post("/planeamento/api/dossies/{uid}/retomar")
async def resume(uid: str, request: Request):
    try:
        await _body(request)
        await run_in_threadpool(store.retry, uid, api_ready=provider.configured())
        return _result(lambda: _public(store.get_document(uid)))
    except DossierError as exc:
        return _error(exc)


@router.post("/planeamento/api/dossies/{uid}/cruzar")
async def refresh(uid: str, request: Request):
    try:
        await _body(request)
        if store.get_document(uid)["status"] in ("waiting_api", "queued", "indexing", "extracting"):
            raise DossierError("Conclui primeiro a leitura do PDF.", 409)
        await run_in_threadpool(pipeline.reconcile, uid)
        return _result(lambda: _public(store.get_document(uid)))
    except DossierError as exc:
        return _error(exc)


@router.post("/planeamento/api/dossies/{uid}/reler")
async def restart(uid: str, request: Request):
    try:
        data = await _body(request)
        await run_in_threadpool(store.restart, uid, api_ready=provider.configured(),
            actor=str(data.get("actor") or ""), reason=str(data.get("reason") or ""))
        return _result(lambda: _public(store.get_document(uid)))
    except DossierError as exc:
        return _error(exc)


@router.post("/planeamento/api/dossies/{uid}/paginas/{number}/reler")
async def reread_page(uid: str, number: int, request: Request):
    try:
        data = await _body(request)
        await run_in_threadpool(store.reread_page, uid, number, api_ready=provider.configured(),
            actor=str(data.get("actor") or ""), reason=str(data.get("reason") or ""))
        return _result(lambda: _public(store.get_document(uid)))
    except DossierError as exc:
        return _error(exc)


@router.post("/planeamento/api/dossies/{uid}/linhas/{piece_id}/reler")
async def reread_piece(uid: str, piece_id: str, request: Request):
    try:
        data = await _body(request)
        await run_in_threadpool(store.reread_piece, uid, piece_id, api_ready=provider.configured(),
            actor=str(data.get("actor") or ""), reason=str(data.get("reason") or ""))
        return _result(lambda: _public(store.get_document(uid)))
    except DossierError as exc:
        return _error(exc)


@router.post("/planeamento/api/dossies/{uid}/linhas/{piece_id}/excluir")
async def exclude_piece(uid: str, piece_id: str, request: Request):
    try:
        data = await _body(request)
        return await run_in_threadpool(_result, lambda: _public(pipeline.exclude_piece(uid, piece_id, data)))
    except DossierError as exc:
        return _error(exc)


@router.post("/planeamento/api/dossies/{uid}/conferir")
async def review_document(uid: str, request: Request):
    try:
        data = await _body(request)
        return await run_in_threadpool(_result, lambda: _public(pipeline.review_document(uid, data)))
    except DossierError as exc:
        return _error(exc)


@router.patch("/planeamento/api/dossies/{uid}/linhas/{piece_id}")
async def review_piece(uid: str, piece_id: str, request: Request):
    try:
        data = await _body(request)
        return await run_in_threadpool(_result, lambda: _public(pipeline.review_piece(uid, piece_id, data)))
    except DossierError as exc:
        return _error(exc)


@router.get("/planeamento/api/necessidades")
def needs():
    from .need_routes import enabled
    if enabled():
        from .. import planning_needs
        return _result(planning_needs.list_needs)
    return _result(lambda: {"rows": [_public(p) for p in store.plan_rows()]})


@router.get("/planeamento/api/modelo")
def model(request: Request):
    return _result(lambda: {**provider.public_config(), "can_configure": _can_configure(request)})


@router.put("/planeamento/api/modelo")
async def configure(request: Request):
    try:
        data = await _body(request, admin=True)
        return await run_in_threadpool(_result, provider.save_config, data)
    except DossierError as exc:
        return _error(exc)


@router.post("/planeamento/api/modelo/testar")
async def test_model(request: Request):
    class Probe(BaseModel):
        text: str

    def probe():
        from PIL import Image, ImageDraw
        image = Image.new("RGB", (280, 100), "white")
        ImageDraw.Draw(image).text((30, 25), "MTG2 473", fill="black", font_size=35)
        data = io.BytesIO()
        image.save(data, format="PNG")
        result = provider.VisionProvider().request("Transcreve apenas o texto visível nesta imagem no campo text.", Probe, [(1, data.getvalue())])
        if "".join(result["text"].split()).upper() != "MTG2473":
            raise DossierError("A API respondeu, mas não leu corretamente a imagem de teste. Confirma que o modelo suporta visão.", 502)
        return {"ok": True, "message": "Ligação e leitura de imagem confirmadas."}
    try:
        await _body(request, admin=True)
        return await run_in_threadpool(_result, probe)
    except DossierError as exc:
        return _error(exc)


@router.post("/planeamento/api/processar")
async def process_waiting(request: Request):
    try:
        await _body(request)
        if not provider.configured():
            raise DossierError("Configura primeiro a API de um modelo com visão.", 409)
        store.queue_waiting()
        return JSONResponse({"queued": True})
    except DossierError as exc:
        return _error(exc)


def _operational_version(rows):
    try:
        ofs = {row.get('production_order') or store.get_document(row['document_id']).get('production_order')
               for row in rows}
        return planning_hub.require_operational_orders(ofs)
    except planning.PlanningError as exc:
        raise DossierError(str(exc), exc.status) from None
    except psycopg.Error:
        raise DossierError('Não foi possível confirmar o CPIS. A saída está bloqueada; os dados foram conservados.', 503) from None


@router.get("/planeamento/api/saida/{format}")
def export(format: str, document: str | None = None, proposal: str | None = None):
    from .need_routes import enabled
    if enabled():
        return JSONResponse({"error":"Prepara uma comparação comum antes de descarregar a saída."},409)
    try:
        if format not in ("csv", "xlsm"):
            raise DossierError("Formato de saída inválido.", 404)
        rows = macro.export_rows([document] if document else None)
        cpis_version = _operational_version(rows)
        if format == "csv":
            data, media = macro.csv_bytes(rows), "text/csv; charset=utf-8"
        else:
            data, summary = macro.fill_macro(rows)
            summary['cpis_version'] = cpis_version
            document_ids = {r["document_id"] for r in rows}
            expected = macro.fingerprint(summary)
            recorded = [store.get_document(uid).get("latest_proposal") for uid in document_ids]
            if (not proposal or proposal != expected or any(not item
                    or item["summary"].get("proposal_fingerprint") != proposal
                    or item["source_sha256"] != summary["source_sha256"] for item in recorded)):
                raise DossierError("A proposta mudou desde a conferência. Revê a nova comparação antes de descarregar.", 409)
            media = "application/vnd.ms-excel.sheet.macroEnabled.12"
            for uid in document_ids:
                store.record_export(uid, summary["source_sha256"], summary)
        return Response(data, media_type=media, headers={
            "Content-Disposition": f'attachment; filename="Planeamento_preenchido.{format}"',
            "Cache-Control": "no-store"})
    except DossierError as exc:
        return _error(exc)


@router.get("/planeamento/api/saida-proposta")
def export_preview(document: str | None = None):
    from .need_routes import enabled
    if enabled():
        return JSONResponse({"error":"Usa a comparação da preparação comum, que verifica as necessidades de todas as origens."},409)
    try:
        rows = macro.export_rows([document] if document else None)
        cpis_version = _operational_version(rows)
        summary = macro.preview_macro(rows)
        summary['cpis_version'] = cpis_version
        summary["proposal_fingerprint"] = macro.fingerprint(summary)
        for uid in {r["document_id"] for r in rows}:
            store.record_proposal(uid, summary["source_sha256"], summary)
        return JSONResponse(summary, headers={"Cache-Control": "no-store"})
    except DossierError as exc:
        return _error(exc)
