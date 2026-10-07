"""Carga e Gantt simples num browser real enquanto as caches se refazem (07/10/2026).

As páginas vêm de um servidor desta pasta, sem base de dados; as respostas da API são sintéticas
(tests/setor_stale_browser.cjs). Corre com RUN_PLANNING_BROWSER=1, como os outros ensaios de browser.
"""
import os
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(os.environ.get("RUN_PLANNING_BROWSER") != "1", reason="Browser opt-in")
def test_pages_do_not_redraw_while_the_answer_is_still_the_previous_one(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {"HOME": os.environ["HOME"], "PATH": os.environ["PATH"], "MES_DATA_DIR": str(tmp_path),
           "MES_DOSSIER_WORKER_DISABLED": "1", "MES_PLANNING_SELECTION_ENABLED": "1", "MES_PLANNING_RAW_ENABLED": "1",
           "MES_RAW_WORKSPACE_ENABLED": "1", "MES_PLANNING_GANTT_ENABLED": "1"}
    log = (tmp_path / "server.log").open("w+")
    server = subprocess.Popen([str(ROOT / ".venv/bin/python"), "-m", "uvicorn", "app.web.planning_app:app", "--host", "127.0.0.1",
                               "--port", str(port)], cwd=ROOT, env=env, stdout=log, stderr=log)
    try:
        for _ in range(200):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/planeamento/setor/carga", timeout=0.5)
                break
            except Exception:
                time.sleep(0.1)
        run = subprocess.run(["node", "tests/setor_stale_browser.cjs"], cwd=ROOT, env={**os.environ, "SETOR_BASE": f"http://127.0.0.1:{port}"},
                             capture_output=True, text=True, timeout=180)
        log.flush()
        log.seek(0)
        assert run.returncode == 0, run.stdout + run.stderr + "\n" + log.read()
    finally:
        server.terminate()
        server.wait(timeout=10)
        log.close()
