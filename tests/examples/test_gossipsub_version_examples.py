"""Smoke tests for Gossipsub versioned example scripts."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from typing import Any
from unittest.mock import patch

import pytest
import trio

from examples.pubsub.gossipsub import compare_versions

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
    assert "may exceed 1.0" in combined


async def test_compare_versions_churn_disconnects_and_reconnects() -> None:
    nodes: list[compare_versions.CompareNode] = []
    samples: list[tuple[int, list[bool]]] = []

    class ObservedNode(compare_versions.CompareNode):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            nodes.append(self)

        async def publish_message(self, message: str) -> None:
            await super().publish_message(message)
            samples.append(
                (
                    nodes.index(self),
                    [bool(n.host and n.host.get_connected_peers()) for n in nodes],
                )
            )

    version, protocol, kwargs = compare_versions.VERSIONS[0]
    with patch.object(compare_versions, "CompareNode", ObservedNode):
        with trio.fail_after(30):
            row = await compare_versions._run_one_version(
                version,
                protocol,
                kwargs,
                node_count=4,
                duration=10,
                scenario="churn",
            )

    isolated = [
        i
        for i, (_, connected) in enumerate(samples)
        if connected == [False, False, True, True]
    ]
    assert isolated, "half the nodes must disconnect while the others publish"
    assert all(samples[i][0] >= 2 for i in isolated), "offline nodes must not publish"
    assert any(all(connected) for _, connected in samples[: isolated[0]])
    assert any(all(connected) for _, connected in samples[isolated[-1] + 1 :]), samples
    assert row["received"] > 0
