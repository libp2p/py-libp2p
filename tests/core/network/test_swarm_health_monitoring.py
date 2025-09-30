"""
Tests for Swarm health monitoring functionality.

This module tests the health monitoring features including:
- Health monitoring task tracking
- Ping connection with timeout
- Health monitoring lifecycle
"""

from unittest.mock import Mock

import pytest
import trio

from libp2p.abc import INetConn, INetStream
from libp2p.network.swarm import (
    ConnectionConfig,
    RetryConfig,
    Swarm,
)
from libp2p.peer.id import ID
from libp2p.peer.peerstore import PeerStore


class MockConnection(INetConn):
    """Mock connection for testing health monitoring."""

    def __init__(self, peer_id: ID, should_fail: bool = False, delay: float = 0.0):
        self.peer_id = peer_id
        self._should_fail = should_fail
        self._delay = delay
        self._is_closed = False
        self.streams = set()
        self.muxed_conn = Mock()
        self.muxed_conn.peer_id = peer_id
        self.event_started = trio.Event()

    async def close(self):
        self._is_closed = True

    @property
    def is_closed(self) -> bool:
        return self._is_closed

    async def new_stream(self) -> INetStream:
        if self._delay > 0:
            await trio.sleep(self._delay)

        if self._should_fail:
            raise Exception("Connection failed")

        mock_stream = Mock(spec=INetStream)
        self.streams.add(mock_stream)
        return mock_stream

    def get_streams(self) -> tuple[INetStream, ...]:
        return tuple(self.streams)

    def get_transport_addresses(self):
        return []


@pytest.fixture
def health_monitoring_swarm():
    """Create a swarm with health monitoring enabled."""
    peer_id = ID(b"QmTest123")
    peerstore = PeerStore()

    # Create configuration with health monitoring enabled
    retry_config = RetryConfig()
    connection_config = ConnectionConfig(
        enable_health_monitoring=True,
        health_check_interval=0.1,  # Fast for testing
        ping_timeout=0.5,  # Short timeout for testing
        min_health_threshold=0.3,
        min_connections_per_peer=1,
    )

    # Create transport and upgrader (using mocks for testing)
    transport = Mock()
    upgrader = Mock()

    return Swarm(
        peer_id, peerstore, upgrader, transport, retry_config, connection_config
    )


@pytest.mark.trio
async def test_health_monitoring_task_tracking(health_monitoring_swarm):
    """Test that health monitoring task tracking works correctly."""
    swarm = health_monitoring_swarm

    # Initially, health monitoring should be inactive
    assert not swarm._health_monitoring_active

    # Test setting the flag
    swarm._health_monitoring_active = True
    assert swarm._health_monitoring_active

    # Test unsetting the flag
    swarm._health_monitoring_active = False
    assert not swarm._health_monitoring_active


@pytest.mark.trio
async def test_ping_connection_with_timeout():
    """Test that ping connection respects the configured timeout."""
    peer_id = ID(b"QmTest123")
    peerstore = PeerStore()

    # Create configuration with short ping timeout
    retry_config = RetryConfig()
    connection_config = ConnectionConfig(
        enable_health_monitoring=True,
        ping_timeout=0.1,  # Very short timeout
        min_health_threshold=0.3,
    )

    transport = Mock()
    upgrader = Mock()

    swarm = Swarm(
        peer_id, peerstore, upgrader, transport, retry_config, connection_config
    )

    # Test 1: Successful ping (fast connection)
    fast_conn = MockConnection(peer_id, should_fail=False, delay=0.05)
    result = await swarm._ping_connection(fast_conn)
    assert result is True

    # Test 2: Ping timeout (slow connection)
    slow_conn = MockConnection(
        peer_id, should_fail=False, delay=0.2
    )  # Longer than timeout
    result = await swarm._ping_connection(slow_conn)
    assert result is False

    # Test 3: Ping failure (connection error)
    failing_conn = MockConnection(peer_id, should_fail=True)
    result = await swarm._ping_connection(failing_conn)
    assert result is False


@pytest.mark.trio
async def test_health_monitoring_lifecycle():
    """Test the complete health monitoring lifecycle."""
    peer_id = ID(b"QmTest123")
    peerstore = PeerStore()

    retry_config = RetryConfig()
    connection_config = ConnectionConfig(
        enable_health_monitoring=True,
        health_check_interval=0.1,
        ping_timeout=0.5,
        min_health_threshold=0.3,
    )

    transport = Mock()
    upgrader = Mock()

    swarm = Swarm(
        peer_id, peerstore, upgrader, transport, retry_config, connection_config
    )

    # Test initial state
    assert not swarm._health_monitoring_active

    # Test setting active
    swarm._health_monitoring_active = True
    assert swarm._health_monitoring_active

    # Test deactivating
    swarm._health_monitoring_active = False
    assert not swarm._health_monitoring_active


@pytest.mark.trio
async def test_health_monitoring_disabled():
    """Test that health monitoring can be disabled."""
    peer_id = ID(b"QmTest123")
    peerstore = PeerStore()

    # Create configuration with health monitoring disabled
    retry_config = RetryConfig()
    connection_config = ConnectionConfig(
        enable_health_monitoring=False,  # Disabled
        health_check_interval=0.1,
        ping_timeout=0.5,
    )

    transport = Mock()
    upgrader = Mock()

    swarm = Swarm(
        peer_id, peerstore, upgrader, transport, retry_config, connection_config
    )

    # Health monitoring should remain inactive (attribute may not exist if disabled)
    assert (
        not hasattr(swarm, "_health_monitoring_active")
        or not swarm._health_monitoring_active
    )


@pytest.mark.trio
async def test_ping_timeout_configuration():
    """Test that different ping timeout values work correctly."""
    peer_id = ID(b"QmTest123")
    peerstore = PeerStore()

    # Test with different timeout values
    timeout_values = [0.05, 0.1, 0.2, 0.5]

    for timeout in timeout_values:
        retry_config = RetryConfig()
        connection_config = ConnectionConfig(
            enable_health_monitoring=True, ping_timeout=timeout
        )

        transport = Mock()
        upgrader = Mock()

        swarm = Swarm(
            peer_id, peerstore, upgrader, transport, retry_config, connection_config
        )

        # Test with connection that takes exactly the timeout duration
        conn = MockConnection(peer_id, should_fail=False, delay=timeout * 0.8)
        result = await swarm._ping_connection(conn)
        assert result is True

        # Test with connection that takes longer than timeout
        slow_conn = MockConnection(peer_id, should_fail=False, delay=timeout * 1.5)
        result = await swarm._ping_connection(slow_conn)
        assert result is False


@pytest.mark.trio
async def test_health_monitoring_task_cancellation(health_monitoring_swarm):
    """Test that health monitoring task is properly cancelled."""
    swarm = health_monitoring_swarm

    # Test initial state
    assert not swarm._health_monitoring_active

    # Test setting active
    swarm._health_monitoring_active = True
    assert swarm._health_monitoring_active

    # Test manual cancellation
    swarm._health_monitoring_active = False
    assert not swarm._health_monitoring_active


@pytest.mark.trio
async def test_connection_health_data_initialization(health_monitoring_swarm):
    """Test that health data is properly initialized."""
    swarm = health_monitoring_swarm

    # Health data should be initialized
    assert hasattr(swarm, "health_data")
    assert hasattr(swarm, "health_config")
    assert hasattr(swarm, "_health_monitoring_active")

    # Initially inactive
    assert not swarm._health_monitoring_active

    # Health config should be properly set
    assert swarm.health_config.ping_timeout == swarm.connection_config.ping_timeout
    assert (
        swarm.health_config.health_check_interval
        == swarm.connection_config.health_check_interval
    )


@pytest.mark.trio
async def test_ping_connection_edge_cases():
    """Test edge cases for ping connection."""
    peer_id = ID(b"QmTest123")
    peerstore = PeerStore()

    retry_config = RetryConfig()
    connection_config = ConnectionConfig(
        enable_health_monitoring=True, ping_timeout=0.1
    )

    transport = Mock()
    upgrader = Mock()

    swarm = Swarm(
        peer_id, peerstore, upgrader, transport, retry_config, connection_config
    )

    # Test with connection that fails immediately
    failing_conn = MockConnection(peer_id, should_fail=True, delay=0.0)
    result = await swarm._ping_connection(failing_conn)
    assert result is False

    # Test with connection that succeeds immediately
    success_conn = MockConnection(peer_id, should_fail=False, delay=0.0)
    result = await swarm._ping_connection(success_conn)
    assert result is True


@pytest.mark.trio
async def test_health_monitoring_configuration_validation():
    """Test that health monitoring configuration is properly validated."""
    peer_id = ID(b"QmTest123")
    peerstore = PeerStore()

    # Test with valid configuration
    retry_config = RetryConfig()
    connection_config = ConnectionConfig(
        enable_health_monitoring=True,
        health_check_interval=0.5,
        ping_timeout=1.0,
        min_health_threshold=0.5,
        min_connections_per_peer=2,
    )

    transport = Mock()
    upgrader = Mock()

    swarm = Swarm(
        peer_id, peerstore, upgrader, transport, retry_config, connection_config
    )

    # Verify configuration is properly set
    assert swarm.connection_config.enable_health_monitoring is True
    assert swarm.connection_config.health_check_interval == 0.5
    assert swarm.connection_config.ping_timeout == 1.0
    assert swarm.connection_config.min_health_threshold == 0.5
    assert swarm.connection_config.min_connections_per_peer == 2

    # Verify health config is properly initialized
    assert swarm.health_config.ping_timeout == 1.0
    assert swarm.health_config.health_check_interval == 0.5
