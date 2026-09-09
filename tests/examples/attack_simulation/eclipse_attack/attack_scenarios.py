import trio

from .malicious_peer import MaliciousPeer
from .metrics_collector import AttackMetrics


class EclipseScenario:
    """Defines a reusable Eclipse attack scenario"""

    def __init__(self, honest_peers: list[str], malicious_peers: list[MaliciousPeer]):
        self.honest_peers = honest_peers
        self.malicious_peers = malicious_peers
        self.metrics: AttackMetrics = AttackMetrics()
        self.honest_peer_tables = {p: [] for p in honest_peers}

    async def execute(self):
        # Each malicious peer poisons DHT entries
        async with trio.open_nursery() as nursery:
            for mp in self.malicious_peers:
                for target in self.honest_peers:
                    nursery.start_soon(mp.poison_dht_entries, target)
                    nursery.start_soon(
                        mp.flood_peer_table, self.honest_peer_tables[target]
                    )

        # Calculate realistic metrics based on attack parameters
        attack_intensity = (
            self.malicious_peers[0].intensity if self.malicious_peers else 0.5
        )
        self.metrics.calculate_metrics(
            self.honest_peers, self.malicious_peers, attack_intensity
        )

        return self.metrics
