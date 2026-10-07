"""Máquinas de cada setor: uma só regra para Definições, Carga e turnos e Gantt (pedido do Luís, 06/10/2026).

Uma máquina pertence a um setor quando o catálogo de recursos da base de pesquisa (cadastro_v2.recursos)
lhe dá a unidade do setor (MTG2 = perfis, MTG3 = cantoneiras) e o tipo máquina ou posto. A área com que
um calendário foi gravado não conta: antes contava e bastava um calendário gravado com o setor errado
para uma máquina de perfis aparecer nas cantoneiras.

Desde 07/10/2026 a mesma regra substitui a caixa «confirmada»: qualquer máquina do setor tem calendários,
taxas, horários no Gantt, histórico e horas reais (`resource_ids`, usada pelo código partilhado com o MES).
"""
from __future__ import annotations

UNIT = {"cantoneiras": "MTG3", "perfis": "MTG2"}
SECTOR_OF_UNIT = {unit: sector for sector, unit in UNIT.items()}
MACHINE_TYPES = ("maquina", "posto")


def is_machine(unit: str | None, kind: str | None) -> bool:
    """Máquina de um setor: unidade MTG2/MTG3 e tipo máquina ou posto no catálogo (função pura)."""
    return unit in SECTOR_OF_UNIT and kind in MACHINE_TYPES


def rule(by_id: dict, catalog: dict, sector: str) -> set[str]:
    """IDs das máquinas do setor (função pura)."""
    out = set()
    for rid, r in by_id.items():
        meta = catalog.get(r.get("code")) or {}
        if meta.get("unit") == UNIT[sector] and is_machine(meta.get("unit"), meta.get("type")):
            out.add(rid)
    return out


def home_sector(code: str | None, catalog: dict) -> str | None:
    """Setor de uma máquina pelo catálogo; None se não for máquina de nenhum setor."""
    meta = catalog.get(code) or {}
    return SECTOR_OF_UNIT[meta["unit"]] if is_machine(meta.get("unit"), meta.get("type")) else None


def resource_ids(c, resources: list[dict]) -> set[str]:
    """IDs dos recursos gravados (raw_objects kind='resource') que o catálogo dá como máquina de um setor.

    Desde 07/10/2026 é isto que conta para calendários, taxas, histórico e horas reais (a caixa «confirmada» saiu).
    A identidade é a do Gantt (integrated._resources): o código do catálogo gravado no recurso ou um nome em comum.
    Com a camada de pesquisa desligada não há catálogo: nenhum. Ligada mas sem importação utilizável, o erro 503
    sobe (como em research.overlay_rows): melhor parar o cálculo do que contar as máquinas à antiga sem avisar.
    """
    from datetime import datetime, timezone
    from ..gantt import research, integrated
    if not resources or not research.enabled():
        return set()
    metadata = research.load(c)["metadata"]
    now = datetime.now(timezone.utc)
    _, by_id = integrated._resources(metadata, [r for r in resources if r["kind"] == "resource"], now, now)
    stored = {str(r["id"]) for r in resources}
    catalog = {r["codigo"]: {"unit": r.get("setor"), "type": r.get("tipo")} for r in metadata.get("resources", [])}
    return {rid for sector in UNIT for rid in rule(by_id, catalog, sector) if rid in stored}


def members(c, sector: str) -> dict[str, dict]:
    """{id: recurso} das máquinas do setor, com o catálogo de cada uma em `catalog`."""
    from .occurrences import resources_context
    from .portfolio_kpis import catalog as resources_catalog
    _, by_id, _, _, _ = resources_context(c)
    info = resources_catalog(c, sector) if by_id else {}
    return {rid: {**by_id[rid], "catalog": info.get(by_id[rid].get("code")) or {}} for rid in rule(by_id, info, sector)}
