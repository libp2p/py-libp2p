"""
Factory functions for creating persistent peerstores.

This module provides convenient factory functions for creating persistent
peerstores with different datastore backends.
"""

from pathlib import Path

from .datastore import (
    IDatastore,
    LevelDBDatastore,
    MemoryDatastore,
    RocksDBDatastore,
    SQLiteDatastore,
)
from .persistent_peerstore import PersistentPeerStore


def create_persistent_peerstore(
    datastore: IDatastore | None = None,
    db_path: str | Path | None = None,
    backend: str = "sqlite",
    max_records: int = 10000,
) -> PersistentPeerStore:
    """
    Create a persistent peerstore with the specified datastore backend.

    Args:
        datastore: Optional datastore instance. If not provided, will create one.
        db_path: Path for database if using file-based backend.
                If not provided, will use in-memory datastore.
        backend: Backend type ("sqlite", "leveldb", "rocksdb", "memory").
                Ignored if datastore is provided.
        max_records: Maximum number of peer records to store.

    Returns:
        PersistentPeerStore instance

    Examples:
        # Create with SQLite backend
        peerstore = create_persistent_peerstore(db_path="./peerstore.db", backend="sqlite")

        # Create with LevelDB backend
        peerstore = create_persistent_peerstore(db_path="./peerstore.ldb", backend="leveldb")

        # Create with RocksDB backend
        peerstore = create_persistent_peerstore(db_path="./peerstore.rdb", backend="rocksdb")

        # Create with custom datastore
        custom_datastore = MyCustomDatastore()
        peerstore = create_persistent_peerstore(datastore=custom_datastore)

        # Create with in-memory backend (for testing)
        peerstore = create_persistent_peerstore(backend="memory")

    """
    if datastore is None:
        if db_path is not None:
            if backend == "sqlite":
                datastore = SQLiteDatastore(db_path)
            elif backend == "leveldb":
                datastore = LevelDBDatastore(db_path)
            elif backend == "rocksdb":
                datastore = RocksDBDatastore(db_path)
            else:
                raise ValueError(f"Unsupported backend: {backend}")
        else:
            datastore = MemoryDatastore()

    return PersistentPeerStore(datastore, max_records)


def create_sqlite_peerstore(
    db_path: str | Path, max_records: int = 10000
) -> PersistentPeerStore:
    """
    Create a persistent peerstore with SQLite backend.

    Args:
        db_path: Path to the SQLite database file
        max_records: Maximum number of peer records to store

    Returns:
        PersistentPeerStore instance with SQLite backend

    """
    datastore = SQLiteDatastore(db_path)
    return PersistentPeerStore(datastore, max_records)


def create_memory_peerstore(max_records: int = 10000) -> PersistentPeerStore:
    """
    Create a persistent peerstore with in-memory backend.

    This is useful for testing or when persistence is not needed.

    Args:
        max_records: Maximum number of peer records to store

    Returns:
        PersistentPeerStore instance with in-memory backend

    """
    datastore = MemoryDatastore()
    return PersistentPeerStore(datastore, max_records)


def create_leveldb_peerstore(
    db_path: str | Path, max_records: int = 10000
) -> PersistentPeerStore:
    """
    Create a persistent peerstore with LevelDB backend.

    LevelDB provides high-performance key-value storage with good read/write performance.

    Args:
        db_path: Path to the LevelDB database directory
        max_records: Maximum number of peer records to store

    Returns:
        PersistentPeerStore instance with LevelDB backend

    """
    datastore = LevelDBDatastore(db_path)
    return PersistentPeerStore(datastore, max_records)


def create_rocksdb_peerstore(
    db_path: str | Path, max_records: int = 10000
) -> PersistentPeerStore:
    """
    Create a persistent peerstore with RocksDB backend.

    RocksDB provides advanced features like compression, bloom filters, and
    high performance for write-heavy workloads.

    Args:
        db_path: Path to the RocksDB database directory
        max_records: Maximum number of peer records to store

    Returns:
        PersistentPeerStore instance with RocksDB backend

    """
    datastore = RocksDBDatastore(db_path)
    return PersistentPeerStore(datastore, max_records)
