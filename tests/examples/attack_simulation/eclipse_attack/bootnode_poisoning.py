"""
Bootnode Poisoning Attack Simulation

This module implements a sophisticated bootnode poisoning attack inspired by
Polkadot/Smoldot network security research. When all bootnodes are compromised, nodes
can
become permanently isolated from the honest network.

Key Insight: Nodes discovering peers through poisoned bootnodes will only connect to
malicious peers, creating a persistent network partition.
"""

import logging
import random
from typing import Any

import trio

from ..utils.attack_metrics import AttackMetrics

logger = logging.getLogger(__name__)


class BootnodeAttacker:
    """Malicious bootnode that provides only malicious peer addresses"""

    def __init__(
        self, bootnode_id: str, malicious_peer_pool: list[str], intensity: float
    ):
        self.bootnode_id = bootnode_id
        self.malicious_peer_pool = malicious_peer_pool
        self.intensity = intensity
        self.queries_handled: int = 0
        self.peers_poisoned: set[str] = set()
        self.isolation_success: list[str] = []

    async def respond_to_peer_discovery(self, requesting_peer: str) -> list[str]:
        """Respond to peer discovery request with malicious peers only"""
        self.queries_handled += 1
        self.peers_poisoned.add(requesting_peer)

        # Return only malicious peers based on attack intensity
        num_peers_to_return = max(
            1, int(len(self.malicious_peer_pool) * self.intensity)
        )
        malicious_peers = random.sample(
            self.malicious_peer_pool,
            min(num_peers_to_return, len(self.malicious_peer_pool)),
        )

        # Simulate discovery response delay
        await trio.sleep(random.uniform(0.01, 0.05))

        return malicious_peers

    async def poison_dht_bootstrap(
        self, target_peers: list[str], duration: float = 30.0
    ) -> dict[str, Any]:
        """Poison DHT bootstrap process continuously"""
        start_time = trio.current_time()

        while trio.current_time() - start_time < duration:
            for target in target_peers:
                poisoned_peers = await self.respond_to_peer_discovery(target)
                if len(poisoned_peers) == len(
                    [p for p in poisoned_peers if p in self.malicious_peer_pool]
                ):
                    # Successfully isolated this peer
                    if target not in self.isolation_success:
                        self.isolation_success.append(target)

            await trio.sleep(0.1)  # Query rate control

        return {
            "queries_handled": self.queries_handled,
            "peers_poisoned": len(self.peers_poisoned),
            "isolation_success_count": len(self.isolation_success),
        }


class BootnodePoisoningScenario:
    """
    Simulates a scenario where all bootnodes are malicious, measuring
    network isolation and recovery capabilities.
    """

    def __init__(
        self,
        honest_peers: list[str],
        malicious_bootnodes: list[BootnodeAttacker],
        fallback_peers: list[str] | None = None,
    ):
        self.honest_peers = honest_peers
        self.malicious_bootnodes = malicious_bootnodes
        self.fallback_peers = fallback_peers or []
        self.metrics = AttackMetrics()
        self.attack_results: dict[str, Any] = {}

    async def execute_bootnode_poisoning_attack(
        self, attack_duration: float = 30.0
    ) -> dict[str, Any]:
        """Execute complete bootnode poisoning attack scenario"""
        logger.info("Executing Bootnode Poisoning Attack")
        logger.info("Honest peers: %d", len(self.honest_peers))
        logger.info("Malicious bootnodes: %d", len(self.malicious_bootnodes))
        logger.info("Fallback peers available: %d", len(self.fallback_peers))
        logger.info("Attack duration: %f seconds", attack_duration)

        # Phase 1: Poison bootstrap process
        attack_start = trio.current_time()
        async with trio.open_nursery() as nursery:
            for bootnode in self.malicious_bootnodes:
                nursery.start_soon(
                    bootnode.poison_dht_bootstrap, self.honest_peers, attack_duration
                )

        attack_end = trio.current_time()

        # Phase 2: Measure isolation effects
        isolated_peers = set()
        for bootnode in self.malicious_bootnodes:
            isolated_peers.update(bootnode.isolation_success)

        isolation_rate = len(isolated_peers) / len(self.honest_peers)

        # Phase 3: Test recovery with fallback peers
        recovery_start = trio.current_time()
        recovered_peers = await self._attempt_recovery_with_fallback(
            list(isolated_peers), attack_duration * 0.3
        )
        recovery_end = trio.current_time()

        # Calculate comprehensive metrics
        self._calculate_bootnode_poisoning_metrics(
            isolated_peers=isolated_peers,
            recovered_peers=recovered_peers,
            attack_duration=attack_end - attack_start,
            recovery_time=recovery_end - recovery_start,
        )

        # Generate detailed results
        self.attack_results = {
            "attack_type": "bootnode_poisoning",
            "total_honest_peers": len(self.honest_peers),
            "malicious_bootnodes": len(self.malicious_bootnodes),
            "isolation_metrics": {
                "isolated_peers_count": len(isolated_peers),
                "isolation_rate": isolation_rate,
                "total_queries_handled": sum(
                    b.queries_handled for b in self.malicious_bootnodes
                ),
                "peers_poisoned": len(
                    set().union(*[b.peers_poisoned for b in self.malicious_bootnodes])
                ),
            },
            "recovery_metrics": {
                "recovered_peers_count": len(recovered_peers),
                "recovery_rate": (
                    len(recovered_peers) / len(isolated_peers) if isolated_peers else 0
                ),
                "recovery_time": recovery_end - recovery_start,
                "fallback_effectiveness": self._calculate_fallback_effectiveness(
                    recovered_peers
                ),
            },
            "attack_persistence": {
                "dht_poisoning_persistence": self._measure_dht_persistence(),
                "time_to_isolation": attack_end - attack_start,
                "permanent_isolation_rate": (len(isolated_peers) - len(recovered_peers))
                / len(self.honest_peers),
            },
            "network_health": {
                "lookup_success_rate": self.metrics.lookup_success_rate,
                "peer_table_contamination": self.metrics.peer_table_contamination,
                "network_connectivity": self.metrics.network_connectivity,
            },
            "recommendations": self._generate_bootnode_recommendations(),
        }

        return self.attack_results

    async def _attempt_recovery_with_fallback(
        self, isolated_peers: list[str], recovery_duration: float
    ) -> list[str]:
        """Simulate recovery attempt using fallback peer discovery mechanisms"""
        recovered = []

        if not self.fallback_peers:
            return recovered

        recovery_start = trio.current_time()

        for peer in isolated_peers:
            if trio.current_time() - recovery_start > recovery_duration:
                break

            # Simulate fallback peer discovery (e.g., mDNS, manual peers, etc.)
            recovery_success = random.random() > 0.5  # 50% base recovery rate

            if recovery_success:
                recovered.append(peer)
                await trio.sleep(random.uniform(0.1, 0.3))  # Recovery delay

        return recovered

    def _calculate_bootnode_poisoning_metrics(
        self,
        isolated_peers: set[str],
        recovered_peers: list[str],
        attack_duration: float,
        recovery_time: float,
    ):
        """Calculate specific metrics for bootnode poisoning attack"""
        num_honest = len(self.honest_peers)
        len(self.malicious_bootnodes)
        isolation_rate = len(isolated_peers) / num_honest

        # Network Health Metrics
        base_success = 0.95
        attack_impact = min(isolation_rate, 0.95)
        during_attack = max(base_success - attack_impact, 0.05)
        after_recovery = min(
            during_attack + (len(recovered_peers) / num_honest) * 0.5, base_success
        )

        self.metrics.lookup_success_rate = [base_success, during_attack, after_recovery]

        # Peer table contamination (higher for bootnode attacks)
        contamination = min(isolation_rate * 1.2, 1.0)
        self.metrics.peer_table_contamination = [
            0.0,
            contamination,
            contamination * 0.6,
        ]

        # Network connectivity severely impacted by bootnode poisoning
        connectivity_impact = isolation_rate * 0.9
        self.metrics.network_connectivity = [
            1.0,
            max(1.0 - connectivity_impact, 0.1),
            max(0.3 + (len(recovered_peers) / num_honest) * 0.5, 0.1),
        ]

        # Attack Effectiveness Metrics
        self.metrics.time_to_partitioning = attack_duration
        self.metrics.affected_nodes_percentage = isolation_rate * 100
        self.metrics.attack_persistence = contamination * 0.9  # Very persistent

        # Recovery Metrics
        self.metrics.recovery_time = recovery_time
        self.metrics.detection_time = attack_duration * 0.3  # Detection is harder
        recovery_success = (
            len(recovered_peers) / len(isolated_peers) if isolated_peers else 1.0
        )
        self.metrics.mitigation_effectiveness = recovery_success * 0.7

        # Attack-specific Metrics
        self.metrics.dht_poisoning_rate = isolation_rate
        self.metrics.routing_disruption_level = attack_impact

    def _measure_dht_persistence(self) -> float:
        """Measure how persistent DHT poisoning remains"""
        # Bootnode poisoning is very persistent
        total_queries = sum(b.queries_handled for b in self.malicious_bootnodes)
        avg_intensity = (
            sum(b.intensity for b in self.malicious_bootnodes)
            / len(self.malicious_bootnodes)
            if self.malicious_bootnodes
            else 0
        )

        persistence = min(avg_intensity * (total_queries / 100.0), 1.0)
        return persistence

    def _calculate_fallback_effectiveness(self, recovered_peers: list[str]) -> float:
        """Calculate effectiveness of fallback peer discovery mechanisms"""
        if not self.fallback_peers:
            return 0.0

        # Effectiveness based on recovery rate and fallback peer availability
        effectiveness = len(recovered_peers) / len(self.honest_peers)
        fallback_factor = len(self.fallback_peers) / len(self.honest_peers)

        return min(effectiveness * fallback_factor, 1.0)

    def _generate_bootnode_recommendations(self) -> list[str]:
        """Generate specific mitigation recommendations for bootnode poisoning"""
        recommendations = []

        isolation_rate = self.attack_results.get("isolation_metrics", {}).get(
            "isolation_rate", 0
        )
        if isolation_rate > 0.5:
            recommendations.append(
                "CRITICAL: Implement bootnode diversity and rotation strategies"
            )
            recommendations.append(
                "Use multiple independent bootnode sources (DNS, hardcoded, community)"
            )

        recovery_rate = self.attack_results.get("recovery_metrics", {}).get(
            "recovery_rate", 0
        )
        if recovery_rate < 0.3:
            recommendations.append(
                "Enable fallback peer discovery (mDNS, manual peers)"
            )
            recommendations.append("Implement periodic bootnode health checks")

        permanent_isolation_rate = self.attack_results.get(
            "attack_persistence", {}
        ).get("permanent_isolation_rate", 0)
        if permanent_isolation_rate > 0.3:
            recommendations.append(
                "Add peer reputation system to detect suspicious patterns"
            )
            recommendations.append("Implement checkpoint validation for network state")

        recommendations.append("Monitor DHT query patterns for anomalies")
        recommendations.append("Enable automatic bootnode failover mechanisms")

        return recommendations


async def run_bootnode_poisoning_simulation(
    num_honest_peers: int = 10,
    num_malicious_bootnodes: int = 3,
    attack_intensity: float = 0.8,
    num_fallback_peers: int = 2,
    attack_duration: float = 30.0,
) -> dict[str, Any]:
    """
    Convenience function to run a complete bootnode poisoning simulation.

    Args:
        num_honest_peers: Number of honest nodes in the network
        num_malicious_bootnodes: Number of compromised bootnodes
        attack_intensity: Attack intensity (0.0 to 1.0)
        num_fallback_peers: Number of fallback peers for recovery
        attack_duration: Duration of attack in seconds

    Returns:
        Comprehensive attack simulation results

    """
    # Create honest peers
    honest_peers = [f"honest_peer_{i}" for i in range(num_honest_peers)]

    # Create malicious peer pool
    malicious_peer_pool = [
        f"malicious_peer_{i}" for i in range(num_malicious_bootnodes * 3)
    ]

    # Create malicious bootnodes
    malicious_bootnodes = [
        BootnodeAttacker(f"bootnode_{i}", malicious_peer_pool, attack_intensity)
        for i in range(num_malicious_bootnodes)
    ]

    # Create fallback peers
    fallback_peers = [f"fallback_peer_{i}" for i in range(num_fallback_peers)]

    # Execute attack scenario
    scenario = BootnodePoisoningScenario(
        honest_peers, malicious_bootnodes, fallback_peers
    )
    results = await scenario.execute_bootnode_poisoning_attack(attack_duration)

    return results
