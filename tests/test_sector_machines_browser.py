"""Página Máquinas num browser real contra um servidor com dados (opcional).

Corre com PLANNING_MACHINES_BROWSER_BASE=http://127.0.0.1:<porta>. As gravações são intercetadas no browser
(ver tests/sector_machines_browser.cjs), por isso pode apontar para uma instância de leitura dos dados reais.
"""
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not os.getenv("PLANNING_MACHINES_BROWSER_BASE"), reason="Browser opt-in (PLANNING_MACHINES_BROWSER_BASE)")
def test_machines_browser_flow():
    env = {**os.environ, "PLANNING_CHECK_BASE": os.environ["PLANNING_MACHINES_BROWSER_BASE"]}
    run = subprocess.run(["node", "tests/sector_machines_browser.cjs"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=900)
    assert run.returncode == 0, run.stdout + run.stderr
