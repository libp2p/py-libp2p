"""
Connection Health Data Structures for Python libp2p.

This module provides the core data structures for tracking connection health,
including metrics, health scoring, and health-related configurations.
"""

from dataclasses import dataclass
import logging
import time
from typing import Any

logger = logging.getLogger("libp2p.network.health.data_structures")


@dataclass
class HealthMonitorStatus:
    """Status information for the health monitoring service."""

    # Basic status
    enabled: bool

    # Service status
    monitoring_task_started: bool = False

    # Configuration
    check_interval_seconds: float = 0.0

    # Statistics
    total_connections: int = 0
    monitored_connections: int = 0
    total_peers: int = 0
    monitored_peers: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for backward compatibility."""
        return {
            "enabled": self.enabled,
            "monitoring_task_started": self.monitoring_task_started,
            "check_interval_seconds": self.check_interval_seconds,
            "total_connections": self.total_connections,
            "monitored_connections": self.monitored_connections,
            "total_peers": self.total_peers,
            "monitored_peers": self.monitored_peers,
        }


@dataclass
class ConnectionHealth:
    """Enhanced connection health tracking."""

    # Basic metrics
    established_at: float
    last_used: float
    last_ping: float
    ping_latency: float

    # Performance metrics
    stream_count: int
    total_bytes_sent: int
    total_bytes_received: int

    # Health indicators
    failed_streams: int
    ping_success_rate: float
    health_score: float  # 0.0 to 1.0

    # Timestamps
    last_successful_operation: float
    last_failed_operation: float

    # Connection quality metrics
    average_stream_lifetime: float
    connection_stability: float  # Based on disconnection frequency

    # Advanced monitoring metrics
    bandwidth_usage: dict[str, float]  # Track bandwidth over time windows
    error_history: list[tuple[float, str]]  # Timestamp and error type
    connection_events: list[tuple[float, str]]  # Connection lifecycle events
    last_bandwidth_check: float
    peak_bandwidth: float
    average_bandwidth: float

    def __post_init__(self) -> None:
        """Initialize default values and validate data."""
        current_time = time.time()

        # Set default timestamps if not provided
        if self.established_at == 0:
            self.established_at = current_time
        if self.last_used == 0:
            self.last_used = current_time
        if self.last_ping == 0:
            self.last_ping = current_time
        if self.last_successful_operation == 0:
            self.last_successful_operation = current_time

        # Validate ranges
        self.health_score = max(0.0, min(1.0, float(self.health_score)))
        self.ping_success_rate = max(0.0, min(1.0, float(self.ping_success_rate)))
        self.connection_stability = max(0.0, min(1.0, float(self.connection_stability)))

    def update_health_score(self) -> None:
        """Calculate overall health score based on metrics."""
        # Weighted scoring algorithm
        latency_score = max(0.0, 1.0 - (self.ping_latency / 1000.0))  # Normalize to 1s
        success_score = self.ping_success_rate
        stability_score = self.connection_stability

        self.health_score = (
            latency_score * 0.4 + success_score * 0.4 + stability_score * 0.2
        )

    def update_ping_metrics(self, latency: float, success: bool) -> None:
        """Update ping-related metrics."""
        self.last_ping = time.time()
        self.ping_latency = latency

        # Update success rate (exponential moving average)
        alpha = 0.3  # Smoothing factor
        if success:
            self.ping_success_rate = alpha * 1.0 + (1 - alpha) * self.ping_success_rate
        else:
            self.ping_success_rate = alpha * 0.0 + (1 - alpha) * self.ping_success_rate

        self.update_health_score()

    def update_stream_metrics(self, stream_count: int, failed: bool = False) -> None:
        """Update stream-related metrics."""
        self.stream_count = stream_count
        self.last_used = time.time()

        if failed:
            self.failed_streams += 1
            self.last_failed_operation = time.time()
            self.add_error("stream_failure")
        else:
            self.last_successful_operation = time.time()

        self.update_health_score()

    def is_healthy(self, min_health_threshold: float = 0.3) -> bool:
        """Check if connection meets minimum health requirements."""
        return self.health_score >= min_health_threshold

    def get_age(self) -> float:
        """Get connection age in seconds."""
        return time.time() - self.established_at

    def get_idle_time(self) -> float:
        """Get time since last activity in seconds."""
        return time.time() - self.last_used

    def add_error(self, error_type: str) -> None:
        """Record an error occurrence."""
        current_time = time.time()
        self.error_history.append((current_time, error_type))

        # Keep only recent errors (last 100)
        if len(self.error_history) > 100:
            self.error_history = self.error_history[-100:]

        # Update health score based on error frequency
        self._update_stability_score()

    def add_connection_event(self, event_type: str) -> None:
        """Record a connection lifecycle event."""
        current_time = time.time()
        self.connection_events.append((current_time, event_type))

        # Keep only recent events (last 50)
        if len(self.connection_events) > 50:
            self.connection_events = self.connection_events[-50:]

    def update_bandwidth_metrics(
        self, bytes_sent: int, bytes_received: int, window_size: int = 300
    ) -> None:
        """Update bandwidth usage metrics."""
        current_time = time.time()
        window_key = str(int(current_time // window_size))

        # Update total bytes
        self.total_bytes_sent += bytes_sent
        self.total_bytes_received += bytes_received

        # Update bandwidth usage for current time window
        if window_key not in self.bandwidth_usage:
            self.bandwidth_usage[window_key] = 0.0

        current_bandwidth = (
            bytes_sent + bytes_received
        ) / window_size  # bytes per second
        self.bandwidth_usage[window_key] = current_bandwidth

        # Update peak and average bandwidth
        if current_bandwidth > self.peak_bandwidth:
            self.peak_bandwidth = current_bandwidth

        # Calculate rolling average bandwidth
        if self.bandwidth_usage:
            self.average_bandwidth = sum(self.bandwidth_usage.values()) / len(
                self.bandwidth_usage
            )

        self.last_bandwidth_check = current_time

        # Clean up old bandwidth data (keep last 10 windows)
        if len(self.bandwidth_usage) > 10:
            oldest_key = min(self.bandwidth_usage.keys(), default=None)
            if oldest_key is not None:
                del self.bandwidth_usage[oldest_key]

    def _update_stability_score(self) -> None:
        """Update connection stability based on error history."""
        current_time = time.time()

        # Calculate error rate in last hour
        recent_errors = [
            error
            for timestamp, error in self.error_history
            if current_time - timestamp < 3600  # Last hour
        ]

        # Calculate stability based on error frequency and connection age
        error_rate = len(recent_errors) / max(1.0, self.get_age() / 3600.0)

        # Convert error rate to stability score (0.0 to 1.0)
        # Lower error rate = higher stability
        self.connection_stability = max(0.0, min(1.0, 1.0 - (error_rate * 0.1)))

        # Update overall health score
        self.update_health_score()

    def get_health_summary(self) -> dict[str, Any]:
        """Get a comprehensive health summary."""
        return {
            "health_score": self.health_score,
            "ping_latency_ms": self.ping_latency,
            "ping_success_rate": self.ping_success_rate,
            "connection_stability": self.connection_stability,
            "stream_count": self.stream_count,
            "failed_streams": self.failed_streams,
            "connection_age_seconds": self.get_age(),
            "idle_time_seconds": self.get_idle_time(),
            "total_bytes_sent": self.total_bytes_sent,
            "total_bytes_received": self.total_bytes_received,
            "peak_bandwidth_bps": self.peak_bandwidth,
            "average_bandwidth_bps": self.average_bandwidth,
            "recent_errors": len(
                [e for t, e in self.error_history if time.time() - t < 3600]
            ),
            "connection_events": len(self.connection_events),
        }


def create_default_connection_health(
    established_at: float | None = None,
) -> ConnectionHealth:
    """Create a new ConnectionHealth instance with default values."""
    current_time = time.time()
    established_at = established_at or current_time

    return ConnectionHealth(
        established_at=established_at,
        last_used=current_time,
        last_ping=current_time,
        ping_latency=0.0,
        stream_count=0,
        total_bytes_sent=0,
        total_bytes_received=0,
        failed_streams=0,
        ping_success_rate=1.0,
        health_score=1.0,
        last_successful_operation=current_time,
        last_failed_operation=0.0,
        average_stream_lifetime=0.0,
        connection_stability=1.0,
        bandwidth_usage={},
        error_history=[],
        connection_events=[],
        last_bandwidth_check=current_time,
        peak_bandwidth=0.0,
        average_bandwidth=0.0,
    )
