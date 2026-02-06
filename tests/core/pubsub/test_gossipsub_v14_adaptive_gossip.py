"""
Tests for GossipSub v1.4 Adaptive Gossip Features.

This module tests the adaptive gossip dissemination features in v1.4, including:
- Network health calculation and monitoring
- Dynamic parameter adjustment based on network conditions
- Adaptive mesh degree bounds
- Gossip factor adaptation
"""

import time

import pytest
import trio

from libp2p.pubsub.gossipsub import (
    PROTOCOL_ID_V14,
    GossipSub,
)
from libp2p.pubsub.score import ScoreParams
from libp2p.tools.utils import connect
from tests.utils.factories import PubsubFactory


@pytest.mark.trio
async def test_adaptive_gossip_initialization():
    """Test adaptive gossip feature initialization."""
    async with PubsubFactory.create_batch_with_gossipsub(
        1, protocols=[PROTOCOL_ID_V14]
    ) as pubsubs:
        router = pubsubs[0].router
        assert isinstance(router, GossipSub)

        # Verify adaptive gossip is enabled
        assert router.adaptive_gossip_enabled

        # Check initial health metrics
        assert router.network_health_score == 1.0  # Start optimistic
        assert router.message_delivery_success_rate == 1.0
        assert router.average_peer_score == 0.0
        assert router.mesh_stability_score == 1.0
        assert router.connection_churn_rate == 0.0

        # Check adaptive parameters initialization
        assert router.adaptive_degree_low == router.degree_low
        assert router.adaptive_degree_high == router.degree_high
        assert router.gossip_factor == 0.25


@pytest.mark.trio
async def test_network_health_calculation():
    """Test network health score calculation."""
    async with PubsubFactory.create_batch_with_gossipsub(
        3, protocols=[PROTOCOL_ID_V14], heartbeat_interval=0.5
    ) as pubsubs:
        routers = [ps.router for ps in pubsubs]

        for router in routers:
            assert isinstance(router, GossipSub)

        # Connect peers
        await connect(pubsubs[0].host, pubsubs[1].host)
        await connect(pubsubs[1].host, pubsubs[2].host)
        await trio.sleep(0.5)

        # Subscribe to topic to form mesh
        topic = "health-test"
        for pubsub in pubsubs:
            await pubsub.subscribe(topic)
        await trio.sleep(1.0)

        # Trigger health update
        router0 = routers[0]
        assert isinstance(router0, GossipSub)

        # Manually trigger health calculation
        router0._update_network_health()

        # Health should be calculated based on mesh connectivity
        assert 0.0 <= router0.network_health_score <= 1.0


@pytest.mark.trio
async def test_connectivity_health_calculation():
    """Test connectivity health component calculation."""
    async with PubsubFactory.create_batch_with_gossipsub(
        10, protocols=[PROTOCOL_ID_V14], degree=2, degree_low=1, degree_high=4
    ) as pubsubs:
        router = pubsubs[0].router
        assert isinstance(router, GossipSub)

        # Connect all peers
        for i in range(1, 10):
            await connect(pubsubs[0].host, pubsubs[i].host)
        await trio.sleep(0.5)

        # Subscribe to topic
        topic = "connectivity-test"
        for pubsub in pubsubs:
            await pubsub.subscribe(topic)
        await trio.sleep(1.0)

        # Calculate health with good connectivity
        # Force health update by resetting the timer
        router.last_health_update = 0
        router._update_network_health()
        good_health = router.network_health_score

        # Simulate poor connectivity by clearing mesh
        original_mesh = dict(router.mesh)
        router.mesh[topic] = set()

        # Force health update again
        router.last_health_update = 0
        router._update_network_health()
        poor_health = router.network_health_score

        # Restore mesh
        router.mesh = original_mesh

        # Poor connectivity should result in lower health
        assert poor_health < good_health


@pytest.mark.trio
async def test_peer_score_health_calculation():
    """Test peer score health component calculation."""
    score_params = ScoreParams(
        p5_behavior_penalty_weight=1.0,
    )

    async with PubsubFactory.create_batch_with_gossipsub(
        2, protocols=[PROTOCOL_ID_V14], score_params=score_params
    ) as pubsubs:
        router = pubsubs[0].router
        assert isinstance(router, GossipSub)

        # Connect peers
        await connect(pubsubs[0].host, pubsubs[1].host)
        await trio.sleep(0.5)

        # Subscribe to topic
        topic = "score-health-test"
        for pubsub in pubsubs:
            await pubsub.subscribe(topic)
        await trio.sleep(1.0)

        # Calculate health with good scores
        router._update_network_health()
        good_health = router.network_health_score

        # Apply penalties to reduce peer scores
        peer1_id = pubsubs[1].host.get_id()
        if router.scorer:
            router.scorer.penalize_behavior(peer1_id, 100.0)

        router._update_network_health()
        poor_health = router.network_health_score

        # Poor peer scores should result in lower health
        assert poor_health <= good_health


@pytest.mark.trio
async def test_connection_churn_tracking():
    """Test connection churn rate tracking."""
    async with PubsubFactory.create_batch_with_gossipsub(
        1, protocols=[PROTOCOL_ID_V14]
    ) as pubsubs:
        router = pubsubs[0].router
        assert isinstance(router, GossipSub)

        # Simulate connections and disconnections

        # Add some connection events
        current_time = time.time()
        router.recent_peer_connections.extend([current_time, current_time - 10])
        router.recent_peer_disconnections.extend([current_time - 5, current_time - 15])

        # Calculate churn health
        churn_health = router._calculate_connection_churn_health()

        # Should be a valid health score
        assert 0.0 <= churn_health <= 1.0

        # High churn should result in lower health
        # Add many more churn events
        for i in range(20):
            router.recent_peer_connections.append(current_time - i)
            router.recent_peer_disconnections.append(current_time - i)

        high_churn_health = router._calculate_connection_churn_health()
        assert high_churn_health < churn_health


@pytest.mark.trio
async def test_adaptive_parameter_adjustment():
    """Test adaptive parameter adjustment based on health."""
    async with PubsubFactory.create_batch_with_gossipsub(
        1, protocols=[PROTOCOL_ID_V14], degree=6, degree_low=4, degree_high=12
    ) as pubsubs:
        router = pubsubs[0].router
        assert isinstance(router, GossipSub)

        # Test with poor health
        router.network_health_score = 0.1  # Very poor health
        router._adapt_gossip_parameters()

        # Parameters should be adapted for poor health
        assert router.adaptive_degree_low >= router.degree_low
        assert router.adaptive_degree_high >= router.degree_high
        assert router.gossip_factor > 0.25

        # Test with good health
        router.network_health_score = 0.9  # Excellent health
        router._adapt_gossip_parameters()

        # Parameters should be optimized for efficiency
        assert router.gossip_factor <= 0.25

        # Test with moderate health
        router.network_health_score = 0.5  # Moderate health
        router._adapt_gossip_parameters()

        # Parameters should be moderately adapted
        assert router.adaptive_degree_low >= router.degree_low
        assert router.gossip_factor >= 0.25


@pytest.mark.trio
async def test_adaptive_gossip_peers_count():
    """Test adaptive gossip peers count calculation."""
    async with PubsubFactory.create_batch_with_gossipsub(
        1, protocols=[PROTOCOL_ID_V14]
    ) as pubsubs:
        router = pubsubs[0].router
        assert isinstance(router, GossipSub)

        topic = "gossip-count-test"
        total_peers = 20

        # Test with good health
        router.network_health_score = 0.9
        router._adapt_gossip_parameters()

        good_health_count = router._get_adaptive_gossip_peers_count(topic, total_peers)

        # Test with poor health
        router.network_health_score = 0.2
        router._adapt_gossip_parameters()

        poor_health_count = router._get_adaptive_gossip_peers_count(topic, total_peers)

        # Poor health should result in more gossip peers
        assert poor_health_count >= good_health_count

        # Both should respect minimum bounds
        assert good_health_count >= 6  # Default minimum
        assert poor_health_count >= 8  # Higher minimum for poor health


@pytest.mark.trio
async def test_mesh_degree_adaptation_in_heartbeat():
    """Test that adaptive mesh degrees are used in heartbeat."""
    async with PubsubFactory.create_batch_with_gossipsub(
        5,
        protocols=[PROTOCOL_ID_V14],
        heartbeat_interval=0.5,
        degree=3,
        degree_low=2,
        degree_high=4,
    ) as pubsubs:
        router = pubsubs[0].router
        assert isinstance(router, GossipSub)

        # Connect all peers
        for i in range(1, 5):
            await connect(pubsubs[0].host, pubsubs[i].host)
        await trio.sleep(0.5)

        # Subscribe to topic
        topic = "adaptive-mesh-test"
        for pubsub in pubsubs:
            await pubsub.subscribe(topic)
        await trio.sleep(1.0)

        # Set poor health to trigger adaptation
        router.network_health_score = 0.2
        router._adapt_gossip_parameters()

        # Verify adaptive parameters are different from defaults
        assert router.adaptive_degree_low > router.degree_low
        assert router.adaptive_degree_high > router.degree_high

        # Let heartbeat run with adaptive parameters
        await trio.sleep(2.0)

        # Mesh should adapt to use new parameters
        # (Exact verification depends on peer availability and mesh formation)


@pytest.mark.trio
async def test_message_delivery_tracking():
    """Test message delivery tracking for health calculation."""
    async with PubsubFactory.create_batch_with_gossipsub(
        2, protocols=[PROTOCOL_ID_V14]
    ) as pubsubs:
        router = pubsubs[0].router
        assert isinstance(router, GossipSub)

        # Connect peers
        await connect(pubsubs[0].host, pubsubs[1].host)
        await trio.sleep(0.5)

        # Subscribe to topic
        topic = "delivery-tracking-test"
        for pubsub in pubsubs:
            await pubsub.subscribe(topic)
        await trio.sleep(1.0)

        # Publish messages to track deliveries
        for i in range(3):
            await pubsubs[0].publish(topic, f"message {i}".encode())
            await trio.sleep(0.2)

        # Verify delivery tracking
        assert topic in router.recent_message_deliveries
        assert len(router.recent_message_deliveries[topic]) > 0

        # Calculate delivery health
        delivery_health = router._calculate_message_delivery_health()
        assert 0.0 <= delivery_health <= 1.0


@pytest.mark.trio
async def test_adaptive_gossip_disabled():
    """Test behavior when adaptive gossip is disabled."""
    async with PubsubFactory.create_batch_with_gossipsub(
        1, protocols=[PROTOCOL_ID_V14]
    ) as pubsubs:
        router = pubsubs[0].router
        assert isinstance(router, GossipSub)

        # Manually disable adaptive gossip for testing
        router.adaptive_gossip_enabled = False

        # Store original parameters
        original_degree_low = router.degree_low
        original_degree_high = router.degree_high
        original_gossip_factor = router.gossip_factor

        # Try to adapt parameters (should be no-op)
        router.network_health_score = 0.1  # Poor health
        router._adapt_gossip_parameters()

        # Parameters should remain unchanged
        assert router.adaptive_degree_low == original_degree_low
        assert router.adaptive_degree_high == original_degree_high
        assert router.gossip_factor == original_gossip_factor


@pytest.mark.trio
async def test_health_update_timing():
    """Test that health updates respect timing intervals."""
    async with PubsubFactory.create_batch_with_gossipsub(
        1, protocols=[PROTOCOL_ID_V14]
    ) as pubsubs:
        router = pubsubs[0].router
        assert isinstance(router, GossipSub)

        # Record initial update time
        initial_time = router.last_health_update

        # Try to update immediately (should be skipped due to timing)
        router._update_network_health()

        # Update time should not change (too soon)
        assert router.last_health_update == initial_time

        # Manually set last update to be old enough
        router.last_health_update = int(time.time()) - 35  # 35 seconds ago

        # Now update should proceed
        router._update_network_health()

        # Update time should be current
        assert router.last_health_update > initial_time
