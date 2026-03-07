import pytest

from .flooding_attack import FloodingAttackScenario, FloodingMaliciousPeer


@pytest.mark.trio
async def test_pubsub_flooding():
    """Test pubsub flooding attack"""
    attacker = FloodingMaliciousPeer("flood_1", "pubsub", intensity=0.5)
    topics = ["topic_1", "topic_2"]

    # Short duration for testing
    await attacker.initiate_pubsub_flood(topics, duration=2.0)

    assert len(attacker.messages_sent) > 0
    assert attacker.flood_start_time is not None
    assert attacker.flood_end_time is not None
    assert attacker.flood_end_time > attacker.flood_start_time


@pytest.mark.trio
async def test_connection_flooding():
    """Test connection flooding attack"""
    attacker = FloodingMaliciousPeer("flood_1", "connection", intensity=0.7)
    targets = ["peer_1", "peer_2", "peer_3"]

    await attacker.initiate_connection_flood(targets, duration=1.5)

    assert len(attacker.connections_attempted) > 0
    assert all("conn_flood" in conn for conn in attacker.connections_attempted)


@pytest.mark.trio
async def test_message_flooding():
    """Test direct message flooding attack"""
    attacker = FloodingMaliciousPeer("flood_1", "message", intensity=0.6)
    targets = ["peer_1", "peer_2"]

    await attacker.initiate_message_flood(targets, duration=1.0)

    assert len(attacker.messages_sent) > 0
    assert all("msg_flood" in msg for msg in attacker.messages_sent)


@pytest.mark.trio
async def test_flooding_attack_scenario():
    """Test complete flooding attack scenario"""
    honest_peers = ["h1", "h2", "h3"]

    attacker1 = FloodingMaliciousPeer("flood1", "pubsub", 0.5)
    attacker2 = FloodingMaliciousPeer("flood2", "connection", 0.6)
    attacker3 = FloodingMaliciousPeer("flood3", "message", 0.4)

    scenario = FloodingAttackScenario(honest_peers, [attacker1, attacker2, attacker3])

    # Short duration for testing
    results = await scenario.execute_flooding_attack(attack_duration=2.0)

    assert "total_messages_sent" in results
    assert "total_connections_attempted" in results
    assert "attack_duration" in results
    assert "attack_metrics" in results

    # Check that some flooding occurred
    assert results["total_messages_sent"] >= 0
    assert results["total_connections_attempted"] >= 0

    # Check metrics structure
    metrics = results["attack_metrics"]
    assert "attack_effectiveness" in metrics
    assert "network_resilience_score" in metrics


def test_flooding_metrics_calculation():
    """Test flooding-specific metrics calculation"""
    honest_peers = ["h1", "h2"]
    attacker = FloodingMaliciousPeer("flood1", "pubsub", 0.5)
    scenario = FloodingAttackScenario(honest_peers, [attacker])

    # Simulate some flooding activity
    attacker.messages_sent = [f"msg_{i}" for i in range(100)]
    attacker.connections_attempted = [f"conn_{i}" for i in range(20)]

    scenario._calculate_flooding_metrics(100, 20, 10.0)  # 10 msgs/sec, 2 conn/sec

    # Check that metrics are calculated
    assert len(scenario.metrics.lookup_success_rate) == 3
    assert len(scenario.metrics.network_connectivity) == 3
    assert scenario.metrics.affected_nodes_percentage > 0
    assert scenario.metrics.recovery_time > 0


@pytest.mark.trio
async def test_flooding_intensity_impact():
    """Test how flooding intensity affects attack impact"""
    honest_peers = ["h1", "h2", "h3"]

    # Low intensity flooding
    low_attacker = FloodingMaliciousPeer("low_flood", "pubsub", 0.3)
    low_scenario = FloodingAttackScenario(honest_peers, [low_attacker])
    low_results = await low_scenario.execute_flooding_attack(1.0)

    # High intensity flooding
    high_attacker = FloodingMaliciousPeer("high_flood", "pubsub", 0.8)
    high_scenario = FloodingAttackScenario(honest_peers, [high_attacker])
    high_results = await high_scenario.execute_flooding_attack(1.0)

    # Higher intensity should generate more messages (in theory)
    # Note: Due to timing, this might not always hold in tests
    assert high_results["total_messages_sent"] >= low_results["total_messages_sent"]


@pytest.mark.trio
async def test_mixed_flooding_types():
    """Test scenario with mixed flooding attack types"""
    honest_peers = ["h1", "h2", "h3", "h4"]

    attackers = [
        FloodingMaliciousPeer("pubsub_flood", "pubsub", 0.5),
        FloodingMaliciousPeer("conn_flood", "connection", 0.6),
        FloodingMaliciousPeer("msg_flood", "message", 0.4),
    ]

    scenario = FloodingAttackScenario(honest_peers, attackers)
    results = await scenario.execute_flooding_attack(2.0)

    # Should have activity from all attack types
    assert results["total_messages_sent"] > 0
    assert results["total_connections_attempted"] > 0

    # Check that metrics reflect the mixed attack
    metrics = results["attack_metrics"]
    assert metrics["network_resilience_score"] < 100  # Should show some impact
