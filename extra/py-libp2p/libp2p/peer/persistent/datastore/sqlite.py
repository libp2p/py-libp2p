"""
SQLite datastore implementation for persistent peer storage.

This provides a SQLite-based datastore for persistent peer storage.
"""

from collections.abc import Iterator
from pathlib import Path
import sqlite3

import trio

from .base import IBatch, IBatchingDatastore


class SQLiteBatch(IBatch):
    """SQLite batch implementation."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
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
            cursor = self.connection.cursor()
            for operation, key, value in self.operations:
                if operation == "put":
                    cursor.execute(
                        "INSERT OR REPLACE INTO datastore (key, value) VALUES (?, ?)",
                        (key, value),
                    )
                elif operation == "delete":
                    cursor.execute("DELETE FROM datastore WHERE key = ?", (key,))
            self.connection.commit()
        except Exception as e:
            self.connection.rollback()
            raise e

    async def discard(self) -> None:
        """Discard all operations in the batch."""
        self.operations.clear()


class SQLiteDatastore(IBatchingDatastore):
    """
    SQLite-based datastore implementation.

    This provides persistent storage using SQLite database files.
    Supports context manager protocol for proper resource management.
    """

    def __init__(self, path: str | Path):
        """
        Initialize SQLite datastore.

        Args:
            path: Path to the SQLite database file

        """
        self.path = Path(path)
        self.connection: sqlite3.Connection | None = None
        self._lock = trio.Lock()
        self._closed = False

    async def _ensure_connection(self) -> None:
        """
        Ensure database connection is established.

        :raises RuntimeError: If datastore is closed
        :raises sqlite3.Error: If database connection fails
        """
        if self._closed:
            raise RuntimeError("Datastore is closed")

        if self.connection is None:
            async with self._lock:
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

    async def get(self, key: bytes) -> bytes | None:
        """Retrieve a value by key."""
        await self._ensure_connection()
        if self.connection is None:
            raise ValueError("SQLite connection is not initialized")
        cursor = self.connection.cursor()
        cursor.execute("SELECT value FROM datastore WHERE key = ?", (key,))
        result = cursor.fetchone()
        return result[0] if result else None

    async def put(self, key: bytes, value: bytes) -> None:
        """Store a key-value pair."""
        await self._ensure_connection()
        if self.connection is None:
            raise ValueError("SQLite connection is not initialized")
        cursor = self.connection.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO datastore (key, value) VALUES (?, ?)", (key, value)
        )
        self.connection.commit()

    async def delete(self, key: bytes) -> None:
        """Delete a key-value pair."""
        await self._ensure_connection()
        if self.connection is None:
            raise ValueError("SQLite connection is not initialized")
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM datastore WHERE key = ?", (key,))
        self.connection.commit()

    async def has(self, key: bytes) -> bool:
        """Check if a key exists."""
        await self._ensure_connection()
        if self.connection is None:
            raise ValueError("SQLite connection is not initialized")
        cursor = self.connection.cursor()
        cursor.execute("SELECT 1 FROM datastore WHERE key = ?", (key,))
        return cursor.fetchone() is not None

    def query(self, prefix: bytes = b"") -> Iterator[tuple[bytes, bytes]]:
        """
        Query key-value pairs with optional prefix.

        Note: query is synchronous per interface and returns an Iterator.
        If the connection is missing, we best-effort open it synchronously.
        """
        if self.connection is None:
            # Create directory and open connection synchronously
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(str(self.path), check_same_thread=False)
            self.connection.execute(
                """
                        CREATE TABLE IF NOT EXISTS datastore (
                            key BLOB PRIMARY KEY,
                            value BLOB NOT NULL
                        )
                    """
            )
            self.connection.commit()

        if self.connection is None:
            raise ValueError("SQLite connection is not initialized")
        cursor = self.connection.cursor()
        if prefix:
            cursor.execute(
                "SELECT key, value FROM datastore WHERE key LIKE ?", (prefix + b"%",)
            )
        else:
            cursor.execute("SELECT key, value FROM datastore")

        for row in cursor:
            yield row[0], row[1]

    async def batch(self) -> IBatch:
        """Create a new batch for atomic operations."""
        await self._ensure_connection()
        if self.connection is None:
            raise ValueError("SQLite connection is not initialized")
        return SQLiteBatch(self.connection)

    async def sync(self, prefix: bytes) -> None:
        """Flush pending writes to disk (commit current transaction)."""
        await self._ensure_connection()
        if self.connection is None:
            raise ValueError("SQLite connection is not initialized")
        self.connection.commit()

    async def close(self) -> None:
        """
        Close the datastore connection.

        This method is idempotent and can be called multiple times safely.
        """
        async with self._lock:
            if self.connection and not self._closed:
                try:
                    self.connection.close()
                finally:
                    self.connection = None
                    self._closed = True

    async def __aenter__(self) -> "SQLiteDatastore":
        """Async context manager entry."""
        await self._ensure_connection()
        return self

    async def __aexit__(
        self, exc_type: type, exc_val: Exception, exc_tb: object
    ) -> None:
        """Async context manager exit."""
        await self.close()
