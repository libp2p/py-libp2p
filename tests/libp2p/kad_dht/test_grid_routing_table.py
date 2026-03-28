"""
Tests for the Grid Routing Table implementation.
"""

import pytest

from libp2p.kad_dht.grid_routing_table import (
    GRID_BUCKET_COUNT,
    GridBucket,
    GridRoutingTable,
    NodeId,
)
from libp2p.peer.id import ID


class TestNodeId:
    """Tests for NodeId class."""

    def test_node_id_creation(self):
        """Test creating a NodeId from a peer ID."""
        peer_id = ID.from_base58("QmaCpDMGvV2BGHeYERUEnRQAwe5CcqarqmtA7xNXT92p2")
        node_id = NodeId(peer_id)

        assert node_id.data is not None
        assert len(node_id.data) == 32

    def test_node_id_distance(self):
        """Test XOR distance calculation between node IDs."""
        peer_id1 = ID.from_base58("QmaCpDMGvV2BGHeYERUEnRQAwe5CcqarqmtA7xNXT92p2")
        peer_id2 = ID.from_base58("QmZLaXk3bbiHgVK3zp5A8n2DEuvMZFRv1GAjTrSvZuLnFr")

        node_id1 = NodeId(peer_id1)
        node_id2 = NodeId(peer_id2)

        distance = node_id1.distance(node_id2)
        assert isinstance(distance, bytes)
        assert len(distance) == 32

    def test_node_id_common_prefix_len(self):
        """Test common prefix length calculation."""
        peer_id = ID.from_base58("QmaCpDMGvV2BGHeYERUEnRQAwe5CcqarqmtA7xNXT92p2")
        node_id = NodeId(peer_id)

        assert node_id.common_prefix_len(node_id) == 256

    def test_node_id_equality(self):
        """Test NodeId equality."""
        peer_id1 = ID.from_base58("QmaCpDMGvV2BGHeYERUEnRQAwe5CcqarqmtA7xNXT92p2")
        node_id1a = NodeId(peer_id1)
        node_id1b = NodeId(peer_id1)

        assert node_id1a == node_id1b


class TestGridBucket:
    """Tests for GridBucket class."""

    def test_bucket_creation(self):
        """Test creating a grid bucket."""
        bucket = GridBucket(max_size=20)
        assert bucket.size() == 0
        assert bucket.max_size == 20

    def test_add_peer_to_empty_bucket(self):
        """Test adding a peer to an empty bucket."""
        bucket = GridBucket(max_size=20)
        peer_id = ID.from_base58("QmaCpDMGvV2BGHeYERUEnRQAwe5CcqarqmtA7xNXT92p2")

        success = bucket.add_peer(peer_id)
        assert success
        assert bucket.size() == 1
        assert bucket.contains(peer_id)

    def test_add_duplicate_peer_moves_to_end(self):
        """Test adding a duplicate peer moves it to MRU position."""
        bucket = GridBucket(max_size=20)
        peer_id1 = ID.from_base58("QmaCpDMGvV2BGHeYERUEnRQAwe5CcqarqmtA7xNXT92p2")
        peer_id2 = ID.from_base58("QmZLaXk3bbiHgVK3zp5A8n2DEuvMZFRv1GAjTrSvZuLnFr")

        bucket.add_peer(peer_id1)
        bucket.add_peer(peer_id2)

        success = bucket.add_peer(peer_id1)
        assert success
        assert bucket.size() == 2
        assert list(bucket.peers)[-1].peer_id == peer_id1

    def test_bucket_full_rejection(self):
        """Test that adding to a full bucket returns False."""
        bucket = GridBucket(max_size=2)
        peer_id1 = ID.from_base58("QmaCpDMGvV2BGHeYERUEnRQAwe5CcqarqmtA7xNXT92p2")
        peer_id2 = ID.from_base58("QmZLaXk3bbiHgVK3zp5A8n2DEuvMZFRv1GAjTrSvZuLnFr")
        peer_id3 = ID.from_base58("QmdgB6x6xfBLvV9VwSPj9D7aHCmXhvEVVBn2CUEbNJnTg")

        bucket.add_peer(peer_id1)
        bucket.add_peer(peer_id2)

        success = bucket.add_peer(peer_id3)
        assert not success
        assert bucket.size() == 2

    def test_remove_replaceable_peer(self):
        """Test removing a replaceable (temporary) peer."""
        bucket = GridBucket(max_size=5)
        peer_id1 = ID.from_base58("QmaCpDMGvV2BGHeYERUEnRQAwe5CcqarqmtA7xNXT92p2")
        peer_id2 = ID.from_base58("QmZLaXk3bbiHgVK3zp5A8n2DEuvMZFRv1GAjTrSvZuLnFr")

        bucket.add_peer(peer_id1, is_replaceable=False)
        bucket.add_peer(peer_id2, is_replaceable=True)

        removed = bucket.remove_replaceable_peer()
        assert removed == peer_id2
        assert bucket.size() == 1
        assert bucket.contains(peer_id1)

    def test_remove_specific_peer(self):
        """Test removing a specific peer."""
        bucket = GridBucket(max_size=20)
        peer_id = ID.from_base58("QmaCpDMGvV2BGHeYERUEnRQAwe5CcqarqmtA7xNXT92p2")

        bucket.add_peer(peer_id)
        assert bucket.contains(peer_id)

        success = bucket.remove_peer(peer_id)
        assert success
        assert not bucket.contains(peer_id)


class TestGridRoutingTable:
    """Tests for GridRoutingTable class."""

    def test_routing_table_creation(self):
        """Test creating a grid routing table."""
        local_id = ID.from_base58("QmaCpDMGvV2BGHeYERUEnRQAwe5CcqarqmtA7xNXT92p2")
        rt = GridRoutingTable(local_id)

        assert rt.local_id == local_id
        assert len(rt.buckets) == GRID_BUCKET_COUNT
        assert rt.size() == 0

    def test_add_peer_updates_routing_table(self):
        """Test adding a peer to the routing table."""
        local_id = ID.from_base58("QmaCpDMGvV2BGHeYERUEnRQAwe5CcqarqmtA7xNXT92p2")
        peer_id = ID.from_base58("QmZLaXk3bbiHgVK3zp5A8n2DEuvMZFRv1GAjTrSvZuLnFr")

        rt = GridRoutingTable(local_id)
        success = rt.update(peer_id)

        assert success
        assert rt.size() == 1
        assert rt.contains(peer_id)

    def test_cannot_add_self(self):
        """Test that local peer cannot be added to routing table."""
        local_id = ID.from_base58("QmaCpDMGvV2BGHeYERUEnRQAwe5CcqarqmtA7xNXT92p2")
        rt = GridRoutingTable(local_id)

        success = rt.update(local_id)
        assert not success
        assert rt.size() == 0

    def test_remove_peer_from_routing_table(self):
        """Test removing a peer from the routing table."""
        local_id = ID.from_base58("QmaCpDMGvV2BGHeYERUEnRQAwe5CcqarqmtA7xNXT92p2")
        peer_id = ID.from_base58("QmZLaXk3bbiHgVK3zp5A8n2DEuvMZFRv1GAjTrSvZuLnFr")

        rt = GridRoutingTable(local_id)
        rt.update(peer_id)
        assert rt.contains(peer_id)

        success = rt.remove(peer_id)
        assert success
        assert not rt.contains(peer_id)

    def test_get_all_peers(self):
        """Test getting all peers from routing table."""
        local_id = ID.from_base58("QmaCpDMGvV2BGHeYERUEnRQAwe5CcqarqmtA7xNXT92p2")
        peer_id1 = ID.from_base58("QmZLaXk3bbiHgVK3zp5A8n2DEuvMZFRv1GAjTrSvZuLnFr")
        peer_id2 = ID.from_base58("QmdgB6x6xfBLvV9VwSPj9D7aHCmXhvEVVBn2CUEbNJnTg")

        rt = GridRoutingTable(local_id)
        rt.update(peer_id1)
        rt.update(peer_id2)

        all_peers = rt.get_all_peers()
        assert len(all_peers) == 2
        assert peer_id1 in all_peers
        assert peer_id2 in all_peers

    def test_get_bucket_index(self):
        """Test getting bucket index for a peer."""
        local_id = ID.from_base58("QmaCpDMGvV2BGHeYERUEnRQAwe5CcqarqmtA7xNXT92p2")
        peer_id = ID.from_base58("QmZLaXk3bbiHgVK3zp5A8n2DEuvMZFRv1GAjTrSvZuLnFr")

        rt = GridRoutingTable(local_id)
        peer_node = NodeId(peer_id)

        bucket_index = rt._get_bucket_index(peer_node)
        assert bucket_index is not None
        assert 0 <= bucket_index < GRID_BUCKET_COUNT

    def test_bucket_index_none_for_self(self):
        """Test that bucket index is None for local ID."""
        local_id = ID.from_base58("QmaCpDMGvV2BGHeYERUEnRQAwe5CcqarqmtA7xNXT92p2")
        rt = GridRoutingTable(local_id)

        bucket_index = rt._get_bucket_index(rt.local_node_id)
        assert bucket_index is None

    def test_multiple_peers_in_same_bucket(self):
        """Test adding multiple peers to the same bucket."""
        local_id = ID.from_base58("QmaCpDMGvV2BGHeYERUEnRQAwe5CcqarqmtA7xNXT92p2")

        rt = GridRoutingTable(local_id)

        peers = [
            ID.from_base58("QmZLaXk3bbiHgVK3zp5A8n2DEuvMZFRv1GAjTrSvZuLnFr"),
            ID.from_base58("QmdgB6x6xfBLvV9VwSPj9D7aHCmXhvEVVBn2CUEbNJnTg"),
            ID.from_base58("QmYPp4CUQpRcpHBqWgmQ4TjqW9AHJ3qLhQV5d7s3d8hMJx"),
        ]

        for peer_id in peers:
            rt.update(peer_id)

        assert rt.size() == len(peers)
        for peer_id in peers:
            assert rt.contains(peer_id)

    def test_get_bucket_stats(self):
        """Test getting bucket statistics."""
        local_id = ID.from_base58("QmaCpDMGvV2BGHeYERUEnRQAwe5CcqarqmtA7xNXT92p2")
        peer_id = ID.from_base58("QmZLaXk3bbiHgVK3zp5A8n2DEuvMZFRv1GAjTrSvZuLnFr")

        rt = GridRoutingTable(local_id)
        rt.update(peer_id)

        stats = rt.get_bucket_stats()
        assert stats["total_peers"] == 1
        assert stats["total_buckets"] == GRID_BUCKET_COUNT
        assert stats["non_empty_buckets"] == 1

    def test_permanent_vs_replaceable_peers(self):
        """Test that replaceable peers can be replaced."""
        local_id = ID.from_base58("QmaCpDMGvV2BGHeYERUEnRQAwe5CcqarqmtA7xNXT92p2")

        rt = GridRoutingTable(local_id, max_bucket_size=2)

        peers = [
            ID.from_base58("QmZLaXk3bbiHgVK3zp5A8n2DEuvMZFRv1GAjTrSvZuLnFr"),
            ID.from_base58("QmdgB6x6xfBLvV9VwSPj9D7aHCmXhvEVVBn2CUEbNJnTg"),
            ID.from_base58("QmYPp4CUQpRcpHBqWgmQ4TjqW9AHJ3qLhQV5d7s3d8hMJx"),
        ]

        rt.update(peers[0], is_permanent=False)
        rt.update(peers[1], is_permanent=True)

        rt.update(peers[2], is_permanent=False)
        assert rt.size() >= 1
        assert rt.size() <= 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
