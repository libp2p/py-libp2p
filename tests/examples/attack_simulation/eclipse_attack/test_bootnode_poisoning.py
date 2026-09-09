"""
Tests for Bootnode Poisoning Attack Simulation

Tests the bootnode poisoning attack scenario inspired by Polkadot network security
research.
"""

import pytest

from .bootnode_poisoning import (
    BootnodeAttacker,
    BootnodePoisoningScenario,
    run_bootnode_poisoning_simulation,
)


@pytest.mark.trio
async def test_bootnode_attacker_initialization():
    """Test that BootnodeAttacker initializes correctly"""
    malicious_pool = ["m1", "m2", "m3"]
    attacker = BootnodeAttacker("bootnode_0", malicious_pool, 0.7)

    assert attacker.bootnode_id == "bootnode_0"
    assert attacker.malicious_peer_pool == malicious_pool
    assert attacker.intensity == 0.7
    assert attacker.queries_handled == 0
    assert len(attacker.peers_poisoned) == 0


@pytest.mark.trio
async def test_bootnode_attacker_peer_discovery():
    """Test malicious bootnode responds with malicious peers only"""
    malicious_pool = ["m1", "m2", "m3", "m4", "m5"]
    attacker = BootnodeAttacker("bootnode_0", malicious_pool, 1.0)

    peers = await attacker.respond_to_peer_discovery("honest_peer_1")

    # Should return only malicious peers
    assert len(peers) > 0
    assert all(p in malicious_pool for p in peers)
    assert attacker.queries_handled == 1
    assert "honest_peer_1" in attacker.peers_poisoned


@pytest.mark.trio
async def test_bootnode_attacker_poison_dht_bootstrap():
    """Test continuous DHT bootstrap poisoning"""
    malicious_pool = ["m1", "m2", "m3"]
    attacker = BootnodeAttacker("bootnode_0", malicious_pool, 0.8)

    target_peers = ["h1", "h2", "h3"]
    results = await attacker.poison_dht_bootstrap(target_peers, duration=0.5)

    assert results["queries_handled"] > 0
    assert results["peers_poisoned"] > 0
    assert results["isolation_success_count"] >= 0
    assert len(attacker.isolation_success) >= 0


@pytest.mark.trio
async def test_bootnode_poisoning_scenario_basic():
    """Test basic bootnode poisoning scenario"""
    honest_peers = ["h1", "h2", "h3", "h4", "h5"]
    malicious_pool = ["m1", "m2", "m3", "m4"]
    malicious_bootnodes = [
        BootnodeAttacker("bootnode_0", malicious_pool, 0.8),
        BootnodeAttacker("bootnode_1", malicious_pool, 0.8),
    ]

    scenario = BootnodePoisoningScenario(honest_peers, malicious_bootnodes)
    results = await scenario.execute_bootnode_poisoning_attack(attack_duration=1.0)

    # Verify result structure
    assert "attack_type" in results
    assert results["attack_type"] == "bootnode_poisoning"
    assert "isolation_metrics" in results
    assert "recovery_metrics" in results
    assert "attack_persistence" in results
    assert "network_health" in results
    assert "recommendations" in results


@pytest.mark.trio
async def test_bootnode_poisoning_with_fallback_peers():
    """Test bootnode poisoning scenario with fallback peer recovery"""
    honest_peers = ["h1", "h2", "h3", "h4", "h5"]
    malicious_pool = ["m1", "m2", "m3"]
    fallback_peers = ["f1", "f2"]

    malicious_bootnodes = [
        BootnodeAttacker("bootnode_0", malicious_pool, 0.9),
    ]

    scenario = BootnodePoisoningScenario(
        honest_peers, malicious_bootnodes, fallback_peers
    )
    results = await scenario.execute_bootnode_poisoning_attack(attack_duration=1.0)

    # Verify recovery metrics exist
    assert "recovery_metrics" in results
    recovery = results["recovery_metrics"]
    assert "recovered_peers_count" in recovery
    assert "recovery_rate" in recovery
    assert "recovery_time" in recovery
    assert "fallback_effectiveness" in recovery


@pytest.mark.trio
async def test_bootnode_poisoning_isolation_rate():
    """Test that high-intensity attacks achieve high isolation rates"""
    honest_peers = [f"h{i}" for i in range(10)]
    malicious_pool = [f"m{i}" for i in range(15)]

    # High intensity attack with multiple bootnodes
    malicious_bootnodes = [
        BootnodeAttacker(f"bootnode_{i}", malicious_pool, 1.0) for i in range(3)
    ]

    scenario = BootnodePoisoningScenario(honest_peers, malicious_bootnodes)
    results = await scenario.execute_bootnode_poisoning_attack(attack_duration=2.0)

    isolation_rate = results["isolation_metrics"]["isolation_rate"]
    # High intensity should achieve significant isolation
    assert isolation_rate > 0.3  # At least 30% isolation


@pytest.mark.trio
async def test_bootnode_poisoning_metrics_collection():
    """Test that metrics are properly collected during attack"""
    honest_peers = ["h1", "h2", "h3"]
    malicious_pool = ["m1", "m2"]
    malicious_bootnodes = [
        BootnodeAttacker("bootnode_0", malicious_pool, 0.7),
    ]

    scenario = BootnodePoisoningScenario(honest_peers, malicious_bootnodes)
    await scenario.execute_bootnode_poisoning_attack(attack_duration=0.5)

    # Verify metrics are populated
    metrics = scenario.metrics

    assert len(metrics.lookup_success_rate) == 3  # before, during, after
    assert len(metrics.peer_table_contamination) == 3
    assert len(metrics.network_connectivity) == 3
    assert metrics.time_to_partitioning > 0
    assert metrics.affected_nodes_percentage >= 0
    assert metrics.attack_persistence >= 0


@pytest.mark.trio
async def test_bootnode_poisoning_recommendations():
    """Test that appropriate recommendations are generated"""
    honest_peers = [f"h{i}" for i in range(10)]
    malicious_pool = [f"m{i}" for i in range(15)]
    malicious_bootnodes = [
        BootnodeAttacker(f"bootnode_{i}", malicious_pool, 0.9) for i in range(3)
    ]

    scenario = BootnodePoisoningScenario(honest_peers, malicious_bootnodes)
    results = await scenario.execute_bootnode_poisoning_attack(attack_duration=1.0)

    recommendations = results["recommendations"]
    assert len(recommendations) > 0
    assert any("bootnode" in r.lower() for r in recommendations)


@pytest.mark.trio
async def test_run_bootnode_poisoning_simulation():
    """Test convenience function for running complete simulation"""
    results = await run_bootnode_poisoning_simulation(
        num_honest_peers=5,
        num_malicious_bootnodes=2,
        attack_intensity=0.7,
        num_fallback_peers=1,
        attack_duration=0.5,
    )

    assert results is not None
    assert "attack_type" in results
    assert "isolation_metrics" in results
    assert results["total_honest_peers"] == 5
    assert results["malicious_bootnodes"] == 2


@pytest.mark.trio
async def test_bootnode_poisoning_low_intensity():
    """Test low intensity bootnode poisoning attack"""
    results = await run_bootnode_poisoning_simulation(
        num_honest_peers=10,
        num_malicious_bootnodes=1,
        attack_intensity=0.3,
        attack_duration=0.5,
    )

    # Low intensity should have lower isolation rate
    isolation_rate = results["isolation_metrics"]["isolation_rate"]
    assert 0.0 <= isolation_rate <= 1.0


@pytest.mark.trio
async def test_bootnode_poisoning_high_intensity():
    """Test high intensity bootnode poisoning attack"""
    results = await run_bootnode_poisoning_simulation(
        num_honest_peers=10,
        num_malicious_bootnodes=3,
        attack_intensity=1.0,
        attack_duration=1.0,
    )

    # High intensity should have higher isolation rate
    isolation_rate = results["isolation_metrics"]["isolation_rate"]
    assert isolation_rate > 0.3


@pytest.mark.trio
async def test_bootnode_poisoning_network_health_degradation():
    """Test that network health metrics show degradation during attack"""
    results = await run_bootnode_poisoning_simulation(
        num_honest_peers=10,
        num_malicious_bootnodes=3,
        attack_intensity=0.8,
        attack_duration=1.0,
    )

    health = results["network_health"]

    # Lookup success should degrade during attack
    lookup_rates = health["lookup_success_rate"]
    assert lookup_rates[1] < lookup_rates[0]  # during < before

    # Peer table contamination should increase
    contamination = health["peer_table_contamination"]
    assert contamination[1] > contamination[0]  # during > before

    # Network connectivity should decrease
    connectivity = health["network_connectivity"]
    assert connectivity[1] < connectivity[0]  # during < before


def test_bootnode_attacker_initialization_sync():
    """Synchronous test for bootnode attacker initialization"""
    malicious_pool = ["m1", "m2", "m3"]
    attacker = BootnodeAttacker("bootnode_0", malicious_pool, 0.8)

    assert attacker.bootnode_id is not None
    assert len(attacker.malicious_peer_pool) == 3
    assert 0.0 <= attacker.intensity <= 1.0


def test_bootnode_poisoning_scenario_initialization():
    """Synchronous test for scenario initialization"""
    honest_peers = ["h1", "h2", "h3"]
    malicious_pool = ["m1", "m2"]
    bootnodes = [BootnodeAttacker("b1", malicious_pool, 0.7)]

    scenario = BootnodePoisoningScenario(honest_peers, bootnodes)

    assert len(scenario.honest_peers) == 3
    assert len(scenario.malicious_bootnodes) == 1
    assert scenario.metrics is not None
    assert len(scenario.fallback_peers) == 0
