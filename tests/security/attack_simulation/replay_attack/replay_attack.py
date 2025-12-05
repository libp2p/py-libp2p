from typing import Any

import trio

from ..utils.attack_metrics import AttackMetrics


class ReplayAttacker:
    def __init__(self, base_peer_id: str, capture_capacity: int = 50):
        self.base_peer_id = base_peer_id
        self.capture_capacity = capture_capacity
        self.captured_messages: list[dict] = []
        self.replayed_count = 0

    async def capture_message(self, msg: dict):
        if len(self.captured_messages) >= self.capture_capacity:
            self.captured_messages.pop(0)
        self.captured_messages.append(msg)
        await trio.sleep(0)

    async def replay_messages(
        self, targets: list[str], times: int = 1, delay: float = 0.01
    ):
        if not targets:
            return
        for _ in range(times):
            for m in list(self.captured_messages):
                for t in list(targets):
                    await self._send_replay(t, m)
                    self.replayed_count += 1
                    await trio.sleep(delay)

    async def _send_replay(self, target: str, msg: dict):
        # Placeholder for sending replay to target peer in simulation
        await trio.sleep(0)


class ReplayAttackScenario:
    def __init__(self, honest_peers: list[str], attackers: list[ReplayAttacker]):
        self.honest_peers = honest_peers
        self.attackers = attackers
        self.metrics = AttackMetrics()

    async def execute_replay(self) -> dict[str, Any]:
        duration = 3.0
        async with trio.open_nursery() as n:
            for a in self.attackers:
                n.start_soon(self._simulate_capture_and_replay, a, duration)
        self._calculate_metrics()
        return {
            "total_captured": sum(len(a.captured_messages) for a in self.attackers),
            "total_replayed": sum(a.replayed_count for a in self.attackers),
            "attack_metrics": self.metrics.generate_attack_report(),
        }

    async def _simulate_capture_and_replay(
        self, attacker: ReplayAttacker, duration: float
    ):
        end = trio.current_time() + duration
        i = 0
        while trio.current_time() < end:
            msg = {"from": attacker.base_peer_id, "seq": i, "payload": f"data_{i}"}
            await attacker.capture_message(msg)
            i += 1
            await trio.sleep(0.02)
        await attacker.replay_messages(self.honest_peers, times=2, delay=0.01)

    def _calculate_metrics(self):
        total_honest = len(self.honest_peers)
        total_captured = sum(len(a.captured_messages) for a in self.attackers)
        total_replayed = sum(a.replayed_count for a in self.attackers)

        if not getattr(self.metrics, "lookup_success_rate", None):
            self.metrics.lookup_success_rate = [0.99, 0.99, 0.99]
        if not getattr(self.metrics, "network_connectivity", None):
            self.metrics.network_connectivity = [1.0, 1.0, 1.0]
        if not getattr(self.metrics, "peer_table_contamination", None):
            self.metrics.peer_table_contamination = [0.0]
        if not getattr(self.metrics, "cpu_utilization", None):
            self.metrics.cpu_utilization = [1.0]
        if not getattr(self.metrics, "memory_usage", None):
            self.metrics.memory_usage = [80]
        if not getattr(self.metrics, "avg_lookup_latency", None):
            self.metrics.avg_lookup_latency = [0.03, 0.03, 0.03]
        if not getattr(self.metrics, "bandwidth_consumption", None):
            self.metrics.bandwidth_consumption = [20]

        # Fallback metrics when no activity
        if total_captured == 0 and total_replayed == 0:
            self.metrics.lookup_success_rate = [0.99, 0.99, 0.99]
            self.metrics.network_connectivity = [1.0, 1.0, 1.0]
            self.metrics.routing_incorrect_rate = 0.0
            self.metrics.resilience_score = 1.0
            self.metrics.avg_lookup_latency = [0.03, 0.03, 0.03]
            self.metrics.time_to_recovery = 0
            self.metrics.affected_nodes_percentage = 0
            self.metrics.memory_usage = [80, 80, 80]
            self.metrics.cpu_utilization = [5, 5, 5]
            self.metrics.bandwidth_consumption = [20, 20, 20]
            self.metrics.replay_success_rate = 0.0
            self.metrics.state_inconsistency_count = 0
            return

        # Main calculation path
        capture_ratio = total_captured / max(1, total_honest)
        replay_density = total_replayed / max(1, total_honest)

        self.metrics.replay_success_rate = (
            min(1.0, replay_density / max(1.0, capture_ratio))
            if capture_ratio > 0
            else 0.0
        )
        self.metrics.state_inconsistency_count = int(
            max(0.0, replay_density - capture_ratio)
        )
        self.metrics.lookup_success_rate = [
            0.99,
            max(0.99 - replay_density * 0.1, 0.5),
            0.97,
        ]
        self.metrics.network_connectivity = [
            1.0,
            max(1.0 - replay_density * 0.05, 0.7),
            0.95,
        ]
        self.metrics.routing_incorrect_rate = min(0.05 + capture_ratio * 0.1, 1.0)
        self.metrics.avg_lookup_latency = [0.03, 0.03 + replay_density * 0.02, 0.04]
        self.metrics.resilience_score = (1 - self.metrics.routing_incorrect_rate) * (
            1 - (self.metrics.state_inconsistency_count / max(1, total_honest))
        )
        self.metrics.time_to_recovery = 10 + replay_density * 10
        self.metrics.affected_nodes_percentage = min(replay_density * 10, 100)
        self.metrics.memory_usage = [80, 80 + capture_ratio * 20, 85]
        self.metrics.cpu_utilization = [5, 5 + replay_density * 10, 6]
        self.metrics.bandwidth_consumption = [20, 20 + replay_density * 40, 30]
