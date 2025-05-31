"""
Unit tests for the Kademlia DHT routing table implementation.

This module contains unit tests for the RoutingTable and KBucket classes.
"""

import logging
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

from libp2p.kad_dht.routing_table import (
    KBucket,
    RoutingTable,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerinfo import (
    PeerInfo,
)

logger = logging.getLogger("test.routing_table")


class TestKBucket:
    """Test cases for the KBucket class."""

    @pytest.fixture
    def mock_host(self):
        """Create a mock host for testing."""
        host = Mock()
        host.get_id.return_value = ID(b"test_peer_id_12345678901234567890")
        host.get_peerstore.return_value = Mock()
        host.new_stream = AsyncMock()
        return host

    @pytest.fixture
    def bucket(self, mock_host):
        """Create a KBucket instance for testing."""
        return KBucket(mock_host, bucket_size=3)

    @pytest.fixture
    def sample_peer_info(self):
        """Create sample peer info for testing."""
        peer_id = ID(b"sample_peer_id_123456789012345678")
        addrs = [Multiaddr("/ip4/127.0.0.1/tcp/4001")]
        return PeerInfo(peer_id, addrs)

    def test_bucket_init(self, mock_host):
        """Test KBucket initialization."""
        bucket = KBucket(mock_host, bucket_size=5, min_range=10, max_range=100)

        assert bucket.bucket_size == 5
        assert bucket.host == mock_host
        assert bucket.min_range == 10
        assert bucket.max_range == 100
        assert len(bucket.peers) == 0

    def test_peer_ids(self, bucket, sample_peer_info):
        """Test getting peer IDs from bucket."""
        # Empty bucket
        assert bucket.peer_ids() == []

        # Add a peer
        bucket.peers[sample_peer_info.peer_id] = (sample_peer_info, time.time())
        peer_ids = bucket.peer_ids()

        assert len(peer_ids) == 1
        assert sample_peer_info.peer_id in peer_ids

    def test_peer_infos(self, bucket, sample_peer_info):
        """Test getting peer infos from bucket."""
        # Empty bucket
        assert bucket.peer_infos() == []

        # Add a peer
        bucket.peers[sample_peer_info.peer_id] = (sample_peer_info, time.time())
        peer_infos = bucket.peer_infos()

        assert len(peer_infos) == 1
        assert sample_peer_info in peer_infos

    def test_get_oldest_peer(self, bucket):
        """Test getting the oldest peer from bucket."""
        # Empty bucket
        assert bucket.get_oldest_peer() is None

        # Add peers with different timestamps
        peer1 = PeerInfo(ID(b"peer1_id_123456789012345678901234"), [])
        peer2 = PeerInfo(ID(b"peer2_id_123456789012345678901234"), [])

        bucket.peers[peer1.peer_id] = (peer1, time.time() - 100)
        bucket.peers[peer2.peer_id] = (peer2, time.time() - 50)

        oldest = bucket.get_oldest_peer()
        assert oldest == peer1.peer_id

    @pytest.mark.trio
    async def test_add_peer_new(self, bucket, sample_peer_info):
        """Test adding a new peer to bucket."""
        result = await bucket.add_peer(sample_peer_info)

        assert result is True
        assert sample_peer_info.peer_id in bucket.peers
        assert bucket.size() == 1

    @pytest.mark.trio
    async def test_add_peer_existing(self, bucket, sample_peer_info):
        """Test adding an existing peer (should update timestamp)."""
        # Add peer first time
        await bucket.add_peer(sample_peer_info)
        initial_timestamp = bucket.peers[sample_peer_info.peer_id][1]

        # Wait a bit and add again
        await trio.sleep(0.01)
        result = await bucket.add_peer(sample_peer_info)
        updated_timestamp = bucket.peers[sample_peer_info.peer_id][1]

        assert result is True
        assert updated_timestamp > initial_timestamp
        assert bucket.size() == 1

    @pytest.mark.trio
    async def test_add_peer_bucket_full(self, mock_host):
        """Test adding peer when bucket is full."""
        bucket = KBucket(mock_host, bucket_size=2)

        # Fill the bucket
        peer1 = PeerInfo(ID(b"peer1_id_123456789012345678901234"), [])
        peer2 = PeerInfo(ID(b"peer2_id_123456789012345678901234"), [])

        await bucket.add_peer(peer1)
        await bucket.add_peer(peer2)
        assert bucket.size() == 2

        # Try to add third peer
        peer3 = PeerInfo(ID(b"peer3_id_123456789012345678901234"), [])

        with patch.object(bucket, "_ping_peer", return_value=True) as mock_ping:
            result = await bucket.add_peer(peer3)

            # Should fail because oldest peer responded to ping
            assert result is False
            assert bucket.size() == 2
            mock_ping.assert_called_once_with(peer1.peer_id)

    @pytest.mark.trio
    async def test_add_peer_replace_unresponsive(self, mock_host):
        """Test adding peer when oldest peer is unresponsive."""
        bucket = KBucket(mock_host, bucket_size=2)

        # Fill the bucket
        peer1 = PeerInfo(ID(b"peer1_id_123456789012345678901234"), [])
        peer2 = PeerInfo(ID(b"peer2_id_123456789012345678901234"), [])

        await bucket.add_peer(peer1)
        await bucket.add_peer(peer2)

        # Try to add third peer with unresponsive oldest peer
        peer3 = PeerInfo(ID(b"peer3_id_123456789012345678901234"), [])

        with patch.object(
            bucket, "_ping_peer", side_effect=Exception("Ping failed")
        ) as mock_ping:
            result = await bucket.add_peer(peer3)

            # Should succeed because oldest peer didn't respond
            assert result is True
            assert bucket.size() == 2
            assert peer3.peer_id in bucket.peers
            assert peer1.peer_id not in bucket.peers
            mock_ping.assert_called_once_with(peer1.peer_id)

    def test_remove_peer(self, bucket, sample_peer_info):
        """Test removing a peer from bucket."""
        # Try removing from empty bucket
        result = bucket.remove_peer(sample_peer_info.peer_id)
        assert result is False

        # Add peer and then remove
        bucket.peers[sample_peer_info.peer_id] = (sample_peer_info, time.time())
        result = bucket.remove_peer(sample_peer_info.peer_id)

        assert result is True
        assert sample_peer_info.peer_id not in bucket.peers

    def test_has_peer(self, bucket, sample_peer_info):
        """Test checking if bucket has a peer."""
        assert bucket.has_peer(sample_peer_info.peer_id) is False

        bucket.peers[sample_peer_info.peer_id] = (sample_peer_info, time.time())
        assert bucket.has_peer(sample_peer_info.peer_id) is True

    def test_get_peer_info(self, bucket, sample_peer_info):
        """Test getting peer info by ID."""
        assert bucket.get_peer_info(sample_peer_info.peer_id) is None

        bucket.peers[sample_peer_info.peer_id] = (sample_peer_info, time.time())
        retrieved_info = bucket.get_peer_info(sample_peer_info.peer_id)

        assert retrieved_info == sample_peer_info

    def test_size(self, bucket, sample_peer_info):
        """Test getting bucket size."""
        assert bucket.size() == 0

        bucket.peers[sample_peer_info.peer_id] = (sample_peer_info, time.time())
        assert bucket.size() == 1

    def test_get_stale_peers(self, bucket):
        """Test getting stale peers from bucket."""
        current_time = time.time()

        # Add fresh peer
        fresh_peer = PeerInfo(ID(b"fresh_peer_id_12345678901234567890"), [])
        bucket.peers[fresh_peer.peer_id] = (fresh_peer, current_time - 10)

        # Add stale peer
        stale_peer = PeerInfo(ID(b"stale_peer_id_12345678901234567890"), [])
        bucket.peers[stale_peer.peer_id] = (
            stale_peer,
            current_time - 7200,
        )  # 2 hours old

        stale_peers = bucket.get_stale_peers(
            stale_threshold_seconds=3600
        )  # 1 hour threshold

        assert len(stale_peers) == 1
        assert stale_peer.peer_id in stale_peers
        assert fresh_peer.peer_id not in stale_peers

    def test_refresh_peer_last_seen(self, bucket, sample_peer_info):
        """Test refreshing peer's last seen timestamp."""
        # Try refreshing non-existent peer
        result = bucket.refresh_peer_last_seen(sample_peer_info.peer_id)
        assert result is False

        # Add peer and refresh
        initial_time = time.time() - 100
        bucket.peers[sample_peer_info.peer_id] = (sample_peer_info, initial_time)

        result = bucket.refresh_peer_last_seen(sample_peer_info.peer_id)
        updated_time = bucket.peers[sample_peer_info.peer_id][1]

        assert result is True
        assert updated_time > initial_time

    def test_key_in_range(self, mock_host):
        """Test checking if key is in bucket's range."""
        bucket = KBucket(mock_host, min_range=100, max_range=200)

        # Key within range
        key_in_range = (150).to_bytes(32, byteorder="big")
        assert bucket.key_in_range(key_in_range) is True

        # Key below range
        key_below = (50).to_bytes(32, byteorder="big")
        assert bucket.key_in_range(key_below) is False

        # Key above range
        key_above = (250).to_bytes(32, byteorder="big")
        assert bucket.key_in_range(key_above) is False

    def test_split(self, mock_host):
        """Test splitting a bucket."""
        bucket = KBucket(mock_host, min_range=0, max_range=100)

        # Add peers
        peer1 = PeerInfo(
            ID((25).to_bytes(32, byteorder="big")), []
        )  # Should go to lower bucket
        peer2 = PeerInfo(
            ID((75).to_bytes(32, byteorder="big")), []
        )  # Should go to upper bucket

        bucket.peers[peer1.peer_id] = (peer1, time.time())
        bucket.peers[peer2.peer_id] = (peer2, time.time())

        lower_bucket, upper_bucket = bucket.split()

        assert lower_bucket.min_range == 0
        assert lower_bucket.max_range == 50
        assert upper_bucket.min_range == 50
        assert upper_bucket.max_range == 100

        assert peer1.peer_id in lower_bucket.peers
        assert peer2.peer_id in upper_bucket.peers


class TestRoutingTable:
    """Test cases for the RoutingTable class."""

    @pytest.fixture
    def mock_host(self):
        """Create a mock host for testing."""
        host = Mock()
        host.get_id.return_value = ID(b"test_peer_id_12345678901234567890")
        host.get_peerstore.return_value = Mock()
        host.new_stream = AsyncMock()
        return host

    @pytest.fixture
    def routing_table(self, mock_host):
        """Create a RoutingTable instance for testing."""
        local_id = ID(b"local_peer_id_123456789012345678")
        return RoutingTable(local_id, mock_host)

    @pytest.fixture
    def sample_peer_info(self):
        """Create sample peer info for testing."""
        peer_id = ID(b"sample_peer_id_123456789012345678")
        addrs = [Multiaddr("/ip4/127.0.0.1/tcp/4001")]
        return PeerInfo(peer_id, addrs)

    def test_routing_table_init(self, mock_host):
        """Test RoutingTable initialization."""
        local_id = ID(b"local_peer_id_123456789012345678")
        rt = RoutingTable(local_id, mock_host)

        assert rt.local_id == local_id
        assert rt.host == mock_host
        assert len(rt.buckets) == 1
        assert isinstance(rt.buckets[0], KBucket)

    @pytest.mark.trio
    async def test_add_peer_info(self, routing_table, sample_peer_info):
        """Test adding a PeerInfo object."""
        result = await routing_table.add_peer(sample_peer_info)

        assert result is True
        assert routing_table.peer_in_table(sample_peer_info.peer_id) is True

    @pytest.mark.trio
    async def test_add_peer_id_with_addrs(self, routing_table):
        """Test adding a peer ID when addresses are available."""
        peer_id = ID(b"peer_with_addrs_123456789012345678")
        addrs = [Multiaddr("/ip4/127.0.0.1/tcp/4001")]

        # Mock peerstore to return addresses
        routing_table.host.get_peerstore().addrs.return_value = addrs

        result = await routing_table.add_peer(peer_id)

        assert result is True
        assert routing_table.peer_in_table(peer_id) is True

    @pytest.mark.trio
    async def test_add_peer_id_no_addrs(self, routing_table):
        """Test adding a peer ID when no addresses are available."""
        peer_id = ID(b"peer_no_addrs_123456789012345678901")

        # Mock peerstore to return no addresses
        routing_table.host.get_peerstore().addrs.return_value = []

        result = await routing_table.add_peer(peer_id)

        assert result is False
        assert routing_table.peer_in_table(peer_id) is False

    @pytest.mark.trio
    async def test_add_self_peer(self, routing_table):
        """Test that we cannot add ourselves to the routing table."""
        result = await routing_table.add_peer(routing_table.local_id)

        assert result is False
        assert routing_table.peer_in_table(routing_table.local_id) is False

    def test_remove_peer(self, routing_table, sample_peer_info):
        """Test removing a peer from routing table."""
        # Add peer first
        bucket = routing_table.find_bucket(sample_peer_info.peer_id)
        bucket.peers[sample_peer_info.peer_id] = (sample_peer_info, time.time())

        result = routing_table.remove_peer(sample_peer_info.peer_id)

        assert result is True
        assert routing_table.peer_in_table(sample_peer_info.peer_id) is False

    def test_find_bucket(self, routing_table, sample_peer_info):
        """Test finding the correct bucket for a peer."""
        bucket = routing_table.find_bucket(sample_peer_info.peer_id)

        assert isinstance(bucket, KBucket)
        assert bucket in routing_table.buckets

    def test_find_bucket_with_peer_info(self, routing_table, sample_peer_info):
        """Test finding bucket with PeerInfo object."""
        bucket = routing_table.find_bucket(sample_peer_info)

        assert isinstance(bucket, KBucket)
        assert bucket in routing_table.buckets

    def test_find_local_closest_peers(self, routing_table):
        """Test finding closest peers to a key."""
        # Add some peers to different buckets
        peers = []
        for i in range(5):
            peer_id = ID(
                f"peer_{i}_id_123456789012345678901234".encode()[:32].ljust(32, b"\0")
            )
            peer_info = PeerInfo(peer_id, [])
            peers.append(peer_info)

            bucket = routing_table.find_bucket(peer_id)
            bucket.peers[peer_id] = (peer_info, time.time())

        target_key = b"target_key_123456789012345678901234"
        closest = routing_table.find_local_closest_peers(target_key, count=3)

        assert len(closest) <= 3
        assert len(closest) <= len(peers)

    def test_get_peer_ids(self, routing_table):
        """Test getting all peer IDs from routing table."""
        assert routing_table.get_peer_ids() == []

        # Add a peer
        peer_info = PeerInfo(ID(b"test_peer_id_123456789012345678"), [])
        bucket = routing_table.find_bucket(peer_info.peer_id)
        bucket.peers[peer_info.peer_id] = (peer_info, time.time())

        peer_ids = routing_table.get_peer_ids()
        assert len(peer_ids) == 1
        assert peer_info.peer_id in peer_ids

    def test_get_peer_info(self, routing_table, sample_peer_info):
        """Test getting peer info by ID."""
        assert routing_table.get_peer_info(sample_peer_info.peer_id) is None

        # Add peer
        bucket = routing_table.find_bucket(sample_peer_info.peer_id)
        bucket.peers[sample_peer_info.peer_id] = (sample_peer_info, time.time())

        retrieved_info = routing_table.get_peer_info(sample_peer_info.peer_id)
        assert retrieved_info == sample_peer_info

    def test_peer_in_table(self, routing_table, sample_peer_info):
        """Test checking if peer is in routing table."""
        assert routing_table.peer_in_table(sample_peer_info.peer_id) is False

        # Add peer
        bucket = routing_table.find_bucket(sample_peer_info.peer_id)
        bucket.peers[sample_peer_info.peer_id] = (sample_peer_info, time.time())

        assert routing_table.peer_in_table(sample_peer_info.peer_id) is True

    def test_size(self, routing_table, sample_peer_info):
        """Test getting routing table size."""
        assert routing_table.size() == 0

        # Add peer
        bucket = routing_table.find_bucket(sample_peer_info.peer_id)
        bucket.peers[sample_peer_info.peer_id] = (sample_peer_info, time.time())

        assert routing_table.size() == 1

    def test_distance_calculation(self, routing_table):
        """Test XOR distance calculation."""
        key1 = b"\x00\x00\x00\x01"  # 1
        key2 = b"\x00\x00\x00\x03"  # 3

        # XOR of 1 and 3 should be 2
        distance = routing_table._distance(key1, key2)
        assert distance == 2

    def test_get_stale_peers(self, routing_table):
        """Test getting stale peers from all buckets."""
        current_time = time.time()

        # Add fresh peer
        fresh_peer = PeerInfo(ID(b"fresh_peer_id_12345678901234567890"), [])
        bucket1 = routing_table.find_bucket(fresh_peer.peer_id)
        bucket1.peers[fresh_peer.peer_id] = (fresh_peer, current_time - 10)

        # Add stale peer
        stale_peer = PeerInfo(ID(b"stale_peer_id_12345678901234567890"), [])
        bucket2 = routing_table.find_bucket(stale_peer.peer_id)
        bucket2.peers[stale_peer.peer_id] = (
            stale_peer,
            current_time - 7200,
        )  # 2 hours old

        stale_peers = routing_table.get_stale_peers(stale_threshold_seconds=3600)

        assert len(stale_peers) == 1
        assert stale_peer.peer_id in stale_peers

    def test_cleanup_routing_table(self, routing_table, sample_peer_info):
        """Test cleaning up the routing table."""
        # Add a peer
        bucket = routing_table.find_bucket(sample_peer_info.peer_id)
        bucket.peers[sample_peer_info.peer_id] = (sample_peer_info, time.time())

        assert routing_table.size() == 1

        routing_table.cleanup_routing_table()

        assert routing_table.size() == 0
        assert len(routing_table.buckets) == 1
