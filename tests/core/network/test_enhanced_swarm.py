import time
from typing import cast
from unittest.mock import Mock

import pytest
from multiaddr import Multiaddr
import trio

from libp2p.abc import INetConn, INetStream
from libp2p.network.exceptions import SwarmException
from libp2p.network.swarm import (
    ConnectionConfig,
    RetryConfig,
    Swarm,
)
from libp2p.peer.id import ID


class MockConnection(INetConn):
    """Mock connection for testing."""

    def __init__(self, peer_id: ID, is_closed: bool = False):
        self.peer_id = peer_id
        self._is_closed = is_closed
        self.streams = set()  # Track streams properly
        # Mock the muxed_conn attribute that Swarm expects
        self.muxed_conn = Mock()
        self.muxed_conn.peer_id = peer_id
        # Required by INetConn interface
        self.event_started = trio.Event()

    async def close(self):
        self._is_closed = True

    @property
    def is_closed(self) -> bool:
        return self._is_closed

    async def new_stream(self) -> INetStream:
        # Create a mock stream and add it to the connection's stream set
        mock_stream = Mock(spec=INetStream)
        self.streams.add(mock_stream)
        return mock_stream

    def get_streams(self) -> tuple[INetStream, ...]:
        """Return all streams associated with this connection."""
        return tuple(self.streams)

    def get_transport_addresses(self) -> list[Multiaddr]:
        """Mock implementation of get_transport_addresses."""
        return []


class MockNetStream(INetStream):
    """Mock network stream for testing."""

    def __init__(self, peer_id: ID):
        self.peer_id = peer_id


@pytest.mark.trio
async def test_retry_config_defaults():
    """Test RetryConfig default values."""
    config = RetryConfig()
    assert config.max_retries == 3
    assert config.initial_delay == 0.1
    assert config.max_delay == 30.0
    assert config.backoff_multiplier == 2.0
    assert config.jitter_factor == 0.1


@pytest.mark.trio
async def test_connection_config_defaults():
    """Test ConnectionConfig default values."""
    config = ConnectionConfig()
    assert config.max_connections_per_peer == 3
    assert config.connection_timeout == 30.0
    assert config.load_balancing_strategy == "round_robin"


@pytest.mark.trio
async def test_enhanced_swarm_constructor():
    """Test enhanced Swarm constructor with new configuration."""
    # Create mock dependencies
    peer_id = ID(b"QmTest")
    peerstore = Mock()
    upgrader = Mock()
    transport = Mock()

    # Test with default config
    swarm = Swarm(peer_id, peerstore, upgrader, transport)
    assert swarm.retry_config.max_retries == 3
    assert swarm.connection_config.max_connections_per_peer == 3
    assert isinstance(swarm.connections, dict)

    # Test with custom config
    custom_retry = RetryConfig(max_retries=5, initial_delay=0.5)
    custom_conn = ConnectionConfig(max_connections_per_peer=5)

    swarm = Swarm(peer_id, peerstore, upgrader, transport, custom_retry, custom_conn)
    assert swarm.retry_config.max_retries == 5
    assert swarm.retry_config.initial_delay == 0.5
    assert swarm.connection_config.max_connections_per_peer == 5


@pytest.mark.trio
async def test_swarm_backoff_calculation():
    """Test exponential backoff calculation with jitter."""
    peer_id = ID(b"QmTest")
    peerstore = Mock()
    upgrader = Mock()
    transport = Mock()

    retry_config = RetryConfig(
        initial_delay=0.1, max_delay=1.0, backoff_multiplier=2.0, jitter_factor=0.1
    )

    swarm = Swarm(peer_id, peerstore, upgrader, transport, retry_config)

    # Test backoff calculation
    delay1 = swarm._calculate_backoff_delay(0)
    delay2 = swarm._calculate_backoff_delay(1)
    delay3 = swarm._calculate_backoff_delay(2)

    # Should increase exponentially
    assert delay2 > delay1
    assert delay3 > delay2

    # Should respect max delay
    assert delay1 <= 1.0
    assert delay2 <= 1.0
    assert delay3 <= 1.0

    # Should have jitter
    assert delay1 != 0.1  # Should have jitter added


@pytest.mark.trio
async def test_swarm_retry_logic():
    """Test retry logic in dial operations."""
    peer_id = ID(b"QmTest")
    peerstore = Mock()
    upgrader = Mock()
    transport = Mock()

    # Configure for fast testing
    retry_config = RetryConfig(
        max_retries=2,
        initial_delay=0.01,  # Very short for testing
        max_delay=0.1,
    )

    swarm = Swarm(peer_id, peerstore, upgrader, transport, retry_config)

    # Mock the single attempt method to fail twice then succeed
    attempt_count = [0]

    async def mock_single_attempt(addr, peer_id):
        attempt_count[0] += 1
        if attempt_count[0] < 3:
            raise SwarmException(f"Attempt {attempt_count[0]} failed")
        return MockConnection(peer_id)

    swarm._dial_addr_single_attempt = mock_single_attempt

    # Test retry logic
    start_time = time.time()
    result = await swarm._dial_with_retry(Mock(spec=Multiaddr), peer_id)
    end_time = time.time()

    # Should have succeeded after 3 attempts
    assert attempt_count[0] == 3
    assert isinstance(result, MockConnection)
    assert end_time - start_time > 0.01  # Should have some delay


@pytest.mark.trio
async def test_swarm_load_balancing_strategies():
    """Test load balancing strategies."""
    peer_id = ID(b"QmTest")
    peerstore = Mock()
    upgrader = Mock()
    transport = Mock()

    swarm = Swarm(peer_id, peerstore, upgrader, transport)

    # Create mock connections with different stream counts
    conn1 = MockConnection(peer_id)
    conn2 = MockConnection(peer_id)
    conn3 = MockConnection(peer_id)

    # Add some streams to simulate load
    await conn1.new_stream()
    await conn1.new_stream()
    await conn2.new_stream()

    connections = [conn1, conn2, conn3]

    # Test round-robin strategy
    swarm.connection_config.load_balancing_strategy = "round_robin"
    # Cast to satisfy type checker
    connections_cast = cast("list[INetConn]", connections)
    selected1 = swarm._select_connection(connections_cast, peer_id)
    selected2 = swarm._select_connection(connections_cast, peer_id)
    selected3 = swarm._select_connection(connections_cast, peer_id)

    # Should cycle through connections
    assert selected1 in connections
    assert selected2 in connections
    assert selected3 in connections

    # Test least loaded strategy
    swarm.connection_config.load_balancing_strategy = "least_loaded"
    least_loaded = swarm._select_connection(connections_cast, peer_id)

    # conn3 has 0 streams, conn2 has 1 stream, conn1 has 2 streams
    # So conn3 should be selected as least loaded
    assert least_loaded == conn3

    # Test default strategy (first connection)
    swarm.connection_config.load_balancing_strategy = "unknown"
    default_selected = swarm._select_connection(connections_cast, peer_id)
    assert default_selected == conn1


@pytest.mark.trio
async def test_swarm_multiple_connections_api():
    """Test the new multiple connections API methods."""
    peer_id = ID(b"QmTest")
    peerstore = Mock()
    upgrader = Mock()
    transport = Mock()

    swarm = Swarm(peer_id, peerstore, upgrader, transport)

    # Test empty connections
    assert swarm.get_connections() == []
    assert swarm.get_connections(peer_id) == []
    assert swarm.get_connection(peer_id) is None
    assert swarm.get_connections_map() == {}

    # Add some connections
    conn1 = MockConnection(peer_id)
    conn2 = MockConnection(peer_id)
    swarm.connections[peer_id] = [conn1, conn2]

    # Test get_connections with peer_id
    peer_connections = swarm.get_connections(peer_id)
    assert len(peer_connections) == 2
    assert conn1 in peer_connections
    assert conn2 in peer_connections

    # Test get_connections without peer_id (all connections)
    all_connections = swarm.get_connections()
    assert len(all_connections) == 2
    assert conn1 in all_connections
    assert conn2 in all_connections

    # Test get_connection (backward compatibility)
    single_conn = swarm.get_connection(peer_id)
    assert single_conn in [conn1, conn2]

    # Test get_connections_map
    connections_map = swarm.get_connections_map()
    assert peer_id in connections_map
    assert connections_map[peer_id] == [conn1, conn2]


@pytest.mark.trio
async def test_swarm_connection_trimming():
    """Test connection trimming when limit is exceeded."""
    peer_id = ID(b"QmTest")
    peerstore = Mock()
    upgrader = Mock()
    transport = Mock()

    # Set max connections to 2
    connection_config = ConnectionConfig(max_connections_per_peer=2)
    swarm = Swarm(
        peer_id, peerstore, upgrader, transport, connection_config=connection_config
    )

    # Add 3 connections
    conn1 = MockConnection(peer_id)
    conn2 = MockConnection(peer_id)
    conn3 = MockConnection(peer_id)

    swarm.connections[peer_id] = [conn1, conn2, conn3]

    # Trigger trimming
    swarm._trim_connections(peer_id)

    # Should have only 2 connections
    assert len(swarm.connections[peer_id]) == 2

    # The most recent connections should remain
    remaining = swarm.connections[peer_id]
    assert conn2 in remaining
    assert conn3 in remaining


@pytest.mark.trio
async def test_swarm_backward_compatibility():
    """Test backward compatibility features."""
    peer_id = ID(b"QmTest")
    peerstore = Mock()
    upgrader = Mock()
    transport = Mock()

    swarm = Swarm(peer_id, peerstore, upgrader, transport)

    # Add connections
    conn1 = MockConnection(peer_id)
    conn2 = MockConnection(peer_id)
    swarm.connections[peer_id] = [conn1, conn2]

    # Test connections_legacy property
    legacy_connections = swarm.connections_legacy
    assert peer_id in legacy_connections
    # Should return first connection
    assert legacy_connections[peer_id] in [conn1, conn2]


if __name__ == "__main__":
    pytest.main([__file__])
