"""
Datastore abstraction layer for persistent peer storage.

This module provides pluggable datastore interfaces that allow different
storage backends to be used for persistent peer storage, similar to the
go-datastore interface in go-libp2p.

The datastore interfaces are completely backend-agnostic, allowing users to
choose from various storage backends including:
- SQLite (for simple file-based storage)
- LevelDB (for high-performance key-value storage)
- RocksDB (for advanced features and performance)
- In-memory (for testing and development)
- Custom backends (user-defined implementations)

Both synchronous and asynchronous interfaces are provided, making the peerstore
completely portable across different storage technologies and usage patterns.
"""

# Async interfaces (original)
from .base import IDatastore, IBatchingDatastore, IBatch

# Sync interfaces
from .base_sync import IDatastoreSync, IBatchingDatastoreSync, IBatchSync

# Async implementations
from .sqlite import SQLiteDatastore
from .memory import MemoryDatastore
from .leveldb import LevelDBDatastore
from .rocksdb import RocksDBDatastore

# Sync implementations
from .sqlite_sync import SQLiteDatastoreSync
from .memory_sync import MemoryDatastoreSync
from .leveldb_sync import LevelDBDatastoreSync
from .rocksdb_sync import RocksDBDatastoreSync

__all__ = [
    # Async interfaces
    "IDatastore",
    "IBatchingDatastore",
    "IBatch",
    # Sync interfaces
    "IDatastoreSync",
    "IBatchingDatastoreSync",
    "IBatchSync",
    # Async implementations
    "SQLiteDatastore",
    "MemoryDatastore",
    "LevelDBDatastore",
    "RocksDBDatastore",
    # Sync implementations
    "SQLiteDatastoreSync",
    "MemoryDatastoreSync",
    "LevelDBDatastoreSync",
    "RocksDBDatastoreSync",
]
