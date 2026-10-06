"""Funções comuns a todos os templates do planeamento (menu _app_nav.html)."""
import os

from fastapi.templating import Jinja2Templates


def _flag(name: str) -> bool:
    return os.getenv(name, "0") == "1"


def install(templates: Jinja2Templates) -> Jinja2Templates:
    templates.env.globals.update(
        raw_enabled=lambda: _flag("MES_PLANNING_RAW_ENABLED"),
        selection_enabled=lambda: _flag("MES_PLANNING_SELECTION_ENABLED"),
        views_enabled=lambda: _flag("MES_PLANNING_FAMILY_VIEWS_ENABLED"),
    )
    return templates
