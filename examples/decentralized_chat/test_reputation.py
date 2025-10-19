"""
Test script for the peer reputation system.

This script tests the core reputation functionality without requiring
a full libp2p network setup.
"""

import time
import unittest
from unittest.mock import Mock

from peer_reputation import PeerReputationManager, PeerReputation, MessageRecord


class TestPeerReputation(unittest.TestCase):
    """Test cases for the peer reputation system."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_peerstore = Mock()
        self.reputation_manager = PeerReputationManager(self.mock_peerstore)
        self.peer_id = Mock()
        self.peer_id.to_string.return_value = "test_peer"
    
    def test_initial_reputation(self):
        """Test that peers start with neutral reputation."""
        reputation = self.reputation_manager.get_reputation(self.peer_id)
        self.assertEqual(reputation.score, 0.5)
        self.assertEqual(reputation.message_count, 0)
        self.assertEqual(reputation.spam_count, 0)
    
    def test_spam_violation_penalty(self):
        """Test that spam violations reduce reputation."""
        reputation = self.reputation_manager.get_reputation(self.peer_id)
        initial_score = reputation.score
        
        reputation.add_spam_violation("spam_content")
        
        self.assertLess(reputation.score, initial_score)
        self.assertEqual(reputation.spam_count, 1)
        self.assertIn("spam_content", reputation.violations)
    
    def test_positive_behavior_reward(self):
        """Test that positive behavior increases reputation."""
        reputation = self.reputation_manager.get_reputation(self.peer_id)
        initial_score = reputation.score
        
        reputation.add_positive_behavior()
        
        self.assertGreater(reputation.score, initial_score)
    
    def test_rate_limiting(self):
        """Test rate limiting functionality."""
        reputation = self.reputation_manager.get_reputation(self.peer_id)
        
        # Add many messages quickly
        for i in range(15):  # More than the 10/minute limit
            reputation.add_message(100, "test_topic")
        
        message_rate = reputation.get_recent_message_rate(60)  # 1 minute window
        self.assertGreater(message_rate, 10)  # Should exceed rate limit
    
    def test_message_validity_check(self):
        """Test message validity checking."""
        # Test valid message
        is_valid, reason = self.reputation_manager.check_message_validity(
            self.peer_id, b"Hello world!", "test_topic"
        )
        self.assertTrue(is_valid)
        self.assertEqual(reason, "Valid message")
        
        # Test spam content
        is_valid, reason = self.reputation_manager.check_message_validity(
            self.peer_id, b"CLICK HERE FOR FREE MONEY!!!", "test_topic"
        )
        self.assertFalse(is_valid)
        self.assertIn("Spam content detected", reason)
        
        # Test message too long
        long_message = b"x" * 2000  # 2KB message
        is_valid, reason = self.reputation_manager.check_message_validity(
            self.peer_id, long_message, "test_topic"
        )
        self.assertFalse(is_valid)
        self.assertIn("Message too long", reason)
    
    def test_trust_levels(self):
        """Test trust level classification."""
        reputation = self.reputation_manager.get_reputation(self.peer_id)
        
        # Test neutral (default)
        trust_level = self.reputation_manager.get_peer_trust_level(self.peer_id)
        self.assertEqual(trust_level, "neutral")
        
        # Test trusted
        reputation.score = 0.8
        trust_level = self.reputation_manager.get_peer_trust_level(self.peer_id)
        self.assertEqual(trust_level, "trusted")
        
        # Test spam
        reputation.score = 0.2
        trust_level = self.reputation_manager.get_peer_trust_level(self.peer_id)
        self.assertEqual(trust_level, "spam")
    
    def test_reputation_decay(self):
        """Test reputation decay over time."""
        reputation = self.reputation_manager.get_reputation(self.peer_id)
        initial_score = reputation.score
        
        # Simulate 2 hours passing
        reputation.decay_reputation(2.0)
        
        expected_decay = 0.01 * 2  # 0.01 per hour
        expected_score = max(0.0, initial_score - expected_decay)
        
        self.assertAlmostEqual(reputation.score, expected_score, places=3)
    
    def test_spam_detection_patterns(self):
        """Test spam content detection."""
        # Test excessive caps
        is_spam = self.reputation_manager._is_spam_content("THIS IS ALL CAPS MESSAGE")
        self.assertTrue(is_spam)
        
        # Test spam keywords
        is_spam = self.reputation_manager._is_spam_content("Click here for free money!")
        self.assertTrue(is_spam)
        
        # Test word repetition
        is_spam = self.reputation_manager._is_spam_content("spam spam spam spam spam spam")
        self.assertTrue(is_spam)
        
        # Test normal message
        is_spam = self.reputation_manager._is_spam_content("Hello, how are you today?")
        self.assertFalse(is_spam)
    
    def test_network_stats(self):
        """Test network statistics generation."""
        # Add some peers with different reputation levels
        peer1 = Mock()
        peer2 = Mock()
        peer3 = Mock()
        
        rep1 = self.reputation_manager.get_reputation(peer1)
        rep2 = self.reputation_manager.get_reputation(peer2)
        rep3 = self.reputation_manager.get_reputation(peer3)
        
        rep1.score = 0.8  # Trusted
        rep2.score = 0.2  # Spam
        rep3.score = 0.5  # Neutral
        
        stats = self.reputation_manager.get_network_stats()
        
        self.assertEqual(stats["total_peers"], 3)
        self.assertEqual(stats["trusted_peers"], 1)
        self.assertEqual(stats["spam_peers"], 1)
        self.assertEqual(stats["neutral_peers"], 1)


class TestMessageRecord(unittest.TestCase):
    """Test cases for message records."""
    
    def test_message_record_creation(self):
        """Test message record creation and properties."""
        timestamp = time.time()
        record = MessageRecord(timestamp, 100, "test_topic")
        
        self.assertEqual(record.timestamp, timestamp)
        self.assertEqual(record.message_length, 100)
        self.assertEqual(record.topic, "test_topic")


if __name__ == "__main__":
    # Run the tests
    unittest.main(verbosity=2)
