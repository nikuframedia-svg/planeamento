"""Fila durável, extrações originais e necessidades preparadas (SQLite local).

Apenas o conector CPIS lê PostgreSQL. Nenhuma extração altera produção realizada.
"""
from __future__ import annotations

import hashlib
import functools
import json
import os
import sqlite3
import tempfile
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from ..config import settings
from . import DossierError
from . import locking
from .models import need_key, specification, filename_order
from .pdf import MAX_BYTES, inspect_pdf

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
 id TEXT PRIMARY KEY, sha256 TEXT UNIQUE NOT NULL, filename TEXT NOT NULL,
 page_count INTEGER NOT NULL, status TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
 progress_label TEXT NOT NULL DEFAULT '', error TEXT,
 production_order TEXT, context_json TEXT NOT NULL DEFAULT '{}',
 issues_json TEXT NOT NULL DEFAULT '[]', model_json TEXT NOT NULL DEFAULT '{}',
 revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS checkpoints (
 document_id TEXT NOT NULL REFERENCES documents(id), stage TEXT NOT NULL,
 item_key TEXT NOT NULL, data_json TEXT NOT NULL, created_at TEXT NOT NULL,
 run_id TEXT, input_fingerprint TEXT,
 PRIMARY KEY(document_id,stage,item_key)
);
CREATE TABLE IF NOT EXISTS checkpoint_history (
 id INTEGER PRIMARY KEY AUTOINCREMENT, document_id TEXT NOT NULL, stage TEXT NOT NULL,
 item_key TEXT NOT NULL, data_json TEXT NOT NULL, run_id TEXT, input_fingerprint TEXT,
 archived_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pieces (
 id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
 source_key TEXT NOT NULL, machine_group TEXT NOT NULL, index_page INTEGER NOT NULL,
 index_ref TEXT NOT NULL, drawing_pages_json TEXT NOT NULL,
 raw_json TEXT NOT NULL, values_json TEXT NOT NULL,
 selection_json TEXT NOT NULL DEFAULT '{}',
 issues_json TEXT NOT NULL DEFAULT '[]', match_json TEXT NOT NULL DEFAULT '{}',
 reviewed_json TEXT NOT NULL DEFAULT '{}', state TEXT NOT NULL DEFAULT 'review',
 revision INTEGER NOT NULL DEFAULT 1,
 UNIQUE(document_id,source_key)
);
CREATE TABLE IF NOT EXISTS needs (
 identity TEXT PRIMARY KEY, piece_id TEXT UNIQUE NOT NULL REFERENCES pieces(id),
 production_order TEXT NOT NULL, specification TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, document_id TEXT NOT NULL REFERENCES documents(id),
 piece_id TEXT, actor TEXT NOT NULL, action TEXT NOT NULL, data_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inbox_files (
 path TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
 document_id TEXT, error TEXT, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS service_state (
 name TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS processing_runs (
 id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
 signature TEXT NOT NULL, status TEXT NOT NULL, config_json TEXT NOT NULL,
 error_kind TEXT, error_message TEXT, created_at TEXT NOT NULL, completed_at TEXT
);
CREATE TABLE IF NOT EXISTS model_attempts (
 id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT REFERENCES processing_runs(id),
 document_id TEXT NOT NULL REFERENCES documents(id), stage TEXT NOT NULL,
 item_key TEXT NOT NULL, attempt INTEGER NOT NULL, status TEXT NOT NULL,
 metadata_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS exports (
 id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
 source_sha256 TEXT NOT NULL, summary_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS export_proposals (
 id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
 source_sha256 TEXT NOT NULL, summary_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS need_identity_history (
 id INTEGER PRIMARY KEY AUTOINCREMENT, old_identity TEXT NOT NULL,
 new_identity TEXT NOT NULL, piece_id TEXT NOT NULL, specification TEXT NOT NULL,
 migrated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS documents_status ON documents(status,created_at);
CREATE INDEX IF NOT EXISTS pieces_document ON pieces(document_id);
CREATE INDEX IF NOT EXISTS events_document ON events(document_id,id);
CREATE INDEX IF NOT EXISTS attempts_document ON model_attempts(document_id,id);
CREATE INDEX IF NOT EXISTS runs_document ON processing_runs(document_id,created_at);
"""

_thread_state = threading.local()
_locks = {}
_locks_guard = threading.Lock()


@contextmanager
def document_lock(uid):
    try:
        uuid.UUID(str(uid))
    except ValueError:
        raise DossierError("Dossiê não encontrado.", 404) from None
    held = getattr(_thread_state, "held", set())
    if uid in held:
        yield
        return
    with _locks_guard:
        thread_lock = _locks.setdefault(uid, threading.Lock())
    if not thread_lock.acquire(blocking=False):
        raise DossierError("Este dossiê está a ser atualizado. Aguarda e tenta novamente.", 409)
    try:
        directory = root() / "locks"
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / f"{uid}.lock").open("a") as lock:
            try:
                locking.acquire(lock)
            except BlockingIOError:
                raise DossierError("Este dossiê está a ser atualizado. Aguarda e tenta novamente.", 409) from None
            _thread_state.held = held | {uid}
            try:
                yield
            finally:
                _thread_state.held = held
                locking.release(lock)
    finally:
        thread_lock.release()


def guarded(function):
    @functools.wraps(function)
    def call(uid, *args, **kwargs):
        with document_lock(uid):
            return function(uid, *args, **kwargs)
    return call


def root() -> Path:
    return settings.data_dir / "dossiers"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


@contextmanager
def connect():
    directory = root()
    directory.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(directory / "dossiers.db", timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(checkpoints)")}
    for name in ("run_id", "input_fingerprint"):
        if name not in columns:
            conn.execute(f"ALTER TABLE checkpoints ADD COLUMN {name} TEXT")
    piece_columns = {row[1] for row in conn.execute("PRAGMA table_info(pieces)")}
    if "selection_json" not in piece_columns:
        conn.execute("ALTER TABLE pieces ADD COLUMN selection_json TEXT NOT NULL DEFAULT '{}'")
    _migrate_need_identities(conn)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _migrate_need_identities(conn):
    marker = conn.execute("SELECT 1 FROM service_state WHERE name='need_identity_v2'").fetchone()
    if marker:
        return
    rows = conn.execute("""SELECT n.*,p.machine_group,p.values_json,p.document_id
        FROM needs n JOIN pieces p ON p.id=n.piece_id ORDER BY n.updated_at DESC""").fetchall()
    groups = {}
    for row in rows:
        values = json.loads(row["values_json"])
        current = need_key(row["production_order"], row["machine_group"], values)
        groups.setdefault(current, []).append(row)
        conn.execute("INSERT INTO need_identity_history(old_identity,new_identity,piece_id,specification,migrated_at) VALUES (?,?,?,?,?)",
                     (row["identity"], current, row["piece_id"], row["specification"], now()))
    for identity, group in groups.items():
        conn.execute("DELETE FROM needs WHERE identity IN (%s)" % ",".join("?" * len(group)),
                     tuple(r["identity"] for r in group))
        specifications = {r["specification"] for r in group}
        if len(specifications) == 1:
            winner = group[0]
            conn.execute("""INSERT INTO needs(identity,piece_id,production_order,specification,revision,updated_at)
                VALUES (?,?,?,?,?,?)""", (identity, winner["piece_id"], winner["production_order"],
                winner["specification"], winner["revision"], winner["updated_at"]))
            for duplicate in group[1:]:
                conn.execute("UPDATE pieces SET state='duplicate' WHERE id=?", (duplicate["piece_id"],))
        else:
            for conflict in group:
                conn.execute("UPDATE pieces SET state='review' WHERE id=?", (conflict["piece_id"],))
                conn.execute("UPDATE documents SET status='review',updated_at=? WHERE id=?",
                             (now(), conflict["document_id"]))
    conn.execute("INSERT INTO service_state(name,value_json,updated_at) VALUES ('need_identity_v2','{}',?)",
                 (now(),))


def _document(conn, uid):
    row = conn.execute("SELECT * FROM documents WHERE id=?", (uid,)).fetchone()
    if not row:
        raise DossierError("Dossiê não encontrado.", 404)
    return row


def decode(row):
    data = dict(row)
    for key in list(data):
        if key.endswith("_json"):
            data[key[:-5]] = json.loads(data.pop(key))
    return data


def event(conn, document_id, action, data, *, piece_id=None, actor="sistema"):
    conn.execute("INSERT INTO events(document_id,piece_id,actor,action,data_json,created_at) VALUES (?,?,?,?,?,?)",
                 (document_id, piece_id, actor, action, dump(data), now()))


def ingest(data: bytes, filename: str, *, configured=False) -> dict:
    filename = str(filename or "dossie.pdf").replace("\\", "/").rsplit("/", 1)[-1][:200]
    if not filename.lower().endswith(".pdf") or not data.lstrip()[:5] == b"%PDF-":
        raise DossierError("Seleciona um ficheiro PDF válido.")
    if len(data) > MAX_BYTES:
        raise DossierError("O limite por PDF é 80 MB.", 413)
    digest = hashlib.sha256(data).hexdigest()
    with connect() as conn:
        existing = conn.execute("SELECT id,filename FROM documents WHERE sha256=?", (digest,)).fetchone()
        if existing:
            if filename_order(filename) and filename_order(existing["filename"]) and filename_order(filename) != filename_order(existing["filename"]):
                raise DossierError("Este PDF já está guardado com outra OF no nome. Confirma a identificação do dossiê; não foi criada uma cópia da necessidade.", 409)
            return {"id": existing["id"], "duplicate": True}
    directory = root() / "files"
    directory.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=directory, suffix=".pdf")
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
        page_count = inspect_pdf(Path(temporary))
        os.replace(temporary, directory / f"{digest}.pdf")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    uid = str(uuid.uuid4())
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute("SELECT id,filename FROM documents WHERE sha256=?", (digest,)).fetchone()
        if existing:
            if filename_order(filename) and filename_order(existing["filename"]) and filename_order(filename) != filename_order(existing["filename"]):
                raise DossierError("Este PDF já está associado a outra OF. Confirma a identificação do dossiê.", 409)
            return {"id": existing["id"], "duplicate": True}
        conn.execute("INSERT INTO documents(id,sha256,filename,page_count,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                     (uid, digest, filename, page_count, "queued" if configured else "waiting_api", now(), now()))
        event(conn, uid, "uploaded", {"filename": filename, "sha256": digest, "pages": page_count})
    return {"id": uid, "duplicate": False}


def file_path(uid: str) -> Path:
    with connect() as conn:
        digest = _document(conn, uid)["sha256"]
    return root() / "files" / f"{digest}.pdf"


def get_document(uid: str) -> dict:
    with connect() as conn:
        data = decode(_document(conn, uid))
        data["pieces"] = [decode(r) for r in conn.execute(
            "SELECT * FROM pieces WHERE document_id=? ORDER BY index_page,index_ref,id", (uid,))]
        data["events"] = [decode(r) for r in conn.execute(
            "SELECT actor,action,data_json,created_at FROM events WHERE document_id=? ORDER BY id DESC LIMIT 30", (uid,))]
        data["attempts"] = [decode(r) for r in conn.execute(
            "SELECT stage,item_key,attempt,status,metadata_json,created_at FROM model_attempts WHERE document_id=? ORDER BY id DESC LIMIT 50", (uid,))]
        latest = conn.execute("SELECT id,source_sha256,summary_json,created_at FROM exports WHERE document_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1", (uid,)).fetchone()
        data["latest_export"] = decode(latest) if latest else None
        proposal = conn.execute("SELECT id,source_sha256,summary_json,created_at FROM export_proposals WHERE document_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1", (uid,)).fetchone()
        data["latest_proposal"] = decode(proposal) if proposal else None
        data["checkpoint_counts"] = {r["stage"]: r["total"] for r in conn.execute(
            "SELECT stage,count(*) AS total FROM checkpoints WHERE document_id=? GROUP BY stage", (uid,))}
    return data


def list_documents(*, limit: int | None = 200) -> list:
    with connect() as conn:
        return [decode(r) for r in conn.execute("""SELECT d.*,
            (SELECT count(*) FROM pieces p WHERE p.document_id=d.id) AS piece_count,
            (SELECT count(*) FROM pieces p WHERE p.document_id=d.id
                AND p.machine_group IN ('Serrote','Vanguard') AND p.state NOT IN ('excluded','superseded')) AS perfis_piece_count,
            (SELECT count(*) FROM pieces p WHERE p.document_id=d.id AND p.state IN ('ready','existing','duplicate')) AS ready_count
            FROM documents d ORDER BY created_at DESC,id DESC""" + (' LIMIT ?' if limit is not None else ''),
            (limit,) if limit is not None else ())]


def update_document(uid: str, **fields):
    allowed = {"status", "progress", "progress_label", "error", "production_order", "context", "issues", "model"}
    if set(fields) - allowed:
        raise ValueError("Invalid document fields")
    values = {}
    for key, val in fields.items():
        values[key + "_json" if key in {"context", "issues", "model"} else key] = dump(val) if key in {"context", "issues", "model"} else val
    values["updated_at"] = now()
    with connect() as conn:
        _document(conn, uid)
        conn.execute("UPDATE documents SET " + ",".join(f"{key}=?" for key in values) + ",revision=revision+1 WHERE id=?",
                     (*values.values(), uid))


def checkpoint(uid, stage, key, data, *, run_id=None, input_fingerprint=None):
    with connect() as conn:
        old = conn.execute("SELECT * FROM checkpoints WHERE document_id=? AND stage=? AND item_key=?",
                           (uid, stage, str(key))).fetchone()
        if old and old["input_fingerprint"] != input_fingerprint:
            conn.execute("""INSERT INTO checkpoint_history(document_id,stage,item_key,data_json,run_id,input_fingerprint,archived_at)
                VALUES (?,?,?,?,?,?,?)""", (uid, stage, str(key), old["data_json"], old["run_id"],
                old["input_fingerprint"], now()))
        conn.execute("""INSERT INTO checkpoints(document_id,stage,item_key,data_json,created_at,run_id,input_fingerprint)
            VALUES (?,?,?,?,?,?,?) ON CONFLICT(document_id,stage,item_key) DO UPDATE SET
            data_json=excluded.data_json,created_at=excluded.created_at,run_id=excluded.run_id,
            input_fingerprint=excluded.input_fingerprint""",
            (uid, stage, str(key), dump(data), now(), run_id, input_fingerprint))


def checkpoints(uid, stage, *, input_fingerprint=None) -> dict:
    with connect() as conn:
        rows = conn.execute("SELECT item_key,data_json,input_fingerprint FROM checkpoints WHERE document_id=? AND stage=?",
                            (uid, stage))
        return {r["item_key"]: json.loads(r["data_json"]) for r in rows
                if input_fingerprint is None or r["input_fingerprint"] == input_fingerprint}


def start_run(uid: str, signature: str, config: dict) -> str:
    run_id = str(uuid.uuid4())
    with connect() as conn:
        _document(conn, uid)
        conn.execute("UPDATE processing_runs SET status='interrupted',completed_at=? WHERE document_id=? AND status='running'",
                     (now(), uid))
        conn.execute("INSERT INTO processing_runs(id,document_id,signature,status,config_json,created_at) VALUES (?,?,?,?,?,?)",
                     (run_id, uid, signature, "running", dump(config), now()))
    return run_id


def prepare_run(uid: str, signature: str):
    """Archive derived rows when their processing contract is incompatible."""
    doc = get_document(uid)
    previous = doc.get("model", {}).get("processing_signature")
    if previous == signature or (previous is None and not doc["pieces"]):
        return
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        checkpoints_before = conn.execute("SELECT * FROM checkpoints WHERE document_id=?", (uid,)).fetchall()
        for row in checkpoints_before:
            conn.execute("""INSERT INTO checkpoint_history(document_id,stage,item_key,data_json,run_id,input_fingerprint,archived_at)
                VALUES (?,?,?,?,?,?,?)""", (uid, row["stage"], row["item_key"], row["data_json"],
                row["run_id"], row["input_fingerprint"], now()))
        event(conn, uid, "incompatible_processing_contract", {"previous_signature": previous,
              "new_signature": signature, "previous_pieces": doc["pieces"]})
        conn.execute("DELETE FROM needs WHERE piece_id IN (SELECT id FROM pieces WHERE document_id=?)", (uid,))
        conn.execute("DELETE FROM pieces WHERE document_id=?", (uid,))
        conn.execute("DELETE FROM checkpoints WHERE document_id=? AND stage!='decisions'", (uid,))


def finish_run(run_id: str, *, status: str, error_kind=None, error_message=None):
    with connect() as conn:
        conn.execute("UPDATE processing_runs SET status=?,error_kind=?,error_message=?,completed_at=? WHERE id=?",
                     (status, error_kind, str(error_message or "")[:1000] or None, now(), run_id))


def record_attempt(run_id: str, uid: str, stage: str, item_key, attempt: int, status: str, metadata: dict):
    with connect() as conn:
        conn.execute("""INSERT INTO model_attempts(run_id,document_id,stage,item_key,attempt,status,metadata_json,created_at)
            VALUES (?,?,?,?,?,?,?,?)""", (run_id, uid, stage, str(item_key), attempt, status,
            dump(metadata), now()))


def record_export(uid: str, source_sha256: str, summary: dict):
    with connect() as conn:
        export_id = str(uuid.uuid4())
        conn.execute("INSERT INTO exports(id,document_id,source_sha256,summary_json,created_at) VALUES (?,?,?,?,?)",
                     (export_id, uid, source_sha256, dump(summary), now()))
        event(conn, uid, "macro_generated", summary)


def record_proposal(uid: str, source_sha256: str, summary: dict):
    with connect() as conn:
        proposal_id = str(uuid.uuid4())
        conn.execute("INSERT INTO export_proposals(id,document_id,source_sha256,summary_json,created_at) VALUES (?,?,?,?,?)",
                     (proposal_id, uid, source_sha256, dump(summary), now()))
        event(conn, uid, "macro_proposed", {"proposal_id": proposal_id,
              "source_sha256": source_sha256, "added": summary.get("added", 0),
              "updated": summary.get("updated", 0), "unchanged": summary.get("unchanged", 0),
              "cell_count": len(summary.get("cells", []))})


def add_piece(uid, source_key, route, pages, values, *, selection=None):
    with connect() as conn:
        conn.execute("""INSERT OR IGNORE INTO pieces
	            (id,document_id,source_key,machine_group,index_page,index_ref,drawing_pages_json,raw_json,values_json,selection_json)
	            VALUES (?,?,?,?,?,?,?,?,?,?)""", (str(uuid.uuid4()), uid, source_key, route["machine_group"],
	            route["page"], route["reference"], dump(pages), dump(values), dump(values), dump(selection or {})))


def save_assessment(piece_id, issues, match, state):
    with connect() as conn:
        conn.execute("UPDATE pieces SET issues_json=?,match_json=?,state=? WHERE id=?",
                     (dump(issues), dump(match), state, piece_id))
        if state in ("review", "blocked"):
            # Uma OF entretanto fechada ou uma dúvida nova retira a necessidade da saída.
            conn.execute("DELETE FROM needs WHERE piece_id=?", (piece_id,))


def register_need(piece: dict, of: str, *, replace=False) -> str:
    identity = need_key(of, piece["machine_group"], piece["values"])
    spec = specification(piece["values"])
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        previous = conn.execute("SELECT * FROM needs WHERE identity=?", (identity,)).fetchone()
        if previous and previous["piece_id"] == piece["id"] and previous["specification"] == spec:
            return "ready"
        if previous and previous["piece_id"] != piece["id"]:
            if previous["specification"] == spec:
                return "duplicate"
            if not replace:
                return "revision_conflict"
            conn.execute("UPDATE pieces SET state='superseded' WHERE id=?", (previous["piece_id"],))
            event(conn, piece["document_id"], "replaced_revision", {"previous_piece_id": previous["piece_id"]}, piece_id=piece["id"])
        conn.execute("""INSERT INTO needs(identity,piece_id,production_order,specification,updated_at)
            VALUES (?,?,?,?,?) ON CONFLICT(identity) DO UPDATE SET piece_id=excluded.piece_id,
            specification=excluded.specification,updated_at=excluded.updated_at,revision=needs.revision+1""",
                     (identity, piece["id"], of, spec, now()))
    return "ready"


def update_piece(uid, piece_id, expected_revision, values, reviewed, machine_group, actor, reason):
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        doc = _document(conn, uid)
        if doc["status"] in ("queued", "indexing", "extracting", "matching"):
            raise DossierError("Aguarda que a leitura termine antes de corrigir campos.", 409)
        old = conn.execute("SELECT * FROM pieces WHERE id=? AND document_id=?", (piece_id, uid)).fetchone()
        if not old:
            raise DossierError("Linha não encontrada.", 404)
        if old["revision"] != expected_revision:
            raise DossierError("Esta linha mudou noutra sessão. Atualiza a página antes de guardar.", 409)
        if old["state"] == "superseded":
            raise DossierError("Esta linha já foi substituída por uma revisão mais recente.", 409)
        conn.execute("DELETE FROM needs WHERE piece_id=?", (piece_id,))
        conn.execute("UPDATE pieces SET values_json=?,reviewed_json=?,machine_group=?,revision=revision+1,state='review' WHERE id=?",
                     (dump(values), dump(reviewed), machine_group, piece_id))
        event(conn, uid, "reviewed", {"before": json.loads(old["values_json"]), "after": values,
              "machine_group_before": old["machine_group"], "machine_group_after": machine_group,
              "reviewed": reviewed, "reason": reason}, piece_id=piece_id, actor=actor)


@guarded
def retry(uid, *, api_ready: bool):
    with connect() as conn:
        doc = _document(conn, uid)
        if doc["status"] in ("indexing", "extracting", "matching", "queued"):
            return
        conn.execute("UPDATE documents SET status=?,error=NULL,updated_at=?,revision=revision+1 WHERE id=?",
                     ("queued" if api_ready else "waiting_api", now(), uid))
        event(conn, uid, "retry", {})


@guarded
def restart(uid, *, api_ready: bool, actor: str = "", reason: str = ""):
    actor = actor.strip()[:120] or "Interface de planeamento"
    reason = reason.strip()[:1000] or "Nova leitura pedida na interface."
    doc = get_document(uid)
    if doc["status"] in ("queued", "indexing", "extracting", "matching"):
        raise DossierError("A leitura já está em curso.", 409)
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        previous = [decode(r) for r in conn.execute("SELECT * FROM checkpoints WHERE document_id=?", (uid,))]
        event(conn, uid, "reading_restarted", {"previous_pieces": doc["pieces"], "checkpoints": previous,
              "reason": reason}, actor=actor)
        for row in conn.execute("SELECT * FROM checkpoints WHERE document_id=? AND stage!='decisions'", (uid,)):
            conn.execute("""INSERT INTO checkpoint_history(document_id,stage,item_key,data_json,run_id,input_fingerprint,archived_at)
                VALUES (?,?,?,?,?,?,?)""", (uid, row["stage"], row["item_key"], row["data_json"],
                row["run_id"], row["input_fingerprint"], now()))
        conn.execute("DELETE FROM needs WHERE piece_id IN (SELECT id FROM pieces WHERE document_id=?)", (uid,))
        conn.execute("DELETE FROM pieces WHERE document_id=?", (uid,))
        conn.execute("DELETE FROM checkpoints WHERE document_id=? AND stage!='decisions'", (uid,))
        conn.execute("UPDATE documents SET status=?,progress=0,progress_label='',error=NULL,issues_json='[]',context_json='{}',revision=revision+1,updated_at=? WHERE id=?",
                     ("queued" if api_ready else "waiting_api", now(), uid))


@guarded
def reread_page(uid: str, page: int, *, api_ready: bool, actor: str = "", reason: str = ""):
    actor = actor.strip()[:120] or "Interface de planeamento"
    reason = reason.strip()[:1000] or f"Releitura da página {page} pedida na interface."
    doc = get_document(uid)
    if not 1 <= page <= doc["page_count"]:
        raise DossierError("Página não encontrada.", 404)
    if doc["status"] in ("queued", "indexing", "extracting", "matching"):
        raise DossierError("A leitura já está em curso.", 409)
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute("SELECT * FROM checkpoints WHERE document_id=?", (uid,)).fetchall()
        for row in current:
            if row["stage"] in ("links", "extractions", "verifications") or (row["stage"] == "inventory" and row["item_key"] == str(page)):
                conn.execute("""INSERT INTO checkpoint_history(document_id,stage,item_key,data_json,run_id,input_fingerprint,archived_at)
                    VALUES (?,?,?,?,?,?,?)""", (uid, row["stage"], row["item_key"], row["data_json"],
                    row["run_id"], row["input_fingerprint"], now()))
        event(conn, uid, "page_reread_requested", {"page": page, "reason": reason,
              "previous_pieces": doc["pieces"]}, actor=actor)
        conn.execute("DELETE FROM needs WHERE piece_id IN (SELECT id FROM pieces WHERE document_id=?)", (uid,))
        conn.execute("DELETE FROM pieces WHERE document_id=?", (uid,))
        conn.execute("DELETE FROM checkpoints WHERE document_id=? AND (stage IN ('links','extractions','verifications') OR (stage='inventory' AND item_key=?))",
                     (uid, str(page)))
        conn.execute("UPDATE documents SET status=?,progress=0,progress_label='',error=NULL,issues_json='[]',context_json='{}',revision=revision+1,updated_at=? WHERE id=?",
                     ("queued" if api_ready else "waiting_api", now(), uid))


@guarded
def reread_piece(uid: str, piece_id: str, *, api_ready: bool, actor: str = "", reason: str = ""):
    actor = actor.strip()[:120] or "Interface de planeamento"
    reason = reason.strip()[:1000] or "Releitura do desenho pedida na interface."
    doc = get_document(uid)
    if doc["status"] in ("queued", "indexing", "extracting", "matching"):
        raise DossierError("A leitura já está em curso.", 409)
    piece = next((item for item in doc["pieces"] if item["id"] == piece_id), None)
    if not piece:
        raise DossierError("Linha não encontrada.", 404)
    route_key = piece["source_key"].rsplit(":", 1)[0]
    affected = [item for item in doc["pieces"] if item["source_key"].rsplit(":", 1)[0] == route_key]
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        checkpoint_rows = conn.execute("SELECT * FROM checkpoints WHERE document_id=? AND stage IN ('extractions','verifications') AND item_key=?",
                                       (uid, route_key)).fetchall()
        for checkpoint_row in checkpoint_rows:
            conn.execute("""INSERT INTO checkpoint_history(document_id,stage,item_key,data_json,run_id,input_fingerprint,archived_at)
                VALUES (?,?,?,?,?,?,?)""", (uid, checkpoint_row["stage"], checkpoint_row["item_key"],
                checkpoint_row["data_json"], checkpoint_row["run_id"], checkpoint_row["input_fingerprint"], now()))
        ids = [item["id"] for item in affected]
        conn.execute("DELETE FROM needs WHERE piece_id IN (%s)" % ",".join("?" * len(ids)), tuple(ids))
        conn.execute("DELETE FROM pieces WHERE id IN (%s)" % ",".join("?" * len(ids)), tuple(ids))
        conn.execute("DELETE FROM checkpoints WHERE document_id=? AND stage IN ('extractions','verifications') AND item_key=?", (uid, route_key))
        event(conn, uid, "piece_reread_requested", {"route_key": route_key, "reason": reason,
              "previous_pieces": affected}, actor=actor)
        conn.execute("UPDATE documents SET status=?,progress=50,progress_label='Desenho pendente de releitura',error=NULL,revision=revision+1,updated_at=? WHERE id=?",
                     ("queued" if api_ready else "waiting_api", now(), uid))


@guarded
def exclude(uid, piece_id, revision, actor, reason):
    actor = str(actor or "").strip()[:120] or "Interface de planeamento"
    reason = str(reason or "").strip()[:1000] or "Linha excluída na interface."
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        doc = _document(conn, uid)
        if doc["status"] in ("queued", "indexing", "extracting", "matching"):
            raise DossierError("Aguarda que a leitura termine.", 409)
        piece = conn.execute("SELECT * FROM pieces WHERE id=? AND document_id=?", (piece_id, uid)).fetchone()
        if not piece or piece["revision"] != revision:
            raise DossierError("A linha mudou. Atualiza a página antes de a excluir.", 409)
        conn.execute("DELETE FROM needs WHERE piece_id=?", (piece_id,))
        conn.execute("UPDATE pieces SET state='excluded',revision=revision+1 WHERE id=?", (piece_id,))
        event(conn, uid, "piece_excluded", {"reason": reason, "values": json.loads(piece["values_json"])}, piece_id=piece_id, actor=actor)


def queue_waiting():
    with connect() as conn:
        conn.execute("UPDATE documents SET status='queued',updated_at=? WHERE status='waiting_api'", (now(),))


def next_job() -> str | None:
    # Chamado dentro do lock interprocesso do worker. Retoma um job interrompido primeiro.
    with connect() as conn:
        row = conn.execute("""SELECT id FROM documents WHERE status IN ('queued','indexing','extracting','matching')
            ORDER BY CASE WHEN status='queued' THEN 1 ELSE 0 END,created_at LIMIT 1""").fetchone()
    return row["id"] if row else None


def plan_rows() -> list:
    with connect() as conn:
        return [decode(r) for r in conn.execute("""SELECT p.*,n.production_order,d.filename,
            d.context_json,n.revision AS need_revision FROM needs n JOIN pieces p ON p.id=n.piece_id
            JOIN documents d ON d.id=p.document_id WHERE d.status='ready'
            AND p.state IN ('ready','existing') ORDER BY n.production_order,p.index_ref""")]
