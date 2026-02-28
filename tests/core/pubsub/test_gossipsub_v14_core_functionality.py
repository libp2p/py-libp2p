"""
Tests for GossipSub v1.4 Core Functionality.

This module tests the core functionality of GossipSub v1.4, including:
- Protocol version support and negotiation
- Basic message propagation with v1.4 features
- Backward compatibility with older versions
"""

import pytest
import trio

from libp2p.pubsub.gossipsub import (
    PROTOCOL_ID_V13,
    PROTOCOL_ID_V14,
    GossipSub,
)
from libp2p.pubsub.score import ScoreParams
from libp2p.tools.utils import connect
from tests.utils.factories import PubsubFactory


@pytest.mark.trio
async def test_gossipsub_v14_protocol_support():
    """Test that GossipSub supports protocol v1.4."""
    async with PubsubFactory.create_batch_with_gossipsub(
        2, protocols=[PROTOCOL_ID_V14]
    ) as pubsubs_gsub:
        # Verify the protocol is registered correctly
        for pubsub in pubsubs_gsub:
            if isinstance(pubsub.router, GossipSub):
                assert PROTOCOL_ID_V14 in pubsub.router.protocols


@pytest.mark.trio
async def test_gossipsub_v13_protocol_support():
    """Test that GossipSub supports protocol v1.3."""
    async with PubsubFactory.create_batch_with_gossipsub(
        2, protocols=[PROTOCOL_ID_V13]
    ) as pubsubs_gsub:
        # Verify the protocol is registered correctly
        for pubsub in pubsubs_gsub:
            if isinstance(pubsub.router, GossipSub):
                assert PROTOCOL_ID_V13 in pubsub.router.protocols


@pytest.mark.trio
async def test_v14_protocol_feature_detection():
    """Test protocol feature detection for v1.4."""
    async with PubsubFactory.create_batch_with_gossipsub(
        2, protocols=[PROTOCOL_ID_V14]
    ) as pubsubs_gsub:
        router = pubsubs_gsub[0].router
        assert isinstance(router, GossipSub)

        # Connect peers
        await connect(pubsubs_gsub[0].host, pubsubs_gsub[1].host)
        await trio.sleep(0.5)

        # Get peer ID
        peer_id = pubsubs_gsub[1].host.get_id()

        # Test v1.4 feature detection
        assert router.supports_protocol_feature(peer_id, "extensions")
        assert router.supports_protocol_feature(peer_id, "adaptive_gossip")
        assert router.supports_protocol_feature(peer_id, "extended_scoring")
        assert router.supports_protocol_feature(peer_id, "idontwant")
        assert router.supports_protocol_feature(peer_id, "scoring")
        assert router.supports_protocol_feature(peer_id, "px")


@pytest.mark.trio
async def test_v13_protocol_feature_detection():
    """Test protocol feature detection for v1.3."""
    async with PubsubFactory.create_batch_with_gossipsub(
        2, protocols=[PROTOCOL_ID_V13]
    ) as pubsubs_gsub:
        router = pubsubs_gsub[0].router
        assert isinstance(router, GossipSub)

        # Connect peers
        await connect(pubsubs_gsub[0].host, pubsubs_gsub[1].host)
        await trio.sleep(0.5)

        # Get peer ID
        peer_id = pubsubs_gsub[1].host.get_id()

        # Test v1.3 feature detection
        assert router.supports_protocol_feature(peer_id, "extensions")
        assert not router.supports_protocol_feature(peer_id, "adaptive_gossip")
        assert not router.supports_protocol_feature(peer_id, "extended_scoring")
        assert router.supports_protocol_feature(peer_id, "idontwant")
        assert router.supports_protocol_feature(peer_id, "scoring")
        assert router.supports_protocol_feature(peer_id, "px")


@pytest.mark.trio
async def test_supports_scoring_includes_v13_v14():
    """Regression: supports_scoring() must include v1.3/v1.4 peers for scoring gates."""
    async with PubsubFactory.create_batch_with_gossipsub(
        2, protocols=[PROTOCOL_ID_V13]
    ) as pubsubs_gsub:
        router = pubsubs_gsub[0].router
        assert isinstance(router, GossipSub)

        await connect(pubsubs_gsub[0].host, pubsubs_gsub[1].host)
        await trio.sleep(0.5)

        peer_id = pubsubs_gsub[1].host.get_id()
        assert router.supports_scoring(peer_id), "v1.3 peers must support scoring"

    async with PubsubFactory.create_batch_with_gossipsub(
        2, protocols=[PROTOCOL_ID_V14]
    ) as pubsubs_gsub:
        router = pubsubs_gsub[0].router
        assert isinstance(router, GossipSub)

        await connect(pubsubs_gsub[0].host, pubsubs_gsub[1].host)
        await trio.sleep(0.5)

        peer_id = pubsubs_gsub[1].host.get_id()
        assert router.supports_scoring(peer_id), "v1.4 peers must support scoring"


@pytest.mark.trio
async def test_message_propagation_with_v14_features():
    """Test message propagation with v1.4 features enabled."""
    # Create score parameters for v1.4
    score_params = ScoreParams(
        p5_behavior_penalty_weight=1.0,
        p6_appl_slack_weight=0.5,
        p7_ip_colocation_weight=2.0,
    )

    async with PubsubFactory.create_batch_with_gossipsub(
        3,
        protocols=[PROTOCOL_ID_V14],
        heartbeat_interval=0.5,
        score_params=score_params,
    ) as pubsubs:
        # Get the hosts and gossipsub routers
        hosts = [ps.host for ps in pubsubs]
        gsubs = [ps.router for ps in pubsubs]

        # Verify they're GossipSub instances
        for gsub in gsubs:
            assert isinstance(gsub, GossipSub)

        # Connect hosts in a line: 0 -- 1 -- 2
        await connect(hosts[0], hosts[1])
        await connect(hosts[1], hosts[2])
        await trio.sleep(0.5)

        # All hosts subscribe to the same topic
        topic = "test_v14_propagation"
        queues = []
        for pubsub in pubsubs:
            queue = await pubsub.subscribe(topic)
            queues.append(queue)
        await trio.sleep(1.0)  # Allow time for mesh formation

        # Verify that mesh has been formed
        for i, gsub in enumerate(gsubs):
            assert topic in gsub.mesh
            assert len(gsub.mesh[topic]) > 0

        # Host 0 publishes a message
        test_message = b"test v1.4 message"
        await pubsubs[0].publish(topic, test_message)

        # Wait for message propagation
        await trio.sleep(1.0)

        # Verify all peers received the message
        for i, queue in enumerate(queues):
            msg = await queue.get()
            assert msg.data == test_message


@pytest.mark.trio
async def test_backward_compatibility_v14_to_v12():
    """Test backward compatibility between v1.4 and v1.2."""
    from libp2p.pubsub.gossipsub import PROTOCOL_ID_V12

    async with PubsubFactory.create_batch_with_gossipsub(
        2, protocols=[PROTOCOL_ID_V14, PROTOCOL_ID_V12]
    ) as pubsubs:
        # Connect the peers
        await connect(pubsubs[0].host, pubsubs[1].host)
        await trio.sleep(0.5)

        # Subscribe to topic
        topic = "compatibility_test"
        queue1 = await pubsubs[1].subscribe(topic)
        await pubsubs[0].subscribe(topic)
        await trio.sleep(1.0)

        # Publish message from v1.4 peer
        test_message = b"v1.4 to v1.2 message"
        await pubsubs[0].publish(topic, test_message)
        await trio.sleep(0.5)

        # Verify v1.2 peer received the message
        msg = await queue1.get()
        assert msg.data == test_message


@pytest.mark.trio
async def test_adaptive_gossip_initialization():
    """Test that adaptive gossip parameters are initialized correctly."""
    async with PubsubFactory.create_batch_with_gossipsub(
        1, protocols=[PROTOCOL_ID_V14]
    ) as pubsubs:
        router = pubsubs[0].router
        assert isinstance(router, GossipSub)

        # Check adaptive gossip initialization
        assert router.adaptive_gossip_enabled
        assert router.network_health_score == 1.0  # Start optimistic
        assert router.adaptive_degree_low == router.degree_low
        assert router.adaptive_degree_high == router.degree_high
        assert router.gossip_factor == 0.25

        # Check v1.4 metrics initialization
        assert router.message_delivery_success_rate == 1.0
        assert router.average_peer_score == 0.0
        assert router.mesh_stability_score == 1.0
        assert router.connection_churn_rate == 0.0


@pytest.mark.trio
async def test_rate_limiting_initialization():
    """Test that rate limiting structures are initialized correctly."""
    async with PubsubFactory.create_batch_with_gossipsub(
        1, protocols=[PROTOCOL_ID_V14]
    ) as pubsubs:
        router = pubsubs[0].router
        assert isinstance(router, GossipSub)

        # Check rate limiting initialization
        assert len(router.iwant_request_limits) == 0
        assert len(router.ihave_message_limits) == 0
        assert len(router.graft_flood_tracking) == 0

        # Check rate limiting parameters
        assert router.max_iwant_requests_per_second == 10.0
        assert router.max_ihave_messages_per_second == 10.0
        assert router.graft_flood_threshold == 10.0


@pytest.mark.trio
async def test_extensions_framework_initialization():
    """Test that extensions framework is initialized correctly."""
    async with PubsubFactory.create_batch_with_gossipsub(
        1, protocols=[PROTOCOL_ID_V14]
    ) as pubsubs:
        router = pubsubs[0].router
        assert isinstance(router, GossipSub)

        # Check extensions initialization
        assert hasattr(router, "extension_handlers")
        assert len(router.extension_handlers) == 0

        # Test extension registration
        async def test_handler(data: bytes, sender_peer_id):
            pass

        router.register_extension_handler("test", test_handler)
        assert "test" in router.extension_handlers

        # Test extension unregistration
        router.unregister_extension_handler("test")
        assert "test" not in router.extension_handlers
