"""
Peer Reputation System for Decentralized Chat

This module implements a peer reputation system that tracks peer behavior
and provides spam resistance through peer scoring.
"""

import time
import logging
from typing import Dict, Optional, Set
from collections import defaultdict, deque
from dataclasses import dataclass, field

from libp2p.peer.id import ID
from libp2p.peer.peerstore import PeerStore

logger = logging.getLogger("decentralized_chat.reputation")

# Reputation constants
INITIAL_REPUTATION = 0.5
MAX_REPUTATION = 1.0
MIN_REPUTATION = 0.0
REPUTATION_DECAY_RATE = 0.01  # Per hour
SPAM_THRESHOLD = 0.3
TRUSTED_THRESHOLD = 0.7

# Message rate limiting
MAX_MESSAGES_PER_MINUTE = 10
MAX_MESSAGES_PER_HOUR = 100
RATE_LIMIT_WINDOW = 60  # seconds

@dataclass
class MessageRecord:
    """Record of a message for rate limiting and spam detection."""
    timestamp: float
    message_length: int
    topic: str

@dataclass
class PeerReputation:
    """Reputation data for a peer."""
    score: float = INITIAL_REPUTATION
    message_count: int = 0
    spam_count: int = 0
    last_activity: float = field(default_factory=time.time)
    message_history: deque = field(default_factory=lambda: deque(maxlen=1000))
    violations: Set[str] = field(default_factory=set)
    
    def update_activity(self) -> None:
        """Update last activity timestamp."""
        self.last_activity = time.time()
    
    def add_message(self, message_length: int, topic: str) -> None:
        """Record a new message."""
        current_time = time.time()
        self.message_history.append(MessageRecord(current_time, message_length, topic))
        self.message_count += 1
        self.update_activity()
    
    def add_spam_violation(self, violation_type: str) -> None:
        """Record a spam violation."""
        self.spam_count += 1
        self.violations.add(violation_type)
        # Reduce reputation based on violation type
        if violation_type == "rate_limit":
            self.score = max(MIN_REPUTATION, self.score - 0.1)
        elif violation_type == "spam_content":
            self.score = max(MIN_REPUTATION, self.score - 0.2)
        elif violation_type == "duplicate":
            self.score = max(MIN_REPUTATION, self.score - 0.05)
        
        logger.warning(f"Peer {self} committed {violation_type} violation. New score: {self.score}")
    
    def add_positive_behavior(self) -> None:
        """Reward positive behavior."""
        self.score = min(MAX_REPUTATION, self.score + 0.01)
    
    def decay_reputation(self, hours_elapsed: float) -> None:
        """Apply reputation decay over time."""
        decay = REPUTATION_DECAY_RATE * hours_elapsed
        self.score = max(MIN_REPUTATION, self.score - decay)
    
    def is_trusted(self) -> bool:
        """Check if peer is trusted."""
        return self.score >= TRUSTED_THRESHOLD
    
    def is_spam_peer(self) -> bool:
        """Check if peer is considered a spammer."""
        return self.score <= SPAM_THRESHOLD
    
    def get_recent_message_rate(self, window_seconds: int = RATE_LIMIT_WINDOW) -> float:
        """Calculate messages per minute in the given window."""
        current_time = time.time()
        cutoff_time = current_time - window_seconds
        
        recent_messages = [
            msg for msg in self.message_history 
            if msg.timestamp >= cutoff_time
        ]
        
        return len(recent_messages) / (window_seconds / 60.0)


class PeerReputationManager:
    """Manages peer reputation across the network."""
    
    def __init__(self, peerstore: PeerStore):
        self.peerstore = peerstore
        self.reputations: Dict[ID, PeerReputation] = {}
        self.last_decay_time = time.time()
    
    def get_reputation(self, peer_id: ID) -> PeerReputation:
        """Get or create reputation for a peer."""
        if peer_id not in self.reputations:
            self.reputations[peer_id] = PeerReputation()
        return self.reputations[peer_id]
    
    def update_reputation_from_peerstore(self, peer_id: ID) -> None:
        """Update reputation from peerstore metadata if available."""
        try:
            # Try to get reputation from peerstore metadata
            stored_score = self.peerstore.get(peer_id, "reputation_score")
            if stored_score is not None:
                reputation = self.get_reputation(peer_id)
                reputation.score = float(stored_score)
                logger.debug(f"Restored reputation for {peer_id}: {reputation.score}")
        except Exception:
            # Peer not in peerstore or no reputation data
            pass
    
    def save_reputation_to_peerstore(self, peer_id: ID) -> None:
        """Save reputation to peerstore metadata."""
        reputation = self.get_reputation(peer_id)
        self.peerstore.put(peer_id, "reputation_score", reputation.score)
        self.peerstore.put(peer_id, "reputation_last_update", reputation.last_activity)
        self.peerstore.put(peer_id, "reputation_violations", list(reputation.violations))
    
    def check_message_validity(self, peer_id: ID, message_data: bytes, topic: str) -> tuple[bool, str]:
        """
        Check if a message is valid based on peer reputation and content.
        
        Returns:
            (is_valid, reason)
        """
        reputation = self.get_reputation(peer_id)
        
        # Check rate limiting
        message_rate = reputation.get_recent_message_rate()
        if message_rate > MAX_MESSAGES_PER_MINUTE:
            reputation.add_spam_violation("rate_limit")
            return False, f"Rate limit exceeded: {message_rate:.1f} msg/min"
        
        # Check message length (spam detection)
        if len(message_data) > 1000:  # 1KB limit
            reputation.add_spam_violation("spam_content")
            return False, "Message too long"
        
        # Check for duplicate messages
        message_text = message_data.decode('utf-8', errors='ignore')
        recent_messages = [
            msg for msg in reputation.message_history 
            if time.time() - msg.timestamp < 300  # 5 minutes
        ]
        
        for recent_msg in recent_messages:
            if message_text == recent_msg.message_data.decode('utf-8', errors='ignore'):
                reputation.add_spam_violation("duplicate")
                return False, "Duplicate message detected"
        
        # Check for spam patterns
        if self._is_spam_content(message_text):
            reputation.add_spam_violation("spam_content")
            return False, "Spam content detected"
        
        # Message is valid
        reputation.add_message(len(message_data), topic)
        reputation.add_positive_behavior()
        return True, "Valid message"
    
    def _is_spam_content(self, message_text: str) -> bool:
        """Simple spam detection based on content patterns."""
        text_lower = message_text.lower()
        
        # Check for excessive repetition
        words = text_lower.split()
        if len(words) > 0:
            word_counts = defaultdict(int)
            for word in words:
                word_counts[word] += 1
            
            # If any word appears more than 30% of the time, it's likely spam
            max_word_ratio = max(word_counts.values()) / len(words)
            if max_word_ratio > 0.3:
                return True
        
        # Check for common spam patterns
        spam_patterns = [
            "click here", "free money", "win now", "urgent", "act now",
            "limited time", "guaranteed", "no risk", "make money"
        ]
        
        for pattern in spam_patterns:
            if pattern in text_lower:
                return True
        
        # Check for excessive caps
        if len(message_text) > 10:
            caps_ratio = sum(1 for c in message_text if c.isupper()) / len(message_text)
            if caps_ratio > 0.7:
                return True
        
        return False
    
    def should_accept_message(self, peer_id: ID) -> bool:
        """Check if we should accept messages from this peer."""
        reputation = self.get_reputation(peer_id)
        return not reputation.is_spam_peer()
    
    def get_peer_trust_level(self, peer_id: ID) -> str:
        """Get human-readable trust level for a peer."""
        reputation = self.get_reputation(peer_id)
        
        if reputation.is_trusted():
            return "trusted"
        elif reputation.is_spam_peer():
            return "spam"
        else:
            return "neutral"
    
    def apply_reputation_decay(self) -> None:
        """Apply reputation decay to all peers."""
        current_time = time.time()
        hours_elapsed = (current_time - self.last_decay_time) / 3600
        
        if hours_elapsed >= 1:  # Apply decay every hour
            for peer_id, reputation in self.reputations.items():
                reputation.decay_reputation(hours_elapsed)
                self.save_reputation_to_peerstore(peer_id)
            
            self.last_decay_time = current_time
            logger.debug(f"Applied reputation decay for {hours_elapsed:.1f} hours")
    
    def get_network_stats(self) -> Dict[str, int]:
        """Get statistics about the network reputation."""
        trusted_count = sum(1 for r in self.reputations.values() if r.is_trusted())
        spam_count = sum(1 for r in self.reputations.values() if r.is_spam_peer())
        neutral_count = len(self.reputations) - trusted_count - spam_count
        
        return {
            "total_peers": len(self.reputations),
            "trusted_peers": trusted_count,
            "spam_peers": spam_count,
            "neutral_peers": neutral_count
        }
