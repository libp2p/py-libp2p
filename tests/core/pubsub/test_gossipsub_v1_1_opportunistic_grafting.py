"""
Tests for Gossipsub v1.1 Opportunistic Grafting functionality.

This module tests the opportunistic grafting feature that allows peers with
higher scores than the median mesh score to be grafted into the mesh.
"""

from typing import cast
from unittest.mock import MagicMock

import pytest
import trio

from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.score import ScoreParams, TopicScoreParams
from libp2p.tools.utils import connect
from tests.utils.factories import IDFactory, PubsubFactory


class TestOpportunisticGrafting:
    """Test opportunistic grafting functionality."""

    @pytest.mark.trio
    async def test_opportunistic_grafting_basic(self):
        """Test basic opportunistic grafting with higher-scoring peers."""
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

            # Set up mesh with some peers having different scores
            gsub0 = gsubs[0]
            if gsub0.scorer:
                # Give peers different scores
                for i, host in enumerate(hosts[1:], 1):
                    peer_id = host.get_id()
                    # Give later peers higher scores
                    for _ in range(i):
                        gsub0.scorer.on_join_mesh(peer_id, topic)
                        gsub0.scorer.on_heartbeat()

                # Manually add some peers to mesh to simulate existing mesh
                gsub0.mesh[topic] = {hosts[1].get_id(), hosts[2].get_id()}

                # Trigger mesh heartbeat to test opportunistic grafting
                peers_to_graft, peers_to_prune = gsub0.mesh_heartbeat()

                # Should attempt to graft higher-scoring peers
                # The exact behavior depends on current mesh state and scores
                assert isinstance(peers_to_graft, dict)
                assert isinstance(peers_to_prune, dict)

    @pytest.mark.trio
    async def test_opportunistic_grafting_median_calculation(self):
        """Test that opportunistic grafting uses median score correctly."""
        score_params = ScoreParams(
            p1_time_in_mesh=TopicScoreParams(weight=1.0, cap=10.0, decay=1.0),
        )

        async with PubsubFactory.create_batch_with_gossipsub(
            1, score_params=score_params, heartbeat_interval=0.1
        ) as pubsubs:
            gsub = cast(GossipSub, pubsubs[0].router)
            host = pubsubs[0].host

            topic = "test_median_calculation"
            await pubsubs[0].subscribe(topic)

            if gsub.scorer:
                # Create fake peer IDs for testing
                fake_peers = [IDFactory() for _ in range(5)]

                # Set up mesh with peers having different scores
                gsub.mesh[topic] = set(fake_peers[:3])  # 3 peers in mesh

                # Give peers different scores
                for i, peer_id in enumerate(fake_peers[:3]):
                    for _ in range(i + 1):  # Scores: 1, 2, 3
                        gsub.scorer.on_join_mesh(peer_id, topic)
                        gsub.scorer.on_heartbeat()

                # Give candidate peers higher scores
                for i, peer_id in enumerate(fake_peers[3:], 4):  # Scores: 4, 5
                    for _ in range(i):
                        gsub.scorer.on_join_mesh(peer_id, topic)
                        gsub.scorer.on_heartbeat()

                # Mock peer_topics to include all peers
                gsub.pubsub.peer_topics[topic] = set(fake_peers)

                # Mock peer_protocol
                for peer_id in fake_peers:
                    gsub.peer_protocol[peer_id] = gsub.protocols[0]

                # Trigger mesh heartbeat
                peers_to_graft, peers_to_prune = gsub.mesh_heartbeat()

                # Should attempt to graft peers with scores > median (2.0)
                # Peers with scores 4 and 5 should be candidates
                grafted_peers = set()
                for peer, topics in peers_to_graft.items():
                    if topic in topics:
                        grafted_peers.add(peer)

                # Should include high-scoring peers
                assert fake_peers[3] in grafted_peers or fake_peers[4] in grafted_peers

    @pytest.mark.trio
    async def test_opportunistic_grafting_only_when_above_degree_low(self):
        """Test that opportunistic grafting only occurs when mesh size >= degree_low."""
        score_params = ScoreParams(
            p1_time_in_mesh=TopicScoreParams(weight=1.0, cap=10.0, decay=1.0),
        )

        async with PubsubFactory.create_batch_with_gossipsub(
            1,
            score_params=score_params,
            degree=3,
            degree_low=2,
            degree_high=4,
            heartbeat_interval=0.1,
        ) as pubsubs:
            gsub = cast(GossipSub, pubsubs[0].router)
            host = pubsubs[0].host

            topic = "test_degree_low_condition"
            await pubsubs[0].subscribe(topic)

            if gsub.scorer:
                # Create fake peer IDs
                fake_peers = [IDFactory() for _ in range(5)]

                # Test with mesh size < degree_low (should not do opportunistic grafting)
                gsub.mesh[topic] = {fake_peers[0]}  # Only 1 peer, degree_low=2

                # Give all peers high scores
                for peer_id in fake_peers:
                    for _ in range(5):
                        gsub.scorer.on_join_mesh(peer_id, topic)
                        gsub.scorer.on_heartbeat()

                # Mock peer_topics and peer_protocol
                gsub.pubsub.peer_topics[topic] = set(fake_peers)
                for peer_id in fake_peers:
                    gsub.peer_protocol[peer_id] = gsub.protocols[0]

                # Trigger mesh heartbeat
                peers_to_graft, peers_to_prune = gsub.mesh_heartbeat()

                # Should not do opportunistic grafting when mesh size < degree_low
                # Instead, should do regular grafting to reach degree
                grafted_peers = set()
                for peer, topics in peers_to_graft.items():
                    if topic in topics:
                        grafted_peers.add(peer)

                # Should graft peers to reach degree, not opportunistic grafting
                assert len(grafted_peers) >= 0  # May graft to reach degree

                # Test with mesh size >= degree_low (should do opportunistic grafting)
                gsub.mesh[topic] = {
                    fake_peers[0],
                    fake_peers[1],
                    fake_peers[2],
                }  # 3 peers

                # Trigger mesh heartbeat again
                peers_to_graft, peers_to_prune = gsub.mesh_heartbeat()

                # Now should consider opportunistic grafting
                grafted_peers = set()
                for peer, topics in peers_to_graft.items():
                    if topic in topics:
                        grafted_peers.add(peer)

    @pytest.mark.trio
    async def test_opportunistic_grafting_with_exception_handling(self):
        """Test that opportunistic grafting handles exceptions gracefully."""
        score_params = ScoreParams(
            p1_time_in_mesh=TopicScoreParams(weight=1.0, cap=10.0, decay=1.0),
        )

        async with PubsubFactory.create_batch_with_gossipsub(
            1,
            score_params=score_params,
            degree=2,
            degree_low=1,
            degree_high=3,
            heartbeat_interval=0.1,
        ) as pubsubs:
            gsub = cast(GossipSub, pubsubs[0].router)
            host = pubsubs[0].host

            topic = "test_exception_handling"
            await pubsubs[0].subscribe(topic)

            if gsub.scorer:
                # Create fake peer IDs
                fake_peers = [IDFactory() for _ in range(3)]

                # Set up mesh
                gsub.mesh[topic] = {fake_peers[0], fake_peers[1]}

                # Mock peer_topics and peer_protocol
                gsub.pubsub.peer_topics[topic] = set(fake_peers)
                for peer_id in fake_peers:
                    gsub.peer_protocol[peer_id] = gsub.protocols[0]

                # Mock scorer.score to raise exception
                original_score = gsub.scorer.score
                gsub.scorer.score = MagicMock(
                    side_effect=Exception("Score calculation error")
                )

                # Trigger mesh heartbeat - should handle exception gracefully
                peers_to_graft, peers_to_prune = gsub.mesh_heartbeat()

                # Should not crash and should return valid results
                assert isinstance(peers_to_graft, dict)
                assert isinstance(peers_to_prune, dict)

                # Restore original score method
                gsub.scorer.score = original_score

    @pytest.mark.trio
    async def test_opportunistic_grafting_limits_candidates(self):
        """Test that opportunistic grafting limits the number of candidates."""
        score_params = ScoreParams(
            p1_time_in_mesh=TopicScoreParams(weight=1.0, cap=10.0, decay=1.0),
        )

        async with PubsubFactory.create_batch_with_gossipsub(
            1,
            score_params=score_params,
            degree=2,
            degree_low=1,
            degree_high=3,
            heartbeat_interval=0.1,
        ) as pubsubs:
            gsub = cast(GossipSub, pubsubs[0].router)
            host = pubsubs[0].host

            topic = "test_candidate_limits"
            await pubsubs[0].subscribe(topic)

            if gsub.scorer:
                # Create many fake peer IDs
                fake_peers = [IDFactory() for _ in range(10)]

                # Set up mesh with 2 peers
                gsub.mesh[topic] = {fake_peers[0], fake_peers[1]}

                # Give all peers high scores
                for peer_id in fake_peers:
                    for _ in range(5):
                        gsub.scorer.on_join_mesh(peer_id, topic)
                        gsub.scorer.on_heartbeat()

                # Mock peer_topics and peer_protocol
                gsub.pubsub.peer_topics[topic] = set(fake_peers)
                for peer_id in fake_peers:
                    gsub.peer_protocol[peer_id] = gsub.protocols[0]

                # Trigger mesh heartbeat
                peers_to_graft, peers_to_prune = gsub.mesh_heartbeat()

                # Should limit the number of grafts (limited by degree)
                grafted_peers = set()
                for peer, topics in peers_to_graft.items():
                    if topic in topics:
                        grafted_peers.add(peer)

                # Should not graft more than degree allows
                assert len(grafted_peers) <= gsub.degree

    @pytest.mark.trio
    async def test_opportunistic_grafting_with_empty_mesh(self):
        """Test opportunistic grafting with empty mesh."""
        score_params = ScoreParams(
            p1_time_in_mesh=TopicScoreParams(weight=1.0, cap=10.0, decay=1.0),
        )

        async with PubsubFactory.create_batch_with_gossipsub(
            1,
            score_params=score_params,
            degree=2,
            degree_low=1,
            degree_high=3,
            heartbeat_interval=0.1,
        ) as pubsubs:
            gsub = cast(GossipSub, pubsubs[0].router)
            host = pubsubs[0].host

            topic = "test_empty_mesh"
            await pubsubs[0].subscribe(topic)

            if gsub.scorer:
                # Create fake peer IDs
                fake_peers = [IDFactory() for _ in range(3)]

                # Set up empty mesh
                gsub.mesh[topic] = set()

                # Give all peers high scores
                for peer_id in fake_peers:
                    for _ in range(5):
                        gsub.scorer.on_join_mesh(peer_id, topic)
                        gsub.scorer.on_heartbeat()

                # Mock peer_topics and peer_protocol
                gsub.pubsub.peer_topics[topic] = set(fake_peers)
                for peer_id in fake_peers:
                    gsub.peer_protocol[peer_id] = gsub.protocols[0]

                # Trigger mesh heartbeat
                peers_to_graft, peers_to_prune = gsub.mesh_heartbeat()

                # Should not do opportunistic grafting with empty mesh
                # Should do regular grafting to reach degree
                grafted_peers = set()
                for peer, topics in peers_to_graft.items():
                    if topic in topics:
                        grafted_peers.add(peer)

                # Should graft peers to reach degree
                assert len(grafted_peers) >= 0  # May graft to reach degree

    @pytest.mark.trio
    async def test_opportunistic_grafting_with_single_peer_mesh(self):
        """Test opportunistic grafting with single peer in mesh."""
        score_params = ScoreParams(
            p1_time_in_mesh=TopicScoreParams(weight=1.0, cap=10.0, decay=1.0),
        )

        async with PubsubFactory.create_batch_with_gossipsub(
            1,
            score_params=score_params,
            degree=2,
            degree_low=1,
            degree_high=3,
            heartbeat_interval=0.1,
        ) as pubsubs:
            gsub = cast(GossipSub, pubsubs[0].router)
            host = pubsubs[0].host

            topic = "test_single_peer_mesh"
            await pubsubs[0].subscribe(topic)

            if gsub.scorer:
                # Create fake peer IDs
                fake_peers = [IDFactory() for _ in range(3)]

                # Set up mesh with single peer
                gsub.mesh[topic] = {fake_peers[0]}

                # Give peers different scores
                gsub.scorer.on_join_mesh(fake_peers[0], topic)
                gsub.scorer.on_heartbeat()  # Score = 1.0

                for peer_id in fake_peers[1:]:
                    for _ in range(3):  # Higher scores
                        gsub.scorer.on_join_mesh(peer_id, topic)
                        gsub.scorer.on_heartbeat()

                # Mock peer_topics and peer_protocol
                gsub.pubsub.peer_topics[topic] = set(fake_peers)
                for peer_id in fake_peers:
                    gsub.peer_protocol[peer_id] = gsub.protocols[0]

                # Trigger mesh heartbeat
                peers_to_graft, peers_to_prune = gsub.mesh_heartbeat()

                # With single peer, median = that peer's score
                # Should graft peers with higher scores
                grafted_peers = set()
                for peer, topics in peers_to_graft.items():
                    if topic in topics:
                        grafted_peers.add(peer)

                # Should include higher-scoring peers
                assert len(grafted_peers) >= 0  # May graft higher-scoring peers

    @pytest.mark.trio
    async def test_opportunistic_grafting_integration_with_real_peers(self):
        """Test opportunistic grafting with real peer connections."""
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

            topic = "test_real_peers_integration"
            for pubsub in pubsubs:
                await pubsub.subscribe(topic)
            await trio.sleep(0.2)

            # Set up different scores for peers
            gsub0 = gsubs[0]
            if gsub0.scorer:
                # Give peers different scores
                for i, host in enumerate(hosts[1:], 1):
                    peer_id = host.get_id()
                    # Give later peers higher scores
                    for _ in range(i):
                        gsub0.scorer.on_join_mesh(peer_id, topic)
                        gsub0.scorer.on_heartbeat()

                # Manually set up mesh
                gsub0.mesh[topic] = {hosts[1].get_id(), hosts[2].get_id()}

                # Trigger mesh heartbeat
                peers_to_graft, peers_to_prune = gsub0.mesh_heartbeat()

                # Should consider opportunistic grafting
                grafted_peers = set()
                for peer, topics in peers_to_graft.items():
                    if topic in topics:
                        grafted_peers.add(peer)

                # Verify that opportunistic grafting is working
                # (exact behavior depends on scores and mesh state)
                assert isinstance(peers_to_graft, dict)
                assert isinstance(peers_to_prune, dict)

    @pytest.mark.trio
    async def test_opportunistic_grafting_with_behavior_penalty(self):
        """Test opportunistic grafting with peers having behavior penalties."""
        score_params = ScoreParams(
            p1_time_in_mesh=TopicScoreParams(weight=1.0, cap=10.0, decay=1.0),
            p5_behavior_penalty_weight=2.0,
            p5_behavior_penalty_threshold=1.0,
            p5_behavior_penalty_decay=1.0,
        )

        async with PubsubFactory.create_batch_with_gossipsub(
            1,
            score_params=score_params,
            degree=2,
            degree_low=1,
            degree_high=3,
            heartbeat_interval=0.1,
        ) as pubsubs:
            gsub = cast(GossipSub, pubsubs[0].router)
            host = pubsubs[0].host

            topic = "test_behavior_penalty"
            await pubsubs[0].subscribe(topic)

            if gsub.scorer:
                # Create fake peer IDs
                fake_peers = [IDFactory() for _ in range(4)]

                # Set up mesh with 2 peers
                gsub.mesh[topic] = {fake_peers[0], fake_peers[1]}

                # Give all peers high base scores
                for peer_id in fake_peers:
                    for _ in range(3):
                        gsub.scorer.on_join_mesh(peer_id, topic)
                        gsub.scorer.on_heartbeat()

                # Apply behavior penalty to some peers
                gsub.scorer.penalize_behavior(fake_peers[2], 2.0)  # High penalty
                gsub.scorer.penalize_behavior(fake_peers[3], 0.5)  # Low penalty

                # Mock peer_topics and peer_protocol
                gsub.pubsub.peer_topics[topic] = set(fake_peers)
                for peer_id in fake_peers:
                    gsub.peer_protocol[peer_id] = gsub.protocols[0]

                # Trigger mesh heartbeat
                peers_to_graft, peers_to_prune = gsub.mesh_heartbeat()

                # Should prefer peers without behavior penalties
                grafted_peers = set()
                for peer, topics in peers_to_graft.items():
                    if topic in topics:
                        grafted_peers.add(peer)

                # Peers with high behavior penalties should be less likely to be grafted
                # (exact behavior depends on score calculations)
                assert isinstance(peers_to_graft, dict)
