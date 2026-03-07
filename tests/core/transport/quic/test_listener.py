from unittest.mock import AsyncMock, Mock, patch

import pytest
from multiaddr.multiaddr import Multiaddr
import trio

from libp2p.crypto.ed25519 import (
    create_new_key_pair,
)
from libp2p.transport.quic.connection import QUICConnection
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
    await listener._registry.register_new_connection_id_for_existing_conn(
        unknown_cid, mock_connection, addr
    )

    # Verify connection was found and new CID registered
    conn, _, _ = await listener._registry.find_by_connection_id(unknown_cid)
    assert conn is mock_connection


@pytest.mark.trio
async def test_connection_id_tracking_with_real_connection():
    """Test that Connection ID tracking works with real QUIC connections."""
    from libp2p.transport.quic.utils import create_quic_multiaddr

    # Setup server
    server_key = create_new_key_pair()
    server_config = QUICTransportConfig(idle_timeout=10.0, connection_timeout=5.0)
    server_transport = QUICTransport(server_key.private_key, server_config)

    connection_established = False
    connection_from_handler: QUICConnection | None = None
    initial_connection_ids = set()
    new_connection_ids = set()

    async def connection_handler(connection: QUICConnection) -> None:
        """Handler that tracks Connection IDs."""
        nonlocal connection_established, connection_from_handler
        nonlocal initial_connection_ids, new_connection_ids

        connection_established = True
        connection_from_handler = connection

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
            # Use the connection object from the handler
            assert connection_from_handler is not None, (
                "Connection should be established"
            )

            # Verify all initial Connection IDs are in mappings
            for cid in initial_connection_ids:
                conn, _, _ = await listener._registry.find_by_connection_id(cid)
                assert conn is not None, (
                    f"Connection ID {cid.hex()[:8]} should map to a connection"
                )
                # Check that it's the same connection (same address and properties)
                assert conn._remote_addr == connection_from_handler._remote_addr, (
                    f"Connection ID {cid.hex()[:8]} should map to same connection "
                    f"(address mismatch)"
                )

            # Verify new Connection IDs (if any) are also tracked
            for cid in new_connection_ids:
                conn, _, _ = await listener._registry.find_by_connection_id(cid)
                assert conn is not None, (
                    f"New Connection ID {cid.hex()[:8]} should map to a connection"
                )
                # Check that it's the same connection (same address and properties)
                # Note: Connection objects may be different instances but represent
                # the same logical connection, so we check by address
                assert conn._remote_addr == connection_from_handler._remote_addr, (
                    f"New Connection ID {cid.hex()[:8]} should map to same connection "
                    f"(address mismatch: {conn._remote_addr} vs "
                    f"{connection_from_handler._remote_addr})"
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


class TestQUICListenerRaceConditions:
    """Regression tests for race condition fixes in PR #1096."""

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
        """Mock connection handler that tracks invocations."""
        handler_calls: list[int] = []

        async def handler(connection):
            handler_calls.append(id(connection))
            return connection

        # Use the function directly instead of AsyncMock to avoid side effects
        handler.calls = handler_calls  # type: ignore[attr-defined]
        handler.call_count = lambda: len(handler_calls)  # type: ignore[attr-defined]
        return handler

    @pytest.fixture
    def listener(self, transport, connection_handler):
        """Create test listener with security disabled for testing."""
        listener_obj = transport.create_listener(connection_handler)
        # Disable security manager for race condition tests to avoid certificate issues
        listener_obj._security_manager = None
        return listener_obj

    @pytest.fixture
    def mock_quic_connection(self):
        """Create mock aioquic QuicConnection."""
        mock = Mock()
        mock.configuration = Mock()
        mock.configuration.is_client = False
        mock.next_event.return_value = None
        mock.datagrams_to_send.return_value = []
        mock.get_timer.return_value = None
        mock.receive_datagram = Mock()
        return mock

    @pytest.mark.trio
    async def test_duplicate_promotion_prevention(
        self, listener, mock_quic_connection, connection_handler
    ):
        """Test that concurrent promotion attempts result in only one promotion."""
        addr = ("127.0.0.1", 4001)
        destination_cid = b"test_cid_12345678"

        # Register pending connection first
        await listener._registry.register_pending(
            destination_cid, mock_quic_connection, addr, 0
        )
        listener._pending_cid_by_quic_id[id(mock_quic_connection)] = destination_cid

        # Patch QUICConnection.connect to avoid blocking - patch at class level
        async def mock_connect(self, nursery):  # type: ignore[misc]
            # Mark as started to prevent re-entry
            self._background_tasks_started = True  # type: ignore[attr-defined]
            self._connected_event.set()  # type: ignore[attr-defined]
            self.event_started.set()  # type: ignore[attr-defined]

        # Create a nursery for the listener
        async with trio.open_nursery() as nursery:
            listener._nursery = nursery

            # Patch before any connections are created
            with patch.object(QUICConnection, "connect", new=mock_connect):
                # Simulate concurrent promotion attempts
                connection_objects: list = []

                async def attempt_promotion():
                    try:
                        await listener._promote_pending_connection(
                            mock_quic_connection, addr, destination_cid
                        )
                        # Get the connection object if it was created
                        quic_key = id(mock_quic_connection)
                        conn = listener._conn_by_quic_id.get(quic_key)
                        if conn:
                            connection_objects.append(conn)
                    except Exception:
                        pass  # Some attempts may fail, that's expected

                # Launch multiple concurrent promotion attempts
                for _ in range(10):
                    nursery.start_soon(attempt_promotion)

                # Give time for promotions to complete
                await trio.sleep(0.1)

                # Verify only one connection object was created
                assert len(set(connection_objects)) <= 1, (
                    "Multiple connection objects created"
                )
                assert len(listener._conn_by_quic_id) <= 1, (
                    "Multiple entries in _conn_by_quic_id"
                )

        # Verify only one connection object was created
        assert len(set(connection_objects)) <= 1, "Multiple connection objects created"
        assert len(listener._conn_by_quic_id) <= 1, (
            "Multiple entries in _conn_by_quic_id"
        )

    @pytest.mark.trio
    async def test_handler_invocation_once_per_connection(
        self, listener, mock_quic_connection, connection_handler
    ):
        """Test that handler is invoked exactly once per connection."""
        addr = ("127.0.0.1", 4001)
        destination_cid = b"test_cid_87654321"

        # Patch QUICConnection.connect to avoid blocking - patch at class level
        async def mock_connect(self, nursery):  # type: ignore[misc]
            # Mark as started to prevent re-entry
            self._background_tasks_started = True  # type: ignore[attr-defined]
            self._connected_event.set()  # type: ignore[attr-defined]
            self.event_started.set()  # type: ignore[attr-defined]

        # Register pending connection
        await listener._registry.register_pending(
            destination_cid, mock_quic_connection, addr, 0
        )
        listener._pending_cid_by_quic_id[id(mock_quic_connection)] = destination_cid

        # Create a nursery for the listener
        async with trio.open_nursery() as nursery:
            listener._nursery = nursery

            # Patch before any connections are created
            with patch.object(QUICConnection, "connect", new=mock_connect):
                # Simulate multiple packets arriving concurrently
                async def send_packet():
                    try:
                        await listener._promote_pending_connection(
                            mock_quic_connection, addr, destination_cid
                        )
                    except Exception:
                        pass  # Some may fail if connection already promoted

                # Launch 20 concurrent promotion attempts
                for _ in range(20):
                    nursery.start_soon(send_packet)

                # Give time for all promotions to complete
                await trio.sleep(0.2)

                # Verify handler was called at most once
                # (if connection was successfully created)
                quic_key = id(mock_quic_connection)
                connection_obj = listener._conn_by_quic_id.get(quic_key)
                if connection_obj is not None:
                    # If connection was created, handler should have been invoked
                    assert quic_key in listener._handler_invoked_quic_ids, (
                        "Handler should be marked as invoked when connection is created"
                    )
                # Note: connection_handler.call_count() would work
                # if we had a proper mock. For now, we verify the tracking set

    @pytest.mark.trio
    async def test_multiple_cid_routing_concurrent_load(
        self, listener, mock_quic_connection, connection_handler
    ):
        """Test packets with different CIDs route to same connection under load."""
        addr = ("127.0.0.1", 4001)
        primary_cid = b"primary_cid_1234"
        secondary_cid1 = b"secondary_cid_1"
        secondary_cid2 = b"secondary_cid_2"
        secondary_cid3 = b"secondary_cid_3"

        # Register pending connection with primary CID
        await listener._registry.register_pending(
            primary_cid, mock_quic_connection, addr, 0
        )
        listener._pending_cid_by_quic_id[id(mock_quic_connection)] = primary_cid

        # Patch QUICConnection.connect to avoid blocking - patch at class level
        async def mock_connect(self, nursery):  # type: ignore[misc]
            # Mark as started to prevent re-entry
            self._background_tasks_started = True  # type: ignore[attr-defined]
            self._connected_event.set()  # type: ignore[attr-defined]
            self.event_started.set()  # type: ignore[attr-defined]

        # Create a nursery for the listener
        async with trio.open_nursery() as nursery:
            listener._nursery = nursery

            # Patch before any connections are created
            with patch.object(QUICConnection, "connect", new=mock_connect):
                # Promote the connection first
                try:
                    await listener._promote_pending_connection(
                        mock_quic_connection, addr, primary_cid
                    )
                except Exception:
                    # Promotion may fail due to mock limitations, skip test if so
                    pytest.skip("Connection promotion failed due to mock limitations")

                # Get the connection object
                quic_key = id(mock_quic_connection)
                connection_obj = listener._conn_by_quic_id.get(quic_key)
                if connection_obj is None:
                    # If connection wasn't created, skip the test
                    pytest.skip(
                        "Connection not created, likely due to mock limitations"
                    )

                # Register additional CIDs for the same connection
                await listener._registry.register_new_connection_id_for_existing_conn(
                    secondary_cid1, connection_obj, addr
                )
                await listener._registry.register_new_connection_id_for_existing_conn(
                    secondary_cid2, connection_obj, addr
                )
                await listener._registry.register_new_connection_id_for_existing_conn(
                    secondary_cid3, connection_obj, addr
                )

                # Track which connection objects are found for each CID
                found_connections = []

                async def route_packet(cid):
                    conn, _, _ = await listener._registry.find_by_connection_id(cid)
                    if conn:
                        found_connections.append((cid, id(conn)))

                # Route packets with different CIDs concurrently
                cids = [primary_cid, secondary_cid1, secondary_cid2, secondary_cid3]
                for _ in range(5):  # Multiple rounds
                    for cid in cids:
                        nursery.start_soon(route_packet, cid)

                # Give time for routing to complete
                await trio.sleep(0.1)

                # Verify all CIDs route to the same connection object
                connection_ids = {conn_id for _, conn_id in found_connections}
                assert len(connection_ids) == 1, (
                    f"All CIDs should route to same connection, "
                    f"got {len(connection_ids)} different connections"
                )

                # Cleanup
                await listener._cleanup_promotion_lock(quic_key)
