"""
Tests for AnyIOManager stats. Run via subprocess so the test has a single,
clean Trio run; avoids pytest-xdist worker reuse (nested trio.run) and
timeout when the same worker has run other trio/anyio tests.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

# Repo root (tests/core/tools/anyio_service -> 5 parents)
_REPO_ROOT = Path(__file__).resolve().parents[4]

_RUNNER_MODULE = "tests.core.tools.anyio_service._anyio_manager_stats_runner"
# CI can be slow; allow enough time for the subprocess to finish
_SUBPROCESS_TIMEOUT = 120


def _run_standalone(test_name: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", _RUNNER_MODULE, test_name],
        cwd=_REPO_ROOT,
        timeout=_SUBPROCESS_TIMEOUT,
        capture_output=True,
        text=True,
    )


def test_anyio_manager_stats() -> None:
    result = _run_standalone("test_anyio_manager_stats")
    assert result.returncode == 0, (result.stdout or "") + (result.stderr or "")


def test_anyio_manager_stats_does_not_count_main_run_method() -> None:
    result = _run_standalone("test_anyio_manager_stats_does_not_count_main_run_method")
    assert result.returncode == 0, (result.stdout or "") + (result.stderr or "")
