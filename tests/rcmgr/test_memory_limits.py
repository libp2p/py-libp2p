"""
Comprehensive tests for MemoryConnectionLimits component.

Tests the memory-based connection limits functionality that enforces
memory thresholds to deny new connections when memory usage is high.
"""

from unittest.mock import Mock, patch

import pytest

from libp2p.rcmgr.exceptions import ResourceLimitExceeded
from libp2p.rcmgr.memory_limits import (
    MemoryConnectionLimits,
    new_memory_connection_limits_with_defaults,
)
from libp2p.rcmgr.memory_stats import MemoryStats, MemoryStatsCache


class TestMemoryConnectionLimits:
    """Test suite for MemoryConnectionLimits class."""

    def test_memory_connection_limits_creation(self):
        """Test MemoryConnectionLimits creation with default values."""
        limits = new_memory_connection_limits_with_defaults()

        assert limits.max_process_memory_bytes is None
        assert limits.max_process_memory_percent == 80.0
        assert limits.max_system_memory_percent == 90.0
        assert limits.memory_stats_cache is not None  # Cache is auto-created

    def test_memory_connection_limits_creation_with_custom_values(self):
        """Test MemoryConnectionLimits creation with custom values."""
        cache = MemoryStatsCache()
        limits = MemoryConnectionLimits(
            max_process_memory_bytes=1024*1024*1024,  # 1GB
            max_process_memory_percent=70.0,
            max_system_memory_percent=85.0,
            memory_stats_cache=cache,
        )

        assert limits.max_process_memory_bytes == 1024*1024*1024
        assert limits.max_process_memory_percent == 70.0
        assert limits.max_system_memory_percent == 85.0
        assert limits.memory_stats_cache == cache

    def test_check_memory_limits_without_cache(self):
        """Test checking memory limits without cache."""
        limits = MemoryConnectionLimits()

        # Should not raise exception when no cache is available
        limits.check_memory_limits()

    def test_check_memory_limits_with_cache_no_limits(self):
        """Test checking memory limits with cache but no limits set."""
        cache = MemoryStatsCache()
        limits = MemoryConnectionLimits(memory_stats_cache=cache)

        # Should not raise exception when no limits are set
        limits.check_memory_limits()

    def test_check_memory_limits_process_bytes_within_limit(self):
        """Test checking process memory bytes when within limit."""
        cache = MemoryStatsCache()
        limits = MemoryConnectionLimits(
            max_process_memory_bytes=1024*1024*1024,  # 1GB
            memory_stats_cache=cache,
        )

        with patch.object(cache, 'get_memory_stats') as mock_get_stats:
            mock_get_stats.return_value = {
                "process_memory_bytes": 512*1024*1024,  # 512MB
                "process_memory_percent": 50.0,
                "system_memory_bytes": 8*1024*1024*1024,  # 8GB
                "system_memory_percent": 60.0,
                "available_memory_bytes": 3*1024*1024*1024,  # 3GB
                "timestamp": 1234567890,
            }

            # Should not raise exception
            limits.check_memory_limits()

    def test_check_memory_limits_process_bytes_exceeds_limit(self):
        """Test checking process memory bytes when exceeding limit."""
        cache = MemoryStatsCache()
        limits = MemoryConnectionLimits(
            max_process_memory_bytes=1024*1024*1024,  # 1GB
            memory_stats_cache=cache,
        )

        with patch.object(cache, 'get_memory_stats') as mock_get_stats:
            mock_get_stats.return_value = MemoryStats(
                process_memory_bytes=2*1024*1024*1024,  # 2GB
                process_memory_percent=50.0,
                system_memory_total=8*1024*1024*1024,  # 8GB
                system_memory_available=3*1024*1024*1024,  # 3GB
                system_memory_percent=60.0,
                timestamp=1234567890,
            )

            with pytest.raises(ResourceLimitExceeded) as exc_info:
                limits.check_memory_limits()

            assert "process memory" in str(exc_info.value).lower()
            assert "2" in str(exc_info.value)  # Current value
            assert "1" in str(exc_info.value)  # Limit value

    def test_check_memory_limits_process_percent_within_limit(self):
        """Test checking process memory percent when within limit."""
        cache = MemoryStatsCache()
        limits = MemoryConnectionLimits(
            max_process_memory_percent=80.0,
            memory_stats_cache=cache,
        )

        with patch.object(cache, 'get_memory_stats') as mock_get_stats:
            mock_get_stats.return_value = {
                "process_memory_bytes": 512*1024*1024,  # 512MB
                "process_memory_percent": 70.0,
                "system_memory_bytes": 8*1024*1024*1024,  # 8GB
                "system_memory_percent": 60.0,
                "available_memory_bytes": 3*1024*1024*1024,  # 3GB
                "timestamp": 1234567890,
            }

            # Should not raise exception
            limits.check_memory_limits()

    def test_check_memory_limits_process_percent_exceeds_limit(self):
        """Test checking process memory percent when exceeding limit."""
        cache = MemoryStatsCache()
        limits = MemoryConnectionLimits(
            max_process_memory_percent=80.0,
            memory_stats_cache=cache,
        )

        with patch.object(cache, 'get_memory_stats') as mock_get_stats:
            mock_get_stats.return_value = MemoryStats(
                process_memory_bytes=512*1024*1024,  # 512MB
                process_memory_percent=85.0,
                system_memory_total=8*1024*1024*1024,  # 8GB
                system_memory_available=3*1024*1024*1024,  # 3GB
                system_memory_percent=60.0,
                timestamp=1234567890,
            )

            with pytest.raises(ResourceLimitExceeded) as exc_info:
                limits.check_memory_limits()

            assert "process memory" in str(exc_info.value).lower()
            assert "85" in str(exc_info.value)  # Current value
            assert "80" in str(exc_info.value)  # Limit value

    def test_check_memory_limits_system_percent_within_limit(self):
        """Test checking system memory percent when within limit."""
        cache = MemoryStatsCache()
        limits = MemoryConnectionLimits(
            max_system_memory_percent=90.0,
            memory_stats_cache=cache,
        )

        with patch.object(cache, 'get_memory_stats') as mock_get_stats:
            mock_get_stats.return_value = {
                "process_memory_bytes": 512*1024*1024,  # 512MB
                "process_memory_percent": 50.0,
                "system_memory_bytes": 8*1024*1024*1024,  # 8GB
                "system_memory_percent": 80.0,
                "available_memory_bytes": 1*1024*1024*1024,  # 1GB
                "timestamp": 1234567890,
            }

            # Should not raise exception
            limits.check_memory_limits()

    def test_check_memory_limits_system_percent_exceeds_limit(self):
        """Test checking system memory percent when exceeding limit."""
        cache = MemoryStatsCache()
        limits = MemoryConnectionLimits(
            max_system_memory_percent=90.0,
            memory_stats_cache=cache,
        )

        with patch.object(cache, 'get_memory_stats') as mock_get_stats:
            mock_get_stats.return_value = MemoryStats(
                process_memory_bytes=512*1024*1024,  # 512MB
                process_memory_percent=50.0,
                system_memory_total=8*1024*1024*1024,  # 8GB
                system_memory_available=400*1024*1024,  # 400MB
                system_memory_percent=95.0,
                timestamp=1234567890,
            )

            with pytest.raises(ResourceLimitExceeded) as exc_info:
                limits.check_memory_limits()

            assert "system memory" in str(exc_info.value).lower()
            assert "95" in str(exc_info.value)  # Current value
            assert "90" in str(exc_info.value)  # Limit value

    def test_check_memory_limits_multiple_limits_exceeded(self):
        """Test checking memory limits when multiple limits are exceeded."""
        cache = MemoryStatsCache()
        limits = MemoryConnectionLimits(
            max_process_memory_bytes=1024*1024*1024,  # 1GB
            max_process_memory_percent=80.0,
            max_system_memory_percent=90.0,
            memory_stats_cache=cache,
        )

        with patch.object(cache, 'get_memory_stats') as mock_get_stats:
            mock_get_stats.return_value = MemoryStats(
                process_memory_bytes=2*1024*1024*1024,  # 2GB
                process_memory_percent=85.0,
                system_memory_total=8*1024*1024*1024,  # 8GB
                system_memory_available=400*1024*1024,  # 400MB
                system_memory_percent=95.0,
                timestamp=1234567890,
            )

            with pytest.raises(ResourceLimitExceeded) as exc_info:
                limits.check_memory_limits()

            # Should mention the first limit that was exceeded
            assert "process memory" in str(exc_info.value).lower()

    def test_check_memory_limits_with_force_refresh(self):
        """Test checking memory limits with force refresh."""
        cache = MemoryStatsCache()
        limits = MemoryConnectionLimits(
            max_process_memory_percent=80.0,
            memory_stats_cache=cache,
        )

        with patch.object(cache, 'get_memory_stats') as mock_get_stats:
            mock_get_stats.return_value = MemoryStats(
                process_memory_bytes=512*1024*1024,  # 512MB
                process_memory_percent=70.0,
                system_memory_total=8*1024*1024*1024,  # 8GB
                system_memory_available=3*1024*1024*1024,  # 3GB
                system_memory_percent=60.0,
                timestamp=1234567890,
            )

            # Should not raise exception
            limits.check_memory_limits(force_refresh=True)

            # Should have called get_memory_stats with force_refresh=True
            mock_get_stats.assert_called_with(force_refresh=True)

    def test_check_memory_limits_cache_error(self):
        """Test checking memory limits when cache raises error."""
        cache = MemoryStatsCache()
        limits = MemoryConnectionLimits(
            max_process_memory_percent=80.0,
            memory_stats_cache=cache,
        )

        with patch.object(cache, 'get_memory_stats') as mock_get_stats:
            mock_get_stats.side_effect = Exception("Cache error")

            # Should not raise exception, should handle error gracefully
            limits.check_memory_limits()

    def test_check_memory_limits_cache_none(self):
        """Test checking memory limits when cache is None."""
        limits = MemoryConnectionLimits(
            max_process_memory_percent=80.0,
            memory_stats_cache=None,
        )

        # Should not raise exception when cache is None
        limits.check_memory_limits()

    def test_get_memory_summary(self):
        """Test getting memory summary."""
        cache = MemoryStatsCache()
        limits = MemoryConnectionLimits(
            max_process_memory_bytes=1024*1024*1024,  # 1GB
            max_process_memory_percent=80.0,
            max_system_memory_percent=90.0,
            memory_stats_cache=cache,
        )

        with patch.object(cache, 'get_memory_summary') as mock_get_summary:
            mock_get_summary.return_value = {
                "process": {
                    "memory_bytes": 512*1024*1024,
                    "memory_percent": 50.0,
                    "rss_bytes": 512*1024*1024,
                    "vms_bytes": 1024*1024*1024,
                },
                "system": {
                    "total_memory_bytes": 8*1024*1024*1024,
                    "available_memory_bytes": 4*1024*1024*1024,
                    "memory_percent": 50.0,
                    "swap_total_bytes": 2*1024*1024*1024,
                    "swap_available_bytes": 1*1024*1024*1024,
                },
                "timestamp": 1234567890,
            }

            summary = limits.get_memory_summary()

            assert summary is not None
            assert "current" in summary
            assert "max_process_memory_bytes" in summary
            assert "max_process_memory_percent" in summary
            assert "max_system_memory_percent" in summary
            assert "has_limits_configured" in summary

    def test_get_memory_summary_with_force_refresh(self):
        """Test getting memory summary with force refresh."""
        cache = MemoryStatsCache()
        limits = MemoryConnectionLimits(memory_stats_cache=cache)

        with patch.object(cache, 'get_memory_summary') as mock_get_summary:
            mock_get_summary.return_value = {"test": "data"}

            limits.get_memory_summary(force_refresh=True)

            # Should have called get_memory_summary with force_refresh=True
            mock_get_summary.assert_called_with(force_refresh=True)

    def test_get_memory_summary_cache_none(self):
        """Test getting memory summary when cache is None."""
        # Create limits and manually set cache to None after initialization
        limits = MemoryConnectionLimits()
        limits.memory_stats_cache = None

        # Should return limits summary when cache is None
        summary = limits.get_memory_summary()
        assert summary is not None
        assert "max_process_memory_bytes" in summary
        assert "max_process_memory_percent" in summary
        assert "max_system_memory_percent" in summary
        assert "has_limits_configured" in summary
        assert "current" not in summary  # No current data when cache is None

    def test_get_memory_summary_cache_error(self):
        """Test getting memory summary when cache raises error."""
        cache = MemoryStatsCache()
        limits = MemoryConnectionLimits(memory_stats_cache=cache)

        with patch.object(cache, 'get_memory_summary') as mock_get_summary:
            mock_get_summary.side_effect = Exception("Cache error")

            # Should return limits summary when cache raises error
            summary = limits.get_memory_summary()
            assert summary is not None
            assert "max_process_memory_bytes" in summary
            assert "max_process_memory_percent" in summary
            assert "max_system_memory_percent" in summary
            assert "has_limits_configured" in summary
            assert "current" not in summary  # No current data when cache raises error

    def test_memory_limits_equality(self):
        """Test memory limits equality comparison."""
        cache1 = MemoryStatsCache()
        cache2 = MemoryStatsCache()

        limits1 = MemoryConnectionLimits(
            max_process_memory_bytes=1024*1024*1024,
            memory_stats_cache=cache1,
        )
        limits2 = MemoryConnectionLimits(
            max_process_memory_bytes=1024*1024*1024,
            memory_stats_cache=cache1,
        )
        limits3 = MemoryConnectionLimits(
            max_process_memory_bytes=2*1024*1024*1024,
            memory_stats_cache=cache1,
        )
        limits4 = MemoryConnectionLimits(
            max_process_memory_bytes=1024*1024*1024,
            memory_stats_cache=cache2,
        )

        # Same values, same cache
        assert limits1 == limits2

        # Different values
        assert limits1 != limits3

        # Same values, different cache - should be equal since cache is not part of configuration
        assert limits1 == limits4

    def test_memory_limits_string_representation(self):
        """Test string representation of memory limits."""
        limits = MemoryConnectionLimits(
            max_process_memory_bytes=1024*1024*1024,
            max_process_memory_percent=80.0,
            max_system_memory_percent=90.0,
        )

        str_repr = str(limits)
        assert "MemoryConnectionLimits" in str_repr
        assert "1073741824" in str_repr  # max_process_memory_bytes (1024*1024*1024)
        assert "80" in str_repr    # max_process_memory_percent
        assert "90" in str_repr    # max_system_memory_percent

    def test_memory_limits_repr(self):
        """Test repr representation of memory limits."""
        limits = MemoryConnectionLimits(max_process_memory_bytes=1024*1024*1024)

        repr_str = repr(limits)
        assert "MemoryConnectionLimits" in repr_str
        assert "max_process_memory_bytes=1073741824" in repr_str

    def test_memory_limits_hash(self):
        """Test memory limits hash functionality."""
        cache = MemoryStatsCache()
        limits1 = MemoryConnectionLimits(
            max_process_memory_bytes=1024*1024*1024,
            memory_stats_cache=cache,
        )
        limits2 = MemoryConnectionLimits(
            max_process_memory_bytes=1024*1024*1024,
            memory_stats_cache=cache,
        )

        # Same values, same cache
        assert hash(limits1) == hash(limits2)

    def test_memory_limits_in_set(self):
        """Test memory limits can be used in sets."""
        cache = MemoryStatsCache()
        limits1 = MemoryConnectionLimits(
            max_process_memory_bytes=1024*1024*1024,
            memory_stats_cache=cache,
        )
        limits2 = MemoryConnectionLimits(
            max_process_memory_bytes=1024*1024*1024,
            memory_stats_cache=cache,
        )
        limits3 = MemoryConnectionLimits(
            max_process_memory_bytes=2*1024*1024*1024,
            memory_stats_cache=cache,
        )

        limits_set = {limits1, limits2, limits3}
        assert len(limits_set) == 2  # limits1 and limits2 are equal

    def test_memory_limits_in_dict(self):
        """Test memory limits can be used as dictionary key."""
        cache = MemoryStatsCache()
        limits = MemoryConnectionLimits(
            max_process_memory_bytes=1024*1024*1024,
            memory_stats_cache=cache,
        )

        limits_dict = {limits: "value"}
        assert limits_dict[limits] == "value"

    def test_memory_limits_copy(self):
        """Test memory limits can be copied."""
        import copy

        cache = MemoryStatsCache()
        limits = MemoryConnectionLimits(
            max_process_memory_bytes=1024*1024*1024,
            memory_stats_cache=cache,
        )

        limits_copy = copy.copy(limits)

        # Should be equal but different objects
        assert limits == limits_copy
        assert limits is not limits_copy

    def test_memory_limits_deep_copy(self):
        """Test memory limits can be deep copied."""
        import copy

        cache = MemoryStatsCache()
        limits = MemoryConnectionLimits(
            max_process_memory_bytes=1024*1024*1024,
            memory_stats_cache=cache,
        )

        limits_deep_copy = copy.deepcopy(limits)

        # Should be equal but different objects
        assert limits == limits_deep_copy
        assert limits is not limits_deep_copy

    def test_memory_limits_serialization(self):
        """Test memory limits can be serialized."""
        import json

        limits = MemoryConnectionLimits(
            max_process_memory_bytes=1024*1024*1024,
            max_process_memory_percent=80.0,
            max_system_memory_percent=90.0,
        )

        # Convert to dict for serialization
        limits_dict = {
            "max_process_memory_bytes": limits.max_process_memory_bytes,
            "max_process_memory_percent": limits.max_process_memory_percent,
            "max_system_memory_percent": limits.max_system_memory_percent,
        }

        # Should be serializable
        json_str = json.dumps(limits_dict)
        assert json_str is not None

        # Should be deserializable
        deserialized = json.loads(json_str)
        assert deserialized["max_process_memory_bytes"] == 1024*1024*1024
        assert deserialized["max_process_memory_percent"] == 80.0
        assert deserialized["max_system_memory_percent"] == 90.0

    def test_memory_limits_edge_cases(self):
        """Test memory limits edge cases."""
        cache = MemoryStatsCache()

        # Test with zero limits
        limits = MemoryConnectionLimits(
            max_process_memory_bytes=0,
            max_process_memory_percent=0.0,
            max_system_memory_percent=0.0,
            memory_stats_cache=cache,
        )

        with patch.object(cache, 'get_memory_stats') as mock_get_stats:
            mock_get_stats.return_value = MemoryStats(
                process_memory_bytes=1,  # Any non-zero value
                process_memory_percent=0.1,  # Any non-zero value
                system_memory_total=8*1024*1024*1024,
                system_memory_available=4*1024*1024*1024,
                system_memory_percent=0.1,  # Any non-zero value
                timestamp=1234567890,
            )

            # Should raise exception for any non-zero usage
            with pytest.raises(ResourceLimitExceeded):
                limits.check_memory_limits()

    def test_memory_limits_very_high_limits(self):
        """Test memory limits with very high limits."""
        cache = MemoryStatsCache()
        limits = MemoryConnectionLimits(
            max_process_memory_bytes=100*1024*1024*1024,  # 100GB
            max_process_memory_percent=99.9,
            max_system_memory_percent=99.9,
            memory_stats_cache=cache,
        )

        with patch.object(cache, 'get_memory_stats') as mock_get_stats:
            mock_get_stats.return_value = {
                "process_memory_bytes": 50*1024*1024*1024,  # 50GB
                "process_memory_percent": 50.0,
                "system_memory_bytes": 8*1024*1024*1024,  # 8GB
                "system_memory_percent": 50.0,
                "available_memory_bytes": 4*1024*1024*1024,  # 4GB
                "timestamp": 1234567890,
            }

            # Should not raise exception
            limits.check_memory_limits()

    def test_memory_limits_negative_values(self):
        """Test memory limits with negative values."""
        cache = MemoryStatsCache()
        limits = MemoryConnectionLimits(
            max_process_memory_bytes=-1,  # Negative value
            max_process_memory_percent=-1.0,  # Negative value
            max_system_memory_percent=-1.0,  # Negative value
            memory_stats_cache=cache,
        )

        with patch.object(cache, 'get_memory_stats') as mock_get_stats:
            mock_get_stats.return_value = {
                "process_memory_bytes": 512*1024*1024,
                "process_memory_percent": 50.0,
                "system_memory_bytes": 8*1024*1024*1024,
                "system_memory_percent": 50.0,
                "available_memory_bytes": 4*1024*1024*1024,
                "timestamp": 1234567890,
            }

            # Should not raise exception (negative limits are ignored)
            limits.check_memory_limits()

    def test_memory_limits_none_values(self):
        """Test memory limits with None values."""
        cache = MemoryStatsCache()
        limits = MemoryConnectionLimits(
            max_process_memory_bytes=None,
            max_process_memory_percent=None,
            max_system_memory_percent=None,
            memory_stats_cache=cache,
        )

        with patch.object(cache, 'get_memory_stats') as mock_get_stats:
            mock_get_stats.return_value = {
                "process_memory_bytes": 512*1024*1024,
                "process_memory_percent": 50.0,
                "system_memory_bytes": 8*1024*1024*1024,
                "system_memory_percent": 50.0,
                "available_memory_bytes": 4*1024*1024*1024,
                "timestamp": 1234567890,
            }

            # Should not raise exception (None limits are ignored)
            limits.check_memory_limits()

    def test_memory_limits_performance(self):
        """Test memory limits performance."""
        cache = MemoryStatsCache()
        limits = MemoryConnectionLimits(
            max_process_memory_percent=80.0,
            memory_stats_cache=cache,
        )

        with patch.object(cache, 'get_memory_stats') as mock_get_stats:
            mock_get_stats.return_value = {
                "process_memory_bytes": 512*1024*1024,
                "process_memory_percent": 70.0,
                "system_memory_bytes": 8*1024*1024*1024,
                "system_memory_percent": 60.0,
                "available_memory_bytes": 3*1024*1024*1024,
                "timestamp": 1234567890,
            }

            # Measure time for many operations
            import time
            start_time = time.time()

            for _ in range(1000):
                limits.check_memory_limits()

            end_time = time.time()
            elapsed = end_time - start_time

            # Should complete in reasonable time
            assert elapsed < 1.0  # Should complete in less than 1 second

    def test_memory_limits_concurrent_access(self):
        """Test memory limits with concurrent access."""
        import threading

        cache = MemoryStatsCache()
        limits = MemoryConnectionLimits(
            max_process_memory_percent=80.0,
            memory_stats_cache=cache,
        )

        results = []
        errors = []

        def check_limits():
            try:
                with patch.object(cache, 'get_memory_stats') as mock_get_stats:
                    mock_get_stats.return_value = {
                        "process_memory_bytes": 512*1024*1024,
                        "process_memory_percent": 70.0,
                        "system_memory_bytes": 8*1024*1024*1024,
                        "system_memory_percent": 60.0,
                        "available_memory_bytes": 3*1024*1024*1024,
                        "timestamp": 1234567890,
                    }

                    limits.check_memory_limits()
                    results.append("success")
            except Exception as e:
                errors.append(e)

        # Start multiple threads
        threads = []
        for _ in range(10):
            t = threading.Thread(target=check_limits)
            threads.append(t)
            t.start()

        # Wait for completion
        for t in threads:
            t.join()

        # All should succeed
        assert len(results) == 10
        assert len(errors) == 0

    def test_memory_limits_with_mock_psutil(self):
        """Test memory limits with mocked psutil."""
        with patch('libp2p.rcmgr.memory_stats.psutil') as mock_psutil:
            # Mock process
            mock_process = Mock()
            mock_process.memory_info.return_value = Mock(rss=1024*1024, vms=2048*1024)
            mock_process.memory_percent.return_value = 85.0  # Exceeds 80% limit

            # Mock virtual memory
            mock_virtual_memory = Mock()
            mock_virtual_memory.total = 8 * 1024 * 1024 * 1024  # 8GB
            mock_virtual_memory.available = 4 * 1024 * 1024 * 1024  # 4GB
            mock_virtual_memory.percent = 50.0

            # Mock swap memory
            mock_swap_memory = Mock()
            mock_swap_memory.total = 2 * 1024 * 1024 * 1024  # 2GB
            mock_swap_memory.free = 1 * 1024 * 1024 * 1024  # 1GB

            # Configure mocks
            mock_psutil.Process.return_value = mock_process
            mock_psutil.virtual_memory.return_value = mock_virtual_memory
            mock_psutil.swap_memory.return_value = mock_swap_memory

            cache = MemoryStatsCache()
            limits = MemoryConnectionLimits(
                max_process_memory_percent=80.0,
                memory_stats_cache=cache,
            )

            # Should raise exception due to high process memory percent
            with pytest.raises(ResourceLimitExceeded):
                limits.check_memory_limits()

    def test_memory_limits_with_psutil_error(self):
        """Test memory limits with psutil error."""
        with patch('libp2p.rcmgr.memory_stats.psutil') as mock_psutil:
            # Mock psutil to raise exception
            mock_psutil.Process.side_effect = Exception("psutil error")

            cache = MemoryStatsCache()
            limits = MemoryConnectionLimits(
                max_process_memory_percent=80.0,
                memory_stats_cache=cache,
            )

            # Should handle error gracefully and not raise exception
            limits.check_memory_limits()

    def test_memory_limits_string_representation_with_cache(self):
        """Test string representation with cache."""
        cache = MemoryStatsCache()
        limits = MemoryConnectionLimits(
            max_process_memory_bytes=1024*1024*1024,
            memory_stats_cache=cache,
        )

        str_repr = str(limits)
        assert "MemoryConnectionLimits" in str_repr
        assert "1073741824" in str_repr  # 1024*1024*1024

    def test_memory_limits_repr_with_cache(self):
        """Test repr representation with cache."""
        cache = MemoryStatsCache()
        limits = MemoryConnectionLimits(
            max_process_memory_bytes=1024*1024*1024,
            memory_stats_cache=cache,
        )

        repr_str = repr(limits)
        assert "MemoryConnectionLimits" in repr_str
        assert "max_process_memory_bytes=1073741824" in repr_str
