"""
Connection rate limiter implementation using sliding window algorithm.

This module provides rate limiting for incoming connections to prevent
abuse and resource exhaustion, matching JavaScript libp2p behavior.

Reference: https://github.com/libp2p/js-libp2p/blob/main/packages/utils/src/rate-limiter.ts
"""

from collections import defaultdict
import logging
import time
from typing import Any

logger = logging.getLogger("libp2p.network.rate_limiter")


class RateLimitError(Exception):
    """Raised when rate limit is exceeded."""

    def __init__(
        self, message: str, consumed_points: int, remaining_points: int = 0
    ) -> None:
        """
        Initialize rate limit error.

        Parameters
        ----------
        message : str
            Error message
        consumed_points : int
            Number of points consumed
        remaining_points : int
            Number of points remaining

        """
        super().__init__(message)
        self.consumed_points = consumed_points
        self.remaining_points = remaining_points


class RateLimiter:
    """
    Rate limiter using sliding window algorithm.

    Tracks consumption of "points" (connection attempts) per key (host/peer)
    within a time window. Raises RateLimitError when limit is exceeded.
    """

    def __init__(
        self,
        points: int = 5,
        duration: float = 1.0,
        block_duration: float = 0.0,
    ):
        """
        Initialize rate limiter.

        Parameters
        ----------
        points : int
            Maximum points (connections) allowed per duration
        duration : float
            Time window in seconds
        block_duration : float
            Block duration in seconds when limit exceeded (0 = no blocking)

        """
        self.points = points
        self.duration = duration
        self.block_duration = block_duration

        # Storage: key -> list of (timestamp, points)
        self._storage: dict[str, list[tuple[float, int]]] = defaultdict(list)
        self._blocked_until: dict[str, float] = {}

    def consume(self, key: str, points_to_consume: int = 1) -> dict[str, Any]:
        """
        Consume points for a key.

        Parameters
        ----------
        key : str
            Rate limit key (e.g., host IP address)
        points_to_consume : int
            Number of points to consume

        Returns
        -------
        dict[str, Any]
            Result with consumed_points, remaining_points

        Raises
        ------
        RateLimitError
            If rate limit is exceeded

        """
        now = time.time()

        # Check if key is blocked
        if key in self._blocked_until:
            if now < self._blocked_until[key]:
                raise RateLimitError(
                    f"Rate limit exceeded for {key}",
                    consumed_points=self.points + 1,
                    remaining_points=0,
                )
            else:
                # Block expired, remove it
                del self._blocked_until[key]

        # Clean up old entries (outside duration window)
        window_start = now - self.duration
        records = self._storage[key]
        records[:] = [(ts, pts) for ts, pts in records if ts > window_start]

        # Calculate current consumption
        consumed_points = sum(pts for _, pts in records)

        # Add new consumption
        consumed_points += points_to_consume
        records.append((now, points_to_consume))

        # Update storage
        self._storage[key] = records

        remaining_points = max(self.points - consumed_points, 0)

        # Check if limit exceeded
        if consumed_points > self.points:
            # Block if block_duration > 0
            if self.block_duration > 0:
                self._blocked_until[key] = now + self.block_duration

            raise RateLimitError(
                f"Rate limit exceeded for {key}",
                consumed_points=consumed_points,
                remaining_points=remaining_points,
            )

        return {
            "consumed_points": consumed_points,
            "remaining_points": remaining_points,
        }

    def reset(self, key: str | None = None) -> None:
        """
        Reset rate limit for a key or all keys.

        Parameters
        ----------
        key : str | None
            Key to reset, or None to reset all

        """
        if key is None:
            self._storage.clear()
            self._blocked_until.clear()
        else:
            self._storage.pop(key, None)
            self._blocked_until.pop(key, None)


class ConnectionRateLimiter:
    """
    Rate limiter for incoming connections.

    Wraps RateLimiter with connection-specific configuration.
    """

    def __init__(
        self,
        points: int = 5,
        duration: float = 1.0,
        block_duration: float = 0.0,
    ):
        """
        Initialize connection rate limiter.

        Parameters
        ----------
        points : int
            Maximum connections allowed per duration (default: 5 per second)
        duration : float
            Time window in seconds (default: 1.0)
        block_duration : float
            Block duration in seconds when limit exceeded

        """
        self._limiter = RateLimiter(
            points=points, duration=duration, block_duration=block_duration
        )

    def check_and_consume(self, host: str) -> bool:
        """
        Check and consume rate limit for a host.

        Parameters
        ----------
        host : str
            Host identifier (IP address)

        Returns
        -------
        bool
            True if connection allowed, False if rate limit exceeded

        """
        try:
            self._limiter.consume(host, points_to_consume=1)
            return True
        except RateLimitError as e:
            logger.debug(
                f"Rate limit exceeded for host {host}: "
                f"{e.consumed_points} points consumed"
            )
            return False

    def reset(self, host: str | None = None) -> None:
        """
        Reset rate limit for a host or all hosts.

        Parameters
        ----------
        host : str | None
            Host to reset, or None to reset all

        """
        self._limiter.reset(host)
