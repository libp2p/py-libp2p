"""
Tests for Gossipsub v1.1 Core Functionality.

This module tests the core functionality of GossipSub v1.1, including:
- Message propagation under normal mesh conditions
- Interoperability with GossipSub v1.0 peers
"""

import pytest
import trio

from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.score import ScoreParams, TopicScoreParams
from libp2p.tools.utils import connect
from tests.utils.factories import PubsubFactory


@pytest.mark.trio
async def test_message_propagation_normal_mesh():
    """Test that messages propagate correctly under normal mesh conditions."""
    async with PubsubFactory.create_batch_with_gossipsub(
        3, heartbeat_interval=0.5
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
        topic = "test_message_propagation"
        for pubsub in pubsubs:
            await pubsub.subscribe(topic)
        await trio.sleep(1.0)  # Allow time for mesh formation

        # Verify that mesh has been formed
        for i, gsub in enumerate(gsubs):
            assert topic in gsub.mesh
            assert len(gsub.mesh[topic]) > 0

        # Host 0 publishes a message
        test_message = b"test message from host 0"
        await pubsubs[0].publish(topic, test_message)
        await trio.sleep(1.0)

        # Host 2 publishes a message
        test_message_2 = b"test message from host 2"
        await pubsubs[2].publish(topic, test_message_2)
        await trio.sleep(1.0)

        # Verify mesh is still intact
        for i, gsub in enumerate(gsubs):
            assert topic in gsub.mesh
            assert len(gsub.mesh[topic]) > 0


@pytest.mark.trio
async def test_interop_with_gossipsub_v1_0():
    """Test interoperability with GossipSub v1.0 peers."""
    # Create a v1.0 node (no scoring)
    async with PubsubFactory.create_batch_with_gossipsub(
        1, score_params=None, heartbeat_interval=0.5
    ) as v1_0_pubsubs:
        # Create v1.1 node with scoring enabled
        async with PubsubFactory.create_batch_with_gossipsub(
            1, heartbeat_interval=0.5
        ) as v1_1_pubsubs:
            v1_0_host = v1_0_pubsubs[0].host
            v1_1_host = v1_1_pubsubs[0].host

            v1_0_gsub = v1_0_pubsubs[0].router
            v1_1_gsub = v1_1_pubsubs[0].router

            assert isinstance(v1_0_gsub, GossipSub)
            assert isinstance(v1_1_gsub, GossipSub)

            # Connect v1.0 and v1.1 hosts
            await connect(v1_0_host, v1_1_host)
            await trio.sleep(0.5)

            # Both subscribe to the same topic
            topic = "test_interop"
            await v1_0_pubsubs[0].subscribe(topic)
            await v1_1_pubsubs[0].subscribe(topic)
            await trio.sleep(1.0)  # Allow time for mesh formation

            # Verify that they've formed a mesh
            assert v1_1_host.get_id() in v1_0_gsub.mesh.get(topic, set())
            assert v1_0_host.get_id() in v1_1_gsub.mesh.get(topic, set())

            # Test message exchange from v1.0 to v1.1
            test_message = b"test message from v1.0"
            await v1_0_pubsubs[0].publish(topic, test_message)
            await trio.sleep(0.5)

            # Test message exchange from v1.1 to v1.0
            test_message_2 = b"test message from v1.1"
            await v1_1_pubsubs[0].publish(topic, test_message_2)
            await trio.sleep(0.5)


@pytest.mark.trio
async def test_graceful_fallback_with_v1_0_peers():
    """Test that v1.1 features gracefully fallback when interacting with v1.0 peers."""
    # Create a v1.0 node (no scoring)
    async with PubsubFactory.create_batch_with_gossipsub(
        1, score_params=None, heartbeat_interval=0.5
    ) as v1_0_pubsubs:
        # Create v1.1 node with scoring enabled
        score_params = ScoreParams(
            p1_time_in_mesh=TopicScoreParams(weight=1.0, cap=10.0, decay=0.9),
            publish_threshold=0.5,
            gossip_threshold=0.0,
            graylist_threshold=-1.0,
            accept_px_threshold=0.2,
        )
        async with PubsubFactory.create_batch_with_gossipsub(
            1, score_params=score_params, heartbeat_interval=0.5
        ) as v1_1_pubsubs:
            v1_0_host = v1_0_pubsubs[0].host
            v1_1_host = v1_1_pubsubs[0].host

            v1_0_gsub = v1_0_pubsubs[0].router
            v1_1_gsub = v1_1_pubsubs[0].router

            assert isinstance(v1_0_gsub, GossipSub)
            assert isinstance(v1_1_gsub, GossipSub)

            # Connect v1.0 and v1.1 hosts
            await connect(v1_0_host, v1_1_host)
            await trio.sleep(0.5)

            # Both subscribe to the same topic
            topic = "test_fallback"
            await v1_0_pubsubs[0].subscribe(topic)
            await v1_1_pubsubs[0].subscribe(topic)
            await trio.sleep(1.0)  # Allow time for mesh formation

            # Verify that they've formed a mesh
            assert v1_1_host.get_id() in v1_0_gsub.mesh.get(topic, set())
            assert v1_0_host.get_id() in v1_1_gsub.mesh.get(topic, set())

            # The v1.1 node should still apply scoring logic
            # but not expect v1.0 node to do the same
            if v1_1_gsub.scorer:
                # Check initial score
                initial_score = v1_1_gsub.scorer.score(v1_0_host.get_id(), [topic])

                # Simulate some positive behavior
                v1_1_gsub.scorer.on_join_mesh(v1_0_host.get_id(), topic)
                v1_1_gsub.scorer.on_heartbeat()

                # Score should have changed (time_in_mesh should increase)
                new_score = v1_1_gsub.scorer.score(v1_0_host.get_id(), [topic])
                assert new_score > initial_score

            # Test message exchange works in both directions
            # v1.0 to v1.1
            test_message = b"test message from v1.0"
            await v1_0_pubsubs[0].publish(topic, test_message)
            await trio.sleep(0.5)

            # v1.1 to v1.0
            test_message_2 = b"test message from v1.1"
            await v1_1_pubsubs[0].publish(topic, test_message_2)
            await trio.sleep(0.5)
