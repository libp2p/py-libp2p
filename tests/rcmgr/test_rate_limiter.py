"""
Tests for RateLimiter implementation.

This module contains comprehensive tests for the RateLimiter class,
including different strategies, scopes, and edge cases.
"""

import time

import pytest

from libp2p.peer.id import ID
from libp2p.rcmgr.rate_limiter import (
    RateLimitConfig,
    RateLimiter,
    RateLimitScope,
    RateLimitStats,
    RateLimitStrategy,
    create_adaptive_rate_limiter,
    create_global_rate_limiter,
    create_per_peer_rate_limiter,
    create_rate_limiter,
)


class TestRateLimitConfig:
    """Test RateLimitConfig dataclass."""

    def test_rate_limit_config_creation(self) -> None:
        """Test RateLimitConfig creation with default values."""
        config = RateLimitConfig()
        assert config.strategy == RateLimitStrategy.TOKEN_BUCKET
        assert config.scope == RateLimitScope.GLOBAL
        assert config.refill_rate == 10.0
        assert config.capacity == 100.0

    def test_rate_limit_config_custom_values(self) -> None:
        """Test RateLimitConfig creation with custom values."""
        config = RateLimitConfig(
            strategy=RateLimitStrategy.FIXED_WINDOW,
            scope=RateLimitScope.PER_PEER,
            refill_rate=20.0,
            capacity=200.0
        )
        assert config.strategy == RateLimitStrategy.FIXED_WINDOW
        assert config.scope == RateLimitScope.PER_PEER
        assert config.refill_rate == 20.0
        assert config.capacity == 200.0

    def test_rate_limit_config_validation(self) -> None:
        """Test RateLimitConfig validation."""
        # Test negative refill rate
        with pytest.raises(ValueError, match="refill_rate must be positive"):
            RateLimitConfig(refill_rate=-1.0)

        # Test negative capacity
        with pytest.raises(ValueError, match="capacity must be positive"):
            RateLimitConfig(capacity=-1.0)

        # Test invalid window size
        with pytest.raises(ValueError, match="window_size_seconds must be positive"):
            RateLimitConfig(window_size_seconds=-1.0)

    def test_rate_limit_config_equality(self) -> None:
        """Test RateLimitConfig equality."""
        config1 = RateLimitConfig(refill_rate=10.0, capacity=100.0)
        config2 = RateLimitConfig(refill_rate=10.0, capacity=100.0)
        config3 = RateLimitConfig(refill_rate=5.0, capacity=100.0)

        assert config1 == config2
        assert config1 != config3


class TestRateLimitStats:
    """Test RateLimitStats dataclass."""

    def test_rate_limit_stats_creation(self) -> None:
        """Test RateLimitStats creation."""
        stats = RateLimitStats(
            current_rate=5.0,
            allowed_requests=100,
            denied_requests=10,
            total_requests=110,
            configured_rate=10.0,
            effective_rate=0.9,
            burst_available=50.0,
            scope=RateLimitScope.GLOBAL,
            tracked_entities=1,
            time_since_last_request=0.0,
            next_available_time=time.time() + 1.0,
        )
        assert stats.current_rate == 5.0
        assert stats.allowed_requests == 100
        assert stats.denied_requests == 10

    def test_rate_limit_stats_to_dict(self) -> None:
        """Test RateLimitStats to_dict method."""
        stats = RateLimitStats(
            current_rate=5.0,
            allowed_requests=100,
            denied_requests=10,
            total_requests=110,
            configured_rate=10.0,
            effective_rate=0.9,
            burst_available=50.0,
            scope=RateLimitScope.GLOBAL,
            tracked_entities=1,
            time_since_last_request=0.0,
            next_available_time=time.time() + 1.0,
        )
        stats_dict = stats.to_dict()
        assert isinstance(stats_dict, dict)
        assert "current_rate" in stats_dict
        assert "allowed_requests" in stats_dict
        assert "denied_requests" in stats_dict


class TestRateLimiter:
    """Test RateLimiter class."""

    def test_rate_limiter_creation(self) -> None:
        """Test RateLimiter creation."""
        config = RateLimitConfig(refill_rate=10.0, capacity=100.0)
        limiter = RateLimiter(config)
        assert limiter.config == config
        assert limiter._total_requests == 0
        assert limiter._allowed_requests == 0
        assert limiter._denied_requests == 0

    def test_rate_limiter_token_bucket_strategy(self) -> None:
        """Test RateLimiter with token bucket strategy."""
        config = RateLimitConfig(
            strategy=RateLimitStrategy.TOKEN_BUCKET,
            refill_rate=10.0,
            capacity=100.0,
            initial_tokens=50.0
        )
        limiter = RateLimiter(config)

        # Should be able to consume tokens
        assert limiter.try_allow(tokens=10.0) is True
        assert limiter._allowed_requests == 1

        # Should not be able to consume more than available
        assert limiter.try_allow(tokens=100.0) is False
        assert limiter._denied_requests == 1

    def test_rate_limiter_fixed_window_strategy(self) -> None:
        """Test RateLimiter with fixed window strategy."""
        config = RateLimitConfig(
            strategy=RateLimitStrategy.FIXED_WINDOW,
            window_size_seconds=60.0,
            max_requests_per_window=5
        )
        limiter = RateLimiter(config)

        # Should be able to make requests within limit
        for i in range(5):
            assert limiter.try_allow() is True

        # Should be denied after limit
        assert limiter.try_allow() is False

    def test_rate_limiter_sliding_window_strategy(self) -> None:
        """Test RateLimiter with sliding window strategy."""
        config = RateLimitConfig(
            strategy=RateLimitStrategy.SLIDING_WINDOW,
            window_size_seconds=60.0,
            max_requests_per_window=5
        )
        limiter = RateLimiter(config)

        # Should be able to make requests within limit
        for i in range(5):
            assert limiter.try_allow() is True

        # Should be denied after limit
        assert limiter.try_allow() is False

    def test_rate_limiter_adaptive_strategy(self) -> None:
        """Test RateLimiter with adaptive strategy."""
        config = RateLimitConfig(
            strategy=RateLimitStrategy.ADAPTIVE,
            base_rate=10.0,
            max_rate=100.0,
            min_rate=1.0,
            adaptation_factor=0.1,
            initial_tokens=10.0
        )
        limiter = RateLimiter(config)

        # Should start with base rate
        assert limiter._current_rate == 10.0

        # Should be able to make requests
        assert limiter.try_allow() is True

    def test_rate_limiter_global_scope(self) -> None:
        """Test RateLimiter with global scope."""
        config = RateLimitConfig(
            scope=RateLimitScope.GLOBAL,
            refill_rate=10.0,
            capacity=100.0,
            initial_tokens=10.0
        )
        limiter = RateLimiter(config)

        # Should work without peer ID
        assert limiter.try_allow() is True

    def test_rate_limiter_per_peer_scope(self) -> None:
        """Test RateLimiter with per-peer scope."""
        config = RateLimitConfig(
            scope=RateLimitScope.PER_PEER,
            refill_rate=10.0,
            capacity=100.0,
            initial_tokens=10.0
        )
        limiter = RateLimiter(config)

        # Create test peer ID
        peer_id = ID.from_base58("QmTest123")

        # Should work with peer ID
        assert limiter.try_allow(peer_id=peer_id) is True

    def test_rate_limiter_per_connection_scope(self) -> None:
        """Test RateLimiter with per-connection scope."""
        config = RateLimitConfig(
            scope=RateLimitScope.PER_CONNECTION,
            refill_rate=10.0,
            capacity=100.0,
            initial_tokens=10.0
        )
        limiter = RateLimiter(config)

        # Should work with connection ID
        assert limiter.try_allow(connection_id="conn1") is True

    def test_rate_limiter_per_protocol_scope(self) -> None:
        """Test RateLimiter with per-protocol scope."""
        config = RateLimitConfig(
            scope=RateLimitScope.PER_PROTOCOL,
            refill_rate=10.0,
            capacity=100.0,
            initial_tokens=10.0
        )
        limiter = RateLimiter(config)

        # Should work with protocol
        assert limiter.try_allow(protocol="test_protocol") is True

    def test_rate_limiter_per_endpoint_scope(self) -> None:
        """Test RateLimiter with per-endpoint scope."""
        config = RateLimitConfig(
            scope=RateLimitScope.PER_ENDPOINT,
            refill_rate=10.0,
            capacity=100.0,
            initial_tokens=10.0
        )
        limiter = RateLimiter(config)

        # Should work with endpoint
        assert limiter.try_allow(endpoint="127.0.0.1:8080") is True

    def test_rate_limiter_allow_method(self) -> None:
        """Test RateLimiter allow method (raises exception)."""
        config = RateLimitConfig(
            refill_rate=1.0,
            capacity=1.0,
            initial_tokens=1.0
        )
        limiter = RateLimiter(config)

        # Should be able to consume token
        limiter.allow(tokens=1.0)
        assert limiter._allowed_requests == 1

        # Should raise exception if not enough tokens
        with pytest.raises(ValueError):
            limiter.allow(tokens=1.0)

    def test_rate_limiter_get_stats(self) -> None:
        """Test RateLimiter statistics."""
        config = RateLimitConfig(refill_rate=10.0, capacity=100.0, initial_tokens=50.0)
        limiter = RateLimiter(config)

        # Make some requests
        limiter.try_allow(tokens=10.0)
        limiter.try_allow(tokens=20.0)

        stats = limiter.get_stats()
        assert stats.total_requests == 2
        assert stats.allowed_requests == 2
        assert stats.denied_requests == 0

    def test_rate_limiter_get_entity_stats(self) -> None:
        """Test RateLimiter entity-specific statistics."""
        config = RateLimitConfig(
            scope=RateLimitScope.PER_PEER,
            refill_rate=10.0,
            capacity=100.0
        )
        limiter = RateLimiter(config)

        # Create test peer ID
        peer_id = ID.from_base58("QmTest123")

        # Make some requests
        limiter.try_allow(peer_id=peer_id, tokens=10.0)

        # Get entity stats
        entity_stats = limiter.get_entity_stats(peer_id=peer_id)
        assert isinstance(entity_stats, dict)

    def test_rate_limiter_reset(self) -> None:
        """Test RateLimiter reset."""
        config = RateLimitConfig(refill_rate=10.0, capacity=100.0)
        limiter = RateLimiter(config)

        # Make some requests
        limiter.try_allow(tokens=10.0)
        limiter.try_allow(tokens=20.0)

        # Reset
        limiter.reset()

        # Should be back to initial state
        assert limiter._total_requests == 0
        assert limiter._allowed_requests == 0
        assert limiter._denied_requests == 0

    def test_rate_limiter_string_representation(self) -> None:
        """Test RateLimiter string representation."""
        config = RateLimitConfig(refill_rate=10.0, capacity=100.0)
        limiter = RateLimiter(config)

        # Should have string representation
        assert "RateLimiter" in str(limiter)
        assert "strategy" in str(limiter)
        assert "scope" in str(limiter)

    def test_rate_limiter_edge_cases(self) -> None:
        """Test RateLimiter edge cases."""
        # Test with zero capacity - should raise ValueError during config creation
        with pytest.raises(ValueError, match="capacity must be positive"):
            RateLimitConfig(refill_rate=10.0, capacity=0.0)

        # Test with negative refill rate - should raise ValueError during config creation
        with pytest.raises(ValueError, match="refill_rate must be positive"):
            RateLimitConfig(refill_rate=-1.0, capacity=100.0)

    def test_rate_limiter_performance(self) -> None:
        """Test RateLimiter performance."""
        config = RateLimitConfig(
            refill_rate=100.0, capacity=1000.0, initial_tokens=1000.0
        )
        limiter = RateLimiter(config)

        # Test many requests
        start_time = time.time()
        for _ in range(1000):
            limiter.try_allow(tokens=1.0)
        end_time = time.time()

        # Should complete quickly
        assert end_time - start_time < 1.0

    def test_rate_limiter_concurrent_access(self) -> None:
        """Test RateLimiter concurrent access."""
        config = RateLimitConfig(
            refill_rate=100.0, capacity=1000.0, initial_tokens=1000.0
        )
        limiter = RateLimiter(config)

        # Test concurrent access (simulated)
        results = []
        for _ in range(100):
            results.append(limiter.try_allow(tokens=1.0))

        # All should succeed
        assert all(results)

    def test_rate_limiter_entity_limits(self) -> None:
        """Test RateLimiter entity limits."""
        config = RateLimitConfig(
            scope=RateLimitScope.PER_PEER,
            refill_rate=10.0,
            capacity=100.0,
            max_peers=2,
            initial_tokens=10.0
        )
        limiter = RateLimiter(config)

        # Create test peer IDs
        peer1 = ID.from_base58("QmTest1")
        peer2 = ID.from_base58("QmTest2")
        peer3 = ID.from_base58("QmTest3")

        # Should work with first two peers
        assert limiter.try_allow(peer_id=peer1) is True
        assert limiter.try_allow(peer_id=peer2) is True

        # Should still work with third peer (LRU cleanup)
        assert limiter.try_allow(peer_id=peer3) is True

    def test_rate_limiter_adaptive_rate_update(self) -> None:
        """Test RateLimiter adaptive rate update."""
        config = RateLimitConfig(
            strategy=RateLimitStrategy.ADAPTIVE,
            base_rate=10.0,
            max_rate=100.0,
            min_rate=1.0,
            adaptation_factor=0.1,
            initial_tokens=10.0,
            min_interval_seconds=0.0001  # Very small interval for immediate adaptation
        )
        limiter = RateLimiter(config)

        # Start with base rate
        assert limiter._current_rate == 10.0

        # Make multiple requests to trigger adaptation
        for _ in range(5):
            limiter.try_allow()
            time.sleep(0.001)  # Small delay between requests

        # Rate should have increased after multiple successful requests
        assert limiter._current_rate > 10.0

    def test_rate_limiter_window_cleanup(self) -> None:
        """Test RateLimiter window cleanup."""
        config = RateLimitConfig(
            strategy=RateLimitStrategy.FIXED_WINDOW,
            window_size_seconds=0.1,
            max_requests_per_window=5
        )
        limiter = RateLimiter(config)

        # Make requests
        for i in range(5):
            assert limiter.try_allow() is True

        # Should be denied
        assert limiter.try_allow() is False

        # Wait for window to reset
        time.sleep(0.2)

        # Should be able to make requests again
        assert limiter.try_allow() is True


class TestRateLimiterFactory:
    """Test RateLimiter factory functions."""

    def test_create_rate_limiter(self) -> None:
        """Test create_rate_limiter factory function."""
        limiter = create_rate_limiter(
            strategy=RateLimitStrategy.TOKEN_BUCKET,
            scope=RateLimitScope.GLOBAL,
            refill_rate=20.0,
            capacity=200.0
        )
        assert limiter.config.strategy == RateLimitStrategy.TOKEN_BUCKET
        assert limiter.config.scope == RateLimitScope.GLOBAL
        assert limiter.config.refill_rate == 20.0
        assert limiter.config.capacity == 200.0

    def test_create_global_rate_limiter(self) -> None:
        """Test create_global_rate_limiter factory function."""
        limiter = create_global_rate_limiter(
            refill_rate=20.0,
            capacity=200.0,
            initial_tokens=100.0
        )
        assert limiter.config.scope == RateLimitScope.GLOBAL
        assert limiter.config.strategy == RateLimitStrategy.TOKEN_BUCKET
        assert limiter.config.refill_rate == 20.0
        assert limiter.config.capacity == 200.0

    def test_create_per_peer_rate_limiter(self) -> None:
        """Test create_per_peer_rate_limiter factory function."""
        limiter = create_per_peer_rate_limiter(
            refill_rate=20.0,
            capacity=200.0,
            initial_tokens=100.0,
            max_peers=500
        )
        assert limiter.config.scope == RateLimitScope.PER_PEER
        assert limiter.config.strategy == RateLimitStrategy.TOKEN_BUCKET
        assert limiter.config.refill_rate == 20.0
        assert limiter.config.capacity == 200.0
        assert limiter.config.max_peers == 500

    def test_create_adaptive_rate_limiter(self) -> None:
        """Test create_adaptive_rate_limiter factory function."""
        limiter = create_adaptive_rate_limiter(
            base_rate=10.0,
            max_rate=100.0,
            min_rate=1.0,
            adaptation_factor=0.1,
            scope=RateLimitScope.GLOBAL
        )
        assert limiter.config.strategy == RateLimitStrategy.ADAPTIVE
        assert limiter.config.scope == RateLimitScope.GLOBAL
        assert limiter.config.base_rate == 10.0
        assert limiter.config.max_rate == 100.0
        assert limiter.config.min_rate == 1.0
        assert limiter.config.adaptation_factor == 0.1


class TestRateLimiterIntegration:
    """Test RateLimiter integration scenarios."""

    def test_rate_limiter_with_monitoring(self) -> None:
        """Test RateLimiter with monitoring enabled."""
        config = RateLimitConfig(
            refill_rate=10.0,
            capacity=100.0,
            enable_monitoring=True,
            max_history_size=5
        )
        limiter = RateLimiter(config)

        # Make requests
        for i in range(10):
            limiter.try_allow(tokens=5.0)

        # Check stats
        stats = limiter.get_stats()
        assert stats.total_requests == 10

    def test_rate_limiter_without_monitoring(self) -> None:
        """Test RateLimiter with monitoring disabled."""
        config = RateLimitConfig(
            refill_rate=10.0,
            capacity=100.0,
            enable_monitoring=False
        )
        limiter = RateLimiter(config)

        # Make requests
        for i in range(10):
            limiter.try_allow(tokens=5.0)

        # Check stats
        stats = limiter.get_stats()
        assert stats.total_requests == 10

    def test_rate_limiter_burst_handling(self) -> None:
        """Test RateLimiter burst handling."""
        config = RateLimitConfig(
            refill_rate=1.0,
            capacity=10.0,
            initial_tokens=10.0,
            allow_burst=True,
            burst_multiplier=2.0
        )
        limiter = RateLimiter(config)

        # Should be able to consume all initial tokens
        assert limiter.try_allow(tokens=10.0) is True

        # Should not be able to consume more
        assert limiter.try_allow(tokens=1.0) is False

    def test_rate_limiter_time_window(self) -> None:
        """Test RateLimiter time window handling."""
        config = RateLimitConfig(
            refill_rate=10.0,
            capacity=100.0,
            time_window_seconds=2.0,
            min_interval_seconds=0.1,
            initial_tokens=10.0
        )
        limiter = RateLimiter(config)

        # Should be able to make requests
        assert limiter.try_allow() is True

    def test_rate_limiter_entity_cleanup(self) -> None:
        """Test RateLimiter entity cleanup."""
        config = RateLimitConfig(
            scope=RateLimitScope.PER_PEER,
            refill_rate=10.0,
            capacity=100.0,
            max_peers=2,
            initial_tokens=10.0
        )
        limiter = RateLimiter(config)

        # Create test peer IDs
        peer1 = ID.from_base58("QmTest1")
        peer2 = ID.from_base58("QmTest2")
        peer3 = ID.from_base58("QmTest3")

        # Should work with all peers (LRU cleanup)
        assert limiter.try_allow(peer_id=peer1) is True
        assert limiter.try_allow(peer_id=peer2) is True
        assert limiter.try_allow(peer_id=peer3) is True
