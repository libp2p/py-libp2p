class AttackMetrics:
    """Collects metrics during attacks"""

    def __init__(self):
        self.lookup_success_rate: list[float] = []
        self.peer_table_contamination: list[float] = []
        self.network_connectivity: list[float] = []
        self.recovery_time: float = 0.0

    def measure_lookup_failures(self, before: float, during: float, after: float):
        self.lookup_success_rate = [before, during, after]

    def calculate_peer_table_pollution(self, honest_peers: list):
        total_peers = sum(len(p["peers"]) for p in honest_peers)
        malicious_peers = sum(len(p.get("malicious_peers", [])) for p in honest_peers)
        return malicious_peers / total_peers if total_peers > 0 else 0
