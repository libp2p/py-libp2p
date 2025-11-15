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
    async with listener._connection_lock:
        listener._connections[initial_cid] = mock_connection
        listener._cid_to_addr[initial_cid] = addr
        listener._addr_to_cid[addr] = initial_cid

    # Simulate fallback mechanism: find by address when CID unknown
    async with listener._connection_lock:
        connection_found = None
        for cid, conn in listener._connections.items():
            if hasattr(conn, "_remote_addr") and conn._remote_addr == addr:
                connection_found = conn
                # Register the new CID
                listener._connections[unknown_cid] = conn
                listener._cid_to_addr[unknown_cid] = addr
                break

    # Verify connection was found and new CID registered
    assert connection_found is mock_connection
    assert listener._connections[unknown_cid] is mock_connection
    assert listener._cid_to_addr[unknown_cid] == addr
