from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
import math
from typing import DefaultDict

from libp2p.peer.id import ID


@dataclass
class TopicScoreParams:
    weight: float = 0.0
    cap: float = 0.0
    decay: float = 1.0


@dataclass
class ScoreParams:
    # Topic-scoped P1..P4
    p1_time_in_mesh: TopicScoreParams = field(
        default_factory=lambda: TopicScoreParams()
    )
    p2_first_message_deliveries: TopicScoreParams = field(
        default_factory=lambda: TopicScoreParams()
    )
    p3_mesh_message_deliveries: TopicScoreParams = field(
        default_factory=lambda: TopicScoreParams()
    )
    p4_invalid_messages: TopicScoreParams = field(
        default_factory=lambda: TopicScoreParams()
    )

    # Global P5..P7
    p5_behavior_penalty_weight: float = 0.0
    p5_behavior_penalty_decay: float = 1.0
    p5_behavior_penalty_threshold: float = 0.0

    p6_appl_slack_weight: float = 0.0
    p6_appl_slack_decay: float = 1.0

    p7_ip_colocation_weight: float = 0.0
    p7_ip_colocation_threshold: int = (
        10  # Number of peers from same IP before penalty applies
    )

    # Acceptance thresholds (permissive defaults for initial implementation)
    # These defaults allow all messages initially. In production environments,
    # consider tuning based on network conditions and attack models:
    # - publish_threshold: Minimum score to accept published messages (e.g., 0.0)
    # - gossip_threshold: Minimum score to gossip about peer (e.g., -1.0)
    # - graylist_threshold: Score below which peer is ignored (e.g., -10.0)
    # - accept_px_threshold: Minimum score to accept PX from peer (e.g., 0.0)
    publish_threshold: float = -math.inf
    gossip_threshold: float = -math.inf
    graylist_threshold: float = -math.inf
    accept_px_threshold: float = -math.inf

    # Application-specific scoring callback
    app_specific_score_fn: Callable[[ID], float] | None = None


class PeerScorer:
    """
    Minimal scorer implementing weighted-decayed counters per peer and topic.

    This is intentionally simple and conservative. It provides the hooks required
    by the Gossipsub v1.1 gates without prescribing specific parameter values.
    """

    def __init__(self, params: ScoreParams) -> None:
        self.params = params
        self.time_in_mesh: DefaultDict[ID, DefaultDict[str, float]] = defaultdict(
            lambda: defaultdict(float)
        )
        self.first_message_deliveries: DefaultDict[ID, DefaultDict[str, float]] = (
            defaultdict(lambda: defaultdict(float))
        )
        self.mesh_message_deliveries: DefaultDict[ID, DefaultDict[str, float]] = (
            defaultdict(lambda: defaultdict(float))
        )
        self.invalid_messages: DefaultDict[ID, DefaultDict[str, float]] = defaultdict(
            lambda: defaultdict(float)
        )

        # Global state
        self.behavior_penalty: dict[ID, float] = defaultdict(float)

        # IP colocation tracking: IP -> set of peer IDs
        self.peer_ips: dict[str, set[ID]] = defaultdict(set)
        # Peer ID -> IP mapping for efficient lookups
        self.ip_by_peer: dict[ID, str] = {}

        # Application-specific scores cache
        self.app_specific_scores: dict[ID, float] = defaultdict(float)

        # Enhanced v1.4 behavioral tracking
        self.graft_flood_penalties: dict[ID, float] = defaultdict(float)
        self.iwant_spam_penalties: dict[ID, float] = defaultdict(float)
        self.ihave_spam_penalties: dict[ID, float] = defaultdict(float)
        self.equivocation_penalties: dict[ID, float] = defaultdict(float)

        # IP subnet tracking for enhanced colocation detection
        self.subnet_tracking: dict[str, set[ID]] = defaultdict(
            set
        )  # /24 subnet -> peers

    # ---- Update hooks ----
    def on_heartbeat(self, dt_seconds: float = 1.0) -> None:
        # Apply decay to all counters
        for peer in list(self.time_in_mesh.keys()):
            for topic in list(self.time_in_mesh[peer].keys()):
                self.time_in_mesh[peer][topic] = (
                    self.time_in_mesh[peer][topic] * self.params.p1_time_in_mesh.decay
                )
        for peer in list(self.first_message_deliveries.keys()):
            for topic in list(self.first_message_deliveries[peer].keys()):
                self.first_message_deliveries[peer][topic] *= (
                    self.params.p2_first_message_deliveries.decay
                )
        for peer in list(self.mesh_message_deliveries.keys()):
            for topic in list(self.mesh_message_deliveries[peer].keys()):
                self.mesh_message_deliveries[peer][topic] *= (
                    self.params.p3_mesh_message_deliveries.decay
                )
        for peer in list(self.invalid_messages.keys()):
            for topic in list(self.invalid_messages[peer].keys()):
                self.invalid_messages[peer][topic] *= (
                    self.params.p4_invalid_messages.decay
                )

        for peer in list(self.behavior_penalty.keys()):
            self.behavior_penalty[peer] *= self.params.p5_behavior_penalty_decay

        # Apply decay to application-specific scores
        for peer in list(self.app_specific_scores.keys()):
            self.app_specific_scores[peer] *= self.params.p6_appl_slack_decay

        # Apply decay to v1.4 behavioral penalties
        for peer in list(self.graft_flood_penalties.keys()):
            self.graft_flood_penalties[peer] *= self.params.p5_behavior_penalty_decay
        for peer in list(self.iwant_spam_penalties.keys()):
            self.iwant_spam_penalties[peer] *= self.params.p5_behavior_penalty_decay
        for peer in list(self.ihave_spam_penalties.keys()):
            self.ihave_spam_penalties[peer] *= self.params.p5_behavior_penalty_decay
        for peer in list(self.equivocation_penalties.keys()):
            self.equivocation_penalties[peer] *= self.params.p5_behavior_penalty_decay

    def on_join_mesh(self, peer: ID, topic: str) -> None:
        # Start counting time in mesh for the peer
        self.time_in_mesh[peer][topic] += 1.0

    def on_leave_mesh(self, peer: ID, topic: str) -> None:
        # No-op; counters decay over time.
        pass

    def remove_peer(self, peer: ID) -> None:
        """
        Remove all scoring data for a peer when they disconnect.

        :param peer: The peer ID to remove
        """
        # Remove from all topic-specific tracking
        if peer in self.time_in_mesh:
            del self.time_in_mesh[peer]
        if peer in self.first_message_deliveries:
            del self.first_message_deliveries[peer]
        if peer in self.mesh_message_deliveries:
            del self.mesh_message_deliveries[peer]
        if peer in self.invalid_messages:
            del self.invalid_messages[peer]

        # Remove from global tracking
        if peer in self.behavior_penalty:
            del self.behavior_penalty[peer]
        if peer in self.app_specific_scores:
            del self.app_specific_scores[peer]

        # Remove IP association
        self.remove_peer_ip(peer)

        # Remove v1.4 behavioral penalties
        if peer in self.graft_flood_penalties:
            del self.graft_flood_penalties[peer]
        if peer in self.iwant_spam_penalties:
            del self.iwant_spam_penalties[peer]
        if peer in self.ihave_spam_penalties:
            del self.ihave_spam_penalties[peer]
        if peer in self.equivocation_penalties:
            del self.equivocation_penalties[peer]

    def on_first_delivery(self, peer: ID, topic: str) -> None:
        self.first_message_deliveries[peer][topic] += 1.0

    def on_mesh_delivery(self, peer: ID, topic: str) -> None:
        self.mesh_message_deliveries[peer][topic] += 1.0

    def on_invalid_message(self, peer: ID, topic: str) -> None:
        self.invalid_messages[peer][topic] += 1.0

    def penalize_behavior(self, peer: ID, amount: float = 1.0) -> None:
        self.behavior_penalty[peer] += amount

    def penalize_graft_flood(self, peer: ID, amount: float = 10.0) -> None:
        """Apply penalty for GRAFT flooding behavior."""
        self.graft_flood_penalties[peer] += amount

    def penalize_iwant_spam(self, peer: ID, amount: float = 5.0) -> None:
        """Apply penalty for IWANT spamming behavior."""
        self.iwant_spam_penalties[peer] += amount

    def penalize_ihave_spam(self, peer: ID, amount: float = 5.0) -> None:
        """Apply penalty for IHAVE spamming behavior."""
        self.ihave_spam_penalties[peer] += amount

    def penalize_equivocation(self, peer: ID, amount: float = 100.0) -> None:
        """Apply severe penalty for message equivocation."""
        self.equivocation_penalties[peer] += amount

    def add_peer_ip(self, peer: ID, ip_str: str) -> None:
        """
        Associate a peer with an IP address for colocation tracking.

        :param peer: The peer ID
        :param ip_str: The IP address as a string
        """
        # Remove peer from old IP if it exists
        if peer in self.ip_by_peer:
            old_ip = self.ip_by_peer[peer]
            self.peer_ips[old_ip].discard(peer)
            if not self.peer_ips[old_ip]:
                del self.peer_ips[old_ip]

        # Add peer to new IP
        self.peer_ips[ip_str].add(peer)
        self.ip_by_peer[peer] = ip_str

        # Track subnet for enhanced colocation detection
        subnet = self._get_subnet(ip_str)
        if subnet:
            self.subnet_tracking[subnet].add(peer)

    def remove_peer_ip(self, peer: ID) -> None:
        """
        Remove a peer's IP association.

        :param peer: The peer ID to remove
        """
        if peer in self.ip_by_peer:
            ip_str = self.ip_by_peer[peer]
            self.peer_ips[ip_str].discard(peer)
            if not self.peer_ips[ip_str]:
                del self.peer_ips[ip_str]

            # Remove from subnet tracking
            subnet = self._get_subnet(ip_str)
            if subnet and subnet in self.subnet_tracking:
                self.subnet_tracking[subnet].discard(peer)
                if not self.subnet_tracking[subnet]:
                    del self.subnet_tracking[subnet]

            del self.ip_by_peer[peer]

    def update_app_specific_score(self, peer: ID) -> None:
        """
        Update the application-specific score for a peer.

        :param peer: The peer ID to update
        """
        if self.params.app_specific_score_fn is not None:
            try:
                self.app_specific_scores[peer] = self.params.app_specific_score_fn(peer)
            except Exception:
                # If app-specific scoring fails, default to 0
                self.app_specific_scores[peer] = 0.0

    def _get_subnet(self, ip_str: str) -> str | None:
        """
        Extract /24 subnet from IP address for subnet-based colocation tracking.

        :param ip_str: IP address string
        :return: Subnet string (e.g., "192.168.1") or None if invalid
        """
        try:
            # Handle IPv4 /24 subnets
            if "." in ip_str and ip_str.count(".") == 3:
                parts = ip_str.split(".")
                if len(parts) == 4 and all(
                    part.isdigit() and 0 <= int(part) <= 255 for part in parts
                ):
                    return ".".join(parts[:3])

            # Handle IPv6 /64 subnets (simplified)
            elif ":" in ip_str:
                parts = ip_str.split(":")
                if len(parts) >= 4:
                    return ":".join(parts[:4])

            return None
        except Exception:
            return None

    # ---- Scoring ----
    def topic_score(self, peer: ID, topic: str) -> float:
        p = self.params
        s = 0.0
        s += p.p1_time_in_mesh.weight * min(
            self.time_in_mesh[peer][topic], p.p1_time_in_mesh.cap
        )
        s += p.p2_first_message_deliveries.weight * min(
            self.first_message_deliveries[peer][topic],
            p.p2_first_message_deliveries.cap,
        )
        s += p.p3_mesh_message_deliveries.weight * min(
            self.mesh_message_deliveries[peer][topic], p.p3_mesh_message_deliveries.cap
        )
        s -= p.p4_invalid_messages.weight * min(
            self.invalid_messages[peer][topic], p.p4_invalid_messages.cap
        )
        return s

    def ip_colocation_penalty(self, peer: ID) -> float:
        """
        Calculate the IP colocation penalty for a peer.

        Enhanced for v1.4 with subnet-level tracking.

        :param peer: The peer ID
        :return: The IP colocation penalty (positive value that will be subtracted)
        """
        if peer not in self.ip_by_peer:
            return 0.0

        ip_str = self.ip_by_peer[peer]

        # Exact IP colocation penalty
        exact_ip_count = len(self.peer_ips[ip_str])
        ip_penalty = 0.0

        if exact_ip_count > self.params.p7_ip_colocation_threshold:
            excess_peers = exact_ip_count - self.params.p7_ip_colocation_threshold
            ip_penalty = self.params.p7_ip_colocation_weight * (excess_peers**2)

        # Additional subnet-level penalty (lighter weight)
        subnet = self._get_subnet(ip_str)
        subnet_penalty = 0.0

        if subnet and subnet in self.subnet_tracking:
            subnet_count = len(self.subnet_tracking[subnet])
            subnet_threshold = (
                self.params.p7_ip_colocation_threshold * 3
            )  # More lenient for subnets

            if subnet_count > subnet_threshold:
                excess_subnet_peers = subnet_count - subnet_threshold
                # Apply lighter penalty for subnet colocation
                subnet_penalty = (
                    self.params.p7_ip_colocation_weight * 0.1
                ) * excess_subnet_peers

        return ip_penalty + subnet_penalty

    def score(self, peer: ID, topics: list[str]) -> float:
        score = 0.0
        for t in topics:
            score += self.topic_score(peer, t)

        # Behavior penalty activates beyond threshold
        total_behavior_penalty = (
            self.behavior_penalty[peer]
            + self.graft_flood_penalties[peer]
            + self.iwant_spam_penalties[peer]
            + self.ihave_spam_penalties[peer]
            + self.equivocation_penalties[peer]
        )

        if total_behavior_penalty > self.params.p5_behavior_penalty_threshold:
            score -= (
                total_behavior_penalty - self.params.p5_behavior_penalty_threshold
            ) * self.params.p5_behavior_penalty_weight

        # P6: Application-specific scoring
        if self.params.app_specific_score_fn is not None:
            self.update_app_specific_score(peer)
            score += self.app_specific_scores[peer] * self.params.p6_appl_slack_weight

        # P7: IP colocation penalty
        ip_penalty = self.ip_colocation_penalty(peer)
        score -= ip_penalty

        return score

    # ---- Gates ----
    def allow_publish(self, peer: ID, topics: list[str]) -> bool:
        """
        Check if a peer is allowed to publish to the given topics.

        If a single topic is provided, the peer must meet the threshold for that topic.
        If multiple topics are provided, the peer must meet the threshold for
        the combined score.
        """
        # Empty topic list - default to False for safety
        if not topics:
            return False

        # When checking a single topic, we need to ensure the peer meets
        # the threshold for that specific topic only
        if len(topics) == 1:
            topic = topics[0]
            # Calculate the topic-specific score
            topic_score = self.topic_score(peer, topic)

            # Apply behavior penalty if applicable
            if self.behavior_penalty[peer] > self.params.p5_behavior_penalty_threshold:
                topic_score -= (
                    self.behavior_penalty[peer]
                    - self.params.p5_behavior_penalty_threshold
                ) * self.params.p5_behavior_penalty_weight

            # Check against the threshold
            return topic_score >= self.params.publish_threshold

        # For multiple topics, use the combined score
        return self.score(peer, topics) >= self.params.publish_threshold

    def allow_gossip(self, peer: ID, topics: list[str]) -> bool:
        """
        Check if a peer is allowed to gossip about the given topics.

        If a single topic is provided, the peer must meet the threshold for that topic.
        If multiple topics are provided, the peer must meet the threshold for
        the combined score.
        """
        # Empty topic list - default to False for safety
        if not topics:
            return False

        # When checking a single topic, we need to ensure the peer meets
        # the threshold for that specific topic only
        if len(topics) == 1:
            topic = topics[0]
            # Calculate the topic-specific score
            topic_score = self.topic_score(peer, topic)

            # Apply behavior penalty if applicable
            if self.behavior_penalty[peer] > self.params.p5_behavior_penalty_threshold:
                topic_score -= (
                    self.behavior_penalty[peer]
                    - self.params.p5_behavior_penalty_threshold
                ) * self.params.p5_behavior_penalty_weight

            # Check against the threshold
            return topic_score >= self.params.gossip_threshold

        # For multiple topics, use the combined score
        return self.score(peer, topics) >= self.params.gossip_threshold

    def is_graylisted(self, peer: ID, topics: list[str]) -> bool:
        """
        Check if a peer is graylisted based on their score for the given topics.

        A peer is graylisted if their score is below the graylist threshold.
        """
        # Empty topic list - default to False for safety
        if not topics:
            return False

        # For graylisting, we always use the combined score
        # as it's a more conservative approach
        return self.score(peer, topics) < self.params.graylist_threshold

    def allow_px_from(self, peer: ID, topics: list[str]) -> bool:
        """
        Check if peer exchange (PX) is allowed from the given peer for the topics.

        PX is allowed if the peer's score meets or exceeds the accept_px_threshold.
        """
        # Empty topic list - default to False for safety
        if not topics:
            return False

        # For PX acceptance, we always use the combined score
        # as it's a more conservative approach
        return self.score(peer, topics) >= self.params.accept_px_threshold

    # ---- Observability ----
    def get_score_stats(self, peer: ID, topic: str) -> dict[str, float | str]:
        """
        Get detailed score statistics for a peer in a specific topic.

        Useful for debugging, monitoring, and understanding peer behavior.

        :param peer: The peer ID to get stats for
        :param topic: The topic to get stats for
        :return: Dictionary containing all score components and total score
        """
        return {
            "time_in_mesh": self.time_in_mesh[peer][topic],
            "first_deliveries": self.first_message_deliveries[peer][topic],
            "mesh_deliveries": self.mesh_message_deliveries[peer][topic],
            "invalid_messages": self.invalid_messages[peer][topic],
            "behavior_penalty": self.behavior_penalty[peer],
            "graft_flood_penalty": self.graft_flood_penalties[peer],
            "iwant_spam_penalty": self.iwant_spam_penalties[peer],
            "ihave_spam_penalty": self.ihave_spam_penalties[peer],
            "equivocation_penalty": self.equivocation_penalties[peer],
            "app_specific_score": self.app_specific_scores[peer],
            "ip_colocation_penalty": self.ip_colocation_penalty(peer),
            "peer_ip": self.ip_by_peer.get(peer, "unknown"),
            "total_score": self.score(peer, [topic]),
        }

    def get_all_peer_scores(self, topics: list[str]) -> dict[str, float]:
        """
        Get scores for all tracked peers across specified topics.

        :param topics: List of topics to calculate scores for
        :return: Dictionary mapping peer ID strings to their scores
        """
        all_peers: set[ID] = set()
        for topic_dict in [
            self.time_in_mesh,
            self.first_message_deliveries,
            self.mesh_message_deliveries,
            self.invalid_messages,
        ]:
            all_peers.update(topic_dict.keys())

        # Also include peers from behavior_penalty dict
        all_peers.update(self.behavior_penalty.keys())

        return {str(peer): self.score(peer, topics) for peer in all_peers}
