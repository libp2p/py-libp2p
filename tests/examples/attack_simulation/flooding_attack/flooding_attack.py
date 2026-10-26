"""
Flooding Attack Implementation

This module implements flooding attacks where an attacker overwhelms the network
with excessive messages, causing denial of service through resource exhaustion.
"""

import logging
from typing import Any

import trio

from ..utils.attack_metrics import AttackMetrics

logger = logging.getLogger(__name__)


class FloodingMaliciousPeer:
    """Malicious peer that performs flooding attacks"""

    def __init__(self, peer_id: str, flood_type: str, intensity: float):
        self.peer_id = peer_id
        self.flood_type = flood_type  # "pubsub", "connection", "message"
        self.intensity = intensity
        self.messages_sent: list[str] = []
        self.connections_attempted: list[str] = []
        self.flood_start_time: float | None = None
        self.flood_end_time: float | None = None

    async def initiate_pubsub_flood(
        self, target_topics: list[str], duration: float = 30.0
    ):
        """Flood pubsub topics with spam messages"""
        self.flood_start_time = trio.current_time()
        messages_sent = 0

        # Calculate message rate based on intensity
        messages_per_second = int(100 * self.intensity)  # 0-100 msgs/sec

        async with trio.open_nursery() as nursery:
            for topic in target_topics:
                nursery.start_soon(
                    self._flood_topic, topic, messages_per_second, duration
                )

        self.flood_end_time = trio.current_time()
        return messages_sent

    async def _flood_topic(self, topic: str, msg_rate: int, duration: float):
        """Flood a specific topic"""
        end_time = trio.current_time() + duration
        msg_count = 0

        while trio.current_time() < end_time:
            # Send burst of messages
            for i in range(msg_rate):
                msg_id = f"{self.peer_id}_flood_{topic}_{msg_count}_{i}"
                self.messages_sent.append(msg_id)
                msg_count += 1

            # Wait for next cycle (optimized)
            await trio.sleep(0.1)  # Optimized for faster test execution

    async def initiate_connection_flood(
        self, target_peers: list[str], duration: float = 30.0
    ):
        """Flood with connection attempts"""
        self.flood_start_time = trio.current_time()
        connections_attempted = 0

        connections_per_second = int(50 * self.intensity)  # 0-50 connections/sec

        async with trio.open_nursery() as nursery:
            for target in target_peers:
                nursery.start_soon(
                    self._flood_connections, target, connections_per_second, duration
                )

        self.flood_end_time = trio.current_time()
        return connections_attempted

    async def _flood_connections(self, target: str, conn_rate: int, duration: float):
        """Flood connections to a specific target"""
        end_time = trio.current_time() + duration
        conn_count = 0

        while trio.current_time() < end_time:
            # Attempt burst of connections
            for i in range(conn_rate):
                conn_id = f"{self.peer_id}_conn_flood_{target}_{conn_count}_{i}"
                self.connections_attempted.append(conn_id)
                conn_count += 1

            await trio.sleep(0.1)  # Optimized for faster test execution

    async def initiate_message_flood(
        self, target_peers: list[str], duration: float = 30.0
    ):
        """Flood with direct messages"""
        self.flood_start_time = trio.current_time()
        messages_sent = 0

        messages_per_second = int(200 * self.intensity)  # 0-200 msgs/sec

        async with trio.open_nursery() as nursery:
            for target in target_peers:
                nursery.start_soon(
                    self._flood_messages, target, messages_per_second, duration
                )

        self.flood_end_time = trio.current_time()
        return messages_sent

    async def _flood_messages(self, target: str, msg_rate: int, duration: float):
        """Flood direct messages to a specific target"""
        end_time = trio.current_time() + duration
        msg_count = 0

        while trio.current_time() < end_time:
            for i in range(msg_rate):
                msg_id = f"{self.peer_id}_msg_flood_{target}_{msg_count}_{i}"
                self.messages_sent.append(msg_id)
                msg_count += 1

            await trio.sleep(0.1)  # Optimized for faster test execution


class FloodingAttackScenario:
    """Defines a flooding attack scenario"""

    def __init__(
        self, honest_peers: list[str], flooding_attackers: list[FloodingMaliciousPeer]
    ):
        self.honest_peers = honest_peers
        self.flooding_attackers = flooding_attackers
        self.metrics = AttackMetrics()

    async def execute_flooding_attack(
        self, attack_duration: float = 30.0
    ) -> dict[str, Any]:
        """Execute the complete flooding attack scenario"""
        logger.info("Executing Flooding Attack Scenario")
        logger.info("Honest peers: %d", len(self.honest_peers))
        logger.info("Flooding attackers: %d", len(self.flooding_attackers))
        logger.info("Attack duration: %f seconds", attack_duration)

        total_messages = 0
        total_connections = 0

        # Execute different types of flooding
        async with trio.open_nursery() as nursery:
            for attacker in self.flooding_attackers:
                if attacker.flood_type == "pubsub":
                    nursery.start_soon(
                        attacker.initiate_pubsub_flood,
                        [f"topic_{i}" for i in range(5)],
                        attack_duration,
                    )
                elif attacker.flood_type == "connection":
                    nursery.start_soon(
                        attacker.initiate_connection_flood,
                        self.honest_peers,
                        attack_duration,
                    )
                elif attacker.flood_type == "message":
                    nursery.start_soon(
                        attacker.initiate_message_flood,
                        self.honest_peers,
                        attack_duration,
                    )

        # Wait for attack to complete
        await trio.sleep(attack_duration + 1)

        # Collect statistics
        for attacker in self.flooding_attackers:
            total_messages += len(attacker.messages_sent)
            total_connections += len(attacker.connections_attempted)

        logger.info("Total messages sent: %d", total_messages)
        logger.info("Total connections attempted: %d", total_connections)

        # Calculate flooding-specific metrics
        self._calculate_flooding_metrics(
            total_messages, total_connections, attack_duration
        )

        return {
            "total_messages_sent": total_messages,
            "total_connections_attempted": total_connections,
            "attack_duration": attack_duration,
            "attack_metrics": self.metrics.generate_attack_report(),
        }

    def _calculate_flooding_metrics(
        self, total_messages: int, total_connections: int, duration: float
    ):
        """Calculate metrics specific to flooding attacks"""
        # Message rate per second
        msg_rate = total_messages / duration if duration > 0 else 0
        conn_rate = total_connections / duration if duration > 0 else 0

        # Flooding impact on network health
        base_success = 0.95
        # Higher rates cause more degradation
        flood_impact = min((msg_rate / 1000 + conn_rate / 500) * 0.5, 0.8)
        during_attack = max(base_success - flood_impact, 0.1)

        self.metrics.lookup_success_rate = [
            base_success,
            during_attack,
            base_success * 0.9,
        ]
        self.metrics.peer_table_contamination = [
            0.0,
            min(flood_impact * 0.3, 0.5),
            flood_impact * 0.2,
        ]
        self.metrics.network_connectivity = [
            1.0,
            max(1.0 - flood_impact * 0.6, 0.3),
            0.85,
        ]
        self.metrics.message_delivery_rate = [
            0.98,
            max(0.98 - flood_impact * 0.8, 0.1),
            0.90,
        ]

        # Flooding attack metrics
        self.metrics.time_to_partitioning = max(
            10.0, float(60 - msg_rate / 10)
        )  # Faster with higher rates
        self.metrics.affected_nodes_percentage = min(flood_impact * 100, 90.0)
        self.metrics.attack_persistence = 0.3  # Flooding effects are temporary

        # Resource impact - flooding causes high resource usage
        base_memory = 100
        base_cpu = 10
        base_bandwidth = 50

        memory_impact = min(msg_rate / 50 + conn_rate / 25, 200)
        cpu_impact = min(msg_rate / 100 + conn_rate / 50, 300)
        bandwidth_impact = min(msg_rate / 20 + conn_rate / 10, 500)

        self.metrics.memory_usage = [
            base_memory,
            base_memory + memory_impact,
            base_memory * 1.1,
        ]
        self.metrics.cpu_utilization = [base_cpu, base_cpu + cpu_impact, base_cpu * 1.2]
        self.metrics.bandwidth_consumption = [
            base_bandwidth,
            base_bandwidth + bandwidth_impact,
            base_bandwidth * 1.3,
        ]

        # Recovery metrics
        self.metrics.recovery_time = (
            flood_impact * 30 + 10
        )  # Recovery time based on impact
        self.metrics.detection_time = 5.0  # Flooding is usually quickly detected
        self.metrics.mitigation_effectiveness = (
            0.8  # Good mitigation possible with rate limiting
        )

        # Flooding-specific metrics
        self.metrics.dht_poisoning_rate = 0.0  # Flooding doesn't poison DHT
        self.metrics.peer_table_flooding_rate = conn_rate
        self.metrics.routing_disruption_level = flood_impact * 0.4
