"""
Graceful degradation for resource exhaustion.

This module provides graceful degradation mechanisms to handle
resource exhaustion scenarios in production environments.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .manager import ResourceLimits, ResourceManager
else:
    # Use string annotations to avoid circular imports
    ResourceManager = Any
    ResourceLimits = Any

logger = logging.getLogger(__name__)


class GracefulDegradation:
    """
    Graceful degradation for resource exhaustion.

    This class implements strategies to handle resource exhaustion
    by gradually reducing resource limits and implementing fallback
    mechanisms.
    """

    def __init__(
        self,
        resource_manager: ResourceManager,
        max_degradation_levels: int = 5,
        degradation_factor: float = 0.2,
    ) -> None:
        """
        Initialize graceful degradation.

        Args:
            resource_manager: The resource manager to degrade
            max_degradation_levels: Maximum number of degradation levels
            degradation_factor: Factor by which to reduce limits per level

        """
        self.rm = resource_manager
        self.max_degradation_levels = max_degradation_levels
        self.degradation_factor = degradation_factor
        self.degradation_level = 0
        self.original_limits: ResourceLimits | None = None
        self._store_original_limits()

    def _store_original_limits(self) -> None:
        """Store original limits for potential recovery."""
        if self.original_limits is None:
            # Import at runtime to avoid circular imports
            from .manager import ResourceLimits

            self.original_limits = ResourceLimits(
                max_connections=self.rm.limits.max_connections,
                max_memory_mb=self.rm.limits.max_memory_bytes // (1024 * 1024),
                max_streams=self.rm.limits.max_streams,
            )

    def handle_resource_exhaustion(self, resource_type: str) -> bool:
        """
        Handle resource exhaustion with graceful degradation.

        Args:
            resource_type: Type of resource that was exhausted

        Returns:
            True if degradation was applied, False if max level reached

        """
        if self.degradation_level >= self.max_degradation_levels:
            logger.warning("Maximum degradation level reached for %s", resource_type)
            return False

        self.degradation_level += 1
        reduction_factor = 1.0 - (self.degradation_level * self.degradation_factor)

        if resource_type == "connections":
            return self._degrade_connections(reduction_factor)
        elif resource_type == "memory":
            return self._degrade_memory(reduction_factor)
        elif resource_type == "streams":
            return self._degrade_streams(reduction_factor)

        return False

    def _degrade_connections(self, reduction_factor: float) -> bool:
        """
        Reduce connection limits gracefully.

        Args:
            reduction_factor: Factor by which to reduce limits

        Returns:
            True if degradation was applied

        """
        if self.original_limits is None:
            return False
        new_limit = int(self.original_limits.max_connections * reduction_factor)
        self.rm.limits.max_connections = max(1, new_limit)

        logger.info(
            "Degraded connection limit to %d (level %d)",
            new_limit,
            self.degradation_level,
        )
        return True

    def _degrade_memory(self, reduction_factor: float) -> bool:
        """
        Reduce memory limits gracefully.

        Args:
            reduction_factor: Factor by which to reduce limits

        Returns:
            True if degradation was applied

        """
        if self.original_limits is None:
            return False
        new_limit = int(self.original_limits.max_memory_bytes * reduction_factor)
        self.rm.limits.max_memory_bytes = max(1024 * 1024, new_limit)  # Min 1MB

        logger.info(
            "Degraded memory limit to %d MB (level %d)",
            new_limit // (1024 * 1024),
            self.degradation_level,
        )
        return True

    def _degrade_streams(self, reduction_factor: float) -> bool:
        """
        Reduce stream limits gracefully.

        Args:
            reduction_factor: Factor by which to reduce limits

        Returns:
            True if degradation was applied

        """
        if self.original_limits is None:
            return False
        new_limit = int(self.original_limits.max_streams * reduction_factor)
        self.rm.limits.max_streams = max(1, new_limit)

        logger.info(
            "Degraded stream limit to %d (level %d)", new_limit, self.degradation_level
        )
        return True

    def recover(self) -> bool:
        """
        Attempt to recover from degradation.

        Returns:
            True if recovery was successful

        """
        if self.degradation_level == 0:
            return True

        # Check if resources are available for recovery
        if self._can_recover():
            self.degradation_level = max(0, self.degradation_level - 1)
            self._apply_current_limits()

            logger.info("Recovered from degradation (level %d)", self.degradation_level)
            return True

        return False

    def _can_recover(self) -> bool:
        """
        Check if system can recover from degradation.

        Returns:
            True if recovery is possible

        """
        # Simple recovery check - can be enhanced with more sophisticated logic
        current_usage = self.rm.get_stats()

        # Check if current usage is below 80% of current limits
        connection_usage = current_usage["connections"] / self.rm.limits.max_connections
        memory_usage = current_usage["memory_bytes"] / self.rm.limits.max_memory_bytes
        stream_usage = current_usage["streams"] / self.rm.limits.max_streams

        return max(connection_usage, memory_usage, stream_usage) < 0.8

    def _apply_current_limits(self) -> None:
        """Apply current degradation level limits."""
        if self.original_limits is None:
            return

        reduction_factor = 1.0 - (self.degradation_level * self.degradation_factor)

        self.rm.limits.max_connections = int(
            self.original_limits.max_connections * reduction_factor
        )
        self.rm.limits.max_memory_bytes = int(
            self.original_limits.max_memory_bytes * reduction_factor
        )
        self.rm.limits.max_streams = int(
            self.original_limits.max_streams * reduction_factor
        )

    def reset(self) -> None:
        """Reset degradation to original limits."""
        if self.original_limits is not None:
            self.rm.limits.max_connections = self.original_limits.max_connections
            self.rm.limits.max_memory_bytes = self.original_limits.max_memory_bytes
            self.rm.limits.max_streams = self.original_limits.max_streams

        self.degradation_level = 0
        logger.info("Reset degradation to original limits")

    def get_stats(self) -> dict[str, Any]:
        """
        Get degradation statistics.

        Returns:
            Dictionary with degradation stats

        """
        return {
            "degradation_level": self.degradation_level,
            "max_degradation_levels": self.max_degradation_levels,
            "degradation_factor": self.degradation_factor,
            "current_limits": {
                "max_connections": self.rm.limits.max_connections,
                "max_memory_bytes": self.rm.limits.max_memory_bytes,
                "max_streams": self.rm.limits.max_streams,
            },
            "original_limits": {
                "max_connections": (
                    self.original_limits.max_connections
                    if self.original_limits
                    else None
                ),
                "max_memory_bytes": (
                    self.original_limits.max_memory_bytes
                    if self.original_limits
                    else None
                ),
                "max_streams": (
                    self.original_limits.max_streams if self.original_limits else None
                ),
            },
        }
