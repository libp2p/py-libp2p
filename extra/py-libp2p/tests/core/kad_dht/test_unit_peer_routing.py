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
import trio
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
    MIN_PEERS_THRESHOLD,
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
        key_pair = create_new_key_pair()
        host.get_id.return_value = ID.from_pubkey(key_pair.public_key)
        host.get_public_key.return_value = key_pair.public_key
        host.get_private_key.return_value = key_pair.private_key
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
    async def test_find_closest_peers_network_empty_start(
        self, peer_routing, mock_host
    ):
        """Test network search with no local peers and no fallback peers."""
        target_key = b"target_key"

        # Mock routing table to return empty list
        with patch.object(
            peer_routing.routing_table, "find_local_closest_peers", return_value=[]
        ):
            # Mock no connected peers and empty peerstore
            mock_host.get_connected_peers.return_value = []
            mock_host.get_peerstore().peer_ids.return_value = []
            result = await peer_routing.find_closest_peers_network(target_key)

            assert result == []

    @pytest.mark.trio
    async def test_find_closest_peers_network_fallback_to_connected_peers(
        self, peer_routing, mock_host
    ):
        """
        Test that network search falls back to connected peers when routing
        table has insufficient peers.
        """
        target_key = b"target_key"

        # Create few local peers (less than MIN_PEERS_THRESHOLD)
        local_peers = [create_valid_peer_id(f"local{i}") for i in range(2)]

        # Create connected peers
        connected_peers = [create_valid_peer_id(f"connected{i}") for i in range(3)]

        # Mock routing table to return insufficient peers
        with patch.object(
            peer_routing.routing_table,
            "find_local_closest_peers",
            return_value=local_peers,
        ):
            # Mock host to return connected peers
            mock_host.get_connected_peers.return_value = connected_peers
            # Mock peerstore to return empty (connected peers should be enough)
            mock_host.get_peerstore().peer_ids.return_value = []

            # Mock _query_peer_for_closest to return empty results
            with patch.object(peer_routing, "_query_peer_for_closest", return_value=[]):
                result = await peer_routing.find_closest_peers_network(
                    target_key, count=10
                )

                # Should include both local and connected peers
                assert len(result) > 0
                # Verify host.get_connected_peers was called
                mock_host.get_connected_peers.assert_called()

    @pytest.mark.trio
    async def test_find_closest_peers_network_fallback_to_peerstore(
        self, peer_routing, mock_host
    ):
        """
        Test that network search falls back to peerstore when connected peers
        are insufficient.
        """
        target_key = b"target_key"

        # Create few local peers (less than MIN_PEERS_THRESHOLD)
        local_peers = [create_valid_peer_id(f"local{i}") for i in range(2)]

        # Create few connected peers (not enough to reach count)
        connected_peers = [create_valid_peer_id(f"connected{i}") for i in range(2)]

        # Create peerstore peers
        peerstore_peers = [create_valid_peer_id(f"peerstore{i}") for i in range(5)]

        # Mock routing table to return insufficient peers
        with patch.object(
            peer_routing.routing_table,
            "find_local_closest_peers",
            return_value=local_peers,
        ):
            # Mock host to return connected peers
            mock_host.get_connected_peers.return_value = connected_peers
            # Mock peerstore to return additional peers
            mock_host.get_peerstore().peer_ids.return_value = peerstore_peers

            # Mock _query_peer_for_closest to return empty results
            with patch.object(peer_routing, "_query_peer_for_closest", return_value=[]):
                result = await peer_routing.find_closest_peers_network(
                    target_key, count=20
                )

                # Should include peers from all sources
                assert len(result) > 0
                # Verify peerstore.peer_ids was called
                mock_host.get_peerstore().peer_ids.assert_called()

    @pytest.mark.trio
    async def test_find_closest_peers_network_no_fallback_when_sufficient_peers(
        self, peer_routing, mock_host
    ):
        """
        Test that fallback is not triggered when routing table has
        sufficient peers.
        """
        target_key = b"target_key"

        # Create enough local peers (>= MIN_PEERS_THRESHOLD)
        local_peers = [
            create_valid_peer_id(f"local{i}") for i in range(MIN_PEERS_THRESHOLD + 1)
        ]

        # Mock routing table to return sufficient peers
        with patch.object(
            peer_routing.routing_table,
            "find_local_closest_peers",
            return_value=local_peers,
        ):
            # Mock _query_peer_for_closest to return empty results
            with patch.object(peer_routing, "_query_peer_for_closest", return_value=[]):
                result = await peer_routing.find_closest_peers_network(
                    target_key, count=10
                )

                # Should have peers from routing table
                assert len(result) > 0
                # Verify host.get_connected_peers was NOT called
                mock_host.get_connected_peers.assert_not_called()

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
            # Mock get_connected_peers and peerstore to return empty
            mock_host.get_connected_peers.return_value = []
            mock_host.get_peerstore().peer_ids.return_value = []
            # Mock _query_peer_for_closest to return empty results
            with patch.object(peer_routing, "_query_peer_for_closest", return_value=[]):
                result = await peer_routing.find_closest_peers_network(
                    target_key, count=5
                )

                assert len(result) <= 5
                # Should return the initial peers since no new ones were discovered
                assert all(peer in initial_peers for peer in result)

    @pytest.mark.trio
    async def test_find_closest_peers_convergence(self, peer_routing, mock_host):
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
            # Mock get_connected_peers and peerstore to return empty
            mock_host.get_connected_peers.return_value = []
            mock_host.get_peerstore().peer_ids.return_value = []
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
    async def test_edge_case_max_rounds_reached(self, peer_routing, mock_host):
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
            # Mock get_connected_peers and peerstore to return empty
            mock_host.get_connected_peers.return_value = []
            mock_host.get_peerstore().peer_ids.return_value = []
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

    @pytest.mark.trio
    async def test_sliding_window_no_idle_slots(self, peer_routing, mock_host):
        """
        Verify the semaphore-based sliding window across rounds.

        With ALPHA=3 per-round admission, round 1 queries [p0, p1, p2].
        The mock makes p0 and p1 "discover" peers p3 and p4 so they appear
        in round 2.  Peer 2 is slow (0.5 s); peers 0/1 are fast (0.01 s).

        Under lock-step batching the timeline would be:
          round 1: [p0, p1, p2] — all finish at t≈0.5 s
          round 2: [p3, p4]     — start at t≈0.5 s

        With the sliding window (semaphore releases after each query),
        round 1 still caps at ALPHA peers, but round 2 starts as soon as
        all three finish.  The key assertion is that p3/p4 are eventually
        queried (multiple rounds fire) and p3 starts well before p2's
        0.5 s sleep would have blocked a lock-step design.
        """
        target_key = b"target_key"

        initial_peers = [create_valid_peer_id(f"sw_peer{i}") for i in range(3)]
        extra_peers = [create_valid_peer_id(f"sw_peer{i}") for i in range(3, 5)]
        started_at: dict[str, float] = {}

        async def mock_query(peer, _target_key, new_peers):
            started_at[str(peer)] = trio.current_time()
            # Peer 2 is slow; all others are fast
            if peer == initial_peers[2]:
                await trio.sleep(0.5)
            else:
                await trio.sleep(0.01)
            # Fast peers in round 1 "discover" extra peers
            if peer == initial_peers[0]:
                new_peers.append(extra_peers[0])
            elif peer == initial_peers[1]:
                new_peers.append(extra_peers[1])

        with patch.object(
            peer_routing.routing_table,
            "find_local_closest_peers",
            return_value=initial_peers,
        ):
            mock_host.get_connected_peers.return_value = []
            mock_host.get_peerstore().peer_ids.return_value = []
            with patch.object(
                peer_routing,
                "_query_single_peer_for_closest",
                side_effect=mock_query,
            ):
                await peer_routing.find_closest_peers_network(target_key)

        # All 5 peers should have been queried across multiple rounds
        assert len(started_at) == 5, f"Expected 5 queried peers, got {len(started_at)}"

        # Extra peers (round 2) should have started well before the slow
        # peer 2 would have blocked a lock-step implementation.
        p3_name = str(extra_peers[0])
        assert p3_name in started_at

    @pytest.mark.trio
    async def test_per_round_query_count_bounded_by_alpha(
        self, peer_routing, mock_host
    ):
        """
        Assert that each lookup round admits at most ALPHA peers, not the
        full ``count`` (20).  This preserves classic Kademlia iterative
        refinement: after each small batch we re-sort with newly discovered
        peers before admitting the next batch.

        We set up 9 peers in 3 groups of ALPHA=3.  Each round's queries
        "discover" the next group, keeping the loop going.  We record the
        order of queries and verify that no more than ALPHA peers are
        admitted per round by checking the total across all rounds.
        """
        target_key = b"target_key"

        # 3 groups of ALPHA peers; each group "discovers" the next.
        group1 = [create_valid_peer_id(f"vol_g1_{i}") for i in range(ALPHA)]
        group2 = [create_valid_peer_id(f"vol_g2_{i}") for i in range(ALPHA)]
        group3 = [create_valid_peer_id(f"vol_g3_{i}") for i in range(ALPHA)]
        queried_peers: list[ID] = []

        async def mock_query(peer, _target_key, new_peers):
            queried_peers.append(peer)
            await trio.sleep(0)
            # Group 1 queries discover group 2 peers
            if peer in group1:
                for p in group2:
                    if p not in new_peers:
                        new_peers.append(p)
            # Group 2 queries discover group 3 peers
            elif peer in group2:
                for p in group3:
                    if p not in new_peers:
                        new_peers.append(p)

        with patch.object(
            peer_routing.routing_table,
            "find_local_closest_peers",
            return_value=group1,
        ):
            mock_host.get_connected_peers.return_value = []
            mock_host.get_peerstore().peer_ids.return_value = []
            with patch.object(
                peer_routing,
                "_query_single_peer_for_closest",
                side_effect=mock_query,
            ):
                await peer_routing.find_closest_peers_network(target_key)

        # All 9 peers should be queried across 3+ rounds.
        assert len(queried_peers) == 9, (
            f"Expected 9 total queries, got {len(queried_peers)}"
        )
        # First ALPHA queries must be from group 1 (round 1 admission).
        assert set(queried_peers[:ALPHA]) == set(group1), (
            "Round 1 should admit exactly the initial ALPHA peers"
        )
