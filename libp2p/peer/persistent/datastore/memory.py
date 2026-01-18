"""
In-memory datastore implementation.

This provides a simple in-memory datastore for testing and development.
"""

from collections.abc import Iterator

import trio

from .base import IBatch, IBatchingDatastore


class MemoryBatch(IBatch):
    """In-memory batch implementation."""

    def __init__(self, datastore: "MemoryDatastore"):
        self.datastore = datastore
        self.operations: list[tuple[str, bytes, bytes | None]] = []

    async def put(self, key: bytes, value: bytes) -> None:
        """Add a put operation to the batch."""
        self.operations.append(("put", key, value))

    async def delete(self, key: bytes) -> None:
        """Add a delete operation to the batch."""
        self.operations.append(("delete", key, None))

    async def commit(self) -> None:
        """Commit all operations in the batch."""
        for op_type, key, value in self.operations:
            if op_type == "put":
                if value is None:
                    raise ValueError("Cannot put None value in memory datastore")
                self.datastore._data[key] = value
            elif op_type == "delete":
                self.datastore._data.pop(key, None)
        self.operations.clear()


class MemoryDatastore(IBatchingDatastore):
    """
    In-memory datastore implementation.

    This is useful for testing and development scenarios where persistence
    is not required.
    """

    def __init__(self) -> None:
        self._data: dict[bytes, bytes] = {}
        self._lock = trio.Lock()

    async def get(self, key: bytes) -> bytes | None:
        """Retrieve a value by key."""
        async with self._lock:
            return self._data.get(key)

    async def put(self, key: bytes, value: bytes) -> None:
        """Store a key-value pair."""
        async with self._lock:
            self._data[key] = value

    async def delete(self, key: bytes) -> None:
        """Delete a key-value pair."""
        async with self._lock:
            self._data.pop(key, None)

    async def has(self, key: bytes) -> bool:
        """Check if a key exists."""
        async with self._lock:
            return key in self._data

    def query(self, prefix: bytes) -> Iterator[tuple[bytes, bytes]]:
        """Query for keys with a given prefix."""
        # Note: This is not thread-safe, but for in-memory datastore it's acceptable
        for key, value in self._data.items():
            if key.startswith(prefix):
                yield (key, value)

    async def close(self) -> None:
        """Close the datastore and clean up resources."""
        async with self._lock:
            self._data.clear()

    async def sync(self, prefix: bytes) -> None:
        """Sync any pending writes to disk (no-op for in-memory)."""
        pass

    async def batch(self) -> MemoryBatch:
        """Create a new batch for batched operations."""
        return MemoryBatch(self)
