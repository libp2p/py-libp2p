"""
Circuit breaker pattern for resource management.

This module provides a circuit breaker implementation to prevent
cascading failures in resource management operations.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
import time
from typing import Any


class CircuitBreakerState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerError(Exception):
    """Exception raised when circuit breaker is open."""

    pass


class CircuitBreaker:
    """
    Circuit breaker for resource management.

    This circuit breaker prevents cascading failures by opening
    the circuit when failure threshold is exceeded.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        timeout: float = 60.0,
        expected_exception: type[Exception] = Exception,
    ) -> None:
        """
        Initialize the circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            timeout: Time in seconds before attempting to close circuit
            expected_exception: Exception type to count as failures

        """
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.expected_exception = expected_exception

        self.failure_count = 0
        self.last_failure_time: float | None = None
        self.state = CircuitBreakerState.CLOSED

    def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """
        Execute function with circuit breaker protection.

        Args:
            func: Function to execute
            args: Function arguments
            kwargs: Function keyword arguments

        Returns:
            Function result

        Raises:
            CircuitBreakerError: If circuit is open
            Exception: If function raises an exception

        """
        if self.state == CircuitBreakerState.OPEN:
            if self._should_attempt_reset():
                self.state = CircuitBreakerState.HALF_OPEN
            else:
                raise CircuitBreakerError("Circuit breaker is open")

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception as e:
            self._on_failure()
            raise e

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset."""
        if self.last_failure_time is None:
            return True
        return time.time() - self.last_failure_time >= self.timeout

    def _on_success(self) -> None:
        """Handle successful operation."""
        if self.state == CircuitBreakerState.HALF_OPEN:
            self.state = CircuitBreakerState.CLOSED
            self.failure_count = 0

    def _on_failure(self) -> None:
        """Handle failed operation."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            self.state = CircuitBreakerState.OPEN

    def get_stats(self) -> dict[str, Any]:
        """
        Get circuit breaker statistics.

        Returns:
            Dictionary with circuit breaker stats

        """
        return {
            "state": self.state.value,
            "failure_count": self.failure_count,
            "failure_threshold": self.failure_threshold,
            "timeout": self.timeout,
            "last_failure_time": self.last_failure_time,
            "time_since_last_failure": (
                time.time() - self.last_failure_time if self.last_failure_time else None
            ),
        }

    def reset(self) -> None:
        """Reset the circuit breaker to closed state."""
        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.last_failure_time = None

    def is_open(self) -> bool:
        """Check if circuit breaker is open."""
        return self.state == CircuitBreakerState.OPEN

    def is_closed(self) -> bool:
        """Check if circuit breaker is closed."""
        return self.state == CircuitBreakerState.CLOSED

    def is_half_open(self) -> bool:
        """Check if circuit breaker is half-open."""
        return self.state == CircuitBreakerState.HALF_OPEN
