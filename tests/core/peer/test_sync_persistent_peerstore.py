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
