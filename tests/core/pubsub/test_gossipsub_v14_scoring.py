"""
Tests for GossipSub v1.4 Enhanced Peer Scoring.

This module tests the enhanced peer scoring system in v1.4, including:
- Extended behavioral penalties (P5-P7)
- IP colocation tracking and penalties
- Subnet-level colocation detection
- Enhanced scoring metrics and observability
"""

import pytest
import trio

from libp2p.peer.id import ID
from libp2p.pubsub.gossipsub import (
    PROTOCOL_ID_V14,
    GossipSub,
)
from libp2p.pubsub.score import ScoreParams
from libp2p.tools.utils import connect
from tests.utils.factories import IDFactory, PubsubFactory


@pytest.mark.trio
async def test_enhanced_behavioral_penalties():
    """Test enhanced behavioral penalty tracking."""
    score_params = ScoreParams(
        p5_behavior_penalty_weight=1.0,
        p5_behavior_penalty_decay=0.9,
    )
    
    async with PubsubFactory.create_batch_with_gossipsub(
        1, protocols=[PROTOCOL_ID_V14], score_params=score_params
    ) as pubsubs:
        router = pubsubs[0].router
        assert isinstance(router, GossipSub)
        
        scorer = router.scorer
        assert scorer is not None
        
        peer_id = IDFactory()
        
        # Test different penalty types
        scorer.penalize_graft_flood(peer_id, 10.0)
        scorer.penalize_iwant_spam(peer_id, 5.0)
        scorer.penalize_ihave_spam(peer_id, 3.0)
        scorer.penalize_equivocation(peer_id, 100.0)
        
        # Verify penalties are tracked separately
        assert scorer.graft_flood_penalties[peer_id] == 10.0
        assert scorer.iwant_spam_penalties[peer_id] == 5.0
        assert scorer.ihave_spam_penalties[peer_id] == 3.0
        assert scorer.equivocation_penalties[peer_id] == 100.0
        
        # Test combined penalty in score calculation
        score = scorer.score(peer_id, ["test-topic"])
        # Total penalty: 10 + 5 + 3 + 100 = 118
        # Should be negative due to penalties
        assert score < 0


@pytest.mark.trio
async def test_ip_colocation_tracking():
    """Test IP colocation tracking and penalties."""
    score_params = ScoreParams(
        p7_ip_colocation_weight=5.0,
        p7_ip_colocation_threshold=2,
    )
    
    async with PubsubFactory.create_batch_with_gossipsub(
        1, protocols=[PROTOCOL_ID_V14], score_params=score_params
    ) as pubsubs:
        router = pubsubs[0].router
        assert isinstance(router, GossipSub)
        
        scorer = router.scorer
        assert scorer is not None
        
        # Create peers from same IP
        peer1 = IDFactory()
        peer2 = IDFactory()
        peer3 = IDFactory()
        
        ip_address = "192.168.1.100"
        
        # Add peers to same IP
        scorer.add_peer_ip(peer1, ip_address)
        scorer.add_peer_ip(peer2, ip_address)
        scorer.add_peer_ip(peer3, ip_address)  # This should trigger penalty
        
        # Verify IP tracking
        assert scorer.ip_by_peer[peer1] == ip_address
        assert scorer.ip_by_peer[peer2] == ip_address
        assert scorer.ip_by_peer[peer3] == ip_address
        assert len(scorer.peer_ips[ip_address]) == 3
        
        # Test colocation penalty
        penalty = scorer.ip_colocation_penalty(peer3)
        assert penalty > 0  # Should have penalty for excess peers
        
        # Remove a peer and verify penalty decreases
        scorer.remove_peer_ip(peer1)
        penalty_after_removal = scorer.ip_colocation_penalty(peer3)
        assert penalty_after_removal < penalty


@pytest.mark.trio
async def test_subnet_colocation_tracking():
    """Test subnet-level colocation tracking."""
    score_params = ScoreParams(
        p7_ip_colocation_weight=10.0,
        p7_ip_colocation_threshold=2,
    )
    
    async with PubsubFactory.create_batch_with_gossipsub(
        1, protocols=[PROTOCOL_ID_V14], score_params=score_params
    ) as pubsubs:
        router = pubsubs[0].router
        assert isinstance(router, GossipSub)
        
        scorer = router.scorer
        assert scorer is not None
        
        # Create peers from same subnet but different IPs
        peers = [IDFactory() for _ in range(10)]
        
        # Add peers to same /24 subnet
        for i, peer in enumerate(peers):
            ip = f"192.168.1.{i + 1}"
            scorer.add_peer_ip(peer, ip)
        
        # Verify subnet tracking
        subnet = "192.168.1"
        assert subnet in scorer.subnet_tracking
        assert len(scorer.subnet_tracking[subnet]) == 10
        
        # Test subnet penalty (should be lighter than exact IP penalty)
        penalty = scorer.ip_colocation_penalty(peers[0])
        assert penalty > 0  # Should have subnet penalty
        
        # Test IPv6 subnet tracking
        peer_ipv6 = IDFactory()
        scorer.add_peer_ip(peer_ipv6, "2001:db8:85a3:8d3:1319:8a2e:370:7344")
        
        ipv6_subnet = "2001:db8:85a3:8d3"
        assert ipv6_subnet in scorer.subnet_tracking


@pytest.mark.trio
async def test_penalty_decay():
    """Test penalty decay over time."""
    score_params = ScoreParams(
        p5_behavior_penalty_decay=0.5,  # Aggressive decay for testing
    )
    
    async with PubsubFactory.create_batch_with_gossipsub(
        1, protocols=[PROTOCOL_ID_V14], score_params=score_params
    ) as pubsubs:
        router = pubsubs[0].router
        assert isinstance(router, GossipSub)
        
        scorer = router.scorer
        assert scorer is not None
        
        peer_id = IDFactory()
        
        # Apply penalties
        scorer.penalize_graft_flood(peer_id, 100.0)
        scorer.penalize_iwant_spam(peer_id, 50.0)
        
        initial_graft_penalty = scorer.graft_flood_penalties[peer_id]
        initial_iwant_penalty = scorer.iwant_spam_penalties[peer_id]
        
        # Apply decay
        scorer.on_heartbeat(1.0)
        
        # Verify penalties decayed
        assert scorer.graft_flood_penalties[peer_id] < initial_graft_penalty
        assert scorer.iwant_spam_penalties[peer_id] < initial_iwant_penalty
        assert scorer.graft_flood_penalties[peer_id] == initial_graft_penalty * 0.5
        assert scorer.iwant_spam_penalties[peer_id] == initial_iwant_penalty * 0.5


@pytest.mark.trio
async def test_score_stats_observability():
    """Test enhanced score statistics for observability."""
    score_params = ScoreParams(
        p7_ip_colocation_weight=2.0,
    )
    
    async with PubsubFactory.create_batch_with_gossipsub(
        1, protocols=[PROTOCOL_ID_V14], score_params=score_params
    ) as pubsubs:
        router = pubsubs[0].router
        assert isinstance(router, GossipSub)
        
        scorer = router.scorer
        assert scorer is not None
        
        peer_id = IDFactory()
        topic = "test-topic"
        
        # Set up scoring data
        scorer.add_peer_ip(peer_id, "192.168.1.1")
        scorer.penalize_graft_flood(peer_id, 10.0)
        scorer.penalize_equivocation(peer_id, 50.0)
        
        # Get detailed stats
        stats = scorer.get_score_stats(peer_id, topic)
        
        # Verify all v1.4 stats are included
        assert "graft_flood_penalty" in stats
        assert "iwant_spam_penalty" in stats
        assert "ihave_spam_penalty" in stats
        assert "equivocation_penalty" in stats
        assert "peer_ip" in stats
        
        assert stats["graft_flood_penalty"] == 10.0
        assert stats["equivocation_penalty"] == 50.0
        assert stats["peer_ip"] == "192.168.1.1"


@pytest.mark.trio
async def test_scoring_integration_with_rate_limiting():
    """Test integration between scoring and rate limiting."""
    score_params = ScoreParams(
        p5_behavior_penalty_weight=1.0,
    )
    
    async with PubsubFactory.create_batch_with_gossipsub(
        2, protocols=[PROTOCOL_ID_V14], score_params=score_params
    ) as pubsubs:
        router0 = pubsubs[0].router
        router1 = pubsubs[1].router
        assert isinstance(router0, GossipSub)
        assert isinstance(router1, GossipSub)
        
        # Connect peers
        await connect(pubsubs[0].host, pubsubs[1].host)
        await trio.sleep(0.5)
        
        peer0_id = pubsubs[0].host.get_id()
        
        # Trigger rate limiting to apply penalties
        router1.max_iwant_requests_per_second = 1.0
        
        # Exceed rate limit multiple times
        for _ in range(5):
            router1._check_iwant_rate_limit(peer0_id)
        
        # Verify penalty was applied through scoring system
        if router1.scorer:
            assert router1.scorer.iwant_spam_penalties[peer0_id] > 0
            
            # Score should be negative due to penalties
            score = router1.scorer.score(peer0_id, ["test-topic"])
            assert score < 0


@pytest.mark.trio
async def test_ip_address_validation():
    """Test IP address validation in colocation tracking."""
    async with PubsubFactory.create_batch_with_gossipsub(
        1, protocols=[PROTOCOL_ID_V14]
    ) as pubsubs:
        router = pubsubs[0].router
        assert isinstance(router, GossipSub)
        
        scorer = router.scorer
        assert scorer is not None
        
        peer_id = IDFactory()
        
        # Test valid IPv4
        scorer.add_peer_ip(peer_id, "192.168.1.1")
        assert scorer.ip_by_peer[peer_id] == "192.168.1.1"
        
        # Test valid IPv6
        scorer.add_peer_ip(peer_id, "2001:db8::1")
        assert scorer.ip_by_peer[peer_id] == "2001:db8::1"
        
        # Test invalid IP (should not crash)
        scorer.add_peer_ip(peer_id, "invalid.ip.address")
        # Should still work, just might not get subnet tracking
        
        # Test IP update (should clean up old IP)
        old_ip = "192.168.1.1"
        new_ip = "10.0.0.1"
        
        scorer.add_peer_ip(peer_id, old_ip)
        assert peer_id in scorer.peer_ips[old_ip]
        
        scorer.add_peer_ip(peer_id, new_ip)
        assert peer_id not in scorer.peer_ips[old_ip]
        assert peer_id in scorer.peer_ips[new_ip]


@pytest.mark.trio
async def test_peer_removal_cleanup():
    """Test that peer removal cleans up all v1.4 scoring data."""
    async with PubsubFactory.create_batch_with_gossipsub(
        1, protocols=[PROTOCOL_ID_V14]
    ) as pubsubs:
        router = pubsubs[0].router
        assert isinstance(router, GossipSub)
        
        scorer = router.scorer
        assert scorer is not None
        
        peer_id = IDFactory()
        
        # Set up all types of scoring data
        scorer.add_peer_ip(peer_id, "192.168.1.1")
        scorer.penalize_graft_flood(peer_id, 10.0)
        scorer.penalize_iwant_spam(peer_id, 5.0)
        scorer.penalize_ihave_spam(peer_id, 3.0)
        scorer.penalize_equivocation(peer_id, 100.0)
        
        # Verify data exists
        assert peer_id in scorer.ip_by_peer
        assert peer_id in scorer.graft_flood_penalties
        assert peer_id in scorer.iwant_spam_penalties
        assert peer_id in scorer.ihave_spam_penalties
        assert peer_id in scorer.equivocation_penalties
        
        # Remove peer
        scorer.remove_peer(peer_id)
        
        # Verify all data is cleaned up
        assert peer_id not in scorer.ip_by_peer
        assert peer_id not in scorer.graft_flood_penalties
        assert peer_id not in scorer.iwant_spam_penalties
        assert peer_id not in scorer.ihave_spam_penalties
        assert peer_id not in scorer.equivocation_penalties