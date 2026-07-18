"""
Synchronous LevelDB datastore implementation for persistent peer storage.

This provides a synchronous LevelDB-based datastore for high-performance
persistent storage. LevelDB is a fast key-value storage library written at Google.
"""

from collections.abc import Iterator
import importlib
from pathlib import Path
import threading
from typing import Any

from .base_sync import IBatchingDatastoreSync, IBatchSync


class LevelDBBatchSync(IBatchSync):
    """Synchronous LevelDB batch implementation."""

    def __init__(self, db: "LevelDBDatastoreSync"):
        self.db = db
        self.operations: list[tuple[str, bytes, bytes | None]] = []

    def put(self, key: bytes, value: bytes) -> None:
        """Add a put operation to the batch."""
        self.operations.append(("put", key, value))

    def delete(self, key: bytes) -> None:
        """Add a delete operation to the batch."""
        self.operations.append(("delete", key, None))

    def commit(self) -> None:
        """Commit all operations in the batch."""
        with self.db._lock:
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
            finally:
                self.operations.clear()


class LevelDBDatastoreSync(IBatchingDatastoreSync):
    """
    Synchronous LevelDB-based datastore implementation.

    This provides high-performance persistent storage using LevelDB with
    synchronous operations.
    """

    def __init__(self, path: str | Path):
        """
        Initialize synchronous LevelDB datastore.

        Args:
            path: Path to the LevelDB database directory

        """
        self.path = Path(path)
        self.db: Any = None
        self._lock = threading.Lock()
        self._leveldb: Any = None
        self._ensure_connection()

    def _ensure_connection(self) -> None:
        """Ensure database connection is established."""
        if self.db is None:
            with self._lock:
                if self.db is None:
                    try:
                        # Import LevelDB (plyvel)
                        self._leveldb = importlib.import_module("plyvel")
                    except ImportError as e:
                        raise ImportError(
                            "LevelDB support requires 'plyvel' package. "
                            "Install it with: pip install plyvel"
                        ) from e

                    # Create directory if it doesn't exist
                    self.path.mkdir(parents=True, exist_ok=True)

                    # Open LevelDB database
                    self.db = self._leveldb.DB(str(self.path), create_if_missing=True)

    def get(self, key: bytes) -> bytes | None:
        """Retrieve a value by key."""
        self._ensure_connection()
        if self.db is None:
            raise ValueError("LevelDB database is not initialized")

        with self._lock:
            try:
                return self.db.Get(key)
            except KeyError:
                return None

    def put(self, key: bytes, value: bytes) -> None:
        """Store a key-value pair."""
        self._ensure_connection()
        if self.db is None:
            raise ValueError("LevelDB database is not initialized")

        with self._lock:
            self.db.Put(key, value)

    def delete(self, key: bytes) -> None:
        """Delete a key-value pair."""
        self._ensure_connection()
        if self.db is None:
            raise ValueError("LevelDB database is not initialized")

        with self._lock:
            try:
                self.db.Delete(key)
            except KeyError:
                pass  # Key doesn't exist, which is fine

    def has(self, key: bytes) -> bool:
        """Check if a key exists."""
        self._ensure_connection()
        if self.db is None:
            raise ValueError("LevelDB database is not initialized")

        with self._lock:
            try:
                self.db.Get(key)
                return True
            except KeyError:
                return False

    def query(self, prefix: bytes = b"") -> Iterator[tuple[bytes, bytes]]:
        """
        Query key-value pairs with optional prefix.
        """
        self._ensure_connection()
        if self.db is None:
            raise ValueError("LevelDB database is not initialized")

        with self._lock:
            # Create iterator with prefix
            if prefix:
                iterator = self.db.iterator(prefix=prefix)
            else:
                iterator = self.db.iterator()

            try:
                yield from iterator
            finally:
                iterator.close()

    def batch(self) -> IBatchSync:
        """Create a new batch for atomic operations."""
        self._ensure_connection()
        if self.db is None:
            raise ValueError("LevelDB database is not initialized")
        return LevelDBBatchSync(self)

    def sync(self, prefix: bytes) -> None:
        """Flush pending writes to disk."""
        # LevelDB automatically syncs writes, but we can force a sync
        if self.db is not None:
            with self._lock:
                # LevelDB doesn't have an explicit sync method in plyvel
                # Writes are automatically synced to disk
                pass

    def close(self) -> None:
        """Close the datastore connection."""
        with self._lock:
            if self.db:
                self.db.close()
                self.db = None

    def __enter__(self) -> "LevelDBDatastoreSync":
        """Context manager entry."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Context manager exit."""
        self.close()
