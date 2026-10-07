"""HTTP da Carteira (plano de 28/09/2026). Só leitura nesta fase; ligada por MES_PLANNING_SELECTION_ENABLED=1.

As leituras (GET e as consultas que nada gravam) aceitam o resultado anterior enquanto as caches se refazem
em segundo plano (`allow_stale`, 07/10/2026); as gravações e os tokens leem sempre as versões atuais.
"""
import hashlib
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from ..web.templates_env import install

from .. import planning, planning_needs as needs
from . import portfolio, selection


@asynccontextmanager
async def _lifespan(app):
    """Aquecimento das caches do setor em segundo plano, junto ao arranque da aplicação que inclui estas rotas
    (o MES não as inclui; planning_app.py fica igual)."""
    from . import warmup
    stop = warmup.start() if warmup.enabled() else None
    try:
        yield
    finally:
        if stop is not None:
            stop.set()


router = APIRouter(lifespan=_lifespan)
WEB = Path(__file__).resolve().parents[1] / "web"
templates = install(Jinja2Templates(directory=str(WEB / "templates")))


def enabled() -> bool:
    return os.environ.get("MES_PLANNING_SELECTION_ENABLED", "0") == "1"


def _guard() -> None:
    if not enabled():
        raise HTTPException(status_code=404)


def _call(function):
    from ..web.planning_routes import _call as call
    return call(function)


# Carteira com seleção por membro (plano de 02/10/2026); tabela_fixa.js = cabeçalho fixo (P2, 08/10), também na Carga.
PAGE_FILES = ("static/carteira2.js", "static/carteira2.css", "static/tabela_fixa.js")


@router.get("/planeamento/carteira", response_class=HTMLResponse)
def page(request: Request):
    _guard()
    version = hashlib.sha256(b"".join((WEB / f).read_bytes() for f in PAGE_FILES)).hexdigest()[:12]
    return templates.TemplateResponse(request=request, name="carteira2.html", context={
        "version": version, "sectors": portfolio.SECTORS, "views": portfolio.VIEW_LABELS, "status": portfolio.STATUS,
    })


def _filters(familia, familia_sku, janela, maquina, sinal, estado, q, semanas):
    return {"familia": familia, "familia_sku": familia_sku, "janela": janela, "maquina": maquina, "sinal": sinal,
            "estado": estado, "q": q, "semanas": [w for w in semanas or [] if w]}


@router.get("/planeamento/api/carteira")
def groups(setor: str = "cantoneiras", vista: str = "referencia", caminho: list[str] = Query(default=[]),
           familia: str | None = None, familia_sku: str | None = None, janela: str | None = None, maquina: str | None = None,
           sinal: str | None = None, estado: str | None = None, q: str | None = None, ordem: str = "urgencia",
           semanas: list[str] = Query(default=[])):
    """Grupos de um nível. `ordem`: corte | picking (só MTG2) | urgencia | metros; a resposta repete-a em `order`."""
    _guard()
    filters = _filters(familia, familia_sku, janela, maquina, sinal, estado, q, semanas)
    return _call(lambda: needs.serial(portfolio.groups(setor, vista, caminho, filters, ordem, data=portfolio.current(setor, allow_stale=True),
                                                       decisions=selection.current(setor))))


@router.get("/planeamento/api/carteira/membros")
def members(setor: str = "cantoneiras", vista: str = "referencia", caminho: list[str] = Query(default=[]),
            cursor: int = 0, limite: int = 200, pesquisa: str | None = None,
            familia: str | None = None, familia_sku: str | None = None, janela: str | None = None, maquina: str | None = None,
            sinal: str | None = None, estado: str | None = None, q: str | None = None, semanas: list[str] = Query(default=[]),
            ordem: str | None = None):
    """Membros exatos de um grupo (lupa): total integral, todas as chaves e a página pedida, pela ordem da lista."""
    _guard()
    filters = {k: v for k, v in _filters(familia, familia_sku, janela, maquina, sinal, estado, q, semanas).items() if v}
    def build():
        sector = portfolio.check_sector(setor)

        def suggest(lines):
            # A máquina que o Planear grava nestas linhas (uma só fonte, 07/10/2026); a sugestão é opcional: a lupa
            # abre na mesma se a previsão falhar.
            try:
                return selection.suggested_machines(sector, lines, allow_stale=True)
            except Exception:
                import logging
                logging.getLogger(__name__).exception("Máquinas sugeridas indisponíveis")
                return {}
        return needs.serial(portfolio.members(sector, vista, caminho, cursor=cursor, limit=limite, q=pesquisa, filters=filters,
                                              data=portfolio.current(sector, allow_stale=True), decisions=selection.current(setor),
                                              suggest=suggest, sort=ordem))
    return _call(build)


@router.post("/planeamento/api/carteira/contagens")
async def counts(request: Request):
    """Quantos membros marcados há em cada grupo de um nível (consulta; nada é gravado)."""
    _guard()

    def build(p):
        sector = portfolio.check_sector(str(p.get("setor") or ""))
        filters = p.get("filtros") or {}
        if not isinstance(filters, dict):
            raise planning.PlanningError("Filtros inválidos.")
        return needs.serial(portfolio.counts(sector, str(p.get("vista") or "referencia"), p.get("caminho") or [],
                                             portfolio.keys_from(p), {k: v for k, v in filters.items() if v},
                                             data=portfolio.current(sector, allow_stale=True), decisions=selection.current(sector)))
    return await _post(request, build)


@router.get("/planeamento/api/carteira/kpis")
def kpis(setor: str = "cantoneiras"):
    """Carga por máquina e resumo por estado do setor. Não aceita filtros da lista."""
    _guard()
    from . import portfolio_kpis
    return _call(lambda: needs.serial(portfolio_kpis.overview(portfolio.check_sector(setor), allow_stale=True)))


@router.post("/planeamento/api/carteira/previsao")
async def kpis_preview(request: Request):
    """Acréscimo dos membros marcados por máquina (consulta; nada é gravado)."""
    _guard()
    from . import portfolio_kpis
    return await _post(request, lambda p: needs.serial(portfolio_kpis.preview(p, allow_stale=True)))


@router.post("/planeamento/api/carteira/selecao")
async def decide(request: Request):
    """Planear (sem máquina, com a máquina sugerida), excluir (motivo opcional) ou limpar membros exatos da Carteira."""
    _guard()
    return await _post(request, lambda payload: needs.serial(selection.apply(payload)))


@router.post("/planeamento/api/carteira/maquina")
async def assign_machine(request: Request):
    """«Atribuir máquina»: as linhas marcadas vão para a máquina escolhida (null tira a escolha da Carteira)."""
    _guard()
    from . import member_machine
    return await _post(request, lambda payload: needs.serial(member_machine.apply(payload)))


@router.post("/planeamento/api/carteira/tokens")
async def member_tokens(request: Request):
    """Tokens atuais das linhas marcadas (depois de atribuir máquina ou de um conflito). Consulta."""
    _guard()

    def build(p):
        sector = portfolio.check_sector(str(p.get("setor") or ""))
        keys = set(portfolio.keys_from(p))
        decisions = selection.current(sector)
        return {"tokens": {x["key"]: portfolio.member_token(x, portfolio.effective(x, decisions)["revision"])
                           for x in portfolio.current(sector)["lines"] if x["key"] in keys}}
    return await _post(request, build)


@router.post("/planeamento/api/carteira/sugestao")
async def machine_suggestion(request: Request):
    """Máquinas do setor e a máquina sugerida mais frequente nas linhas marcadas — a que o Planear grava (consulta)."""
    _guard()

    def build(p):
        from collections import Counter
        from . import family_sets
        sector = portfolio.check_sector(str(p.get("setor") or ""))
        keys = set(portfolio.keys_from(p))
        marked = [x for x in portfolio.current(sector, allow_stale=True)["lines"] if x["key"] in keys]
        votes, labels = Counter(), {}
        for found in selection.suggested_machines(sector, marked, allow_stale=True).values():
            votes[found["resource_id"]] += 1
            labels.setdefault(found["resource_id"], found)
        top = votes.most_common(1)
        return needs.serial({"machines": family_sets.machines(sector),
                             "suggestion": {**labels[top[0][0]], "lines": top[0][1], "marked": len(keys)} if top else None})
    return await _post(request, build)


@router.get("/planeamento/carteira/conjuntos", response_class=HTMLResponse)
def family_sets_page(request: Request):
    _guard()
    version = hashlib.sha256((WEB / "static/conjuntos.js").read_bytes() + (WEB / "static/conjuntos.css").read_bytes()).hexdigest()[:12]
    return templates.TemplateResponse(request=request, name="carteira_conjuntos.html",
                                      context={"version": version, "sectors": portfolio.SECTORS})


@router.get("/planeamento/api/carteira/conjuntos")
def family_sets_list(setor: str = "cantoneiras"):
    _guard()
    from . import family_sets
    return _call(lambda: family_sets.listing(setor))


@router.post("/planeamento/api/carteira/conjuntos")
async def family_sets_save(request: Request):
    _guard()
    from . import family_sets
    return await _post(request, lambda payload: needs.serial(family_sets.save(payload)))


@router.post("/planeamento/api/carteira/conjuntos/arquivar")
async def family_sets_archive(request: Request):
    _guard()
    from . import family_sets
    return await _post(request, lambda payload: needs.serial(family_sets.archive(payload)))


# --- Definições do setor, turnos e carga (pedido de 06/10/2026). Interruptor da Carteira.

def _page(request: Request, name: str, files: tuple, **context):
    version = hashlib.sha256(b"".join((WEB / f).read_bytes() for f in files)).hexdigest()[:12]
    return templates.TemplateResponse(request=request, name=name, context={"version": version, "sectors": portfolio.SECTORS, **context})


@router.get("/planeamento/setor/definicoes", response_class=HTMLResponse)
def settings_page(request: Request):
    _guard()
    return _page(request, "setor_definicoes.html", ("static/setor_definicoes.js", "static/setor_definicoes.css"))


@router.get("/planeamento/api/setor/definicoes")
def settings_view(setor: str = "cantoneiras"):
    _guard()
    from . import settings
    return _call(lambda: settings.overview(setor))


@router.post("/planeamento/api/setor/definicoes")
async def settings_save(request: Request):
    _guard()
    from . import settings
    return await _post(request, lambda payload: needs.serial(settings.save(payload)))


@router.get("/planeamento/setor/carga", response_class=HTMLResponse)
def load_page(request: Request):
    _guard()
    return _page(request, "setor_carga.html", ("static/setor_carga.js", "static/setor_carga.css", "static/tabela_fixa.js"))


@router.get("/planeamento/api/setor/carga")
def load_view(setor: str = "cantoneiras"):
    _guard()
    from . import load
    return _call(lambda: load.overview(portfolio.check_sector(setor)))


@router.get("/planeamento/api/setor/carga/celula")
def load_cell(setor: str, maquina: str, ano: int, semana: int):
    _guard()
    from . import load
    return _call(lambda: load.cell(portfolio.check_sector(setor), maquina, ano, semana))


@router.get("/planeamento/api/setor/carga/operacoes")
def load_operations(setor: str, maquina: str, ano: int, semana: int, of: str):
    """Operações de uma OF numa célula da Carga, com o cálculo de cada uma (06/10/2026)."""
    _guard()
    from . import load
    return _call(lambda: load.operations(portfolio.check_sector(setor), maquina, ano, semana, of))


@router.get("/planeamento/api/setor/carga/producao")
def load_production(setor: str, maquina: str, ano: int, semana: int, pagina: int = 1):
    """Produção registada (OCR validado) numa máquina e semana, e as horas reais declaradas (06/10/2026)."""
    _guard()
    from . import load
    return _call(lambda: load.production(portfolio.check_sector(setor), maquina, ano, semana, pagina))


@router.post("/planeamento/api/setor/turnos")
async def shifts_save(request: Request):
    """Mais ou menos turnos numa semana ou num dia, para uma ou várias máquinas (um só lote)."""
    _guard()
    from . import shifts
    return await _post(request, lambda payload: needs.serial(shifts.apply(payload)))


@router.get("/planeamento/api/carteira/opcoes")
def options(setor: str = "cantoneiras"):
    _guard()

    def build():
        data = portfolio.current(setor, allow_stale=True)
        return needs.serial({"families": portfolio.families(setor, data=data), "sku_families": portfolio.sku_families(setor, data=data),
                             "machines": portfolio.machines(setor, data=data), "weeks": portfolio.weeks(setor, data=data),
                             "status": portfolio.STATUS})
    return _call(build)


@router.get("/planeamento/api/setor/quadro")
def board(setor: str = "cantoneiras"):
    """Gantt simples e lista vermelha das OF por planear (pedido de 02/10/2026). Só leitura."""
    _guard()
    from . import board as quadro
    return _call(lambda: needs.serial(quadro.board(setor, allow_stale=True)))


@router.get("/planeamento/api/setor/quadro/dia")
def board_day(setor: str = "cantoneiras", dia: str = "", maquina: str | None = None):
    """Gantt de um dia por máquina do setor: horas, turnos e o que não tem hora (pedido de 06/10/2026)."""
    _guard()
    from . import board as quadro
    return _call(lambda: quadro.day(setor, dia, maquina or None, allow_stale=True))


# --- Vistas por família e capacidade (plano de 01/10/2026). Interruptor próprio, desligado por defeito.

def views_enabled() -> bool:
    return os.environ.get("MES_PLANNING_FAMILY_VIEWS_ENABLED", "0") == "1"


def _views() -> None:
    if not views_enabled():
        raise HTTPException(status_code=404)


async def _post(request: Request, function):
    """JSON body with the same origin checks as the other planning writes; no audit outbox."""
    from ..web.need_routes import write
    return await write(request, function, audit=False)


@router.get("/planeamento/api/setor/necessidades/facetas")
def needs_facets(areas: list[str] = Query(default=[])):
    _views()
    from . import needs_view
    return _call(lambda: needs_view.facet_view({"areas": areas or None}))


@router.post("/planeamento/api/setor/necessidades/arvore")
async def needs_tree(request: Request):
    """Read-only query in JSON (filters may hold many values); no record is created."""
    _views()
    from . import needs_view
    return await _post(request, needs_view.view)


@router.get("/planeamento/api/setor/necessidades/ocorrencia")
def needs_occurrence(setor: str, key: str):
    _views()
    from . import needs_view
    return _call(lambda: needs_view.occurrence(setor, key))


@router.post("/planeamento/api/setor/capacidade")
async def capacity_view(request: Request):
    _views()
    from . import capacity

    def build(p):
        try:
            horizon = int(p.get("horizon_weeks") or 12)
        except (TypeError, ValueError):
            raise planning.PlanningError("Horizonte inválido.") from None
        areas = p.get("areas") or ["perfis", "cantoneiras"]
        return capacity.view(areas if isinstance(areas, list) else [areas], horizon_weeks=horizon,
                             granularity=p.get("granularity") or "auto", mode=p.get("mode") or "needs",
                             scenario_id=p.get("scenario_id"), filters=p.get("filters"),
                             scenario=p.get("capacity_scenario") or "mediana")
    return await _post(request, build)


@router.post("/planeamento/api/setor/capacidade/quotas")
async def capacity_quota(request: Request):
    _views()
    from . import capacity
    return await _post(request, capacity.save_quota)


@router.post("/planeamento/api/setor/maquinas/previsao")
async def machine_preview(request: Request):
    _views()
    from . import assignments
    return await _post(request, assignments.preview)


@router.post("/planeamento/api/setor/maquinas/aplicar")
async def machine_apply(request: Request):
    _views()
    from . import assignments
    return await _post(request, assignments.apply)


@router.post("/planeamento/api/setor/maquinas/desfazer")
async def machine_undo(request: Request):
    _views()
    from . import assignments
    return await _post(request, assignments.undo)


@router.get("/planeamento/api/setor/maquinas/acoes")
def machine_actions(setor: str):
    _views()
    from . import assignments
    return _call(lambda: assignments.actions(setor))


@router.get("/planeamento/api/setor/conjuntos")
def reference_sets(setor: str):
    _views()
    from . import sets
    return _call(lambda: sets.listing(setor))


@router.get("/planeamento/api/setor/conjuntos/{set_id}")
def reference_set(set_id: str, setor: str):
    _views()
    from . import sets
    return _call(lambda: sets.detail(setor, set_id))


@router.post("/planeamento/api/setor/conjuntos")
async def reference_set_save(request: Request):
    _views()
    from . import sets
    return await _post(request, sets.save)


@router.post("/planeamento/api/setor/conjuntos/arquivar")
async def reference_set_archive(request: Request):
    _views()
    from . import sets
    return await _post(request, sets.archive)


@router.get("/planeamento/api/setor/prioridades")
def priorities():
    _views()
    from . import priority

    def build():
        with planning.connect(readonly=True) as c:
            return needs.serial({"policies": priority.policies(c), "overrides": list(priority.overrides(c).values()),
                                 "fields": priority.FIELDS, "milestones": priority.MILESTONES,
                                 "defaults": {area: priority.default(area) for area in priority.DEFAULTS}})
    return _call(build)


@router.post("/planeamento/api/setor/prioridades/politica")
async def priority_policy(request: Request):
    _views()
    from . import priority
    return await _post(request, priority.save_policy)


@router.post("/planeamento/api/setor/prioridades/of")
async def priority_override(request: Request):
    _views()
    from . import priority
    return await _post(request, priority.save_override)



@router.get("/planeamento/maquinas", response_class=HTMLResponse)
def machines_page(request: Request):
    """Carga por máquina, sugestões e equilíbrio: a página de trabalho do dia a dia do planeador."""
    _views()
    version = hashlib.sha256((WEB / "static/maquinas.js").read_bytes() + (WEB / "static/maquinas.css").read_bytes()).hexdigest()[:12]
    return templates.TemplateResponse(request=request, name="maquinas.html", context={"version": version})


@router.get("/planeamento/api/setor/maquinas/painel")
def machines_panel(areas: list[str] = Query(default=[]), cenario: str = "mediana"):
    _views()
    from . import workbench
    return _call(lambda: workbench.overview(areas or None, cenario))


@router.get("/planeamento/api/ordens/{of}/sugestoes")
def manual_suggestions(of: str, setor: str = "perfis", ref: str | None = None, perfil: str | None = None,
                       equipa: str | None = None, material: str | None = None, cliente: str | None = None,
                       designacao: str | None = None):
    """Valores sugeridos para o registo manual (/planeamento/manual): Equipa, Pav., Data Corte, Máquina,
    dimensões… cada um com a origem. Só leitura; o ecrã nunca escreve por cima do que o utilizador escreveu."""
    _guard()
    from .. import planning_suggestions
    values = {k: v for k, v in (("team", equipa), ("material_type", material), ("customer", cliente),
                                ("designation", designacao)) if v}
    return _call(lambda: needs.serial(planning_suggestions.for_order(portfolio.check_sector(setor), of, ref, perfil, values)))
