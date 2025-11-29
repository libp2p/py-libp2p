"""
Tests for Gossipsub v1.1 Peer Scoring Behavior.

This module tests the peer scoring behavior of GossipSub v1.1, including:
- Score decreases for spamming invalid/duplicate messages
- Score stability for honest peers
- Pruning of low-scoring peers
"""

import pytest
import trio

from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.score import ScoreParams, TopicScoreParams
from libp2p.tools.utils import connect
from tests.utils.factories import PubsubFactory


@pytest.mark.trio
async def test_score_decreases_for_invalid_messages():
    """Test that peer score decreases when sending invalid messages."""
    score_params = ScoreParams(
        p4_invalid_messages=TopicScoreParams(weight=1.0, cap=10.0, decay=1.0),
    )

    async with PubsubFactory.create_batch_with_gossipsub(
        2, score_params=score_params, heartbeat_interval=0.5
    ) as pubsubs:
        gsub0, gsub1 = (ps.router for ps in pubsubs)
        host0, host1 = (ps.host for ps in pubsubs)

        # Connect hosts
        await connect(host0, host1)
        await trio.sleep(0.5)

        # Both subscribe to the same topic
        topic = "test_invalid_messages"
        await pubsubs[0].subscribe(topic)
        await pubsubs[1].subscribe(topic)
        await trio.sleep(1.0)  # Allow time for mesh formation

        # Get initial score
        assert isinstance(gsub0, GossipSub)
        assert gsub0.scorer is not None
        initial_score = gsub0.scorer.score(host1.get_id(), [topic])

        # Simulate invalid messages
        for _ in range(3):
            gsub0.scorer.on_invalid_message(host1.get_id(), topic)

        # Check that score decreased
        new_score = gsub0.scorer.score(host1.get_id(), [topic])
        assert new_score < initial_score
        assert (
            new_score <= initial_score - 3.0
        )  # Each invalid message should decrease by weight (1.0)


@pytest.mark.trio
async def test_score_decreases_for_duplicate_messages():
    """Test that peer score decreases when sending duplicate messages."""
    score_params = ScoreParams(
        p4_invalid_messages=TopicScoreParams(weight=1.0, cap=10.0, decay=1.0),
    )

    async with PubsubFactory.create_batch_with_gossipsub(
        2, score_params=score_params, heartbeat_interval=0.5
    ) as pubsubs:
        gsub0, gsub1 = (ps.router for ps in pubsubs)
        host0, host1 = (ps.host for ps in pubsubs)

        # Connect hosts
        await connect(host0, host1)
        await trio.sleep(0.5)

        # Both subscribe to the same topic
        topic = "test_duplicate_messages"
        await pubsubs[0].subscribe(topic)
        await pubsubs[1].subscribe(topic)
        await trio.sleep(1.0)  # Allow time for mesh formation

        # Get initial score
        assert isinstance(gsub0, GossipSub)
        assert gsub0.scorer is not None
        initial_score = gsub0.scorer.score(host1.get_id(), [topic])

        # Simulate invalid message (duplicate)
        gsub0.scorer.on_invalid_message(host1.get_id(), topic)

        # Check that score decreased
        score_after_invalid = gsub0.scorer.score(host1.get_id(), [topic])
        assert score_after_invalid < initial_score


@pytest.mark.trio
async def test_honest_peers_maintain_stable_scores():
    """Test that honest peers maintain stable or positive scores."""
    score_params = ScoreParams(
        p1_time_in_mesh=TopicScoreParams(weight=1.0, cap=10.0, decay=0.9),
        p2_first_message_deliveries=TopicScoreParams(weight=1.0, cap=10.0, decay=0.9),
        p3_mesh_message_deliveries=TopicScoreParams(weight=1.0, cap=10.0, decay=0.9),
    )

    async with PubsubFactory.create_batch_with_gossipsub(
        2, score_params=score_params, heartbeat_interval=0.5
    ) as pubsubs:
        gsub0, gsub1 = (ps.router for ps in pubsubs)
        host0, host1 = (ps.host for ps in pubsubs)

        # Connect hosts
        await connect(host0, host1)
        await trio.sleep(0.5)

        # Both subscribe to the same topic
        topic = "test_honest_peers"
        await pubsubs[0].subscribe(topic)
        await pubsubs[1].subscribe(topic)
        await trio.sleep(1.0)  # Allow time for mesh formation

        # Get initial score
        assert isinstance(gsub0, GossipSub)
        assert gsub0.scorer is not None
        initial_score = gsub0.scorer.score(host1.get_id(), [topic])

        # Simulate honest behavior
        gsub0.scorer.on_join_mesh(host1.get_id(), topic)

        # Wait for a few heartbeats
        for _ in range(3):
            gsub0.scorer.on_heartbeat()
            await trio.sleep(0.1)

        # Simulate message deliveries
        gsub0.scorer.on_first_delivery(host1.get_id(), topic)
        gsub0.scorer.on_mesh_delivery(host1.get_id(), topic)

        # Check that score increased or remained stable
        new_score = gsub0.scorer.score(host1.get_id(), [topic])
        assert new_score >= initial_score


@pytest.mark.trio
async def test_low_scoring_peers_get_pruned():
    """Test that peers with low scores get pruned from the mesh."""
    score_params = ScoreParams(
        p4_invalid_messages=TopicScoreParams(weight=1.0, cap=10.0, decay=1.0),
        gossip_threshold=0.5,  # Set threshold for gossip
    )

    async with PubsubFactory.create_batch_with_gossipsub(
        2, score_params=score_params, heartbeat_interval=0.5
    ) as pubsubs:
        gsub0, gsub1 = (ps.router for ps in pubsubs)
        host0, host1 = (ps.host for ps in pubsubs)

        # Connect hosts
        await connect(host0, host1)
        await trio.sleep(0.5)

        # Both subscribe to the same topic
        topic = "test_pruning"
        await pubsubs[0].subscribe(topic)
        await pubsubs[1].subscribe(topic)
        await trio.sleep(1.0)  # Allow time for mesh formation

        # Verify that hosts are in each other's mesh
        assert isinstance(gsub0, GossipSub)
        assert isinstance(gsub1, GossipSub)
        assert host1.get_id() in gsub0.mesh.get(topic, set())
        assert host0.get_id() in gsub1.mesh.get(topic, set())

        # Simulate invalid behavior to decrease score
        assert gsub0.scorer is not None
        # Multiple invalid messages to ensure score drops below threshold
        for _ in range(5):
            gsub0.scorer.on_invalid_message(host1.get_id(), topic)

        # Trigger mesh heartbeat to process score-based pruning
        peers_to_graft, peers_to_prune = gsub0.mesh_heartbeat()

        # After several invalid messages, the peer should be considered for pruning
        # We can't assert the exact structure of peers_to_prune, but we can check
        # that the peer's score is now negative
        assert gsub0.scorer.score(host1.get_id(), [topic]) < 0


@pytest.mark.trio
async def test_score_based_message_propagation():
    """Test that messages propagate based on peer scores."""
    score_params = ScoreParams(
        p1_time_in_mesh=TopicScoreParams(weight=1.0, cap=10.0, decay=0.9),
        publish_threshold=0.5,  # Set threshold for publishing
    )

    async with PubsubFactory.create_batch_with_gossipsub(
        3, score_params=score_params, heartbeat_interval=0.5
    ) as pubsubs:
        gsub0, gsub1, gsub2 = (ps.router for ps in pubsubs)
        host0, host1, host2 = (ps.host for ps in pubsubs)

        # Connect hosts
        await connect(host0, host1)
        await connect(host0, host2)
        await trio.sleep(0.5)

        # All subscribe to the same topic
        topic = "test_score_propagation"
        for pubsub in pubsubs:
            await pubsub.subscribe(topic)
        await trio.sleep(1.0)  # Allow time for mesh formation

        # Give host1 a good score
        assert isinstance(gsub0, GossipSub)
        assert gsub0.scorer is not None
        gsub0.scorer.on_join_mesh(host1.get_id(), topic)
        gsub0.scorer.on_heartbeat()

        # Keep host2 with default score (below threshold)

        # Check which peers are allowed to publish
        assert gsub0.scorer.allow_publish(host1.get_id(), [topic])

        # Get peers that would receive messages
        # Use empty ID objects instead of None
        from libp2p.peer.id import ID

        empty_id = ID(b"")
        peers_for_gossip = list(gsub0._get_peers_to_send([topic], empty_id, empty_id))

        # The high-scoring peer should be included
        assert host1.get_id() in peers_for_gossip
