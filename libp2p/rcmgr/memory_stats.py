"""
Memory statistics caching for resource management.

This module implements memory statistics caching and monitoring to support
memory-based connection limits, matching the Rust libp2p-memory-connection-limits
behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
import threading
import time

import psutil


@dataclass
class MemoryStats:
    """Memory statistics snapshot."""

    # Process memory
    process_memory_bytes: int
    process_memory_percent: float

    # System memory
    system_memory_total: int
    system_memory_available: int
    system_memory_percent: float

    # Timestamp
    timestamp: float

    @property
    def process_memory_mb(self) -> float:
        """Process memory in megabytes."""
        return self.process_memory_bytes / (1024 * 1024)

    @property
    def system_memory_total_gb(self) -> float:
        """System total memory in gigabytes."""
        return self.system_memory_total / (1024 * 1024 * 1024)

    @property
    def system_memory_available_gb(self) -> float:
        """System available memory in gigabytes."""
        return self.system_memory_available / (1024 * 1024 * 1024)


class MemoryStatsCache:
    """
    Cache and monitor memory statistics for resource management.

    This class provides memory statistics caching and monitoring to support
    memory-based connection limits, matching the Rust libp2p-memory-connection-limits
    behavior.
    """

    def __init__(self, cache_duration: float = 1.0):
        """
        Initialize memory stats cache.

        Args:
            cache_duration: Duration in seconds to cache memory stats

        """
        self.cache_duration = cache_duration
        self._lock = threading.RLock()
        self._cached_stats: MemoryStats | None = None
        self._last_update: float = 0.0
        self._cached_summary: dict[str, object] | None = None

        # Process object for monitoring
        try:
            self._process: psutil.Process = psutil.Process()
        except Exception:
            # If psutil fails, we'll handle it in get_memory_stats
            self._process = None  # type: ignore

    def get_memory_stats(self, force_refresh: bool = False) -> MemoryStats:
        """
        Get current memory statistics.

        Args:
            force_refresh: Force refresh of cached statistics

        Returns:
            MemoryStats: Current memory statistics

        """
        with self._lock:
            current_time = time.time()

            # Return cached stats if still valid
            if (
                not force_refresh
                and self._cached_stats is not None
                and (current_time - self._last_update) < self.cache_duration
            ):
                return self._cached_stats

            # Refresh memory statistics
            self._cached_stats = self._collect_memory_stats()
            self._last_update = current_time

            return self._cached_stats

    def _collect_memory_stats(self) -> MemoryStats:
        """
        Collect current memory statistics.

        Returns:
            MemoryStats: Current memory statistics

        """
        if self._process is None:
            # Return default values if psutil failed
            return MemoryStats(
                process_memory_bytes=0,
                process_memory_percent=0.0,
                system_memory_total=0,
                system_memory_available=0,
                system_memory_percent=0.0,
                timestamp=time.time(),
            )

        # Process memory
        process_memory_info = self._process.memory_info()  # type: ignore
        process_memory_bytes = process_memory_info.rss  # Resident Set Size

        # System memory
        system_memory = psutil.virtual_memory()

        return MemoryStats(
            process_memory_bytes=process_memory_bytes,
            process_memory_percent=self._process.memory_percent(),  # type: ignore
            system_memory_total=system_memory.total,
            system_memory_available=system_memory.available,
            system_memory_percent=system_memory.percent,
            timestamp=time.time(),
        )

    def get_process_memory_bytes(self, force_refresh: bool = False) -> int:
        """
        Get current process memory usage in bytes.

        Args:
            force_refresh: Force refresh of cached statistics

        Returns:
            int: Process memory usage in bytes

        """
        stats = self.get_memory_stats(force_refresh)
        return stats.process_memory_bytes

    def get_process_memory_percent(self, force_refresh: bool = False) -> float:
        """
        Get current process memory usage as percentage of system memory.

        Args:
            force_refresh: Force refresh of cached statistics

        Returns:
            float: Process memory usage percentage

        """
        stats = self.get_memory_stats(force_refresh)
        return stats.process_memory_percent

    def get_system_memory_total(self, force_refresh: bool = False) -> int:
        """
        Get total system memory in bytes.

        Args:
            force_refresh: Force refresh of cached statistics

        Returns:
            int: Total system memory in bytes

        """
        stats = self.get_memory_stats(force_refresh)
        return stats.system_memory_total

    def get_system_memory_available(self, force_refresh: bool = False) -> int:
        """
        Get available system memory in bytes.

        Args:
            force_refresh: Force refresh of cached statistics

        Returns:
            int: Available system memory in bytes

        """
        stats = self.get_memory_stats(force_refresh)
        return stats.system_memory_available

    def get_system_memory_percent(self, force_refresh: bool = False) -> float:
        """
        Get system memory usage percentage.

        Args:
            force_refresh: Force refresh of cached statistics

        Returns:
            float: System memory usage percentage

        """
        stats = self.get_memory_stats(force_refresh)
        return stats.system_memory_percent

    def is_memory_available(
        self, required_bytes: int, force_refresh: bool = False
    ) -> bool:
        """
        Check if required memory is available.

        Args:
            required_bytes: Required memory in bytes
            force_refresh: Force refresh of cached statistics

        Returns:
            bool: True if memory is available, False otherwise

        """
        stats = self.get_memory_stats(force_refresh)
        return stats.system_memory_available >= required_bytes

    def get_memory_summary(self, force_refresh: bool = False) -> dict[str, object]:
        """
        Get comprehensive memory summary.

        Args:
            force_refresh: Force refresh of cached statistics

        Returns:
            dict: Memory summary with all statistics

        """
        with self._lock:
            current_time = time.time()

            # Check if we should use cached data
            if (
                not force_refresh
                and self._cached_summary is not None
                and (current_time - self._last_update) < self.cache_duration
            ):
                # Return cached summary
                return self._cached_summary
            else:
                # Get fresh data
                stats = self.get_memory_stats(force_refresh)
                cache_age = current_time - stats.timestamp

                summary: dict[str, object] = {
                    "process_memory_bytes": stats.process_memory_bytes,
                    "process_memory_mb": stats.process_memory_mb,
                    "process_memory_percent": stats.process_memory_percent,
                    "system_memory_total": stats.system_memory_total,
                    "system_memory_total_gb": stats.system_memory_total_gb,
                    "system_memory_available": stats.system_memory_available,
                    "system_memory_available_gb": stats.system_memory_available_gb,
                    "system_memory_percent": stats.system_memory_percent,
                    "timestamp": stats.timestamp,
                    "cache_age": cache_age,
                }

                # Cache the summary
                self._cached_summary = summary
                return summary

    def clear_cache(self) -> None:
        """Clear cached memory statistics."""
        with self._lock:
            self._cached_stats = None
            self._cached_summary = None
            self._last_update = 0.0

    def __str__(self) -> str:
        """String representation of memory stats cache."""
        try:
            stats = self.get_memory_stats()
            return (
                f"MemoryStatsCache("
                f"process_memory={stats.process_memory_mb:.1f}MB, "
                f"system_memory={stats.system_memory_available_gb:.1f}GB "
                f"available)"
            )
        except Exception:
            return "MemoryStatsCache(unknown)"

    def __eq__(self, other: object) -> bool:
        """Compare memory stats cache based on configuration."""
        if not isinstance(other, MemoryStatsCache):
            return False
        return self.cache_duration == other.cache_duration

    def __hash__(self) -> int:
        """Hash memory stats cache based on configuration."""
        return hash(self.cache_duration)

    def __copy__(self) -> MemoryStatsCache:
        """Create a shallow copy of the memory stats cache."""
        return MemoryStatsCache(cache_duration=self.cache_duration)

    def __deepcopy__(self, memo: dict[str, object]) -> MemoryStatsCache:
        """Create a deep copy of the memory stats cache."""
        return MemoryStatsCache(cache_duration=self.cache_duration)


# Global memory stats cache instance
_global_memory_cache: MemoryStatsCache | None = None


def get_global_memory_cache() -> MemoryStatsCache:
    """
    Get the global memory stats cache instance.

    Returns:
        MemoryStatsCache: Global memory stats cache

    """
    global _global_memory_cache
    if _global_memory_cache is None:
        _global_memory_cache = MemoryStatsCache()
    return _global_memory_cache


def set_global_memory_cache(cache: MemoryStatsCache) -> None:
    """
    Set the global memory stats cache instance.

    Args:
        cache: Memory stats cache to use globally

    """
    global _global_memory_cache
    _global_memory_cache = cache
