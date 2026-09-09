"""
Protocol Attack Implementation

This module implements protocol-level attacks that exploit weaknesses
in libp2p protocols, such as malformed messages, protocol violations, etc.
"""

import logging
import random
from typing import Any

import trio

from ..utils.attack_metrics import AttackMetrics

logger = logging.getLogger(__name__)


class ProtocolExploitAttacker:
    """Malicious peer that exploits protocol weaknesses"""

    def __init__(self, peer_id: str, exploit_type: str, intensity: float):
        self.peer_id = peer_id
        self.exploit_type = (
            exploit_type  # "malformed_msg", "protocol_violation", "handshake_exploit"
        )
        self.intensity = intensity
        self.exploits_attempted: list[dict[str, Any]] = []
        self.successful_exploits: list[dict[str, Any]] = []
        self.victims_affected: list[str] = []

    async def execute_malformed_message_attack(
        self, target_peers: list[str], duration: float = 30.0
    ):
        """Send malformed messages to exploit protocol parsing"""
        exploits_per_second = int(10 * self.intensity)  # 0-10 malformed msgs/sec

        async with trio.open_nursery() as nursery:
            for target in target_peers:
                nursery.start_soon(
                    self._send_malformed_messages, target, exploits_per_second, duration
                )

    async def _send_malformed_messages(
        self, target: str, exploit_rate: int, duration: float
    ):
        """Send malformed messages to a specific target"""
        end_time = trio.current_time() + duration

        while trio.current_time() < end_time:
            for i in range(exploit_rate):
                exploit = {
                    "type": "malformed_message",
                    "target": target,
                    "exploit_id": f"{self.peer_id}_malformed_{target}_{i}",
                    "payload": self._generate_malformed_payload(),
                    "timestamp": trio.current_time(),
                }

                self.exploits_attempted.append(exploit)

                # Simulate success/failure
                if (
                    trio.current_time() % 2 < self.intensity
                ):  # Success based on intensity
                    exploit["success"] = "true"  # Using string instead of boolean
                    self.successful_exploits.append(exploit)
                    if target not in self.victims_affected:
                        self.victims_affected.append(target)

            await trio.sleep(0.1)  # Optimized for faster test execution

    async def execute_protocol_violation_attack(
        self, target_peers: list[str], duration: float = 30.0
    ):
        """Violate protocol rules to cause crashes or undefined behavior"""
        violations_per_second = int(5 * self.intensity)  # 0-5 violations/sec

        async with trio.open_nursery() as nursery:
            for target in target_peers:
                nursery.start_soon(
                    self._send_protocol_violations,
                    target,
                    violations_per_second,
                    duration,
                )

    async def _send_protocol_violations(
        self, target: str, violation_rate: int, duration: float
    ):
        """Send protocol violations to a specific target"""
        end_time = trio.current_time() + duration

        while trio.current_time() < end_time:
            for i in range(violation_rate):
                violation = {
                    "type": "protocol_violation",
                    "target": target,
                    "violation_id": f"{self.peer_id}_violation_{target}_{i}",
                    "violation_type": self._random_violation_type(),
                    "timestamp": trio.current_time(),
                }

                self.exploits_attempted.append(violation)

                # Protocol violations often succeed in causing issues
                if trio.current_time() % 3 < self.intensity * 2:
                    violation["success"] = "true"  # Using string instead of boolean
                    self.successful_exploits.append(violation)
                    if target not in self.victims_affected:
                        self.victims_affected.append(target)

            await trio.sleep(0.1)  # Optimized for faster test execution

    async def execute_handshake_exploit(
        self, target_peers: list[str], duration: float = 30.0
    ):
        """Exploit handshake protocol weaknesses"""
        handshakes_per_second = int(3 * self.intensity)  # 0-3 handshake exploits/sec

        async with trio.open_nursery() as nursery:
            for target in target_peers:
                nursery.start_soon(
                    self._exploit_handshakes, target, handshakes_per_second, duration
                )

    async def _exploit_handshakes(
        self, target: str, handshake_rate: int, duration: float
    ):
        """Exploit handshakes with a specific target"""
        end_time = trio.current_time() + duration

        while trio.current_time() < end_time:
            for i in range(handshake_rate):
                exploit = {
                    "type": "handshake_exploit",
                    "target": target,
                    "exploit_id": f"{self.peer_id}_handshake_{target}_{i}",
                    "exploit_method": self._random_handshake_exploit(),
                    "timestamp": trio.current_time(),
                }

                self.exploits_attempted.append(exploit)

                # Handshake exploits can be very effective
                if trio.current_time() % 4 < self.intensity * 3:
                    exploit["success"] = "true"  # Using string instead of boolean
                    self.successful_exploits.append(exploit)
                    if target not in self.victims_affected:
                        self.victims_affected.append(target)

            await trio.sleep(0.1)  # Optimized for faster test execution

    def _generate_malformed_payload(self) -> bytes:
        """Generate a malformed payload for testing protocol robustness"""
        malformed_types = [
            b"",  # Empty payload
            b"\x00\x01\x02",  # Invalid encoding
            b"A" * 10000,  # Oversized payload
            b"\xff\xfe\xfd",  # Invalid UTF-8
        ]
        return random.choice(malformed_types)

    def _random_violation_type(self) -> str:
        """Generate a random protocol violation type"""
        violations = [
            "invalid_message_length",
            "wrong_protocol_version",
            "missing_required_field",
            "invalid_peer_id",
            "malformed_multiaddr",
        ]
        return random.choice(violations)

    def _random_handshake_exploit(self) -> str:
        """Generate a random handshake exploit method"""
        exploits = [
            "incomplete_handshake",
            "wrong_crypto_suite",
            "invalid_certificate",
            "timing_attack",
            "replay_attack",
        ]
        return random.choice(exploits)


class ProtocolAttackScenario:
    """Defines a protocol-level attack scenario"""

    def __init__(
        self, honest_peers: list[str], protocol_attackers: list[ProtocolExploitAttacker]
    ):
        self.honest_peers = honest_peers
        self.protocol_attackers = protocol_attackers
        self.metrics = AttackMetrics()

    async def execute_protocol_attack(
        self, attack_duration: float = 30.0
    ) -> dict[str, Any]:
        """Execute the complete protocol attack scenario"""
        logger.info("Executing Protocol Attack Scenario")
        logger.info("Honest peers: %d", len(self.honest_peers))
        logger.info("Protocol attackers: %d", len(self.protocol_attackers))
        logger.info("Attack duration: %f seconds", attack_duration)

        # Execute different types of protocol exploits
        async with trio.open_nursery() as nursery:
            for attacker in self.protocol_attackers:
                if attacker.exploit_type == "malformed_msg":
                    nursery.start_soon(
                        attacker.execute_malformed_message_attack,
                        self.honest_peers,
                        attack_duration,
                    )
                elif attacker.exploit_type == "protocol_violation":
                    nursery.start_soon(
                        attacker.execute_protocol_violation_attack,
                        self.honest_peers,
                        attack_duration,
                    )
                elif attacker.exploit_type == "handshake_exploit":
                    nursery.start_soon(
                        attacker.execute_handshake_exploit,
                        self.honest_peers,
                        attack_duration,
                    )

        # Wait for attack to complete (optimized for faster tests)
        await trio.sleep(min(2.0, attack_duration / 5))

        # Collect statistics
        total_exploits = 0
        successful_exploits = 0
        affected_victims = set()

        for attacker in self.protocol_attackers:
            total_exploits += len(attacker.exploits_attempted)
            successful_exploits += len(attacker.successful_exploits)
            affected_victims.update(attacker.victims_affected)

        logger.info("Total exploits attempted: %d", total_exploits)
        logger.info("Successful exploits: %d", successful_exploits)
        logger.info("Victims affected: %d", len(affected_victims))

        # Calculate protocol-specific metrics
        self._calculate_protocol_metrics(
            total_exploits, successful_exploits, len(affected_victims), attack_duration
        )

        return {
            "total_exploits_attempted": total_exploits,
            "successful_exploits": successful_exploits,
            "victims_affected": len(affected_victims),
            "success_rate": successful_exploits / total_exploits
            if total_exploits > 0
            else 0,
            "attack_duration": attack_duration,
            "attack_metrics": self.metrics.generate_attack_report(),
        }

    def _calculate_protocol_metrics(
        self,
        total_exploits: int,
        successful_exploits: int,
        victims_affected: int,
        duration: float,
    ):
        """Calculate metrics specific to protocol attacks"""
        success_rate = successful_exploits / total_exploits if total_exploits > 0 else 0
        victim_ratio = (
            victims_affected / len(self.honest_peers) if self.honest_peers else 0
        )
        exploit_rate = total_exploits / duration if duration > 0 else 0

        # Protocol exploits can cause severe but targeted damage
        base_success = 0.95
        protocol_impact = min(success_rate * 0.6 + victim_ratio * 0.4, 0.9)
        during_attack = max(base_success - protocol_impact, 0.2)

        self.metrics.lookup_success_rate = [
            base_success,
            during_attack,
            base_success * 0.98,
        ]
        self.metrics.peer_table_contamination = [
            0.0,
            victim_ratio * 0.1,
            victim_ratio * 0.05,
        ]
        self.metrics.network_connectivity = [
            1.0,
            max(1.0 - protocol_impact * 0.7, 0.5),
            0.95,
        ]
        self.metrics.message_delivery_rate = [
            0.98,
            max(0.98 - protocol_impact * 0.5, 0.6),
            0.97,
        ]

        # Protocol attack metrics
        self.metrics.time_to_partitioning = 30 + success_rate * 90  # Variable timing
        self.metrics.affected_nodes_percentage = victim_ratio * 100
        self.metrics.attack_persistence = (
            success_rate * 0.8
        )  # Can be persistent if exploits work

        # Resource impact - protocol exploits are targeted but resource-efficient
        base_memory = 100
        base_cpu = 10
        base_bandwidth = 50

        memory_impact = min(exploit_rate * 2, 50)  # Protocol parsing uses some memory
        cpu_impact = min(exploit_rate * 5, 150)  # Protocol validation uses CPU
        bandwidth_impact = min(exploit_rate * 10, 100)  # Exploit messages use bandwidth

        self.metrics.memory_usage = [
            base_memory,
            base_memory + memory_impact,
            base_memory * 1.02,
        ]
        self.metrics.cpu_utilization = [
            base_cpu,
            base_cpu + cpu_impact,
            base_cpu * 1.05,
        ]
        self.metrics.bandwidth_consumption = [
            base_bandwidth,
            base_bandwidth + bandwidth_impact,
            base_bandwidth * 1.1,
        ]

        # Recovery metrics
        self.metrics.recovery_time = (
            protocol_impact * 45 + 15
        )  # Protocol fixes take time
        self.metrics.detection_time = 10.0  # Protocol issues are detectable
        self.metrics.mitigation_effectiveness = (
            0.95  # Very effective with protocol updates
        )

        # Protocol-specific metrics
        self.metrics.dht_poisoning_rate = 0.0  # Doesn't directly poison DHT
        self.metrics.peer_table_flooding_rate = 0.0  # Doesn't flood peer tables
        self.metrics.routing_disruption_level = protocol_impact * 0.3
