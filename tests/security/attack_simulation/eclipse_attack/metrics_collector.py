"""
Attack metrics collection for Eclipse attack simulations
"""

from dataclasses import dataclass, field
import time
from typing import Any


@dataclass
class AttackMetrics:
    """Collects and tracks metrics during attack simulations"""

    attack_type: str = "eclipse"
    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0
    honest_peers: list[str] = field(default_factory=list)
    malicious_peers: list[str] = field(default_factory=list)
    connections_blocked: int = 0
    messages_intercepted: int = 0
    routing_table_poisoning_attempts: int = 0
    network_isolation_achieved: bool = False
    isolation_duration: float = 0.0
    lookup_success_rate: list[float] = field(default_factory=list)
    peer_table_contamination: list[float] = field(default_factory=list)
    network_connectivity: list[float] = field(default_factory=list)
    recovery_time: float = 0.0
    message_delivery_rate: list[float] = field(default_factory=list)
    time_to_partitioning: float = 0.0
    affected_nodes_percentage: float = 0.0
    attack_persistence: float = 0.0
    memory_usage: list[float] = field(default_factory=list)
    cpu_utilization: list[float] = field(default_factory=list)
    bandwidth_consumption: list[float] = field(default_factory=list)
    dht_poisoning_rate: float = 0.0
    peer_table_flooding_rate: float = 0.0
    routing_disruption_level: float = 0.0
    custom_metrics: dict[str, Any] = field(default_factory=dict)

    def record_connection_block(self):
        """Record a blocked connection attempt"""
        self.connections_blocked += 1

    def record_message_intercept(self):
        """Record an intercepted message"""
        self.messages_intercepted += 1

    def record_routing_table_poisoning(self):
        """Record a routing table poisoning attempt"""
        self.routing_table_poisoning_attempts += 1

    def set_isolation_achieved(self, duration: float = 0.0):
        """Mark that network isolation was achieved"""
        self.network_isolation_achieved = True
        self.isolation_duration = duration

    def add_custom_metric(self, key: str, value: Any):
        """Add a custom metric"""
        self.custom_metrics[key] = value

    def finalize(self):
        """Finalize metrics collection"""
        self.end_time = time.time()

    def calculate_metrics(
        self,
        honest_peers: list[str],
        malicious_peers: list[Any],
        attack_intensity: float,
    ):
        """Calculate attack metrics based on network state and attack parameters"""
        self.honest_peers = honest_peers
        self.malicious_peers = [
            str(peer.peer_id) if hasattr(peer, "peer_id") else str(peer)
            for peer in malicious_peers
        ]

        # Simulate realistic attack metrics based on intensity
        base_connections = len(honest_peers) * 2  # Assume each peer has ~2 connections
        self.connections_blocked = int(base_connections * attack_intensity * 0.7)
        self.messages_intercepted = int(base_connections * attack_intensity * 10)
        self.routing_table_poisoning_attempts = int(
            len(malicious_peers) * attack_intensity * 5
        )

        # Network isolation is more likely with
        #  higher intensity and more malicious peers
        isolation_probability = min(
            attack_intensity * len(malicious_peers) / len(honest_peers), 0.9
        )

        if isolation_probability > 0.5:
            self.network_isolation_achieved = True
            self.isolation_duration = isolation_probability * 10.0  # seconds

        # Calculate lookup success rates for each honest peer
        self.lookup_success_rate = []
        for i in range(len(honest_peers)):
            # Success rate decreases with attack intensity
            base_rate = 0.95
            attack_impact = attack_intensity * 0.6
            success_rate = max(0.1, base_rate - attack_impact)
            self.lookup_success_rate.append(success_rate)

        # Calculate peer table contamination for each honest peer
        self.peer_table_contamination = []
        for i in range(len(honest_peers)):
            # Contamination increases with attack intensity
            contamination = min(0.9, attack_intensity * 0.8)
            self.peer_table_contamination.append(contamination)

        # Calculate network connectivity for each honest peer
        self.network_connectivity = []
        for i in range(len(honest_peers)):
            # Connectivity decreases with attack intensity
            base_connectivity = 0.9
            connectivity_loss = attack_intensity * 0.7
            connectivity = max(0.1, base_connectivity - connectivity_loss)
            self.network_connectivity.append(connectivity)

        # Calculate recovery time based on attack intensity
        self.recovery_time = attack_intensity * 30.0 + 5.0  # 5-35 seconds

        # Calculate message delivery rates for each honest peer
        self.message_delivery_rate = []
        for i in range(len(honest_peers)):
            # Delivery rate decreases with attack intensity
            base_rate = 0.98
            attack_impact = attack_intensity * 0.5
            delivery_rate = max(0.2, base_rate - attack_impact)
            self.message_delivery_rate.append(delivery_rate)

        # Calculate time to partitioning
        self.time_to_partitioning = max(1.0, (1.0 - attack_intensity) * 15.0)

        # Calculate affected nodes percentage
        self.affected_nodes_percentage = min(100.0, attack_intensity * 80.0 + 10.0)

        # Calculate attack persistence (how long the attack effect lasts)
        self.attack_persistence = attack_intensity * 60.0 + 30.0  # 30-90 seconds

        # Calculate resource usage metrics
        self.memory_usage = []
        self.cpu_utilization = []
        self.bandwidth_consumption = []
        for i in range(len(honest_peers)):
            # Resource usage increases during attack
            base_memory = 50.0  # MB
            base_cpu = 20.0  # %
            base_bandwidth = 100.0  # KB/s

            memory_increase = attack_intensity * 30.0
            cpu_increase = attack_intensity * 40.0
            bandwidth_increase = attack_intensity * 200.0

            self.memory_usage.append(base_memory + memory_increase)
            self.cpu_utilization.append(base_cpu + cpu_increase)
            self.bandwidth_consumption.append(base_bandwidth + bandwidth_increase)

        # Calculate DHT poisoning rate
        self.dht_poisoning_rate = min(0.9, attack_intensity * 0.6)

        # Calculate peer table flooding rate
        self.peer_table_flooding_rate = min(0.95, attack_intensity * 0.8)

        # Calculate routing disruption level
        self.routing_disruption_level = min(1.0, attack_intensity * 0.7 + 0.1)

    def generate_attack_report(self) -> dict[str, Any]:
        """Generate a comprehensive attack report"""
        # Calculate network resilience score (0-100)
        avg_connectivity = (
            sum(self.network_connectivity) / len(self.network_connectivity)
            if self.network_connectivity
            else 0
        )
        avg_lookup_success = (
            sum(self.lookup_success_rate) / len(self.lookup_success_rate)
            if self.lookup_success_rate
            else 0
        )
        avg_message_delivery = (
            sum(self.message_delivery_rate) / len(self.message_delivery_rate)
            if self.message_delivery_rate
            else 0
        )

        network_resilience_score = (
            avg_connectivity * 0.4
            + avg_lookup_success * 0.3
            + avg_message_delivery * 0.3
        ) * 100

        # Generate mitigation recommendations based on attack metrics
        mitigation_recommendations = []

        if avg_connectivity < 0.7:
            mitigation_recommendations.append(
                "Implement redundant peer connections to improve network connectivity"
            )
        if avg_lookup_success < 0.8:
            mitigation_recommendations.append(
                "Deploy DHT redundancy mechanisms to improve lookup success rates"
            )
        if self.dht_poisoning_rate > 0.3:
            mitigation_recommendations.append(
                "Enable DHT entry validation and signature verification"
            )
        if self.peer_table_flooding_rate > 0.5:
            mitigation_recommendations.append(
                "Implement rate limiting for peer table updates"
            )
        if self.routing_disruption_level > 0.6:
            mitigation_recommendations.append(
                "Deploy alternative routing protocols for resilience"
            )
        if self.affected_nodes_percentage > 60:
            mitigation_recommendations.append(
                "Increase network size and diversity to reduce attack impact"
            )
        if self.recovery_time > 20:
            mitigation_recommendations.append(
                "Implement faster recovery mechanisms and backup connections"
            )

        if not mitigation_recommendations:
            mitigation_recommendations.append(
                "Current network resilience is adequate for the given attack scenario"
            )

        return {
            "attack_summary": {
                "attack_type": self.attack_type,
                "total_duration": self.total_duration,
                "network_isolation_achieved": self.network_isolation_achieved,
                "isolation_duration": self.isolation_duration,
                "recovery_time": self.recovery_time,
                "time_to_partitioning": self.time_to_partitioning,
                "affected_nodes_percentage": self.affected_nodes_percentage,
                "attack_persistence": self.attack_persistence,
            },
            "network_metrics": {
                "honest_peers_count": len(self.honest_peers),
                "malicious_peers_count": len(self.malicious_peers),
                "connections_blocked": self.connections_blocked,
                "messages_intercepted": self.messages_intercepted,
                "routing_table_poisoning_attempts": (
                    self.routing_table_poisoning_attempts
                ),
                "dht_poisoning_rate": self.dht_poisoning_rate,
            },
            "peer_metrics": {
                "average_lookup_success_rate": avg_lookup_success,
                "average_peer_table_contamination": (
                    sum(self.peer_table_contamination)
                    / len(self.peer_table_contamination)
                    if self.peer_table_contamination
                    else 0
                ),
                "average_network_connectivity": avg_connectivity,
                "average_message_delivery_rate": avg_message_delivery,
                "lookup_success_rate_per_peer": self.lookup_success_rate,
                "peer_table_contamination_per_peer": self.peer_table_contamination,
                "network_connectivity_per_peer": self.network_connectivity,
                "message_delivery_rate_per_peer": self.message_delivery_rate,
            },
            "resource_metrics": {
                "average_memory_usage": (
                    sum(self.memory_usage) / len(self.memory_usage)
                    if self.memory_usage
                    else 0
                ),
                "average_cpu_utilization": (
                    sum(self.cpu_utilization) / len(self.cpu_utilization)
                    if self.cpu_utilization
                    else 0
                ),
                "average_bandwidth_consumption": (
                    sum(self.bandwidth_consumption) / len(self.bandwidth_consumption)
                    if self.bandwidth_consumption
                    else 0
                ),
                "memory_usage_per_peer": self.memory_usage,
                "cpu_utilization_per_peer": self.cpu_utilization,
                "bandwidth_consumption_per_peer": self.bandwidth_consumption,
            },
            "network_resilience_score": network_resilience_score,
            "mitigation_recommendations": mitigation_recommendations,
            "custom_metrics": self.custom_metrics,
            "timestamp": self.start_time,
        }

    @property
    def total_duration(self) -> float:
        """Get total test duration"""
        end = self.end_time if self.end_time > 0 else time.time()
        return end - self.start_time

    def to_dict(self) -> dict[str, Any]:
        """Convert metrics to dictionary"""
        return {
            "attack_type": self.attack_type,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_duration": self.total_duration,
            "honest_peers_count": len(self.honest_peers),
            "malicious_peers_count": len(self.malicious_peers),
            "connections_blocked": self.connections_blocked,
            "messages_intercepted": self.messages_intercepted,
            "routing_table_poisoning_attempts": self.routing_table_poisoning_attempts,
            "network_isolation_achieved": self.network_isolation_achieved,
            "isolation_duration": self.isolation_duration,
            "lookup_success_rate": self.lookup_success_rate,
            "peer_table_contamination": self.peer_table_contamination,
            "network_connectivity": self.network_connectivity,
            "recovery_time": self.recovery_time,
            "message_delivery_rate": self.message_delivery_rate,
            "time_to_partitioning": self.time_to_partitioning,
            "affected_nodes_percentage": self.affected_nodes_percentage,
            "attack_persistence": self.attack_persistence,
            "memory_usage": self.memory_usage,
            "cpu_utilization": self.cpu_utilization,
            "bandwidth_consumption": self.bandwidth_consumption,
            "dht_poisoning_rate": self.dht_poisoning_rate,
            "peer_table_flooding_rate": self.peer_table_flooding_rate,
            "routing_disruption_level": self.routing_disruption_level,
            "custom_metrics": self.custom_metrics,
        }
