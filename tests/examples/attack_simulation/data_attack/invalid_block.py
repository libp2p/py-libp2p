"""
Invalid Best Block Propagation Attack (Light Client Model)

This module implements invalid block propagation attacks inspired by Polkadot's light
client security model. Validators may create blocks that are authentic (properly signed)
but invalid (violate state transition rules). Light clients can accept these before
finality.

Key Insight: Authenticity (valid signature) != Integrity (valid state transition).
Light clients must validate both properties, but may temporarily accept invalid blocks
before finality confirmation.
"""

from enum import Enum
import logging
import random
from typing import Any

import trio

logger = logging.getLogger(__name__)


class BlockInvalidityType(Enum):
    """Types of block invalidity"""

    INVALID_STATE_TRANSITION = "invalid_state_transition"
    DOUBLE_SPEND = "double_spend"
    INVALID_MERKLE_ROOT = "invalid_merkle_root"
    CONSENSUS_VIOLATION = "consensus_violation"
    INVALID_TRANSACTION = "invalid_transaction"


class Block:
    """Represents a blockchain block"""

    def __init__(
        self,
        block_number: int,
        block_hash: str,
        parent_hash: str,
        is_authentic: bool,
        is_valid: bool,
        is_finalized: bool = False,
        invalidity_type: BlockInvalidityType | None = None,
    ):
        self.block_number = block_number
        self.block_hash = block_hash
        self.parent_hash = parent_hash
        self.is_authentic = is_authentic  # Has valid signature
        self.is_valid = is_valid  # Has valid state transition
        self.is_finalized = is_finalized
        self.invalidity_type = invalidity_type
        self.propagation_count = 0
        self.acceptance_count = 0


class MaliciousValidator:
    """Validator that creates authentic but invalid blocks"""

    def __init__(self, validator_id: str, intensity: float):
        self.validator_id = validator_id
        self.intensity = intensity
        self.blocks_created: list[Block] = []
        self.propagation_attempts: int = 0
        self.successful_propagations: int = 0

    def create_invalid_block(
        self, block_number: int, parent_hash: str, invalidity_type: BlockInvalidityType
    ) -> Block:
        """Create an authentic but invalid block"""
        block = Block(
            block_number=block_number,
            block_hash=f"invalid_block_{block_number}_{self.validator_id}",
            parent_hash=parent_hash,
            is_authentic=True,  # Has valid signature (from actual validator)
            is_valid=False,  # But violates state transition rules
            is_finalized=False,
            invalidity_type=invalidity_type,
        )
        self.blocks_created.append(block)
        return block

    async def propagate_invalid_block(
        self, block: Block, target_peers: list[str], is_light_client: bool = True
    ) -> dict[str, Any]:
        """
        Propagate invalid block to target peers.

        Light clients are more vulnerable as they may accept before finality.
        Full nodes typically detect invalidity faster.
        """
        self.propagation_attempts += 1

        # Simulate network propagation delay (optimized)
        await trio.sleep(random.uniform(0.001, 0.005))  # 10x faster

        accepted_peers = []
        rejected_peers = []

        for peer in target_peers:
            # Acceptance probability depends on:
            # 1. Light client vs full node (light clients more vulnerable)
            # 2. Attack intensity
            # 3. Block hasn't been finalized yet

            if is_light_client:
                # Light clients check authenticity but may miss invalidity pre-finality
                base_acceptance = 0.6  # Higher for light clients
            else:
                # Full nodes can validate state transitions
                base_acceptance = 0.2  # Lower for full nodes

            acceptance_probability = base_acceptance * self.intensity

            if random.random() < acceptance_probability:
                accepted_peers.append(peer)
                block.acceptance_count += 1
            else:
                rejected_peers.append(peer)

            block.propagation_count += 1

        if accepted_peers:
            self.successful_propagations += 1

        return {
            "accepted_peers": accepted_peers,
            "rejected_peers": rejected_peers,
            "acceptance_rate": (
                len(accepted_peers) / len(target_peers) if target_peers else 0
            ),
        }


class InvalidBlockScenario:
    """
    Simulates invalid block propagation attack targeting light clients.
    Measures pre-finality acceptance, detection latency, and peer isolation.
    """

    def __init__(
        self,
        full_nodes: list[str],
        light_clients: list[str],
        malicious_validators: list[MaliciousValidator],
    ):
        self.full_nodes = full_nodes
        self.light_clients = light_clients
        self.malicious_validators = malicious_validators
        self.attack_results = {}

    async def execute_invalid_block_attack(
        self, attack_duration: float = 30.0, finality_delay: float = 10.0
    ) -> dict[str, Any]:
        """
        Execute complete invalid block propagation attack scenario.

        Args:
            attack_duration: Duration of attack in seconds
            finality_delay: Time until finality is reached (when invalidity is detected)

        """
        logger.info("Executing Invalid Block Propagation Attack")
        logger.info("Full nodes: %d", len(self.full_nodes))
        logger.info("Light clients: %d", len(self.light_clients))
        logger.info("Malicious validators: %d", len(self.malicious_validators))
        logger.info(
            "Attack duration: %fs, Finality delay: %fs",
            attack_duration,
            finality_delay,
        )

        # Phase 1: Create and propagate invalid blocks (pre-finality)
        attack_start = trio.current_time()
        pre_finality_results = await self._propagate_invalid_blocks_pre_finality(
            min(attack_duration, finality_delay)
        )
        pre_finality_end = trio.current_time()

        # Phase 2: Finality reached - detect invalid blocks
        finality_start = trio.current_time()
        detection_results = await self._detect_invalid_blocks_post_finality()
        finality_end = trio.current_time()

        # Phase 3: Peer isolation and recovery
        isolation_start = trio.current_time()
        isolation_results = await self._isolate_malicious_peers()
        isolation_end = trio.current_time()

        # Calculate comprehensive metrics
        all_blocks = []
        for validator in self.malicious_validators:
            all_blocks.extend(validator.blocks_created)

        total_blocks = len(all_blocks)
        total_propagations = sum(b.propagation_count for b in all_blocks)
        total_acceptances = sum(b.acceptance_count for b in all_blocks)

        # Light client specific metrics
        light_client_acceptance_rate = pre_finality_results[
            "light_client_acceptance_rate"
        ]
        full_node_acceptance_rate = pre_finality_results["full_node_acceptance_rate"]

        # Generate detailed results
        self.attack_results = {
            "attack_type": "invalid_block_propagation",
            "network_composition": {
                "full_nodes": len(self.full_nodes),
                "light_clients": len(self.light_clients),
                "malicious_validators": len(self.malicious_validators),
            },
            "block_propagation_metrics": {
                "total_invalid_blocks": total_blocks,
                "total_propagation_attempts": total_propagations,
                "total_acceptances": total_acceptances,
                "overall_acceptance_rate": (
                    total_acceptances / total_propagations
                    if total_propagations > 0
                    else 0
                ),
            },
            "pre_finality_metrics": {
                "light_client_acceptance_rate": light_client_acceptance_rate,
                "full_node_acceptance_rate": full_node_acceptance_rate,
                "vulnerability_gap": (
                    light_client_acceptance_rate - full_node_acceptance_rate
                ),
                "blocks_accepted_pre_finality": pre_finality_results[
                    "blocks_accepted_pre_finality"
                ],
            },
            "detection_metrics": {
                "detection_latency": finality_end - finality_start,
                "post_finality_detection_rate": detection_results["detection_rate"],
                "false_negatives": detection_results["false_negatives"],
            },
            "isolation_metrics": {
                "malicious_peers_isolated": isolation_results["peers_isolated"],
                "isolation_success_rate": isolation_results["isolation_rate"],
                "time_to_isolation": isolation_end - isolation_start,
            },
            "timing": {
                "pre_finality_duration": pre_finality_end - attack_start,
                "finality_detection_duration": finality_end - finality_start,
                "isolation_duration": isolation_end - isolation_start,
                "total_duration": isolation_end - attack_start,
            },
            "security_analysis": self._generate_security_analysis(
                light_client_acceptance_rate, detection_results
            ),
            "recommendations": self._generate_invalid_block_recommendations(
                light_client_acceptance_rate, full_node_acceptance_rate
            ),
        }

        return self.attack_results

    async def _propagate_invalid_blocks_pre_finality(
        self, duration: float
    ) -> dict[str, Any]:
        """Propagate invalid blocks before finality is reached"""
        trio.current_time()

        light_client_acceptances = []
        full_node_acceptances = []
        blocks_accepted = 0

        async with trio.open_nursery() as nursery:
            for validator in self.malicious_validators:
                nursery.start_soon(
                    self._validator_propagation_campaign,
                    validator,
                    duration,
                    light_client_acceptances,
                    full_node_acceptances,
                )

        blocks_accepted = sum(len(lc) for lc in light_client_acceptances) + sum(
            len(fn) for fn in full_node_acceptances
        )

        # Calculate acceptance rates
        light_client_acceptance_rate = (
            sum(len(lc) for lc in light_client_acceptances)
            / (len(self.light_clients) * len(self.malicious_validators))
            if self.light_clients and self.malicious_validators
            else 0
        )

        full_node_acceptance_rate = (
            sum(len(fn) for fn in full_node_acceptances)
            / (len(self.full_nodes) * len(self.malicious_validators))
            if self.full_nodes and self.malicious_validators
            else 0
        )

        return {
            "light_client_acceptance_rate": light_client_acceptance_rate,
            "full_node_acceptance_rate": full_node_acceptance_rate,
            "blocks_accepted_pre_finality": blocks_accepted,
        }

    async def _validator_propagation_campaign(
        self,
        validator: MaliciousValidator,
        duration: float,
        light_client_results: list,
        full_node_results: list,
    ):
        """Individual validator's block propagation campaign"""
        start_time = trio.current_time()
        block_num = 1000

        while trio.current_time() - start_time < duration:
            # Create invalid block
            invalidity_type = random.choice(
                [
                    BlockInvalidityType.INVALID_STATE_TRANSITION,
                    BlockInvalidityType.DOUBLE_SPEND,
                    BlockInvalidityType.INVALID_MERKLE_ROOT,
                    BlockInvalidityType.CONSENSUS_VIOLATION,
                    BlockInvalidityType.INVALID_TRANSACTION,
                ]
            )
            block = validator.create_invalid_block(
                block_num, f"parent_{block_num - 1}", invalidity_type
            )
            block_num += 1

            # Propagate to light clients
            if self.light_clients:
                lc_result = await validator.propagate_invalid_block(
                    block, self.light_clients, is_light_client=True
                )
                light_client_results.append(lc_result["accepted_peers"])

            # Propagate to full nodes
            if self.full_nodes:
                fn_result = await validator.propagate_invalid_block(
                    block, self.full_nodes, is_light_client=False
                )
                full_node_results.append(fn_result["accepted_peers"])

            await trio.sleep(random.uniform(0.1, 0.3))  # Block creation interval

    async def _detect_invalid_blocks_post_finality(self) -> dict[str, Any]:
        """Simulate detection of invalid blocks after finality is reached"""
        # After finality, invalidity becomes obvious
        await trio.sleep(random.uniform(0.1, 0.3))  # Detection processing time

        all_blocks = []
        for validator in self.malicious_validators:
            all_blocks.extend(validator.blocks_created)

        # Post-finality detection rate should be very high
        base_detection_rate = 0.95

        # Some false negatives possible in distributed systems
        detected_blocks = int(len(all_blocks) * base_detection_rate)
        false_negatives = len(all_blocks) - detected_blocks

        return {
            "detection_rate": base_detection_rate,
            "false_negatives": false_negatives,
            "detected_blocks": detected_blocks,
        }

    async def _isolate_malicious_peers(self) -> dict[str, Any]:
        """Simulate isolation of malicious validators after detection"""
        await trio.sleep(random.uniform(0.05, 0.15))  # Isolation processing time

        # High isolation success rate after detection
        isolation_rate = 0.9
        peers_isolated = int(len(self.malicious_validators) * isolation_rate)

        return {
            "peers_isolated": peers_isolated,
            "isolation_rate": isolation_rate,
        }

    def _generate_security_analysis(
        self, light_client_acceptance: float, detection_results: dict
    ) -> list[str]:
        """Generate security analysis insights"""
        analysis = []

        if light_client_acceptance > 0.5:
            analysis.append(
                f"CRITICAL: {light_client_acceptance * 100:.1f}% of light clients "
                f"accepted invalid blocks pre-finality"
            )

        if light_client_acceptance > 0.3:
            analysis.append(
                "Light clients vulnerable to authentic-but-invalid block attacks"
            )

        if detection_results["false_negatives"] > 0:
            analysis.append(
                f"WARNING: {detection_results['false_negatives']} invalid blocks "
                f"not detected post-finality"
            )

        if detection_results["detection_rate"] < 0.9:
            analysis.append("Detection rate below recommended threshold (90%)")

        if not analysis:
            analysis.append(
                "Network shows good resilience against invalid block propagation"
            )

        return analysis

    def _generate_invalid_block_recommendations(
        self, light_client_acceptance: float, full_node_acceptance: float
    ) -> list[str]:
        """Generate specific mitigation recommendations"""
        recommendations = []

        if light_client_acceptance > 0.5:
            recommendations.append(
                "CRITICAL: Implement mandatory finality wait for light clients"
            )
            recommendations.append(
                "Require multiple independent validator confirmations"
            )

        if light_client_acceptance > 0.3:
            recommendations.append(
                "Enable state transition validation in light client mode"
            )
            recommendations.append("Implement fraud proof mechanism for light clients")

        recommendations.append("Validate both authenticity AND integrity of blocks")
        recommendations.append("Add reputation system for validators")
        recommendations.append(
            "Implement automatic peer isolation on invalid block detection"
        )
        recommendations.append("Monitor finality lag and adjust trust assumptions")

        if light_client_acceptance - full_node_acceptance > 0.3:
            recommendations.append(
                "Bridge light clients with trusted full nodes for validation"
            )

        return recommendations


async def run_invalid_block_simulation(
    num_full_nodes: int = 10,
    num_light_clients: int = 15,
    num_malicious_validators: int = 2,
    attack_intensity: float = 0.7,
    attack_duration: float = 20.0,
    finality_delay: float = 10.0,
) -> dict[str, Any]:
    """
    Convenience function to run a complete invalid block propagation simulation.

    Args:
        num_full_nodes: Number of full nodes
        num_light_clients: Number of light clients (more vulnerable)
        num_malicious_validators: Number of malicious validators
        attack_intensity: Attack intensity (0.0 to 1.0)
        attack_duration: Duration of attack in seconds
        finality_delay: Time until finality is reached

    Returns:
        Comprehensive attack simulation results

    """
    # Create nodes
    full_nodes = [f"full_node_{i}" for i in range(num_full_nodes)]
    light_clients = [f"light_client_{i}" for i in range(num_light_clients)]

    # Create malicious validators
    malicious_validators = [
        MaliciousValidator(f"validator_{i}", attack_intensity)
        for i in range(num_malicious_validators)
    ]

    # Execute attack scenario
    scenario = InvalidBlockScenario(full_nodes, light_clients, malicious_validators)
    results = await scenario.execute_invalid_block_attack(
        attack_duration, finality_delay
    )

    return results
