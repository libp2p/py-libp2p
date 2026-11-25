"""
Run the example programs themselves, as a user would, and check what they print.

``test_examples.py`` re-implements each demo's logic in-process, so it keeps
passing when an example script breaks (#523). These tests start the real
modules as subprocesses: a listener, then a dialer pointed at the address the
listener printed, and they check the dialer's own output. One-shot dialers must
also exit by themselves.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
ENV = {**os.environ, "PYTHONUNBUFFERED": "1"}
TCP = r"/ip4/127\.0\.0\.1/tcp/\d+/p2p/\w+"
WS = r"/ip4/127\.0\.0\.1/tcp/\d+/ws/p2p/\w+"
QUIC = r"/ip4/127\.0\.0\.1/udp/\d+/quic(?:-v1)?/p2p/\w+"


@dataclass(frozen=True)
class Pair:
    """A listener and a dialer started with ``{addr}`` filled in."""

    id: str
    listener: tuple[str, ...]
    dialer: tuple[str, ...]
    addr: str
    expect: str
    stdin: str | None = None  # sent to the dialer; interactive demos
    exits: bool = True  # one-shot dialers must exit by themselves


PAIRS = [
    Pair(
        "ping-tcp",
        ("examples.ping.ping", "-p", "0"),
        ("examples.ping.ping", "-d", "{addr}"),
        TCP,
        r"received pong from \w+",
    ),
    Pair(
        "ping-ws",
        ("examples.ping.ping", "-t", "ws", "-p", "0"),
        ("examples.ping.ping", "-t", "ws", "-d", "{addr}"),
        WS,
        r"received pong from \w+",
    ),
    Pair(
        "ping-psk",
        ("examples.ping.ping", "-psk", "1", "-p", "0"),
        ("examples.ping.ping", "-psk", "1", "-d", "{addr}"),
        TCP,
        r"received pong from \w+",
    ),
    Pair(
        "echo",
        ("examples.echo.echo", "-p", "0"),
        ("examples.echo.echo", "-d", "{addr}"),
        TCP,
        r"Got: hi, there!",
    ),
    Pair(
        "echo-quic",
        ("examples.echo.echo_quic", "-p", "0"),
        ("examples.echo.echo_quic", "-d", "{addr}"),
        QUIC,
        r"Got: hi, there!",
    ),
    Pair(
        "identify",
        ("examples.identify.identify", "-p", "0"),
        ("examples.identify.identify", "-d", "{addr}"),
        TCP,
        r"Protocols: \[.*'/ipfs/id/1\.0\.0'",
    ),
    Pair(
        "identify-push",
        ("examples.identify_push.identify_push_listener_dialer", "-p", "0"),
        ("examples.identify_push.identify_push_listener_dialer", "-d", "{addr}"),
        TCP,
        r"Received identify/push request from peer: \w+",
    ),
    Pair(
        "request-response",
        ("examples.request_response.request_response_demo", "-p", "0"),
        ("examples.request_response.request_response_demo", "-d", "{addr}"),
        TCP,
        r"Received: \{'message': 'hello', 'echo': 'HELLO'",
    ),
    Pair(
        "tls-ping",
        ("examples.tls.example_tls_server", "-p", "0"),
        (
            "examples.tls.example_tls_client",
            "--server",
            "{addr}",
            "--mode",
            "ping",
            "--count",
            "3",
        ),
        TCP,
        r"Ping #3: [\d.]+ ms",
    ),
    Pair(
        "tls-echo",  # the client's default mode (#1613)
        ("examples.tls.example_tls_server", "-p", "0"),
        ("examples.tls.example_tls_client", "--server", "{addr}"),
        TCP,
        r"Received: Hello from TLS client!",
    ),
    Pair(
        "chat",
        ("examples.chat.chat", "-p", "0"),
        ("examples.chat.chat", "-d", "{addr}"),
        TCP,
        r"hello from the dialer",
        stdin="hello from the dialer\n",
        exits=False,
    ),
    Pair(
        "pubsub",
        ("examples.pubsub.pubsub", "-p", "0"),
        ("examples.pubsub.pubsub", "-d", "{addr}"),
        TCP,
        r"Received message: hello pubsub",
        stdin="hello pubsub\n",
        exits=False,
    ),
    Pair(
        "floodsub",
        ("examples.pubsub.floodsub", "-p", "0"),
        ("examples.pubsub.floodsub", "-d", "{addr}"),
        TCP,
        r"Received message: hello floodsub",
        stdin="hello floodsub\n",
        exits=False,
    ),
]


def _start(
    log: Path, module_args: tuple[str, ...], stdin: int | None = None
) -> subprocess.Popen[bytes]:
    with open(log, "wb") as out:
        return subprocess.Popen(
            [sys.executable, "-u", "-m", *module_args],
            stdin=stdin,
            stdout=out,
            stderr=subprocess.STDOUT,
            env=ENV,
            cwd=str(PROJECT_ROOT),
        )


def _wait_for(logs: list[Path], pattern: str, timeout: float) -> re.Match[str]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for log in logs:
            m = re.search(pattern, log.read_text(errors="replace"))
            if m:
                return m
        time.sleep(0.1)
    tails = "\n".join(
        f"--- {log.name}\n{log.read_text(errors='replace')[-1500:]}" for log in logs
    )
    raise AssertionError(f"no output matched {pattern!r} in {timeout}s\n{tails}")


def _stop(proc: subprocess.Popen[bytes]) -> None:
    with contextlib.suppress(ProcessLookupError):
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)
    if proc.stdin is not None:
        proc.stdin.close()


@pytest.mark.parametrize("pair", PAIRS, ids=[p.id for p in PAIRS])
def test_listener_and_dialer(pair: Pair, tmp_path: Path) -> None:
    listener_log = tmp_path / "listener.log"
    dialer_log = tmp_path / "dialer.log"
    listener = _start(listener_log, pair.listener)
    dialer = None
    try:
        addr = _wait_for([listener_log], pair.addr, timeout=30)[0]
        args = tuple(a.format(addr=addr) for a in pair.dialer)
        dialer = _start(dialer_log, args, stdin=subprocess.PIPE if pair.stdin else None)
        if pair.stdin and dialer.stdin is not None:
            # Interactive demos read stdin once connected; a short wait keeps
            # the line from arriving before the prompt is listening.
            time.sleep(2)
            dialer.stdin.write(pair.stdin.encode())
            dialer.stdin.flush()

        _wait_for([dialer_log, listener_log], pair.expect, timeout=30)

        if pair.exits:
            try:
                rc = dialer.wait(timeout=20)
            except subprocess.TimeoutExpired:
                raise AssertionError(
                    f"{pair.id}: the dialer printed its result but did not exit"
                ) from None
            assert rc == 0, dialer_log.read_text(errors="replace")[-1500:]
    finally:
        if dialer is not None:
            _stop(dialer)
        _stop(listener)


@pytest.mark.parametrize(
    ("module_args", "expect"),
    [
        (
            ("examples.dht_chat.dht_chat", "-n", "6", "-k", "3"),
            r"COMPLETE: all lookup\+chat pairs succeeded",
        ),
        (
            (
                "examples.health_monitoring.live_demo",
                "--peers",
                "6",
                "--scenario",
                "all",
            ),
            r"average peer health: [\d.]+",
        ),
    ],
    ids=["dht-chat", "health-monitoring"],
)
def test_self_contained_demo_exits_cleanly(
    module_args: tuple[str, ...], expect: str, tmp_path: Path
) -> None:
    log = tmp_path / "demo.log"
    proc = _start(log, module_args)
    try:
        rc = proc.wait(timeout=120)
    finally:
        _stop(proc)
    output = log.read_text(errors="replace")
    assert rc == 0, output[-1500:]
    assert re.search(expect, output), output[-1500:]
