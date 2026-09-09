"""
Tests for different persistent peerstore backends.

This module contains functional tests for different datastore backends
(Memory, SQLite, LevelDB, RocksDB) for both sync and async implementations.
"""

from pathlib import Path
import tempfile

import pytest

from libp2p.peer.persistent import (
    AsyncPersistentPeerStore,
    SyncPersistentPeerStore,
    create_async_leveldb_peerstore,
    create_async_memory_peerstore,
    create_async_rocksdb_peerstore,
    create_async_sqlite_peerstore,
    create_sync_leveldb_peerstore,
    create_sync_memory_peerstore,
    create_sync_rocksdb_peerstore,
    create_sync_sqlite_peerstore,
)

# ============================================================================
# Async Backend Tests
# ============================================================================


@pytest.mark.trio
async def test_async_memory_backend():
    """Test async memory backend."""
    peerstore = create_async_memory_peerstore()
    assert isinstance(peerstore, AsyncPersistentPeerStore)
    await peerstore.close_async()


@pytest.mark.trio
async def test_async_sqlite_backend():
    """Test async SQLite backend."""
    with tempfile.TemporaryDirectory() as temp_dir:
        peerstore = create_async_sqlite_peerstore(Path(temp_dir) / "test.db")
        assert isinstance(peerstore, AsyncPersistentPeerStore)
        await peerstore.close_async()


@pytest.mark.trio
async def test_async_leveldb_backend():
    """Test async LevelDB backend if available."""
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            peerstore = create_async_leveldb_peerstore(Path(temp_dir) / "leveldb")
            assert isinstance(peerstore, AsyncPersistentPeerStore)
            await peerstore.close_async()
    except ImportError:
        pytest.skip("LevelDB backend not available (plyvel not installed)")


@pytest.mark.trio
async def test_async_rocksdb_backend():
    """Test async RocksDB backend if available."""
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            peerstore = create_async_rocksdb_peerstore(Path(temp_dir) / "rocksdb")
            assert isinstance(peerstore, AsyncPersistentPeerStore)
            await peerstore.close_async()
    except ImportError:
        pytest.skip("RocksDB backend not available (python-rocksdb not installed)")


# ============================================================================
# Sync Backend Tests
# ============================================================================


def test_sync_memory_backend():
    """Test sync memory backend."""
    peerstore = create_sync_memory_peerstore()
    assert isinstance(peerstore, SyncPersistentPeerStore)
    peerstore.close()


def test_sync_sqlite_backend():
    """Test sync SQLite backend."""
    with tempfile.TemporaryDirectory() as temp_dir:
        peerstore = create_sync_sqlite_peerstore(Path(temp_dir) / "test.db")
        assert isinstance(peerstore, SyncPersistentPeerStore)
        peerstore.close()


def test_sync_leveldb_backend():
    """Test sync LevelDB backend if available."""
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            peerstore = create_sync_leveldb_peerstore(Path(temp_dir) / "leveldb")
            assert isinstance(peerstore, SyncPersistentPeerStore)
            peerstore.close()
    except ImportError:
        pytest.skip("LevelDB backend not available (plyvel not installed)")


def test_sync_rocksdb_backend():
    """Test sync RocksDB backend if available."""
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            peerstore = create_sync_rocksdb_peerstore(Path(temp_dir) / "rocksdb")
            assert isinstance(peerstore, SyncPersistentPeerStore)
            peerstore.close()
    except ImportError:
        pytest.skip("RocksDB backend not available (python-rocksdb not installed)")


# ============================================================================
# Backend Comparison Tests
# ============================================================================


@pytest.mark.trio
async def test_async_backends_consistency():
    """Test that all async backends behave consistently."""
    from multiaddr import Multiaddr

    from libp2p.peer.id import ID

    peer_id = ID.from_base58("QmTestPeer")
    addr = Multiaddr("/ip4/127.0.0.1/tcp/4001")

    # Test memory backend
    memory_store = create_async_memory_peerstore()
    await memory_store.add_addrs_async(peer_id, [addr], 3600)
    memory_addrs = await memory_store.addrs_async(peer_id)
    await memory_store.close_async()

    # Test SQLite backend
    with tempfile.TemporaryDirectory() as temp_dir:
        sqlite_store = create_async_sqlite_peerstore(Path(temp_dir) / "test.db")
        await sqlite_store.add_addrs_async(peer_id, [addr], 3600)
        sqlite_addrs = await sqlite_store.addrs_async(peer_id)
        await sqlite_store.close_async()

    # Both should return the same result
    assert memory_addrs == sqlite_addrs
    assert len(memory_addrs) == 1
    assert memory_addrs[0] == addr


def test_sync_backends_consistency():
    """Test that all sync backends behave consistently."""
    from multiaddr import Multiaddr

    from libp2p.peer.id import ID

    peer_id = ID.from_base58("QmTestPeer")
    addr = Multiaddr("/ip4/127.0.0.1/tcp/4001")

    # Test memory backend
    memory_store = create_sync_memory_peerstore()
    memory_store.add_addrs(peer_id, [addr], 3600)
    memory_addrs = memory_store.addrs(peer_id)
    memory_store.close()

    # Test SQLite backend
    with tempfile.TemporaryDirectory() as temp_dir:
        sqlite_store = create_sync_sqlite_peerstore(Path(temp_dir) / "test.db")
        sqlite_store.add_addrs(peer_id, [addr], 3600)
        sqlite_addrs = sqlite_store.addrs(peer_id)
        sqlite_store.close()

    # Both should return the same result
    assert memory_addrs == sqlite_addrs
    assert len(memory_addrs) == 1
    assert memory_addrs[0] == addr


# ============================================================================
# Backend-Specific Feature Tests
# ============================================================================


@pytest.mark.trio
async def test_sqlite_file_creation():
    """Test that SQLite backend creates database files."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "test.db"

        # File shouldn't exist initially
        assert not db_path.exists()

        # Create peerstore
        peerstore = create_async_sqlite_peerstore(str(db_path))

        # Add some data to trigger database creation
        from libp2p.peer.id import ID

        peer_id = ID.from_base58("QmTestPeer")
        await peerstore.add_addrs_async(peer_id, [], 3600)

        await peerstore.close_async()

        # File should exist now
        assert db_path.exists()


def test_sync_sqlite_file_creation():
    """Test that sync SQLite backend creates database files."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "test.db"

        # File shouldn't exist initially
        assert not db_path.exists()

        # Create peerstore
        peerstore = create_sync_sqlite_peerstore(str(db_path))

        # Add some data to trigger database creation
        from libp2p.peer.id import ID

        peer_id = ID.from_base58("QmTestPeer")
        peerstore.add_addrs(peer_id, [], 3600)

        peerstore.close()

        # File should exist now
        assert db_path.exists()


@pytest.mark.trio
async def test_memory_backend_isolation():
    """Test that memory backends are isolated from each other."""
    from multiaddr import Multiaddr

    from libp2p.peer.id import ID

    peer_id = ID.from_base58("QmTestPeer")
    addr = Multiaddr("/ip4/127.0.0.1/tcp/4001")

    # Create two separate memory peerstores
    store1 = create_async_memory_peerstore()
    store2 = create_async_memory_peerstore()

    # Add data to first store
    await store1.add_addrs_async(peer_id, [addr], 3600)

    # Second store should not have the data
    addrs1 = await store1.addrs_async(peer_id)
    addrs2 = await store2.addrs_async(peer_id)

    assert len(addrs1) == 1
    assert len(addrs2) == 0

    await store1.close_async()
    await store2.close_async()


def test_sync_memory_backend_isolation():
    """Test that sync memory backends are isolated from each other."""
    from multiaddr import Multiaddr

    from libp2p.peer.id import ID

    peer_id = ID.from_base58("QmTestPeer")
    addr = Multiaddr("/ip4/127.0.0.1/tcp/4001")

    # Create two separate memory peerstores
    store1 = create_sync_memory_peerstore()
    store2 = create_sync_memory_peerstore()

    # Add data to first store
    store1.add_addrs(peer_id, [addr], 3600)

    # Second store should not have the data
    addrs1 = store1.addrs(peer_id)
    addrs2 = store2.addrs(peer_id)

    assert len(addrs1) == 1
    assert len(addrs2) == 0

    store1.close()
    store2.close()
