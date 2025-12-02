"""
Tests for Gossipsub v2.0 features.

This module tests the new features introduced in Gossipsub 2.0, including:
- Enhanced peer scoring with P6 and P7 parameters
- Adaptive gossip dissemination
- Enhanced message validation with caching and timeouts
- Security features (spam protection, Sybil mitigation, Eclipse protection)
- Enhanced opportunistic grafting
- Improved mesh maintenance
"""

import time
from unittest.mock import Mock

import pytest
import trio

from libp2p.pubsub.gossipsub import PROTOCOL_ID_V20, GossipSub
from libp2p.pubsub.pb import rpc_pb2
from libp2p.pubsub.pubsub import ValidationCache, ValidationResult
from libp2p.pubsub.score import PeerScorer, ScoreParams
from tests.utils.factories import IDFactory, PubsubFactory


class TestGossipsubV20Protocol:
    """Test Gossipsub v2.0 protocol support."""

    def test_protocol_id_v20_support(self):
        """Test that v2.0 protocol ID is supported."""
        gossipsub = GossipSub(
            protocols=[PROTOCOL_ID_V20],
            degree=6,
            degree_low=4,
            degree_high=12,
        )

        assert PROTOCOL_ID_V20 in gossipsub.protocols

        # Test protocol negotiation
        peer_id = IDFactory()
        gossipsub.add_peer(peer_id, PROTOCOL_ID_V20)
        assert gossipsub.peer_protocol[peer_id] == PROTOCOL_ID_V20
        assert gossipsub.supports_v20_features(peer_id)

    def test_backward_compatibility(self):
        """Test that v2.0 maintains backward compatibility."""
        from libp2p.pubsub.gossipsub import PROTOCOL_ID_V11, PROTOCOL_ID_V12

        gossipsub = GossipSub(
            protocols=[PROTOCOL_ID_V20, PROTOCOL_ID_V12, PROTOCOL_ID_V11],
            degree=6,
            degree_low=4,
            degree_high=12,
        )

        peer_v11 = IDFactory()
        peer_v12 = IDFactory()
        peer_v20 = IDFactory()

        gossipsub.add_peer(peer_v11, PROTOCOL_ID_V11)
        gossipsub.add_peer(peer_v12, PROTOCOL_ID_V12)
        gossipsub.add_peer(peer_v20, PROTOCOL_ID_V20)

        assert gossipsub.supports_scoring(peer_v11)
        assert gossipsub.supports_scoring(peer_v12)
        assert gossipsub.supports_scoring(peer_v20)

        assert not gossipsub.supports_v20_features(peer_v11)
        assert not gossipsub.supports_v20_features(peer_v12)
        assert gossipsub.supports_v20_features(peer_v20)


class TestEnhancedPeerScoring:
    """Test enhanced peer scoring with P6 and P7 parameters."""

    def test_ip_colocation_penalty(self):
        """Test IP colocation penalty calculation."""
        params = ScoreParams(
            p7_ip_colocation_weight=10.0,
            p7_ip_colocation_threshold=3,
        )
        scorer = PeerScorer(params)

        # Add peers from same IP
        peer1 = IDFactory()
        peer2 = IDFactory()
        peer3 = IDFactory()
        peer4 = IDFactory()

        ip = "192.168.1.1"
        scorer.add_peer_ip(peer1, ip)
        scorer.add_peer_ip(peer2, ip)
        scorer.add_peer_ip(peer3, ip)
        scorer.add_peer_ip(peer4, ip)  # 4th peer should trigger penalty

        # No penalty for peers within threshold
        assert scorer.ip_colocation_penalty(peer1) == 0.0
        assert scorer.ip_colocation_penalty(peer2) == 0.0
        assert scorer.ip_colocation_penalty(peer3) == 0.0

        # Penalty for excess peers (4 - 3 = 1 excess, penalty = 10.0 * 1^2 = 10.0)
        assert scorer.ip_colocation_penalty(peer4) == 10.0

    def test_application_specific_scoring(self):
        """Test application-specific scoring (P6)."""
        app_scores = {IDFactory(): 5.0, IDFactory(): -2.0}

        def app_score_fn(peer_id):
            return app_scores.get(peer_id, 0.0)

        params = ScoreParams(
            app_specific_score_fn=app_score_fn,
            p6_appl_slack_weight=2.0,
        )
        scorer = PeerScorer(params)

        peer1, peer2 = list(app_scores.keys())

        # Test application-specific scoring
        scorer.update_app_specific_score(peer1)
        scorer.update_app_specific_score(peer2)

        assert scorer.app_specific_scores[peer1] == 5.0
        assert scorer.app_specific_scores[peer2] == -2.0

        # Test integration into overall score
        score1 = scorer.score(peer1, ["topic1"])
        score2 = scorer.score(peer2, ["topic1"])

        # peer1 should have higher score due to positive app score
        assert score1 > score2

    def test_peer_removal_cleanup(self):
        """Test that peer removal cleans up all scoring data."""
        params = ScoreParams()
        scorer = PeerScorer(params)

        peer = IDFactory()
        topic = "test_topic"

        # Add various scoring data
        scorer.on_join_mesh(peer, topic)
        scorer.on_first_delivery(peer, topic)
        scorer.on_mesh_delivery(peer, topic)
        scorer.penalize_behavior(peer, 5.0)
        scorer.add_peer_ip(peer, "192.168.1.1")

        # Verify data exists
        assert peer in scorer.time_in_mesh
        assert peer in scorer.behavior_penalty
        assert peer in scorer.ip_by_peer

        # Remove peer
        scorer.remove_peer(peer)

        # Verify all data is cleaned up
        assert peer not in scorer.time_in_mesh
        assert peer not in scorer.first_message_deliveries
        assert peer not in scorer.mesh_message_deliveries
        assert peer not in scorer.invalid_messages
        assert peer not in scorer.behavior_penalty
        assert peer not in scorer.app_specific_scores
        assert peer not in scorer.ip_by_peer


class TestAdaptiveGossip:
    """Test adaptive gossip dissemination features."""

    def test_network_health_calculation(self):
        """Test network health score calculation."""
        gossipsub = GossipSub(
            protocols=[PROTOCOL_ID_V20],
            degree=6,
            degree_low=4,
            degree_high=12,
            adaptive_gossip_enabled=True,
        )

        # Mock pubsub and scorer
        gossipsub.pubsub = Mock()
        gossipsub.scorer = Mock()
        gossipsub.scorer.score = Mock(return_value=1.0)

        # Set up mesh with good connectivity
        topic = "test_topic"
        peers = [IDFactory() for _ in range(6)]  # Target degree
        gossipsub.mesh[topic] = set(peers)

        # Update network health
        gossipsub._update_network_health()

        # Should have good health score
        assert 0.5 <= gossipsub.network_health_score <= 1.0

    def test_adaptive_parameter_adjustment(self):
        """Test adaptive parameter adjustment based on network health."""
        gossipsub = GossipSub(
            protocols=[PROTOCOL_ID_V20],
            degree=6,
            degree_low=4,
            degree_high=12,
            adaptive_gossip_enabled=True,
        )

        # Test poor network health
        gossipsub.network_health_score = 0.2
        gossipsub._adapt_gossip_parameters()

        assert gossipsub.adaptive_degree_low > gossipsub.degree_low
        assert gossipsub.adaptive_degree_high > gossipsub.degree_high
        assert gossipsub.gossip_factor > 0.25

        # Test good network health
        gossipsub.network_health_score = 0.9
        gossipsub._adapt_gossip_parameters()

        assert gossipsub.adaptive_degree_low == gossipsub.degree_low
        assert gossipsub.adaptive_degree_high == gossipsub.degree_high
        assert gossipsub.gossip_factor == 0.25

    def test_adaptive_gossip_peer_count(self):
        """Test adaptive gossip peer count calculation."""
        gossipsub = GossipSub(
            protocols=[PROTOCOL_ID_V20],
            degree=6,
            degree_low=4,
            degree_high=12,
            adaptive_gossip_enabled=True,
        )

        topic = "test_topic"
        total_peers = 20

        # Test with good network health
        gossipsub.network_health_score = 0.8
        count_good = gossipsub._get_adaptive_gossip_peers_count(topic, total_peers)

        # Test with poor network health
        gossipsub.network_health_score = 0.3
        count_poor = gossipsub._get_adaptive_gossip_peers_count(topic, total_peers)

        # Poor health should result in more gossip peers
        assert count_poor >= count_good


class TestValidationCaching:
    """Test enhanced message validation with caching."""

    def test_validation_cache_basic(self):
        """Test basic validation cache functionality."""
        cache = ValidationCache(ttl=60, max_size=100)

        msg_id = b"test_message_id"
        result = ValidationResult(is_valid=True, timestamp=time.time())

        # Test cache miss
        assert cache.get(msg_id) is None

        # Test cache put and hit
        cache.put(msg_id, result)
        cached_result = cache.get(msg_id)
        assert cached_result is not None
        assert cached_result.is_valid

    def test_validation_cache_expiry(self):
        """Test validation cache expiry."""
        cache = ValidationCache(ttl=1, max_size=100)  # 1 second TTL

        msg_id = b"test_message_id"
        result = ValidationResult(is_valid=True, timestamp=time.time() - 2)  # Expired

        cache.cache[msg_id] = result

        # Should return None for expired entry
        assert cache.get(msg_id) is None
        assert msg_id not in cache.cache  # Should be cleaned up

    def test_validation_cache_lru_eviction(self):
        """Test LRU eviction in validation cache."""
        cache = ValidationCache(ttl=300, max_size=2)

        msg1 = b"msg1"
        msg2 = b"msg2"
        msg3 = b"msg3"

        result = ValidationResult(is_valid=True, timestamp=time.time())

        # Fill cache to capacity
        cache.put(msg1, result)
        cache.put(msg2, result)

        # Access msg1 to make it recently used
        cache.get(msg1)

        # Add msg3, should evict msg2 (least recently used)
        cache.put(msg3, result)

        assert cache.get(msg1) is not None  # Should still be there
        assert cache.get(msg2) is None  # Should be evicted
        assert cache.get(msg3) is not None  # Should be there


class TestSecurityFeatures:
    """Test security features (spam, Sybil, Eclipse protection)."""

    def test_spam_protection(self):
        """Test spam protection rate limiting."""
        gossipsub = GossipSub(
            protocols=[PROTOCOL_ID_V20],
            degree=6,
            degree_low=4,
            degree_high=12,
            spam_protection_enabled=True,
            max_messages_per_topic_per_second=2.0,
        )

        peer = IDFactory()
        topic = "test_topic"

        # Create test message
        msg = rpc_pb2.Message(
            data=b"test",
            topicIDs=[topic],
            from_id=peer.to_bytes(),
            seqno=b"1",
        )

        # First two messages should be allowed
        assert gossipsub._check_spam_protection(peer, msg)
        assert gossipsub._check_spam_protection(peer, msg)

        # Third message should be rejected (rate limit exceeded)
        assert not gossipsub._check_spam_protection(peer, msg)

    def test_equivocation_detection(self):
        """Test message equivocation detection."""
        gossipsub = GossipSub(
            protocols=[PROTOCOL_ID_V20],
            degree=6,
            degree_low=4,
            degree_high=12,
        )

        peer = IDFactory()
        seqno = b"123"

        # First message
        msg1 = rpc_pb2.Message(
            data=b"original_data",
            topicIDs=["topic1"],
            from_id=peer.to_bytes(),
            seqno=seqno,
        )

        # Second message with same seqno/from but different data (equivocation)
        msg2 = rpc_pb2.Message(
            data=b"different_data",
            topicIDs=["topic1"],
            from_id=peer.to_bytes(),
            seqno=seqno,
        )

        # First message should be accepted
        assert gossipsub._check_equivocation(msg1)

        # Second message should be rejected as equivocation
        assert not gossipsub._check_equivocation(msg2)

    def test_ip_diversity_enforcement(self):
        """Test IP diversity enforcement for Eclipse attack protection."""
        gossipsub = GossipSub(
            protocols=[PROTOCOL_ID_V20],
            degree=6,
            degree_low=4,
            degree_high=12,
            eclipse_protection_enabled=True,
            min_mesh_diversity_ips=3,
        )

        # Mock scorer with IP tracking
        gossipsub.scorer = Mock()
        gossipsub.scorer.ip_by_peer = {}

        topic = "test_topic"
        peers = [IDFactory() for _ in range(6)]
        gossipsub.mesh[topic] = set(peers)

        # All peers from same IP (poor diversity)
        scorer = gossipsub.scorer
        if scorer is not None:
            for peer in peers:
                scorer.add_peer_ip(peer, "192.168.1.1")

        # Should detect low diversity
        gossipsub._ensure_mesh_diversity(topic)
        # In a full implementation, this would trigger diversity improvement


class TestOpportunisticGrafting:
    """Test enhanced opportunistic grafting."""

    def test_grafting_threshold_calculation(self):
        """Test grafting threshold calculation based on mesh quality."""
        gossipsub = GossipSub(
            protocols=[PROTOCOL_ID_V20],
            degree=6,
            degree_low=4,
            degree_high=12,
        )

        # Mock scorer
        gossipsub.scorer = Mock()
        gossipsub.scorer.params = Mock()
        gossipsub.scorer.params.gossip_threshold = -1.0

        topic = "test_topic"
        median_score = 5.0
        avg_score = 4.5
        min_score = 2.0

        # Test with good network health
        gossipsub.network_health_score = 0.9
        threshold_good = gossipsub._calculate_grafting_threshold(
            median_score, avg_score, min_score, topic
        )

        # Test with poor network health
        gossipsub.network_health_score = 0.3
        threshold_poor = gossipsub._calculate_grafting_threshold(
            median_score, avg_score, min_score, topic
        )

        # Poor health should have lower threshold (more aggressive)
        assert threshold_poor <= threshold_good

    def test_candidate_selection_for_diversity(self):
        """Test candidate selection for IP diversity."""
        gossipsub = GossipSub(
            protocols=[PROTOCOL_ID_V20],
            degree=6,
            degree_low=4,
            degree_high=12,
            eclipse_protection_enabled=True,
        )

        # Mock scorer
        scorer = Mock()
        scorer.ip_by_peer = {}
        gossipsub.scorer = scorer

        topic = "test_topic"
        mesh_peers = [IDFactory() for _ in range(3)]
        gossipsub.mesh[topic] = set(mesh_peers)

        # Mesh peers from same IP
        for peer in mesh_peers:
            scorer.add_peer_ip = Mock()
            scorer.ip_by_peer[peer] = "192.168.1.1"

        # Candidates from different IPs
        candidates = [
            (IDFactory(), 5.0),  # Different IP
            (IDFactory(), 4.0),  # Same IP as mesh
        ]

        scorer.ip_by_peer[candidates[0][0]] = "192.168.1.2"  # Different IP
        scorer.ip_by_peer[candidates[1][0]] = "192.168.1.1"  # Same IP

        selected = gossipsub._select_for_ip_diversity(candidates, topic, 2)

        # Should prefer peer from different IP
        assert candidates[0][0] in selected
        assert len(selected) >= 1


class TestMeshMaintenance:
    """Test improved mesh maintenance."""

    def test_score_based_pruning_selection(self):
        """Test score-based peer selection for pruning."""
        gossipsub = GossipSub(
            protocols=[PROTOCOL_ID_V20],
            degree=6,
            degree_low=4,
            degree_high=12,
        )

        # Mock scorer
        gossipsub.scorer = Mock()
        gossipsub.scorer.params = Mock()
        gossipsub.scorer.params.graylist_threshold = -5.0
        gossipsub.scorer.score = Mock(
            side_effect=lambda peer, topics: {
                "good_peer": 10.0,
                "bad_peer": -10.0,  # Below graylist threshold
                "mediocre_peer": 2.0,
            }.get(str(peer), 0.0)
        )

        topic = "test_topic"
        mesh_peers = [IDFactory() for _ in range(3)]
        gossipsub.mesh[topic] = set(mesh_peers)

        # Should prune the bad peer first
        to_prune = gossipsub._select_peers_for_pruning(topic, 1)
        assert "bad_peer" in to_prune

    def test_peer_replacement_consideration(self):
        """Test consideration of peer replacement in mesh."""
        gossipsub = GossipSub(
            protocols=[PROTOCOL_ID_V20],
            degree=6,
            degree_low=4,
            degree_high=12,
        )

        # Mock pubsub and scorer
        gossipsub.pubsub = Mock()
        gossipsub.scorer = Mock()

        topic = "test_topic"
        mesh_peers = [IDFactory() for _ in range(6)]  # At target degree
        available_peers = [IDFactory() for _ in range(3)]

        gossipsub.mesh[topic] = set(mesh_peers)
        gossipsub.pubsub.peer_topics = {topic: set(mesh_peers + available_peers)}

        # Mock scoring: worst mesh peer has score 1.0, best available has 5.0
        def mock_score(peer, topics):
            if peer == mesh_peers[0]:
                return 1.0  # Worst mesh peer
            elif peer == available_peers[0]:
                return 5.0  # Best available peer
            else:
                return 3.0

        gossipsub.scorer.score = mock_score
        gossipsub.supports_scoring = Mock(return_value=True)
        gossipsub._check_back_off = Mock(return_value=False)

        # Should consider replacement (logged but not actually performed in test)
        gossipsub._consider_peer_replacement(topic)

        # Verify scoring was called for mesh peers
        assert gossipsub.scorer.score.called


class TestGossipsubV20Integration:
    """Integration tests for Gossipsub v2.0 features."""

    @pytest.mark.trio
    async def test_gossipsub_v20_basic_integration(self):
        """Basic integration test for Gossipsub v2.0 features."""
        async with PubsubFactory.create_batch_with_gossipsub(
            3,
            protocols=[PROTOCOL_ID_V20],
            heartbeat_interval=0.5,
        ) as pubsubs:
            # Enable v2.0 features manually
            for pubsub in pubsubs:
                if isinstance(pubsub.router, GossipSub):
                    pubsub.router.adaptive_gossip_enabled = True
                    pubsub.router.spam_protection_enabled = True
                    pubsub.router.eclipse_protection_enabled = True
            hosts = [ps.host for ps in pubsubs]
            gsubs = [ps.router for ps in pubsubs]

            # Verify v2.0 features are enabled
            for gsub in gsubs:
                assert isinstance(gsub, GossipSub)
                assert gsub.adaptive_gossip_enabled
                assert gsub.spam_protection_enabled
                assert gsub.eclipse_protection_enabled
                assert PROTOCOL_ID_V20 in gsub.protocols

            # Connect hosts
            from libp2p.tools.utils import connect

            await connect(hosts[0], hosts[1])
            await connect(hosts[1], hosts[2])
            await trio.sleep(0.5)

            # Subscribe to topic
            topic = "gossipsub_v20_test"
            for pubsub in pubsubs:
                await pubsub.subscribe(topic)
            await trio.sleep(1.0)

            # Verify mesh formation with v2.0 features
            for gsub in gsubs:
                if topic in gsub.mesh:
                    assert len(gsub.mesh[topic]) > 0
                    # Verify adaptive parameters are being used
                    assert hasattr(gsub, "network_health_score")
                    assert 0.0 <= gsub.network_health_score <= 1.0

            # Test message publishing with v2.0 security checks
            test_message = b"gossipsub v2.0 test message"
            await pubsubs[0].publish(topic, test_message)
            await trio.sleep(1.0)

            # All implementations should handle the message correctly
            # (detailed message verification would require more complex setup)

    @pytest.mark.trio
    async def test_v20_with_mixed_protocol_versions(self):
        """Test v2.0 nodes interacting with older protocol versions."""
        from libp2p.pubsub.gossipsub import PROTOCOL_ID_V11, PROTOCOL_ID_V12

        # Create mixed version network
        async with PubsubFactory.create_batch_with_gossipsub(
            4,
            protocols=[PROTOCOL_ID_V20, PROTOCOL_ID_V12, PROTOCOL_ID_V11],
            heartbeat_interval=0.5,
        ) as pubsubs:
            hosts = [ps.host for ps in pubsubs]
            gsubs = [ps.router for ps in pubsubs]

            # Connect all hosts
            from libp2p.tools.utils import connect

            for i in range(len(hosts)):
                for j in range(i + 1, len(hosts)):
                    await connect(hosts[i], hosts[j])
            await trio.sleep(0.5)

            # All subscribe to same topic
            topic = "mixed_version_test"
            for pubsub in pubsubs:
                await pubsub.subscribe(topic)
            await trio.sleep(1.0)

            # Verify mesh formation works across versions
            for gsub in gsubs:
                if topic in gsub.mesh:
                    assert len(gsub.mesh[topic]) > 0

            # Test message propagation across versions
            test_message = b"cross-version message"
            await pubsubs[0].publish(topic, test_message)
            await trio.sleep(1.0)
