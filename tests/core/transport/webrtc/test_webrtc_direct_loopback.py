"""
Integration tests for WebRTC Direct listener setup (aiortc required).

Verifies that a listener advertises a multiaddr with /certhash/ and /p2p/,
binds a real port when port 0 is requested, uses an aiortc-native
certificate, and — end to end — that dial() reaches the listener's handler
through ICE/DTLS + Noise (server initiates, dialer responds) and a stream
echoes.  See test_multiplexing_loopback.py for data-channel layer loopback.
"""
# pyrefly: ignore

from __future__ import annotations

import pytest
import trio

try:
    import aiortc  # noqa: F401

    HAS_AIORTC = True
except ImportError:
    HAS_AIORTC = False

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.transport.webrtc.transport import WebRTCDirectTransport

pytestmark = pytest.mark.skipif(not HAS_AIORTC, reason="aiortc not installed")


@pytest.mark.trio
async def test_listener_advertises_certhash_in_multiaddr():
    """Listener publishes a multiaddr that contains /certhash/ and /p2p/."""
    key_pair = create_new_key_pair()
    transport = WebRTCDirectTransport(private_key=key_pair.private_key)

    async def noop_handler(conn: object) -> None:
        pass

    listener = transport.create_listener(noop_handler)
    maddr_str = "/ip4/127.0.0.1/udp/0/webrtc-direct"

    from multiaddr import Multiaddr

    await listener.listen(Multiaddr(maddr_str))

    addrs = listener.get_addrs()
    assert len(addrs) == 1
    addr_str = str(addrs[0])
    assert "/webrtc-direct/" in addr_str
    assert "/certhash/" in addr_str
    assert "/p2p/" in addr_str

    await listener.close()
    await transport.close()


@pytest.mark.trio
async def test_listener_binds_actual_port():
    """When port 0 is requested, the listener binds to a real port > 0."""
    key_pair = create_new_key_pair()
    transport = WebRTCDirectTransport(private_key=key_pair.private_key)

    async def noop_handler(conn: object) -> None:
        pass

    listener = transport.create_listener(noop_handler)
    from multiaddr import Multiaddr

    await listener.listen(Multiaddr("/ip4/127.0.0.1/udp/0/webrtc-direct"))

    addrs = listener.get_addrs()
    addr_str = str(addrs[0])
    # Parse the port from the multiaddr
    parts = addr_str.split("/")
    udp_idx = parts.index("udp")
    port = int(parts[udp_idx + 1])
    assert port > 0

    await listener.close()
    await transport.close()


@pytest.mark.trio
async def test_certificate_is_aiortc_native():
    """Transport certificate should have an aiortc RTCCertificate attached."""
    key_pair = create_new_key_pair()
    transport = WebRTCDirectTransport(private_key=key_pair.private_key)
    assert hasattr(transport.certificate, "_rtc_certificate")
    assert transport.certificate._rtc_certificate is not None
    await transport.close()


@pytest.mark.trio
async def test_dial_listen_open_stream_echo():
    """
    Full transport loopback: dial → ICE/DTLS → Noise (server initiates,
    dialer responds) → handler gets an authenticated connection → stream echo.
    """
    from multiaddr import Multiaddr

    from libp2p.peer.id import ID
    from libp2p.transport.webrtc.config import WebRTCTransportConfig

    server_kp = create_new_key_pair()
    dialer_kp = create_new_key_pair()
    server_id = ID.from_pubkey(server_kp.public_key)
    dialer_id = ID.from_pubkey(dialer_kp.public_key)
    # ice_servers=[] keeps loopback local (no external STUN round-trip).
    server = WebRTCDirectTransport(
        private_key=server_kp.private_key,
        config=WebRTCTransportConfig(ice_servers=[]),
    )
    dialer = WebRTCDirectTransport(
        private_key=dialer_kp.private_key,
        config=WebRTCTransportConfig(ice_servers=[]),
    )

    seen_by_server: list[ID] = []
    handler_done = trio.Event()

    async def echo_handler(conn) -> None:  # type: ignore[no-untyped-def]
        seen_by_server.append(conn.peer_id)
        stream = await conn.accept_stream()
        data = await stream.read()
        await stream.write(data)
        await handler_done.wait()

    listener = server.create_listener(echo_handler)
    await listener.listen(Multiaddr("/ip4/127.0.0.1/udp/0/webrtc-direct"))
    (maddr,) = listener.get_addrs()

    try:
        with trio.fail_after(30):
            conn = await dialer.dial(maddr)
            assert conn.peer_id == server_id
            stream = await conn.open_stream()
            await stream.write(b"ping-over-webrtc-direct")
            assert await stream.read() == b"ping-over-webrtc-direct"
            assert seen_by_server == [dialer_id]
            handler_done.set()
            await conn.close()
    finally:
        await listener.close()
        await dialer.close()
        await server.close()


@pytest.mark.trio
async def test_dial_rejects_wrong_p2p_id():
    """A /p2p/ component that doesn't match the authenticated server fails."""
    from multiaddr import Multiaddr

    from libp2p.peer.id import ID
    from libp2p.transport.webrtc.config import WebRTCTransportConfig
    from libp2p.transport.webrtc.exceptions import WebRTCConnectionError

    server = WebRTCDirectTransport(
        private_key=create_new_key_pair().private_key,
        config=WebRTCTransportConfig(ice_servers=[]),
    )
    dialer = WebRTCDirectTransport(
        private_key=create_new_key_pair().private_key,
        config=WebRTCTransportConfig(ice_servers=[]),
    )

    async def handler(conn) -> None:  # type: ignore[no-untyped-def]
        await trio.sleep_forever()

    listener = server.create_listener(handler)
    await listener.listen(Multiaddr("/ip4/127.0.0.1/udp/0/webrtc-direct"))
    (maddr,) = listener.get_addrs()
    impostor = ID.from_pubkey(create_new_key_pair().public_key)
    wrong = Multiaddr(str(maddr).rsplit("/p2p/", 1)[0] + f"/p2p/{impostor}")

    try:
        with trio.fail_after(30):
            with pytest.raises(WebRTCConnectionError):
                await dialer.dial(wrong)
    finally:
        await listener.close()
        await dialer.close()
        await server.close()


@pytest.mark.trio
async def test_handler_exception_does_not_crash_listener():
    """
    A raising handler must only affect its own connection: the listener
    nursery lives in a trio system task, so an escaping exception would
    otherwise abort the whole trio run.
    """
    from multiaddr import Multiaddr

    from libp2p.transport.webrtc.config import WebRTCTransportConfig

    server = WebRTCDirectTransport(
        private_key=create_new_key_pair().private_key,
        config=WebRTCTransportConfig(ice_servers=[]),
    )
    dialer = WebRTCDirectTransport(
        private_key=create_new_key_pair().private_key,
        config=WebRTCTransportConfig(ice_servers=[]),
    )
    calls = 0

    async def bad_handler(conn) -> None:  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        raise RuntimeError("boom")

    listener = server.create_listener(bad_handler)
    await listener.listen(Multiaddr("/ip4/127.0.0.1/udp/0/webrtc-direct"))
    (maddr,) = listener.get_addrs()
    try:
        with trio.fail_after(30):
            conn = await dialer.dial(maddr)  # handshake completes before handler
            while calls == 0:
                await trio.sleep(0.01)
            await conn.close()
            # Listener still alive and usable.
            conn2 = await dialer.dial(maddr)
            await conn2.close()
        assert calls == 2
    finally:
        await listener.close()
        await dialer.close()
        await server.close()
