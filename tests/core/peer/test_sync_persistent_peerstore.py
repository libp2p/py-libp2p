"""
Tests for SyncPersistentPeerStore implementation.

This module contains functional tests for the SyncPersistentPeerStore class,
testing all synchronous methods without the _async suffix.
"""

from pathlib import Path
import tempfile

import pytest
from multiaddr import Multiaddr
import trio

from libp2p.peer.id import ID
from libp2p.peer.peerstore import PeerStoreError
from libp2p.peer.persistent import (
    create_sync_memory_peerstore,
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


@pytest.fixture
def sync_memory_peerstore():
    """Create a sync memory-based peerstore for testing."""
    return create_sync_memory_peerstore()


@pytest.fixture
def sync_sqlite_peerstore():
    """Create a sync SQLite-based peerstore for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield create_sync_sqlite_peerstore(Path(temp_dir) / "test.db")


# ============================================================================
# Basic Functionality Tests
# ============================================================================


def test_initialization(sync_memory_peerstore):
    """Test sync peerstore initialization."""
    assert sync_memory_peerstore.max_records == 10000
    assert len(sync_memory_peerstore.peer_data_map) == 0
    assert len(sync_memory_peerstore.peer_record_map) == 0
    assert sync_memory_peerstore.local_peer_record is None


def test_add_and_get_addrs(sync_memory_peerstore, peer_id, addr):
    """Test adding and retrieving addresses."""
    # Add address
    sync_memory_peerstore.add_addrs(peer_id, [addr], 3600)

    # Retrieve address
    addrs = sync_memory_peerstore.addrs(peer_id)
    assert len(addrs) == 1
    assert addrs[0] == addr


def test_add_multiple_addrs(sync_memory_peerstore, peer_id, addr, addr2):
    """Test adding multiple addresses."""
    # Add multiple addresses
    sync_memory_peerstore.add_addrs(peer_id, [addr, addr2], 3600)

    # Retrieve addresses
    addrs = sync_memory_peerstore.addrs(peer_id)
    assert len(addrs) == 2
    assert addr in addrs
    assert addr2 in addrs


def test_add_and_get_protocols(sync_memory_peerstore, peer_id):
    """Test adding and retrieving protocols."""
    protocols = ["/ipfs/ping/1.0.0", "/ipfs/id/1.0.0"]

    # Add protocols
    sync_memory_peerstore.add_protocols(peer_id, protocols)

    # Retrieve protocols
    retrieved_protocols = sync_memory_peerstore.get_protocols(peer_id)
    assert set(retrieved_protocols) == set(protocols)


def test_add_and_get_metadata(sync_memory_peerstore, peer_id):
    """Test adding and retrieving metadata."""
    key = "agent"
    value = "py-libp2p/0.1.0"

    # Add metadata
    sync_memory_peerstore.put(peer_id, key, value)

    # Retrieve metadata
    retrieved_value = sync_memory_peerstore.get(peer_id, key)
    assert retrieved_value == value


def test_latency_recording(sync_memory_peerstore, peer_id):
    """Test latency recording and retrieval."""
    # Record latency
    sync_memory_peerstore.record_latency(peer_id, 0.05)  # 50ms

    # Retrieve latency
    latency = sync_memory_peerstore.latency_EWMA(peer_id)
    assert latency > 0


def test_peer_info(sync_memory_peerstore, peer_id, addr):
    """Test peer info retrieval."""
    # Add address
    sync_memory_peerstore.add_addrs(peer_id, [addr], 3600)

    # Get peer info
    peer_info = sync_memory_peerstore.peer_info(peer_id)
    assert peer_info.peer_id == peer_id
    assert len(peer_info.addrs) == 1
    assert peer_info.addrs[0] == addr


def test_peer_ids(sync_memory_peerstore, peer_id, peer_id_2, addr):
    """Test peer ID listing."""
    # Add addresses for two peers
    sync_memory_peerstore.add_addrs(peer_id, [addr], 3600)
    sync_memory_peerstore.add_addrs(peer_id_2, [addr], 3600)

    # Get all peer IDs
    peer_ids = sync_memory_peerstore.peer_ids()
    assert len(peer_ids) == 2
    assert peer_id in peer_ids
    assert peer_id_2 in peer_ids


def test_valid_peer_ids(sync_memory_peerstore, peer_id, peer_id_2, addr):
    """Test valid peer ID listing."""
    # Add addresses for two peers
    sync_memory_peerstore.add_addrs(peer_id, [addr], 3600)
    sync_memory_peerstore.add_addrs(peer_id_2, [addr], 3600)

    # Get valid peer IDs
    valid_peer_ids = sync_memory_peerstore.valid_peer_ids()
    assert len(valid_peer_ids) == 2
    assert peer_id in valid_peer_ids
    assert peer_id_2 in valid_peer_ids


def test_peers_with_addrs(sync_memory_peerstore, peer_id, peer_id_2, addr):
    """Test peers with addresses listing."""
    # Add addresses for two peers
    sync_memory_peerstore.add_addrs(peer_id, [addr], 3600)
    sync_memory_peerstore.add_addrs(peer_id_2, [addr], 3600)

    # Get peers with addresses
    peers_with_addrs = sync_memory_peerstore.peers_with_addrs()
    assert len(peers_with_addrs) == 2
    assert peer_id in peers_with_addrs
    assert peer_id_2 in peers_with_addrs


def test_supports_protocols(sync_memory_peerstore, peer_id):
    """Test protocol support checking."""
    protocols = ["/ipfs/ping/1.0.0", "/ipfs/id/1.0.0", "/ipfs/kad/1.0.0"]
    sync_memory_peerstore.add_protocols(peer_id, protocols)

    # Check supported protocols
    supported = sync_memory_peerstore.supports_protocols(
        peer_id, ["/ipfs/ping/1.0.0", "/ipfs/unknown/1.0.0"]
    )
    assert "/ipfs/ping/1.0.0" in supported
    assert "/ipfs/unknown/1.0.0" not in supported


def test_first_supported_protocol(sync_memory_peerstore, peer_id):
    """Test first supported protocol finding."""
    protocols = ["/ipfs/ping/1.0.0", "/ipfs/id/1.0.0"]
    sync_memory_peerstore.add_protocols(peer_id, protocols)

    # Find first supported protocol
    first_supported = sync_memory_peerstore.first_supported_protocol(
        peer_id, ["/ipfs/unknown/1.0.0", "/ipfs/ping/1.0.0", "/ipfs/id/1.0.0"]
    )
    assert first_supported == "/ipfs/ping/1.0.0"


# ============================================================================
# Data Management Tests
# ============================================================================


def test_clear_peerdata(sync_memory_peerstore, peer_id, addr):
    """Test clearing peer data."""
    # Add some data
    sync_memory_peerstore.add_addrs(peer_id, [addr], 3600)
    sync_memory_peerstore.add_protocols(peer_id, ["/ipfs/ping/1.0.0"])
    sync_memory_peerstore.put(peer_id, "test", "value")

    # Clear peer data
    sync_memory_peerstore.clear_peerdata(peer_id)

    # Verify data is cleared - should return empty list, not raise error
    addrs = sync_memory_peerstore.addrs(peer_id)
    assert len(addrs) == 0


def test_clear_protocol_data(sync_memory_peerstore, peer_id):
    """Test clearing protocol data."""
    protocols = ["/ipfs/ping/1.0.0", "/ipfs/id/1.0.0"]
    sync_memory_peerstore.add_protocols(peer_id, protocols)

    # Clear protocol data
    sync_memory_peerstore.clear_protocol_data(peer_id)

    # Verify protocols are cleared
    retrieved_protocols = sync_memory_peerstore.get_protocols(peer_id)
    assert len(retrieved_protocols) == 0


def test_clear_metadata(sync_memory_peerstore, peer_id):
    """Test clearing metadata."""
    sync_memory_peerstore.put(peer_id, "test", "value")
    sync_memory_peerstore.put(peer_id, "test2", "value2")

    # Clear metadata
    sync_memory_peerstore.clear_metadata(peer_id)

    # Verify metadata is cleared
    with pytest.raises(PeerStoreError):
        sync_memory_peerstore.get(peer_id, "test")


def test_clear_keydata(sync_memory_peerstore, peer_id):
    """Test clearing key data."""
    # This test would require actual key objects, so we'll just test the method exists
    sync_memory_peerstore.clear_keydata(peer_id)


def test_clear_metrics(sync_memory_peerstore, peer_id):
    """Test clearing metrics."""
    sync_memory_peerstore.record_latency(peer_id, 0.05)

    # Clear metrics
    sync_memory_peerstore.clear_metrics(peer_id)

    # Verify metrics are cleared
    latency = sync_memory_peerstore.latency_EWMA(peer_id)
    assert latency == 0


# ============================================================================
# Stream Tests
# ============================================================================


def test_addr_stream_not_supported(sync_memory_peerstore, peer_id):
    """Test that addr_stream is not supported in sync peerstore."""
    # This should raise NotImplementedError
    with pytest.raises(NotImplementedError):
        # We need to use trio.run to call the async method
        trio.run(sync_memory_peerstore.addr_stream, peer_id)


# ============================================================================
# Lifecycle Tests
# ============================================================================


def test_close(sync_memory_peerstore):
    """Test closing the sync peerstore."""
    # This should not raise an exception
    sync_memory_peerstore.close()


# ============================================================================
# Error Handling Tests
# ============================================================================


def test_nonexistent_peer(sync_memory_peerstore, peer_id):
    """Test operations on nonexistent peer."""
    # Should return empty list, not raise error
    addrs = sync_memory_peerstore.addrs(peer_id)
    assert len(addrs) == 0


def test_nonexistent_metadata(sync_memory_peerstore, peer_id):
    """Test getting nonexistent metadata."""
    with pytest.raises(PeerStoreError):
        sync_memory_peerstore.get(peer_id, "nonexistent")


def test_empty_peer_ids(sync_memory_peerstore):
    """Test getting peer IDs from empty peerstore."""
    peer_ids = sync_memory_peerstore.peer_ids()
    assert len(peer_ids) == 0


def test_empty_valid_peer_ids(sync_memory_peerstore):
    """Test getting valid peer IDs from empty peerstore."""
    valid_peer_ids = sync_memory_peerstore.valid_peer_ids()
    assert len(valid_peer_ids) == 0


def test_empty_peers_with_addrs(sync_memory_peerstore):
    """Test getting peers with addresses from empty peerstore."""
    peers_with_addrs = sync_memory_peerstore.peers_with_addrs()
    assert len(peers_with_addrs) == 0


# ============================================================================
# SQLite Persistence Test
# ============================================================================


def test_sqlite_persistence(peer_id, addr):
    """Test SQLite persistence with sync peerstore."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "test.db"

        # Create first peerstore
        peerstore1 = create_sync_sqlite_peerstore(str(db_path))
        peerstore1.add_addrs(peer_id, [addr], 3600)
        peerstore1.add_protocols(peer_id, ["/ipfs/ping/1.0.0"])
        peerstore1.put(peer_id, "test", "value")

        peerstore1.close()

        # Create second peerstore
        peerstore2 = create_sync_sqlite_peerstore(str(db_path))

        # Verify data was persisted
        addrs = peerstore2.addrs(peer_id)
        assert len(addrs) == 1
        assert addrs[0] == addr

        protocols = peerstore2.get_protocols(peer_id)
        assert "/ipfs/ping/1.0.0" in protocols

        value = peerstore2.get(peer_id, "test")
        assert value == "value"

        peerstore2.close()


def test_memory_not_persistent(peer_id, addr):
    """Test that sync memory peerstore is not persistent."""
    # Create memory peerstore
    peerstore1 = create_sync_memory_peerstore()
    peerstore1.add_addrs(peer_id, [addr], 3600)
    peerstore1.close()

    # Create new memory peerstore
    peerstore2 = create_sync_memory_peerstore()

    # Verify data is not persisted - should return empty list
    addrs = peerstore2.addrs(peer_id)
    assert len(addrs) == 0

    peerstore2.close()


def test_sync_peerstore_lru_cache_eviction(tmp_path):
    """Test that SyncPersistentPeerStore bounds cache and protects local ID."""
    from libp2p.crypto.ed25519 import create_new_key_pair
    from libp2p.peer.persistent.datastore.sqlite_sync import SQLiteDatastoreSync
    from libp2p.peer.persistent.sync.peerstore import SyncPersistentPeerStore

    db_path = tmp_path / "lru_peerstore.db"
    datastore = SQLiteDatastoreSync(str(db_path))
    # Cap memory cache to 5 peers
    store = SyncPersistentPeerStore(datastore, max_cached_peers=5)

    # 1. Add local peer identity
    local_key_pair = create_new_key_pair()
    local_id = ID.from_pubkey(local_key_pair.public_key)
    store.add_key_pair(local_id, local_key_pair)

    assert local_id in store.peer_data_map
    assert store.privkey(local_id) == local_key_pair.private_key

    # 2. Add 10 remote peers
    remote_peers = []
    for i in range(10):
        key_pair = create_new_key_pair()
        pid = ID.from_pubkey(key_pair.public_key)
        remote_peers.append(pid)
        store.add_addrs(pid, [Multiaddr(f"/ip4/10.0.0.{i + 1}/tcp/4001")], ttl=3600)
        store.add_protocols(pid, [f"/proto/{i}"])

    # In-memory cache must not exceed max_cached_peers (5)
    assert len(store.peer_data_map) == 5

    # Local peer identity must NEVER be evicted
    assert local_id in store.peer_data_map
    assert store.privkey(local_id) == local_key_pair.private_key

    # 3. Oldest evicted peers can still be retrieved (reloaded from SQLite on demand)
    oldest_pid = remote_peers[0]
    assert oldest_pid not in store.peer_data_map  # Was evicted from RAM
    # Reading it should transparently load from datastore
    addrs = store.addrs(oldest_pid)
    assert len(addrs) == 1
    assert str(addrs[0]) == "/ip4/10.0.0.1/tcp/4001"
    assert "/proto/0" in store.get_protocols(oldest_pid)

    # Now oldest_pid is loaded back into RAM cache
    assert oldest_pid in store.peer_data_map
    assert len(store.peer_data_map) == 5
    # Local identity still preserved
    assert local_id in store.peer_data_map

    store.close()


def test_sync_peerstore_lru_access_order():
    """Test that accessing a peer refreshes its LRU position."""
    from libp2p.crypto.ed25519 import create_new_key_pair
    from libp2p.peer.persistent.datastore.memory_sync import MemoryDatastoreSync
    from libp2p.peer.persistent.sync.peerstore import SyncPersistentPeerStore

    datastore = MemoryDatastoreSync()
    store = SyncPersistentPeerStore(datastore, max_cached_peers=3)

    peers = []
    for i in range(3):
        kp = create_new_key_pair()
        pid = ID.from_pubkey(kp.public_key)
        peers.append(pid)
        store.add_addrs(pid, [Multiaddr(f"/ip4/192.168.1.{i + 1}/tcp/4001")], ttl=3600)

    # Memory cache has peers[0], peers[1], peers[2]
    assert list(store.peer_data_map.keys()) == peers

    # Access peers[0] (should move to MRU)
    _ = store.addrs(peers[0])
    assert list(store.peer_data_map.keys()) == [peers[1], peers[2], peers[0]]

    # Add a 4th peer -> should evict peers[1] (oldest), keeping peers[0] and peers[2]
    kp4 = create_new_key_pair()
    pid4 = ID.from_pubkey(kp4.public_key)
    store.add_addrs(pid4, [Multiaddr("/ip4/192.168.1.4/tcp/4001")], ttl=3600)

    assert len(store.peer_data_map) == 3
    assert peers[1] not in store.peer_data_map
    assert peers[0] in store.peer_data_map
    assert peers[2] in store.peer_data_map
    assert pid4 in store.peer_data_map

    store.close()


def test_sync_peerstore_count_peers(tmp_path):
    from libp2p.crypto.ed25519 import create_new_key_pair
    from libp2p.peer.persistent.datastore.sqlite_sync import SQLiteDatastoreSync
    from libp2p.peer.persistent.sync.peerstore import SyncPersistentPeerStore

    db_path = tmp_path / "count_peerstore.db"
    datastore = SQLiteDatastoreSync(path=db_path)
    store = SyncPersistentPeerStore(datastore)

    assert store.count_peers() == 0

    for i in range(5):
        kp = create_new_key_pair()
        pid = ID.from_pubkey(kp.public_key)
        store.add_addrs(pid, [Multiaddr(f"/ip4/192.168.1.{i + 1}/tcp/4001")], ttl=3600)

    assert store.count_peers() == 5
    store.close()


def test_sync_peerstore_bounds_persisted_peers(tmp_path):
    """Evicting peers from the cache must also bound the datastore rows."""
    from libp2p.peer.persistent.datastore.sqlite_sync import SQLiteDatastoreSync
    from libp2p.peer.persistent.sync.peerstore import SyncPersistentPeerStore

    datastore = SQLiteDatastoreSync(path=tmp_path / "bounded_peerstore.db")
    store = SyncPersistentPeerStore(
        datastore, max_cached_peers=50, max_stored_peers=200
    )

    for i in range(1000):
        store.add_addrs(
            ID(b"peer-%08d" % i),
            [Multiaddr(f"/ip4/10.0.0.1/tcp/{1000 + i}")],
            ttl=3600,
        )

    rows = datastore.count(store.ADDR_PREFIX)
    assert rows <= 200 + store.DATASTORE_PRUNE_INTERVAL
    store.close()


def test_sync_peerstore_trim_legacy_backlog(tmp_path):
    """enforce_datastore_limit() drains rows written by an older build."""
    from libp2p.peer.persistent.datastore.sqlite_sync import SQLiteDatastoreSync
    from libp2p.peer.persistent.sync.peerstore import SyncPersistentPeerStore

    db_path = tmp_path / "legacy_peerstore.db"
    datastore = SQLiteDatastoreSync(path=db_path)
    # An unbounded legacy store: every peer keeps its rows.
    legacy = SyncPersistentPeerStore(
        datastore, max_cached_peers=500, max_stored_peers=500
    )
    for i in range(500):
        legacy.add_addrs(
            ID(b"legacy-%08d" % i),
            [Multiaddr(f"/ip4/10.0.0.2/tcp/{2000 + i}")],
            ttl=3600,
        )
    assert datastore.count(legacy.ADDR_PREFIX) == 500

    # Restart with a smaller cap: the cache is empty, so the backlog is visible.
    store = SyncPersistentPeerStore(
        datastore, max_cached_peers=100, max_stored_peers=100
    )
    removed = store.enforce_datastore_limit()
    assert removed == 400
    assert datastore.count(store.ADDR_PREFIX) == 100
    store.close()


def test_sync_peerstore_caps_addresses_loaded_from_datastore(tmp_path):
    """Rows written before the per-peer cap must be truncated on load."""
    from libp2p.peer.peerdata import MAX_ADDRS_PER_PEER
    from libp2p.peer.persistent.datastore.sqlite_sync import SQLiteDatastoreSync
    from libp2p.peer.persistent.serialization import serialize_addresses
    from libp2p.peer.persistent.sync.peerstore import SyncPersistentPeerStore

    datastore = SQLiteDatastoreSync(path=tmp_path / "legacy_addrs.db")
    pid = ID(b"legacy-addresses")
    addrs = [
        Multiaddr(f"/ip4/10.0.0.1/tcp/{1000 + i}")
        for i in range(MAX_ADDRS_PER_PEER + 200)
    ]
    datastore.put(b"addr:" + pid.to_bytes(), serialize_addresses(addrs))

    store = SyncPersistentPeerStore(datastore)
    loaded = store.addrs(pid)
    assert len(loaded) == MAX_ADDRS_PER_PEER
    assert loaded[-1] == addrs[-1]
    assert addrs[0] not in loaded
    store.close()


def test_sync_peerstore_prunes_peers_without_addresses(tmp_path):
    """Peers that only have protocol/key rows must also be pruned."""
    from libp2p.peer.persistent.datastore.sqlite_sync import SQLiteDatastoreSync
    from libp2p.peer.persistent.sync.peerstore import SyncPersistentPeerStore

    datastore = SQLiteDatastoreSync(path=tmp_path / "addrless_peerstore.db")
    legacy = SyncPersistentPeerStore(
        datastore, max_cached_peers=500, max_stored_peers=500
    )
    # No addresses at all: only an identify-style protocol row per peer.
    for i in range(500):
        legacy.add_protocols(ID(b"addrless-%08d" % i), ["/ipfs/id/1.0.0"])
    assert datastore.count(b"protocol:") == 500

    store = SyncPersistentPeerStore(datastore, max_cached_peers=50, max_stored_peers=50)
    removed = store.enforce_datastore_limit()
    assert removed == 450
    assert datastore.count(b"protocol:") == 50
    store.close()


def test_sqlite_compact_truncates_wal(tmp_path):
    """A big delete + compact must not leave a huge WAL sidecar behind."""
    from libp2p.peer.persistent.datastore.sqlite_sync import SQLiteDatastoreSync

    db_path = tmp_path / "wal_peerstore.db"
    datastore = SQLiteDatastoreSync(path=db_path)
    payload = b"x" * 2048
    for i in range(4000):
        datastore.put(b"addr:" + (b"%08d" % i), payload)
    datastore.sync(b"")

    batch = datastore.batch()
    for i in range(4000):
        batch.delete(b"addr:" + (b"%08d" % i))
    batch.commit()
    datastore.sync(b"")

    assert datastore.compact(min_free_bytes=0) is True
    wal_size = db_path.with_suffix(".db-wal").stat().st_size
    assert wal_size == 0
    datastore.close()


def test_sqlite_compact_truncates_wal_without_vacuum(tmp_path):
    """compact() drains the WAL even when no VACUUM is needed."""
    from libp2p.peer.persistent.datastore.sqlite_sync import SQLiteDatastoreSync

    db_path = tmp_path / "wal_no_vacuum.db"
    datastore = SQLiteDatastoreSync(path=db_path)
    for i in range(500):
        datastore.put(b"key:" + (b"%08d" % i), b"y" * 1024)
    datastore.sync(b"")
    wal_path = db_path.parent / (db_path.name + "-wal")
    assert wal_path.stat().st_size > 0

    # min_free_bytes well above what the freelist holds -> no VACUUM.
    assert datastore.compact(min_free_bytes=1 << 40) is False
    assert datastore.checkpoint() is True
    assert wal_path.stat().st_size == 0
    datastore.close()
