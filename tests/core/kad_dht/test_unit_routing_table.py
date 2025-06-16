"""
Unit tests for the RoutingTable and KBucket classes in Kademlia DHT.

This module tests the core functionality of the routing table including:
- KBucket operations (add, remove, split, ping)
- RoutingTable management (peer addition, closest peer finding)
- Distance calculations and peer ordering
- Bucket splitting and range management
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

from libp2p.crypto.secp256k1 import (
    create_new_key_pair,
)
from libp2p.kad_dht.routing_table import (
    BUCKET_SIZE,
    KBucket,
    RoutingTable,
)
from libp2p.kad_dht.utils import (
    create_key_from_binary,
    xor_distance,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerinfo import (
    PeerInfo,
)


def create_valid_peer_id(name: str) -> ID:
    """Create a valid peer ID for testing."""
    # Use crypto to generate valid peer IDs
    key_pair = create_new_key_pair()
    return ID.from_pubkey(key_pair.public_key)


class TestKBucket:
    """Test suite for KBucket class."""

    @pytest.fixture
    def mock_host(self):
        """Create a mock host for testing."""
        host = Mock()
        host.get_peerstore.return_value = Mock()
        host.new_stream = AsyncMock()
        return host

    @pytest.fixture
    def sample_peer_info(self):
        """Create sample peer info for testing."""
        peer_id = create_valid_peer_id("test")
        addresses = [Multiaddr("/ip4/127.0.0.1/tcp/8000")]
        return PeerInfo(peer_id, addresses)

    def test_init_default_parameters(self, mock_host):
        """Test KBucket initialization with default parameters."""
        bucket = KBucket(mock_host)

        assert bucket.bucket_size == BUCKET_SIZE
        assert bucket.host == mock_host
        assert bucket.min_range == 0
        assert bucket.max_range == 2**256
        assert len(bucket.peers) == 0

    def test_peer_operations(self, mock_host, sample_peer_info):
        """Test basic peer operations: add, check, and remove."""
        bucket = KBucket(mock_host)

        # Test empty bucket
        assert bucket.peer_ids() == []
        assert bucket.size() == 0
        assert not bucket.has_peer(sample_peer_info.peer_id)

        # Add peer manually
        bucket.peers[sample_peer_info.peer_id] = (sample_peer_info, time.time())

        # Test with peer
        assert len(bucket.peer_ids()) == 1
        assert sample_peer_info.peer_id in bucket.peer_ids()
        assert bucket.size() == 1
        assert bucket.has_peer(sample_peer_info.peer_id)
        assert bucket.get_peer_info(sample_peer_info.peer_id) == sample_peer_info

        # Remove peer
        result = bucket.remove_peer(sample_peer_info.peer_id)
        assert result is True
        assert bucket.size() == 0
        assert not bucket.has_peer(sample_peer_info.peer_id)

    @pytest.mark.trio
    async def test_add_peer_functionality(self, mock_host):
        """Test add_peer method with different scenarios."""
        bucket = KBucket(mock_host, bucket_size=2)  # Small bucket for testing

        # Add first peer
        peer1 = PeerInfo(create_valid_peer_id("peer1"), [])
        result = await bucket.add_peer(peer1)
        assert result is True
        assert bucket.size() == 1

        # Add second peer
        peer2 = PeerInfo(create_valid_peer_id("peer2"), [])
        result = await bucket.add_peer(peer2)
        assert result is True
        assert bucket.size() == 2

        # Add same peer again (should update timestamp)
        await trio.sleep(0.001)
        result = await bucket.add_peer(peer1)
        assert result is True
        assert bucket.size() == 2  # Still 2 peers

        # Try to add third peer when bucket is full
        peer3 = PeerInfo(create_valid_peer_id("peer3"), [])
        with patch.object(bucket, "_ping_peer", return_value=True):
            result = await bucket.add_peer(peer3)
            assert result is False  # Should fail if oldest peer responds

    def test_get_oldest_peer(self, mock_host):
        """Test get_oldest_peer method."""
        bucket = KBucket(mock_host)

        # Empty bucket
        assert bucket.get_oldest_peer() is None

        # Add peers with different timestamps
        peer1 = PeerInfo(create_valid_peer_id("peer1"), [])
        peer2 = PeerInfo(create_valid_peer_id("peer2"), [])

        current_time = time.time()
        bucket.peers[peer1.peer_id] = (peer1, current_time - 300)  # Older
        bucket.peers[peer2.peer_id] = (peer2, current_time)  # Newer

        oldest = bucket.get_oldest_peer()
        assert oldest == peer1.peer_id

    def test_stale_peers(self, mock_host):
        """Test stale peer identification."""
        bucket = KBucket(mock_host)

        current_time = time.time()
        fresh_peer = PeerInfo(create_valid_peer_id("fresh"), [])
        stale_peer = PeerInfo(create_valid_peer_id("stale"), [])

        bucket.peers[fresh_peer.peer_id] = (fresh_peer, current_time)
        bucket.peers[stale_peer.peer_id] = (
            stale_peer,
            current_time - 7200,
        )  # 2 hours ago

        stale_peers = bucket.get_stale_peers(3600)  # 1 hour threshold
        assert len(stale_peers) == 1
        assert stale_peer.peer_id in stale_peers

    def test_key_in_range(self, mock_host):
        """Test key_in_range method."""
        bucket = KBucket(mock_host, min_range=100, max_range=200)

        # Test keys within range
        key_in_range = (150).to_bytes(32, byteorder="big")
        assert bucket.key_in_range(key_in_range) is True

        # Test keys outside range
        key_below = (50).to_bytes(32, byteorder="big")
        assert bucket.key_in_range(key_below) is False

        key_above = (250).to_bytes(32, byteorder="big")
        assert bucket.key_in_range(key_above) is False

        # Test boundary conditions
        key_min = (100).to_bytes(32, byteorder="big")
        assert bucket.key_in_range(key_min) is True

        key_max = (200).to_bytes(32, byteorder="big")
        assert bucket.key_in_range(key_max) is False

    def test_split_bucket(self, mock_host):
        """Test bucket splitting functionality."""
        bucket = KBucket(mock_host, min_range=0, max_range=256)

        lower_bucket, upper_bucket = bucket.split()

        # Check ranges
        assert lower_bucket.min_range == 0
        assert lower_bucket.max_range == 128
        assert upper_bucket.min_range == 128
        assert upper_bucket.max_range == 256

        # Check properties
        assert lower_bucket.bucket_size == bucket.bucket_size
        assert upper_bucket.bucket_size == bucket.bucket_size
        assert lower_bucket.host == mock_host
        assert upper_bucket.host == mock_host

    @pytest.mark.trio
    async def test_ping_peer_scenarios(self, mock_host, sample_peer_info):
        """Test different ping scenarios."""
        bucket = KBucket(mock_host)
        bucket.peers[sample_peer_info.peer_id] = (sample_peer_info, time.time())

        # Test ping peer not in bucket
        other_peer_id = create_valid_peer_id("other")
        with pytest.raises(ValueError, match="Peer .* not in bucket"):
            await bucket._ping_peer(other_peer_id)

        # Test ping failure due to stream error
        mock_host.new_stream.side_effect = Exception("Stream failed")
        result = await bucket._ping_peer(sample_peer_info.peer_id)
        assert result is False


class TestRoutingTable:
    """Test suite for RoutingTable class."""

    @pytest.fixture
    def mock_host(self):
        """Create a mock host for testing."""
        host = Mock()
        host.get_peerstore.return_value = Mock()
        return host

    @pytest.fixture
    def local_peer_id(self):
        """Create a local peer ID for testing."""
        return create_valid_peer_id("local")

    @pytest.fixture
    def sample_peer_info(self):
        """Create sample peer info for testing."""
        peer_id = create_valid_peer_id("sample")
        addresses = [Multiaddr("/ip4/127.0.0.1/tcp/8000")]
        return PeerInfo(peer_id, addresses)

    def test_init_routing_table(self, mock_host, local_peer_id):
        """Test RoutingTable initialization."""
        routing_table = RoutingTable(local_peer_id, mock_host)

        assert routing_table.local_id == local_peer_id
        assert routing_table.host == mock_host
        assert len(routing_table.buckets) == 1
        assert isinstance(routing_table.buckets[0], KBucket)

    @pytest.mark.trio
    async def test_add_peer_operations(
        self, mock_host, local_peer_id, sample_peer_info
    ):
        """Test adding peers to routing table."""
        routing_table = RoutingTable(local_peer_id, mock_host)

        # Test adding peer with PeerInfo
        result = await routing_table.add_peer(sample_peer_info)
        assert result is True
        assert routing_table.size() == 1
        assert routing_table.peer_in_table(sample_peer_info.peer_id)

        # Test adding peer with just ID
        peer_id = create_valid_peer_id("test")
        mock_addrs = [Multiaddr("/ip4/127.0.0.1/tcp/8001")]
        mock_host.get_peerstore().addrs.return_value = mock_addrs

        result = await routing_table.add_peer(peer_id)
        assert result is True
        assert routing_table.size() == 2

        # Test adding peer with no addresses
        no_addr_peer_id = create_valid_peer_id("no_addr")
        mock_host.get_peerstore().addrs.return_value = []

        result = await routing_table.add_peer(no_addr_peer_id)
        assert result is False
        assert routing_table.size() == 2

        # Test adding local peer (should be ignored)
        result = await routing_table.add_peer(local_peer_id)
        assert result is False
        assert routing_table.size() == 2

    def test_find_bucket(self, mock_host, local_peer_id):
        """Test finding appropriate bucket for peers."""
        routing_table = RoutingTable(local_peer_id, mock_host)

        # Test with peer ID
        peer_id = create_valid_peer_id("test")
        bucket = routing_table.find_bucket(peer_id)
        assert isinstance(bucket, KBucket)

    def test_peer_management(self, mock_host, local_peer_id, sample_peer_info):
        """Test peer management operations."""
        routing_table = RoutingTable(local_peer_id, mock_host)

        # Add peer manually
        bucket = routing_table.find_bucket(sample_peer_info.peer_id)
        bucket.peers[sample_peer_info.peer_id] = (sample_peer_info, time.time())

        # Test peer queries
        assert routing_table.peer_in_table(sample_peer_info.peer_id)
        assert routing_table.get_peer_info(sample_peer_info.peer_id) == sample_peer_info
        assert routing_table.size() == 1
        assert len(routing_table.get_peer_ids()) == 1

        # Test remove peer
        result = routing_table.remove_peer(sample_peer_info.peer_id)
        assert result is True
        assert not routing_table.peer_in_table(sample_peer_info.peer_id)
        assert routing_table.size() == 0

    def test_find_closest_peers(self, mock_host, local_peer_id):
        """Test finding closest peers."""
        routing_table = RoutingTable(local_peer_id, mock_host)

        # Empty table
        target_key = create_key_from_binary(b"target_key")
        closest_peers = routing_table.find_local_closest_peers(target_key, 5)
        assert closest_peers == []

        # Add some peers
        bucket = routing_table.buckets[0]
        test_peers = []
        for i in range(5):
            peer = PeerInfo(create_valid_peer_id(f"peer{i}"), [])
            test_peers.append(peer)
            bucket.peers[peer.peer_id] = (peer, time.time())

        closest_peers = routing_table.find_local_closest_peers(target_key, 3)
        assert len(closest_peers) <= 3
        assert len(closest_peers) <= len(test_peers)
        assert all(isinstance(peer_id, ID) for peer_id in closest_peers)

    def test_distance_calculation(self, mock_host, local_peer_id):
        """Test XOR distance calculation."""
        # Test same keys
        key = b"\x42" * 32
        distance = xor_distance(key, key)
        assert distance == 0

        # Test different keys
        key1 = b"\x00" * 32
        key2 = b"\xff" * 32
        distance = xor_distance(key1, key2)
        expected = int.from_bytes(b"\xff" * 32, byteorder="big")
        assert distance == expected

    def test_edge_cases(self, mock_host, local_peer_id):
        """Test various edge cases."""
        routing_table = RoutingTable(local_peer_id, mock_host)

        # Test with invalid peer ID
        nonexistent_peer_id = create_valid_peer_id("nonexistent")
        assert not routing_table.peer_in_table(nonexistent_peer_id)
        assert routing_table.get_peer_info(nonexistent_peer_id) is None
        assert routing_table.remove_peer(nonexistent_peer_id) is False

        # Test bucket splitting scenario
        assert len(routing_table.buckets) == 1
        initial_bucket = routing_table.buckets[0]
        assert initial_bucket.min_range == 0
        assert initial_bucket.max_range == 2**256
