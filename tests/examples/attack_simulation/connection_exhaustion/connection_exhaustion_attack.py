"""
Connection Exhaustion Attack Implementation

This module implements connection exhaustion attacks where an attacker
attempts to exhaust the connection limits of target peers.
"""

import logging
from typing import Any

import trio

from ..utils.attack_metrics import AttackMetrics

logger = logging.getLogger(__name__)


class ConnectionExhaustionAttacker:
    """Malicious peer that performs connection exhaustion attacks"""

    def __init__(
        self, peer_id: str, intensity: float, max_connections_per_target: int = 100
    ):
        self.peer_id = peer_id
        self.intensity = intensity
        self.max_connections_per_target = max_connections_per_target
        self.active_connections: dict[str, list[str]] = {}
        self.exhausted_targets: list[str] = []
        self.attack_start_time: float | None = None
        self.attack_end_time: float | None = None

    async def exhaust_connections(
        self, target_peers: list[str], duration: float = 60.0
    ):
        """Attempt to exhaust connection limits of target peers"""
        self.attack_start_time = trio.current_time()

        connections_per_second = int(
            20 * self.intensity
        )  # 0-20 connections/sec per target

        async with trio.open_nursery() as nursery:
            for target in target_peers:
                nursery.start_soon(
                    self._exhaust_target_connections,
                    target,
                    connections_per_second,
                    duration,
                )

        self.attack_end_time = trio.current_time()

    async def _exhaust_target_connections(
        self, target: str, conn_rate: int, duration: float
    ):
        """Exhaust connections for a specific target"""
        end_time = trio.current_time() + duration
        connections = []
        exhausted = False

        while trio.current_time() < end_time and not exhausted:
            # Attempt connections in bursts
            for i in range(conn_rate):
                if len(connections) >= self.max_connections_per_target:
                    exhausted = True
                    break

                conn_id = f"{self.peer_id}_exhaust_{target}_{len(connections)}"
                connections.append(conn_id)

                # Simulate connection establishment time
                await trio.sleep(0.01)

            if not exhausted:
                await trio.sleep(1.0)  # Wait before next burst

        self.active_connections[target] = connections
        if exhausted:
            self.exhausted_targets.append(target)

    async def maintain_exhaustion(
        self, target_peers: list[str], maintenance_duration: float = 30.0
    ):
        """Maintain connection exhaustion by replacing dropped connections"""
        async with trio.open_nursery() as nursery:
            for target in target_peers:
                nursery.start_soon(
                    self._maintain_target_exhaustion, target, maintenance_duration
                )

    async def _maintain_target_exhaustion(self, target: str, duration: float):
        """Maintain exhaustion for a specific target"""
        end_time = trio.current_time() + duration

        while trio.current_time() < end_time:
            current_connections = len(self.active_connections.get(target, []))

            # Simulate some connections being dropped
            drop_rate = 0.1  # 10% drop rate
            dropped = int(current_connections * drop_rate)
            if dropped > 0:
                self.active_connections[target] = self.active_connections[target][
                    dropped:
                ]

            # Replace dropped connections
            while (
                len(self.active_connections[target])
                < self.max_connections_per_target * 0.9
            ):
                conn_count = len(self.active_connections[target])
                conn_id = f"{self.peer_id}_maintain_{target}_{conn_count}"
                self.active_connections[target].append(conn_id)
                await trio.sleep(0.05)

            await trio.sleep(1.0)


class ConnectionExhaustionScenario:
    """Defines a connection exhaustion attack scenario"""

    def __init__(
        self,
        honest_peers: list[str],
        exhaustion_attackers: list[ConnectionExhaustionAttacker],
    ):
        self.honest_peers = honest_peers
        self.exhaustion_attackers = exhaustion_attackers
        self.metrics = AttackMetrics()

    async def execute_connection_exhaustion_attack(
        self, attack_duration: float = 60.0
    ) -> dict[str, Any]:
        """Execute the complete connection exhaustion attack scenario"""
        logger.info("Executing Connection Exhaustion Attack Scenario")
        logger.info("Honest peers: %d", len(self.honest_peers))
        logger.info("Exhaustion attackers: %d", len(self.exhaustion_attackers))
        logger.info("Attack duration: %f seconds", attack_duration)

        # Phase 1: Initial exhaustion
        async with trio.open_nursery() as nursery:
            for attacker in self.exhaustion_attackers:
                nursery.start_soon(
                    attacker.exhaust_connections, self.honest_peers, attack_duration
                )

        # Phase 2: Maintenance phase
        maintenance_duration = min(
            attack_duration * 0.3, 30.0
        )  # 30% of attack time or 30s max
        async with trio.open_nursery() as nursery:
            for attacker in self.exhaustion_attackers:
                nursery.start_soon(
                    attacker.maintain_exhaustion,
                    self.honest_peers,
                    maintenance_duration,
                )

        # Collect statistics
        total_connections = 0
        exhausted_targets = set()

        for attacker in self.exhaustion_attackers:
            for target, connections in attacker.active_connections.items():
                total_connections += len(connections)
            exhausted_targets.update(attacker.exhausted_targets)

        logger.info("Total connections established: %d", total_connections)
        logger.info("Targets exhausted: %d", len(exhausted_targets))

        # Calculate exhaustion-specific metrics
        self._calculate_exhaustion_metrics(
            total_connections, len(exhausted_targets), attack_duration
        )

        return {
            "total_connections_established": total_connections,
            "targets_exhausted": len(exhausted_targets),
            "exhausted_target_list": list(exhausted_targets),
            "attack_duration": attack_duration,
            "attack_metrics": self.metrics.generate_attack_report(),
        }

    def _calculate_exhaustion_metrics(
        self, total_connections: int, exhausted_count: int, duration: float
    ):
        """Calculate metrics specific to connection exhaustion attacks"""
        total_targets = len(self.honest_peers)
        exhaustion_ratio = exhausted_count / total_targets if total_targets > 0 else 0
        connection_rate = total_connections / duration if duration > 0 else 0

        # Connection exhaustion impact on network health
        base_success = 0.95
        # Exhaustion causes gradual degradation
        exhaustion_impact = min(
            exhaustion_ratio * 0.7 + (connection_rate / 100) * 0.3, 0.85
        )
        during_attack = max(base_success - exhaustion_impact, 0.15)

        self.metrics.lookup_success_rate = [
            base_success,
            during_attack,
            base_success * 0.95,
        ]
        self.metrics.peer_table_contamination = [
            0.0,
            exhaustion_ratio * 0.2,
            exhaustion_ratio * 0.1,
        ]
        self.metrics.network_connectivity = [
            1.0,
            max(1.0 - exhaustion_impact * 0.8, 0.4),
            0.90,
        ]
        self.metrics.message_delivery_rate = [
            0.98,
            max(0.98 - exhaustion_impact * 0.6, 0.5),
            0.95,
        ]

        # Exhaustion attack metrics
        self.metrics.time_to_partitioning = (
            120 + exhaustion_ratio * 180
        )  # Takes time to exhaust
        self.metrics.affected_nodes_percentage = exhaustion_ratio * 100
        self.metrics.attack_persistence = (
            exhaustion_ratio * 0.7
        )  # Moderately persistent

        # Resource impact - high memory and connection usage
        base_memory = 100
        base_cpu = 10
        base_bandwidth = 50

        memory_impact = min(connection_rate / 5, 150)  # Connection tables use memory
        cpu_impact = min(connection_rate / 10, 100)  # Connection management uses CPU
        bandwidth_impact = min(
            connection_rate * 2, 200
        )  # Connection handshakes use bandwidth

        self.metrics.memory_usage = [
            base_memory,
            base_memory + memory_impact,
            base_memory * 1.05,
        ]
        self.metrics.cpu_utilization = [base_cpu, base_cpu + cpu_impact, base_cpu * 1.1]
        self.metrics.bandwidth_consumption = [
            base_bandwidth,
            base_bandwidth + bandwidth_impact,
            base_bandwidth * 1.2,
        ]

        # Recovery metrics
        self.metrics.recovery_time = (
            exhaustion_impact * 60 + 30
        )  # Time to clean up connections
        self.metrics.detection_time = 15.0  # Connection exhaustion is detectable
        self.metrics.mitigation_effectiveness = (
            0.9  # Very effective with connection limits
        )

        # Exhaustion-specific metrics
        self.metrics.dht_poisoning_rate = 0.0  # Doesn't poison DHT
        self.metrics.peer_table_flooding_rate = connection_rate
        self.metrics.routing_disruption_level = exhaustion_impact * 0.5
