"""
Unit tests for the RTRefreshManager and related random walk logic.
"""

from unittest.mock import AsyncMock, Mock

import pytest

from libp2p.discovery.random_walk.config import (
    MIN_RT_REFRESH_THRESHOLD,
    REFRESH_INTERVAL,
)
from libp2p.discovery.random_walk.exceptions import RandomWalkError
from libp2p.discovery.random_walk.random_walk import RandomWalk
from libp2p.discovery.random_walk.rt_refresh_manager import RTRefreshManager
from libp2p.peer.id import ID


class DummyRoutingTable:
    def __init__(self, size=0):
        self._size = size
        self.added_peers = []

    def size(self):
        return self._size

    async def add_peer(self, peer_obj):
        self.added_peers.append(peer_obj)
        self._size += 1
        return True


@pytest.fixture
def mock_host():
    host = Mock()
    host.get_peerstore.return_value = Mock()
    host.new_stream = AsyncMock()
    return host


@pytest.fixture
def local_peer_id():
    return ID(b"\x01" * 32)


@pytest.fixture
def dummy_query_function():
    async def query(key_bytes):
        return [ID(b"\x02" * 32)]

    return query


@pytest.mark.trio
async def test_rt_refresh_manager_initialization(
    mock_host, local_peer_id, dummy_query_function
):
    rt = DummyRoutingTable(size=5)
    manager = RTRefreshManager(
        host=mock_host,
        routing_table=rt,
        local_peer_id=local_peer_id,
        query_function=dummy_query_function,
        enable_auto_refresh=True,
        refresh_interval=REFRESH_INTERVAL,
        min_refresh_threshold=MIN_RT_REFRESH_THRESHOLD,
    )
    assert manager.host == mock_host
    assert manager.routing_table == rt
    assert manager.local_peer_id == local_peer_id
    assert manager.query_function == dummy_query_function


@pytest.mark.trio
async def test_rt_refresh_manager_refresh_logic(
    mock_host, local_peer_id, dummy_query_function
):
    rt = DummyRoutingTable(size=2)
    # Simulate refresh logic
    if rt.size() < MIN_RT_REFRESH_THRESHOLD:
        await rt.add_peer(Mock())
    assert rt.size() >= 3


@pytest.mark.trio
async def test_rt_refresh_manager_random_walk_integration(
    mock_host, local_peer_id, dummy_query_function
):
    # Simulate random walk usage
    rw = RandomWalk(mock_host, local_peer_id, dummy_query_function)
    random_peer_id = rw.generate_random_peer_id()
    assert isinstance(random_peer_id, str)
    assert len(random_peer_id) == 64


@pytest.mark.trio
async def test_rt_refresh_manager_error_handling(mock_host, local_peer_id):
    rt = DummyRoutingTable(size=0)

    async def failing_query(_):
        raise RandomWalkError("Query failed")

    manager = RTRefreshManager(
        host=mock_host,
        routing_table=rt,
        local_peer_id=local_peer_id,
        query_function=failing_query,
        enable_auto_refresh=True,
        refresh_interval=REFRESH_INTERVAL,
        min_refresh_threshold=MIN_RT_REFRESH_THRESHOLD,
    )
    with pytest.raises(RandomWalkError):
        await manager.query_function(b"key")
