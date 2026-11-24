"""
Run the circuit relay example end to end: a relay, a destination that reserves
a slot on it, and a source that reaches the destination through the relay.

Each role runs as its own process, as the example's README describes.
"""

import contextlib
import os
from pathlib import Path
import re
import subprocess
import sys
import time

project_root = Path(__file__).parent.parent.parent
MODULE = "examples.circuit_relay.relay_example"
ENV = {**os.environ, "PYTHONUNBUFFERED": "1"}


def _start(log: Path, *args: str) -> subprocess.Popen[bytes]:
    with open(log, "wb") as out:
        return subprocess.Popen(
            [sys.executable, "-u", "-m", MODULE, *args],
            stdout=out,
            stderr=subprocess.STDOUT,
            env=ENV,
            cwd=str(project_root),
        )


def _wait_for(log: Path, pattern: str, timeout: float = 30.0) -> re.Match[str]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        m = re.search(pattern, log.read_text(errors="replace"))
        if m:
            return m
        time.sleep(0.1)
    raise AssertionError(
        f"{log.name} never matched {pattern!r}; last output:\n"
        + log.read_text(errors="replace")[-2000:]
    )


def _stop(proc: subprocess.Popen[bytes]) -> None:
    with contextlib.suppress(ProcessLookupError):
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


def test_source_reaches_destination_through_relay(tmp_path: Path) -> None:
    relay_log = tmp_path / "relay.log"
    dest_log = tmp_path / "dest.log"
    source_log = tmp_path / "source.log"

    relay = _start(relay_log, "--role", "relay", "--port", "0")
    dest = None
    try:
        m = _wait_for(relay_log, r"Listening on: /ip4/0\.0\.0\.0/tcp/(\d+)/p2p/(\w+)")
        relay_addr = f"/ip4/127.0.0.1/tcp/{m[1]}/p2p/{m[2]}"

        dest = _start(
            dest_log,
            "--role",
            "destination",
            "--port",
            "0",
            "--relay-addr",
            relay_addr,
        )
        dest_id = _wait_for(dest_log, r"Destination node started with ID: (\w+)")[1]
        # Printed once the destination has connected and reserved a slot.
        _wait_for(dest_log, r"Press Ctrl\+C to exit")

        source = subprocess.run(
            [
                sys.executable,
                "-u",
                "-m",
                MODULE,
                "--role",
                "source",
                "--relay-addr",
                relay_addr,
                "--dest-id",
                dest_id,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=ENV,
            cwd=str(project_root),
            timeout=60,
        )
        source_log.write_bytes(source.stdout)
        out = source.stdout.decode(errors="replace")

        assert "Successfully connected to destination through relay!" in out, out[
            -2000:
        ]
        assert re.search(r"Received response: Hello! This is \w+", out), out[-2000:]
        _wait_for(dest_log, r"Received message \(\d+ bytes\): Hello from \w+!")
    finally:
        if dest is not None:
            _stop(dest)
        _stop(relay)
