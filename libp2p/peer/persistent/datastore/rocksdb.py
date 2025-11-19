"""
RocksDB datastore implementation for persistent peer storage.

This provides a RocksDB-based datastore for high-performance persistent storage.
RocksDB is a persistent key-value store for fast storage based
on Log-Structured Merge Trees.
"""

from collections.abc import Iterator
import importlib
from pathlib import Path
from typing import Any

import trio

from .base import IBatch, IBatchingDatastore


class RocksDBBatch(IBatch):
    """RocksDB batch implementation."""

    def __init__(self, db: "RocksDBDatastore"):
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
                raise ValueError("RocksDB database is not initialized")
            write_batch = db.WriteBatch()

            for operation, key, value in self.operations:
                if operation == "put":
                    write_batch.put(key, value)
                elif operation == "delete":
                    write_batch.delete(key)

            # Write the batch atomically
            db.write(write_batch)
        except Exception as e:
            raise e

    async def discard(self) -> None:
        """Discard all operations in the batch."""
        self.operations.clear()


class RocksDBDatastore(IBatchingDatastore):
    """
    RocksDB-based datastore implementation.

    This provides persistent storage using RocksDB, which offers advanced features
    like compression, bloom filters, and high performance for write-heavy workloads.
    """

    def __init__(self, path: str | Path):
        """
        Initialize RocksDB datastore.

        Args:
            path: Path to the RocksDB database directory

        """
        self.path = Path(path)
        self.db: Any | None = None
        self._lock = trio.Lock()

    async def _ensure_connection(self) -> None:
        """Ensure database connection is established."""
        if self.db is None:
            async with self._lock:
                if self.db is None:
                    try:
                        rocksdb = importlib.import_module("rocksdb")

                        # Create directory if it doesn't exist
                        self.path.mkdir(parents=True, exist_ok=True)

                        # Configure RocksDB options
                        opts = rocksdb.Options()
                        opts.create_if_missing = True
                        opts.max_open_files = 300000
                        opts.write_buffer_size = 67108864
                        opts.max_write_buffer_number = 3
                        opts.target_file_size_base = 67108864

                        self.db = rocksdb.DB(str(self.path), opts)
                    except ImportError:
                        raise ImportError(
                            "RocksDB support requires 'python-rocksdb' package. "
                            "Install with: pip install python-rocksdb"
                        )

    async def get(self, key: bytes) -> bytes | None:
        """Retrieve a value by key."""
        await self._ensure_connection()
        try:
            if self.db is None:
                raise ValueError("RocksDB database is not initialized")
            return self.db.get(key)
        except Exception:
            return None

    async def put(self, key: bytes, value: bytes) -> None:
        """Store a key-value pair."""
        await self._ensure_connection()
        if self.db is None:
            raise ValueError("RocksDB database is not initialized")
        self.db.put(key, value)

    async def delete(self, key: bytes) -> None:
        """Delete a key-value pair."""
        await self._ensure_connection()
        if self.db is None:
            raise ValueError("RocksDB database is not initialized")
        self.db.delete(key)

    async def has(self, key: bytes) -> bool:
        """Check if a key exists."""
        await self._ensure_connection()
        if self.db is None:
            raise ValueError("RocksDB database is not initialized")
        return self.db.get(key) is not None

    def query(self, prefix: bytes = b"") -> Iterator[tuple[bytes, bytes]]:
        """Query key-value pairs with optional prefix."""
        # query is synchronous per interface; ensure DB is open sync if needed
        if self.db is None:
            try:
                rocksdb = importlib.import_module("rocksdb")

                self.path.mkdir(parents=True, exist_ok=True)
                opts = rocksdb.Options()
                opts.create_if_missing = True
                opts.max_open_files = 300000
                opts.write_buffer_size = 67108864
                opts.max_write_buffer_number = 3
                opts.target_file_size_base = 67108864
                self.db = rocksdb.DB(str(self.path), opts)
            except Exception:
                # If we cannot init synchronously, yield nothing
                yield from ()

        if self.db is None:
            raise ValueError("RocksDB database is not initialized")
        if prefix:
            iterator = self.db.iteritems(prefix=prefix)
        else:
            iterator = self.db.iteritems()

        yield from iterator

    async def batch(self) -> IBatch:
        """Create a new batch for atomic operations."""
        await self._ensure_connection()
        return RocksDBBatch(self)

    async def sync(self, prefix: bytes) -> None:
        """Flush pending writes to disk. RocksDB writes are durable; no-op."""
        await self._ensure_connection()

    async def close(self) -> None:
        """Close the datastore connection."""
        if self.db:
            self.db.close()
            self.db = None

    async def __aenter__(self) -> "RocksDBDatastore":
        """Async context manager entry."""
        return self

    async def __aexit__(
        self, exc_type: type, exc_val: Exception, exc_tb: object
    ) -> None:
        """Async context manager exit."""
        await self.close()
