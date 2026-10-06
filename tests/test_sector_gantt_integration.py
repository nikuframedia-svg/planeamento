"""Gantt integrado + vistas por família sobre a mesma base (critérios 7, 16 e 20 do plano de 01/10/2026)."""
from pathlib import Path
import uuid

import psycopg
from psycopg.types.json import Jsonb

from app import planning
from app.gantt import integrated, research, service
from app.sector import capacity, needs_view, occurrences
from tests.test_integrated_gantt import integrated_db, row  # noqa: F401  (fixture)
from tests.test_planning_raw import database, canonical, registry, postgres16  # noqa: F401
from tests.test_raw_workspace import workspace  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def with_views(dsn):
    with psycopg.connect(dsn) as c:
        if not c.execute("SELECT to_regclass('planning_mtg.sector_machine_decisions')").fetchone()[0]:
            c.execute((ROOT / "sql/045_sector_needs_views.sql").read_text())
        c.execute("TRUNCATE planning_mtg.sector_machine_decision_history, planning_mtg.sector_machine_decisions, "
                  "planning_mtg.sector_machine_actions, planning_mtg.sector_priority_overrides CASCADE")
    occurrences.invalidate()


def test_mtg3_operation_is_prioritised_by_cut_date_in_the_engine(integrated_db):
    with_views(integrated_db)
    op = service.operations()["operations"][0]
    assert op["priority"]["priority_field"] == "cut_date" and op["priority"]["priority_scope"] == "operation"
    assert op["deadline"] == "2026-09-23T00:00:00+01:00" and op["priority_group"] == 1
    with planning.connect() as c:
        before = integrated.references(c)
        c.execute("""INSERT INTO planning_mtg.sector_priority_overrides(area,production_order_no,reference,id,definition,reason,actor)
            VALUES ('cantoneiras','OF100','*',%s,%s,'Antecipar','teste')""", (uuid.uuid4(), Jsonb({"due_date": "2026-09-30", "applies_to": "principal"})))
    with planning.connect() as c:
        assert integrated.references(c) != before  # a scenario computed before becomes stale
    changed = service.operations()["operations"][0]
    assert changed["priority"]["priority_source"] == "Substituição manual" and changed["deadline"].startswith("2026-10-01T00:00")


def test_sector_machine_decision_reaches_gantt_and_needs_view(integrated_db):
    with_views(integrated_db)
    xpt6 = research.resource_id("XPT6")
    _, signature = integrated.identity(row())
    action = uuid.uuid4()
    with planning.connect() as c:
        c.execute("""INSERT INTO planning_mtg.sector_machine_actions(id,request_id,area,mode,resource_id,reason,actor,scope,versions,summary)
            VALUES (%s,%s,'cantoneiras','assign',%s,'Ferramentas na XP T6','teste','{}','{}','{}')""", (action, uuid.uuid4(), xpt6))
        c.execute("""INSERT INTO planning_mtg.sector_machine_decisions(area,occurrence_key,production_order_no,reference,operation_code,
            occurrence,technical_signature,mode,resource_id,reason,scope_level,action_id,actor)
            VALUES ('cantoneiras','OF100|PART|CPIS:112|1','OF100','PART','CPIS:112',1,%s,'assign',%s,'Ferramentas na XP T6',2,%s,'teste')""",
                  (signature, xpt6, action))
    op = service.operations()["operations"][0]
    assert op["assignment"]["mode"] == "manual" and op["assignment"]["resource_id"] == xpt6
    assert op["assignment"]["sector_decision"]["source"] == "occurrence"
    assert "Decisão do setor" in op["assignment"]["reason"]
    view = needs_view.view({"areas": ["cantoneiras"], "preset": "maquinas"})
    assert [g["key"] for g in view["rows"]] == ["XPT6"]  # machine name as published for the resource
    fact = occurrences.load("cantoneiras")["facts"][0]
    assert fact["key"] == op["key"] and fact["decision"]["mode"] == "assign"
    # Changing the variant's signature never carries the decision over.
    with planning.connect() as c:
        c.execute("UPDATE planning_mtg.sector_machine_decisions SET technical_signature='outra-variante'")
    op = service.operations()["operations"][0]
    assert op["assignment"]["mode"] == "automatic"
    assert "Decisão de máquina gravada para outra variante técnica; rever no setor." in op["blocking_reasons"]


def test_needs_view_capacity_and_gantt_use_the_same_occurrence(integrated_db):
    with_views(integrated_db)
    gantt = service.operations()["operations"]
    facts = occurrences.load("cantoneiras")["facts"]
    assert {f["key"] for f in facts} == {o["key"] for o in gantt}
    view = capacity.view(["cantoneiras"], horizon_weeks=4)
    unit = view["units"]["cantoneiras"]
    assert unit["periods"][0]["capacity_status"] == "por_confirmar"
    assert unit["backlog"]["balance"]["deficit_hours"] is None and view["mode"] == "needs"
