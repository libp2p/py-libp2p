"""
Synchronous SQLite datastore implementation for persistent peer storage.

This provides a synchronous SQLite-based datastore for persistent storage.
"""

from collections.abc import Iterator
import logging
from pathlib import Path
import sqlite3
import threading

from .base_sync import IBatchingDatastoreSync, IBatchSync

logger = logging.getLogger(__name__)


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
                    cursor.execute("PRAGMA cache_size=1000")  # Bounded 4MB cache size
                    cursor.execute(
                        "PRAGMA temp_store=MEMORY"
                    )  # Use memory for temp storage

                    # Let SQLite return freed pages to the filesystem for
                    # databases created from now on.  Existing databases keep
                    # their layout until compact() runs (VACUUM).
                    cursor.execute("PRAGMA auto_vacuum=INCREMENTAL")

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
                    "SELECT key, value FROM datastore WHERE substr(key, 1, ?) = ?",
                    (len(prefix), prefix),
                )
            else:
                cursor.execute("SELECT key, value FROM datastore")

            for row in cursor:
                yield row[0], row[1]

    def query_keys(
        self, prefix: bytes = b"", limit: int | None = None, random_order: bool = False
    ) -> Iterator[bytes]:
        """
        Query only keys (omitting value blobs) with optional prefix,
        random ordering, and limit. Significantly faster and lighter on memory
        than query().
        """
        self._ensure_connection()
        if self.connection is None:
            raise ValueError("SQLite connection is not initialized")

        with self._lock:
            cursor = self.connection.cursor()
            order_clause = " ORDER BY RANDOM()" if random_order else ""
            limit_clause = f" LIMIT {int(limit)}" if limit is not None else ""
            if prefix:
                query = (
                    "SELECT key FROM datastore WHERE substr(key, 1, ?) = ?"
                    f"{order_clause}{limit_clause}"
                )
                cursor.execute(query, (len(prefix), prefix))
            else:
                cursor.execute(f"SELECT key FROM datastore{order_clause}{limit_clause}")

            for row in cursor:
                yield row[0]

    def count(self, prefix: bytes = b"") -> int:
        """Count keys matching an optional prefix without fetching rows."""
        self._ensure_connection()
        if self.connection is None:
            raise ValueError("SQLite connection is not initialized")

        with self._lock:
            cursor = self.connection.cursor()
            if prefix:
                cursor.execute(
                    "SELECT count(*) FROM datastore WHERE substr(key, 1, ?) = ?",
                    (len(prefix), prefix),
                )
            else:
                cursor.execute("SELECT count(*) FROM datastore")
            row = cursor.fetchone()
            return int(row[0]) if row else 0

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

    def compact(self, min_free_bytes: int = 16 * 1024 * 1024) -> bool:
        """
        Reclaim free pages with VACUUM when enough space has been freed.

        Deleting rows leaves the pages in SQLite's freelist so future writes
        reuse them, but the file itself never shrinks.  Running this after a
        large prune returns the space to the filesystem.  It is a no-op until
        ``min_free_bytes`` worth of pages are free, so periodic callers stay
        cheap.

        Returns:
            True if the database was vacuumed.

        """
        self._ensure_connection()
        if self.connection is None:
            raise ValueError("SQLite connection is not initialized")

        with self._lock:
            cursor = self.connection.cursor()
            freelist = cursor.execute("PRAGMA freelist_count").fetchone()
            page_size = cursor.execute("PRAGMA page_size").fetchone()
            free_bytes = int(freelist[0]) * int(page_size[0]) if freelist else 0
            if free_bytes < min_free_bytes:
                return False

            # VACUUM cannot run inside an open transaction.
            self.connection.commit()
            cursor.execute("VACUUM")
            self.connection.commit()
            # A large prune writes every touched page to the WAL, so the -wal
            # file can be much bigger than the database itself.  Checkpointing
            # with TRUNCATE moves those pages into the database and resets the
            # WAL, otherwise the freed disk space just moves from the .db file
            # to the sidecar.
            cursor.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.connection.commit()
            logger.info(
                "Compacted SQLite datastore %s (freed about %.1f MiB)",
                self.path,
                free_bytes / (1024 * 1024),
            )
            return True

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
