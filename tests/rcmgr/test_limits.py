"""
Tests for resource limits and limiters.
"""

from libp2p.peer.id import ID
from libp2p.rcmgr.limits import BaseLimit, Direction, FixedLimiter


def test_base_limit_creation():
    """Test BaseLimit creation with default values."""
    limit = BaseLimit()

    # Check that defaults are set properly
    assert limit.get_memory_limit() > 0
    assert limit.get_stream_limit(Direction.INBOUND) > 0
    assert limit.get_stream_limit(Direction.OUTBOUND) > 0
    assert limit.get_conn_limit(Direction.INBOUND) > 0
    assert limit.get_conn_limit(Direction.OUTBOUND) > 0
    assert limit.get_fd_limit() > 0


def test_base_limit_custom_values():
    """Test BaseLimit with custom values."""
    limit = BaseLimit(
        streams=100,
        streams_inbound=60,
        streams_outbound=40,
        conns=50,
        conns_inbound=30,
        conns_outbound=20,
        fd=64,
        memory=1024 * 1024  # 1MB
    )

    assert limit.get_memory_limit() == 1024 * 1024
    assert limit.get_stream_limit(Direction.INBOUND) == 60
    assert limit.get_stream_limit(Direction.OUTBOUND) == 40
    assert limit.get_stream_total_limit() == 100
    assert limit.get_conn_limit(Direction.INBOUND) == 30
    assert limit.get_conn_limit(Direction.OUTBOUND) == 20
    assert limit.get_conn_total_limit() == 50
    assert limit.get_fd_limit() == 64


def test_fixed_limiter_defaults():
    """Test FixedLimiter with default values."""
    limiter = FixedLimiter()

    # Test system limits
    system_limits = limiter.get_system_limits()
    assert system_limits.get_memory_limit() == 1 << 30  # 1GB
    assert system_limits.get_stream_total_limit() == 16000
    assert system_limits.get_conn_total_limit() == 1000

    # Test transient limits
    transient_limits = limiter.get_transient_limits()
    assert transient_limits.get_memory_limit() == 32 << 20  # 32MB
    assert transient_limits.get_stream_total_limit() == 500
    assert transient_limits.get_conn_total_limit() == 50


def test_fixed_limiter_custom_limits():
    """Test FixedLimiter with custom limits."""
    custom_system = BaseLimit(
        streams=1000,
        memory=512 << 20  # 512MB
    )

    limiter = FixedLimiter(system=custom_system)

    system_limits = limiter.get_system_limits()
    assert system_limits.get_memory_limit() == 512 << 20
    assert system_limits.get_stream_total_limit() == 1000


def test_fixed_limiter_peer_limits():
    """Test peer-specific limits."""
    limiter = FixedLimiter()
    peer_id = ID(b"test_peer")

    # Should return default peer limits
    peer_limits = limiter.get_peer_limits(peer_id)
    assert peer_limits.get_stream_total_limit() == 64
    assert peer_limits.get_conn_total_limit() == 8
    assert peer_limits.get_memory_limit() == 64 << 20  # 64MB


def test_fixed_limiter_protocol_limits():
    """Test protocol-specific limits."""
    limiter = FixedLimiter()
    protocol = "/test/1.0.0"

    # Should return default protocol limits
    protocol_limits = limiter.get_protocol_limits(protocol)
    assert protocol_limits.get_stream_total_limit() == 512
    assert protocol_limits.get_conn_total_limit() == 100
    assert protocol_limits.get_memory_limit() == 16 << 20  # 16MB


def test_fixed_limiter_service_limits():
    """Test service-specific limits."""
    limiter = FixedLimiter()
    service = "test_service"

    # Should return default service limits
    service_limits = limiter.get_service_limits(service)
    assert service_limits.get_stream_total_limit() == 100
    assert service_limits.get_conn_total_limit() == 50
    assert service_limits.get_memory_limit() == 16 << 20  # 16MB


def test_direction_enum():
    """Test Direction enum values."""
    assert Direction.INBOUND.value == "inbound"
    assert Direction.OUTBOUND.value == "outbound"
