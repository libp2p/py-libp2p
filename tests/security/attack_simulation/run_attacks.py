#!/usr/bin/env python3
"""
Run Attack Simulation Scripts

This script demonstrates and runs the various attack simulation scenarios
that have been implemented in the extended threat model.
"""

import asyncio
import trio
from typing import Any

# Import attack simulation modules
from data_attack.invalid_block import run_invalid_block_simulation
from eclipse_attack.bootnode_poisoning import run_bootnode_poisoning_simulation
from finality_attack.stall_simulation import run_finality_stall_simulation
from fork_attack.long_range_fork import run_long_range_fork_simulation


async def run_invalid_block_attack():
    """Run invalid block propagation attack simulation"""
    print("🧱 Running Invalid Block Propagation Attack Simulation")
    print("=" * 60)
    
    try:
        results = await run_invalid_block_simulation(
            num_full_nodes=5,
            num_light_clients=10,
            num_malicious_validators=2,
            attack_duration=3.0,
            finality_delay=1.5
        )
        
        print(f"✅ Attack completed successfully!")
        print(f"📊 Results summary:")
        print(f"   - Attack type: {results.get('attack_type', 'N/A')}")
        print(f"   - Light client acceptance rate: {results.get('pre_finality_metrics', {}).get('light_client_acceptance_rate', 0):.2%}")
        print(f"   - Full node acceptance rate: {results.get('pre_finality_metrics', {}).get('full_node_acceptance_rate', 0):.2%}")
        print(f"   - Vulnerability gap: {results.get('pre_finality_metrics', {}).get('vulnerability_gap', 0):.2%}")
        
        return results
    except Exception as e:
        print(f"❌ Attack simulation failed: {e}")
        return None


async def run_bootnode_poisoning_attack():
    """Run bootnode poisoning attack simulation"""
    print("\n🌐 Running Bootnode Poisoning Attack Simulation")
    print("=" * 60)
    
    try:
        results = await run_bootnode_poisoning_simulation(
            num_honest_peers=20,
            num_malicious_bootnodes=3,
            num_fallback_peers=5,
            attack_duration=5.0,
            attack_intensity=0.8
        )
        
        print(f"✅ Attack completed successfully!")
        print(f"📊 Results summary:")
        print(f"   - Attack type: {results.get('attack_type', 'N/A')}")
        print(f"   - Isolation rate: {results.get('isolation_metrics', {}).get('isolation_rate', 0):.2%}")
        print(f"   - Recovery rate: {results.get('recovery_metrics', {}).get('recovery_rate', 0):.2%}")
        print(f"   - Permanent isolation: {results.get('attack_persistence', {}).get('permanent_isolation_rate', 0):.2%}")
        
        return results
    except Exception as e:
        print(f"❌ Attack simulation failed: {e}")
        return None


async def run_finality_stall_attack():
    """Run finality stall attack simulation"""
    print("\n⏸️  Running Finality Stall Attack Simulation")
    print("=" * 60)
    
    try:
        results = await run_finality_stall_simulation(
            num_light_clients=8,
            num_full_nodes=3,
            num_attackers=2,
            stall_duration=4.0,
            block_production_rate=2.0,
            finality_timeout=2.0,
            attack_intensity=0.7
        )
        
        print(f"✅ Attack completed successfully!")
        print(f"📊 Results summary:")
        print(f"   - Attack type: {results.get('attack_type', 'N/A')}")
        print(f"   - Memory exhaustion rate: {results.get('memory_metrics', {}).get('exhaustion_rate', 0):.2%}")
        print(f"   - Peak memory usage: {results.get('memory_metrics', {}).get('peak_memory_mb', 0):.1f} MB")
        print(f"   - Timeout detection rate: {results.get('detection_metrics', {}).get('timeout_detection_rate', 0):.2%}")
        
        return results
    except Exception as e:
        print(f"❌ Attack simulation failed: {e}")
        return None


async def run_long_range_fork_attack():
    """Run long-range fork attack simulation"""
    print("\n🔱 Running Long-Range Fork Attack Simulation")
    print("=" * 60)
    
    try:
        results = await run_long_range_fork_simulation(
            num_online_peers=15,
            num_offline_peers=8,
            num_fork_attackers=2,
            attack_duration=6.0,
            attack_intensity=0.6
        )
        
        print(f"✅ Attack completed successfully!")
        print(f"📊 Results summary:")
        print(f"   - Attack type: {results.get('attack_type', 'N/A')}")
        print(f"   - Fork replay success rate: {results.get('fork_metrics', {}).get('replay_success_rate', 0):.2%}")
        print(f"   - Fork detection rate: {results.get('detection_metrics', {}).get('detection_rate', 0):.2%}")
        print(f"   - Resync success rate: {results.get('resync_metrics', {}).get('success_rate', 0):.2%}")
        
        return results
    except Exception as e:
        print(f"❌ Attack simulation failed: {e}")
        return None


async def main():
    """Run all attack simulations"""
    print("🚀 Extended Threat Model Attack Simulation Suite")
    print("=" * 60)
    print("Running comprehensive attack simulations inspired by Polkadot/Smoldot security research")
    print()
    
    all_results = {}
    
    # Run all attack simulations
    all_results['invalid_block'] = await run_invalid_block_attack()
    all_results['bootnode_poisoning'] = await run_bootnode_poisoning_attack()
    all_results['finality_stall'] = await run_finality_stall_attack()
    all_results['long_range_fork'] = await run_long_range_fork_attack()
    
    # Summary
    print("\n" + "=" * 60)
    print("📋 ATTACK SIMULATION SUMMARY")
    print("=" * 60)
    
    successful_attacks = sum(1 for result in all_results.values() if result is not None)
    total_attacks = len(all_results)
    
    print(f"✅ Successful attacks: {successful_attacks}/{total_attacks}")
    print()
    
    for attack_name, result in all_results.items():
        if result:
            print(f"✅ {attack_name.replace('_', ' ').title()}: PASSED")
        else:
            print(f"❌ {attack_name.replace('_', ' ').title()}: FAILED")
    
    print("\n🎯 All attack simulations completed!")
    print("💡 Check the detailed results above for security insights and recommendations.")


if __name__ == "__main__":
    # Run the main function using trio
    trio.run(main)
