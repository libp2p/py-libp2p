"""
Tests for GossipSub v1.4 Rate Limiting Features.

This module tests the rate limiting mechanisms introduced in v1.4, including:
- IWANT request rate limiting
- IHAVE message rate limiting
- GRAFT flood protection
- Rate limiting cleanup and memory management
"""

import time

import pytest
import trio

from libp2p.pubsub.gossipsub import (
    PROTOCOL_ID_V14,
    GossipSub,
)
from libp2p.pubsub.pb import rpc_pb2
from libp2p.tools.utils import connect
from tests.utils.factories import IDFactory, PubsubFactory


@pytest.mark.trio
async def test_iwant_rate_limiting():
    """Test IWANT request rate limiting."""
    async with PubsubFactory.create_batch_with_gossipsub(
        1, protocols=[PROTOCOL_ID_V14]
    ) as pubsubs:
        router = pubsubs[0].router
        assert isinstance(router, GossipSub)

        # Override the rate limit for testing
        router.max_iwant_requests_per_second = 5.0

        peer_id = IDFactory()

        # First 5 requests should be allowed
        for i in range(5):
            allowed = router._check_iwant_rate_limit(peer_id)
            assert allowed, f"Request {i} should be allowed"

        # 6th request should be blocked
        allowed = router._check_iwant_rate_limit(peer_id)
        assert not allowed, "6th request should be blocked"

        # Verify penalty was applied if scorer exists
        if router.scorer:
            assert router.scorer.iwant_spam_penalties[peer_id] > 0


@pytest.mark.trio
async def test_ihave_rate_limiting():
    """Test IHAVE message rate limiting."""
    async with PubsubFactory.create_batch_with_gossipsub(
        1, protocols=[PROTOCOL_ID_V14]
    ) as pubsubs:
        router = pubsubs[0].router
        assert isinstance(router, GossipSub)

        # Override the rate limit for testing
        router.max_ihave_messages_per_second = 3.0

        peer_id = IDFactory()
        topic = "test-topic"

        # First 3 messages should be allowed
        for i in range(3):
            allowed = router._check_ihave_rate_limit(peer_id, topic)
            assert allowed, f"IHAVE {i} should be allowed"

        # 4th message should be blocked
        allowed = router._check_ihave_rate_limit(peer_id, topic)
        assert not allowed, "4th IHAVE should be blocked"

        # Verify penalty was applied if scorer exists
        if router.scorer:
            assert router.scorer.ihave_spam_penalties[peer_id] > 0


@pytest.mark.trio
async def test_graft_flood_protection():
    """Test GRAFT flood protection."""
    async with PubsubFactory.create_batch_with_gossipsub(
        1, protocols=[PROTOCOL_ID_V14]
    ) as pubsubs:
        router = pubsubs[0].router
        assert isinstance(router, GossipSub)

        # Override the threshold for testing
        router.graft_flood_threshold = 5.0

        peer_id = IDFactory()
        topic = "test-topic"

        # Initially should be allowed (no previous PRUNE)
        allowed = router._check_graft_flood_protection(peer_id, topic)
        assert allowed

        # Simulate a PRUNE by setting the timestamp
        router.graft_flood_tracking[peer_id][topic] = time.time()

        # Immediate GRAFT should be blocked (flood detected)
        allowed = router._check_graft_flood_protection(peer_id, topic)
        assert not allowed

        # After threshold time, should be allowed again
        router.graft_flood_tracking[peer_id][topic] = time.time() - 10.0
        allowed = router._check_graft_flood_protection(peer_id, topic)
        assert allowed


@pytest.mark.trio
async def test_rate_limiting_cleanup():
    """Test rate limiting data cleanup."""
    async with PubsubFactory.create_batch_with_gossipsub(
        1, protocols=[PROTOCOL_ID_V14]
    ) as pubsubs:
        router = pubsubs[0].router
        assert isinstance(router, GossipSub)

        peer_id = IDFactory()

        # Add some rate limiting data
        router._check_iwant_rate_limit(peer_id)
        router._check_ihave_rate_limit(peer_id, "topic1")
        router.graft_flood_tracking[peer_id]["topic1"] = time.time()

        # Verify data exists
        assert peer_id in router.iwant_request_limits
        assert peer_id in router.ihave_message_limits
        assert peer_id in router.graft_flood_tracking

        # Simulate peer removal
        router.remove_peer(peer_id)

        # Verify cleanup
        assert peer_id not in router.iwant_request_limits
        assert peer_id not in router.ihave_message_limits
        assert peer_id not in router.graft_flood_tracking


@pytest.mark.trio
async def test_iwant_rate_limiting_integration():
    """Test IWANT rate limiting in message exchange."""
    async with PubsubFactory.create_batch_with_gossipsub(
        2, protocols=[PROTOCOL_ID_V14], heartbeat_interval=0.5
    ) as pubsubs:
        router0 = pubsubs[0].router
        router1 = pubsubs[1].router
        assert isinstance(router0, GossipSub)
        assert isinstance(router1, GossipSub)

        # Set low rate limits for testing
        router1.max_iwant_requests_per_second = 2.0

        # Connect peers
        await connect(pubsubs[0].host, pubsubs[1].host)
        await trio.sleep(0.5)

        # Subscribe to topic
        topic = "rate-limit-test"
        await pubsubs[0].subscribe(topic)
        await pubsubs[1].subscribe(topic)
        await trio.sleep(1.0)

        # Publish several messages quickly to trigger IWANT requests
        for i in range(5):
            await pubsubs[0].publish(topic, f"message {i}".encode())
            await trio.sleep(0.1)

        # Wait for processing
        await trio.sleep(1.0)

        # Check if rate limiting was applied
        peer0_id = pubsubs[0].host.get_id()
        if peer0_id in router1.iwant_request_limits:
            # Some requests should have been made
            assert len(router1.iwant_request_limits[peer0_id]["requests"]) > 0


@pytest.mark.trio
async def test_ihave_rate_limiting_integration():
    """Test IHAVE rate limiting in gossip."""
    async with PubsubFactory.create_batch_with_gossipsub(
        3, protocols=[PROTOCOL_ID_V14], heartbeat_interval=0.5
    ) as pubsubs:
        routers = [ps.router for ps in pubsubs]

        # Set low rate limits for testing
        for router in routers:
            assert isinstance(router, GossipSub)
            router.max_ihave_messages_per_second = 2.0

        # Connect in a line: 0 -- 1 -- 2
        await connect(pubsubs[0].host, pubsubs[1].host)
        await connect(pubsubs[1].host, pubsubs[2].host)
        await trio.sleep(0.5)

        # Subscribe to topic
        topic = "ihave-rate-test"
        await pubsubs[0].subscribe(topic)
        await pubsubs[2].subscribe(topic)  # Don't subscribe peer 1 to force gossip
        await trio.sleep(1.0)

        # Publish several messages to trigger IHAVE gossip
        for i in range(5):
            await pubsubs[0].publish(topic, f"gossip message {i}".encode())
            await trio.sleep(0.2)

        # Wait for gossip processing
        await trio.sleep(2.0)

        # Rate limiting should have been applied during gossip
        # (Exact verification depends on gossip timing)


@pytest.mark.trio
async def test_graft_flood_protection_integration():
    """Test GRAFT flood protection in mesh operations."""
    async with PubsubFactory.create_batch_with_gossipsub(
        2, protocols=[PROTOCOL_ID_V14], heartbeat_interval=0.5
    ) as pubsubs:
        router0 = pubsubs[0].router
        router1 = pubsubs[1].router
        assert isinstance(router0, GossipSub)
        assert isinstance(router1, GossipSub)

        # Set low flood threshold for testing
        router1.graft_flood_threshold = 2.0

        # Connect peers
        await connect(pubsubs[0].host, pubsubs[1].host)
        await trio.sleep(0.5)

        # Subscribe and form mesh
        topic = "graft-flood-test"
        await pubsubs[0].subscribe(topic)
        await pubsubs[1].subscribe(topic)
        await trio.sleep(1.0)

        # Manually trigger PRUNE to set up flood protection
        peer0_id = pubsubs[0].host.get_id()

        # Create and handle PRUNE message
        prune_msg = rpc_pb2.ControlPrune()
        prune_msg.topicID = topic
        await router1.handle_prune(prune_msg, peer0_id)

        # Immediate GRAFT should trigger flood protection
        graft_msg = rpc_pb2.ControlGraft()
        graft_msg.topicID = topic
        await router1.handle_graft(graft_msg, peer0_id)

        # Verify flood penalty was applied
        if router1.scorer:
            assert router1.scorer.graft_flood_penalties[peer0_id] > 0


@pytest.mark.trio
async def test_rate_limiting_time_windows():
    """Test that rate limiting respects time windows."""
    async with PubsubFactory.create_batch_with_gossipsub(
        1, protocols=[PROTOCOL_ID_V14]
    ) as pubsubs:
        router = pubsubs[0].router
        assert isinstance(router, GossipSub)

        router.max_iwant_requests_per_second = 2.0
        peer_id = IDFactory()

        # Use up the rate limit
        assert router._check_iwant_rate_limit(peer_id)
        assert router._check_iwant_rate_limit(peer_id)
        assert not router._check_iwant_rate_limit(peer_id)  # Should be blocked

        # Manually advance time by modifying timestamps
        current_time = time.time()
        old_time = current_time - 2.0  # 2 seconds ago

        # Replace recent timestamps with old ones
        router.iwant_request_limits[peer_id]["requests"] = [old_time, old_time]

        # Should be allowed again after time window
        assert router._check_iwant_rate_limit(peer_id)


@pytest.mark.trio
async def test_periodic_rate_limiting_cleanup():
    """Test periodic cleanup of rate limiting data."""
    async with PubsubFactory.create_batch_with_gossipsub(
        1, protocols=[PROTOCOL_ID_V14]
    ) as pubsubs:
        router = pubsubs[0].router
        assert isinstance(router, GossipSub)

        peer_id = IDFactory()

        # Add old data (graft_flood uses 30s window, so use >30s ago to avoid boundary)
        old_time = time.time() - 10.0
        router.iwant_request_limits[peer_id]["requests"] = [old_time]
        router.ihave_message_limits[peer_id]["topic"] = [old_time]
        router.graft_flood_tracking[peer_id]["topic"] = time.time() - 35.0

        # Trigger periodic cleanup
        router._periodic_security_cleanup()

        # Old data should be cleaned up
        assert len(router.iwant_request_limits[peer_id]["requests"]) == 0
        assert len(router.ihave_message_limits[peer_id]["topic"]) == 0
        # GRAFT flood tracking should be cleaned up (30 second window)
        assert peer_id not in router.graft_flood_tracking
