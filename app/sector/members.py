"""Máquinas de cada setor: uma só regra para Definições, Carga e turnos e Gantt (pedido do Luís, 06/10/2026).

Uma máquina pertence a um setor quando o catálogo de recursos da base de pesquisa (cadastro_v2.recursos)
lhe dá a unidade do setor (MTG2 = perfis, MTG3 = cantoneiras) e o tipo máquina ou posto. A área com que
um calendário foi gravado não conta: antes contava e bastava um calendário gravado com o setor errado
para uma máquina de perfis aparecer nas cantoneiras.
"""
from __future__ import annotations

UNIT = {"cantoneiras": "MTG3", "perfis": "MTG2"}
SECTOR_OF_UNIT = {unit: sector for sector, unit in UNIT.items()}
MACHINE_TYPES = ("maquina", "posto")


def rule(by_id: dict, catalog: dict, sector: str) -> set[str]:
    """IDs das máquinas do setor (função pura)."""
    out = set()
    for rid, r in by_id.items():
        meta = catalog.get(r.get("code")) or {}
        if meta.get("unit") == UNIT[sector] and meta.get("type") in MACHINE_TYPES:
            out.add(rid)
    return out


def home_sector(code: str | None, catalog: dict) -> str | None:
    """Setor de uma máquina pelo catálogo; None se não for máquina de nenhum setor."""
    meta = catalog.get(code) or {}
    return SECTOR_OF_UNIT.get(meta.get("unit")) if meta.get("type") in MACHINE_TYPES else None


def members(c, sector: str) -> dict[str, dict]:
    """{id: recurso} das máquinas do setor, com o catálogo de cada uma em `catalog`."""
    from .occurrences import resources_context
    from .portfolio_kpis import catalog as resources_catalog
    _, by_id, _, _, _ = resources_context(c)
    info = resources_catalog(c, sector) if by_id else {}
    return {rid: {**by_id[rid], "catalog": info.get(by_id[rid].get("code")) or {}} for rid in rule(by_id, info, sector)}
