"""Chaves das caches do setor numa base PostgreSQL descartável (07/10/2026).

- Uma nova exportação do OCR original (original:*) não muda nenhuma chave: nenhuma destas vistas a lê.
- As ocorrências de um setor não se refazem com um Planear ou «Atribuir máquina» no outro setor.
"""
import uuid
from datetime import date
from pathlib import Path

import psycopg

from app import planning
from app.raw import projection
from app.sector import board, occurrences, portfolio
from tests.test_integrated_gantt import integrated_db  # noqa: F401  (fixture)
from tests.test_planning_raw import database, canonical, registry, postgres16  # noqa: F401
from tests.test_raw_workspace import workspace  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 10, 7)


def keys():
    with planning.connect(readonly=True) as c:
        return {"ocorrencias": occurrences.stamp(c, "cantoneiras", TODAY),
                "carteira": portfolio._stamp(c, "cantoneiras", TODAY)[0]}


def with_member_machine(dsn):
    with psycopg.connect(dsn) as c:
        if not c.execute("SELECT to_regclass('planning_mtg.sector_member_machine')").fetchone()[0]:
            c.execute((ROOT / "sql/048_family_sets_member_machine.sql").read_text())
        c.execute("TRUNCATE planning_mtg.sector_member_machine, planning_mtg.sector_family_sets")


def test_a_new_ocr_original_export_changes_no_cache_key(integrated_db):
    before, sources = keys(), board._sources("cantoneiras")
    with planning.connect() as c:
        for version in (1, 2):  # duas versões da exportação, como a cada 3 minutos num dia de trabalho
            projection.publish(c, "original:cantoneiras", f"export-{version}", [
                {"key": "original:1:1:0", "values": {"of": "OF100", "quantity": 3}, "area": "cantoneiras",
                 "source_export": {"version": version}}], {})
    assert keys() == before
    assert board._sources("cantoneiras") == sources


def test_decisions_of_the_other_sector_do_not_rebuild_these_occurrences(integrated_db):
    with_member_machine(integrated_db)
    before = keys()
    with planning.connect() as c:
        c.execute("""INSERT INTO planning_mtg.sector_member_selection(area, member_key, production_order_no, reference, decision,
            actor, request_id) VALUES ('perfis', 'macro:outro', 'OF900', 'P1', 'selected', 'teste', %s)""", (uuid.uuid4(),))
        c.execute("""INSERT INTO planning_mtg.sector_member_machine(area, member_key, production_order_no, reference, resource_id,
            machine_name, actor, request_id) VALUES ('perfis', 'macro:outro', 'OF900', 'P1', 'r1', 'Serrote', 'teste', %s)""", (uuid.uuid4(),))
    assert keys() == before
    with planning.connect() as c:  # o mesmo no próprio setor refaz
        c.execute("""INSERT INTO planning_mtg.sector_member_selection(area, member_key, production_order_no, reference, decision,
            actor, request_id) VALUES ('cantoneiras', 'macro:line', 'OF100', 'PART', 'selected', 'teste', %s)""", (uuid.uuid4(),))
    assert keys()["ocorrencias"] != before["ocorrencias"]
    with planning.connect() as c:
        c.execute("""INSERT INTO planning_mtg.sector_member_machine(area, member_key, production_order_no, reference, resource_id,
            machine_name, actor, request_id) VALUES ('cantoneiras', 'macro:line', 'OF100', 'PART', 'r2', 'XP T6', 'teste', %s)""", (uuid.uuid4(),))
    after = keys()["ocorrencias"]
    with planning.connect() as c:
        c.execute("DELETE FROM planning_mtg.sector_member_machine WHERE area = 'cantoneiras'")
    assert keys()["ocorrencias"] != after
