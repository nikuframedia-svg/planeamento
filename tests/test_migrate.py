"""scripts/migrate.py against a disposable PostgreSQL 16 (one database per test)."""
import importlib.util
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("migrate", ROOT / "scripts/migrate.py")
migrate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migrate)

KINDS_SQL = ", ".join(f"'{k}'::text" for k in sorted(
    ["view", "formula", "format", "resource", "calendar", "rate", "conversation",
     "analysis", "period", "week_reference", "worked_hours", "gantt"]))


@pytest.fixture(scope="module")
def container():
    if shutil.which("docker") is None:
        pytest.skip("docker indisponível")
    name = f"planning-migrate-{uuid.uuid4().hex[:10]}"
    subprocess.run(["docker", "run", "-d", "--rm", "--name", name, "-e", f"POSTGRES_PASSWORD={uuid.uuid4().hex}",
                    "postgres:16-alpine"], check=True, capture_output=True)
    try:
        deadline = time.monotonic() + 60
        while subprocess.run(["docker", "exec", name, "pg_isready", "-U", "postgres"], capture_output=True).returncode:
            if time.monotonic() > deadline:
                raise RuntimeError("PostgreSQL de teste não arrancou")
            time.sleep(0.5)
        time.sleep(1)
        yield name
    finally:
        subprocess.run(["docker", "stop", name], capture_output=True)


@pytest.fixture()
def prefix(container):
    db = f"t_{uuid.uuid4().hex[:8]}"
    subprocess.run(["docker", "exec", container, "createdb", "-U", "postgres", db], check=True, capture_output=True)
    return ["docker", "exec", "-i", container, "psql", "-U", "postgres", "-d", db]


def sql_dir(tmp_path, **files):
    folder = tmp_path / "sql"
    folder.mkdir()
    shutil.copy(ROOT / "sql/039_schema_migrations.sql", folder)
    for name, body in files.items():
        (folder / f"{name}.sql").write_text(body)
    return folder


def scalar(prefix, sql):
    return migrate.psql(prefix, sql).strip()


def test_apply_bootstraps_registry_and_is_idempotent(prefix, tmp_path):
    folder = sql_dir(tmp_path, **{"040_demo": "CREATE TABLE planning_mtg.demo (x int);"})
    assert migrate.apply(prefix, folder) == ["039_schema_migrations.sql", "040_demo.sql"]
    assert set(migrate.applied(prefix)) == {"039", "040"}
    assert scalar(prefix, "SELECT to_regclass('planning_mtg.demo') IS NOT NULL;") == "t"
    assert migrate.apply(prefix, folder) == []


def test_changed_migration_is_refused(prefix, tmp_path):
    folder = sql_dir(tmp_path, **{"040_demo": "CREATE TABLE planning_mtg.demo (x int);"})
    migrate.apply(prefix, folder)
    (folder / "040_demo.sql").write_text("CREATE TABLE planning_mtg.demo (x bigint);")
    with pytest.raises(migrate.MigrationError, match="mudou depois de aplicada"):
        migrate.apply(prefix, folder)


def test_failed_migration_rolls_back_and_is_not_recorded(prefix, tmp_path):
    folder = sql_dir(tmp_path, **{"040_broken": "CREATE TABLE planning_mtg.half (x int);\nSELECT 1/0;"})
    with pytest.raises(migrate.MigrationError):
        migrate.apply(prefix, folder)
    assert scalar(prefix, "SELECT to_regclass('planning_mtg.half') IS NULL;") == "t"
    assert "040" not in migrate.applied(prefix)


def test_explicit_transaction_is_refused(prefix, tmp_path):
    folder = sql_dir(tmp_path, **{"040_tx": "BEGIN;\nCREATE TABLE planning_mtg.t (x int);\nCOMMIT;"})
    with pytest.raises(migrate.MigrationError, match="BEGIN/COMMIT"):
        migrate.apply(prefix, folder)
    assert migrate.applied(prefix) == {}


def test_database_in_use_requires_baseline(prefix, tmp_path):
    migrate.psql(prefix, "CREATE SCHEMA planning_mtg; CREATE TABLE planning_mtg.needs (id int);")
    with pytest.raises(migrate.MigrationError, match="baseline 038"):
        migrate.apply(prefix, sql_dir(tmp_path))


def live_like(prefix, kinds_sql=KINDS_SQL):
    migrate.psql(prefix, f"""
        CREATE SCHEMA planning_mtg;
        CREATE TABLE planning_mtg.needs (id int);
        CREATE TABLE planning_mtg.raw_objects (kind text CONSTRAINT raw_objects_kind_check CHECK (kind = ANY (ARRAY[{kinds_sql}])));
        CREATE FUNCTION planning_mtg.raw_capacity_detail(jsonb, jsonb) RETURNS jsonb LANGUAGE sql AS 'SELECT $1';
    """)


def test_baseline_checks_live_state_and_records_everything(prefix):
    live_like(prefix)
    names = migrate.baseline(prefix, ROOT / "sql", "038")
    assert names[0].startswith("010_") and names[-2].startswith("038_") and names[-1] == "039_schema_migrations.sql"
    done = migrate.applied(prefix)
    assert set(done) == {f"{v:03d}" for v in range(10, 40)}
    assert migrate.apply(prefix, ROOT / "sql", dry_run=True) == [
        p.name for v, p, _ in migrate.migrations(ROOT / "sql") if v > "039"]
    with pytest.raises(migrate.MigrationError, match="só se faz uma vez"):
        migrate.baseline(prefix, ROOT / "sql", "038")


def test_baseline_refuses_a_database_that_does_not_match(prefix):
    live_like(prefix, kinds_sql=", ".join(f"'{k}'::text" for k in ["view", "formula"]))
    with pytest.raises(migrate.MigrationError, match="não confere"):
        migrate.baseline(prefix, ROOT / "sql", "038")
    assert migrate.applied(prefix) == {}
