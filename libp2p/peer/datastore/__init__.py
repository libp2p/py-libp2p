"""
Datastore abstraction layer for persistent peer storage.

This module provides a pluggable datastore interface that allows different
storage backends to be used for persistent peer storage, similar to the
go-datastore interface in go-libp2p.

The datastore interface is completely backend-agnostic, allowing users to
choose from various storage backends including:
- SQLite (for simple file-based storage)
- LevelDB (for high-performance key-value storage)
- RocksDB (for advanced features and performance)
- BadgerDB (for Go-like performance)
- In-memory (for testing and development)
- Custom backends (user-defined implementations)

All backends implement the same IDatastore interface, making the peerstore
completely portable across different storage technologies.
"""

from .base import IDatastore, IBatchingDatastore, IBatch
from .sqlite import SQLiteDatastore
from .memory import MemoryDatastore
from .leveldb import LevelDBDatastore
from .rocksdb import RocksDBDatastore

__all__ = [
    "IDatastore",
    "IBatchingDatastore",
    "IBatch",
    "SQLiteDatastore",
    "MemoryDatastore",
    "LevelDBDatastore",
    "RocksDBDatastore",
]
