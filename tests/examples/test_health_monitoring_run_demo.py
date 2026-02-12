"""
Tests for examples/health_monitoring/run_demo.py: run the demo with different
parameters and assert that resource limits are enforced and output is consistent.
"""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys

# Project root (from tests/examples/ -> tests/ -> root)
_current_file = Path(__file__).resolve()
PROJECT_ROOT = _current_file.parent.parent.parent
RUN_DEMO = PROJECT_ROOT / "examples" / "health_monitoring" / "run_demo.py"

# Port used for test runs (avoid clashing with a live demo on 8000)
TEST_PORT = 18765


def run_demo(
    *args: str,
    timeout: int = 60,
) -> subprocess.CompletedProcess:
    """Run run_demo.py with the given CLI arguments. Returns the result."""
    cmd = [sys.executable, str(RUN_DEMO), "--port", str(TEST_PORT), *args]
    return subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def parse_final_state(stdout: str) -> dict[str, int | None]:
    """
    Parse the last 'Current:', 'Blocked:', and 'active connections' lines.
    Returns dict with conns, streams, memory_bytes, blocked_conns, blocked_streams,
    blocked_memory, active_connections, blocked_connections.
    """
    out: dict[str, int | None] = {
        "conns": None,
        "streams": None,
        "memory_bytes": None,
        "blocked_conns": None,
        "blocked_streams": None,
        "blocked_memory": None,
        "active_connections": None,
        "blocked_connections": None,
    }
    # Current: N conns, M streams, K bytes memory
    m = re.findall(
        r"Current:\s*(\d+)\s+conns,\s*(\d+)\s+streams,\s*(\d+)\s+bytes memory",
        stdout,
    )
    if m:
        last = m[-1]
        out["conns"] = int(last[0])
        out["streams"] = int(last[1])
        out["memory_bytes"] = int(last[2])
    # Blocked: X conns, Y streams, Z memory
    m = re.findall(
        r"Blocked:\s*(\d+)\s+conns,\s*(\d+)\s+streams,\s*(\d+)\s+memory",
        stdout,
    )
    if m:
        last = m[-1]
        out["blocked_conns"] = int(last[0])
        out["blocked_streams"] = int(last[1])
        out["blocked_memory"] = int(last[2])
    # "N active connections, X blocked"
    m = re.search(
        r"(\d+)\s+active connections,\s*(\d+)\s+blocked",
        stdout,
    )
    if m:
        out["active_connections"] = int(m.group(1))
        out["blocked_connections"] = int(m.group(2))
    return out


def test_default_limits_few_iterations() -> None:
    """Default limits, few iterations; usage stays below limits."""
    result = run_demo("--iterations", "6", timeout=15)
    assert result.returncode == 0, f"Demo failed: {result.stderr}"
    state = parse_final_state(result.stdout)
    assert state["conns"] is not None and state["streams"] is not None
    assert state["conns"] <= 10
    assert state["streams"] <= 20
    max_mem = 32 * 1024 * 1024
    assert state["memory_bytes"] is not None and state["memory_bytes"] <= max_mem
    assert state["active_connections"] == state["conns"]
    assert state["blocked_connections"] == state["blocked_conns"]


def test_tight_limits_hit_connections_and_streams() -> None:
    """Tight limits (2 conns, 4 streams, 2 MB), enough iterations; we see blocks."""
    result = run_demo(
        "--max-connections",
        "2",
        "--max-streams",
        "4",
        "--max-memory-mb",
        "2",
        "--iterations",
        "15",
        "--interval",
        "0.1",
        timeout=15,
    )
    assert result.returncode == 0, f"Demo failed: {result.stderr}"
    state = parse_final_state(result.stdout)
    assert state["conns"] is not None, "Could not parse final conns"
    assert state["streams"] is not None
    assert state["memory_bytes"] is not None
    assert state["conns"] <= 2, f"Connections {state['conns']} should be <= 2"
    assert state["streams"] <= 4, f"Streams {state['streams']} should be <= 4"
    assert state["memory_bytes"] <= 2 * 1024 * 1024 + 500 * 1024, (
        f"Memory {state['memory_bytes']} should be <= ~2 MB"
    )
    blocked = (state["blocked_conns"] or 0) + (state["blocked_streams"] or 0)
    blocked += state["blocked_memory"] or 0
    assert blocked >= 1, "Expected at least one type of block with tight limits"


def test_tight_limits_final_state_at_cap() -> None:
    """Very tight limits (1 conn, 2 streams, 1 MB), many iterations; final at cap."""
    result = run_demo(
        "--max-connections",
        "1",
        "--max-streams",
        "2",
        "--max-memory-mb",
        "1",
        "--iterations",
        "20",
        "--interval",
        "0.05",
        timeout=15,
    )
    assert result.returncode == 0, f"Demo failed: {result.stderr}"
    state = parse_final_state(result.stdout)
    assert state["conns"] == 1, f"Expected 1 connection, got {state['conns']}"
    assert state["streams"] == 2, f"Expected 2 streams, got {state['streams']}"
    assert state["memory_bytes"] is not None and state["memory_bytes"] <= 1024 * 1024, (
        f"Memory should be <= 1 MB, got {state['memory_bytes']}"
    )
    assert (state["blocked_connections"] or 0) >= 1, (
        "Expected at least one blocked connection"
    )


def test_custom_interval_runs_and_respects_limits() -> None:
    """Custom --interval: run completes and limits still enforced."""
    result = run_demo(
        "--max-connections",
        "3",
        "--max-streams",
        "6",
        "--max-memory-mb",
        "4",
        "--interval",
        "0.2",
        "--iterations",
        "12",
        timeout=15,
    )
    assert result.returncode == 0, f"Demo failed: {result.stderr}"
    state = parse_final_state(result.stdout)
    assert state["conns"] is not None and state["conns"] <= 3
    assert state["streams"] is not None and state["streams"] <= 6
    assert state["memory_bytes"] is not None
    assert state["memory_bytes"] <= 4 * 1024 * 1024


def test_duration_stops_in_time() -> None:
    """--duration: run stops after about that many seconds (we use 3s, check exit 0)."""
    result = run_demo("--duration", "3", "--max-connections", "5", timeout=10)
    assert result.returncode == 0, f"Demo failed: {result.stderr}"
    state = parse_final_state(result.stdout)
    assert state["conns"] is not None and state["conns"] <= 5


def test_no_connection_tracking_runs() -> None:
    """--no-connection-tracking: demo runs and exits successfully."""
    result = run_demo(
        "--no-connection-tracking",
        "--iterations",
        "5",
        timeout=15,
    )
    assert result.returncode == 0, f"Demo failed: {result.stderr}"
    state = parse_final_state(result.stdout)
    assert state["conns"] is not None and state["conns"] <= 10


def test_no_protocol_metrics_runs() -> None:
    """--no-protocol-metrics: demo runs and exits successfully."""
    result = run_demo(
        "--no-protocol-metrics",
        "--iterations",
        "5",
        timeout=15,
    )
    assert result.returncode == 0, f"Demo failed: {result.stderr}"
    state = parse_final_state(result.stdout)
    assert state["conns"] is not None
