"""Nomes de cada conceito (06/10/2026): lidos de app/web/static/nomes.json, a fonte única usada pelo ecrã.

Os ficheiros partilhados com o MES não importam este módulo; os seus rótulos ficam escritos à mão e o
teste tests/test_naming.py confirma que batem com o JSON.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

PATH = Path(__file__).parent / "web" / "static" / "nomes.json"


@lru_cache(maxsize=1)
def fields() -> dict:
    return json.loads(PATH.read_text(encoding="utf-8"))


def label(key: str) -> str:
    return fields()["campos"][key]["nome"]


def synonyms() -> dict[str, list[str]]:
    return fields()["sinonimos"]
