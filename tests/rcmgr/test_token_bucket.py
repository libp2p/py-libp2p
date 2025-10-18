"""
Tests for TokenBucket rate limiting implementation.

This module contains comprehensive tests for the TokenBucket class,
including basic functionality, edge cases, performance, and concurrency.
"""

import time

import pytest

from libp2p.rcmgr.token_bucket import (
    TokenBucket,
    TokenBucketConfig,
    TokenBucketStats,
    create_burst_token_bucket,
    create_strict_token_bucket,
    create_token_bucket,
)


class TestTokenBucketConfig:
    """Test TokenBucketConfig dataclass."""

    def test_token_bucket_config_creation(self) -> None:
        """Test TokenBucketConfig creation with required parameters."""
        config = TokenBucketConfig(refill_rate=10.0, capacity=100.0)
        assert config.refill_rate == 10.0
        assert config.capacity == 100.0
        assert config.initial_tokens == 0.0

    def test_token_bucket_config_custom_values(self) -> None:
        """Test TokenBucketConfig creation with custom values."""
        config = TokenBucketConfig(
            refill_rate=5.0,
            capacity=100.0,
            initial_tokens=50.0
        )
        assert config.refill_rate == 5.0
        assert config.capacity == 100.0
        assert config.initial_tokens == 50.0

    def test_token_bucket_config_validation(self) -> None:
        """Test TokenBucketConfig validation."""
        # Test negative refill rate
        with pytest.raises(ValueError, match="refill_rate must be positive"):
            TokenBucketConfig(refill_rate=-1.0, capacity=100.0)

        # Test negative capacity
        with pytest.raises(ValueError, match="capacity must be positive"):
            TokenBucketConfig(refill_rate=10.0, capacity=-1.0)

        # Test negative initial tokens
        with pytest.raises(ValueError, match="initial_tokens must be non-negative"):
            TokenBucketConfig(refill_rate=10.0, capacity=100.0, initial_tokens=-1.0)

        # Test initial tokens exceeding capacity
        with pytest.raises(ValueError, match="initial_tokens cannot exceed capacity"):
            TokenBucketConfig(refill_rate=10.0, capacity=100.0, initial_tokens=150.0)

    def test_token_bucket_config_defaults(self) -> None:
        """Test TokenBucketConfig default values."""
        config = TokenBucketConfig(refill_rate=10.0, capacity=100.0)
        assert config.allow_burst is True
        assert config.burst_multiplier == 1.0
        assert config.time_window_seconds == 1.0
        assert config.min_interval_seconds == 0.001
        assert config.enable_monitoring is True
        assert config.max_history_size == 1000

    def test_token_bucket_config_equality(self) -> None:
        """Test TokenBucketConfig equality."""
        config1 = TokenBucketConfig(refill_rate=10.0, capacity=100.0)
        config2 = TokenBucketConfig(refill_rate=10.0, capacity=100.0)
        config3 = TokenBucketConfig(refill_rate=5.0, capacity=100.0)

        assert config1 == config2
        assert config1 != config3

    def test_token_bucket_config_string_representation(self) -> None:
        """Test TokenBucketConfig string representation."""
        config = TokenBucketConfig(refill_rate=10.0, capacity=100.0)
        config_str = str(config)
        assert "TokenBucketConfig" in config_str
        assert "refill_rate=10.0" in config_str
        assert "capacity=100.0" in config_str


class TestTokenBucketStats:
    """Test TokenBucketStats dataclass."""

    def test_token_bucket_stats_creation(self) -> None:
        """Test TokenBucketStats creation."""
        stats = TokenBucketStats(
            current_tokens=50.0,
            last_refill_time=time.time(),
            total_requests=110,
            allowed_requests=100,
            denied_requests=10,
            refill_rate=10.0,
            capacity=100.0,
            effective_rate=0.9,
            burst_used=50.0,
            burst_available=50.0,
            time_since_last_refill=0.0,
            next_refill_time=time.time() + 1.0,
        )
        assert stats.current_tokens == 50.0
        assert stats.last_refill_time > 0
        assert stats.allowed_requests == 100
        assert stats.denied_requests == 10

    def test_token_bucket_stats_to_dict(self) -> None:
        """Test TokenBucketStats to_dict method."""
        stats = TokenBucketStats(
            current_tokens=50.0,
            last_refill_time=time.time(),
            total_requests=110,
            allowed_requests=100,
            denied_requests=10,
            refill_rate=10.0,
            capacity=100.0,
            effective_rate=0.9,
            burst_used=50.0,
            burst_available=50.0,
            time_since_last_refill=0.0,
            next_refill_time=time.time() + 1.0,
        )
        stats_dict = stats.to_dict()
        assert isinstance(stats_dict, dict)
        assert "current_tokens" in stats_dict
        assert "last_refill_time" in stats_dict
        assert "allowed_requests" in stats_dict
        assert "denied_requests" in stats_dict


class TestTokenBucket:
    """Test TokenBucket class."""

    def test_token_bucket_creation(self) -> None:
        """Test TokenBucket creation."""
        config = TokenBucketConfig(refill_rate=10.0, capacity=100.0)
        bucket = TokenBucket(config)
        assert bucket.config == config
        assert bucket._tokens == 0.0
        assert bucket.config.capacity == 100.0
        assert bucket.config.refill_rate == 10.0
        assert bucket._total_requests == 0
        assert bucket._denied_requests == 0

    def test_token_bucket_initial_tokens(self) -> None:
        """Test TokenBucket with initial tokens."""
        config = TokenBucketConfig(
            refill_rate=10.0, capacity=100.0, initial_tokens=50.0
        )
        bucket = TokenBucket(config)
        assert bucket._tokens == 50.0

    def test_token_bucket_refill_tokens(self) -> None:
        """Test TokenBucket refill logic."""
        config = TokenBucketConfig(refill_rate=10.0, capacity=100.0)
        bucket = TokenBucket(config)

        # Test refill with time elapsed
        current_time = time.time() + 1.0  # 1 second later
        bucket._refill_tokens(current_time)

        # Should have refilled tokens
        assert bucket._tokens > 0
        assert bucket._tokens <= config.capacity

    def test_token_bucket_try_consume(self) -> None:
        """Test TokenBucket try_consume method."""
        config = TokenBucketConfig(
            refill_rate=10.0, capacity=100.0, initial_tokens=50.0
        )
        bucket = TokenBucket(config)

        # Should be able to consume tokens
        assert bucket.try_consume(10.0) is True
        assert bucket._tokens == 40.0
        assert bucket._total_requests == 1

        # Should not be able to consume more than available
        assert bucket.try_consume(50.0) is False
        assert bucket._tokens == 40.0
        assert bucket._denied_requests == 1

    def test_token_bucket_consume(self) -> None:
        """Test TokenBucket consume method (raises exception)."""
        config = TokenBucketConfig(
            refill_rate=10.0, capacity=100.0, initial_tokens=10.0
        )
        bucket = TokenBucket(config)

        # Should be able to consume tokens
        bucket.consume(5.0)
        assert bucket._tokens == 5.0

        # Should raise exception if not enough tokens
        with pytest.raises(ValueError):
            bucket.consume(10.0)

    def test_token_bucket_get_stats(self) -> None:
        """Test TokenBucket statistics."""
        config = TokenBucketConfig(
            refill_rate=10.0, capacity=100.0, initial_tokens=50.0
        )
        bucket = TokenBucket(config)

        # Consume some tokens
        bucket.try_consume(10.0)
        bucket.try_consume(20.0)

        stats = bucket.get_stats()
        assert stats.current_tokens == 20.0
        assert stats.last_refill_time > 0
        assert stats.allowed_requests == 2
        assert stats.denied_requests == 0

    def test_token_bucket_get_history(self) -> None:
        """Test TokenBucket history."""
        config = TokenBucketConfig(
            refill_rate=10.0, capacity=100.0, enable_monitoring=True
        )
        bucket = TokenBucket(config)

        # Make some requests
        bucket.try_consume(10.0)
        bucket.try_consume(20.0)

        history = bucket.get_history()
        assert history["enabled"] is True
        assert history["total_requests"] == 2
        assert len(history["recent_requests"]) == 2

    def test_token_bucket_reset(self) -> None:
        """Test TokenBucket reset."""
        config = TokenBucketConfig(
            refill_rate=10.0, capacity=100.0, initial_tokens=50.0
        )
        bucket = TokenBucket(config)

        # Consume some tokens
        bucket.try_consume(10.0)
        bucket.try_consume(20.0)

        # Reset
        bucket.reset()

        # Should be back to initial state
        assert bucket._tokens == 50.0
        assert bucket._total_requests == 0
        assert bucket._denied_requests == 0

    def test_token_bucket_string_representation(self) -> None:
        """Test TokenBucket string representation."""
        config = TokenBucketConfig(
            refill_rate=10.0, capacity=100.0, initial_tokens=50.0
        )
        bucket = TokenBucket(config)

        # Should have string representation
        assert "TokenBucket" in str(bucket)
        assert "tokens" in str(bucket)
        assert "rate" in str(bucket)

    def test_token_bucket_edge_cases(self) -> None:
        """Test TokenBucket edge cases."""
        # Test with zero capacity
        config = TokenBucketConfig(refill_rate=10.0, capacity=0.0)
        with pytest.raises(ValueError):
            TokenBucket(config)

        # Test with negative refill rate
        config = TokenBucketConfig(refill_rate=-1.0, capacity=100.0)
        with pytest.raises(ValueError):
            TokenBucket(config)

    def test_token_bucket_performance(self) -> None:
        """Test TokenBucket performance."""
        config = TokenBucketConfig(
            refill_rate=10.0, capacity=1000.0, initial_tokens=1000.0
        )
        bucket = TokenBucket(config)

        # Test many requests
        start_time = time.time()
        for _ in range(1000):
            bucket.try_consume(1.0)
        end_time = time.time()

        # Should complete quickly
        assert end_time - start_time < 1.0

    def test_token_bucket_concurrent_access(self) -> None:
        """Test TokenBucket concurrent access."""
        config = TokenBucketConfig(
            refill_rate=10.0, capacity=1000.0, initial_tokens=1000.0
        )
        bucket = TokenBucket(config)

        # Test concurrent access (simulated)
        results = []
        for _ in range(100):
            results.append(bucket.try_consume(1.0))

        # All should succeed
        assert all(results)

    def test_token_bucket_history_cleanup(self) -> None:
        """Test TokenBucket history cleanup."""
        config = TokenBucketConfig(
            refill_rate=10.0,
            capacity=100.0,
            enable_monitoring=True,
            max_history_size=10,
        )
        bucket = TokenBucket(config)

        # Make many requests
        for _ in range(20):
            bucket.try_consume(1.0)

        # History should be limited
        history = bucket.get_history()
        assert len(history["recent_requests"]) <= 10

    def test_token_bucket_stats_serialization(self) -> None:
        """Test TokenBucket statistics serialization."""
        config = TokenBucketConfig(
            refill_rate=10.0, capacity=100.0, initial_tokens=50.0
        )
        bucket = TokenBucket(config)

        # Consume some tokens
        bucket.try_consume(10.0)

        stats = bucket.get_stats()
        stats_dict = stats.to_dict()

        # Should be serializable
        assert isinstance(stats_dict, dict)
        assert "current_tokens" in stats_dict
        assert "last_refill_time" in stats_dict
        assert "allowed_requests" in stats_dict
        assert "denied_requests" in stats_dict


class TestTokenBucketFactory:
    """Test TokenBucket factory functions."""

    def test_create_token_bucket(self) -> None:
        """Test create_token_bucket factory function."""
        bucket = create_token_bucket(
            refill_rate=20.0,
            capacity=200.0,
            initial_tokens=100.0,
        )
        assert bucket.config.refill_rate == 20.0
        assert bucket.config.capacity == 200.0
        assert bucket.config.initial_tokens == 100.0

    def test_create_strict_token_bucket(self) -> None:
        """Test create_strict_token_bucket factory function."""
        bucket = create_strict_token_bucket(
            refill_rate=20.0,
            capacity=200.0,
            initial_tokens=100.0,
        )
        assert bucket.config.refill_rate == 20.0
        assert bucket.config.capacity == 200.0
        assert bucket.config.initial_tokens == 100.0
        assert bucket.config.allow_burst is False

    def test_create_burst_token_bucket(self) -> None:
        """Test create_burst_token_bucket factory function."""
        bucket = create_burst_token_bucket(
            refill_rate=20.0,
            capacity=200.0,
            initial_tokens=100.0,
            burst_multiplier=2.0,
        )
        assert bucket.config.refill_rate == 20.0
        assert bucket.config.capacity == 200.0
        assert bucket.config.initial_tokens == 100.0
        assert bucket.config.allow_burst is True
        assert bucket.config.burst_multiplier == 2.0


class TestTokenBucketIntegration:
    """Test TokenBucket integration scenarios."""

    def test_token_bucket_with_monitoring(self) -> None:
        """Test TokenBucket with monitoring enabled."""
        config = TokenBucketConfig(
            refill_rate=10.0,
            capacity=100.0,
            enable_monitoring=True,
            max_history_size=5
        )
        bucket = TokenBucket(config)

        # Make requests
        for i in range(10):
            bucket.try_consume(5.0)

        # Check history
        history = bucket.get_history()
        assert history["enabled"] is True
        assert history["total_requests"] == 10

    def test_token_bucket_without_monitoring(self) -> None:
        """Test TokenBucket with monitoring disabled."""
        config = TokenBucketConfig(
            refill_rate=10.0,
            capacity=100.0,
            enable_monitoring=False
        )
        bucket = TokenBucket(config)

        # Make requests
        for i in range(10):
            bucket.try_consume(5.0)

        # Check history
        history = bucket.get_history()
        assert history["enabled"] is False

    def test_token_bucket_burst_handling(self) -> None:
        """Test TokenBucket burst handling."""
        config = TokenBucketConfig(
            refill_rate=1.0,
            capacity=10.0,
            initial_tokens=10.0,
            allow_burst=True,
            burst_multiplier=2.0
        )
        bucket = TokenBucket(config)

        # Should be able to consume all initial tokens
        assert bucket.try_consume(10.0) is True
        assert bucket._tokens == 0.0

        # Should not be able to consume more
        assert bucket.try_consume(1.0) is False

    def test_token_bucket_time_window(self) -> None:
        """Test TokenBucket time window handling."""
        config = TokenBucketConfig(
            refill_rate=10.0,
            capacity=100.0,
            time_window_seconds=2.0,
            min_interval_seconds=0.1
        )
        bucket = TokenBucket(config)

        # Wait for refill
        time.sleep(0.2)
        bucket._refill_tokens(time.time())

        # Should have some tokens
        assert bucket._tokens > 0

    def test_token_bucket_cleanup_history(self) -> None:
        """Test TokenBucket history cleanup."""
        config = TokenBucketConfig(
            refill_rate=10.0,
            capacity=100.0,
            enable_monitoring=True,
            time_window_seconds=0.1,
            max_history_size=3
        )
        bucket = TokenBucket(config)

        # Make requests
        for i in range(5):
            bucket.try_consume(1.0)

        # Wait for cleanup
        time.sleep(0.2)

        # Check history
        history = bucket.get_history()
        assert len(history["recent_requests"]) <= 3
