"""Adapter pytest para os 3 smoke tests legacy em formato standalone.

Os smokes LESSON-002/003/004 foram escritos como scripts com `run()` + sys.exit.
Este adapter os expoe para `pytest tests/ -q` sem alterar os arquivos originais.
"""
import subprocess
import sys
from pathlib import Path

LEGACY_DIR = Path(__file__).parent


def _run_legacy(name: str):
    script = LEGACY_DIR / name
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"{name} exit={result.returncode}\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


def test_legacy_execution_context_smoke():
    _run_legacy("test_execution_context_smoke.py")


def test_legacy_audit_log_smoke():
    _run_legacy("test_audit_log_smoke.py")


def test_legacy_runtime_guard_smoke():
    _run_legacy("test_runtime_guard_smoke.py")
