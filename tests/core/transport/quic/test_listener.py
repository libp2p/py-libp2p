from unittest.mock import AsyncMock, Mock

import pytest
from multiaddr.multiaddr import Multiaddr
import trio

from libp2p.crypto.ed25519 import (
    create_new_key_pair,
)
from libp2p.transport.quic.exceptions import (
    QUICListenError,
)
from libp2p.transport.quic.listener import QUICListener
from libp2p.transport.quic.transport import (
    QUICTransport,
    QUICTransportConfig,
)
from libp2p.transport.quic.utils import (
    create_quic_multiaddr,
)


class TestQUICListener:
    """Test suite for QUIC listener functionality."""

    @pytest.fixture
    def private_key(self):
        """Generate test private key."""
        return create_new_key_pair().private_key

    @pytest.fixture
    def transport_config(self):
        """Generate test transport configuration."""
        return QUICTransportConfig(idle_timeout=10.0)

    @pytest.fixture
    def transport(self, private_key, transport_config):
        """Create test transport instance."""
        return QUICTransport(private_key, transport_config)

    @pytest.fixture
    def connection_handler(self):
        """Mock connection handler."""
        return AsyncMock()

    @pytest.fixture
    def listener(self, transport, connection_handler):
        """Create test listener."""
        return transport.create_listener(connection_handler)

    def test_listener_creation(self, transport, connection_handler):
        """Test listener creation."""
        listener = transport.create_listener(connection_handler)

        assert isinstance(listener, QUICListener)
        assert listener._transport == transport
        assert listener._handler == connection_handler
        assert not listener._listening
        assert not listener._closed

    @pytest.mark.trio
    async def test_listener_invalid_multiaddr(self, listener: QUICListener):
        """Test listener with invalid multiaddr."""
        async with trio.open_nursery() as nursery:
            invalid_addr = Multiaddr("/ip4/127.0.0.1/tcp/4001")

            with pytest.raises(QUICListenError, match="Invalid QUIC multiaddr"):
                await listener.listen(invalid_addr, nursery)

    @pytest.mark.trio
    async def test_listener_basic_lifecycle(self, listener: QUICListener):
        """Test basic listener lifecycle."""
        listen_addr = create_quic_multiaddr("127.0.0.1", 0, "/quic")  # Port 0 = random

        async with trio.open_nursery() as nursery:
            # Start listening
            success = await listener.listen(listen_addr, nursery)
            assert success
            assert listener.is_listening()

            # Check bound addresses
            addrs = listener.get_addrs()
            assert len(addrs) == 1

            # Check stats
            stats = listener.get_stats()
            assert stats["is_listening"] is True
            assert stats["active_connections"] == 0
            assert stats["pending_connections"] == 0

            # Sender Cancel Signal
            nursery.cancel_scope.cancel()

        await listener.close()
        assert not listener.is_listening()

    @pytest.mark.trio
    async def test_listener_double_listen(self, listener: QUICListener):
        """Test that double listen raises error."""
        listen_addr = create_quic_multiaddr("127.0.0.1", 9001, "/quic")

        try:
            async with trio.open_nursery() as nursery:
                success = await listener.listen(listen_addr, nursery)
                assert success
                await trio.sleep(0.01)

                addrs = listener.get_addrs()
                assert len(addrs) > 0
                async with trio.open_nursery() as nursery2:
                    with pytest.raises(QUICListenError, match="Already listening"):
                        await listener.listen(listen_addr, nursery2)
                        nursery2.cancel_scope.cancel()

                nursery.cancel_scope.cancel()
        finally:
            await listener.close()

    @pytest.mark.trio
    async def test_listener_port_binding(self, listener: QUICListener):
        """Test listener port binding and cleanup."""
        listen_addr = create_quic_multiaddr("127.0.0.1", 0, "/quic")

        try:
            async with trio.open_nursery() as nursery:
                success = await listener.listen(listen_addr, nursery)
                assert success
                await trio.sleep(0.5)

                addrs = listener.get_addrs()
                assert len(addrs) > 0

                nursery.cancel_scope.cancel()
        finally:
            await listener.close()

        # By the time we get here, the listener and its tasks have been fully
        # shut down, allowing the nursery to exit without hanging.
        print("TEST COMPLETED SUCCESSFULLY.")

    @pytest.mark.trio
    async def test_listener_stats_tracking(self, listener):
        """Test listener statistics tracking."""
        initial_stats = listener.get_stats()

        # All counters should start at 0
        assert initial_stats["connections_accepted"] == 0
        assert initial_stats["connections_rejected"] == 0
        assert initial_stats["bytes_received"] == 0
        assert initial_stats["packets_processed"] == 0


@pytest.mark.trio
async def test_listener_fallback_routing_by_address():
    """Test that listener can route packets by address when CID is unknown."""
    # Setup
    private_key = create_new_key_pair().private_key
    config = QUICTransportConfig(idle_timeout=10.0)
    transport = QUICTransport(private_key, config)
    handler = AsyncMock()
    listener = transport.create_listener(handler)

    # Create mock connection
    mock_connection = Mock()
    addr = ("127.0.0.1", 9999)
    mock_connection._remote_addr = addr

    initial_cid = b"\x01" * 8
    unknown_cid = b"\x02" * 8

    # Register connection with initial CID
    await listener._registry.register_connection(initial_cid, mock_connection, addr)

    # Simulate fallback mechanism: find by address when CID unknown
    connection_found, found_cid = await listener._registry.find_by_address(addr)
    assert connection_found is mock_connection

    # Register the new CID using the registry
    await listener._registry.register_new_connection_id_for_existing_connection(
        unknown_cid, mock_connection, addr
    )

    # Verify connection was found and new CID registered
    conn, _, _ = await listener._registry.find_by_connection_id(unknown_cid)
    assert conn is mock_connection


@pytest.mark.trio
async def test_connection_id_tracking_with_real_connection():
    """Test that Connection ID tracking works with real QUIC connections."""
    from libp2p.transport.quic.connection import QUICConnection
    from libp2p.transport.quic.utils import create_quic_multiaddr

    # Setup server
    server_key = create_new_key_pair()
    server_config = QUICTransportConfig(idle_timeout=10.0, connection_timeout=5.0)
    server_transport = QUICTransport(server_key.private_key, server_config)

    connection_established = False
    initial_connection_ids = set()
    new_connection_ids = set()

    async def connection_handler(connection: QUICConnection) -> None:
        """Handler that tracks Connection IDs."""
        nonlocal connection_established, initial_connection_ids, new_connection_ids

        connection_established = True

        # Get initial Connection IDs from listener
        # Find this connection in the listener's registry
        for listener in server_transport._listeners:
            cids = await listener._registry.get_all_cids_for_connection(connection)
            initial_connection_ids.update(cids)

        # Wait a bit for potential new Connection IDs to be issued
        await trio.sleep(0.5)

        # Check for new Connection IDs
        for listener in server_transport._listeners:
            cids = await listener._registry.get_all_cids_for_connection(connection)
            for cid in cids:
                if cid not in initial_connection_ids:
                    new_connection_ids.add(cid)

    # Create listener
    listener = server_transport.create_listener(connection_handler)
    listen_addr = create_quic_multiaddr("127.0.0.1", 0, "/quic")

    # Setup client
    client_key = create_new_key_pair()
    client_config = QUICTransportConfig(idle_timeout=10.0, connection_timeout=5.0)
    client_transport = QUICTransport(client_key.private_key, client_config)

    try:
        async with trio.open_nursery() as nursery:
            # Start server
            server_transport.set_background_nursery(nursery)
            success = await listener.listen(listen_addr, nursery)
            assert success, "Failed to start server listener"

            server_addrs = listener.get_addrs()
            assert len(server_addrs) > 0, "Server should have listen addresses"

            # Get server address with peer ID
            import multiaddr

            from libp2p.peer.id import ID

            server_addr = multiaddr.Multiaddr(
                f"{server_addrs[0]}/p2p/{ID.from_pubkey(server_key.public_key)}"
            )

            # Give server time to be ready
            await trio.sleep(0.1)

            # Connect client to server
            client_transport.set_background_nursery(nursery)
            client_connection = await client_transport.dial(server_addr)

            # Wait for connection to be established and handler to run
            await trio.sleep(1.0)

            # Verify connection was established
            assert connection_established, "Connection handler should have been called"

            # Verify at least one Connection ID was tracked
            assert len(initial_connection_ids) > 0, (
                "At least one Connection ID should be tracked initially"
            )

            # Verify Connection ID mappings exist in listener
            # Get the connection object from the handler
            # We need to find the connection that was established
            connection_found = None
            for listener in server_transport._listeners:
                cids = await listener._registry.get_all_established_cids()
                if cids:
                    conn, _, _ = await listener._registry.find_by_connection_id(cids[0])
                    if conn:
                        connection_found = conn
                        break

            assert connection_found is not None, "Connection should be established"

            # Verify all initial Connection IDs are in mappings
            for cid in initial_connection_ids:
                conn, _, _ = await listener._registry.find_by_connection_id(cid)
                assert conn is connection_found, (
                    f"Connection ID {cid.hex()[:8]} should map to connection"
                )

            # Verify new Connection IDs (if any) are also tracked
            for cid in new_connection_ids:
                conn, _, _ = await listener._registry.find_by_connection_id(cid)
                assert conn is connection_found, (
                    f"New Connection ID {cid.hex()[:8]} should map to connection"
                )

            # Clean up
            await client_connection.close()
            await client_transport.close()

            # Cancel nursery to stop server
            nursery.cancel_scope.cancel()

    finally:
        # Cleanup
        if not listener._closed:
            await listener.close()
        await server_transport.close()
        if not client_transport._closed:
            await client_transport.close()
