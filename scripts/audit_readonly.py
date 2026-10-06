"""Ligações só de leitura para auditorias (06/10/2026).

Uso num script de auditoria:
    from scripts.audit_readonly import planning_db, research_db, query
    with planning_db() as c:
        rows = query(c, "SELECT ...", params)

- A transação fica READ ONLY e com tempo limite; qualquer escrita falha no PostgreSQL.
- `query` recusa texto que não comece por SELECT ou WITH.
- Lê o .env do projeto ao ser importado (antes de `import app`), se as variáveis ainda não estiverem definidas.
  Importa este módulo primeiro.
"""
from __future__ import annotations

import os
import re
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_READ = re.compile(r"^\s*(--[^\n]*\n\s*)*(SELECT|WITH)\b", re.I)


def _load_env() -> None:
    env = ROOT / ".env"
    if not env.is_file():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env()  # antes de qualquer `import app...`: app.config lê o ambiente quando é importado


def _guard(c, timeout_ms: int) -> None:
    c.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
    c.execute(f"SET statement_timeout = {int(timeout_ms)}")


@contextmanager
def planning_db(timeout_ms: int = 120_000):
    _load_env()
    import sys
    sys.path.insert(0, str(ROOT))
    from app import planning
    with planning.connect(readonly=True) as c:
        _guard(c, timeout_ms)
        yield c


@contextmanager
def research_db(timeout_ms: int = 120_000):
    _load_env()
    import sys
    sys.path.insert(0, str(ROOT))
    from app.gantt import research
    with research.connect() as c:
        _guard(c, timeout_ms)
        yield c


def query(c, sql: str, params=None) -> list[dict]:
    if not _READ.match(sql):
        raise ValueError("Auditoria só de leitura: só SELECT/WITH.")
    return c.execute(sql, params or ()).fetchall()
