"""
Memory-based connection limits for resource management.

This module implements memory-based connection limits matching the Rust
libp2p-memory-connection-limits behavior, denying connections when memory
usage exceeds configured thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging

from .exceptions import ResourceLimitExceeded
from .memory_stats import MemoryStats, MemoryStatsCache, get_global_memory_cache

logger = logging.getLogger(__name__)


@dataclass
class MemoryConnectionLimits:
    """
    Memory-based connection limits configuration.

    This class provides memory-based connection limits matching the Rust
    libp2p-memory-connection-limits behavior, denying connections when
    memory usage exceeds configured thresholds.
    """

    max_process_memory_bytes: int | None = None
    max_process_memory_percent: float | None = None
    max_system_memory_percent: float | None = None
    memory_stats_cache: MemoryStatsCache | None = None

    def __post_init__(self) -> None:
        """Initialize memory stats cache if not provided."""
        if self.memory_stats_cache is None:
            self.memory_stats_cache = get_global_memory_cache()

    def with_max_process_memory_bytes(self, max_bytes: int) -> MemoryConnectionLimits:
        """
        Configure maximum process memory usage in bytes.

        Args:
            max_bytes: Maximum process memory in bytes

        Returns:
            Self for method chaining

        """
        self.max_process_memory_bytes = max_bytes
        return self

    def with_max_process_memory_percent(
        self, max_percent: float
    ) -> MemoryConnectionLimits:
        """
        Configure maximum process memory usage as percentage of system memory.

        Args:
            max_percent: Maximum process memory percentage (0.0-100.0)

        Returns:
            Self for method chaining

        """
        if not 0.0 <= max_percent <= 100.0:
            raise ValueError(
                f"Memory percentage must be between 0.0 and 100.0, got {max_percent}"
            )
        self.max_process_memory_percent = max_percent
        return self

    def with_max_system_memory_percent(
        self, max_percent: float
    ) -> MemoryConnectionLimits:
        """
        Configure maximum system memory usage percentage.

        Args:
            max_percent: Maximum system memory percentage (0.0-100.0)

        Returns:
            Self for method chaining

        """
        if not 0.0 <= max_percent <= 100.0:
            raise ValueError(
                f"Memory percentage must be between 0.0 and 100.0, got {max_percent}"
            )
        self.max_system_memory_percent = max_percent
        return self

    def with_memory_stats_cache(
        self, cache: MemoryStatsCache
    ) -> MemoryConnectionLimits:
        """
        Configure memory statistics cache.

        Args:
            cache: Memory stats cache to use

        Returns:
            Self for method chaining

        """
        self.memory_stats_cache = cache
        return self

    def check_memory_limits(self, force_refresh: bool = False) -> None:
        """
        Check if current memory usage exceeds configured limits.

        Args:
            force_refresh: Force refresh of memory statistics

        Raises:
            ResourceLimitExceeded: If memory limits are exceeded

        """
        if not self._has_limits_configured():
            return

        try:
            if self.memory_stats_cache is None:
                return
            stats = self.memory_stats_cache.get_memory_stats(
                force_refresh=force_refresh
            )

            # Check process memory bytes limit
            if self.max_process_memory_bytes is not None:
                if stats.process_memory_bytes >= self.max_process_memory_bytes:
                    raise ResourceLimitExceeded(
                        message=f"Process memory limit exceeded: "
                        f"current={stats.process_memory_bytes} bytes, "
                        f"limit={self.max_process_memory_bytes} bytes"
                    )

            # Check process memory percentage limit
            if self.max_process_memory_percent is not None:
                if stats.process_memory_percent >= self.max_process_memory_percent:
                    raise ResourceLimitExceeded(
                        message=f"Process memory percentage limit exceeded: "
                        f"current={stats.process_memory_percent:.2f}%, "
                        f"limit={self.max_process_memory_percent:.2f}%"
                    )

            # Check system memory percentage limit
            if self.max_system_memory_percent is not None:
                if stats.system_memory_percent >= self.max_system_memory_percent:
                    raise ResourceLimitExceeded(
                        message=f"System memory percentage limit exceeded: "
                        f"current={stats.system_memory_percent:.2f}%, "
                        f"limit={self.max_system_memory_percent:.2f}%"
                    )

            logger.debug(
                f"Memory limits check passed: "
                f"process={stats.process_memory_bytes} bytes "
                f"({stats.process_memory_percent:.2f}%), "
                f"system={stats.system_memory_percent:.2f}%"
            )

        except Exception as e:
            if isinstance(e, ResourceLimitExceeded):
                raise
            logger.warning(f"Failed to check memory limits: {e}")
            # Don't raise on monitoring failures, allow connection
            # This matches Rust behavior where monitoring failures don't block
            # connections

    def _has_limits_configured(self) -> bool:
        """
        Check if any memory limits are configured.

        Returns:
            bool: True if any limits are configured, False otherwise

        """
        return (
            self.max_process_memory_bytes is not None
            or self.max_process_memory_percent is not None
            or self.max_system_memory_percent is not None
        )

    def get_current_memory_stats(self, force_refresh: bool = False) -> MemoryStats:
        """
        Get current memory statistics.

        Args:
            force_refresh: Force refresh of memory statistics

        Returns:
            MemoryStats: Current memory statistics

        """
        if self.memory_stats_cache is None:
            raise RuntimeError("Memory stats cache not configured")
        return self.memory_stats_cache.get_memory_stats(force_refresh)

    def get_limits_summary(self) -> dict[str, object]:
        """
        Get memory limits configuration summary.

        Returns:
            dict[str, object]: Memory limits configuration

        """
        return {
            "max_process_memory_bytes": self.max_process_memory_bytes,
            "max_process_memory_percent": self.max_process_memory_percent,
            "max_system_memory_percent": self.max_system_memory_percent,
            "has_limits_configured": self._has_limits_configured(),
        }

    def get_memory_summary(self, force_refresh: bool = False) -> dict[str, object]:
        """
        Get comprehensive memory summary including current usage.

        Args:
            force_refresh: Force refresh of memory statistics

        Returns:
            dict: Memory summary with limits and current usage

        """
        limits = self.get_limits_summary()
        if self.memory_stats_cache is None:
            return limits

        try:
            current = self.memory_stats_cache.get_memory_summary(
                force_refresh=force_refresh
            )
            return {
                **limits,
                "current": current,
            }
        except Exception as e:
            logger.warning(f"Failed to get memory summary: {e}")
            return limits

    def __str__(self) -> str:
        """String representation of memory connection limits."""
        limits = self.get_limits_summary()
        limit_strs = []

        if limits["max_process_memory_bytes"] is not None:
            limit_strs.append(f"process_bytes={limits['max_process_memory_bytes']}")

        if limits["max_process_memory_percent"] is not None:
            limit_strs.append(
                f"process_percent={limits['max_process_memory_percent']:.1f}%"
            )

        if limits["max_system_memory_percent"] is not None:
            limit_strs.append(
                f"system_percent={limits['max_system_memory_percent']:.1f}%"
            )

        if not limit_strs:
            return "MemoryConnectionLimits(no_limits)"

        return f"MemoryConnectionLimits({', '.join(limit_strs)})"

    def __eq__(self, other: object) -> bool:
        """Compare memory connection limits based on configuration."""
        if not isinstance(other, MemoryConnectionLimits):
            return False
        return (
            self.max_process_memory_bytes == other.max_process_memory_bytes
            and self.max_process_memory_percent == other.max_process_memory_percent
            and self.max_system_memory_percent == other.max_system_memory_percent
            # Don't compare cache as it's not part of the configuration
        )

    def __hash__(self) -> int:
        """Hash memory connection limits based on configuration."""
        return hash(
            (
                self.max_process_memory_bytes,
                self.max_process_memory_percent,
                self.max_system_memory_percent,
                # Don't include cache in hash as it's not part of the configuration
            )
        )

    def __deepcopy__(self, memo: dict[str, object]) -> MemoryConnectionLimits:
        """Deep copy memory connection limits, creating new cache."""
        from .memory_stats import MemoryStatsCache

        return MemoryConnectionLimits(
            max_process_memory_bytes=self.max_process_memory_bytes,
            max_process_memory_percent=self.max_process_memory_percent,
            max_system_memory_percent=self.max_system_memory_percent,
            memory_stats_cache=MemoryStatsCache() if self.memory_stats_cache else None,
        )


def new_memory_connection_limits() -> MemoryConnectionLimits:
    """
    Create new memory connection limits with no limits configured.

    Returns:
        MemoryConnectionLimits: New instance with no limits

    """
    return MemoryConnectionLimits()


def new_memory_connection_limits_with_defaults() -> MemoryConnectionLimits:
    """
    Create new memory connection limits with sensible defaults.

    These defaults are based on typical libp2p usage patterns and provide
    reasonable memory limits for most applications.

    Returns:
        MemoryConnectionLimits: New instance with default limits

    """
    return MemoryConnectionLimits(
        max_process_memory_percent=80.0,  # 80% of system memory
        max_system_memory_percent=90.0,  # 90% system memory usage
    )


def new_memory_connection_limits_with_bytes(max_bytes: int) -> MemoryConnectionLimits:
    """
    Create new memory connection limits with absolute byte limit.

    Args:
        max_bytes: Maximum process memory in bytes

    Returns:
        MemoryConnectionLimits: New instance with byte limit

    """
    return MemoryConnectionLimits(max_process_memory_bytes=max_bytes)


def new_memory_connection_limits_with_percent(
    max_percent: float,
) -> MemoryConnectionLimits:
    """
    Create new memory connection limits with percentage limit.

    Args:
        max_percent: Maximum process memory percentage (0.0-100.0)

    Returns:
        MemoryConnectionLimits: New instance with percentage limit

    """
    return MemoryConnectionLimits(max_process_memory_percent=max_percent)
