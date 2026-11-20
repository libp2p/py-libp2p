"""
End-to-end checks that abandoning a stream releases it in aioquic.

aioquic removes a stream from ``QuicConnection._streams`` only when both its
sender and receiver report finished, and a half finishes only after its FIN,
RESET or STOP_SENDING is acknowledged. The unit tests in test_connection.py
assert which frames py-libp2p queues; these tests drive a real QUIC connection
between two peers and assert that the stream actually leaves aioquic's
registry rather than being pinned for the lifetime of the connection.
"""

from typing import Any

import pytest
import multiaddr
import trio

from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.transport.quic.config import QUICTransportConfig
from libp2p.transport.quic.transport import QUICTransport
from libp2p.transport.quic.utils import create_quic_multiaddr


async def _wait_until(predicate: Any, timeout: float = 8.0) -> bool:
    """Return True once *predicate* holds, or False after *timeout* seconds."""
    with trio.move_on_after(timeout) as scope:
        while not predicate():
            await trio.sleep(0.02)
    return not scope.cancelled_caught


class _EchoPeer:
    """Server-side fixture keeping one accepted stream open for a test."""

    peer_addr: multiaddr.Multiaddr

    def __init__(self) -> None:
        self.connection: Any = None
        self.stream: Any = None
        self.release = trio.Event()
        self.accepted = trio.Event()
        self.transport: QUICTransport | None = None
        self.listener: Any = None

    async def handle_connection(self, connection: Any) -> None:
        try:
            stream = await connection.accept_stream(timeout=5.0)
            if stream is None:
                return
            self.connection = connection
            self.stream = stream
        except Exception:
            return
        self.accepted.set()
        # Keep the connection owned by the handler until the test is done.
        await self.release.wait()

    async def start(self) -> None:
        key = create_new_key_pair()
        self.transport = QUICTransport(key.private_key, QUICTransportConfig())
        self.listener = self.transport.create_listener(self.handle_connection)
        await self.listener.listen(create_quic_multiaddr("127.0.0.1", 0, "/quic"))
        addr = self.listener.get_addrs()[0]
        self.peer_addr = multiaddr.Multiaddr(
            f"{addr}/p2p/{ID.from_pubkey(key.public_key)}"
        )

    async def stop(self) -> None:
        self.release.set()
        if self.listener is not None and not self.listener._closed:
            await self.listener.close()
        if self.transport is not None:
            await self.transport.close()


@pytest.mark.trio
async def test_dropped_wrapper_lets_aioquic_discard_the_stream() -> None:
    """
    Removing a wrapper whose send half is still open must finish the stream.

    This is the dominant production leak shape: a peer-initiated bidirectional
    stream whose send half was never used, with the wrapper dropped before
    aioquic saw a FIN or RESET. Without the release step the stream stays in
    ``_quic._streams`` until the connection dies.
    """
    server = _EchoPeer()
    await server.start()
    client_connection = None
    client_transport = None

    async with trio.open_nursery() as nursery:
        try:
            client_transport = QUICTransport(
                create_new_key_pair().private_key, QUICTransportConfig()
            )
            client_transport.set_background_nursery(nursery)
            client_connection = await client_transport.dial(server.peer_addr)
            client_stream = await client_connection.open_stream()
            await client_stream.write(b"hello")
            with trio.fail_after(8.0):
                await server.accepted.wait()

            server_connection = server.connection
            aioquic_stream_id = int(server.stream.stream_id)
            assert aioquic_stream_id in server_connection._quic._streams

            server_connection._remove_stream(aioquic_stream_id)

            assert await _wait_until(
                lambda: aioquic_stream_id not in server_connection._quic._streams
            ), "aioquic still tracks the stream after its wrapper was removed"
        finally:
            await server.stop()
            if client_connection is not None:
                await client_connection.close()
            if client_transport is not None:
                await client_transport.close()
            nursery.cancel_scope.cancel()


@pytest.mark.trio
async def test_abandoned_stream_is_discarded_by_aioquic() -> None:
    """
    Stop+RESET must release a live stream: it is what the ignore sites call.

    The abandoned stream has no pending application data and no FIN, so the only
    way it can leave ``_quic._streams`` is the explicit release frame.
    """
    server = _EchoPeer()
    await server.start()
    client_connection = None
    client_transport = None

    async with trio.open_nursery() as nursery:
        try:
            client_transport = QUICTransport(
                create_new_key_pair().private_key, QUICTransportConfig()
            )
            client_transport.set_background_nursery(nursery)
            client_connection = await client_transport.dial(server.peer_addr)
            client_stream = await client_connection.open_stream()
            await client_stream.write(b"hello")
            with trio.fail_after(8.0):
                await server.accepted.wait()

            server_connection = server.connection
            aioquic_stream_id = int(server.stream.stream_id)
            assert aioquic_stream_id in server_connection._quic._streams

            server_connection._abandon_quic_stream(aioquic_stream_id)

            assert await _wait_until(
                lambda: aioquic_stream_id not in server_connection._quic._streams
            ), "aioquic still tracks the abandoned stream"
        finally:
            await server.stop()
            if client_connection is not None:
                await client_connection.close()
            if client_transport is not None:
                await client_transport.close()
            nursery.cancel_scope.cancel()
