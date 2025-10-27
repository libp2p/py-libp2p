"""
Tests for PersistentPeerStore implementation.

This module contains comprehensive tests for the PersistentPeerStore class,
including tests for different datastore backends and persistence behavior.
"""

import importlib.util
from pathlib import Path
import tempfile
from unittest.mock import AsyncMock, Mock, patch

import pytest
from multiaddr import Multiaddr
import trio

from libp2p.peer.id import ID
from libp2p.peer.peerstore import PeerStoreError
from libp2p.peer.persistent_peerstore import PersistentPeerStore
from libp2p.peer.persistent_peerstore_factory import (
    create_leveldb_peerstore,
    create_memory_peerstore,
    create_rocksdb_peerstore,
    create_sqlite_peerstore,
)


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


@pytest.fixture
def memory_peerstore():
    """Create a memory-based peerstore for testing."""
    return create_memory_peerstore()


@pytest.fixture
def sqlite_peerstore():
    """Create a SQLite-based peerstore for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield create_sqlite_peerstore(Path(temp_dir) / "test.db")


@pytest.mark.trio
async def test_initialization(memory_peerstore):
    """Test peerstore initialization."""
    assert memory_peerstore.max_records == 10000
    assert len(memory_peerstore.peer_data_map) == 0
    assert len(memory_peerstore.peer_record_map) == 0
    assert memory_peerstore.local_peer_record is None


@pytest.mark.trio
async def test_add_and_get_addrs(memory_peerstore, peer_id, addr):
    """Test adding and retrieving addresses."""
    # Add address
    memory_peerstore.add_addrs(peer_id, [addr], 3600)

    # Retrieve address
    addrs = memory_peerstore.addrs(peer_id)
    assert len(addrs) == 1
    assert addrs[0] == addr


@pytest.mark.trio
async def test_add_and_get_protocols(memory_peerstore, peer_id):
    """Test adding and retrieving protocols."""
    protocols = ["/ipfs/ping/1.0.0", "/ipfs/id/1.0.0"]

    # Add protocols
    memory_peerstore.add_protocols(peer_id, protocols)

    # Retrieve protocols
    retrieved_protocols = memory_peerstore.get_protocols(peer_id)
    assert set(retrieved_protocols) == set(protocols)


@pytest.mark.trio
async def test_add_and_get_metadata(memory_peerstore, peer_id):
    """Test adding and retrieving metadata."""
    key = "agent"
    value = "py-libp2p/0.1.0"

    # Add metadata
    memory_peerstore.put(peer_id, key, value)

    # Retrieve metadata
    retrieved_value = memory_peerstore.get(peer_id, key)
    assert retrieved_value == value


@pytest.mark.trio
async def test_latency_recording(memory_peerstore, peer_id):
    """Test latency recording and retrieval."""
    # Record latency
    memory_peerstore.record_latency(peer_id, 0.05)  # 50ms

    # Retrieve latency
    latency = memory_peerstore.latency_EWMA(peer_id)
    assert latency > 0


@pytest.mark.trio
async def test_peer_info(memory_peerstore, peer_id, addr):
    """Test peer info retrieval."""
    # Add address
    memory_peerstore.add_addrs(peer_id, [addr], 3600)

    # Get peer info
    peer_info = memory_peerstore.peer_info(peer_id)
    assert peer_info.peer_id == peer_id
    assert len(peer_info.addrs) == 1
    assert peer_info.addrs[0] == addr


@pytest.mark.trio
async def test_peer_ids(memory_peerstore, peer_id, peer_id_2, addr):
    """Test peer ID listing."""
    # Add addresses for two peers
    memory_peerstore.add_addrs(peer_id, [addr], 3600)
    memory_peerstore.add_addrs(peer_id_2, [addr], 3600)

    # Get all peer IDs
    peer_ids = memory_peerstore.peer_ids()
    assert len(peer_ids) == 2
    assert peer_id in peer_ids
    assert peer_id_2 in peer_ids


@pytest.mark.trio
async def test_clear_peerdata(memory_peerstore, peer_id, addr):
    """Test clearing peer data."""
    # Add some data
    memory_peerstore.add_addrs(peer_id, [addr], 3600)
    memory_peerstore.add_protocols(peer_id, ["/ipfs/ping/1.0.0"])
    memory_peerstore.put(peer_id, "test", "value")

    # Clear peer data
    memory_peerstore.clear_peerdata(peer_id)

    # Verify data is cleared
    with pytest.raises(PeerStoreError):
        memory_peerstore.addrs(peer_id)


@pytest.mark.trio
async def test_valid_peer_ids(memory_peerstore, peer_id, peer_id_2, addr):
    """Test valid peer ID listing."""
    # Add addresses for two peers
    memory_peerstore.add_addrs(peer_id, [addr], 3600)
    memory_peerstore.add_addrs(peer_id_2, [addr], 3600)

    # Get valid peer IDs
    valid_peer_ids = memory_peerstore.valid_peer_ids()
    assert len(valid_peer_ids) == 2
    assert peer_id in valid_peer_ids
    assert peer_id_2 in valid_peer_ids


@pytest.mark.trio
async def test_peers_with_addrs(memory_peerstore, peer_id, peer_id_2, addr):
    """Test peers with addresses listing."""
    # Add addresses for two peers
    memory_peerstore.add_addrs(peer_id, [addr], 3600)
    memory_peerstore.add_addrs(peer_id_2, [addr], 3600)

    # Get peers with addresses
    peers_with_addrs = memory_peerstore.peers_with_addrs()
    assert len(peers_with_addrs) == 2
    assert peer_id in peers_with_addrs
    assert peer_id_2 in peers_with_addrs


@pytest.mark.trio
async def test_supports_protocols(memory_peerstore, peer_id):
    """Test protocol support checking."""
    protocols = ["/ipfs/ping/1.0.0", "/ipfs/id/1.0.0", "/ipfs/kad/1.0.0"]
    memory_peerstore.add_protocols(peer_id, protocols)

    # Check supported protocols
    supported = memory_peerstore.supports_protocols(
        peer_id, ["/ipfs/ping/1.0.0", "/ipfs/unknown/1.0.0"]
    )
    assert "/ipfs/ping/1.0.0" in supported
    assert "/ipfs/unknown/1.0.0" not in supported


@pytest.mark.trio
async def test_first_supported_protocol(memory_peerstore, peer_id):
    """Test first supported protocol finding."""
    protocols = ["/ipfs/ping/1.0.0", "/ipfs/id/1.0.0"]
    memory_peerstore.add_protocols(peer_id, protocols)

    # Find first supported protocol
    first_supported = memory_peerstore.first_supported_protocol(
        peer_id, ["/ipfs/unknown/1.0.0", "/ipfs/ping/1.0.0", "/ipfs/id/1.0.0"]
    )
    assert first_supported == "/ipfs/ping/1.0.0"


@pytest.mark.trio
async def test_clear_protocol_data(memory_peerstore, peer_id):
    """Test clearing protocol data."""
    protocols = ["/ipfs/ping/1.0.0", "/ipfs/id/1.0.0"]
    memory_peerstore.add_protocols(peer_id, protocols)

    # Clear protocol data
    memory_peerstore.clear_protocol_data(peer_id)

    # Verify protocols are cleared
    retrieved_protocols = memory_peerstore.get_protocols(peer_id)
    assert len(retrieved_protocols) == 0


@pytest.mark.trio
async def test_clear_metadata(memory_peerstore, peer_id):
    """Test clearing metadata."""
    memory_peerstore.put(peer_id, "test", "value")
    memory_peerstore.put(peer_id, "test2", "value2")

    # Clear metadata
    memory_peerstore.clear_metadata(peer_id)

    # Verify metadata is cleared
    with pytest.raises(PeerStoreError):
        memory_peerstore.get(peer_id, "test")


@pytest.mark.trio
async def test_clear_keydata(memory_peerstore, peer_id):
    """Test clearing key data."""
    # This test would require actual key objects, so we'll just test the method exists
    # In a real implementation, you'd need to create actual PublicKey/PrivateKey objects
    memory_peerstore.clear_keydata(peer_id)


@pytest.mark.trio
async def test_clear_metrics(memory_peerstore, peer_id):
    """Test clearing metrics."""
    memory_peerstore.record_latency(peer_id, 0.05)

    # Clear metrics
    memory_peerstore.clear_metrics(peer_id)

    # Verify metrics are cleared
    latency = memory_peerstore.latency_EWMA(peer_id)
    assert latency == 0


@pytest.mark.trio
async def test_local_record(memory_peerstore):
    """Test local record operations."""
    # Mock envelope
    envelope = Mock()

    # Set local record
    memory_peerstore.set_local_record(envelope)

    # Get local record
    retrieved_envelope = memory_peerstore.get_local_record()
    assert retrieved_envelope == envelope


@pytest.mark.trio
async def test_consume_peer_record(memory_peerstore, peer_id, addr):
    """Test consuming peer records."""
    # Mock envelope and record
    envelope = Mock()
    record = Mock()
    record.peer_id = peer_id
    record.addrs = [addr]
    record.seq = 1
    envelope.record.return_value = record

    # Consume peer record
    result = memory_peerstore.consume_peer_record(envelope, 3600)
    assert result is True


@pytest.mark.trio
async def test_consume_peer_records(memory_peerstore, peer_id, addr):
    """Test consuming multiple peer records."""
    # Mock envelopes
    envelope1 = Mock()
    record1 = Mock()
    record1.peer_id = peer_id
    record1.addrs = [addr]
    record1.seq = 1
    envelope1.record.return_value = record1

    envelope2 = Mock()
    record2 = Mock()
    record2.peer_id = peer_id
    record2.addrs = [addr]
    record2.seq = 2
    envelope2.record.return_value = record2

    # Consume multiple peer records
    results = memory_peerstore.consume_peer_records([envelope1, envelope2], 3600)
    assert len(results) == 2
    assert all(results)


@pytest.mark.trio
async def test_get_peer_record(memory_peerstore, peer_id, addr):
    """Test getting peer records."""
    # Add address first
    memory_peerstore.add_addrs(peer_id, [addr], 3600)

    # Mock envelope and record
    envelope = Mock()
    record = Mock()
    record.peer_id = peer_id
    record.addrs = [addr]
    record.seq = 1
    envelope.record.return_value = record

    # Consume peer record
    memory_peerstore.consume_peer_record(envelope, 3600)

    # Get peer record
    retrieved_envelope = memory_peerstore.get_peer_record(peer_id)
    assert retrieved_envelope == envelope


@pytest.mark.trio
async def test_maybe_delete_peer_record(memory_peerstore, peer_id):
    """Test maybe deleting peer records."""
    # This should not raise an exception
    memory_peerstore.maybe_delete_peer_record(peer_id)


@pytest.mark.trio
async def test_addr_stream(memory_peerstore, peer_id, addr):
    """Test address stream functionality."""
    # Start address stream
    stream = memory_peerstore.addr_stream(peer_id)

    # Add address in another task
    async def add_addr():
        await trio.sleep(0.1)
        memory_peerstore.add_addrs(peer_id, [addr], 3600)

    # Run both tasks
    async with trio.open_nursery() as nursery:
        nursery.start_soon(add_addr)
        async for received_addr in stream:
            assert received_addr == addr
            break


@pytest.mark.trio
async def test_close(memory_peerstore):
    """Test closing the peerstore."""
    # This should not raise an exception
    await memory_peerstore.close()


@pytest.mark.trio
async def test_sqlite_persistence(peer_id, addr):
    """Test SQLite persistence."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "test.db"

        # Create first peerstore
        peerstore1 = create_sqlite_peerstore(str(db_path))
        peerstore1.add_addrs(peer_id, [addr], 3600)
        peerstore1.add_protocols(peer_id, ["/ipfs/ping/1.0.0"])
        peerstore1.put(peer_id, "test", "value")

        # Trigger persistence by calling an async method
        # The _load_peer_data method will automatically persist pending changes
        await peerstore1._load_peer_data(peer_id)

        await peerstore1.close()

        # Create second peerstore
        peerstore2 = create_sqlite_peerstore(str(db_path))

        # Trigger data loading by calling an async method
        await peerstore2._load_peer_data(peer_id)

        # Verify data was loaded
        addrs = peerstore2.addrs(peer_id)
        assert len(addrs) == 1
        assert addrs[0] == addr

        protocols = peerstore2.get_protocols(peer_id)
        assert "/ipfs/ping/1.0.0" in protocols

        value = peerstore2.get(peer_id, "test")
        assert value == "value"

        await peerstore2.close()


@pytest.mark.trio
async def test_memory_not_persistent(peer_id, addr):
    """Test that memory peerstore is not persistent."""
    # Create memory peerstore
    peerstore1 = create_memory_peerstore()
    peerstore1.add_addrs(peer_id, [addr], 3600)
    await peerstore1.close()

    # Create new memory peerstore
    peerstore2 = create_memory_peerstore()

    # Verify data is not persisted
    with pytest.raises(PeerStoreError):
        peerstore2.addrs(peer_id)

    await peerstore2.close()


@pytest.mark.trio
async def test_memory_backend():
    """Test memory backend."""
    peerstore = create_memory_peerstore()
    assert isinstance(peerstore, PersistentPeerStore)
    await peerstore.close()


@pytest.mark.trio
async def test_sqlite_backend():
    """Test SQLite backend."""
    with tempfile.TemporaryDirectory() as temp_dir:
        peerstore = create_sqlite_peerstore(Path(temp_dir) / "test.db")
        assert isinstance(peerstore, PersistentPeerStore)
        await peerstore.close()


@pytest.mark.trio
async def test_leveldb_backend():
    """Test LevelDB backend if available."""
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            peerstore = create_leveldb_peerstore(Path(temp_dir) / "leveldb")
            assert isinstance(peerstore, PersistentPeerStore)
            await peerstore.close()
    except ImportError:
        pytest.skip("LevelDB backend not available (plyvel not installed)")


@pytest.mark.trio
async def test_rocksdb_backend():
    """Test RocksDB backend if available."""
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            peerstore = create_rocksdb_peerstore(Path(temp_dir) / "rocksdb")
            assert isinstance(peerstore, PersistentPeerStore)
            await peerstore.close()
    except ImportError:
        pytest.skip("RocksDB backend not available (pyrocksdb not installed)")


@pytest.mark.trio
async def test_nonexistent_peer(memory_peerstore, peer_id):
    """Test operations on nonexistent peer."""
    with pytest.raises(PeerStoreError):
        memory_peerstore.addrs(peer_id)


@pytest.mark.trio
async def test_nonexistent_metadata(memory_peerstore, peer_id):
    """Test getting nonexistent metadata."""
    with pytest.raises(PeerStoreError):
        memory_peerstore.get(peer_id, "nonexistent")


@pytest.mark.trio
async def test_nonexistent_protocols(memory_peerstore, peer_id):
    """Test getting protocols for nonexistent peer."""
    with pytest.raises(PeerStoreError):
        memory_peerstore.get_protocols(peer_id)


@pytest.mark.trio
async def test_nonexistent_latency(memory_peerstore, peer_id):
    """Test getting latency for nonexistent peer."""
    with pytest.raises(PeerStoreError):
        memory_peerstore.latency_EWMA(peer_id)


@pytest.mark.trio
async def test_empty_peer_ids(memory_peerstore):
    """Test getting peer IDs from empty peerstore."""
    peer_ids = memory_peerstore.peer_ids()
    assert len(peer_ids) == 0


@pytest.mark.trio
async def test_empty_valid_peer_ids(memory_peerstore):
    """Test getting valid peer IDs from empty peerstore."""
    valid_peer_ids = memory_peerstore.valid_peer_ids()
    assert len(valid_peer_ids) == 0


@pytest.mark.trio
async def test_empty_peers_with_addrs(memory_peerstore):
    """Test getting peers with addresses from empty peerstore."""
    peers_with_addrs = memory_peerstore.peers_with_addrs()
    assert len(peers_with_addrs) == 0


@pytest.mark.trio
async def test_sqlite_not_initialized():
    """Test SQLite connection not initialized error."""
    from libp2p.peer.datastore.sqlite import SQLiteDatastore

    # Create a datastore with connection that will remain None
    datastore = SQLiteDatastore(":memory:")
    # Mock _ensure_connection to do nothing
    with patch.object(datastore, "_ensure_connection", new=AsyncMock()):
        datastore.connection = None

        # Test get
        with pytest.raises(ValueError, match="SQLite connection is not initialized"):
            await datastore.get(b"key")

        # Test put
        with pytest.raises(ValueError, match="SQLite connection is not initialized"):
            await datastore.put(b"key", b"value")

        # Test delete
        with pytest.raises(ValueError, match="SQLite connection is not initialized"):
            await datastore.delete(b"key")


@pytest.mark.trio
async def test_memory_none_value():
    """Test memory datastore with None value."""
    from libp2p.peer.datastore.memory import MemoryBatch, MemoryDatastore

    datastore = MemoryDatastore()
    batch = MemoryBatch(datastore)

    # Add an operation with None value
    batch.operations.append(("put", b"key", None))

    # Test commit with None value
    with pytest.raises(ValueError, match="Cannot put None value in memory datastore"):
        await batch.commit()


@pytest.mark.trio
@pytest.mark.skipif(
    not importlib.util.find_spec("plyvel"), reason="plyvel not installed"
)
async def test_leveldb_not_initialized():
    """Test LevelDB not initialized error."""
    from libp2p.peer.datastore.leveldb import LevelDBBatch, LevelDBDatastore

    # Create a datastore with db initialized but then set to None
    with patch("plyvel.DB"):  # Mock the DB to avoid actual DB creation
        datastore = LevelDBDatastore("test_db")
        # Skip _ensure_connection to avoid ImportError
        with patch.object(datastore, "_ensure_connection", new=AsyncMock()):
            datastore.db = None

            # Test get
            with pytest.raises(ValueError, match="LevelDB database is not initialized"):
                await datastore.get(b"key")

            # Test put
            with pytest.raises(ValueError, match="LevelDB database is not initialized"):
                await datastore.put(b"key", b"value")

            # Test delete
            with pytest.raises(ValueError, match="LevelDB database is not initialized"):
                await datastore.delete(b"key")

            # Test batch
            batch = LevelDBBatch(datastore)
            batch.put(b"key", b"value")
            with pytest.raises(ValueError, match="LevelDB database is not initialized"):
                await batch.commit()


@pytest.mark.trio
@pytest.mark.skipif(
    not importlib.util.find_spec("rocksdb"), reason="python-rocksdb not installed"
)
async def test_rocksdb_not_initialized():
    """Test RocksDB not initialized error."""
    from libp2p.peer.datastore.rocksdb import RocksDBBatch, RocksDBDatastore

    # Create a datastore with db initialized but then set to None
    with patch("rocksdb.DB"):  # Mock the DB to avoid actual DB creation
        datastore = RocksDBDatastore("test_db")
        # Skip _ensure_connection to avoid ImportError
        with patch.object(datastore, "_ensure_connection", new=AsyncMock()):
            datastore.db = None

            # Test get
            with pytest.raises(ValueError, match="RocksDB database is not initialized"):
                await datastore.get(b"key")

            # Test put
            with pytest.raises(ValueError, match="RocksDB database is not initialized"):
                await datastore.put(b"key", b"value")

            # Test delete
            with pytest.raises(ValueError, match="RocksDB database is not initialized"):
                await datastore.delete(b"key")

            # Test batch
            batch = RocksDBBatch(datastore)
            batch.put(b"key", b"value")
            with pytest.raises(ValueError, match="RocksDB database is not initialized"):
                await batch.commit()
