"""Apply and record the SQL migrations in sql/ (since 28/09/2026).

Every new migration (039 onwards) runs in a single transaction with a lock timeout and is
recorded in planning_mtg.schema_migrations inside that same transaction. Migrations 010–038
were applied by hand before the registry existed; `baseline 038` records them after checking
the live database state.

Usage (from the project root):
  .venv/bin/python scripts/migrate.py status
  .venv/bin/python scripts/migrate.py baseline 038
  .venv/bin/python scripts/migrate.py apply [--dry-run]

By default it talks to the production database through the postgres container
(`docker exec -i postgres psql -U postgres -d dataresearchmtg`); --psql overrides that.
"""
import argparse
import ast
import getpass
import hashlib
import re
import shlex
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PSQL = "docker exec -i postgres psql -U postgres -d dataresearchmtg"
REGISTRY_VERSION = "039"
FILE_RE = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")
TRANSACTION_RE = re.compile(r"^\s*(BEGIN|COMMIT|ROLLBACK|START\s+TRANSACTION)\s*;", re.I | re.M)
LOCK_TIMEOUT = "5s"
BASELINE_NOTE = "linha de base: aplicada à mão antes do registo (28/09/2026)"


class MigrationError(Exception):
    pass


def literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def migrations(sql_dir: Path) -> list[tuple[str, Path, str]]:
    found = {}
    for path in sorted(sql_dir.glob("*.sql")):
        match = FILE_RE.match(path.name)
        if not match:
            continue
        version = match.group(1)
        if version in found:
            raise MigrationError(f"Versão {version} repetida: {found[version][0].name} e {path.name}.")
        found[version] = (path, hashlib.sha256(path.read_bytes()).hexdigest())
    return [(v, p, s) for v, (p, s) in sorted(found.items())]


def psql(prefix: list[str], sql: str, *, single_transaction: bool = False) -> str:
    command = prefix + ["-X", "-q", "-At", "-F", "\t", "-v", "ON_ERROR_STOP=1"]
    if single_transaction:
        command.append("-1")
    result = subprocess.run(command, input=sql, capture_output=True, text=True)
    if result.returncode != 0:
        raise MigrationError(result.stderr.strip() or f"psql terminou com o código {result.returncode}.")
    return result.stdout


def applied(prefix: list[str]) -> dict[str, tuple[str, str]]:
    exists = psql(prefix, "SELECT to_regclass('planning_mtg.schema_migrations') IS NOT NULL;").strip()
    if exists != "t":
        return {}
    rows = psql(prefix, "SELECT version, filename, sha256 FROM planning_mtg.schema_migrations ORDER BY version;")
    return {v: (f, s) for v, f, s in (line.split("\t") for line in rows.splitlines() if line)}


def check_unchanged(files: list[tuple[str, Path, str]], done: dict[str, tuple[str, str]]) -> None:
    by_version = {v: (p, s) for v, p, s in files}
    for version, (filename, sha) in done.items():
        if version not in by_version:
            raise MigrationError(f"A migração {version} ({filename}) está registada mas o ficheiro já não existe.")
        path, current = by_version[version]
        if current != sha:
            raise MigrationError(f"{path.name} mudou depois de aplicada. Crie uma migração nova em vez de a alterar.")


def actor() -> str:
    return f"{getpass.getuser()}@{socket.gethostname()}"


def registry_insert(version: str, path: Path, sha: str, who: str, note: str | None = None) -> str:
    return ("INSERT INTO planning_mtg.schema_migrations (version, filename, sha256, applied_by, note) VALUES ("
            f"{literal(version)}, {literal(path.name)}, {literal(sha)}, {literal(who)}, "
            f"{literal(note) if note else 'NULL'});\n")


def apply(prefix: list[str], sql_dir: Path, *, dry_run: bool = False) -> list[str]:
    files = migrations(sql_dir)
    done = applied(prefix)
    check_unchanged(files, done)
    if not done:
        in_use = psql(prefix, "SELECT to_regclass('planning_mtg.needs') IS NOT NULL;").strip() == "t"
        if in_use:
            raise MigrationError("A base já está em uso mas não tem registo de migrações. "
                                 "Corra primeiro `baseline 038`, que confere o estado e regista 010–038.")
    pending = [(v, p, s) for v, p, s in files if v not in done]
    if not done:  # base nova: só a partir do registo, as anteriores não são desta ferramenta
        pending = [(v, p, s) for v, p, s in pending if v >= REGISTRY_VERSION]
    for version, path, sha in pending:
        body = path.read_text()
        if TRANSACTION_RE.search(body):
            raise MigrationError(f"{path.name} tem BEGIN/COMMIT próprios; a transação é aberta pelo programa.")
    if dry_run:
        return [p.name for _, p, _ in pending]
    who = actor()
    for version, path, sha in pending:
        sql = f"SET LOCAL lock_timeout = {literal(LOCK_TIMEOUT)};\n" + path.read_text() + "\n" + registry_insert(version, path, sha, who)
        psql(prefix, sql, single_transaction=True)
    return [p.name for _, p, _ in pending]


def live_state_problems(prefix: list[str]) -> list[str]:
    """Checks that the live database matches migrations 010–038 before recording them."""
    problems = []
    source = (ROOT / "app/raw/objects.py").read_text()
    kinds_node = next(n for n in ast.parse(source).body
                      if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "KINDS" for t in n.targets))
    expected = set(ast.literal_eval(kinds_node.value))
    definition = psql(prefix, "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                              "WHERE conrelid = to_regclass('planning_mtg.raw_objects') AND conname = 'raw_objects_kind_check';").strip()
    live = set(re.findall(r"'([a-z_]+)'::text", definition))
    if live != expected:
        problems.append(f"Tipos em raw_objects na base {sorted(live)} diferentes do código {sorted(expected)}.")
    function = psql(prefix, "SELECT to_regprocedure('planning_mtg.raw_capacity_detail(jsonb,jsonb)') IS NOT NULL;").strip()
    if function != "t":
        problems.append("Falta a função planning_mtg.raw_capacity_detail da migração 038.")
    return problems


def baseline(prefix: list[str], sql_dir: Path, upto: str) -> list[str]:
    files = migrations(sql_dir)
    done = applied(prefix)
    if done:
        raise MigrationError("O registo já tem migrações; a linha de base só se faz uma vez.")
    base = [(v, p, s) for v, p, s in files if v <= upto]
    registry = [(v, p, s) for v, p, s in files if v == REGISTRY_VERSION]
    if not base or base[-1][0] != upto or not registry or upto >= REGISTRY_VERSION:
        raise MigrationError(f"Linha de base inválida: é preciso {upto} e {REGISTRY_VERSION} em {sql_dir}.")
    problems = live_state_problems(prefix)
    if problems:
        raise MigrationError("O estado da base não confere:\n- " + "\n- ".join(problems))
    who = actor()
    version, path, sha = registry[0]
    sql = f"SET LOCAL lock_timeout = {literal(LOCK_TIMEOUT)};\n" + path.read_text() + "\n"
    sql += "".join(registry_insert(v, p, s, who, BASELINE_NOTE) for v, p, s in base)
    sql += registry_insert(version, path, sha, who)
    psql(prefix, sql, single_transaction=True)
    return [p.name for _, p, _ in base] + [path.name]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--psql", default=DEFAULT_PSQL, help="comando psql para a base (por omissão, a de produção)")
    parser.add_argument("--sql-dir", type=Path, default=ROOT / "sql")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    base = sub.add_parser("baseline")
    base.add_argument("upto")
    run = sub.add_parser("apply")
    run.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    prefix = shlex.split(args.psql)
    try:
        if args.command == "status":
            files, done = migrations(args.sql_dir), applied(prefix)
            check_unchanged(files, done)
            for version, path, _ in files:
                print(f"{version}  {'aplicada ' if version in done else 'PENDENTE '}  {path.name}")
        elif args.command == "baseline":
            for name in baseline(prefix, args.sql_dir, args.upto):
                print(f"registada: {name}")
        else:
            names = apply(prefix, args.sql_dir, dry_run=args.dry_run)
            verb = "por aplicar" if args.dry_run else "aplicada"
            print("\n".join(f"{verb}: {n}" for n in names) or "Nada por aplicar.")
    except MigrationError as error:
        print(f"ERRO: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
