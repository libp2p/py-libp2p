"""
Token bucket rate limiter for resource management.

This module implements a token bucket rate limiter that provides
smooth rate limiting with burst capacity for production-ready
resource management.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any


@dataclass
class TokenBucketConfig:
    """Configuration for token bucket rate limiter."""

    # Rate limiting parameters
    refill_rate: float  # Tokens per second
    capacity: float  # Maximum tokens in bucket
    initial_tokens: float = 0.0  # Initial tokens in bucket

    # Burst handling
    allow_burst: bool = True  # Allow burst up to capacity
    burst_multiplier: float = 1.0  # Burst capacity multiplier

    # Time window parameters
    time_window_seconds: float = 1.0  # Time window for rate calculation
    min_interval_seconds: float = 0.001  # Minimum interval between refills

    # Monitoring parameters
    enable_monitoring: bool = True  # Enable monitoring and statistics
    max_history_size: int = 1000  # Maximum history size for monitoring

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
        if self.burst_multiplier < 1.0:
            raise ValueError("burst_multiplier must be >= 1.0")
        if self.time_window_seconds <= 0:
            raise ValueError("time_window_seconds must be positive")
        if self.min_interval_seconds <= 0:
            raise ValueError("min_interval_seconds must be positive")
        if self.max_history_size <= 0:
            raise ValueError("max_history_size must be positive")


@dataclass
class TokenBucketStats:
    """Statistics for token bucket rate limiter."""

    # Current state
    current_tokens: float
    last_refill_time: float
    total_requests: int
    allowed_requests: int
    denied_requests: int

    # Rate information
    refill_rate: float
    capacity: float
    effective_rate: float  # Current effective rate

    # Burst information
    burst_used: float
    burst_available: float

    # Time information
    time_since_last_refill: float
    next_refill_time: float

    def to_dict(self) -> dict[str, Any]:
        """Convert statistics to dictionary."""
        return {
            "current_tokens": self.current_tokens,
            "last_refill_time": self.last_refill_time,
            "total_requests": self.total_requests,
            "allowed_requests": self.allowed_requests,
            "denied_requests": self.denied_requests,
            "refill_rate": self.refill_rate,
            "capacity": self.capacity,
            "effective_rate": self.effective_rate,
            "burst_used": self.burst_used,
            "burst_available": self.burst_available,
            "time_since_last_refill": self.time_since_last_refill,
            "next_refill_time": self.next_refill_time,
        }


class TokenBucket:
    """
    Token bucket rate limiter implementation.

    This class implements a token bucket rate limiter that provides
    smooth rate limiting with burst capacity. It supports both
    strict rate limiting and burst handling.
    """

    def __init__(self, config: TokenBucketConfig):
        """
        Initialize token bucket rate limiter.

        Args:
            config: Token bucket configuration

        """
        self.config = config

        # Current state
        self._tokens: float = config.initial_tokens
        self._last_refill_time: float = time.time()

        # Statistics
        self._total_requests: int = 0
        self._allowed_requests: int = 0
        self._denied_requests: int = 0

        # History for monitoring
        self._request_history: list[tuple[float, bool]] = []
        self._refill_history: list[tuple[float, float]] = []

    def _refill_tokens(self, current_time: float) -> None:
        """
        Refill tokens based on elapsed time.

        Args:
            current_time: Current timestamp

        """
        if current_time <= self._last_refill_time:
            return

        # Calculate time elapsed
        time_elapsed = current_time - self._last_refill_time

        # Only refill if enough time has passed
        if time_elapsed < self.config.min_interval_seconds:
            return

        # Calculate tokens to add
        tokens_to_add = time_elapsed * self.config.refill_rate

        # Add tokens up to capacity
        self._tokens = min(self._tokens + tokens_to_add, self.config.capacity)

        # Update last refill time
        self._last_refill_time = current_time

        # Record refill for monitoring
        if self.config.enable_monitoring:
            self._refill_history.append((current_time, tokens_to_add))
            if len(self._refill_history) > self.config.max_history_size:
                self._refill_history.pop(0)

    def _cleanup_history(self) -> None:
        """Clean up old history entries."""
        if not self.config.enable_monitoring:
            return

        current_time = time.time()
        cutoff_time = current_time - self.config.time_window_seconds

        # Clean up request history by time window
        self._request_history = [
            (timestamp, allowed)
            for timestamp, allowed in self._request_history
            if timestamp > cutoff_time
        ]

        # Clean up request history by size limit
        if len(self._request_history) > self.config.max_history_size:
            self._request_history = self._request_history[
                -self.config.max_history_size :
            ]

        # Clean up refill history by time window
        self._refill_history = [
            (timestamp, tokens)
            for timestamp, tokens in self._refill_history
            if timestamp > cutoff_time
        ]

        # Clean up refill history by size limit
        if len(self._refill_history) > self.config.max_history_size:
            self._refill_history = self._refill_history[-self.config.max_history_size :]

    def try_consume(
        self, tokens: float = 1.0, current_time: float | None = None
    ) -> bool:
        """
        Try to consume tokens from the bucket.

        Args:
            tokens: Number of tokens to consume
            current_time: Current timestamp (optional)

        Returns:
            True if tokens were consumed, False otherwise

        """
        if current_time is None:
            current_time = time.time()

        # Refill tokens first
        self._refill_tokens(current_time)

        # Check if we have enough tokens
        if self._tokens >= tokens:
            # Consume tokens
            self._tokens -= tokens

            # Update statistics
            self._total_requests += 1
            self._allowed_requests += 1

            # Record for monitoring
            if self.config.enable_monitoring:
                self._request_history.append((current_time, True))
                self._cleanup_history()

            return True
        else:
            # Not enough tokens
            self._total_requests += 1
            self._denied_requests += 1

            # Record for monitoring
            if self.config.enable_monitoring:
                self._request_history.append((current_time, False))
                self._cleanup_history()

            return False

    def consume(self, tokens: float = 1.0, current_time: float | None = None) -> None:
        """
        Consume tokens from the bucket (raises exception if not enough).

        Args:
            tokens: Number of tokens to consume
            current_time: Current timestamp (optional)

        Raises:
            ValueError: If not enough tokens available

        """
        if not self.try_consume(tokens, current_time):
            raise ValueError(f"Not enough tokens available: {tokens} > {self._tokens}")

    def get_stats(self, current_time: float | None = None) -> TokenBucketStats:
        """
        Get current statistics for the token bucket.

        Args:
            current_time: Current timestamp (optional)

        Returns:
            TokenBucketStats: Current statistics

        """
        if current_time is None:
            current_time = time.time()

        # Refill tokens first
        self._refill_tokens(current_time)

        # Calculate effective rate
        effective_rate = 0.0
        if self._total_requests > 0:
            effective_rate = self._allowed_requests / self._total_requests

        # Calculate burst information
        burst_used = self.config.capacity - self._tokens
        burst_available = self._tokens

        # Calculate time information
        time_since_last_refill = current_time - self._last_refill_time
        next_refill_time = self._last_refill_time + self.config.min_interval_seconds

        return TokenBucketStats(
            current_tokens=self._tokens,
            last_refill_time=self._last_refill_time,
            total_requests=self._total_requests,
            allowed_requests=self._allowed_requests,
            denied_requests=self._denied_requests,
            refill_rate=self.config.refill_rate,
            capacity=self.config.capacity,
            effective_rate=effective_rate,
            burst_used=burst_used,
            burst_available=burst_available,
            time_since_last_refill=time_since_last_refill,
            next_refill_time=next_refill_time,
        )

    def get_history(self, time_window: float | None = None) -> dict[str, Any]:
        """
        Get request history for monitoring.

        Args:
            time_window: Time window in seconds (optional)

        Returns:
            Dictionary with request history

        """
        if not self.config.enable_monitoring:
            return {"enabled": False}

        current_time = time.time()
        if time_window is None:
            time_window = self.config.time_window_seconds

        cutoff_time = current_time - time_window

        # Filter history by time window
        recent_requests = [
            (timestamp, allowed)
            for timestamp, allowed in self._request_history
            if timestamp > cutoff_time
        ]

        recent_refills = [
            (timestamp, tokens)
            for timestamp, tokens in self._refill_history
            if timestamp > cutoff_time
        ]

        # Calculate statistics
        total_requests = len(recent_requests)
        allowed_requests = sum(1 for _, allowed in recent_requests if allowed)
        denied_requests = total_requests - allowed_requests

        return {
            "enabled": True,
            "time_window": time_window,
            "total_requests": total_requests,
            "allowed_requests": allowed_requests,
            "denied_requests": denied_requests,
            "allow_rate": (
                allowed_requests / total_requests if total_requests > 0 else 0.0
            ),
            "recent_requests": recent_requests,
            "recent_refills": recent_refills,
        }

    def reset(self) -> None:
        """Reset the token bucket to initial state."""
        self._tokens = self.config.initial_tokens
        self._last_refill_time = time.time()
        self._total_requests = 0
        self._allowed_requests = 0
        self._denied_requests = 0
        self._request_history.clear()
        self._refill_history.clear()

    def __str__(self) -> str:
        """String representation of token bucket."""
        stats = self.get_stats()
        return (
            f"TokenBucket(tokens={stats.current_tokens:.2f}/"
            f"{stats.capacity:.2f}, rate={stats.refill_rate:.2f}/s, "
            f"allowed={stats.allowed_requests}/{stats.total_requests})"
        )


# Factory functions
def create_token_bucket(
    refill_rate: float,
    capacity: float,
    initial_tokens: float = 0.0,
    allow_burst: bool = True,
    burst_multiplier: float = 1.0,
    time_window_seconds: float = 1.0,
    min_interval_seconds: float = 0.001,
    enable_monitoring: bool = True,
    max_history_size: int = 1000,
) -> TokenBucket:
    """
    Create a token bucket rate limiter.

    Args:
        refill_rate: Tokens per second
        capacity: Maximum tokens in bucket
        initial_tokens: Initial tokens in bucket
        allow_burst: Allow burst up to capacity
        burst_multiplier: Burst capacity multiplier
        time_window_seconds: Time window for rate calculation
        min_interval_seconds: Minimum interval between refills
        enable_monitoring: Enable monitoring and statistics
        max_history_size: Maximum history size for monitoring

    Returns:
        TokenBucket: Configured token bucket rate limiter

    """
    config = TokenBucketConfig(
        refill_rate=refill_rate,
        capacity=capacity,
        initial_tokens=initial_tokens,
        allow_burst=allow_burst,
        burst_multiplier=burst_multiplier,
        time_window_seconds=time_window_seconds,
        min_interval_seconds=min_interval_seconds,
        enable_monitoring=enable_monitoring,
        max_history_size=max_history_size,
    )
    return TokenBucket(config)


def create_strict_token_bucket(
    refill_rate: float,
    capacity: float,
    initial_tokens: float = 0.0,
) -> TokenBucket:
    """
    Create a strict token bucket rate limiter (no burst).

    Args:
        refill_rate: Tokens per second
        capacity: Maximum tokens in bucket
        initial_tokens: Initial tokens in bucket

    Returns:
        TokenBucket: Configured strict token bucket rate limiter

    """
    return create_token_bucket(
        refill_rate=refill_rate,
        capacity=capacity,
        initial_tokens=initial_tokens,
        allow_burst=False,
        burst_multiplier=1.0,
    )


def create_burst_token_bucket(
    refill_rate: float,
    capacity: float,
    initial_tokens: float = 0.0,
    burst_multiplier: float = 2.0,
) -> TokenBucket:
    """
    Create a burst-capable token bucket rate limiter.

    Args:
        refill_rate: Tokens per second
        capacity: Maximum tokens in bucket
        initial_tokens: Initial tokens in bucket
        burst_multiplier: Burst capacity multiplier

    Returns:
        TokenBucket: Configured burst-capable token bucket rate limiter

    """
    return create_token_bucket(
        refill_rate=refill_rate,
        capacity=capacity,
        initial_tokens=initial_tokens,
        allow_burst=True,
        burst_multiplier=burst_multiplier,
    )
