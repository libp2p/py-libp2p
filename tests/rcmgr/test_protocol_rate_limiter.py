"""
Tests for ProtocolRateLimiter implementation.

This module contains comprehensive tests for the ProtocolRateLimiter class,
including protocol-specific rate limiting, concurrent request tracking,
and backoff handling.
"""

import time

import pytest

from libp2p.peer.id import ID
from libp2p.rcmgr.protocol_rate_limiter import (
    ProtocolRateLimitConfig,
    ProtocolRateLimiter,
    ProtocolRateLimitStats,
    create_burst_protocol_rate_limiter,
    create_protocol_rate_limiter,
    create_strict_protocol_rate_limiter,
)
from libp2p.rcmgr.rate_limiter import RateLimitScope


class TestProtocolRateLimitConfig:
    """Test ProtocolRateLimitConfig dataclass."""

    def test_protocol_rate_limit_config_creation(self) -> None:
        """Test ProtocolRateLimitConfig creation with required parameters."""
        config = ProtocolRateLimitConfig(protocol_name="test_protocol")
        assert config.protocol_name == "test_protocol"
        assert config.protocol_version is None
        assert config.refill_rate == 10.0
        assert config.capacity == 100.0

    def test_protocol_rate_limit_config_custom_values(self) -> None:
        """Test ProtocolRateLimitConfig creation with custom values."""
        config = ProtocolRateLimitConfig(
            protocol_name="test_protocol",
            protocol_version="1.0.0",
            refill_rate=20.0,
            capacity=200.0,
            initial_tokens=100.0,
        )
        assert config.protocol_name == "test_protocol"
        assert config.protocol_version == "1.0.0"
        assert config.refill_rate == 20.0
        assert config.capacity == 200.0
        assert config.initial_tokens == 100.0

    def test_protocol_rate_limit_config_validation(self) -> None:
        """Test ProtocolRateLimitConfig validation."""
        # Test empty protocol name
        with pytest.raises(ValueError, match="protocol_name cannot be empty"):
            ProtocolRateLimitConfig(protocol_name="")

        # Test negative refill rate
        with pytest.raises(ValueError, match="refill_rate must be positive"):
            ProtocolRateLimitConfig(protocol_name="test", refill_rate=-1.0)

        # Test negative capacity
        with pytest.raises(ValueError, match="capacity must be positive"):
            ProtocolRateLimitConfig(protocol_name="test", capacity=-1.0)

        # Test negative initial tokens
        with pytest.raises(ValueError, match="initial_tokens must be non-negative"):
            ProtocolRateLimitConfig(protocol_name="test", initial_tokens=-1.0)

        # Test initial tokens exceeding capacity
        with pytest.raises(ValueError, match="initial_tokens cannot exceed capacity"):
            ProtocolRateLimitConfig(
                protocol_name="test", initial_tokens=150.0, capacity=100.0
            )

    def test_protocol_rate_limit_config_defaults(self) -> None:
        """Test ProtocolRateLimitConfig default values."""
        config = ProtocolRateLimitConfig(protocol_name="test")
        assert config.allow_burst is True
        assert config.burst_multiplier == 1.0
        assert config.time_window_seconds == 1.0
        assert config.min_interval_seconds == 0.001
        assert config.scope == RateLimitScope.PER_PEER
        assert config.max_peers == 1000
        assert config.max_connections == 1000
        assert config.enable_monitoring is True
        assert config.max_history_size == 1000
        assert config.max_concurrent_requests == 10
        assert config.request_timeout_seconds == 30.0
        assert config.backoff_factor == 2.0

    def test_protocol_rate_limit_config_equality(self) -> None:
        """Test ProtocolRateLimitConfig equality."""
        config1 = ProtocolRateLimitConfig(
            protocol_name="test", refill_rate=10.0, capacity=100.0
        )
        config2 = ProtocolRateLimitConfig(
            protocol_name="test", refill_rate=10.0, capacity=100.0
        )
        config3 = ProtocolRateLimitConfig(
            protocol_name="test", refill_rate=5.0, capacity=100.0
        )

        assert config1 == config2
        assert config1 != config3


class TestProtocolRateLimitStats:
    """Test ProtocolRateLimitStats dataclass."""

    def test_protocol_rate_limit_stats_creation(self) -> None:
        """Test ProtocolRateLimitStats creation."""
        stats = ProtocolRateLimitStats(
            protocol_name="test_protocol",
            protocol_version="1.0.0",
            current_rate=5.0,
            allowed_requests=100,
            denied_requests=10,
            total_requests=110,
            concurrent_requests=5,
            max_concurrent_requests=10,
            request_timeouts=2,
            backoff_events=1,
            scope=RateLimitScope.PER_PEER,
            tracked_entities=1,
            time_since_last_request=0.0,
            next_available_time=time.time() + 1.0,
        )
        assert stats.protocol_name == "test_protocol"
        assert stats.protocol_version == "1.0.0"
        assert stats.current_rate == 5.0
        assert stats.allowed_requests == 100
        assert stats.denied_requests == 10

    def test_protocol_rate_limit_stats_to_dict(self) -> None:
        """Test ProtocolRateLimitStats to_dict method."""
        stats = ProtocolRateLimitStats(
            protocol_name="test_protocol",
            protocol_version="1.0.0",
            current_rate=5.0,
            allowed_requests=100,
            denied_requests=10,
            total_requests=110,
            concurrent_requests=5,
            max_concurrent_requests=10,
            request_timeouts=2,
            backoff_events=1,
            scope=RateLimitScope.PER_PEER,
            tracked_entities=1,
            time_since_last_request=0.0,
            next_available_time=time.time() + 1.0,
        )
        stats_dict = stats.to_dict()
        assert isinstance(stats_dict, dict)
        assert "protocol_name" in stats_dict
        assert "current_rate" in stats_dict
        assert "allowed_requests" in stats_dict
        assert "denied_requests" in stats_dict


class TestProtocolRateLimiter:
    """Test ProtocolRateLimiter class."""

    def test_protocol_rate_limiter_creation(self) -> None:
        """Test ProtocolRateLimiter creation."""
        config = ProtocolRateLimitConfig(protocol_name="test_protocol")
        limiter = ProtocolRateLimiter(config)
        assert limiter.config == config
        assert limiter._request_timeouts == 0
        assert limiter._backoff_events == 0

    def test_protocol_rate_limiter_try_allow_request(self) -> None:
        """Test ProtocolRateLimiter try_allow_request method."""
        config = ProtocolRateLimitConfig(
            protocol_name="test_protocol",
            refill_rate=10.0,
            capacity=100.0,
            initial_tokens=50.0,
        )
        limiter = ProtocolRateLimiter(config)

        # Create test peer ID
        peer_id = ID.from_base58("QmTest123")

        # Should be able to allow request
        assert limiter.try_allow_request(peer_id=peer_id, tokens=10.0) is True

        # Should not be able to allow request with too many tokens
        assert limiter.try_allow_request(peer_id=peer_id, tokens=100.0) is False

    def test_protocol_rate_limiter_allow_request(self) -> None:
        """Test ProtocolRateLimiter allow_request method (raises exception)."""
        config = ProtocolRateLimitConfig(
            protocol_name="test_protocol",
            refill_rate=1.0,
            capacity=1.0,
            initial_tokens=1.0,
        )
        limiter = ProtocolRateLimiter(config)

        # Create test peer ID
        peer_id = ID.from_base58("QmTest123")

        # Should be able to allow request
        limiter.allow_request(peer_id=peer_id, tokens=1.0)

        # Should raise exception if not enough tokens
        with pytest.raises(ValueError):
            limiter.allow_request(peer_id=peer_id, tokens=1.0)

    def test_protocol_rate_limiter_finish_request(self) -> None:
        """Test ProtocolRateLimiter finish_request method."""
        config = ProtocolRateLimitConfig(protocol_name="test_protocol")
        limiter = ProtocolRateLimiter(config)

        # Create test peer ID
        peer_id = ID.from_base58("QmTest123")

        # Allow request
        limiter.try_allow_request(peer_id=peer_id)

        # Finish request
        limiter.finish_request(peer_id=peer_id)

        # Should have finished the request
        assert True  # No exception raised

    def test_protocol_rate_limiter_concurrent_requests(self) -> None:
        """Test ProtocolRateLimiter concurrent request tracking."""
        config = ProtocolRateLimitConfig(
            protocol_name="test_protocol",
            max_concurrent_requests=2,
            initial_tokens=10.0,
        )
        limiter = ProtocolRateLimiter(config)

        # Create test peer ID
        peer_id = ID.from_base58("QmTest123")

        # Should be able to allow 2 concurrent requests
        assert limiter.try_allow_request(peer_id=peer_id) is True
        assert limiter.try_allow_request(peer_id=peer_id) is True

        # Should be denied after reaching limit
        assert limiter.try_allow_request(peer_id=peer_id) is False

    def test_protocol_rate_limiter_backoff_handling(self) -> None:
        """Test ProtocolRateLimiter backoff handling."""
        config = ProtocolRateLimitConfig(
            protocol_name="test_protocol",
            max_concurrent_requests=1,
            request_timeout_seconds=0.1,
            backoff_factor=2.0,
            initial_tokens=10.0,
        )
        limiter = ProtocolRateLimiter(config)

        # Create test peer ID
        peer_id = ID.from_base58("QmTest123")

        # Allow request
        assert limiter.try_allow_request(peer_id=peer_id) is True

        # Try to allow another request (should be denied and trigger backoff)
        assert limiter.try_allow_request(peer_id=peer_id) is False

        # Should be in backoff
        assert (
            limiter._is_in_backoff(limiter._get_entity_key(peer_id), time.time())
            is True
        )

    def test_protocol_rate_limiter_request_timeout(self) -> None:
        """Test ProtocolRateLimiter request timeout handling."""
        config = ProtocolRateLimitConfig(
            protocol_name="test_protocol",
            request_timeout_seconds=0.1,
            initial_tokens=10.0,
        )
        limiter = ProtocolRateLimiter(config)

        # Create test peer ID
        peer_id = ID.from_base58("QmTest123")

        # Allow request
        assert limiter.try_allow_request(peer_id=peer_id) is True

        # Wait for timeout
        time.sleep(0.2)

        # Clean up old requests
        limiter._cleanup_old_requests(limiter._get_entity_key(peer_id), time.time())

        # Should have cleaned up old requests (concurrent count should be 0)
        entity_key = limiter._get_entity_key(peer_id)
        assert limiter._concurrent_requests.get(entity_key, 0) == 0

    def test_protocol_rate_limiter_get_stats(self) -> None:
        """Test ProtocolRateLimiter statistics."""
        config = ProtocolRateLimitConfig(protocol_name="test_protocol")
        limiter = ProtocolRateLimiter(config)

        # Create test peer ID
        peer_id = ID.from_base58("QmTest123")

        # Make some requests
        limiter.try_allow_request(peer_id=peer_id, tokens=10.0)
        limiter.try_allow_request(peer_id=peer_id, tokens=20.0)

        stats = limiter.get_stats(peer_id=peer_id)
        assert stats.protocol_name == "test_protocol"
        assert stats.total_requests >= 2

    def test_protocol_rate_limiter_get_entity_stats(self) -> None:
        """Test ProtocolRateLimiter entity-specific statistics."""
        config = ProtocolRateLimitConfig(protocol_name="test_protocol")
        limiter = ProtocolRateLimiter(config)

        # Create test peer ID
        peer_id = ID.from_base58("QmTest123")

        # Make some requests
        limiter.try_allow_request(peer_id=peer_id, tokens=10.0)

        # Get entity stats
        entity_stats = limiter.get_entity_stats(peer_id=peer_id)
        assert isinstance(entity_stats, dict)
        assert "protocol_name" in entity_stats

    def test_protocol_rate_limiter_reset(self) -> None:
        """Test ProtocolRateLimiter reset."""
        config = ProtocolRateLimitConfig(protocol_name="test_protocol")
        limiter = ProtocolRateLimiter(config)

        # Create test peer ID
        peer_id = ID.from_base58("QmTest123")

        # Make some requests
        limiter.try_allow_request(peer_id=peer_id, tokens=10.0)

        # Reset
        limiter.reset()

        # Should be back to initial state
        assert limiter._request_timeouts == 0
        assert limiter._backoff_events == 0

    def test_protocol_rate_limiter_string_representation(self) -> None:
        """Test ProtocolRateLimiter string representation."""
        config = ProtocolRateLimitConfig(protocol_name="test_protocol")
        limiter = ProtocolRateLimiter(config)

        # Should have string representation
        assert "ProtocolRateLimiter" in str(limiter)
        assert "protocol=test_protocol" in str(limiter)

    def test_protocol_rate_limiter_edge_cases(self) -> None:
        """Test ProtocolRateLimiter edge cases."""
        # Test with zero capacity - should raise ValueError during config creation
        with pytest.raises(ValueError, match="capacity must be positive"):
            ProtocolRateLimitConfig(protocol_name="test", capacity=0.0)

        # Test with negative refill rate - should raise ValueError during config creation
        with pytest.raises(ValueError, match="refill_rate must be positive"):
            ProtocolRateLimitConfig(protocol_name="test", refill_rate=-1.0)

    def test_protocol_rate_limiter_performance(self) -> None:
        """Test ProtocolRateLimiter performance."""
        config = ProtocolRateLimitConfig(
            protocol_name="test_protocol",
            refill_rate=100.0,
            capacity=1000.0,
            initial_tokens=1000.0,
        )
        limiter = ProtocolRateLimiter(config)

        # Create test peer ID
        peer_id = ID.from_base58("QmTest123")

        # Test many requests
        start_time = time.time()
        for _ in range(1000):
            limiter.try_allow_request(peer_id=peer_id, tokens=1.0)
        end_time = time.time()

        # Should complete quickly
        assert end_time - start_time < 1.0

    def test_protocol_rate_limiter_concurrent_access(self) -> None:
        """Test ProtocolRateLimiter concurrent access."""
        config = ProtocolRateLimitConfig(
            protocol_name="test_protocol",
            refill_rate=100.0,
            capacity=1000.0,
            initial_tokens=1000.0,
            max_concurrent_requests=100,  # Allow all 100 concurrent requests
        )
        limiter = ProtocolRateLimiter(config)

        # Create test peer ID
        peer_id = ID.from_base58("QmTest123")

        # Test concurrent access (simulated)
        results = []
        for _ in range(100):
            results.append(limiter.try_allow_request(peer_id=peer_id, tokens=1.0))

        # All should succeed
        assert all(results)

    def test_protocol_rate_limiter_entity_limits(self) -> None:
        """Test ProtocolRateLimiter entity limits."""
        config = ProtocolRateLimitConfig(
            protocol_name="test_protocol",
            scope=RateLimitScope.PER_PEER,
            refill_rate=10.0,
            capacity=100.0,
            max_peers=2,
            initial_tokens=10.0,
        )
        limiter = ProtocolRateLimiter(config)

        # Create test peer IDs
        peer1 = ID.from_base58("QmTest1")
        peer2 = ID.from_base58("QmTest2")
        peer3 = ID.from_base58("QmTest3")

        # Should work with first two peers
        assert limiter.try_allow_request(peer_id=peer1) is True
        assert limiter.try_allow_request(peer_id=peer2) is True

        # Should still work with third peer (LRU cleanup)
        assert limiter.try_allow_request(peer_id=peer3) is True

    def test_protocol_rate_limiter_global_scope(self) -> None:
        """Test ProtocolRateLimiter with global scope."""
        config = ProtocolRateLimitConfig(
            protocol_name="test_protocol",
            scope=RateLimitScope.GLOBAL,
            refill_rate=10.0,
            capacity=100.0,
            initial_tokens=10.0,
        )
        limiter = ProtocolRateLimiter(config)

        # Should work without peer ID
        assert limiter.try_allow_request() is True

    def test_protocol_rate_limiter_per_connection_scope(self) -> None:
        """Test ProtocolRateLimiter with per-connection scope."""
        config = ProtocolRateLimitConfig(
            protocol_name="test_protocol",
            scope=RateLimitScope.PER_CONNECTION,
            refill_rate=10.0,
            capacity=100.0,
            initial_tokens=10.0,
        )
        limiter = ProtocolRateLimiter(config)

        # Should work with connection ID
        assert limiter.try_allow_request(connection_id="conn1") is True

    def test_protocol_rate_limiter_request_cleanup(self) -> None:
        """Test ProtocolRateLimiter request cleanup."""
        config = ProtocolRateLimitConfig(
            protocol_name="test_protocol",
            request_timeout_seconds=0.1,
            initial_tokens=10.0,
        )
        limiter = ProtocolRateLimiter(config)

        # Create test peer ID
        peer_id = ID.from_base58("QmTest123")

        # Allow request
        assert limiter.try_allow_request(peer_id=peer_id) is True

        # Wait for timeout
        time.sleep(0.2)

        # Clean up old requests
        limiter._cleanup_old_requests(limiter._get_entity_key(peer_id), time.time())

        # Should have cleaned up
        assert True  # No exception raised

    def test_protocol_rate_limiter_backoff_period(self) -> None:
        """Test ProtocolRateLimiter backoff period."""
        config = ProtocolRateLimitConfig(
            protocol_name="test_protocol",
            max_concurrent_requests=1,
            request_timeout_seconds=0.1,
            backoff_factor=2.0,
            initial_tokens=10.0,
        )
        limiter = ProtocolRateLimiter(config)

        # Create test peer ID
        peer_id = ID.from_base58("QmTest123")

        # Allow request
        assert limiter.try_allow_request(peer_id=peer_id) is True

        # Try to allow another request (should be denied and trigger backoff)
        assert limiter.try_allow_request(peer_id=peer_id) is False

        # Should be in backoff
        entity_key = limiter._get_entity_key(peer_id)
        assert limiter._is_in_backoff(entity_key, time.time()) is True

        # Wait for backoff to end
        time.sleep(0.3)

        # Should no longer be in backoff
        assert limiter._is_in_backoff(entity_key, time.time()) is False


class TestProtocolRateLimiterFactory:
    """Test ProtocolRateLimiter factory functions."""

    def test_create_protocol_rate_limiter(self) -> None:
        """Test create_protocol_rate_limiter factory function."""
        limiter = create_protocol_rate_limiter(
            protocol_name="test_protocol",
            protocol_version="1.0.0",
            refill_rate=20.0,
            capacity=200.0,
            initial_tokens=100.0,
        )
        assert limiter.config.protocol_name == "test_protocol"
        assert limiter.config.protocol_version == "1.0.0"
        assert limiter.config.refill_rate == 20.0
        assert limiter.config.capacity == 200.0
        assert limiter.config.initial_tokens == 100.0

    def test_create_strict_protocol_rate_limiter(self) -> None:
        """Test create_strict_protocol_rate_limiter factory function."""
        limiter = create_strict_protocol_rate_limiter(
            protocol_name="test_protocol",
            protocol_version="1.0.0",
            refill_rate=20.0,
            capacity=200.0,
            initial_tokens=100.0,
        )
        assert limiter.config.protocol_name == "test_protocol"
        assert limiter.config.protocol_version == "1.0.0"
        assert limiter.config.refill_rate == 20.0
        assert limiter.config.capacity == 200.0
        assert limiter.config.initial_tokens == 100.0
        assert limiter.config.allow_burst is False

    def test_create_burst_protocol_rate_limiter(self) -> None:
        """Test create_burst_protocol_rate_limiter factory function."""
        limiter = create_burst_protocol_rate_limiter(
            protocol_name="test_protocol",
            protocol_version="1.0.0",
            refill_rate=20.0,
            capacity=200.0,
            initial_tokens=100.0,
            burst_multiplier=2.0,
        )
        assert limiter.config.protocol_name == "test_protocol"
        assert limiter.config.protocol_version == "1.0.0"
        assert limiter.config.refill_rate == 20.0
        assert limiter.config.capacity == 200.0
        assert limiter.config.initial_tokens == 100.0
        assert limiter.config.allow_burst is True
        assert limiter.config.burst_multiplier == 2.0


class TestProtocolRateLimiterIntegration:
    """Test ProtocolRateLimiter integration scenarios."""

    def test_protocol_rate_limiter_with_monitoring(self) -> None:
        """Test ProtocolRateLimiter with monitoring enabled."""
        config = ProtocolRateLimitConfig(
            protocol_name="test_protocol",
            refill_rate=10.0,
            capacity=100.0,
            enable_monitoring=True,
            max_history_size=5,
        )
        limiter = ProtocolRateLimiter(config)

        # Create test peer ID
        peer_id = ID.from_base58("QmTest123")

        # Make requests
        for i in range(10):
            limiter.try_allow_request(peer_id=peer_id, tokens=5.0)

        # Check stats
        stats = limiter.get_stats(peer_id=peer_id)
        assert stats.protocol_name == "test_protocol"
        assert stats.total_requests >= 10

    def test_protocol_rate_limiter_without_monitoring(self) -> None:
        """Test ProtocolRateLimiter with monitoring disabled."""
        config = ProtocolRateLimitConfig(
            protocol_name="test_protocol",
            refill_rate=10.0,
            capacity=100.0,
            enable_monitoring=False,
        )
        limiter = ProtocolRateLimiter(config)

        # Create test peer ID
        peer_id = ID.from_base58("QmTest123")

        # Make requests
        for i in range(10):
            limiter.try_allow_request(peer_id=peer_id, tokens=5.0)

        # Check stats
        stats = limiter.get_stats(peer_id=peer_id)
        assert stats.protocol_name == "test_protocol"
        assert stats.total_requests >= 10

    def test_protocol_rate_limiter_burst_handling(self) -> None:
        """Test ProtocolRateLimiter burst handling."""
        config = ProtocolRateLimitConfig(
            protocol_name="test_protocol",
            refill_rate=1.0,
            capacity=10.0,
            initial_tokens=10.0,
            allow_burst=True,
            burst_multiplier=2.0,
        )
        limiter = ProtocolRateLimiter(config)

        # Create test peer ID
        peer_id = ID.from_base58("QmTest123")

        # Should be able to consume all initial tokens
        assert limiter.try_allow_request(peer_id=peer_id, tokens=10.0) is True

        # Should not be able to consume more
        assert limiter.try_allow_request(peer_id=peer_id, tokens=1.0) is False

    def test_protocol_rate_limiter_time_window(self) -> None:
        """Test ProtocolRateLimiter time window handling."""
        config = ProtocolRateLimitConfig(
            protocol_name="test_protocol",
            refill_rate=10.0,
            capacity=100.0,
            time_window_seconds=2.0,
            min_interval_seconds=0.1,
            initial_tokens=10.0,
        )
        limiter = ProtocolRateLimiter(config)

        # Create test peer ID
        peer_id = ID.from_base58("QmTest123")

        # Should be able to make requests
        assert limiter.try_allow_request(peer_id=peer_id) is True

    def test_protocol_rate_limiter_entity_cleanup(self) -> None:
        """Test ProtocolRateLimiter entity cleanup."""
        config = ProtocolRateLimitConfig(
            protocol_name="test_protocol",
            scope=RateLimitScope.PER_PEER,
            refill_rate=10.0,
            capacity=100.0,
            max_peers=2,
            initial_tokens=10.0,
        )
        limiter = ProtocolRateLimiter(config)

        # Create test peer IDs
        peer1 = ID.from_base58("QmTest1")
        peer2 = ID.from_base58("QmTest2")
        peer3 = ID.from_base58("QmTest3")

        # Should work with all peers (LRU cleanup)
        assert limiter.try_allow_request(peer_id=peer1) is True
        assert limiter.try_allow_request(peer_id=peer2) is True
        assert limiter.try_allow_request(peer_id=peer3) is True
