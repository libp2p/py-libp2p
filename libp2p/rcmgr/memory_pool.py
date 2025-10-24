"""
Pre-allocated memory pool for resource management.

This module provides a memory pool implementation that pre-allocates
memory blocks to avoid allocation overhead in hot paths.
"""

from __future__ import annotations

from collections import deque
import threading


class MemoryPool:
    """
    Pre-allocated memory pool to avoid allocation overhead.

    This pool pre-allocates memory blocks of a fixed size to avoid
    the overhead of dynamic memory allocation in hot paths.
    """

    def __init__(
        self, block_size: int, initial_blocks: int = 1000, max_blocks: int | None = None
    ) -> None:
        """
        Initialize the memory pool.

        Args:
            block_size: Size of each memory block in bytes
            initial_blocks: Number of blocks to pre-allocate
            max_blocks: Maximum number of blocks in the pool (None for unlimited)

        """
        self.block_size = block_size
        self.max_blocks = max_blocks
        self._pool: deque[bytearray] = deque()
        self._lock = threading.RLock()
        self._total_allocated = 0
        self._total_created = 0

        # Pre-allocate blocks
        for _ in range(initial_blocks):
            self._pool.append(bytearray(block_size))
            self._total_created += 1

    def acquire(self) -> bytearray | None:
        """
        Acquire a memory block from the pool.

        Returns:
            Memory block or None if pool is exhausted

        """
        with self._lock:
            if self._pool:
                block = self._pool.popleft()
                self._total_allocated += 1
                return block

            # Create new block if under limit
            if self.max_blocks is None or self._total_created < self.max_blocks:
                try:
                    block = bytearray(self.block_size)
                    self._total_created += 1
                    self._total_allocated += 1
                    return block
                except MemoryError:
                    return None

            return None

    def release(self, block: bytearray) -> None:
        """
        Release a memory block back to the pool.

        Args:
            block: Memory block to release

        """
        if len(block) != self.block_size:
            # Block size mismatch, can't reuse
            return

        with self._lock:
            # Zero out the block for security
            block[:] = b"\x00" * self.block_size

            # Only add back to pool if we have space
            if len(self._pool) < (self.max_blocks or self._total_created):
                self._pool.append(block)

    def get_stats(self) -> dict[str, int | float | None]:
        """
        Get pool statistics.

        Returns:
            Dictionary with pool statistics

        """
        with self._lock:
            return {
                "pool_size": len(self._pool),
                "total_allocated": self._total_allocated,
                "total_created": self._total_created,
                "block_size": self.block_size,
                "max_blocks": self.max_blocks,
                "utilization": (
                    self._total_allocated / self._total_created
                    if self._total_created > 0
                    else 0.0
                ),
            }

    def clear(self) -> None:
        """Clear all blocks from the pool."""
        with self._lock:
            self._pool.clear()
            self._total_allocated = 0
            self._total_created = 0

    def __len__(self) -> int:
        """Get the number of available blocks in the pool."""
        with self._lock:
            return len(self._pool)

    def __bool__(self) -> bool:
        """Check if pool has any available blocks."""
        return len(self) > 0
