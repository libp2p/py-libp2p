from collections import (
    defaultdict,
)
from dataclasses import (
    dataclass,
)
import time

from libp2p.peer.id import (
    ID,
)


@dataclass
class TopicScoreParams:
    """Parameters for topic-specific scoring."""

    # Time in mesh parameters
    time_in_mesh_weight: float = 0.01
    time_in_mesh_quantum: float = 1.0  # seconds
    time_in_mesh_cap: float = 3600.0  # 1 hour

    # First message delivery parameters
    first_message_deliveries_weight: float = 1.0
    first_message_deliveries_decay: float = 0.5
    first_message_deliveries_cap: float = 100.0

    # Mesh message delivery parameters
    mesh_message_deliveries_weight: float = -1.0
    mesh_message_deliveries_decay: float = 0.5
    mesh_message_deliveries_threshold: float = 0.8
    mesh_message_deliveries_cap: float = 10.0
    mesh_message_deliveries_activation: float = 1.0  # seconds
    mesh_message_delivery_window: float = 0.1  # seconds

    # Mesh failure parameters
    mesh_failure_penalty_weight: float = -1.0
    mesh_failure_penalty_decay: float = 0.5

    # Invalid message parameters
    invalid_message_deliveries_weight: float = -100.0
    invalid_message_deliveries_decay: float = 0.5


@dataclass
class PeerScoreParams:
    """Parameters for peer scoring."""

    topic_weights: dict[str, float]
    topic_score_params: dict[str, TopicScoreParams]
    app_specific_weight: float = 1.0
    app_specific_decay: float = 0.5
    ip_colocation_factor_weight: float = -1.0
    ip_colocation_factor_threshold: float = 1.0
    ip_colocation_factor_decay: float = 0.5


class PeerScore:
    """Implementation of peer scoring for gossipsub v1.1."""

    def __init__(self, params: PeerScoreParams) -> None:
        self.params = params
        self.scores: dict[ID, float] = {}
        self.topic_scores: dict[ID, dict[str, float]] = defaultdict(dict)

        # Track time in mesh
        self.mesh_time: dict[ID, dict[str, float]] = defaultdict(dict)

        # Track first message deliveries
        self.first_message_deliveries: dict[ID, dict[str, float]] = defaultdict(dict)

        # Track mesh message deliveries
        self.mesh_message_deliveries: dict[ID, dict[str, float]] = defaultdict(dict)
        self.mesh_failures: dict[ID, dict[str, float]] = defaultdict(dict)

        # Track invalid messages
        self.invalid_message_deliveries: dict[ID, dict[str, float]] = defaultdict(dict)

        # Track IP colocation
        self.ip_colocation_factor: dict[ID, float] = {}

        # Track last score update time
        self.last_update: float = time.time()

    def add_peer(self, peer_id: ID) -> None:
        """Add a new peer to the scoring system."""
        if peer_id not in self.scores:
            self.scores[peer_id] = 0.0

    def remove_peer(self, peer_id: ID) -> None:
        """Remove a peer from the scoring system."""
        self.scores.pop(peer_id, None)
        self.topic_scores.pop(peer_id, None)
        self.mesh_time.pop(peer_id, None)
        self.first_message_deliveries.pop(peer_id, None)
        self.mesh_message_deliveries.pop(peer_id, None)
        self.mesh_failures.pop(peer_id, None)
        self.invalid_message_deliveries.pop(peer_id, None)
        self.ip_colocation_factor.pop(peer_id, None)

    def add_to_mesh(self, peer_id: ID, topic: str) -> None:
        """Add a peer to the mesh for a topic."""
        if topic in self.params.topic_score_params:
            self.mesh_time[peer_id][topic] = time.time()

    def remove_from_mesh(self, peer_id: ID, topic: str) -> None:
        """Remove a peer from the mesh for a topic."""
        self.mesh_time[peer_id].pop(topic, None)

    def deliver_message(self, peer_id: ID, topic: str, is_first: bool = False) -> None:
        """Record a message delivery from a peer."""
        if topic not in self.params.topic_score_params:
            return

        self.params.topic_score_params[topic]

        if is_first:
            self.first_message_deliveries[peer_id][topic] = (
                self.first_message_deliveries[peer_id].get(topic, 0) + 1
            )

        if topic in self.mesh_time[peer_id]:
            self.mesh_message_deliveries[peer_id][topic] = (
                self.mesh_message_deliveries[peer_id].get(topic, 0) + 1
            )

    def deliver_invalid_message(self, peer_id: ID, topic: str) -> None:
        """Record an invalid message from a peer."""
        if topic in self.params.topic_score_params:
            self.invalid_message_deliveries[peer_id][topic] = (
                self.invalid_message_deliveries[peer_id].get(topic, 0) + 1
            )

    def record_mesh_failure(self, peer_id: ID, topic: str) -> None:
        """Record a mesh failure for a peer."""
        if topic in self.params.topic_score_params:
            self.mesh_failures[peer_id][topic] = (
                self.mesh_failures[peer_id].get(topic, 0) + 1
            )

    def update_scores(self) -> None:
        """Update all peer scores."""
        current_time = time.time()
        time_diff = current_time - self.last_update

        for peer_id in list(self.scores.keys()):
            score = 0.0

            # Update topic-specific scores
            for topic, params in self.params.topic_score_params.items():
                topic_score = 0.0

                # P1: Time in mesh
                if topic in self.mesh_time[peer_id]:
                    time_in_mesh = current_time - self.mesh_time[peer_id][topic]
                    p1 = min(
                        time_in_mesh / params.time_in_mesh_quantum,
                        params.time_in_mesh_cap,
                    )
                    topic_score += p1 * params.time_in_mesh_weight

                # P2: First message deliveries
                if topic in self.first_message_deliveries[peer_id]:
                    p2 = min(
                        self.first_message_deliveries[peer_id][topic],
                        params.first_message_deliveries_cap,
                    )
                    topic_score += p2 * params.first_message_deliveries_weight

                    # Apply decay
                    self.first_message_deliveries[peer_id][topic] *= (
                        params.first_message_deliveries_decay**time_diff
                    )

                # P3: Mesh message deliveries
                if topic in self.mesh_message_deliveries[peer_id]:
                    p3 = self.mesh_message_deliveries[peer_id][topic]
                    if p3 < params.mesh_message_deliveries_threshold:
                        topic_score += (
                            p3 - params.mesh_message_deliveries_threshold
                        ) * params.mesh_message_deliveries_weight

                    # Apply decay
                    self.mesh_message_deliveries[peer_id][topic] *= (
                        params.mesh_message_deliveries_decay**time_diff
                    )

                # P4: Invalid messages
                if topic in self.invalid_message_deliveries[peer_id]:
                    p4 = self.invalid_message_deliveries[peer_id][topic]
                    topic_score += p4 * params.invalid_message_deliveries_weight

                    # Apply decay
                    self.invalid_message_deliveries[peer_id][topic] *= (
                        params.invalid_message_deliveries_decay**time_diff
                    )

                score += topic_score * self.params.topic_weights.get(topic, 1.0)

            self.scores[peer_id] = score

        self.last_update = current_time

    def get_score(self, peer_id: ID) -> float:
        """Get the current score for a peer."""
        return self.scores.get(peer_id, 0.0)

    def get_topic_score(self, peer_id: ID, topic: str) -> float:
        """Get the current topic-specific score for a peer."""
        return self.topic_scores[peer_id].get(topic, 0.0)
