"""Arranque independente dos dossiês, sem iniciar captura/OCR kanban.

uvicorn app.web.planning_app:app --host 127.0.0.1 --port 8113 --env-file .env
"""
from pathlib import Path
from contextlib import asynccontextmanager
import importlib.util
import os

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .planning_routes import router

@asynccontextmanager
async def lifespan(app):
    from ..dossiers.pipeline import start_worker
    stop = start_worker() if os.environ.get("MES_DOSSIER_WORKER_DISABLED") != "1" else None
    from .need_routes import enabled
    from ..planning_needs import start_outbox_worker
    audit_stop = start_outbox_worker() if enabled() and os.environ.get('MES_DOSSIER_WORKER_DISABLED') != '1' else None
    if os.environ.get('MES_PLANNING_RAW_ENABLED')=='1' and os.environ.get('MES_DOSSIER_WORKER_DISABLED')!='1':
        from ..planning_raw_analysis import recover
        recover()
    try:
        yield
    finally:
        if audit_stop:
            audit_stop.set()
        if stop:
            stop.set()


app = FastAPI(title="Planeamento · Dossiês de fabrico", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
app.include_router(router)
from .raw_workspace_routes import router as raw_workspace_router
app.include_router(raw_workspace_router)

# Carteira e planeamento por setor (plano de 28/09/2026). O MES tem uma ligação para este ficheiro
# mas não tem o pacote sector: aí não se inclui nada; aqui, erros de importação continuam visíveis.
if importlib.util.find_spec(__package__.rsplit(".", 1)[0] + ".sector") is not None:
    from ..sector.routes import router as sector_router
    app.include_router(sector_router)


@app.get("/")
def root():
    return RedirectResponse("/planeamento", status_code=307)
