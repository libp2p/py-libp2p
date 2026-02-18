"""
Finality Stall Simulation Attack

This module implements finality stall attacks inspired by Polkadot's finality model.
When finality halts while block production continues, light clients can exhaust memory
tracking non-finalized blocks.

Key Insight: Light clients must track all non-finalized blocks. If finality stalls
for extended periods while block production continues, memory usage grows unbounded
unless proper pruning and timeout mechanisms are in place.
"""

import logging
import random
from typing import Any

import trio

logger = logging.getLogger(__name__)


class MemoryTracker:
    """Tracks memory usage for non-finalized blocks"""

    def __init__(self, initial_memory_mb: float = 50.0):
        self.memory_usage_mb = initial_memory_mb
        self.peak_memory_mb = initial_memory_mb
        self.block_memory_cost_mb = 0.5  # MB per block
        self.memory_samples: list[float] = [initial_memory_mb]

    def add_block(self, block_count: int = 1):
        """Add memory for tracking new blocks"""
        self.memory_usage_mb += self.block_memory_cost_mb * block_count
        self.peak_memory_mb = max(self.peak_memory_mb, self.memory_usage_mb)
        self.memory_samples.append(self.memory_usage_mb)

    def prune_blocks(self, block_count: int):
        """Prune old blocks to free memory"""
        freed_memory = self.block_memory_cost_mb * block_count
        self.memory_usage_mb = max(self.memory_usage_mb - freed_memory, 0)
        self.memory_samples.append(self.memory_usage_mb)

    def get_memory_growth_rate(self) -> float:
        """Calculate memory growth rate (MB per sample)"""
        if len(self.memory_samples) < 2:
            return 0.0
        return (self.memory_samples[-1] - self.memory_samples[0]) / len(
            self.memory_samples
        )


class LightClientNode:
    """Light client that tracks non-finalized blocks"""

    def __init__(
        self,
        node_id: str,
        memory_limit_mb: float = 500.0,
        pruning_enabled: bool = True,
        pruning_threshold: int = 1000,
    ):
        self.node_id = node_id
        self.memory_tracker = MemoryTracker()
        self.memory_limit_mb = memory_limit_mb
        self.pruning_enabled = pruning_enabled
        self.pruning_threshold = pruning_threshold

        self.non_finalized_blocks: list[int] = []
        self.last_finalized_block: int = 0
        self.is_exhausted = False
        self.timeout_triggered = False

    async def receive_new_block(self, block_number: int):
        """Receive and track a new non-finalized block"""
        self.non_finalized_blocks.append(block_number)
        self.memory_tracker.add_block()

        # Check memory exhaustion
        if self.memory_tracker.memory_usage_mb >= self.memory_limit_mb:
            self.is_exhausted = True

        # Attempt pruning if enabled
        if (
            self.pruning_enabled
            and len(self.non_finalized_blocks) > self.pruning_threshold
        ):
            await self._prune_old_blocks()

    async def _prune_old_blocks(self):
        """Prune oldest non-finalized blocks"""
        # Prune oldest 20% of blocks
        prune_count = max(1, len(self.non_finalized_blocks) // 5)
        self.non_finalized_blocks = self.non_finalized_blocks[prune_count:]
        self.memory_tracker.prune_blocks(prune_count)

    async def finalize_block(self, block_number: int):
        """Finalize a block and free memory for all blocks up to it"""
        self.last_finalized_block = block_number

        # Free memory for finalized blocks
        finalized_count = sum(1 for b in self.non_finalized_blocks if b <= block_number)
        self.non_finalized_blocks = [
            b for b in self.non_finalized_blocks if b > block_number
        ]
        self.memory_tracker.prune_blocks(finalized_count)

        # Reset exhaustion if memory drops below limit
        if self.memory_tracker.memory_usage_mb < self.memory_limit_mb:
            self.is_exhausted = False

    def trigger_timeout(self):
        """Trigger finality stall timeout detection"""
        self.timeout_triggered = True


class FinalityStallAttacker:
    """
    Attacker that causes or exploits finality stalls.
    This could be a malicious validator set or network partition.
    """

    def __init__(self, attacker_id: str, intensity: float):
        self.attacker_id = attacker_id
        self.intensity = intensity
        self.stall_duration: float = 0.0
        self.blocks_produced_during_stall: int = 0

    async def cause_finality_stall(
        self, duration: float, block_production_rate: float = 1.0
    ) -> dict[str, Any]:
        """
        Cause finality to stall for specified duration.

        Args:
            duration: How long finality is stalled (seconds)
            block_production_rate: Blocks produced per second during stall

        Returns:
            Stall attack results

        """
        self.stall_duration = duration
        start_time = trio.current_time()

        # Simulate block production during stall
        while trio.current_time() - start_time < duration:
            blocks_this_interval = int(block_production_rate * self.intensity)
            self.blocks_produced_during_stall += blocks_this_interval
            await trio.sleep(0.1)  # Optimized intervals for faster tests

        return {
            "stall_duration": self.stall_duration,
            "blocks_produced": self.blocks_produced_during_stall,
            "avg_block_rate": (
                self.blocks_produced_during_stall / duration if duration > 0 else 0
            ),
        }


class FinalityStallScenario:
    """
    Simulates finality stall attack measuring memory exhaustion,
    timeout detection, and recovery mechanisms.
    """

    def __init__(
        self,
        light_clients: list[LightClientNode],
        full_nodes: list[str],
        attackers: list[FinalityStallAttacker],
    ):
        self.light_clients = light_clients
        self.full_nodes = full_nodes
        self.attackers = attackers
        self.attack_results = {}

    async def execute_finality_stall_attack(
        self,
        stall_duration: float = 30.0,
        block_production_rate: float = 2.0,
        finality_timeout: float = 15.0,
    ) -> dict[str, Any]:
        """
        Execute complete finality stall attack scenario.

        Args:
            stall_duration: Duration finality is stalled (seconds)
            block_production_rate: Blocks produced per second
            finality_timeout: Time before timeout detection triggers

        Returns:
            Comprehensive attack simulation results

        """
        logger.info("Executing Finality Stall Attack")
        logger.info("Light clients: %d", len(self.light_clients))
        logger.info("Full nodes: %d", len(self.full_nodes))
        logger.info("Attackers: %d", len(self.attackers))
        logger.info(
            "Stall duration: %fs, Block rate: %f/s",
            stall_duration,
            block_production_rate,
        )

        # Phase 1: Cause finality stall and produce blocks
        stall_start = trio.current_time()
        await self._execute_stall_with_block_production(
            stall_duration, block_production_rate, finality_timeout
        )
        stall_end = trio.current_time()

        # Phase 2: Measure memory exhaustion
        trio.current_time()
        memory_metrics = self._measure_memory_exhaustion()
        trio.current_time()

        # Phase 3: Detect finality stall via timeout
        detection_start = trio.current_time()
        await self._detect_finality_stall(finality_timeout)
        detection_end = trio.current_time()

        # Phase 4: Resume finality and measure recovery
        recovery_start = trio.current_time()
        recovery_metrics = await self._resume_finality_and_recover()
        recovery_end = trio.current_time()

        # Calculate comprehensive metrics
        total_blocks_produced = sum(
            a.blocks_produced_during_stall for a in self.attackers
        )
        exhausted_clients = sum(1 for lc in self.light_clients if lc.is_exhausted)
        timeout_detected_clients = sum(
            1 for lc in self.light_clients if lc.timeout_triggered
        )

        # Generate detailed results
        self.attack_results = {
            "attack_type": "finality_stall",
            "network_composition": {
                "light_clients": len(self.light_clients),
                "full_nodes": len(self.full_nodes),
                "attackers": len(self.attackers),
            },
            "stall_metrics": {
                "stall_duration": stall_end - stall_start,
                "total_blocks_produced": total_blocks_produced,
                "avg_block_production_rate": total_blocks_produced
                / (stall_end - stall_start)
                if (stall_end - stall_start) > 0
                else 0,
            },
            "memory_metrics": {
                "clients_exhausted": exhausted_clients,
                "exhaustion_rate": exhausted_clients / len(self.light_clients)
                if self.light_clients
                else 0,
                "peak_memory_usage_mb": memory_metrics["peak_memory"],
                "avg_memory_usage_mb": memory_metrics["avg_memory"],
                "memory_growth_rate": memory_metrics["growth_rate"],
                "memory_samples": memory_metrics["samples"],
            },
            "detection_metrics": {
                "timeout_detection_rate": (
                    timeout_detected_clients / len(self.light_clients)
                )
                if self.light_clients
                else 0,
                "detection_latency": detection_end - detection_start,
                "clients_detected_stall": timeout_detected_clients,
            },
            "recovery_metrics": {
                "recovery_success_rate": recovery_metrics["recovery_rate"],
                "recovery_time": recovery_end - recovery_start,
                "clients_recovered": recovery_metrics["recovered_clients"],
                "memory_freed_mb": recovery_metrics["memory_freed"],
            },
            "timing": {
                "stall_phase": stall_end - stall_start,
                "detection_phase": detection_end - detection_start,
                "recovery_phase": recovery_end - recovery_start,
                "total_duration": recovery_end - stall_start,
            },
            "security_insights": self._generate_stall_security_insights(
                exhausted_clients, timeout_detected_clients, recovery_metrics
            ),
            "recommendations": self._generate_stall_recommendations(
                exhausted_clients, memory_metrics
            ),
        }

        return self.attack_results

    async def _execute_stall_with_block_production(
        self, stall_duration: float, block_rate: float, finality_timeout: float
    ) -> dict[str, Any]:
        """Execute finality stall while producing blocks"""
        current_block = 1000

        async with trio.open_nursery() as nursery:
            # Start attacker stall campaigns
            for attacker in self.attackers:
                nursery.start_soon(
                    attacker.cause_finality_stall, stall_duration, block_rate
                )

            # Produce blocks and send to light clients
            nursery.start_soon(
                self._produce_blocks_during_stall,
                stall_duration,
                block_rate,
                current_block,
                finality_timeout,
            )

        return {"status": "completed"}

    async def _produce_blocks_during_stall(
        self,
        duration: float,
        block_rate: float,
        starting_block: int,
        timeout_threshold: float,
    ):
        """Produce blocks continuously while finality is stalled"""
        start_time = trio.current_time()
        current_block = starting_block
        time_since_finality = 0.0

        while trio.current_time() - start_time < duration:
            # Produce blocks
            for _ in range(int(block_rate)):
                current_block += 1

                # Send to all light clients
                for lc in self.light_clients:
                    await lc.receive_new_block(current_block)

            time_since_finality += 1.0

            # Trigger timeout detection if threshold exceeded
            if time_since_finality >= timeout_threshold:
                for lc in self.light_clients:
                    if not lc.timeout_triggered:
                        lc.trigger_timeout()

            await trio.sleep(0.1)  # Optimized intervals for faster tests

    def _measure_memory_exhaustion(self) -> dict[str, Any]:
        """Measure memory exhaustion across light clients"""
        if not self.light_clients:
            return {"peak_memory": 0, "avg_memory": 0, "growth_rate": 0, "samples": []}

        peak_memory = max(lc.memory_tracker.peak_memory_mb for lc in self.light_clients)
        avg_memory = sum(
            lc.memory_tracker.memory_usage_mb for lc in self.light_clients
        ) / len(self.light_clients)
        avg_growth_rate = sum(
            lc.memory_tracker.get_memory_growth_rate() for lc in self.light_clients
        ) / len(self.light_clients)

        # Collect sample data from first client for visualization
        sample_client = self.light_clients[0]
        memory_samples = sample_client.memory_tracker.memory_samples

        return {
            "peak_memory": peak_memory,
            "avg_memory": avg_memory,
            "growth_rate": avg_growth_rate,
            "samples": memory_samples,
        }

    async def _detect_finality_stall(self, timeout_threshold: float) -> dict[str, Any]:
        """Measure finality stall detection capabilities"""
        await trio.sleep(random.uniform(0.05, 0.15))  # Detection processing time

        # Count clients that detected the stall
        detected = sum(1 for lc in self.light_clients if lc.timeout_triggered)

        return {
            "detected_count": detected,
            "detection_rate": (
                detected / len(self.light_clients) if self.light_clients else 0
            ),
        }

    async def _resume_finality_and_recover(self) -> dict[str, Any]:
        """Resume finality and measure recovery"""
        # Simulate finality resuming - finalize all pending blocks
        max_block = 0
        for lc in self.light_clients:
            if lc.non_finalized_blocks:
                max_block = max(max_block, max(lc.non_finalized_blocks))

        initial_memory = sum(
            lc.memory_tracker.memory_usage_mb for lc in self.light_clients
        )

        # Finalize all blocks
        for lc in self.light_clients:
            await lc.finalize_block(max_block)

        final_memory = sum(
            lc.memory_tracker.memory_usage_mb for lc in self.light_clients
        )
        memory_freed = initial_memory - final_memory

        # Count recovered clients (no longer exhausted)
        recovered = sum(1 for lc in self.light_clients if not lc.is_exhausted)

        return {
            "recovered_clients": recovered,
            "recovery_rate": (
                recovered / len(self.light_clients) if self.light_clients else 0
            ),
            "memory_freed": memory_freed,
        }

    def _generate_stall_security_insights(
        self, exhausted_clients: int, timeout_detected: int, recovery_metrics: dict
    ) -> list[str]:
        """Generate security insights from finality stall attack"""
        insights = []

        exhaustion_rate = (
            exhausted_clients / len(self.light_clients) if self.light_clients else 0
        )

        if exhaustion_rate > 0.5:
            insights.append(
                f"CRITICAL: {exhaustion_rate * 100:.1f}% of light clients "
                f"exhausted memory"
            )

        if exhaustion_rate > 0.3:
            insights.append(
                "Light clients vulnerable to memory exhaustion during finality stalls"
            )

        timeout_rate = (
            timeout_detected / len(self.light_clients) if self.light_clients else 0
        )
        if timeout_rate < 0.7:
            insights.append(
                f"WARNING: Only {timeout_rate * 100:.1f}% of clients detected "
                f"stall via timeout"
            )

        if recovery_metrics["recovery_rate"] < 0.8:
            insights.append(
                f"CONCERN: Recovery rate only "
                f"{recovery_metrics['recovery_rate'] * 100:.1f}%"
            )

        if not insights:
            insights.append("Network shows good resilience to finality stall attacks")

        return insights

    def _generate_stall_recommendations(
        self, exhausted_clients: int, memory_metrics: dict
    ) -> list[str]:
        """Generate mitigation recommendations for finality stall attacks"""
        recommendations = []

        exhaustion_rate = (
            exhausted_clients / len(self.light_clients) if self.light_clients else 0
        )

        if exhaustion_rate > 0.5:
            recommendations.append(
                "CRITICAL: Implement aggressive block pruning for light clients"
            )
            recommendations.append("Set maximum non-finalized block tracking limit")

        if exhaustion_rate > 0.3:
            recommendations.append(
                "Enable finality stall detection via timeout mechanism"
            )
            recommendations.append(
                "Implement auto-pruning when memory threshold reached"
            )

        if memory_metrics["growth_rate"] > 1.0:
            recommendations.append(
                "Memory growth rate exceeds safe threshold - tune pruning parameters"
            )

        recommendations.append("Monitor finality lag and trigger alerts on stalls")
        recommendations.append(
            "Implement exponential backoff for block acceptance during stalls"
        )
        recommendations.append("Add memory usage monitoring and automatic cleanup")
        recommendations.append("Consider checkpoint-based recovery for extended stalls")

        return recommendations


async def run_finality_stall_simulation(
    num_light_clients: int = 10,
    num_full_nodes: int = 5,
    num_attackers: int = 1,
    attack_intensity: float = 0.8,
    stall_duration: float = 20.0,
    block_production_rate: float = 2.0,
    finality_timeout: float = 10.0,
    memory_limit_mb: float = 300.0,
    pruning_enabled: bool = True,
) -> dict[str, Any]:
    """
    Convenience function to run a complete finality stall simulation.

    Args:
        num_light_clients: Number of light clients
        num_full_nodes: Number of full nodes
        num_attackers: Number of attackers causing stall
        attack_intensity: Attack intensity (0.0 to 1.0)
        stall_duration: Duration finality is stalled (seconds)
        block_production_rate: Blocks produced per second
        finality_timeout: Timeout before stall detection (seconds)
        memory_limit_mb: Memory limit for light clients
        pruning_enabled: Whether automatic pruning is enabled

    Returns:
        Comprehensive attack simulation results

    """
    # Create light clients
    light_clients = [
        LightClientNode(
            f"light_client_{i}",
            memory_limit_mb=memory_limit_mb,
            pruning_enabled=pruning_enabled,
            pruning_threshold=int(block_production_rate * finality_timeout * 0.8),
        )
        for i in range(num_light_clients)
    ]

    # Create full nodes
    full_nodes = [f"full_node_{i}" for i in range(num_full_nodes)]

    # Create attackers
    attackers = [
        FinalityStallAttacker(f"attacker_{i}", attack_intensity)
        for i in range(num_attackers)
    ]

    # Execute attack scenario
    scenario = FinalityStallScenario(light_clients, full_nodes, attackers)
    results = await scenario.execute_finality_stall_attack(
        stall_duration, block_production_rate, finality_timeout
    )

    return results
