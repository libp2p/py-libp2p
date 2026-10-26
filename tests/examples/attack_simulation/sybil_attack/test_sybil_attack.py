import pytest

from .sybil_attack import SybilAttackScenario, SybilMaliciousPeer


@pytest.mark.trio
async def test_sybil_malicious_peer_creation():
    """Test Sybil malicious peer identity creation"""
    attacker = SybilMaliciousPeer("attacker_1", num_fake_identities=5, intensity=0.5)

    fake_ids = await attacker.create_fake_identities()

    assert len(fake_ids) == 5
    assert all("attacker_1_sybil_" in fid for fid in fake_ids)
    assert len(attacker.fake_identities) == 5


@pytest.mark.trio
async def test_sybil_connections_establishment():
    """Test establishing connections from fake identities"""
    attacker = SybilMaliciousPeer("attacker_1", num_fake_identities=3, intensity=0.7)
    await attacker.create_fake_identities()

    target_peers = ["honest_1", "honest_2", "honest_3", "honest_4"]
    await attacker.establish_sybil_connections(target_peers)

    # Check that connections were established
    assert len(attacker.created_connections) == 3
    for fake_id, connections in attacker.created_connections.items():
        assert len(connections) > 0  # Should connect to some targets
        assert all(conn in target_peers for conn in connections)


@pytest.mark.trio
async def test_sybil_influence_amplification():
    """Test influence amplification through fake identities"""
    attacker = SybilMaliciousPeer("attacker_1", num_fake_identities=2, intensity=0.5)
    await attacker.create_fake_identities()

    honest_peers = ["honest_1", "honest_2"]
    influence_actions = await attacker.amplify_influence(honest_peers)

    # Should have actions for each fake identity targeting each honest peer
    expected_actions = 2 * 2  # 2 fake ids * 2 honest peers
    assert len(influence_actions) == expected_actions
    assert all(
        "attacker_1_sybil_" in action and "_influences_" in action
        for action in influence_actions
    )


@pytest.mark.trio
async def test_sybil_attack_scenario_execution():
    """Test complete Sybil attack scenario"""
    honest_peers = ["honest_1", "honest_2", "honest_3"]

    attacker1 = SybilMaliciousPeer("attacker_1", num_fake_identities=3, intensity=0.6)
    attacker2 = SybilMaliciousPeer("attacker_2", num_fake_identities=2, intensity=0.4)

    scenario = SybilAttackScenario(honest_peers, [attacker1, attacker2])

    results = await scenario.execute_sybil_attack()

    # Check results structure
    assert "total_fake_identities" in results
    assert "total_influence_actions" in results
    assert "attack_metrics" in results

    # Check metrics
    assert results["total_fake_identities"] == 5  # 3 + 2
    assert results["total_influence_actions"] == 5 * 3  # 5 fake ids * 3 honest peers

    # Check attack metrics
    metrics = results["attack_metrics"]
    assert "attack_effectiveness" in metrics
    assert "vulnerability_assessment" in metrics
    assert "mitigation_recommendations" in metrics
    assert "network_resilience_score" in metrics


def test_sybil_metrics_calculation():
    """Test Sybil-specific metrics calculation"""
    honest_peers = ["h1", "h2"]
    attacker = SybilMaliciousPeer("a1", num_fake_identities=4, intensity=0.5)
    scenario = SybilAttackScenario(honest_peers, [attacker])

    # Manually set up fake identities for testing
    attacker.fake_identities = ["a1_sybil_0", "a1_sybil_1", "a1_sybil_2", "a1_sybil_3"]
    scenario._calculate_sybil_metrics()

    # Sybil ratio: 4 fake / (2 honest + 4 fake) = 4/6 ≈ 0.667
    expected_sybil_ratio = 4 / 6

    assert (
        abs(scenario.metrics.peer_table_contamination[1] - expected_sybil_ratio) < 0.01
    )
    assert scenario.metrics.affected_nodes_percentage == expected_sybil_ratio * 100
    assert len(scenario.metrics.lookup_success_rate) == 3
    assert len(scenario.metrics.network_connectivity) == 3


@pytest.mark.trio
async def test_sybil_attack_with_different_intensities():
    """Test Sybil attack with different intensity levels"""
    honest_peers = ["h1", "h2", "h3", "h4"]

    # Low intensity
    low_attacker = SybilMaliciousPeer("low", num_fake_identities=2, intensity=0.3)
    low_scenario = SybilAttackScenario(honest_peers, [low_attacker])
    low_results = await low_scenario.execute_sybil_attack()

    # High intensity
    high_attacker = SybilMaliciousPeer("high", num_fake_identities=4, intensity=0.8)
    high_scenario = SybilAttackScenario(honest_peers, [high_attacker])
    high_results = await high_scenario.execute_sybil_attack()

    # High intensity should create more fake identities
    assert high_results["total_fake_identities"] > low_results["total_fake_identities"]

    # High intensity should have more influence actions
    assert (
        high_results["total_influence_actions"] > low_results["total_influence_actions"]
    )
