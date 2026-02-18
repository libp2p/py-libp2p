#!/usr/bin/env python3
"""
Trio Test Runner

This script runs the attack simulation tests using trio.run() to properly
handle the async context required by trio.sleep() and trio.current_time().
"""

import logging
import os
import sys

import trio

# Add the project root to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../"))

# Import test modules
from .data_attack.invalid_block import BlockInvalidityType, MaliciousValidator
from .eclipse_attack.bootnode_poisoning import (
    BootnodeAttacker,
    BootnodePoisoningScenario,
)
from .finality_attack.stall_simulation import (
    FinalityStallAttacker,
    FinalityStallScenario,
    LightClientNode,
)
from .fork_attack.long_range_fork import ChainState, ForkAttacker, LongRangeForkScenario

logger = logging.getLogger(__name__)


async def test_invalid_block_basic():
    """Test basic invalid block functionality"""
    logger.debug("Testing Invalid Block Basic Functionality")

    # Test block creation
    validator = MaliciousValidator("validator_0", 0.8)
    block = validator.create_invalid_block(
        1000, "parent_999", BlockInvalidityType.INVALID_STATE_TRANSITION
    )

    assert block.block_number == 1000
    assert block.parent_hash == "parent_999"
    assert block.invalidity_type == BlockInvalidityType.INVALID_STATE_TRANSITION

    # Test propagation to light clients
    light_clients = ["lc1", "lc2", "lc3", "lc4", "lc5"]
    result = await validator.propagate_invalid_block(
        block, light_clients, is_light_client=True
    )

    assert "acceptance_rate" in result
    assert "propagation_time" in result

    # Test propagation to full nodes
    full_nodes = ["fn1", "fn2", "fn3", "fn4", "fn5"]
    result = await validator.propagate_invalid_block(
        block, full_nodes, is_light_client=False
    )

    assert "acceptance_rate" in result
    assert "propagation_time" in result
    logger.debug(
        "[PASSED] Full node propagation (acceptance: %.1f%%)",
        result["acceptance_rate"] * 100,
    )
    return True


async def test_bootnode_poisoning_basic():
    """Test basic bootnode poisoning functionality"""
    logger.debug("Testing Bootnode Poisoning Basic Functionality")

    # Test bootnode attacker creation
    malicious_pool = [f"malicious_peer_{i}" for i in range(5)]
    attacker = BootnodeAttacker("bootnode_0", malicious_pool, 0.9)

    assert attacker.bootnode_id == "bootnode_0"
    assert len(attacker.malicious_peer_pool) == 5
    assert attacker.intensity == 0.9

    # Test bootnode poisoning scenario
    honest_peers = [f"honest_peer_{i}" for i in range(10)]
    malicious_bootnodes = [attacker]
    fallback_peers = [f"fallback_peer_{i}" for i in range(3)]

    scenario = BootnodePoisoningScenario(
        honest_peers, malicious_bootnodes, fallback_peers
    )

    results = await scenario.execute_bootnode_poisoning_attack(attack_duration=1.0)

    assert "attack_type" in results
    assert "isolation_metrics" in results
    assert "recovery_metrics" in results
    logger.debug(
        "[PASSED] Bootnode poisoning scenario\n"
        "  - Isolation rate: %.1f%%\n"
        "  - Recovery rate: %.1f%%",
        results["isolation_metrics"]["isolation_rate"] * 100,
        results["recovery_metrics"]["recovery_rate"] * 100,
    )
    return True


async def test_finality_stall_basic():
    """Test basic finality stall functionality"""
    logger.debug("\nTesting Finality Stall Basic Functionality")

    # Test light client node creation
    lc = LightClientNode("lc_0", memory_limit_mb=200.0)
    assert lc.node_id == "lc_0"
    assert lc.memory_limit_mb == 200.0

    # Test finality stall attacker
    attacker = FinalityStallAttacker("attacker_0", 0.8)
    assert attacker.attacker_id == "attacker_0"
    assert attacker.intensity == 0.8

    # Test finality stall scenario
    light_clients = [
        LightClientNode(f"lc_{i}", memory_limit_mb=200.0) for i in range(3)
    ]
    full_nodes = ["fn1", "fn2"]
    attackers = [attacker]

    scenario = FinalityStallScenario(light_clients, full_nodes, attackers)

    results = await scenario.execute_finality_stall_attack(
        stall_duration=1.0, block_production_rate=1.0, finality_timeout=0.5
    )

    assert "attack_type" in results
    assert "memory_metrics" in results
    assert "detection_metrics" in results

    logger.debug(
        "[PASSED] Finality stall scenario\n"
        "  - Memory exhaustion: %.1f%%\n"
        "  - Timeout detection: %.1f%%",
        results["memory_metrics"]["exhaustion_rate"] * 100,
        results["detection_metrics"]["timeout_detection_rate"],
    )
    return True


async def test_long_range_fork_basic():
    """Test basic long-range fork functionality"""
    logger.debug("Testing Long-Range Fork Basic Functionality")

    # Test chain state creation
    canonical_chain = ChainState(
        block_height=1000,
        block_hash="canonical_1000",
        finality_checkpoint=900,
        timestamp=1000.0,
        validator_set=["v1", "v2"],
    )
    stale_fork = ChainState(
        block_height=800,
        block_hash="stale_800",
        finality_checkpoint=700,
        timestamp=800.0,
        validator_set=["v1", "v2"],
    )

    assert canonical_chain.block_height == 1000
    assert stale_fork.block_height == 800

    # Test fork attacker
    attacker = ForkAttacker("fork_attacker_0", stale_fork, canonical_chain, 0.7)
    assert attacker.attacker_id == "fork_attacker_0"
    assert attacker.intensity == 0.7

    # Test long-range fork scenario
    online_peers = [f"online_peer_{i}" for i in range(10)]
    offline_peers = [(f"offline_peer_{i}", 100.0) for i in range(5)]
    fork_attackers = [attacker]

    scenario = LongRangeForkScenario(online_peers, offline_peers, fork_attackers)

    results = await scenario.execute_long_range_fork_attack(attack_duration=1.0)

    assert "attack_type" in results
    assert "fork_metrics" in results
    assert "detection_metrics" in results

    logger.debug(
        "[PASSED] Long-range fork scenario\n"
        "   - Fork replay success: %.1f%%\n"
        "   - Detection rate: %.1f%%",
        results["fork_metrics"]["replay_success_rate"] * 100,
        results["detection_metrics"]["detection_rate"] * 100,
    )
    return True


async def run_all_tests():
    """Run all attack simulation tests"""
    logger.info("ATTACK SIMULATION TEST SUITE")

    test_results = {}
    tests = [
        ("invalid_block", test_invalid_block_basic),
        ("bootnode_poisoning", test_bootnode_poisoning_basic),
        ("finality_stall", test_finality_stall_basic),
        ("long_range_fork", test_long_range_fork_basic),
    ]

    for name, test_func in tests:
        try:
            test_results[name] = await test_func()
            logger.info("%s [PASSED]", name.replace("_", " ").title())
        except Exception as e:
            logger.error(
                "%s [FAILED] %s",
                name.replace("_", " ").title(),
                e,
                exc_info=True,
            )
            test_results[name] = False

    # Summary
    passed_tests = sum(1 for result in test_results.values() if result)
    total_tests = len(test_results)

    logger.info("TEST SUMMARY")
    logger.info("Passed: %d / %d", passed_tests, total_tests)

    if passed_tests < total_tests:
        logger.warning("Failed tests:")
        for name, ok in test_results.items():
            if not ok:
                logger.warning("  • %s", name.replace("_", " ").title())

    if passed_tests == total_tests:
        logger.info("ALL TESTS PASSED")
        logger.info("Extended threat model attack simulations are working correctly")
    else:
        logger.warning("%d test(s) failed", total_tests - passed_tests)

    return passed_tests == total_tests


def main():
    """Main test runner function"""
    try:
        # Run all tests using trio.run()
        success = trio.run(run_all_tests)
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.critical("Test runner crashed: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
