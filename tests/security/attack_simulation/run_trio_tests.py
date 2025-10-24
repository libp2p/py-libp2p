#!/usr/bin/env python3
"""
Trio Test Runner

This script runs the attack simulation tests using trio.run() to properly
handle the async context required by trio.sleep() and trio.current_time().
"""

import trio
import asyncio
import sys
import os
from typing import Any, Dict, List

# Add the project root to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../'))

# Import test modules
from data_attack.invalid_block import (
    Block, BlockInvalidityType, MaliciousValidator, InvalidBlockScenario
)
from eclipse_attack.bootnode_poisoning import (
    BootnodeAttacker, BootnodePoisoningScenario
)
from finality_attack.stall_simulation import (
    LightClientNode, FinalityStallAttacker, FinalityStallScenario
)
from fork_attack.long_range_fork import (
    ChainState, ForkAttacker, LongRangeForkScenario
)


async def test_invalid_block_basic():
    """Test basic invalid block functionality"""
    print("🧱 Testing Invalid Block Basic Functionality")
    print("-" * 50)
    
    # Test block creation
    validator = MaliciousValidator("validator_0", 0.8)
    block = validator.create_invalid_block(
        1000, "parent_999", BlockInvalidityType.INVALID_STATE_TRANSITION
    )
    
    assert block.block_number == 1000
    assert block.parent_hash == "parent_999"
    assert block.invalidity_type == BlockInvalidityType.INVALID_STATE_TRANSITION
    print("✅ Block creation: PASSED")
    
    # Test propagation to light clients
    light_clients = ["lc1", "lc2", "lc3", "lc4", "lc5"]
    result = await validator.propagate_invalid_block(
        block, light_clients, is_light_client=True
    )
    
    assert "acceptance_rate" in result
    assert "propagation_time" in result
    print(f"✅ Light client propagation: PASSED (acceptance: {result['acceptance_rate']:.1%})")
    
    # Test propagation to full nodes
    full_nodes = ["fn1", "fn2", "fn3", "fn4", "fn5"]
    result = await validator.propagate_invalid_block(
        block, full_nodes, is_light_client=False
    )
    
    assert "acceptance_rate" in result
    assert "propagation_time" in result
    print(f"✅ Full node propagation: PASSED (acceptance: {result['acceptance_rate']:.1%})")
    
    print("✅ Invalid Block Basic Tests: ALL PASSED")
    return True


async def test_bootnode_poisoning_basic():
    """Test basic bootnode poisoning functionality"""
    print("\n🌐 Testing Bootnode Poisoning Basic Functionality")
    print("-" * 50)
    
    # Test bootnode attacker creation
    malicious_pool = [f"malicious_peer_{i}" for i in range(5)]
    attacker = BootnodeAttacker("bootnode_0", malicious_pool, 0.9)
    
    assert attacker.bootnode_id == "bootnode_0"
    assert len(attacker.malicious_peer_pool) == 5
    assert attacker.intensity == 0.9
    print("✅ Bootnode attacker creation: PASSED")
    
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
    print(f"✅ Bootnode poisoning scenario: PASSED")
    print(f"   - Isolation rate: {results['isolation_metrics']['isolation_rate']:.1%}")
    print(f"   - Recovery rate: {results['recovery_metrics']['recovery_rate']:.1%}")
    
    print("✅ Bootnode Poisoning Basic Tests: ALL PASSED")
    return True


async def test_finality_stall_basic():
    """Test basic finality stall functionality"""
    print("\n⏸️  Testing Finality Stall Basic Functionality")
    print("-" * 50)
    
    # Test light client node creation
    lc = LightClientNode("lc_0", memory_limit_mb=200.0)
    assert lc.node_id == "lc_0"
    assert lc.memory_limit_mb == 200.0
    print("✅ Light client node creation: PASSED")
    
    # Test finality stall attacker
    attacker = FinalityStallAttacker("attacker_0", 0.8)
    assert attacker.attacker_id == "attacker_0"
    assert attacker.intensity == 0.8
    print("✅ Finality stall attacker creation: PASSED")
    
    # Test finality stall scenario
    light_clients = [LightClientNode(f"lc_{i}", memory_limit_mb=200.0) for i in range(3)]
    full_nodes = ["fn1", "fn2"]
    attackers = [attacker]
    
    scenario = FinalityStallScenario(light_clients, full_nodes, attackers)
    
    results = await scenario.execute_finality_stall_attack(
        stall_duration=1.0, block_production_rate=1.0, finality_timeout=0.5
    )
    
    assert "attack_type" in results
    assert "memory_metrics" in results
    assert "detection_metrics" in results
    print(f"✅ Finality stall scenario: PASSED")
    print(f"   - Memory exhaustion: {results['memory_metrics']['exhaustion_rate']:.1%}")
    print(f"   - Timeout detection: {results['detection_metrics']['timeout_detection_rate']:.1%}")
    
    print("✅ Finality Stall Basic Tests: ALL PASSED")
    return True


async def test_long_range_fork_basic():
    """Test basic long-range fork functionality"""
    print("\n🔱 Testing Long-Range Fork Basic Functionality")
    print("-" * 50)
    
    # Test chain state creation
    canonical_chain = ChainState(block_height=1000, block_hash="canonical_1000")
    stale_fork = ChainState(block_height=800, block_hash="stale_800")
    
    assert canonical_chain.block_height == 1000
    assert stale_fork.block_height == 800
    print("✅ Chain state creation: PASSED")
    
    # Test fork attacker
    attacker = ForkAttacker("fork_attacker_0", stale_fork, canonical_chain, 0.7)
    assert attacker.attacker_id == "fork_attacker_0"
    assert attacker.intensity == 0.7
    print("✅ Fork attacker creation: PASSED")
    
    # Test long-range fork scenario
    online_peers = [f"online_peer_{i}" for i in range(10)]
    offline_peers = [f"offline_peer_{i}" for i in range(5)]
    fork_attackers = [attacker]
    
    scenario = LongRangeForkScenario(online_peers, offline_peers, fork_attackers)
    
    results = await scenario.execute_long_range_fork_attack(attack_duration=1.0)
    
    assert "attack_type" in results
    assert "fork_metrics" in results
    assert "detection_metrics" in results
    print(f"✅ Long-range fork scenario: PASSED")
    print(f"   - Fork replay success: {results['fork_metrics']['replay_success_rate']:.1%}")
    print(f"   - Detection rate: {results['detection_metrics']['detection_rate']:.1%}")
    
    print("✅ Long-Range Fork Basic Tests: ALL PASSED")
    return True


async def run_all_tests():
    """Run all attack simulation tests"""
    print("🚀 ATTACK SIMULATION TEST SUITE")
    print("=" * 60)
    print("Testing extended threat model attack simulations")
    print("Using trio.run() for proper async context handling")
    print()
    
    test_results = {}
    
    try:
        test_results['invalid_block'] = await test_invalid_block_basic()
    except Exception as e:
        print(f"❌ Invalid Block Tests FAILED: {e}")
        test_results['invalid_block'] = False
    
    try:
        test_results['bootnode_poisoning'] = await test_bootnode_poisoning_basic()
    except Exception as e:
        print(f"❌ Bootnode Poisoning Tests FAILED: {e}")
        test_results['bootnode_poisoning'] = False
    
    try:
        test_results['finality_stall'] = await test_finality_stall_basic()
    except Exception as e:
        print(f"❌ Finality Stall Tests FAILED: {e}")
        test_results['finality_stall'] = False
    
    try:
        test_results['long_range_fork'] = await test_long_range_fork_basic()
    except Exception as e:
        print(f"❌ Long-Range Fork Tests FAILED: {e}")
        test_results['long_range_fork'] = False
    
    # Summary
    print("\n" + "=" * 60)
    print("📋 TEST RESULTS SUMMARY")
    print("=" * 60)
    
    passed_tests = sum(1 for result in test_results.values() if result)
    total_tests = len(test_results)
    
    print(f"✅ Passed: {passed_tests}/{total_tests}")
    print()
    
    for test_name, result in test_results.items():
        status = "✅ PASSED" if result else "❌ FAILED"
        test_display = test_name.replace('_', ' ').title()
        print(f"{status} {test_display}")
    
    if passed_tests == total_tests:
        print("\n🎉 ALL TESTS PASSED!")
        print("💡 Extended threat model attack simulations are working correctly")
    else:
        print(f"\n⚠️  {total_tests - passed_tests} TESTS FAILED")
        print("💡 Some attack simulations need attention")
    
    return passed_tests == total_tests


def main():
    """Main test runner function"""
    try:
        # Run all tests using trio.run()
        success = trio.run(run_all_tests)
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"❌ Test runner failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
