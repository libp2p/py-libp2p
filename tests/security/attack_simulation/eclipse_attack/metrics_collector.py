class AttackMetrics:
    """Comprehensive metrics collection for attack analysis"""

    def __init__(self):
        # Network Health Metrics
        self.lookup_success_rate: list[float] = []
        self.peer_table_contamination: list[float] = []
        self.network_connectivity: list[float] = []
        self.message_delivery_rate: list[float] = []

        # Attack Effectiveness Metrics
        self.time_to_partitioning: float = 0.0
        self.affected_nodes_percentage: float = 0.0
        self.attack_persistence: float = 0.0

        # Recovery Metrics
        self.recovery_time: float = 0.0
        self.detection_time: float = 0.0
        self.mitigation_effectiveness: float = 0.0

        # Resource Impact Metrics
        self.memory_usage: list[float] = []
        self.cpu_utilization: list[float] = []
        self.bandwidth_consumption: list[float] = []

        # Attack-specific Metrics
        self.dht_poisoning_rate: float = 0.0
        self.peer_table_flooding_rate: float = 0.0
        self.routing_disruption_level: float = 0.0

    def measure_lookup_failures(self, before: float, during: float, after: float):
        self.lookup_success_rate = [before, during, after]

    def calculate_peer_table_pollution(self, honest_peers: list):
        total_peers = sum(len(p["peers"]) for p in honest_peers)
        malicious_peers = sum(len(p.get("malicious_peers", [])) for p in honest_peers)
        return malicious_peers / total_peers if total_peers > 0 else 0

    def calculate_metrics(
        self, honest_peers: list[str], malicious_peers: list, attack_intensity: float
    ):
        """Calculate realistic metrics based on attack parameters"""
        num_honest = len(honest_peers)
        num_malicious = len(malicious_peers)

        # Network Health Metrics
        base_success = 0.95  # Normal success rate
        attack_impact = min(
            attack_intensity * (num_malicious / (num_honest + num_malicious)), 0.9
        )
        during_attack = max(base_success - attack_impact, 0.1)
        after_attack = min(during_attack + 0.3, base_success)  # Partial recovery

        self.lookup_success_rate = [base_success, during_attack, after_attack]

        # Peer table contamination
        contamination = min(attack_intensity * (num_malicious / num_honest), 1.0)
        self.peer_table_contamination = [
            0.0,
            contamination,
            contamination * 0.7,
        ]  # Some cleanup

        # Network connectivity impact
        connectivity_impact = attack_impact * 0.8
        self.network_connectivity = [1.0, max(1.0 - connectivity_impact, 0.2), 0.8]

        # Message delivery rate (correlated with connectivity)
        self.message_delivery_rate = [
            0.98,
            max(0.98 - connectivity_impact * 1.2, 0.1),
            0.85,
        ]

        # Attack Effectiveness Metrics
        self.time_to_partitioning = attack_intensity * 30 + num_malicious * 5  # seconds
        self.affected_nodes_percentage = min(contamination * 100, 100.0)
        self.attack_persistence = contamination * 0.8  # How long attack effects last

        # Recovery Metrics
        self.recovery_time = attack_intensity * 10 + num_malicious * 2
        self.detection_time = attack_intensity * 5 + num_malicious * 1
        self.mitigation_effectiveness = 1.0 - (
            contamination * 0.5
        )  # Effectiveness of defenses

        # Resource Impact Metrics (simulated)
        base_memory = 100  # MB
        base_cpu = 10  # %
        base_bandwidth = 50  # KB/s

        attack_memory = base_memory * (1 + attack_intensity * 0.5)
        attack_cpu = base_cpu * (1 + attack_intensity * 2.0)
        attack_bandwidth = base_bandwidth * (1 + attack_intensity * 3.0)

        self.memory_usage = [base_memory, attack_memory, base_memory * 1.1]
        self.cpu_utilization = [base_cpu, attack_cpu, base_cpu * 1.2]
        self.bandwidth_consumption = [
            base_bandwidth,
            attack_bandwidth,
            base_bandwidth * 1.3,
        ]

        # Attack-specific Metrics
        self.dht_poisoning_rate = attack_intensity * (num_malicious / num_honest)
        self.peer_table_flooding_rate = attack_intensity * num_malicious
        self.routing_disruption_level = attack_impact

    def generate_attack_report(self) -> dict:
        """Generate comprehensive attack analysis report"""
        return {
            "attack_effectiveness": {
                "time_to_partitioning": self.time_to_partitioning,
                "affected_nodes_percentage": self.affected_nodes_percentage,
                "attack_persistence": self.attack_persistence,
                "dht_poisoning_rate": self.dht_poisoning_rate,
                "routing_disruption_level": self.routing_disruption_level,
            },
            "vulnerability_assessment": {
                "lookup_success_degradation": self.lookup_success_rate[0]
                - self.lookup_success_rate[1],
                "max_contamination": max(self.peer_table_contamination),
                "connectivity_impact": self.network_connectivity[0]
                - self.network_connectivity[1],
                "resource_stress": max(self.cpu_utilization) / self.cpu_utilization[0],
            },
            "mitigation_recommendations": self._generate_mitigation_recommendations(),
            "network_resilience_score": self._calculate_resilience_score(),
            "recovery_analysis": {
                "recovery_time": self.recovery_time,
                "detection_time": self.detection_time,
                "mitigation_effectiveness": self.mitigation_effectiveness,
                "full_recovery_achieved": self.lookup_success_rate[2]
                >= self.lookup_success_rate[0] * 0.95,
            },
        }

    def _generate_mitigation_recommendations(self) -> list[str]:
        """Generate specific mitigation recommendations based on metrics"""
        recommendations = []

        if self.affected_nodes_percentage > 50:
            recommendations.append("Implement strict peer validation mechanisms")
        if self.routing_disruption_level > 0.5:
            recommendations.append("Add DHT entry verification and reputation systems")
        if max(self.peer_table_contamination) > 0.3:
            recommendations.append("Enable peer table monitoring and cleanup")
        if self.time_to_partitioning < 60:
            recommendations.append("Implement faster attack detection algorithms")
        if self.mitigation_effectiveness < 0.7:
            recommendations.append("Strengthen network segmentation and isolation")

        return recommendations

    def _calculate_resilience_score(self) -> float:
        """Calculate overall network resilience score (0-100)"""
        base_score = 100.0

        # Penalize for various attack impacts
        lookup_penalty = (
            self.lookup_success_rate[0] - self.lookup_success_rate[1]
        ) * 50
        contamination_penalty = max(self.peer_table_contamination) * 30
        connectivity_penalty = (
            self.network_connectivity[0] - self.network_connectivity[1]
        ) * 20

        resilience_score = (
            base_score - lookup_penalty - contamination_penalty - connectivity_penalty
        )
        return max(0.0, min(100.0, resilience_score))
