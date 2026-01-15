import random
from typing import Any

import trio

from ..utils.attack_metrics import AttackMetrics


class RoutingPoisoner:
    def __init__(self, base_peer_id: str, fake_rate: float, intensity: float = 1.0):
        self.base_peer_id = base_peer_id
        self.fake_rate = fake_rate
        self.intensity = intensity
        self.advertised_entries: list[dict] = []

    async def create_fake_entries(self, count: int) -> list[dict]:
        self.advertised_entries = []
        for i in range(count):
            fake_peer = f"{self.base_peer_id}_rpoison_{random.randint(1000, 9999)}"
            fake_addr = (
                f"/ip4/10.0.{random.randint(0, 255)}.{random.randint(1, 254)}/tcp/4001"
            )
            entry = {"peer_id": fake_peer, "addresses": [fake_addr], "marker": "fake"}
            self.advertised_entries.append(entry)
            await trio.sleep(0.01 * max(0.01, 1.0 / (self.fake_rate * self.intensity)))
        return self.advertised_entries

    async def advertise_to_targets(self, targets: list[str], duration: float):
        targets = list(targets)
        if not targets:
            return
        end = trio.current_time() + duration
        while trio.current_time() < end:
            fake_peer = f"{self.base_peer_id}_rpoison_{random.randint(1000, 9999)}"
            fake_addr = (
                f"/ip4/10.0.{random.randint(0, 255)}.{random.randint(1, 254)}/tcp/4001"
            )
            entry = {"peer_id": fake_peer, "addresses": [fake_addr], "marker": "fake"}
            self.advertised_entries.append(entry)
            for t in list(targets):
                try:
                    await self._send_advert(t, entry)
                except IndexError:
                    continue
                except Exception:
                    continue
            await trio.sleep(1.0 / max(self.fake_rate, 0.01))

    async def _send_advert(self, target: str, entry: dict):
        """Send advertisement to target peer (simulated)"""
        # Simulate sending advertisement
        await trio.sleep(0.001)


class RoutingPoisoningScenario:
    def __init__(self, honest_peers: list[str], poisoners: list[RoutingPoisoner]):
        self.honest_peers = honest_peers
        self.poisoners = poisoners
        self.metrics = AttackMetrics()

    async def execute_poisoning(self) -> dict[str, Any]:
        duration = 4.0
        async with trio.open_nursery() as n:
            for p in self.poisoners:
                n.start_soon(p.advertise_to_targets, self.honest_peers, duration)
        self._calculate_metrics()
        return {
            "total_fake_entries": sum(
                len(p.advertised_entries) for p in self.poisoners
            ),
            "attack_metrics": self.metrics.generate_attack_report(),
        }

    def _calculate_metrics(self):
        total_honest = len(self.honest_peers)
        total_fake = sum(len(p.advertised_entries) for p in self.poisoners)
        poison_ratio = total_fake / max(1, total_honest)
        self.metrics.lookup_success_rate = [
            0.99,
            max(0.99 - poison_ratio * 0.45, 0.05),
            0.97,
        ]
        self.metrics.routing_incorrect_rate = poison_ratio * 0.25
        self.metrics.lookup_failure_rate = min(poison_ratio * 0.2, 0.95)
        self.metrics.avg_lookup_latency = [0.04, 0.04 + poison_ratio * 0.25, 0.06]
        self.metrics.resilience_score = (1 - self.metrics.routing_incorrect_rate) * (
            1 - self.metrics.lookup_failure_rate
        )
        self.metrics.peer_table_contamination = [
            0.0,
            min(poison_ratio, 1.0),
            min(poison_ratio * 0.6, 1.0),
        ]
        self.metrics.time_to_recovery = 20 + poison_ratio * 80
        self.metrics.affected_nodes_percentage = min(poison_ratio * 100, 100)
        self.metrics.memory_usage = [90, 90 + poison_ratio * 35, 95]
        self.metrics.cpu_utilization = [6, 6 + poison_ratio * 25, 8]
        self.metrics.bandwidth_consumption = [30, 30 + poison_ratio * 70, 45]
        self.metrics.network_connectivity = [
            1.0,
            max(1.0 - poison_ratio * 0.5, 0.5),
            0.85,
        ]
