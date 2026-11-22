"""
go-libp2p ↔ py-libp2p WebRTC-Direct interop.

Runs the pinned go-libp2p v0.49 harness (built by conftest) against our
transport in both directions and both protocol versions.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from multiaddr import Multiaddr
import trio

from libp2p.peer.id import ID
from tests.interop.webrtc_direct_harness import (
    lan_addr,
    make_transport,
    read_lines,
    spawn,
)

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.trio


@pytest.mark.parametrize("version", [1, 2])
async def test_py_dials_go(go_harness: Path, version: int) -> None:
    """Py dialer (v1/v2) connects to a go-libp2p listener."""
    proc = await spawn([go_harness], "listen")
    try:
        # One call: wait for the first LISTEN, then briefly settle for siblings
        # (go prints one LISTEN per interface back-to-back).
        lines = await read_lines(proc, "LISTEN", count=1, settle=0.25)
        assert lines, "go harness never printed a LISTEN address"
        addr = lan_addr(lines)
        go_id = addr.rsplit("/p2p/", 1)[1]

        dialer = make_transport(webrtc_direct_dial_version=version)
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


@pytest.mark.parametrize("version", [1, 2])
async def test_go_dials_py(go_harness: Path, version: int) -> None:
    """go-libp2p dialer (v1/v2) connects to our listener."""
    listener_t = make_transport()
    got = trio.Event()
    seen: list[ID] = []

    async def handler(conn) -> None:  # type: ignore[no-untyped-def]
        seen.append(conn.peer_id)
        got.set()
        await trio.sleep_forever()

    listener = listener_t.create_listener(handler)
    await listener.listen(Multiaddr("/ip4/0.0.0.0/udp/0/webrtc-direct"))
    addr = lan_addr([f"X {a}" for a in map(str, listener.get_addrs())])

    proc = await spawn([go_harness], "dial", "-version", str(version), addr)
    try:
        with trio.fail_after(45):
            out = await read_lines(proc, "DIAL_OK", count=1)
            await got.wait()
        assert out and seen
    finally:
        proc.terminate()
        with trio.move_on_after(5):
            await proc.wait()
        await listener.close()
        await listener_t.close()
