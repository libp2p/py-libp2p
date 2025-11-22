"""
Synchronous SQLite datastore implementation for persistent peer storage.

This provides a synchronous SQLite-based datastore for persistent storage.
"""

from collections.abc import Iterator
from pathlib import Path
import sqlite3
import threading

from .base_sync import IBatchingDatastoreSync, IBatchSync


class SQLiteBatchSync(IBatchSync):
    """Synchronous SQLite batch implementation."""

    def __init__(self, connection: sqlite3.Connection, lock: threading.RLock):
        self.connection = connection
        self.lock = lock
        self.operations: list[tuple[str, bytes, bytes | None]] = []

    def put(self, key: bytes, value: bytes) -> None:
        """Add a put operation to the batch."""
        self.operations.append(("put", key, value))

    def delete(self, key: bytes) -> None:
        """Add a delete operation to the batch."""
        self.operations.append(("delete", key, None))

    def commit(self) -> None:
        """Commit all operations in the batch."""
        with self.lock:
            try:
                cursor = self.connection.cursor()
                for operation, key, value in self.operations:
                    if operation == "put":
                        cursor.execute(
                            "INSERT OR REPLACE INTO datastore "
                            "(key, value) VALUES (?, ?)",
                            (key, value),
                        )
                    elif operation == "delete":
                        cursor.execute("DELETE FROM datastore WHERE key = ?", (key,))
                self.connection.commit()
            except Exception as e:
                self.connection.rollback()
                raise e
            finally:
                self.operations.clear()


class SQLiteDatastoreSync(IBatchingDatastoreSync):
    """
    Synchronous SQLite-based datastore implementation.

    This provides persistent storage using SQLite database files with
    synchronous operations.
    """

    def __init__(self, path: str | Path):
        """
        Initialize synchronous SQLite datastore.

        Args:
            path: Path to the SQLite database file

        """
        self.path = Path(path)
        self.connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()  # Use RLock for better thread safety
        self._closed = False
        self._ensure_connection()

    def _ensure_connection(self) -> None:
        """
        Ensure database connection is established.

        :raises RuntimeError: If datastore is closed
        :raises sqlite3.Error: If database connection fails
        """
        if self._closed:
            raise RuntimeError("Datastore is closed")

        if self.connection is None:
            with self._lock:
                if self.connection is None:
                    # Create directory if it doesn't exist
                    self.path.parent.mkdir(parents=True, exist_ok=True)

                    # Set appropriate file permissions (readable/writable by owner only)
                    if not self.path.exists():
                        self.path.touch(mode=0o600)

                    self.connection = sqlite3.connect(
                        str(self.path),
                        check_same_thread=False,
                        timeout=30.0,  # Add timeout for database locks
                    )

                    # Enable WAL mode for better concurrency
                    cursor = self.connection.cursor()
                    cursor.execute("PRAGMA journal_mode=WAL")
                    cursor.execute(
                        "PRAGMA synchronous=NORMAL"
                    )  # Balance between safety and performance
                    cursor.execute("PRAGMA cache_size=10000")  # Increase cache size
                    cursor.execute(
                        "PRAGMA temp_store=MEMORY"
                    )  # Use memory for temp storage

                    # Create table if it doesn't exist
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS datastore (
                            key BLOB PRIMARY KEY,
                            value BLOB NOT NULL
                        )
                    """)
                    self.connection.commit()

    def get(self, key: bytes) -> bytes | None:
        """Retrieve a value by key."""
        self._ensure_connection()
        if self.connection is None:
            raise ValueError("SQLite connection is not initialized")

        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute("SELECT value FROM datastore WHERE key = ?", (key,))
            result = cursor.fetchone()
            return result[0] if result else None

    def put(self, key: bytes, value: bytes) -> None:
        """Store a key-value pair."""
        self._ensure_connection()
        if self.connection is None:
            raise ValueError("SQLite connection is not initialized")

        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO datastore (key, value) VALUES (?, ?)",
                (key, value),
            )
            self.connection.commit()

    def delete(self, key: bytes) -> None:
        """Delete a key-value pair."""
        self._ensure_connection()
        if self.connection is None:
            raise ValueError("SQLite connection is not initialized")

        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute("DELETE FROM datastore WHERE key = ?", (key,))
            self.connection.commit()

    def has(self, key: bytes) -> bool:
        """Check if a key exists."""
        self._ensure_connection()
        if self.connection is None:
            raise ValueError("SQLite connection is not initialized")

        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute("SELECT 1 FROM datastore WHERE key = ?", (key,))
            return cursor.fetchone() is not None

    def query(self, prefix: bytes = b"") -> Iterator[tuple[bytes, bytes]]:
        """
        Query key-value pairs with optional prefix.
        """
        self._ensure_connection()
        if self.connection is None:
            raise ValueError("SQLite connection is not initialized")

        with self._lock:
            cursor = self.connection.cursor()
            if prefix:
                cursor.execute(
                    "SELECT key, value FROM datastore WHERE key LIKE ?",
                    (prefix + b"%",),
                )
            else:
                cursor.execute("SELECT key, value FROM datastore")

            for row in cursor:
                yield row[0], row[1]

    def batch(self) -> IBatchSync:
        """Create a new batch for atomic operations."""
        self._ensure_connection()
        if self.connection is None:
            raise ValueError("SQLite connection is not initialized")
        return SQLiteBatchSync(self.connection, self._lock)

    def sync(self, prefix: bytes) -> None:
        """Flush pending writes to disk (commit current transaction)."""
        self._ensure_connection()
        if self.connection is None:
            raise ValueError("SQLite connection is not initialized")

        with self._lock:
            self.connection.commit()

    def close(self) -> None:
        """
        Close the datastore connection.

        This method is idempotent and can be called multiple times safely.
        """
        with self._lock:
            if self.connection and not self._closed:
                try:
                    self.connection.close()
                finally:
                    self.connection = None
                    self._closed = True

    def __enter__(self) -> "SQLiteDatastoreSync":
        """Context manager entry."""
        self._ensure_connection()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Context manager exit."""
        self.close()
