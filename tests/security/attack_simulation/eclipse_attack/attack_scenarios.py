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
        # Measure fake metrics
        self.metrics.measure_lookup_failures(1.0, 0.5, 0.9)
        return self.metrics
