"""
Unit tests for the Kademlia DHT implementation.

This module contains unit tests for the core KadDHT class functionality.
"""

import logging
from unittest.mock import (
    AsyncMock,
    Mock,
    patch,
)

import pytest
import trio

from libp2p.kad_dht.kad_dht import (
    PROTOCOL_ID,
    KadDHT,
)
from libp2p.kad_dht.pb.kademlia_pb2 import (
    Message,
)
from libp2p.network.stream.net_stream import (
    INetStream,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerinfo import (
    PeerInfo,
)

logger = logging.getLogger("test.kad_dht_unit")


class TestKadDHT:
    """Test cases for the KadDHT class."""

    @pytest.fixture
    def mock_host(self):
        """Create a mock host for testing."""
        host = Mock()
        host.get_id.return_value = ID(b"test_peer_id_12345678901234567890")
        host.get_addrs.return_value = []
        host.get_peerstore.return_value = Mock()
        host.set_stream_handler = Mock()
        host.new_stream = AsyncMock()
        host.connect = AsyncMock()
        return host

    @pytest.fixture
    def kad_dht_server(self, mock_host):
        """Create a KadDHT instance in server mode."""
        return KadDHT(mock_host, mode="server", bootstrap_peers=[])

    @pytest.fixture
    def kad_dht_client(self, mock_host):
        """Create a KadDHT instance in client mode."""
        return KadDHT(mock_host, mode="client", bootstrap_peers=[])

    def test_init_server_mode(self, mock_host):
        """Test KadDHT initialization in server mode."""
        bootstrap_peers = ["/ip4/127.0.0.1/tcp/4001/p2p/QmBootstrap"]
        dht = KadDHT(mock_host, mode="server", bootstrap_peers=bootstrap_peers)

        assert dht.host == mock_host
        assert dht.mode == "SERVER"
        assert dht.bootstrap_peers == bootstrap_peers
        assert dht.local_peer_id == mock_host.get_id()
        assert dht.routing_table is not None
        assert dht.peer_routing is not None
        assert dht.value_store is not None
        assert dht.provider_store is not None

        # Verify stream handler is set for server mode
        mock_host.set_stream_handler.assert_called_with(PROTOCOL_ID, dht.handle_stream)

    def test_init_client_mode(self, mock_host):
        """Test KadDHT initialization in client mode."""
        dht = KadDHT(mock_host, mode="client")

        assert dht.mode == "CLIENT"
        # Verify stream handler is set to None for client mode
        mock_host.set_stream_handler.assert_called_with(PROTOCOL_ID, None)

    def test_init_invalid_mode(self, mock_host):
        """Test KadDHT initialization with invalid mode."""
        with pytest.raises(ValueError, match="Invalid mode 'invalid'"):
            KadDHT(mock_host, mode="invalid")

    @pytest.mark.trio
    async def test_switch_mode_to_client(self, kad_dht_server):
        """Test switching from server to client mode."""
        result = await kad_dht_server.switch_mode("client")

        assert result == "CLIENT"
        assert kad_dht_server.mode == "CLIENT"
        kad_dht_server.host.set_stream_handler.assert_called_with(PROTOCOL_ID, None)

    @pytest.mark.trio
    async def test_switch_mode_to_server(self, kad_dht_client):
        """Test switching from client to server mode."""
        result = await kad_dht_client.switch_mode("server")

        assert result == "SERVER"
        assert kad_dht_client.mode == "SERVER"
        kad_dht_client.host.set_stream_handler.assert_called_with(
            PROTOCOL_ID, kad_dht_client.handle_stream
        )

    @pytest.mark.trio
    async def test_switch_mode_invalid(self, kad_dht_server):
        """Test switching to invalid mode."""
        with pytest.raises(ValueError, match="Invalid mode 'INVALID'"):
            await kad_dht_server.switch_mode("invalid")

    @pytest.mark.trio
    async def test_add_peer(self, kad_dht_server):
        """Test adding a peer to the routing table."""
        peer_id = ID(b"test_peer_id_99999999999999999999")

        with patch.object(
            kad_dht_server.routing_table, "add_peer", return_value=True
        ) as mock_add:
            result = await kad_dht_server.add_peer(peer_id)

            assert result is True
            mock_add.assert_called_once_with(peer_id)

    def test_get_routing_table_size(self, kad_dht_server):
        """Test getting routing table size."""
        with patch.object(
            kad_dht_server.routing_table, "size", return_value=5
        ) as mock_size:
            result = kad_dht_server.get_routing_table_size()

            assert result == 5
            mock_size.assert_called_once()

    def test_get_value_store_size(self, kad_dht_server):
        """Test getting value store size."""
        with patch.object(
            kad_dht_server.value_store, "size", return_value=10
        ) as mock_size:
            result = kad_dht_server.get_value_store_size()

            assert result == 10
            mock_size.assert_called_once()

    @pytest.mark.trio
    async def test_find_peer(self, kad_dht_server):
        """Test finding a peer."""
        peer_id = ID(b"test_peer_id_99999999999999999999")
        expected_peer_info = PeerInfo(peer_id, [])

        with patch.object(
            kad_dht_server.peer_routing, "find_peer", return_value=expected_peer_info
        ) as mock_find:
            result = await kad_dht_server.find_peer(peer_id)

            assert result == expected_peer_info
            mock_find.assert_called_once_with(peer_id)

    @pytest.mark.trio
    async def test_put_value(self, kad_dht_server):
        """Test storing a value in the DHT."""
        key = b"test_key"
        value = b"test_value"

        with patch.object(kad_dht_server.value_store, "put") as mock_put, patch.object(
            kad_dht_server.routing_table, "find_local_closest_peers", return_value=[]
        ) as mock_find:
            await kad_dht_server.put_value(key, value)

            mock_put.assert_called_once_with(key, value)
            mock_find.assert_called_once_with(key, 3)

    @pytest.mark.trio
    async def test_get_value_local(self, kad_dht_server):
        """Test retrieving a value from local store."""
        key = b"test_key"
        value = b"test_value"

        with patch.object(
            kad_dht_server.value_store, "get", return_value=value
        ) as mock_get:
            result = await kad_dht_server.get_value(key)

            assert result == value
            mock_get.assert_called_once_with(key)

    @pytest.mark.trio
    async def test_get_value_remote(self, kad_dht_server):
        """Test retrieving a value from remote peers."""
        key = b"test_key"
        value = b"test_value"
        peer_id = ID(b"remote_peer_id_123456789012345678")

        with patch.object(
            kad_dht_server.value_store, "get", return_value=None
        ) as mock_get_local, patch.object(
            kad_dht_server.routing_table,
            "find_local_closest_peers",
            return_value=[peer_id],
        ) as mock_find, patch.object(
            kad_dht_server.value_store, "_get_from_peer", return_value=value
        ) as mock_get_remote, patch.object(
            kad_dht_server.value_store, "put"
        ) as mock_put:
            result = await kad_dht_server.get_value(key)

            assert result == value
            mock_get_local.assert_called_once_with(key)
            mock_find.assert_called_once_with(key)
            mock_get_remote.assert_called_once_with(peer_id, key)
            mock_put.assert_called_once_with(key, value)

    @pytest.mark.trio
    async def test_refresh_routing_table(self, kad_dht_server):
        """Test refreshing the routing table."""
        with patch.object(
            kad_dht_server.peer_routing, "refresh_routing_table"
        ) as mock_refresh:
            await kad_dht_server.refresh_routing_table()

            mock_refresh.assert_called_once()

    @pytest.mark.trio
    async def test_handle_stream_find_node(self, kad_dht_server):
        """Test handling a FIND_NODE message."""
        # Create mock stream with proper muxed_conn attribute
        mock_stream = Mock(spec=INetStream)
        mock_muxed_conn = Mock()
        mock_muxed_conn.peer_id = ID(b"requesting_peer_123456789012345")
        mock_stream.muxed_conn = mock_muxed_conn

        # Mock stream read operations for varint and message
        target_key = b"target_key_1234567890123456"
        message = Message()
        message.type = Message.MessageType.FIND_NODE
        message.key = target_key
        msg_bytes = message.SerializeToString()

        # Mock varint reading
        mock_stream.read.side_effect = [
            b"\x10",  # varint length prefix (16 bytes)
            msg_bytes,  # actual message
        ]
        mock_stream.write = AsyncMock()
        mock_stream.close = AsyncMock()

        closest_peers = [
            ID(b"close_peer_1_123456789012345678"),
            ID(b"close_peer_2_123456789012345678"),
        ]

        with patch.object(
            kad_dht_server, "add_peer", return_value=True
        ) as mock_add_peer, patch.object(
            kad_dht_server.routing_table,
            "find_local_closest_peers",
            return_value=closest_peers,
        ) as mock_find, patch.object(
            kad_dht_server.host, "get_peerstore"
        ) as mock_peerstore:
            mock_peerstore.return_value.addrs.return_value = []

            await kad_dht_server.handle_stream(mock_stream)

            mock_add_peer.assert_called_once_with(mock_stream.muxed_conn.peer_id)
            mock_find.assert_called_once_with(target_key, 20)
            mock_stream.write.assert_called()
            mock_stream.close.assert_called_once()

    @pytest.mark.trio
    async def test_handle_stream_get_value(self, kad_dht_server):
        """Test handling a GET_VALUE message."""
        # Create mock stream with proper muxed_conn attribute
        mock_stream = Mock(spec=INetStream)
        mock_muxed_conn = Mock()
        mock_muxed_conn.peer_id = ID(b"requesting_peer_123456789012345")
        mock_stream.muxed_conn = mock_muxed_conn

        # Create GET_VALUE message
        key = b"test_key_1234567890"
        value = b"test_value"
        message = Message()
        message.type = Message.MessageType.GET_VALUE
        message.key = key
        msg_bytes = message.SerializeToString()

        # Mock stream operations
        mock_stream.read.side_effect = [
            b"\x15",  # varint length prefix (21 bytes)
            msg_bytes,  # actual message
        ]
        mock_stream.write = AsyncMock()
        mock_stream.close = AsyncMock()

        with patch.object(kad_dht_server, "add_peer", return_value=True), patch.object(
            kad_dht_server.value_store, "get", return_value=value
        ) as mock_get:
            await kad_dht_server.handle_stream(mock_stream)

            mock_get.assert_called_once_with(key)
            mock_stream.write.assert_called()
            mock_stream.close.assert_called_once()

    @pytest.mark.trio
    async def test_handle_stream_put_value(self, kad_dht_server):
        """Test handling a PUT_VALUE message."""
        # Create mock stream with proper muxed_conn attribute
        mock_stream = Mock(spec=INetStream)
        mock_muxed_conn = Mock()
        mock_muxed_conn.peer_id = ID(b"requesting_peer_123456789012345")
        mock_stream.muxed_conn = mock_muxed_conn

        # Create PUT_VALUE message
        key = b"test_key_1234567890"
        value = b"test_value"
        message = Message()
        message.type = Message.MessageType.PUT_VALUE
        message.record.key = key
        message.record.value = value
        msg_bytes = message.SerializeToString()

        # Mock stream operations
        mock_stream.read.side_effect = [
            bytes([len(msg_bytes)]),  # varint length prefix
            msg_bytes,  # actual message
        ]
        mock_stream.write = AsyncMock()
        mock_stream.close = AsyncMock()

        with patch.object(kad_dht_server, "add_peer", return_value=True), patch.object(
            kad_dht_server.value_store, "put"
        ) as mock_put:
            await kad_dht_server.handle_stream(mock_stream)

            mock_put.assert_called_once_with(key, value)
            mock_stream.write.assert_called()
            mock_stream.close.assert_called_once()

    @pytest.mark.trio
    async def test_run_service_loop(self, kad_dht_server):
        """Test the main service run loop."""
        with patch.object(
            kad_dht_server.peer_routing, "bootstrap"
        ) as mock_bootstrap, patch.object(
            kad_dht_server, "refresh_routing_table"
        ) as mock_refresh, patch.object(
            kad_dht_server.value_store, "cleanup_expired"
        ) as mock_cleanup_values, patch.object(
            kad_dht_server.provider_store, "cleanup_expired"
        ) as mock_cleanup_providers, patch(
            "trio.sleep"
        ) as mock_sleep:
            # Create a mock manager to simulate the service framework
            mock_manager = Mock()
            mock_manager.is_running = True

            # Set the manager attribute directly
            # since we're not using the full service framework
            kad_dht_server._manager = mock_manager

            # Make the service stop after a few iterations
            call_count = 0

            def sleep_side_effect(*args):
                nonlocal call_count
                call_count += 1
                if call_count >= 2:  # Stop after second sleep call
                    mock_manager.is_running = False
                # Don't actually sleep in tests
                return

            mock_sleep.side_effect = sleep_side_effect

            # Run the service
            await kad_dht_server.run()

            # Verify bootstrap was called if bootstrap peers exist
            if kad_dht_server.bootstrap_peers:
                mock_bootstrap.assert_called_once_with(kad_dht_server.bootstrap_peers)

            # Verify maintenance tasks were called
            assert mock_refresh.call_count >= 1
            assert mock_cleanup_values.call_count >= 1
            assert mock_cleanup_providers.call_count >= 1
            assert mock_sleep.call_count >= 1

    @pytest.mark.trio
    async def test_handle_stream_connection_error(self, kad_dht_server):
        """Test handling stream when connection fails."""
        mock_stream = Mock(spec=INetStream)
        mock_muxed_conn = Mock()
        mock_muxed_conn.peer_id = ID(b"requesting_peer_123456789012345")
        mock_stream.muxed_conn = mock_muxed_conn
        mock_stream.read.side_effect = Exception("Connection failed")
        mock_stream.close = AsyncMock()

        with patch.object(kad_dht_server, "add_peer", return_value=True):
            # Should not raise exception, just handle gracefully
            await kad_dht_server.handle_stream(mock_stream)
            mock_stream.close.assert_called_once()

    @pytest.mark.trio
    async def test_handle_stream_invalid_varint(self, kad_dht_server):
        """Test handling stream with invalid varint length."""
        mock_stream = Mock(spec=INetStream)
        mock_muxed_conn = Mock()
        mock_muxed_conn.peer_id = ID(b"requesting_peer_123456789012345")
        mock_stream.muxed_conn = mock_muxed_conn

        # Mock invalid varint (empty byte)
        mock_stream.read.side_effect = [b"", None]
        mock_stream.close = AsyncMock()

        with patch.object(kad_dht_server, "add_peer", return_value=True):
            # Should not raise exception, just handle gracefully
            await kad_dht_server.handle_stream(mock_stream)
            mock_stream.close.assert_called_once()

    def test_protocol_constants(self):
        """Test that protocol constants are properly defined."""
        assert PROTOCOL_ID == "/ipfs/kad/1.0.0"

    @pytest.mark.trio
    async def test_service_integration(self, kad_dht_server):
        """Test basic service integration with background service."""
        # Create a mock manager to simulate the service framework
        mock_manager = Mock()
        mock_manager.is_running = True

        # Set the manager attribute directly
        # since we're not using the full service framework
        kad_dht_server._manager = mock_manager

        # Mock the manager to control service lifecycle
        with patch("trio.sleep") as mock_sleep:
            # Make sleep raise Cancelled to stop the service loop after first call
            def sleep_side_effect(*args):
                mock_manager.is_running = False
                raise trio.Cancelled._create()

            mock_sleep.side_effect = sleep_side_effect

            try:
                await kad_dht_server.run()
            except trio.Cancelled:
                pass  # Expected behavior

            # Verify sleep was called (service loop started)
            mock_sleep.assert_called()
