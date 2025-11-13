"""
Optimized resource metrics implementation.

This module provides high-performance metrics collection for the resource manager,
using array-based storage for optimal performance in production environments.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import IntEnum
import threading
import time
from typing import Any


class Direction(IntEnum):
    """Direction enum for resource tracking"""

    INBOUND = 0
    OUTBOUND = 1

    def __str__(self) -> str:
        """Return string representation as numeric value."""
        return str(self.value)


class MetricType(IntEnum):
    """Enumeration of metric types for array indexing."""

    CONNECTIONS_INBOUND = 0
    CONNECTIONS_OUTBOUND = 1
    MEMORY_USAGE = 2
    STREAMS_INBOUND = 3
    STREAMS_OUTBOUND = 4
    CONNECTION_BLOCKS = 5
    MEMORY_BLOCKS = 6
    STREAM_BLOCKS = 7
    PEAK_CONNECTIONS = 8
    PEAK_MEMORY = 9
    PEAK_STREAMS = 10

    def __str__(self) -> str:
        """Return string representation as numeric value."""
        return str(self.value)


@dataclass
class ResourceMetrics:
    """Metrics for a specific resource type."""

    allowed: int = 0
    blocked: int = 0
    current_usage: int = 0
    peak_usage: int = 0
    last_updated: float = field(default_factory=time.time)


class Metrics:
    """
    High-performance metrics with array storage.

    This implementation uses pre-allocated arrays for O(1) access
    to metrics, avoiding dictionary overhead and string operations.
    """

    def __init__(self) -> None:
        """Initialize the optimized metrics collector."""
        # Pre-allocated arrays for O(1) access
        self._counters = [0] * len(MetricType)
        self._gauges = [0.0] * len(MetricType)
        self._lock = threading.RLock()
        self._start_time = time.time()

        # Resource-specific metrics (for backward compatibility)
        self.resource_metrics: dict[str, ResourceMetrics] = defaultdict(ResourceMetrics)

    def increment(self, metric: MetricType, delta: int = 1) -> None:
        """
        Increment a counter metric.

        Args:
            metric: The metric type to increment
            delta: Amount to increment by

        """
        with self._lock:
            self._counters[metric] += delta

    def set_gauge(self, metric: MetricType, value: float) -> None:
        """
        Set a gauge metric value.

        Args:
            metric: The metric type to set
            value: The value to set

        """
        with self._lock:
            self._gauges[metric] = value

    def get_counter(self, metric: MetricType) -> int:
        """
        Get a counter metric value.

        Args:
            metric: The metric type to get

        Returns:
            The counter value

        """
        with self._lock:
            return self._counters[metric]

    def get_gauge(self, metric: MetricType) -> float:
        """
        Get a gauge metric value.

        Args:
            metric: The metric type to get

        Returns:
            The gauge value

        """
        with self._lock:
            return self._gauges[metric]

    def record_connection(self, direction: str, delta: int = 1) -> None:
        """
        Record a connection event.

        Args:
            direction: Connection direction ('inbound' or 'outbound')
            delta: Change in connection count

        """
        if direction == "inbound":
            self.increment(MetricType.CONNECTIONS_INBOUND, delta)
        else:
            self.increment(MetricType.CONNECTIONS_OUTBOUND, delta)

        # Update peak connections
        current_total = self.get_counter(
            MetricType.CONNECTIONS_INBOUND
        ) + self.get_counter(MetricType.CONNECTIONS_OUTBOUND)
        if current_total > self.get_gauge(MetricType.PEAK_CONNECTIONS):
            self.set_gauge(MetricType.PEAK_CONNECTIONS, current_total)

    def record_memory(self, size: int, delta: int = 1) -> None:
        """
        Record a memory event.

        Args:
            size: Memory size in bytes
            delta: Change in memory count

        """
        self.increment(MetricType.MEMORY_USAGE, size * delta)

        # Update peak memory
        current_memory = self.get_counter(MetricType.MEMORY_USAGE)
        if current_memory > self.get_gauge(MetricType.PEAK_MEMORY):
            self.set_gauge(MetricType.PEAK_MEMORY, current_memory)

    def record_stream(self, direction: str, delta: int = 1) -> None:
        """
        Record a stream event.

        Args:
            direction: Stream direction ('inbound' or 'outbound')
            delta: Change in stream count

        """
        if direction == "inbound":
            self.increment(MetricType.STREAMS_INBOUND, delta)
        else:
            self.increment(MetricType.STREAMS_OUTBOUND, delta)

        # Update peak streams
        current_total = self.get_counter(MetricType.STREAMS_INBOUND) + self.get_counter(
            MetricType.STREAMS_OUTBOUND
        )
        if current_total > self.get_gauge(MetricType.PEAK_STREAMS):
            self.set_gauge(MetricType.PEAK_STREAMS, current_total)

    def record_block(self, resource_type: str) -> None:
        """
        Record a resource block event.

        Args:
            resource_type: Type of resource that was blocked

        """
        if resource_type == "connection":
            self.increment(MetricType.CONNECTION_BLOCKS)
        elif resource_type == "memory":
            self.increment(MetricType.MEMORY_BLOCKS)
        elif resource_type == "stream":
            self.increment(MetricType.STREAM_BLOCKS)

    # Backward compatibility methods
    def allow_conn(self, direction: str, use_fd: bool = True) -> None:
        """Record an allowed connection (backward compatibility)."""
        self.record_connection(direction)

    def remove_conn(self, direction: str, use_fd: bool = True) -> None:
        """Record a removed connection (backward compatibility)."""
        self.record_connection(direction, -1)

    def allow_stream(self, peer_id: str, direction: str) -> None:
        """Record an allowed stream (backward compatibility)."""
        self.record_stream(direction)

    def remove_stream(self, direction: str) -> None:
        """Record a removed stream (backward compatibility)."""
        self.record_stream(direction, -1)

    def allow_memory(self, size: int) -> None:
        """Record allowed memory (backward compatibility)."""
        self.record_memory(size)

    def release_memory(self, size: int) -> None:
        """Record released memory (backward compatibility)."""
        self.record_memory(size, -1)

    def block_conn(self, direction: str, use_fd: bool = True) -> None:
        """Record a blocked connection (backward compatibility)."""
        self.record_block("connection")

    def block_stream(self, peer_id: str, direction: str) -> None:
        """Record a blocked stream (backward compatibility)."""
        self.record_block("stream")

    def block_memory(self, size: int) -> None:
        """Record blocked memory (backward compatibility)."""
        self.record_block("memory")

    def get_summary(self) -> dict[str, Any]:
        """
        Get a summary of all metrics.

        Returns:
            Dictionary containing all metric values

        """
        with self._lock:
            return {
                "uptime": time.time() - self._start_time,
                "connections": {
                    "inbound": self.get_counter(MetricType.CONNECTIONS_INBOUND),
                    "outbound": self.get_counter(MetricType.CONNECTIONS_OUTBOUND),
                    "total": (
                        self.get_counter(MetricType.CONNECTIONS_INBOUND)
                        + self.get_counter(MetricType.CONNECTIONS_OUTBOUND)
                    ),
                    "peak": self.get_gauge(MetricType.PEAK_CONNECTIONS),
                },
                "memory": {
                    "current": self.get_counter(MetricType.MEMORY_USAGE),
                    "peak": self.get_gauge(MetricType.PEAK_MEMORY),
                },
                "streams": {
                    "inbound": self.get_counter(MetricType.STREAMS_INBOUND),
                    "outbound": self.get_counter(MetricType.STREAMS_OUTBOUND),
                    "total": (
                        self.get_counter(MetricType.STREAMS_INBOUND)
                        + self.get_counter(MetricType.STREAMS_OUTBOUND)
                    ),
                    "peak": self.get_gauge(MetricType.PEAK_STREAMS),
                },
                "blocks": {
                    "connections": self.get_counter(MetricType.CONNECTION_BLOCKS),
                    "memory": self.get_counter(MetricType.MEMORY_BLOCKS),
                    "streams": self.get_counter(MetricType.STREAM_BLOCKS),
                },
            }

    def reset(self) -> None:
        """Reset all metrics to zero."""
        with self._lock:
            self._counters = [0] * len(MetricType)
            self._gauges = [0.0] * len(MetricType)
        self.resource_metrics.clear()
        self._start_time = time.time()
