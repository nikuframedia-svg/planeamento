"""Aviso «há uma versão do Excel no Drive por importar» na Carteira, na Carga e no Gantt simples (08/10).

Até aqui o aviso `newer_available` de raw.workbooks.status() só aparecia no painel de fontes da Tabela; quem
planeava pela Carteira não sabia que o Excel das cantoneiras gravado em SAIDA/ (07/10) ainda não tinha
entrado. Só leitura: duas consultas pequenas, guardadas 60 s por processo (também quando falham, para uma
base indisponível não atrasar cada pedido). Sem observação do Drive ou sem diferença: sem aviso.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime

from .week import LISBON

TTL_SECONDS = 60
LABELS = {"cantoneiras": "MTG3 Cantoneiras", "perfis": "MTG2 Perfis"}

log = logging.getLogger(__name__)
_lock = threading.Lock()
_cache: dict = {}  # {"at": instante, "notices": {setor: texto}}


def _when(value) -> str | None:
    if not value:
        return None
    try:
        moment = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        return moment.strftime("%d/%m %H:%M")
    return moment.astimezone(LISBON).strftime("%d/%m %H:%M")


def notice_of(source: dict) -> str | None:
    """Texto do aviso de um setor a partir de uma entrada de workbooks.status()["sources"]; None sem aviso."""
    if not source.get("newer_available"):
        return None
    drive, imported = source.get("drive") or {}, source.get("imported") or {}
    label = LABELS.get(source.get("area"), source.get("area") or "")
    where = [x for x in (_when(drive.get("remote_modified_at")),
                         f"pasta {source['newer_folder']}" if source.get("newer_folder") else None) if x]
    text = f"O Excel de {label} no Drive é mais recente" + (f" ({', '.join(where)})" if where else "")
    imported_at = _when(imported.get("loaded_at"))
    return text + (f" do que o importado ({imported_at})." if imported_at else " do que o importado.")


def _status() -> dict:
    from ..raw import workbooks
    return workbooks.status()


def text(sector: str) -> str | None:
    """O aviso do setor, ou None. Nunca falha: um erro dá None (e fica registado)."""
    now = time.monotonic()
    with _lock:
        if _cache and now - _cache["at"] < TTL_SECONDS:
            return _cache["notices"].get(sector)
    try:
        notices = {s.get("area"): notice_of(s) for s in (_status().get("sources") or [])}
    except Exception:  # aviso acessório: a página funciona sem ele
        log.debug("Aviso do Excel no Drive indisponível", exc_info=True)
        notices = {}
    with _lock:
        _cache.update(at=now, notices=notices)
    return notices.get(sector)


def clear() -> None:
    with _lock:
        _cache.clear()
