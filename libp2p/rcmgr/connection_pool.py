"""
High-performance connection pool for resource management.

This module provides a connection pool implementation that pre-allocates
connections to avoid allocation overhead in hot paths.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
import threading
from typing import Generic, TypeVar

T = TypeVar("T")


class ConnectionPool(Generic[T]):
    """
    High-performance connection pool with pre-allocation.

    This pool pre-allocates connections to avoid allocation overhead
    in hot paths, providing O(1) acquire/release operations.
    """

    def __init__(
        self,
        max_size: int,
        pre_allocate: bool = True,
        connection_factory: Callable[[], T] | None = None,
    ) -> None:
        """
        Initialize the connection pool.

        Args:
            max_size: Maximum number of connections in the pool
            pre_allocate: Whether to pre-allocate connections
            connection_factory: Factory function to create new connections

        """
        self.max_size = max_size
        self.connection_factory = connection_factory
        self._pool: deque[T] = deque()
        self._active: set[T] = set()
        self._lock = threading.RLock()
        self._total_created = 0

        if pre_allocate:
            self._pre_allocate_connections()

    def _pre_allocate_connections(self) -> None:
        """Pre-allocate connections for zero-allocation hot path."""
        if self.connection_factory is None:
            return

        if self.connection_factory is not None:
            factory = self.connection_factory
            pre_alloc_count = min(100, self.max_size // 4)
            for _ in range(pre_alloc_count):
                try:
                    conn = factory()
                    self._pool.append(conn)
                    self._total_created += 1
                except Exception:
                    # If factory fails, stop pre-allocating
                    break

    def acquire(self) -> T | None:
        """
        Acquire a connection from the pool.

        Returns:
            Connection object or None if pool is exhausted

        """
        with self._lock:
            # Try to get from pre-allocated pool
            if self._pool:
                conn = self._pool.popleft()
                self._active.add(conn)
                return conn

            # Create new connection if under limit
            if len(self._active) < self.max_size:
                if self.connection_factory is not None:
                    try:
                        conn = self.connection_factory()
                        self._active.add(conn)
                        self._total_created += 1
                        return conn
                    except Exception:
                        return None
                else:
                    # No factory provided, can't create new connections
                    return None

            return None

    def release(self, conn: T) -> None:
        """
        Release a connection back to the pool.

        Args:
            conn: Connection to release

        """
        with self._lock:
            self._active.discard(conn)

            # Only add back to pool if we have space
            if len(self._pool) < self.max_size // 2:
                self._pool.append(conn)

    def get_stats(self) -> dict[str, int | float]:
        """
        Get pool statistics.

        Returns:
            Dictionary with pool statistics

        """
        with self._lock:
            return {
                "pool_size": len(self._pool),
                "active_connections": len(self._active),
                "total_created": self._total_created,
                "max_size": self.max_size,
                "utilization": (
                    len(self._active) / self.max_size if self.max_size > 0 else 0.0
                ),
            }

    def clear(self) -> None:
        """Clear all connections from the pool."""
        with self._lock:
            self._pool.clear()
            self._active.clear()
            self._total_created = 0

    def __len__(self) -> int:
        """Get the number of active connections."""
        with self._lock:
            return len(self._active)

    def __bool__(self) -> bool:
        """Check if pool has any active connections."""
        return len(self) > 0
