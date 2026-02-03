"""
Long-Range Fork Replay Attack Simulation

This module implements a long-range fork attack inspired by Polkadot's security model.
Nodes offline longer than the validator unstaking period can be tricked into following
an outdated fork when they reconnect.

Key Insight: After sufficient time offline, nodes lose context about canonical chain
state and can be fed a plausible but stale alternative history.
"""

import logging
import random
from typing import Any

import trio

logger = logging.getLogger(__name__)


class ChainState:
    """Represents a blockchain state snapshot"""

    def __init__(
        self,
        block_height: int,
        block_hash: str,
        finality_checkpoint: int,
        timestamp: float,
        validator_set: list[str],
    ):
        self.block_height = block_height
        self.block_hash = block_hash
        self.finality_checkpoint = finality_checkpoint
        self.timestamp = timestamp
        self.validator_set = validator_set
        self.is_canonical = True


class ForkAttacker:
    """Malicious peer that replays stale chain forks"""

    def __init__(
        self,
        attacker_id: str,
        stale_fork: ChainState,
        canonical_chain: ChainState,
        intensity: float,
    ):
        self.attacker_id = attacker_id
        self.stale_fork = stale_fork
        self.canonical_chain = canonical_chain
        self.intensity = intensity
        self.replay_attempts: int = 0
        self.successful_replays: list[str] = []
        self.failed_replays: list[str] = []

    async def replay_stale_fork(
        self, target_peer: str, peer_offline_duration: float
    ) -> bool:
        """
        Attempt to replay stale fork to a peer that has been offline.

        Args:
            target_peer: ID of target peer
            peer_offline_duration: How long the peer has been offline (seconds)

        Returns:
            True if replay successful, False otherwise

        """
        self.replay_attempts += 1

        # Simulate network delay (optimized)
        await trio.sleep(random.uniform(0.001, 0.005))  # 10x faster

        # Success probability increases with:
        # 1. Longer offline duration
        # 2. Higher attacker intensity
        # 3. Older finality checkpoint
        offline_factor = min(peer_offline_duration / 3600.0, 1.0)  # 1 hour = max factor
        checkpoint_age = (
            self.canonical_chain.finality_checkpoint
            - self.stale_fork.finality_checkpoint
        )
        checkpoint_factor = min(
            checkpoint_age / 1000.0, 0.5
        )  # Older checkpoints are riskier

        success_probability = (
            self.intensity * (offline_factor + checkpoint_factor) * 0.5
        )

        if random.random() < success_probability:
            self.successful_replays.append(target_peer)
            return True
        else:
            self.failed_replays.append(target_peer)
            return False

    async def execute_fork_replay_campaign(
        self, offline_peers: list[tuple[str, float]], duration: float = 30.0
    ) -> dict[str, Any]:
        """
        Execute a campaign of fork replay attempts against offline peers.

        Args:
            offline_peers: List of (peer_id, offline_duration) tuples
            duration: Campaign duration in seconds

        Returns:
            Campaign results dictionary

        """
        start_time = trio.current_time()

        async with trio.open_nursery() as nursery:
            for peer_id, offline_duration in offline_peers:
                if trio.current_time() - start_time >= duration:
                    break
                nursery.start_soon(self.replay_stale_fork, peer_id, offline_duration)

        return {
            "replay_attempts": self.replay_attempts,
            "successful_replays": len(self.successful_replays),
            "failed_replays": len(self.failed_replays),
            "success_rate": (
                len(self.successful_replays) / self.replay_attempts
                if self.replay_attempts > 0
                else 0
            ),
        }


class LongRangeForkScenario:
    """
    Simulates long-range fork attack where nodes offline for extended periods
    can be tricked into following stale chain views.
    """

    def __init__(
        self,
        online_peers: list[str],
        offline_peers: list[tuple[str, float]],  # (peer_id, offline_duration)
        fork_attackers: list[ForkAttacker],
    ):
        self.online_peers = online_peers
        self.offline_peers = offline_peers
        self.fork_attackers = fork_attackers
        self.attack_results = {}

    async def execute_long_range_fork_attack(
        self, attack_duration: float = 30.0
    ) -> dict[str, Any]:
        """Execute complete long-range fork replay attack scenario"""
        logger.info("Executing Long-Range Fork Replay Attack")
        logger.info("Online peers: %d", len(self.online_peers))
        logger.info("Offline peers: %d", len(self.offline_peers))
        logger.info("Fork attackers: %d", len(self.fork_attackers))
        logger.info("Attack duration: %f seconds", attack_duration)

        # Phase 1: Execute fork replay attacks
        attack_start = trio.current_time()
        campaign_results = []

        async with trio.open_nursery() as nursery:
            for attacker in self.fork_attackers:
                nursery.start_soon(
                    self._run_attacker_campaign,
                    attacker,
                    attack_duration,
                    campaign_results,
                )

        attack_end = trio.current_time()

        # Phase 2: Measure fork detection and recovery
        detection_start = trio.current_time()
        detection_results = await self._measure_fork_detection()
        detection_end = trio.current_time()

        # Phase 3: Measure resync capabilities
        resync_start = trio.current_time()
        resync_results = await self._measure_resync_performance()
        resync_end = trio.current_time()

        # Calculate comprehensive metrics
        total_replay_attempts = sum(r["replay_attempts"] for r in campaign_results)
        total_successful_replays = sum(
            r["successful_replays"] for r in campaign_results
        )
        total_failed_replays = sum(r["failed_replays"] for r in campaign_results)

        overall_success_rate = (
            total_successful_replays / total_replay_attempts
            if total_replay_attempts > 0
            else 0
        )

        # Analyze offline duration impact
        avg_offline_duration = (
            sum(duration for _, duration in self.offline_peers)
            / len(self.offline_peers)
            if self.offline_peers
            else 0
        )

        # Generate detailed results
        self.attack_results = {
            "attack_type": "long_range_fork",
            "network_composition": {
                "online_peers": len(self.online_peers),
                "offline_peers": len(self.offline_peers),
                "fork_attackers": len(self.fork_attackers),
            },
            "fork_replay_metrics": {
                "total_replay_attempts": total_replay_attempts,
                "successful_replays": total_successful_replays,
                "failed_replays": total_failed_replays,
                "overall_success_rate": overall_success_rate,
                "avg_offline_duration": avg_offline_duration,
            },
            "detection_metrics": {
                "fork_detection_rate": detection_results["detection_rate"],
                "detection_latency": detection_end - detection_start,
                "false_acceptance_rate": detection_results["false_acceptance_rate"],
            },
            "resync_metrics": {
                "time_to_resync": resync_end - resync_start,
                "resync_success_rate": resync_results["success_rate"],
                "peers_still_on_stale_fork": resync_results["peers_on_stale_fork"],
            },
            "timing": {
                "attack_duration": attack_end - attack_start,
                "detection_duration": detection_end - detection_start,
                "resync_duration": resync_end - resync_start,
                "total_duration": resync_end - attack_start,
            },
            "security_insights": self._generate_security_insights(
                overall_success_rate, detection_results, resync_results
            ),
            "recommendations": self._generate_fork_recommendations(
                overall_success_rate
            ),
        }

        return self.attack_results

    async def _run_attacker_campaign(
        self, attacker: ForkAttacker, duration: float, results_list: list
    ):
        """Run individual attacker campaign and collect results"""
        results = await attacker.execute_fork_replay_campaign(
            self.offline_peers, duration
        )
        results_list.append(results)

    async def _measure_fork_detection(self) -> dict[str, Any]:
        """Measure fork detection capabilities of the network"""
        # Simulate fork detection by online peers
        await trio.sleep(random.uniform(0.1, 0.3))  # Detection delay

        # Detection rate depends on:
        # 1. Number of online peers (more peers = better detection)
        # 2. How many attackers there are
        # 3. Quality of checkpoint validation

        total_peers = len(self.online_peers) + len(self.offline_peers)
        online_ratio = len(self.online_peers) / total_peers if total_peers > 0 else 0

        # Base detection rate
        base_detection = 0.7

        # Online peers improve detection
        detection_rate = min(base_detection + (online_ratio * 0.25), 0.95)

        # False acceptance rate (accepting stale fork as canonical)
        false_acceptance_rate = max(0.05, (1.0 - detection_rate) * 0.5)

        return {
            "detection_rate": detection_rate,
            "false_acceptance_rate": false_acceptance_rate,
        }

    async def _measure_resync_performance(self) -> dict[str, Any]:
        """Measure how quickly peers can resync to canonical chain"""
        # Simulate resync process
        await trio.sleep(random.uniform(0.2, 0.5))

        # Resync success depends on:
        # 1. Availability of honest peers with canonical chain
        # 2. Network connectivity
        # 3. Checkpoint validation mechanism

        total_peers = len(self.online_peers) + len(self.offline_peers)
        online_ratio = len(self.online_peers) / total_peers if total_peers > 0 else 0

        # Higher online ratio = better resync success
        resync_success_rate = min(0.6 + (online_ratio * 0.35), 0.95)

        # Peers that remain on stale fork
        peers_on_stale_fork = int(len(self.offline_peers) * (1.0 - resync_success_rate))

        return {
            "success_rate": resync_success_rate,
            "peers_on_stale_fork": peers_on_stale_fork,
        }

    def _generate_security_insights(
        self, success_rate: float, detection_results: dict, resync_results: dict
    ) -> list[str]:
        """Generate security insights from attack results"""
        insights = []

        if success_rate > 0.5:
            insights.append(
                f"HIGH RISK: {success_rate * 100:.1f}% of fork replay "
                "attempts succeeded"
            )

        if detection_results["false_acceptance_rate"] > 0.2:
            insights.append(
                f"CONCERN: {detection_results['false_acceptance_rate'] * 100:.1f}% "
                f"false acceptance rate for stale forks"
            )

        if resync_results["peers_on_stale_fork"] > len(self.offline_peers) * 0.2:
            insights.append(
                f"WARNING: {resync_results['peers_on_stale_fork']} peers remained "
                f"on stale fork after resync attempt"
            )

        if detection_results["detection_rate"] < 0.7:
            insights.append("Detection capabilities below recommended threshold (70%)")

        if resync_results["success_rate"] < 0.7:
            insights.append("Resync success rate below recommended threshold (70%)")

        if not insights:
            insights.append(
                "Network shows good resilience against long-range fork attacks"
            )

        return insights

    def _generate_fork_recommendations(self, success_rate: float) -> list[str]:
        """Generate specific mitigation recommendations"""
        recommendations = []

        if success_rate > 0.5:
            recommendations.append(
                "CRITICAL: Implement checkpoint freshness validation"
            )
            recommendations.append(
                "Require recent finality proofs before accepting chain state"
            )

        if success_rate > 0.3:
            recommendations.append("Enable weak subjectivity checkpoints")
            recommendations.append(
                "Implement social consensus fallback for long offline periods"
            )

        recommendations.append(
            "Monitor peer offline duration and apply stricter validation"
        )
        recommendations.append("Maintain trusted peer set for checkpoint validation")
        recommendations.append("Implement fork choice rule with finality awareness")
        recommendations.append("Add peer reputation based on chain state consistency")

        return recommendations


async def run_long_range_fork_simulation(
    num_online_peers: int = 10,
    num_offline_peers: int = 5,
    avg_offline_duration: float = 7200.0,  # 2 hours
    num_fork_attackers: int = 2,
    attack_intensity: float = 0.7,
    attack_duration: float = 30.0,
) -> dict[str, Any]:
    """
    Convenience function to run a complete long-range fork simulation.

    Args:
        num_online_peers: Number of peers that remain online
        num_offline_peers: Number of peers that have been offline
        avg_offline_duration: Average duration peers have been offline (seconds)
        num_fork_attackers: Number of attackers replaying stale forks
        attack_intensity: Attack intensity (0.0 to 1.0)
        attack_duration: Duration of attack in seconds

    Returns:
        Comprehensive attack simulation results

    """
    # Create online peers
    online_peers = [f"online_peer_{i}" for i in range(num_online_peers)]

    # Create offline peers with varying offline durations
    offline_peers = [
        (
            f"offline_peer_{i}",
            avg_offline_duration
            + random.uniform(-avg_offline_duration * 0.3, avg_offline_duration * 0.3),
        )
        for i in range(num_offline_peers)
    ]

    # Create canonical chain state
    canonical_chain = ChainState(
        block_height=10000,
        block_hash="canonical_hash_10000",
        finality_checkpoint=9900,
        timestamp=trio.current_time(),
        validator_set=[f"validator_{i}" for i in range(20)],
    )

    # Create stale fork (older state)
    stale_fork = ChainState(
        block_height=9000,
        block_hash="stale_hash_9000",
        finality_checkpoint=8900,
        timestamp=trio.current_time() - avg_offline_duration,
        validator_set=[f"validator_{i}" for i in range(18)],  # Slightly different
    )
    stale_fork.is_canonical = False

    # Create fork attackers
    fork_attackers = [
        ForkAttacker(
            f"fork_attacker_{i}", stale_fork, canonical_chain, attack_intensity
        )
        for i in range(num_fork_attackers)
    ]

    # Execute attack scenario
    scenario = LongRangeForkScenario(online_peers, offline_peers, fork_attackers)
    results = await scenario.execute_long_range_fork_attack(attack_duration)

    return results
