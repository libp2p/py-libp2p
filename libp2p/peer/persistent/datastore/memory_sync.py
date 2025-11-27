"""
Synchronous in-memory datastore implementation for persistent peer storage.

This provides a synchronous in-memory datastore for testing and development
scenarios where persistence is not required.
"""

from collections.abc import Iterator
import threading

from .base_sync import IBatchingDatastoreSync, IBatchSync


class MemoryBatchSync(IBatchSync):
    """Synchronous in-memory batch implementation."""

    def __init__(self, datastore: "MemoryDatastoreSync"):
        self.datastore = datastore
        self.operations: list[tuple[str, bytes, bytes | None]] = []

    def put(self, key: bytes, value: bytes) -> None:
        """Add a put operation to the batch."""
        self.operations.append(("put", key, value))

    def delete(self, key: bytes) -> None:
        """Add a delete operation to the batch."""
        self.operations.append(("delete", key, None))

    def commit(self) -> None:
        """Commit all operations in the batch."""
        with self.datastore._lock:
            for operation, key, value in self.operations:
                if operation == "put" and value is not None:
                    self.datastore._data[key] = value
                elif operation == "delete":
                    self.datastore._data.pop(key, None)

        self.operations.clear()


class MemoryDatastoreSync(IBatchingDatastoreSync):
    """
    Synchronous in-memory datastore implementation.

    This is useful for testing and development scenarios where persistence
    is not required and synchronous operations are preferred.
    """

    def __init__(self) -> None:
        self._data: dict[bytes, bytes] = {}
        self._lock = threading.Lock()

    def get(self, key: bytes) -> bytes | None:
        """Retrieve a value by key."""
        with self._lock:
            return self._data.get(key)

    def put(self, key: bytes, value: bytes) -> None:
        """Store a key-value pair."""
        with self._lock:
            self._data[key] = value

    def delete(self, key: bytes) -> None:
        """Delete a key-value pair."""
        with self._lock:
            self._data.pop(key, None)

    def has(self, key: bytes) -> bool:
        """Check if a key exists."""
        with self._lock:
            return key in self._data

    def query(self, prefix: bytes) -> Iterator[tuple[bytes, bytes]]:
        """Query for keys with a given prefix."""
        with self._lock:
            # Create a copy to avoid issues with concurrent modification
            data_copy: dict[bytes, bytes] = dict(self._data)

        for key, value in data_copy.items():
            if key.startswith(prefix):
                yield (key, value)

    def close(self) -> None:
        """Close the datastore and clean up resources."""
        with self._lock:
            self._data.clear()

    def sync(self, prefix: bytes) -> None:
        """Sync any pending writes to disk (no-op for in-memory)."""
        pass

    def batch(self) -> MemoryBatchSync:
        """Create a new batch for batched operations."""
        return MemoryBatchSync(self)
