"""
Core resource manager tests.

Tests the basic functionality of the resource manager including
resource acquisition, release, limits, and error handling.
"""

import threading
from unittest.mock import Mock

import pytest

from libp2p.rcmgr import (
    Direction,
    ResourceLimits,
    ResourceScopeClosed,
    new_resource_manager,
)


class TestResourceManager:
    """Test the core ResourceManager functionality."""

    def test_basic_initialization(self):
        """Test basic resource manager initialization."""
        rm = new_resource_manager()
        assert rm is not None
        assert rm.limits is not None
        assert rm._current_connections == 0
        assert rm._current_memory == 0
        assert rm._current_streams == 0

    def test_custom_limits(self):
        """Test resource manager with custom limits."""
        limits = ResourceLimits(max_connections=100, max_memory_mb=200, max_streams=50)
        rm = new_resource_manager(limits=limits)
        assert rm.limits.max_connections == 100
        assert rm.limits.max_memory_bytes == 200 * 1024 * 1024
        assert rm.limits.max_streams == 50

    def test_connection_acquisition_success(self):
        """Test successful connection acquisition."""
        rm = new_resource_manager()
        assert rm.acquire_connection("peer1") is True
        assert rm._current_connections == 1

    def test_connection_acquisition_limit_exceeded(self):
        """Test connection acquisition when limit is exceeded."""
        limits = ResourceLimits(max_connections=1)
        rm = new_resource_manager(limits=limits)

        # First connection should succeed
        assert rm.acquire_connection("peer1") is True

        # Second connection should fail
        assert rm.acquire_connection("peer2") is False

    def test_connection_release(self):
        """Test connection release."""
        rm = new_resource_manager()
        rm.acquire_connection("peer1")
        assert rm._current_connections == 1

        rm.release_connection("peer1")
        assert rm._current_connections == 0

    def test_memory_acquisition_success(self):
        """Test successful memory acquisition."""
        rm = new_resource_manager()
        assert rm.acquire_memory(1024) is True
        assert rm._current_memory == 1024

    def test_memory_acquisition_limit_exceeded(self):
        """Test memory acquisition when limit is exceeded."""
        limits = ResourceLimits(max_memory_mb=1)  # 1MB limit
        rm = new_resource_manager(limits=limits, enable_graceful_degradation=False)

        # Should succeed with 512KB
        assert rm.acquire_memory(512 * 1024) is True

        # Should fail with another 600KB (would exceed 1MB)
        assert rm.acquire_memory(600 * 1024) is False

    def test_memory_release(self):
        """Test memory release."""
        rm = new_resource_manager()
        rm.acquire_memory(1024)
        assert rm._current_memory == 1024

        rm.release_memory(1024)
        assert rm._current_memory == 0

    def test_stream_acquisition_success(self):
        """Test successful stream acquisition."""
        rm = new_resource_manager()
        from libp2p.rcmgr import Direction

        assert rm.acquire_stream("peer1", Direction.INBOUND) is True
        assert rm._current_streams == 1

    def test_stream_acquisition_limit_exceeded(self):
        """Test stream acquisition when limit is exceeded."""
        limits = ResourceLimits(max_streams=1)
        rm = new_resource_manager(limits=limits)
        from libp2p.rcmgr import Direction

        # First stream should succeed
        assert rm.acquire_stream("peer1", Direction.INBOUND) is True

        # Second stream should fail
        assert rm.acquire_stream("peer2", Direction.OUTBOUND) is False

    def test_stream_release(self):
        """Test stream release."""
        rm = new_resource_manager()
        from libp2p.rcmgr import Direction

        rm.acquire_stream("peer1", Direction.INBOUND)
        assert rm._current_streams == 1

        rm.release_stream("peer1", Direction.INBOUND)
        assert rm._current_streams == 0

    def test_get_stats(self):
        """Test getting resource statistics."""
        rm = new_resource_manager()
        rm.acquire_connection("peer1")
        rm.acquire_memory(1024)
        rm.acquire_stream("peer1", Direction.INBOUND)

        stats = rm.get_stats()
        assert stats["connections"] == 1
        assert stats["memory_bytes"] == 1024
        assert stats["streams"] == 1
        assert "limits" in stats

    def test_is_resource_available(self):
        """Test resource availability checking."""
        limits = ResourceLimits(max_connections=2)
        rm = new_resource_manager(limits=limits)

        # Should be available initially
        assert rm.is_resource_available("connections", 1) is True
        assert rm.is_resource_available("connections", 2) is True
        assert rm.is_resource_available("connections", 3) is False

    def test_closed_manager_raises_error(self):
        """Test that operations on closed manager raise ResourceScopeClosed."""
        rm = new_resource_manager()
        rm.close()

        with pytest.raises(ResourceScopeClosed):
            rm.acquire_connection("peer1")

        with pytest.raises(ResourceScopeClosed):
            rm.acquire_memory(1024)

        with pytest.raises(ResourceScopeClosed):
            rm.acquire_stream("peer1", Direction.INBOUND)

    def test_thread_safety(self):
        """Test thread safety of resource manager."""
        rm = new_resource_manager()
        results = []

        def acquire_connection():
            try:
                result = rm.acquire_connection("peer1")
                results.append(result)
            except Exception:
                results.append(False)

        # Create multiple threads
        threads = []
        for _ in range(10):
            thread = threading.Thread(target=acquire_connection)
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # All acquisitions should succeed (no limit exceeded)
        assert len(results) == 10
        assert all(result is True for result in results)

    def test_open_connection_compatibility(self):
        """Test open_connection method for compatibility."""
        rm = new_resource_manager()

        # Test with string peer_id
        assert rm.open_connection(peer_id="peer1") is not None

        # Test with None peer_id
        assert rm.open_connection(peer_id=None) is not None

        # Test with object peer_id
        mock_peer = Mock()
        mock_peer.__str__ = Mock(return_value="peer2")
        assert rm.open_connection(peer_id=mock_peer) is not None

    def test_resource_limits_validation(self):
        """Test resource limits validation."""
        # Test that negative limits are handled gracefully
        limits = ResourceLimits(max_connections=-1, max_memory_mb=-1, max_streams=-1)
        assert limits.max_connections == -1
        assert limits.max_memory_bytes == -1024 * 1024
        assert limits.max_streams == -1

    def test_memory_limits_edge_cases(self):
        """Test memory limits with edge cases."""
        limits = ResourceLimits(max_memory_mb=1)  # 1MB
        rm = new_resource_manager(limits=limits)

        # Test exact limit
        assert rm.acquire_memory(1024 * 1024) is True
        assert rm._current_memory == 1024 * 1024

        # Test exceeding by 1 byte
        assert rm.acquire_memory(1) is False

    def test_connection_limits_edge_cases(self):
        """Test connection limits with edge cases."""
        limits = ResourceLimits(max_connections=1)
        rm = new_resource_manager(limits=limits)

        # Test exact limit
        assert rm.acquire_connection("peer1") is True
        assert rm._current_connections == 1

        # Test exceeding by 1
        assert rm.acquire_connection("peer2") is False

    def test_stream_limits_edge_cases(self):
        """Test stream limits with edge cases."""
        limits = ResourceLimits(max_streams=1)
        rm = new_resource_manager(limits=limits)
        from libp2p.rcmgr import Direction

        # Test exact limit
        assert rm.acquire_stream("peer1", Direction.INBOUND) is True
        assert rm._current_streams == 1

        # Test exceeding by 1
        assert rm.acquire_stream("peer2", Direction.OUTBOUND) is False

    def test_concurrent_operations(self):
        """Test concurrent resource operations."""
        rm = new_resource_manager()
        results = []

        def mixed_operations():
            try:
                # Mix of different operations
                rm.acquire_connection("peer1")
                rm.acquire_memory(1024)
                rm.acquire_stream("peer1", Direction.INBOUND)
                results.append("success")
            except Exception as e:
                results.append(f"error: {e}")

        # Create multiple threads
        threads = []
        for _ in range(5):
            thread = threading.Thread(target=mixed_operations)
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # All operations should succeed
        assert len(results) == 5
        assert all(result == "success" for result in results)

    def test_resource_cleanup_on_close(self):
        """Test that resources are cleaned up when manager is closed."""
        rm = new_resource_manager()
        rm.acquire_connection("peer1")
        rm.acquire_memory(1024)
        rm.acquire_stream("peer1", Direction.INBOUND)

        # Verify resources are allocated
        assert rm._current_connections == 1
        assert rm._current_memory == 1024
        assert rm._current_streams == 1

        # Close manager
        rm.close()

        # Verify resources are reset
        assert rm._current_connections == 0
        assert rm._current_memory == 0
        assert rm._current_streams == 0

    def test_stats_accuracy(self):
        """Test that statistics are accurate."""
        rm = new_resource_manager()

        # Initial state
        stats = rm.get_stats()
        assert stats["connections"] == 0
        assert stats["memory_bytes"] == 0
        assert stats["streams"] == 0

        # After acquiring resources
        rm.acquire_connection("peer1")
        rm.acquire_memory(2048)
        rm.acquire_stream("peer1", Direction.INBOUND)

        stats = rm.get_stats()
        assert stats["connections"] == 1
        assert stats["memory_bytes"] == 2048
        assert stats["streams"] == 1

        # After releasing resources
        rm.release_connection("peer1")
        rm.release_memory(2048)
        rm.release_stream("peer1", Direction.INBOUND)

        stats = rm.get_stats()
        assert stats["connections"] == 0
        assert stats["memory_bytes"] == 0
        assert stats["streams"] == 0
