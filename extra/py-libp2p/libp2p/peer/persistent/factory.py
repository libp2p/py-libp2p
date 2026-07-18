"""
Unified factory functions for creating persistent peerstores.

This module provides convenient factory functions for creating both synchronous
and asynchronous persistent peerstores with different datastore backends.
"""

from pathlib import Path
from typing import Any, Literal

# Optional imports - check availability once at module level
try:
    import plyvel  # type: ignore[import-untyped]

    PLYVEL_AVAILABLE = True
except ImportError:
    plyvel = None  # type: ignore[assignment]
    PLYVEL_AVAILABLE = False

try:
    import rocksdb  # type: ignore[import-untyped]

    ROCKSDB_AVAILABLE = True
except ImportError:
    rocksdb = None  # type: ignore[assignment]
    ROCKSDB_AVAILABLE = False

from .async_.peerstore import AsyncPersistentPeerStore
from .datastore import (
    IDatastore,
    IDatastoreSync,
    LevelDBDatastore,
    LevelDBDatastoreSync,
    MemoryDatastore,
    MemoryDatastoreSync,
    RocksDBDatastore,
    RocksDBDatastoreSync,
    SQLiteDatastore,
    SQLiteDatastoreSync,
)
from .sync.peerstore import SyncPersistentPeerStore

# Type aliases for better type hints
SyncBackend = Literal["sqlite", "leveldb", "rocksdb", "memory"]
AsyncBackend = Literal["sqlite", "leveldb", "rocksdb", "memory"]


def create_sync_peerstore(
    datastore: IDatastoreSync | None = None,
    db_path: str | Path | None = None,
    backend: SyncBackend = "sqlite",
    max_records: int = 10000,
    sync_interval: float = 1.0,
    auto_sync: bool = True,
    **backend_options: Any,
) -> SyncPersistentPeerStore:
    """
    Create a synchronous persistent peerstore with the specified datastore backend.

    Args:
        datastore: Optional sync datastore instance. If not provided, will create one.
        db_path: Path for database if using file-based backend.
                If not provided, will use in-memory datastore.
        backend: Backend type ("sqlite", "leveldb", "rocksdb", "memory").
                Ignored if datastore is provided.
        max_records: Maximum number of peer records to store.
        sync_interval: Minimum interval between sync operations (seconds).
        auto_sync: Whether to automatically sync after writes.
        **backend_options: Additional options passed to the datastore backend.

    Returns:
        SyncPersistentPeerStore instance

    Examples:
        # Create with SQLite backend
        peerstore = create_sync_peerstore(
            db_path="./peerstore.db",
            backend="sqlite"
        )

        # Create with LevelDB backend
        peerstore = create_sync_peerstore(
            db_path="./peerstore.ldb",
            backend="leveldb"
        )

        # Create with RocksDB backend
        peerstore = create_sync_peerstore(
            db_path="./peerstore.rdb",
            backend="rocksdb"
        )

        # Create with custom datastore
        custom_datastore = MyCustomSyncDatastore()
        peerstore = create_sync_peerstore(datastore=custom_datastore)

        # Create with in-memory backend (for testing)
        peerstore = create_sync_peerstore(backend="memory")

    """
    if datastore is None:
        if db_path is not None:
            if backend == "sqlite":
                datastore = SQLiteDatastoreSync(db_path, **backend_options)
            elif backend == "leveldb":
                datastore = LevelDBDatastoreSync(db_path, **backend_options)
            elif backend == "rocksdb":
                datastore = RocksDBDatastoreSync(db_path, **backend_options)
            else:
                raise ValueError(f"Unsupported sync backend: {backend}")
        else:
            if backend == "memory":
                datastore = MemoryDatastoreSync(**backend_options)
            else:
                raise ValueError(
                    f"Backend '{backend}' requires db_path. "
                    f"Use backend='memory' for in-memory storage."
                )

    return SyncPersistentPeerStore(datastore, max_records, sync_interval, auto_sync)


def create_async_peerstore(
    datastore: IDatastore | None = None,
    db_path: str | Path | None = None,
    backend: AsyncBackend = "sqlite",
    max_records: int = 10000,
    sync_interval: float = 1.0,
    auto_sync: bool = True,
    **backend_options: Any,
) -> AsyncPersistentPeerStore:
    """
    Create an asynchronous persistent peerstore with the specified datastore backend.

    Args:
        datastore: Optional async datastore instance. If not provided, will create one.
        db_path: Path for database if using file-based backend.
                If not provided, will use in-memory datastore.
        backend: Backend type ("sqlite", "leveldb", "rocksdb", "memory").
                Ignored if datastore is provided.
        max_records: Maximum number of peer records to store.
        sync_interval: Minimum interval between sync operations (seconds).
        auto_sync: Whether to automatically sync after writes.
        **backend_options: Additional options passed to the datastore backend.

    Returns:
        AsyncPersistentPeerStore instance

    Examples:
        # Create with SQLite backend
        peerstore = create_async_peerstore(
            db_path="./peerstore.db",
            backend="sqlite"
        )

        # Create with LevelDB backend
        peerstore = create_async_peerstore(
            db_path="./peerstore.ldb",
            backend="leveldb"
        )

        # Create with RocksDB backend
        peerstore = create_async_peerstore(
            db_path="./peerstore.rdb",
            backend="rocksdb"
        )

        # Create with custom datastore
        custom_datastore = MyCustomAsyncDatastore()
        peerstore = create_async_peerstore(datastore=custom_datastore)

        # Create with in-memory backend (for testing)
        peerstore = create_async_peerstore(backend="memory")

    """
    if datastore is None:
        if db_path is not None:
            if backend == "sqlite":
                datastore = SQLiteDatastore(db_path, **backend_options)
            elif backend == "leveldb":
                datastore = LevelDBDatastore(db_path, **backend_options)
            elif backend == "rocksdb":
                datastore = RocksDBDatastore(db_path, **backend_options)
            else:
                raise ValueError(f"Unsupported async backend: {backend}")
        else:
            if backend == "memory":
                datastore = MemoryDatastore(**backend_options)
            else:
                raise ValueError(
                    f"Backend '{backend}' requires db_path. "
                    f"Use backend='memory' for in-memory storage."
                )

    return AsyncPersistentPeerStore(datastore, max_records, sync_interval, auto_sync)


# Convenience functions for specific backends


def create_sync_sqlite_peerstore(
    db_path: str | Path,
    max_records: int = 10000,
    sync_interval: float = 1.0,
    auto_sync: bool = True,
    **options: Any,
) -> SyncPersistentPeerStore:
    """
    Create a synchronous persistent peerstore with SQLite backend.

    Args:
        db_path: Path to the SQLite database file
        max_records: Maximum number of peer records to store
        sync_interval: Minimum interval between sync operations (seconds)
        auto_sync: Whether to automatically sync after writes
        **options: Additional SQLite options

    Returns:
        SyncPersistentPeerStore instance with SQLite backend

    """
    datastore = SQLiteDatastoreSync(db_path, **options)
    return SyncPersistentPeerStore(datastore, max_records, sync_interval, auto_sync)


def create_async_sqlite_peerstore(
    db_path: str | Path,
    max_records: int = 10000,
    sync_interval: float = 1.0,
    auto_sync: bool = True,
    **options: Any,
) -> AsyncPersistentPeerStore:
    """
    Create an asynchronous persistent peerstore with SQLite backend.

    Args:
        db_path: Path to the SQLite database file
        max_records: Maximum number of peer records to store
        sync_interval: Minimum interval between sync operations (seconds)
        auto_sync: Whether to automatically sync after writes
        **options: Additional SQLite options

    Returns:
        AsyncPersistentPeerStore instance with SQLite backend

    """
    datastore = SQLiteDatastore(db_path, **options)
    return AsyncPersistentPeerStore(datastore, max_records, sync_interval, auto_sync)


def create_sync_memory_peerstore(
    max_records: int = 10000, sync_interval: float = 1.0, auto_sync: bool = True
) -> SyncPersistentPeerStore:
    """
    Create a synchronous persistent peerstore with in-memory backend.

    This is useful for testing or when persistence is not needed.

    Args:
        max_records: Maximum number of peer records to store
        sync_interval: Minimum interval between sync operations (seconds)
        auto_sync: Whether to automatically sync after writes

    Returns:
        SyncPersistentPeerStore instance with in-memory backend

    """
    datastore = MemoryDatastoreSync()
    return SyncPersistentPeerStore(datastore, max_records, sync_interval, auto_sync)


def create_async_memory_peerstore(
    max_records: int = 10000, sync_interval: float = 1.0, auto_sync: bool = True
) -> AsyncPersistentPeerStore:
    """
    Create an asynchronous persistent peerstore with in-memory backend.

    This is useful for testing or when persistence is not needed.

    Args:
        max_records: Maximum number of peer records to store
        sync_interval: Minimum interval between sync operations (seconds)
        auto_sync: Whether to automatically sync after writes

    Returns:
        AsyncPersistentPeerStore instance with in-memory backend

    """
    datastore = MemoryDatastore()
    return AsyncPersistentPeerStore(datastore, max_records, sync_interval, auto_sync)


def create_sync_leveldb_peerstore(
    db_path: str | Path,
    max_records: int = 10000,
    sync_interval: float = 1.0,
    auto_sync: bool = True,
    **options: Any,
) -> SyncPersistentPeerStore:
    """
    Create a synchronous persistent peerstore with LevelDB backend.

    LevelDB provides high-performance key-value storage with
    good read/write performance.

    Args:
        db_path: Path to the LevelDB database directory
        max_records: Maximum number of peer records to store
        sync_interval: Minimum interval between sync operations (seconds)
        auto_sync: Whether to automatically sync after writes
        **options: Additional LevelDB options

    Returns:
        SyncPersistentPeerStore instance with LevelDB backend

    Raises:
        ImportError: If plyvel package is not installed

    """
    if not PLYVEL_AVAILABLE:
        raise ImportError(
            "LevelDB support requires 'plyvel' package. "
            "Install with: pip install plyvel"
        )

    datastore = LevelDBDatastoreSync(db_path, **options)
    return SyncPersistentPeerStore(datastore, max_records, sync_interval, auto_sync)


def create_async_leveldb_peerstore(
    db_path: str | Path,
    max_records: int = 10000,
    sync_interval: float = 1.0,
    auto_sync: bool = True,
    **options: Any,
) -> AsyncPersistentPeerStore:
    """
    Create an asynchronous persistent peerstore with LevelDB backend.

    LevelDB provides high-performance key-value storage with
    good read/write performance.

    Args:
        db_path: Path to the LevelDB database directory
        max_records: Maximum number of peer records to store
        sync_interval: Minimum interval between sync operations (seconds)
        auto_sync: Whether to automatically sync after writes
        **options: Additional LevelDB options

    Returns:
        AsyncPersistentPeerStore instance with LevelDB backend

    Raises:
        ImportError: If plyvel package is not installed

    """
    if not PLYVEL_AVAILABLE:
        raise ImportError(
            "LevelDB support requires 'plyvel' package. "
            "Install with: pip install plyvel"
        )

    datastore = LevelDBDatastore(db_path, **options)
    return AsyncPersistentPeerStore(datastore, max_records, sync_interval, auto_sync)


def create_sync_rocksdb_peerstore(
    db_path: str | Path,
    max_records: int = 10000,
    sync_interval: float = 1.0,
    auto_sync: bool = True,
    **options: Any,
) -> SyncPersistentPeerStore:
    """
    Create a synchronous persistent peerstore with RocksDB backend.

    RocksDB provides advanced features like compression, bloom filters, and
    high performance for write-heavy workloads.

    Args:
        db_path: Path to the RocksDB database directory
        max_records: Maximum number of peer records to store
        sync_interval: Minimum interval between sync operations (seconds)
        auto_sync: Whether to automatically sync after writes
        **options: Additional RocksDB options

    Returns:
        SyncPersistentPeerStore instance with RocksDB backend

    Raises:
        ImportError: If python-rocksdb package is not installed

    """
    if not ROCKSDB_AVAILABLE:
        raise ImportError(
            "RocksDB support requires 'python-rocksdb' package. "
            "Install with: pip install python-rocksdb"
        )

    datastore = RocksDBDatastoreSync(db_path, **options)
    return SyncPersistentPeerStore(datastore, max_records, sync_interval, auto_sync)


def create_async_rocksdb_peerstore(
    db_path: str | Path,
    max_records: int = 10000,
    sync_interval: float = 1.0,
    auto_sync: bool = True,
    **options: Any,
) -> AsyncPersistentPeerStore:
    """
    Create an asynchronous persistent peerstore with RocksDB backend.

    RocksDB provides advanced features like compression, bloom filters, and
    high performance for write-heavy workloads.

    Args:
        db_path: Path to the RocksDB database directory
        max_records: Maximum number of peer records to store
        sync_interval: Minimum interval between sync operations (seconds)
        auto_sync: Whether to automatically sync after writes
        **options: Additional RocksDB options

    Returns:
        AsyncPersistentPeerStore instance with RocksDB backend

    Raises:
        ImportError: If python-rocksdb package is not installed

    """
    if not ROCKSDB_AVAILABLE:
        raise ImportError(
            "RocksDB support requires 'python-rocksdb' package. "
            "Install with: pip install python-rocksdb"
        )

    datastore = RocksDBDatastore(db_path, **options)
    return AsyncPersistentPeerStore(datastore, max_records, sync_interval, auto_sync)
