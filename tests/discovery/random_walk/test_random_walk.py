"""
Unit tests for the RandomWalk module in libp2p.discovery.random_walk.
"""

from unittest.mock import AsyncMock, Mock

import pytest

from libp2p.discovery.random_walk.random_walk import RandomWalk
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo


@pytest.fixture
def mock_host():
    host = Mock()
    peerstore = Mock()
    peerstore.peers_with_addrs.return_value = []
    peerstore.addrs.return_value = [Mock()]
    host.get_peerstore.return_value = peerstore
    host.new_stream = AsyncMock()
    return host


@pytest.fixture
def dummy_query_function():
    async def query(key_bytes):
        return []

    return query


@pytest.fixture
def dummy_peer_id():
    return b"\x01" * 32


@pytest.mark.trio
async def test_random_walk_initialization(
    mock_host, dummy_peer_id, dummy_query_function
):
    rw = RandomWalk(mock_host, dummy_peer_id, dummy_query_function)
    assert rw.host == mock_host
    assert rw.local_peer_id == dummy_peer_id
    assert rw.query_function == dummy_query_function


def test_generate_random_peer_id(mock_host, dummy_peer_id, dummy_query_function):
    rw = RandomWalk(mock_host, dummy_peer_id, dummy_query_function)
    peer_id = rw.generate_random_peer_id()
    assert isinstance(peer_id, str)
    assert len(peer_id) == 64  # 32 bytes hex


@pytest.mark.trio
async def test_run_concurrent_random_walks(mock_host, dummy_peer_id):
    # Dummy query function returns different peer IDs for each walk
    call_count = {"count": 0}

    async def query(key_bytes):
        call_count["count"] += 1
        # Return a unique peer ID for each call
        return [ID(bytes([call_count["count"]] * 32))]

    rw = RandomWalk(mock_host, dummy_peer_id, query)
    peers = await rw.run_concurrent_random_walks(count=3)
    # Should get 3 unique peers
    assert len(peers) == 3
    peer_ids = [peer.peer_id for peer in peers]
    assert len(set(peer_ids)) == 3


@pytest.mark.trio
async def test_perform_random_walk_running(mock_host, dummy_peer_id):
    # Query function returns a single peer ID
    async def query(key_bytes):
        return [ID(b"\x02" * 32)]

    rw = RandomWalk(mock_host, dummy_peer_id, query)
    peers = await rw.perform_random_walk()
    assert isinstance(peers, list)
    if peers:
        assert isinstance(peers[0], PeerInfo)


@pytest.mark.trio
async def test_perform_random_walk_no_peers_found(mock_host, dummy_peer_id):
    """Test perform_random_walk when no peers are discovered."""

    # Query function returns empty list (no peers found)
    async def query(key_bytes):
        return []

    rw = RandomWalk(mock_host, dummy_peer_id, query)
    peers = await rw.perform_random_walk()

    # Should return empty list when no peers are found
    assert isinstance(peers, list)
    assert len(peers) == 0
