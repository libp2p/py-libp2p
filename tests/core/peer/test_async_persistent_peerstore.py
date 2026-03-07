"""
Tests for AsyncPersistentPeerStore implementation.

This module contains functional tests for the AsyncPersistentPeerStore class,
testing all async methods with the _async suffix.
"""

from pathlib import Path
import tempfile

import pytest
from multiaddr import Multiaddr
import trio

from libp2p.peer.id import ID
from libp2p.peer.peerstore import PeerStoreError
from libp2p.peer.persistent import (
    create_async_memory_peerstore,
    create_async_sqlite_peerstore,
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
def async_memory_peerstore():
    """Create an async memory-based peerstore for testing."""
    return create_async_memory_peerstore()


@pytest.fixture
def async_sqlite_peerstore():
    """Create an async SQLite-based peerstore for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield create_async_sqlite_peerstore(Path(temp_dir) / "test.db")


# ============================================================================
# Basic Functionality Tests
# ============================================================================


@pytest.mark.trio
async def test_initialization(async_memory_peerstore):
    """Test async peerstore initialization."""
    assert async_memory_peerstore.max_records == 10000
    assert len(async_memory_peerstore.peer_data_map) == 0
    assert len(async_memory_peerstore.peer_record_map) == 0
    assert async_memory_peerstore.local_peer_record is None


@pytest.mark.trio
async def test_add_and_get_addrs(async_memory_peerstore, peer_id, addr):
    """Test adding and retrieving addresses."""
    # Add address
    await async_memory_peerstore.add_addrs_async(peer_id, [addr], 3600)

    # Retrieve address
    addrs = await async_memory_peerstore.addrs_async(peer_id)
    assert len(addrs) == 1
    assert addrs[0] == addr


@pytest.mark.trio
async def test_add_multiple_addrs(async_memory_peerstore, peer_id, addr, addr2):
    """Test adding multiple addresses."""
    # Add multiple addresses
    await async_memory_peerstore.add_addrs_async(peer_id, [addr, addr2], 3600)

    # Retrieve addresses
    addrs = await async_memory_peerstore.addrs_async(peer_id)
    assert len(addrs) == 2
    assert addr in addrs
    assert addr2 in addrs


@pytest.mark.trio
async def test_add_and_get_protocols(async_memory_peerstore, peer_id):
    """Test adding and retrieving protocols."""
    protocols = ["/ipfs/ping/1.0.0", "/ipfs/id/1.0.0"]

    # Add protocols
    await async_memory_peerstore.add_protocols_async(peer_id, protocols)

    # Retrieve protocols
    retrieved_protocols = await async_memory_peerstore.get_protocols_async(peer_id)
    assert set(retrieved_protocols) == set(protocols)


@pytest.mark.trio
async def test_add_and_get_metadata(async_memory_peerstore, peer_id):
    """Test adding and retrieving metadata."""
    key = "agent"
    value = "py-libp2p/0.1.0"

    # Add metadata
    await async_memory_peerstore.put_async(peer_id, key, value)

    # Retrieve metadata
    retrieved_value = await async_memory_peerstore.get_async(peer_id, key)
    assert retrieved_value == value


@pytest.mark.trio
async def test_latency_recording(async_memory_peerstore, peer_id):
    """Test latency recording and retrieval."""
    # Record latency
    await async_memory_peerstore.record_latency_async(peer_id, 0.05)  # 50ms

    # Retrieve latency
    latency = await async_memory_peerstore.latency_EWMA_async(peer_id)
    assert latency > 0


@pytest.mark.trio
async def test_peer_info(async_memory_peerstore, peer_id, addr):
    """Test peer info retrieval."""
    # Add address
    await async_memory_peerstore.add_addrs_async(peer_id, [addr], 3600)

    # Get peer info
    peer_info = await async_memory_peerstore.peer_info_async(peer_id)
    assert peer_info.peer_id == peer_id
    assert len(peer_info.addrs) == 1
    assert peer_info.addrs[0] == addr


@pytest.mark.trio
async def test_peer_ids(async_memory_peerstore, peer_id, peer_id_2, addr):
    """Test peer ID listing."""
    # Add addresses for two peers
    await async_memory_peerstore.add_addrs_async(peer_id, [addr], 3600)
    await async_memory_peerstore.add_addrs_async(peer_id_2, [addr], 3600)

    # Get all peer IDs
    peer_ids = await async_memory_peerstore.peer_ids_async()
    assert len(peer_ids) == 2
    assert peer_id in peer_ids
    assert peer_id_2 in peer_ids


@pytest.mark.trio
async def test_valid_peer_ids(async_memory_peerstore, peer_id, peer_id_2, addr):
    """Test valid peer ID listing."""
    # Add addresses for two peers
    await async_memory_peerstore.add_addrs_async(peer_id, [addr], 3600)
    await async_memory_peerstore.add_addrs_async(peer_id_2, [addr], 3600)

    # Get valid peer IDs
    valid_peer_ids = await async_memory_peerstore.valid_peer_ids_async()
    assert len(valid_peer_ids) == 2
    assert peer_id in valid_peer_ids
    assert peer_id_2 in valid_peer_ids


@pytest.mark.trio
async def test_peers_with_addrs(async_memory_peerstore, peer_id, peer_id_2, addr):
    """Test peers with addresses listing."""
    # Add addresses for two peers
    await async_memory_peerstore.add_addrs_async(peer_id, [addr], 3600)
    await async_memory_peerstore.add_addrs_async(peer_id_2, [addr], 3600)

    # Get peers with addresses
    peers_with_addrs = await async_memory_peerstore.peers_with_addrs_async()
    assert len(peers_with_addrs) == 2
    assert peer_id in peers_with_addrs
    assert peer_id_2 in peers_with_addrs


@pytest.mark.trio
async def test_supports_protocols(async_memory_peerstore, peer_id):
    """Test protocol support checking."""
    protocols = ["/ipfs/ping/1.0.0", "/ipfs/id/1.0.0", "/ipfs/kad/1.0.0"]
    await async_memory_peerstore.add_protocols_async(peer_id, protocols)

    # Check supported protocols
    supported = await async_memory_peerstore.supports_protocols_async(
        peer_id, ["/ipfs/ping/1.0.0", "/ipfs/unknown/1.0.0"]
    )
    assert "/ipfs/ping/1.0.0" in supported
    assert "/ipfs/unknown/1.0.0" not in supported


@pytest.mark.trio
async def test_first_supported_protocol(async_memory_peerstore, peer_id):
    """Test first supported protocol finding."""
    protocols = ["/ipfs/ping/1.0.0", "/ipfs/id/1.0.0"]
    await async_memory_peerstore.add_protocols_async(peer_id, protocols)

    # Find first supported protocol
    first_supported = await async_memory_peerstore.first_supported_protocol_async(
        peer_id, ["/ipfs/unknown/1.0.0", "/ipfs/ping/1.0.0", "/ipfs/id/1.0.0"]
    )
    assert first_supported == "/ipfs/ping/1.0.0"


# ============================================================================
# Data Management Tests
# ============================================================================


@pytest.mark.trio
async def test_clear_peerdata(async_memory_peerstore, peer_id, addr):
    """Test clearing peer data."""
    # Add some data
    await async_memory_peerstore.add_addrs_async(peer_id, [addr], 3600)
    await async_memory_peerstore.add_protocols_async(peer_id, ["/ipfs/ping/1.0.0"])
    await async_memory_peerstore.put_async(peer_id, "test", "value")

    # Clear peer data
    await async_memory_peerstore.clear_peerdata_async(peer_id)

    # Verify data is cleared - should return empty list, not raise error
    addrs = await async_memory_peerstore.addrs_async(peer_id)
    assert len(addrs) == 0


@pytest.mark.trio
async def test_clear_protocol_data(async_memory_peerstore, peer_id):
    """Test clearing protocol data."""
    protocols = ["/ipfs/ping/1.0.0", "/ipfs/id/1.0.0"]
    await async_memory_peerstore.add_protocols_async(peer_id, protocols)

    # Clear protocol data
    await async_memory_peerstore.clear_protocol_data_async(peer_id)

    # Verify protocols are cleared
    retrieved_protocols = await async_memory_peerstore.get_protocols_async(peer_id)
    assert len(retrieved_protocols) == 0


@pytest.mark.trio
async def test_clear_metadata(async_memory_peerstore, peer_id):
    """Test clearing metadata."""
    await async_memory_peerstore.put_async(peer_id, "test", "value")
    await async_memory_peerstore.put_async(peer_id, "test2", "value2")

    # Clear metadata
    await async_memory_peerstore.clear_metadata_async(peer_id)

    # Verify metadata is cleared
    with pytest.raises(PeerStoreError):
        await async_memory_peerstore.get_async(peer_id, "test")


@pytest.mark.trio
async def test_clear_keydata(async_memory_peerstore, peer_id):
    """Test clearing key data."""
    # This test would require actual key objects, so we'll just test the method exists
    await async_memory_peerstore.clear_keydata_async(peer_id)


@pytest.mark.trio
async def test_clear_metrics(async_memory_peerstore, peer_id):
    """Test clearing metrics."""
    await async_memory_peerstore.record_latency_async(peer_id, 0.05)

    # Clear metrics
    await async_memory_peerstore.clear_metrics_async(peer_id)

    # Verify metrics are cleared
    latency = await async_memory_peerstore.latency_EWMA_async(peer_id)
    assert latency == 0


# ============================================================================
# Stream Tests
# ============================================================================


@pytest.mark.trio
async def test_addr_stream(async_memory_peerstore, peer_id, addr):
    """Test address stream functionality."""
    # Start address stream
    stream = async_memory_peerstore.addr_stream_async(peer_id)

    # Add address in another task
    async def add_addr():
        await trio.sleep(0.1)
        await async_memory_peerstore.add_addrs_async(peer_id, [addr], 3600)

    # Run both tasks
    async with trio.open_nursery() as nursery:
        nursery.start_soon(add_addr)
        async for received_addr in stream:
            assert received_addr == addr
            break


# ============================================================================
# Lifecycle Tests
# ============================================================================


@pytest.mark.trio
async def test_close(async_memory_peerstore):
    """Test closing the async peerstore."""
    # This should not raise an exception
    await async_memory_peerstore.close_async()


# ============================================================================
# Error Handling Tests
# ============================================================================


@pytest.mark.trio
async def test_nonexistent_peer(async_memory_peerstore, peer_id):
    """Test operations on nonexistent peer."""
    # Should return empty list, not raise error
    addrs = await async_memory_peerstore.addrs_async(peer_id)
    assert len(addrs) == 0


@pytest.mark.trio
async def test_nonexistent_metadata(async_memory_peerstore, peer_id):
    """Test getting nonexistent metadata."""
    with pytest.raises(PeerStoreError):
        await async_memory_peerstore.get_async(peer_id, "nonexistent")


@pytest.mark.trio
async def test_empty_peer_ids(async_memory_peerstore):
    """Test getting peer IDs from empty peerstore."""
    peer_ids = await async_memory_peerstore.peer_ids_async()
    assert len(peer_ids) == 0


@pytest.mark.trio
async def test_empty_valid_peer_ids(async_memory_peerstore):
    """Test getting valid peer IDs from empty peerstore."""
    valid_peer_ids = await async_memory_peerstore.valid_peer_ids_async()
    assert len(valid_peer_ids) == 0


@pytest.mark.trio
async def test_empty_peers_with_addrs(async_memory_peerstore):
    """Test getting peers with addresses from empty peerstore."""
    peers_with_addrs = await async_memory_peerstore.peers_with_addrs_async()
    assert len(peers_with_addrs) == 0


# ============================================================================
# SQLite Persistence Test
# ============================================================================


@pytest.mark.trio
async def test_sqlite_persistence(peer_id, addr):
    """Test SQLite persistence with async peerstore."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "test.db"

        # Create first peerstore
        peerstore1 = create_async_sqlite_peerstore(str(db_path))
        await peerstore1.add_addrs_async(peer_id, [addr], 3600)
        await peerstore1.add_protocols_async(peer_id, ["/ipfs/ping/1.0.0"])
        await peerstore1.put_async(peer_id, "test", "value")

        await peerstore1.close_async()

        # Create second peerstore
        peerstore2 = create_async_sqlite_peerstore(str(db_path))

        # Verify data was persisted
        addrs = await peerstore2.addrs_async(peer_id)
        assert len(addrs) == 1
        assert addrs[0] == addr

        protocols = await peerstore2.get_protocols_async(peer_id)
        assert "/ipfs/ping/1.0.0" in protocols

        value = await peerstore2.get_async(peer_id, "test")
        assert value == "value"

        await peerstore2.close_async()


@pytest.mark.trio
async def test_memory_not_persistent(peer_id, addr):
    """Test that async memory peerstore is not persistent."""
    # Create memory peerstore
    peerstore1 = create_async_memory_peerstore()
    await peerstore1.add_addrs_async(peer_id, [addr], 3600)
    await peerstore1.close_async()

    # Create new memory peerstore
    peerstore2 = create_async_memory_peerstore()

    # Verify data is not persisted - should return empty list
    addrs = await peerstore2.addrs_async(peer_id)
    assert len(addrs) == 0

    await peerstore2.close_async()
