"""
go-libp2p ↔ py-libp2p WebTransport interop.

Runs the pinned go-libp2p v0.49 harness (built by conftest) against our
WebTransport transport in both directions.
"""

from __future__ import annotations

import logging
from pathlib import Path
import subprocess

import pytest
from multiaddr import Multiaddr
import trio

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.transport.webtransport.transport import WebTransportTransport

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.trio


def _transport() -> WebTransportTransport:
    return WebTransportTransport(private_key=create_new_key_pair().private_key)


async def _spawn(harness: Path, *args: str) -> trio.Process:
    return await trio.lowlevel.open_process(
        [str(harness), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


async def _read_lines(
    proc: trio.Process,
    prefix: str,
    *,
    count: int = 1,
    settle: float = 0.0,
    timeout: float = 45.0,
) -> list[str]:
    """
    Read stdout until at least *count* lines start with *prefix*.

    If *settle* > 0, after the first match keep draining for that many seconds
    so a multi-line burst (e.g. one LISTEN per interface) is collected in one
    call.
    """
    stdout = proc.stdout
    assert stdout is not None
    found: list[str] = []
    buf: list[bytes] = [b""]

    def _consume(chunk: bytes) -> None:
        buf[0] += chunk
        while b"\n" in buf[0]:
            line, buf[0] = buf[0].split(b"\n", 1)
            text = line.decode(errors="replace").strip()
            if text:
                logger.debug("go: %s", text)
            if text.startswith(prefix):
                found.append(text)

    with trio.move_on_after(timeout):
        while len(found) < count:
            chunk = await stdout.receive_some(4096)
            if not chunk:
                return found
            _consume(chunk)

    if settle > 0.0 and found:
        with trio.move_on_after(settle):
            while True:
                chunk = await stdout.receive_some(4096)
                if not chunk:
                    break
                _consume(chunk)

    return found


def _lan_addr(listen_lines: list[str]) -> str:
    """Prefer loopback, then a concrete non-loopback IPv4 multiaddr."""
    addrs = [ln.split(" ", 1)[1] for ln in listen_lines]
    for a in addrs:
        if "/ip4/127.0.0.1/" in a:
            return a
    for a in addrs:
        if a.startswith("/ip4/") and "/ip4/127.0.0.1/" not in a:
            return a
    return addrs[0]


async def test_py_dials_go(go_webtransport_harness: Path) -> None:
    """Py WebTransport dialer connects to a go-libp2p WebTransport listener."""
    proc = await _spawn(go_webtransport_harness, "listen")
    try:
        lines = await _read_lines(proc, "LISTEN", count=1, settle=0.25)
        assert lines, "go harness never printed a LISTEN address"
        addr = _lan_addr(lines)
        go_id = addr.rsplit("/p2p/", 1)[1]

        dialer = _transport()
        try:
            with trio.fail_after(45):
                conn = await dialer.dial(Multiaddr(addr))
            assert conn.peer_id == ID.from_base58(go_id)
            await conn.close()
        finally:
            await dialer.close()
    finally:
        proc.terminate()
        with trio.move_on_after(5):
            await proc.wait()


async def test_go_dials_py(go_webtransport_harness: Path) -> None:
    """go-libp2p WebTransport dialer connects to our listener."""
    listener_t = _transport()
    got = trio.Event()
    seen: list[ID] = []

    async def handler(conn) -> None:  # type: ignore[no-untyped-def]
        seen.append(conn.peer_id)
        got.set()
        await trio.sleep_forever()

    listener = listener_t.create_listener(handler)
    await listener.listen(Multiaddr("/ip4/0.0.0.0/udp/0/quic-v1/webtransport"))
    addr = _lan_addr([f"X {a}" for a in map(str, listener.get_addrs())])

    proc = await _spawn(go_webtransport_harness, "dial", addr)
    try:
        with trio.fail_after(45):
            out = await _read_lines(proc, "DIAL_OK", count=1)
            await got.wait()
        assert out and seen
    finally:
        proc.terminate()
        with trio.move_on_after(5):
            await proc.wait()
        await listener.close()
        await listener_t.close()
