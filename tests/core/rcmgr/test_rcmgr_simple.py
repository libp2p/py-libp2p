"""
Simple resource manager tests.

Basic tests for the core functionality without complex scenarios.
"""

from libp2p.rcmgr import (
    Direction,
    ResourceLimits,
    new_resource_manager,
)


class TestSimpleResourceManager:
    """Simple tests for the resource manager."""

    def test_basic_initialization(self):
        """Test basic resource manager initialization."""
        rm = new_resource_manager()
        assert rm is not None
        assert rm.limits is not None

    def test_connection_acquisition(self):
        """Test connection acquisition."""
        rm = new_resource_manager()
        assert rm.acquire_connection("peer1") is True
        assert rm._current_connections == 1

    def test_connection_release(self):
        """Test connection release."""
        rm = new_resource_manager()
        rm.acquire_connection("peer1")
        rm.release_connection("peer1")
        assert rm._current_connections == 0

    def test_memory_acquisition(self):
        """Test memory acquisition."""
        rm = new_resource_manager()
        assert rm.acquire_memory(1024) is True
        assert rm._current_memory == 1024

    def test_memory_release(self):
        """Test memory release."""
        rm = new_resource_manager()
        rm.acquire_memory(1024)
        rm.release_memory(1024)
        assert rm._current_memory == 0

    def test_stream_acquisition(self):
        """Test stream acquisition."""
        rm = new_resource_manager()
        assert rm.acquire_stream("peer1", Direction.INBOUND) is True
        assert rm._current_streams == 1

    def test_stream_release(self):
        """Test stream release."""
        rm = new_resource_manager()
        rm.acquire_stream("peer1", Direction.INBOUND)
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

    def test_custom_limits(self):
        """Test resource manager with custom limits."""
        limits = ResourceLimits(max_connections=100, max_memory_mb=200, max_streams=50)
        rm = new_resource_manager(limits=limits)
        assert rm.limits.max_connections == 100
        assert rm.limits.max_memory_bytes == 200 * 1024 * 1024
        assert rm.limits.max_streams == 50

    def test_connection_limit_exceeded(self):
        """Test connection limit exceeded."""
        limits = ResourceLimits(max_connections=1)
        rm = new_resource_manager(limits=limits, enable_graceful_degradation=False)

        # First connection should succeed
        assert rm.acquire_connection("peer1") is True

        # Second connection should fail
        assert rm.acquire_connection("peer2") is False

    def test_memory_limit_exceeded(self):
        """Test memory limit exceeded."""
        limits = ResourceLimits(max_memory_mb=1)  # 1MB
        rm = new_resource_manager(limits=limits, enable_graceful_degradation=False)

        # Should succeed with 512KB
        assert rm.acquire_memory(512 * 1024) is True

        # Should fail with another 600KB (would exceed 1MB)
        assert rm.acquire_memory(600 * 1024) is False

    def test_stream_limit_exceeded(self):
        """Test stream limit exceeded."""
        limits = ResourceLimits(max_streams=1)
        rm = new_resource_manager(limits=limits, enable_graceful_degradation=False)

        # First stream should succeed
        assert rm.acquire_stream("peer1", Direction.INBOUND) is True

        # Second stream should fail
        assert rm.acquire_stream("peer2", Direction.OUTBOUND) is False

    def test_open_connection_compatibility(self):
        """Test open_connection method for compatibility."""
        rm = new_resource_manager()

        # Test with string peer_id
        assert rm.open_connection(peer_id="peer1") is not None

        # Test with None peer_id
        assert rm.open_connection(peer_id=None) is not None

    def test_resource_cleanup_on_close(self):
        """Test resource cleanup when manager is closed."""
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
