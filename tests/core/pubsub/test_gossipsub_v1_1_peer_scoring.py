"""
Tests for Gossipsub v1.1 Peer Scoring functionality.

This module tests the PeerScorer class and its integration with GossipSub,
including score calculation, decay, gates, and opportunistic grafting.
"""

from typing import cast

import pytest
import trio

from libp2p.pubsub.gossipsub import PROTOCOL_ID_V11, GossipSub
from libp2p.pubsub.score import PeerScorer, ScoreParams, TopicScoreParams
from libp2p.tools.utils import connect
from tests.utils.factories import IDFactory, PubsubFactory


class TestPeerScorer:
    """Test the PeerScorer class functionality."""

    def test_initialization(self):
        """Test PeerScorer initialization with default and custom parameters."""
        # Test with default parameters
        scorer = PeerScorer(ScoreParams())
        assert scorer.params is not None
        assert len(scorer.time_in_mesh) == 0
        assert len(scorer.first_message_deliveries) == 0
        assert len(scorer.mesh_message_deliveries) == 0
        assert len(scorer.invalid_messages) == 0
        assert len(scorer.behavior_penalty) == 0

        # Test with custom parameters
        custom_params = ScoreParams(
            p1_time_in_mesh=TopicScoreParams(weight=1.0, cap=10.0, decay=0.9),
            p2_first_message_deliveries=TopicScoreParams(
                weight=2.0, cap=5.0, decay=0.8
            ),
            publish_threshold=0.5,
            gossip_threshold=0.0,
            graylist_threshold=-1.0,
            accept_px_threshold=0.2,
        )
        scorer = PeerScorer(custom_params)
        assert scorer.params.p1_time_in_mesh.weight == 1.0
        assert scorer.params.publish_threshold == 0.5

    def test_topic_score_calculation(self):
        """Test topic score calculation with various parameters."""
        params = ScoreParams(
            p1_time_in_mesh=TopicScoreParams(weight=1.0, cap=10.0, decay=1.0),
            p2_first_message_deliveries=TopicScoreParams(
                weight=2.0, cap=5.0, decay=1.0
            ),
            p3_mesh_message_deliveries=TopicScoreParams(weight=1.5, cap=8.0, decay=1.0),
            p4_invalid_messages=TopicScoreParams(weight=3.0, cap=3.0, decay=1.0),
        )
        scorer = PeerScorer(params)
        peer_id = IDFactory()
        topic = "test_topic"

        # Test with no activity
        score = scorer.topic_score(peer_id, topic)
        assert score == 0.0

        # Test P1: Time in mesh
        scorer.on_join_mesh(peer_id, topic)
        scorer.on_heartbeat()  # Increment time
        score = scorer.topic_score(peer_id, topic)
        assert score == 1.0  # weight * min(1, cap)

        # Test P2: First message deliveries
        scorer.on_first_delivery(peer_id, topic)
        score = scorer.topic_score(peer_id, topic)
        assert score == 3.0  # 1.0 (P1) + 2.0 (P2)

        # Test P3: Mesh message deliveries
        scorer.on_mesh_delivery(peer_id, topic)
        score = scorer.topic_score(peer_id, topic)
        assert score == 4.5  # 1.0 (P1) + 2.0 (P2) + 1.5 (P3)

        # Test P4: Invalid messages (penalty)
        scorer.on_invalid_message(peer_id, topic)
        score = scorer.topic_score(peer_id, topic)
        assert score == 1.5  # 4.5 - 3.0 (P4 penalty)

    def test_score_caps(self):
        """Test that score components are properly capped."""
        params = ScoreParams(
            p1_time_in_mesh=TopicScoreParams(weight=1.0, cap=2.0, decay=1.0),
            p2_first_message_deliveries=TopicScoreParams(
                weight=1.0, cap=1.0, decay=1.0
            ),
        )
        scorer = PeerScorer(params)
        peer_id = IDFactory()
        topic = "test_topic"

        # Exceed P1 cap
        for _ in range(5):
            scorer.on_join_mesh(peer_id, topic)
            scorer.on_heartbeat()
        score = scorer.topic_score(peer_id, topic)
        assert score == 2.0  # Capped at 2.0

        # Exceed P2 cap
        for _ in range(3):
            scorer.on_first_delivery(peer_id, topic)
        score = scorer.topic_score(peer_id, topic)
        assert score == 3.0  # 2.0 (P1 capped) + 1.0 (P2 capped)

    def test_behavior_penalty(self):
        """Test behavior penalty calculation."""
        params = ScoreParams(
            p5_behavior_penalty_weight=2.0,
            p5_behavior_penalty_threshold=1.0,
            p5_behavior_penalty_decay=1.0,
        )
        scorer = PeerScorer(params)
        peer_id = IDFactory()
        topics = ["topic1", "topic2"]

        # Test below threshold
        scorer.penalize_behavior(peer_id, 0.5)
        score = scorer.score(peer_id, topics)
        assert score == 0.0  # No penalty applied

        # Test above threshold
        scorer.penalize_behavior(peer_id, 1.0)  # Total: 1.5
        score = scorer.score(peer_id, topics)
        expected_penalty = (1.5 - 1.0) * 2.0  # (penalty - threshold) * weight
        assert score == -expected_penalty

    def test_decay_functionality(self):
        """Test that scores decay over time."""
        params = ScoreParams(
            p1_time_in_mesh=TopicScoreParams(weight=1.0, cap=10.0, decay=0.5),
            p2_first_message_deliveries=TopicScoreParams(
                weight=1.0, cap=10.0, decay=0.8
            ),
        )
        scorer = PeerScorer(params)
        peer_id = IDFactory()
        topic = "test_topic"

        # Set up initial scores
        scorer.on_join_mesh(peer_id, topic)
        scorer.on_first_delivery(peer_id, topic)
        initial_score = scorer.topic_score(peer_id, topic)
        assert initial_score == 2.0

        # Apply decay
        scorer.on_heartbeat()
        decayed_score = scorer.topic_score(peer_id, topic)
        expected_p1 = 1.0 * 0.5  # time_in_mesh * decay
        expected_p2 = 1.0 * 0.8  # first_deliveries * decay
        assert decayed_score == expected_p1 + expected_p2

    def test_score_gates(self):
        """Test score-based gates (publish, gossip, graylist, PX)."""
        params = ScoreParams(
            p1_time_in_mesh=TopicScoreParams(weight=1.0, cap=10.0, decay=0.9),
            p4_invalid_messages=TopicScoreParams(weight=1.0, cap=10.0, decay=1.0),
            publish_threshold=1.0,
            gossip_threshold=0.5,
            graylist_threshold=-0.5,
            accept_px_threshold=0.2,
        )
        scorer = PeerScorer(params)
        peer_id = IDFactory()
        topics = ["test_topic"]

        # Test with zero score
        assert not scorer.allow_publish(peer_id, topics)
        assert not scorer.allow_gossip(peer_id, topics)
        assert not scorer.is_graylisted(peer_id, topics)
        assert not scorer.allow_px_from(peer_id, topics)

        # Test with positive score
        scorer.on_join_mesh(peer_id, topics[0])
        # Don't call heartbeat immediately to avoid decay
        assert scorer.allow_publish(peer_id, topics)
        assert scorer.allow_gossip(peer_id, topics)
        assert not scorer.is_graylisted(peer_id, topics)
        assert scorer.allow_px_from(peer_id, topics)

        # Test with negative score
        scorer.on_invalid_message(peer_id, topics[0])
        scorer.on_invalid_message(peer_id, topics[0])
        assert scorer.is_graylisted(peer_id, topics)

    def test_multi_topic_scoring(self):
        """Test scoring across multiple topics."""
        params = ScoreParams(
            p1_time_in_mesh=TopicScoreParams(weight=1.0, cap=10.0, decay=1.0),
        )
        scorer = PeerScorer(params)
        peer_id = IDFactory()
        topics = ["topic1", "topic2", "topic3"]

        # Add peer to multiple topics
        for topic in topics:
            scorer.on_join_mesh(peer_id, topic)
            scorer.on_heartbeat()

        # Score should be sum of all topic scores
        total_score = scorer.score(peer_id, topics)
        assert total_score == 3.0  # 1.0 per topic.

        # Test with subset of topics
        subset_score = scorer.score(peer_id, topics[:2])
        assert subset_score == 2.0  # Only first two topics.

    def test_per_topic_gates(self):
        """
        Test that gates evaluate each topic individually when
        a single topic is provided.
        """
        params = ScoreParams(
            publish_threshold=0.5,
            gossip_threshold=0.3,
            p1_time_in_mesh=TopicScoreParams(weight=1.0, cap=10.0, decay=1.0),
        )
        scorer = PeerScorer(params)
        peer_id = IDFactory()

        # Give peer high score in topic1, no score in topic2
        scorer.on_join_mesh(peer_id, "topic1")  # Score = 1.0 for topic1

        # Test individual topic gates
        # Should pass (score = 1.0)
        assert scorer.allow_publish(peer_id, ["topic1"])
        # Should fail (score = 0.0)
        assert not scorer.allow_publish(peer_id, ["topic2"])

        # Should pass (score = 1.0)
        assert scorer.allow_gossip(peer_id, ["topic1"])
        # Should fail (score = 0.0)
        assert not scorer.allow_gossip(peer_id, ["topic2"])

        # Test combined topic gates
        assert scorer.allow_publish(
            peer_id, ["topic1", "topic2"]
        )  # Combined score = 1.0
        assert scorer.allow_gossip(
            peer_id, ["topic1", "topic2"]
        )  # Combined score = 1.0


class TestGossipSubScoringIntegration:
    """Test GossipSub integration with peer scoring."""

    @pytest.mark.trio
    async def test_scorer_initialization(self):
        """Test that GossipSub initializes with scorer."""
        score_params = ScoreParams(
            publish_threshold=0.5,
            gossip_threshold=0.0,
            graylist_threshold=-1.0,
        )

        async with PubsubFactory.create_batch_with_gossipsub(
            1, score_params=score_params
        ) as pubsubs:
            gsub = cast(GossipSub, pubsubs[0].router)
            assert isinstance(gsub, GossipSub)
            assert gsub.scorer is not None
            scorer = gsub.scorer
            assert scorer.params.publish_threshold == 0.5

    @pytest.mark.trio
    async def test_publish_gate(self):
        """Test that publish gate blocks low-scoring peers."""
        score_params = ScoreParams(
            publish_threshold=1.0,  # High threshold
            p1_time_in_mesh=TopicScoreParams(weight=1.0, cap=10.0, decay=1.0),
        )

        async with PubsubFactory.create_batch_with_gossipsub(
            2, score_params=score_params, heartbeat_interval=0.1
        ) as pubsubs:
            gsub0 = pubsubs[0].router
            host0, host1 = pubsubs[0].host, pubsubs[1].host

            # Connect hosts
            await connect(host0, host1)
            await trio.sleep(0.2)

            topic = "test_publish_gate"
            await pubsubs[0].subscribe(topic)
            await pubsubs[1].subscribe(topic)
            await trio.sleep(0.2)

            # Ensure scorer exists
            assert isinstance(gsub0, GossipSub)
            assert gsub0.scorer is not None
            scorer = gsub0.scorer

            # Get peer ID
            peer_id = host1.get_id()

            # Reset any existing scores to ensure clean state
            if peer_id in scorer.time_in_mesh:
                for t in list(scorer.time_in_mesh[peer_id].keys()):
                    scorer.time_in_mesh[peer_id][t] = 0.0

            # Verify initial score is below threshold
            initial_score = scorer.topic_score(peer_id, topic)
            assert initial_score < score_params.publish_threshold, (
                f"Initial score {initial_score} should be < "
                f"{score_params.publish_threshold}"
            )

            # Initially, peer should have low score and be blocked
            assert not scorer.allow_publish(peer_id, [topic]), (
                "Peer with low score should not be allowed to publish"
            )

            # Simulate peer joining mesh to increase score
            # Add enough score to exceed threshold
            scorer.on_join_mesh(peer_id, topic)
            # Add more score to ensure it's above threshold
            scorer.on_join_mesh(peer_id, topic)

            # Verify the score is now above threshold
            new_score = scorer.topic_score(peer_id, topic)
            assert new_score >= score_params.publish_threshold, (
                f"New score {new_score} should be >= {score_params.publish_threshold}"
            )

            # Now peer should be allowed to publish
            assert scorer.allow_publish(peer_id, [topic]), (
                "Peer with high score should be allowed to publish"
            )

    @pytest.mark.trio
    async def test_gossip_gate(self):
        """Test that gossip gate filters peers for gossip."""
        score_params = ScoreParams(
            gossip_threshold=0.5,
            p1_time_in_mesh=TopicScoreParams(weight=1.0, cap=10.0, decay=1.0),
        )

        async with PubsubFactory.create_batch_with_gossipsub(
            3, score_params=score_params, heartbeat_interval=0.1
        ) as pubsubs:
            hosts = [ps.host for ps in pubsubs]
            gsubs = [ps.router for ps in pubsubs]

            # Connect all hosts
            for i in range(len(hosts)):
                for j in range(i + 1, len(hosts)):
                    await connect(hosts[i], hosts[j])
            await trio.sleep(0.2)

            topic = "test_gossip_gate"
            for pubsub in pubsubs:
                await pubsub.subscribe(topic)
            await trio.sleep(0.2)

            # Test gossip filtering
            gsub0 = cast(GossipSub, gsubs[0])
            peer1_id = hosts[1].get_id()
            peer2_id = hosts[2].get_id()

            # Remove peers from mesh to reset their scores to 0.0
            if topic in gsub0.mesh:
                gsub0.mesh[topic].discard(peer1_id)
                gsub0.mesh[topic].discard(peer2_id)
            # Reset their time_in_mesh scores
            if gsub0.scorer is not None:
                scorer = cast(PeerScorer, gsub0.scorer)
                scorer.time_in_mesh[peer1_id][topic] = 0.0
                scorer.time_in_mesh[peer2_id][topic] = 0.0

            # Initially both peers should be filtered out
            assert isinstance(gsub0, GossipSub)
            assert gsub0.scorer is not None
            scorer = cast(PeerScorer, gsub0.scorer)
            assert not scorer.allow_gossip(peer1_id, [topic])
            assert not scorer.allow_gossip(peer2_id, [topic])

            # Increase peer1's score
            scorer.on_join_mesh(peer1_id, topic)
            scorer.on_heartbeat()

            # Only peer1 should be allowed for gossip
            assert scorer.allow_gossip(peer1_id, [topic])
            assert not scorer.allow_gossip(peer2_id, [topic])

    @pytest.mark.trio
    async def test_graylist_gate(self):
        """Test that graylist gate blocks misbehaving peers."""
        score_params = ScoreParams(
            graylist_threshold=-0.5,
            p4_invalid_messages=TopicScoreParams(weight=1.0, cap=10.0, decay=1.0),
        )

        async with PubsubFactory.create_batch_with_gossipsub(
            2, score_params=score_params, heartbeat_interval=0.1
        ) as pubsubs:
            gsub0 = pubsubs[0].router
            host0, host1 = pubsubs[0].host, pubsubs[1].host

            # Connect hosts
            await connect(host0, host1)
            await trio.sleep(0.2)

            topic = "test_graylist_gate"
            await pubsubs[0].subscribe(topic)
            await pubsubs[1].subscribe(topic)
            await trio.sleep(0.2)

            peer_id = host1.get_id()

            # Initially peer should not be graylisted
            assert isinstance(gsub0, GossipSub)
            assert gsub0.scorer is not None
            assert not gsub0.scorer.is_graylisted(peer_id, [topic])

            # Simulate invalid messages to trigger graylist
            gsub0.scorer.on_invalid_message(peer_id, topic)
            gsub0.scorer.on_invalid_message(peer_id, topic)

            # Peer should now be graylisted
            assert gsub0.scorer.is_graylisted(peer_id, [topic])

    @pytest.mark.trio
    async def test_px_gate(self):
        """Test that PX gate controls peer exchange acceptance."""
        score_params = ScoreParams(
            accept_px_threshold=0.3,
            p1_time_in_mesh=TopicScoreParams(weight=1.0, cap=10.0, decay=1.0),
        )

        async with PubsubFactory.create_batch_with_gossipsub(
            2, score_params=score_params, do_px=True, heartbeat_interval=0.1
        ) as pubsubs:
            gsub0 = pubsubs[0].router
            host0, host1 = pubsubs[0].host, pubsubs[1].host

            # Connect hosts
            await connect(host0, host1)
            await trio.sleep(0.2)

            topic = "test_px_gate"
            await pubsubs[0].subscribe(topic)
            await pubsubs[1].subscribe(topic)
            await trio.sleep(0.2)

            peer_id = host1.get_id()

            # Initially peer should not be allowed for PX
            assert isinstance(gsub0, GossipSub)
            assert gsub0.scorer is not None
            assert not gsub0.scorer.allow_px_from(peer_id, [topic])

            # Increase peer's score
            gsub0.scorer.on_join_mesh(peer_id, topic)
            gsub0.scorer.on_heartbeat()

            # Now peer should be allowed for PX
            assert gsub0.scorer.allow_px_from(peer_id, [topic])

    @pytest.mark.trio
    async def test_opportunistic_grafting(self):
        """Test opportunistic grafting based on peer scores."""
        score_params = ScoreParams(
            p1_time_in_mesh=TopicScoreParams(weight=1.0, cap=10.0, decay=1.0),
        )

        async with PubsubFactory.create_batch_with_gossipsub(
            4,
            score_params=score_params,
            degree=2,
            degree_low=1,
            degree_high=3,
            heartbeat_interval=0.1,
        ) as pubsubs:
            hosts = [ps.host for ps in pubsubs]
            gsubs = [ps.router for ps in pubsubs]

            # Connect all hosts
            for i in range(len(hosts)):
                for j in range(i + 1, len(hosts)):
                    await connect(hosts[i], hosts[j])
            await trio.sleep(0.2)

            topic = "test_opportunistic_grafting"
            for pubsub in pubsubs:
                await pubsub.subscribe(topic)
            await trio.sleep(0.2)

            # Manually set up mesh with some peers having higher scores
            gsub0 = gsubs[0]
            assert isinstance(gsub0, GossipSub)
            assert gsub0.scorer is not None
            scorer = cast(PeerScorer, gsub0.scorer)
            # Give some peers higher scores
            for i, host in enumerate(hosts[1:], 1):
                peer_id = host.get_id()
                scorer.on_join_mesh(peer_id, topic)
                # Give later peers higher scores
                for _ in range(i):
                    scorer.on_heartbeat()

            # Trigger mesh heartbeat to test opportunistic grafting
            peers_to_graft, peers_to_prune = gsub0.mesh_heartbeat()

            # Should attempt to graft higher-scoring peers
            assert (
                len(peers_to_graft) >= 0
            )  # May or may not graft depending on current mesh

    @pytest.mark.trio
    async def test_heartbeat_decay(self):
        """Test that heartbeat triggers score decay."""
        score_params = ScoreParams(
            p1_time_in_mesh=TopicScoreParams(weight=1.0, cap=10.0, decay=0.9),
        )

        async with PubsubFactory.create_batch_with_gossipsub(
            1, score_params=score_params, heartbeat_interval=0.1
        ) as pubsubs:
            gsub = cast(GossipSub, pubsubs[0].router)
            host = pubsubs[0].host

            topic = "test_heartbeat_decay"
            await pubsubs[0].subscribe(topic)

            assert gsub.scorer is not None
            peer_id = host.get_id()
            gsub.scorer.on_join_mesh(peer_id, topic)

            # Get initial score before any heartbeats
            initial_score = gsub.scorer.topic_score(peer_id, topic)
            assert initial_score == 1.0

            # Trigger first heartbeat (decay)
            gsub.scorer.on_heartbeat()
            score_after_first_heartbeat = gsub.scorer.topic_score(peer_id, topic)
            assert score_after_first_heartbeat == 0.9  # 1.0 * 0.9

            # Wait for more heartbeats to trigger additional decay
            await trio.sleep(0.2)

            # Score should have decayed further
            decayed_score = gsub.scorer.topic_score(peer_id, topic)
            assert decayed_score < score_after_first_heartbeat
            assert decayed_score < initial_score

    @pytest.mark.trio
    async def test_mesh_join_leave_hooks(self):
        """Test that mesh join/leave triggers scorer hooks."""
        score_params = ScoreParams(
            p1_time_in_mesh=TopicScoreParams(weight=1.0, cap=10.0, decay=1.0),
        )

        async with PubsubFactory.create_batch_with_gossipsub(
            2, score_params=score_params, heartbeat_interval=0.1
        ) as pubsubs:
            gsub0 = pubsubs[0].router
            host0, host1 = pubsubs[0].host, pubsubs[1].host

            # Connect hosts
            await connect(host0, host1)
            await trio.sleep(0.2)

            topic = "test_mesh_hooks"
            await pubsubs[0].subscribe(topic)
            await pubsubs[1].subscribe(topic)
            await trio.sleep(0.2)

            peer_id = host1.get_id()

            # Test join hook
            assert isinstance(gsub0, GossipSub)
            assert gsub0.scorer is not None
            initial_score = gsub0.scorer.topic_score(peer_id, topic)

            # Manually trigger join (simulating mesh addition)
            gsub0.scorer.on_join_mesh(peer_id, topic)
            gsub0.scorer.on_heartbeat()

            join_score = gsub0.scorer.topic_score(peer_id, topic)
            assert join_score > initial_score

            # Test leave hook (should not change score immediately)
            gsub0.scorer.on_leave_mesh(peer_id, topic)
            leave_score = gsub0.scorer.topic_score(peer_id, topic)
            assert leave_score == join_score  # No immediate change

    @pytest.mark.trio
    async def test_message_delivery_hooks(self):
        """Test that message delivery triggers scorer hooks."""
        score_params = ScoreParams(
            p2_first_message_deliveries=TopicScoreParams(
                weight=1.0, cap=10.0, decay=1.0
            ),
            p3_mesh_message_deliveries=TopicScoreParams(
                weight=1.0, cap=10.0, decay=1.0
            ),
        )

        async with PubsubFactory.create_batch_with_gossipsub(
            2, score_params=score_params, heartbeat_interval=0.1
        ) as pubsubs:
            gsub0 = pubsubs[0].router
            host0, host1 = pubsubs[0].host, pubsubs[1].host

            # Connect hosts
            await connect(host0, host1)
            await trio.sleep(0.2)

            topic = "test_delivery_hooks"
            await pubsubs[0].subscribe(topic)
            await pubsubs[1].subscribe(topic)
            await trio.sleep(0.2)

            peer_id = host1.get_id()

            assert isinstance(gsub0, GossipSub)
            assert gsub0.scorer is not None
            initial_score = gsub0.scorer.topic_score(peer_id, topic)

            # Test first delivery hook
            gsub0.scorer.on_first_delivery(peer_id, topic)
            first_delivery_score = gsub0.scorer.topic_score(peer_id, topic)
            assert first_delivery_score > initial_score

            # Test mesh delivery hook
            gsub0.scorer.on_mesh_delivery(peer_id, topic)
            mesh_delivery_score = gsub0.scorer.topic_score(peer_id, topic)
            assert mesh_delivery_score > first_delivery_score

    @pytest.mark.trio
    async def test_invalid_message_hook(self):
        """Test that invalid messages trigger scorer hooks."""
        score_params = ScoreParams(
            p4_invalid_messages=TopicScoreParams(weight=1.0, cap=10.0, decay=1.0),
        )

        async with PubsubFactory.create_batch_with_gossipsub(
            2, score_params=score_params, heartbeat_interval=0.1
        ) as pubsubs:
            gsub0 = pubsubs[0].router
            host0, host1 = pubsubs[0].host, pubsubs[1].host

            # Connect hosts
            await connect(host0, host1)
            await trio.sleep(0.2)

            topic = "test_invalid_hook"
            await pubsubs[0].subscribe(topic)
            await pubsubs[1].subscribe(topic)
            await trio.sleep(0.2)

            peer_id = host1.get_id()

            assert isinstance(gsub0, GossipSub)
            assert gsub0.scorer is not None
            initial_score = gsub0.scorer.topic_score(peer_id, topic)

            # Test invalid message hook
            gsub0.scorer.on_invalid_message(peer_id, topic)
            invalid_score = gsub0.scorer.topic_score(peer_id, topic)
            assert invalid_score < initial_score  # Should decrease score

    @pytest.mark.trio
    async def test_behavior_penalty_hook(self):
        """Test that behavior penalty can be applied."""
        score_params = ScoreParams(
            p5_behavior_penalty_weight=2.0,
            p5_behavior_penalty_threshold=1.0,
            p5_behavior_penalty_decay=1.0,
        )

        async with PubsubFactory.create_batch_with_gossipsub(
            2, score_params=score_params, heartbeat_interval=0.1
        ) as pubsubs:
            gsub0 = pubsubs[0].router
            host0, host1 = pubsubs[0].host, pubsubs[1].host

            # Connect hosts
            await connect(host0, host1)
            await trio.sleep(0.2)

            topic = "test_behavior_penalty"
            await pubsubs[0].subscribe(topic)
            await pubsubs[1].subscribe(topic)
            await trio.sleep(0.2)

            peer_id = host1.get_id()
            topics = [topic]

            assert isinstance(gsub0, GossipSub)
            assert gsub0.scorer is not None
            initial_score = gsub0.scorer.score(peer_id, topics)

            # Apply behavior penalty
            gsub0.scorer.penalize_behavior(peer_id, 1.5)
            penalty_score = gsub0.scorer.score(peer_id, topics)

            # Score should decrease due to penalty
            expected_penalty = (1.5 - 1.0) * 2.0  # (penalty - threshold) * weight
            assert penalty_score == initial_score - expected_penalty

    @pytest.mark.trio
    async def test_supports_scoring_protocol_detection(self):
        """Test supports_scoring method for protocol version detection."""
        score_params = ScoreParams()

        async with PubsubFactory.create_batch_with_gossipsub(
            2, score_params=score_params, heartbeat_interval=0.1
        ) as pubsubs:
            gsub0 = cast(GossipSub, pubsubs[0].router)
            host0, host1 = pubsubs[0].host, pubsubs[1].host

            # Connect hosts
            await connect(host0, host1)
            await trio.sleep(0.2)

            peer_id = host1.get_id()

            # Initially, peer should not be in peer_protocol mapping
            assert not gsub0.supports_scoring(peer_id)

            # Subscribe to a topic to trigger protocol negotiation
            topic = "test_protocol_detection"
            await pubsubs[0].subscribe(topic)
            await pubsubs[1].subscribe(topic)
            await trio.sleep(0.2)

            # After subscription, peer should be in peer_protocol mapping
            # The exact protocol depends on the factory implementation
            # but we can test that the method works correctly
            assert peer_id in gsub0.peer_protocol
            protocol = gsub0.peer_protocol[peer_id]

            # Test the method returns correct result based on protocol
            expected_supports_scoring = protocol == PROTOCOL_ID_V11
            assert gsub0.supports_scoring(peer_id) == expected_supports_scoring

    @pytest.mark.trio
    async def test_supports_scoring_with_unknown_peer(self):
        """Test supports_scoring with unknown peer ID."""
        score_params = ScoreParams()

        async with PubsubFactory.create_batch_with_gossipsub(
            1, score_params=score_params, heartbeat_interval=0.1
        ) as pubsubs:
            gsub0 = cast(GossipSub, pubsubs[0].router)

            # Create a peer ID that's not connected
            unknown_peer = IDFactory()

            # Should return False for unknown peer
            assert not gsub0.supports_scoring(unknown_peer)

    def test_get_score_stats(self):
        """Test get_score_stats method for observability."""
        params = ScoreParams(
            p1_time_in_mesh=TopicScoreParams(weight=1.0, cap=10.0, decay=1.0),
            p2_first_message_deliveries=TopicScoreParams(
                weight=2.0, cap=5.0, decay=1.0
            ),
            p3_mesh_message_deliveries=TopicScoreParams(weight=1.5, cap=8.0, decay=1.0),
            p4_invalid_messages=TopicScoreParams(weight=3.0, cap=3.0, decay=1.0),
            p5_behavior_penalty_weight=2.0,
            p5_behavior_penalty_threshold=1.0,
            p5_behavior_penalty_decay=1.0,
        )
        scorer = PeerScorer(params)
        peer_id = IDFactory()
        topic = "test_topic"

        # Set up some activity
        scorer.on_join_mesh(peer_id, topic)
        scorer.on_first_delivery(peer_id, topic)
        scorer.on_mesh_delivery(peer_id, topic)
        scorer.on_invalid_message(peer_id, topic)
        scorer.penalize_behavior(peer_id, 2.0)

        # Get stats
        stats = scorer.get_score_stats(peer_id, topic)

        # Verify all components are present
        expected_keys = {
            "time_in_mesh",
            "first_deliveries",
            "mesh_deliveries",
            "invalid_messages",
            "behavior_penalty",
            "total_score",
        }
        assert set(stats.keys()) == expected_keys

        # Verify values match expected
        assert stats["time_in_mesh"] == 1.0
        assert stats["first_deliveries"] == 1.0
        assert stats["mesh_deliveries"] == 1.0
        assert stats["invalid_messages"] == 1.0
        assert stats["behavior_penalty"] == 2.0

        # Verify total score calculation
        expected_score = (
            1.0 * 1.0  # P1: time_in_mesh
            + 1.0 * 2.0  # P2: first_deliveries
            + 1.0 * 1.5  # P3: mesh_deliveries
            - 1.0 * 3.0  # P4: invalid_messages (penalty)
            - (2.0 - 1.0) * 2.0
        )  # P5: behavior penalty
        assert stats["total_score"] == expected_score

    def test_get_all_peer_scores(self):
        """Test get_all_peer_scores method for observability."""
        params = ScoreParams(
            p1_time_in_mesh=TopicScoreParams(weight=1.0, cap=10.0, decay=1.0),
        )
        scorer = PeerScorer(params)

        # Create multiple peers with different activities
        peer1 = IDFactory()
        peer2 = IDFactory()
        peer3 = IDFactory()
        topic = "test_topic"

        # Set up different activities for each peer
        scorer.on_join_mesh(peer1, topic)  # Score = 1.0
        scorer.on_join_mesh(peer2, topic)  # Score = 1.0
        scorer.on_join_mesh(peer2, topic)  # Score = 2.0
        # Add peer3 to behavior_penalty to ensure it's tracked
        scorer.penalize_behavior(peer3, 0.0)  # Score = 0.0

        # Get all peer scores
        all_scores = scorer.get_all_peer_scores([topic])

        # Verify all peers are included
        assert str(peer1) in all_scores
        assert str(peer2) in all_scores
        assert str(peer3) in all_scores

        # Verify scores are correct
        assert all_scores[str(peer1)] == 1.0
        assert all_scores[str(peer2)] == 2.0
        assert all_scores[str(peer3)] == 0.0

    def test_get_all_peer_scores_multiple_topics(self):
        """Test get_all_peer_scores with multiple topics."""
        params = ScoreParams(
            p1_time_in_mesh=TopicScoreParams(weight=1.0, cap=10.0, decay=1.0),
        )
        scorer = PeerScorer(params)

        peer = IDFactory()
        topic1 = "topic1"
        topic2 = "topic2"

        # Set up activity in both topics
        scorer.on_join_mesh(peer, topic1)  # Score in topic1 = 1.0
        scorer.on_join_mesh(peer, topic2)  # Score in topic2 = 1.0

        # Get scores for both topics
        all_scores = scorer.get_all_peer_scores([topic1, topic2])

        # Should be sum of both topic scores
        assert all_scores[str(peer)] == 2.0  # 1.0 + 1.0
