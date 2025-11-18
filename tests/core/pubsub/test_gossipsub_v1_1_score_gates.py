"""
Tests for Gossipsub v1.1 Score-based Gates functionality.

This module tests the score-based gates that control publish acceptance,
gossip emission, peer exchange (PX) acceptance, and graylisting in GossipSub v1.1.
"""

from typing import cast
from unittest.mock import AsyncMock

import pytest
import trio

from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pb import rpc_pb2
from libp2p.pubsub.score import PeerScorer, ScoreParams, TopicScoreParams
from libp2p.tools.utils import connect
from tests.utils.factories import IDFactory, PubsubFactory


class TestScoreGates:
    """Test score-based gates functionality."""

    @pytest.mark.trio
    async def test_publish_gate_blocks_low_scoring_peers(self):
        """Test that publish gate blocks peers with scores below threshold."""
        score_params = ScoreParams(
            publish_threshold=1.0,  # High threshold
            p1_time_in_mesh=TopicScoreParams(weight=1.0, cap=10.0, decay=1.0),
        )

        async with PubsubFactory.create_batch_with_gossipsub(
            2, score_params=score_params, heartbeat_interval=0.1
        ) as pubsubs:
            gsub0, gsub1 = (cast(GossipSub, ps.router) for ps in pubsubs)
            host0, host1 = (ps.host for ps in pubsubs)

            # Connect hosts
            await connect(host0, host1)
            await trio.sleep(0.2)

            topic = "test_publish_gate"
            await pubsubs[0].subscribe(topic)
            await pubsubs[1].subscribe(topic)
            await trio.sleep(0.2)

            # Mock write_msg to capture sent messages
            mock_write_msg = AsyncMock()
            if gsub0.pubsub is not None:
                gsub0.pubsub.write_msg = mock_write_msg

            # Create a message to publish
            msg = rpc_pb2.Message(
                data=b"test_message",
                topicIDs=[topic],
                from_id=host0.get_id().to_bytes(),
                seqno=b"1",
            )

            # Initially, peer should have low score and be blocked
            peer_id = host1.get_id()

            # Ensure scorer exists and reset any existing scores
            assert gsub0.scorer is not None, "Scorer should not be None"
            scorer = gsub0.scorer

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

            # Now test that peer is blocked
            assert not scorer.allow_publish(peer_id, [topic]), (
                "Peer with low score should not be allowed to publish"
            )

            # Publish message - should be blocked for low-scoring peer
            await gsub0.publish(host0.get_id(), msg)

            # Verify that no message was sent to the low-scoring peer
            mock_write_msg.assert_not_called()

            # Increase peer's score
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

            # Publish message again - should now be sent
            await gsub0.publish(host0.get_id(), msg)

            # Verify that message was sent
            mock_write_msg.assert_called()

    @pytest.mark.trio
    async def test_gossip_gate_filters_peers(self):
        """Test that gossip gate filters peers for gossip emission."""
        score_params = ScoreParams(
            gossip_threshold=0.5,  # Threshold between 0.0 and 1.0
            p1_time_in_mesh=TopicScoreParams(weight=1.0, cap=10.0, decay=1.0),
        )

        async with PubsubFactory.create_batch_with_gossipsub(
            3, score_params=score_params, heartbeat_interval=0.1
        ) as pubsubs:
            hosts = [ps.host for ps in pubsubs]
            gsubs = [cast(GossipSub, ps.router) for ps in pubsubs]

            # Connect all hosts
            for i in range(len(hosts)):
                for j in range(i + 1, len(hosts)):
                    await connect(hosts[i], hosts[j])
            await trio.sleep(0.2)

            topic = "test_gossip_gate"
            for pubsub in pubsubs:
                await pubsub.subscribe(topic)
            await trio.sleep(0.2)

            # Test gossip filtering in _get_peers_to_send
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

            # Initially both peers should have score 0.0 and be filtered out
            if gsub0.scorer:
                scorer = cast(PeerScorer, gsub0.scorer)
                assert not scorer.allow_gossip(peer1_id, [topic])
                assert not scorer.allow_gossip(peer2_id, [topic])

                # Increase peer1's score by adding time in mesh
                scorer.on_join_mesh(peer1_id, topic)  # Now score = 1.0
                # Don't call heartbeat to avoid decay

                # Only peer1 should be allowed for gossip now (score 1.0 >= 0.5)
                assert scorer.allow_gossip(peer1_id, [topic])
                assert not scorer.allow_gossip(peer2_id, [topic])

                # Add peer1 back to mesh so it can be selected by _get_peers_to_send
                if topic not in gsub0.mesh:
                    gsub0.mesh[topic] = set()
                gsub0.mesh[topic].add(peer1_id)

            # Test that _get_peers_to_send respects gossip gate
            # Use peer2 as msg_forwarder and origin so peer1 doesn't get excluded
            peers_to_send = list(gsub0._get_peers_to_send([topic], peer2_id, peer2_id))

            # Should include peer1 (high score) but not peer2 (low score)
            if gsub0.scorer:
                assert peer1_id in peers_to_send
                assert peer2_id not in peers_to_send

    @pytest.mark.trio
    async def test_graylist_gate_blocks_misbehaving_peers(self):
        """Test that graylist gate blocks peers with very low scores."""
        score_params = ScoreParams(
            graylist_threshold=-0.5,
            p4_invalid_messages=TopicScoreParams(weight=1.0, cap=10.0, decay=1.0),
        )

        async with PubsubFactory.create_batch_with_gossipsub(
            2, score_params=score_params, heartbeat_interval=0.1
        ) as pubsubs:
            gsub0, gsub1 = (cast(GossipSub, ps.router) for ps in pubsubs)
            host0, host1 = (ps.host for ps in pubsubs)

            # Connect hosts
            await connect(host0, host1)
            await trio.sleep(0.2)

            topic = "test_graylist_gate"
            await pubsubs[0].subscribe(topic)
            await pubsubs[1].subscribe(topic)
            await trio.sleep(0.2)

            peer_id = host1.get_id()

            # Initially peer should not be graylisted
            if gsub0.scorer:
                assert not gsub0.scorer.is_graylisted(peer_id, [topic])

                # Simulate invalid messages to trigger graylist
                gsub0.scorer.on_invalid_message(peer_id, topic)
                gsub0.scorer.on_invalid_message(peer_id, topic)

                # Peer should now be graylisted
                assert gsub0.scorer.is_graylisted(peer_id, [topic])

            # Test that graylisted peers are excluded from gossip
            peers_to_send = list(gsub0._get_peers_to_send([topic], peer_id, peer_id))
            assert peer_id not in peers_to_send

    @pytest.mark.trio
    async def test_px_gate_controls_peer_exchange(self):
        """Test that PX gate controls peer exchange acceptance."""
        score_params = ScoreParams(
            accept_px_threshold=0.3,
            p1_time_in_mesh=TopicScoreParams(weight=1.0, cap=10.0, decay=1.0),
        )

        async with PubsubFactory.create_batch_with_gossipsub(
            2, score_params=score_params, do_px=True, heartbeat_interval=0.1
        ) as pubsubs:
            gsub0, gsub1 = (cast(GossipSub, ps.router) for ps in pubsubs)
            host0, host1 = (ps.host for ps in pubsubs)

            # Connect hosts
            await connect(host0, host1)
            await trio.sleep(0.2)

            topic = "test_px_gate"
            await pubsubs[0].subscribe(topic)
            await pubsubs[1].subscribe(topic)
            await trio.sleep(0.2)

            peer_id = host1.get_id()

            # Remove peer from mesh to reset their score to 0.0
            if topic in gsub0.mesh:
                gsub0.mesh[topic].discard(peer_id)
            # Reset their time_in_mesh score
            if gsub0.scorer is not None:
                scorer = cast(PeerScorer, gsub0.scorer)
                scorer.time_in_mesh[peer_id][topic] = 0.0

            # Initially peer should not be allowed for PX
            if gsub0.scorer:
                assert not gsub0.scorer.allow_px_from(peer_id, [topic])

            # Mock _do_px to capture calls
            mock_do_px = AsyncMock()
            gsub0._do_px = mock_do_px

            # Create prune message with PX peers
            prune_msg = rpc_pb2.ControlPrune(topicID=topic)
            px_peer = rpc_pb2.PeerInfo()
            px_peer.peerID = IDFactory().to_bytes()
            prune_msg.peers.append(px_peer)

            # Handle prune - should not trigger PX due to low score
            await gsub0.handle_prune(prune_msg, peer_id)
            mock_do_px.assert_not_called()

            # Increase peer's score
            if gsub0.scorer:
                scorer.on_join_mesh(peer_id, topic)
                # Don't call heartbeat to avoid decay
                assert scorer.allow_px_from(peer_id, [topic])

            # Handle prune again - should now trigger PX
            await gsub0.handle_prune(prune_msg, peer_id)
            mock_do_px.assert_called_once()

    @pytest.mark.trio
    async def test_graft_gate_blocks_graylisted_peers(self):
        """Test that GRAFT gate blocks graylisted peers."""
        score_params = ScoreParams(
            graylist_threshold=-0.5,
            p4_invalid_messages=TopicScoreParams(weight=1.0, cap=10.0, decay=1.0),
        )

        async with PubsubFactory.create_batch_with_gossipsub(
            2, score_params=score_params, heartbeat_interval=0.1
        ) as pubsubs:
            gsub0, gsub1 = (cast(GossipSub, ps.router) for ps in pubsubs)
            host0, host1 = (ps.host for ps in pubsubs)

            # Connect hosts
            await connect(host0, host1)
            await trio.sleep(0.2)

            topic = "test_graft_gate"
            await pubsubs[0].subscribe(topic)
            await pubsubs[1].subscribe(topic)
            await trio.sleep(0.2)

            peer_id = host1.get_id()

            # Remove peer from mesh if it was added during subscription
            if topic in gsub0.mesh and peer_id in gsub0.mesh[topic]:
                gsub0.mesh[topic].remove(peer_id)

            # Make peer graylisted
            if gsub0.scorer:
                gsub0.scorer.on_invalid_message(peer_id, topic)
                gsub0.scorer.on_invalid_message(peer_id, topic)
                assert gsub0.scorer.is_graylisted(peer_id, [topic])

            # Mock emit_prune to capture calls
            mock_emit_prune = AsyncMock()
            gsub0.emit_prune = mock_emit_prune

            # Create graft message
            graft_msg = rpc_pb2.ControlGraft(topicID=topic)

            # Handle graft - should be rejected and emit prune
            await gsub0.handle_graft(graft_msg, peer_id)
            mock_emit_prune.assert_called_once_with(topic, peer_id, False, False)

            # Verify that peer was not added to mesh
            assert peer_id not in gsub0.mesh.get(topic, set())

    @pytest.mark.trio
    async def test_score_gates_with_multiple_topics(self):
        """Test score gates with multiple topics."""
        score_params = ScoreParams(
            publish_threshold=0.5,
            gossip_threshold=0.3,
            p1_time_in_mesh=TopicScoreParams(weight=1.0, cap=10.0, decay=1.0),
        )

        async with PubsubFactory.create_batch_with_gossipsub(
            2, score_params=score_params, heartbeat_interval=0.1
        ) as pubsubs:
            gsub0, gsub1 = (cast(GossipSub, ps.router) for ps in pubsubs)
            host0, host1 = (ps.host for ps in pubsubs)

            # Connect hosts
            await connect(host0, host1)
            await trio.sleep(0.2)

            topics = ["topic1", "topic2"]
            for topic in topics:
                await pubsubs[0].subscribe(topic)
                await pubsubs[1].subscribe(topic)
            await trio.sleep(0.2)

            peer_id = host1.get_id()

            # Test with mixed topic scores
            # Ensure scorer exists
            assert gsub0.scorer is not None, "Scorer should not be None"
            scorer = gsub0.scorer

            # Reset any existing scores to ensure clean state
            if peer_id in scorer.time_in_mesh:
                for topic in list(scorer.time_in_mesh[peer_id].keys()):
                    scorer.time_in_mesh[peer_id][topic] = 0.0

            # Explicitly set topic1 score high and keep topic2 score at 0
            scorer.on_join_mesh(peer_id, "topic1")
            scorer.on_join_mesh(peer_id, "topic1")  # Add more score

            # Verify the scores are as expected before testing gates
            topic1_score = scorer.topic_score(peer_id, "topic1")
            topic2_score = scorer.topic_score(peer_id, "topic2")

            # Ensure topic1 score is above threshold and topic2 is below
            assert topic1_score >= score_params.publish_threshold, (
                f"Topic1 score {topic1_score} should be >= "
                f"{score_params.publish_threshold}"
            )
            assert topic2_score < score_params.publish_threshold, (
                f"Topic2 score {topic2_score} should be < "
                f"{score_params.publish_threshold}"
            )

            # Now test the gates with the verified scores
            # Test publish gate
            assert scorer.allow_publish(peer_id, ["topic1"]), (
                "Should allow publish for topic1 with high score"
            )
            assert not scorer.allow_publish(peer_id, ["topic2"]), (
                "Should not allow publish for topic2 with low score"
            )

            # Test combined score (should be above threshold)
            combined_score = scorer.score(peer_id, topics)
            assert combined_score >= score_params.publish_threshold, (
                f"Combined score {combined_score} should be >= "
                f"{score_params.publish_threshold}"
            )
            assert scorer.allow_publish(peer_id, topics), (
                "Should allow publish for combined topics"
            )

            # Test gossip gate
            assert scorer.allow_gossip(peer_id, ["topic1"]), (
                "Should allow gossip for topic1 with high score"
            )
            assert not scorer.allow_gossip(peer_id, ["topic2"]), (
                "Should not allow gossip for topic2 with low score"
            )
            assert scorer.allow_gossip(peer_id, topics), (
                "Should allow gossip for combined topics"
            )

    @pytest.mark.trio
    async def test_score_gates_with_behavior_penalty(self):
        """Test score gates with behavior penalty."""
        score_params = ScoreParams(
            publish_threshold=0.0,
            gossip_threshold=-1.0,
            p5_behavior_penalty_weight=2.0,
            p5_behavior_penalty_threshold=1.0,
            p5_behavior_penalty_decay=1.0,
        )

        async with PubsubFactory.create_batch_with_gossipsub(
            2, score_params=score_params, heartbeat_interval=0.1
        ) as pubsubs:
            gsub0, gsub1 = (cast(GossipSub, ps.router) for ps in pubsubs)
            host0, host1 = (ps.host for ps in pubsubs)

            # Connect hosts
            await connect(host0, host1)
            await trio.sleep(0.2)

            topic = "test_behavior_penalty_gates"
            await pubsubs[0].subscribe(topic)
            await pubsubs[1].subscribe(topic)
            await trio.sleep(0.2)

            peer_id = host1.get_id()
            topics = [topic]

            # Initially peer should pass gates
            if gsub0.scorer:
                assert gsub0.scorer.allow_publish(peer_id, topics)
                assert gsub0.scorer.allow_gossip(peer_id, topics)

                # Apply behavior penalty
                gsub0.scorer.penalize_behavior(peer_id, 2.0)  # Total penalty = 2.0

                # Score should now be negative due to penalty
                score = gsub0.scorer.score(peer_id, topics)
                expected_penalty = (2.0 - 1.0) * 2.0  # (penalty - threshold) * weight
                assert score == -expected_penalty

                # Gates should now block the peer
                assert not gsub0.scorer.allow_publish(peer_id, topics)
                assert not gsub0.scorer.allow_gossip(peer_id, topics)

    @pytest.mark.trio
    async def test_score_gates_edge_cases(self):
        """Test score gates with edge cases."""
        # Test with infinite thresholds
        score_params = ScoreParams(
            publish_threshold=float("inf"),
            gossip_threshold=float("-inf"),
            graylist_threshold=float("-inf"),
            accept_px_threshold=float("inf"),
        )

        async with PubsubFactory.create_batch_with_gossipsub(
            2, score_params=score_params, heartbeat_interval=0.1
        ) as pubsubs:
            gsub0, gsub1 = (cast(GossipSub, ps.router) for ps in pubsubs)
            host0, host1 = (ps.host for ps in pubsubs)

            # Connect hosts
            await connect(host0, host1)
            await trio.sleep(0.2)

            topic = "test_edge_cases"
            await pubsubs[0].subscribe(topic)
            await pubsubs[1].subscribe(topic)
            await trio.sleep(0.2)

            peer_id = host1.get_id()
            topics = [topic]

            if gsub0.scorer:
                # With infinite publish threshold, no peer should be allowed
                assert not gsub0.scorer.allow_publish(peer_id, topics)

                # With negative infinite gossip threshold, all peers should be allowed
                assert gsub0.scorer.allow_gossip(peer_id, topics)

                # With negative infinite graylist threshold
                # (should never happen in practice)
                # no peer should be graylisted
                assert not gsub0.scorer.is_graylisted(peer_id, topics)

                # With infinite PX threshold, no peer should be allowed for PX
                assert not gsub0.scorer.allow_px_from(peer_id, topics)

    @pytest.mark.trio
    async def test_score_gates_with_zero_weights(self):
        """Test score gates with zero weights (disabled components)."""
        score_params = ScoreParams(
            publish_threshold=0.0,
            p1_time_in_mesh=TopicScoreParams(weight=0.0, cap=10.0, decay=1.0),
            p2_first_message_deliveries=TopicScoreParams(
                weight=0.0, cap=10.0, decay=1.0
            ),
            p3_mesh_message_deliveries=TopicScoreParams(
                weight=0.0, cap=10.0, decay=1.0
            ),
            p4_invalid_messages=TopicScoreParams(weight=0.0, cap=10.0, decay=1.0),
        )

        async with PubsubFactory.create_batch_with_gossipsub(
            2, score_params=score_params, heartbeat_interval=0.1
        ) as pubsubs:
            gsub0, gsub1 = (cast(GossipSub, ps.router) for ps in pubsubs)
            host0, host1 = (ps.host for ps in pubsubs)

            # Connect hosts
            await connect(host0, host1)
            await trio.sleep(0.2)

            topic = "test_zero_weights"
            await pubsubs[0].subscribe(topic)
            await pubsubs[1].subscribe(topic)
            await trio.sleep(0.2)

            peer_id = host1.get_id()
            topics = [topic]

            if gsub0.scorer:
                # With zero weights, all activities should result in zero score
                gsub0.scorer.on_join_mesh(peer_id, topic)
                gsub0.scorer.on_first_delivery(peer_id, topic)
                gsub0.scorer.on_mesh_delivery(peer_id, topic)
                gsub0.scorer.on_invalid_message(peer_id, topic)

                score = gsub0.scorer.score(peer_id, topics)
                assert score == 0.0

                # With zero score and zero threshold, peer should be allowed
                assert gsub0.scorer.allow_publish(peer_id, topics)

    @pytest.mark.trio
    async def test_score_gates_integration_with_mesh_management(self):
        """Test score gates integration with mesh management."""
        score_params = ScoreParams(
            graylist_threshold=-0.5,
            p4_invalid_messages=TopicScoreParams(weight=1.0, cap=10.0, decay=1.0),
        )

        async with PubsubFactory.create_batch_with_gossipsub(
            3,
            score_params=score_params,
            degree=2,
            degree_low=1,
            degree_high=3,
            heartbeat_interval=0.1,
        ) as pubsubs:
            hosts = [ps.host for ps in pubsubs]
            gsubs = [cast(GossipSub, ps.router) for ps in pubsubs]

            # Connect all hosts
            for i in range(len(hosts)):
                for j in range(i + 1, len(hosts)):
                    await connect(hosts[i], hosts[j])
            await trio.sleep(0.2)

            topic = "test_mesh_integration"
            for pubsub in pubsubs:
                await pubsub.subscribe(topic)
            await trio.sleep(0.2)

            # Test that graylisted peers are excluded from mesh management
            gsub0 = gsubs[0]
            peer1_id = hosts[1].get_id()
            peer2_id = hosts[2].get_id()

            if gsub0.scorer:
                # Graylist peer2
                gsub0.scorer.on_invalid_message(peer2_id, topic)
                gsub0.scorer.on_invalid_message(peer2_id, topic)
                assert gsub0.scorer.is_graylisted(peer2_id, [topic])

            # Test mesh heartbeat - should not include graylisted peers
            peers_to_graft, peers_to_prune = gsub0.mesh_heartbeat()

            # Graylisted peer should not be in peers_to_graft
            if gsub0.scorer:
                assert peer2_id not in peers_to_graft
                # Non-graylisted peer might be in peers_to_graft
                if peer1_id in peers_to_graft:
                    assert not gsub0.scorer.is_graylisted(peer1_id, [topic])

    @pytest.mark.trio
    async def test_score_gates_with_decay_over_time(self):
        """Test score gates behavior as scores decay over time."""
        score_params = ScoreParams(
            publish_threshold=0.5,
            p1_time_in_mesh=TopicScoreParams(weight=1.0, cap=10.0, decay=0.8),
            p2_first_message_deliveries=TopicScoreParams(
                weight=0.0, cap=0.0, decay=1.0
            ),
            p3_mesh_message_deliveries=TopicScoreParams(weight=0.0, cap=0.0, decay=1.0),
            p4_invalid_messages=TopicScoreParams(weight=0.0, cap=0.0, decay=1.0),
            p5_behavior_penalty_weight=0.0,
            p5_behavior_penalty_decay=1.0,
            p5_behavior_penalty_threshold=0.0,
            p6_appl_slack_weight=0.0,
            p6_appl_slack_decay=1.0,
            p7_ip_colocation_weight=0.0,
        )

        async with PubsubFactory.create_batch_with_gossipsub(
            2, score_params=score_params, heartbeat_interval=0.1
        ) as pubsubs:
            gsub0, gsub1 = (cast(GossipSub, ps.router) for ps in pubsubs)
            host0, host1 = (ps.host for ps in pubsubs)

            # Connect hosts
            await connect(host0, host1)
            await trio.sleep(0.2)

            topic = "test_decay_gates"
            await pubsubs[0].subscribe(topic)
            await pubsubs[1].subscribe(topic)
            await trio.sleep(0.2)

            peer_id = host1.get_id()
            topics = [topic]

            if gsub0.scorer:
                # Give peer high initial score
                gsub0.scorer.on_join_mesh(peer_id, topic)
                gsub0.scorer.on_heartbeat()
                gsub0.scorer.on_join_mesh(peer_id, topic)
                gsub0.scorer.on_heartbeat()  # Score = 2.0

                # Peer should initially pass gates
                assert gsub0.scorer.allow_publish(peer_id, topics)

                # Apply decay multiple times
                for _ in range(
                    7
                ):  # Use 7 heartbeats so 2.0 * 0.8**7 < 0.5 on all platforms
                    gsub0.scorer.on_heartbeat()

                # Score should have decayed below threshold
                score = gsub0.scorer.score(peer_id, topics)
                assert score < 0.5, f"Score {score} should be below 0.5 after decay"

                # Peer should now be blocked by gates
                assert not gsub0.scorer.allow_publish(peer_id, topics)
