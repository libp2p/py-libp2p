"""
Unit tests for the Kademlia DHT peer routing implementation.

This module contains unit tests for the PeerRouting class.
"""

import logging
from unittest.mock import (
    AsyncMock,
    Mock,
    patch,
)

import pytest
from multiaddr import (
    Multiaddr,
)

from libp2p.kad_dht.pb.kademlia_pb2 import (
    Message,
)
from libp2p.kad_dht.peer_routing import (
    ALPHA,
    MAX_PEER_LOOKUP_ROUNDS,
    PeerRouting,
)
from libp2p.kad_dht.routing_table import (
    RoutingTable,
)
from libp2p.network.stream.net_stream import (
    INetStream,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerinfo import (
    InvalidAddrError,
    PeerInfo,
)

logger = logging.getLogger("test.peer_routing")


class TestPeerRouting:
    """Test cases for the PeerRouting class."""

    @pytest.fixture
    def mock_host(self):
        """Create a mock host for testing."""
        host = Mock()
        host.get_id.return_value = ID(b"test_peer_id_12345678901234567890")
        host.get_addrs.return_value = [Multiaddr("/ip4/127.0.0.1/tcp/4001")]
        host.get_peerstore.return_value = Mock()
        host.set_stream_handler = Mock()
        host.new_stream = AsyncMock()
        host.connect = AsyncMock()
        return host

    @pytest.fixture
    def mock_routing_table(self, mock_host):
        """Create a mock routing table for testing."""
        local_id = ID(b"local_peer_id_123456789012345678")
        return RoutingTable(local_id, mock_host)

    @pytest.fixture
    def peer_routing(self, mock_host, mock_routing_table):
        """Create a PeerRouting instance for testing."""
        return PeerRouting(mock_host, mock_routing_table)

    @pytest.fixture
    def sample_peer_info(self):
        """Create sample peer info for testing."""
        peer_id = ID(b"sample_peer_id_123456789012345678")
        addrs = [Multiaddr("/ip4/127.0.0.1/tcp/4001")]
        return PeerInfo(peer_id, addrs)

    def test_peer_routing_init(self, mock_host, mock_routing_table):
        """Test PeerRouting initialization."""
        pr = PeerRouting(mock_host, mock_routing_table)

        assert pr.host == mock_host
        assert pr.routing_table == mock_routing_table
        assert pr.protocol_id == "/ipfs/kad/1.0.0"

        # Note: Stream handler is now managed by KadDHT, not PeerRouting
        # so we don't expect set_stream_handler to be called here

    @pytest.mark.trio
    async def test_find_peer_self(self, peer_routing):
        """Test finding our own peer ID."""
        self_id = peer_routing.host.get_id()

        result = await peer_routing.find_peer(self_id)

        assert result is not None
        assert result.peer_id == self_id
        assert result.addrs == peer_routing.host.get_addrs()

    @pytest.mark.trio
    async def test_find_peer_in_routing_table(self, peer_routing, sample_peer_info):
        """Test finding a peer that's in our routing table."""
        with patch.object(
            peer_routing.routing_table, "get_peer_info", return_value=sample_peer_info
        ) as mock_get:
            result = await peer_routing.find_peer(sample_peer_info.peer_id)

            assert result == sample_peer_info
            mock_get.assert_called_once_with(sample_peer_info.peer_id)

    @pytest.mark.trio
    async def test_find_peer_in_peerstore(self, peer_routing, sample_peer_info):
        """Test finding a peer that's in our peerstore but not routing table."""
        with patch.object(
            peer_routing.routing_table, "get_peer_info", return_value=None
        ), patch.object(
            peer_routing.host.get_peerstore(),
            "addrs",
            return_value=sample_peer_info.addrs,
        ):
            result = await peer_routing.find_peer(sample_peer_info.peer_id)

            assert result is not None
            assert result.peer_id == sample_peer_info.peer_id
            assert result.addrs == sample_peer_info.addrs

    @pytest.mark.trio
    async def test_find_peer_network_search(self, peer_routing, sample_peer_info):
        """Test finding a peer through network search."""
        # Create a mock peerstore
        mock_peerstore = Mock()

        # First call (checking if peer exists locally) returns empty list
        # Second call (after network search) returns the peer's addresses
        mock_peerstore.addrs.side_effect = [[], sample_peer_info.addrs]

        with patch.object(
            peer_routing.routing_table, "get_peer_info", return_value=None
        ), patch.object(
            peer_routing.host, "get_peerstore", return_value=mock_peerstore
        ), patch.object(
            peer_routing,
            "find_closest_peers_network",
            return_value=[sample_peer_info.peer_id],
        ) as mock_find:
            result = await peer_routing.find_peer(sample_peer_info.peer_id)

            assert result is not None
            assert result.peer_id == sample_peer_info.peer_id
            mock_find.assert_called_once_with(sample_peer_info.peer_id.to_bytes())

    @pytest.mark.trio
    async def test_find_peer_not_found(self, peer_routing, sample_peer_info):
        """Test finding a peer that doesn't exist."""
        with patch.object(
            peer_routing.routing_table, "get_peer_info", return_value=None
        ), patch.object(
            peer_routing.host.get_peerstore(), "addrs", return_value=[]
        ), patch.object(
            peer_routing, "find_closest_peers_network", return_value=[]
        ):
            result = await peer_routing.find_peer(sample_peer_info.peer_id)

            assert result is None

    @pytest.mark.trio
    async def test_find_closest_peers_network_empty_table(self, peer_routing):
        """Test network search when routing table is empty."""
        target_key = b"target_key_123456789012345678901234"

        with patch.object(
            peer_routing.routing_table, "find_local_closest_peers", return_value=[]
        ):
            result = await peer_routing.find_closest_peers_network(target_key)

            assert result == []

    @pytest.mark.trio
    async def test_find_closest_peers_network_with_peers(self, peer_routing):
        """Test network search with available peers."""
        target_key = b"target_key_123456789012345678901234"
        local_peers = [
            ID(b"local_peer_1_123456789012345678901"),
            ID(b"local_peer_2_123456789012345678901"),
        ]

        with patch.object(
            peer_routing.routing_table,
            "find_local_closest_peers",
            return_value=local_peers,
        ), patch.object(peer_routing, "_query_single_peer_for_closest"):
            result = await peer_routing.find_closest_peers_network(target_key, count=5)

            # Should return the local peers since no new peers were discovered
            assert len(result) <= len(local_peers)

    @pytest.mark.trio
    async def test_query_peer_for_closest_success(self, peer_routing, sample_peer_info):
        """Test querying a peer for closest peers successfully."""
        target_key = b"target_key_123456789012345678901234"
        peer_id = sample_peer_info.peer_id

        # Mock stream operations
        mock_stream = Mock(spec=INetStream)
        mock_stream.write = AsyncMock()
        mock_stream.read = AsyncMock()
        mock_stream.close = AsyncMock()

        # Create mock response
        response_msg = Message()
        response_msg.type = Message.MessageType.FIND_NODE

        # Add a closer peer to the response
        closer_peer = response_msg.closerPeers.add()
        closer_peer_id = ID(b"closer_peer_id_12345678901234567")
        closer_peer.id = closer_peer_id.to_bytes()
        closer_peer.addrs.append(b"/ip4/127.0.0.1/tcp/4002")

        response_bytes = response_msg.SerializeToString()

        # Mock varint reading
        mock_stream.read.side_effect = [
            b"\x01",  # varint length prefix (single byte)
            response_bytes,
        ]

        with patch.object(
            peer_routing.routing_table, "add_peer", return_value=True
        ), patch.object(
            peer_routing.host.get_peerstore(),
            "addrs",
            return_value=sample_peer_info.addrs,
        ), patch.object(
            peer_routing.host, "new_stream", return_value=mock_stream
        ), patch.object(
            peer_routing.host.get_peerstore(), "add_addrs"
        ) as mock_add_addrs:
            result = await peer_routing._query_peer_for_closest(peer_id, target_key)

            assert len(result) == 1
            assert closer_peer_id in result
            mock_add_addrs.assert_called()

    @pytest.mark.trio
    async def test_query_peer_for_closest_connection_error(
        self, peer_routing, sample_peer_info
    ):
        """Test querying a peer when connection fails."""
        target_key = b"target_key_123456789012345678901234"
        peer_id = sample_peer_info.peer_id

        with patch.object(
            peer_routing.routing_table, "add_peer", return_value=True
        ), patch.object(
            peer_routing.host.get_peerstore(),
            "addrs",
            return_value=sample_peer_info.addrs,
        ), patch.object(
            peer_routing.host, "new_stream", side_effect=Exception("Connection failed")
        ):
            result = await peer_routing._query_peer_for_closest(peer_id, target_key)

            assert result == []

    @pytest.mark.trio
    async def test_bootstrap_success(self, peer_routing):
        """Test bootstrapping with valid peers."""
        bootstrap_peers = [
            "/ip4/127.0.0.1/tcp/4001/p2p/QmBootstrap1",
            "/ip4/127.0.0.1/tcp/4002/p2p/QmBootstrap2",
        ]

        with patch(
            "libp2p.kad_dht.peer_routing.info_from_p2p_addr"
        ) as mock_info_from_addr, patch.object(
            peer_routing.host.get_peerstore(), "add_addrs"
        ), patch.object(
            peer_routing.host, "connect"
        ), patch.object(
            peer_routing.routing_table, "add_peer", return_value=True
        ), patch.object(
            peer_routing, "refresh_routing_table"
        ):
            # Mock peer info creation
            mock_peer_info = Mock()
            mock_peer_info.peer_id = ID(b"bootstrap_peer_123456789012345678")
            mock_peer_info.addrs = [Multiaddr("/ip4/127.0.0.1/tcp/4001")]
            mock_info_from_addr.return_value = mock_peer_info

            await peer_routing.bootstrap(bootstrap_peers)

            # Verify calls were made
            assert mock_info_from_addr.call_count == len(bootstrap_peers)

    @pytest.mark.trio
    async def test_bootstrap_connection_failure(self, peer_routing):
        """Test bootstrapping when connection fails."""
        bootstrap_peers = ["/ip4/127.0.0.1/tcp/4001/p2p/QmBootstrap1"]

        with patch(
            "libp2p.peer.peerinfo.info_from_p2p_addr"
        ) as mock_info_from_addr, patch.object(
            peer_routing.host.get_peerstore(), "add_addrs"
        ), patch.object(
            peer_routing.host, "connect", side_effect=Exception("Connection failed")
        ), patch.object(
            peer_routing, "refresh_routing_table"
        ):
            mock_peer_info = Mock()
            mock_peer_info.peer_id = ID(b"bootstrap_peer_123456789012345678")
            mock_peer_info.addrs = [Multiaddr("/ip4/127.0.0.1/tcp/4001")]
            mock_info_from_addr.return_value = mock_peer_info

            # Should not raise exception even if connection fails
            await peer_routing.bootstrap(bootstrap_peers)

    @pytest.mark.trio
    async def test_bootstrap_invalid_address(self, peer_routing):
        """Test bootstrapping with invalid address."""
        bootstrap_peers = ["invalid_address"]

        with patch(
            "libp2p.peer.peerinfo.info_from_p2p_addr",
            side_effect=InvalidAddrError("Invalid address"),
        ):
            with pytest.raises(InvalidAddrError):
                await peer_routing.bootstrap(bootstrap_peers)

    @pytest.mark.trio
    async def test_refresh_routing_table(self, peer_routing):
        """Test refreshing the routing table."""
        local_id = peer_routing.host.get_id()
        closest_peers = [
            ID(b"peer1_id_123456789012345678901234"),
            ID(b"peer2_id_123456789012345678901234"),
        ]

        with patch.object(
            peer_routing, "find_closest_peers_network", return_value=closest_peers
        ) as mock_find, patch.object(
            peer_routing.host.get_peerstore(),
            "addrs",
            return_value=[Multiaddr("/ip4/127.0.0.1/tcp/4001")],
        ), patch.object(
            peer_routing.routing_table, "add_peer", return_value=True
        ) as mock_add:
            await peer_routing.refresh_routing_table()

            mock_find.assert_called_once_with(local_id.to_bytes())
            assert mock_add.call_count == len(closest_peers)

    @pytest.mark.trio
    async def test_handle_kad_stream_find_node(self, peer_routing):
        """Test handling incoming FIND_NODE stream."""
        mock_stream = Mock(spec=INetStream)
        mock_stream.read = AsyncMock()
        mock_stream.write = AsyncMock()
        mock_stream.close = AsyncMock()

        # Create FIND_NODE message
        target_key = b"target_key_1234567890123456"
        message = Message()
        message.type = Message.MessageType.FIND_NODE
        message.key = target_key
        msg_bytes = message.SerializeToString()

        # Mock stream reading
        mock_stream.read.side_effect = [
            len(msg_bytes).to_bytes(4, byteorder="big"),
            msg_bytes,
        ]

        closest_peers = [
            ID(b"close_peer_1_123456789012345678"),
            ID(b"close_peer_2_123456789012345678"),
        ]

        with patch.object(
            peer_routing.routing_table,
            "find_local_closest_peers",
            return_value=closest_peers,
        ), patch.object(peer_routing.host.get_peerstore(), "addrs", return_value=[]):
            await peer_routing._handle_kad_stream(mock_stream)

            mock_stream.write.assert_called()
            mock_stream.close.assert_called_once()

    @pytest.mark.trio
    async def test_handle_kad_stream_connection_error(self, peer_routing):
        """Test handling stream when connection fails."""
        mock_stream = Mock(spec=INetStream)
        mock_stream.read.side_effect = Exception("Connection failed")
        mock_stream.close = AsyncMock()

        # Should not raise exception
        await peer_routing._handle_kad_stream(mock_stream)

        mock_stream.close.assert_called_once()

    @pytest.mark.trio
    async def test_query_single_peer_for_closest(self, peer_routing, sample_peer_info):
        """Test querying a single peer for closest peers."""
        target_key = b"target_key_123456789012345678901234"
        new_peers = []

        with patch.object(
            peer_routing,
            "_query_peer_for_closest",
            return_value=[sample_peer_info.peer_id],
        ) as mock_query:
            await peer_routing._query_single_peer_for_closest(
                sample_peer_info.peer_id, target_key, new_peers
            )

            assert sample_peer_info.peer_id in new_peers
            mock_query.assert_called_once_with(sample_peer_info.peer_id, target_key)

    @pytest.mark.trio
    async def test_query_single_peer_for_closest_error(
        self, peer_routing, sample_peer_info
    ):
        """Test querying a single peer when it fails."""
        target_key = b"target_key_123456789012345678901234"
        new_peers = []

        with patch.object(
            peer_routing,
            "_query_peer_for_closest",
            side_effect=Exception("Query failed"),
        ):
            # Should not raise exception
            await peer_routing._query_single_peer_for_closest(
                sample_peer_info.peer_id, target_key, new_peers
            )

            assert len(new_peers) == 0

    def test_constants(self):
        """Test that constants are properly defined."""
        assert ALPHA == 3
        assert MAX_PEER_LOOKUP_ROUNDS == 20

    @pytest.mark.trio
    async def test_find_closest_peers_network_max_rounds(self, peer_routing):
        """Test that network search respects maximum rounds limit."""
        target_key = b"target_key_123456789012345678901234"
        local_peers = [ID(b"local_peer_1_123456789012345678901")]

        with patch.object(
            peer_routing.routing_table,
            "find_local_closest_peers",
            return_value=local_peers,
        ), patch.object(peer_routing, "_query_single_peer_for_closest") as mock_query:
            # Mock query to always return new peers to force max rounds
            def mock_query_side_effect(peer, key, new_peers):
                if len(new_peers) < MAX_PEER_LOOKUP_ROUNDS:
                    new_peer = ID(
                        f"new_peer_{len(new_peers)}_12345678901234567890".encode()[
                            :32
                        ].ljust(32, b"\0")
                    )
                    new_peers.append(new_peer)

            mock_query.side_effect = mock_query_side_effect

            await peer_routing.find_closest_peers_network(target_key)

            # Should stop after MAX_PEER_LOOKUP_ROUNDS
            assert mock_query.call_count <= MAX_PEER_LOOKUP_ROUNDS * ALPHA
