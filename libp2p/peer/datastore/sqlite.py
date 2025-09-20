"""
SQLite datastore implementation for persistent peer storage.

This provides a SQLite-based datastore for persistent peer storage.
"""

import asyncio
from collections.abc import Iterator
from pathlib import Path
import sqlite3

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
    """

    def __init__(self, path: str | Path):
        """
        Initialize SQLite datastore.

        Args:
            path: Path to the SQLite database file

        """
        self.path = Path(path)
        self.connection: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    async def _ensure_connection(self) -> None:
        """Ensure database connection is established."""
        if self.connection is None:
            async with self._lock:
                if self.connection is None:
                    # Create directory if it doesn't exist
                    self.path.parent.mkdir(parents=True, exist_ok=True)

                    self.connection = sqlite3.connect(
                        str(self.path), check_same_thread=False
                    )
                    self.connection.execute("""
                        CREATE TABLE IF NOT EXISTS datastore (
                            key BLOB PRIMARY KEY,
                            value BLOB NOT NULL
                        )
                    """)
                    self.connection.commit()

    async def get(self, key: bytes) -> bytes | None:
        """Retrieve a value by key."""
        await self._ensure_connection()
        cursor = self.connection.cursor()
        cursor.execute("SELECT value FROM datastore WHERE key = ?", (key,))
        result = cursor.fetchone()
        return result[0] if result else None

    async def put(self, key: bytes, value: bytes) -> None:
        """Store a key-value pair."""
        await self._ensure_connection()
        cursor = self.connection.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO datastore (key, value) VALUES (?, ?)", (key, value)
        )
        self.connection.commit()

    async def delete(self, key: bytes) -> None:
        """Delete a key-value pair."""
        await self._ensure_connection()
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM datastore WHERE key = ?", (key,))
        self.connection.commit()

    async def has(self, key: bytes) -> bool:
        """Check if a key exists."""
        await self._ensure_connection()
        cursor = self.connection.cursor()
        cursor.execute("SELECT 1 FROM datastore WHERE key = ?", (key,))
        return cursor.fetchone() is not None

    async def query(self, prefix: bytes = b"") -> Iterator[tuple[bytes, bytes]]:
        """Query key-value pairs with optional prefix."""
        await self._ensure_connection()
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
        return SQLiteBatch(self.connection)

    async def close(self) -> None:
        """Close the datastore connection."""
        if self.connection:
            self.connection.close()
            self.connection = None

    def __del__(self):
        """Cleanup on deletion."""
        if self.connection:
            self.connection.close()
