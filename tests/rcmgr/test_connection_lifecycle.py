"""
Comprehensive tests for ConnectionLifecycleManager component.

Tests the connection lifecycle management functionality that coordinates
connection state tracking and limit enforcement.
"""

import pytest
import multiaddr

from libp2p.peer.id import ID
from libp2p.rcmgr.connection_lifecycle import ConnectionLifecycleManager
from libp2p.rcmgr.connection_limits import (
    ConnectionLimits,
    new_connection_limits_with_defaults,
)
from libp2p.rcmgr.connection_tracker import ConnectionTracker
from libp2p.rcmgr.exceptions import ResourceLimitExceeded


class TestConnectionLifecycleManager:
    """Test suite for ConnectionLifecycleManager class."""

    def test_connection_lifecycle_manager_creation(self) -> None:
        """Test ConnectionLifecycleManager creation."""
        limits = new_connection_limits_with_defaults()
        tracker = ConnectionTracker(limits)
        manager = ConnectionLifecycleManager(tracker, limits)

        assert manager.tracker == tracker
        assert manager.limits == limits

    @pytest.mark.asyncio
    async def test_handle_pending_inbound_connection_success(self) -> None:
        """Test handling pending inbound connection successfully."""
        limits = ConnectionLimits(max_pending_inbound=5)
        tracker = ConnectionTracker(limits)
        manager = ConnectionLifecycleManager(tracker, limits)

        connection_id = "conn_1"
        local_addr = multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/8080")
        remote_addr = multiaddr.Multiaddr("/ip4/192.168.1.1/tcp/9090")

        # Should not raise exception
        await manager.handle_pending_inbound_connection(
            connection_id, local_addr, remote_addr
        )

        assert connection_id in tracker.pending_inbound

    @pytest.mark.asyncio
    async def test_handle_pending_inbound_connection_limit_exceeded(self) -> None:
        """Test handling pending inbound connection when limit exceeded."""
        limits = ConnectionLimits(max_pending_inbound=2)
        tracker = ConnectionTracker(limits)
        manager = ConnectionLifecycleManager(tracker, limits)

        local_addr = multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/8080")
        remote_addr = multiaddr.Multiaddr("/ip4/192.168.1.1/tcp/9090")

        # Fill up the limit
        await manager.handle_pending_inbound_connection(
            "conn_1", local_addr, remote_addr
        )
        await manager.handle_pending_inbound_connection(
            "conn_2", local_addr, remote_addr
        )

        # Third connection should fail
        with pytest.raises(ResourceLimitExceeded) as exc_info:
            await manager.handle_pending_inbound_connection(
                "conn_3", local_addr, remote_addr
            )

        assert "pending inbound" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_handle_pending_outbound_connection_success(self) -> None:
        """Test handling pending outbound connection successfully."""
        limits = ConnectionLimits(max_pending_outbound=5)
        tracker = ConnectionTracker(limits)
        manager = ConnectionLifecycleManager(tracker, limits)

        connection_id = "conn_1"
        local_addr = multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/8080")
        peer_id = ID(b"test_peer")

        # Should not raise exception
        await manager.handle_pending_outbound_connection(
            connection_id, peer_id, [local_addr], "tcp"
        )

        assert connection_id in tracker.pending_outbound

    @pytest.mark.asyncio
    async def test_handle_pending_outbound_connection_limit_exceeded(self) -> None:
        """Test handling pending outbound connection when limit exceeded."""
        limits = ConnectionLimits(max_pending_outbound=2)
        tracker = ConnectionTracker(limits)
        manager = ConnectionLifecycleManager(tracker, limits)

        local_addr = multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/8080")
        peer_id = ID(b"test_peer")

        # Fill up the limit
        await manager.handle_pending_outbound_connection(
            "conn_1", peer_id, [local_addr], "tcp"
        )
        await manager.handle_pending_outbound_connection(
            "conn_2", peer_id, [local_addr], "tcp"
        )

        # Third connection should fail
        with pytest.raises(ResourceLimitExceeded) as exc_info:
            await manager.handle_pending_outbound_connection(
                "conn_3", peer_id, [local_addr], "tcp"
            )

        assert "pending outbound" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_handle_established_inbound_connection_success(self) -> None:
        """Test handling established inbound connection successfully."""
        limits = ConnectionLimits(
            max_established_inbound=5,
            max_established_per_peer=3,
            max_established_total=10
        )
        tracker = ConnectionTracker(limits)
        manager = ConnectionLifecycleManager(tracker, limits)

        connection_id = "conn_1"
        peer_id = ID(b"test_peer")
        local_addr = multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/8080")
        remote_addr = multiaddr.Multiaddr("/ip4/192.168.1.1/tcp/9090")

        # Should not raise exception
        await manager.handle_established_inbound_connection(
            connection_id, peer_id, local_addr, remote_addr
        )

        assert connection_id in tracker.established_inbound
        assert peer_id in tracker.established_per_peer
        assert connection_id in tracker.established_per_peer[peer_id]

    @pytest.mark.asyncio
    async def test_handle_established_inbound_connection_limit_exceeded(self) -> None:
        """Test handling established inbound connection when limit exceeded."""
        limits = ConnectionLimits(max_established_inbound=2)
        tracker = ConnectionTracker(limits)
        manager = ConnectionLifecycleManager(tracker, limits)

        local_addr = multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/8080")
        remote_addr = multiaddr.Multiaddr("/ip4/192.168.1.1/tcp/9090")

        # Fill up the limit
        await manager.handle_established_inbound_connection(
            "conn_1", ID(b"peer1"), local_addr, remote_addr
        )
        await manager.handle_established_inbound_connection(
            "conn_2", ID(b"peer2"), local_addr, remote_addr
        )

        # Third connection should fail
        with pytest.raises(ResourceLimitExceeded) as exc_info:
            await manager.handle_established_inbound_connection(
                "conn_3", ID(b"peer3"), local_addr, remote_addr
            )

        assert "established inbound" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_handle_established_outbound_connection_success(self) -> None:
        """Test handling established outbound connection successfully."""
        limits = ConnectionLimits(
            max_established_outbound=5,
            max_established_per_peer=3,
            max_established_total=10
        )
        tracker = ConnectionTracker(limits)
        manager = ConnectionLifecycleManager(tracker, limits)

        connection_id = "conn_1"
        peer_id = ID(b"test_peer")
        local_addr = multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/8080")

        # Should not raise exception
        await manager.handle_established_outbound_connection(
            connection_id, peer_id, local_addr, "tcp"
        )

        assert connection_id in tracker.established_outbound
        assert peer_id in tracker.established_per_peer
        assert connection_id in tracker.established_per_peer[peer_id]

    @pytest.mark.asyncio
    async def test_handle_established_outbound_connection_limit_exceeded(self) -> None:
        """Test handling established outbound connection when limit exceeded."""
        limits = ConnectionLimits(max_established_outbound=2)
        tracker = ConnectionTracker(limits)
        manager = ConnectionLifecycleManager(tracker, limits)

        local_addr = multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/8080")

        # Fill up the limit
        await manager.handle_established_outbound_connection(
            "conn_1", ID(b"peer1"), local_addr, "tcp"
        )
        await manager.handle_established_outbound_connection(
            "conn_2", ID(b"peer2"), local_addr, "tcp"
        )

        # Third connection should fail
        with pytest.raises(ResourceLimitExceeded) as exc_info:
            await manager.handle_established_outbound_connection(
                "conn_3", ID(b"peer3"), local_addr, "tcp"
            )

        assert "established outbound" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_handle_established_connection_per_peer_limit_exceeded(self) -> None:
        """Test handling established connection when per-peer limit exceeded."""
        limits = ConnectionLimits(max_established_per_peer=2)
        tracker = ConnectionTracker(limits)
        manager = ConnectionLifecycleManager(tracker, limits)
        peer_id = ID(b"test_peer")
        local_addr = multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/8080")
        remote_addr = multiaddr.Multiaddr("/ip4/192.168.1.1/tcp/9090")

        # Fill up the per-peer limit
        await manager.handle_established_inbound_connection(
            "conn_1", peer_id, local_addr, remote_addr,
        )
        await manager.handle_established_outbound_connection(
            "conn_2", peer_id, local_addr, "tcp"
        )

        # Third connection for same peer should fail
        with pytest.raises(ResourceLimitExceeded) as exc_info:
            await manager.handle_established_inbound_connection(
                "conn_3", peer_id, local_addr, remote_addr,
            )

        assert "per peer" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_handle_established_connection_total_limit_exceeded(self) -> None:
        """Test handling established connection when total limit exceeded."""
        limits = ConnectionLimits(max_established_total=2)
        tracker = ConnectionTracker(limits)
        manager = ConnectionLifecycleManager(tracker, limits)

        local_addr = multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/8080")
        remote_addr = multiaddr.Multiaddr("/ip4/192.168.1.1/tcp/9090")

        # Fill up the total limit
        await manager.handle_established_inbound_connection(
            "conn_1", ID(b"peer1"), local_addr, remote_addr
        )
        await manager.handle_established_outbound_connection(
            "conn_2", ID(b"peer2"), local_addr, "tcp"
        )

        # Third connection should fail
        with pytest.raises(ResourceLimitExceeded) as exc_info:
            await manager.handle_established_inbound_connection(
                "conn_3", ID(b"peer3"), local_addr, remote_addr
            )

        assert "total" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_handle_connection_closed(self) -> None:
        """Test handling connection closure."""
        limits = ConnectionLimits()
        tracker = ConnectionTracker(limits)
        manager = ConnectionLifecycleManager(tracker, limits)

        connection_id = "conn_1"
        peer_id = ID(b"test_peer")
        local_addr = multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/8080")
        remote_addr = multiaddr.Multiaddr("/ip4/192.168.1.1/tcp/9090")

        # Add connection
        await manager.handle_established_inbound_connection(
            connection_id, peer_id, local_addr, remote_addr
        )
        assert connection_id in tracker.established_inbound

        # Close connection
        await manager.handle_connection_closed(connection_id, peer_id)
        assert connection_id not in tracker.established_inbound
        assert connection_id not in tracker.established_outbound

    @pytest.mark.asyncio
    async def test_handle_connection_closed_nonexistent(self) -> None:
        """Test handling closure of non-existent connection."""
        limits = ConnectionLimits()
        tracker = ConnectionTracker(limits)
        manager = ConnectionLifecycleManager(tracker, limits)

        # Should not raise error
        await manager.handle_connection_closed("nonexistent", ID(b"peer"))

    def test_string_representation(self) -> None:
        """Test string representation of manager."""
        limits = ConnectionLimits()
        tracker = ConnectionTracker(limits)
        manager = ConnectionLifecycleManager(tracker, limits)

        str_repr = str(manager)
        assert "ConnectionLifecycleManager" in str_repr

    def test_repr(self) -> None:
        """Test repr representation of manager."""
        limits = ConnectionLimits()
        tracker = ConnectionTracker(limits)
        manager = ConnectionLifecycleManager(tracker, limits)

        repr_str = repr(manager)
        assert "ConnectionLifecycleManager" in repr_str

    def test_equality(self) -> None:
        """Test manager equality comparison."""
        limits = ConnectionLimits()
        tracker1 = ConnectionTracker(limits)
        tracker2 = ConnectionTracker(limits)
        manager1 = ConnectionLifecycleManager(tracker1, limits)
        manager2 = ConnectionLifecycleManager(tracker1, limits)
        manager3 = ConnectionLifecycleManager(tracker2, limits)

        # Same tracker and limits
        assert manager1 == manager2

        # Different tracker
        assert manager1 != manager3

    def test_hash(self) -> None:
        """Test manager hash functionality."""
        limits = ConnectionLimits()
        tracker = ConnectionTracker(limits)
        manager1 = ConnectionLifecycleManager(tracker, limits)
        manager2 = ConnectionLifecycleManager(tracker, limits)

        # Same tracker and limits
        assert hash(manager1) == hash(manager2)

    def test_in_set(self) -> None:
        """Test manager can be used in sets."""
        limits = ConnectionLimits()
        tracker = ConnectionTracker(limits)
        manager1 = ConnectionLifecycleManager(tracker, limits)
        manager2 = ConnectionLifecycleManager(tracker, limits)

        manager_set = {manager1, manager2}
        assert len(manager_set) == 1  # Same state

    def test_in_dict(self) -> None:
        """Test manager can be used as dictionary key."""
        limits = ConnectionLimits()
        tracker = ConnectionTracker(limits)
        manager = ConnectionLifecycleManager(tracker, limits)

        manager_dict = {manager: "value"}
        assert manager_dict[manager] == "value"

    def test_copy(self) -> None:
        """Test manager can be copied."""
        import copy

        limits = ConnectionLimits()
        tracker = ConnectionTracker(limits)
        manager = ConnectionLifecycleManager(tracker, limits)

        manager_copy = copy.copy(manager)

        # Should be equal but different objects
        assert manager == manager_copy
        assert manager is not manager_copy

    def test_deep_copy(self) -> None:
        """Test manager can be deep copied."""
        import copy

        limits = ConnectionLimits()
        tracker = ConnectionTracker(limits)
        manager = ConnectionLifecycleManager(tracker, limits)

        manager_deep_copy = copy.deepcopy(manager)

        # Should be different objects (realistic for deep copy with new tracker)
        assert manager is not manager_deep_copy
        # Deep copy creates new tracker, so equality is based on tracker identity
        assert manager != manager_deep_copy
