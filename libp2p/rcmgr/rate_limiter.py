"""
Rate limiter for resource management.

This module implements a comprehensive rate limiter that provides
multiple rate limiting strategies for production-ready resource
management.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import time
from typing import Any

import multiaddr

from libp2p.peer.id import ID

from .token_bucket import TokenBucket, TokenBucketConfig


class RateLimitStrategy(Enum):
    """Rate limiting strategies."""

    TOKEN_BUCKET = "token_bucket"
    FIXED_WINDOW = "fixed_window"
    SLIDING_WINDOW = "sliding_window"
    ADAPTIVE = "adaptive"


class RateLimitScope(Enum):
    """Rate limiting scopes."""

    GLOBAL = "global"
    PER_PEER = "per_peer"
    PER_CONNECTION = "per_connection"
    PER_PROTOCOL = "per_protocol"
    PER_ENDPOINT = "per_endpoint"


@dataclass
class RateLimitConfig:
    """Configuration for rate limiter."""

    # Rate limiting parameters
    strategy: RateLimitStrategy = RateLimitStrategy.TOKEN_BUCKET
    scope: RateLimitScope = RateLimitScope.GLOBAL

    # Token bucket parameters (for TOKEN_BUCKET strategy)
    refill_rate: float = 10.0  # Tokens per second
    capacity: float = 100.0  # Maximum tokens in bucket
    initial_tokens: float = 0.0  # Initial tokens in bucket

    # Window parameters (for FIXED_WINDOW and SLIDING_WINDOW strategies)
    window_size_seconds: float = 60.0  # Window size in seconds
    max_requests_per_window: int = 100  # Maximum requests per window

    # Adaptive parameters (for ADAPTIVE strategy)
    base_rate: float = 10.0  # Base rate for adaptive limiting
    max_rate: float = 100.0  # Maximum rate for adaptive limiting
    min_rate: float = 1.0  # Minimum rate for adaptive limiting
    adaptation_factor: float = 0.1  # Adaptation factor

    # Burst handling
    allow_burst: bool = True  # Allow burst up to capacity
    burst_multiplier: float = 1.0  # Burst capacity multiplier

    # Time parameters
    time_window_seconds: float = 1.0  # Time window for rate calculation
    min_interval_seconds: float = 0.001  # Minimum interval between refills

    # Monitoring parameters
    enable_monitoring: bool = True  # Enable monitoring and statistics
    max_history_size: int = 1000  # Maximum history size for monitoring

    # Scope-specific parameters
    max_peers: int = 1000  # Maximum number of peers to track
    max_connections: int = 1000  # Maximum number of connections to track
    max_protocols: int = 100  # Maximum number of protocols to track

    def __post_init__(self) -> None:
        """Validate configuration parameters."""
        if self.refill_rate <= 0:
            raise ValueError("refill_rate must be positive")
        if self.capacity <= 0:
            raise ValueError("capacity must be positive")
        if self.initial_tokens < 0:
            raise ValueError("initial_tokens must be non-negative")
        if self.initial_tokens > self.capacity:
            raise ValueError("initial_tokens cannot exceed capacity")
        if self.window_size_seconds <= 0:
            raise ValueError("window_size_seconds must be positive")
        if self.max_requests_per_window <= 0:
            raise ValueError("max_requests_per_window must be positive")
        if self.base_rate <= 0:
            raise ValueError("base_rate must be positive")
        if self.max_rate <= self.base_rate:
            raise ValueError("max_rate must be greater than base_rate")
        if self.min_rate <= 0:
            raise ValueError("min_rate must be positive")
        if self.min_rate > self.base_rate:
            raise ValueError("min_rate must be less than or equal to base_rate")
        if self.adaptation_factor <= 0 or self.adaptation_factor > 1:
            raise ValueError("adaptation_factor must be between 0 and 1")
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
        if self.max_protocols <= 0:
            raise ValueError("max_protocols must be positive")


@dataclass
class RateLimitStats:
    """Statistics for rate limiter."""

    # Current state
    current_rate: float
    allowed_requests: int
    denied_requests: int
    total_requests: int

    # Rate information
    configured_rate: float
    effective_rate: float
    burst_available: float

    # Scope information
    scope: RateLimitScope
    tracked_entities: int

    # Time information
    time_since_last_request: float
    next_available_time: float

    def to_dict(self) -> dict[str, Any]:
        """Convert statistics to dictionary."""
        return {
            "current_rate": self.current_rate,
            "allowed_requests": self.allowed_requests,
            "denied_requests": self.denied_requests,
            "total_requests": self.total_requests,
            "configured_rate": self.configured_rate,
            "effective_rate": self.effective_rate,
            "burst_available": self.burst_available,
            "scope": self.scope.value,
            "tracked_entities": self.tracked_entities,
            "time_since_last_request": self.time_since_last_request,
            "next_available_time": self.next_available_time,
        }


class RateLimiter:
    """
    Comprehensive rate limiter implementation.

    This class implements multiple rate limiting strategies including
    token bucket, fixed window, sliding window, and adaptive limiting.
    """

    def __init__(self, config: RateLimitConfig):
        """
        Initialize rate limiter.

        Args:
            config: Rate limiter configuration

        """
        self.config = config

        # Rate limiting state
        self._token_buckets: dict[str, TokenBucket] = {}
        self._window_counts: dict[str, list[float]] = {}
        self._last_request_times: dict[str, float] = {}

        # Statistics
        self._total_requests: int = 0
        self._allowed_requests: int = 0
        self._denied_requests: int = 0

        # Adaptive rate limiting
        self._current_rate: float = config.base_rate
        self._last_adaptation_time: float = time.time()

    def _get_entity_key(
        self,
        peer_id: ID | None = None,
        connection_id: str | None = None,
        protocol: str | None = None,
        endpoint: str | multiaddr.Multiaddr | None = None,
    ) -> str:
        """
        Get entity key for rate limiting.

        Args:
            peer_id: Peer ID (optional)
            connection_id: Connection ID (optional)
            protocol: Protocol name (optional)
            endpoint: Endpoint address (optional)

        Returns:
            Entity key for rate limiting

        """
        if self.config.scope == RateLimitScope.GLOBAL:
            return "global"
        elif self.config.scope == RateLimitScope.PER_PEER:
            return f"peer:{peer_id}" if peer_id else "unknown"
        elif self.config.scope == RateLimitScope.PER_CONNECTION:
            return f"conn:{connection_id}" if connection_id else "unknown"
        elif self.config.scope == RateLimitScope.PER_PROTOCOL:
            return f"proto:{protocol}" if protocol else "unknown"
        elif self.config.scope == RateLimitScope.PER_ENDPOINT:
            endpoint_str = str(endpoint) if endpoint else "unknown"
            return f"endpoint:{endpoint_str}"
        else:
            return "unknown"

    def _get_or_create_token_bucket(self, entity_key: str) -> TokenBucket:
        """
        Get or create token bucket for entity.

        Args:
            entity_key: Entity key for rate limiting

        Returns:
            Token bucket for entity

        """
        if entity_key not in self._token_buckets:
            # Check if we've reached the limit for this scope
            if len(self._token_buckets) >= self._get_max_entities():
                # Remove oldest entity (simple LRU)
                oldest_key = min(
                    self._token_buckets.keys(),
                    key=lambda k: self._last_request_times.get(k, 0),
                )
                del self._token_buckets[oldest_key]
                if oldest_key in self._last_request_times:
                    del self._last_request_times[oldest_key]

            # Create new token bucket
            bucket_config = TokenBucketConfig(
                refill_rate=self.config.refill_rate,
                capacity=self.config.capacity,
                initial_tokens=self.config.initial_tokens,
                allow_burst=self.config.allow_burst,
                burst_multiplier=self.config.burst_multiplier,
                time_window_seconds=self.config.time_window_seconds,
                min_interval_seconds=self.config.min_interval_seconds,
                enable_monitoring=self.config.enable_monitoring,
                max_history_size=self.config.max_history_size,
            )
            self._token_buckets[entity_key] = TokenBucket(bucket_config)

        return self._token_buckets[entity_key]

    def _get_max_entities(self) -> int:
        """Get maximum number of entities to track."""
        if self.config.scope == RateLimitScope.PER_PEER:
            return self.config.max_peers
        elif self.config.scope == RateLimitScope.PER_CONNECTION:
            return self.config.max_connections
        elif self.config.scope == RateLimitScope.PER_PROTOCOL:
            return self.config.max_protocols
        else:
            return 1  # Global scope

    def _update_adaptive_rate(self, allowed: bool, current_time: float) -> None:
        """
        Update adaptive rate based on request outcome.

        Args:
            allowed: Whether request was allowed
            current_time: Current timestamp

        """
        if self.config.strategy != RateLimitStrategy.ADAPTIVE:
            return

        # Calculate time since last adaptation
        time_since_adaptation = current_time - self._last_adaptation_time

        # Only adapt if enough time has passed
        if time_since_adaptation < self.config.min_interval_seconds:
            return

        # Adapt rate based on outcome
        if allowed:
            # Increase rate if request was allowed
            self._current_rate = min(
                self._current_rate * (1 + self.config.adaptation_factor),
                self.config.max_rate,
            )
        else:
            # Decrease rate if request was denied
            self._current_rate = max(
                self._current_rate * (1 - self.config.adaptation_factor),
                self.config.min_rate,
            )

        # Update last adaptation time
        self._last_adaptation_time = current_time

    def try_allow(
        self,
        tokens: float = 1.0,
        peer_id: ID | None = None,
        connection_id: str | None = None,
        protocol: str | None = None,
        endpoint: str | multiaddr.Multiaddr | None = None,
        current_time: float | None = None,
    ) -> bool:
        """
        Try to allow a request based on rate limiting.

        Args:
            tokens: Number of tokens to consume
            peer_id: Peer ID (optional)
            connection_id: Connection ID (optional)
            protocol: Protocol name (optional)
            endpoint: Endpoint address (optional)
            current_time: Current timestamp (optional)

        Returns:
            True if request is allowed, False otherwise

        """
        if current_time is None:
            current_time = time.time()

        # Get entity key
        entity_key = self._get_entity_key(peer_id, connection_id, protocol, endpoint)

        # Update last request time
        self._last_request_times[entity_key] = current_time

        # Update statistics
        self._total_requests += 1

        # Apply rate limiting strategy
        allowed = False

        if self.config.strategy == RateLimitStrategy.TOKEN_BUCKET:
            # Token bucket strategy
            bucket = self._get_or_create_token_bucket(entity_key)
            allowed = bucket.try_consume(tokens, current_time)

        elif self.config.strategy == RateLimitStrategy.FIXED_WINDOW:
            # Fixed window strategy
            window_start = current_time - self.config.window_size_seconds
            if entity_key not in self._window_counts:
                self._window_counts[entity_key] = []

            # Clean up old requests
            self._window_counts[entity_key] = [
                timestamp
                for timestamp in self._window_counts[entity_key]
                if timestamp > window_start
            ]

            # Check if we're within the limit
            if (
                len(self._window_counts[entity_key])
                < self.config.max_requests_per_window
            ):
                allowed = True
                self._window_counts[entity_key].append(current_time)

        elif self.config.strategy == RateLimitStrategy.SLIDING_WINDOW:
            # Sliding window strategy (similar to fixed window for simplicity)
            window_start = current_time - self.config.window_size_seconds
            if entity_key not in self._window_counts:
                self._window_counts[entity_key] = []

            # Clean up old requests
            self._window_counts[entity_key] = [
                timestamp
                for timestamp in self._window_counts[entity_key]
                if timestamp > window_start
            ]

            # Check if we're within the limit
            if (
                len(self._window_counts[entity_key])
                < self.config.max_requests_per_window
            ):
                allowed = True
                self._window_counts[entity_key].append(current_time)

        elif self.config.strategy == RateLimitStrategy.ADAPTIVE:
            # Adaptive strategy
            bucket = self._get_or_create_token_bucket(entity_key)
            # Update bucket rate based on current adaptive rate
            bucket.config.refill_rate = self._current_rate
            allowed = bucket.try_consume(tokens, current_time)

        # Update statistics
        if allowed:
            self._allowed_requests += 1
        else:
            self._denied_requests += 1

        # Update adaptive rate
        self._update_adaptive_rate(allowed, current_time)

        return allowed

    def allow(
        self,
        tokens: float = 1.0,
        peer_id: ID | None = None,
        connection_id: str | None = None,
        protocol: str | None = None,
        endpoint: str | multiaddr.Multiaddr | None = None,
        current_time: float | None = None,
    ) -> None:
        """
        Allow a request based on rate limiting (raises exception if denied).

        Args:
            tokens: Number of tokens to consume
            peer_id: Peer ID (optional)
            connection_id: Connection ID (optional)
            protocol: Protocol name (optional)
            endpoint: Endpoint address (optional)
            current_time: Current timestamp (optional)

        Raises:
            ValueError: If request is denied by rate limiting

        """
        if not self.try_allow(
            tokens, peer_id, connection_id, protocol, endpoint, current_time
        ):
            raise ValueError("Request denied by rate limiting")

    def get_stats(
        self,
        peer_id: ID | None = None,
        connection_id: str | None = None,
        protocol: str | None = None,
        endpoint: str | multiaddr.Multiaddr | None = None,
        current_time: float | None = None,
    ) -> RateLimitStats:
        """
        Get current statistics for the rate limiter.

        Args:
            peer_id: Peer ID (optional)
            connection_id: Connection ID (optional)
            protocol: Protocol name (optional)
            endpoint: Endpoint address (optional)
            current_time: Current timestamp (optional)

        Returns:
            RateLimitStats: Current statistics

        """
        if current_time is None:
            current_time = time.time()

        # Get entity key
        entity_key = self._get_entity_key(peer_id, connection_id, protocol, endpoint)

        # Get entity-specific statistics
        if entity_key in self._token_buckets:
            bucket_stats = self._token_buckets[entity_key].get_stats(current_time)
            current_rate = bucket_stats.effective_rate
            burst_available = bucket_stats.burst_available
        else:
            current_rate = 0.0
            burst_available = 0.0

        # Calculate time since last request
        time_since_last_request = 0.0
        if entity_key in self._last_request_times:
            time_since_last_request = (
                current_time - self._last_request_times[entity_key]
            )

        # Calculate next available time
        next_available_time = 0.0
        if self.config.strategy == RateLimitStrategy.TOKEN_BUCKET:
            if entity_key in self._token_buckets:
                bucket_stats = self._token_buckets[entity_key].get_stats(current_time)
                next_available_time = bucket_stats.next_refill_time

        return RateLimitStats(
            current_rate=current_rate,
            allowed_requests=self._allowed_requests,
            denied_requests=self._denied_requests,
            total_requests=self._total_requests,
            configured_rate=self.config.refill_rate,
            effective_rate=(
                self._allowed_requests / self._total_requests
                if self._total_requests > 0
                else 0.0
            ),
            burst_available=burst_available,
            scope=self.config.scope,
            tracked_entities=len(self._token_buckets),
            time_since_last_request=time_since_last_request,
            next_available_time=next_available_time,
        )

    def get_entity_stats(
        self,
        peer_id: ID | None = None,
        connection_id: str | None = None,
        protocol: str | None = None,
        endpoint: str | multiaddr.Multiaddr | None = None,
    ) -> dict[str, Any]:
        """
        Get entity-specific statistics.

        Args:
            peer_id: Peer ID (optional)
            connection_id: Connection ID (optional)
            protocol: Protocol name (optional)
            endpoint: Endpoint address (optional)

        Returns:
            Dictionary with entity-specific statistics

        """
        entity_key = self._get_entity_key(peer_id, connection_id, protocol, endpoint)

        if entity_key in self._token_buckets:
            bucket = self._token_buckets[entity_key]
            return bucket.get_stats().to_dict()
        else:
            return {"exists": False}

    def reset(self) -> None:
        """Reset the rate limiter to initial state."""
        self._token_buckets.clear()
        self._window_counts.clear()
        self._last_request_times.clear()
        self._total_requests = 0
        self._allowed_requests = 0
        self._denied_requests = 0
        self._current_rate = self.config.base_rate
        self._last_adaptation_time = time.time()

    def __str__(self) -> str:
        """String representation of rate limiter."""
        return (
            f"RateLimiter(strategy={self.config.strategy.value}, "
            f"scope={self.config.scope.value}, "
            f"rate={self.config.refill_rate:.2f}/s, "
            f"capacity={self.config.capacity:.2f})"
        )


# Factory functions
def create_rate_limiter(
    strategy: RateLimitStrategy = RateLimitStrategy.TOKEN_BUCKET,
    scope: RateLimitScope = RateLimitScope.GLOBAL,
    refill_rate: float = 10.0,
    capacity: float = 100.0,
    initial_tokens: float = 0.0,
    allow_burst: bool = True,
    burst_multiplier: float = 1.0,
    time_window_seconds: float = 1.0,
    min_interval_seconds: float = 0.001,
    enable_monitoring: bool = True,
    max_history_size: int = 1000,
    max_peers: int = 1000,
    max_connections: int = 1000,
    max_protocols: int = 100,
) -> RateLimiter:
    """
    Create a rate limiter.

    Args:
        strategy: Rate limiting strategy
        scope: Rate limiting scope
        refill_rate: Tokens per second
        capacity: Maximum tokens in bucket
        initial_tokens: Initial tokens in bucket
        allow_burst: Allow burst up to capacity
        burst_multiplier: Burst capacity multiplier
        time_window_seconds: Time window for rate calculation
        min_interval_seconds: Minimum interval between refills
        enable_monitoring: Enable monitoring and statistics
        max_history_size: Maximum history size for monitoring
        max_peers: Maximum number of peers to track
        max_connections: Maximum number of connections to track
        max_protocols: Maximum number of protocols to track

    Returns:
        RateLimiter: Configured rate limiter

    """
    config = RateLimitConfig(
        strategy=strategy,
        scope=scope,
        refill_rate=refill_rate,
        capacity=capacity,
        initial_tokens=initial_tokens,
        allow_burst=allow_burst,
        burst_multiplier=burst_multiplier,
        time_window_seconds=time_window_seconds,
        min_interval_seconds=min_interval_seconds,
        enable_monitoring=enable_monitoring,
        max_history_size=max_history_size,
        max_peers=max_peers,
        max_connections=max_connections,
        max_protocols=max_protocols,
    )
    return RateLimiter(config)


def create_global_rate_limiter(
    refill_rate: float = 10.0,
    capacity: float = 100.0,
    initial_tokens: float = 0.0,
) -> RateLimiter:
    """
    Create a global rate limiter.

    Args:
        refill_rate: Tokens per second
        capacity: Maximum tokens in bucket
        initial_tokens: Initial tokens in bucket

    Returns:
        RateLimiter: Configured global rate limiter

    """
    return create_rate_limiter(
        strategy=RateLimitStrategy.TOKEN_BUCKET,
        scope=RateLimitScope.GLOBAL,
        refill_rate=refill_rate,
        capacity=capacity,
        initial_tokens=initial_tokens,
    )


def create_per_peer_rate_limiter(
    refill_rate: float = 10.0,
    capacity: float = 100.0,
    initial_tokens: float = 0.0,
    max_peers: int = 1000,
) -> RateLimiter:
    """
    Create a per-peer rate limiter.

    Args:
        refill_rate: Tokens per second
        capacity: Maximum tokens in bucket
        initial_tokens: Initial tokens in bucket
        max_peers: Maximum number of peers to track

    Returns:
        RateLimiter: Configured per-peer rate limiter

    """
    # If bursting is allowed and no explicit initial tokens were provided,
    # start buckets full to enable immediate burst as in common token-bucket usage.
    effective_initial = initial_tokens if initial_tokens > 0.0 else capacity
    return create_rate_limiter(
        strategy=RateLimitStrategy.TOKEN_BUCKET,
        scope=RateLimitScope.PER_PEER,
        refill_rate=refill_rate,
        capacity=capacity,
        initial_tokens=effective_initial,
        max_peers=max_peers,
    )


def create_adaptive_rate_limiter(
    base_rate: float = 10.0,
    max_rate: float = 100.0,
    min_rate: float = 1.0,
    adaptation_factor: float = 0.1,
    scope: RateLimitScope = RateLimitScope.GLOBAL,
) -> RateLimiter:
    """
    Create an adaptive rate limiter.

    Args:
        base_rate: Base rate for adaptive limiting
        max_rate: Maximum rate for adaptive limiting
        min_rate: Minimum rate for adaptive limiting
        adaptation_factor: Adaptation factor
        scope: Rate limiting scope

    Returns:
        RateLimiter: Configured adaptive rate limiter

    """
    config = RateLimitConfig(
        strategy=RateLimitStrategy.ADAPTIVE,
        scope=scope,
        refill_rate=base_rate,
        capacity=max_rate,
        initial_tokens=0.0,
        base_rate=base_rate,
        max_rate=max_rate,
        min_rate=min_rate,
        adaptation_factor=adaptation_factor,
    )
    return RateLimiter(config)
