"""Caches das vistas pesadas: resposta antiga enquanto se refaz, cálculo único e aquecimento (07/10/2026).

Sem base de dados: as fontes e os cálculos são substituídos por funções do ensaio que contam as chamadas.
A estabilidade das chaves com a base real está em test_sector_cache_keys.py.
"""
from __future__ import annotations

import threading
import time
from datetime import date

import pytest

from app import planning
from app.sector import cache


def wait_until(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("condição não cumprida a tempo")
        time.sleep(0.01)


@pytest.fixture(autouse=True)
def no_refresh_delay(monkeypatch):
    """Os ensaios não esperam pelos 15 s antes de cada recálculo de fundo (há um ensaio próprio para essa espera)."""
    monkeypatch.setattr(cache, "REFRESH_DELAY", 0)


# --- O mecanismo (app/sector/cache.py)

def test_same_key_is_served_from_memory():
    c, calls = cache.Cache("ensaio"), []
    assert c.get("s", 1, lambda: calls.append(1) or "v1") == "v1"
    assert c.get("s", 1, lambda: calls.append(1) or "outro") == "v1"
    assert calls == [1]


def test_changed_key_answers_previous_result_then_rebuilds_once_in_background():
    c = cache.Cache("ensaio", mark=lambda v: {**v, "stale": True})
    c.get("s", 1, lambda: {"v": 1, "stale": False})
    release, builds, refreshes = threading.Event(), [], []

    def build():
        builds.append(2)
        release.wait(5)
        return {"v": 2, "stale": False}

    def refresh():
        refreshes.append(1)
        return c.get("s", 2, build)

    first = c.get("s", 2, build, allow_stale=True, refresh=refresh)
    second = c.get("s", 2, build, allow_stale=True, refresh=refresh)
    assert first == second == {"v": 1, "stale": True}
    assert first is second  # a mesma vista antiga: quem depende da identidade não refaz nada
    wait_until(lambda: builds)
    assert refreshes == [1] and builds == [2]  # um só recálculo em segundo plano, por muitos pedidos
    release.set()
    wait_until(lambda: c.get("s", 2, build, allow_stale=True, refresh=refresh) == {"v": 2, "stale": False})
    assert builds == [2]


def test_background_rebuilds_run_one_at_a_time_across_caches():
    first, second = cache.Cache("ensaio-1"), cache.Cache("ensaio-2")
    first.get("s", 1, lambda: "a")
    second.get("s", 1, lambda: "b")
    running, peak, lock, release = [0], [0], threading.Lock(), threading.Event()

    def refresh(c, value):
        def run():
            with lock:
                running[0] += 1
                peak[0] = max(peak[0], running[0])
            release.wait(5)
            c.get("s", 2, lambda: value)
            with lock:
                running[0] -= 1
        return run

    assert first.get("s", 2, lambda: "x", allow_stale=True, refresh=refresh(first, "a2")) == "a"
    assert second.get("s", 2, lambda: "x", allow_stale=True, refresh=refresh(second, "b2")) == "b"
    time.sleep(0.1)
    release.set()
    current = lambda c: c.get("s", 2, lambda: "x", allow_stale=True, refresh=lambda: None)  # noqa: E731  (lê sem calcular)
    wait_until(lambda: current(first) == "a2" and current(second) == "b2")
    assert peak == [1]  # servidor partilhado: nunca dois cálculos de fundo ao mesmo tempo


def test_writes_never_get_the_previous_result():
    c = cache.Cache("ensaio", mark=lambda v: {**v, "stale": True})
    c.get("s", 1, lambda: {"v": 1})
    assert c.get("s", 2, lambda: {"v": 2}) == {"v": 2}  # sem allow_stale: calcula já


def test_concurrent_requests_for_the_same_key_build_once():
    c, builds, release = cache.Cache("ensaio"), [], threading.Event()

    def build():
        builds.append(1)
        release.wait(5)
        return "v"

    results = []
    threads = [threading.Thread(target=lambda: results.append(c.get("s", 1, build))) for _ in range(5)]
    for t in threads:
        t.start()
    wait_until(lambda: builds)
    time.sleep(0.05)
    release.set()
    for t in threads:
        t.join(5)
    assert builds == [1] and results == ["v"] * 5


def test_a_write_waits_for_the_background_rebuild_of_the_same_key():
    c, builds, release = cache.Cache("ensaio"), [], threading.Event()
    c.get("s", 1, lambda: "v1")

    def build():
        builds.append(1)
        release.wait(5)
        return "v2"

    c.get("s", 2, build, allow_stale=True, refresh=lambda: c.get("s", 2, build))
    wait_until(lambda: builds)
    result = []
    writer = threading.Thread(target=lambda: result.append(c.get("s", 2, build)))
    writer.start()
    time.sleep(0.05)
    assert not result  # espera pelo cálculo em curso, não começa outro
    release.set()
    writer.join(5)
    assert result == ["v2"] and builds == [1]


def test_an_older_build_never_replaces_a_newer_result():
    c, release, started = cache.Cache("ensaio"), threading.Event(), threading.Event()

    def slow():
        started.set()
        release.wait(5)
        return "antigo"

    old = threading.Thread(target=lambda: c.get("s", 1, slow))
    old.start()
    started.wait(5)
    assert c.get("s", 2, lambda: "novo") == "novo"
    release.set()
    old.join(5)
    assert c.get("s", 2, lambda: "outra vez") == "novo"


def test_previous_result_is_only_served_when_stale_if_allows_it():
    c = cache.Cache("ensaio")
    c.get("s", ("g1", "2026-10-06"), lambda: "ontem")
    same_day = lambda old: old[-1] == "2026-10-07"  # noqa: E731
    assert c.get("s", ("g1", "2026-10-07"), lambda: "hoje", allow_stale=True, refresh=lambda: None, stale_if=same_day) == "hoje"


def test_expired_result_is_served_while_it_refreshes():
    c, builds = cache.Cache("ensaio", max_age=0.05), []
    c.get("s", 1, lambda: "v1")
    time.sleep(0.06)

    def build():
        builds.append(1)
        return "v1b"

    assert c.get("s", 1, build, allow_stale=True, refresh=lambda: c.get("s", 1, build)) == "v1"
    wait_until(lambda: c.get("s", 1, build, allow_stale=True, refresh=lambda: None) == "v1b")
    assert builds == [1]


def test_failed_build_reaches_every_waiter_and_keeps_nothing():
    c, release = cache.Cache("ensaio"), threading.Event()

    def boom():
        release.wait(5)
        raise planning.PlanningError("falhou")

    errors = []

    def call():
        try:
            c.get("s", 1, boom)
        except planning.PlanningError as exc:
            errors.append(str(exc))

    threads = [threading.Thread(target=call) for _ in range(3)]
    for t in threads:
        t.start()
    time.sleep(0.05)
    release.set()
    for t in threads:
        t.join(5)
    assert errors == ["falhou"] * 3
    assert c.get("s", 1, lambda: "depois") == "depois"


def test_failed_background_rebuild_sends_the_error_of_that_key_to_the_next_read():
    """Um recálculo de fundo que falha não deixa a página na versão anterior o dia inteiro, sem aviso: o pedido
    seguinte com a mesma chave calcula logo, e o erro chega ao utilizador como antes das caches."""
    c, attempts = cache.Cache("ensaio"), []
    c.get("s", 1, lambda: "v1")

    def boom():
        attempts.append(1)
        raise planning.PlanningError("indisponível")

    refresh = lambda: c.get("s", 2, boom)  # noqa: E731
    assert c.get("s", 2, boom, allow_stale=True, refresh=refresh) == "v1"
    wait_until(lambda: attempts and not c._refreshing)
    with pytest.raises(planning.PlanningError, match="indisponível"):
        c.get("s", 2, boom, allow_stale=True, refresh=refresh)
    assert len(attempts) == 2 and not c._refreshing  # calculou no pedido; nenhum recálculo de fundo condenado
    assert c.get("s", 2, lambda: "v2", allow_stale=True, refresh=refresh) == "v2"  # corrigido: volta a calcular
    assert c.get("s", 2, boom, allow_stale=True, refresh=refresh) == "v2"


def test_failure_reading_the_key_in_the_background_also_reaches_the_next_read():
    c, built = cache.Cache("ensaio"), []
    c.get("s", 1, lambda: "v1")

    def refresh():
        raise planning.PlanningError("A preparar a consulta deste setor.")

    assert c.get("s", 2, lambda: "x", allow_stale=True, refresh=refresh) == "v1"
    wait_until(lambda: not c._refreshing)
    assert c.get("s", 2, lambda: built.append(1) or "v2", allow_stale=True, refresh=refresh) == "v2"
    assert built == [1]


def test_after_a_failure_a_newer_key_serves_the_previous_result_again():
    c = cache.Cache("ensaio")
    c.get("s", 1, lambda: "v1")

    def boom():
        raise planning.PlanningError("indisponível")

    assert c.get("s", 2, boom, allow_stale=True, refresh=lambda: c.get("s", 2, boom)) == "v1"
    wait_until(lambda: not c._refreshing)
    release = threading.Event()
    assert c.get("s", 3, lambda: "v3", allow_stale=True,
                 refresh=lambda: release.wait(5) and c.get("s", 3, lambda: "v3")) == "v1"
    release.set()
    wait_until(lambda: c.get("s", 3, lambda: "x", allow_stale=True, refresh=lambda: None) == "v3")


def test_older_data_never_replaces_newer_data_even_if_computed_later():
    """Com `rank`, o que decide é a idade dos dados e não a ordem dos cálculos: um cálculo começado depois, mas
    sobre um retrato mais antigo da base (outra ligação), não substitui uma geração mais recente."""
    c = cache.Cache("ensaio", rank=lambda key: key)
    assert c.get("s", 2, lambda: "geração 2") == "geração 2"
    assert c.get("s", 1, lambda: "geração 1") == "geração 1"  # quem pediu recebe o que pediu
    assert c.get("s", 2, lambda: "outra vez") == "geração 2"  # mas a cache guarda a mais recente


def test_background_rebuild_waits_for_the_second_generation_of_a_validation(monkeypatch):
    """Cada validação do MES publica duas gerações planning com poucos segundos entre elas: o recálculo de
    fundo espera REFRESH_DELAY e lê a chave nessa altura, por isso calcula uma só vez, já com a segunda."""
    monkeypatch.setattr(cache, "REFRESH_DELAY", 0.2)
    c, builds, latest = cache.Cache("ensaio"), [], [2]
    assert c.refresh_delay is None  # por omissão, a espera do módulo
    c.get("s", 1, lambda: "v1")

    def refresh():
        key = latest[0]
        return c.get("s", key, lambda: builds.append(key) or f"v{key}")

    assert c.get("s", 2, lambda: "x", allow_stale=True, refresh=refresh) == "v1"
    latest[0] = 3  # a segunda geração chega durante a espera
    wait_until(lambda: builds)
    wait_until(lambda: not c._refreshing)
    assert builds == [3]


def test_urgent_background_rebuild_goes_before_the_queued_ones():
    """Uma vez de fundo para todo o processo, mas as ocorrências (botões da página Máquinas à espera) passam à
    frente dos recálculos que já estavam na fila; o aquecimento vai sempre no fim."""
    from app.sector import occurrences
    assert occurrences._cache.priority == cache.URGENT and occurrences._cache.refresh_delay == 0  # nem espera os 15 s
    holder, normal, urgent = cache.Cache("ensaio-a"), cache.Cache("ensaio-b"), cache.Cache("ensaio-c", priority=cache.URGENT)
    for c in (holder, normal, urgent):
        c.get("s", 1, lambda: "v1")
    order, inside, release = [], threading.Event(), threading.Event()
    holder.get("s", 2, lambda: "x", allow_stale=True, refresh=lambda: (inside.set(), release.wait(5), order.append("a")))
    assert inside.wait(5)  # o primeiro recálculo tem a vez

    def warm_step():
        with cache.BACKGROUND.hold(cache.WARMUP):
            order.append("aquecimento")

    threading.Thread(target=warm_step, daemon=True).start()
    wait_until(lambda: cache.BACKGROUND.waiting() == 1)
    normal.get("s", 2, lambda: "x", allow_stale=True, refresh=lambda: order.append("b"))
    wait_until(lambda: cache.BACKGROUND.waiting() == 2)
    urgent.get("s", 2, lambda: "x", allow_stale=True, refresh=lambda: order.append("c"))
    wait_until(lambda: cache.BACKGROUND.waiting() == 3)
    release.set()
    wait_until(lambda: len(order) == 4)
    assert order == ["a", "c", "b", "aquecimento"]


# --- Carteira (portfolio.load / current)

class FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, *args, **kw):
        return self


@pytest.fixture()
def fake_portfolio(monkeypatch):
    """Fontes da Carteira em memória: a chave muda quando o ensaio muda `state['generation']`."""
    from app.sector import machine_choice, portfolio
    portfolio._cache.clear()
    portfolio._current_cache.clear()
    state = {"generation": 1, "builds": [], "release": None}
    monkeypatch.setattr(planning, "connect", lambda readonly=False: FakeConn())
    monkeypatch.setattr(machine_choice, "context", lambda area, conn=None: machine_choice.empty(area))

    def stamp(c, sector, today):
        head = {"id": state["generation"], "snapshot": "s", "created_at": None}
        return (head["id"], today, None, state.get("priority", "p")), head

    def rows(c, sector, head, today):
        state["builds"].append(head["id"])
        if state["release"] is not None:
            state["release"].wait(5)
        return {"sector": sector, "generation": head["id"], "snapshot": "s", "imported_at": None, "today": today,
                "lines": [], "stale": False, "build": len(state["builds"])}

    monkeypatch.setattr(portfolio, "_stamp", stamp)
    monkeypatch.setattr(portfolio, "_build", rows)
    yield state
    portfolio._cache.clear()
    portfolio._current_cache.clear()


def test_portfolio_read_gets_previous_lines_while_the_new_generation_builds(fake_portfolio):
    from app.sector import portfolio
    assert portfolio.current("cantoneiras")["generation"] == 1
    fake_portfolio["generation"], fake_portfolio["release"] = 2, threading.Event()
    stale = portfolio.current("cantoneiras", allow_stale=True)
    assert stale["generation"] == 1 and stale["stale"] is True
    wait_until(lambda: fake_portfolio["builds"] == [1, 2])
    fake_portfolio["release"].set()
    wait_until(lambda: portfolio.current("cantoneiras", allow_stale=True)["generation"] == 2)
    fresh = portfolio.current("cantoneiras", allow_stale=True)
    assert fresh["stale"] is False and fake_portfolio["builds"] == [1, 2]


def test_portfolio_write_reads_the_current_generation(fake_portfolio):
    from app.sector import portfolio
    portfolio.current("cantoneiras")
    fake_portfolio["generation"] = 2
    data = portfolio.current("cantoneiras")  # Planear, Atribuir, tokens: sem allow_stale
    assert data["generation"] == 2 and data["stale"] is False


def test_portfolio_previous_day_is_never_served(fake_portfolio, monkeypatch):
    from app.sector import portfolio
    portfolio.load("cantoneiras", today=date(2026, 10, 6))
    data = portfolio.load("cantoneiras", today=date(2026, 10, 7), allow_stale=True)
    assert data["today"] == date(2026, 10, 7) and data["stale"] is False


def test_portfolio_older_snapshot_never_replaces_a_newer_generation(fake_portfolio):
    """machine_learning.model lê portfolio.load(conn=c) num retrato da base mais antigo: esse cálculo começa
    depois, mas não pode substituir a geração mais recente já guardada (custava outro cálculo de 20–50 s)."""
    from app.sector import portfolio
    fake_portfolio["generation"] = 2
    assert portfolio.current("cantoneiras")["generation"] == 2
    fake_portfolio["generation"] = 1  # retrato antigo, numa ligação de quem chama
    assert portfolio.load("cantoneiras", conn=FakeConn())["generation"] == 1
    fake_portfolio["generation"] = 2
    data = portfolio.current("cantoneiras", allow_stale=True)
    assert data["generation"] == 2 and data["stale"] is False and fake_portfolio["builds"] == [2, 1]


def test_portfolio_current_follows_the_base_even_when_python_reuses_its_address(fake_portfolio, monkeypatch):
    """current() não identifica a base pelo endereço (id), que o CPython reutiliza: com a mesma geração mas
    outras prioridades, as linhas têm de ser as da base nova."""
    from app.sector import portfolio
    monkeypatch.setattr(portfolio, "id", lambda obj: 1, raising=False)  # o endereço da base anterior, reutilizado
    assert portfolio.current("cantoneiras")["build"] == 1
    fake_portfolio["priority"] = "outras prioridades"
    assert portfolio.current("cantoneiras")["build"] == 2
    assert portfolio.current("cantoneiras")["build"] == 2 and fake_portfolio["builds"] == [1, 1]


# --- Ocorrências (occurrences.load)

@pytest.fixture()
def fake_occurrences(monkeypatch):
    from app.sector import occurrences
    occurrences.invalidate()
    state = {"key": "k1", "builds": [], "release": None}
    monkeypatch.setattr(planning, "connect", lambda readonly=False: FakeConn())
    monkeypatch.setattr(occurrences, "stamp", lambda c, area, today: (area, state["key"], today))

    def build(c, area, today):
        state["builds"].append(state["key"])
        if state["release"] is not None:
            state["release"].wait(5)
        return {"area": area, "facts": [state["key"]], "today": today}

    monkeypatch.setattr(occurrences, "build", build)
    yield state
    occurrences.invalidate()


def test_occurrences_write_joins_the_background_rebuild_instead_of_building_twice(fake_occurrences):
    from app.sector import occurrences
    occurrences.load("cantoneiras")
    fake_occurrences["key"], fake_occurrences["release"] = "k2", threading.Event()
    assert occurrences.load("cantoneiras", allow_stale=True)["stale"] is True
    wait_until(lambda: fake_occurrences["builds"] == ["k1", "k2"])
    result = []
    writer = threading.Thread(target=lambda: result.append(occurrences.load("cantoneiras")))
    writer.start()
    time.sleep(0.05)
    fake_occurrences["release"].set()
    writer.join(5)
    assert result[0]["facts"] == ["k2"] and result[0]["stale"] is False
    assert fake_occurrences["builds"] == ["k1", "k2"]


# --- Quadro (board._built): o limite de 10 minutos já não faz esperar

def test_board_refreshes_in_background_after_the_time_limit(monkeypatch):
    from app.sector import board
    board._board.clear()
    monkeypatch.setattr(board._board, "max_age", 0.05)
    monkeypatch.setattr(board, "_sources", lambda sector: "fontes")
    builds, release = [], threading.Event()

    def build(sector):
        builds.append(sector)
        if len(builds) > 1:
            release.wait(5)
        return {"sector": sector, "n": len(builds), "stale": False}, {}

    monkeypatch.setattr(board, "_build", build)
    today = date(2026, 10, 7)
    assert board._built("cantoneiras", {"today": today})[0]["n"] == 1
    time.sleep(0.06)
    started = time.monotonic()
    result, _ = board._built("cantoneiras", {"today": today}, allow_stale=True)
    assert time.monotonic() - started < 0.5 and result["n"] == 1 and result["stale"] is True
    release.set()
    wait_until(lambda: board._built("cantoneiras", {"today": today}, allow_stale=True)[0]["n"] >= 2)
    wait_until(lambda: not board._board._refreshing)  # nenhum recálculo fica a correr depois do ensaio
    board._board.clear()


# --- Aquecimento ao arrancar (app/sector/warmup.py)

@pytest.fixture()
def warmup_module(monkeypatch):
    from app.sector import warmup
    monkeypatch.setenv("MES_PLANNING_SELECTION_ENABLED", "1")
    monkeypatch.delenv("MES_DOSSIER_WORKER_DISABLED", raising=False)
    monkeypatch.delenv("MES_PLANNING_WARMUP_DISABLED", raising=False)
    warmup._reset()
    yield warmup
    warmup._reset()


def test_warm_up_runs_once_in_background_and_does_not_block_startup(warmup_module, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.sector import routes
    release, runs = threading.Event(), []

    def warm(sectors=warmup_module.SECTORS):
        runs.append(tuple(sectors))
        release.wait(5)
        return True

    monkeypatch.setattr(warmup_module, "warm", warm)
    app = FastAPI()
    app.include_router(routes.router)
    started = time.monotonic()
    with TestClient(app):
        assert time.monotonic() - started < 2  # o arranque não espera pelo aquecimento
        wait_until(lambda: runs)
        assert warmup_module.start() is None  # um só aquecimento por processo
        release.set()
    assert runs == [("cantoneiras", "perfis")]


def test_warm_up_builds_every_cache_of_both_sectors_and_logs_durations(warmup_module, monkeypatch, caplog):
    from app.sector import board, forecast, load, occurrences, portfolio, portfolio_kpis
    calls = []
    monkeypatch.setattr(portfolio, "current", lambda sector, **kw: calls.append(("carteira", sector, kw)))
    monkeypatch.setattr(occurrences, "load", lambda sector, **kw: calls.append(("ocorrencias", sector, kw)))
    monkeypatch.setattr(board, "board", lambda sector, **kw: calls.append(("quadro", sector, kw)))
    monkeypatch.setattr(load, "overview", lambda sector, **kw: calls.append(("carga", sector, kw)))
    monkeypatch.setattr(forecast, "current", lambda sector, **kw: calls.append(("previsao", sector, kw)))

    def kpis(sector, **kw):
        if sector == "perfis":
            raise planning.PlanningError("indisponível")
        calls.append(("kpis", sector, kw))

    monkeypatch.setattr(portfolio_kpis, "overview", kpis)
    with caplog.at_level("INFO", logger="app.sector.warmup"):
        assert warmup_module.warm() is False  # um passo falhou: tenta outra vez mais tarde
    # Etapa 3 (08/10): Carteira → ocorrências → Carga → Previsão → Gantt → KPIs (cada passo lê o anterior).
    assert [(name, sector) for name, sector, _ in calls] == [
        ("carteira", "cantoneiras"), ("ocorrencias", "cantoneiras"), ("carga", "cantoneiras"), ("previsao", "cantoneiras"),
        ("quadro", "cantoneiras"), ("kpis", "cantoneiras"), ("carteira", "perfis"), ("ocorrencias", "perfis"), ("carga", "perfis"),
        ("previsao", "perfis"), ("quadro", "perfis")]
    assert all(not kw.get("allow_stale") for _, _, kw in calls)  # calcula as versões atuais
    text = caplog.text
    assert "cantoneiras" in text and " s" in text and "falhou" in text


def test_warm_up_durations_reach_the_service_log_when_logging_is_not_configured(warmup_module, monkeypatch):
    import logging
    sector = logging.getLogger("app.sector")
    monkeypatch.setattr(logging.getLogger(), "handlers", [])  # como no uvicorn: só os registos dele têm saída
    monkeypatch.setattr(sector, "handlers", [])
    monkeypatch.setattr(sector, "level", logging.NOTSET)
    warmup_module._visible_logs()
    assert len(sector.handlers) == 1 and sector.level == logging.INFO
    warmup_module._visible_logs()
    assert len(sector.handlers) == 1  # uma só vez


def test_warm_up_is_off_in_test_servers_and_when_disabled(warmup_module, monkeypatch):
    assert warmup_module.enabled()
    monkeypatch.setenv("MES_DOSSIER_WORKER_DISABLED", "1")
    assert not warmup_module.enabled()
    monkeypatch.delenv("MES_DOSSIER_WORKER_DISABLED")
    monkeypatch.setenv("MES_PLANNING_WARMUP_DISABLED", "1")
    assert not warmup_module.enabled()
    monkeypatch.delenv("MES_PLANNING_WARMUP_DISABLED")
    monkeypatch.delenv("MES_PLANNING_SELECTION_ENABLED")
    assert not warmup_module.enabled()


def test_warm_up_sectors_can_be_limited_when_memory_is_short(warmup_module, monkeypatch):
    """Por omissão aquece os dois setores; MES_PLANNING_WARMUP_SECTORS=cantoneiras deixa o MTG2 para quando alguém
    o abrir (a meio caminho de MES_PLANNING_WARMUP_DISABLED=1)."""
    assert warmup_module.sectors() == ("cantoneiras", "perfis")
    monkeypatch.setenv("MES_PLANNING_WARMUP_SECTORS", "cantoneiras")
    assert warmup_module.sectors() == ("cantoneiras",)
    monkeypatch.setenv("MES_PLANNING_WARMUP_SECTORS", " perfis , outro ")
    assert warmup_module.sectors() == ("perfis",)
    runs = []
    monkeypatch.setattr(warmup_module, "warm", lambda sectors=None: runs.append(tuple(sectors)) or True)
    stop = threading.Event()
    monkeypatch.setattr(stop, "wait", lambda seconds: True)
    warmup_module._loop(stop, 300)
    assert runs == [("perfis",)]


def test_warm_up_repeats_when_the_day_changes_or_after_a_failure(warmup_module, monkeypatch):
    days, results, runs = iter([date(2026, 10, 7)] * 3 + [date(2026, 10, 8)] * 10), iter([False, True, True]), []
    monkeypatch.setattr(warmup_module, "_today", lambda: next(days))
    monkeypatch.setattr(warmup_module, "warm", lambda sectors=None: runs.append(1) or next(results))
    stop = threading.Event()
    checks = []
    monkeypatch.setattr(stop, "wait", lambda seconds: checks.append(seconds) or len(checks) >= 4)
    warmup_module._loop(stop, 300)
    # 07/10: falhou → volta a tentar; correu bem → espera; 08/10: novo dia → aquece outra vez.
    assert runs == [1, 1, 1]


# --- Rotas: as leituras aceitam a versão anterior; as gravações não

def test_get_endpoints_answer_with_previous_result_while_rebuilding(fake_portfolio, monkeypatch):
    from fastapi.testclient import TestClient
    from app.sector import selection
    from app.web.planning_app import app
    monkeypatch.setenv("MES_PLANNING_SELECTION_ENABLED", "1")
    monkeypatch.setattr(selection, "current", lambda sector, conn=None: {})
    client = TestClient(app)
    assert client.get("/planeamento/api/carteira/opcoes").status_code == 200
    fake_portfolio["generation"], fake_portfolio["release"] = 2, threading.Event()
    started = time.monotonic()
    body = client.get("/planeamento/api/carteira", params={"vista": "referencia"}).json()
    assert body["generation"] == 1 and body["stale"] is True
    assert client.get("/planeamento/api/carteira/opcoes").status_code == 200
    assert time.monotonic() - started < 2  # não esperou pelo cálculo da geração 2
    fake_portfolio["release"].set()
    wait_until(lambda: client.get("/planeamento/api/carteira", params={"vista": "referencia"}).json()["generation"] == 2)


def test_heavy_get_endpoints_pass_allow_stale(monkeypatch):
    from fastapi.testclient import TestClient
    from app.sector import board, portfolio_kpis
    from app.web.planning_app import app
    monkeypatch.setenv("MES_PLANNING_SELECTION_ENABLED", "1")
    seen = {}
    monkeypatch.setattr(board, "board", lambda sector, **kw: seen.setdefault("quadro", kw) and {})
    monkeypatch.setattr(board, "day", lambda sector, day, machine=None, **kw: seen.setdefault("dia", kw) and {})
    monkeypatch.setattr(portfolio_kpis, "overview", lambda sector, **kw: seen.setdefault("kpis", kw) and {})
    client = TestClient(app)
    client.get("/planeamento/api/setor/quadro", params={"setor": "cantoneiras"})
    client.get("/planeamento/api/setor/quadro/dia", params={"setor": "cantoneiras", "dia": "2026-10-07"})
    client.get("/planeamento/api/carteira/kpis", params={"setor": "cantoneiras"})
    assert seen == {"quadro": {"allow_stale": True}, "dia": {"allow_stale": True}, "kpis": {"allow_stale": True}}


def test_load_view_reads_portfolio_and_occurrences_allowing_previous_result(monkeypatch):
    from app.sector import load, occurrences, portfolio, selection
    seen = {}
    monkeypatch.setattr(portfolio, "current", lambda sector, **kw: seen.setdefault("carteira", kw) and {"lines": []})
    monkeypatch.setattr(selection, "current", lambda sector, conn=None: {})
    monkeypatch.setattr(occurrences, "load", lambda sector, **kw: seen.setdefault("ocorrencias", kw) and {"facts": []})
    load._context("cantoneiras")
    assert seen == {"carteira": {"allow_stale": True}, "ocorrencias": {"allow_stale": True}}
