"""
Protocol rate limiter for resource management.

This module implements protocol-specific rate limiting that provides
fine-grained control over protocol usage for production-ready
resource management.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

from libp2p.peer.id import ID

from .rate_limiter import (
    RateLimitConfig,
    RateLimiter,
    RateLimitScope,
    RateLimitStrategy,
)


@dataclass
class ProtocolRateLimitConfig:
    """Configuration for protocol rate limiter."""

    # Protocol identification
    protocol_name: str
    protocol_version: str | None = None

    # Rate limiting parameters
    refill_rate: float = 10.0  # Tokens per second
    capacity: float = 100.0  # Maximum tokens in bucket
    initial_tokens: float = 0.0  # Initial tokens in bucket

    # Burst handling
    allow_burst: bool = True  # Allow burst up to capacity
    burst_multiplier: float = 1.0  # Burst capacity multiplier

    # Time parameters
    time_window_seconds: float = 1.0  # Time window for rate calculation
    min_interval_seconds: float = 0.001  # Minimum interval between refills

    # Scope parameters
    scope: RateLimitScope = RateLimitScope.PER_PEER  # Rate limiting scope
    max_peers: int = 1000  # Maximum number of peers to track
    max_connections: int = 1000  # Maximum number of connections to track

    # Monitoring parameters
    enable_monitoring: bool = True  # Enable monitoring and statistics
    max_history_size: int = 1000  # Maximum history size for monitoring

    # Protocol-specific parameters
    max_concurrent_requests: int = 10  # Maximum concurrent requests
    request_timeout_seconds: float = 30.0  # Request timeout in seconds
    backoff_factor: float = 2.0  # Backoff factor for retries

    def __post_init__(self) -> None:
        """Validate configuration parameters."""
        if not self.protocol_name:
            raise ValueError("protocol_name cannot be empty")
        if self.refill_rate <= 0:
            raise ValueError("refill_rate must be positive")
        if self.capacity <= 0:
            raise ValueError("capacity must be positive")
        if self.initial_tokens < 0:
            raise ValueError("initial_tokens must be non-negative")
        if self.initial_tokens > self.capacity:
            raise ValueError("initial_tokens cannot exceed capacity")
        if self.burst_multiplier < 1.0:
            raise ValueError("burst_multiplier must be >= 1.0")
        if self.time_window_seconds <= 0:
            raise ValueError("time_window_seconds must be positive")
        if self.min_interval_seconds <= 0:
            raise ValueError("min_interval_seconds must be positive")
        if self.max_history_size <= 0:
            raise ValueError("max_history_size must be positive")
        if self.max_peers <= 0:
            raise ValueError("max_peers must be positive")
        if self.max_connections <= 0:
            raise ValueError("max_connections must be positive")
        if self.max_concurrent_requests <= 0:
            raise ValueError("max_concurrent_requests must be positive")
        if self.request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")
        if self.backoff_factor < 1.0:
            raise ValueError("backoff_factor must be >= 1.0")


@dataclass
class ProtocolRateLimitStats:
    """Statistics for protocol rate limiter."""

    # Protocol information
    protocol_name: str
    protocol_version: str | None

    # Rate limiting statistics
    current_rate: float
    allowed_requests: int
    denied_requests: int
    total_requests: int

    # Protocol-specific statistics
    concurrent_requests: int
    max_concurrent_requests: int
    request_timeouts: int
    backoff_events: int

    # Scope information
    scope: RateLimitScope
    tracked_entities: int

    # Time information
    time_since_last_request: float
    next_available_time: float

    def to_dict(self) -> dict[str, Any]:
        """Convert statistics to dictionary."""
        return {
            "protocol_name": self.protocol_name,
            "protocol_version": self.protocol_version,
            "current_rate": self.current_rate,
            "allowed_requests": self.allowed_requests,
            "denied_requests": self.denied_requests,
            "total_requests": self.total_requests,
            "concurrent_requests": self.concurrent_requests,
            "max_concurrent_requests": self.max_concurrent_requests,
            "request_timeouts": self.request_timeouts,
            "backoff_events": self.backoff_events,
            "scope": self.scope.value,
            "tracked_entities": self.tracked_entities,
            "time_since_last_request": self.time_since_last_request,
            "next_available_time": self.next_available_time,
        }


class ProtocolRateLimiter:
    """
    Protocol-specific rate limiter implementation.

    This class implements protocol-specific rate limiting that provides
    fine-grained control over protocol usage with support for
    concurrent request tracking and backoff handling.
    """

    def __init__(self, config: ProtocolRateLimitConfig):
        """
        Initialize protocol rate limiter.

        Args:
            config: Protocol rate limiter configuration

        """
        self.config = config

        # Rate limiting state
        self._rate_limiter: RateLimiter = self._create_rate_limiter()

        # Protocol-specific state
        self._concurrent_requests: dict[str, int] = {}
        self._request_start_times: dict[str, list[float]] = {}
        self._backoff_until: dict[str, float] = {}

        # Statistics
        self._request_timeouts: int = 0
        self._backoff_events: int = 0

    def _create_rate_limiter(self) -> RateLimiter:
        """Create the underlying rate limiter."""
        rate_config = RateLimitConfig(
            strategy=RateLimitStrategy.TOKEN_BUCKET,
            scope=self.config.scope,
            refill_rate=self.config.refill_rate,
            capacity=self.config.capacity,
            initial_tokens=self.config.initial_tokens,
            allow_burst=self.config.allow_burst,
            burst_multiplier=self.config.burst_multiplier,
            time_window_seconds=self.config.time_window_seconds,
            min_interval_seconds=self.config.min_interval_seconds,
            enable_monitoring=self.config.enable_monitoring,
            max_history_size=self.config.max_history_size,
            max_peers=self.config.max_peers,
            max_connections=self.config.max_connections,
        )
        return RateLimiter(rate_config)

    def _get_entity_key(
        self,
        peer_id: ID | None = None,
        connection_id: str | None = None,
    ) -> str:
        """
        Get entity key for rate limiting.

        Args:
            peer_id: Peer ID (optional)
            connection_id: Connection ID (optional)

        Returns:
            Entity key for rate limiting

        """
        if self.config.scope == RateLimitScope.GLOBAL:
            return "global"
        elif self.config.scope == RateLimitScope.PER_PEER:
            return f"peer:{peer_id}" if peer_id else "unknown"
        elif self.config.scope == RateLimitScope.PER_CONNECTION:
            return f"conn:{connection_id}" if connection_id else "unknown"
        else:
            return "unknown"

    def _cleanup_old_requests(self, entity_key: str, current_time: float) -> None:
        """
        Clean up old requests that have timed out.

        Args:
            entity_key: Entity key for rate limiting
            current_time: Current timestamp

        """
        if entity_key not in self._request_start_times:
            return

        # Remove requests that have timed out
        timeout_threshold = current_time - self.config.request_timeout_seconds
        self._request_start_times[entity_key] = [
            start_time
            for start_time in self._request_start_times[entity_key]
            if start_time > timeout_threshold
        ]

        # Update concurrent request count
        self._concurrent_requests[entity_key] = len(
            self._request_start_times[entity_key]
        )

        # Count timeouts
        if len(self._request_start_times[entity_key]) < self._concurrent_requests.get(
            entity_key, 0
        ):
            self._request_timeouts += 1

    def _is_in_backoff(self, entity_key: str, current_time: float) -> bool:
        """
        Check if entity is in backoff period.

        Args:
            entity_key: Entity key for rate limiting
            current_time: Current timestamp

        Returns:
            True if entity is in backoff period

        """
        if entity_key not in self._backoff_until:
            return False

        if current_time < self._backoff_until[entity_key]:
            return True

        # Backoff period has ended
        del self._backoff_until[entity_key]
        return False

    def _start_backoff(self, entity_key: str, current_time: float) -> None:
        """
        Start backoff period for entity.

        Args:
            entity_key: Entity key for rate limiting
            current_time: Current timestamp

        """
        # Calculate backoff duration
        backoff_duration = (
            self.config.request_timeout_seconds * self.config.backoff_factor
        )

        # Set backoff end time
        self._backoff_until[entity_key] = current_time + backoff_duration

        # Record backoff event
        self._backoff_events += 1

    def try_allow_request(
        self,
        tokens: float = 1.0,
        peer_id: ID | None = None,
        connection_id: str | None = None,
        current_time: float | None = None,
    ) -> bool:
        """
        Try to allow a protocol request based on rate limiting.

        Args:
            tokens: Number of tokens to consume
            peer_id: Peer ID (optional)
            connection_id: Connection ID (optional)
            current_time: Current timestamp (optional)

        Returns:
            True if request is allowed, False otherwise

        """
        if current_time is None:
            current_time = time.time()

        # Get entity key
        entity_key = self._get_entity_key(peer_id, connection_id)

        # Clean up old requests
        self._cleanup_old_requests(entity_key, current_time)

        # Check if entity is in backoff period
        if self._is_in_backoff(entity_key, current_time):
            return False

        # Check concurrent request limit
        current_concurrent = self._concurrent_requests.get(entity_key, 0)
        if current_concurrent >= self.config.max_concurrent_requests:
            # Start backoff period
            self._start_backoff(entity_key, current_time)
            return False

        # Check rate limiting
        if not self._rate_limiter.try_allow(
            tokens,
            peer_id,
            connection_id,
            self.config.protocol_name,
            None,
            current_time,
        ):
            return False

        # Allow request
        if entity_key not in self._request_start_times:
            self._request_start_times[entity_key] = []

        self._request_start_times[entity_key].append(current_time)
        self._concurrent_requests[entity_key] = len(
            self._request_start_times[entity_key]
        )

        return True

    def allow_request(
        self,
        tokens: float = 1.0,
        peer_id: ID | None = None,
        connection_id: str | None = None,
        current_time: float | None = None,
    ) -> None:
        """
        Allow a protocol request based on rate limiting (raises exception if denied).

        Args:
            tokens: Number of tokens to consume
            peer_id: Peer ID (optional)
            connection_id: Connection ID (optional)
            current_time: Current timestamp (optional)

        Raises:
            ValueError: If request is denied by rate limiting

        """
        if not self.try_allow_request(tokens, peer_id, connection_id, current_time):
            raise ValueError("Protocol request denied by rate limiting")

    def finish_request(
        self,
        peer_id: ID | None = None,
        connection_id: str | None = None,
        current_time: float | None = None,
    ) -> None:
        """
        Finish a protocol request.

        Args:
            peer_id: Peer ID (optional)
            connection_id: Connection ID (optional)
            current_time: Current timestamp (optional)

        """
        if current_time is None:
            current_time = time.time()

        # Get entity key
        entity_key = self._get_entity_key(peer_id, connection_id)

        # Remove oldest request
        if (
            entity_key in self._request_start_times
            and self._request_start_times[entity_key]
        ):
            self._request_start_times[entity_key].pop(0)
            self._concurrent_requests[entity_key] = len(
                self._request_start_times[entity_key]
            )

    def get_stats(
        self,
        peer_id: ID | None = None,
        connection_id: str | None = None,
        current_time: float | None = None,
    ) -> ProtocolRateLimitStats:
        """
        Get current statistics for the protocol rate limiter.

        Args:
            peer_id: Peer ID (optional)
            connection_id: Connection ID (optional)
            current_time: Current timestamp (optional)

        Returns:
            ProtocolRateLimitStats: Current statistics

        """
        if current_time is None:
            current_time = time.time()

        # Get entity key
        entity_key = self._get_entity_key(peer_id, connection_id)

        # Clean up old requests
        self._cleanup_old_requests(entity_key, current_time)

        # Get rate limiter statistics
        rate_stats = self._rate_limiter.get_stats(
            peer_id, connection_id, self.config.protocol_name, None, current_time
        )

        # Get protocol-specific statistics
        concurrent_requests = self._concurrent_requests.get(entity_key, 0)

        # Calculate time since last request
        time_since_last_request = 0.0
        if (
            entity_key in self._request_start_times
            and self._request_start_times[entity_key]
        ):
            last_request_time = max(self._request_start_times[entity_key])
            time_since_last_request = current_time - last_request_time

        return ProtocolRateLimitStats(
            protocol_name=self.config.protocol_name,
            protocol_version=self.config.protocol_version,
            current_rate=rate_stats.current_rate,
            allowed_requests=rate_stats.allowed_requests,
            denied_requests=rate_stats.denied_requests,
            total_requests=rate_stats.total_requests,
            concurrent_requests=concurrent_requests,
            max_concurrent_requests=self.config.max_concurrent_requests,
            request_timeouts=self._request_timeouts,
            backoff_events=self._backoff_events,
            scope=self.config.scope,
            tracked_entities=rate_stats.tracked_entities,
            time_since_last_request=time_since_last_request,
            next_available_time=rate_stats.next_available_time,
        )

    def get_entity_stats(
        self,
        peer_id: ID | None = None,
        connection_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Get entity-specific statistics.

        Args:
            peer_id: Peer ID (optional)
            connection_id: Connection ID (optional)

        Returns:
            Dictionary with entity-specific statistics

        """
        entity_key = self._get_entity_key(peer_id, connection_id)

        # Get rate limiter entity stats
        rate_stats = self._rate_limiter.get_entity_stats(peer_id, connection_id)

        # Add protocol-specific stats
        protocol_stats = {
            "protocol_name": self.config.protocol_name,
            "protocol_version": self.config.protocol_version,
            "concurrent_requests": self._concurrent_requests.get(entity_key, 0),
            "max_concurrent_requests": self.config.max_concurrent_requests,
            "request_start_times": self._request_start_times.get(entity_key, []),
            "in_backoff": entity_key in self._backoff_until,
            "backoff_until": self._backoff_until.get(entity_key, 0.0),
        }

        return {**rate_stats, **protocol_stats}

    def reset(self) -> None:
        """Reset the protocol rate limiter to initial state."""
        self._rate_limiter.reset()
        self._concurrent_requests.clear()
        self._request_start_times.clear()
        self._backoff_until.clear()
        self._request_timeouts = 0
        self._backoff_events = 0

    def __str__(self) -> str:
        """String representation of protocol rate limiter."""
        return (
            f"ProtocolRateLimiter(protocol={self.config.protocol_name}, "
            f"version={self.config.protocol_version}, "
            f"rate={self.config.refill_rate:.2f}/s, "
            f"capacity={self.config.capacity:.2f})"
        )


# Factory functions
def create_protocol_rate_limiter(
    protocol_name: str,
    protocol_version: str | None = None,
    refill_rate: float = 10.0,
    capacity: float = 100.0,
    initial_tokens: float = 0.0,
    allow_burst: bool = True,
    burst_multiplier: float = 1.0,
    time_window_seconds: float = 1.0,
    min_interval_seconds: float = 0.001,
    scope: RateLimitScope = RateLimitScope.PER_PEER,
    max_peers: int = 1000,
    max_connections: int = 1000,
    enable_monitoring: bool = True,
    max_history_size: int = 1000,
    max_concurrent_requests: int = 10,
    request_timeout_seconds: float = 30.0,
    backoff_factor: float = 2.0,
) -> ProtocolRateLimiter:
    """
    Create a protocol rate limiter.

    Args:
        protocol_name: Name of the protocol
        protocol_version: Version of the protocol (optional)
        refill_rate: Tokens per second
        capacity: Maximum tokens in bucket
        initial_tokens: Initial tokens in bucket
        allow_burst: Allow burst up to capacity
        burst_multiplier: Burst capacity multiplier
        time_window_seconds: Time window for rate calculation
        min_interval_seconds: Minimum interval between refills
        scope: Rate limiting scope
        max_peers: Maximum number of peers to track
        max_connections: Maximum number of connections to track
        enable_monitoring: Enable monitoring and statistics
        max_history_size: Maximum history size for monitoring
        max_concurrent_requests: Maximum concurrent requests
        request_timeout_seconds: Request timeout in seconds
        backoff_factor: Backoff factor for retries

    Returns:
        ProtocolRateLimiter: Configured protocol rate limiter

    """
    config = ProtocolRateLimitConfig(
        protocol_name=protocol_name,
        protocol_version=protocol_version,
        refill_rate=refill_rate,
        capacity=capacity,
        initial_tokens=initial_tokens,
        allow_burst=allow_burst,
        burst_multiplier=burst_multiplier,
        time_window_seconds=time_window_seconds,
        min_interval_seconds=min_interval_seconds,
        scope=scope,
        max_peers=max_peers,
        max_connections=max_connections,
        enable_monitoring=enable_monitoring,
        max_history_size=max_history_size,
        max_concurrent_requests=max_concurrent_requests,
        request_timeout_seconds=request_timeout_seconds,
        backoff_factor=backoff_factor,
    )
    return ProtocolRateLimiter(config)


def create_strict_protocol_rate_limiter(
    protocol_name: str,
    protocol_version: str | None = None,
    refill_rate: float = 10.0,
    capacity: float = 100.0,
    initial_tokens: float = 0.0,
) -> ProtocolRateLimiter:
    """
    Create a strict protocol rate limiter (no burst).

    Args:
        protocol_name: Name of the protocol
        protocol_version: Version of the protocol (optional)
        refill_rate: Tokens per second
        capacity: Maximum tokens in bucket
        initial_tokens: Initial tokens in bucket

    Returns:
        ProtocolRateLimiter: Configured strict protocol rate limiter

    """
    return create_protocol_rate_limiter(
        protocol_name=protocol_name,
        protocol_version=protocol_version,
        refill_rate=refill_rate,
        capacity=capacity,
        initial_tokens=initial_tokens,
        allow_burst=False,
        burst_multiplier=1.0,
    )


def create_burst_protocol_rate_limiter(
    protocol_name: str,
    protocol_version: str | None = None,
    refill_rate: float = 10.0,
    capacity: float = 100.0,
    initial_tokens: float = 0.0,
    burst_multiplier: float = 2.0,
) -> ProtocolRateLimiter:
    """
    Create a burst-capable protocol rate limiter.

    Args:
        protocol_name: Name of the protocol
        protocol_version: Version of the protocol (optional)
        refill_rate: Tokens per second
        capacity: Maximum tokens in bucket
        initial_tokens: Initial tokens in bucket
        burst_multiplier: Burst capacity multiplier

    Returns:
        ProtocolRateLimiter: Configured burst-capable protocol rate limiter

    """
    return create_protocol_rate_limiter(
        protocol_name=protocol_name,
        protocol_version=protocol_version,
        refill_rate=refill_rate,
        capacity=capacity,
        initial_tokens=initial_tokens,
        allow_burst=True,
        burst_multiplier=burst_multiplier,
    )
