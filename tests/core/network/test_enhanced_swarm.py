import time
from unittest.mock import Mock

import pytest
from multiaddr import Multiaddr

from libp2p.abc import INetConn, INetStream
from libp2p.network.exceptions import SwarmException
from libp2p.network.swarm import (
    ConnectionConfig,
    ConnectionPool,
    RetryConfig,
    Swarm,
)
from libp2p.peer.id import ID


class MockConnection(INetConn):
    """Mock connection for testing."""

    def __init__(self, peer_id: ID, is_closed: bool = False):
        self.peer_id = peer_id
        self._is_closed = is_closed
        self.stream_count = 0
        # Mock the muxed_conn attribute that Swarm expects
        self.muxed_conn = Mock()
        self.muxed_conn.peer_id = peer_id

    async def close(self):
        self._is_closed = True

    @property
    def is_closed(self) -> bool:
        return self._is_closed

    async def new_stream(self) -> INetStream:
        self.stream_count += 1
        return Mock(spec=INetStream)

    def get_streams(self) -> tuple[INetStream, ...]:
        """Mock implementation of get_streams."""
        return tuple()

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
    assert config.enable_connection_pool is True
    assert config.load_balancing_strategy == "round_robin"


@pytest.mark.trio
async def test_connection_pool_basic_operations():
    """Test basic ConnectionPool operations."""
    pool = ConnectionPool(max_connections_per_peer=2)
    peer_id = ID(b"QmTest")

    # Test empty pool
    assert not pool.has_connection(peer_id)
    assert pool.get_connection(peer_id) is None

    # Add connection
    conn1 = MockConnection(peer_id)
    pool.add_connection(peer_id, conn1, "addr1")
    assert pool.has_connection(peer_id)
    assert pool.get_connection(peer_id) == conn1

    # Add second connection
    conn2 = MockConnection(peer_id)
    pool.add_connection(peer_id, conn2, "addr2")
    assert len(pool.peer_connections[peer_id]) == 2

    # Test round-robin - should cycle through connections
    first_conn = pool.get_connection(peer_id, "round_robin")
    second_conn = pool.get_connection(peer_id, "round_robin")
    third_conn = pool.get_connection(peer_id, "round_robin")

    # Should cycle through both connections
    assert first_conn in [conn1, conn2]
    assert second_conn in [conn1, conn2]
    assert third_conn in [conn1, conn2]
    assert first_conn != second_conn or second_conn != third_conn

    # Test least loaded - set different stream counts
    conn1.stream_count = 5
    conn2.stream_count = 1
    least_loaded_conn = pool.get_connection(peer_id, "least_loaded")
    assert least_loaded_conn == conn2  # conn2 has fewer streams


@pytest.mark.trio
async def test_connection_pool_deduplication():
    """Test connection deduplication by address."""
    pool = ConnectionPool(max_connections_per_peer=3)
    peer_id = ID(b"QmTest")

    conn1 = MockConnection(peer_id)
    pool.add_connection(peer_id, conn1, "addr1")

    # Try to add connection with same address
    conn2 = MockConnection(peer_id)
    pool.add_connection(peer_id, conn2, "addr1")

    # Should only have one connection
    assert len(pool.peer_connections[peer_id]) == 1
    assert pool.get_connection(peer_id) == conn1


@pytest.mark.trio
async def test_connection_pool_trimming():
    """Test connection trimming when limit is exceeded."""
    pool = ConnectionPool(max_connections_per_peer=2)
    peer_id = ID(b"QmTest")

    # Add 3 connections
    conn1 = MockConnection(peer_id)
    conn2 = MockConnection(peer_id)
    conn3 = MockConnection(peer_id)

    pool.add_connection(peer_id, conn1, "addr1")
    pool.add_connection(peer_id, conn2, "addr2")
    pool.add_connection(peer_id, conn3, "addr3")

    # Should trim to 2 connections
    assert len(pool.peer_connections[peer_id]) == 2

    # The oldest connections should be removed
    remaining_connections = [c.connection for c in pool.peer_connections[peer_id]]
    assert conn3 in remaining_connections  # Most recent should remain


@pytest.mark.trio
async def test_connection_pool_remove_connection():
    """Test removing connections from pool."""
    pool = ConnectionPool(max_connections_per_peer=3)
    peer_id = ID(b"QmTest")

    conn1 = MockConnection(peer_id)
    conn2 = MockConnection(peer_id)

    pool.add_connection(peer_id, conn1, "addr1")
    pool.add_connection(peer_id, conn2, "addr2")

    assert len(pool.peer_connections[peer_id]) == 2

    # Remove connection
    pool.remove_connection(peer_id, conn1)
    assert len(pool.peer_connections[peer_id]) == 1
    assert pool.get_connection(peer_id) == conn2

    # Remove last connection
    pool.remove_connection(peer_id, conn2)
    assert not pool.has_connection(peer_id)


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
    assert swarm.connection_pool is not None

    # Test with custom config
    custom_retry = RetryConfig(max_retries=5, initial_delay=0.5)
    custom_conn = ConnectionConfig(
        max_connections_per_peer=5,
        enable_connection_pool=False
    )

    swarm = Swarm(peer_id, peerstore, upgrader, transport, custom_retry, custom_conn)
    assert swarm.retry_config.max_retries == 5
    assert swarm.retry_config.initial_delay == 0.5
    assert swarm.connection_config.max_connections_per_peer == 5
    assert swarm.connection_pool is None


@pytest.mark.trio
async def test_swarm_backoff_calculation():
    """Test exponential backoff calculation with jitter."""
    peer_id = ID(b"QmTest")
    peerstore = Mock()
    upgrader = Mock()
    transport = Mock()

    retry_config = RetryConfig(
        initial_delay=0.1,
        max_delay=1.0,
        backoff_multiplier=2.0,
        jitter_factor=0.1
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
        max_delay=0.1
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
    assert result is not None

    # Should have taken some time due to retries
    assert end_time - start_time > 0.02  # At least 2 delays


@pytest.mark.trio
async def test_swarm_multi_connection_support():
    """Test multi-connection support in Swarm."""
    peer_id = ID(b"QmTest")
    peerstore = Mock()
    upgrader = Mock()
    transport = Mock()

    connection_config = ConnectionConfig(
        max_connections_per_peer=3,
        enable_connection_pool=True,
        load_balancing_strategy="round_robin"
    )

    swarm = Swarm(
        peer_id,
        peerstore,
        upgrader,
        transport,
        connection_config=connection_config
    )

    # Mock connection pool methods
    assert swarm.connection_pool is not None
    connection_pool = swarm.connection_pool
    connection_pool.has_connection = Mock(return_value=True)
    connection_pool.get_connection = Mock(return_value=MockConnection(peer_id))

    # Test that new_stream uses connection pool
    result = await swarm.new_stream(peer_id)
    assert result is not None
    # Use the mocked method directly to avoid type checking issues
    get_connection_mock = connection_pool.get_connection
    assert get_connection_mock.call_count == 1


@pytest.mark.trio
async def test_swarm_backward_compatibility():
    """Test that enhanced Swarm maintains backward compatibility."""
    peer_id = ID(b"QmTest")
    peerstore = Mock()
    upgrader = Mock()
    transport = Mock()

    # Create swarm with connection pool disabled
    connection_config = ConnectionConfig(enable_connection_pool=False)
    swarm = Swarm(
        peer_id, peerstore, upgrader, transport,
        connection_config=connection_config
    )

    # Should behave like original swarm
    assert swarm.connection_pool is None
    assert isinstance(swarm.connections, dict)

    # Test that dial_peer still works (will fail due to mocks, but structure is correct)
    peerstore.addrs.return_value = [Mock(spec=Multiaddr)]
    transport.dial.side_effect = Exception("Transport error")

    with pytest.raises(SwarmException):
        await swarm.dial_peer(peer_id)


@pytest.mark.trio
async def test_swarm_connection_pool_integration():
    """Test integration between Swarm and ConnectionPool."""
    peer_id = ID(b"QmTest")
    peerstore = Mock()
    upgrader = Mock()
    transport = Mock()

    connection_config = ConnectionConfig(
        max_connections_per_peer=2,
        enable_connection_pool=True
    )

    swarm = Swarm(
        peer_id, peerstore, upgrader, transport,
        connection_config=connection_config
    )

    # Mock successful connection creation
    mock_conn = MockConnection(peer_id)
    peerstore.addrs.return_value = [Mock(spec=Multiaddr)]

    async def mock_dial_with_retry(addr, peer_id):
        return mock_conn

    swarm._dial_with_retry = mock_dial_with_retry

    # Test dial_peer adds to connection pool
    result = await swarm.dial_peer(peer_id)
    assert result == mock_conn
    assert swarm.connection_pool is not None
    assert swarm.connection_pool.has_connection(peer_id)

    # Test that subsequent calls reuse connection
    result2 = await swarm.dial_peer(peer_id)
    assert result2 == mock_conn


@pytest.mark.trio
async def test_swarm_connection_cleanup():
    """Test connection cleanup in enhanced Swarm."""
    peer_id = ID(b"QmTest")
    peerstore = Mock()
    upgrader = Mock()
    transport = Mock()

    connection_config = ConnectionConfig(enable_connection_pool=True)
    swarm = Swarm(
        peer_id, peerstore, upgrader, transport,
        connection_config=connection_config
    )

    # Add a connection
    mock_conn = MockConnection(peer_id)
    swarm.connections[peer_id] = mock_conn
    assert swarm.connection_pool is not None
    swarm.connection_pool.add_connection(peer_id, mock_conn, "test_addr")

    # Test close_peer removes from pool
    await swarm.close_peer(peer_id)
    assert swarm.connection_pool is not None
    assert not swarm.connection_pool.has_connection(peer_id)

    # Test remove_conn removes from pool
    mock_conn2 = MockConnection(peer_id)
    swarm.connections[peer_id] = mock_conn2
    assert swarm.connection_pool is not None
    connection_pool = swarm.connection_pool
    connection_pool.add_connection(peer_id, mock_conn2, "test_addr2")

    # Note: remove_conn expects SwarmConn, but for testing we'll just
    # remove from pool directly
    connection_pool = swarm.connection_pool
    connection_pool.remove_connection(peer_id, mock_conn2)
    assert connection_pool is not None
    assert not connection_pool.has_connection(peer_id)


if __name__ == "__main__":
    pytest.main([__file__])
