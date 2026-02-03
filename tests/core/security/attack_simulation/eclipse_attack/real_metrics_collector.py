"""
Real Metrics Collector for Eclipse Attack Analysis

This module collects actual performance metrics from real libp2p networks
during eclipse attacks, measuring genuine network degradation and recovery.
"""

import logging
import time
from typing import Any, cast

import trio

from libp2p.abc import IHost
from libp2p.kad_dht import KadDHT
from libp2p.peer.peerinfo import PeerInfo

from .metrics_collector import AttackMetrics

logger = logging.getLogger(__name__)


class RealAttackMetrics(AttackMetrics):
    """Collects real metrics from actual libp2p network during attacks"""

    def __init__(self):
        super().__init__()
        self.test_keys = []  # Keys used for testing lookups
        self.attack_start_time = 0.0
        self.attack_end_time = 0.0
        self.detailed_results = {}

    async def measure_real_lookup_performance(
        self, dhts: list[KadDHT], num_test_keys: int = 10, lookups_per_key: int = 5
    ) -> dict[str, float]:
        """Measure actual DHT lookup success rates"""
        # Generate test keys for lookups
        self.test_keys = []
        for i in range(num_test_keys):
            # Use string keys as KadDHT expects strings
            key = f"test_key_{i}"
            self.test_keys.append(key)

        # First, populate some values in the DHT
        await self._populate_test_values(dhts[0])  # Use first DHT as source

        # Measure lookup performance
        total_successful = 0
        total_attempts = 0

        for dht in dhts:
            for key in self.test_keys:
                for attempt in range(lookups_per_key):
                    total_attempts += 1
                    try:
                        result = await dht.get_value(key)
                        if result is not None:
                            total_successful += 1
                    except Exception:
                        pass  # Failed lookup

                    await trio.sleep(0.01)  # Small delay between lookups

        success_rate = total_successful / total_attempts if total_attempts > 0 else 0

        results = {
            "success_rate": success_rate,
            "total_successful": total_successful,
            "total_attempts": total_attempts,
            "average_per_dht": success_rate,
        }

        return results

    async def _populate_test_values(self, source_dht: KadDHT):
        """Populate the network with test values"""
        for key in self.test_keys:
            test_value = f"test_value_for_{key}".encode()
            try:
                await source_dht.put_value(key, test_value)
                await trio.sleep(0.01)
            except Exception as e:
                logger.error("Failed to populate key %s: %s", key, e)

    async def measure_network_connectivity(self, hosts: list[IHost]) -> dict[str, Any]:
        """Measure real network connectivity between hosts"""
        total_possible_connections = len(hosts) * (len(hosts) - 1)
        actual_connections = 0
        connectivity_matrix = {}

        for i, host_a in enumerate(hosts):
            connectivity_matrix[i] = {}
            connected_peers = host_a.get_connected_peers()

            for j, host_b in enumerate(hosts):
                if i != j:
                    is_connected = host_b.get_id() in connected_peers
                    connectivity_matrix[i][j] = is_connected
                    if is_connected:
                        actual_connections += 1

        connectivity_ratio = (
            actual_connections / total_possible_connections
            if total_possible_connections > 0
            else 0
        )

        return {
            "connectivity_ratio": connectivity_ratio,
            "actual_connections": actual_connections,
            "possible_connections": total_possible_connections,
            "connectivity_matrix": connectivity_matrix,
        }

    async def measure_routing_table_contamination(
        self, honest_dhts: list[KadDHT], malicious_peer_ids: list[str]
    ) -> dict[str, Any]:
        """Measure how much malicious content is in routing tables"""
        total_contamination = 0
        total_entries = 0
        contamination_per_dht = []

        for dht in honest_dhts:
            routing_table_peers = dht.routing_table.get_peer_ids()
            malicious_count = 0

            for peer_id in routing_table_peers:
                total_entries += 1
                if peer_id.to_string() in malicious_peer_ids:
                    malicious_count += 1
                    total_contamination += 1

            dht_contamination = (
                malicious_count / len(routing_table_peers) if routing_table_peers else 0
            )
            contamination_per_dht.append(dht_contamination)

        overall_contamination = (
            total_contamination / total_entries if total_entries > 0 else 0
        )

        return {
            "overall_contamination_rate": overall_contamination,
            "average_contamination_per_dht": (
                sum(contamination_per_dht) / len(contamination_per_dht)
                if contamination_per_dht
                else 0
            ),
            "contamination_per_dht": contamination_per_dht,
            "total_malicious_entries": total_contamination,
            "total_entries_checked": total_entries,
        }

    async def measure_complete_attack_cycle(
        self,
        honest_hosts: list[IHost],
        honest_dhts: list[KadDHT],
        malicious_peers: list,
        attack_duration: float = 30.0,
    ) -> dict[str, Any]:
        """Measure complete attack cycle: before, during, after"""
        results = {
            "before_attack": {},
            "during_attack": {},
            "after_attack": {},
            "recovery_metrics": {},
        }

        # Phase 1: Baseline measurements
        logger.info("Measuring baseline network performance...")
        results["before_attack"][
            "lookup_performance"
        ] = await self.measure_real_lookup_performance(honest_dhts)
        results["before_attack"][
            "connectivity"
        ] = await self.measure_network_connectivity(honest_hosts)
        results["before_attack"][
            "contamination"
        ] = await self.measure_routing_table_contamination(
            honest_dhts, [mp.peer_id for mp in malicious_peers]
        )

        # Phase 2: Execute attack
        logger.info("Executing Eclipse attack...")
        self.attack_start_time = time.time()

        # Let malicious peers poison the network
        async with trio.open_nursery() as nursery:
            for malicious_peer in malicious_peers:
                for honest_dht in honest_dhts:
                    # Create fake peer info for the malicious peer
                    fake_peer_info = PeerInfo(
                        malicious_peer.host.get_id(), malicious_peer.host.get_addrs()
                    )
                    nursery.start_soon(
                        malicious_peer.poison_real_dht_entries,
                        honest_dht,
                        fake_peer_info,
                    )
                    nursery.start_soon(malicious_peer.flood_real_peer_table, honest_dht)

        # Wait during attack (optimized for faster tests)
        await trio.sleep(
            min(5.0, attack_duration / 6)
        )  # Reduced from full attack_duration

        # Phase 3: Measure during attack
        logger.info("Measuring network performance during attack...")
        results["during_attack"][
            "lookup_performance"
        ] = await self.measure_real_lookup_performance(honest_dhts)
        results["during_attack"][
            "connectivity"
        ] = await self.measure_network_connectivity(honest_hosts)
        results["during_attack"][
            "contamination"
        ] = await self.measure_routing_table_contamination(
            honest_dhts, [mp.peer_id for mp in malicious_peers]
        )

        # Phase 4: Recovery phase (stop attack)
        logger.info("Measuring network recovery...")
        self.attack_end_time = time.time()

        # Allow network to recover (optimized for faster tests)
        recovery_time = 5.0  # Reduced from 60s to 5s
        await trio.sleep(recovery_time)

        # Phase 5: Measure recovery
        results["after_attack"][
            "lookup_performance"
        ] = await self.measure_real_lookup_performance(honest_dhts)
        results["after_attack"][
            "connectivity"
        ] = await self.measure_network_connectivity(honest_hosts)
        results["after_attack"][
            "contamination"
        ] = await self.measure_routing_table_contamination(
            honest_dhts, [mp.peer_id for mp in malicious_peers]
        )

        # Calculate recovery metrics
        results["recovery_metrics"] = cast(
            Any, self._calculate_recovery_metrics(results)
        )

        return results

    def _calculate_recovery_metrics(self, results: dict[str, Any]) -> dict[str, float]:
        """Calculate recovery effectiveness metrics"""
        before_success = results["before_attack"]["lookup_performance"]["success_rate"]
        during_success = results["during_attack"]["lookup_performance"]["success_rate"]
        after_success = results["after_attack"]["lookup_performance"]["success_rate"]

        attack_effectiveness = (
            (before_success - during_success) / before_success
            if before_success > 0
            else 0
        )
        recovery_effectiveness = (
            (after_success - during_success) / (before_success - during_success)
            if (before_success - during_success) > 0
            else 0
        )

        before_connectivity = results["before_attack"]["connectivity"][
            "connectivity_ratio"
        ]
        during_connectivity = results["during_attack"]["connectivity"][
            "connectivity_ratio"
        ]
        after_connectivity = results["after_attack"]["connectivity"][
            "connectivity_ratio"
        ]

        connectivity_impact = (
            (before_connectivity - during_connectivity) / before_connectivity
            if before_connectivity > 0
            else 0
        )
        connectivity_recovery = (
            (after_connectivity - during_connectivity)
            / (before_connectivity - during_connectivity)
            if (before_connectivity - during_connectivity) > 0
            else 0
        )

        return {
            "attack_effectiveness_lookup": attack_effectiveness,
            "recovery_effectiveness_lookup": recovery_effectiveness,
            "attack_effectiveness_connectivity": connectivity_impact,
            "recovery_effectiveness_connectivity": connectivity_recovery,
            "attack_duration": self.attack_end_time - self.attack_start_time,
            "overall_network_resilience": (
                (recovery_effectiveness + connectivity_recovery) / 2
            ),
        }
