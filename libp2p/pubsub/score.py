from __future__ import annotations

from collections import defaultdict
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

    def on_join_mesh(self, peer: ID, topic: str) -> None:
        # Start counting time in mesh for the peer
        self.time_in_mesh[peer][topic] += 1.0

    def on_leave_mesh(self, peer: ID, topic: str) -> None:
        # No-op; counters decay over time.
        pass

    def on_first_delivery(self, peer: ID, topic: str) -> None:
        self.first_message_deliveries[peer][topic] += 1.0

    def on_mesh_delivery(self, peer: ID, topic: str) -> None:
        self.mesh_message_deliveries[peer][topic] += 1.0

    def on_invalid_message(self, peer: ID, topic: str) -> None:
        self.invalid_messages[peer][topic] += 1.0

    def penalize_behavior(self, peer: ID, amount: float = 1.0) -> None:
        self.behavior_penalty[peer] += amount

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

    def score(self, peer: ID, topics: list[str]) -> float:
        score = 0.0
        for t in topics:
            score += self.topic_score(peer, t)

        # Behavior penalty activates beyond threshold
        if self.behavior_penalty[peer] > self.params.p5_behavior_penalty_threshold:
            score -= (
                self.behavior_penalty[peer] - self.params.p5_behavior_penalty_threshold
            ) * self.params.p5_behavior_penalty_weight

        # TODO: P6 (Application-specific penalty) and P7 (IP colocation penalty)
        # These require application-specific logic and will be implemented
        # when concrete use cases are identified.
        # P6: App-specific scoring based on custom application metrics
        # P7: IP colocation penalty to prevent Sybil attacks from same IP ranges
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
    def get_score_stats(self, peer: ID, topic: str) -> dict[str, float]:
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
