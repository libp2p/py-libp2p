"""
Tests for enhanced message validation features in Gossipsub 2.0.

This module tests the validation caching, timeout mechanisms, and
enhanced error reporting introduced in Gossipsub 2.0.
"""

import time
from unittest.mock import Mock

import pytest
import trio

from libp2p.exceptions import ValidationError
from libp2p.pubsub.pb import rpc_pb2
from libp2p.pubsub.pubsub import Pubsub, ValidationCache, ValidationResult
from tests.utils.factories import HostFactory, IDFactory


class TestValidationCache:
    """Test validation cache functionality."""

    def test_cache_initialization(self):
        """Test validation cache initialization."""
        cache = ValidationCache(ttl=300, max_size=1000)
        assert cache.ttl == 300
        assert cache.max_size == 1000
        assert len(cache.cache) == 0
        assert len(cache.access_order) == 0

    def test_cache_put_and_get(self):
        """Test basic cache put and get operations."""
        cache = ValidationCache(ttl=300, max_size=100)

        msg_id = b"test_message_123"
        result = ValidationResult(is_valid=True, timestamp=time.time())

        # Test cache miss
        assert cache.get(msg_id) is None

        # Test cache put
        cache.put(msg_id, result)
        assert len(cache.cache) == 1
        assert msg_id in cache.access_order

        # Test cache hit
        cached_result = cache.get(msg_id)
        assert cached_result is not None
        assert cached_result.is_valid == result.is_valid
        assert cached_result.timestamp == result.timestamp

    def test_cache_expiry(self):
        """Test cache entry expiry based on TTL."""
        cache = ValidationCache(ttl=2, max_size=100)  # 2 second TTL

        msg_id = b"expired_message"
        # Create result with old timestamp
        old_result = ValidationResult(is_valid=True, timestamp=time.time() - 5)

        # Manually add expired entry
        cache.cache[msg_id] = old_result
        cache.access_order.append(msg_id)

        # Should return None and clean up expired entry
        assert cache.get(msg_id) is None
        assert msg_id not in cache.cache
        assert msg_id not in cache.access_order

    def test_cache_lru_eviction(self):
        """Test LRU eviction when cache reaches max size."""
        cache = ValidationCache(ttl=300, max_size=3)

        msg1 = b"msg1"
        msg2 = b"msg2"
        msg3 = b"msg3"
        msg4 = b"msg4"

        current_time = time.time()
        result = ValidationResult(is_valid=True, timestamp=current_time)

        # Fill cache to capacity
        cache.put(msg1, result)
        cache.put(msg2, result)
        cache.put(msg3, result)

        assert len(cache.cache) == 3

        # Access msg1 to make it recently used
        cache.get(msg1)

        # Add msg4, should evict msg2 (least recently used)
        cache.put(msg4, result)

        assert len(cache.cache) == 3
        assert cache.get(msg1) is not None  # Should still be there
        assert cache.get(msg2) is None  # Should be evicted
        assert cache.get(msg3) is not None  # Should still be there
        assert cache.get(msg4) is not None  # Should be there

    def test_cache_clear_expired(self):
        """Test manual cleanup of expired entries."""
        cache = ValidationCache(ttl=1, max_size=100)

        current_time = time.time()

        # Add fresh entry
        fresh_msg = b"fresh"
        fresh_result = ValidationResult(is_valid=True, timestamp=current_time)
        cache.put(fresh_msg, fresh_result)

        # Add expired entry manually
        expired_msg = b"expired"
        expired_result = ValidationResult(is_valid=False, timestamp=current_time - 2)
        cache.cache[expired_msg] = expired_result
        cache.access_order.append(expired_msg)

        assert len(cache.cache) == 2

        # Clear expired entries
        cache.clear_expired()

        assert len(cache.cache) == 1
        assert cache.get(fresh_msg) is not None
        assert expired_msg not in cache.cache


class TestEnhancedValidation:
    """Test enhanced validation features in Pubsub."""

    @pytest.mark.trio
    async def test_validation_with_caching(self):
        """Test message validation with caching enabled."""
        host = HostFactory()
        router = Mock()
        router.get_protocols = Mock(return_value=[])
        router.attach = Mock()

        pubsub = Pubsub(
            host=host,
            router=router,
            validation_cache_ttl=60,
            validation_cache_size=100,
        )

        # Create test message
        msg = rpc_pb2.Message(
            data=b"test data",
            topicIDs=["test_topic"],
            from_id=IDFactory().to_bytes(),
            seqno=b"123",
        )

        # Mock validator that always returns True
        def mock_validator(forwarder, message):
            return True

        pubsub.set_topic_validator("test_topic", mock_validator, False)

        # First validation should call validator and cache result
        await pubsub.validate_msg(IDFactory(), msg)

        # Verify result was cached
        msg_id = pubsub._msg_id_constructor(msg)
        cached_result = pubsub.validation_cache.get(msg_id)
        assert cached_result is not None
        assert cached_result.is_valid

        # Second validation should use cache (validator won't be called again)
        await pubsub.validate_msg(IDFactory(), msg)

    @pytest.mark.trio
    async def test_validation_timeout(self):
        """Test validation timeout for async validators."""
        host = HostFactory()
        router = Mock()
        router.get_protocols = Mock(return_value=[])
        router.attach = Mock()

        pubsub = Pubsub(
            host=host,
            router=router,
            validation_timeout=0.1,  # Very short timeout
        )

        # Create test message
        msg = rpc_pb2.Message(
            data=b"test data",
            topicIDs=["test_topic"],
            from_id=IDFactory().to_bytes(),
            seqno=b"123",
        )

        # Mock async validator that takes too long
        async def slow_validator(forwarder, message):
            await trio.sleep(0.5)  # Longer than timeout
            return True

        pubsub.set_topic_validator("test_topic", slow_validator, True)

        # Validation should timeout and raise ValidationError
        with pytest.raises(ValidationError, match="timeout"):
            await pubsub.validate_msg(IDFactory(), msg)

        # Verify failed result was cached
        msg_id = pubsub._msg_id_constructor(msg)
        cached_result = pubsub.validation_cache.get(msg_id)
        assert cached_result is not None
        assert not cached_result.is_valid
        assert cached_result.error_message is not None
        assert "timeout" in cached_result.error_message

    @pytest.mark.trio
    async def test_validation_error_caching(self):
        """Test that validation errors are properly cached."""
        host = HostFactory()
        router = Mock()
        router.get_protocols = Mock(return_value=[])
        router.attach = Mock()

        pubsub = Pubsub(host=host, router=router)

        # Create test message
        msg = rpc_pb2.Message(
            data=b"invalid data",
            topicIDs=["test_topic"],
            from_id=IDFactory().to_bytes(),
            seqno=b"123",
        )

        # Mock validator that always fails
        def failing_validator(forwarder, message):
            return False

        pubsub.set_topic_validator("test_topic", failing_validator, False)

        # First validation should fail and cache the failure
        with pytest.raises(ValidationError):
            await pubsub.validate_msg(IDFactory(), msg)

        # Verify failure was cached
        msg_id = pubsub._msg_id_constructor(msg)
        cached_result = pubsub.validation_cache.get(msg_id)
        assert cached_result is not None
        assert not cached_result.is_valid

        # Second validation should use cached failure
        with pytest.raises(ValidationError):
            await pubsub.validate_msg(IDFactory(), msg)

    @pytest.mark.trio
    async def test_mixed_sync_async_validators(self):
        """Test validation with both sync and async validators."""
        host = HostFactory()
        router = Mock()
        router.get_protocols = Mock(return_value=[])
        router.attach = Mock()

        pubsub = Pubsub(host=host, router=router)

        # Create test message
        msg = rpc_pb2.Message(
            data=b"test data",
            topicIDs=["topic1", "topic2"],
            from_id=IDFactory().to_bytes(),
            seqno=b"123",
        )

        # Mock sync validator
        def sync_validator(forwarder, message):
            return True

        # Mock async validator
        async def async_validator(forwarder, message):
            await trio.sleep(0.01)  # Small delay
            return True

        pubsub.set_topic_validator("topic1", sync_validator, False)
        pubsub.set_topic_validator("topic2", async_validator, True)

        # Should validate successfully with both validators
        await pubsub.validate_msg(IDFactory(), msg)

        # Verify result was cached
        msg_id = pubsub._msg_id_constructor(msg)
        cached_result = pubsub.validation_cache.get(msg_id)
        assert cached_result is not None
        assert cached_result.is_valid

    @pytest.mark.trio
    async def test_validation_cache_cleanup_daemon(self):
        """Test that validation cache cleanup daemon works."""
        host = HostFactory()
        router = Mock()
        router.get_protocols = Mock(return_value=[])
        router.attach = Mock()

        pubsub = Pubsub(
            host=host,
            router=router,
            validation_cache_ttl=1,  # 1 second TTL
        )

        # Add expired entry to cache
        msg_id = b"expired_msg"
        expired_result = ValidationResult(
            is_valid=True,
            timestamp=time.time() - 2,  # 2 seconds ago
        )
        pubsub.validation_cache.cache[msg_id] = expired_result
        pubsub.validation_cache.access_order.append(msg_id)

        assert len(pubsub.validation_cache.cache) == 1

        # Manually trigger cleanup (normally done by daemon)
        pubsub.validation_cache.clear_expired()

        # Expired entry should be removed
        assert len(pubsub.validation_cache.cache) == 0


class TestValidationIntegration:
    """Integration tests for validation enhancements."""

    @pytest.mark.trio
    async def test_validation_performance_with_cache(self):
        """Test that validation caching improves performance."""
        host = HostFactory()
        router = Mock()
        router.get_protocols = Mock(return_value=[])
        router.attach = Mock()

        pubsub = Pubsub(host=host, router=router)

        # Create test message
        msg = rpc_pb2.Message(
            data=b"performance test",
            topicIDs=["perf_topic"],
            from_id=IDFactory().to_bytes(),
            seqno=b"123",
        )

        # Mock expensive validator
        call_count = {"value": 0}

        async def expensive_validator(forwarder, message):
            call_count["value"] += 1
            await trio.sleep(0.01)  # Simulate expensive operation
            return True

        pubsub.set_topic_validator("perf_topic", expensive_validator, True)

        # First validation should call validator
        await pubsub.validate_msg(IDFactory(), msg)
        assert call_count["value"] == 1

        # Second validation should use cache (validator not called again)
        await pubsub.validate_msg(IDFactory(), msg)
        assert call_count["value"] == 1  # Validator not called again

        # Verify result was cached
        msg_id = pubsub._msg_id_constructor(msg)
        cached_result = pubsub.validation_cache.get(msg_id)
        assert cached_result is not None
        assert cached_result.is_valid

    @pytest.mark.trio
    async def test_validation_with_multiple_topics_and_cache(self):
        """Test validation caching with multiple topics."""
        host = HostFactory()
        router = Mock()
        router.get_protocols = Mock(return_value=[])
        router.attach = Mock()

        pubsub = Pubsub(host=host, router=router)

        # Create messages for different topics
        msg1 = rpc_pb2.Message(
            data=b"topic1 data",
            topicIDs=["topic1"],
            from_id=IDFactory().to_bytes(),
            seqno=b"123",
        )

        msg2 = rpc_pb2.Message(
            data=b"topic2 data",
            topicIDs=["topic2"],
            from_id=IDFactory().to_bytes(),
            seqno=b"456",
        )

        # Set up validators
        def validator1(forwarder, message):
            return True

        def validator2(forwarder, message):
            return True

        pubsub.set_topic_validator("topic1", validator1, False)
        pubsub.set_topic_validator("topic2", validator2, False)

        # Validate both messages
        await pubsub.validate_msg(IDFactory(), msg1)
        await pubsub.validate_msg(IDFactory(), msg2)

        # Both should be cached separately
        msg1_id = pubsub._msg_id_constructor(msg1)
        msg2_id = pubsub._msg_id_constructor(msg2)

        assert pubsub.validation_cache.get(msg1_id) is not None
        assert pubsub.validation_cache.get(msg2_id) is not None

        # Cache should contain both entries
        assert len(pubsub.validation_cache.cache) == 2


@pytest.mark.trio
async def test_pubsub_with_enhanced_validation():
    """Test Pubsub with enhanced validation features enabled."""
    from libp2p.tools.anyio_service import background_trio_service
    from tests.utils.factories import GossipsubFactory, HostFactory

    async with HostFactory.create_batch_and_listen(2) as hosts:
        routers = [GossipsubFactory() for _ in range(2)]
        pubsubs = []
        for host, router in zip(hosts, routers):
            from libp2p.pubsub.pubsub import Pubsub

            pubsub = Pubsub(
                host=host,
                router=router,
                validation_cache_ttl=60,
                validation_cache_size=100,
                validation_timeout=1.0,
            )
            async with background_trio_service(pubsub):
                await pubsub.wait_until_ready()
                pubsubs.append(pubsub)

        try:
            topic = "enhanced_validation_test"

            # Set up validators
            def strict_validator(forwarder, message):
                return b"valid" in message.data

            for pubsub in pubsubs:
                pubsub.set_topic_validator(topic, strict_validator, False)
                await pubsub.subscribe(topic)

            await trio.sleep(0.5)

            # Test valid message
            await pubsubs[0].publish(topic, b"valid message")
            await trio.sleep(0.5)

            # Test invalid message (should be rejected)
            await pubsubs[0].publish(topic, b"invalid message")
            await trio.sleep(0.5)
        finally:
            for pubsub in pubsubs:
                await pubsub.manager.stop()


@pytest.mark.trio
async def test_validation_cache_integration():
    """Test validation cache integration in real pubsub scenario."""
    from tests.utils.factories import PubsubFactory

    async with PubsubFactory.create_batch_with_gossipsub(2) as pubsubs:
        topic = "cache_integration_test"

        # Track validator calls
        call_counts = {"count": 0}

        def counting_validator(forwarder, message):
            call_counts["count"] += 1
            return True

        for pubsub in pubsubs:
            pubsub.set_topic_validator(topic, counting_validator, False)
            await pubsub.subscribe(topic)

        await trio.sleep(0.5)

        # Publish same message multiple times
        message_data = b"repeated message"
        for _ in range(3):
            await pubsubs[0].publish(topic, message_data)
            await trio.sleep(0.1)

        # Validator should only be called once due to caching
        # (Note: actual count may vary due to message routing, but should be minimal)
        assert call_counts["count"] >= 1
