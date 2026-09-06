"""
go-libp2p ↔ py-libp2p WebRTC-Direct interop.

Runs the pinned go-libp2p v0.49 harness (built by conftest) against our
transport in both directions and both protocol versions.

py → go is exercised for real. go → py is currently xfail: the inbound
listener path tears the peer connection down right after ICE completes
(libp2p/py-libp2p#1470); the go dialer just times out.
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
from libp2p.transport.webrtc.config import WebRTCTransportConfig
from libp2p.transport.webrtc.transport import WebRTCDirectTransport

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.trio


def _transport(**cfg: object) -> WebRTCDirectTransport:
    # ice_servers=[] keeps everything on-box; no public STUN round-trip.
    return WebRTCDirectTransport(
        private_key=create_new_key_pair().private_key,
        config=WebRTCTransportConfig(ice_servers=[], **cfg),  # type: ignore[arg-type]
    )


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
    call. Without this, a second wait-for-N call either loses siblings already
    sitting in the pipe or burns the full *timeout* when no further lines come.
    """
    stdout = proc.stdout
    assert stdout is not None  # opened with stdout=PIPE above
    found: list[str] = []
    # Mutable cell so the nested drain helper can update the incomplete-line
    # remainder without a `nonlocal` (pyrefly rejects that pattern here).
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
        # Drain siblings from the same burst / near-simultaneous prints.
        with trio.move_on_after(settle):
            while True:
                chunk = await stdout.receive_some(4096)
                if not chunk:
                    break
                _consume(chunk)

    return found


def _lan_addr(listen_lines: list[str]) -> str:
    """
    Prefer a concrete non-loopback IPv4 multiaddr (Windows can't reach
    127.0.0.1 from a LAN-bound socket; go gathers LAN host candidates).
    """
    addrs = [ln.split(" ", 1)[1] for ln in listen_lines]
    for a in addrs:
        if a.startswith("/ip4/") and "/ip4/127.0.0.1/" not in a:
            return a
    return addrs[0]


@pytest.mark.parametrize("version", [1, 2])
async def test_py_dials_go(go_harness: Path, version: int) -> None:
    """Py dialer (v1/v2) connects to a go-libp2p listener."""
    proc = await _spawn(go_harness, "listen")
    try:
        # One call: wait for the first LISTEN, then briefly settle for siblings
        # (go prints one LISTEN per interface back-to-back).
        lines = await _read_lines(proc, "LISTEN", count=1, settle=0.25)
        assert lines, "go harness never printed a LISTEN address"
        addr = _lan_addr(lines)
        go_id = addr.rsplit("/p2p/", 1)[1]

        dialer = _transport(webrtc_direct_dial_version=version)
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


@pytest.mark.xfail(reason="go->py inbound stalls after ICE; see #1470", strict=True)
@pytest.mark.parametrize("version", [1, 2])
async def test_go_dials_py(go_harness: Path, version: int) -> None:
    """go-libp2p dialer (v1/v2) connects to our listener."""
    listener_t = _transport()
    got = trio.Event()
    seen: list[ID] = []

    async def handler(conn) -> None:  # type: ignore[no-untyped-def]
        seen.append(conn.peer_id)
        got.set()
        await trio.sleep_forever()

    listener = listener_t.create_listener(handler)
    await listener.listen(Multiaddr("/ip4/0.0.0.0/udp/0/webrtc-direct"))
    addr = _lan_addr([f"X {a}" for a in map(str, listener.get_addrs())])

    proc = await _spawn(go_harness, "dial", "-version", str(version), addr)
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
