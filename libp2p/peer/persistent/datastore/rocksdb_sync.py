"""
Synchronous RocksDB datastore implementation for persistent peer storage.

This provides a synchronous RocksDB-based datastore for advanced features and
high performance. RocksDB provides compression, bloom filters, and excellent
performance for write-heavy workloads.
"""

from collections.abc import Iterator
import importlib
from pathlib import Path
import threading
from typing import Any

from .base_sync import IBatchingDatastoreSync, IBatchSync


class RocksDBBatchSync(IBatchSync):
    """Synchronous RocksDB batch implementation."""

    def __init__(self, db: "RocksDBDatastoreSync"):
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
                    raise ValueError("RocksDB database is not initialized")

                rocksdb = self.db._rocksdb
                write_batch = rocksdb.WriteBatch()

                for operation, key, value in self.operations:
                    if operation == "put":
                        write_batch.put(key, value)
                    elif operation == "delete":
                        write_batch.delete(key)

                # Write the batch atomically
                db.write(write_batch)
            except Exception as e:
                raise e
            finally:
                self.operations.clear()


class RocksDBDatastoreSync(IBatchingDatastoreSync):
    """
    Synchronous RocksDB-based datastore implementation.

    This provides advanced persistent storage using RocksDB with features like
    compression, bloom filters, and high performance for write-heavy workloads.
    """

    def __init__(self, path: str | Path, **options: Any):
        """
        Initialize synchronous RocksDB datastore.

        Args:
            path: Path to the RocksDB database directory
            **options: Additional RocksDB options

        """
        self.path = Path(path)
        self.options = options
        self.db: Any = None
        self._lock = threading.Lock()
        self._rocksdb: Any = None
        self._ensure_connection()

    def _ensure_connection(self) -> None:
        """Ensure database connection is established."""
        if self.db is None:
            with self._lock:
                if self.db is None:
                    try:
                        # Import RocksDB (python-rocksdb)
                        self._rocksdb = importlib.import_module("rocksdb")
                    except ImportError as e:
                        raise ImportError(
                            "RocksDB support requires 'python-rocksdb' package. "
                            "Install it with: pip install python-rocksdb"
                        ) from e

                    # Create directory if it doesn't exist
                    self.path.mkdir(parents=True, exist_ok=True)

                    # Set up RocksDB options
                    opts = self._rocksdb.Options()
                    opts.create_if_missing = True
                    opts.max_open_files = 300000
                    opts.write_buffer_size = 67108864
                    opts.max_write_buffer_number = 3
                    opts.target_file_size_base = 67108864

                    # Apply user-provided options
                    for key, value in self.options.items():
                        if hasattr(opts, key):
                            setattr(opts, key, value)

                    # Open RocksDB database
                    # pyrefly can't infer types for dynamically imported modules
                    self.db = self._rocksdb.DB(str(self.path), opts)  # type: ignore[missing-attribute]

    def get(self, key: bytes) -> bytes | None:
        """Retrieve a value by key."""
        self._ensure_connection()
        if self.db is None:
            raise ValueError("RocksDB database is not initialized")

        with self._lock:
            return self.db.get(key)

    def put(self, key: bytes, value: bytes) -> None:
        """Store a key-value pair."""
        self._ensure_connection()
        if self.db is None:
            raise ValueError("RocksDB database is not initialized")

        with self._lock:
            self.db.put(key, value)

    def delete(self, key: bytes) -> None:
        """Delete a key-value pair."""
        self._ensure_connection()
        if self.db is None:
            raise ValueError("RocksDB database is not initialized")

        with self._lock:
            self.db.delete(key)

    def has(self, key: bytes) -> bool:
        """Check if a key exists."""
        self._ensure_connection()
        if self.db is None:
            raise ValueError("RocksDB database is not initialized")

        with self._lock:
            return self.db.get(key) is not None

    def query(self, prefix: bytes = b"") -> Iterator[tuple[bytes, bytes]]:
        """
        Query key-value pairs with optional prefix.
        """
        self._ensure_connection()
        if self.db is None:
            raise ValueError("RocksDB database is not initialized")

        with self._lock:
            # Create iterator
            iterator = self.db.iterkeys()
            iterator.seek_to_first()

            try:
                for key in iterator:
                    if not prefix or key.startswith(prefix):
                        value = self.db.get(key)
                        if value is not None:
                            yield key, value
            finally:
                # RocksDB iterators are automatically cleaned up
                pass

    def batch(self) -> IBatchSync:
        """Create a new batch for atomic operations."""
        self._ensure_connection()
        if self.db is None:
            raise ValueError("RocksDB database is not initialized")
        return RocksDBBatchSync(self)

    def sync(self, prefix: bytes) -> None:
        """Flush pending writes to disk."""
        if self.db is not None:
            with self._lock:
                # Force a sync to disk
                self.db.flush()

    def close(self) -> None:
        """Close the datastore connection."""
        with self._lock:
            if self.db:
                self.db.close()
                self.db = None

    def __enter__(self) -> "RocksDBDatastoreSync":
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
