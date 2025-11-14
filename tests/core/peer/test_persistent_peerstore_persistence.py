"""
Tests for persistent peerstore persistence behavior.

This module contains functional tests for persistence behavior across
peerstore restarts, testing that data is properly saved and loaded.
"""

from pathlib import Path
import tempfile

import pytest
from multiaddr import Multiaddr

from libp2p.peer.id import ID
from libp2p.peer.peerstore import PeerStoreError
from libp2p.peer.persistent import (
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
# Fixtures
# ============================================================================


@pytest.fixture
def peer_id():
    """Create a test peer ID."""
    return ID.from_base58("QmTestPeer")


@pytest.fixture
def peer_id_2():
    """Create a second test peer ID."""
    return ID.from_base58("QmTestPeer2")


@pytest.fixture
def addr():
    """Create a test address."""
    return Multiaddr("/ip4/127.0.0.1/tcp/4001")


@pytest.fixture
def addr2():
    """Create a second test address."""
    return Multiaddr("/ip4/192.168.1.1/tcp/4002")


# ============================================================================
# Async Persistence Tests
# ============================================================================


@pytest.mark.trio
async def test_async_sqlite_basic_persistence(peer_id, addr):
    """Test basic SQLite persistence with async peerstore."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "test.db"

        # Create first peerstore and add data
        peerstore1 = create_async_sqlite_peerstore(str(db_path))
        await peerstore1.add_addrs_async(peer_id, [addr], 3600)
        await peerstore1.add_protocols_async(peer_id, ["/ipfs/ping/1.0.0"])
        await peerstore1.put_async(peer_id, "test", "value")
        await peerstore1.close_async()

        # Create second peerstore and verify data persisted
        peerstore2 = create_async_sqlite_peerstore(str(db_path))

        addrs = await peerstore2.addrs_async(peer_id)
        assert len(addrs) == 1
        assert addrs[0] == addr

        protocols = await peerstore2.get_protocols_async(peer_id)
        assert "/ipfs/ping/1.0.0" in protocols

        value = await peerstore2.get_async(peer_id, "test")
        assert value == "value"

        await peerstore2.close_async()


@pytest.mark.trio
async def test_async_sqlite_multiple_peers_persistence(peer_id, peer_id_2, addr, addr2):
    """Test SQLite persistence with multiple peers."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "test.db"

        # Create first peerstore and add data for multiple peers
        peerstore1 = create_async_sqlite_peerstore(str(db_path))
        await peerstore1.add_addrs_async(peer_id, [addr], 3600)
        await peerstore1.add_addrs_async(peer_id_2, [addr2], 3600)
        await peerstore1.add_protocols_async(peer_id, ["/ipfs/ping/1.0.0"])
        await peerstore1.add_protocols_async(peer_id_2, ["/ipfs/id/1.0.0"])
        await peerstore1.put_async(peer_id, "agent", "py-libp2p")
        await peerstore1.put_async(peer_id_2, "version", "1.0.0")
        await peerstore1.close_async()

        # Create second peerstore and verify all data persisted
        peerstore2 = create_async_sqlite_peerstore(str(db_path))

        # Check first peer
        addrs1 = await peerstore2.addrs_async(peer_id)
        assert len(addrs1) == 1
        assert addrs1[0] == addr

        protocols1 = await peerstore2.get_protocols_async(peer_id)
        assert "/ipfs/ping/1.0.0" in protocols1

        agent = await peerstore2.get_async(peer_id, "agent")
        assert agent == "py-libp2p"

        # Check second peer
        addrs2 = await peerstore2.addrs_async(peer_id_2)
        assert len(addrs2) == 1
        assert addrs2[0] == addr2

        protocols2 = await peerstore2.get_protocols_async(peer_id_2)
        assert "/ipfs/id/1.0.0" in protocols2

        version = await peerstore2.get_async(peer_id_2, "version")
        assert version == "1.0.0"

        await peerstore2.close_async()


@pytest.mark.trio
async def test_async_sqlite_data_updates_persistence(peer_id, addr, addr2):
    """Test that data updates are properly persisted."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "test.db"

        # Create first peerstore and add initial data
        peerstore1 = create_async_sqlite_peerstore(str(db_path))
        await peerstore1.add_addrs_async(peer_id, [addr], 3600)
        await peerstore1.put_async(peer_id, "version", "1.0.0")
        await peerstore1.close_async()

        # Create second peerstore and update data
        peerstore2 = create_async_sqlite_peerstore(str(db_path))
        await peerstore2.add_addrs_async(peer_id, [addr2], 3600)  # Add second address
        await peerstore2.put_async(peer_id, "version", "2.0.0")  # Update version
        await peerstore2.close_async()

        # Create third peerstore and verify updates persisted
        peerstore3 = create_async_sqlite_peerstore(str(db_path))

        addrs = await peerstore3.addrs_async(peer_id)
        assert len(addrs) == 2
        assert addr in addrs
        assert addr2 in addrs

        version = await peerstore3.get_async(peer_id, "version")
        assert version == "2.0.0"

        await peerstore3.close_async()


@pytest.mark.trio
async def test_async_memory_not_persistent(peer_id, addr):
    """Test that async memory peerstore is not persistent."""
    # Create memory peerstore and add data
    peerstore1 = create_async_memory_peerstore()
    await peerstore1.add_addrs_async(peer_id, [addr], 3600)
    await peerstore1.put_async(peer_id, "test", "value")
    await peerstore1.close_async()

    # Create new memory peerstore
    peerstore2 = create_async_memory_peerstore()

    # Verify data is not persisted
    addrs = await peerstore2.addrs_async(peer_id)
    assert len(addrs) == 0

    with pytest.raises(PeerStoreError):
        await peerstore2.get_async(peer_id, "test")

    await peerstore2.close_async()


@pytest.mark.trio
async def test_async_leveldb_persistence_if_available(peer_id, addr):
    """Test LevelDB persistence if available."""
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "leveldb"

            # Create first peerstore and add data
            peerstore1 = create_async_leveldb_peerstore(str(db_path))
            await peerstore1.add_addrs_async(peer_id, [addr], 3600)
            await peerstore1.put_async(peer_id, "test", "value")
            await peerstore1.close_async()

            # Create second peerstore and verify data persisted
            peerstore2 = create_async_leveldb_peerstore(str(db_path))

            addrs = await peerstore2.addrs_async(peer_id)
            assert len(addrs) == 1
            assert addrs[0] == addr

            value = await peerstore2.get_async(peer_id, "test")
            assert value == "value"

            await peerstore2.close_async()
    except ImportError:
        pytest.skip("LevelDB backend not available (plyvel not installed)")


@pytest.mark.trio
async def test_async_rocksdb_persistence_if_available(peer_id, addr):
    """Test RocksDB persistence if available."""
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "rocksdb"

            # Create first peerstore and add data
            peerstore1 = create_async_rocksdb_peerstore(str(db_path))
            await peerstore1.add_addrs_async(peer_id, [addr], 3600)
            await peerstore1.put_async(peer_id, "test", "value")
            await peerstore1.close_async()

            # Create second peerstore and verify data persisted
            peerstore2 = create_async_rocksdb_peerstore(str(db_path))

            addrs = await peerstore2.addrs_async(peer_id)
            assert len(addrs) == 1
            assert addrs[0] == addr

            value = await peerstore2.get_async(peer_id, "test")
            assert value == "value"

            await peerstore2.close_async()
    except ImportError:
        pytest.skip("RocksDB backend not available (python-rocksdb not installed)")


# ============================================================================
# Sync Persistence Tests
# ============================================================================


def test_sync_sqlite_basic_persistence(peer_id, addr):
    """Test basic SQLite persistence with sync peerstore."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "test.db"

        # Create first peerstore and add data
        peerstore1 = create_sync_sqlite_peerstore(str(db_path))
        peerstore1.add_addrs(peer_id, [addr], 3600)
        peerstore1.add_protocols(peer_id, ["/ipfs/ping/1.0.0"])
        peerstore1.put(peer_id, "test", "value")
        peerstore1.close()

        # Create second peerstore and verify data persisted
        peerstore2 = create_sync_sqlite_peerstore(str(db_path))

        addrs = peerstore2.addrs(peer_id)
        assert len(addrs) == 1
        assert addrs[0] == addr

        protocols = peerstore2.get_protocols(peer_id)
        assert "/ipfs/ping/1.0.0" in protocols

        value = peerstore2.get(peer_id, "test")
        assert value == "value"

        peerstore2.close()


def test_sync_sqlite_multiple_peers_persistence(peer_id, peer_id_2, addr, addr2):
    """Test SQLite persistence with multiple peers."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "test.db"

        # Create first peerstore and add data for multiple peers
        peerstore1 = create_sync_sqlite_peerstore(str(db_path))
        peerstore1.add_addrs(peer_id, [addr], 3600)
        peerstore1.add_addrs(peer_id_2, [addr2], 3600)
        peerstore1.add_protocols(peer_id, ["/ipfs/ping/1.0.0"])
        peerstore1.add_protocols(peer_id_2, ["/ipfs/id/1.0.0"])
        peerstore1.put(peer_id, "agent", "py-libp2p")
        peerstore1.put(peer_id_2, "version", "1.0.0")
        peerstore1.close()

        # Create second peerstore and verify all data persisted
        peerstore2 = create_sync_sqlite_peerstore(str(db_path))

        # Check first peer
        addrs1 = peerstore2.addrs(peer_id)
        assert len(addrs1) == 1
        assert addrs1[0] == addr

        protocols1 = peerstore2.get_protocols(peer_id)
        assert "/ipfs/ping/1.0.0" in protocols1

        agent = peerstore2.get(peer_id, "agent")
        assert agent == "py-libp2p"

        # Check second peer
        addrs2 = peerstore2.addrs(peer_id_2)
        assert len(addrs2) == 1
        assert addrs2[0] == addr2

        protocols2 = peerstore2.get_protocols(peer_id_2)
        assert "/ipfs/id/1.0.0" in protocols2

        version = peerstore2.get(peer_id_2, "version")
        assert version == "1.0.0"

        peerstore2.close()


def test_sync_sqlite_data_updates_persistence(peer_id, addr, addr2):
    """Test that data updates are properly persisted."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "test.db"

        # Create first peerstore and add initial data
        peerstore1 = create_sync_sqlite_peerstore(str(db_path))
        peerstore1.add_addrs(peer_id, [addr], 3600)
        peerstore1.put(peer_id, "version", "1.0.0")
        peerstore1.close()

        # Create second peerstore and update data
        peerstore2 = create_sync_sqlite_peerstore(str(db_path))
        peerstore2.add_addrs(peer_id, [addr2], 3600)  # Add second address
        peerstore2.put(peer_id, "version", "2.0.0")  # Update version
        peerstore2.close()

        # Create third peerstore and verify updates persisted
        peerstore3 = create_sync_sqlite_peerstore(str(db_path))

        addrs = peerstore3.addrs(peer_id)
        assert len(addrs) == 2
        assert addr in addrs
        assert addr2 in addrs

        version = peerstore3.get(peer_id, "version")
        assert version == "2.0.0"

        peerstore3.close()


def test_sync_memory_not_persistent(peer_id, addr):
    """Test that sync memory peerstore is not persistent."""
    # Create memory peerstore and add data
    peerstore1 = create_sync_memory_peerstore()
    peerstore1.add_addrs(peer_id, [addr], 3600)
    peerstore1.put(peer_id, "test", "value")
    peerstore1.close()

    # Create new memory peerstore
    peerstore2 = create_sync_memory_peerstore()

    # Verify data is not persisted
    addrs = peerstore2.addrs(peer_id)
    assert len(addrs) == 0

    with pytest.raises(PeerStoreError):
        peerstore2.get(peer_id, "test")

    peerstore2.close()


def test_sync_leveldb_persistence_if_available(peer_id, addr):
    """Test LevelDB persistence if available."""
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "leveldb"

            # Create first peerstore and add data
            peerstore1 = create_sync_leveldb_peerstore(str(db_path))
            peerstore1.add_addrs(peer_id, [addr], 3600)
            peerstore1.put(peer_id, "test", "value")
            peerstore1.close()

            # Create second peerstore and verify data persisted
            peerstore2 = create_sync_leveldb_peerstore(str(db_path))

            addrs = peerstore2.addrs(peer_id)
            assert len(addrs) == 1
            assert addrs[0] == addr

            value = peerstore2.get(peer_id, "test")
            assert value == "value"

            peerstore2.close()
    except ImportError:
        pytest.skip("LevelDB backend not available (plyvel not installed)")


def test_sync_rocksdb_persistence_if_available(peer_id, addr):
    """Test RocksDB persistence if available."""
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "rocksdb"

            # Create first peerstore and add data
            peerstore1 = create_sync_rocksdb_peerstore(str(db_path))
            peerstore1.add_addrs(peer_id, [addr], 3600)
            peerstore1.put(peer_id, "test", "value")
            peerstore1.close()

            # Create second peerstore and verify data persisted
            peerstore2 = create_sync_rocksdb_peerstore(str(db_path))

            addrs = peerstore2.addrs(peer_id)
            assert len(addrs) == 1
            assert addrs[0] == addr

            value = peerstore2.get(peer_id, "test")
            assert value == "value"

            peerstore2.close()
    except ImportError:
        pytest.skip("RocksDB backend not available (python-rocksdb not installed)")


# ============================================================================
# Cross-Backend Persistence Tests
# ============================================================================


@pytest.mark.trio
async def test_async_cross_backend_no_persistence():
    """Test that different backends don't share data."""
    from multiaddr import Multiaddr

    from libp2p.peer.id import ID

    peer_id = ID.from_base58("QmTestPeer")
    addr = Multiaddr("/ip4/127.0.0.1/tcp/4001")

    # Add data to memory backend
    memory_store = create_async_memory_peerstore()
    await memory_store.add_addrs_async(peer_id, [addr], 3600)
    await memory_store.close_async()

    # Create SQLite backend - should not have the data
    with tempfile.TemporaryDirectory() as temp_dir:
        sqlite_store = create_async_sqlite_peerstore(Path(temp_dir) / "test.db")
        addrs = await sqlite_store.addrs_async(peer_id)
        assert len(addrs) == 0
        await sqlite_store.close_async()


def test_sync_cross_backend_no_persistence():
    """Test that different backends don't share data."""
    from multiaddr import Multiaddr

    from libp2p.peer.id import ID

    peer_id = ID.from_base58("QmTestPeer")
    addr = Multiaddr("/ip4/127.0.0.1/tcp/4001")

    # Add data to memory backend
    memory_store = create_sync_memory_peerstore()
    memory_store.add_addrs(peer_id, [addr], 3600)
    memory_store.close()

    # Create SQLite backend - should not have the data
    with tempfile.TemporaryDirectory() as temp_dir:
        sqlite_store = create_sync_sqlite_peerstore(Path(temp_dir) / "test.db")
        addrs = sqlite_store.addrs(peer_id)
        assert len(addrs) == 0
        sqlite_store.close()
