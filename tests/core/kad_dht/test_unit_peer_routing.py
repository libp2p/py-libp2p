"""
Unit tests for the PeerRouting class in Kademlia DHT.

This module tests the core functionality of peer routing including:
- Peer discovery and lookup
- Network queries for closest peers
- Protocol message handling
- Error handling and edge cases
"""

import time
from unittest.mock import (
    AsyncMock,
    Mock,
    patch,
)

import pytest
from multiaddr import (
    Multiaddr,
)
import varint

from libp2p.crypto.secp256k1 import (
    create_new_key_pair,
)
from libp2p.kad_dht.pb.kademlia_pb2 import (
    Message,
)
from libp2p.kad_dht.peer_routing import (
    ALPHA,
    MAX_PEER_LOOKUP_ROUNDS,
    PROTOCOL_ID,
    PeerRouting,
)
from libp2p.kad_dht.routing_table import (
    RoutingTable,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerinfo import (
    PeerInfo,
)


def create_valid_peer_id(name: str) -> ID:
    """Create a valid peer ID for testing."""
    key_pair = create_new_key_pair()
    return ID.from_pubkey(key_pair.public_key)


class TestPeerRouting:
    """Test suite for PeerRouting class."""

    @pytest.fixture
    def mock_host(self):
        """Create a mock host for testing."""
        host = Mock()
        host.get_id.return_value = create_valid_peer_id("local")
        host.get_addrs.return_value = [Multiaddr("/ip4/127.0.0.1/tcp/8000")]
        host.get_peerstore.return_value = Mock()
        host.new_stream = AsyncMock()
        host.connect = AsyncMock()
        return host

    @pytest.fixture
    def mock_routing_table(self, mock_host):
        """Create a mock routing table for testing."""
        local_id = create_valid_peer_id("local")
        routing_table = RoutingTable(local_id, mock_host)
        return routing_table

    @pytest.fixture
    def peer_routing(self, mock_host, mock_routing_table):
        """Create a PeerRouting instance for testing."""
        return PeerRouting(mock_host, mock_routing_table)

    @pytest.fixture
    def sample_peer_info(self):
        """Create sample peer info for testing."""
        peer_id = create_valid_peer_id("sample")
        addresses = [Multiaddr("/ip4/127.0.0.1/tcp/8001")]
        return PeerInfo(peer_id, addresses)

    def test_init_peer_routing(self, mock_host, mock_routing_table):
        """Test PeerRouting initialization."""
        peer_routing = PeerRouting(mock_host, mock_routing_table)

        assert peer_routing.host == mock_host
        assert peer_routing.routing_table == mock_routing_table

    @pytest.mark.trio
    async def test_find_peer_local_host(self, peer_routing, mock_host):
        """Test finding our own peer."""
        local_id = mock_host.get_id()

        result = await peer_routing.find_peer(local_id)

        assert result is not None
        assert result.peer_id == local_id
        assert result.addrs == mock_host.get_addrs()

    @pytest.mark.trio
    async def test_find_peer_in_routing_table(self, peer_routing, sample_peer_info):
        """Test finding peer that exists in routing table."""
        # Add peer to routing table
        await peer_routing.routing_table.add_peer(sample_peer_info)

        result = await peer_routing.find_peer(sample_peer_info.peer_id)

        assert result is not None
        assert result.peer_id == sample_peer_info.peer_id

    @pytest.mark.trio
    async def test_find_peer_in_peerstore(self, peer_routing, mock_host):
        """Test finding peer that exists in peerstore."""
        peer_id = create_valid_peer_id("peerstore")
        mock_addrs = [Multiaddr("/ip4/127.0.0.1/tcp/8002")]

        # Mock peerstore to return addresses
        mock_host.get_peerstore().addrs.return_value = mock_addrs

        result = await peer_routing.find_peer(peer_id)

        assert result is not None
        assert result.peer_id == peer_id
        assert result.addrs == mock_addrs

    @pytest.mark.trio
    async def test_find_peer_not_found(self, peer_routing, mock_host):
        """Test finding peer that doesn't exist anywhere."""
        peer_id = create_valid_peer_id("nonexistent")

        # Mock peerstore to return no addresses
        mock_host.get_peerstore().addrs.return_value = []

        # Mock network search to return empty results
        with patch.object(peer_routing, "find_closest_peers_network", return_value=[]):
            result = await peer_routing.find_peer(peer_id)

            assert result is None

    @pytest.mark.trio
    async def test_find_closest_peers_network_empty_start(self, peer_routing):
        """Test network search with no local peers."""
        target_key = b"target_key"

        # Mock routing table to return empty list
        with patch.object(
            peer_routing.routing_table, "find_local_closest_peers", return_value=[]
        ):
            result = await peer_routing.find_closest_peers_network(target_key)

            assert result == []

    @pytest.mark.trio
    async def test_find_closest_peers_network_with_peers(self, peer_routing, mock_host):
        """Test network search with some initial peers."""
        target_key = b"target_key"

        # Create some test peers
        initial_peers = [create_valid_peer_id(f"peer{i}") for i in range(3)]

        # Mock routing table to return initial peers
        with patch.object(
            peer_routing.routing_table,
            "find_local_closest_peers",
            return_value=initial_peers,
        ):
            # Mock _query_peer_for_closest to return empty results (no new peers found)
            with patch.object(peer_routing, "_query_peer_for_closest", return_value=[]):
                result = await peer_routing.find_closest_peers_network(
                    target_key, count=5
                )

                assert len(result) <= 5
                # Should return the initial peers since no new ones were discovered
                assert all(peer in initial_peers for peer in result)

    @pytest.mark.trio
    async def test_find_closest_peers_convergence(self, peer_routing):
        """Test that network search converges properly."""
        target_key = b"target_key"

        # Create test peers
        initial_peers = [create_valid_peer_id(f"peer{i}") for i in range(2)]

        # Mock to simulate convergence (no improvement in closest peers)
        with patch.object(
            peer_routing.routing_table,
            "find_local_closest_peers",
            return_value=initial_peers,
        ):
            with patch.object(peer_routing, "_query_peer_for_closest", return_value=[]):
                with patch(
                    "libp2p.kad_dht.peer_routing.sort_peer_ids_by_distance",
                    return_value=initial_peers,
                ):
                    result = await peer_routing.find_closest_peers_network(target_key)

                    assert result == initial_peers

    @pytest.mark.trio
    async def test_query_peer_for_closest_success(
        self, peer_routing, mock_host, sample_peer_info
    ):
        """Test successful peer query for closest peers."""
        target_key = b"target_key"

        # Create mock stream
        mock_stream = AsyncMock()
        mock_host.new_stream.return_value = mock_stream

        # Create mock response
        response_msg = Message()
        response_msg.type = Message.MessageType.FIND_NODE

        # Add a peer to the response
        peer_proto = response_msg.closerPeers.add()
        response_peer_id = create_valid_peer_id("response_peer")
        peer_proto.id = response_peer_id.to_bytes()
        peer_proto.addrs.append(Multiaddr("/ip4/127.0.0.1/tcp/8003").to_bytes())

        response_bytes = response_msg.SerializeToString()

        # Mock stream reading
        varint_length = varint.encode(len(response_bytes))
        mock_stream.read.side_effect = [varint_length, response_bytes]

        # Mock peerstore
        mock_host.get_peerstore().addrs.return_value = [sample_peer_info.addrs[0]]
        mock_host.get_peerstore().add_addrs = Mock()

        result = await peer_routing._query_peer_for_closest(
            sample_peer_info.peer_id, target_key
        )

        assert len(result) == 1
        assert result[0] == response_peer_id
        mock_stream.write.assert_called()
        mock_stream.close.assert_called_once()

    @pytest.mark.trio
    async def test_query_peer_for_closest_stream_failure(self, peer_routing, mock_host):
        """Test peer query when stream creation fails."""
        target_key = b"target_key"
        peer_id = create_valid_peer_id("test")

        # Mock stream creation failure
        mock_host.new_stream.side_effect = Exception("Stream failed")
        mock_host.get_peerstore().addrs.return_value = []

        result = await peer_routing._query_peer_for_closest(peer_id, target_key)

        assert result == []

    @pytest.mark.trio
    async def test_query_peer_for_closest_read_failure(
        self, peer_routing, mock_host, sample_peer_info
    ):
        """Test peer query when reading response fails."""
        target_key = b"target_key"

        # Create mock stream that fails to read
        mock_stream = AsyncMock()
        mock_stream.read.side_effect = [b""]  # Empty read simulates connection close
        mock_host.new_stream.return_value = mock_stream
        mock_host.get_peerstore().addrs.return_value = [sample_peer_info.addrs[0]]

        result = await peer_routing._query_peer_for_closest(
            sample_peer_info.peer_id, target_key
        )

        assert result == []
        mock_stream.close.assert_called_once()

    @pytest.mark.trio
    async def test_refresh_routing_table(self, peer_routing, mock_host):
        """Test routing table refresh."""
        local_id = mock_host.get_id()
        discovered_peers = [create_valid_peer_id(f"discovered{i}") for i in range(3)]

        # Mock find_closest_peers_network to return discovered peers
        with patch.object(
            peer_routing, "find_closest_peers_network", return_value=discovered_peers
        ):
            # Mock peerstore to return addresses for discovered peers
            mock_addrs = [Multiaddr("/ip4/127.0.0.1/tcp/8003")]
            mock_host.get_peerstore().addrs.return_value = mock_addrs

            await peer_routing.refresh_routing_table()

            # Should perform lookup for local ID
            peer_routing.find_closest_peers_network.assert_called_once_with(
                local_id.to_bytes()
            )

    @pytest.mark.trio
    async def test_handle_kad_stream_find_node(self, peer_routing, mock_host):
        """Test handling incoming FIND_NODE requests."""
        # Create mock stream
        mock_stream = AsyncMock()

        # Create FIND_NODE request
        request_msg = Message()
        request_msg.type = Message.MessageType.FIND_NODE
        request_msg.key = b"target_key"

        request_bytes = request_msg.SerializeToString()

        # Mock stream reading
        mock_stream.read.side_effect = [
            len(request_bytes).to_bytes(4, byteorder="big"),
            request_bytes,
        ]

        # Mock routing table to return some peers
        closest_peers = [create_valid_peer_id(f"close{i}") for i in range(2)]
        with patch.object(
            peer_routing.routing_table,
            "find_local_closest_peers",
            return_value=closest_peers,
        ):
            mock_host.get_peerstore().addrs.return_value = [
                Multiaddr("/ip4/127.0.0.1/tcp/8004")
            ]

            await peer_routing._handle_kad_stream(mock_stream)

            # Should write response
            mock_stream.write.assert_called()
            mock_stream.close.assert_called_once()

    @pytest.mark.trio
    async def test_handle_kad_stream_invalid_message(self, peer_routing):
        """Test handling stream with invalid message."""
        mock_stream = AsyncMock()

        # Mock stream to return invalid data
        mock_stream.read.side_effect = [
            (10).to_bytes(4, byteorder="big"),
            b"invalid_proto_data",
        ]

        # Should handle gracefully without raising exception
        await peer_routing._handle_kad_stream(mock_stream)

        mock_stream.close.assert_called_once()

    @pytest.mark.trio
    async def test_handle_kad_stream_connection_closed(self, peer_routing):
        """Test handling stream when connection is closed early."""
        mock_stream = AsyncMock()

        # Mock stream to return empty data (connection closed)
        mock_stream.read.return_value = b""

        await peer_routing._handle_kad_stream(mock_stream)

        mock_stream.close.assert_called_once()

    @pytest.mark.trio
    async def test_query_single_peer_for_closest_success(self, peer_routing):
        """Test _query_single_peer_for_closest method."""
        target_key = b"target_key"
        peer_id = create_valid_peer_id("test")
        new_peers = []

        # Mock successful query
        mock_result = [create_valid_peer_id("result1"), create_valid_peer_id("result2")]
        with patch.object(
            peer_routing, "_query_peer_for_closest", return_value=mock_result
        ):
            await peer_routing._query_single_peer_for_closest(
                peer_id, target_key, new_peers
            )

            assert len(new_peers) == 2
            assert all(peer in new_peers for peer in mock_result)

    @pytest.mark.trio
    async def test_query_single_peer_for_closest_failure(self, peer_routing):
        """Test _query_single_peer_for_closest when query fails."""
        target_key = b"target_key"
        peer_id = create_valid_peer_id("test")
        new_peers = []

        # Mock query failure
        with patch.object(
            peer_routing,
            "_query_peer_for_closest",
            side_effect=Exception("Query failed"),
        ):
            await peer_routing._query_single_peer_for_closest(
                peer_id, target_key, new_peers
            )

            # Should handle exception gracefully
            assert len(new_peers) == 0

    @pytest.mark.trio
    async def test_query_single_peer_deduplication(self, peer_routing):
        """Test that _query_single_peer_for_closest deduplicates peers."""
        target_key = b"target_key"
        peer_id = create_valid_peer_id("test")
        duplicate_peer = create_valid_peer_id("duplicate")
        new_peers = [duplicate_peer]  # Pre-existing peer

        # Mock query to return the same peer
        mock_result = [duplicate_peer, create_valid_peer_id("new")]
        with patch.object(
            peer_routing, "_query_peer_for_closest", return_value=mock_result
        ):
            await peer_routing._query_single_peer_for_closest(
                peer_id, target_key, new_peers
            )

            # Should not add duplicate
            assert len(new_peers) == 2  # Original + 1 new peer
            assert new_peers.count(duplicate_peer) == 1

    def test_constants(self):
        """Test that important constants are properly defined."""
        assert ALPHA == 3
        assert MAX_PEER_LOOKUP_ROUNDS == 20
        assert PROTOCOL_ID == "/ipfs/kad/1.0.0"

    @pytest.mark.trio
    async def test_edge_case_max_rounds_reached(self, peer_routing):
        """Test that lookup stops after maximum rounds."""
        target_key = b"target_key"
        initial_peers = [create_valid_peer_id("peer1")]

        # Mock to always return new peers to force max rounds
        def mock_query_side_effect(peer, key):
            return [create_valid_peer_id(f"new_peer_{time.time()}")]

        with patch.object(
            peer_routing.routing_table,
            "find_local_closest_peers",
            return_value=initial_peers,
        ):
            with patch.object(
                peer_routing,
                "_query_peer_for_closest",
                side_effect=mock_query_side_effect,
            ):
                with patch(
                    "libp2p.kad_dht.peer_routing.sort_peer_ids_by_distance"
                ) as mock_sort:
                    # Always return different peers to prevent convergence
                    mock_sort.side_effect = lambda key, peers: peers[:20]

                    result = await peer_routing.find_closest_peers_network(target_key)

                    # Should stop after max rounds, not infinite loop
                    assert isinstance(result, list)
