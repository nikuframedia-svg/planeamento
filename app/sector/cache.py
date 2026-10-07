"""Caches das vistas pesadas do setor: resposta logo, recálculo em segundo plano (07/10/2026).

Cada cache guarda, por posição (normalmente o setor), o último resultado e a chave das fontes que o deram.

- Chave igual: devolve o resultado guardado.
- Chave diferente numa leitura que aceita a versão anterior (`allow_stale`): devolve o resultado anterior,
  marcado como antigo (`mark`), e refaz uma única vez em segundo plano (`refresh`); nunca há dois recálculos
  em segundo plano da mesma posição ao mesmo tempo.
- Sem resultado anterior, ou numa gravação (sem `allow_stale`): calcula já. Se outro pedido (ou o recálculo em
  segundo plano) já estiver a calcular a mesma chave, espera por esse cálculo em vez de o repetir.
- Se o último cálculo de uma chave falhou (em segundo plano ou num pedido), a versão anterior deixa de servir
  para essa chave: o pedido seguinte calcula logo e, se voltar a falhar, o erro chega ao utilizador, como antes
  das caches. Uma chave nova volta a receber a versão anterior e a tentar em segundo plano.
- O resultado guardado é sempre o dos dados mais recentes (`rank`, quando a chave diz a idade dos dados) e, com
  dados da mesma idade, o do cálculo começado depois.
- `max_age` (opcional): um resultado mais velho do que isto conta como antigo, mesmo com a mesma chave (para
  fontes que a chave não segue).
- Os recálculos em segundo plano (e o aquecimento) correm um de cada vez em todo o processo (`BACKGROUND`): o
  servidor é partilhado e cada cálculo ocupa 1–2 GB e um núcleo durante 15–40 s; as leituras não esperam por
  eles, recebem a versão anterior. Quando a vez fica livre, passa primeiro a prioridade mais baixa (`priority`).
- Cada recálculo em segundo plano espera `REFRESH_DELAY` antes de ler a chave atual: cada validação do MES
  publica duas gerações planning seguidas e assim só se calcula a segunda (`refresh_delay` muda-o por cache).

As gravações nunca passam `allow_stale`: decidem sempre sobre as versões atuais.
"""
from __future__ import annotations

import heapq
import itertools
import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# Prioridades na vez de fundo: as ocorrências primeiro (a página Máquinas tem os botões parados à espera delas),
# depois as outras caches e, no fim, o aquecimento.
URGENT, NORMAL, WARMUP = 0, 1, 2

# Cada validação do MES publica duas gerações planning (07/10/2026, últimos 7 dias: mediana de 3,6 s entre elas,
# a maioria abaixo de 13 s). Lida a chave 15 s depois, o recálculo apanha logo a segunda.
REFRESH_DELAY = 15.0

FAILED_KEYS_KEPT = 32  # por posição; chega para as chaves de um dia de falhas


class _Turn:
    """A vez de fundo: um cálculo de cada vez em todo o processo. Quando fica livre, passa quem tem a prioridade
    mais baixa e, com a mesma prioridade, quem chegou primeiro.

    Sem ciclos: só os fios de segundo plano a tomam, e um fio só passa a calcular uma chave depois de a tomar;
    um pedido nunca espera por ela.
    """

    def __init__(self):
        self._changed = threading.Condition()
        self._busy = False
        self._queue: list[tuple[int, int]] = []
        self._tickets = itertools.count()

    @contextmanager
    def hold(self, priority: int = NORMAL):
        with self._changed:
            ticket = (priority, next(self._tickets))
            heapq.heappush(self._queue, ticket)
            try:
                while self._busy or self._queue[0] != ticket:
                    self._changed.wait()
            except BaseException:  # quem desiste não pode ficar à frente da fila
                self._queue.remove(ticket)
                heapq.heapify(self._queue)
                self._changed.notify_all()
                raise
            heapq.heappop(self._queue)
            self._busy = True
        try:
            yield
        finally:
            with self._changed:
                self._busy = False
                self._changed.notify_all()

    def waiting(self) -> int:
        """Quantos esperam pela vez (ensaios e diagnóstico)."""
        with self._changed:
            return len(self._queue)


BACKGROUND = _Turn()


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
    def __init__(self, name: str, *, mark=None, max_age: float | None = None, rank=None, priority: int = NORMAL,
                 refresh_delay: float | None = None):
        """`rank(chave)` (opcional) dá a idade dos dados de uma chave, comparável entre chaves (por exemplo
        (dia, geração)): um resultado de dados mais antigos nunca substitui o guardado. `priority`: a vez dos
        recálculos em segundo plano desta cache (URGENT, NORMAL). `refresh_delay`: a espera antes de cada
        recálculo em segundo plano (por omissão, REFRESH_DELAY)."""
        self.name = name
        self._mark = mark or (lambda value: value)
        self.max_age = max_age
        self._rank = rank or (lambda key: 0)
        self.priority = priority
        self.refresh_delay = refresh_delay
        self._lock = threading.Lock()
        self._entries: dict = {}
        self._flights: dict = {}
        self._refreshing: set = set()
        self._failed: dict = {}  # posição → {chave cujo último cálculo falhou: None}, pela ordem das falhas
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
            if (allow_stale and refresh is not None and entry is not None and key not in self._failed.get(slot, ())
                    and (stale_if is None or stale_if(entry.key))):
                self._refresh(slot, key, refresh)
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
                if flight.error is not None:
                    self._remember_failure(slot, key)
                else:
                    self._failed.get(slot, {}).pop(key, None)
                    current = self._entries.get(slot)
                    if current is None or (self._rank(key), flight.order) > (self._rank(current.key), current.order):
                        self._entries[slot] = _Entry(key, flight.value, flight.order, time.monotonic())
            flight.done.set()
        return flight.value

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._failed.clear()

    def _expired(self, entry: _Entry) -> bool:
        return self.max_age is not None and time.monotonic() - entry.built_at >= self.max_age

    def _remember_failure(self, slot, key) -> None:
        """Chamado com o cadeado tomado."""
        failed = self._failed.setdefault(slot, {})
        failed.pop(key, None)
        failed[key] = None
        while len(failed) > FAILED_KEYS_KEPT:
            del failed[next(iter(failed))]

    def _refresh(self, slot, key, refresh) -> None:
        """Um recálculo em segundo plano por posição (chamado com o cadeado tomado). `key` é a chave que o
        pediu: se o recálculo falhar, a versão anterior deixa de servir para ela."""
        if slot in self._refreshing:
            return
        self._refreshing.add(slot)

        def run():
            try:
                time.sleep(REFRESH_DELAY if self.refresh_delay is None else self.refresh_delay)
                with BACKGROUND.hold(self.priority):
                    started = time.monotonic()
                    refresh()
                log.info("%s · %s: atualizado em segundo plano em %.1f s", self.name, slot, time.monotonic() - started)
            except Exception:
                with self._lock:
                    self._remember_failure(slot, key)
                log.exception("%s · %s: o recálculo em segundo plano falhou; o próximo pedido calcula e mostra o erro",
                              self.name, slot)
            finally:
                with self._lock:
                    self._refreshing.discard(slot)

        threading.Thread(target=run, name=f"cache-{self.name}-{slot}", daemon=True).start()
