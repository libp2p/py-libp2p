import pytest

from .connection_exhaustion_attack import (
    ConnectionExhaustionAttacker,
    ConnectionExhaustionScenario,
)


@pytest.mark.trio
async def test_connection_exhaustion_basic():
    """Test basic connection exhaustion attack"""
    attacker = ConnectionExhaustionAttacker(
        "exhaust_1", intensity=0.6, max_connections_per_target=50
    )
    targets = ["peer_1", "peer_2"]

    await attacker.exhaust_connections(targets, duration=2.0)

    assert attacker.attack_start_time is not None
    assert attacker.attack_end_time is not None
    assert len(attacker.active_connections) > 0

    # Check that connections were attempted
    total_connections = sum(
        len(conns) for conns in attacker.active_connections.values()
    )
    assert total_connections > 0


@pytest.mark.trio
async def test_connection_exhaustion_limit():
    """Test that connection limits are respected"""
    attacker = ConnectionExhaustionAttacker(
        "exhaust_1", intensity=1.0, max_connections_per_target=10
    )
    targets = ["peer_1"]

    await attacker.exhaust_connections(targets, duration=5.0)

    # Should not exceed max connections per target
    connections_to_peer1 = attacker.active_connections.get("peer_1", [])
    assert len(connections_to_peer1) <= 10


@pytest.mark.trio
async def test_maintain_exhaustion():
    """Test maintaining connection exhaustion"""
    attacker = ConnectionExhaustionAttacker(
        "exhaust_1", intensity=0.5, max_connections_per_target=20
    )

    # First establish some connections
    await attacker.exhaust_connections(["peer_1"], duration=1.0)

    initial_connections = len(attacker.active_connections.get("peer_1", []))

    # Then maintain exhaustion
    await attacker.maintain_exhaustion(["peer_1"], maintenance_duration=2.0)

    final_connections = len(attacker.active_connections.get("peer_1", []))

    # Should maintain or increase connections
    assert final_connections >= initial_connections


@pytest.mark.trio
async def test_connection_exhaustion_scenario():
    """Test complete connection exhaustion scenario"""
    honest_peers = ["h1", "h2", "h3"]

    attacker1 = ConnectionExhaustionAttacker(
        "exhaust1", 0.7, max_connections_per_target=30
    )
    attacker2 = ConnectionExhaustionAttacker(
        "exhaust2", 0.5, max_connections_per_target=25
    )

    scenario = ConnectionExhaustionScenario(honest_peers, [attacker1, attacker2])

    results = await scenario.execute_connection_exhaustion_attack(attack_duration=3.0)

    assert "total_connections_established" in results
    assert "targets_exhausted" in results
    assert "attack_metrics" in results

    assert results["total_connections_established"] > 0
    assert results["targets_exhausted"] >= 0

    # Check metrics
    metrics = results["attack_metrics"]
    assert "network_resilience_score" in metrics


def test_exhaustion_metrics_calculation():
    """Test exhaustion-specific metrics calculation"""
    honest_peers = ["h1", "h2"]
    attacker = ConnectionExhaustionAttacker("exhaust1", 0.5)
    scenario = ConnectionExhaustionScenario(honest_peers, [attacker])

    # Simulate exhaustion results
    attacker.active_connections = {
        "h1": [f"conn_{i}" for i in range(40)],
        "h2": [f"conn_{i}" for i in range(35)],
    }
    attacker.exhausted_targets = ["h1"]  # Assume h1 was exhausted

    scenario._calculate_exhaustion_metrics(
        75, 1, 10.0
    )  # 75 connections over 10s, 1 target exhausted

    assert len(scenario.metrics.lookup_success_rate) == 3
    assert scenario.metrics.affected_nodes_percentage == 50.0  # 1/2 targets exhausted
    assert scenario.metrics.recovery_time > 0


@pytest.mark.trio
async def test_exhaustion_intensity_impact():
    """Test how exhaustion intensity affects attack impact"""
    honest_peers = ["h1", "h2"]

    # Low intensity
    low_attacker = ConnectionExhaustionAttacker(
        "low_exhaust", 0.3, max_connections_per_target=20
    )
    low_scenario = ConnectionExhaustionScenario(honest_peers, [low_attacker])
    low_results = await low_scenario.execute_connection_exhaustion_attack(2.0)

    # High intensity
    high_attacker = ConnectionExhaustionAttacker(
        "high_exhaust", 0.8, max_connections_per_target=50
    )
    high_scenario = ConnectionExhaustionScenario(honest_peers, [high_attacker])
    high_results = await high_scenario.execute_connection_exhaustion_attack(2.0)

    # Higher intensity should establish more connections
    assert (
        high_results["total_connections_established"]
        >= low_results["total_connections_established"]
    )


@pytest.mark.trio
async def test_multiple_attackers_exhaustion():
    """Test exhaustion with multiple attackers"""
    honest_peers = ["h1", "h2", "h3", "h4"]

    attackers = [
        ConnectionExhaustionAttacker("exhaust1", 0.6, 25),
        ConnectionExhaustionAttacker("exhaust2", 0.7, 30),
        ConnectionExhaustionAttacker("exhaust3", 0.5, 20),
    ]

    scenario = ConnectionExhaustionScenario(honest_peers, attackers)
    results = await scenario.execute_connection_exhaustion_attack(3.0)

    # Should have connections from all attackers
    assert results["total_connections_established"] > 0

    # Check that metrics reflect the attack
    metrics = results["attack_metrics"]
    assert metrics["network_resilience_score"] < 100
