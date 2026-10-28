"""
End-to-end py↔py WebTransport dial/listen with Noise + stream echo.
"""

from __future__ import annotations

import pytest
from multiaddr import Multiaddr
import trio

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.crypto.keys import KeyPair
from libp2p.peer.id import ID
from libp2p.transport.webtransport.transport import WebTransportTransport


def _transport() -> tuple[WebTransportTransport, KeyPair]:
    kp = create_new_key_pair()
    return WebTransportTransport(private_key=kp.private_key), kp


@pytest.mark.trio
async def test_dial_listen_open_stream_echo() -> None:
    server, server_kp = _transport()
    dialer, dialer_kp = _transport()
    dialer_id = ID.from_pubkey(dialer_kp.public_key)
    server_id = ID.from_pubkey(server_kp.public_key)

    seen_by_server: list[ID] = []
    ready = trio.Event()

    async def echo_handler(conn) -> None:  # type: ignore[no-untyped-def]
        seen_by_server.append(conn.peer_id)
        stream = await conn.accept_stream()
        data = await stream.read()
        await stream.write(data)
        await stream.close()

    listener = server.create_listener(echo_handler)
    listen_maddr = Multiaddr("/ip4/127.0.0.1/udp/0/quic-v1/webtransport")
    await listener.listen(listen_maddr)
    addrs = listener.get_addrs()
    assert len(addrs) >= 1
    maddr = addrs[0]
    assert "/webtransport/" in str(maddr)
    assert "/certhash/" in str(maddr)
    assert "/p2p/" in str(maddr)
    ready.set()

    try:
        with trio.fail_after(30):
            await ready.wait()
            conn = await dialer.dial(maddr)
            assert conn.peer_id == server_id
            stream = await conn.open_stream()
            await stream.write(b"ping-over-webtransport")
            assert await stream.read() == b"ping-over-webtransport"
            assert seen_by_server == [dialer_id]
            await conn.close()
    finally:
        await listener.close()
        await dialer.close()
        await server.close()


@pytest.mark.trio
async def test_listener_advertises_dual_certhash() -> None:
    transport, _ = _transport()

    async def noop(conn: object) -> None:
        pass

    listener = transport.create_listener(noop)
    await listener.listen(Multiaddr("/ip4/127.0.0.1/udp/0/quic-v1/webtransport"))
    try:
        addr = str(listener.get_addrs()[0])
        assert addr.count("/certhash/") == 2
    finally:
        await listener.close()
        await transport.close()
