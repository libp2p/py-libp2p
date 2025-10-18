"""
Comprehensive tests for ConnectionTracker component.

Tests the connection state tracking functionality that maintains
connection states and provides per-peer connection counting.
"""

import threading
import time

from libp2p.peer.id import ID
from libp2p.rcmgr.connection_limits import ConnectionLimits
from libp2p.rcmgr.connection_tracker import ConnectionTracker


class TestConnectionTracker:
    """Test suite for ConnectionTracker class."""

    def test_connection_tracker_creation(self) -> None:
        """Test ConnectionTracker creation."""
        limits = ConnectionLimits()
        tracker = ConnectionTracker(limits)

        assert tracker.limits == limits
        assert len(tracker.pending_inbound) == 0
        assert len(tracker.pending_outbound) == 0
        assert len(tracker.established_inbound) == 0
        assert len(tracker.established_outbound) == 0
        assert len(tracker.established_per_peer) == 0
        assert len(tracker.bypass_peers) == 0

    def test_connection_tracker_creation_with_none_limits(self) -> None:
        """Test ConnectionTracker creation with None limits."""
        tracker = ConnectionTracker(None)

        assert tracker.limits is not None  # Should create default limits
        assert len(tracker.pending_inbound) == 0

    def test_add_pending_inbound_connection(self) -> None:
        """Test adding pending inbound connection."""
        limits = ConnectionLimits(max_pending_inbound=5)
        tracker = ConnectionTracker(limits)
        connection_id = "conn_1"
        peer_id = ID(b"test_peer")

        tracker.add_pending_inbound(connection_id, peer_id)

        assert connection_id in tracker.pending_inbound
        assert len(tracker.pending_inbound) == 1

    def test_add_pending_outbound_connection(self) -> None:
        """Test adding pending outbound connection."""
        limits = ConnectionLimits(max_pending_outbound=5)
        tracker = ConnectionTracker(limits)
        connection_id = "conn_1"
        peer_id = ID(b"test_peer")

        tracker.add_pending_outbound(connection_id, peer_id)

        assert connection_id in tracker.pending_outbound
        assert len(tracker.pending_outbound) == 1

    def test_move_to_established_inbound_connection(self) -> None:
        """Test moving connection to established inbound."""
        limits = ConnectionLimits(max_established_inbound=5)
        tracker = ConnectionTracker(limits)
        connection_id = "conn_1"
        peer_id = ID(b"test_peer")

        # First add as pending
        tracker.add_pending_inbound(connection_id, peer_id)
        assert connection_id in tracker.pending_inbound

        # Move to established
        tracker.move_to_established_inbound(connection_id, peer_id)

        assert connection_id not in tracker.pending_inbound
        assert connection_id in tracker.established_inbound
        assert peer_id in tracker.established_per_peer
        assert connection_id in tracker.established_per_peer[peer_id]

    def test_move_to_established_outbound_connection(self) -> None:
        """Test moving connection to established outbound."""
        limits = ConnectionLimits(max_established_outbound=5)
        tracker = ConnectionTracker(limits)
        connection_id = "conn_1"
        peer_id = ID(b"test_peer")

        # First add as pending
        tracker.add_pending_outbound(connection_id, peer_id)
        assert connection_id in tracker.pending_outbound

        # Move to established
        tracker.move_to_established_outbound(connection_id, peer_id)

        assert connection_id not in tracker.pending_outbound
        assert connection_id in tracker.established_outbound
        assert peer_id in tracker.established_per_peer
        assert connection_id in tracker.established_per_peer[peer_id]

    def test_remove_connection(self) -> None:
        """Test removing connection."""
        limits = ConnectionLimits()
        tracker = ConnectionTracker(limits)
        connection_id = "conn_1"
        peer_id = ID(b"test_peer")

        # Add connection
        tracker.add_pending_inbound(connection_id, peer_id)
        tracker.move_to_established_inbound(connection_id, peer_id)

        # Remove connection
        tracker.remove_connection(connection_id, peer_id)

        assert connection_id not in tracker.established_inbound
        assert connection_id not in tracker.established_outbound
        assert peer_id not in tracker.established_per_peer

    def test_remove_connection_nonexistent(self) -> None:
        """Test removing non-existent connection."""
        limits = ConnectionLimits()
        tracker = ConnectionTracker(limits)

        # Should not raise error
        tracker.remove_connection("nonexistent", ID(b"peer"))

    def test_bypass_peer_management(self) -> None:
        """Test bypass peer management."""
        limits = ConnectionLimits()
        tracker = ConnectionTracker(limits)
        peer_id = ID(b"bypass_peer")

        # Add to bypass list
        tracker.add_bypass_peer(peer_id)
        assert peer_id in tracker.bypass_peers
        assert tracker.is_bypassed(peer_id)

        # Remove from bypass list
        tracker.remove_bypass_peer(peer_id)
        assert peer_id not in tracker.bypass_peers
        assert not tracker.is_bypassed(peer_id)

    def test_get_connection_count(self) -> None:
        """Test getting connection count."""
        limits = ConnectionLimits()
        tracker = ConnectionTracker(limits)

        # Add some connections
        tracker.add_pending_inbound("conn_1", ID(b"peer1"))
        tracker.add_pending_outbound("conn_2", ID(b"peer2"))
        tracker.move_to_established_inbound("conn_3", ID(b"peer3"))

        assert tracker.get_connection_count("pending_inbound") == 1
        assert tracker.get_connection_count("pending_outbound") == 1
        assert tracker.get_connection_count("established_inbound") == 1
        assert tracker.get_connection_count("established_outbound") == 0

    def test_get_peer_connection_count(self) -> None:
        """Test getting peer connection count."""
        limits = ConnectionLimits()
        tracker = ConnectionTracker(limits)
        peer_id = ID(b"test_peer")

        # Add connections for peer
        tracker.move_to_established_inbound("conn_1", peer_id)
        tracker.move_to_established_outbound("conn_2", peer_id)

        assert tracker.get_peer_connection_count(peer_id) == 2

    def test_get_peer_connection_count_nonexistent_peer(self) -> None:
        """Test getting connection count for non-existent peer."""
        limits = ConnectionLimits()
        tracker = ConnectionTracker(limits)

        assert tracker.get_peer_connection_count(ID(b"nonexistent")) == 0

    def test_get_connection_info(self) -> None:
        """Test getting connection info."""
        limits = ConnectionLimits()
        tracker = ConnectionTracker(limits)
        connection_id = "conn_1"
        peer_id = ID(b"test_peer")

        # Add connection
        tracker.add_pending_inbound(connection_id, peer_id)

        info = tracker.get_connection_info(connection_id)
        assert info is not None
        assert info.connection_id == connection_id
        assert info.peer_id == peer_id
        assert info.direction == "inbound"
        assert info.state == "pending"

    def test_get_connection_info_nonexistent(self) -> None:
        """Test getting connection info for non-existent connection."""
        limits = ConnectionLimits()
        tracker = ConnectionTracker(limits)

        info = tracker.get_connection_info("nonexistent")
        assert info is None

    def test_get_all_connections(self) -> None:
        """Test getting all connections."""
        limits = ConnectionLimits()
        tracker = ConnectionTracker(limits)

        # Add some connections
        tracker.add_pending_inbound("conn_1", ID(b"peer1"))
        tracker.add_pending_outbound("conn_2", ID(b"peer2"))
        tracker.add_pending_inbound("conn_3", ID(b"peer3"))
        tracker.move_to_established_inbound("conn_3", ID(b"peer3"))

        connections = tracker.get_all_connections()
        assert len(connections) == 3

    def test_get_stats(self) -> None:
        """Test getting tracker statistics."""
        limits = ConnectionLimits()
        tracker = ConnectionTracker(limits)

        # Add some connections
        tracker.add_pending_inbound("conn_1", ID(b"peer1"))
        tracker.move_to_established_inbound("conn_2", ID(b"peer2"))

        stats = tracker.get_stats()
        assert isinstance(stats, dict)
        assert "total_connections_created" in stats
        assert "total_connections_established" in stats

    def test_clear(self) -> None:
        """Test clearing all connections."""
        limits = ConnectionLimits()
        tracker = ConnectionTracker(limits)

        # Add some connections
        tracker.add_pending_inbound("conn_1", ID(b"peer1"))
        tracker.move_to_established_inbound("conn_2", ID(b"peer2"))

        # Clear all
        tracker.clear()

        assert len(tracker.pending_inbound) == 0
        assert len(tracker.pending_outbound) == 0
        assert len(tracker.established_inbound) == 0
        assert len(tracker.established_outbound) == 0
        assert len(tracker.established_per_peer) == 0

    def test_edge_cases_empty_connection_id(self) -> None:
        """Test edge cases with empty connection ID."""
        limits = ConnectionLimits()
        tracker = ConnectionTracker(limits)

        # Should not raise error
        tracker.add_pending_inbound("", ID(b"peer"))
        tracker.remove_connection("", ID(b"peer"))

    def test_edge_cases_empty_peer_id(self) -> None:
        """Test edge cases with empty peer ID."""
        limits = ConnectionLimits()
        tracker = ConnectionTracker(limits)
        empty_peer = ID(b"")

        # Should not raise error
        tracker.add_pending_inbound("conn_1", empty_peer)
        tracker.remove_connection("conn_1", empty_peer)

    def test_edge_cases_unicode_connection_id(self) -> None:
        """Test edge cases with unicode connection ID."""
        limits = ConnectionLimits()
        tracker = ConnectionTracker(limits)
        unicode_conn_id = "conn_测试_🚀"
        peer_id = ID(b"test_peer")

        tracker.add_pending_inbound(unicode_conn_id, peer_id)
        assert unicode_conn_id in tracker.pending_inbound

        tracker.remove_connection(unicode_conn_id, peer_id)
        assert unicode_conn_id not in tracker.pending_inbound

    def test_edge_cases_very_long_connection_id(self) -> None:
        """Test edge cases with very long connection ID."""
        limits = ConnectionLimits()
        tracker = ConnectionTracker(limits)
        long_conn_id = "conn_" + "x" * 1000
        peer_id = ID(b"test_peer")

        tracker.add_pending_inbound(long_conn_id, peer_id)
        assert long_conn_id in tracker.pending_inbound

        tracker.remove_connection(long_conn_id, peer_id)
        assert long_conn_id not in tracker.pending_inbound

    def test_concurrent_access(self) -> None:
        """Test concurrent access to tracker."""
        limits = ConnectionLimits()
        tracker = ConnectionTracker(limits)
        results = []
        errors = []

        def add_connection(conn_id) -> None:
            try:
                tracker.add_pending_inbound(conn_id, ID(b"peer"))
                results.append(conn_id)
            except Exception as e:
                errors.append(e)

        # Create multiple threads
        threads = []
        for i in range(10):
            thread = threading.Thread(target=add_connection, args=(f"conn_{i}",))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # All should succeed
        assert len(results) == 10
        assert len(errors) == 0
        assert len(tracker.pending_inbound) == 10

    def test_performance_large_operations(self) -> None:
        """Test performance with large number of operations."""
        limits = ConnectionLimits()
        tracker = ConnectionTracker(limits)

        start_time = time.time()

        # Perform many operations
        for i in range(1000):
            conn_id = f"conn_{i}"
            peer_id = ID(f"peer_{i}".encode())
            tracker.add_pending_inbound(conn_id, peer_id)
            tracker.move_to_established_inbound(conn_id, peer_id)
            tracker.remove_connection(conn_id, peer_id)

        end_time = time.time()
        elapsed = end_time - start_time

        # Should complete in reasonable time
        assert elapsed < 1.0

    def test_string_representation(self) -> None:
        """Test string representation of tracker."""
        limits = ConnectionLimits()
        tracker = ConnectionTracker(limits)

        str_repr = str(tracker)
        assert "ConnectionTracker" in str_repr

    def test_equality(self) -> None:
        """Test tracker equality comparison."""
        limits = ConnectionLimits()
        tracker1 = ConnectionTracker(limits)
        tracker2 = ConnectionTracker(limits)

        # Should be equal (same state)
        assert tracker1 == tracker2

    def test_hash(self) -> None:
        """Test tracker hash functionality."""
        limits = ConnectionLimits()
        tracker1 = ConnectionTracker(limits)
        tracker2 = ConnectionTracker(limits)

        # Should have same hash (same state)
        assert hash(tracker1) == hash(tracker2)

    def test_in_set(self) -> None:
        """Test tracker can be used in sets."""
        limits = ConnectionLimits()
        tracker1 = ConnectionTracker(limits)
        tracker2 = ConnectionTracker(limits)

        tracker_set = {tracker1, tracker2}
        assert len(tracker_set) == 1  # Same state

    def test_in_dict(self) -> None:
        """Test tracker can be used as dictionary key."""
        limits = ConnectionLimits()
        tracker = ConnectionTracker(limits)

        tracker_dict = {tracker: "value"}
        assert tracker_dict[tracker] == "value"

    def test_copy(self) -> None:
        """Test tracker can be copied."""
        import copy

        limits = ConnectionLimits()
        tracker = ConnectionTracker(limits)

        tracker_copy = copy.copy(tracker)

        # Should be equal but different objects
        assert tracker == tracker_copy
        assert tracker is not tracker_copy

    def test_deep_copy(self) -> None:
        """Test tracker can be deep copied."""
        import copy

        limits = ConnectionLimits()
        tracker = ConnectionTracker(limits)

        tracker_deep_copy = copy.deepcopy(tracker)

        # Should be equal but different objects
        assert tracker == tracker_deep_copy
        assert tracker is not tracker_deep_copy

    def test_serialization(self) -> None:
        """Test tracker can be serialized."""
        import json

        limits = ConnectionLimits()
        tracker = ConnectionTracker(limits)

        # Add some data
        tracker.add_pending_inbound("conn_1", ID(b"peer1"))

        # Get stats for serialization
        stats = tracker.get_stats()

        # Should be serializable
        json_str = json.dumps(stats)
        assert isinstance(json_str, str)

        # Should be deserializable
        deserialized = json.loads(json_str)
        assert isinstance(deserialized, dict)
