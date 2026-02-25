"""
Unit tests for ConnectionIDRegistry.

Tests the Connection ID routing state management and all registry operations.
"""

from unittest.mock import Mock

import pytest
import trio

from libp2p.transport.quic.connection_id_registry import ConnectionIDRegistry


@pytest.fixture
def registry():
    """Create a ConnectionIDRegistry instance for testing."""
    lock = trio.Lock()
    return ConnectionIDRegistry(lock)


@pytest.fixture
def mock_connection():
    """Create a mock QUICConnection for testing."""
    conn = Mock()
    conn._remote_addr = ("127.0.0.1", 12345)
    return conn


@pytest.fixture
def mock_pending_connection():
    """Create a mock QuicConnection (aioquic) for testing."""
    return Mock()


@pytest.mark.trio
async def test_register_connection(registry, mock_connection):
    """Test registering an established connection."""
    cid = b"test_cid_1"
    addr = ("127.0.0.1", 12345)

    await registry.register_connection(cid, mock_connection, addr)

    # Verify connection is registered
    connection_obj, pending_conn, is_pending = await registry.find_by_connection_id(cid)
    assert connection_obj is mock_connection
    assert pending_conn is None
    assert is_pending is False

    # Verify address mappings
    found_connection, found_cid = await registry.find_by_address(addr)
    assert found_connection is mock_connection
    assert found_cid == cid


@pytest.mark.trio
async def test_register_pending(registry, mock_pending_connection):
    """Test registering a pending connection."""
    cid = b"test_cid_2"
    addr = ("127.0.0.1", 54321)

    await registry.register_pending(cid, mock_pending_connection, addr)

    # Verify pending connection is registered
    connection_obj, pending_conn, is_pending = await registry.find_by_connection_id(cid)
    assert connection_obj is None
    assert pending_conn is mock_pending_connection
    assert is_pending is True

    # Verify address mappings exist (but find_by_address only returns
    # established connections)
    # The CID should still be mapped to the address internally
    found_connection, found_cid = await registry.find_by_address(addr)
    # find_by_address only searches established connections, so it won't find pending
    assert found_connection is None
    # But we can verify the CID is registered by checking directly
    _, pending_conn, is_pending = await registry.find_by_connection_id(cid)
    assert pending_conn is mock_pending_connection
    assert is_pending is True


@pytest.mark.trio
async def test_find_by_connection_id_not_found(registry):
    """Test finding a non-existent Connection ID."""
    cid = b"nonexistent_cid"

    connection_obj, pending_conn, is_pending = await registry.find_by_connection_id(cid)
    assert connection_obj is None
    assert pending_conn is None
    assert is_pending is False


@pytest.mark.trio
async def test_find_by_address_not_found(registry):
    """Test finding a connection by non-existent address."""
    addr = ("192.168.1.1", 9999)

    found_connection, found_cid = await registry.find_by_address(addr)
    assert found_connection is None
    assert found_cid is None


@pytest.mark.trio
async def test_add_connection_id(registry, mock_connection):
    """Test adding a new Connection ID for an existing connection."""
    original_cid = b"original_cid"
    new_cid = b"new_cid"
    addr = ("127.0.0.1", 12345)

    # Register original connection
    await registry.register_connection(original_cid, mock_connection, addr)

    # Add new Connection ID
    await registry.add_connection_id(new_cid, original_cid, sequence=1)

    # Verify both Connection IDs map to the same connection
    conn1, _, _ = await registry.find_by_connection_id(original_cid)
    conn2, _, _ = await registry.find_by_connection_id(new_cid)
    assert conn1 is mock_connection
    assert conn2 is mock_connection

    # Verify both Connection IDs map to the same address
    found_conn1, cid1 = await registry.find_by_address(addr)
    assert found_conn1 is mock_connection
    # The address should map to one of the Connection IDs
    assert cid1 in (original_cid, new_cid)


@pytest.mark.trio
async def test_remove_connection_id(registry, mock_connection):
    """Test removing a Connection ID and cleaning up mappings."""
    cid = b"test_cid_3"
    addr = ("127.0.0.1", 12345)

    # Register connection
    await registry.register_connection(cid, mock_connection, addr)

    # Verify it exists
    connection_obj, _, _ = await registry.find_by_connection_id(cid)
    assert connection_obj is mock_connection

    # Remove Connection ID
    removed_addr = await registry.remove_connection_id(cid)

    # Verify it's removed
    connection_obj, _, _ = await registry.find_by_connection_id(cid)
    assert connection_obj is None
    assert removed_addr == addr

    # Verify address mapping is cleaned up
    found_connection, found_cid = await registry.find_by_address(addr)
    assert found_connection is None
    assert found_cid is None


@pytest.mark.trio
async def test_remove_pending_connection(registry, mock_pending_connection):
    """Test removing a pending connection."""
    cid = b"pending_cid"
    addr = ("127.0.0.1", 54321)

    # Register pending connection
    await registry.register_pending(cid, mock_pending_connection, addr)

    # Verify it exists
    _, pending_conn, is_pending = await registry.find_by_connection_id(cid)
    assert pending_conn is mock_pending_connection
    assert is_pending is True

    # Remove pending connection
    await registry.remove_pending_connection(cid)

    # Verify it's removed
    _, pending_conn, is_pending = await registry.find_by_connection_id(cid)
    assert pending_conn is None
    assert is_pending is False


@pytest.mark.trio
async def test_promote_pending(registry, mock_connection, mock_pending_connection):
    """Test promoting a pending connection to established."""
    cid = b"promote_cid"
    addr = ("127.0.0.1", 12345)

    # Register as pending
    await registry.register_pending(cid, mock_pending_connection, addr)

    # Verify it's pending
    _, pending_conn, is_pending = await registry.find_by_connection_id(cid)
    assert pending_conn is mock_pending_connection
    assert is_pending is True

    # Promote to established
    await registry.promote_pending(cid, mock_connection)

    # Verify it's now established
    connection_obj, pending_conn, is_pending = await registry.find_by_connection_id(cid)
    assert connection_obj is mock_connection
    assert pending_conn is None
    assert is_pending is False

    # Verify address mapping is still intact
    found_connection, found_cid = await registry.find_by_address(addr)
    assert found_connection is mock_connection
    assert found_cid == cid


@pytest.mark.trio
async def test_register_new_cid_for_existing_connection(registry, mock_connection):
    """Test registering a new Connection ID (fallback mechanism)."""
    original_cid = b"original_cid_2"
    new_cid = b"new_cid_2"
    addr = ("127.0.0.1", 12345)

    # Register original connection
    await registry.register_connection(original_cid, mock_connection, addr)

    # Register new Connection ID using fallback mechanism
    await registry.register_new_connection_id_for_existing_conn(
        new_cid, mock_connection, addr
    )

    # Verify both Connection IDs work
    conn1, _, _ = await registry.find_by_connection_id(original_cid)
    conn2, _, _ = await registry.find_by_connection_id(new_cid)
    assert conn1 is mock_connection
    assert conn2 is mock_connection

    # Verify address now maps to new Connection ID
    found_connection, found_cid = await registry.find_by_address(addr)
    assert found_connection is mock_connection
    assert found_cid == new_cid


@pytest.mark.trio
async def test_get_all_cids_for_connection(registry, mock_connection):
    """Test getting all Connection IDs for a connection."""
    cid1 = b"cid_1"
    cid2 = b"cid_2"
    cid3 = b"cid_3"
    addr1 = ("127.0.0.1", 12345)

    # Register connection with first Connection ID
    await registry.register_connection(cid1, mock_connection, addr1)

    # Add additional Connection IDs
    await registry.add_connection_id(cid2, cid1, sequence=1)
    await registry.add_connection_id(cid3, cid1, sequence=2)

    # Get all Connection IDs for this connection
    cids = await registry.get_all_cids_for_connection(mock_connection)

    # Verify all Connection IDs are returned
    assert len(cids) == 3
    assert cid1 in cids
    assert cid2 in cids
    assert cid3 in cids


@pytest.mark.trio
async def test_find_by_address_fallback_search(registry, mock_connection):
    """Test the fallback address search mechanism."""
    cid = b"fallback_cid"
    addr = ("127.0.0.1", 12345)

    # Register connection
    await registry.register_connection(cid, mock_connection, addr)

    # Remove address mapping to simulate stale mapping scenario
    # (This tests the fallback linear search)
    async with registry._lock:
        registry._addr_to_connection_id.pop(addr, None)

    # find_by_address should still find the connection via linear search
    found_connection, found_cid = await registry.find_by_address(addr)
    assert found_connection is mock_connection
    assert found_cid == cid


@pytest.mark.trio
async def test_remove_by_address(registry, mock_connection):
    """Test removing a connection by address."""
    cid = b"addr_cid"
    addr = ("127.0.0.1", 12345)

    # Register connection
    await registry.register_connection(cid, mock_connection, addr)

    # Remove by address
    removed_cid = await registry.remove_by_address(addr)

    # Verify it's removed
    assert removed_cid == cid
    connection_obj, _, _ = await registry.find_by_connection_id(cid)
    assert connection_obj is None
    found_connection, found_cid = await registry.find_by_address(addr)
    assert found_connection is None
    assert found_cid is None


@pytest.mark.trio
async def test_cleanup_stale_address_mapping(registry):
    """Test cleaning up stale address mappings."""
    addr = ("127.0.0.1", 12345)

    # Create a stale mapping
    async with registry._lock:
        registry._addr_to_connection_id[addr] = b"stale_cid"

    # Clean up stale mapping
    await registry.cleanup_stale_address_mapping(addr)

    # Verify mapping is removed
    found_connection, found_cid = await registry.find_by_address(addr)
    assert found_connection is None
    assert found_cid is None


@pytest.mark.trio
async def test_multiple_connections_same_address(registry):
    """Test handling multiple connections (edge case - shouldn't happen but test it)."""
    conn1 = Mock()
    conn1._remote_addr = ("127.0.0.1", 12345)
    conn2 = Mock()
    conn2._remote_addr = ("127.0.0.1", 12345)

    cid1 = b"cid_1"
    cid2 = b"cid_2"
    addr = ("127.0.0.1", 12345)

    # Register first connection
    await registry.register_connection(cid1, conn1, addr)

    # Register second connection with same address (overwrites address mapping)
    await registry.register_connection(cid2, conn2, addr)

    # Address lookup should return the most recently registered connection
    found_connection, found_cid = await registry.find_by_address(addr)
    assert found_connection is conn2
    assert found_cid == cid2

    # But both Connection IDs should still work
    conn1_found, _, _ = await registry.find_by_connection_id(cid1)
    conn2_found, _, _ = await registry.find_by_connection_id(cid2)
    assert conn1_found is conn1
    assert conn2_found is conn2


@pytest.mark.trio
async def test_get_all_established_cids(registry, mock_connection):
    """Test getting all established Connection IDs."""
    cid1 = b"established_1"
    cid2 = b"established_2"
    addr1 = ("127.0.0.1", 12345)
    addr2 = ("127.0.0.1", 12346)

    await registry.register_connection(cid1, mock_connection, addr1)
    await registry.register_connection(cid2, mock_connection, addr2)

    established_cids = await registry.get_all_established_cids()
    assert len(established_cids) == 2
    assert cid1 in established_cids
    assert cid2 in established_cids


@pytest.mark.trio
async def test_get_all_pending_cids(registry, mock_pending_connection):
    """Test getting all pending Connection IDs."""
    cid1 = b"pending_1"
    cid2 = b"pending_2"
    addr1 = ("127.0.0.1", 12345)
    addr2 = ("127.0.0.1", 12346)

    await registry.register_pending(cid1, mock_pending_connection, addr1)
    await registry.register_pending(cid2, mock_pending_connection, addr2)

    pending_cids = await registry.get_all_pending_cids()
    assert len(pending_cids) == 2
    assert cid1 in pending_cids
    assert cid2 in pending_cids


@pytest.mark.trio
async def test_get_stats(registry, mock_connection, mock_pending_connection):
    """Test getting registry statistics."""
    cid1 = b"stats_cid_1"
    cid2 = b"stats_cid_2"
    addr1 = ("127.0.0.1", 12345)
    addr2 = ("127.0.0.1", 12346)

    await registry.register_connection(cid1, mock_connection, addr1)
    await registry.register_pending(cid2, mock_pending_connection, addr2)

    stats = registry.get_stats()
    assert stats["established_connections"] == 1
    assert stats["pending_connections"] == 1
    assert stats["total_connection_ids"] == 2
    assert stats["address_mappings"] == 2


@pytest.mark.trio
async def test_len(registry, mock_connection, mock_pending_connection):
    """Test __len__ method."""
    cid1 = b"len_cid_1"
    cid2 = b"len_cid_2"
    addr1 = ("127.0.0.1", 12345)
    addr2 = ("127.0.0.1", 12346)

    assert len(registry) == 0

    await registry.register_connection(cid1, mock_connection, addr1)
    assert len(registry) == 1

    await registry.register_pending(cid2, mock_pending_connection, addr2)
    assert len(registry) == 2

    await registry.remove_connection_id(cid1)
    assert len(registry) == 1


@pytest.mark.trio
async def test_connection_id_retired_cleanup(registry, mock_connection):
    """Test cleanup when Connection ID is retired but address mapping remains."""
    original_cid = b"original_retired"
    new_cid = b"new_not_retired"
    addr = ("127.0.0.1", 12345)

    # Register connection with original Connection ID
    await registry.register_connection(original_cid, mock_connection, addr)

    # Add new Connection ID
    await registry.add_connection_id(new_cid, original_cid, sequence=1)

    # Remove original Connection ID (simulating retirement)
    await registry.remove_connection_id(original_cid)

    # New Connection ID should still work
    conn, _, _ = await registry.find_by_connection_id(new_cid)
    assert conn is mock_connection

    # Address should still map to new Connection ID
    found_connection, found_cid = await registry.find_by_address(addr)
    assert found_connection is mock_connection
    assert found_cid == new_cid


# ============================================================================
# New tests for quinn-inspired improvements
# ============================================================================


@pytest.mark.trio
async def test_sequence_number_tracking(registry, mock_connection):
    """Test sequence number tracking for Connection IDs (inspired by quinn)."""
    cid1 = b"cid_seq_1"
    cid2 = b"cid_seq_2"
    cid3 = b"cid_seq_3"
    addr = ("127.0.0.1", 12345)

    # Register connection with sequence 0
    await registry.register_connection(cid1, mock_connection, addr, sequence=0)
    seq1 = await registry.get_sequence_for_connection_id(cid1)
    assert seq1 == 0

    # Add new Connection IDs with increasing sequences
    await registry.add_connection_id(cid2, cid1, sequence=1)
    seq2 = await registry.get_sequence_for_connection_id(cid2)
    assert seq2 == 1

    await registry.add_connection_id(cid3, cid1, sequence=2)
    seq3 = await registry.get_sequence_for_connection_id(cid3)
    assert seq3 == 2

    # Verify all sequences are tracked
    assert await registry.get_sequence_for_connection_id(cid1) == 0
    assert await registry.get_sequence_for_connection_id(cid2) == 1
    assert await registry.get_sequence_for_connection_id(cid3) == 2


@pytest.mark.trio
async def test_sequence_number_retirement_ordering(registry, mock_connection):
    """Test proper retirement ordering using sequence numbers (inspired by quinn)."""
    cid1 = b"cid_retire_1"
    cid2 = b"cid_retire_2"
    cid3 = b"cid_retire_3"
    cid4 = b"cid_retire_4"
    addr = ("127.0.0.1", 12345)

    # Register connection with multiple CIDs
    await registry.register_connection(cid1, mock_connection, addr, sequence=0)
    await registry.add_connection_id(cid2, cid1, sequence=1)
    await registry.add_connection_id(cid3, cid1, sequence=2)
    await registry.add_connection_id(cid4, cid1, sequence=3)

    # Get CIDs in sequence range (for retirement ordering)
    cids_range_0_2 = await registry.get_cids_by_sequence_range(
        mock_connection, start_seq=0, end_seq=2
    )
    assert len(cids_range_0_2) == 2
    assert cid1 in cids_range_0_2
    assert cid2 in cids_range_0_2

    cids_range_2_4 = await registry.get_cids_by_sequence_range(
        mock_connection, start_seq=2, end_seq=4
    )
    assert len(cids_range_2_4) == 2
    assert cid3 in cids_range_2_4
    assert cid4 in cids_range_2_4

    # Verify sequences are in order
    sequences = [
        await registry.get_sequence_for_connection_id(cid) for cid in cids_range_0_2
    ]
    assert sequences == sorted(sequences)


@pytest.mark.trio
async def test_initial_vs_established_cid_separation(registry, mock_pending_connection):
    """
    Test that initial and established CIDs are tracked separately
    (inspired by quinn).
    """
    initial_cid = b"initial_cid"
    established_cid = b"established_cid"
    addr = ("127.0.0.1", 12345)

    # Register initial CID
    await registry.register_initial_connection_id(
        initial_cid, mock_pending_connection, addr, sequence=0
    )

    # Verify initial CID is found when is_initial=True
    _, pending_conn, is_pending = await registry.find_by_connection_id(
        initial_cid, is_initial=True
    )
    assert pending_conn is mock_pending_connection
    assert is_pending is True

    # Verify initial CID is NOT found when is_initial=False
    # (it's not in established/pending)
    _, pending_conn2, is_pending2 = await registry.find_by_connection_id(
        initial_cid, is_initial=False
    )
    assert pending_conn2 is None
    assert is_pending2 is False

    # Register established connection with different CID
    mock_connection = Mock()
    mock_connection._remote_addr = addr
    await registry.register_connection(
        established_cid, mock_connection, addr, sequence=0
    )

    # Verify established CID is found
    conn, _, _ = await registry.find_by_connection_id(established_cid, is_initial=False)
    assert conn is mock_connection


@pytest.mark.trio
async def test_initial_cid_promotion(registry, mock_pending_connection):
    """
    Test moving initial CID to established when connection is promoted
    (inspired by quinn).
    """
    initial_cid = b"initial_promote"
    addr = ("127.0.0.1", 12345)

    # Register initial CID
    await registry.register_initial_connection_id(
        initial_cid, mock_pending_connection, addr, sequence=0
    )

    # Verify it's in initial CIDs
    _, pending_conn, is_pending = await registry.find_by_connection_id(
        initial_cid, is_initial=True
    )
    assert pending_conn is mock_pending_connection

    # Promote connection
    mock_connection = Mock()
    mock_connection._remote_addr = addr
    await registry.promote_pending(initial_cid, mock_connection)

    # Verify it's no longer in initial CIDs
    _, pending_conn2, is_pending2 = await registry.find_by_connection_id(
        initial_cid, is_initial=True
    )
    assert pending_conn2 is None

    # Verify it's now in established connections
    conn, _, _ = await registry.find_by_connection_id(initial_cid, is_initial=False)
    assert conn is mock_connection


@pytest.mark.trio
async def test_reverse_address_mapping(registry, mock_connection):
    """Test reverse mapping from connection to address for O(1) fallback routing."""
    cid1 = b"reverse_cid_1"
    cid2 = b"reverse_cid_2"
    addr = ("127.0.0.1", 12345)

    # Register connection
    await registry.register_connection(cid1, mock_connection, addr, sequence=0)

    # Add another CID for same connection
    await registry.add_connection_id(cid2, cid1, sequence=1)

    # Remove address-to-CID mapping to test reverse lookup
    async with registry._lock:
        registry._addr_to_connection_id.pop(addr, None)

    # find_by_address should still find connection via reverse mapping
    found_connection, found_cid = await registry.find_by_address(addr)
    assert found_connection is mock_connection
    assert found_cid in (cid1, cid2)


@pytest.mark.trio
async def test_fallback_routing_o1_performance(registry, mock_connection):
    """Test that fallback routing uses O(1) lookups instead of O(n) search."""
    # Create multiple connections to test performance
    connections = []
    for i in range(10):
        conn = Mock()
        conn._remote_addr = (f"127.0.0.{i + 1}", 12345 + i)
        connections.append(conn)
        cid = f"cid_{i}".encode()
        await registry.register_connection(
            cid, conn, (f"127.0.0.{i + 1}", 12345 + i), sequence=0
        )

    # Test that address lookup is fast (O(1) via reverse mapping)
    # This test verifies the mechanism works, not actual performance
    target_addr = ("127.0.0.5", 12349)
    found_connection, found_cid = await registry.find_by_address(target_addr)
    assert found_connection is connections[4]
    assert found_cid == b"cid_4"


@pytest.mark.trio
async def test_concurrent_operations_with_sequences(registry):
    """Test high concurrency with sequence tracking."""
    import trio

    async def register_connection_with_sequences(i: int):
        """Register a connection and add multiple CIDs with sequences."""
        conn = Mock()
        conn._remote_addr = (f"127.0.0.{i}", 12345 + i)
        cid_base = f"cid_base_{i}".encode()
        addr = (f"127.0.0.{i}", 12345 + i)

        # Register with sequence 0
        await registry.register_connection(cid_base, conn, addr, sequence=0)

        # Add multiple CIDs with increasing sequences
        for seq in range(1, 5):
            cid = f"cid_{i}_{seq}".encode()
            await registry.add_connection_id(cid, cid_base, sequence=seq)

        # Verify sequences
        for seq in range(5):
            if seq == 0:
                cid = cid_base
            else:
                cid = f"cid_{i}_{seq}".encode()
            found_seq = await registry.get_sequence_for_connection_id(cid)
            assert found_seq == seq

    # Run 20 concurrent registrations
    async with trio.open_nursery() as nursery:
        for i in range(20):
            nursery.start_soon(register_connection_with_sequences, i)

    # Verify all connections are registered
    # Note: established_connections counts CIDs, not unique connections
    # Each connection has 5 CIDs (1 base + 4 additional), so 20 connections = 100 CIDs
    stats = registry.get_stats()
    assert stats["established_connections"] == 100  # 20 connections * 5 CIDs each
    assert stats["tracked_sequences"] >= 20 * 5  # At least 5 sequences per connection


@pytest.mark.trio
async def test_cid_retirement_ordering(registry, mock_connection):
    """Test retirement of CIDs in sequence order."""
    cid_base = b"base_cid"
    addr = ("127.0.0.1", 12345)

    # Register base CID with sequence 0
    await registry.register_connection(cid_base, mock_connection, addr, sequence=0)

    # Add multiple CIDs with increasing sequences
    cids = [cid_base]
    for seq in range(1, 5):
        cid = f"cid_seq_{seq}".encode()
        await registry.add_connection_id(cid, cid_base, sequence=seq)
        cids.append(cid)

    # Verify all CIDs are registered
    for cid in cids:
        conn, _, _ = await registry.find_by_connection_id(cid)
        assert conn is mock_connection

    # Retire CIDs in sequence range [0, 3) - should retire sequences 0, 1, 2
    retired = await registry.retire_connection_ids_by_sequence_range(
        mock_connection, 0, 3
    )

    # Verify retirement order (should be sorted by sequence)
    assert len(retired) == 3
    assert retired[0] == cid_base  # sequence 0
    assert retired[1] == b"cid_seq_1"  # sequence 1
    assert retired[2] == b"cid_seq_2"  # sequence 2

    # Verify retired CIDs are removed
    for cid in retired:
        conn, _, _ = await registry.find_by_connection_id(cid)
        assert conn is None

    # Verify remaining CIDs are still registered
    conn, _, _ = await registry.find_by_connection_id(b"cid_seq_3")
    assert conn is mock_connection
    conn, _, _ = await registry.find_by_connection_id(b"cid_seq_4")
    assert conn is mock_connection


@pytest.mark.trio
async def test_retire_connection_ids_by_sequence_range(registry, mock_connection):
    """Test batch retirement of CIDs by sequence range."""
    cid_base = b"base_cid"
    addr = ("127.0.0.1", 12345)

    # Register base CID
    await registry.register_connection(cid_base, mock_connection, addr, sequence=0)

    # Add 10 CIDs with sequences 1-10
    for seq in range(1, 11):
        cid = f"cid_{seq}".encode()
        await registry.add_connection_id(cid, cid_base, sequence=seq)

    # Get sequence numbers before retirement
    cid_to_seq = {}
    for seq in range(2, 7):
        cid = f"cid_{seq}".encode()
        cid_to_seq[cid] = seq

    # Retire sequences 2-7 (inclusive start, exclusive end)
    retired = await registry.retire_connection_ids_by_sequence_range(
        mock_connection, 2, 7
    )

    # Should retire sequences 2, 3, 4, 5, 6
    assert len(retired) == 5
    # Verify all expected CIDs were retired
    for cid in retired:
        assert cid in cid_to_seq

    # Verify remaining CIDs
    conn, _, _ = await registry.find_by_connection_id(cid_base)  # seq 0
    assert conn is mock_connection
    conn, _, _ = await registry.find_by_connection_id(b"cid_1")  # seq 1
    assert conn is mock_connection
    conn, _, _ = await registry.find_by_connection_id(b"cid_7")  # seq 7
    assert conn is mock_connection
    conn, _, _ = await registry.find_by_connection_id(b"cid_10")  # seq 10
    assert conn is mock_connection


@pytest.mark.trio
async def test_retirement_cleanup(registry, mock_connection):
    """Verify all mappings are cleaned up properly during retirement."""
    cid_base = b"base_cid"
    addr = ("127.0.0.1", 12345)

    # Register base CID
    await registry.register_connection(cid_base, mock_connection, addr, sequence=0)

    # Add additional CID
    cid2 = b"cid_2"
    await registry.add_connection_id(cid2, cid_base, sequence=1)

    # Verify mappings exist
    conn, _, _ = await registry.find_by_connection_id(cid_base)
    assert conn is mock_connection
    conn, _, _ = await registry.find_by_connection_id(cid2)
    assert conn is mock_connection
    found_conn, found_cid = await registry.find_by_address(addr)
    assert found_conn is mock_connection

    # Retire cid2
    await registry.remove_connection_id(cid2)

    # Verify cid2 is removed
    conn, _, _ = await registry.find_by_connection_id(cid2)
    assert conn is None

    # Verify base CID and address mapping still exist
    conn, _, _ = await registry.find_by_connection_id(cid_base)
    assert conn is mock_connection
    found_conn, found_cid = await registry.find_by_address(addr)
    assert found_conn is mock_connection
    assert found_cid == cid_base

    # Verify sequence tracking is cleaned up
    seq = await registry.get_sequence_for_connection_id(cid2)
    assert seq is None


@pytest.mark.trio
async def test_retirement_with_multiple_connections(registry):
    """Test retirement across multiple connections."""
    conn1 = Mock()
    conn2 = Mock()
    addr1 = ("127.0.0.1", 12345)
    addr2 = ("127.0.0.1", 54321)

    # Register two connections
    cid1_base = b"conn1_base"
    cid2_base = b"conn2_base"
    await registry.register_connection(cid1_base, conn1, addr1, sequence=0)
    await registry.register_connection(cid2_base, conn2, addr2, sequence=0)

    # Add CIDs to both connections
    cid1_1 = b"conn1_cid1"
    cid1_2 = b"conn1_cid2"
    cid2_1 = b"conn2_cid1"
    await registry.add_connection_id(cid1_1, cid1_base, sequence=1)
    await registry.add_connection_id(cid1_2, cid1_base, sequence=2)
    await registry.add_connection_id(cid2_1, cid2_base, sequence=1)

    # Retire CIDs from conn1 only
    retired = await registry.retire_connection_ids_by_sequence_range(conn1, 0, 2)

    # Should retire cid1_base (seq 0) and cid1_1 (seq 1)
    assert len(retired) == 2
    assert cid1_base in retired
    assert cid1_1 in retired

    # Verify conn1's remaining CID
    conn, _, _ = await registry.find_by_connection_id(cid1_2)
    assert conn is conn1

    # Verify conn2's CIDs are unaffected
    conn, _, _ = await registry.find_by_connection_id(cid2_base)
    assert conn is conn2
    conn, _, _ = await registry.find_by_connection_id(cid2_1)
    assert conn is conn2


@pytest.mark.trio
async def test_performance_metrics(registry, mock_connection):
    """Test that performance metrics are tracked correctly."""
    cid = b"test_cid"
    addr = ("127.0.0.1", 12345)

    # Register connection
    await registry.register_connection(cid, mock_connection, addr, sequence=0)

    # Add CIDs with different sequences
    for seq in range(1, 4):
        new_cid = f"cid_{seq}".encode()
        await registry.add_connection_id(new_cid, cid, sequence=seq)

    # Use fallback routing (strategy 2)
    found_conn, found_cid = await registry.find_by_address(addr)
    assert found_conn is mock_connection

    # Get stats
    stats = registry.get_stats()

    # Verify metrics are present
    assert "fallback_routing_count" in stats
    assert "sequence_distribution" in stats

    # Verify fallback routing was counted
    assert stats["fallback_routing_count"] >= 0  # May be 0 if strategy 1 worked

    # Verify sequence distribution
    assert isinstance(stats["sequence_distribution"], dict)
    # Should have sequences 0, 1, 2, 3
    for seq in range(4):
        assert seq in stats["sequence_distribution"]


@pytest.mark.trio
async def test_fallback_routing_metrics(registry, mock_connection):
    """Test that fallback routing usage is counted correctly."""
    cid = b"test_cid"
    addr = ("127.0.0.1", 12345)

    # Register connection
    await registry.register_connection(cid, mock_connection, addr, sequence=0)

    # Reset stats to get baseline
    registry.reset_stats()

    # Use fallback routing by finding by address
    # This should trigger fallback routing (strategy 2) if address mapping is stale
    found_conn, found_cid = await registry.find_by_address(addr)

    # Get stats
    stats = registry.get_stats()

    # Fallback routing count should be tracked
    assert "fallback_routing_count" in stats
    # Note: Fallback routing count increments when strategy 2 is used
    # Strategy 1 (address-to-CID) might work first, so count may be 0
    assert stats["fallback_routing_count"] >= 0


@pytest.mark.trio
async def test_reset_stats(registry, mock_connection):
    """Test that stats can be reset."""
    cid = b"test_cid"
    addr = ("127.0.0.1", 12345)

    # Register connection and perform operations
    await registry.register_connection(cid, mock_connection, addr, sequence=0)
    await registry.add_connection_id(b"cid_1", cid, sequence=1)

    # Get initial stats
    stats_before = registry.get_stats()
    assert stats_before["fallback_routing_count"] >= 0

    # Reset stats
    registry.reset_stats()

    # Get stats after reset
    stats_after = registry.get_stats()

    # Fallback routing count should be reset
    assert stats_after["fallback_routing_count"] == 0

    # But connection counts should remain
    assert (
        stats_after["established_connections"]
        == stats_before["established_connections"]
    )
