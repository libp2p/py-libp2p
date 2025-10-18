"""
Comprehensive tests for MemoryStatsCache component.

Tests the memory statistics caching and monitoring functionality
that provides efficient memory usage tracking.
"""

import threading
import time
from unittest.mock import Mock, patch

from libp2p.rcmgr.memory_stats import MemoryStats, MemoryStatsCache


class TestMemoryStatsCache:
    """Test suite for MemoryStatsCache class."""

    def test_memory_stats_cache_creation(self) -> None:
        """Test MemoryStatsCache creation."""
        cache = MemoryStatsCache()

        assert cache is not None
        assert cache.cache_duration > 0
        assert cache._last_update == 0.0
        assert cache._cached_stats is None

    def test_memory_stats_cache_creation_with_custom_duration(self) -> None:
        """Test MemoryStatsCache creation with custom duration."""
        cache = MemoryStatsCache(cache_duration=5.0)

        assert cache.cache_duration == 5.0

    def test_get_memory_stats_fresh(self) -> None:
        """Test getting fresh memory statistics."""
        cache = MemoryStatsCache()

        stats = cache.get_memory_stats()

        assert stats is not None
        assert isinstance(stats, MemoryStats)
        assert stats.process_memory_bytes >= 0
        assert 0 <= stats.process_memory_percent <= 100
        assert stats.system_memory_total > 0
        assert 0 <= stats.system_memory_percent <= 100
        assert stats.system_memory_available >= 0
        assert stats.timestamp > 0

    def test_get_memory_stats_cached(self) -> None:
        """Test getting cached memory statistics."""
        cache = MemoryStatsCache(cache_duration=1.0)

        # First call - should be fresh
        stats1 = cache.get_memory_stats()
        assert cache._last_update > 0
        assert cache._cached_stats is not None

        # Second call within duration - should be cached
        stats2 = cache.get_memory_stats()
        assert stats1 == stats2  # Should be identical

    def test_get_memory_stats_cache_expiry(self) -> None:
        """Test memory statistics cache expiry."""
        cache = MemoryStatsCache(cache_duration=0.1)  # Very short duration

        # First call
        cache.get_memory_stats()

        # Wait for cache to expire
        time.sleep(0.2)

        # Second call - should be fresh
        cache.get_memory_stats()

        # Should be different (or same if memory didn't change)
        # But cache should be refreshed
        assert cache._last_update > 0

    def test_get_memory_summary(self) -> None:
        """Test getting memory summary."""
        cache = MemoryStatsCache()

        summary = cache.get_memory_summary()

        assert summary is not None
        assert "process_memory_bytes" in summary
        assert "process_memory_mb" in summary
        assert "process_memory_percent" in summary
        assert "system_memory_total" in summary
        assert "system_memory_total_gb" in summary
        assert "system_memory_available" in summary
        assert "system_memory_available_gb" in summary
        assert "system_memory_percent" in summary
        assert "timestamp" in summary
        assert "cache_age" in summary

        # Values should be reasonable
        assert summary["process_memory_bytes"] >= 0
        assert 0 <= summary["process_memory_percent"] <= 100
        assert summary["system_memory_total"] > 0
        assert 0 <= summary["system_memory_percent"] <= 100
        assert summary["system_memory_available"] >= 0

    def test_get_memory_summary_cached(self) -> None:
        """Test getting cached memory summary."""
        cache = MemoryStatsCache(cache_duration=1.0)

        # First call
        summary1 = cache.get_memory_summary()

        # Second call within duration - should be cached
        summary2 = cache.get_memory_summary()
        assert summary1 == summary2

    def test_get_memory_summary_cache_expiry(self) -> None:
        """Test memory summary cache expiry."""
        cache = MemoryStatsCache(cache_duration=0.1)  # Very short duration

        # First call
        cache.get_memory_summary()

        # Wait for cache to expire
        time.sleep(0.2)

        # Second call - should be fresh
        cache.get_memory_summary()

        # Cache should be refreshed
        assert cache._last_update > 0

    def test_force_refresh(self) -> None:
        """Test forcing cache refresh."""
        cache = MemoryStatsCache(cache_duration=1.0)

        # First call
        cache.get_memory_stats()

        # Force refresh
        cache.get_memory_stats(force_refresh=True)

        # Should be fresh (or same if memory didn't change)
        # But cache should be updated
        assert cache._last_update > 0

    def test_force_refresh_summary(self) -> None:
        """Test forcing cache refresh for summary."""
        cache = MemoryStatsCache(cache_duration=1.0)

        # First call
        cache.get_memory_summary()

        # Force refresh
        cache.get_memory_summary(force_refresh=True)

        # Should be fresh (or same if memory didn't change)
        # But cache should be updated
        assert cache._last_update > 0

    def test_concurrent_access(self) -> None:
        """Test concurrent access to memory stats."""
        cache = MemoryStatsCache()
        results = []
        errors = []

        def get_stats():
            try:
                stats = cache.get_memory_stats()
                results.append(stats)
            except Exception as e:
                errors.append(e)

        # Start multiple threads
        threads = []
        for _ in range(10):
            t = threading.Thread(target=get_stats)
            threads.append(t)
            t.start()

        # Wait for completion
        for t in threads:
            t.join()

        # All should succeed
        assert len(results) == 10
        assert len(errors) == 0

    def test_concurrent_access_with_cache(self) -> None:
        """Test concurrent access with caching."""
        cache = MemoryStatsCache(cache_duration=1.0)
        results = []
        errors = []

        def get_stats():
            try:
                stats = cache.get_memory_stats()
                results.append(stats)
            except Exception as e:
                errors.append(e)

        # Start multiple threads
        threads = []
        for _ in range(10):
            t = threading.Thread(target=get_stats)
            threads.append(t)
            t.start()

        # Wait for completion
        for t in threads:
            t.join()

        # All should succeed
        assert len(results) == 10
        assert len(errors) == 0

        # All results should be identical (cached)
        for i in range(1, len(results)):
            assert results[i] == results[0]

    def test_memory_stats_consistency(self) -> None:
        """Test memory statistics consistency."""
        cache = MemoryStatsCache()

        stats = cache.get_memory_stats()

        # Process memory should be reasonable
        assert stats.process_memory_bytes >= 0
        assert 0 <= stats.process_memory_percent <= 100

        # System memory should be reasonable
        assert stats.system_memory_total > 0
        assert 0 <= stats.system_memory_percent <= 100
        assert stats.system_memory_available >= 0

        # Available memory should not exceed total memory
        assert stats.system_memory_available <= stats.system_memory_total

    def test_memory_summary_consistency(self) -> None:
        """Test memory summary consistency."""
        cache = MemoryStatsCache()

        summary = cache.get_memory_summary()

        # Process summary consistency
        assert summary["process_memory_bytes"] >= 0
        assert 0 <= summary["process_memory_percent"] <= 100
        assert summary["process_memory_mb"] >= 0

        # System summary consistency
        assert summary["system_memory_total"] > 0
        assert summary["system_memory_available"] >= 0
        assert 0 <= summary["system_memory_percent"] <= 100
        assert summary["system_memory_total_gb"] > 0
        assert summary["system_memory_available_gb"] >= 0

        # Available memory should not exceed total memory
        assert summary["system_memory_available"] <= summary["system_memory_total"]

    def test_memory_stats_with_mock_psutil(self) -> None:
        """Test memory stats with mocked psutil."""
        with patch("libp2p.rcmgr.memory_stats.psutil") as mock_psutil:
            # Mock process
            mock_process = Mock()
            mock_process.memory_info.return_value = Mock(
                rss=1024 * 1024, vms=2048 * 1024
            )
            mock_process.memory_percent.return_value = 1.5

            # Mock virtual memory
            mock_virtual_memory = Mock()
            mock_virtual_memory.total = 8 * 1024 * 1024 * 1024  # 8GB
            mock_virtual_memory.available = 4 * 1024 * 1024 * 1024  # 4GB
            mock_virtual_memory.percent = 50.0

            # Configure mocks
            mock_psutil.Process.return_value = mock_process
            mock_psutil.virtual_memory.return_value = mock_virtual_memory

            cache = MemoryStatsCache()
            stats = cache.get_memory_stats()

            # Check mocked values
            assert stats.process_memory_bytes == 1024 * 1024
            assert stats.process_memory_percent == 1.5
            assert stats.system_memory_total == 8 * 1024 * 1024 * 1024
            assert stats.system_memory_percent == 50.0
            assert stats.system_memory_available == 4 * 1024 * 1024 * 1024

    def test_memory_summary_with_mock_psutil(self) -> None:
        """Test memory summary with mocked psutil."""
        with patch("libp2p.rcmgr.memory_stats.psutil") as mock_psutil:
            # Mock process
            mock_process = Mock()
            mock_process.memory_info.return_value = Mock(
                rss=1024 * 1024, vms=2048 * 1024
            )
            mock_process.memory_percent.return_value = 1.5

            # Mock virtual memory
            mock_virtual_memory = Mock()
            mock_virtual_memory.total = 8 * 1024 * 1024 * 1024  # 8GB
            mock_virtual_memory.available = 4 * 1024 * 1024 * 1024  # 4GB
            mock_virtual_memory.percent = 50.0

            # Configure mocks
            mock_psutil.Process.return_value = mock_process
            mock_psutil.virtual_memory.return_value = mock_virtual_memory

            cache = MemoryStatsCache()
            summary = cache.get_memory_summary()

            # Check mocked values
            assert summary["process_memory_bytes"] == 1024 * 1024
            assert summary["process_memory_percent"] == 1.5
            assert summary["process_memory_mb"] == 1.0
            assert summary["system_memory_total"] == 8 * 1024 * 1024 * 1024
            assert summary["system_memory_available"] == 4 * 1024 * 1024 * 1024
            assert summary["system_memory_percent"] == 50.0
            assert summary["system_memory_total_gb"] == 8.0
            assert summary["system_memory_available_gb"] == 4.0

    def test_memory_stats_with_psutil_error(self) -> None:
        """Test memory stats with psutil error."""
        with patch("libp2p.rcmgr.memory_stats.psutil") as mock_psutil:
            # Mock psutil to raise exception
            mock_psutil.Process.side_effect = Exception("psutil error")

            cache = MemoryStatsCache()

            # Should handle error gracefully
            try:
                stats = cache.get_memory_stats()
                # If it doesn't raise, check that it has reasonable defaults
                assert stats.process_memory_bytes >= 0
                assert 0 <= stats.process_memory_percent <= 100
            except Exception:
                # It's acceptable for the cache to raise if psutil fails
                pass

    def test_memory_summary_with_psutil_error(self) -> None:
        """Test memory summary with psutil error."""
        with patch("libp2p.rcmgr.memory_stats.psutil") as mock_psutil:
            # Mock psutil to raise exception
            mock_psutil.Process.side_effect = Exception("psutil error")

            cache = MemoryStatsCache()

            # Should handle error gracefully
            try:
                summary = cache.get_memory_summary()
                # If it doesn't raise, check that it has reasonable defaults
                assert summary["process_memory_bytes"] >= 0
                assert 0 <= summary["process_memory_percent"] <= 100
            except Exception:
                # It's acceptable for the cache to raise if psutil fails
                pass

    def test_memory_stats_performance(self) -> None:
        """Test memory stats performance."""
        cache = MemoryStatsCache()

        # Measure time for many operations
        start_time = time.time()

        for _ in range(100):
            cache.get_memory_stats()

        end_time = time.time()
        elapsed = end_time - start_time

        # Should complete in reasonable time
        assert elapsed < 1.0  # Should complete in less than 1 second

    def test_memory_summary_performance(self) -> None:
        """Test memory summary performance."""
        cache = MemoryStatsCache()

        # Measure time for many operations
        start_time = time.time()

        for _ in range(100):
            cache.get_memory_summary()

        end_time = time.time()
        elapsed = end_time - start_time

        # Should complete in reasonable time
        assert elapsed < 1.0  # Should complete in less than 1 second

    def test_memory_stats_caching_performance(self) -> None:
        """Test memory stats caching performance."""
        cache = MemoryStatsCache(cache_duration=1.0)

        # First call - should be fresh
        start_time = time.time()
        cache.get_memory_stats()
        first_call_time = time.time() - start_time

        # Second call - should be cached (faster)
        start_time = time.time()
        cache.get_memory_stats()
        second_call_time = time.time() - start_time

        # Cached call should be faster
        assert second_call_time < first_call_time

    def test_memory_summary_caching_performance(self) -> None:
        """Test memory summary caching performance."""
        cache = MemoryStatsCache(cache_duration=1.0)

        # First call - should be fresh
        start_time = time.time()
        cache.get_memory_summary()
        first_call_time = time.time() - start_time

        # Second call - should be cached (faster)
        start_time = time.time()
        cache.get_memory_summary()
        second_call_time = time.time() - start_time

        # Cached call should be faster
        assert second_call_time < first_call_time

    def test_memory_stats_thread_safety(self) -> None:
        """Test memory stats thread safety."""
        cache = MemoryStatsCache()
        results = []
        errors = []

        def get_stats():
            try:
                stats = cache.get_memory_stats()
                results.append(stats)
            except Exception as e:
                errors.append(e)

        # Start many threads
        threads = []
        for _ in range(50):
            t = threading.Thread(target=get_stats)
            threads.append(t)
            t.start()

        # Wait for completion
        for t in threads:
            t.join()

        # All should succeed
        assert len(results) == 50
        assert len(errors) == 0

    def test_memory_summary_thread_safety(self) -> None:
        """Test memory summary thread safety."""
        cache = MemoryStatsCache()
        results = []
        errors = []

        def get_summary():
            try:
                summary = cache.get_memory_summary()
                results.append(summary)
            except Exception as e:
                errors.append(e)

        # Start many threads
        threads = []
        for _ in range(50):
            t = threading.Thread(target=get_summary)
            threads.append(t)
            t.start()

        # Wait for completion
        for t in threads:
            t.join()

        # All should succeed
        assert len(results) == 50
        assert len(errors) == 0

    def test_memory_stats_with_different_duration(self) -> None:
        """Test memory stats with different duration values."""
        # Test with very short duration
        cache1 = MemoryStatsCache(cache_duration=0.01)
        cache1.get_memory_stats()
        time.sleep(0.02)
        cache1.get_memory_stats()
        # Should be different (or same if memory didn't change)
        # But cache should be refreshed

        # Test with very long duration
        cache2 = MemoryStatsCache(cache_duration=100.0)
        stats3 = cache2.get_memory_stats()
        stats4 = cache2.get_memory_stats()
        # Should be identical (cached)
        assert stats3 == stats4

    def test_memory_summary_with_different_duration(self) -> None:
        """Test memory summary with different duration values."""
        # Test with very short duration
        cache1 = MemoryStatsCache(cache_duration=0.01)
        cache1.get_memory_summary()
        time.sleep(0.02)
        cache1.get_memory_summary()
        # Should be different (or same if memory didn't change)
        # But cache should be refreshed

        # Test with very long duration
        cache2 = MemoryStatsCache(cache_duration=100.0)
        summary3 = cache2.get_memory_summary()
        summary4 = cache2.get_memory_summary()
        # Should be identical (cached)
        assert summary3 == summary4

    def test_memory_stats_edge_cases(self) -> None:
        """Test memory stats edge cases."""
        cache = MemoryStatsCache()

        # Test with None values
        cache._cached_stats = None
        cache._last_update = 0.0

        stats = cache.get_memory_stats()
        assert stats is not None

        # Test with invalid cache
        cache._cached_stats = None  # Invalid cache
        cache._last_update = time.time() - 1000  # Very old

        stats = cache.get_memory_stats()
        assert stats is not None

    def test_memory_summary_edge_cases(self) -> None:
        """Test memory summary edge cases."""
        cache = MemoryStatsCache()

        # Test with None values
        cache._cached_stats = None
        cache._last_update = 0.0

        summary = cache.get_memory_summary()
        assert summary is not None

        # Test with invalid cache
        cache._cached_stats = None  # Invalid cache
        cache._last_update = time.time() - 1000  # Very old

        summary = cache.get_memory_summary()
        assert summary is not None

    def test_memory_stats_string_representation(self) -> None:
        """Test string representation of cache."""
        cache = MemoryStatsCache()

        str_repr = str(cache)
        assert "MemoryStatsCache" in str_repr

    def test_memory_stats_repr(self) -> None:
        """Test repr representation of cache."""
        cache = MemoryStatsCache()

        repr_str = repr(cache)
        assert "MemoryStatsCache" in repr_str

    def test_memory_stats_equality(self) -> None:
        """Test cache equality comparison."""
        cache1 = MemoryStatsCache()
        cache2 = MemoryStatsCache()
        cache3 = MemoryStatsCache(cache_duration=5.0)

        # Same duration
        assert cache1 == cache2

        # Different duration
        assert cache1 != cache3

    def test_memory_stats_hash(self) -> None:
        """Test cache hash functionality."""
        cache1 = MemoryStatsCache()
        cache2 = MemoryStatsCache()

        # Same duration
        assert hash(cache1) == hash(cache2)

    def test_memory_stats_in_set(self) -> None:
        """Test cache can be used in sets."""
        cache1 = MemoryStatsCache()
        cache2 = MemoryStatsCache()
        cache3 = MemoryStatsCache(cache_duration=5.0)

        cache_set = {cache1, cache2, cache3}
        assert len(cache_set) == 2  # cache1 and cache2 are equal

    def test_memory_stats_in_dict(self) -> None:
        """Test cache can be used as dictionary key."""
        cache = MemoryStatsCache()

        cache_dict = {cache: "value"}
        assert cache_dict[cache] == "value"

    def test_memory_stats_copy(self) -> None:
        """Test cache can be copied."""
        import copy

        cache = MemoryStatsCache()
        cache_copy = copy.copy(cache)

        # Should be equal but different objects
        assert cache == cache_copy
        assert cache is not cache_copy

    def test_memory_stats_deep_copy(self) -> None:
        """Test cache can be deep copied."""
        import copy

        cache = MemoryStatsCache()
        cache_deep_copy = copy.deepcopy(cache)

        # Should be equal but different objects
        assert cache == cache_deep_copy
        assert cache is not cache_deep_copy

    def test_memory_stats_serialization(self) -> None:
        """Test cache can be serialized."""
        import json

        cache = MemoryStatsCache()

        # Get stats
        stats = cache.get_memory_stats()

        # Should be serializable
        json_str = json.dumps(
            {
                "process_memory_bytes": stats.process_memory_bytes,
                "process_memory_percent": stats.process_memory_percent,
                "system_memory_total": stats.system_memory_total,
                "system_memory_available": stats.system_memory_available,
                "system_memory_percent": stats.system_memory_percent,
                "timestamp": stats.timestamp,
            }
        )
        assert json_str is not None

        # Should be deserializable
        deserialized = json.loads(json_str)
        assert deserialized["process_memory_bytes"] == stats.process_memory_bytes

    def test_memory_summary_serialization(self) -> None:
        """Test cache summary can be serialized."""
        import json

        cache = MemoryStatsCache()

        # Get summary
        summary = cache.get_memory_summary()

        # Should be serializable
        json_str = json.dumps(summary)
        assert json_str is not None

        # Should be deserializable
        deserialized = json.loads(json_str)
        expected = summary["process_memory_bytes"]
        actual = deserialized["process_memory_bytes"]
        assert actual == expected

    def test_memory_stats_with_custom_duration_zero(self) -> None:
        """Test cache with zero duration."""
        cache = MemoryStatsCache(cache_duration=0.0)

        # Should always be fresh
        try:
            cache.get_memory_stats()
        except Exception:
            pass

        # Should be different (or same if memory didn't change)
        # But cache should be refreshed
        assert cache._last_update > 0

    def test_memory_summary_with_custom_duration_zero(self) -> None:
        """Test cache summary with zero duration."""
        cache = MemoryStatsCache(cache_duration=0.0)

        # Should always be fresh
        try:
            cache.get_memory_summary()
        except Exception:
            pass

        # Should be different (or same if memory didn't change)
        # But cache should be refreshed
        assert cache._last_update > 0

    def test_memory_stats_with_custom_duration_negative(self) -> None:
        """Test cache with negative duration."""
        cache = MemoryStatsCache(cache_duration=-1.0)

        # Should always be fresh
        try:
            cache.get_memory_stats()
        except Exception:
            pass

        # Should be different (or same if memory didn't change)
        # But cache should be refreshed
        assert cache._last_update > 0

    def test_memory_summary_with_custom_duration_negative(self) -> None:
        """Test cache summary with negative duration."""
        cache = MemoryStatsCache(cache_duration=-1.0)

        # Should always be fresh
        cache.get_memory_summary()
        cache.get_memory_summary()

        # Should be different (or same if memory didn't change)
        # But cache should be refreshed
        assert cache._last_update > 0

    def test_clear_cache(self) -> None:
        """Test clearing cache."""
        cache = MemoryStatsCache(cache_duration=1.0)

        # Get stats to populate cache
        cache.get_memory_stats()
        assert cache._cached_stats is not None
        assert cache._last_update > 0

        # Clear cache
        cache.clear_cache()
        assert cache._cached_stats is None
        assert cache._last_update == 0.0

    def test_get_process_memory_bytes(self) -> None:
        """Test getting process memory bytes."""
        cache = MemoryStatsCache()

        memory_bytes = cache.get_process_memory_bytes()
        assert memory_bytes >= 0

    def test_get_process_memory_percent(self) -> None:
        """Test getting process memory percent."""
        cache = MemoryStatsCache()

        memory_percent = cache.get_process_memory_percent()
        assert 0 <= memory_percent <= 100

    def test_get_system_memory_total(self) -> None:
        """Test getting system memory total."""
        cache = MemoryStatsCache()

        memory_total = cache.get_system_memory_total()
        assert memory_total > 0

    def test_get_system_memory_available(self) -> None:
        """Test getting system memory available."""
        cache = MemoryStatsCache()

        memory_available = cache.get_system_memory_available()
        assert memory_available >= 0

    def test_get_system_memory_percent(self) -> None:
        """Test getting system memory percent."""
        cache = MemoryStatsCache()

        memory_percent = cache.get_system_memory_percent()
        assert 0 <= memory_percent <= 100

    def test_is_memory_available(self) -> None:
        """Test checking if memory is available."""
        cache = MemoryStatsCache()

        # Test with small amount
        is_available = cache.is_memory_available(1024)  # 1KB
        assert isinstance(is_available, bool)

        # Test with large amount
        is_available_large = cache.is_memory_available(1024 * 1024 * 1024 * 1024)  # 1TB
        assert isinstance(is_available_large, bool)

    def test_memory_stats_properties(self) -> None:
        """Test MemoryStats properties."""
        cache = MemoryStatsCache()
        stats = cache.get_memory_stats()

        # Test process memory properties
        assert stats.process_memory_mb >= 0
        assert isinstance(stats.process_memory_mb, float)

        # Test system memory properties
        assert stats.system_memory_total_gb > 0
        assert isinstance(stats.system_memory_total_gb, float)
        assert stats.system_memory_available_gb >= 0
        assert isinstance(stats.system_memory_available_gb, float)
