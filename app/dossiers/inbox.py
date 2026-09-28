"""Entrada opcional por pasta, com espera por ficheiros estáveis e erros visíveis."""
from __future__ import annotations

import os
import time
from pathlib import Path

from . import DossierError, store, provider
from .pdf import MAX_BYTES


def status():
    if not os.environ.get("MES_DOSSIER_INBOX", "").strip():
        return {"enabled": False, "errors": []}
    with store.connect() as conn:
        row = conn.execute("SELECT value_json FROM service_state WHERE name='inbox'").fetchone()
    import json
    return json.loads(row["value_json"]) if row else {"enabled": True, "errors": [], "last_scan": None}


def scan():
    directory = os.environ.get("MES_DOSSIER_INBOX", "").strip()
    if not directory:
        return
    path = Path(directory).expanduser()
    result = {"enabled": True, "directory_name": path.name, "errors": [], "last_scan": store.now()}
    try:
        files = sorted(p for p in path.iterdir() if p.is_file() and p.suffix.casefold() == ".pdf")
        processed = 0
        for file in files:
            if processed >= 10:
                break
            before = file.stat()
            if time.time() - before.st_mtime < 10:
                continue
            with store.connect() as conn:
                old = conn.execute("SELECT * FROM inbox_files WHERE path=?", (str(file.resolve()),)).fetchone()
            if old and old["size"] == before.st_size and old["mtime_ns"] == before.st_mtime_ns:
                if old["error"]:
                    result["errors"].append({"filename": file.name, "message": old["error"]})
                continue
            error, uid = None, None
            try:
                if before.st_size > MAX_BYTES:
                    raise DossierError("O limite por PDF é 80 MB.")
                data = file.read_bytes()
                after = file.stat()
                if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
                    continue
                uid = store.ingest(data, file.name, configured=provider.configured())["id"]
            except DossierError as exc:
                error = str(exc)
                result["errors"].append({"filename": file.name, "message": error})
            with store.connect() as conn:
                conn.execute("""INSERT INTO inbox_files(path,size,mtime_ns,document_id,error,updated_at) VALUES (?,?,?,?,?,?)
                    ON CONFLICT(path) DO UPDATE SET size=excluded.size,mtime_ns=excluded.mtime_ns,
                    document_id=excluded.document_id,error=excluded.error,updated_at=excluded.updated_at""",
                    (str(file.resolve()), before.st_size, before.st_mtime_ns, uid, error, store.now()))
            processed += 1
    except OSError:
        result["errors"].append({"filename": path.name, "message": "Não foi possível aceder à pasta de entrada. Confirma o caminho e as permissões no servidor."})
    result["errors"] = result["errors"][:20]
    with store.connect() as conn:
        conn.execute("INSERT INTO service_state(name,value_json,updated_at) VALUES ('inbox',?,?) "
                     "ON CONFLICT(name) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at",
                     (store.dump(result), store.now()))
