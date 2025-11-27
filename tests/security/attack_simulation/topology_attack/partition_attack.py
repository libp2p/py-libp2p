from typing import Any

import trio

from ..utils.attack_metrics import AttackMetrics


class NetworkPartitioner:
    def __init__(
        self,
        node_ids: list[str],
        partitions: list[list[str]],
        intensity: float = 1.0,
    ):
        self.node_ids = node_ids
        self.partitions = partitions
        self.intensity = intensity
        self.cut_edges: list[tuple[str, str]] = []
        self.remaining_edges: list[tuple[str, str]] = []

    def _build_full_mesh(self) -> list[tuple[str, str]]:
        edges: list[tuple[str, str]] = []
        for i in range(len(self.node_ids)):
            for j in range(i + 1, len(self.node_ids)):
                edges.append((self.node_ids[i], self.node_ids[j]))
        return edges

    def _partition_index(self) -> dict[str, int]:
        mapping: dict[str, int] = {}
        for idx, group in enumerate(self.partitions):
            for n in group:
                mapping[n] = idx
        # any node not explicitly in a partition goes to partition 0
        for n in self.node_ids:
            mapping.setdefault(n, 0)
        return mapping

    async def apply_partition(
        self,
    ) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
        part_map = self._partition_index()
        edges = self._build_full_mesh()
        self.cut_edges = []
        self.remaining_edges = []

        for u, v in edges:
            if part_map[u] != part_map[v]:
                self.cut_edges.append((u, v))
            else:
                self.remaining_edges.append((u, v))

        await trio.sleep(0.05 * max(0.1, self.intensity))
        return self.cut_edges, self.remaining_edges


class TopologyPartitionScenario:
    def __init__(self, node_ids: list[str], attacker: NetworkPartitioner):
        self.node_ids = node_ids
        self.attacker = attacker
        self.metrics = AttackMetrics()

    async def run(self) -> dict[str, Any]:
        cut_edges, remaining_edges = await self.attacker.apply_partition()
        total_edges = len(cut_edges) + len(remaining_edges)
        cut_ratio = cut_edges_count = 0.0

        if total_edges > 0:
            cut_edges_count = len(cut_edges)
            cut_ratio = cut_edges_count / total_edges

        # Simple notion of "affected nodes"
        affected_nodes = set()
        for u, v in cut_edges:
            affected_nodes.add(u)
            affected_nodes.add(v)
        affected_nodes_percentage = (
            len(affected_nodes) / len(self.node_ids) * 100.0 if self.node_ids else 0.0
        )

        # ----------------------------
        # Populate AttackMetrics-style values
        # ----------------------------

        # lookup success degrades as partitions cut more of the network
        lookup_success_degradation = cut_ratio
        lookup_failure_rate = min(cut_ratio * 0.6, 0.95)

        self.metrics.lookup_success_rate = [
            0.99,
            max(0.99 - lookup_success_degradation * 0.7, 0.4),
            0.97,
        ]
        self.metrics.lookup_failure_rate = lookup_failure_rate

        routing_incorrect_rate = cut_ratio * 0.4
        self.metrics.routing_incorrect_rate = routing_incorrect_rate

        self.metrics.avg_lookup_latency = [
            0.04,
            0.04 + cut_ratio * 0.5,
            0.06,
        ]

        self.metrics.network_connectivity = [
            1.0,
            max(1.0 - cut_ratio * 0.8, 0.2),
            0.9,
        ]

        self.metrics.peer_table_contamination = [
            0.0,
            min(cut_ratio, 1.0),
            min(cut_ratio * 0.5, 1.0),
        ]

        # simple resource model
        self.metrics.memory_usage = [90, 90 + cut_ratio * 25, 95]
        self.metrics.bandwidth_consumption = [30, 30 + cut_ratio * 40, 45]
        self.metrics.cpu_utilization = [6, 6 + cut_ratio * 20, 10]

        # resilience score goes down as cut_ratio grows
        resilience_score = max(0.0, 1.0 - cut_ratio * 1.5)
        self.metrics.resilience_score = resilience_score

        attack_metrics: dict[str, Any] = {
            "partition_cut_ratio": cut_ratio,
            "routing_incorrect_rate": routing_incorrect_rate,
            "lookup_failure_rate": lookup_failure_rate,
            "avg_lookup_latency": self.metrics.avg_lookup_latency,
            "resilience_score": resilience_score,
            "network_connectivity": self.metrics.network_connectivity,
            "peer_table_contamination": self.metrics.peer_table_contamination,
            "lookup_success_degradation": lookup_success_degradation,
            "affected_nodes_percentage": affected_nodes_percentage,
        }

        return {
            "cut_edges": cut_edges,
            "remaining_edges": remaining_edges,
            "cut_ratio": cut_ratio,
            "attack_metrics": attack_metrics,
        }
