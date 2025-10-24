"""
Unit tests for the RTRefreshManager and related random walk logic.
"""

import time
from unittest.mock import AsyncMock, Mock, patch

import pytest
import trio

from libp2p.discovery.random_walk.config import (
    MIN_RT_REFRESH_THRESHOLD,
    RANDOM_WALK_CONCURRENCY,
    REFRESH_INTERVAL,
)
from libp2p.discovery.random_walk.exceptions import (
    RandomWalkError,
)
from libp2p.discovery.random_walk.random_walk import RandomWalk
from libp2p.discovery.random_walk.rt_refresh_manager import RTRefreshManager
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo


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


@pytest.mark.trio
async def test_rt_refresh_manager_start_method(
    mock_host, local_peer_id, dummy_query_function
):
    """Test the start method functionality."""
    rt = DummyRoutingTable(size=2)
    manager = RTRefreshManager(
        host=mock_host,
        routing_table=rt,
        local_peer_id=local_peer_id,
        query_function=dummy_query_function,
        enable_auto_refresh=False,  # Disable auto-refresh to control the test
        refresh_interval=0.1,
        min_refresh_threshold=MIN_RT_REFRESH_THRESHOLD,
    )

    # Mock the random walk to return some peers
    mock_peer_info = Mock(spec=PeerInfo)
    with patch.object(
        manager.random_walk,
        "run_concurrent_random_walks",
        return_value=[mock_peer_info],
    ):
        # Test starting the manager
        assert not manager._running

        # Start the manager in a nursery that we can control
        async with trio.open_nursery() as nursery:
            nursery.start_soon(manager.start)
            await trio.sleep(0.01)  # Let it start

            # Verify it's running
            assert manager._running

            # Stop the manager
            await manager.stop()
            assert not manager._running


@pytest.mark.trio
async def test_rt_refresh_manager_main_loop_with_auto_refresh(
    mock_host, local_peer_id, dummy_query_function
):
    """Test the _main_loop method with auto-refresh enabled."""
    rt = DummyRoutingTable(size=1)  # Small size to trigger refresh
    manager = RTRefreshManager(
        host=mock_host,
        routing_table=rt,
        local_peer_id=local_peer_id,
        query_function=dummy_query_function,
        enable_auto_refresh=True,
        refresh_interval=0.1,
        min_refresh_threshold=MIN_RT_REFRESH_THRESHOLD,
    )

    # Mock the random walk to return some peers
    mock_peer_info = Mock(spec=PeerInfo)
    with patch.object(
        manager.random_walk,
        "run_concurrent_random_walks",
        return_value=[mock_peer_info],
    ) as mock_random_walk:
        manager._running = True

        # Run the main loop for a short time
        async with trio.open_nursery() as nursery:
            nursery.start_soon(manager._main_loop)
            await trio.sleep(0.05)  # Let it run briefly
            manager._running = False  # Stop the loop

        # Verify that random walk was called (initial refresh)
        mock_random_walk.assert_called()


@pytest.mark.trio
async def test_rt_refresh_manager_main_loop_without_auto_refresh(
    mock_host, local_peer_id, dummy_query_function
):
    """Test the _main_loop method with auto-refresh disabled."""
    rt = DummyRoutingTable(size=1)
    manager = RTRefreshManager(
        host=mock_host,
        routing_table=rt,
        local_peer_id=local_peer_id,
        query_function=dummy_query_function,
        enable_auto_refresh=False,
        refresh_interval=0.1,
        min_refresh_threshold=MIN_RT_REFRESH_THRESHOLD,
    )

    with patch.object(
        manager.random_walk, "run_concurrent_random_walks"
    ) as mock_random_walk:
        manager._running = True

        # Run the main loop for a short time
        async with trio.open_nursery() as nursery:
            nursery.start_soon(manager._main_loop)
            await trio.sleep(0.05)
            manager._running = False

        # Verify that random walk was not called since auto-refresh is disabled
        mock_random_walk.assert_not_called()


@pytest.mark.trio
async def test_rt_refresh_manager_main_loop_initial_refresh_exception(
    mock_host, local_peer_id, dummy_query_function
):
    """Test that _main_loop propagates exceptions from initial refresh."""
    rt = DummyRoutingTable(size=1)
    manager = RTRefreshManager(
        host=mock_host,
        routing_table=rt,
        local_peer_id=local_peer_id,
        query_function=dummy_query_function,
        enable_auto_refresh=True,
        refresh_interval=0.1,
        min_refresh_threshold=MIN_RT_REFRESH_THRESHOLD,
    )

    # Mock _do_refresh to raise an exception on the initial call
    with patch.object(
        manager, "_do_refresh", side_effect=Exception("Initial refresh failed")
    ):
        manager._running = True

        # The initial refresh exception should propagate
        with pytest.raises(Exception, match="Initial refresh failed"):
            await manager._main_loop()


@pytest.mark.trio
async def test_do_refresh_force_refresh(mock_host, local_peer_id, dummy_query_function):
    """Test _do_refresh method with force=True."""
    rt = DummyRoutingTable(size=10)  # Large size, but force should override
    manager = RTRefreshManager(
        host=mock_host,
        routing_table=rt,
        local_peer_id=local_peer_id,
        query_function=dummy_query_function,
        enable_auto_refresh=True,
        refresh_interval=REFRESH_INTERVAL,
        min_refresh_threshold=MIN_RT_REFRESH_THRESHOLD,
    )

    # Mock the random walk to return some peers
    mock_peer_info1 = Mock(spec=PeerInfo)
    mock_peer_info2 = Mock(spec=PeerInfo)
    discovered_peers = [mock_peer_info1, mock_peer_info2]

    with patch.object(
        manager.random_walk,
        "run_concurrent_random_walks",
        return_value=discovered_peers,
    ) as mock_random_walk:
        # Force refresh should work regardless of RT size
        await manager._do_refresh(force=True)

        # Verify random walk was called
        mock_random_walk.assert_called_once_with(
            count=RANDOM_WALK_CONCURRENCY, current_routing_table_size=10
        )

        # Verify peers were added to routing table
        assert len(rt.added_peers) == 2
        assert manager._last_refresh_time > 0


@pytest.mark.trio
async def test_do_refresh_skip_due_to_interval(
    mock_host, local_peer_id, dummy_query_function
):
    """Test _do_refresh skips refresh when interval hasn't elapsed."""
    rt = DummyRoutingTable(size=1)  # Small size to trigger refresh normally
    manager = RTRefreshManager(
        host=mock_host,
        routing_table=rt,
        local_peer_id=local_peer_id,
        query_function=dummy_query_function,
        enable_auto_refresh=True,
        refresh_interval=100.0,  # Long interval
        min_refresh_threshold=MIN_RT_REFRESH_THRESHOLD,
    )

    # Set last refresh time to recent
    manager._last_refresh_time = time.time()

    with patch.object(
        manager.random_walk, "run_concurrent_random_walks"
    ) as mock_random_walk:
        with patch(
            "libp2p.discovery.random_walk.rt_refresh_manager.logger"
        ) as mock_logger:
            await manager._do_refresh(force=False)

            # Verify refresh was skipped
            mock_random_walk.assert_not_called()
            mock_logger.debug.assert_called_with(
                "Skipping refresh: interval not elapsed"
            )


@pytest.mark.trio
async def test_do_refresh_skip_due_to_rt_size(
    mock_host, local_peer_id, dummy_query_function
):
    """Test _do_refresh skips refresh when RT size is above threshold."""
    rt = DummyRoutingTable(size=20)  # Large size above threshold
    manager = RTRefreshManager(
        host=mock_host,
        routing_table=rt,
        local_peer_id=local_peer_id,
        query_function=dummy_query_function,
        enable_auto_refresh=True,
        refresh_interval=0.1,  # Short interval
        min_refresh_threshold=MIN_RT_REFRESH_THRESHOLD,
    )

    # Set last refresh time to old
    manager._last_refresh_time = 0.0

    with patch.object(
        manager.random_walk, "run_concurrent_random_walks"
    ) as mock_random_walk:
        with patch(
            "libp2p.discovery.random_walk.rt_refresh_manager.logger"
        ) as mock_logger:
            await manager._do_refresh(force=False)

            # Verify refresh was skipped
            mock_random_walk.assert_not_called()
            mock_logger.debug.assert_called_with(
                "Skipping refresh: routing table size above threshold"
            )


@pytest.mark.trio
async def test_refresh_done_callbacks(mock_host, local_peer_id, dummy_query_function):
    """Test refresh completion callbacks functionality."""
    rt = DummyRoutingTable(size=1)
    manager = RTRefreshManager(
        host=mock_host,
        routing_table=rt,
        local_peer_id=local_peer_id,
        query_function=dummy_query_function,
        enable_auto_refresh=True,
        refresh_interval=0.1,
        min_refresh_threshold=MIN_RT_REFRESH_THRESHOLD,
    )

    # Create mock callbacks
    callback1 = Mock()
    callback2 = Mock()
    failing_callback = Mock(side_effect=Exception("Callback failed"))

    # Add callbacks
    manager.add_refresh_done_callback(callback1)
    manager.add_refresh_done_callback(callback2)
    manager.add_refresh_done_callback(failing_callback)

    # Mock the random walk
    mock_peer_info = Mock(spec=PeerInfo)
    with patch.object(
        manager.random_walk,
        "run_concurrent_random_walks",
        return_value=[mock_peer_info],
    ):
        with patch(
            "libp2p.discovery.random_walk.rt_refresh_manager.logger"
        ) as mock_logger:
            await manager._do_refresh(force=True)

            # Verify all callbacks were called
            callback1.assert_called_once()
            callback2.assert_called_once()
            failing_callback.assert_called_once()

            # Verify warning was logged for failing callback
            mock_logger.warning.assert_called()


@pytest.mark.trio
async def test_stop_when_not_running(mock_host, local_peer_id, dummy_query_function):
    """Test stop method when manager is not running."""
    rt = DummyRoutingTable(size=1)
    manager = RTRefreshManager(
        host=mock_host,
        routing_table=rt,
        local_peer_id=local_peer_id,
        query_function=dummy_query_function,
        enable_auto_refresh=True,
        refresh_interval=0.1,
        min_refresh_threshold=MIN_RT_REFRESH_THRESHOLD,
    )

    # Manager is not running
    assert not manager._running

    # Stop should return without doing anything
    await manager.stop()
    assert not manager._running


@pytest.mark.trio
async def test_periodic_refresh_task(mock_host, local_peer_id, dummy_query_function):
    """Test the _periodic_refresh_task method."""
    rt = DummyRoutingTable(size=1)
    manager = RTRefreshManager(
        host=mock_host,
        routing_table=rt,
        local_peer_id=local_peer_id,
        query_function=dummy_query_function,
        enable_auto_refresh=True,
        refresh_interval=0.05,  # Very short interval for testing
        min_refresh_threshold=MIN_RT_REFRESH_THRESHOLD,
    )

    # Mock _do_refresh to track calls
    with patch.object(manager, "_do_refresh") as mock_do_refresh:
        manager._running = True

        # Run periodic refresh task for a short time
        async with trio.open_nursery() as nursery:
            nursery.start_soon(manager._periodic_refresh_task)
            await trio.sleep(0.12)  # Let it run for ~2 intervals
            manager._running = False  # Stop the task

        # Verify _do_refresh was called at least once
        assert mock_do_refresh.call_count >= 1
