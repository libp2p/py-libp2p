"""
LevelDB datastore implementation for persistent peer storage.

This provides a LevelDB-based datastore for high-performance persistent storage.
LevelDB is a fast key-value storage library written at Google.
"""

from collections.abc import Iterator
import importlib
from pathlib import Path
from typing import Any

import trio

from .base import IBatch, IBatchingDatastore


class LevelDBBatch(IBatch):
    """LevelDB batch implementation."""

    def __init__(self, db: "LevelDBDatastore"):
        self.db = db
        self.operations: list[tuple[str, bytes, bytes | None]] = []

    async def put(self, key: bytes, value: bytes) -> None:
        """Add a put operation to the batch."""
        self.operations.append(("put", key, value))

    async def delete(self, key: bytes) -> None:
        """Add a delete operation to the batch."""
        self.operations.append(("delete", key, None))

    async def commit(self) -> None:
        """Commit all operations in the batch."""
        try:
            # Create a write batch
            db = self.db.db
            if db is None:
                raise ValueError("LevelDB database is not initialized")
            write_batch = db.WriteBatch()

            for operation, key, value in self.operations:
                if operation == "put":
                    write_batch.Put(key, value)
                elif operation == "delete":
                    write_batch.Delete(key)

            # Write the batch atomically
            db.Write(write_batch)
        except Exception as e:
            raise e

    async def discard(self) -> None:
        """Discard all operations in the batch."""
        self.operations.clear()


class LevelDBDatastore(IBatchingDatastore):
    """
    LevelDB-based datastore implementation.

    This provides persistent storage using LevelDB, which offers high performance
    and is widely used in distributed systems.
    """

    def __init__(self, path: str | Path):
        """
        Initialize LevelDB datastore.

        Args:
            path: Path to the LevelDB database directory

        """
        self.path = Path(path)
        self.db: Any | None = None
        self._lock = trio.Lock()
        self._closed = False

    async def _ensure_connection(self) -> None:
        """Ensure database connection is established."""
        if self.db is None:
            async with self._lock:
                if self.db is None:
                    try:
                        plyvel = importlib.import_module("plyvel")

                        # Create directory if it doesn't exist
                        self.path.mkdir(parents=True, exist_ok=True)

                        self.db = plyvel.DB(str(self.path), create_if_missing=True)
                    except ImportError:
                        raise ImportError(
                            "LevelDB support requires 'plyvel' package. "
                            "Install with: pip install plyvel"
                        )

    async def get(self, key: bytes) -> bytes | None:
        """Retrieve a value by key."""
        await self._ensure_connection()
        try:
            if self.db is None:
                raise ValueError("LevelDB database is not initialized")
            return self.db.get(key)
        except Exception:
            return None

    async def put(self, key: bytes, value: bytes) -> None:
        """Store a key-value pair."""
        await self._ensure_connection()
        if self.db is None:
            raise ValueError("LevelDB database is not initialized")
        self.db.put(key, value)

    async def delete(self, key: bytes) -> None:
        """Delete a key-value pair."""
        await self._ensure_connection()
        if self.db is None:
            raise ValueError("LevelDB database is not initialized")
        self.db.delete(key)

    async def has(self, key: bytes) -> bool:
        """Check if a key exists."""
        await self._ensure_connection()
        if self.db is None:
            raise ValueError("LevelDB database is not initialized")
        return self.db.get(key) is not None

    def query(self, prefix: bytes = b"") -> Iterator[tuple[bytes, bytes]]:
        """Query key-value pairs with optional prefix."""
        # Ensure DB exists synchronously if needed
        if self.db is None:
            try:
                plyvel = importlib.import_module("plyvel")

                self.path.mkdir(parents=True, exist_ok=True)
                self.db = plyvel.DB(str(self.path), create_if_missing=True)
            except Exception:
                yield from ()

        if self.db is None:
            raise ValueError("LevelDB database is not initialized")
        if prefix:
            iterator = self.db.iterator(prefix=prefix)
        else:
            iterator = self.db.iterator()

        yield from iterator

    async def batch(self) -> IBatch:
        """Create a new batch for atomic operations."""
        await self._ensure_connection()
        return LevelDBBatch(self)

    async def sync(self, prefix: bytes) -> None:
        """Flush pending writes to disk (no-op for plyvel default)."""
        await self._ensure_connection()

    async def close(self) -> None:
        """
        Close the datastore connection.

        This method is idempotent and can be called multiple times safely.
        """
        if self.db and not getattr(self, "_closed", False):
            try:
                self.db.close()
            finally:
                self.db = None
                self._closed = True

    async def __aenter__(self) -> "LevelDBDatastore":
        """Async context manager entry."""
        return self

    async def __aexit__(
        self, exc_type: type, exc_val: Exception, exc_tb: object
    ) -> None:
        """Async context manager exit."""
        await self.close()
