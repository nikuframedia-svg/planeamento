"""Aquecimento das caches do setor ao arrancar e no início de cada dia (07/10/2026).

Depois de o serviço arrancar, um fio em segundo plano calcula, para os dois setores (MTG3 primeiro), o mesmo
que as páginas pedem: Carteira, ocorrências, Gantt simples, Carga e KPIs. O primeiro utilizador já não espera
pelos 25–30 s de cada cache fria. As caches são por dia: de 5 em 5 minutos o fio vê se o dia mudou (ou se o
último aquecimento falhou) e volta a aquecer. Um só aquecimento por processo; nada é gravado; um pedido que
chegue a meio espera pelo mesmo cálculo em vez de o repetir (cache.py).

Desligado quando os trabalhos de fundo do processo estão desligados (MES_DOSSIER_WORKER_DISABLED=1, como nos
servidores de ensaio), com MES_PLANNING_WARMUP_DISABLED=1, ou com a Carteira desligada.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import date

log = logging.getLogger(__name__)

SECTORS = ("cantoneiras", "perfis")
CHECK_SECONDS = 300
ATTEMPTS_PER_DAY = 3  # um passo que falha sempre não volta a correr de 5 em 5 minutos o dia inteiro

_lock = threading.Lock()
_stop: threading.Event | None = None


def enabled() -> bool:
    from .routes import enabled as carteira
    return (carteira() and os.environ.get("MES_DOSSIER_WORKER_DISABLED") != "1"
            and os.environ.get("MES_PLANNING_WARMUP_DISABLED") != "1")


def _steps(sector: str):
    from . import board, load, occurrences, portfolio, portfolio_kpis
    return (("Carteira", lambda: portfolio.current(sector)),
            ("ocorrências", lambda: occurrences.load(sector)),
            ("Gantt simples", lambda: board.board(sector)),
            ("Carga", lambda: load.overview(sector)),
            ("KPIs", lambda: portfolio_kpis.overview(sector)))


def warm(sectors=SECTORS) -> bool:
    """Calcula as versões atuais das caches de cada setor e regista a duração de cada passo; True se tudo correu bem."""
    ok = True
    for sector in sectors:
        started = time.monotonic()
        for label, step in _steps(sector):
            began = time.monotonic()
            try:
                step()
                log.info("Aquecimento %s · %s: %.1f s", sector, label, time.monotonic() - began)
            except Exception:
                ok = False
                log.exception("Aquecimento %s · %s falhou ao fim de %.1f s", sector, label, time.monotonic() - began)
        log.info("Aquecimento %s: %.1f s no total", sector, time.monotonic() - started)
    return ok


def _today() -> date:
    return date.today()  # o mesmo dia das chaves das caches (portfolio, occurrences)


def _loop(stop: threading.Event, check_seconds: float) -> None:
    done, failures = None, 0
    while True:
        day = _today()
        if day != done:
            if warm() or failures + 1 >= ATTEMPTS_PER_DAY:
                done, failures = day, 0
            else:
                failures += 1
        if stop.wait(check_seconds):
            return


def start(*, check_seconds: float = CHECK_SECONDS) -> threading.Event | None:
    """Arranca o aquecimento uma só vez por processo e volta logo (nunca atrasa o arranque).

    Devolve o evento que o para, ou None se já estava a correr.
    """
    global _stop
    with _lock:
        if _stop is not None:
            return None
        _stop = threading.Event()
        stop = _stop
    threading.Thread(target=_loop, args=(stop, check_seconds), name="aquecimento-setor", daemon=True).start()
    log.info("Aquecimento das caches do setor iniciado em segundo plano")
    return stop


def _reset() -> None:
    """Ensaios: para o aquecimento em curso e permite outro."""
    global _stop
    with _lock:
        if _stop is not None:
            _stop.set()
        _stop = None
