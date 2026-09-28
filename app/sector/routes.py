"""HTTP da Carteira (plano de 28/09/2026). Só leitura nesta fase; ligada por MES_PLANNING_SELECTION_ENABLED=1."""
import hashlib
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .. import planning_needs as needs
from . import portfolio, selection

router = APIRouter()
WEB = Path(__file__).resolve().parents[1] / "web"
templates = Jinja2Templates(directory=str(WEB / "templates"))
templates.env.globals["raw_enabled"] = lambda: os.getenv("MES_PLANNING_RAW_ENABLED", "0") == "1"


def enabled() -> bool:
    return os.environ.get("MES_PLANNING_SELECTION_ENABLED", "0") == "1"


def _guard() -> None:
    if not enabled():
        raise HTTPException(status_code=404)


def _call(function):
    from ..web.planning_routes import _call as call
    return call(function)


@router.get("/planeamento/carteira", response_class=HTMLResponse)
def page(request: Request):
    _guard()
    version = hashlib.sha256((WEB / "static/carteira.js").read_bytes() + (WEB / "static/carteira.css").read_bytes()).hexdigest()[:12]
    return templates.TemplateResponse(request=request, name="carteira.html", context={
        "version": version, "sectors": portfolio.SECTORS, "views": portfolio.VIEW_LABELS,
        "windows": portfolio.WINDOWS, "signals": portfolio.SIGNALS, "states": portfolio.STATES,
    })


@router.get("/planeamento/api/carteira")
def groups(setor: str = "cantoneiras", vista: str = "referencia", caminho: list[str] = Query(default=[]),
           familia: str | None = None, janela: str | None = None, maquina: str | None = None,
           sinal: str | None = None, estado: str | None = None, q: str | None = None, ordem: str = "urgencia"):
    _guard()
    filters = {"familia": familia, "janela": janela, "maquina": maquina, "sinal": sinal, "estado": estado, "q": q}
    return _call(lambda: needs.serial(portfolio.groups(setor, vista, caminho, filters, ordem, decisions=selection.current(setor))))


@router.post("/planeamento/api/carteira/selecao")
async def decide(request: Request):
    """Planear, excluir (com motivo) ou limpar a decisão de um grupo da Carteira."""
    _guard()
    from ..web.need_routes import write
    return await write(request, lambda payload: needs.serial(selection.apply(payload)), audit=False)


@router.get("/planeamento/api/carteira/opcoes")
def options(setor: str = "cantoneiras"):
    _guard()

    def build():
        data = portfolio.load(setor)
        return needs.serial({"families": portfolio.families(setor, data=data), "machines": portfolio.machines(setor, data=data)})
    return _call(build)
