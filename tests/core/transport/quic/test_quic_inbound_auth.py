"""
Regression tests for QUIC inbound peer authentication (issue #1345 / PR #1346).

Verifies that inbound connections without a libp2p TLS certificate are rejected
before the application callback is invoked.
"""

import ssl
import time
from unittest.mock import Mock, patch

import pytest
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.connection import QuicConnection as AioQuicConnection
import multiaddr
import trio

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.transport.quic.connection import QUICConnection
from libp2p.transport.quic.listener import ServerQuicConnection
from libp2p.transport.quic.security import QUICTLSConfigManager
from libp2p.transport.quic.transport import QUICTransport, QUICTransportConfig
from libp2p.transport.quic.utils import (
    create_quic_multiaddr,
    get_alpn_protocols,
    quic_multiaddr_to_endpoint,
)


async def _run_unauthenticated_quic_client(host: str, port: int) -> None:
    """
    Dial a libp2p QUIC listener using raw aioquic without a TLS certificate.

    Mirrors the issue #1345 PoC: the TLS handshake may complete, but no libp2p
    peer certificate is presented.
    """
    config = QuicConfiguration(is_client=True)
    config.verify_mode = ssl.CERT_NONE
    config.alpn_protocols = get_alpn_protocols()
    # Intentionally no config.certificate / config.private_key

    quic = AioQuicConnection(configuration=config)
    quic.connect((host, port), now=time.time())

    sock = trio.socket.socket(trio.socket.AF_INET, trio.socket.SOCK_DGRAM)
    await sock.bind(("127.0.0.1", 0))

    try:
        deadline = trio.current_time() + 10.0
        while trio.current_time() < deadline:
            now = time.time()
            for data, _dest in quic.datagrams_to_send(now=now):
                await sock.sendto(data, (host, port))

            with trio.move_on_after(0.05):
                try:
                    data, addr = await sock.recvfrom(65535)
                    quic.receive_datagram(data, addr, now=time.time())
                except trio.WouldBlock:
                    pass

            await trio.sleep(0.01)
    finally:
        sock.close()


@pytest.mark.trio
async def test_listener_rejects_inbound_without_peer_certificate() -> None:
    """Unauthenticated aioquic clients must not reach the application callback."""
    server_key = create_new_key_pair()
    server_config = QUICTransportConfig(idle_timeout=10.0, connection_timeout=5.0)
    server_transport = QUICTransport(server_key.private_key, server_config)

    handler_called = False

    async def handler(connection: QUICConnection) -> None:
        nonlocal handler_called
        handler_called = True

    listener = server_transport.create_listener(handler)
    listen_addr = create_quic_multiaddr("127.0.0.1", 0, "/quic-v1")

    try:
        async with trio.open_nursery() as nursery:
            server_transport.set_background_nursery(nursery)
            await listener.listen(listen_addr)

            host, port = quic_multiaddr_to_endpoint(listener.get_addrs()[0])

            await _run_unauthenticated_quic_client(host, port)

            for _ in range(50):
                stats = listener.get_stats()
                if stats["connections_rejected"] >= 1:
                    break
                await trio.sleep(0.1)
            else:
                stats = listener.get_stats()

            nursery.cancel_scope.cancel()
    finally:
        await listener.close()

    stats = listener.get_stats()
    assert handler_called is False
    assert stats["connections_rejected"] >= 1
    assert stats["connections_accepted"] == 0


@pytest.mark.trio
async def test_listener_accepts_authenticated_libp2p_peer() -> None:
    """Positive control: legitimate libp2p QUIC peers are still accepted."""
    server_key = create_new_key_pair()
    server_config = QUICTransportConfig(idle_timeout=10.0, connection_timeout=5.0)
    server_transport = QUICTransport(server_key.private_key, server_config)

    handler_called = False

    async def handler(connection: QUICConnection) -> None:
        nonlocal handler_called
        handler_called = True

    listener = server_transport.create_listener(handler)
    listen_addr = create_quic_multiaddr("127.0.0.1", 0, "/quic-v1")

    client_key = create_new_key_pair()
    client_config = QUICTransportConfig(idle_timeout=10.0, connection_timeout=5.0)
    client_transport = QUICTransport(client_key.private_key, client_config)

    try:
        async with trio.open_nursery() as nursery:
            server_transport.set_background_nursery(nursery)
            await listener.listen(listen_addr)

            server_addrs = listener.get_addrs()
            server_addr = multiaddr.Multiaddr(
                f"{server_addrs[0]}/p2p/{ID.from_pubkey(server_key.public_key)}"
            )

            client_transport.set_background_nursery(nursery)
            await client_transport.dial(server_addr)
            await trio.sleep(1.0)

            nursery.cancel_scope.cancel()
    finally:
        await listener.close()

    assert handler_called is True


def test_server_quic_connection_requests_client_certificate() -> None:
    """ServerQuicConnection must request a client certificate during TLS init."""
    fake_tls = Mock()
    fake_tls._request_client_certificate = False

    def fake_initialize(self, peer_cid: bytes) -> None:
        self.tls = fake_tls

    key_pair = create_new_key_pair()
    peer_id = ID.from_pubkey(key_pair.public_key)
    manager = QUICTLSConfigManager(
        libp2p_private_key=key_pair.private_key, peer_id=peer_id
    )

    config = QuicConfiguration(is_client=False)
    config.certificate = manager.tls_config.certificate
    config.private_key = manager.tls_config.private_key
    config.verify_mode = ssl.CERT_NONE
    config.alpn_protocols = get_alpn_protocols()

    conn = ServerQuicConnection(
        configuration=config,
        original_destination_connection_id=b"\x01" * 8,
    )

    with patch.object(AioQuicConnection, "_initialize", fake_initialize):
        conn._initialize(b"\x02" * 8)

    assert conn.tls._request_client_certificate is True
