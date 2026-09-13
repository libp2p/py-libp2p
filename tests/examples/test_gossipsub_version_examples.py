"""Smoke tests for Gossipsub versioned example scripts."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
GOSSIPSUB_DIR = PROJECT_ROOT / "examples" / "pubsub" / "gossipsub"

SCRIPTS = [
    ("gossipsub_v1.0.py", ["--nodes", "3", "--duration", "4"]),
    ("gossipsub_v1.1.py", ["--nodes", "3", "--duration", "4"]),
    ("gossipsub_v1.2.py", ["--nodes", "3", "--duration", "4"]),
    ("gossipsub_v1.3.py", ["--nodes", "4", "--duration", "4"]),
    ("gossipsub_v1.4.py", ["--nodes", "4", "--duration", "4"]),
    ("gossipsub_v2.0.py", ["--nodes", "3", "--duration", "4"]),
]


@pytest.mark.parametrize(("script", "args"), SCRIPTS)
def test_gossipsub_version_example_runs(script: str, args: list[str]) -> None:
    path = GOSSIPSUB_DIR / script
    assert path.is_file(), f"missing example script {path}"
    result = subprocess.run(
        [sys.executable, str(path), *args],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, (
        f"{script} failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    combined = f"{result.stdout}\n{result.stderr}"
    assert "DEMO STATISTICS" in combined


def test_compare_versions_runs() -> None:
    path = GOSSIPSUB_DIR / "compare_versions.py"
    result = subprocess.run(
        [
            sys.executable,
            str(path),
            "--nodes",
            "3",
            "--duration",
            "4",
            "--versions",
            "1.0,1.1",
            "--scenario",
            "normal",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, (
        f"compare_versions failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    combined = f"{result.stdout}\n{result.stderr}"
    assert "COMPARISON TABLE" in combined
