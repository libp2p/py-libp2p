"""
Persistent peerstore implementations for py-libp2p.

This module provides both synchronous and asynchronous persistent peerstore
implementations that store peer data in various datastore backends, following
the same architectural pattern as go-libp2p's pstoreds package.

The module is organized into:
- datastore/: Pluggable datastore backends (SQLite, LevelDB, RocksDB, Memory)
- sync/: Synchronous peerstore implementation
- async/: Asynchronous peerstore implementation
- factory: Unified factory for creating peerstores
"""

# Import factory functions for easy access
from .factory import (
    create_async_peerstore,
    create_sync_peerstore,
    # Convenience functions
    create_async_sqlite_peerstore,
    create_sync_sqlite_peerstore,
    create_async_memory_peerstore,
    create_sync_memory_peerstore,
    create_async_leveldb_peerstore,
    create_sync_leveldb_peerstore,
    create_async_rocksdb_peerstore,
    create_sync_rocksdb_peerstore,
)

# Import peerstore classes for direct use
from .async_.peerstore import AsyncPersistentPeerStore
from .sync.peerstore import SyncPersistentPeerStore

__all__ = [
    # Main factory functions
    "create_async_peerstore",
    "create_sync_peerstore",
    # Convenience factory functions
    "create_async_sqlite_peerstore",
    "create_sync_sqlite_peerstore",
    "create_async_memory_peerstore",
    "create_sync_memory_peerstore",
    "create_async_leveldb_peerstore",
    "create_sync_leveldb_peerstore",
    "create_async_rocksdb_peerstore",
    "create_sync_rocksdb_peerstore",
    # Peerstore classes
    "AsyncPersistentPeerStore",
    "SyncPersistentPeerStore",
]
