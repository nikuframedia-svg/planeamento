"""Caches das vistas pesadas do setor: resposta logo, recálculo em segundo plano (07/10/2026).

Cada cache guarda, por posição (normalmente o setor), o último resultado e a chave das fontes que o deram.

- Chave igual: devolve o resultado guardado.
- Chave diferente numa leitura que aceita a versão anterior (`allow_stale`): devolve o resultado anterior,
  marcado como antigo (`mark`), e refaz uma única vez em segundo plano (`refresh`); nunca há dois recálculos
  em segundo plano da mesma posição ao mesmo tempo.
- Sem resultado anterior, ou numa gravação (sem `allow_stale`): calcula já. Se outro pedido (ou o recálculo em
  segundo plano) já estiver a calcular a mesma chave, espera por esse cálculo em vez de o repetir.
- Um cálculo começado antes nunca substitui um começado depois: o resultado guardado é sempre o mais recente.
- `max_age` (opcional): um resultado mais velho do que isto conta como antigo, mesmo com a mesma chave (para
  fontes que a chave não segue).
- Os recálculos em segundo plano (e o aquecimento) correm um de cada vez em todo o processo (`BACKGROUND`): o
  servidor é partilhado e cada cálculo ocupa 1–2 GB e um núcleo durante 15–40 s; as leituras não esperam por
  eles, recebem a versão anterior.

As gravações nunca passam `allow_stale`: decidem sempre sobre as versões atuais.
"""
from __future__ import annotations

import itertools
import logging
import threading
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# Sem ciclos: só os fios de segundo plano o tomam, e um fio só passa a calcular uma chave depois de o tomar;
# um pedido nunca espera por ele.
BACKGROUND = threading.BoundedSemaphore(1)


@dataclass
class _Entry:
    key: object
    value: object
    order: int
    built_at: float
    marked: object = None


@dataclass
class _Flight:
    order: int
    done: threading.Event = field(default_factory=threading.Event)
    value: object = None
    error: BaseException | None = None


class Cache:
    def __init__(self, name: str, *, mark=None, max_age: float | None = None):
        self.name = name
        self._mark = mark or (lambda value: value)
        self.max_age = max_age
        self._lock = threading.Lock()
        self._entries: dict = {}
        self._flights: dict = {}
        self._refreshing: set = set()
        self._order = itertools.count()

    def get(self, slot, key, build, *, allow_stale: bool = False, refresh=None, stale_if=None):
        """O valor da chave `key` na posição `slot`.

        `build()` calcula o valor desta chave. `refresh()` refaz em segundo plano: volta a ler a chave atual e
        chama `get` sem `allow_stale`. `stale_if(chave_guardada)` diz se o resultado guardado ainda pode servir
        de versão anterior (por exemplo, só se for do mesmo dia).
        """
        with self._lock:
            entry = self._entries.get(slot)
            if entry is not None and entry.key == key and not self._expired(entry):
                return entry.value
            if allow_stale and refresh is not None and entry is not None and (stale_if is None or stale_if(entry.key)):
                self._refresh(slot, refresh)
                if entry.marked is None:
                    entry.marked = self._mark(entry.value)
                return entry.marked
            flight = self._flights.get((slot, key))
            owner = flight is None
            if owner:
                flight = self._flights[(slot, key)] = _Flight(next(self._order))
        if not owner:
            flight.done.wait()
            if flight.error is not None:
                raise flight.error
            return flight.value
        try:
            flight.value = build()
        except BaseException as exc:
            flight.error = exc
            raise
        finally:
            with self._lock:
                del self._flights[(slot, key)]
                current = self._entries.get(slot)
                if flight.error is None and (current is None or current.order < flight.order):
                    self._entries[slot] = _Entry(key, flight.value, flight.order, time.monotonic())
            flight.done.set()
        return flight.value

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def _expired(self, entry: _Entry) -> bool:
        return self.max_age is not None and time.monotonic() - entry.built_at >= self.max_age

    def _refresh(self, slot, refresh) -> None:
        """Um recálculo em segundo plano por posição (chamado com o cadeado tomado)."""
        if slot in self._refreshing:
            return
        self._refreshing.add(slot)

        def run():
            try:
                with BACKGROUND:
                    started = time.monotonic()
                    refresh()
                log.info("%s · %s: atualizado em segundo plano em %.1f s", self.name, slot, time.monotonic() - started)
            except Exception:  # fica o resultado anterior; o próximo pedido volta a tentar
                log.exception("%s · %s: o recálculo em segundo plano falhou", self.name, slot)
            finally:
                with self._lock:
                    self._refreshing.discard(slot)

        threading.Thread(target=run, name=f"cache-{self.name}-{slot}", daemon=True).start()
