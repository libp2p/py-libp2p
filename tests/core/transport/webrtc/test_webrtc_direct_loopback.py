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


def _listen_addr() -> str:
    """
    Listen on a concrete non-loopback IPv4 interface when one exists.

    aiortc dialers gather LAN host candidates only (aioice skips loopback) and
    on Windows a LAN-bound UDP socket cannot send to 127.0.0.1 at all
    (WinError 1214), so a listener advertising 127.0.0.1 is unreachable there.
    Linux's weak-host model hides this. Falls back to loopback when the host
    has no other IPv4 address.
    """
    from libp2p.utils.address_validation import get_available_interfaces

    for maddr in get_available_interfaces(0, "udp"):
        ip = maddr.value_for_protocol("ip4") if "/ip4/" in str(maddr) else None
        if ip and ip != "127.0.0.1":
            return f"/ip4/{ip}/udp/0/webrtc-direct"
    return "/ip4/127.0.0.1/udp/0/webrtc-direct"


LISTEN_ADDR = _listen_addr()


def _host_port(maddr) -> tuple[str, int]:  # type: ignore[no-untyped-def]
    parts = str(maddr).split("/")
    return parts[2], int(parts[4])


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

    await listener.listen(Multiaddr(LISTEN_ADDR))

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


def _transport(**cfg):  # type: ignore[no-untyped-def]
    from libp2p.transport.webrtc.config import WebRTCTransportConfig

    # ice_servers=[] keeps loopback local (no external STUN round-trip).
    kp = create_new_key_pair()
    return WebRTCDirectTransport(
        private_key=kp.private_key,
        config=WebRTCTransportConfig(ice_servers=[], **cfg),
    ), kp


@pytest.mark.trio
@pytest.mark.parametrize("harness", [False, True], ids=["stun", "sdp-http-harness"])
async def test_dial_listen_open_stream_echo(harness):
    """
    Full transport loopback: dial → ICE/DTLS → Noise (server initiates,
    dialer responds) → handler gets an authenticated connection → stream echo.
    Runs over the spec STUN path (default) and the experimental HTTP harness.
    """
    from multiaddr import Multiaddr

    from libp2p.peer.id import ID

    server, server_kp = _transport(enable_sdp_http_harness=harness)
    dialer, dialer_kp = _transport(enable_sdp_http_harness=harness)
    server_id = ID.from_pubkey(server_kp.public_key)
    dialer_id = ID.from_pubkey(dialer_kp.public_key)

    seen_by_server: list[ID] = []
    handler_done = trio.Event()

    async def echo_handler(conn) -> None:  # type: ignore[no-untyped-def]
        seen_by_server.append(conn.peer_id)
        stream = await conn.accept_stream()
        data = await stream.read()
        await stream.write(data)
        await handler_done.wait()

    listener = server.create_listener(echo_handler)
    await listener.listen(Multiaddr(LISTEN_ADDR))
    (maddr,) = listener.get_addrs()
    assert listener._mux is not None  # STUN path is always on
    assert (listener._signaling_server is not None) is harness

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
async def test_concurrent_dials_share_one_udp_port():
    """Two dialers hit the same advertised port; the mux demuxes by ufrag."""
    from multiaddr import Multiaddr

    from libp2p.peer.id import ID

    server, _ = _transport()
    dialers = [_transport() for _ in range(2)]
    dialer_ids = {ID.from_pubkey(kp.public_key) for _, kp in dialers}
    seen: set[ID] = set()
    release = trio.Event()

    async def handler(conn) -> None:  # type: ignore[no-untyped-def]
        seen.add(conn.peer_id)
        stream = await conn.accept_stream()
        await stream.write(await stream.read())
        await release.wait()

    listener = server.create_listener(handler)
    await listener.listen(Multiaddr(LISTEN_ADDR))
    (maddr,) = listener.get_addrs()
    conns = []

    async def _dial(t) -> None:  # type: ignore[no-untyped-def]
        conn = await t.dial(maddr)
        stream = await conn.open_stream()
        payload = f"hello from {id(t)}".encode()
        await stream.write(payload)
        assert await stream.read() == payload
        conns.append(conn)

    try:
        with trio.fail_after(30):
            async with trio.open_nursery() as nursery:
                for t, _ in dialers:
                    nursery.start_soon(_dial, t)
            assert seen == dialer_ids
            # Both dials went through the one mux socket: two ufrags registered.
            assert len(listener._mux._by_ufrag) == 2
            release.set()
            for c in conns:
                await c.close()
    finally:
        await listener.close()
        for t, _ in dialers:
            await t.close()
        await server.close()


@pytest.mark.trio
async def test_unknown_version_prefix_is_rejected():
    """A first contact without a libp2p+webrtc+vN/ prefix must not create a PC."""
    import asyncio

    from multiaddr import Multiaddr

    from libp2p.transport.webrtc._udp_mux import UdpMux
    from tests.core.transport.webrtc.test_udp_mux import _stun_binding_request

    server, _ = _transport()
    listener = server.create_listener(lambda conn: trio.sleep_forever())
    await listener.listen(Multiaddr(LISTEN_ADDR))
    (maddr,) = listener.get_addrs()
    host, port = _host_port(maddr)
    bridge = await server._ensure_bridge()

    async def _poke() -> None:
        # Fresh UDP endpoint on the asyncio thread; send crafted requests.
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            asyncio.DatagramProtocol, local_addr=("0.0.0.0", 0)
        )
        try:
            for username in ("noprefix1:cli1", "libp2p+webrtc+v9/abcd:cli1", "x:y"):
                transport.sendto(_stun_binding_request(username), (host, port))
            await asyncio.sleep(0.2)
        finally:
            transport.close()

    try:
        await bridge.run_coro(_poke())
        assert isinstance(listener._mux, UdpMux)
        assert listener._mux._by_ufrag == {}
        assert listener._in_flight == 0
    finally:
        await listener.close()
        await server.close()


@pytest.mark.trio
async def test_in_flight_cap_drops_excess_first_contacts():
    """Beyond max_in_flight_connections, new first contacts are dropped."""
    import asyncio

    from multiaddr import Multiaddr

    from tests.core.transport.webrtc.test_udp_mux import _stun_binding_request

    server, _ = _transport(max_in_flight_connections=1)
    listener = server.create_listener(lambda conn: trio.sleep_forever())
    await listener.listen(Multiaddr(LISTEN_ADDR))
    (maddr,) = listener.get_addrs()
    host, port = _host_port(maddr)
    bridge = await server._ensure_bridge()

    async def _poke() -> None:
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            asyncio.DatagramProtocol, local_addr=("0.0.0.0", 0)
        )
        try:
            for i in range(3):
                cred = f"libp2p+webrtc+v1/{'a' * 20}{i}"
                transport.sendto(_stun_binding_request(f"{cred}:{cred}"), (host, port))
            await asyncio.sleep(0.3)
        finally:
            transport.close()

    try:
        await bridge.run_coro(_poke())
        assert listener._in_flight == 1
        assert len(listener._mux._by_ufrag) == 1
        assert len(listener._accept_tasks) == 1
        # close() cancels the in-flight setup instead of letting it wait out
        # handshake_timeout.
        with trio.fail_after(5):
            await listener.close()
        assert listener._accept_tasks == set()
    finally:
        await listener.close()
        await server.close()


@pytest.mark.trio
async def test_listen_bind_failure_raises_connection_error():
    """A port already in use surfaces as WebRTCConnectionError, no orphans."""
    from multiaddr import Multiaddr

    from libp2p.transport.webrtc.exceptions import WebRTCConnectionError

    server, _ = _transport()
    first = server.create_listener(lambda conn: trio.sleep_forever())
    await first.listen(Multiaddr("/ip4/127.0.0.1/udp/0/webrtc-direct"))
    (maddr,) = first.get_addrs()
    port = int(str(maddr).split("/udp/")[1].split("/")[0])
    second = server.create_listener(lambda conn: trio.sleep_forever())
    try:
        with pytest.raises(WebRTCConnectionError):
            await second.listen(Multiaddr(f"/ip4/127.0.0.1/udp/{port}/webrtc-direct"))
        assert second._nursery is None and second._mux is None
    finally:
        await first.close()
        await server.close()


@pytest.mark.trio
async def test_dial_rejects_wrong_p2p_id():
    """A /p2p/ component that doesn't match the authenticated server fails."""
    from multiaddr import Multiaddr

    from libp2p.peer.id import ID
    from libp2p.transport.webrtc.exceptions import WebRTCConnectionError

    server, _ = _transport()
    dialer, _ = _transport()

    async def handler(conn) -> None:  # type: ignore[no-untyped-def]
        await trio.sleep_forever()

    listener = server.create_listener(handler)
    await listener.listen(Multiaddr(LISTEN_ADDR))
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

    server, _ = _transport()
    dialer, _ = _transport()
    calls = 0

    async def bad_handler(conn) -> None:  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        raise RuntimeError("boom")

    listener = server.create_listener(bad_handler)
    await listener.listen(Multiaddr(LISTEN_ADDR))
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
